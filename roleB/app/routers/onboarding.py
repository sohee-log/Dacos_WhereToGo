"""POST /api/onboarding — 온보딩 5문항 수집 (B4-5).

`user_id`는 **답변 내용의 해시**다. 같은 답을 하면 같은 id가 나온다.
  - 목/실 두 모드에서 규칙이 같아 C의 로컬 저장값이 모드를 오가도 깨지지 않는다
  - 새 개인 식별자를 만들지 않는다 (PLAN.md §8.3 개인정보 최소화)
  - 재제출이 자연히 갱신(upsert)이 된다

`taste_vector`는 서버에서 임베딩하지 않는다. 태그가 유한 집합이므로 A가 배치로
만들어 둔 `tag_embedding`(16행)의 평균을 낸다. 그 테이블이 비어 있으면
`taste_vector`는 NULL이고, 취향 항이 중립으로 계산될 뿐 서비스는 돈다.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException

from app.config import Settings, get_settings
from app.db import Database, DatabaseUnavailable, get_db
from app.schemas import OnboardingRequest, OnboardingResponse
from app.services.user_svc import make_user_id, upsert_profile

router = APIRouter(prefix="/api", tags=["user"])
log = logging.getLogger("wheretogo.onboarding")


@router.post("/onboarding", response_model=OnboardingResponse, summary="온보딩 제출")
def submit_onboarding(
    payload: OnboardingRequest,
    settings: Settings = Depends(get_settings),
) -> OnboardingResponse:
    atmosphere = [t.value for t in payload.atmosphere_tags]
    purpose = [t.value for t in payload.purpose_tags]
    user_id = make_user_id(
        payload.gender,
        payload.age_band,
        atmosphere,
        purpose,
        payload.budget_band,
        payload.weather_sensitivity,
    )

    if settings.mock_mode:
        return OnboardingResponse(user_id=user_id)

    try:
        db: Database = get_db()
        if not db.available:
            raise DatabaseUnavailable("DB 풀이 열려 있지 않다")
        # 취향 벡터의 재료는 분위기 + 목적 태그를 함께 쓴다.
        # 둘 다 "어떤 곳을 좋아하는가"의 축이고, poi.tag_vector도 같은 조합이다.
        upsert_profile(
            db.fetch_all,
            user_id=user_id,
            gender=payload.gender,
            age_band=payload.age_band,
            taste_tags=[*atmosphere, *purpose],
            weather_sensitivity=payload.weather_sensitivity,
        )
    except DatabaseUnavailable as exc:
        log.warning("온보딩 저장 실패: %s", exc)
        raise HTTPException(
            status_code=503, detail=f"프로필을 저장할 수 없습니다: {exc}"
        ) from exc

    return OnboardingResponse(user_id=user_id)
