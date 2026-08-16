"""시나리오 · 페이싱 · 퍼센타일 (B6-2 / B6-4의 순수 부분).

측정 도구의 버그는 **틀린 숫자를 그럴듯하게** 내놓는다. 그래서 네트워크가
없는 부분만이라도 테스트를 세워 둔다. 실제로 한 번 당했다 — 레이트 리밋에
걸린 429 응답 시간을 재고 p50이 1ms라고 좋아했다.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app.constants import PURPOSE_TAGS, ZONES
from tools import scenarios as sc

NOW = datetime(2026, 8, 10, 15, 0, tzinfo=sc.KST)   # 2026-08-10 은 월요일


# --- 시나리오 파일 --------------------------------------------------------------


@pytest.fixture(scope="module")
def rows():
    return sc.load()


def test_twenty_scenarios(rows):
    assert len(rows) == 20, "ROLE_C C5-4가 요구하는 개수다"
    assert len({s.id for s in rows}) == 20


def test_all_purposes_are_covered(rows):
    """목적 6종 전부. 한 종류라도 빠지면 그 경로의 캐시가 비어 있게 된다."""
    assert {s.purpose for s in rows} == set(PURPOSE_TAGS)


def test_all_zones_are_covered(rows):
    assert {s.zone for s in rows} == set(ZONES)


def test_party_size_bands_are_covered(rows):
    sizes = {s.party_size for s in rows}
    assert any(n <= 2 for n in sizes)
    assert any(3 <= n <= 4 for n in sizes)
    assert any(n >= 5 for n in sizes)


def test_hotspot_outside_zones_are_included(rows):
    """지점 밖 경로(live_* 없음)는 여기서만 검증된다 (ROLE_C §5)."""
    outside = {"huam", "ichon", "cheongpa"}
    assert len([s for s in rows if s.zone in outside]) >= 5


def test_budget_bands_are_spread(rows):
    assert len({s.budget_band for s in rows}) >= 3


def test_scenarios_are_valid_requests(rows):
    """그대로 API에 넣을 수 있어야 한다."""
    from app.schemas import RecommendRequest

    for s in rows:
        RecommendRequest(**sc.to_payload(s, NOW))


# --- 방문 시각 -----------------------------------------------------------------


def test_next_occurrence_is_always_in_the_future():
    """절대 날짜를 박으면 하루만 지나도 과거가 되고 혼잡 예측이 사라진다."""
    for weekday in range(7):
        for hour in (8, 15, 22):
            got = sc.next_occurrence(weekday, hour, NOW)
            assert got > NOW
            assert got.weekday() == weekday and got.hour == hour


def test_same_weekday_later_today_is_today():
    got = sc.next_occurrence(0, 19, NOW)        # 월요일 19시, 지금은 월 15시
    assert got.date() == NOW.date()


def test_same_weekday_earlier_today_rolls_a_week():
    got = sc.next_occurrence(0, 9, NOW)         # 월요일 9시는 이미 지났다
    assert got - NOW > timedelta(days=6)


def test_payload_uses_a_distinct_user_per_scenario(rows):
    ids = {sc.to_payload(s, NOW)["user_id"] for s in rows}
    assert len(ids) == len(rows)


# --- 페이싱 (B5-6 대응) ----------------------------------------------------------


def test_pacing_keeps_us_under_the_limit():
    """분당 10회면 간격이 6초를 넘어야 한다. 안 그러면 11번째부터 429다."""
    interval = sc.pacing_interval(10)
    assert interval > 6.0
    assert 60.0 / interval < 10


def test_pacing_is_zero_when_unlimited():
    assert sc.pacing_interval(0) == 0.0
    assert sc.pacing_interval(-1) == 0.0


def test_pacing_scales_with_the_limit():
    assert sc.pacing_interval(60) < sc.pacing_interval(10)


# --- 퍼센타일 ------------------------------------------------------------------


def test_percentiles_on_a_known_series():
    st = sc.percentiles([float(x) for x in range(1, 101)])
    assert st["min"] == 1.0 and st["max"] == 100.0
    assert st["p50"] == 50.0
    assert st["p95"] == 95.0
    assert st["p99"] == 99.0


def test_percentiles_survive_tiny_samples():
    assert sc.percentiles([]) == {}
    one = sc.percentiles([7.0])
    assert one["p50"] == one["p95"] == one["p99"] == 7.0


def test_percentiles_do_not_care_about_input_order():
    a = sc.percentiles([5.0, 1.0, 3.0])
    b = sc.percentiles([1.0, 3.0, 5.0])
    assert a == b
