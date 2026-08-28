"""③ RAG — 근거 검색 (B5-1).

**사전 필터(pre-filtering)가 이 모듈의 전부다.**

    poi_id IN (상위 20)  →  그 안에서 벡터 검색       ✅
    벡터로 전체 검색     →  나중에 상위 20으로 거르기   ❌ 정확도 붕괴

후자는 "이 요청에 잘 맞는 문장"을 전체 리뷰에서 찾은 뒤 대부분을 버리는 짓이라,
상위 20개 POI에 대한 근거가 하나도 안 남는 일이 생긴다.

**쿼리 벡터를 온라인에서 계산하지 않는다.** 임베딩 모델이 서버에 없다(§1.2).
요청 조합이 유한하다는 성질을 써서 A가 만들어 둔 `query_vector_cache`(목적 6 ×
날씨 4 × 인원밴드 3 = 72행)를 조회한다.

캐시가 비어 있어도 인용은 나간다 — 벡터 없이 "협찬 아닌 최신 후기"로 물러선다.
근거 없는 추천을 내보내는 것보다 덜 맞는 근거를 붙이는 편이 낫다.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from typing import Any

from app.constants import (
    COLD_FEELS_LIKE,
    HEAT_FEELS_LIKE,
    PM_BAD_GRADE,
    RAIN_TRIGGER,
    party_band,
)

log = logging.getLogger("wheretogo.rag")

MAX_CHUNKS_PER_POI = 3          # POI당 인용 후보 (ROLE_B §6.8)

QUERY_VECTOR_SQL = """
SELECT embedding, query_text
FROM query_vector_cache
WHERE purpose = %(purpose)s
  AND weather_state = %(weather_state)s
  AND party_band = %(party_band)s
"""

# 사전 필터가 서브쿼리 안의 WHERE다. 벡터 정렬은 그 뒤에 일어난다.
# is_sponsored를 첫 정렬 키로 두어 협찬 글을 뒤로 민다 — 인용문이 광고면 신뢰를 잃는다.
EVIDENCE_SQL = """
SELECT poi_id, text, source, sim
FROM (
    SELECT rc.poi_id, rc.text, rc.source,
           1 - (rc.embedding <=> %(qvec)s::halfvec) AS sim,
           row_number() OVER (
               PARTITION BY rc.poi_id
               ORDER BY rc.is_sponsored, rc.embedding <=> %(qvec)s::halfvec
           ) AS rn
    FROM review_chunk rc
    WHERE rc.poi_id = ANY(%(poi_ids)s)
      AND rc.embedding IS NOT NULL
) t
WHERE rn <= %(per_poi)s
ORDER BY poi_id, rn
"""

# 쿼리 벡터가 없을 때. 벡터 정렬만 빠지고 나머지는 같다.
EVIDENCE_FALLBACK_SQL = """
SELECT poi_id, text, source, NULL::float8 AS sim
FROM (
    SELECT rc.poi_id, rc.text, rc.source,
           row_number() OVER (
               PARTITION BY rc.poi_id
               -- A의 A3-2는 written_at을 채우지 않는다(리뷰 JSONL의 postdate가
               -- INSERT에 안 실린다). 전 건 NULL이면 이 정렬은 동점이 되고,
               -- 그러면 같은 요청이 요청마다 다른 문장을 인용할 수 있다.
               -- chunk_id로 동점을 끊는다. DESC인 이유는 주 정렬키가
               -- written_at DESC(최신 우선)이고 BIGSERIAL이 시간순으로 늘기
               -- 때문이다 — 같은 규칙을 이어 간다.
               ORDER BY rc.is_sponsored, rc.written_at DESC NULLS LAST,
                        rc.chunk_id DESC
           ) AS rn
    FROM review_chunk rc
    WHERE rc.poi_id = ANY(%(poi_ids)s)
) t
WHERE rn <= %(per_poi)s
ORDER BY poi_id, rn
"""


def weather_state_of(wx: Mapping[str, Any]) -> str:
    """날씨를 고정 어휘 4종으로 접는다. `query_vector_cache`의 조회 축이다.

    순서가 의미를 갖는다. 비가 오면서 미세먼지도 나쁜 날은 **비**로 본다 —
    행동을 더 크게 바꾸는 쪽이 비다.
    """
    if float(wx.get("rain_prob") or 0.0) > RAIN_TRIGGER:
        return "비"
    if int(wx.get("pm25_grade") or 1) >= PM_BAD_GRADE:
        return "미세먼지나쁨"
    feels = float(wx.get("feels_like", 20.0))
    if feels > HEAT_FEELS_LIKE or feels < COLD_FEELS_LIKE:
        return "폭염한파"
    return "맑음"


def fetch_query_vector(
    executor, purpose: str, weather_state: str, size: int
) -> Any | None:
    """72행 캐시에서 조회. 없으면 None (온라인에서 임베딩하지 않는다)."""
    try:
        rows = executor(
            QUERY_VECTOR_SQL,
            {
                "purpose": purpose,
                "weather_state": weather_state,
                "party_band": party_band(size),
            },
        )
    except Exception as exc:
        log.warning("query_vector_cache 조회 실패: %s", exc)
        return None
    if not rows:
        log.info(
            "query_vector_cache 미스 (%s/%s/%s) — 벡터 없이 인용을 고른다",
            purpose, weather_state, party_band(size),
        )
        return None
    return rows[0]["embedding"]


def _collect(executor, sql: str, params: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    try:
        rows = executor(sql, params)
    except Exception as exc:
        # 근거를 못 붙였다고 추천이 멈추지는 않는다. 인용 없이 나간다.
        log.warning("인용 검색 실패: %s", exc)
        return {}

    out: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        if not r.get("text"):
            continue
        out.setdefault(r["poi_id"], []).append(
            {
                "text": r["text"],
                "source": r.get("source") or "naver_blog",
                "sim": r.get("sim"),
            }
        )
    return out


def fetch_evidence(
    executor,
    poi_ids: Sequence[str],
    query_vector: Any | None,
    per_poi: int = MAX_CHUNKS_PER_POI,
) -> dict[str, list[dict[str, Any]]]:
    """{poi_id: [인용 후보]}. 리뷰가 아예 없는 POI는 키 자체가 없다.

    ⚠️ **임베딩이 아직 없는 청크도 인용에 쓴다.**
    벡터 검색은 `embedding IS NOT NULL`인 것만 볼 수 있는데, A의 수집(월 1회)과
    임베딩 배치(Colab)는 시점이 다르다. 그 사이에 들어온 후기를 통째로 버리면
    **새로 수집한 POI가 근거 없는 추천이 된다.** 그래서 벡터로 하나도 못 찾은
    POI만 골라 비-벡터 정렬(협찬 뒤로 · 최신순)로 한 번 더 찾는다.
    """
    if not poi_ids:
        return {}

    ids = list(poi_ids)
    if query_vector is None:
        return _collect(
            executor, EVIDENCE_FALLBACK_SQL, {"poi_ids": ids, "per_poi": per_poi}
        )

    out = _collect(
        executor,
        EVIDENCE_SQL,
        {"poi_ids": ids, "per_poi": per_poi, "qvec": query_vector},
    )

    missing = [p for p in ids if p not in out]
    if missing:
        out.update(
            _collect(
                executor,
                EVIDENCE_FALLBACK_SQL,
                {"poi_ids": missing, "per_poi": per_poi},
            )
        )
    return out
