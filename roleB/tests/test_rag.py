"""근거 검색 (B5-1).

**사전 필터가 이 모듈의 전부다.** 벡터로 전체를 먼저 뒤진 뒤 상위 20개로 거르면
상위 20개에 대한 근거가 하나도 안 남는 일이 생긴다. SQL에서 `poi_id` 필터가
정렬보다 **먼저** 있는지 문자열로 확인한다 — 실행 계획까지는 test_live_db가 본다.
"""

from __future__ import annotations

import pytest

from app.services.rag import (
    EVIDENCE_FALLBACK_SQL,
    EVIDENCE_SQL,
    fetch_evidence,
    fetch_query_vector,
    weather_state_of,
)


# --- 날씨 상태 접기 -------------------------------------------------------------


@pytest.mark.parametrize(
    "wx, expected",
    [
        ({"rain_prob": 0.6}, "비"),
        ({"rain_prob": 0.0, "pm25_grade": 3}, "미세먼지나쁨"),
        ({"rain_prob": 0.0, "pm25_grade": 1, "feels_like": 34.0}, "폭염한파"),
        ({"rain_prob": 0.0, "pm25_grade": 1, "feels_like": -10.0}, "폭염한파"),
        ({"rain_prob": 0.0, "pm25_grade": 1, "feels_like": 21.0}, "맑음"),
    ],
)
def test_weather_state_folds_into_four(wx, expected):
    assert weather_state_of(wx) == expected


def test_rain_wins_over_dust():
    """비와 미세먼지가 겹치면 비다. 행동을 더 크게 바꾸는 쪽이다."""
    assert weather_state_of({"rain_prob": 0.8, "pm25_grade": 4}) == "비"


def test_missing_weather_defaults_to_clear():
    assert weather_state_of({}) == "맑음"


# --- 쿼리 벡터 ------------------------------------------------------------------


def test_query_vector_is_looked_up_not_computed():
    """온라인에서 임베딩하지 않는다. 캐시 조회만 한다 (§1.2)."""
    captured = {}

    def ex(sql, params):
        captured.update(params)
        return [{"embedding": "<vec>", "query_text": "..."}]

    assert fetch_query_vector(ex, "데이트", "비", 2) == "<vec>"
    assert captured == {"purpose": "데이트", "weather_state": "비", "party_band": 1}


def test_party_size_is_folded_into_band():
    captured = {}

    def ex(sql, params):
        captured.update(params)
        return []

    fetch_query_vector(ex, "회식", "맑음", 8)
    assert captured["party_band"] == 3


def test_cache_miss_returns_none():
    assert fetch_query_vector(lambda s, p: [], "데이트", "비", 2) is None


def test_query_vector_failure_is_not_fatal():
    def ex(sql, params):
        raise RuntimeError("query_vector_cache 없음")

    assert fetch_query_vector(ex, "데이트", "비", 2) is None


# --- 사전 필터 ------------------------------------------------------------------


def test_sql_filters_by_poi_id_before_ordering():
    """사후 필터링을 쓰면 정확도가 붕괴한다 (ROLE_B §6.8)."""
    where_pos = EVIDENCE_SQL.index("rc.poi_id = ANY(%(poi_ids)s)")
    order_pos = EVIDENCE_SQL.index("row_number() OVER")
    assert where_pos > order_pos  # 같은 서브쿼리 안. 바깥 필터가 아니다
    assert "WHERE rn <=" in EVIDENCE_SQL


def test_sponsored_chunks_are_pushed_back():
    """인용문이 광고면 신뢰를 잃는다. 정렬 첫 키가 is_sponsored여야 한다."""
    for sql in (EVIDENCE_SQL, EVIDENCE_FALLBACK_SQL):
        order = sql[sql.index("ORDER BY rc.is_sponsored") :]
        assert order.startswith("ORDER BY rc.is_sponsored")


# --- 인용 수집 ------------------------------------------------------------------


def test_evidence_is_grouped_by_poi():
    rows = [
        {"poi_id": "p1", "text": "조용해요", "source": "naver_blog", "sim": 0.8},
        {"poi_id": "p1", "text": "창가가 좋아요", "source": "naver_blog", "sim": 0.7},
        {"poi_id": "p2", "text": "넓어요", "source": "naver_blog", "sim": 0.6},
    ]
    got = fetch_evidence(lambda s, p: rows, ["p1", "p2"], "<vec>")
    assert set(got) == {"p1", "p2"}
    assert len(got["p1"]) == 2


def test_vector_sql_is_used_when_a_query_vector_exists():
    used: list[str] = []

    def ex(sql, params):
        used.append(sql)
        return [{"poi_id": "p1", "text": "좋아요", "source": "naver_blog", "sim": 0.5}]

    fetch_evidence(ex, ["p1"], "<vec>")
    assert used == [EVIDENCE_SQL]


def test_fallback_sql_is_used_without_a_query_vector():
    used: list[str] = []
    fetch_evidence(lambda s, p: used.append(s) or [], ["p1"], None)
    assert used == [EVIDENCE_FALLBACK_SQL]


def test_unembedded_chunks_are_still_quotable():
    """수집(월 1회)과 임베딩 배치는 시점이 다르다. 그 사이 후기를 버리면
    새로 수집한 POI가 근거 없는 추천이 된다."""
    used: list[str] = []

    def ex(sql, params):
        used.append(sql)
        if sql is EVIDENCE_SQL:
            return [{"poi_id": "p1", "text": "임베딩 있음", "source": "naver_blog", "sim": 0.8}]
        # p2는 벡터 검색에서 안 나왔다 → 비-벡터 정렬로 한 번 더 찾는다
        assert params["poi_ids"] == ["p2"]
        return [{"poi_id": "p2", "text": "임베딩 아직 없음", "source": "naver_blog", "sim": None}]

    got = fetch_evidence(ex, ["p1", "p2"], "<vec>")
    assert used == [EVIDENCE_SQL, EVIDENCE_FALLBACK_SQL]
    assert set(got) == {"p1", "p2"}


def test_no_second_query_when_every_poi_matched():
    used: list[str] = []

    def ex(sql, params):
        used.append(sql)
        return [{"poi_id": "p1", "text": "t", "source": "naver_blog", "sim": 0.5}]

    fetch_evidence(ex, ["p1"], "<vec>")
    assert used == [EVIDENCE_SQL]


def test_no_poi_ids_skips_the_query():
    calls: list[str] = []
    fetch_evidence(lambda s, p: calls.append(s) or [], [], "<vec>")
    assert calls == []


def test_evidence_failure_is_not_fatal():
    """근거를 못 붙였다고 추천이 멈추지는 않는다."""

    def ex(sql, params):
        raise RuntimeError("review_chunk 없음")

    assert fetch_evidence(ex, ["p1"], None) == {}


def test_empty_text_rows_are_dropped():
    rows = [{"poi_id": "p1", "text": "", "source": "naver_blog", "sim": 0.9}]
    assert fetch_evidence(lambda s, p: rows, ["p1"], None) == {}
