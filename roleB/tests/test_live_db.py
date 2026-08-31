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


def test_null_group_capacity_is_not_dropped(executor, query):
    """인원 수를 **모르는** 것과 인원이 **안 되는** 것은 다르다.

    NULL을 그대로 비교하면 3값 논리로 WHERE가 NULL이 되어, 그 POI가 인원 수와
    무관하게 **항상** 후보에서 빠진다. 에러도 경고도 없이 사라지는 종류다.
    실제로 A의 `--clear-seed-mock`이 이 컬럼을 NULL로 되돌린다.
    """
    null_rows = executor(
        "SELECT count(*) AS n FROM poi WHERE group_capacity IS NULL", {}
    )[0]["n"]
    if not null_rows:
        pytest.skip("NULL group_capacity 행이 없다 — 이 경로를 확인할 수 없다")

    # 실제 후보 SQL을 그대로 태운다. 조건을 여기 다시 적으면 코드가 바뀔 때 어긋난다.
    big = retrieval.RetrievalQuery(**{**query.__dict__, "party_size": 20})
    params = retrieval._params(big, 100_000.0, 0.0)
    rows = executor(retrieval.CANDIDATE_SQL, params)
    assert any(r["group_capacity"] is None for r in rows), (
        "인원 수를 모르는 POI가 하드필터에서 통째로 빠졌다"
    )


def test_rain_hard_cut_excludes_exposed_places(executor, query):
    """관측된 야외만 잘라낸다. **미관측(NULL)은 자르지 않는다** — 아래 테스트 참조."""
    rainy = retrieval.RetrievalQuery(**{**query.__dict__, "rain_prob": 0.9})
    result = retrieval.retrieve(executor, rainy)
    if result.strategy != "nearest_fallback":
        assert all(
            r["outdoor_exposure"] is None or r["outdoor_exposure"] <= 0.7
            for r in result.candidates
        )


def test_null_outdoor_exposure_survives_the_rain_cut(executor, query):
    """야외 노출을 **모르는** POI가 비 오는 날 통째로 사라지면 안 된다.

    `p.outdoor_exposure <= 0.7`에 NULL이 들어오면 3값 논리로 WHERE가 NULL이 되어
    그 행이 항상 빠진다. group_capacity와 같은 함정인데, 예전엔 "DDL 기본값이
    0.0이라 NULL이 안 생긴다"는 전제로 일부러 남겨 뒀다. A의 A3-2가 리뷰에
    근거가 없으면 이 컬럼을 NULL로 남기면서 그 전제가 깨졌다 — T1이 통째로
    비 오는 날 후보에서 빠질 수 있는 모양이었다.
    """
    null_rows = executor(
        "SELECT count(*) AS n FROM poi WHERE outdoor_exposure IS NULL", {}
    )[0]["n"]
    if not null_rows:
        pytest.skip("NULL outdoor_exposure 행이 없다 — A3-2가 아직 안 돌았다")

    rainy = retrieval.RetrievalQuery(**{**query.__dict__, "rain_prob": 0.9})
    params = retrieval._params(rainy, 100_000.0, 0.0)
    rows = executor(retrieval.CANDIDATE_SQL, params)
    assert any(r["outdoor_exposure"] is None for r in rows), (
        "야외 노출을 모르는 POI가 우천 하드컷에서 통째로 빠졌다"
    )


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


# --- W3 컨텍스트 (B3-2 / B3-3) --------------------------------------------------


@pytest.fixture
def soon() -> datetime:
    """실행 시각 기준 2시간 뒤. 실황 경로."""
    return datetime.now(KST) + timedelta(hours=2)


@pytest.fixture
def later() -> datetime:
    """실행 시각 기준 5시간 뒤. 예보 경로(키가 없으면 실황으로 폴백)."""
    return datetime.now(KST) + timedelta(hours=5)


def test_context_reports_its_weather_source(settings, executor, soon):
    from app.services.pipeline import resolve_context

    resolved = resolve_context(executor, settings, *ITAEWON, soon)
    assert resolved.ctx.weather_source in {"citydata", "kma", "kma+citydata", "mock"}
    # 데모 스냅샷에 WEATHER_STTS를 넣어 뒀으므로 mock으로 떨어지면 파싱이 깨진 것이다
    assert resolved.ctx.weather_source != "mock", "citydata 스냅샷 파싱이 실패했다"


def test_citydata_weather_is_parsed_from_snapshot(settings, executor, soon):
    """스냅샷 원본과 대조한다. **고정값을 박지 않는다.**

    예전엔 개발 시드 값(31.7 / 등급2 / 19:42)을 그대로 기대했다. 그러다 실 DB를
    붙이니 전부 틀렸다 — 시드에만 있던 `SENSIBLE_TEMP`가 실제 응답엔 없다.
    **테스트가 검증해야 하는 것은 값이 아니라 "행에 있는 것을 그대로 읽는가"** 다.
    """
    from app.services.live_signals import as_float, parse_citydata_weather
    from app.services.pipeline import resolve_context

    resolved = resolve_context(executor, settings, *ITAEWON, soon)
    ctx = resolved.ctx
    row = executor(
        "SELECT weather FROM hotspot_latest WHERE hotspot_code = %(code)s",
        {"code": resolved.nearest_code},
    )
    if not row or not row[0]["weather"]:
        pytest.skip("가장 가까운 지점의 스냅샷에 WEATHER_STTS가 없다")

    raw = row[0]["weather"]
    parsed = parse_citydata_weather(raw)
    assert parsed is not None, "실 스냅샷의 WEATHER_STTS 파싱이 실패했다"

    assert ctx.pm25_grade == parsed["pm25_grade"]
    assert ctx.sunset == parsed["sunset"]             # 분까지 보존한다
    assert ctx.sunset == str(raw.get("SUNSET")).strip()

    # 실황에 SENSIBLE_TEMP가 있으면 그게 우선, 없으면 습도·풍속으로 만든 체감온도다.
    # 어느 쪽이든 **기온보다 낮아질 이유는 없다** (여름 기준). 여기가 §6.3의 입력이다.
    temp = as_float(raw.get("TEMP"))
    assert ctx.feels_like == pytest.approx(parsed["feels_like"])
    if raw.get("SENSIBLE_TEMP") is None and temp is not None and temp >= 27:
        assert ctx.feels_like > temp, "습도·풍속이 체감온도에 반영되지 않았다"


def test_congest_forecast_uses_visit_time_not_now(settings, executor, soon):
    """FCST_PPLTN에서 방문 시각 슬롯을 고른다. 실황과 값이 갈릴 수 있어야 한다."""
    from app.services.pipeline import resolve_context

    ctx = resolve_context(executor, settings, *ITAEWON, soon).ctx
    assert ctx.congest_now is not None
    assert ctx.congest_forecast_at_visit is not None


def test_missing_kma_key_falls_back_to_citydata(settings, executor, later):
    """키가 없어도 예보 시각 요청이 500이 되지 않는다.

    폴백 순서가 바뀌었다 — 실황이 아니라 **citydata 24시간 예보가 먼저**다.
    `KMA_SERVICE_KEY`가 없는 동안 *"5시간 뒤에 갈 건데"* 에 지금 날씨로 답하는 것은
    마지막 수단이어야 한다. 스냅샷의 `FCST24HOURS`는 이미 적재돼 있다.
    """
    from app.services.pipeline import resolve_context

    resolved = resolve_context(executor, settings, *ITAEWON, later)
    ctx = resolved.ctx
    assert ctx.weather_source in {"citydata", "citydata_fcst", "kma", "kma+citydata"}

    if settings.kma_service_key:
        return                                  # 키가 있으면 기상청이 이긴다

    near = resolved.signals.get(resolved.nearest_code or "")
    if near and near.weather_at_visit:
        assert ctx.weather_source == "citydata_fcst", (
            "예보 슬롯이 있는데도 실황으로 물러섰다"
        )
        # 예보의 강수는 확률이다. 실황(0/1)과 의미가 다르다.
        assert ctx.rain_prob == pytest.approx(near.weather_at_visit["rain_prob"])
        # 대기질과 일몰은 예보에 없다 — 실황에서 채워져야 한다.
        assert ctx.pm25_grade is not None
        assert ctx.sunset


def test_context_outside_hotspot_has_no_live_fields(settings, executor, soon):
    """지점에서 먼 좌표. 혼잡·연령 문구를 지어내지 않는다.

    좌표를 **DB에서 찾는다.** 예전엔 이촌 한강변을 하드코딩했는데, A가 용산
    11개 지점을 실제로 적재하니 그 점이 국립중앙박물관 반경 1km 안이 됐다.
    지점 배치가 바뀔 때마다 테스트가 거짓으로 깨진다.
    """
    from app.services.pipeline import resolve_context

    # 전 지점에서 1km 밖인 POI 하나를 빌려 쓴다. `hotspot_code IS NULL`이
    # A의 매핑 규칙(1km 밖은 NULL)과 같은 기준이다.
    rows = executor(
        "SELECT ST_Y(geom::geometry) AS lat, ST_X(geom::geometry) AS lng"
        " FROM poi WHERE hotspot_code IS NULL LIMIT 1",
        {},
    )
    if not rows:
        pytest.skip("지점 반경 밖 POI가 없다 — 이 경로를 검증할 수 없다")

    far = (rows[0]["lat"], rows[0]["lng"])
    ctx = resolve_context(executor, settings, *far, soon).ctx
    assert ctx.hotspot is None
    assert ctx.congest_now is None
    assert ctx.age_mix_top is None


def test_weather_sensitivity_changes_the_score(settings, db, executor, req):
    """B3-4 — 온보딩 5번 문항이 실제 응답을 바꾸는지 DB 경로로 확인한다."""
    from app.services.pipeline import build_live_recommendation

    db.execute(
        "INSERT INTO user_profile (user_id, gender, age_band, weather_sensitivity) "
        "VALUES ('u_ws_test','F',20,1) "
        "ON CONFLICT (user_id) DO UPDATE SET weather_sensitivity = 1"
    )
    low = build_live_recommendation(
        req.model_copy(update={"user_id": "u_ws_test"}), settings, executor
    )
    db.execute("UPDATE user_profile SET weather_sensitivity = 3 WHERE user_id = 'u_ws_test'")
    high = build_live_recommendation(
        req.model_copy(update={"user_id": "u_ws_test"}), settings, executor
    )

    # 비가 안 오는 날씨면 민감도가 아무것도 바꾸지 않는다. 그때는 순서만 확인한다.
    if (low.context.rain_prob or 0) > 0.3:
        assert [r.score for r in low.results] != [r.score for r in high.results]
    else:
        assert [r.poi_id for r in low.results] == [r.poi_id for r in high.results]


# --- W4 로깅 · 온보딩 · 피드백 ---------------------------------------------------


def test_recommendation_is_logged_with_unshown_candidates(settings, db, executor, req):
    """🚩 B4-4 — 노출 안 된 후보까지 남아야 나중에 랭킹을 학습할 수 있다."""
    from app.services.pipeline import build_live_recommendation

    res = build_live_recommendation(req, settings, executor)
    row = executor(
        "SELECT log_id, candidates, context, explain_mode, latency_ms "
        "FROM recommendation_log WHERE log_id = %(log_id)s",
        {"log_id": res.log_id},
    )
    assert row, "log_id가 실제 행을 가리키지 않는다"
    entry = row[0]
    cands = entry["candidates"]

    if res.radius_expanded or res.low_confidence:
        # 최근접 폴백은 후보가 3건뿐이라 '노출 안 된 후보'가 존재할 수 없다.
        # 실패가 아니라 **A의 속성 추출(attr_confidence)이 아직**이라는 신호다.
        assert cands, "폴백 경로에서도 후보는 남아야 한다"
        assert all("terms" in c and "shown" in c for c in cands)
        pytest.skip(
            "최근접 폴백 상태다 (attr_confidence 전 건 0) — negative sample이 나올 수 없다"
        )

    assert len(cands) > len(res.results), "상위 20건이 아니라 노출분만 남았다"
    assert any(c["shown"] for c in cands)
    assert any(not c["shown"] for c in cands)
    assert all("terms" in c for c in cands)
    assert entry["explain_mode"] == "template"
    assert entry["latency_ms"] is not None


def test_logged_context_coarsens_coordinates(settings, executor, req):
    from app.services.pipeline import build_live_recommendation

    res = build_live_recommendation(req, settings, executor)
    ctx = executor(
        "SELECT context FROM recommendation_log WHERE log_id = %(log_id)s",
        {"log_id": res.log_id},
    )[0]["context"]
    assert ctx["lat"] == round(ITAEWON[0], 3)
    assert "weather" in ctx and "weather_source" in ctx


def test_feedback_updates_the_log(settings, db, executor, req):
    from app.services.logging_svc import record_feedback
    from app.services.pipeline import build_live_recommendation

    res = build_live_recommendation(req, settings, executor)
    picked = res.results[0].poi_id

    assert record_feedback(
        db.fetch_all, log_id=res.log_id, clicked=[picked], selected=None, feedback=None
    )
    # 두 번째 호출은 만족도만 보낸다 — 앞선 클릭이 지워지면 안 된다
    assert record_feedback(
        db.fetch_all, log_id=res.log_id, clicked=None, selected=picked, feedback=5
    )

    row = executor(
        "SELECT clicked, selected, feedback FROM recommendation_log WHERE log_id=%(id)s",
        {"id": res.log_id},
    )[0]
    assert row["clicked"] == [picked]
    assert row["selected"] == picked
    assert row["feedback"] == 5


def test_clicked_accumulates_across_calls(settings, db, executor, req):
    """C의 ResultCard는 카드를 누를 때마다 원소 하나짜리 배열을 보낸다.

    덧쓰기면 마지막 클릭 하나만 남는다. 노출-클릭 로그가 랭킹 학습의 전제인데
    (B4-4) 그러면 학습 데이터가 조용히 망가진다.
    """
    from app.services.logging_svc import record_feedback
    from app.services.pipeline import build_live_recommendation

    res = build_live_recommendation(req, settings, executor)
    if len(res.results) < 2:
        pytest.skip("후보가 2건 미만 — A의 적재 대기")
    first, second = res.results[0].poi_id, res.results[1].poi_id

    record_feedback(db.fetch_all, log_id=res.log_id, clicked=[first], selected=None, feedback=None)
    record_feedback(db.fetch_all, log_id=res.log_id, clicked=[second], selected=None, feedback=None)
    # 같은 것을 또 눌러도 중복으로 쌓이지 않는다
    record_feedback(db.fetch_all, log_id=res.log_id, clicked=[first], selected=None, feedback=None)

    row = executor(
        "SELECT clicked FROM recommendation_log WHERE log_id=%(id)s", {"id": res.log_id}
    )[0]
    assert row["clicked"] == [first, second]      # 처음 등장한 순서 그대로


def test_feedback_on_unknown_log_is_false(db):
    from app.services.logging_svc import record_feedback

    assert not record_feedback(
        db.fetch_all, log_id=999_999_999, clicked=["x"], selected=None, feedback=1
    )


def test_onboarding_creates_profile_and_taste_vector(settings, db, executor):
    """B4-5 — tag_embedding이 있으면 taste_vector가 채워진다."""
    from app.services.user_svc import make_user_id, upsert_profile

    tags = ["조용한", "감성적인", "데이트"]
    uid = make_user_id("F", 20, tags[:2], tags[2:], 3, 3)
    upsert_profile(
        db.fetch_all, user_id=uid, gender="F", age_band=20,
        taste_tags=tags, weather_sensitivity=3,
    )

    row = executor(
        "SELECT gender, age_band, taste_tags, weather_sensitivity, "
        "       (taste_vector IS NOT NULL) AS has_vector "
        "FROM user_profile WHERE user_id = %(uid)s",
        {"uid": uid},
    )
    assert row, "프로필이 저장되지 않았다"
    assert row[0]["taste_tags"] == tags
    assert row[0]["weather_sensitivity"] == 3

    embedded = executor("SELECT count(*) AS n FROM tag_embedding", {})[0]["n"]
    if embedded:
        assert row[0]["has_vector"], "tag_embedding이 있는데 taste_vector가 비었다"


def test_taste_similarity_comes_from_the_database(settings, db, executor, req):
    """1024차원 벡터를 파이썬으로 끌어오지 않는다. `<=>`가 실제로 도는지 본다."""
    from app.services.user_svc import upsert_profile

    if not executor("SELECT count(*) AS n FROM tag_embedding", {})[0]["n"]:
        pytest.skip("tag_embedding이 비어 있다 (--demo-vectors 없이 적재됨)")

    uid = "u_taste_test"
    upsert_profile(
        db.fetch_all, user_id=uid, gender="F", age_band=20,
        taste_tags=["조용한", "감성적인"], weather_sensitivity=2,
    )
    # ⚠️ 파라미터를 손으로 적지 않는다. 예전엔 dict를 여기 직접 썼는데,
    #    CANDIDATE_SQL에 `outdoor_unknown`이 하나 늘면서 이 테스트가
    #    `query parameter missing`으로 죽었다 — SQL이 바뀐 것을 잡은 게 아니라
    #    테스트가 따라가지 못한 것이다. `_params`가 SQL과 같은 곳에서 나온다.
    q = retrieval.RetrievalQuery(
        lat=ITAEWON[0], lng=ITAEWON[1], visit_at=datetime.now(KST),
        party_size=2, budget_band=4, limit=50, user_id=uid, conf_min=0.0,
    )
    rows = executor(retrieval.CANDIDATE_SQL, retrieval._params(q, 3000.0, 0.0))
    sims = [r["taste_sim"] for r in rows if r["taste_sim"] is not None]
    assert sims, "taste_sim이 전부 NULL이다 — tag_vector 또는 taste_vector가 비었다"
    assert all(-1.01 <= s <= 1.01 for s in sims)
    assert len(set(round(s, 4) for s in sims)) > 1, "모든 POI의 유사도가 같다"


# --- W5 RAG · 설명 캐시 ----------------------------------------------------------


def test_query_vector_cache_is_hit(settings, executor):
    """온라인에서 임베딩하지 않는다. 72행 캐시에서 조회한다."""
    from app.services.rag import fetch_query_vector

    if not executor("SELECT count(*) AS n FROM query_vector_cache", {})[0]["n"]:
        pytest.skip("query_vector_cache가 비어 있다 (--demo-vectors --reviews 없이 적재됨)")
    assert fetch_query_vector(executor, "데이트", "비", 2) is not None


def test_evidence_is_prefiltered_to_given_pois(settings, executor):
    """🚩 B5-1 — 사후 필터링을 쓰면 정확도가 붕괴한다."""
    from app.services.rag import fetch_evidence, fetch_query_vector

    ids = [
        r["poi_id"]
        for r in executor("SELECT DISTINCT poi_id FROM review_chunk LIMIT 5", {})
    ]
    if not ids:
        pytest.skip("review_chunk가 비어 있다 (--reviews 없이 적재됨)")

    qvec = fetch_query_vector(executor, "데이트", "맑음", 2)
    got = fetch_evidence(executor, ids, qvec)
    assert got, "인용이 하나도 나오지 않았다"
    assert set(got) <= set(ids), "요청하지 않은 POI의 인용이 섞였다"
    assert all(len(v) <= 3 for v in got.values()), "POI당 3청크 상한이 지켜지지 않았다"


def test_evidence_pushes_sponsored_chunks_back(settings, executor):
    """인용문이 광고면 신뢰를 잃는다."""
    from app.services.rag import fetch_evidence

    row = executor(
        "SELECT poi_id FROM review_chunk GROUP BY poi_id "
        "HAVING count(*) FILTER (WHERE is_sponsored) > 0 "
        "   AND count(*) FILTER (WHERE NOT is_sponsored) > 0 LIMIT 1",
        {},
    )
    if not row:
        pytest.skip("협찬/비협찬이 섞인 POI가 없다")
    poi_id = row[0]["poi_id"]

    top = fetch_evidence(executor, [poi_id], None)[poi_id][0]["text"]
    sponsored = {
        r["text"]
        for r in executor(
            "SELECT text FROM review_chunk WHERE poi_id=%(p)s AND is_sponsored",
            {"p": poi_id},
        )
    }
    assert top not in sponsored


def test_recommendation_quotes_come_from_review_chunk(settings, db, executor, req):
    """인용은 창작이 아니라 원문 발췌다. DB에 실제로 있는 문장인지 본다.

    실제로 상위에 오를 POI에 후기를 직접 심는다. 시드의 리뷰 분포에 기대면
    (특히 `--scale`로 복제된 POI가 많을 때) 이 테스트가 조용히 skip된다.

    ⚠️ **심은 문장이 인용되는지는 보지 않는다.** 예전엔 그걸 단언했는데, 그건
    "이 POI에 후기가 거의 없다"는 시드 DB의 전제 위에서만 참이다. 실 Supabase에는
    같은 POI에 진짜 후기 2,200청크가 있어 심은 문장이 밀리고, 그러면 **인용이
    정상 동작하는데도 테스트가 빨간불**이 된다. 심는 이유는 인용이 0건이라
    아래 루프가 공허하게 통과하는 것을 막기 위해서지, 순위를 보려는 게 아니다.
    지켜야 할 계약은 하나다 — **나간 인용은 전부 원문에 있다.**
    """
    from app.services.pipeline import build_live_recommendation

    target = build_live_recommendation(req, settings, executor).results[0].poi_id
    marker = "통합테스트 전용 후기 — 창가 자리가 조용합니다"
    db.execute(
        "INSERT INTO review_chunk (poi_id, source, text, is_sponsored) "
        "VALUES (%(p)s, 'naver_blog', %(t)s, false)",
        {"p": target, "t": marker},
    )
    try:
        res = build_live_recommendation(req, settings, executor)
        quoted = [(r.poi_id, e.text) for r in res.results for e in r.evidence]
        assert quoted, "리뷰를 심었는데 인용이 하나도 붙지 않았다"

        for poi_id, text in quoted:
            found = executor(
                "SELECT 1 FROM review_chunk WHERE poi_id=%(p)s AND text = %(t)s",
                {"p": poi_id, "t": text},
            )
            assert found, f"원문에 없는 인용이다: {text[:30]}"
    finally:
        db.execute("DELETE FROM review_chunk WHERE text = %(t)s", {"t": marker})


def test_explain_mode_is_template_without_a_key(settings, executor, req):
    """🚩 B5-5 — 키가 없어도 서비스가 돈다. 500이 아니라 template이다."""
    from app.services.pipeline import build_live_recommendation

    res = build_live_recommendation(req, settings, executor)
    assert {r.explain_mode.value for r in res.results} == {"template"}
    assert all(r.reason for r in res.results)


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


def test_live_결과도_점수_내림차순이다(settings, executor, req):
    """LLM이 고른 순서가 아니라 **점수 순**으로 나가야 한다 (2026-08-30).

    live 경로만 이 규칙에서 빠져 있었다. `explain.generate`가 돌려준 순서를
    그대로 화면에 실어서, 배포본에서 1번 카드 0.8603 · 4번 카드 0.8808 이
    나왔다. 목 경로는 처음부터 점수 순이라 목으로는 재현되지 않는다 —
    그래서 이 테스트가 여기(실 DB)에 있다.

    LLM 응답에 의존하지 않는다. 캐시든 템플릿이든 순서 규칙은 같아야 한다.
    """
    res = build_live_recommendation(req, settings, executor)
    ranked = [r.score for r in res.results if not r.is_exploration]
    assert len(ranked) >= 1
    assert all(a >= b for a, b in zip(ranked, ranked[1:])), f"점수 순이 아니다: {ranked}"

    flags = [r.is_exploration for r in res.results]
    assert flags.count(True) <= 1
    if True in flags:
        assert flags[-1] is True, "탐색 슬롯은 맨 뒤다 (ROLE_B §6.7)"


def test_추천은_왕복_예산_안에서_끝난다(settings, db, req):
    """DB **호출 횟수**가 이 파이프라인의 지연을 정한다 (BRIEF_2026-08-30 §1②).

    Render(싱가포르) → Supabase(서울) 왕복이 실측 88ms다. 호출이 하나 늘면
    p50이 88ms 늘어난다 — 쿼리를 아무리 튜닝해도 되돌릴 수 없는 종류의 비용이다.
    그래서 호출 수 자체를 계약으로 못박는다.

    지금 구조 (묶음은 동시에 나가므로 왕복 1회로 친다)
        ⓪ 최근접지점 · 스냅샷 · 프로필 · 생활권   (4 호출 · 왕복 1)
        ① 후보 생성                              (1)
        ② 세그먼트 · 쿼리벡터                     (2 호출 · 왕복 1)
        ③ 인용                                    (1)
        ④ 설명 캐시 조회                          (1)
        ⑤ 로그 기록                               (1)
                                        합계 10 호출 · 왕복 6회

    호출 수가 늘면 여기서 먼저 깨진다. 늘려야 할 이유가 있으면 이 숫자를 같이
    올리되, **묶을 수 있는지 먼저 본다** (`pipeline.gather`).
    """
    from app.services.pipeline import build_live_recommendation

    calls: list[str] = []

    def counting(sql, params=None):
        calls.append(" ".join(sql.split())[:40])
        return db.fetch_all(sql, params)

    build_live_recommendation(req, settings, counting)

    assert len(calls) <= 11, (
        f"DB 호출이 {len(calls)}회다 (예산 10~11). Render에서 호출 하나가 88ms다:\n  "
        + "\n  ".join(calls)
    )
