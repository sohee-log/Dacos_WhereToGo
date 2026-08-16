"""스코어링 수식 테스트.

ROLE_B §6.4 재정규화가 이 프로젝트에서 가장 자주 틀리는 지점이다.
틀려도 에러가 나지 않고 **핫스팟 밖 POI가 조용히 순위에서 사라지는** 형태로
망가지기 때문에, 눈으로는 발견되지 않는다. 그래서 W1부터 테스트를 세워 둔다.
"""

from __future__ import annotations

import pytest

from app.constants import (
    NEUTRAL_TERM,
    W,
    ZONE_BARRIER,
    ZONES,
    hour_band,
    normalize_pair,
    segment_age_bands,
    zone_multiplier,
)
from app.services.scoring import (
    build_terms,
    context_fit,
    crowd_fit,
    distance_penalty,
    effective_distance_m,
    haversine_m,
    live_segment_match,
    purpose_match,
    quality_term,
    renormalized_score,
    segment_affinity_term,
    taste_similarity,
    total_score,
)

CLEAR = {"rain_prob": 0.0, "pm25_grade": 1, "feels_like": 20.0,
         "visit_hour": 14, "sunset_hour": 19}
RAINY = {**CLEAR, "rain_prob": 0.8}

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


# --- 개별 항 (B2-3) ---------------------------------------------------------


def test_purpose_match_ranks_primary_tag_highest():
    assert purpose_match(["데이트", "혼자"], "데이트") > purpose_match(["혼자", "데이트"], "데이트")
    assert purpose_match(["혼자", "데이트"], "데이트") > purpose_match(["회식"], "데이트")


def test_purpose_match_without_tags_is_neutral_not_zero():
    """속성 추출이 안 된 것과 '목적에 안 맞는 것'은 다르다."""
    assert purpose_match([], "데이트") == NEUTRAL_TERM
    assert purpose_match(None, "데이트") == NEUTRAL_TERM
    assert purpose_match(["회식"], "데이트") < NEUTRAL_TERM


def test_missing_inputs_fall_back_to_neutral():
    assert segment_affinity_term(None) == NEUTRAL_TERM
    assert quality_term(None) == NEUTRAL_TERM
    assert taste_similarity(None, [1.0, 0.0]) == NEUTRAL_TERM
    assert taste_similarity([0.0, 0.0], [1.0, 0.0]) == NEUTRAL_TERM   # 영벡터


def test_taste_similarity_is_cosine():
    assert taste_similarity([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)
    assert taste_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)
    assert taste_similarity([1.0, 0.0], [-1.0, 0.0]) == 0.0           # 음수는 0으로


# context_fit 자체의 비선형 테스트는 W3에 분리됐다 → tests/test_context_fit.py


# --- 실시간 항 — None 경로가 핵심 ---------------------------------------------


def test_live_terms_are_none_outside_hotspot():
    assert live_segment_match(None, 20) is None
    assert live_segment_match({"20": 30.0}, None) is None
    assert crowd_fit(None, "데이트") is None


def test_live_segment_match_accepts_percent_and_fraction():
    """citydata는 퍼센트(31.2), 픽스처는 비율(0.312)로 온다. 같은 값이어야 한다."""
    a = live_segment_match({"20": 31.2}, 20)
    b = live_segment_match({"20": 0.312}, 20)
    assert a == pytest.approx(b)
    assert 0.0 <= a <= 1.0


def test_live_segment_match_rewards_over_representation():
    below = live_segment_match({"20": 5.0}, 20)
    above = live_segment_match({"20": 40.0}, 20)
    assert above > below


def test_crowd_fit_flips_with_purpose():
    """조용함을 원하는 목적과 활기를 원하는 목적은 혼잡을 반대로 평가한다."""
    assert crowd_fit("붐빔", "데이트") < crowd_fit("여유", "데이트")
    assert crowd_fit("붐빔", "회식") > crowd_fit("여유", "회식")


def test_crowd_fit_unknown_level_is_neutral_not_crash():
    """고정 어휘 밖의 값이 와도 KeyError로 터지지 않는다."""
    assert crowd_fit("혼잡", "데이트") == pytest.approx(0.8)


# --- build_terms — 조립 -------------------------------------------------------

POI_OUTSIDE = {
    "purpose_tags": ["데이트", "혼자"],
    "outdoor_exposure": 0.1,
    "quality_score": 0.8,
}
INSIDE = {"congest_lvl": "여유", "age_rates": {"20": 34.0}, "user_age_band": 20}


def test_build_terms_drops_live_terms_outside_hotspot():
    terms = build_terms(POI_OUTSIDE, purpose="데이트", wx=CLEAR)
    assert terms["live_segment_match"] is None
    assert terms["crowd_fit"] is None
    assert all(terms[k] is not None for k in
               ("segment_affinity", "purpose_match", "taste_similarity",
                "context_fit", "quality"))


def test_build_terms_fills_live_terms_inside_hotspot():
    terms = build_terms(POI_OUTSIDE, purpose="데이트", wx=CLEAR, **INSIDE)
    assert terms["live_segment_match"] is not None
    assert terms["crowd_fit"] == pytest.approx(1.0)      # 데이트 × 여유


def test_hotspot_inside_and_outside_score_in_same_range():
    """ROLE_B W2 B2-3이 명시한 테스트를 실제 조립 경로로도 확인한다."""
    inside = build_terms(POI_OUTSIDE, purpose="데이트", wx=CLEAR, **INSIDE)
    outside = build_terms(POI_OUTSIDE, purpose="데이트", wx=CLEAR)

    s_in, _ = renormalized_score(inside)
    s_out, avail_out = renormalized_score(outside)

    assert 0 <= s_out <= 1
    assert len(avail_out) == 5
    assert abs(s_in - s_out) < 0.15


# --- segment_affinity 조회 축 --------------------------------------------------


def test_hour_band_folds_into_six_buckets():
    assert hour_band(0) == 0
    assert hour_band(19) == 4
    assert hour_band(23) == 5
    assert hour_band(99) == 5          # 범위를 벗어나도 터지지 않는다


def test_segment_age_bands_covers_both_five_year_buckets():
    """사용자는 '20대'로 답하지만 상권분석 원본은 20·25로 쪼개져 있다."""
    assert segment_age_bands(20) == (20, 25)
    assert segment_age_bands(None) == ()
