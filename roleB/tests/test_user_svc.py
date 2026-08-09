"""온보딩 프로필 (B4-5).

`taste_vector`가 없을 때 무엇을 하는가가 이 테스트의 핵심이다.
빈 벡터나 영벡터를 넣으면 모든 POI와의 코사인이 0이 되어 "취향이 정반대"가 된다.
**NULL이어야 취향 축이 조용히 쉰다.**
"""

from __future__ import annotations

from app.services.user_svc import build_taste_vector, make_user_id, upsert_profile


# --- user_id ------------------------------------------------------------------


def test_same_answers_give_same_id():
    """C가 목/실 모드를 오가도 로컬 저장값이 깨지지 않아야 한다."""
    args = ("F", 20, ["조용한", "감성적인"], ["데이트"], 3, 2)
    assert make_user_id(*args) == make_user_id(*args)


def test_tag_order_does_not_matter():
    a = make_user_id("F", 20, ["조용한", "감성적인"], ["데이트"], 3, 2)
    b = make_user_id("F", 20, ["감성적인", "조용한"], ["데이트"], 3, 2)
    assert a == b


def test_different_answers_give_different_ids():
    a = make_user_id("F", 20, ["조용한"], ["데이트"], 3, 2)
    b = make_user_id("F", 20, ["조용한"], ["데이트"], 3, 3)   # 날씨 민감도만 다름
    assert a != b


def test_id_has_stable_shape():
    uid = make_user_id("M", 30, ["활기찬"], ["회식"], 2, 1)
    assert uid.startswith("u_") and len(uid) == 8


# --- taste_vector -------------------------------------------------------------


def test_no_tags_means_no_vector():
    assert build_taste_vector(lambda s, p: [], []) is None


def test_unmatched_tags_mean_no_vector():
    """tag_embedding이 비어 있으면 NULL이다. 영벡터를 만들지 않는다."""
    assert build_taste_vector(lambda s, p: [{"taste_vector": None, "matched": 0}], ["조용한"]) is None


def test_matched_tags_return_the_average():
    ex = lambda s, p: [{"taste_vector": "<vec>", "matched": 2}]  # noqa: E731
    assert build_taste_vector(ex, ["조용한", "데이트"]) == "<vec>"


def test_missing_table_does_not_break_onboarding():
    """002 마이그레이션이 아직 적용되지 않았을 수 있다. 온보딩은 계속돼야 한다."""

    def ex(sql, params):
        raise RuntimeError('relation "tag_embedding" does not exist')

    assert build_taste_vector(ex, ["조용한"]) is None


# --- upsert -------------------------------------------------------------------


def test_upsert_sends_tags_and_vector():
    calls: list[tuple[str, dict]] = []

    def ex(sql, params):
        calls.append((sql, dict(params)))
        # 주석에도 'tag_embedding'이 나온다. SELECT 여부로 갈라야 한다
        if sql.lstrip().startswith("SELECT"):
            return [{"taste_vector": "<vec>", "matched": 3}]
        return [{"user_id": params["user_id"]}]

    upsert_profile(
        ex,
        user_id="u_abc123",
        gender="F",
        age_band=20,
        taste_tags=["조용한", "감성적인", "데이트"],
        weather_sensitivity=3,
    )
    insert = calls[-1][1]
    assert insert["taste_tags"] == ["조용한", "감성적인", "데이트"]
    assert insert["taste_vector"] == "<vec>"
    assert insert["weather_sensitivity"] == 3


def test_upsert_does_not_wipe_existing_vector():
    """tag_embedding이 잠시 비어 있는 사이 재제출하면 애써 만든 벡터가 날아간다."""
    seen: list[str] = []

    def ex(sql, params):
        seen.append(sql)
        # 주석에도 'tag_embedding'이 나온다. SELECT 여부로 갈라야 한다
        if sql.lstrip().startswith("SELECT"):
            return [{"taste_vector": None, "matched": 0}]
        return [{"user_id": params["user_id"]}]

    upsert_profile(
        ex, user_id="u_x", gender="M", age_band=30,
        taste_tags=["조용한"], weather_sensitivity=2,
    )
    assert "COALESCE(EXCLUDED.taste_vector, user_profile.taste_vector)" in seen[-1]
