"""① 후보 생성 — PostGIS 반경 + 하드필터 (B2-2).

ROLE_B §6.1. "틀리면 무조건 실패하는 조건"만 SQL에 넣는다. 취향·인기도처럼
"덜 맞을 뿐인" 것은 여기서 자르지 않고 ② 스코어링에서 순위로 내린다.

이 모듈이 반드시 지키는 것
--------------------------
**빈 배열을 반환하지 않는다** (ROLE_B §1.3). 물러서는 순서가 정해져 있다.

    1200m 기본
      → 후보 30개 미만이면 반경 ×1.6 (최대 2회)
      → 그래도 RESULT_MIN 미만이면 attr_confidence 기준을 0.30 → 0.15로 완화
      → 그래도 0건이면 하드필터를 풀고 최근접 N개
         (low_confidence=true 로 표시해 C가 "조건을 완화했다"를 말할 수 있게 한다)

DB를 직접 잡지 않고 `executor`(sql, params) -> list[dict] 를 받는다.
그래야 반경 확대·완화 분기를 DB 없이 테스트할 수 있다. 이 분기는 실데이터가
얇을 때만 타는 경로라, DB 통합 테스트로는 오히려 재현이 어렵다.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.constants import (
    ATTR_CONFIDENCE_MIN,
    ATTR_CONFIDENCE_RELAXED,
    DEFAULT_RADIUS_M,
    MAX_RADIUS_RETRY,
    MIN_CANDIDATES,
    OUTDOOR_EXPOSURE_UNKNOWN,
    RADIUS_EXPAND_FACTOR,
    RESULT_MIN,
)

Executor = Callable[[str, Mapping[str, Any]], list[dict[str, Any]]]

# 후보 한 건당 가져오는 컬럼. 스코어링에 필요한 것만 가져온다.
# **tag_vector 자체는 가져오지 않는다.** 1024차원 × 500건이면 그 자체가 지연이다.
# 취향 유사도는 DB에서 `<=>`(코사인 거리)로 계산해 숫자 하나만 받는다 (W4).
_COLUMNS = """
    p.poi_id, p.name, p.category_l1, p.category_l2,
    ST_Y(p.geom::geometry) AS lat,
    ST_X(p.geom::geometry) AS lng,
    p.dong, p.zone, p.commercial_area_id, p.hotspot_code,
    p.outdoor_exposure, p.group_capacity, p.price_band, p.noise_level,
    p.purpose_tags, p.atmosphere_tags,
    p.quality_score, p.mention_count, p.review_count, p.attr_confidence,
    ST_Distance(p.geom, {pt}) AS dist_m,
    CASE
        WHEN p.tag_vector IS NOT NULL AND u.taste_vector IS NOT NULL
        THEN 1 - (p.tag_vector <=> u.taste_vector)
    END AS taste_sim
"""

# 사용자 좌표. geography로 캐스팅해야 ST_DWithin/ST_Distance가 미터 단위로 돈다.
_POINT = "ST_SetSRID(ST_MakePoint(%(lng)s, %(lat)s), 4326)::geography"

# 취향 벡터 한 행. LATERAL로 붙여서 후보마다 서브쿼리가 돌지 않게 한다.
# 프로필이 없거나 tag_embedding이 비어 있으면 NULL이고, 그러면 taste_sim도 NULL이다
# (0이 아니다 — 0은 "취향이 정반대"라는 뜻이 된다).
_TASTE_JOIN = """
LEFT JOIN LATERAL (
    SELECT taste_vector FROM user_profile WHERE user_id = %(user_id)s
) u ON TRUE
"""

CANDIDATE_SQL = f"""
SELECT {_COLUMNS.format(pt=_POINT)}
FROM poi p
{_TASTE_JOIN}
WHERE ST_DWithin(p.geom, {_POINT}, %(radius_m)s)
  AND is_open_at(p.business_hours, %(visit_at)s)
  -- 인원 수를 **모르는** 것과 인원이 **안 되는** 것은 다르다. NULL을 그대로
  -- 비교하면 3값 논리로 NULL이 되어 그 POI가 조건과 무관하게 항상 빠진다.
  -- 속성 미확보는 배제가 아니라 순위 강등으로 다룬다 (ROLE_B §1.3) —
  -- 실제로 attr_confidence가 그 역할을 하고, price_band도 같은 규칙이다.
  AND (p.group_capacity IS NULL OR p.group_capacity >= %(party_size)s)
  -- outdoor_exposure도 같은 규칙이다. 예전엔 일부러 NULL을 떨어뜨렸는데,
  -- 그 판단은 "NULL은 --clear-seed-mock 자리에만 생긴다"는 전제 위에 있었다.
  -- A의 A3-2가 리뷰에 근거가 없으면 이 컬럼을 NULL로 남기면서 전제가 깨졌다 —
  -- T1 전량이 우천 시 후보에서 통째로 빠질 수 있는 모양이 됐다.
  -- 미관측을 어떻게 볼지는 constants.OUTDOOR_EXPOSURE_UNKNOWN 한 곳에서 정하고,
  -- 점수(context_fit)와 **같은 값**을 쓴다. 갈리면 필터와 순위가 다른 세계를 본다.
  AND (%(rain_prob)s < 0.6
       OR COALESCE(p.outdoor_exposure, %(outdoor_unknown)s) <= 0.7)
  AND (%(pm25_grade)s < 4
       OR COALESCE(p.outdoor_exposure, %(outdoor_unknown)s) <= 0.5)
  AND (p.price_band IS NULL OR p.price_band <= %(budget_band)s)
  AND p.attr_confidence >= %(conf_min)s
ORDER BY dist_m
LIMIT %(limit)s
"""

# 최후 폴백. 하드필터를 전부 풀고 가장 가까운 곳만 준다.
# 빈 화면보다는 "조건을 완화했습니다"가 낫다 (ROLE_B §1.3).
NEAREST_SQL = f"""
SELECT {_COLUMNS.format(pt=_POINT)}
FROM poi p
{_TASTE_JOIN}
ORDER BY p.geom <-> {_POINT}
LIMIT %(limit)s
"""

# 지점별 최신 실시간 스냅샷. 5~7행이라 통째로 읽어도 싸다.
# 15분 폴링은 A가 한다. B는 이 뷰만 읽는다 (ROLE_B §6.5).
HOTSPOT_LATEST_SQL = """
SELECT hotspot_code, hotspot_name, observed_at,
       congest_lvl, ppltn_min, ppltn_max, age_rates, male_rate, female_rate,
       weather, fcst
FROM hotspot_latest
"""

# 사용자에게 가장 가까운 지점. 응답 context.hotspot 에 실린다.
# 반경 밖이면 0행 → context.hotspot = null 이고, 그게 정상이다.
NEAREST_HOTSPOT_SQL = f"""
SELECT h.code, h.name, ST_Distance(h.geom, {_POINT}) AS dist_m
FROM hotspot h
WHERE ST_DWithin(h.geom, {_POINT}, %(radius_m)s)
ORDER BY dist_m
LIMIT 1
"""

USER_PROFILE_SQL = """
SELECT user_id, gender, age_band, taste_tags, weather_sensitivity
FROM user_profile
WHERE user_id = %(user_id)s
"""

# 상세 화면. 후보 생성과 달리 한 건이므로 리뷰 인용까지 함께 가져온다.
# 협찬 글은 뒤로 민다 — 상세에서도 광고 문장이 대표로 보이면 신뢰를 잃는다.
POI_DETAIL_SQL = """
SELECT p.poi_id, p.name, p.category_l1, p.category_l2,
       ST_Y(p.geom::geometry) AS lat,
       ST_X(p.geom::geometry) AS lng,
       p.dong, p.zone, p.business_hours,
       p.outdoor_exposure, p.group_capacity, p.noise_level, p.price_band,
       p.purpose_tags, p.atmosphere_tags,
       p.quality_score, p.mention_count, p.attr_confidence,
       COALESCE(r.reviews, '[]'::json) AS reviews
FROM poi p
LEFT JOIN LATERAL (
    SELECT json_agg(json_build_object('text', c.text, 'source', c.source)) AS reviews
    FROM (
        SELECT text, source
        FROM review_chunk
        WHERE poi_id = p.poi_id
        -- written_at이 전 건 NULL이면 동점이라 순서가 매번 달라진다 (rag.py 참조)
        ORDER BY is_sponsored, written_at DESC NULLS LAST, chunk_id DESC
        LIMIT 5
    ) c
) r ON TRUE
WHERE p.poi_id = %(poi_id)s
"""

# 사용자가 서 있는 생활권. 거리 배율의 기준점이다 (ROLE_B §6.6).
# admin_dong이 아직 비어 있으면 0행 → zone 배율 1.0(중립)로 떨어진다.
USER_ZONE_SQL = """
SELECT zone
FROM admin_dong
WHERE ST_Contains(geom, ST_SetSRID(ST_MakePoint(%(lng)s, %(lat)s), 4326))
  AND zone IS NOT NULL
LIMIT 1
"""

# 세그먼트 선호도. 후보의 (상권 × 업종) 조합만 골라서 한 번에 가져온다.
# 후보마다 쿼리를 날리면 500번이 된다.
SEGMENT_AFFINITY_SQL = """
SELECT commercial_area_id, category_l2, AVG(affinity)::float8 AS affinity
FROM segment_affinity
WHERE commercial_area_id = ANY(%(area_ids)s)
  AND category_l2 = ANY(%(categories)s)
  AND gender = %(gender)s
  AND age_band = ANY(%(age_bands)s)
  AND dow_type = %(dow_type)s
  AND hour_band = %(hour_band)s
GROUP BY commercial_area_id, category_l2
"""


@dataclass(frozen=True)
class RetrievalQuery:
    """하드필터 입력. 날씨는 방문 예정 시각의 **예보**다 (실측이 아니다)."""

    lat: float
    lng: float
    visit_at: datetime
    party_size: int
    budget_band: int
    rain_prob: float = 0.0
    pm25_grade: int = 1
    limit: int = 500
    # 취향 유사도를 DB에서 계산하기 위한 키. 프로필이 없으면 taste_sim이 NULL이 된다.
    user_id: str = ""
    # 속성 신뢰도 하한. 기본값은 설계값이고, 호출부(pipeline)가 설정값으로 덮는다.
    # A의 속성 추출 전에는 전 건 0이라 이 값을 낮춰야 후보가 남는다 (config.py 참고).
    conf_min: float = float(ATTR_CONFIDENCE_MIN)
    conf_relaxed: float = float(ATTR_CONFIDENCE_RELAXED)


@dataclass
class RetrievalResult:
    candidates: list[dict[str, Any]] = field(default_factory=list)
    radius_m: float = float(DEFAULT_RADIUS_M)
    radius_expanded: bool = False
    low_confidence: bool = False
    # 어느 경로로 후보를 얻었는지. 로그·디버깅용이며 응답에는 싣지 않는다.
    strategy: str = "base"


def _params(q: RetrievalQuery, radius_m: float, conf_min: float) -> dict[str, Any]:
    return {
        "lat": q.lat,
        "lng": q.lng,
        "radius_m": radius_m,
        "visit_at": q.visit_at,
        "party_size": q.party_size,
        "budget_band": q.budget_band,
        "rain_prob": q.rain_prob,
        "pm25_grade": q.pm25_grade,
        "outdoor_unknown": OUTDOOR_EXPOSURE_UNKNOWN,
        "conf_min": conf_min,
        "limit": q.limit,
        "user_id": q.user_id,
    }


def retrieve(executor: Executor, q: RetrievalQuery) -> RetrievalResult:
    """후보를 만든다. 어떤 경로로도 빈 리스트를 반환하지 않는다."""
    radius = float(DEFAULT_RADIUS_M)
    rows = executor(CANDIDATE_SQL, _params(q, radius, q.conf_min))
    result = RetrievalResult(candidates=rows, radius_m=radius)

    # ① 반경 확대 — 후보가 얇으면 순위가 의미를 잃는다
    for _ in range(MAX_RADIUS_RETRY):
        if len(result.candidates) >= MIN_CANDIDATES:
            break
        radius *= RADIUS_EXPAND_FACTOR
        result.candidates = executor(
            CANDIDATE_SQL, _params(q, radius, q.conf_min)
        )
        result.radius_m = radius
        result.radius_expanded = True
        result.strategy = "radius_expanded"

    # 반경을 다 넓혔는데도 얇으면, 결과가 3건 나오더라도 **순위는 못 믿는다.**
    # 예전엔 이 표시를 ②·③ 분기에서만 켰다. 그래서 임계값을 통과한 POI가 전
    # 도시에 3건뿐인 상태에서도 `low_confidence=False`가 나갔다 —
    # C에게 준 계약("후보가 극소수 → 순위를 신뢰하기 어렵다")과 어긋나고,
    # 하필 **안전한 쪽으로 틀리지 않는다.** 전환 판정을 이 필드로 보는데
    # 3/6,644에서 초록불이 켜진다. MIN_CANDIDATES가 이미 "순위가 의미를 갖는
    # 최소 후보 수"라 그 기준을 그대로 쓴다.
    if len(result.candidates) < MIN_CANDIDATES:
        result.low_confidence = True

    if len(result.candidates) >= RESULT_MIN:
        return result

    # ② 신뢰도 완화 — 속성이 얕은 POI까지 받는다. 응답에 low_confidence로 표시된다
    relaxed = executor(CANDIDATE_SQL, _params(q, radius, q.conf_relaxed))
    if relaxed:
        result.candidates = relaxed
        result.low_confidence = True
        result.strategy = "confidence_relaxed"
        if len(relaxed) >= RESULT_MIN:
            return result

    # ③ 최후 — 하드필터를 풀고 최근접. 빈 화면만은 만들지 않는다
    if len(result.candidates) < RESULT_MIN:
        nearest = executor(
            NEAREST_SQL,
            {"lat": q.lat, "lng": q.lng, "limit": RESULT_MIN, "user_id": q.user_id},
        )
        if len(nearest) > len(result.candidates):
            result.candidates = nearest
            result.low_confidence = True
            result.strategy = "nearest_fallback"

    return result


def fetch_hotspot_latest(executor: Executor) -> dict[str, dict[str, Any]]:
    """{hotspot_code: 최신 스냅샷}. 폴링이 아직 안 돌았으면 빈 dict다.

    빈 dict여도 정상이다. 그 경우 모든 POI의 `live_*` 항이 None이 되고
    ②에서 나머지 가중치로 재정규화된다 (ROLE_B §6.4).
    """
    return {r["hotspot_code"]: r for r in executor(HOTSPOT_LATEST_SQL, {})}


def fetch_nearest_hotspot(
    executor: Executor, lat: float, lng: float, radius_m: float = 1000.0
) -> dict[str, Any] | None:
    rows = executor(
        NEAREST_HOTSPOT_SQL, {"lat": lat, "lng": lng, "radius_m": radius_m}
    )
    return rows[0] if rows else None


def fetch_user_profile(executor: Executor, user_id: str) -> dict[str, Any] | None:
    rows = executor(USER_PROFILE_SQL, {"user_id": user_id})
    return rows[0] if rows else None


def fetch_poi_detail(executor: Executor, poi_id: str) -> dict[str, Any] | None:
    rows = executor(POI_DETAIL_SQL, {"poi_id": poi_id})
    return rows[0] if rows else None


def fetch_user_zone(executor: Executor, lat: float, lng: float) -> str | None:
    rows = executor(USER_ZONE_SQL, {"lat": lat, "lng": lng})
    return rows[0]["zone"] if rows else None


def fetch_segment_affinity(
    executor: Executor,
    candidates: Sequence[Mapping[str, Any]],
    gender: str,
    age_bands: Sequence[int],
    dow_type: int,
    hour_band: int,
) -> dict[tuple[str, str], float]:
    """{(상권, 업종): affinity}. 조인 키가 없는 후보는 애초에 조회하지 않는다.

    상권 코드가 없는 POI(공간조인 실패 또는 상권 밖)는 여기서 값을 못 얻는다.
    그때 0을 주면 안 된다 — 스코어링에서 중립값으로 처리한다 (ROLE_B §1.3).
    """
    area_ids = sorted({c["commercial_area_id"] for c in candidates if c.get("commercial_area_id")})
    categories = sorted({c["category_l2"] for c in candidates if c.get("category_l2")})
    if not area_ids or not categories or not gender or not age_bands:
        return {}

    rows = executor(
        SEGMENT_AFFINITY_SQL,
        {
            "area_ids": list(area_ids),
            "categories": list(categories),
            "gender": gender,
            "age_bands": list(age_bands),
            "dow_type": dow_type,
            "hour_band": hour_band,
        },
    )
    return {(r["commercial_area_id"], r["category_l2"]): float(r["affinity"]) for r in rows}
