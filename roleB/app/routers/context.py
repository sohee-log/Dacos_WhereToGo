"""GET /api/context/now — 결과 화면 상단 배너용 컨텍스트 (B3-3).

이 배너가 이 서비스의 차별점을 보여주는 자리다 (ROLE_C C3-4).
*"날씨를 봤다"* 가 아니라 *"날씨를 보고 후보를 바꿨다"* 가 드러나야 한다.

그래서 여기서 만드는 값과 `/api/recommend`의 점수에 쓰인 값이 **같은 함수에서**
나온다(`pipeline.resolve_context`). 배너의 날씨와 점수의 날씨가 다르면
"비가 와서 실내로 골랐습니다"라는 문장이 근거를 잃는다.

소스는 방문 시각으로 갈린다 (PLAN §3.3.3).
  - 2시간 이내  → citydata 실황 (A가 15분마다 적재한 hotspot_snapshot)
  - 3시간 이상 뒤 → 기상청 단기예보
  - 혼잡도      → citydata FCST_PPLTN 12시간 예측
어느 쪽을 썼는지는 응답의 `weather_source`에 실린다.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query

from app.config import Settings, get_settings
from app.db import Database, DatabaseUnavailable, get_db
from app.mock_data import build_context
from app.schemas import Context
from app.services.pipeline import resolve_context
from app.timeutil import parse_visit_at

router = APIRouter(prefix="/api", tags=["recommend"])
log = logging.getLogger("wheretogo.context")


@router.get("/context/now", response_model=Context, summary="현재/예정 시각 컨텍스트")
def get_context_now(
    lat: float = Query(..., description="현재 위도"),
    lng: float = Query(..., description="현재 경도"),
    visit_at: str | None = Query(None, description="생략하면 현재 시각"),
    settings: Settings = Depends(get_settings),
) -> Context:
    if settings.mock_mode:
        ctx, _ = build_context(lat, lng, visit_at, settings)
        return ctx

    try:
        db: Database = get_db()
        if not db.available:
            raise DatabaseUnavailable("DB 풀이 열려 있지 않다")
        return resolve_context(
            db.fetch_all, settings, lat, lng, parse_visit_at(visit_at)
        ).ctx
    except DatabaseUnavailable as exc:
        log.warning("컨텍스트 조회 실패: %s", exc)
        raise HTTPException(
            status_code=503, detail=f"컨텍스트를 사용할 수 없습니다: {exc}"
        ) from exc
