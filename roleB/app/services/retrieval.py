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
    RADIUS_EXPAND_FACTOR,
    RESULT_MIN,
)

Executor = Callable[[str, Mapping[str, Any]], list[dict[str, Any]]]

# 후보 한 건당 가져오는 컬럼. 스코어링에 필요한 것만 가져온다.
# tag_vector는 1024차원이라 500개를 끌어오면 그 자체가 지연이 된다.
# 취향 유사도는 W4에 SQL 쪽 `<=>` 연산으로 옮긴다 (ROLE_B §6.8과 같은 방식).
_COLUMNS = """
    p.poi_id, p.name, p.category_l1, p.category_l2,
    ST_Y(p.geom::geometry) AS lat,
    ST_X(p.geom::geometry) AS lng,
    p.dong, p.zone, p.commercial_area_id, p.hotspot_code,
    p.outdoor_exposure, p.group_capacity, p.price_band, p.noise_level,
    p.purpose_tags, p.atmosphere_tags,
    p.quality_score, p.mention_count, p.review_count, p.attr_confidence,
    ST_Distance(p.geom, {pt}) AS dist_m
"""

# 사용자 좌표. geography로 캐스팅해야 ST_DWithin/ST_Distance가 미터 단위로 돈다.
_POINT = "ST_SetSRID(ST_MakePoint(%(lng)s, %(lat)s), 4326)::geography"

CANDIDATE_SQL = f"""
SELECT {_COLUMNS.format(pt=_POINT)}
FROM poi p
WHERE ST_DWithin(p.geom, {_POINT}, %(radius_m)s)
  AND is_open_at(p.business_hours, %(visit_at)s)
  AND p.group_capacity >= %(party_size)s
  AND (%(rain_prob)s < 0.6 OR p.outdoor_exposure <= 0.7)
  AND (%(pm25_grade)s < 4 OR p.outdoor_exposure <= 0.5)
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
        "conf_min": conf_min,
        "limit": q.limit,
    }


def retrieve(executor: Executor, q: RetrievalQuery) -> RetrievalResult:
    """후보를 만든다. 어떤 경로로도 빈 리스트를 반환하지 않는다."""
    radius = float(DEFAULT_RADIUS_M)
    rows = executor(CANDIDATE_SQL, _params(q, radius, ATTR_CONFIDENCE_MIN))
    result = RetrievalResult(candidates=rows, radius_m=radius)

    # ① 반경 확대 — 후보가 얇으면 순위가 의미를 잃는다
    for _ in range(MAX_RADIUS_RETRY):
        if len(result.candidates) >= MIN_CANDIDATES:
            break
        radius *= RADIUS_EXPAND_FACTOR
        result.candidates = executor(
            CANDIDATE_SQL, _params(q, radius, ATTR_CONFIDENCE_MIN)
        )
        result.radius_m = radius
        result.radius_expanded = True
        result.strategy = "radius_expanded"

    if len(result.candidates) >= RESULT_MIN:
        return result

    # ② 신뢰도 완화 — 속성이 얕은 POI까지 받는다. 응답에 low_confidence로 표시된다
    relaxed = executor(CANDIDATE_SQL, _params(q, radius, ATTR_CONFIDENCE_RELAXED))
    if relaxed:
        result.candidates = relaxed
        result.low_confidence = True
        result.strategy = "confidence_relaxed"
        if len(relaxed) >= RESULT_MIN:
            return result

    # ③ 최후 — 하드필터를 풀고 최근접. 빈 화면만은 만들지 않는다
    if len(result.candidates) < RESULT_MIN:
        nearest = executor(NEAREST_SQL, {"lat": q.lat, "lng": q.lng, "limit": RESULT_MIN})
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
