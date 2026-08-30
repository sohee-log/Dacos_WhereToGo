"""목 API 동작 테스트 — C가 이 형태를 보고 UI를 만든다.

여기서 검증하는 것은 "값이 맞는가"가 아니라 **"형태가 계약과 같은가"** 다.
값은 W2~W4에 실데이터로 바뀌지만 형태는 바뀌면 안 된다.
"""

from __future__ import annotations

import pytest

from app.schemas import RecommendResponse


# --- 시스템 ---------------------------------------------------------------


def test_health_ok(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["mode"] == "mock"


def test_mock_responses_are_tagged(client):
    """목 응답에는 헤더가 붙는다. C가 실서버와 구분할 수 있어야 한다."""
    assert client.get("/health").headers.get("X-Mock-Response") == "true"


# --- 온보딩 ---------------------------------------------------------------


def test_onboarding_returns_stable_user_id(client):
    payload = {
        "gender": "F",
        "age_band": 20,
        "atmosphere_tags": ["조용한", "감성적인"],
        "purpose_tags": ["데이트", "작업"],
        "budget_band": 3,
        "weather_sensitivity": 3,
    }
    first = client.post("/api/onboarding", json=payload).json()["user_id"]
    second = client.post("/api/onboarding", json=payload).json()["user_id"]
    assert first.startswith("u_") and first == second


def test_onboarding_rejects_unknown_tag(client):
    r = client.post(
        "/api/onboarding",
        json={
            "gender": "F", "age_band": 20,
            "atmosphere_tags": ["힙한"],          # 고정 어휘 밖
            "purpose_tags": ["데이트"], "budget_band": 3, "weather_sensitivity": 2,
        },
    )
    assert r.status_code == 422


# --- 컨텍스트 -------------------------------------------------------------


def test_context_now(client):
    r = client.get("/api/context/now", params={"lat": 37.5340, "lng": 126.9946})
    assert r.status_code == 200
    body = r.json()
    assert 1 <= body["pm25_grade"] <= 4
    assert body["hotspot"] is not None          # 이태원은 지점 반경 안


def test_context_outside_hotspot_is_null_not_zero(client):
    """지점 반경 밖이면 혼잡도는 null이다. 0이나 '여유'로 채우지 않는다."""
    r = client.get("/api/context/now", params={"lat": 37.5205, "lng": 126.9760})
    body = r.json()
    assert body["hotspot"] is None
    assert body["congest_now"] is None
    assert body["congest_forecast_at_visit"] is None


# --- 추천 -----------------------------------------------------------------


def test_recommend_shape(client, recommend_payload):
    r = client.post("/api/recommend", json=recommend_payload)
    assert r.status_code == 200
    body = r.json()

    RecommendResponse.model_validate(body)      # 계약 그대로인지 재검증
    assert 3 <= len(body["results"]) <= 5
    assert isinstance(body["log_id"], int)

    first = body["results"][0]
    for key in ("poi_id", "name", "category", "lat", "lng", "distance_m",
                "score", "score_breakdown", "reason", "evidence",
                "is_exploration", "explain_mode"):
        assert key in first


def test_recommend_is_deterministic(client, recommend_payload):
    """같은 요청은 항상 같은 결과. 서버를 재시작해도 C의 화면이 흔들리지 않는다."""
    a = client.post("/api/recommend", json=recommend_payload).json()
    b = client.post("/api/recommend", json=recommend_payload).json()
    assert a == b


def test_recommend_sorted_by_score_except_exploration(client, recommend_payload):
    results = client.post("/api/recommend", json=recommend_payload).json()["results"]
    ranked = [r["score"] for r in results if not r["is_exploration"]]
    assert ranked == sorted(ranked, reverse=True)


def test_exploration_slot_present(client, recommend_payload):
    """탐색 슬롯 1개. 인기 쏠림 방지 + 랭킹 학습 로그 다양성 (ROLE_B §6.7)."""
    results = client.post("/api/recommend", json=recommend_payload).json()["results"]
    assert sum(1 for r in results if r["is_exploration"]) == 1


def test_live_terms_omitted_outside_hotspot(client, recommend_payload):
    """핫스팟 밖 POI는 live_segment/crowd **키 자체가 없다.**

    0이 들어가 있으면 C가 그걸 '실시간 점수 0점'으로 그리게 되고,
    엔진에서는 그 POI가 구조적으로 전멸한다 (ROLE_B §1.3 · §6.4).
    """
    results = client.post("/api/recommend", json=recommend_payload).json()["results"]
    breakdowns = [r["score_breakdown"] for r in results]

    assert any("live_segment" not in b for b in breakdowns), (
        "핫스팟 밖 POI가 응답에 하나도 없다 — C가 이 경로를 테스트할 수 없다"
    )
    for b in breakdowns:
        assert {"segment", "purpose", "taste", "context", "quality", "distance"} <= set(b)
        # 있는 경우엔 값이 있어야 하고, 없으면 키가 아예 없어야 한다 (null 금지)
        assert b.get("live_segment") is None or isinstance(b["live_segment"], float)
        if "live_segment" in b:
            assert b["live_segment"] is not None


def test_scores_comparable_across_hotspot_boundary(client, recommend_payload):
    """핫스팟 안/밖 POI 점수가 같은 스케일에 있어야 한다 — 재정규화 확인."""
    results = client.post("/api/recommend", json=recommend_payload).json()["results"]
    inside = [r["score"] for r in results if "live_segment" in r["score_breakdown"]]
    outside = [r["score"] for r in results if "live_segment" not in r["score_breakdown"]]
    if inside and outside:
        assert abs(max(inside) - max(outside)) < 0.25


def test_never_returns_empty_even_when_filters_are_harsh(client):
    """9명 · 예산 1밴드 · 외곽 좌표 — 하드필터가 다 걸려도 빈 배열을 주지 않는다."""
    r = client.post(
        "/api/recommend",
        json={
            "user_id": "u_edge", "purpose": "회식", "party_size": 9,
            "budget_band": 1, "location": {"lat": 37.5205, "lng": 126.9760},
            "visit_at": "2026-08-03T20:00:00+09:00",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert len(body["results"]) >= 1
    assert body["low_confidence"] is True or body["radius_expanded"] is True


@pytest.mark.parametrize("purpose", ["데이트", "친구모임", "혼자", "가족", "작업", "회식"])
def test_all_purposes_work(client, recommend_payload, purpose):
    payload = {**recommend_payload, "purpose": purpose}
    r = client.post("/api/recommend", json=payload)
    assert r.status_code == 200
    assert len(r.json()["results"]) >= 1


@pytest.mark.parametrize("state", ["맑음", "비", "미세먼지나쁨", "폭염한파"])
def test_all_weather_states_render(recommend_payload, state):
    """네 가지 날씨 상태에서 모두 결과가 나온다. C가 배너 4종을 그려볼 수 있다."""
    body = _recommend_with_weather(recommend_payload, state)
    assert 1 <= len(body.results) <= 5


def test_rain_hardcut_removes_outdoor_places(recommend_payload):
    """비 60% 예보면 야외 노출도 0.7 초과 POI는 후보에서 빠진다 (ROLE_B §6.1)."""
    from app.mock_data import FALLBACK_POIS

    body = _recommend_with_weather(recommend_payload, "비")
    assert body.context.rain_prob >= 0.6

    exposure = {p["poi_id"]: p["outdoor_exposure"] for p in FALLBACK_POIS}
    for r in body.results:
        assert exposure[r.poi_id] <= 0.7


def _recommend_with_weather(payload: dict, state: str):
    """날씨를 고정한 목 설정으로 추천을 만든다. 환경변수 캐시를 건드리지 않는다."""
    from app.config import Settings
    from app.mock_data import build_recommendation
    from app.schemas import RecommendRequest

    settings = Settings(mock_mode=True, mock_weather_state=state, seed_path="__none__")
    return build_recommendation(RecommendRequest.model_validate(payload), settings)


def test_invalid_purpose_is_422(client, recommend_payload):
    r = client.post("/api/recommend", json={**recommend_payload, "purpose": "산책"})
    assert r.status_code == 422


# --- 피드백 · 상세 --------------------------------------------------------


def test_feedback_roundtrip(client, recommend_payload):
    log_id = client.post("/api/recommend", json=recommend_payload).json()["log_id"]
    r = client.post(
        "/api/feedback",
        json={"log_id": log_id, "clicked": ["mock_0001"],
              "selected": "mock_0001", "feedback": 5},
    )
    assert r.status_code == 204


def test_feedback_unknown_log_is_404(client):
    assert client.post("/api/feedback", json={"log_id": 1}).status_code == 404


def test_poi_detail(client, recommend_payload):
    poi_id = client.post("/api/recommend", json=recommend_payload).json()["results"][0]["poi_id"]
    r = client.get(f"/api/poi/{poi_id}")
    assert r.status_code == 200
    assert r.json()["poi_id"] == poi_id


def test_poi_detail_404(client):
    assert client.get("/api/poi/nope").status_code == 404


# --- /health 의 db_reason (2026-08-28) ----------------------------------------
#
# `db:false`가 "DSN이 틀렸다"인지 "아직 목 모드다"인지 구분이 안 돼서 C가
# 설정을 의심하며 없는 버그를 쫓았다. 전환일에는 더 위험하다 — MOCK_MODE를
# 내리기 전까지 DSN이 맞는지 알 방법이 없으면 내리고 나서야 알게 된다.


def test_목모드에서도_이유를_말한다(client):
    body = client.get("/health").json()
    assert body["mode"] == "mock"
    assert body["db_reason"], "db가 그 값인 이유가 없다"
    assert "MOCK_MODE=true" in body["db_reason"]


def test_DSN이_없으면_그렇게_말한다(client):
    """설정이 안 들어간 것과 틀린 것을 구분할 수 있어야 한다."""
    body = client.get("/health").json()
    # 테스트 환경엔 DATABASE_URL이 없다
    assert "DATABASE_URL 없음" in body["db_reason"] or "DSN 연결" in body["db_reason"]


def test_health_응답이_계약_필드를_전부_갖는다(client):
    body = client.get("/health").json()
    assert set(body) >= {"status", "db", "db_reason", "mode", "version"}
    assert body["status"] == "ok"      # DB가 죽어도 200·ok다 (UptimeRobot 때문)


# --- 결과 순서 (2026-08-30) ---------------------------------------------------
#
# live 경로가 LLM이 반환한 순서를 그대로 화면에 실었다. 그래서 배포본에서
# 1번 카드 0.8603 · 4번 카드 0.8808 이 나왔다 — `?debug=1`이면 그대로 보인다.
# 목 경로는 처음부터 점수 순이었다. 두 경로의 순서 규칙이 갈리면 목으로 만든
# 화면이 실데이터에서 다르게 보이므로, 계약을 여기에 못박는다.


def _sorted_desc(scores: list[float]) -> bool:
    return all(a >= b for a, b in zip(scores, scores[1:]))


def test_결과는_점수_내림차순이다(client, recommend_payload):
    body = client.post("/api/recommend", json=recommend_payload).json()
    # 탐색 슬롯은 점수와 무관하게 맨 뒤다 (ROLE_B §6.7). 그것만 빼고 본다.
    ranked = [r["score"] for r in body["results"] if not r["is_exploration"]]
    assert len(ranked) >= 3
    assert _sorted_desc(ranked), f"점수 순이 아니다: {ranked}"


def test_탐색_슬롯은_있다면_맨_뒤_한_건뿐이다(client, recommend_payload):
    body = client.post("/api/recommend", json=recommend_payload).json()
    flags = [r["is_exploration"] for r in body["results"]]
    assert flags.count(True) <= 1
    if True in flags:
        assert flags[-1] is True
