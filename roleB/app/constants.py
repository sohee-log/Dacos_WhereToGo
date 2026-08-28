"""고정 상수 — 어휘 · 가중치 · zone 배율.

여기 있는 값은 A(추출) · C(온보딩 UI)와 공유된다.
**임의로 확장하지 않는다.** 어휘를 늘리려면 3인 합의 + openapi.yaml 동시 수정이다.

출처: docs/ROLE_B_ENGINE.md §4.4 · §6.2 · §6.6
"""

from __future__ import annotations

# ============================================================================
# 고정 어휘 (openapi.yaml의 enum과 1:1로 일치해야 한다 — tests/test_contract.py가 검증)
# ============================================================================

PURPOSE_TAGS: tuple[str, ...] = ("데이트", "친구모임", "혼자", "가족", "작업", "회식")

ATMOSPHERE_TAGS: tuple[str, ...] = (
    "조용한", "활기찬", "감성적인", "트렌디한", "로컬한",
    "넓은", "뷰가좋은", "아늑한", "이국적인", "가성비",
)

WEATHER_STATES: tuple[str, ...] = ("맑음", "비", "미세먼지나쁨", "폭염한파")

CONGEST_LEVELS: tuple[str, ...] = ("여유", "보통", "약간 붐빔", "붐빔")

ZONES: tuple[str, ...] = ("itaewon", "yongsan_stn", "huam", "ichon", "cheongpa")

AGE_BANDS: tuple[int, ...] = (10, 20, 30, 40, 50, 60)

# 인원 밴드 — query_vector_cache의 축 (목적 6 × 날씨 4 × 인원밴드 3 = 72행)
PARTY_BANDS: dict[int, tuple[int, int]] = {1: (1, 2), 2: (3, 4), 3: (5, 99)}


def party_band(party_size: int) -> int:
    """인원수를 밴드(1~3)로 접는다. query_vector_cache 조회 키."""
    for band, (lo, hi) in PARTY_BANDS.items():
        if lo <= party_size <= hi:
            return band
    return 3


# segment_affinity 조회 축 (ROLE_B §4.1). 테이블은 4시간 단위 6밴드다.
SEGMENT_HOUR_BAND_SIZE = 4


def hour_band(hour: int) -> int:
    """0~23시 → 0~5 밴드."""
    return max(0, min(hour, 23)) // SEGMENT_HOUR_BAND_SIZE


def dow_type(weekday: int) -> int:
    """0=평일 1=주말. `datetime.weekday()`(월=0) 기준."""
    return 1 if weekday >= 5 else 0


def segment_age_bands(age_band: int | None) -> tuple[int, ...]:
    """사용자 연령대(10년 단위) → segment_affinity의 5세 단위 밴드.

    사용자는 "20대"로 답하지만 상권분석 원본은 20·25로 쪼개져 있다.
    한쪽만 조회하면 표본의 절반을 버리게 된다.
    """
    if age_band is None:
        return ()
    return (age_band, age_band + 5)


# 값을 관측하지 못했을 때의 중립값.
#   0을 주면 "정보 없음"이 "최악"으로 바뀐다 (ROLE_B §1.3).
#   live_* 두 항만 None으로 두고 재정규화하는 이유는 응답 계약 때문이다 —
#   score_breakdown의 나머지 6개 키는 C가 항상 있다고 가정한다 (schemas.py).
NEUTRAL_TERM = 0.5


# ============================================================================
# 스코어링 가중치 (ROLE_B §6.2)
#   live_* 두 항은 옵셔널이다. hotspot_code가 NULL인 POI에는 값이 없고,
#   이때 0을 넣으면 핫스팟 밖 POI가 구조적으로 전멸한다 → §6.4 재정규화.
# ============================================================================

W: dict[str, float] = {
    "segment_affinity": 0.22,
    "purpose_match": 0.22,
    "taste_similarity": 0.16,
    "context_fit": 0.13,
    "quality": 0.09,
    "live_segment_match": 0.10,   # ★옵셔널
    "crowd_fit": 0.08,            # ★옵셔널
}

PENALTY: dict[str, float] = {"distance": 0.05}

# 값이 None일 수 있는 항. 재정규화 대상이다.
OPTIONAL_TERMS: frozenset[str] = frozenset({"live_segment_match", "crowd_fit"})

# 응답(score_breakdown)의 키 이름 ↔ 내부 항 이름
TERM_TO_BREAKDOWN: dict[str, str] = {
    "segment_affinity": "segment",
    "purpose_match": "purpose",
    "taste_similarity": "taste",
    "context_fit": "context",
    "quality": "quality",
    "live_segment_match": "live_segment",
    "crowd_fit": "crowd",
}

# ============================================================================
# 후보 생성 파라미터 (ROLE_B §6.1)
# ============================================================================

DEFAULT_RADIUS_M = 1200          # 도보 15분
RADIUS_EXPAND_FACTOR = 1.6
MAX_RADIUS_RETRY = 2
MIN_CANDIDATES = 30              # 이 밑이면 반경을 넓힌다
ATTR_CONFIDENCE_MIN = 0.30       # 속성 미확보 POI 제외선
ATTR_CONFIDENCE_RELAXED = 0.15   # 반경을 다 넓혀도 부족할 때만 여기까지 완화
TOP_N = 20                       # RAG 대상
RESULT_MIN, RESULT_MAX = 3, 5
EXPLORATION_RANK_RANGE = (6, 20)  # 탐색 슬롯을 뽑는 순위 구간 (ROLE_B §6.7)

DISTANCE_NORM_M = 2000.0         # 거리 정규화 분모
RAIN_DISTANCE_MULTIPLIER = 2.0   # 비 올 때 거리 페널티 2배
RAIN_PROB_HEAVY = 0.5

# ============================================================================
# zone 배율 (ROLE_B §6.6)
#   용산은 남산·한강·경부선 철로로 생활권이 물리적으로 끊긴다.
#   직선 800m라도 철로 반대편이면 도보 20분이다.
#
#   ⚠️ 5×5 대칭 행렬 = 10개 조합을 **전부** 채운다. 빠지면 KeyError로 터진다.
#   문서에 값이 명시된 5개 외 나머지 5개는 §13 지형 설명 기준의 잠정치이며,
#   W2에 실제 도보/대중교통 소요로 검증한다.
# ============================================================================

_ZONE_BARRIER_RAW: dict[tuple[str, str], float] = {
    ("itaewon", "yongsan_stn"): 1.4,    # 문서 명시
    ("itaewon", "huam"):        1.6,    # 문서 명시 — 남산 자락
    ("itaewon", "ichon"):       2.2,    # 문서 명시 — 한강로+철로 이중 장벽
    ("itaewon", "cheongpa"):    2.0,    # 잠정 — 구를 가로지른다
    ("yongsan_stn", "huam"):    1.5,    # 잠정 — 남영역 경유 언덕
    ("yongsan_stn", "ichon"):   1.1,    # 문서 명시 — 1정거장, 오히려 가깝다
    ("yongsan_stn", "cheongpa"): 1.2,   # 잠정 — 철로 서편 인접
    ("huam", "ichon"):          2.5,    # 문서 명시 — 최대 장벽
    ("huam", "cheongpa"):       1.4,    # 잠정 — 남영동 경유 인접, 언덕
    ("ichon", "cheongpa"):      1.9,    # 잠정 — 철로+한강로 건너
}


def normalize_pair(a: str, b: str) -> tuple[str, str]:
    """(from, to)를 대칭 조회용 정렬 키로 바꾼다."""
    return (a, b) if a <= b else (b, a)


# 조회 키는 항상 정렬된 형태다. 위 표를 손으로 정렬해 적으면 반드시 한 칸 틀린다.
ZONE_BARRIER: dict[tuple[str, str], float] = {
    normalize_pair(a, b): v for (a, b), v in _ZONE_BARRIER_RAW.items()
}


def zone_multiplier(from_zone: str | None, to_zone: str | None) -> float:
    """생활권 이동 저항 배율. 같은 zone이거나 zone을 모르면 1.0."""
    if not from_zone or not to_zone or from_zone == to_zone:
        return 1.0
    return ZONE_BARRIER[normalize_pair(from_zone, to_zone)]


# ============================================================================
# 실시간 항 (ROLE_B §6.5)
# ============================================================================

# 목적에 따라 혼잡이 호재일 수도 악재일 수도 있다.
CROWD_FIT_QUIET: dict[str, float] = {"여유": 1.0, "보통": 0.8, "약간 붐빔": 0.5, "붐빔": 0.2}
CROWD_FIT_LIVELY: dict[str, float] = {"여유": 0.6, "보통": 0.9, "약간 붐빔": 1.0, "붐빔": 0.8}
CROWD_FIT_NEUTRAL = 0.8

PURPOSE_QUIET: frozenset[str] = frozenset({"데이트", "혼자", "작업"})
PURPOSE_LIVELY: frozenset[str] = frozenset({"친구모임", "회식"})

# 서울 전체 평균 연령 비율. live_segment_match의 분모다.
# ⚠️ 잠정치 — W3에 citydata 실측 분포(또는 생활인구 통계)로 교체한다.
BASELINE_AGE_RATE: dict[int, float] = {
    10: 0.10, 20: 0.22, 30: 0.20, 40: 0.18, 50: 0.16, 60: 0.14,
}

# ============================================================================
# 날씨 (ROLE_B §6.3) — 비선형 계수. 선형 가중합으로 만들지 말 것.
# ============================================================================

# 야외 노출도를 **모르는** POI를 계산에서 어떻게 볼 것인가.
#
# A의 속성 추출(A3-2)은 리뷰에 근거가 없으면 이 컬럼을 NULL로 남긴다 —
# DDL 기본값 0.0이 "완전 실내"라는 **거짓 관측**이 되는 것보다 맞는 선택이다.
# 대신 엔진 쪽에서 NULL을 어떻게 볼지 한 곳에 정해 둬야 한다.
#
# 0.0으로 본다. 근거는 두 가지다.
#   ① 하드컷에서 배제하지 않는다. 속성 미확보는 배제가 아니라 순위 강등이고
#      (ROLE_B §1.3), 그 역할은 attr_confidence가 한다. group_capacity·price_band가
#      이미 같은 규칙이다.
#   ② context_fit에서 e=0이면 모든 날씨 계수가 1로 접혀 정확히 중립(1.0)이 된다.
#      즉 "모르는 곳은 날씨로 올리지도 내리지도 않는다"와 같은 뜻이다.
#
# **이 상수는 후보 SQL(retrieval)과 점수(context_fit)가 함께 쓴다.** 한쪽만
# 바꾸면 필터와 점수가 다른 세계를 보게 된다 — 이미 SNAPSHOT_STALE에서 겪었다.
# 다만 "모른다"를 "실내라고 말한다"로 바꾸지는 않는다 (explain.py).
OUTDOOR_EXPOSURE_UNKNOWN = 0.0

RAIN_TRIGGER = 0.3           # 이 확률을 넘으면 야외 감점 시작
IS_CLEAR_RAIN_PROB = 0.2     # 이 밑이면 "맑음"으로 보고 야외 보너스를 준다
RAIN_COEF = 0.7              # weather_sensitivity로 스케일된다
PM_BAD_GRADE = 3             # 나쁨 이상
PM_COEF = 0.5
HEAT_FEELS_LIKE = 31.0
COLD_FEELS_LIKE = -5.0
EXTREME_TEMP_COEF = 0.6
PLEASANT_RANGE = (15.0, 25.0)
PLEASANT_BONUS = 0.4
AFTER_SUNSET_COEF = 0.3
CONTEXT_FIT_MAX = 1.5

# weather_sensitivity(1~3) → 비 계수 스케일 (ROLE_B §6.3 개인화 훅)
WEATHER_SENSITIVITY_RAIN_COEF: dict[int, float] = {1: 0.5, 2: 0.7, 3: 0.9}
