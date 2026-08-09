"""POST /api/feedback — 클릭·선택·만족도 기록 (B4-5).

노출됐지만 선택되지 않은 후보는 추천 시점에 이미 `recommendation_log.candidates`에
들어가 있다(B4-4). 여기서는 `clicked`/`selected`/`feedback`만 덧쓴다.

**빈 값은 덮어쓰지 않는다.** C는 클릭 → 선택 → 만족도를 여러 번에 나눠 보낸다.
매번 전체를 요구하면 앞선 클릭 기록이 지워진다 (logging_svc의 COALESCE).

404는 "그 추천이 기록되지 않았다"는 뜻이다. 추천 응답의 `log_id`가 로그 INSERT
실패로 폴백 값이었을 때 여기로 온다. C는 무시하고 넘어가면 된다 — 피드백 한 건이
빠지는 것이지 사용자 흐름이 막히는 것은 아니다.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.config import Settings, get_settings
from app.db import Database, DatabaseUnavailable, get_db
from app.schemas import FeedbackRequest
from app.services.logging_svc import record_feedback

router = APIRouter(prefix="/api", tags=["recommend"])
log = logging.getLogger("wheretogo.feedback")


@router.post(
    "/feedback",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="클릭·선택·만족도 기록",
    responses={404: {"description": "log_id 없음"}},
)
def submit_feedback(
    payload: FeedbackRequest,
    settings: Settings = Depends(get_settings),
) -> Response:
    if settings.mock_mode:
        # 목 log_id는 6자리 양수다. 그 밖의 값은 없는 로그로 취급한다.
        if payload.log_id < 100_000 or payload.log_id > 999_999:
            raise HTTPException(status_code=404, detail="log_id를 찾을 수 없습니다")
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    try:
        db: Database = get_db()
        if not db.available:
            raise DatabaseUnavailable("DB 풀이 열려 있지 않다")
        found = record_feedback(
            db.fetch_all,
            log_id=payload.log_id,
            clicked=payload.clicked,
            selected=payload.selected,
            feedback=payload.feedback,
        )
    except DatabaseUnavailable as exc:
        log.warning("피드백 기록 실패: %s", exc)
        raise HTTPException(
            status_code=503, detail=f"피드백을 기록할 수 없습니다: {exc}"
        ) from exc

    if not found:
        raise HTTPException(status_code=404, detail="log_id를 찾을 수 없습니다")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
