"""시나리오 로딩 · 요청 생성 · 호출 페이싱.

`perf_probe.py`(B6-2)와 `warm_cache.py`(B6-4)가 함께 쓴다. 두 도구가 **같은
시나리오**를 태워야 "측정한 것"과 "데워 둔 것"이 어긋나지 않는다.

여기 있는 것은 전부 순수 함수라 네트워크 없이 테스트된다.
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

KST = timezone(timedelta(hours=9))

ROLEB_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_SCENARIO_PATH = os.path.join(ROLEB_ROOT, "scenarios", "warm_scenarios.json")


@dataclass(frozen=True)
class Scenario:
    id: str
    desc: str
    purpose: str
    party_size: int
    budget_band: int
    lat: float
    lng: float
    hour: int
    weekday: int          # 0=월 … 6=일
    zone: str | None = None

    # 온보딩 프로필. **없으면 개인화 항 세 개가 통째로 중립이 된다** —
    # segment_affinity(0.22) · taste_similarity(0.16) · live_segment_match(0.10).
    # 응답은 200이라 화면으로는 구분이 안 되고, 캐시 워밍이 '개인화가 죽은 결과'를
    # 데워 둔다. 실제로 그러고 있었다 (2026-08-28).
    gender: str | None = None
    age_band: int | None = None
    weather_sensitivity: int = 2

    def user_id(self) -> str:
        """시나리오마다 다른 사용자로 보낸다.

        전부 같은 user_id로 보내면 프로필·로그가 한 사람에게 몰려서
        실제 트래픽과 다른 모양이 된다.
        """
        return f"u_warm_{self.id.lower()}"


def load(path: str | None = None) -> list[Scenario]:
    with open(path or DEFAULT_SCENARIO_PATH, encoding="utf-8") as f:
        raw = json.load(f)
    rows = raw.get("scenarios", raw) if isinstance(raw, dict) else raw
    return [
        Scenario(
            id=str(r["id"]),
            desc=str(r.get("desc") or r["id"]),
            purpose=str(r["purpose"]),
            party_size=int(r["party_size"]),
            budget_band=int(r["budget_band"]),
            lat=float(r["lat"]),
            lng=float(r["lng"]),
            hour=int(r.get("hour", 19)),
            weekday=int(r.get("weekday", 4)),
            zone=r.get("zone"),
            gender=r.get("gender"),
            age_band=(int(r["age_band"]) if r.get("age_band") is not None else None),
            weather_sensitivity=int(r.get("weather_sensitivity", 2)),
        )
        for r in rows
    ]


# 온보딩 태그는 시나리오의 목적에서 끌어온다. 취향 축이 사람마다 달라야
# taste_similarity가 의미를 갖는데, 시나리오에 태그를 또 손으로 적으면
# 고정 어휘(constants.py가 원본이다)와 어긋나기 쉽다.
_ATMOSPHERE_BY_PURPOSE: dict[str, list[str]] = {
    "데이트": ["감성적인", "아늑한"],
    "친구모임": ["활기찬", "트렌디한"],
    "혼자": ["조용한", "아늑한"],
    "가족": ["넓은", "조용한"],
    "작업": ["조용한", "넓은"],
    "회식": ["활기찬", "넓은"],
}


def onboarding_payload(s: Scenario) -> dict[str, Any] | None:
    """`POST /api/onboarding` 본문. 프로필 축이 없는 시나리오면 None.

    시나리오를 **온보딩 없이** 추천에 태우면 개인화 항 세 개가 중립이 된다.
    측정(`scenario_report`)과 워밍(`warm_cache`)이 둘 다 이걸 먼저 태워야
    "재는 경로"와 "도는 경로"가 같아진다 — 어긋나서 겪은 사고가 이미 있다
    (LLM_QUOTA.md 참조: 프로브는 httpx, 앱은 urllib을 써서 403을 못 잡았다).
    """
    if not s.gender or s.age_band is None:
        return None
    return {
        "gender": s.gender,
        "age_band": s.age_band,
        "atmosphere_tags": _ATMOSPHERE_BY_PURPOSE.get(s.purpose, ["조용한"]),
        "purpose_tags": [s.purpose],
        "budget_band": s.budget_band,
        "weather_sensitivity": s.weather_sensitivity,
    }


def next_occurrence(weekday: int, hour: int, now: datetime) -> datetime:
    """다음에 오는 그 요일·그 시각 (KST).

    시나리오에 절대 날짜를 박으면 하루만 지나도 **과거 시각**이 되고,
    그러면 혼잡도 예측(FCST_PPLTN)이 범위 밖으로 나가 값이 사라진다.
    """
    base = now.astimezone(KST).replace(minute=0, second=0, microsecond=0)
    delta = (weekday - base.weekday()) % 7
    target = base.replace(hour=hour) + timedelta(days=delta)
    if target <= now.astimezone(KST):
        target += timedelta(days=7)
    return target


def to_payload(s: Scenario, now: datetime) -> dict[str, Any]:
    return {
        "user_id": s.user_id(),
        "purpose": s.purpose,
        "party_size": s.party_size,
        "budget_band": s.budget_band,
        "location": {"lat": s.lat, "lng": s.lng},
        "visit_at": next_occurrence(s.weekday, s.hour, now).isoformat(),
    }


def pacing_interval(rate_limit_per_min: int, safety: float = 1.15) -> float:
    """레이트 리밋(B5-6)에 걸리지 않는 호출 간격(초).

    시나리오 20개를 연달아 부르면 11번째부터 429다. 워밍이 절반만 되고
    "다 데웠다"고 착각하게 된다 — 발표 전날 밤에 알아채기 가장 나쁜 종류의 실패다.
    제한이 0 이하면 간격 없이 간다.
    """
    if rate_limit_per_min <= 0:
        return 0.0
    return 60.0 / rate_limit_per_min * safety


def percentiles(samples: list[float]) -> dict[str, float]:
    """p50/p95/p99. 표본이 적을 때도 터지지 않는다.

    최근접 순위법(nearest-rank): `ceil(p × n)` 번째 값이다. `round`를 쓰면
    파이썬의 은행가 반올림 때문에 p95가 96번째가 되는 식으로 한 칸씩 밀린다.
    """
    if not samples:
        return {}
    ordered = sorted(samples)
    n = len(ordered)

    def at(p: float) -> float:
        idx = min(n - 1, max(0, math.ceil(p * n) - 1))
        return ordered[idx]

    return {
        "n": float(n),
        "min": ordered[0],
        "p50": at(0.50),
        "p95": at(0.95),
        "p99": at(0.99),
        "max": ordered[-1],
    }
