"""W1 목(mock) 데이터 — C의 대기를 푸는 장치.

**하드코딩 응답이지만 형태는 진짜다.** C가 이걸 보고 UI를 만들기 때문에
필드 하나라도 다르면 W4 통합에서 화면을 다시 짜야 한다. 그래서
openapi.yaml의 스키마 그대로 반환하고, 아래 세 가지를 일부러 섞어 둔다.

  1. `hotspot_code`가 없는 POI  → score_breakdown에 live_segment/crowd **키가 없다**
     C가 undefined를 0으로 렌더링하면 W4에 버그가 된다. 지금 걸리게 한다.
  2. 탐색 슬롯                  → 마지막 결과에 is_exploration: true
  3. explain_mode 세 값         → llm / cache / template UI를 전부 그려보게 한다

목 응답은 **결정적(deterministic)** 이다. 같은 요청은 항상 같은 결과를 준다.
서버를 재시작해도 C의 화면이 바뀌지 않아야 디버깅이 가능하다.

POI·후기 문장은 전부 **가상 데이터**다. 실재하는 상호가 아니다.
A가 `seeds/poi_seed.json`을 커밋하면 자동으로 그쪽을 읽는다.
"""

from __future__ import annotations

import hashlib
import json
import os
import random
from datetime import datetime, timedelta, timezone
from typing import Any

from app.config import Settings, seed_file_path
from app.constants import (
    AFTER_SUNSET_COEF,
    ATTR_CONFIDENCE_MIN,
    ATTR_CONFIDENCE_RELAXED,
    CONTEXT_FIT_MAX,
    CROWD_FIT_LIVELY,
    CROWD_FIT_NEUTRAL,
    CROWD_FIT_QUIET,
    DEFAULT_RADIUS_M,
    EXTREME_TEMP_COEF,
    MAX_RADIUS_RETRY,
    PLEASANT_BONUS,
    PLEASANT_RANGE,
    PM_COEF,
    PURPOSE_LIVELY,
    PURPOSE_QUIET,
    RADIUS_EXPAND_FACTOR,
    RAIN_COEF,
    RAIN_TRIGGER,
    RESULT_MAX,
    RESULT_MIN,
    WEATHER_STATES,
)
from app.schemas import (
    Context,
    Evidence,
    PoiDetail,
    Recommendation,
    RecommendRequest,
    RecommendResponse,
    ScoreBreakdown,
)
from app.services.scoring import haversine_m, total_score

KST = timezone(timedelta(hours=9))

# 목 전용 후보 하한. 실서비스는 constants.MIN_CANDIDATES(30)를 쓴다.
# 상위 4곳 + 탐색 슬롯 1곳을 뽑으려면 최소 이만큼은 남아야 한다.
MOCK_MIN_CANDIDATES = RESULT_MAX


# ============================================================================
# 내장 픽스처 — A의 시드가 아직 없을 때 쓴다 (B는 A를 기다리지 않는다)
#   zone 5종을 모두 덮고, hotspot이 없는 POI를 의도적으로 섞었다.
# ============================================================================

FALLBACK_POIS: list[dict[str, Any]] = [
    {
        "poi_id": "mock_0001", "name": "한남 라운지 카페", "category_l1": "카페",
        "category_l2": "베이커리카페", "lat": 37.5352, "lng": 127.0007,
        "dong": "한남동", "zone": "itaewon", "hotspot": "이태원 관광특구",
        "outdoor_exposure": 0.1, "group_capacity": 6, "price_band": 3, "noise_level": 2,
        "purpose_tags": ["데이트", "작업", "혼자"],
        "atmosphere_tags": ["조용한", "감성적인", "아늑한"],
        "quality_score": 0.82, "mention_count": 340, "review_count": 12,
        "attr_confidence": 0.86,
        "terms": {"segment_affinity": 0.88, "taste_similarity": 0.79, "live_segment_match": 0.84},
        "evidence": [
            "창가 자리에서 보는 뷰가 좋아서 비 오는 날에 더 자주 가게 돼요",
            "평일 낮에는 조용해서 노트북 펴기 좋습니다",
        ],
    },
    {
        "poi_id": "mock_0002", "name": "이태원 루프탑 바", "category_l1": "음식",
        "category_l2": "바", "lat": 37.5340, "lng": 126.9944,
        "dong": "이태원1동", "zone": "itaewon", "hotspot": "이태원 관광특구",
        "outdoor_exposure": 0.9, "group_capacity": 12, "price_band": 4, "noise_level": 4,
        "purpose_tags": ["친구모임", "데이트", "회식"],
        "atmosphere_tags": ["활기찬", "뷰가좋은", "이국적인"],
        "quality_score": 0.74, "mention_count": 512, "review_count": 21,
        "attr_confidence": 0.81,
        "terms": {"segment_affinity": 0.80, "taste_similarity": 0.61, "live_segment_match": 0.90},
        "evidence": ["해질 무렵 옥상에서 남산이 통째로 보입니다"],
    },
    {
        "poi_id": "mock_0003", "name": "경리단 소셜 다이닝", "category_l1": "음식",
        "category_l2": "양식", "lat": 37.5386, "lng": 126.9891,
        "dong": "이태원2동", "zone": "itaewon", "hotspot": "이태원 관광특구",
        "outdoor_exposure": 0.2, "group_capacity": 10, "price_band": 3, "noise_level": 4,
        "purpose_tags": ["친구모임", "회식", "데이트"],
        "atmosphere_tags": ["활기찬", "트렌디한", "넓은"],
        "quality_score": 0.69, "mention_count": 188, "review_count": 9,
        "attr_confidence": 0.72,
        "terms": {"segment_affinity": 0.71, "taste_similarity": 0.66,
                  "live_segment_match": 0.72},
        "evidence": ["8명이 갔는데 자리가 넉넉했어요", "웨이팅은 주말 저녁만 좀 있습니다"],
    },
    {
        # 지점 반경(1km) 안 — live 항 있음
        "poi_id": "mock_0015", "name": "이태원 골목 라멘집", "category_l1": "음식",
        "category_l2": "일식", "lat": 37.5352, "lng": 126.9930,
        "dong": "이태원1동", "zone": "itaewon", "hotspot": "이태원 관광특구",
        "outdoor_exposure": 0.1, "group_capacity": 4, "price_band": 2, "noise_level": 3,
        "purpose_tags": ["혼자", "친구모임", "데이트"],
        "atmosphere_tags": ["아늑한", "가성비", "로컬한"],
        "quality_score": 0.72, "mention_count": 156, "review_count": 9,
        "attr_confidence": 0.73,
        "terms": {"segment_affinity": 0.76, "taste_similarity": 0.63,
                  "live_segment_match": 0.81},
        "evidence": ["혼자 가도 바 자리가 있어서 편했습니다"],
    },
    {
        # 지점 반경 **밖** (약 1.1km) — live_segment/crowd 키가 생략되는 경로.
        # C가 이 응답으로 undefined 렌더링 버그를 W1에 잡을 수 있어야 한다.
        "poi_id": "mock_0016", "name": "보광동 필름 카페", "category_l1": "카페",
        "category_l2": "커피전문점", "lat": 37.5245, "lng": 126.9955,
        "dong": "보광동", "zone": "itaewon", "hotspot": None,
        "outdoor_exposure": 0.2, "group_capacity": 4, "price_band": 2, "noise_level": 2,
        "purpose_tags": ["데이트", "혼자"],
        "atmosphere_tags": ["감성적인", "조용한", "로컬한"],
        "quality_score": 0.76, "mention_count": 94, "review_count": 6,
        "attr_confidence": 0.66,
        "terms": {"segment_affinity": 0.68, "taste_similarity": 0.80},
        "evidence": ["필름 사진 걸린 벽이 예뻐서 오래 앉아 있게 됩니다"],
    },
    {
        # 지점 반경 밖 (약 1.05km)
        "poi_id": "mock_0017", "name": "한남 언덕 와인바", "category_l1": "음식",
        "category_l2": "와인바", "lat": 37.5430, "lng": 127.0000,
        "dong": "한남동", "zone": "itaewon", "hotspot": None,
        "outdoor_exposure": 0.1, "group_capacity": 6, "price_band": 3, "noise_level": 2,
        "purpose_tags": ["데이트", "친구모임"],
        "atmosphere_tags": ["조용한", "감성적인", "트렌디한"],
        "quality_score": 0.81, "mention_count": 133, "review_count": 8,
        "attr_confidence": 0.71,
        "terms": {"segment_affinity": 0.79, "taste_similarity": 0.77},
        "evidence": ["둘이 조용히 이야기하기 좋은 자리 간격입니다"],
    },
    {
        "poi_id": "mock_0004", "name": "용산역 실내 정원 카페", "category_l1": "카페",
        "category_l2": "디저트카페", "lat": 37.5297, "lng": 126.9653,
        "dong": "한강로동", "zone": "yongsan_stn", "hotspot": "용산역",
        "outdoor_exposure": 0.0, "group_capacity": 8, "price_band": 2, "noise_level": 3,
        "purpose_tags": ["가족", "친구모임", "데이트"],
        "atmosphere_tags": ["넓은", "아늑한", "가성비"],
        "quality_score": 0.77, "mention_count": 260, "review_count": 15,
        "attr_confidence": 0.79,
        "terms": {"segment_affinity": 0.74, "taste_similarity": 0.70, "live_segment_match": 0.62},
        "evidence": ["비 오는 날 우산 접고 바로 들어갈 수 있어서 좋았습니다"],
    },
    {
        "poi_id": "mock_0005", "name": "한강로 대형 서점 라운지", "category_l1": "문화",
        "category_l2": "복합문화공간", "lat": 37.5303, "lng": 126.9668,
        "dong": "한강로동", "zone": "yongsan_stn", "hotspot": "용산역",
        "outdoor_exposure": 0.0, "group_capacity": 20, "price_band": 1, "noise_level": 2,
        "purpose_tags": ["혼자", "작업", "가족"],
        "atmosphere_tags": ["조용한", "넓은", "가성비"],
        "quality_score": 0.71, "mention_count": 143, "review_count": 7,
        "attr_confidence": 0.68,
        "terms": {"segment_affinity": 0.63, "taste_similarity": 0.72, "live_segment_match": 0.55},
        "evidence": ["혼자 반나절 앉아 있어도 눈치가 보이지 않는 곳"],
    },
    {
        "poi_id": "mock_0006", "name": "후암동 언덕 로스터리", "category_l1": "카페",
        "category_l2": "커피전문점", "lat": 37.5487, "lng": 126.9772,
        "dong": "후암동", "zone": "huam", "hotspot": None,
        "outdoor_exposure": 0.6, "group_capacity": 4, "price_band": 2, "noise_level": 2,
        "purpose_tags": ["혼자", "데이트", "작업"],
        "atmosphere_tags": ["로컬한", "감성적인", "뷰가좋은"],
        "quality_score": 0.80, "mention_count": 210, "review_count": 11,
        "attr_confidence": 0.75,
        "terms": {"segment_affinity": 0.66, "taste_similarity": 0.83},
        "evidence": ["테라스에서 남산 방향이 보이는데 날 좋은 날은 정말 좋아요"],
    },
    {
        "poi_id": "mock_0007", "name": "해방촌 골목 식당", "category_l1": "음식",
        "category_l2": "한식", "lat": 37.5462, "lng": 126.9836,
        "dong": "용산2가동", "zone": "huam", "hotspot": None,
        "outdoor_exposure": 0.3, "group_capacity": 6, "price_band": 2, "noise_level": 3,
        "purpose_tags": ["친구모임", "혼자", "가족"],
        "atmosphere_tags": ["로컬한", "가성비", "아늑한"],
        "quality_score": 0.73, "mention_count": 121, "review_count": 8,
        "attr_confidence": 0.64,
        "terms": {"segment_affinity": 0.69, "taste_similarity": 0.58},
        "evidence": ["동네 사람들이 더 많이 오는 집이라 웨이팅이 짧습니다"],
    },
    {
        "poi_id": "mock_0008", "name": "이촌 한강 피크닉 라운지", "category_l1": "자연",
        "category_l2": "공원편의시설", "lat": 37.5175, "lng": 126.9723,
        "dong": "이촌1동", "zone": "ichon", "hotspot": None,
        "outdoor_exposure": 1.0, "group_capacity": 30, "price_band": 1, "noise_level": 3,
        "purpose_tags": ["가족", "친구모임", "데이트"],
        "atmosphere_tags": ["넓은", "뷰가좋은", "활기찬"],
        "quality_score": 0.66, "mention_count": 97, "review_count": 6,
        "attr_confidence": 0.55,
        "terms": {"segment_affinity": 0.58, "taste_similarity": 0.54},
        "evidence": ["돗자리 펴기 좋은데 그늘이 부족해서 한여름 낮은 힘듭니다"],
    },
    {
        "poi_id": "mock_0009", "name": "서빙고 가족 브런치하우스", "category_l1": "음식",
        "category_l2": "브런치", "lat": 37.5216, "lng": 126.9930,
        "dong": "서빙고동", "zone": "ichon", "hotspot": None,
        "outdoor_exposure": 0.1, "group_capacity": 10, "price_band": 3, "noise_level": 2,
        "purpose_tags": ["가족", "데이트"],
        "atmosphere_tags": ["아늑한", "조용한", "넓은"],
        "quality_score": 0.75, "mention_count": 88, "review_count": 5,
        "attr_confidence": 0.61,
        "terms": {"segment_affinity": 0.72, "taste_similarity": 0.64},
        "evidence": ["유아 의자가 있어서 아이 데리고 가기 편했어요"],
    },
    {
        "poi_id": "mock_0010", "name": "중앙박물관 앞 전시 카페", "category_l1": "문화",
        "category_l2": "전시", "lat": 37.5240, "lng": 126.9803,
        "dong": "용산동6가", "zone": "ichon", "hotspot": None,
        "outdoor_exposure": 0.2, "group_capacity": 12, "price_band": 2, "noise_level": 1,
        "purpose_tags": ["가족", "데이트", "혼자"],
        "atmosphere_tags": ["조용한", "넓은", "감성적인"],
        "quality_score": 0.79, "mention_count": 175, "review_count": 10,
        "attr_confidence": 0.70,
        "terms": {"segment_affinity": 0.67, "taste_similarity": 0.76},
        "evidence": ["비 오는 날 실내에서 반나절 보내기 좋은 코스입니다"],
    },
    {
        "poi_id": "mock_0011", "name": "청파동 학생 골목 분식", "category_l1": "음식",
        "category_l2": "분식", "lat": 37.5451, "lng": 126.9663,
        "dong": "청파동", "zone": "cheongpa", "hotspot": None,
        "outdoor_exposure": 0.1, "group_capacity": 6, "price_band": 1, "noise_level": 4,
        "purpose_tags": ["혼자", "친구모임"],
        "atmosphere_tags": ["가성비", "로컬한", "활기찬"],
        "quality_score": 0.64, "mention_count": 64, "review_count": 4,
        "attr_confidence": 0.52,
        "terms": {"segment_affinity": 0.61, "taste_similarity": 0.49},
        "evidence": ["가격대가 착해서 학생들이 많습니다"],
    },
    {
        "poi_id": "mock_0012", "name": "원효로 공유 작업실 카페", "category_l1": "카페",
        "category_l2": "스터디카페", "lat": 37.5356, "lng": 126.9608,
        "dong": "원효로1동", "zone": "cheongpa", "hotspot": None,
        "outdoor_exposure": 0.0, "group_capacity": 4, "price_band": 2, "noise_level": 1,
        "purpose_tags": ["작업", "혼자"],
        "atmosphere_tags": ["조용한", "아늑한", "가성비"],
        "quality_score": 0.70, "mention_count": 52, "review_count": 4,
        "attr_confidence": 0.58,
        "terms": {"segment_affinity": 0.55, "taste_similarity": 0.81},
        "evidence": ["콘센트가 자리마다 있어서 오래 작업하기 좋았습니다"],
    },
    {
        "poi_id": "mock_0013", "name": "남영동 심야 포차", "category_l1": "음식",
        "category_l2": "주점", "lat": 37.5411, "lng": 126.9718,
        "dong": "남영동", "zone": "yongsan_stn", "hotspot": None,
        "outdoor_exposure": 0.4, "group_capacity": 16, "price_band": 2, "noise_level": 5,
        "purpose_tags": ["회식", "친구모임"],
        "atmosphere_tags": ["활기찬", "로컬한", "가성비"],
        "quality_score": 0.62, "mention_count": 110, "review_count": 7,
        "attr_confidence": 0.60,
        "terms": {"segment_affinity": 0.70, "taste_similarity": 0.44},
        "evidence": ["10명 넘게 가도 자리를 붙여줍니다"],
    },
    {
        "poi_id": "mock_0014", "name": "이태원 지하 재즈바", "category_l1": "음식",
        "category_l2": "바", "lat": 37.5336, "lng": 126.9922,
        "dong": "이태원1동", "zone": "itaewon", "hotspot": "이태원 관광특구",
        "outdoor_exposure": 0.0, "group_capacity": 8, "price_band": 3, "noise_level": 3,
        "purpose_tags": ["데이트", "친구모임"],
        "atmosphere_tags": ["감성적인", "아늑한", "이국적인"],
        "quality_score": 0.78, "mention_count": 231, "review_count": 13,
        "attr_confidence": 0.77,
        "terms": {"segment_affinity": 0.83, "taste_similarity": 0.74, "live_segment_match": 0.79},
        "evidence": ["지하라 비가 와도 상관없고 음악 소리가 좋습니다"],
    },
]


# ============================================================================
# 시드 적재 — A가 커밋하면 자동 전환
# ============================================================================


def _coerce_seed_row(row: dict[str, Any]) -> dict[str, Any] | None:
    """A의 시드 스키마를 목 픽스처 형태로 맞춘다. 필수 필드가 없으면 버린다."""
    poi_id = row.get("poi_id") or row.get("id")
    name = row.get("name")
    lat = row.get("lat") or (row.get("location") or {}).get("lat")
    lng = row.get("lng") or (row.get("location") or {}).get("lng")
    if not (poi_id and name and lat is not None and lng is not None):
        return None

    return {
        "poi_id": str(poi_id),
        "name": str(name),
        "category_l1": row.get("category_l1") or "기타",
        "category_l2": row.get("category_l2") or row.get("category") or "기타",
        "lat": float(lat),
        "lng": float(lng),
        "dong": row.get("dong"),
        "zone": row.get("zone"),
        "hotspot": row.get("hotspot") or row.get("hotspot_code"),
        "outdoor_exposure": float(row.get("outdoor_exposure", 0.0) or 0.0),
        "group_capacity": int(row.get("group_capacity", 4) or 4),
        "price_band": int(row.get("price_band", 2) or 2),
        "noise_level": row.get("noise_level"),
        "purpose_tags": row.get("purpose_tags") or [],
        "atmosphere_tags": row.get("atmosphere_tags") or [],
        "quality_score": float(row.get("quality_score", 0.6) or 0.6),
        "mention_count": int(row.get("mention_count", 0) or 0),
        "review_count": int(row.get("review_count", 0) or 0),
        "attr_confidence": float(row.get("attr_confidence", 0.5) or 0.5),
        # 시드에 점수 성분은 없다. 목 단계에서는 결정적 의사값으로 채운다.
        "terms": _pseudo_terms(str(poi_id)),
        "evidence": row.get("evidence") or row.get("reviews") or [],
    }


def _pseudo_terms(poi_id: str) -> dict[str, float]:
    """poi_id 해시로 만든 결정적 점수 성분. 시드에 성분이 없을 때만 쓴다."""
    h = hashlib.sha256(poi_id.encode()).digest()
    return {
        "segment_affinity": 0.45 + h[0] / 255 * 0.5,
        "taste_similarity": 0.40 + h[1] / 255 * 0.55,
    }


def load_pois(settings: Settings) -> tuple[list[dict[str, Any]], str]:
    """(POI 목록, 출처). 시드가 없거나 깨졌으면 내장 픽스처로 폴백한다."""
    path = seed_file_path(settings)
    if not os.path.exists(path):
        return FALLBACK_POIS, "fallback"

    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
        rows = raw.get("pois", raw) if isinstance(raw, dict) else raw
        parsed = [c for c in (_coerce_seed_row(r) for r in rows) if c]
        if not parsed:
            return FALLBACK_POIS, "fallback"
        return parsed, os.path.basename(path)
    except (OSError, ValueError, TypeError, AttributeError):
        # 시드가 깨졌다고 서버가 죽으면 C가 막힌다. 폴백해서 계속 뜬다.
        return FALLBACK_POIS, "fallback"


# ============================================================================
# 컨텍스트 — 목 날씨는 방문 시각으로부터 결정적으로 만든다
# ============================================================================

_WEATHER_PROFILE: dict[str, dict[str, Any]] = {
    "맑음":        {"label": "맑음", "rain_prob": 0.05, "pm25_grade": 1, "feels_like": 22.6},
    "비":          {"label": "비 60%", "rain_prob": 0.60, "pm25_grade": 2, "feels_like": 24.1},
    "미세먼지나쁨": {"label": "흐림", "rain_prob": 0.10, "pm25_grade": 3, "feels_like": 26.3},
    "폭염한파":     {"label": "맑음", "rain_prob": 0.00, "pm25_grade": 2, "feels_like": 33.8},
}

_CONGEST_BY_HOUR: list[str] = (
    ["여유"] * 7 + ["보통"] * 4 + ["약간 붐빔"] * 3
    + ["보통"] * 3 + ["약간 붐빔"] * 3 + ["붐빔"] * 3 + ["보통"]
)  # 24개


def parse_visit_at(visit_at: str | None) -> datetime:
    """ISO8601 → KST datetime. 파싱 실패해도 예외를 올리지 않는다."""
    if not visit_at:
        return datetime.now(KST)
    try:
        dt = datetime.fromisoformat(visit_at.replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(KST)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=KST)
    return dt.astimezone(KST)


def weather_state_for(dt: datetime, settings: Settings) -> str:
    """MOCK_WEATHER_STATE가 있으면 그 값, 없으면 날짜로부터 결정적으로 고른다."""
    forced = settings.mock_weather_state
    if forced in WEATHER_STATES:
        return forced
    return WEATHER_STATES[dt.timetuple().tm_yday % len(WEATHER_STATES)]


def build_context(
    lat: float, lng: float, visit_at: str | None, settings: Settings
) -> tuple[Context, dict[str, Any]]:
    """(응답용 Context, 스코어링용 날씨 dict)."""
    dt = parse_visit_at(visit_at)
    state = weather_state_for(dt, settings)
    prof = _WEATHER_PROFILE[state]

    nearest = nearest_hotspot(lat, lng)
    congest_now = _CONGEST_BY_HOUR[datetime.now(KST).hour]
    congest_visit = _CONGEST_BY_HOUR[dt.hour]

    ctx = Context(
        weather=prof["label"] if state != "비" else f"비 {int(prof['rain_prob'] * 100)}%",
        pm25_grade=prof["pm25_grade"],
        feels_like=prof["feels_like"],
        rain_prob=prof["rain_prob"],
        sunset="19:42",
        hotspot=nearest,
        congest_now=congest_now if nearest else None,
        congest_forecast_at_visit=congest_visit if nearest else None,
        age_mix_top="20대 31%" if nearest else None,
    )
    wx = {
        "state": state,
        "rain_prob": prof["rain_prob"],
        "pm25_grade": prof["pm25_grade"],
        "feels_like": prof["feels_like"],
        "sunset_hour": 19,
        "visit_hour": dt.hour,
        "congest_at_visit": congest_visit,
    }
    return ctx, wx


# 용산 해당 실시간 도시데이터 지점 (목). 실제 코드·목록은 A가 121장소 xlsx로 확정한다.
_MOCK_HOTSPOTS: list[tuple[str, float, float]] = [
    ("이태원 관광특구", 37.5345, 126.9946),
    ("용산역", 37.5299, 126.9648),
    ("남산공원", 37.5512, 126.9882),
]
HOTSPOT_RADIUS_M = 1000.0


def nearest_hotspot(lat: float, lng: float) -> str | None:
    """반경 1km 안에 지점이 없으면 None. **0이 아니라 None이다.**"""
    best, best_d = None, HOTSPOT_RADIUS_M
    for name, hlat, hlng in _MOCK_HOTSPOTS:
        d = haversine_m(lat, lng, hlat, hlng)
        if d < best_d:
            best, best_d = name, d
    return best


# ============================================================================
# 점수 성분 (목 전용 근사)
# ============================================================================


def _mock_context_fit(outdoor_exposure: float, wx: dict[str, Any]) -> float:
    """목 전용 근사. 실제 비선형 로직은 W3(B3-1) services/context_fit.py가 소유한다.

    형태만 맞춰 둔다 — 기온은 U자형, 미세먼지는 등급 임계값에서 꺾인다.
    """
    s, e = 1.0, outdoor_exposure
    if wx["rain_prob"] > RAIN_TRIGGER:
        s *= 1 - RAIN_COEF * e * min(wx["rain_prob"], 1.0)
    if wx["pm25_grade"] >= 3:
        s *= 1 - PM_COEF * e
    if wx["feels_like"] > 31 or wx["feels_like"] < -5:
        s *= 1 - EXTREME_TEMP_COEF * e
    if wx["rain_prob"] < 0.2 and PLEASANT_RANGE[0] <= wx["feels_like"] <= PLEASANT_RANGE[1]:
        s *= 1 + PLEASANT_BONUS * e
    if wx["visit_hour"] >= wx["sunset_hour"]:
        s *= 1 - AFTER_SUNSET_COEF * e
    return max(0.0, min(s, CONTEXT_FIT_MAX))


def _purpose_match(poi: dict[str, Any], purpose: str) -> float:
    tags = poi.get("purpose_tags") or []
    if not tags:
        return 0.5                      # 정보 없음. 0으로 떨구지 않는다
    if purpose == (tags[0] if tags else None):
        return 0.95
    if purpose in tags:
        return 0.80
    return 0.35


def _crowd_fit(poi: dict[str, Any], purpose: str, wx: dict[str, Any]) -> float | None:
    """핫스팟 밖이면 None. ROLE_B §6.5."""
    if not poi.get("hotspot"):
        return None
    lvl = wx["congest_at_visit"]
    if purpose in PURPOSE_QUIET:
        return CROWD_FIT_QUIET[lvl]
    if purpose in PURPOSE_LIVELY:
        return CROWD_FIT_LIVELY[lvl]
    return CROWD_FIT_NEUTRAL


def _terms_for(
    poi: dict[str, Any], purpose: str, wx: dict[str, Any]
) -> dict[str, float | None]:
    base = poi.get("terms") or {}
    return {
        "segment_affinity": base.get("segment_affinity", 0.6),
        "purpose_match": _purpose_match(poi, purpose),
        "taste_similarity": base.get("taste_similarity", 0.6),
        "context_fit": _mock_context_fit(poi.get("outdoor_exposure", 0.0), wx),
        "quality": poi.get("quality_score", 0.6),
        # ↓ 핫스팟 밖이면 None. 절대 0을 넣지 않는다 (ROLE_B §1.3)
        "live_segment_match": base.get("live_segment_match") if poi.get("hotspot") else None,
        "crowd_fit": _crowd_fit(poi, purpose, wx),
    }


# ============================================================================
# 목 추천
# ============================================================================

_EXPLAIN_CYCLE = ("template", "cache", "llm")


def _template_reason(poi: dict[str, Any], wx: dict[str, Any], req: RecommendRequest,
                     terms: dict[str, float]) -> str:
    """W4의 template_reason()과 같은 형태. 목 단계에서 미리 문장 길이를 보여준다."""
    parts: list[str] = []
    if wx["rain_prob"] > 0.5 and poi.get("outdoor_exposure", 0.0) < 0.3:
        parts.append("비 예보가 있어 실내 공간 위주로 골랐습니다")
    if wx["pm25_grade"] >= 3 and poi.get("outdoor_exposure", 0.0) < 0.3:
        parts.append("미세먼지 나쁨 예보를 반영해 실내를 우선했습니다")
    if terms.get("segment_affinity", 0) > 0.8:
        parts.append("이 시간대에 또래 방문 비중이 높은 곳입니다")
    if terms.get("purpose_match", 0) > 0.8:
        parts.append(f"{req.purpose.value}에 적합하다는 후기가 많습니다")
    if terms.get("crowd_fit", 1.0) < 0.4:
        parts.append("다만 방문 시각에 다소 붐빌 수 있습니다")
    if not parts:
        return "요청하신 조건에 가장 근접한 장소입니다."
    return ". ".join(parts) + "."


def build_recommendation(
    req: RecommendRequest, settings: Settings
) -> RecommendResponse:
    """목 추천. 하드필터 → 스코어링 → 탐색 슬롯까지 실제 파이프라인 순서를 따른다."""
    pois, _ = load_pois(settings)
    ctx, wx = build_context(req.location.lat, req.location.lng, req.visit_at, settings)
    user_zone = zone_of(req.location.lat, req.location.lng)

    # ① 하드필터 — 실제 W2 SQL(ROLE_B §6.1)의 축소판. 조건 순서까지 같게 둔다.
    def passes(p: dict[str, Any], radius_m: float, conf_min: float) -> bool:
        d = haversine_m(req.location.lat, req.location.lng, p["lat"], p["lng"])
        if d > radius_m:
            return False
        if p.get("group_capacity", 4) < req.party_size:
            return False
        if (p.get("price_band") or 2) > req.budget_band:
            return False
        if wx["rain_prob"] >= 0.6 and p.get("outdoor_exposure", 0.0) > 0.7:
            return False
        if wx["pm25_grade"] >= 4 and p.get("outdoor_exposure", 0.0) > 0.5:
            return False
        return (p.get("attr_confidence") or 0.0) >= conf_min

    low_confidence = False
    radius_expanded = False

    # 반경 확대 재시도 → 그래도 부족하면 신뢰도 완화.
    # **어느 경로에서도 빈 배열을 반환하지 않는다** (ROLE_B §1.3).
    radius = float(DEFAULT_RADIUS_M)
    cands = [p for p in pois if passes(p, radius, ATTR_CONFIDENCE_MIN)]
    for _ in range(MAX_RADIUS_RETRY):
        # 실서비스 기준은 MIN_CANDIDATES(30)다. 픽스처는 POI가 17개뿐이라
        # 그 값을 그대로 쓰면 항상 반경이 확대되어 플래그가 의미를 잃는다.
        if len(cands) >= MOCK_MIN_CANDIDATES:
            break
        radius *= RADIUS_EXPAND_FACTOR
        radius_expanded = True
        cands = [p for p in pois if passes(p, radius, ATTR_CONFIDENCE_MIN)]

    if len(cands) < RESULT_MIN:
        low_confidence = True
        cands = [p for p in pois if passes(p, radius, ATTR_CONFIDENCE_RELAXED)]
    if not cands:
        low_confidence = True
        cands = sorted(
            pois,
            key=lambda p: haversine_m(
                req.location.lat, req.location.lng, p["lat"], p["lng"]
            ),
        )[:RESULT_MAX]

    # ② 스코어링
    scored: list[tuple[float, dict[str, Any], dict[str, float], float, float]] = []
    for p in cands:
        terms = _terms_for(p, req.purpose.value, wx)
        straight = haversine_m(req.location.lat, req.location.lng, p["lat"], p["lng"])
        score, avail, dist_pen = total_score(
            terms, straight, user_zone, p.get("zone"), wx["rain_prob"]
        )
        scored.append((score, p, avail, straight, dist_pen))
    scored.sort(key=lambda x: (-x[0], x[1]["poi_id"]))

    # ③ 상위 4 + 탐색 슬롯 1 (6~20위에서 결정적으로 선택)
    top = scored[: RESULT_MAX - 1]
    explore = None
    pool = scored[RESULT_MAX - 1:]
    if pool:
        rng = random.Random(
            f"{req.user_id}|{req.purpose.value}|{req.visit_at}|{len(pool)}"
        )
        explore = pool[rng.randrange(len(pool))]

    results: list[Recommendation] = []
    for idx, item in enumerate([*top, *( [explore] if explore else [] )]):
        score, p, avail, straight, dist_pen = item
        is_explore = explore is not None and idx == len(top)
        results.append(
            Recommendation(
                poi_id=p["poi_id"],
                name=p["name"],
                category=p.get("category_l2") or p.get("category_l1") or "기타",
                lat=p["lat"],
                lng=p["lng"],
                distance_m=int(round(straight)),
                score=round(score, 4),
                score_breakdown=ScoreBreakdown(
                    segment=round(avail.get("segment_affinity", 0.0), 3),
                    purpose=round(avail.get("purpose_match", 0.0), 3),
                    taste=round(avail.get("taste_similarity", 0.0), 3),
                    context=round(avail.get("context_fit", 0.0), 3),
                    quality=round(avail.get("quality", 0.0), 3),
                    distance=round(dist_pen, 3),
                    # 관측 안 된 항은 None → 응답에서 키 자체가 빠진다
                    live_segment=(round(avail["live_segment_match"], 3)
                                  if "live_segment_match" in avail else None),
                    crowd=(round(avail["crowd_fit"], 3) if "crowd_fit" in avail else None),
                ),
                reason=_template_reason(p, wx, req, avail),
                evidence=[
                    Evidence(text=t, source="naver_blog")
                    for t in (p.get("evidence") or [])[:2]
                ],
                is_exploration=is_explore,
                explain_mode=_EXPLAIN_CYCLE[idx % len(_EXPLAIN_CYCLE)],
                image_url=p.get("image_url"),
            )
        )

    return RecommendResponse(
        context=ctx,
        results=results,
        log_id=_mock_log_id(req),
        low_confidence=low_confidence,
        radius_expanded=radius_expanded,
    )


def _mock_log_id(req: RecommendRequest) -> int:
    """결정적 log_id. 같은 요청은 같은 값을 준다 (C의 피드백 연동 테스트용)."""
    key = f"{req.user_id}|{req.purpose.value}|{req.visit_at}|{req.party_size}"
    return int(hashlib.sha256(key.encode()).hexdigest()[:8], 16) % 900_000 + 100_000


# 목 zone 판정: 대표 좌표 최근접. 실제로는 admin_dong 폴리곤 공간조인이다 (A, W2).
_ZONE_ANCHORS: list[tuple[str, float, float]] = [
    ("itaewon", 37.5345, 126.9946),
    ("yongsan_stn", 37.5299, 126.9648),
    ("huam", 37.5487, 126.9772),
    ("ichon", 37.5205, 126.9760),
    ("cheongpa", 37.5420, 126.9640),
]


def zone_of(lat: float, lng: float) -> str:
    return min(
        _ZONE_ANCHORS, key=lambda z: haversine_m(lat, lng, z[1], z[2])
    )[0]


def build_poi_detail(poi_id: str, settings: Settings) -> PoiDetail | None:
    pois, _ = load_pois(settings)
    for p in pois:
        if p["poi_id"] == poi_id:
            return PoiDetail(
                poi_id=p["poi_id"],
                name=p["name"],
                lat=p["lat"],
                lng=p["lng"],
                category_l1=p.get("category_l1"),
                category_l2=p.get("category_l2"),
                dong=p.get("dong"),
                zone=p.get("zone"),
                business_hours={"mon": ["11:00", "22:00"], "sat": ["11:00", "23:00"]},
                outdoor_exposure=p.get("outdoor_exposure", 0.0),
                group_capacity=p.get("group_capacity", 4),
                noise_level=p.get("noise_level"),
                price_band=p.get("price_band"),
                purpose_tags=p.get("purpose_tags") or [],
                atmosphere_tags=p.get("atmosphere_tags") or [],
                quality_score=p.get("quality_score"),
                mention_count=p.get("mention_count", 0),
                attr_confidence=p.get("attr_confidence", 0.0),
                reviews=[
                    Evidence(text=t, source="naver_blog")
                    for t in (p.get("evidence") or [])
                ],
                image_url=p.get("image_url"),
            )
    return None
