"""② 스코어링 — 7항 가중합 + 재정규화 (B2-3).

    ROLE_B §6.4 재정규화는 이 프로젝트에서 가장 자주 틀리는 지점이고,
    틀리면 에러 없이 **핫스팟 밖 POI가 조용히 순위에서 사라진다.**

거리와 haversine도 여기 둔다. 후보 생성(retrieval.py)은 SQL에서 ST_Distance로
직선거리를 받지만, **점수에 들어가는 거리는 zone 배율이 곱해진 값**이어야 한다.

값이 없을 때의 규칙 (두 가지가 다르다)
--------------------------------------
- `live_segment_match` / `crowd_fit` → **None.** 관측 자체가 불가능한 항이고
  (핫스팟 1km 밖), 가중치를 다른 항에 재분배한다. 응답에서도 키가 빠진다.
- 나머지 5항 → **중립값 0.5.** score_breakdown의 이 키들은 C가 항상 있다고
  가정한다(schemas.py). "상권 코드가 없어서 세그먼트 통계를 못 붙였다"를
  0점으로 바꾸면 조인 실패한 POI가 전부 바닥으로 간다.

W3(B3-1/B3-2)에서 `context_fit`의 실측 날씨 소스와 `live_*`의 스냅샷 조회가
`context_fit.py` / `live_signals.py`로 분리된다. 순수 수식은 여기 남는다.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from app.constants import (
    AFTER_SUNSET_COEF,
    BASELINE_AGE_RATE,
    COLD_FEELS_LIKE,
    CONTEXT_FIT_MAX,
    CROWD_FIT_LIVELY,
    CROWD_FIT_NEUTRAL,
    CROWD_FIT_QUIET,
    DISTANCE_NORM_M,
    EXTREME_TEMP_COEF,
    HEAT_FEELS_LIKE,
    IS_CLEAR_RAIN_PROB,
    NEUTRAL_TERM,
    OPTIONAL_TERMS,
    PENALTY,
    PLEASANT_BONUS,
    PLEASANT_RANGE,
    PM_BAD_GRADE,
    PM_COEF,
    PURPOSE_LIVELY,
    PURPOSE_QUIET,
    RAIN_COEF,
    RAIN_DISTANCE_MULTIPLIER,
    RAIN_PROB_HEAVY,
    RAIN_TRIGGER,
    W,
    WEATHER_SENSITIVITY_RAIN_COEF,
    zone_multiplier,
)

EARTH_RADIUS_M = 6_371_000.0


def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """직선거리(m). 표시용이며, 점수에는 zone 배율을 곱한 값을 쓴다."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def effective_distance_m(
    straight_m: float, user_zone: str | None, poi_zone: str | None
) -> float:
    """체감 거리. 직선 800m라도 철로 반대편이면 도보 20분이다 (ROLE_B §6.6)."""
    return straight_m * zone_multiplier(user_zone, poi_zone)


def distance_penalty(
    straight_m: float,
    user_zone: str | None,
    poi_zone: str | None,
    rain_prob: float = 0.0,
) -> float:
    """0~1로 정규화한 거리 페널티. 비 오면 2배로 민감해진다."""
    d = effective_distance_m(straight_m, user_zone, poi_zone)
    d_norm = min(d / DISTANCE_NORM_M, 1.0)
    mult = RAIN_DISTANCE_MULTIPLIER if rain_prob > RAIN_PROB_HEAVY else 1.0
    return min(d_norm * mult, 1.0)


def renormalized_score(terms: dict[str, float | None]) -> tuple[float, dict[str, float]]:
    """가용한 항만으로 가중합을 내고 **가중치 합으로 나눈다**.

    ⚠️ 여기가 ROLE_B §6.4다. `live_*`가 None인 것은 "실시간 신호 0점"이 아니라
    "그 신호를 관측할 수 없음"이다. 0으로 채우면 핫스팟 반경 밖 POI —
    용산 POI의 상당수 — 가 구조적으로 불리해진다.

    반환: (0~1 점수, 실제로 사용된 항들)
    """
    avail = {k: v for k, v in terms.items() if v is not None and k in W}
    if not avail:
        return 0.0, {}

    wsum = sum(W[k] for k in avail)
    if wsum <= 0:
        return 0.0, {}

    score = sum(W[k] * v for k, v in avail.items()) / wsum
    return score, avail


def total_score(
    terms: dict[str, float | None],
    straight_m: float,
    user_zone: str | None,
    poi_zone: str | None,
    rain_prob: float = 0.0,
) -> tuple[float, dict[str, float], float]:
    """최종 점수 = 재정규화 가중합 − 거리 페널티.

    반환: (점수, 사용된 항, 거리 페널티 값)
    거리 페널티는 score_breakdown.distance로 그대로 응답에 실린다.
    """
    base, avail = renormalized_score(terms)
    dist_pen = distance_penalty(straight_m, user_zone, poi_zone, rain_prob)
    score = base - PENALTY["distance"] * dist_pen
    return max(0.0, min(score, 1.0)), avail, dist_pen


def missing_optional_terms(terms: dict[str, float | None]) -> set[str]:
    """관측되지 않은 옵셔널 항. 응답에서 키를 생략할 대상이다."""
    return {k for k in OPTIONAL_TERMS if terms.get(k) is None}


# ============================================================================
# 개별 항 (B2-3)
# ============================================================================


def _clip01(x: float) -> float:
    return max(0.0, min(x, 1.0))


def purpose_match(purpose_tags: Sequence[str] | None, purpose: str) -> float:
    """요청 목적 ↔ poi.purpose_tags 일치도.

    태그가 아예 없는 POI는 0.35가 아니라 중립이다. 속성 추출이 안 된 것이지
    "목적에 안 맞는다"가 아니다.
    """
    tags = list(purpose_tags or [])
    if not tags:
        return NEUTRAL_TERM
    if purpose == tags[0]:
        return 0.95          # 대표 목적으로 뽑힌 곳
    if purpose in tags:
        return 0.80
    return 0.35


def cosine(a: Sequence[float] | None, b: Sequence[float] | None) -> float | None:
    """길이가 다르거나 영벡터면 None. 0을 반환하면 '정반대'로 오해된다."""
    if not a or not b or len(a) != len(b):
        return None
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return None
    return dot / (na * nb)


def taste_similarity(
    user_vector: Sequence[float] | None, poi_vector: Sequence[float] | None
) -> float:
    """cosine(user.taste_vector, poi.tag_vector). 한쪽이라도 없으면 중립.

    온보딩 임베딩은 W4(B4-5)에 붙는다. 그전까지는 대부분 중립으로 계산되며,
    이는 "취향 축을 아직 안 쓴다"는 뜻이지 취향이 안 맞는다는 뜻이 아니다.
    """
    c = cosine(user_vector, poi_vector)
    if c is None:
        return NEUTRAL_TERM
    return _clip01(c)        # 음의 코사인은 0으로 본다


def segment_affinity_term(affinity: float | None) -> float:
    """상권×업종×세그먼트 소비강도. 조인 키가 없으면 중립 (0이 아니다)."""
    return NEUTRAL_TERM if affinity is None else _clip01(float(affinity))


def quality_term(quality_score: float | None) -> float:
    """별점 대체 품질 점수. 배치가 아직 안 돈 POI는 중립."""
    return NEUTRAL_TERM if quality_score is None else _clip01(float(quality_score))


def context_fit(
    outdoor_exposure: float,
    wx: Mapping[str, Any],
    weather_sensitivity: int = 2,
) -> float:
    """날씨 적합도. **비선형이다** — 선형 가중합으로 바꾸면 로직의 핵심이 사라진다.

    기온은 U자형(쾌적 구간에서만 야외 가산), 미세먼지는 등급 임계값에서 꺾인다.
    `weather_sensitivity`(온보딩 5번 문항, 1~3)가 비 계수를 스케일한다 — 민감한
    사용자일수록 같은 강수확률에서 야외를 더 크게 깎는다 (ROLE_B §6.3 개인화 훅).

    wx 키: rain_prob / pm25_grade / feels_like / visit_hour / sunset_hour
    """
    s = 1.0
    e = float(outdoor_exposure or 0.0)
    rain_prob = float(wx.get("rain_prob", 0.0) or 0.0)
    pm25_grade = int(wx.get("pm25_grade", 1) or 1)
    feels_like = float(wx.get("feels_like", 20.0))
    visit_hour = int(wx.get("visit_hour", 12))
    sunset_hour = int(wx.get("sunset_hour", 19))

    rain_coef = WEATHER_SENSITIVITY_RAIN_COEF.get(weather_sensitivity, RAIN_COEF)

    if rain_prob > RAIN_TRIGGER:
        s *= 1 - rain_coef * e * min(rain_prob, 1.0)
    if pm25_grade >= PM_BAD_GRADE:
        s *= 1 - PM_COEF * e
    if feels_like > HEAT_FEELS_LIKE or feels_like < COLD_FEELS_LIKE:
        s *= 1 - EXTREME_TEMP_COEF * e
    if rain_prob < IS_CLEAR_RAIN_PROB and PLEASANT_RANGE[0] <= feels_like <= PLEASANT_RANGE[1]:
        s *= 1 + PLEASANT_BONUS * e          # 맑고 선선하면 야외가 오히려 유리하다
    if visit_hour >= sunset_hour:
        s *= 1 - AFTER_SUNSET_COEF * e

    return max(0.0, min(s, CONTEXT_FIT_MAX))


def _rate_as_fraction(rate: float) -> float:
    """citydata의 PPLTN_RATE_* 는 퍼센트(31.2)로 온다. 픽스처는 비율(0.312)로 오기도 한다."""
    return rate / 100.0 if rate > 1.0 else rate


def live_segment_match(
    age_rates: Mapping[str, Any] | None, age_band: int | None
) -> float | None:
    """지금 이 지역에 사용자 또래가 실제로 얼마나 있는가.

    **핫스팟 밖이면 None이다. 0이 아니다.** 0을 주면 용산 POI의 상당수 —
    121개 지점 반경 1km 밖 — 가 구조적으로 전멸한다 (ROLE_B §1.3).
    """
    if not age_rates or age_band is None:
        return None
    base = BASELINE_AGE_RATE.get(age_band)
    if not base:
        return None
    raw = age_rates.get(str(age_band))
    if raw is None:
        return None
    try:
        rate = _rate_as_fraction(float(raw))
    except (TypeError, ValueError):
        return None
    # 평균의 2배면 1.0. "또래가 평균보다 많다"를 0~1로 접는다.
    return _clip01(rate / base / 2.0)


def crowd_fit(congest_lvl: str | None, purpose: str) -> float | None:
    """목적에 따라 혼잡이 호재일 수도 악재일 수도 있다. 핫스팟 밖이면 None."""
    if not congest_lvl:
        return None
    if purpose in PURPOSE_QUIET:
        return CROWD_FIT_QUIET.get(congest_lvl, CROWD_FIT_NEUTRAL)
    if purpose in PURPOSE_LIVELY:
        return CROWD_FIT_LIVELY.get(congest_lvl, CROWD_FIT_NEUTRAL)
    return CROWD_FIT_NEUTRAL


def build_terms(
    poi: Mapping[str, Any],
    *,
    purpose: str,
    wx: Mapping[str, Any],
    affinity: float | None = None,
    user_vector: Sequence[float] | None = None,
    user_age_band: int | None = None,
    weather_sensitivity: int = 2,
    hotspot: Mapping[str, Any] | None = None,
) -> dict[str, float | None]:
    """7개 항을 한 번에 만든다. 호출부(pipeline)는 이 dict를 total_score에 넘긴다.

    `hotspot`이 None이면 live 두 항이 None이 되고 ②에서 재정규화된다.
    """
    congest = None
    age_rates = None
    if hotspot:
        # 방문 시각 예측 혼잡도는 W3(B3-2)에서 fcst 배열로 바뀐다.
        # W2는 최신 실황(congest_lvl)을 그대로 쓴다.
        congest = hotspot.get("congest_lvl")
        age_rates = hotspot.get("age_rates")

    return {
        "segment_affinity": segment_affinity_term(affinity),
        "purpose_match": purpose_match(poi.get("purpose_tags"), purpose),
        "taste_similarity": taste_similarity(user_vector, poi.get("tag_vector")),
        "context_fit": context_fit(
            poi.get("outdoor_exposure", 0.0), wx, weather_sensitivity
        ),
        "quality": quality_term(poi.get("quality_score")),
        # ↓ 관측 불가면 None. 절대 0을 넣지 않는다 (ROLE_B §1.3 · §6.4)
        "live_segment_match": live_segment_match(age_rates, user_age_band),
        "crowd_fit": crowd_fit(congest, purpose),
    }
