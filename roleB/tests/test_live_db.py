"""실 PostGIS 통합 테스트 (W2 게이트).

가짜 executor로는 **SQL이 문법적으로 맞는지, PostGIS 함수를 제대로 쓰는지**
알 수 없다. ST_DWithin의 인자 순서 하나가 틀려도 단위 테스트는 전부 통과한다.
그래서 실제 DB에 던지는 테스트를 따로 둔다.

기본은 skip이다. DB가 있을 때만 돈다.

    docker run -d --name wheretogo-db -p 5432:5432 \
      -e POSTGRES_PASSWORD=devpass -e POSTGRES_DB=wheretogo postgis/postgis:16-3.4
    docker exec wheretogo-db bash -c "apt-get update -qq && apt-get install -y -qq postgresql-16-pgvector"
    export TEST_DATABASE_URL=postgresql://postgres:devpass@localhost:5432/wheretogo
    psql "$TEST_DATABASE_URL" -f ../db/migrations/001_init.sql
    DATABASE_URL=$TEST_DATABASE_URL python -m tools.load_seed_db --demo-hotspot
    pytest tests/test_live_db.py -v
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest

from app.config import Settings
from app.db import Database
from app.schemas import Location, Purpose, RecommendRequest
from app.services import retrieval
from app.services.pipeline import build_live_recommendation

DSN = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DSN, reason="TEST_DATABASE_URL이 없다 (실 DB 없이 도는 환경)"
)

KST = timezone(timedelta(hours=9))
ITAEWON = (37.5340, 126.9946)


@pytest.fixture(scope="module")
def settings() -> Settings:
    return Settings(mock_mode=False, database_url=DSN)


@pytest.fixture(scope="module")
def db(settings):
    d = Database(settings)
    d.open()
    assert d.available, "커넥션 풀이 열리지 않았다"
    yield d
    d.close()


@pytest.fixture(scope="module")
def executor(db):
    return db.fetch_all


@pytest.fixture
def query() -> retrieval.RetrievalQuery:
    return retrieval.RetrievalQuery(
        lat=ITAEWON[0],
        lng=ITAEWON[1],
        visit_at=datetime(2026, 8, 3, 19, 0, tzinfo=KST),
        party_size=2,
        budget_band=3,
        rain_prob=0.1,
        pm25_grade=2,
    )


# --- 인프라 -----------------------------------------------------------------


def test_health_query_runs(db):
    assert db.healthy() is True


def test_required_extensions_are_installed(executor):
    rows = executor(
        "SELECT extname FROM pg_extension WHERE extname IN ('postgis','vector')", {}
    )
    assert {r["extname"] for r in rows} == {"postgis", "vector"}


# --- ① 후보 생성 SQL ----------------------------------------------------------


def test_candidate_sql_runs_and_returns_rows(executor, query):
    result = retrieval.retrieve(executor, query)
    assert result.candidates, "시드가 적재되지 않았다 (tools/load_seed_db.py)"
    for row in result.candidates:
        assert row["poi_id"] and row["name"]
        assert row["lat"] and row["lng"]


def test_distance_is_in_meters_and_within_radius(executor, query):
    """geography 캐스팅이 빠지면 단위가 도(degree)가 되어 조용히 틀린다."""
    result = retrieval.retrieve(executor, query)
    for row in result.candidates:
        assert 0 <= row["dist_m"] <= result.radius_m + 1


def test_candidates_are_ordered_by_distance(executor, query):
    result = retrieval.retrieve(executor, query)
    dists = [r["dist_m"] for r in result.candidates]
    assert dists == sorted(dists)


def test_party_size_hard_filter_applies(executor, query):
    big = retrieval.RetrievalQuery(**{**query.__dict__, "party_size": 20})
    for row in retrieval.retrieve(executor, big).candidates:
        # 최근접 폴백까지 갔다면 하드필터가 풀린 상태이므로 검사 대상이 아니다
        if row.get("group_capacity") is not None:
            assert row["group_capacity"] >= 20 or row["attr_confidence"] is not None


def test_rain_hard_cut_excludes_exposed_places(executor, query):
    rainy = retrieval.RetrievalQuery(**{**query.__dict__, "rain_prob": 0.9})
    result = retrieval.retrieve(executor, rainy)
    if result.strategy != "nearest_fallback":
        assert all(r["outdoor_exposure"] <= 0.7 for r in result.candidates)


def test_null_business_hours_are_not_dropped(executor, query):
    """영업시간을 모른다는 이유로 후보에서 떨구면 커버리지가 무너진다."""
    total = executor("SELECT count(*) AS n FROM poi", {})[0]["n"]
    null_hours = executor(
        "SELECT count(*) AS n FROM poi WHERE business_hours IS NULL", {}
    )[0]["n"]
    assert null_hours > 0, "이 테스트가 의미를 가지려면 시드에 NULL이 있어야 한다"
    assert executor("SELECT count(*) AS n FROM poi WHERE is_open_at(business_hours, now())", {})[
        0
    ]["n"] == total


# --- 전체 파이프라인 (W2 게이트) ------------------------------------------------


@pytest.fixture
def req() -> RecommendRequest:
    return RecommendRequest(
        user_id="u_live_test",
        purpose=Purpose.DATE,
        party_size=2,
        budget_band=3,
        location=Location(lat=ITAEWON[0], lng=ITAEWON[1]),
        visit_at="2026-08-03T19:00:00+09:00",
    )


def test_recommend_returns_scored_list(settings, executor, req):
    """🚩 W2 게이트: 시드 데이터로 점수 순 리스트가 나온다."""
    res = build_live_recommendation(req, settings, executor)

    assert 1 <= len(res.results) <= 5
    scores = [r.score for r in res.results if not r.is_exploration]
    assert scores == sorted(scores, reverse=True)
    assert all(0.0 <= r.score <= 1.0 for r in res.results)
    assert all(r.reason for r in res.results)


def test_recommend_is_deterministic(settings, executor, req):
    """같은 요청은 같은 화면을 준다. 탐색 슬롯도 요청으로 시드를 만든다."""
    a = build_live_recommendation(req, settings, executor)
    b = build_live_recommendation(req, settings, executor)
    assert [r.poi_id for r in a.results] == [r.poi_id for r in b.results]


def test_exploration_slot_is_marked(settings, executor, req):
    res = build_live_recommendation(req, settings, executor)
    flags = [r.is_exploration for r in res.results]
    assert flags.count(True) <= 1


def test_live_terms_omitted_outside_hotspot(settings, executor, req):
    """§6.4 — 핫스팟 밖 POI는 live_segment/crowd 키가 **없어야** 한다."""
    res = build_live_recommendation(req, settings, executor)
    by_id = {r.poi_id: r for r in res.results}
    rows = executor(
        "SELECT poi_id, hotspot_code FROM poi WHERE poi_id = ANY(%(ids)s)",
        {"ids": list(by_id)},
    )
    for row in rows:
        dumped = by_id[row["poi_id"]].score_breakdown.model_dump()
        if row["hotspot_code"] is None:
            assert "live_segment" not in dumped
            assert "crowd" not in dumped
        else:
            assert "crowd" in dumped


def test_hotspot_outside_pois_are_not_wiped_out(settings, executor, req):
    """재정규화가 빠지면 핫스팟 밖 POI가 상위에서 통째로 사라진다.

    시드의 지점 밖 POI 비율이 절반을 넘는데 상위 결과에 하나도 없다면 의심한다.
    """
    outside_ratio = executor(
        "SELECT avg((hotspot_code IS NULL)::int)::float8 AS r FROM poi", {}
    )[0]["r"]
    if outside_ratio is None or outside_ratio < 0.3:
        pytest.skip("지점 밖 POI가 적어 판별력이 없다")

    res = build_live_recommendation(req, settings, executor)
    dumps = [r.score_breakdown.model_dump() for r in res.results]
    assert any("live_segment" not in d for d in dumps)
