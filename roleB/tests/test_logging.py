"""추천 로그 (B4-4).

**노출됐지만 선택되지 않은 후보를 남기는가.** 이게 없으면 로그를 몇 달 모아도
랭킹 모델을 학습할 수 없다 — positive만 있고 negative가 없는 데이터셋이 된다.
6주 안에 학습은 안 하지만 구조는 지금 만든다. 나중에 만들면 그때부터 0건이다.
"""

from __future__ import annotations

import json

from app.services.logging_svc import (
    build_candidate_rows,
    context_snapshot,
    record_feedback,
    write_recommendation_log,
)

SCORED = [
    (0.87, {"poi_id": "p_001"}, {"segment_affinity": 0.9, "purpose_match": 0.8}, 0.12),
    (0.85, {"poi_id": "p_002"}, {"segment_affinity": 0.7, "purpose_match": 0.9}, 0.20),
    (0.41, {"poi_id": "p_047"}, {"segment_affinity": 0.3, "purpose_match": 0.4}, 0.90),
]


# --- candidates ---------------------------------------------------------------


def test_unshown_candidates_are_kept():
    rows = build_candidate_rows(SCORED, shown_ids={"p_001", "p_002"})
    assert [r["poi_id"] for r in rows] == ["p_001", "p_002", "p_047"]
    assert [r["shown"] for r in rows] == [True, True, False]


def test_rank_starts_at_one_and_follows_order():
    rows = build_candidate_rows(SCORED, shown_ids=set())
    assert [r["rank"] for r in rows] == [1, 2, 3]


def test_terms_are_kept_for_rescoring():
    """최종 점수만 남기면 가중치를 바꿨을 때 과거 로그를 다시 채점할 수 없다."""
    rows = build_candidate_rows(SCORED, shown_ids=set())
    assert rows[0]["terms"] == {"segment_affinity": 0.9, "purpose_match": 0.8}
    assert rows[0]["distance_penalty"] == 0.12


# --- context 스냅샷 -------------------------------------------------------------


def test_coordinates_are_coarsened():
    """개인의 이동 궤적이 로그에 남지 않게 한다 (PLAN §8.3)."""
    snap = context_snapshot(
        {"lat": 37.534012345, "lng": 126.994678, "purpose": "데이트"},
        {"rain_prob": 0.6, "pm25_grade": 2, "feels_like": 27.4, "visit_hour": 19},
        {"weather_source": "citydata"},
    )
    assert snap["lat"] == 37.534
    assert snap["lng"] == 126.995
    assert snap["weather"]["rain_prob"] == 0.6
    assert snap["weather_source"] == "citydata"


def test_snapshot_is_json_serializable():
    """JSONB로 들어간다. 직렬화가 안 되면 로그가 통째로 날아간다."""
    snap = context_snapshot({"purpose": "데이트"}, {"rain_prob": 0.1}, {})
    json.dumps(snap, ensure_ascii=False)


# --- INSERT -------------------------------------------------------------------


class FakeExec:
    def __init__(self, user_exists: bool = True, insert_result=None, fail: bool = False):
        self.user_exists = user_exists
        self.insert_result = insert_result if insert_result is not None else [{"log_id": 55123}]
        self.fail = fail
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, sql, params):
        self.calls.append((sql, dict(params)))
        if self.fail:
            raise RuntimeError("DB가 흔들렸다")
        if "FROM user_profile" in sql:
            return [{"?column?": 1}] if self.user_exists else []
        return self.insert_result


def _write(ex):
    return write_recommendation_log(
        ex,
        user_id="u_1",
        context={"purpose": "데이트"},
        candidates=[{"poi_id": "p_001", "shown": True}],
        explain_mode="template",
        latency_ms=42,
    )


def test_log_id_is_returned():
    assert _write(FakeExec()) == 55123


def test_unknown_user_is_nulled_not_rejected():
    """user_id는 user_profile을 참조한다. 온보딩을 건너뛴 사용자도 로그는 남아야 한다."""
    ex = FakeExec(user_exists=False)
    assert _write(ex) == 55123
    insert_params = ex.calls[-1][1]
    assert insert_params["user_id"] is None


def test_known_user_is_kept():
    ex = FakeExec(user_exists=True)
    _write(ex)
    assert ex.calls[-1][1]["user_id"] == "u_1"


def test_failure_does_not_raise():
    """로그는 부수 효과다. 실패했다고 추천을 500으로 만들지 않는다."""
    assert _write(FakeExec(fail=True)) is None


def test_latency_and_mode_are_recorded():
    ex = FakeExec()
    _write(ex)
    params = ex.calls[-1][1]
    assert params["latency_ms"] == 42
    assert params["explain_mode"] == "template"


# --- 피드백 --------------------------------------------------------------------


def test_feedback_returns_false_when_log_missing():
    assert record_feedback(lambda s, p: [], log_id=1, clicked=[], selected=None, feedback=None) is False


def test_feedback_returns_true_when_updated():
    ok = record_feedback(
        lambda s, p: [{"log_id": 7}], log_id=7, clicked=["p_1"], selected="p_1", feedback=5
    )
    assert ok is True


def test_empty_fields_are_sent_as_null_for_coalesce():
    """C는 클릭 → 선택 → 만족도를 나눠 보낸다. 빈 값이 앞선 기록을 지우면 안 된다."""
    captured: dict = {}

    def ex(sql, params):
        captured.update(params)
        assert "COALESCE" in sql
        return [{"log_id": 7}]

    record_feedback(ex, log_id=7, clicked=[], selected=None, feedback=4)
    assert captured["clicked"] is None
    assert captured["selected"] is None
    assert captured["feedback"] == 4
