"""후보 생성 테스트 (B2-2).

여기서 검증하는 것은 SQL 문법이 아니라 **물러서는 순서**다.

    반경 확대 → 신뢰도 완화 → 최근접 폴백

이 경로는 실데이터가 얇을 때만 타기 때문에 DB 통합 테스트로는 재현이 어렵다.
그래서 executor를 가짜로 주입해 분기만 본다. SQL 자체는 test_live_db.py가
실제 PostGIS에 던져 확인한다.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from app.constants import (
    ATTR_CONFIDENCE_MIN,
    ATTR_CONFIDENCE_RELAXED,
    DEFAULT_RADIUS_M,
    RADIUS_EXPAND_FACTOR,
)
from app.services.retrieval import (
    CANDIDATE_SQL,
    NEAREST_SQL,
    RetrievalQuery,
    fetch_hotspot_latest,
    fetch_segment_affinity,
    retrieve,
)

KST = timezone(timedelta(hours=9))


def _rows(n: int) -> list[dict[str, Any]]:
    return [{"poi_id": f"p_{i:03d}", "name": f"곳 {i}", "dist_m": 100.0 + i} for i in range(n)]


class FakeExecutor:
    """(sql, params)를 기록하고 정해진 답을 준다."""

    def __init__(self, candidate_counts: list[int], relaxed: int = 0, nearest: int = 0):
        self.candidate_counts = list(candidate_counts)
        self.relaxed = relaxed
        self.nearest = nearest
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def __call__(self, sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        self.calls.append((sql, dict(params)))
        if sql == NEAREST_SQL:
            return _rows(self.nearest)
        if sql == CANDIDATE_SQL:
            if params["conf_min"] == ATTR_CONFIDENCE_RELAXED:
                return _rows(self.relaxed)
            n = self.candidate_counts.pop(0) if self.candidate_counts else 0
            return _rows(n)
        return []

    @property
    def candidate_calls(self) -> list[dict[str, Any]]:
        return [p for s, p in self.calls if s == CANDIDATE_SQL]


@pytest.fixture
def query() -> RetrievalQuery:
    return RetrievalQuery(
        lat=37.5340,
        lng=126.9946,
        visit_at=datetime(2026, 8, 3, 19, 0, tzinfo=KST),
        party_size=2,
        budget_band=3,
        rain_prob=0.6,
        pm25_grade=2,
    )


# --- 정상 경로 ---------------------------------------------------------------


def test_no_expansion_when_enough_candidates(query):
    ex = FakeExecutor([40])
    result = retrieve(ex, query)

    assert len(result.candidates) == 40
    assert result.radius_m == float(DEFAULT_RADIUS_M)
    assert result.radius_expanded is False
    assert result.low_confidence is False
    assert len(ex.candidate_calls) == 1


def test_hard_filter_params_are_passed_through(query):
    ex = FakeExecutor([40])
    retrieve(ex, query)
    p = ex.candidate_calls[0]

    assert p["radius_m"] == float(DEFAULT_RADIUS_M)
    assert p["party_size"] == 2
    assert p["budget_band"] == 3
    assert p["rain_prob"] == 0.6
    assert p["pm25_grade"] == 2
    assert p["conf_min"] == ATTR_CONFIDENCE_MIN
    assert p["visit_at"] == query.visit_at


# --- 물러서는 순서 -----------------------------------------------------------


def test_expands_radius_when_candidates_are_thin(query):
    """후보가 얇으면 순위가 의미를 잃는다. 최대 2회까지 넓힌다."""
    ex = FakeExecutor([5, 5, 5])
    result = retrieve(ex, query)

    assert result.radius_expanded is True
    assert result.radius_m == pytest.approx(DEFAULT_RADIUS_M * RADIUS_EXPAND_FACTOR**2)
    assert len(ex.candidate_calls) == 3          # 최초 1 + 확대 2
    assert result.low_confidence is False        # 확대만으로 충분했다


def test_relaxes_confidence_when_still_short(query):
    """반경을 다 넓혀도 부족하면 속성 신뢰도 기준을 낮춘다. 대신 표시한다."""
    ex = FakeExecutor([1, 1, 1], relaxed=4)
    result = retrieve(ex, query)

    assert result.low_confidence is True
    assert len(result.candidates) == 4
    assert ex.candidate_calls[-1]["conf_min"] == ATTR_CONFIDENCE_RELAXED


def test_nearest_fallback_never_returns_empty(query):
    """어떤 경로로도 빈 배열을 반환하지 않는다 (ROLE_B §1.3)."""
    ex = FakeExecutor([0, 0, 0], relaxed=0, nearest=3)
    result = retrieve(ex, query)

    assert result.candidates != []
    assert result.low_confidence is True
    assert result.strategy == "nearest_fallback"
    assert any(sql == NEAREST_SQL for sql, _ in ex.calls)


def test_fallback_does_not_shrink_existing_candidates(query):
    """완화로 2건을 얻었는데 최근접이 1건이면 2건을 유지해야 한다."""
    ex = FakeExecutor([0, 0, 0], relaxed=2, nearest=1)
    result = retrieve(ex, query)
    assert len(result.candidates) == 2


# --- 부수 조회 ---------------------------------------------------------------


def test_hotspot_latest_is_keyed_by_code():
    ex = lambda sql, params: [  # noqa: E731
        {"hotspot_code": "POI_ITW", "congest_lvl": "보통"},
        {"hotspot_code": "POI_YSS", "congest_lvl": "붐빔"},
    ]
    got = fetch_hotspot_latest(ex)
    assert set(got) == {"POI_ITW", "POI_YSS"}
    assert got["POI_YSS"]["congest_lvl"] == "붐빔"


def test_hotspot_latest_empty_is_normal():
    """폴링이 아직 안 돌았으면 빈 dict다. 이건 정상이고 live_*가 None이 된다."""
    assert fetch_hotspot_latest(lambda sql, params: []) == {}


def test_segment_affinity_skips_query_without_join_keys():
    """상권 코드가 하나도 없으면 쿼리를 날리지 않는다."""
    calls: list[str] = []

    def ex(sql, params):
        calls.append(sql)
        return []

    got = fetch_segment_affinity(
        ex,
        [{"commercial_area_id": None, "category_l2": "카페"}],
        gender="F",
        age_bands=(20, 25),
        dow_type=0,
        hour_band=4,
    )
    assert got == {}
    assert calls == []


def test_segment_affinity_maps_area_category_pairs():
    def ex(sql, params):
        assert params["age_bands"] == [20, 25]     # 20대는 20·25 두 밴드다
        return [{"commercial_area_id": "A1", "category_l2": "카페", "affinity": 0.73}]

    got = fetch_segment_affinity(
        ex,
        [{"commercial_area_id": "A1", "category_l2": "카페"}],
        gender="F",
        age_bands=(20, 25),
        dow_type=0,
        hour_band=4,
    )
    assert got == {("A1", "카페"): 0.73}


# --- 신뢰도 임계값이 설정으로 바뀌는가 (전환기 조정) --------------------------
#
# A의 LLM 속성 추출 전에는 attr_confidence가 전 건 0이라 기본값(0.30)으로는
# 후보가 한 건도 안 남는다. 그때 코드 수정 없이 환경변수만 내려서 전환할 수
# 있어야 한다. 아래 두 테스트가 그 배선이 끊기지 않았는지 지킨다.


def test_conf_min_defaults_to_design_value(query):
    ex = FakeExecutor([40])
    retrieve(ex, query)
    assert ex.candidate_calls[0]["conf_min"] == ATTR_CONFIDENCE_MIN


def test_conf_min_override_reaches_sql(query):
    """설정값이 SQL 파라미터까지 그대로 내려가야 의미가 있다."""
    q = replace(query, conf_min=0.0, conf_relaxed=0.0)
    ex = FakeExecutor([40])
    retrieve(ex, q)
    assert ex.candidate_calls[0]["conf_min"] == 0.0


def test_relaxed_step_uses_overridden_value(query):
    """완화 단계도 상수가 아니라 설정값을 써야 한다.

    여기가 상수로 남아 있으면 임계값을 0으로 내려도 완화 단계만 0.15로 돌아가
    '왜 아직도 후보가 없지'가 된다.
    """
    q = replace(query, conf_min=0.05, conf_relaxed=0.0)
    ex = FakeExecutor([0, 0, 0])          # 반경을 넓혀도 계속 0건
    retrieve(ex, q)
    assert ex.candidate_calls[-1]["conf_min"] == 0.0
