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
