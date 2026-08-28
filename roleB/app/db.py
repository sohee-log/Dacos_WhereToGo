"""DB 커넥션 풀 (B2-1).

이 파일이 지키는 것은 세 가지다.

1. **DB가 없어도 앱은 뜬다.** `MOCK_MODE=true`이거나 `DATABASE_URL`이 비어 있으면
   풀을 아예 만들지 않는다. W1의 계약(C가 B를 기다리지 않는다)을 W2에도 유지한다.
2. **Render 재시작·Supabase 유휴 끊김을 견딘다.** Render Free는 15분 무접속이면
   슬립하고, 깨어날 때 프로세스가 새로 뜬다. 그때 남아 있던 커넥션은 이미 죽어 있다.
   `check=ConnectionPool.check_connection`이 대여 직전에 죽은 커넥션을 걸러낸다.
3. **기동을 DB에 걸지 않는다.** `pool.open(wait=False)`다. DB가 느리다고 헬스체크가
   막히면 UptimeRobot이 서비스를 죽은 것으로 판정한다.

커넥션 상한은 Supabase Free 기준으로 좁게 잡는다 (`db_pool_max`, 기본 5).
무료 티어의 병목은 CPU가 아니라 커넥션 수다.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from typing import Any

from app.config import Settings

log = logging.getLogger("wheretogo.db")

try:  # psycopg는 W2부터 필요하다. 없으면 목 모드로만 돈다.
    import psycopg
    from psycopg import OperationalError
    from psycopg.rows import dict_row
    from psycopg_pool import ConnectionPool, PoolTimeout

    PSYCOPG_AVAILABLE = True
    # "DB에 닿지 못했다"로 볼 예외들. 문법 오류 같은 프로그래밍 실수는 여기 없다 —
    # 그건 503이 아니라 500이어야 고쳐진다.
    CONNECTION_ERRORS: tuple[type[BaseException], ...] = (PoolTimeout, OperationalError)
except ImportError:  # pragma: no cover - 배포 환경에는 항상 설치된다
    PSYCOPG_AVAILABLE = False
    CONNECTION_ERRORS = ()


class DatabaseUnavailable(RuntimeError):
    """DB를 써야 하는 경로인데 풀이 없거나 죽었다.

    이 예외를 삼켜서 목 응답으로 대체하지 않는다. 조용히 목으로 흘러가면
    "실데이터로 동작한다"는 게이트가 거짓으로 통과한다.
    """


class Database:
    """psycopg_pool 얇은 래퍼. 라우터는 이 객체의 fetch_* 만 쓴다."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._pool: Any = None

    # --- 수명주기 ----------------------------------------------------------

    def open(self) -> None:
        """앱 기동 시 1회. 실패해도 예외를 올리지 않는다 (앱은 떠야 한다)."""
        if self._pool is not None:
            return

        reason = self._skip_reason()
        if reason:
            log.info("DB 풀을 열지 않는다: %s", reason)
            return

        try:
            self._pool = ConnectionPool(
                conninfo=self._settings.database_url or "",
                min_size=self._settings.db_pool_min,
                max_size=self._settings.db_pool_max,
                timeout=self._settings.db_pool_timeout,
                # 대여 직전 살아 있는 커넥션인지 확인한다. Supabase가 유휴 커넥션을
                # 끊어도 첫 요청이 죽지 않는다.
                check=ConnectionPool.check_connection,
                kwargs={
                    "row_factory": dict_row,
                    "connect_timeout": int(self._settings.db_pool_timeout),
                    "application_name": "wheretogo-api",
                    # 무료 티어에서 느린 쿼리 하나가 워커를 잡아먹지 않게 한다.
                    # 목표 응답은 300ms다 (ROLE_B W4 B4-1).
                    "options": f"-c statement_timeout={self._settings.db_statement_timeout_ms}",
                },
                open=False,
                name="wheretogo",
            )
            # wait=False — 기동을 DB 응답에 걸지 않는다.
            self._pool.open(wait=False)
            log.info(
                "DB 풀 오픈 (min=%s max=%s)",
                self._settings.db_pool_min,
                self._settings.db_pool_max,
            )
        except Exception as exc:  # pragma: no cover - 환경 의존
            self._pool = None
            log.warning("DB 풀 오픈 실패: %s", exc)

    def close(self) -> None:
        if self._pool is not None:
            self._pool.close()
            self._pool = None

    def _skip_reason(self) -> str | None:
        if not PSYCOPG_AVAILABLE:
            return "psycopg 미설치"
        if self._settings.mock_mode:
            return "MOCK_MODE=true"
        if not self._settings.database_url:
            return "DATABASE_URL 없음"
        return None

    # --- 상태 --------------------------------------------------------------

    @property
    def available(self) -> bool:
        return self._pool is not None

    def healthy(self) -> bool:
        """`/health`용. 예외를 밖으로 내보내지 않는다."""
        if self._pool is None:
            return False
        try:
            return self.fetch_one("SELECT 1 AS ok") is not None
        except Exception as exc:  # pragma: no cover - 환경 의존
            log.warning("헬스체크 쿼리 실패: %s", exc)
            return False

    # --- 쿼리 --------------------------------------------------------------

    def _run(
        self,
        sql: str,
        params: Mapping[str, Any] | Sequence[Any] | None,
        *,
        fetch: bool,
    ) -> Any:
        """모든 쿼리가 지나는 자리.

        커넥션을 못 얻거나 연결이 끊긴 것은 `DatabaseUnavailable`로 바꾼다.
        그래야 라우터가 503으로 답할 수 있다. 이 변환이 없으면 DB가 죽었을 때
        사용자가 `db_pool_timeout`만큼 기다린 뒤 500을 받는다.
        SQL 문법 오류 같은 것은 그대로 올린다 — 500이어야 고쳐진다.
        """
        if self._pool is None:
            raise DatabaseUnavailable(self._skip_reason() or "풀이 열려 있지 않다")
        try:
            with self._pool.connection(
                timeout=self._settings.db_acquire_timeout
            ) as conn, conn.cursor() as cur:
                cur.execute(sql, params)
                return list(cur.fetchall()) if fetch else cur.rowcount
        except CONNECTION_ERRORS as exc:
            raise DatabaseUnavailable(f"DB에 닿지 못했다: {exc}") from exc

    def fetch_all(
        self, sql: str, params: Mapping[str, Any] | Sequence[Any] | None = None
    ) -> list[dict[str, Any]]:
        return self._run(sql, params, fetch=True)

    def fetch_one(
        self, sql: str, params: Mapping[str, Any] | Sequence[Any] | None = None
    ) -> dict[str, Any] | None:
        rows = self.fetch_all(sql, params)
        return rows[0] if rows else None

    def execute(
        self, sql: str, params: Mapping[str, Any] | Sequence[Any] | None = None
    ) -> int:
        return self._run(sql, params, fetch=False)


# 목 모드에서 DSN이 실제로 붙는지 확인한다 (풀은 열지 않는다).
#
# 왜 필요한가 — `/health`의 `db`는 `MOCK_MODE=false`일 때만 검사했다. 그래서
# DATABASE_URL을 정확히 넣어도 목 모드에서는 **무조건 db:false**였고, C가 설정을
# 의심하며 없는 버그를 쫓았다(2026-08-28). 더 나쁜 건 전환일이다 —
# MOCK_MODE를 내리기 **전까지 DSN이 맞는지 알 방법이 없어서**, 내리고 나서야
# 틀린 걸 발견하게 된다. 그때는 이미 사용자에게 503이 나가는 중이다.
#
# 풀을 열지 않고 한 번짜리 커넥션으로만 본다. 목 모드의 계약("풀을 열지 않는다")을
# 그대로 지키면서 사실만 확인한다.
DSN_PROBE_TIMEOUT = 3       # /health가 느려지면 UptimeRobot이 슬립 방지에 실패한다


def probe_dsn(settings: Settings) -> tuple[bool, str]:
    """(닿는가, 사람이 읽을 이유). 예외를 밖으로 내보내지 않는다."""
    if not PSYCOPG_AVAILABLE:
        return False, "psycopg 미설치"
    if not settings.database_url:
        return False, "DATABASE_URL 없음"
    try:
        with psycopg.connect(
            settings.database_url, connect_timeout=DSN_PROBE_TIMEOUT
        ) as conn:
            conn.execute("SELECT 1")
        return True, "DSN 연결 OK"
    except Exception as exc:  # noqa: BLE001 - 헬스체크는 어떤 경우에도 200이다
        # 원인이 보여야 한다. DSN에 비밀번호가 들어 있으므로 **메시지만** 남긴다.
        head = str(exc).strip().splitlines()[0][:160]
        log.warning("DSN 사전 점검 실패: %s", head)
        return False, f"DSN 연결 실패: {head}"


# 앱 전역 인스턴스. main.py의 lifespan이 open/close 한다.
_db: Database | None = None


def init_db(settings: Settings) -> Database:
    global _db
    _db = Database(settings)
    _db.open()
    return _db


def get_db() -> Database:
    """FastAPI 의존성. 풀이 없어도 객체는 준다 (available=False)."""
    if _db is None:
        raise DatabaseUnavailable("init_db()가 호출되지 않았다")
    return _db


def shutdown_db() -> None:
    global _db
    if _db is not None:
        _db.close()
        _db = None
