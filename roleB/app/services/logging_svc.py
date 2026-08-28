"""④ 로깅 — recommendation_log (B4-4).

**노출됐지만 선택되지 않은 후보를 남기는 것이 이 모듈의 존재 이유다.**
선택된 것만 기록하면 로그를 몇 달 모아도 랭킹 모델을 학습할 수 없다.
positive만 있고 negative가 없는 데이터셋이 되기 때문이다.

6주 안에 학습은 하지 않는다(ROLE_B §9.5). 그래도 **구조는 지금 만든다** —
나중에 만들면 그때부터 모으기 시작하는 것이고, 그건 로그가 0건이라는 뜻이다.

기록이 실패해도 추천은 나간다
-----------------------------
로그 INSERT가 깨졌다고 사용자에게 500을 주지 않는다. 로그는 부수 효과지
응답의 일부가 아니다. 실패하면 경고만 남기고 `log_id=None`으로 응답한다.
(C는 log_id가 없으면 피드백 전송을 건너뛴다.)
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping, Sequence
from typing import Any

log = logging.getLogger("wheretogo.logging")

INSERT_LOG_SQL = """
INSERT INTO recommendation_log
    (user_id, requested_at, context, candidates, explain_mode, latency_ms)
VALUES
    (%(user_id)s, now(), %(context)s, %(candidates)s, %(explain_mode)s, %(latency_ms)s)
RETURNING log_id
"""

# user_id는 user_profile을 참조한다. 온보딩을 건너뛴 사용자는 프로필 행이 없고,
# 그대로 INSERT하면 FK 위반으로 로그가 통째로 날아간다. 있을 때만 채운다.
USER_EXISTS_SQL = "SELECT 1 FROM user_profile WHERE user_id = %(user_id)s"

# `clicked`만 덧쓰기가 아니라 **합집합**이다.
#
# C는 카드를 누를 때마다 한 건씩 보낸다. 덧쓰기면 두 번째 클릭이 첫 번째를
# 지운다 — 이 모듈이 COALESCE로 막으려던 것과 정확히 같은 사고이고, 값이 있는
# 경우에만 일어나서 더 안 보인다. 원소 하나짜리 배열이 와도 안전해야 한다.
#
# WITH ORDINALITY + MIN(ord)로 **처음 등장한 순서**를 지킨다. DISTINCT만 쓰면
# 순서가 매번 달라져서 나중에 클릭 순서를 분석할 수 없다.
UPDATE_FEEDBACK_SQL = """
UPDATE recommendation_log
SET clicked  = CASE
        WHEN %(clicked)s IS NULL THEN clicked
        ELSE ARRAY(
            SELECT t.x
            FROM unnest(COALESCE(clicked, '{}'::TEXT[]) || %(clicked)s::TEXT[])
                 WITH ORDINALITY AS t(x, ord)
            GROUP BY t.x
            ORDER BY MIN(t.ord)
        )
    END,
    selected = COALESCE(%(selected)s, selected),
    feedback = COALESCE(%(feedback)s, feedback)
WHERE log_id = %(log_id)s
RETURNING log_id
"""


def build_candidate_rows(
    scored: Sequence[tuple[float, Mapping[str, Any], Mapping[str, float], float]],
    shown_ids: set[str],
) -> list[dict[str, Any]]:
    """`candidates` JSONB. 상위 20개 전부 남기고 노출 여부만 구분한다.

    `terms`(점수 성분)를 함께 남기는 이유는, 나중에 가중치를 바꿔도 **과거 로그를
    다시 채점할 수 있게** 하기 위해서다. 최종 점수만 남기면 그게 불가능하다.
    """
    rows: list[dict[str, Any]] = []
    for rank, (score, poi, terms, dist_pen) in enumerate(scored, start=1):
        rows.append(
            {
                "poi_id": poi["poi_id"],
                "rank": rank,
                "score": round(float(score), 4),
                "terms": {k: round(float(v), 4) for k, v in terms.items()},
                "distance_penalty": round(float(dist_pen), 4),
                "shown": poi["poi_id"] in shown_ids,
            }
        )
    return rows


def write_recommendation_log(
    executor,
    *,
    user_id: str,
    context: Mapping[str, Any],
    candidates: Sequence[Mapping[str, Any]],
    explain_mode: str,
    latency_ms: int,
) -> int | None:
    """log_id를 돌려준다. 실패하면 None (추천은 그대로 나간다)."""
    try:
        exists = executor(USER_EXISTS_SQL, {"user_id": user_id})
        rows = executor(
            INSERT_LOG_SQL,
            {
                "user_id": user_id if exists else None,
                "context": json.dumps(context, ensure_ascii=False, default=str),
                "candidates": json.dumps(candidates, ensure_ascii=False, default=str),
                "explain_mode": explain_mode,
                "latency_ms": latency_ms,
            },
        )
        return int(rows[0]["log_id"]) if rows else None
    except Exception as exc:  # 로그 때문에 추천이 죽지 않는다
        log.warning("추천 로그 기록 실패: %s", exc)
        return None


def record_feedback(
    executor,
    *,
    log_id: int,
    clicked: Sequence[str] | None,
    selected: str | None,
    feedback: int | None,
) -> bool:
    """해당 log_id가 있으면 True. 없으면 False (라우터가 404로 바꾼다).

    빈 값은 덮어쓰지 않는다(`COALESCE`). C가 클릭 → 선택 → 만족도를 **여러 번에
    나눠 보내기** 때문이다. 매번 전체를 보내게 하면 앞선 클릭 기록이 지워진다.

    `clicked`는 덧쓰기가 아니라 **합집합**이다 — 카드마다 한 건씩 보내도
    앞선 클릭이 남는다. 순서는 처음 등장한 순서를 지킨다.
    """
    rows = executor(
        UPDATE_FEEDBACK_SQL,
        {
            "log_id": log_id,
            "clicked": list(clicked) if clicked else None,
            "selected": selected,
            "feedback": feedback,
        },
    )
    return bool(rows)


def context_snapshot(
    req_context: Mapping[str, Any], wx: Mapping[str, Any], extra: Mapping[str, Any]
) -> dict[str, Any]:
    """로그에 남길 요청 컨텍스트.

    **좌표는 격자 단위로 뭉갠다** (PLAN.md §8.3 개인정보). 소수 3자리 ≈ 110m다.
    추천 품질 분석에는 충분하고, 개인의 이동 궤적을 복원하기에는 부족하다.
    """
    snap = dict(req_context)
    if "lat" in snap and snap["lat"] is not None:
        snap["lat"] = round(float(snap["lat"]), 3)
    if "lng" in snap and snap["lng"] is not None:
        snap["lng"] = round(float(snap["lng"]), 3)
    snap["weather"] = {
        k: wx.get(k) for k in ("rain_prob", "pm25_grade", "feels_like", "visit_hour")
    }
    snap.update(extra)
    return snap
