"""POST /api/recommend — 메인 엔드포인트.

W1(목): 내장 픽스처(또는 A의 시드)로 실제 파이프라인 순서를 흉내 낸다.
        하드필터 → 재정규화 스코어링 → 탐색 슬롯까지 형태가 같다.
W2~W4:  retrieval.py(PostGIS) · scoring.py(7항) · logging_svc.py로 교체한다.
W5:     rag.py + explain.py(캐시·폴백)를 얹는다.

목 단계에서도 지키는 것:
  - 빈 배열을 반환하지 않는다 (반경 확대 → 신뢰도 완화 순으로 물러선다)
  - 핫스팟 밖 POI는 score_breakdown에서 live_segment/crowd **키를 생략**한다
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.config import Settings, get_settings
from app.mock_data import build_recommendation
from app.schemas import RecommendRequest, RecommendResponse

router = APIRouter(prefix="/api", tags=["recommend"])


@router.post("/recommend", response_model=RecommendResponse, summary="장소 추천")
def recommend(
    payload: RecommendRequest,
    settings: Settings = Depends(get_settings),
) -> RecommendResponse:
    return build_recommendation(payload, settings)
