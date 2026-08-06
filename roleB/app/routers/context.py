"""GET /api/context/now — 결과 화면 상단 배너용 컨텍스트.

W1(목): 방문 시각으로부터 결정적인 날씨·혼잡도를 만든다.
W3(B3-3): citydata(2시간 이내 실황) + 기상청 단기예보(3시간 이상 뒤)를 병합한다.
  서비스 원칙이 "실측값이 아니라 방문 예정 시각의 예보"이므로 둘 다 필요하다.
  citydata는 사용자 요청마다 부르지 않는다. A가 15분마다 적재한 hotspot_snapshot을 읽는다.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.config import Settings, get_settings
from app.mock_data import build_context
from app.schemas import Context

router = APIRouter(prefix="/api", tags=["recommend"])


@router.get("/context/now", response_model=Context, summary="현재/예정 시각 컨텍스트")
def get_context_now(
    lat: float = Query(..., description="현재 위도"),
    lng: float = Query(..., description="현재 경도"),
    visit_at: str | None = Query(None, description="생략하면 현재 시각"),
    settings: Settings = Depends(get_settings),
) -> Context:
    ctx, _ = build_context(lat, lng, visit_at, settings)
    return ctx
