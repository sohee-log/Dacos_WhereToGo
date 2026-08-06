"""POST /api/feedback — 클릭·선택·만족도 기록.

노출됐지만 선택되지 않은 후보는 추천 시점에 이미 recommendation_log.candidates에
들어가 있다. 여기서는 clicked/selected/feedback만 덧쓴다 (ROLE_B §W4 B4-4).

W1(목): 204만 돌려준다. log_id 형식이 틀리면 404 — C가 에러 경로를 그려볼 수 있게.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response, status

from app.schemas import FeedbackRequest

router = APIRouter(prefix="/api", tags=["recommend"])


@router.post(
    "/feedback",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="클릭·선택·만족도 기록",
    responses={404: {"description": "log_id 없음"}},
)
def submit_feedback(payload: FeedbackRequest) -> Response:
    # 목 log_id는 6자리 양수다. 그 밖의 값은 없는 로그로 취급한다.
    if payload.log_id < 100_000 or payload.log_id > 999_999:
        raise HTTPException(status_code=404, detail="log_id를 찾을 수 없습니다")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
