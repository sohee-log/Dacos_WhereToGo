"""설명 생성 — 캐시 → LLM → 템플릿 (W5 B5-2·B5-3·B5-4·B5-5).

**LLM 없이도 서비스가 돈다**는 것이 무료 티어의 전제다 (ROLE_B §1.2).
그래서 순서가 정해져 있다.

    explanation_cache 조회  →  히트하면 LLM 호출 0회        (explain_mode: cache)
    미스면 LLM 호출         →  성공하면 캐시에 저장          (explain_mode: llm)
    키 없음·쿼터·타임아웃   →  점수 성분으로 만든 템플릿      (explain_mode: template)

데모처럼 시나리오가 반복되는 환경에서는 캐시 히트율이 90%를 넘는다. 발표 전날
시나리오 20개를 미리 호출해 두면(W6 B6-4) 발표 중 LLM 호출이 0회가 된다.

인용은 지어내지 않는다 (B5-4)
------------------------------
LLM이 반환한 인용문이 실제 `review_chunk.text` 안에 있는지 후처리에서 검사한다.
없으면 그 인용을 버리고 **원문에서 가장 가까운 청크로 대체**한다. 대체할 것도
없으면 인용 없이 내보낸다. 그럴듯하게 만들어진 후기 한 줄이 서비스 전체의
신뢰를 깎는다 — "실제 리뷰 근거와 함께"가 이 프로젝트의 한 줄 정의다.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import logging
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from app.config import Settings
from app.services import llm

log = logging.getLogger("wheretogo.explain")

# 이 임계값들은 "말할 만한 근거인가"의 기준이다. 점수 계산에는 쓰이지 않는다.
STRONG_TERM = 0.8
WEAK_CROWD = 0.4
HEAVY_RAIN = 0.5
INDOOR_EXPOSURE = 0.3


def template_reason(
    poi: Mapping[str, Any],
    wx: Mapping[str, Any],
    purpose: str,
    terms: Mapping[str, float],
) -> str:
    """근거가 있는 항만 골라 문장으로 만든다. 근거가 없으면 지어내지 않는다."""
    outdoor = float(poi.get("outdoor_exposure", 0.0) or 0.0)
    parts: list[str] = []

    if float(wx.get("rain_prob", 0.0) or 0.0) > HEAVY_RAIN and outdoor < INDOOR_EXPOSURE:
        parts.append("비 예보가 있어 실내 공간 위주로 골랐습니다")
    if int(wx.get("pm25_grade", 1) or 1) >= 3 and outdoor < INDOOR_EXPOSURE:
        parts.append("미세먼지 나쁨 예보를 반영해 실내를 우선했습니다")
    if terms.get("segment_affinity", 0.0) > STRONG_TERM:
        parts.append("이 시간대에 또래 방문 비중이 높은 곳입니다")
    if terms.get("purpose_match", 0.0) > STRONG_TERM:
        parts.append(f"{purpose}에 적합하다는 후기가 많습니다")
    if terms.get("crowd_fit", 1.0) < WEAK_CROWD:
        parts.append("다만 방문 시각에 다소 붐빌 수 있습니다")

    if not parts:
        return "요청하신 조건에 가장 근접한 장소입니다."
    return ". ".join(parts) + "."


# ============================================================================
# explanation_cache (B5-3)
# ============================================================================

CACHE_GET_SQL = """
UPDATE explanation_cache
SET hit_count = hit_count + 1
WHERE cache_key = %(cache_key)s
RETURNING payload
"""

CACHE_PUT_SQL = """
INSERT INTO explanation_cache (cache_key, payload)
VALUES (%(cache_key)s, %(payload)s)
ON CONFLICT (cache_key) DO UPDATE SET payload = EXCLUDED.payload
"""


def cache_key(
    purpose: str,
    party_band: int,
    weather_state: str,
    zone: str | None,
    poi_ids: Sequence[str],
) -> str:
    """ROLE_B §B5-3의 키.

    **POI 목록이 키에 들어간다.** 같은 조건이라도 후보가 달라지면 설명도 달라야
    하기 때문이다. 정렬해서 넣는 이유는 순위가 미세하게 흔들려도 같은 캐시를
    쓰기 위해서다 — 순서까지 키에 넣으면 히트율이 바닥난다.
    """
    raw = "|".join(
        [purpose, str(party_band), weather_state, zone or "-", ",".join(sorted(poi_ids))]
    )
    return hashlib.sha256(raw.encode()).hexdigest()


def fetch_cached(executor, key: str) -> dict[str, Any] | None:
    """히트하면 payload. 조회 자체가 실패하면 미스로 취급한다."""
    try:
        rows = executor(CACHE_GET_SQL, {"cache_key": key})
    except Exception as exc:
        log.warning("설명 캐시 조회 실패: %s", exc)
        return None
    if not rows:
        return None
    payload = rows[0].get("payload")
    return payload if isinstance(payload, dict) else None


def store_cache(executor, key: str, payload: Mapping[str, Any]) -> None:
    try:
        executor(
            CACHE_PUT_SQL,
            {
                "cache_key": key,
                "payload": json.dumps(payload, ensure_ascii=False, default=str),
            },
        )
    except Exception as exc:
        # 캐시에 못 넣었다고 응답을 버릴 이유가 없다. 다음 요청에 다시 만들면 된다.
        log.warning("설명 캐시 저장 실패: %s", exc)


# ============================================================================
# LLM 설명 생성 (B5-2)
# ============================================================================

# `strict: true`는 모든 필드가 required이고 additionalProperties=false여야 한다.
# 이걸 어기면 게이트웨이가 400을 준다 (docs/LLM_QUOTA.md).
RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "results": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "poi_id": {"type": "string"},
                    "fit": {"type": "number"},
                    "reason": {"type": "string"},
                    "quote": {"type": "string"},
                },
                "required": ["poi_id", "fit", "reason", "quote"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["results"],
    "additionalProperties": False,
}

PROMPT_HEADER = """당신은 서울 용산구 장소 추천 서비스의 설명을 쓴다.

아래 후보 중에서 요청 상황에 가장 맞는 곳을 3~5곳 고르고, 각각의 추천 이유를 쓴다.

규칙
- reason은 한국어 1~2문장. 날씨·인원·목적 중 실제로 근거가 되는 것만 말한다.
- quote는 아래 '인용 후보'에 있는 문장을 **그대로** 옮긴다. 요약·수정·창작 금지.
  마땅한 인용 후보가 없으면 quote는 빈 문자열로 둔다.
- 인용 후보가 없는 곳을 고르지 않는다.
- poi_id는 아래 목록에 있는 값만 쓴다.
- 없는 사실을 만들지 않는다. 후보 정보에 없는 메뉴·가격·영업시간을 말하지 않는다.
"""


def build_prompt(
    ctx: Mapping[str, Any],
    candidates: Sequence[Mapping[str, Any]],
    evidence: Mapping[str, Sequence[Mapping[str, Any]]],
) -> str:
    """요청 상황 + 후보 요약 + 인용 후보. **리뷰 전문을 넣지 않는다** (R3)."""
    lines = [PROMPT_HEADER, "\n[요청]"]
    lines.append(
        f"- 목적 {ctx.get('purpose')} / {ctx.get('party_size')}명 / "
        f"예산밴드 {ctx.get('budget_band')} / 방문 {ctx.get('visit_at')}"
    )
    lines.append(
        f"- 날씨 {ctx.get('weather')} · 체감 {ctx.get('feels_like')}° · "
        f"미세먼지 등급 {ctx.get('pm25_grade')}"
    )
    if ctx.get("hotspot"):
        lines.append(f"- 지역 {ctx['hotspot']} · 방문 시각 혼잡 {ctx.get('congest')}")

    lines.append("\n[후보]")
    for c in candidates:
        tags = ", ".join(c.get("atmosphere_tags") or [])
        lines.append(
            f"- {c['poi_id']} | {c.get('name')} | {c.get('category_l2') or ''} | "
            f"{int(c.get('dist_m') or 0)}m | 야외노출 {c.get('outdoor_exposure')} | {tags}"
        )

    lines.append("\n[인용 후보] (이 문장들만 quote에 쓸 수 있다)")
    for poi_id, chunks in evidence.items():
        for ch in chunks:
            lines.append(f"- {poi_id} :: {ch['text']}")

    return "\n".join(lines)


# ============================================================================
# 인용 검증 (B5-4)
# ============================================================================

_WS = re.compile(r"\s+")
SIMILAR_ENOUGH = 0.6            # 이보다 낮으면 "가장 비슷한 청크"라고 부를 수 없다


def _normalize(text: str) -> str:
    return _WS.sub(" ", str(text or "")).strip()


@dataclass
class VerifiedQuote:
    text: str
    source: str = "naver_blog"
    replaced: bool = False


def verify_quote(
    quote: str, chunks: Sequence[Mapping[str, Any]]
) -> VerifiedQuote | None:
    """인용문이 실제 원문에 있는지 확인한다. 없으면 가장 가까운 원문으로 바꾼다.

    반환 None은 "인용 없이 내보낸다"는 뜻이다. **지어낸 문장을 그대로 내보내지 않는다.**
    """
    if not chunks:
        return None

    normalized = _normalize(quote)
    if normalized:
        for ch in chunks:
            if normalized in _normalize(ch["text"]):
                # 원문의 부분 문자열이면 그 자체가 발췌다. 그대로 쓴다.
                return VerifiedQuote(text=quote.strip(), source=ch.get("source") or "naver_blog")

        best = max(
            chunks,
            key=lambda c: difflib.SequenceMatcher(
                None, normalized, _normalize(c["text"])
            ).ratio(),
        )
        ratio = difflib.SequenceMatcher(
            None, normalized, _normalize(best["text"])
        ).ratio()
        if ratio >= SIMILAR_ENOUGH:
            log.info("인용이 원문과 달라 대체한다 (유사도 %.2f)", ratio)
            return VerifiedQuote(
                text=best["text"], source=best.get("source") or "naver_blog", replaced=True
            )

    # 인용이 비었거나 원문과 너무 다르다 → 가장 관련 높은 청크를 대신 붙인다
    head = chunks[0]
    return VerifiedQuote(
        text=head["text"], source=head.get("source") or "naver_blog", replaced=True
    )


@dataclass
class Explanation:
    poi_id: str
    reason: str
    evidence: list[dict[str, str]] = field(default_factory=list)


def verify_results(
    items: Sequence[Mapping[str, Any]],
    evidence: Mapping[str, Sequence[Mapping[str, Any]]],
    allowed_ids: Sequence[str],
) -> list[Explanation]:
    """LLM 출력에서 **믿을 수 있는 것만** 남긴다.

    - 후보에 없는 poi_id는 버린다 (환각)
    - 같은 곳을 두 번 고르면 첫 번째만
    - 인용은 verify_quote를 통과한 것만
    """
    allowed = set(allowed_ids)
    seen: set[str] = set()
    out: list[Explanation] = []

    for item in items:
        poi_id = str(item.get("poi_id") or "")
        if poi_id not in allowed or poi_id in seen:
            continue
        reason = _normalize(item.get("reason"))
        if not reason:
            continue
        seen.add(poi_id)

        quote = verify_quote(str(item.get("quote") or ""), evidence.get(poi_id) or [])
        out.append(
            Explanation(
                poi_id=poi_id,
                reason=reason,
                evidence=[{"text": quote.text, "source": quote.source}] if quote else [],
            )
        )
    return out


def generate(
    settings: Settings,
    executor,
    *,
    key: str,
    ctx: Mapping[str, Any],
    candidates: Sequence[Mapping[str, Any]],
    evidence: Mapping[str, Sequence[Mapping[str, Any]]],
) -> tuple[list[Explanation], str]:
    """(설명 목록, explain_mode). 실패는 빈 목록 + "template"이다."""
    allowed = [c["poi_id"] for c in candidates]

    cached = fetch_cached(executor, key)
    if cached and cached.get("items"):
        # 캐시에 담긴 것도 한 번 더 검증한다. 저장 시점과 후보가 달라졌을 수 있다.
        verified = verify_results(cached["items"], evidence, allowed)
        if verified:
            return verified, "cache"

    if not llm.available(settings):
        return [], "template"

    payload = llm.chat_json(
        settings,
        build_prompt(ctx, candidates, evidence),
        RESPONSE_SCHEMA,
        schema_name="recommendation_explanations",
    )
    if not payload or not isinstance(payload.get("results"), list):
        return [], "template"

    verified = verify_results(payload["results"], evidence, allowed)
    if not verified:
        return [], "template"

    store_cache(
        executor,
        key,
        {
            "items": [
                {"poi_id": e.poi_id, "reason": e.reason, "quote": (e.evidence or [{}])[0].get("text", "")}
                for e in verified
            ],
            "model": settings.llm_model,
        },
    )
    return verified, "llm"
