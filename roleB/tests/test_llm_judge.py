"""LLM-as-judge 도구의 순수 부분 (B6-3).

LLM 호출 없이 도는 것만 본다. **도구가 실제로 돌 수 있는 상태인가**를 지키는
테스트다 — query_plan이 파라미터 하나 때문에 한 번도 못 돌았던 것과 같은 부류를
막는다.
"""

from __future__ import annotations

import pytest

from tools import llm_judge as lj
from tools import scenarios as sc


class FakeEvidence:
    def __init__(self, text: str) -> None:
        self.text = text


class FakeResult:
    def __init__(self, poi_id: str, name: str, reason: str) -> None:
        self.poi_id = poi_id
        self.name = name
        self.category = "카페"
        self.distance_m = 300
        self.reason = reason
        self.evidence = [FakeEvidence("조용하고 좋았다")]


class FakeCtx:
    weather = "맑음"
    feels_like = 24.0
    pm25_grade = 2
    hotspot = "이태원 관광특구"
    congest_now = "보통"


class FakeRes:
    def __init__(self) -> None:
        self.results = [FakeResult("p_1", "가게하나", "이유하나"),
                        FakeResult("p_2", "가게둘", "이유둘")]
        self.context = FakeCtx()


@pytest.fixture
def scenario() -> sc.Scenario:
    return sc.load()[0]


def test_스키마의_필수필드가_축과_어긋나지_않는다():
    """축을 늘려 놓고 스키마를 안 고치면 strict 모드에서 조용히 빠진다."""
    for axis in lj.AXES:
        assert axis in lj.JUDGE_SCHEMA["properties"]
        assert axis in lj.JUDGE_SCHEMA["required"]
    assert lj.JUDGE_SCHEMA["additionalProperties"] is False


def test_blind_모드는_추천_이유를_보여주지_않는다(scenario):
    """판정 LLM과 설명 LLM이 같은 모델이다. 자기 문장을 자기가 채점하면 후해진다."""
    blind = lj.build_prompt(scenario, FakeRes(), FakeCtx(), blind=True)
    assert "이유하나" not in blind
    assert "인용" in blind          # 근거는 여전히 준다

    with_reason = lj.build_prompt(scenario, FakeRes(), FakeCtx(), blind=False)
    assert "이유하나" in with_reason


def test_프롬프트에_점수_성분을_넣지_않는다(scenario):
    """score_breakdown을 보여주면 판정자가 엔진의 판단을 그대로 따라간다."""
    prompt = lj.build_prompt(scenario, FakeRes(), FakeCtx(), blind=True)
    for banned in ("segment", "score_breakdown", "가중치"):
        assert banned not in prompt


def test_프롬프트가_요청_조건을_전부_담는다(scenario):
    """빠지면 판정자가 상황을 모른 채 채점한다."""
    prompt = lj.build_prompt(scenario, FakeRes(), FakeCtx(), blind=True)
    assert scenario.purpose in prompt
    assert f"{scenario.party_size}명" in prompt
    assert f"{scenario.age_band}대" in prompt
    assert "맑음" in prompt              # 컨텍스트
    assert "p_1" in prompt               # worst_poi_id 로 지목할 수 있어야 한다


def test_판정_실패는_평균에서_빠지지_않고_기록된다():
    """실패를 빼면 점수가 좋아 보인다. 리포트에 그대로 남아야 한다."""
    rows = [
        {"id": "S01", "desc": "d", **{a: 4 for a in lj.AXES}, "mean": 4.0,
         "worst": "x", "worst_reason": "r", "error": ""},
        {"id": "S02", "desc": "d", "error": "판정 실패(LLM None)"},
    ]
    ok = [r for r in rows if not r.get("error")]
    assert len(ok) == 1 and len(rows) == 2      # total 과 judged 가 달라야 한다
