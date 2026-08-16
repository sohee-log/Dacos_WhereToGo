"""기상청 단기예보 (B3-3).

**실 API 키 없이 검증할 수 있는 것까지만 본다.** 격자 변환, 발표 회차 계산,
응답 파싱, 실패 처리는 전부 순수 함수라 키 없이 확인된다. 실제 호출은
`KMA_SERVICE_KEY`가 생긴 뒤 `--run-kma`로 따로 돌린다 (맨 아래).

공공데이터포털에서 가장 자주 터지는 두 가지를 특히 본다.
  1. 키 이중 인코딩 — `%2F`가 `%252F`가 되어 인증이 깨진다
  2. **에러도 HTTP 200으로 온다** — resultCode를 안 보면 "예보가 비었다"로 오해한다
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta

import pytest

from app.services.kma import (
    _service_key_param,
    base_datetime,
    extract_items,
    fetch_forecast,
    latlng_to_grid,
    parse_forecast,
    should_use_forecast,
)
from app.timeutil import KST

TARGET = datetime(2026, 8, 3, 19, 0, tzinfo=KST)


# --- 격자 변환 ----------------------------------------------------------------


def test_seoul_city_hall_maps_to_known_grid():
    """기상청 문서의 기준점. 이게 틀리면 다른 동네 날씨를 가져온다."""
    assert latlng_to_grid(37.5665, 126.9780) == (60, 127)


def test_yongsan_is_in_the_seoul_neighborhood():
    nx, ny = latlng_to_grid(37.5340, 126.9946)      # 이태원
    assert 58 <= nx <= 62 and 124 <= ny <= 128


def test_grid_is_stable_within_a_cell():
    """5km 격자다. 용산 안에서 몇백 미터 움직여도 같은 칸이어야 캐시가 산다."""
    assert latlng_to_grid(37.5340, 126.9946) == latlng_to_grid(37.5352, 126.9930)


# --- 발표 회차 ----------------------------------------------------------------


@pytest.mark.parametrize(
    "now, expected",
    [
        (datetime(2026, 8, 3, 14, 30, tzinfo=KST), ("20260803", "1400")),
        (datetime(2026, 8, 3, 16, 59, tzinfo=KST), ("20260803", "1400")),
        (datetime(2026, 8, 3, 17, 20, tzinfo=KST), ("20260803", "1700")),
    ],
)
def test_base_datetime_picks_latest_published_slot(now, expected):
    assert base_datetime(now) == expected


def test_base_time_waits_for_publish_delay():
    """정시에 바로 부르면 빈 응답이 온다. 02:00 발표는 02:10쯤부터 조회된다."""
    assert base_datetime(datetime(2026, 8, 3, 17, 5, tzinfo=KST)) == ("20260803", "1400")


def test_before_dawn_uses_previous_day_2300():
    assert base_datetime(datetime(2026, 8, 3, 1, 0, tzinfo=KST)) == ("20260802", "2300")


# --- 예보 사용 조건 -------------------------------------------------------------


def test_forecast_used_only_for_distant_visits():
    """2시간 이내면 실황이 더 정확하다 (PLAN §3.3.3)."""
    now = TARGET - timedelta(hours=1)
    assert should_use_forecast(TARGET, now) is False
    assert should_use_forecast(TARGET, TARGET - timedelta(hours=5)) is True


# --- 응답 파싱 ----------------------------------------------------------------


def _items(**over):
    base = {"POP": "60", "PTY": "1", "SKY": "4", "TMP": "27", "REH": "80", "WSD": "2.0"}
    base.update(over)
    return [
        {"category": k, "fcstValue": v, "fcstDate": "20260803", "fcstTime": "1900"}
        for k, v in base.items()
    ]


def test_parse_forecast_reads_the_visit_slot():
    wx = parse_forecast(_items(), TARGET)
    assert wx["rain_prob"] == pytest.approx(0.6)
    assert wx["precpt_type"] == "비"
    assert wx["temp"] == 27.0
    assert wx["feels_like"] >= 27.0          # 습도 80%면 체감이 더 높다


def test_forecast_rain_is_a_probability():
    """실황(0/1)과 달리 예보는 확률이다. context_fit의 비 계수가 여기서 의미를 갖는다."""
    assert parse_forecast(_items(POP="30"), TARGET)["rain_prob"] == pytest.approx(0.3)
    assert parse_forecast(_items(POP="0", PTY="0"), TARGET)["rain_prob"] == 0.0


def test_parse_picks_nearest_slot_when_exact_missing():
    items = [
        {"category": "TMP", "fcstValue": "20", "fcstDate": "20260803", "fcstTime": "1500"},
        {"category": "TMP", "fcstValue": "26", "fcstDate": "20260803", "fcstTime": "2000"},
    ]
    assert parse_forecast(items, TARGET)["temp"] == 26.0


def test_parse_without_temperature_is_none():
    items = [{"category": "POP", "fcstValue": "60", "fcstDate": "20260803", "fcstTime": "1900"}]
    assert parse_forecast(items, TARGET) is None
    assert parse_forecast([], TARGET) is None


def test_forecast_has_no_air_quality_or_sunset():
    """단기예보에 대기질·일몰이 없다. 호출부가 citydata에서 채워야 한다."""
    wx = parse_forecast(_items(), TARGET)
    assert wx["pm25_grade"] is None
    assert wx["sunset_hour"] is None


# --- 실패 처리 ----------------------------------------------------------------


def test_extract_items_rejects_error_envelope():
    """포털은 에러도 HTTP 200으로 준다. resultCode를 안 보면 조용히 틀린다."""
    payload = {"response": {"header": {"resultCode": "30", "resultMsg": "SERVICE KEY IS NOT REGISTERED"}}}
    assert extract_items(payload) is None


def test_extract_items_accepts_success_envelope():
    payload = {
        "response": {
            "header": {"resultCode": "00", "resultMsg": "NORMAL_SERVICE"},
            "body": {"items": {"item": [{"category": "TMP"}]}},
        }
    }
    assert extract_items(payload) == [{"category": "TMP"}]


def test_extract_items_survives_garbage():
    for payload in (None, "<xml/>", {}, {"response": {}}):
        assert extract_items(payload) is None


def test_service_key_is_not_double_encoded():
    encoded = "abc%2Fdef%3D%3D"
    assert _service_key_param(encoded) == encoded          # 이미 인코딩된 키는 그대로
    assert _service_key_param("abc/def==") == "abc%2Fdef%3D%3D"


def test_no_key_returns_none_without_calling():
    """키가 없다고 추천이 멈추면 안 된다. 조용히 실황으로 물러선다."""
    assert fetch_forecast(None, 37.534, 126.9946, TARGET) is None
    assert fetch_forecast("", 37.534, 126.9946, TARGET) is None


# --- 실 API (키가 있을 때만) -----------------------------------------------------


@pytest.mark.skipif(
    not os.environ.get("KMA_SERVICE_KEY"),
    reason="KMA_SERVICE_KEY가 없다 — 파싱까지만 검증한다",
)
def test_real_api_returns_forecast():
    from app.timeutil import KST as _KST

    now = datetime.now(_KST)
    wx = fetch_forecast(
        os.environ["KMA_SERVICE_KEY"], 37.5340, 126.9946, now + timedelta(hours=4)
    )
    assert wx is not None, "응답이 없다 — 키 승인 상태와 이중 인코딩을 확인할 것"
    assert 0.0 <= wx["rain_prob"] <= 1.0
    assert -30.0 < wx["feels_like"] < 50.0
