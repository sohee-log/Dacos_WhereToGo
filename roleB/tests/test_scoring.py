"""스코어링 수식 테스트.

ROLE_B §6.4 재정규화가 이 프로젝트에서 가장 자주 틀리는 지점이다.
틀려도 에러가 나지 않고 **핫스팟 밖 POI가 조용히 순위에서 사라지는** 형태로
망가지기 때문에, 눈으로는 발견되지 않는다. 그래서 W1부터 테스트를 세워 둔다.
"""

from __future__ import annotations

import pytest

from app.constants import W, ZONE_BARRIER, ZONES, normalize_pair, zone_multiplier
from app.services.scoring import (
    distance_penalty,
    effective_distance_m,
    haversine_m,
    renormalized_score,
    total_score,
)

FULL_TERMS = {
    "segment_affinity": 0.8,
    "purpose_match": 0.8,
    "taste_similarity": 0.8,
    "context_fit": 0.8,
    "quality": 0.8,
    "live_segment_match": 0.8,
    "crowd_fit": 0.8,
}
PARTIAL_TERMS = {**FULL_TERMS, "live_segment_match": None, "crowd_fit": None}


# --- 재정규화 ---------------------------------------------------------------


def test_renormalize_when_hotspot_missing():
    """핫스팟 밖 POI와 안쪽 POI의 점수 스케일이 같은 범위여야 한다 (ROLE_B W2 B2-3)."""
    inside, _ = renormalized_score(FULL_TERMS)
    outside, avail = renormalized_score(PARTIAL_TERMS)

    assert 0 <= outside <= 1
    assert len(avail) == 5                       # live 두 항이 빠졌다
    assert abs(inside - outside) < 0.15          # 동일 조건이면 차이가 0.15 이내


def test_all_terms_equal_gives_that_value():
    """모든 항이 v면 재정규화 결과도 v다. 가중치 합으로 나누는지 확인."""
    for terms in (FULL_TERMS, PARTIAL_TERMS):
        score, _ = renormalized_score({k: (0.6 if v is not None else None)
                                       for k, v in terms.items()})
        assert score == pytest.approx(0.6, abs=1e-9)


def test_missing_live_terms_are_not_zero_filled():
    """None을 0으로 채우면 점수가 눈에 띄게 떨어진다. 그 실수를 잡는 테스트."""
    outside, _ = renormalized_score(PARTIAL_TERMS)
    zero_filled = sum(W[k] * (v or 0.0) for k, v in PARTIAL_TERMS.items())
    assert outside > zero_filled + 0.1


def test_partial_availability_only_counts_available_weights():
    score, avail = renormalized_score({"quality": 1.0})
    assert score == pytest.approx(1.0)
    assert avail == {"quality": 1.0}


def test_empty_terms_do_not_crash():
    assert renormalized_score({}) == (0.0, {})
    assert renormalized_score({"live_segment_match": None}) == (0.0, {})


# --- zone 배율 --------------------------------------------------------------


def test_zone_barrier_covers_all_pairs():
    """5×5 대칭 = 10개 조합. 하나라도 빠지면 런타임 KeyError로 터진다."""
    pairs = {normalize_pair(a, b) for a in ZONES for b in ZONES if a != b}
    assert len(pairs) == 10
    assert pairs == set(ZONE_BARRIER)


def test_zone_barrier_is_symmetric():
    for a in ZONES:
        for b in ZONES:
            assert zone_multiplier(a, b) == zone_multiplier(b, a)


def test_same_zone_and_unknown_zone_are_neutral():
    assert zone_multiplier("itaewon", "itaewon") == 1.0
    assert zone_multiplier(None, "itaewon") == 1.0
    assert zone_multiplier("itaewon", None) == 1.0


def test_cross_zone_distance_is_penalized():
    """직선 800m라도 철로 반대편이면 체감이 다르다."""
    same = effective_distance_m(800, "itaewon", "itaewon")
    across = effective_distance_m(800, "huam", "ichon")
    assert across > same * 2


def test_one_stop_pair_is_barely_penalized():
    """이촌↔용산역은 1정거장이라 배율이 거의 없다."""
    assert zone_multiplier("yongsan_stn", "ichon") < 1.2


# --- 거리 -------------------------------------------------------------------


def test_haversine_sanity():
    """이태원역 ↔ 용산역은 대략 2.5~3.5km다."""
    d = haversine_m(37.5345, 126.9946, 37.5299, 126.9648)
    assert 2000 < d < 3500


def test_distance_penalty_is_bounded_and_doubles_in_rain():
    dry = distance_penalty(600, "itaewon", "itaewon", rain_prob=0.0)
    wet = distance_penalty(600, "itaewon", "itaewon", rain_prob=0.8)
    assert 0 <= dry <= 1 and 0 <= wet <= 1
    assert wet == pytest.approx(min(dry * 2, 1.0))


def test_total_score_stays_in_range():
    score, avail, pen = total_score(PARTIAL_TERMS, 5000, "huam", "ichon", rain_prob=0.9)
    assert 0.0 <= score <= 1.0
    assert pen == pytest.approx(1.0)             # 멀고 비 오면 페널티가 상한
    assert "live_segment_match" not in avail
