"""레이트 리밋 (B5-6).

보호 대상은 서버가 아니라 **무료 LLM 쿼터**다. 그래서 추천에만 걸고
`/health`는 절대 막지 않는다 — UptimeRobot의 핑이 429가 되면 Render가 잠든다.
"""

from __future__ import annotations

from app.config import get_settings
from app.ratelimit import SlidingWindow, client_key, is_limited


# --- 윈도우 --------------------------------------------------------------------


def test_allows_up_to_the_limit():
    w = SlidingWindow()
    assert all(w.allow("ip", 3, now=100.0) for _ in range(3))
    assert w.allow("ip", 3, now=100.0) is False


def test_window_slides():
    w = SlidingWindow(window=60.0)
    for _ in range(3):
        w.allow("ip", 3, now=100.0)
    assert w.allow("ip", 3, now=159.0) is False       # 아직 창 안
    assert w.allow("ip", 3, now=161.0) is True        # 창 밖으로 나갔다


def test_ips_are_counted_separately():
    w = SlidingWindow()
    for _ in range(3):
        w.allow("a", 3, now=100.0)
    assert w.allow("a", 3, now=100.0) is False
    assert w.allow("b", 3, now=100.0) is True


def test_zero_limit_means_unlimited():
    w = SlidingWindow()
    assert all(w.allow("ip", 0, now=100.0) for _ in range(50))


def test_retry_after_is_at_least_one_second():
    w = SlidingWindow(window=60.0)
    w.allow("ip", 1, now=100.0)
    assert 1 <= w.retry_after("ip", now=159.0) <= 61
    assert w.retry_after("없는ip") == 0


# --- 클라이언트 식별 ------------------------------------------------------------


def test_forwarded_for_uses_the_first_entry():
    """마지막을 쓰면 모든 사용자가 프록시 IP 하나로 뭉쳐 서로를 막는다."""
    headers = {"x-forwarded-for": "203.0.113.7, 10.0.0.1, 10.0.0.2"}
    assert client_key(headers, "10.0.0.2") == "203.0.113.7"


def test_falls_back_to_socket_ip():
    assert client_key({}, "198.51.100.4") == "198.51.100.4"
    assert client_key({}, None) == "unknown"


# --- 대상 경로 -----------------------------------------------------------------


def test_only_recommend_is_limited():
    assert is_limited("/api/recommend") is True
    assert is_limited("/health") is False
    assert is_limited("/api/context/now") is False
    assert is_limited("/api/poi/p_1") is False


# --- 엔드투엔드 ----------------------------------------------------------------


def test_recommend_returns_429_with_retry_after(client, recommend_payload):
    limit = get_settings().rate_limit_per_min
    codes = [
        client.post("/api/recommend", json=recommend_payload).status_code
        for _ in range(limit + 2)
    ]
    assert codes[:limit] == [200] * limit
    assert codes[limit] == 429

    blocked = client.post("/api/recommend", json=recommend_payload)
    assert blocked.json()["code"] == "rate_limited"
    assert int(blocked.headers["retry-after"]) >= 1


def test_health_is_never_limited(client, recommend_payload):
    """슬립 방지 핑을 막으면 Render가 15분 만에 잠든다."""
    for _ in range(get_settings().rate_limit_per_min + 5):
        client.post("/api/recommend", json=recommend_payload)
    assert client.get("/health").status_code == 200
