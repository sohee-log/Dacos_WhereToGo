"""LLM 클라이언트 — OpenAI 호환 게이트웨이 (W5).

호출 규약은 B1-5 실측 결과 그대로다 (docs/LLM_QUOTA.md).
  - Base URL: FactChat 게이트웨이. **경로에 끝 슬래시가 필요하다** (`/chat/completions/`)
  - 인증: `Authorization: Bearer <KEY>`
  - **`response_format`을 `json_schema` + `strict: true`로 강제한다.**
    이걸 빼면 nano가 JSON이 아닌 것을 뱉거나 스키마를 통째로 지어낸다. 실측된 사실이다.

이 모듈의 규칙 하나
-------------------
**어떤 실패도 예외로 올리지 않는다. None을 반환한다.**
키가 없든, 429든, 타임아웃이든, JSON이 깨졌든 호출부에서 할 일은 같다 —
템플릿으로 폴백한다. 실패 종류를 구분해봐야 사용자에게는 같은 화면이다.

쿼터 방어
---------
게이트웨이가 rate limit 헤더를 주지 않아 남은 양을 알 수 없다(B1-5). 그래서
**프로세스 안에서 호출 수를 센다.** `LLM_DAILY_LIMIT`에 도달하면 더 부르지 않고
템플릿으로 내려간다. 발표 중에 쿼터가 마르는 것보다 미리 멈추는 편이 낫다.
카운터는 프로세스 수명과 같다 — Render가 재시작하면 초기화된다. 정확한 회계가
아니라 **폭주 방지 장치**다.
"""

from __future__ import annotations

import json
import logging
import threading
import urllib.error
import urllib.request
from datetime import date
from typing import Any

from app.config import Settings

log = logging.getLogger("wheretogo.llm")

CHAT_PATH = "/chat/completions/"        # 끝 슬래시 필수 (docs/LLM_QUOTA.md)


class _DailyCounter:
    """오늘 몇 번 불렀는가. 날짜가 바뀌면 저절로 리셋된다."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._day: date | None = None
        self._count = 0

    def take(self, limit: int, today: date) -> bool:
        """한도 안이면 1건 소비하고 True. 한도를 넘으면 False.

        `limit <= 0`(무제한)일 때도 **센다.** 이 카운터는 차단 장치이면서
        "오늘 몇 번 불렀는가"를 알 수 있는 유일한 창구다 — 게이트웨이가
        사용량을 알려주지 않기 때문이다.
        """
        with self._lock:
            if self._day != today:
                self._day, self._count = today, 0
            if 0 < limit <= self._count:
                return False
            self._count += 1
            return True

    def used(self, today: date) -> int:
        with self._lock:
            return self._count if self._day == today else 0

    def reset(self) -> None:
        with self._lock:
            self._day, self._count = None, 0


_counter = _DailyCounter()


def calls_today(today: date | None = None) -> int:
    return _counter.used(today or date.today())


def reset_counter() -> None:
    """테스트용. 프로덕션 경로에서는 부르지 않는다."""
    _counter.reset()


def available(settings: Settings) -> bool:
    """부를 수 있는 상태인가. 키가 없거나 강제 실패 스위치가 켜져 있으면 False."""
    return bool(settings.llm_api_key) and not settings.llm_force_fail


def chat_json(
    settings: Settings,
    prompt: str,
    schema: dict[str, Any],
    schema_name: str,
    max_tokens: int | None = None,
    today: date | None = None,
) -> dict[str, Any] | None:
    """JSON 스키마를 강제한 한 번의 호출. 실패하면 None."""
    if settings.llm_force_fail:
        # B5-5 강제 테스트 스위치. 폴백 경로를 실제로 밟아 보기 위한 것이다.
        log.info("LLM_FORCE_FAIL=true — 호출하지 않고 폴백한다")
        return None
    if not settings.llm_api_key:
        log.info("LLM_API_KEY 없음 — 템플릿으로 간다")
        return None
    if not _counter.take(settings.llm_daily_limit, today or date.today()):
        log.warning(
            "일일 호출 한도(%s) 도달 — 오늘은 템플릿으로 간다", settings.llm_daily_limit
        )
        return None

    body = {
        "model": settings.llm_model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens or settings.llm_max_tokens,
        "temperature": 0.2,          # 설명문은 창의성보다 일관성이 중요하다
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": schema_name, "strict": True, "schema": schema},
        },
    }

    req = urllib.request.Request(
        settings.llm_base_url.rstrip("/") + CHAT_PATH,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {settings.llm_api_key}",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=settings.llm_timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        # 429(쿼터)·402(크레딧)는 "오늘은 여기까지"라는 뜻이다. 재시도하지 않는다.
        log.warning("LLM HTTP %s — 폴백한다", exc.code)
        return None
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
        log.warning("LLM 호출 실패 (%s) — 폴백한다", exc)
        return None

    return parse_choice(payload)


def parse_choice(payload: Any) -> dict[str, Any] | None:
    """응답 봉투에서 JSON 본문을 꺼낸다.

    `strict: true`를 걸어도 게이트웨이가 코드펜스를 씌워 보내는 경우가 있어
    한 겹 벗겨 본다. 그래도 파싱이 안 되면 None이다 — 지어낸 내용을 내보내느니
    템플릿 문장이 낫다.
    """
    if not isinstance(payload, dict):
        return None
    choices = payload.get("choices") or []
    if not choices:
        return None
    content = ((choices[0] or {}).get("message") or {}).get("content")
    if not content:
        return None

    text = str(content).strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()

    try:
        parsed = json.loads(text)
    except ValueError:
        log.warning("LLM 응답이 JSON이 아니다 — 폴백한다")
        return None

    usage = payload.get("usage") or {}
    if usage:
        log.info("LLM 토큰: %s", usage.get("total_tokens"))
    return parsed if isinstance(parsed, dict) else None
