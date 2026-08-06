"""GET /api/poi/{poi_id} — 장소 상세."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.config import Settings, get_settings
from app.mock_data import build_poi_detail
from app.schemas import PoiDetail

router = APIRouter(prefix="/api", tags=["recommend"])


@router.get("/poi/{poi_id}", response_model=PoiDetail, summary="장소 상세")
def get_poi(
    poi_id: str,
    settings: Settings = Depends(get_settings),
) -> PoiDetail:
    detail = build_poi_detail(poi_id, settings)
    if detail is None:
        raise HTTPException(status_code=404, detail="해당 장소를 찾을 수 없습니다")
    return detail
