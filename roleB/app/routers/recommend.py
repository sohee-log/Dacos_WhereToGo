"""POST /api/recommend — 메인 엔드포인트.

두 경로가 있고 **가르는 것은 `MOCK_MODE` 하나다.**

    MOCK_MODE=true   → mock_data.build_recommendation  (픽스처/시드 JSON)
    MOCK_MODE=false  → services.pipeline               (PostGIS + 스코어링)

live에서 DB가 없거나 후보가 0건이면 **503을 낸다. 목으로 조용히 되돌아가지 않는다.**
목으로 흘려보내면 "실데이터로 동작한다"는 W2 게이트가 거짓으로 통과하고,
그 사실을 발표 당일에 알게 된다.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException

from app.config import Settings, get_settings
from app.db import Database, DatabaseUnavailable, get_db
from app.mock_data import build_recommendation
from app.schemas import RecommendRequest, RecommendResponse
from app.services.pipeline import LiveDataUnavailable, build_live_recommendation

router = APIRouter(prefix="/api", tags=["recommend"])
log = logging.getLogger("wheretogo.recommend")


@router.post("/recommend", response_model=RecommendResponse, summary="장소 추천")
def recommend(
    payload: RecommendRequest,
    settings: Settings = Depends(get_settings),
) -> RecommendResponse:
    if settings.mock_mode:
        return build_recommendation(payload, settings)

    try:
        db: Database = get_db()
        if not db.available:
            raise DatabaseUnavailable("DB 풀이 열려 있지 않다")
        return build_live_recommendation(payload, settings, db.fetch_all)
    except (DatabaseUnavailable, LiveDataUnavailable) as exc:
        log.warning("live 추천 실패: %s", exc)
        raise HTTPException(
            status_code=503,
            detail=f"추천 데이터를 사용할 수 없습니다: {exc}",
        ) from exc
