"""레이트 리밋 — IP당 분당 N회 (B5-6).

보호 대상은 서버가 아니라 **무료 LLM 쿼터**다. 한 사람이 새로고침을 연타하면
그날의 설명 생성 예산이 마른다. 그래서 추천 엔드포인트에만 건다.
`/health`는 절대 막지 않는다 — UptimeRobot이 5분마다 치는 슬립 방지 핑이다.

프로세스 안의 슬라이딩 윈도우다. Render Free는 인스턴스가 하나라 이걸로 충분하고,
Redis를 붙이면 그 자체가 §0.1(결제수단 없는 무료)을 시험하게 된다.
인스턴스가 재시작되면 초기화되지만, 그건 슬립에서 깨어난 직후라 어차피 한산하다.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

WINDOW_SECONDS = 60.0

# 이 경로만 센다. 나머지는 싸거나(상세) 막으면 안 된다(헬스체크).
LIMITED_PATHS = ("/api/recommend",)


class SlidingWindow:
    def __init__(self, window: float = WINDOW_SECONDS) -> None:
        self._window = window
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str, limit: int, now: float | None = None) -> bool:
        if limit <= 0:
            return True                     # 0 이하면 제한 없음
        t = time.monotonic() if now is None else now
        with self._lock:
            q = self._hits[key]
            cutoff = t - self._window
            while q and q[0] <= cutoff:
                q.popleft()
            if len(q) >= limit:
                return False
            q.append(t)
            return True

    def retry_after(self, key: str, now: float | None = None) -> int:
        """다음 요청까지 남은 초. 429 응답의 Retry-After에 쓴다."""
        t = time.monotonic() if now is None else now
        with self._lock:
            q = self._hits.get(key)
            if not q:
                return 0
            return max(1, int(self._window - (t - q[0])) + 1)

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


limiter = SlidingWindow()


def client_key(headers, client_host: str | None) -> str:
    """Render는 프록시 뒤에 있다. `X-Forwarded-For`의 **첫 항목**이 실제 클라이언트다.

    마지막 항목을 쓰면 모든 사용자가 프록시 IP 하나로 뭉쳐 서로를 막게 된다.
    """
    forwarded = headers.get("x-forwarded-for")
    if forwarded:
        first = forwarded.split(",")[0].strip()
        if first:
            return first
    return client_host or "unknown"


def is_limited(path: str) -> bool:
    return any(path.startswith(p) for p in LIMITED_PATHS)
