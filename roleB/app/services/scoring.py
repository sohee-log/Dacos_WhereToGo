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
    BASELINE_AGE_RATE,
    CROWD_FIT_LIVELY,
    CROWD_FIT_NEUTRAL,
    CROWD_FIT_QUIET,
    DISTANCE_NORM_M,
    NEUTRAL_TERM,
    OPTIONAL_TERMS,
    PENALTY,
    PURPOSE_LIVELY,
    PURPOSE_QUIET,
    RAIN_DISTANCE_MULTIPLIER,
    RAIN_PROB_HEAVY,
    W,
    zone_multiplier,
)

# 날씨 비선형 로직은 W3(B3-1)에 context_fit.py로 분리됐다.
# 여기서 다시 내보내는 것은 기존 임포트 경로를 깨지 않기 위해서다.
from app.services.context_fit import (  # noqa: F401
    DEFAULT_WEATHER_SENSITIVITY,
    context_fit,
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

    ⚠️ **실제 경로는 이 함수를 쓰지 않는다.** 1024차원 벡터를 후보 500건만큼
    끌어오면 그 자체가 지연이라, W4부터는 DB에서 `<=>`로 계산해 숫자 하나만
    받는다(retrieval.CANDIDATE_SQL). 이 함수는 그 값의 **정의**를 코드로 남겨
    두는 자리이며, 벡터를 직접 다루는 테스트가 쓴다.
    """
    return taste_from_similarity(cosine(user_vector, poi_vector))


def taste_from_similarity(similarity: float | None) -> float:
    """DB가 계산해 준 코사인 유사도 → 점수 항.

    None은 "취향 축을 관측할 수 없다"는 뜻이다 — 프로필이 없거나 POI에
    `tag_vector`가 없다. **0으로 바꾸지 않는다.** 0은 "취향이 정반대"다.
    """
    if similarity is None:
        return NEUTRAL_TERM
    return _clip01(float(similarity))        # 음의 코사인은 0으로 본다


def segment_affinity_term(affinity: float | None) -> float:
    """상권×업종×세그먼트 소비강도. 조인 키가 없으면 중립 (0이 아니다)."""
    return NEUTRAL_TERM if affinity is None else _clip01(float(affinity))


def quality_term(quality_score: float | None) -> float:
    """별점 대체 품질 점수. 배치가 아직 안 돈 POI는 중립."""
    return NEUTRAL_TERM if quality_score is None else _clip01(float(quality_score))


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
    taste_sim: float | None = None,
    user_age_band: int | None = None,
    weather_sensitivity: int = DEFAULT_WEATHER_SENSITIVITY,
    congest_lvl: str | None = None,
    age_rates: Mapping[str, Any] | None = None,
) -> dict[str, float | None]:
    """7개 항을 한 번에 만든다. 호출부(pipeline)는 이 dict를 total_score에 넘긴다.

    `congest_lvl`·`age_rates`는 지점 반경 밖 POI면 None으로 들어온다. 그러면
    live 두 항이 None이 되고 ②에서 재정규화된다 (§6.4).
    스냅샷 해석은 live_signals.py가 한다 — 여기는 순수 수식만 남긴다.
    """
    congest = congest_lvl

    return {
        "segment_affinity": segment_affinity_term(affinity),
        "purpose_match": purpose_match(poi.get("purpose_tags"), purpose),
        "taste_similarity": taste_from_similarity(
            taste_sim if taste_sim is not None else poi.get("taste_sim")
        ),
        "context_fit": context_fit(
            poi.get("outdoor_exposure", 0.0), wx, weather_sensitivity
        ),
        "quality": quality_term(poi.get("quality_score")),
        # ↓ 관측 불가면 None. 절대 0을 넣지 않는다 (ROLE_B §1.3 · §6.4)
        "live_segment_match": live_segment_match(age_rates, user_age_band),
        "crowd_fit": crowd_fit(congest, purpose),
    }
