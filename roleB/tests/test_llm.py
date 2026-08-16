"""LLM 클라이언트 (W5).

**키 없이 검증할 수 있는 것까지만 본다** — 응답 파싱, 실패 처리, 쿼터 카운터.
실제 호출은 `LLM_API_KEY`가 생기면 `tools/llm_quota_probe.py --confirm`으로 한다.

여기서 지키는 규칙 하나: **어떤 실패도 예외로 올리지 않는다.** 키가 없든 429든
JSON이 깨졌든 호출부가 할 일은 같다 — 템플릿으로 폴백한다.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.config import Settings
from app.services import llm


def _settings(**over) -> Settings:
    base = {"mock_mode": False, "llm_api_key": "test-key", "llm_daily_limit": 500}
    return Settings(**{**base, **over})


@pytest.fixture(autouse=True)
def _reset():
    llm.reset_counter()
    yield
    llm.reset_counter()


# --- 호출 가능 여부 --------------------------------------------------------------


def test_available_requires_a_key():
    assert llm.available(_settings()) is True
    assert llm.available(_settings(llm_api_key=None)) is False


def test_force_fail_makes_it_unavailable():
    """B5-5 스위치. 폴백 경로를 실제로 밟아 보기 위한 것이다."""
    assert llm.available(_settings(llm_force_fail=True)) is False


def test_no_key_returns_none_without_network():
    assert llm.chat_json(_settings(llm_api_key=None), "prompt", {}, "s") is None


def test_force_fail_returns_none_without_network():
    assert llm.chat_json(_settings(llm_force_fail=True), "prompt", {}, "s") is None


# --- 쿼터 카운터 ----------------------------------------------------------------


def test_daily_limit_stops_calling():
    """게이트웨이가 rate limit 헤더를 주지 않아 남은 양을 알 수 없다.

    그래서 프로세스 안에서 센다. 발표 중에 마르는 것보다 미리 멈추는 편이 낫다.
    """
    s = _settings(llm_daily_limit=2)
    today = date(2026, 8, 10)
    # 네트워크에 나가지 않도록 URL을 죽은 곳으로 돌린다 — 실패해도 카운터는 소비된다
    s = s.model_copy(update={"llm_base_url": "http://127.0.0.1:59997"})

    for _ in range(2):
        llm.chat_json(s, "p", {}, "s", today=today)
    assert llm.calls_today(today) == 2

    # 세 번째는 아예 시도하지 않는다
    assert llm.chat_json(s, "p", {}, "s", today=today) is None
    assert llm.calls_today(today) == 2


def test_counter_resets_on_a_new_day():
    s = _settings(llm_daily_limit=1).model_copy(
        update={"llm_base_url": "http://127.0.0.1:59997"}
    )
    llm.chat_json(s, "p", {}, "s", today=date(2026, 8, 10))
    assert llm.calls_today(date(2026, 8, 10)) == 1
    assert llm.calls_today(date(2026, 8, 11)) == 0


def test_zero_limit_means_unlimited():
    s = _settings(llm_daily_limit=0).model_copy(
        update={"llm_base_url": "http://127.0.0.1:59997"}
    )
    for _ in range(3):
        llm.chat_json(s, "p", {}, "s", today=date(2026, 8, 10))
    assert llm.calls_today(date(2026, 8, 10)) == 3


def test_network_failure_returns_none():
    """죽은 주소로 보낸다. 예외가 아니라 None이어야 한다."""
    s = _settings().model_copy(update={"llm_base_url": "http://127.0.0.1:59997"})
    assert llm.chat_json(s, "p", {}, "s") is None


# --- 응답 파싱 -----------------------------------------------------------------


def _envelope(content: str) -> dict:
    return {"choices": [{"message": {"content": content}}], "usage": {"total_tokens": 100}}


def test_parses_plain_json():
    assert llm.parse_choice(_envelope('{"results": []}')) == {"results": []}


def test_strips_code_fences():
    """strict를 걸어도 게이트웨이가 코드펜스를 씌워 보내는 경우가 있다."""
    assert llm.parse_choice(_envelope('```json\n{"a": 1}\n```')) == {"a": 1}
    assert llm.parse_choice(_envelope('```\n{"a": 2}\n```')) == {"a": 2}


def test_non_json_returns_none():
    """실측된 실패 모드 — JS 코드 조각이 섞여 나온 적이 있다 (docs/LLM_QUOTA.md)."""
    assert llm.parse_choice(_envelope(".filter(t => true)")) is None


def test_json_array_returns_none():
    """스키마는 객체다. 배열이 오면 우리가 기대한 형태가 아니다."""
    assert llm.parse_choice(_envelope("[1, 2, 3]")) is None


@pytest.mark.parametrize("payload", [None, {}, {"choices": []}, "문자열", {"choices": [{}]}])
def test_broken_envelopes_return_none(payload):
    assert llm.parse_choice(payload) is None
