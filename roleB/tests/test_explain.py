"""설명 생성 — 캐시 · 인용 검증 · 폴백 (B5-2 ~ B5-5).

가장 중요한 테스트는 **인용 검증**이다. LLM이 그럴듯한 후기 한 줄을 지어내면
"실제 리뷰 근거와 함께"라는 이 프로젝트의 한 줄 정의가 무너진다. 그리고 그건
에러 없이, 화면에서 멀쩡해 보이는 형태로 무너진다.
"""

from __future__ import annotations

import pytest

from app.config import Settings
from app.services import llm
from app.services.explain import (
    RESPONSE_SCHEMA,
    build_prompt,
    cache_key,
    generate,
    template_reason,
    verify_quote,
    verify_results,
)

CHUNKS = [
    {"text": "비 오는 날 창가 자리에서 보는 뷰가 좋아요", "source": "naver_blog"},
    {"text": "평일 낮에는 조용해서 노트북 펴기 좋습니다", "source": "naver_blog"},
]
EVIDENCE = {"p_001": CHUNKS, "p_002": [CHUNKS[1]]}
CANDIDATES = [
    {"poi_id": "p_001", "name": "가게1", "dist_m": 100, "atmosphere_tags": ["조용한"]},
    {"poi_id": "p_002", "name": "가게2", "dist_m": 300, "atmosphere_tags": ["넓은"]},
]
CTX = {"purpose": "데이트", "party_size": 2, "budget_band": 3, "weather": "비 60%"}


def _settings(**over) -> Settings:
    base = {"mock_mode": False, "llm_api_key": None, "llm_force_fail": False}
    return Settings(**{**base, **over})


@pytest.fixture(autouse=True)
def _reset():
    llm.reset_counter()


# --- 캐시 키 (B5-3) -------------------------------------------------------------


def test_cache_key_is_stable():
    a = cache_key("데이트", 1, "비", "itaewon", ["p2", "p1"])
    b = cache_key("데이트", 1, "비", "itaewon", ["p1", "p2"])
    assert a == b, "후보 순서가 흔들려도 같은 캐시를 써야 히트율이 산다"


def test_cache_key_changes_with_candidates():
    a = cache_key("데이트", 1, "비", "itaewon", ["p1", "p2"])
    b = cache_key("데이트", 1, "비", "itaewon", ["p1", "p3"])
    assert a != b, "후보가 다르면 설명도 달라야 한다"


def test_cache_key_changes_with_weather():
    assert cache_key("데이트", 1, "비", "itaewon", ["p1"]) != cache_key(
        "데이트", 1, "맑음", "itaewon", ["p1"]
    )


# --- 인용 검증 (B5-4) -----------------------------------------------------------


def test_exact_quote_is_kept():
    q = verify_quote("창가 자리에서 보는 뷰가 좋아요", CHUNKS)
    assert q is not None and q.replaced is False


def test_hallucinated_quote_is_replaced_with_source_text():
    """지어낸 문장을 그대로 내보내지 않는다."""
    q = verify_quote("사장님이 직접 로스팅한 원두를 씁니다", CHUNKS)
    assert q is not None
    assert q.replaced is True
    assert q.text in [c["text"] for c in CHUNKS]


def test_near_miss_quote_is_replaced_with_the_closest_chunk():
    q = verify_quote("평일 낮에는 조용해서 노트북 하기 좋아요", CHUNKS)
    assert q is not None and q.replaced is True
    assert q.text == CHUNKS[1]["text"]


def test_no_chunks_means_no_quote():
    """대체할 원문이 없으면 인용 없이 내보낸다."""
    assert verify_quote("무엇이든", []) is None


def test_empty_quote_falls_back_to_top_chunk():
    q = verify_quote("", CHUNKS)
    assert q is not None and q.text == CHUNKS[0]["text"]


# --- 결과 검증 ------------------------------------------------------------------


def test_unknown_poi_id_is_dropped():
    """후보에 없는 곳을 지어내면 버린다."""
    items = [{"poi_id": "p_999", "reason": "좋아요", "quote": ""}]
    assert verify_results(items, EVIDENCE, ["p_001", "p_002"]) == []


def test_duplicate_poi_keeps_first_only():
    items = [
        {"poi_id": "p_001", "reason": "첫 번째", "quote": ""},
        {"poi_id": "p_001", "reason": "두 번째", "quote": ""},
    ]
    out = verify_results(items, EVIDENCE, ["p_001"])
    assert len(out) == 1 and out[0].reason == "첫 번째"


def test_empty_reason_is_dropped():
    items = [{"poi_id": "p_001", "reason": "   ", "quote": "창가"}]
    assert verify_results(items, EVIDENCE, ["p_001"]) == []


def test_poi_without_evidence_gets_no_quote():
    items = [{"poi_id": "p_003", "reason": "좋아요", "quote": "지어낸 문장"}]
    out = verify_results(items, {"p_003": []}, ["p_003"])
    assert len(out) == 1 and out[0].evidence == []


# --- 프롬프트 -------------------------------------------------------------------


def test_prompt_contains_only_given_quotes():
    """리뷰 전문을 넣지 않는다 (R3). 인용 후보만 들어간다."""
    prompt = build_prompt(CTX, CANDIDATES, EVIDENCE)
    assert "인용 후보" in prompt
    assert CHUNKS[0]["text"] in prompt
    assert "p_001" in prompt and "p_002" in prompt


def test_schema_is_strict_compatible():
    """strict:true는 모든 필드 required + additionalProperties=false를 요구한다."""
    item = RESPONSE_SCHEMA["properties"]["results"]["items"]
    assert item["additionalProperties"] is False
    assert set(item["required"]) == set(item["properties"])
    assert RESPONSE_SCHEMA["additionalProperties"] is False


# --- 모드 전환 (B5-3 / B5-5) -----------------------------------------------------


def _gen(settings, executor):
    return generate(
        settings,
        executor,
        key="k",
        ctx=CTX,
        candidates=CANDIDATES,
        evidence=EVIDENCE,
    )


def test_no_key_falls_back_to_template():
    out, mode = _gen(_settings(), lambda s, p: [])
    assert out == [] and mode == "template"


def test_force_fail_falls_back_to_template():
    """B5-5 — 쿼터가 터진 상황을 강제로 만들어 폴백을 확인한다.

    이 테스트가 없으면 발표 당일 쿼터가 마를 때 서비스 전체가 500을 뱉는다.
    """
    out, mode = _gen(_settings(llm_api_key="k", llm_force_fail=True), lambda s, p: [])
    assert out == [] and mode == "template"


def test_cache_hit_skips_the_llm():
    payload = {"items": [{"poi_id": "p_001", "reason": "캐시된 이유", "quote": ""}]}
    calls: list[str] = []

    def ex(sql, params):
        calls.append(sql)
        return [{"payload": payload}] if "UPDATE explanation_cache" in sql else []

    out, mode = _gen(_settings(llm_api_key="key"), ex)
    assert mode == "cache"
    assert out[0].reason == "캐시된 이유"


def test_cache_hit_increments_hit_count():
    seen: list[str] = []

    def ex(sql, params):
        seen.append(sql)
        return [{"payload": {"items": [{"poi_id": "p_001", "reason": "r", "quote": ""}]}}]

    _gen(_settings(llm_api_key="key"), ex)
    assert "hit_count = hit_count + 1" in seen[0]


def test_llm_result_is_verified_and_cached(monkeypatch):
    stored: dict = {}

    def ex(sql, params):
        if "INSERT INTO explanation_cache" in sql:
            stored.update(params)
        return []

    monkeypatch.setattr(
        llm,
        "chat_json",
        lambda *a, **k: {
            "results": [
                {"poi_id": "p_001", "fit": 0.9, "reason": "비가 와서 실내로 골랐습니다",
                 "quote": "사장님이 직접 로스팅"},          # 지어낸 인용
                {"poi_id": "p_999", "fit": 0.8, "reason": "없는 곳", "quote": ""},
            ]
        },
    )
    out, mode = _gen(_settings(llm_api_key="key"), ex)

    assert mode == "llm"
    assert [e.poi_id for e in out] == ["p_001"]          # 환각 poi는 빠졌다
    assert out[0].evidence[0]["text"] in [c["text"] for c in CHUNKS]   # 인용은 원문으로
    assert stored, "생성 결과가 캐시에 저장되지 않았다"


def test_llm_garbage_falls_back_to_template(monkeypatch):
    monkeypatch.setattr(llm, "chat_json", lambda *a, **k: {"nope": []})
    out, mode = _gen(_settings(llm_api_key="key"), lambda s, p: [])
    assert out == [] and mode == "template"


def test_all_results_dropped_falls_back_to_template(monkeypatch):
    """검증을 다 통과하지 못하면 템플릿이다. 빈 설명을 내보내지 않는다."""
    monkeypatch.setattr(
        llm, "chat_json",
        lambda *a, **k: {"results": [{"poi_id": "없음", "fit": 1, "reason": "r", "quote": ""}]},
    )
    out, mode = _gen(_settings(llm_api_key="key"), lambda s, p: [])
    assert out == [] and mode == "template"


def test_cache_write_failure_does_not_break_generation(monkeypatch):
    def ex(sql, params):
        if "INSERT INTO explanation_cache" in sql:
            raise RuntimeError("디스크 가득")
        return []

    monkeypatch.setattr(
        llm, "chat_json",
        lambda *a, **k: {"results": [{"poi_id": "p_001", "fit": 1, "reason": "이유", "quote": ""}]},
    )
    out, mode = _gen(_settings(llm_api_key="key"), ex)
    assert mode == "llm" and len(out) == 1


# --- 템플릿 문장 ----------------------------------------------------------------


def test_template_reason_uses_only_available_terms():
    text = template_reason(
        {"outdoor_exposure": 0.1}, {"rain_prob": 0.8, "pm25_grade": 2}, "데이트",
        {"purpose_match": 0.9},
    )
    assert "비 예보" in text and "데이트" in text


def test_template_reason_never_returns_empty():
    assert template_reason({}, {}, "데이트", {}).strip()
