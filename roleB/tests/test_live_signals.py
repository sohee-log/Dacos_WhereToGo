"""실시간 도시데이터 해석 (B3-2).

citydata는 **전부 문자열**로 온다. `"27.4"`, `"-"`, `""`, `"1.5mm"` 가 같은 필드에
섞여 오고, 지점에 따라 아예 빠지기도 한다. 여기서 한 번 터지면 추천 전체가 500이 된다.

그리고 없을 때는 **None이어야 한다.** 혼잡도를 모르는 지점에 "보통"을 채워 넣으면
그 값이 점수에 들어가 버린다.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app.services.live_signals import (
    SNAPSHOT_STALE_AFTER,
    age_mix_top,
    as_float,
    build_signal_map,
    build_signals,
    forecast_congest_at,
    parse_citydata_weather,
    pm_grade,
    sunset_hour,
)
from app.timeutil import KST

VISIT = datetime(2026, 8, 3, 19, 0, tzinfo=KST)


# --- 값 파싱 ------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw, expected",
    [("27.4", 27.4), (27.4, 27.4), ("1.5mm", 1.5), ("-3", -3.0),
     ("-", None), ("", None), (None, None), ("정보없음", None)],
)
def test_as_float_survives_citydata_junk(raw, expected):
    assert as_float(raw) == expected


@pytest.mark.parametrize(
    "value, grade",
    [("5", 1), ("15", 1), ("16", 2), ("35", 2), ("36", 3), ("75", 3), ("120", 4)],
)
def test_pm25_grades_follow_korean_bounds(value, grade):
    """사용자가 뉴스에서 보는 등급과 같아야 '미세먼지 나쁨이라 실내로'가 납득된다."""
    assert pm_grade(value) == grade


def test_pm_grade_missing_is_none_not_two():
    """모르는 것을 '보통'으로 채우면 그 값이 점수에 들어간다."""
    assert pm_grade("-") is None
    assert pm_grade(None) is None


def test_sunset_hour_parsing():
    assert sunset_hour("19:42") == 19
    assert sunset_hour("7:05") == 7
    assert sunset_hour("깨진값") == 19
    assert sunset_hour(None) == 19


# --- WEATHER_STTS -------------------------------------------------------------


def test_parse_citydata_weather_prefers_sensible_temp():
    wx = parse_citydata_weather(
        {"TEMP": "30.0", "SENSIBLE_TEMP": "33.8", "PRECPT_TYPE": "없음",
         "PM25": "12", "SUNSET": "19:42"}
    )
    assert wx["feels_like"] == 33.8
    assert wx["pm25_grade"] == 1
    assert wx["sunset_hour"] == 19
    assert wx["sunset"] == "19:42"      # 배너에는 분까지 보여준다
    assert wx["rain_prob"] == 0.0


def test_citydata_rain_is_fact_not_probability():
    """실황은 확률이 아니다. 확률이 필요한 건 3시간 뒤 방문이고 그건 기상청 몫이다."""
    wx = parse_citydata_weather({"TEMP": "24", "PRECPT_TYPE": "비"})
    assert wx["rain_prob"] == 1.0


def test_parse_falls_back_from_pm25_to_pm10_to_air_idx():
    only_pm10 = parse_citydata_weather({"TEMP": "20", "PM25": "-", "PM10": "100"})
    assert only_pm10["pm25_grade"] == 3

    only_text = parse_citydata_weather({"TEMP": "20", "PM25": "-", "AIR_IDX": "매우나쁨"})
    assert only_text["pm25_grade"] == 4


def test_parse_returns_none_without_temperature():
    """기온이 없으면 날씨라고 부를 수 없다. 억지로 만들지 않는다."""
    assert parse_citydata_weather({"PRECPT_TYPE": "비"}) is None
    assert parse_citydata_weather(None) is None


def test_parse_accepts_lowercase_keys():
    """A가 스냅샷을 소문자로 정규화해 넣어도 읽혀야 한다."""
    assert parse_citydata_weather({"temp": "21.0"})["feels_like"] == 21.0


# --- FCST_PPLTN — 방문 시각 예측 ------------------------------------------------


FCST = [
    {"FCST_TIME": "2026-08-03 17:00", "FCST_CONGEST_LVL": "보통"},
    {"FCST_TIME": "2026-08-03 19:00", "FCST_CONGEST_LVL": "붐빔"},
    {"FCST_TIME": "2026-08-03 21:00", "FCST_CONGEST_LVL": "약간 붐빔"},
]


def test_forecast_picks_the_visit_slot():
    assert forecast_congest_at(FCST, VISIT) == "붐빔"


def test_forecast_picks_nearest_within_tolerance():
    assert forecast_congest_at(FCST, VISIT + timedelta(minutes=45)) == "붐빔"
    assert forecast_congest_at(FCST, VISIT + timedelta(hours=1, minutes=30)) == "약간 붐빔"


def test_forecast_outside_range_is_none():
    """예측 구간 밖인데 가까운 값을 끌어다 쓰면 틀린 근거가 화면에 뜬다."""
    assert forecast_congest_at(FCST, VISIT + timedelta(hours=8)) is None


def test_forecast_ignores_broken_entries():
    broken = [{"FCST_TIME": "깨짐", "FCST_CONGEST_LVL": "붐빔"},
              {"FCST_CONGEST_LVL": "여유"},
              {"FCST_TIME": "2026-08-03 19:00", "FCST_CONGEST_LVL": "혼잡"}]  # 어휘 밖
    assert forecast_congest_at(broken, VISIT) is None
    assert forecast_congest_at(None, VISIT) is None


# --- 스냅샷 묶음 ---------------------------------------------------------------


def _snapshot(**over):
    base = {
        "hotspot_code": "POI_ITW",
        "hotspot_name": "이태원 관광특구",
        "observed_at": VISIT - timedelta(minutes=5),
        "congest_lvl": "보통",
        "age_rates": {"20": 34.0, "30": 21.0},
        "weather": {"TEMP": "28", "SENSIBLE_TEMP": "30.2", "PRECPT_TYPE": "없음", "PM25": "20"},
        "fcst": FCST,
    }
    return {**base, **over}


def test_build_signals_prefers_forecast_over_now():
    """사람은 지금이 아니라 도착할 때를 기준으로 결정한다."""
    sig = build_signals(_snapshot(), VISIT, now=VISIT)
    assert sig.congest_now == "보통"
    assert sig.congest_at_visit == "붐빔"
    assert sig.congest_for_scoring == "붐빔"


def test_scoring_falls_back_to_now_without_forecast():
    sig = build_signals(_snapshot(fcst=None), VISIT, now=VISIT)
    assert sig.congest_at_visit is None
    assert sig.congest_for_scoring == "보통"


def test_stale_snapshot_is_flagged():
    """A의 15분 폴링이 죽으면 여기서 보인다."""
    fresh = build_signals(_snapshot(), VISIT, now=VISIT)
    old = build_signals(
        _snapshot(observed_at=VISIT - SNAPSHOT_STALE_AFTER - timedelta(minutes=5)),
        VISIT,
        now=VISIT,
    )
    assert fresh.is_stale is False
    assert old.is_stale is True


def test_build_signals_without_code_is_none():
    assert build_signals({}, VISIT) is None
    assert build_signals(None, VISIT) is None


def test_signal_map_is_keyed_by_code():
    got = build_signal_map({"POI_ITW": _snapshot()}, VISIT)
    assert set(got) == {"POI_ITW"}
    assert got["POI_ITW"].name == "이태원 관광특구"


def test_signal_map_drops_unusable_rows():
    got = build_signal_map({"BAD": {"hotspot_code": None}}, VISIT)
    assert got == {}


# --- 연령 구성 ------------------------------------------------------------------


def test_age_mix_top_handles_percent_and_fraction():
    assert age_mix_top({"20": 34.0, "30": 21.0}) == "20대 34%"
    assert age_mix_top({"20": 0.34, "30": 0.21}) == "20대 34%"


def test_age_mix_top_without_data_is_none():
    """값이 없으면 문구를 지어내지 않는다."""
    assert age_mix_top(None) is None
    assert age_mix_top({}) is None
    assert age_mix_top({"20": "-"}) is None
