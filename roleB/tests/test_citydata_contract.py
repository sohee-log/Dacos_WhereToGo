"""A가 실제로 적재하는 형태로 읽히는가 (B3-2 계약 테스트).

**이 파일이 왜 따로 있는가.** `test_live_signals.py`는 B가 *가정한* 형태로
픽스처를 만들어 검증한다. 그래서 A의 `poll_citydata.py`가 `fcst`를 배열이
아니라 `{"population": [...], "weather": [...]}` 객체로 넣기 시작했을 때
**테스트는 전부 통과하면서 "19시 붐빔 예상" 배너만 조용히 사라졌다.**
가정을 가정으로 검증하면 이런 건 안 잡힌다.

그래서 픽스처를 실제 응답에서 뜬다. `tests/fixtures/citydata_hotspot_latest.json`은
서울시 실시간 도시데이터 sample 응답(V8.5)을 A의 `build_snapshot()` 규칙대로
`hotspot_latest` 한 행으로 변환한 것이다. 지점이 용산이 아니라 광화문인 것은
상관없다 — 여기서 검증하는 것은 **컬럼에 담기는 형태**지 값이 아니다.

필드가 늘거나 이름이 바뀌면 여기가 먼저 깨져야 한다.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from app.config import Settings
from app.constants import CONGEST_LEVELS
from app.services.live_signals import (
    age_mix_top,
    build_signals,
    fcst_items,
    forecast_congest_at,
    forecast_weather_at,
)
from app.services.pipeline import _resolve_weather
from app.timeutil import KST

FIXTURE = Path(__file__).parent / "fixtures" / "citydata_hotspot_latest.json"


def _shift(text: str, fmt: str, delta: timedelta) -> str:
    return (datetime.strptime(text, fmt) + delta).strftime(fmt)


@pytest.fixture
def row() -> dict:
    """A가 `hotspot_snapshot`에 넣는 한 행. **시각을 지금으로 옮긴다.**

    픽스처는 2026-08-23 18:00에 뜬 실제 응답이다. 그대로 쓰면
    `kma.should_use_forecast()`가 **실제 벽시계**와 비교하므로, 테스트가 도는
    시각에 따라 결과가 갈린다. 실제로 CI에서 한 번 깨졌다 — 로컬은 18:5x라
    통과했고 CI는 19:02라 방문까지 2시간 58분이 되어 예보 구간(3시간) 밖이었다.
    **날짜가 박힌 픽스처와 `now()`를 보는 코드를 같이 쓰면 언젠가 깨진다.**

    그래서 `observed_at`을 정시로 자른 현재 시각에 맞추고 예측 슬롯을 같은
    폭만큼 민다. 형태와 값은 그대로고 시각만 상대적으로 바뀐다.
    """
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    observed = datetime.strptime(data["observed_at"], "%Y-%m-%d %H:%M").replace(tzinfo=KST)
    delta = datetime.now(KST).replace(minute=0, second=0, microsecond=0) - observed

    data["observed_at"] = observed + delta
    data["fcst"] = {
        "population": [
            {**s, "FCST_TIME": _shift(s["FCST_TIME"], "%Y-%m-%d %H:%M", delta)}
            for s in data["fcst"]["population"]
        ],
        "weather": [
            {**s, "FCST_DT": _shift(s["FCST_DT"], "%Y%m%d%H%M", delta)}
            for s in data["fcst"]["weather"]
        ],
    }
    return data


@pytest.fixture
def visit(row) -> datetime:
    """관측 1시간 뒤 = 첫 예측 슬롯. 예보 경로가 실제로 도는 시각이다."""
    return row["observed_at"] + timedelta(hours=1)


# ---------------------------------------------------------------------------
# fcst — 이번에 실제로 깨졌던 곳
# ---------------------------------------------------------------------------


def test_fcst_is_an_object_not_an_array(row):
    """A는 인구예측과 날씨예측을 한 컬럼에 함께 담는다. 그게 지금의 계약이다."""
    assert isinstance(row["fcst"], dict)
    assert set(row["fcst"]) == {"population", "weather"}


def test_forecast_reads_the_object_shape(row, visit):
    """🔴 회귀 방지. 배열만 받으면 여기서 None이 나오고 배너 한 줄이 사라진다."""
    level = forecast_congest_at(row["fcst"], visit)
    assert level in CONGEST_LEVELS


def test_forecast_still_reads_the_bare_array(row, visit):
    """개발용 `tools/load_seed_db.py`는 아직 배열로 넣는다. 둘 다 받아야 한다."""
    assert forecast_congest_at(row["fcst"]["population"], visit) == forecast_congest_at(
        row["fcst"], visit
    )


def test_fcst_items_never_raises_on_junk():
    """모르는 형태가 와도 추천이 멈추지는 않는다."""
    for junk in (None, {}, [], "문자열", {"population": "문자열"}, {"population": None}, 3):
        assert fcst_items(junk, "population") == []


def test_population_slots_are_hourly_and_cover_the_evening(row):
    """FCST_PPLTN은 12슬롯이다. 문서에 '2시간 간격'이라 적혀 있었지만 실측은 1시간이다."""
    slots = fcst_items(row["fcst"], "population")
    assert len(slots) == 12
    assert all("FCST_TIME" in s and "FCST_CONGEST_LVL" in s for s in slots)


def test_forecast_vocabulary_stays_inside_the_fixed_four(row):
    """어휘가 하나라도 새면 `_valid_level`이 조용히 버린다 — 여기서 잡는다."""
    for slot in fcst_items(row["fcst"], "population"):
        assert slot["FCST_CONGEST_LVL"] in CONGEST_LEVELS


# ---------------------------------------------------------------------------
# WEATHER_STTS 실황
# ---------------------------------------------------------------------------


def test_live_weather_has_no_sensible_temp(row):
    """실측 응답에 `SENSIBLE_TEMP`는 **없다.** 습도·풍속으로 체감을 만들어야 한다."""
    assert "SENSIBLE_TEMP" not in row["weather"]
    assert {"TEMP", "HUMIDITY", "WIND_SPD"} <= set(row["weather"])


def test_feels_like_is_warmer_than_the_thermometer(row, visit):
    """31.3°C · 습도 62% 를 기온 그대로 쓰면 폭염 임계(31°)를 아슬하게 못 넘는다."""
    sig = build_signals(row, visit, now=row["observed_at"])
    assert sig.weather is not None
    assert sig.weather["feels_like"] > float(row["weather"]["TEMP"])


def test_air_quality_and_sunset_come_from_live(row, visit):
    sig = build_signals(row, visit, now=row["observed_at"])
    assert sig.weather["pm25_grade"] == 1          # PM25 "9"
    assert sig.weather["sunset"] == row["weather"]["SUNSET"]
    assert sig.weather["rain_prob"] == 0.0         # PRECPT_TYPE "없음"


def test_live_rain_is_a_fact(row, visit):
    row["weather"] = {**row["weather"], "PRECPT_TYPE": "비", "PRECIPITATION": "1.5mm"}
    sig = build_signals(row, visit, now=row["observed_at"])
    assert sig.weather["rain_prob"] == 1.0
    assert sig.weather["label"] == "비"


# ---------------------------------------------------------------------------
# FCST24HOURS — 기상청 키 없이 쓰는 예보
# ---------------------------------------------------------------------------


def test_weather_forecast_slot_is_read(row, visit):
    wx = forecast_weather_at(row["fcst"], visit)
    assert wx is not None
    assert wx["temp"] == 29.0
    assert wx["rain_prob"] == 0.0            # RAIN_CHANCE "0"
    assert wx["pm25_grade"] is None          # 예보에 대기질이 없다


def test_weather_forecast_rain_is_a_probability(row, visit):
    slots = [dict(s) for s in fcst_items(row["fcst"], "weather")]
    slots[0] = {**slots[0], "RAIN_CHANCE": "70", "PRECPT_TYPE": "비", "SKY_STTS": "흐림"}
    wx = forecast_weather_at({"population": [], "weather": slots}, visit)
    assert wx["rain_prob"] == pytest.approx(0.7)
    assert wx["label"] == "비"


def test_weather_forecast_outside_range_is_none(row, visit):
    """24시간 예보라도 슬롯 밖이면 지어내지 않는다."""
    assert forecast_weather_at(row["fcst"], visit + timedelta(hours=20)) is None


def test_resolve_weather_uses_citydata_forecast_without_a_kma_key(row):
    """🟠 `KMA_SERVICE_KEY`가 아직 없다. 그래도 '저녁에 갈 건데'가 예보로 답해야 한다."""
    # `observed_at`은 정시로 잘린 현재 시각이다. +5h면 실제 now 기준으로도
    # 최소 4시간 1분 뒤라 예보 구간(3시간)에 확실히 들어간다.
    visit = row["observed_at"] + timedelta(hours=5)
    sig = build_signals(row, visit, now=row["observed_at"])
    wx, source = _resolve_weather(
        Settings(kma_service_key=None), 37.5340, 126.9946, visit, sig
    )
    assert source == "citydata_fcst"
    assert wx["pm25_grade"] == 1                        # 대기질은 실황에서 채운다
    assert wx["sunset"] == row["weather"]["SUNSET"]


def test_resolve_weather_falls_back_to_live_without_any_forecast(row):
    """예보 슬롯이 비면 실황이다. 그게 마지막 수단이라는 것만 출처로 드러난다."""
    row["fcst"] = {"population": [], "weather": []}
    visit = row["observed_at"] + timedelta(hours=5)      # 예보 구간인데도 슬롯이 없다
    sig = build_signals(row, visit, now=row["observed_at"])
    _, source = _resolve_weather(
        Settings(kma_service_key=None), 37.5340, 126.9946, visit, sig
    )
    assert source == "citydata"


# ---------------------------------------------------------------------------
# 연령 구성
# ---------------------------------------------------------------------------


def test_age_rates_span_zero_to_seventy(row):
    """citydata는 0~9세와 70세 이상까지 준다. `BASELINE_AGE_RATE`는 10~60뿐이다."""
    assert set(row["age_rates"]) == {"0", "10", "20", "30", "40", "50", "60", "70"}


def test_age_banner_never_says_zero_dae(row):
    top = age_mix_top(row["age_rates"])
    assert top and not top.startswith("0대")
    assert age_mix_top({"0": 90.0}) == "10대 미만 90%"
    assert age_mix_top({"70": 90.0}) == "70대 이상 90%"


def test_scoring_age_bands_are_all_present(row):
    """`live_segment_match`는 `age_rates[str(age_band)]`로 찾는다. 10~60이 다 있어야 한다."""
    for band in (10, 20, 30, 40, 50, 60):
        assert row["age_rates"][str(band)] is not None


# ---------------------------------------------------------------------------
# 스냅샷 전체
# ---------------------------------------------------------------------------


def test_snapshot_columns_match_the_view(row):
    """`hotspot_latest`가 내보내는 컬럼. 늘거나 줄면 여기서 먼저 깨진다."""
    assert set(row) == {
        "hotspot_code", "hotspot_name", "observed_at", "congest_lvl",
        "ppltn_min", "ppltn_max", "age_rates", "male_rate", "female_rate",
        "weather", "fcst",
    }


def test_build_signals_reads_every_line_of_the_banner(row, visit):
    sig = build_signals(row, visit, now=row["observed_at"])
    assert sig is not None
    assert sig.code == row["hotspot_code"]
    assert sig.congest_now in CONGEST_LEVELS
    assert sig.congest_at_visit in CONGEST_LEVELS      # 🔴 여기가 이번에 죽어 있었다
    assert sig.congest_for_scoring == sig.congest_at_visit
    assert sig.weather is not None
    assert sig.weather_at_visit is not None
    assert sig.is_stale is False


# ---------------------------------------------------------------------------
# 하늘 상태 — 실황에 없는 필드를 예보에서 빌려 온다
# ---------------------------------------------------------------------------


def test_live_weather_has_no_sky_status(row):
    """`SKY_STTS`는 `FCST24HOURS` 안에만 있다. 실황에는 없다 — 실측이다."""
    assert "SKY_STTS" not in row["weather"]


def test_banner_does_not_claim_clear_sky_on_a_cloudy_day(row, visit):
    """비가 안 오면 무조건 '맑음'이었다. 흐린 날에도 그랬다."""
    slots = [{**s, "SKY_STTS": "흐림"} for s in fcst_items(row["fcst"], "weather")]
    row["fcst"] = {"population": row["fcst"]["population"], "weather": slots}

    sig = build_signals(row, visit, now=row["observed_at"])
    assert sig.weather["label"] == "흐림"


def test_rain_wins_over_the_forecast_sky(row, visit):
    """실황에서 비가 오는 중이면 예보의 하늘 상태로 덮지 않는다."""
    row["weather"] = {**row["weather"], "PRECPT_TYPE": "비"}
    row["fcst"] = {
        "population": row["fcst"]["population"],
        "weather": [{**s, "SKY_STTS": "맑음"} for s in fcst_items(row["fcst"], "weather")],
    }
    sig = build_signals(row, visit, now=row["observed_at"])
    assert sig.weather["label"] == "비"


def test_sky_stays_clear_when_the_forecast_says_so(row, visit):
    sig = build_signals(row, visit, now=row["observed_at"])
    assert sig.weather["label"] == "맑음"      # 픽스처의 예보 슬롯이 전부 맑음이다


# ---------------------------------------------------------------------------
# 신선도 — 임계값이 실제 폴링 간격과 맞는가
# ---------------------------------------------------------------------------


def test_stale_threshold_tolerates_the_real_polling_cadence(row):
    """`*/15` cron이지만 실측 평균은 40분, 최대 115분이다 (2026-08-23 · 704 간격).

    40분으로 두면 정상 가동 중 31%가 stale로 찍힌다 — 경보가 잡음이 된다.
    """
    from app.services.live_signals import SNAPSHOT_STALE_AFTER

    assert SNAPSHOT_STALE_AFTER > timedelta(minutes=60)

    normal = build_signals(
        row, row["observed_at"], now=row["observed_at"] + timedelta(minutes=55)
    )
    broken = build_signals(
        row, row["observed_at"], now=row["observed_at"] + timedelta(minutes=150)
    )
    assert normal.is_stale is False
    assert broken.is_stale is True
