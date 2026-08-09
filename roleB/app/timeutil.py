"""시각 처리. 이 서비스의 모든 판단 기준은 **방문 예정 시각(KST)** 이다.

"지금 비가 오는가"가 아니라 "도착할 때 비가 오는가"로 후보가 바뀐다(PLAN.md §3.3.3).
그래서 요청의 `visit_at`을 파싱하는 지점이 하나여야 한다.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))


def parse_visit_at(visit_at: str | None) -> datetime:
    """ISO8601 → KST datetime.

    파싱에 실패해도 예외를 올리지 않는다. 시각 형식 하나 때문에 추천 전체가
    500이 되는 것보다, 현재 시각으로 답하고 넘어가는 편이 낫다.
    타임존이 없는 문자열은 KST로 본다 (C가 로컬 시각을 그대로 보내는 경우).
    """
    if not visit_at:
        return datetime.now(KST)
    try:
        dt = datetime.fromisoformat(visit_at.replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(KST)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=KST)
    return dt.astimezone(KST)
