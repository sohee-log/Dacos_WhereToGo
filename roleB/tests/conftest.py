from __future__ import annotations

import os
import sys

import pytest
from fastapi.testclient import TestClient

ROLEB_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROLEB_ROOT not in sys.path:
    sys.path.insert(0, ROLEB_ROOT)

from app import ratelimit  # noqa: E402
from app.main import app  # noqa: E402
from app.services import llm  # noqa: E402


@pytest.fixture(scope="session")
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture(autouse=True)
def _clean_process_state():
    """레이트 리밋과 LLM 호출 카운터는 프로세스 전역이다.

    테스트끼리 상태를 물려주면 앞선 테스트가 뒤 테스트를 429로 떨어뜨린다.
    실제로 한 번 겪었다 — 테스트가 아니라 상태 공유가 원인이었다.
    """
    ratelimit.limiter.reset()
    llm.reset_counter()
    yield
    ratelimit.limiter.reset()
    llm.reset_counter()


@pytest.fixture
def recommend_payload() -> dict:
    """이태원 한복판 · 데이트 · 2인 · 저녁. 데모 기본 시나리오."""
    return {
        "user_id": "u_test01",
        "purpose": "데이트",
        "party_size": 2,
        "budget_band": 3,
        "location": {"lat": 37.5340, "lng": 126.9946},
        "visit_at": "2026-08-03T19:00:00+09:00",
    }
