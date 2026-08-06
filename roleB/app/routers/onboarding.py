"""POST /api/onboarding — 온보딩 5문항 수집.

W1(목): user_id만 결정적으로 발급한다.
W4(B4-5): user_profile INSERT + taste_vector 계산으로 교체한다.
  taste_vector는 서버에서 임베딩하지 않는다. 온보딩 태그는 유한 집합이므로
  태그별 벡터를 배치로 미리 만들어 두고 평균만 낸다 (PLAN.md §11.3).
"""

from __future__ import annotations

import hashlib

from fastapi import APIRouter

from app.schemas import OnboardingRequest, OnboardingResponse

router = APIRouter(prefix="/api", tags=["user"])


@router.post("/onboarding", response_model=OnboardingResponse, summary="온보딩 제출")
def submit_onboarding(payload: OnboardingRequest) -> OnboardingResponse:
    key = "|".join(
        [
            payload.gender,
            str(payload.age_band),
            ",".join(sorted(t.value for t in payload.atmosphere_tags)),
            ",".join(sorted(t.value for t in payload.purpose_tags)),
            str(payload.budget_band),
            str(payload.weather_sensitivity),
        ]
    )
    return OnboardingResponse(
        user_id="u_" + hashlib.sha256(key.encode()).hexdigest()[:6]
    )
