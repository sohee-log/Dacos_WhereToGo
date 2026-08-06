"""② 스코어링 — W1 골격.

W1에서는 **수식만** 넣는다. 각 항의 실제 계산(segment_affinity 조회, taste 코사인 등)은
W2(B2-3)에서 DB를 붙이며 채운다. 여기 미리 넣어 두는 이유는 하나다.

    ROLE_B §6.4 재정규화는 이 프로젝트에서 가장 자주 틀리는 지점이고,
    틀리면 핫스팟 밖 POI가 조용히 전멸한다. 목 API 단계부터 같은 함수를 쓰면
    W2에 로직을 갈아끼울 때 이미 테스트가 서 있다.

거리와 haversine도 여기 둔다. 후보 생성(retrieval.py)은 SQL에서 ST_Distance로
직선거리를 받지만, **점수에 들어가는 거리는 zone 배율이 곱해진 값**이어야 한다.
"""

from __future__ import annotations

import math

from app.constants import (
    DISTANCE_NORM_M,
    OPTIONAL_TERMS,
    PENALTY,
    RAIN_DISTANCE_MULTIPLIER,
    RAIN_PROB_HEAVY,
    W,
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
