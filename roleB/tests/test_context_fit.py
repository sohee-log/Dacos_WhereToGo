"""날씨 비선형 로직 (B3-1) + 체감온도 근사.

이 테스트가 지키는 것은 **"선형으로 바뀌지 않았는가"** 다.
누군가 리팩터링하면서 `s -= 0.3 * rain_prob` 같은 식으로 바꿔도 점수는 그럴듯하게
나온다. 그러면 "비가 오면 후보 집합 자체가 바뀐다"는 차별점이 조용히 사라진다.
"""

from __future__ import annotations

import pytest

from app.constants import PLEASANT_RANGE
from app.services.context_fit import apparent_temperature, context_fit

CLEAR = {"rain_prob": 0.0, "pm25_grade": 1, "feels_like": 20.0,
         "visit_hour": 14, "sunset_hour": 19}
RAINY = {**CLEAR, "rain_prob": 0.8}


# --- 야외 노출도에만 곱해진다 --------------------------------------------------


def test_indoor_is_immune_to_weather():
    """실내(노출 0)는 어떤 날씨에도 값이 변하지 않는다. 이게 곱셈 구조의 핵심이다."""
    for wx in (CLEAR, RAINY,
               {**CLEAR, "pm25_grade": 4},
               {**CLEAR, "feels_like": 38.0},
               {**CLEAR, "visit_hour": 23}):
        assert context_fit(0.0, wx) == pytest.approx(1.0)


def test_rain_penalizes_outdoor_proportionally_to_exposure():
    half = context_fit(0.5, RAINY)
    full = context_fit(1.0, RAINY)
    assert full < half < context_fit(0.0, RAINY)


# --- U자형 · 임계값 ------------------------------------------------------------


def test_pleasant_weather_gives_outdoor_a_bonus():
    """감점만 있으면 U자형이 아니다. 쾌적 구간에서는 야외가 1.0을 넘어야 한다."""
    mid = sum(PLEASANT_RANGE) / 2
    assert context_fit(1.0, {**CLEAR, "feels_like": mid}) > 1.0


def test_temperature_response_is_u_shaped():
    """양 끝(폭염·한파)이 가운데(쾌적)보다 낮아야 한다."""
    hot = context_fit(1.0, {**CLEAR, "feels_like": 35.0})
    mild = context_fit(1.0, {**CLEAR, "feels_like": 20.0})
    cold = context_fit(1.0, {**CLEAR, "feels_like": -10.0})
    assert hot < mild and cold < mild


def test_pm_is_a_threshold_not_a_slope():
    """등급 2→3에서 꺾이고, 3→4 사이에서는 같은 계수가 걸린다."""
    g2 = context_fit(1.0, {**CLEAR, "pm25_grade": 2})
    g3 = context_fit(1.0, {**CLEAR, "pm25_grade": 3})
    g4 = context_fit(1.0, {**CLEAR, "pm25_grade": 4})
    assert g3 < g2
    assert g4 == pytest.approx(g3)


def test_heat_threshold_is_at_31_degrees():
    below = context_fit(1.0, {**CLEAR, "feels_like": 30.9})
    above = context_fit(1.0, {**CLEAR, "feels_like": 31.1})
    assert above < below


def test_after_sunset_outdoor_is_penalized():
    day = context_fit(1.0, {**CLEAR, "visit_hour": 18})
    night = context_fit(1.0, {**CLEAR, "visit_hour": 20})
    assert night < day


# --- 개인화 훅 (B3-4) ----------------------------------------------------------


def test_weather_sensitivity_scales_rain_penalty():
    """온보딩 5번 문항이 실제로 점수를 바꿔야 한다. 안 바뀌면 개인화 항 하나가 죽는다."""
    low = context_fit(1.0, RAINY, weather_sensitivity=1)
    mid = context_fit(1.0, RAINY, weather_sensitivity=2)
    high = context_fit(1.0, RAINY, weather_sensitivity=3)
    assert high < mid < low


def test_sensitivity_does_not_matter_without_rain():
    """비가 안 오면 민감도는 아무것도 바꾸지 않는다."""
    assert context_fit(1.0, CLEAR, 1) == pytest.approx(context_fit(1.0, CLEAR, 3))


def test_unknown_sensitivity_falls_back_to_default():
    assert context_fit(1.0, RAINY, weather_sensitivity=99) == pytest.approx(
        context_fit(1.0, RAINY, weather_sensitivity=2)
    )


# --- 방어 ---------------------------------------------------------------------


def test_bounded_even_in_extremes():
    extreme = {"rain_prob": 1.0, "pm25_grade": 4, "feels_like": 45.0,
               "visit_hour": 23, "sunset_hour": 19}
    assert 0.0 <= context_fit(1.0, extreme) <= 1.5


def test_missing_keys_do_not_crash():
    """날씨를 모른다고 추천이 멈추면 안 된다.

    빠진 키는 '쾌적한 낮'(20도·맑음·일몰 전)으로 본다. 야외에 보너스가 붙는
    구간이라 값이 1.0이 아니라 1.2다 — 실내는 1.0 그대로다.
    """
    assert context_fit(0.5, {}) == pytest.approx(1.2)
    assert context_fit(0.0, {}) == pytest.approx(1.0)
    assert context_fit(0.5, {"rain_prob": None, "pm25_grade": None}) == pytest.approx(1.2)


# --- 체감온도 근사 -------------------------------------------------------------


def test_apparent_temperature_is_identity_in_mild_range():
    assert apparent_temperature(20.0, 50.0, 2.0) == pytest.approx(20.0)


def test_humid_heat_feels_hotter():
    """단기예보는 체감온도를 주지 않는다. 습도를 무시하면 폭염 임계를 못 넘는다."""
    dry = apparent_temperature(31.0, 30.0)
    humid = apparent_temperature(31.0, 85.0)
    assert humid > dry >= 31.0 - 2.0


def test_wind_makes_cold_feel_colder():
    calm = apparent_temperature(0.0, None, 0.5)
    windy = apparent_temperature(0.0, None, 8.0)
    assert windy < calm


def test_missing_humidity_or_wind_returns_temperature():
    assert apparent_temperature(33.0) == pytest.approx(33.0)
    assert apparent_temperature(-3.0) == pytest.approx(-3.0)
