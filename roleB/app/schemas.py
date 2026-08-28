"""Pydantic 모델 — roleC와의 계약.

**openapi.yaml이 원본이고 이 파일이 그 구현이다.** 둘 중 하나만 바꾸면 안 된다.
tests/test_contract.py가 enum·required·필드명을 대조해 어긋나면 실패시킨다.

한 가지 중요한 규칙:
    ScoreBreakdown의 live_segment / crowd는 값이 없을 때 **키 자체를 생략**한다.
    null도 0도 아니다. 그 POI가 실시간 도시데이터 지점 반경 1km 밖이라는 뜻이며,
    엔진은 두 항을 빼고 나머지 가중치를 재정규화한다 (ROLE_B §6.4).
    C가 undefined를 0으로 렌더링하면 "실시간 신호 없음"이 "실시간 점수 0점"으로 뒤바뀐다.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_serializer


# ============================================================================
# 고정 어휘
# ============================================================================


class Purpose(str, Enum):
    DATE = "데이트"
    FRIENDS = "친구모임"
    ALONE = "혼자"
    FAMILY = "가족"
    WORK = "작업"
    DINING = "회식"


class Atmosphere(str, Enum):
    QUIET = "조용한"
    LIVELY = "활기찬"
    EMOTIONAL = "감성적인"
    TRENDY = "트렌디한"
    LOCAL = "로컬한"
    SPACIOUS = "넓은"
    GOOD_VIEW = "뷰가좋은"
    COZY = "아늑한"
    EXOTIC = "이국적인"
    VALUE = "가성비"


class CongestLevel(str, Enum):
    FREE = "여유"
    NORMAL = "보통"
    SLIGHTLY_CROWDED = "약간 붐빔"
    CROWDED = "붐빔"


class ExplainMode(str, Enum):
    """llm=실시간 생성 · cache=explanation_cache 히트 · template=쿼터 소진 폴백."""

    LLM = "llm"
    CACHE = "cache"
    TEMPLATE = "template"


Zone = Literal["itaewon", "yongsan_stn", "huam", "ichon", "cheongpa"]


# ============================================================================
# 공통
# ============================================================================


class Location(BaseModel):
    lat: float = Field(..., examples=[37.5340])
    lng: float = Field(..., examples=[126.9946])


class ErrorResponse(BaseModel):
    detail: str
    code: str | None = None


class HealthResponse(BaseModel):
    status: str = "ok"
    db: bool = False
    mode: Literal["mock", "live"] = "mock"
    version: str = "0.1.0"


# ============================================================================
# 온보딩 — POST /api/onboarding
# ============================================================================


class OnboardingRequest(BaseModel):
    gender: Literal["M", "F"]
    age_band: Literal[10, 20, 30, 40, 50, 60]
    atmosphere_tags: list[Atmosphere] = Field(..., min_length=1)
    purpose_tags: list[Purpose] = Field(..., min_length=1)
    budget_band: int = Field(..., ge=1, le=4)
    weather_sensitivity: int = Field(
        ..., ge=1, le=3,
        description="비 오면 약속을 미루는 편인가. context_fit 개인 가중치로 쓰인다",
    )


class OnboardingResponse(BaseModel):
    user_id: str = Field(..., examples=["u_a91f3c"])


# ============================================================================
# 컨텍스트 — GET /api/context/now
# ============================================================================


class Context(BaseModel):
    weather: str = Field(..., examples=["비 60%"])
    pm25_grade: int = Field(..., ge=1, le=4, description="1 좋음 / 2 보통 / 3 나쁨 / 4 매우나쁨")
    feels_like: float = Field(..., examples=[27.4])
    rain_prob: float | None = None
    sunset: str | None = Field(default=None, examples=["19:42"])
    hotspot: str | None = Field(
        default=None, description="가장 가까운 실시간 도시데이터 지점. 없으면 null"
    )
    congest_now: CongestLevel | None = None
    congest_forecast_at_visit: CongestLevel | None = None
    age_mix_top: str | None = Field(default=None, examples=["20대 31%"])
    weather_source: (
        Literal["citydata", "citydata_fcst", "kma", "kma+citydata", "mock"] | None
    ) = Field(
        default=None,
        description=(
            "날씨를 어디서 가져왔는가. citydata=실황 · citydata_fcst=citydata 24시간 예보 "
            "· kma=기상청 단기예보 · mock=소스 없음(결정적 가짜). 화면에 꼭 그릴 "
            "필요는 없지만, **mock이 뜨는데 실서버라면 키·적재가 빠진 것**이다"
        ),
    )


# ============================================================================
# 추천 — POST /api/recommend
# ============================================================================


class RecommendRequest(BaseModel):
    user_id: str
    purpose: Purpose
    party_size: int = Field(..., ge=1, le=99)
    budget_band: int = Field(..., ge=1, le=4)
    location: Location
    visit_at: str = Field(
        ...,
        description="방문 예정 시각(ISO8601). 실측이 아니라 이 시각의 예보로 판단한다",
        examples=["2026-08-03T19:00:00+09:00"],
    )


class ScoreBreakdown(BaseModel):
    """점수 성분. 디버깅과 발표 시연에 쓰이므로 반드시 반환한다.

    live_segment / crowd 는 None이면 **직렬화에서 제외**된다 (키 자체가 사라진다).
    """

    model_config = ConfigDict(populate_by_name=True)

    segment: float
    purpose: float
    taste: float
    context: float
    quality: float
    distance: float
    live_segment: float | None = None
    crowd: float | None = None

    @model_serializer
    def _drop_missing_live_terms(self) -> dict[str, float]:
        data = {
            "segment": self.segment,
            "purpose": self.purpose,
            "taste": self.taste,
            "context": self.context,
            "quality": self.quality,
            "distance": self.distance,
        }
        if self.live_segment is not None:
            data["live_segment"] = self.live_segment
        if self.crowd is not None:
            data["crowd"] = self.crowd
        return data


class Evidence(BaseModel):
    """review_chunk.text에서 그대로 발췌한 문장. 생성문이 아니다."""

    text: str
    source: str = Field(default="naver_blog", examples=["naver_blog"])


class Recommendation(BaseModel):
    poi_id: str
    name: str
    category: str = Field(..., examples=["베이커리카페"])
    lat: float
    lng: float
    distance_m: int = Field(..., description="직선거리. 점수에는 zone 배율이 반영된다")
    score: float
    score_breakdown: ScoreBreakdown
    reason: str
    evidence: list[Evidence] = Field(default_factory=list)
    is_exploration: bool = Field(
        default=False, description="6~20위에서 무작위로 뽑은 탐색 슬롯. 인기 쏠림 방지용"
    )
    explain_mode: ExplainMode
    image_url: str | None = None


class RecommendResponse(BaseModel):
    context: Context
    results: list[Recommendation] = Field(..., min_length=1, max_length=5)
    log_id: int = Field(..., description="피드백 전송 시 이 값을 함께 보낸다")
    low_confidence: bool = Field(
        default=False, description="후보가 부족해 attr_confidence 기준을 완화한 경우 true"
    )
    radius_expanded: bool = Field(
        default=False, description="후보 부족으로 검색 반경을 넓힌 경우 true"
    )


# ============================================================================
# 피드백 — POST /api/feedback
# ============================================================================


class FeedbackRequest(BaseModel):
    log_id: int
    clicked: list[str] = Field(default_factory=list)
    selected: str | None = None
    feedback: int | None = Field(default=None, ge=1, le=5)


# ============================================================================
# 상세 — GET /api/poi/{poi_id}
# ============================================================================


class PoiDetail(BaseModel):
    poi_id: str
    name: str
    lat: float
    lng: float
    category_l1: str | None = None
    category_l2: str | None = None
    dong: str | None = None
    zone: Zone | None = None
    business_hours: dict[str, Any] | None = None
    # A의 A3-2는 리뷰에 근거가 없으면 이 둘을 NULL로 남긴다. 0.0("완전 실내")과
    # 4("4인석")를 대신 넣으면 **모르는 것을 관측한 척** 상세 화면에 적게 된다.
    # 바로 아래 noise_level·price_band가 이미 nullable이라 거기에 맞췄다.
    # C는 null이면 그 줄을 그리지 않는다 (0으로 그리면 안 된다 — HANDOFF_TO_C §6).
    outdoor_exposure: float | None = Field(default=None, ge=0, le=1)
    group_capacity: int | None = Field(default=None, ge=1)
    noise_level: int | None = Field(default=None, ge=1, le=5)
    price_band: int | None = Field(default=None, ge=1, le=4)
    purpose_tags: list[Purpose] = Field(default_factory=list)
    atmosphere_tags: list[Atmosphere] = Field(default_factory=list)
    quality_score: float | None = None
    mention_count: int = 0
    attr_confidence: float = 0.0
    reviews: list[Evidence] = Field(default_factory=list)
    image_url: str | None = None
