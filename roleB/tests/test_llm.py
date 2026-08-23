"""LLM 클라이언트 (W5).

**키 없이 검증할 수 있는 것까지만 본다** — 응답 파싱, 실패 처리, 쿼터 카운터.
실제 호출은 `LLM_API_KEY`가 생기면 `tools/llm_quota_probe.py --confirm`으로 한다.

여기서 지키는 규칙 하나: **어떤 실패도 예외로 올리지 않는다.** 키가 없든 429든
JSON이 깨졌든 호출부가 할 일은 같다 — 템플릿으로 폴백한다.
"""

from __future__ import annotations

import json
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


# --- 요청을 어떻게 만드는가 --------------------------------------------------------
#
# 여기가 비어 있어서 사고가 났다. 파싱과 폴백만 검증하고 **요청 자체**는 한 번도
# 보지 않았다. 그래서 `User-Agent`가 빠진 채로 전 테스트가 통과했고, prod에서만
# Cloudflare가 403(error 1010)을 줬다 — 그리고 그 403마저 폴백에 삼켜졌다.
# (docs/LLM_QUOTA.md §0-1)


class _Resp:
    def __init__(self, payload: dict):
        self._body = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> bool:
        return False


@pytest.fixture
def sent(monkeypatch) -> list:
    """`urlopen`에 실제로 넘어간 Request를 잡아 둔다."""
    captured: list = []

    def fake_urlopen(req, timeout=None):
        captured.append(req)
        return _Resp({"choices": [{"message": {"content": '{"ok": 1}'}}]})

    monkeypatch.setattr(llm.urllib.request, "urlopen", fake_urlopen)
    return captured


def test_sends_a_user_agent(sent):
    """🔴 회귀 방지. 기본 `Python-urllib/3.x`는 게이트웨이 앞단에서 차단된다."""
    llm.chat_json(_settings(), "prompt", {"type": "object"}, "s")
    ua = sent[0].get_header("User-agent")
    assert ua and "python-urllib" not in ua.lower()


def test_sends_the_key_as_a_bearer_token(sent):
    llm.chat_json(_settings(llm_api_key="k123"), "prompt", {"type": "object"}, "s")
    assert sent[0].get_header("Authorization") == "Bearer k123"


def test_url_keeps_the_trailing_slash(sent):
    """끝 슬래시가 없으면 게이트웨이가 다른 응답을 준다 (docs/LLM_QUOTA.md)."""
    llm.chat_json(_settings(), "prompt", {"type": "object"}, "s")
    assert sent[0].full_url.endswith("/chat/completions/")


def test_forces_a_strict_json_schema(sent):
    """이걸 빼면 모델이 스키마를 통째로 지어낸다. 실측된 실패 모드다."""
    schema = {"type": "object", "properties": {}}
    llm.chat_json(_settings(llm_model="m1"), "프롬프트", schema, "my_schema")
    body = json.loads(sent[0].data.decode("utf-8"))
    assert body["model"] == "m1"
    assert body["response_format"]["type"] == "json_schema"
    assert body["response_format"]["json_schema"]["strict"] is True
    assert body["response_format"]["json_schema"]["name"] == "my_schema"
    assert body["response_format"]["json_schema"]["schema"] == schema


def test_http_error_is_swallowed_into_none(sent, monkeypatch):
    """403이든 429든 호출부가 할 일은 같다 — 템플릿으로 폴백한다."""

    def boom(req, timeout=None):
        raise llm.urllib.error.HTTPError(req.full_url, 403, "Forbidden", {}, None)

    monkeypatch.setattr(llm.urllib.request, "urlopen", boom)
    assert llm.chat_json(_settings(), "prompt", {}, "s") is None
