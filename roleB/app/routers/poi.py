"""GET /api/poi/{poi_id} — 장소 상세.

고정 어휘 밖의 태그는 **버린다.** A의 LLM 추출이 어휘를 벗어난 값을 넣으면
(nano 모델은 실제로 그런다 — docs/LLM_QUOTA.md) 응답 검증에서 500이 난다.
상세 화면 하나 때문에 서비스가 죽는 것보다 태그 한 개가 빠지는 게 낫다.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from app.config import Settings, get_settings
from app.constants import ATMOSPHERE_TAGS, PURPOSE_TAGS, ZONES
from app.db import Database, DatabaseUnavailable, get_db
from app.mock_data import build_poi_detail
from app.schemas import Evidence, PoiDetail
from app.services.retrieval import fetch_poi_detail

router = APIRouter(prefix="/api", tags=["recommend"])
log = logging.getLogger("wheretogo.poi")


def _known(tags: Any, vocabulary: tuple[str, ...]) -> list[str]:
    return [t for t in (tags or []) if t in vocabulary]


def _to_detail(row: dict[str, Any]) -> PoiDetail:
    return PoiDetail(
        poi_id=row["poi_id"],
        name=row["name"],
        lat=float(row["lat"]),
        lng=float(row["lng"]),
        category_l1=row.get("category_l1"),
        category_l2=row.get("category_l2"),
        dong=row.get("dong"),
        zone=row["zone"] if row.get("zone") in ZONES else None,
        business_hours=row.get("business_hours"),
        # `or`를 쓰면 실제로 관측된 0.0까지 None으로 바뀐다. 미관측만 통과시킨다.
        outdoor_exposure=row.get("outdoor_exposure"),
        group_capacity=row.get("group_capacity"),
        noise_level=row.get("noise_level"),
        price_band=row.get("price_band"),
        purpose_tags=_known(row.get("purpose_tags"), PURPOSE_TAGS),
        atmosphere_tags=_known(row.get("atmosphere_tags"), ATMOSPHERE_TAGS),
        quality_score=row.get("quality_score"),
        mention_count=row.get("mention_count") or 0,
        attr_confidence=row.get("attr_confidence") or 0.0,
        reviews=[
            Evidence(text=r["text"], source=r.get("source") or "naver_blog")
            for r in (row.get("reviews") or [])
            if r and r.get("text")
        ],
    )


@router.get("/poi/{poi_id}", response_model=PoiDetail, summary="장소 상세")
def get_poi(
    poi_id: str,
    settings: Settings = Depends(get_settings),
) -> PoiDetail:
    if settings.mock_mode:
        detail = build_poi_detail(poi_id, settings)
        if detail is None:
            raise HTTPException(status_code=404, detail="해당 장소를 찾을 수 없습니다")
        return detail

    try:
        db: Database = get_db()
        if not db.available:
            raise DatabaseUnavailable("DB 풀이 열려 있지 않다")
        row = fetch_poi_detail(db.fetch_all, poi_id)
    except DatabaseUnavailable as exc:
        log.warning("장소 상세 조회 실패: %s", exc)
        raise HTTPException(
            status_code=503, detail=f"장소 정보를 사용할 수 없습니다: {exc}"
        ) from exc

    if row is None:
        raise HTTPException(status_code=404, detail="해당 장소를 찾을 수 없습니다")
    return _to_detail(row)
