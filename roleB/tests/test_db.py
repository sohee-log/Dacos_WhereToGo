"""커넥션 풀 테스트 (B2-1).

여기서 보는 것은 "DB가 없을 때 어떻게 실패하는가"다. 정상 경로는
test_live_db.py가 실제 DB로 확인한다.

**DB가 죽었을 때 500이 아니라 503이어야 한다.** 500은 "우리 코드가 터졌다"이고
503은 "의존 서비스가 없다"다. Render Free + Supabase Free 조합에서 후자는
드물지 않게 일어나고, 둘을 섞으면 원인 파악에 시간을 버린다.
"""

from __future__ import annotations

import time

import pytest

from app.config import Settings
from app.db import Database, DatabaseUnavailable

pytest.importorskip("psycopg_pool")

# 아무도 듣지 않는 포트. 연결이 성립할 수 없다.
DEAD_DSN = "postgresql://postgres:nope@127.0.0.1:59998/nope"


def _settings(**over) -> Settings:
    base = {
        "mock_mode": False,
        "database_url": DEAD_DSN,
        "db_pool_min": 0,
        "db_acquire_timeout": 0.5,
        "db_pool_timeout": 0.5,
    }
    return Settings(**{**base, **over})


# --- 풀을 열지 않는 조건 -------------------------------------------------------


def test_mock_mode_does_not_open_pool():
    db = Database(_settings(mock_mode=True))
    db.open()
    assert db.available is False
    assert db.healthy() is False


def test_missing_dsn_does_not_open_pool():
    db = Database(_settings(database_url=None))
    db.open()
    assert db.available is False


def test_queries_without_pool_raise_unavailable():
    db = Database(_settings(mock_mode=True))
    db.open()
    with pytest.raises(DatabaseUnavailable):
        db.fetch_all("SELECT 1")


# --- DB가 죽었을 때 ------------------------------------------------------------


def test_open_does_not_block_on_dead_db():
    """기동이 DB에 걸리면 헬스체크가 막히고 UptimeRobot이 서비스를 죽은 것으로 본다."""
    db = Database(_settings())
    started = time.perf_counter()
    db.open()
    elapsed = time.perf_counter() - started
    try:
        assert elapsed < 2.0
        assert db.available is True          # 풀 객체는 있다. 연결은 아직 없다
    finally:
        db.close()


def test_dead_db_raises_unavailable_quickly():
    """PoolTimeout이 그대로 새어 나가면 라우터가 503을 만들 수 없다."""
    db = Database(_settings())
    db.open()
    try:
        started = time.perf_counter()
        with pytest.raises(DatabaseUnavailable):
            db.fetch_all("SELECT 1")
        assert time.perf_counter() - started < 3.0
    finally:
        db.close()


def test_health_returns_false_instead_of_raising():
    db = Database(_settings())
    db.open()
    try:
        assert db.healthy() is False
    finally:
        db.close()


# --- 왕복 줄이기 (2026-08-30) -------------------------------------------------
#
# 배포본 추천이 캐시 히트에도 2,954ms였다. 원인은 쿼리 실행 시간이 아니라
# **왕복 횟수**였다 — Render(싱가포르) → Supabase(서울) 왕복이 실측 88ms인데
# DB 호출 한 번이 왕복을 3회 썼다: `check`의 SELECT 1 · 실제 쿼리 · COMMIT.
# 추천은 DB를 10번 부르므로 10 × 3 × 88ms ≈ 2.6초다.
#
# 그래서 `check`를 `max_idle`로, 트랜잭션을 `autocommit`으로 바꿨다. 대신
# 죽은 커넥션을 집어오는 드문 경우를 `_run`이 **읽기에 한해** 재시도한다.
# 쓰기를 재시도하지 않는 것이 이 설계의 핵심이다.


def test_풀은_대여마다_확인하지_않는다():
    """`check`가 다시 붙으면 요청당 왕복이 10회 늘어난다."""
    db = Database(_settings())
    db.open()
    try:
        assert db._pool.kwargs.get("autocommit") is True, "COMMIT 왕복이 되살아났다"
        assert db._pool._check is None, "check가 다시 붙었다 — 왕복 10회가 늘어난다"
        assert db._pool.max_idle <= 300, "유휴 커넥션을 너무 오래 들고 있다"
    finally:
        db.close()


@pytest.mark.parametrize(
    "sql, read_only",
    [
        ("SELECT 1", True),
        ("  \n  select poi_id from poi", True),
        ("-- 주석 한 줄\nSELECT 1", True),
        ("INSERT INTO recommendation_log (user_id) VALUES (%(u)s) RETURNING log_id", False),
        ("UPDATE explanation_cache SET hit_count = hit_count + 1 RETURNING payload", False),
        ("DELETE FROM query_vector_cache", False),
        # WITH 는 `WITH x AS (...) INSERT ...` 가 가능하다. 읽기로 보지 않는다.
        ("WITH x AS (SELECT 1) SELECT * FROM x", False),
    ],
)
def test_재시도_대상은_SELECT_뿐이다(sql, read_only):
    """`UPDATE ... RETURNING`도 결과를 돌려준다 — '결과를 읽는가'로는 못 가른다.

    쓰기를 재시도하면 '닿기 전에 끊긴 것'과 '실행됐는데 응답이 유실된 것'을
    구분할 수 없어 recommendation_log에 한 요청이 두 줄 남는다. 조용히 틀린
    데이터보다 503이 낫다.
    """
    from app.db import _is_read_only

    assert _is_read_only(sql) is read_only


def test_쓰기는_커넥션이_죽어도_재시도하지_않는다(monkeypatch):
    db = Database(_settings())
    db.open()
    try:
        from psycopg import OperationalError

        tries = {"n": 0}

        def boom(*a, **kw):
            tries["n"] += 1
            raise OperationalError("커넥션이 끊겼다")

        monkeypatch.setattr(db, "_once", boom)

        with pytest.raises(DatabaseUnavailable):
            db.fetch_all("INSERT INTO recommendation_log (user_id) VALUES ('u') RETURNING log_id")
        assert tries["n"] == 1, "쓰기를 재시도했다"

        tries["n"] = 0
        with pytest.raises(DatabaseUnavailable):
            db.fetch_all("SELECT 1")
        assert tries["n"] == 2, "읽기는 한 번 재시도해야 한다"
    finally:
        db.close()
