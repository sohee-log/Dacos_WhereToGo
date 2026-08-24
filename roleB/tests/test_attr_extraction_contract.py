"""A의 LLM 속성 추출(A3-2)이 내놓는 형태로 엔진이 읽히는가 — 계약 테스트.

**이 파일이 왜 따로 있는가.** `test_scoring.py` · `test_retrieval.py`는 B가
*가정한* POI 행으로 검증한다. 그래서 A가 `fcst`를 객체로 넣기 시작했을 때
테스트는 전부 통과하면서 배너만 조용히 사라졌다(`test_citydata_contract.py`
머리말). 같은 실수를 속성 추출에서 반복하지 않으려고 만든다.

A3-2가 W3에 들어오면서 전제 하나가 바뀌었다.

    이전:  poi.outdoor_exposure 는 DDL 기본값 0.0 이라 **NULL이 아니다**
    지금:  리뷰에 근거가 없으면 A가 **NULL로 남긴다** (프롬프트 규칙 1)

이 전제 위에 서 있던 판단이 최소 세 곳 있었고, 전부 200이 나가면서 기능만
사라지는 모양이다. 그래서 여기서는 두 가지를 검증한다.

    ① 어휘·컬럼이 양쪽에서 같은가 — A의 소스를 **직접 파싱해서** 대조한다.
       상수를 여기 다시 적으면 그게 또 가정이 된다.
    ② A가 실제로 남기는 행(대부분의 필드가 NULL)이 엔진을 통과하는가.

A가 어휘를 늘리거나 UPDATE 컬럼을 바꾸면 여기가 먼저 깨져야 한다.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from app.constants import (
    ATMOSPHERE_TAGS,
    OUTDOOR_EXPOSURE_UNKNOWN,
    PURPOSE_TAGS,
)
from app.services.context_fit import context_fit
from app.services.explain import template_reason
from app.services.rag import EVIDENCE_FALLBACK_SQL
from app.services.retrieval import CANDIDATE_SQL, POI_DETAIL_SQL
from app.services.scoring import build_terms, total_score

REPO = Path(__file__).resolve().parents[2]
BATCH = REPO / "roleA" / "jobs" / "extract_attributes.py"
DDL = REPO / "db" / "migrations" / "001_init.sql"


# ---------------------------------------------------------------------------
# A의 소스에서 값을 직접 뜬다 (import하지 않는다 — roleA는 의존성이 다르다)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def batch_ast() -> ast.Module:
    if not BATCH.exists():
        pytest.skip(f"A의 배치가 아직 없다: {BATCH}")
    return ast.parse(BATCH.read_text(encoding="utf-8"))


def _module_list(tree: ast.Module, name: str) -> list[str]:
    """모듈 최상단의 `name = [...]` 리터럴을 그대로 읽는다."""
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == name for t in node.targets
        ):
            return list(ast.literal_eval(node.value))
    raise AssertionError(f"A의 배치에 {name}이 없다")


def test_purpose_vocab_matches_engine(batch_ast):
    """목적 태그 어휘는 A·B·C가 같아야 한다.

    어긋나면 에러가 아니다. `purpose_match`가 **영원히 0.5(중립)**로 나오고,
    가중치 0.22가 순위에서 통째로 사라진다.
    """
    assert _module_list(batch_ast, "PURPOSE_TAGS") == list(PURPOSE_TAGS)


def test_atmosphere_vocab_matches_engine(batch_ast):
    """분위기 태그 어휘. `tag_embedding` 16행(분위기 10 + 목적 6)의 근거이기도 하다."""
    assert _module_list(batch_ast, "ATMOSPHERE_TAGS") == list(ATMOSPHERE_TAGS)


def test_llm_schema_enum_points_at_the_shared_vocab(batch_ast):
    """JSON Schema의 enum이 **상수를 참조**해야 한다.

    A가 프롬프트만 고치고 스키마에 어휘를 인라인으로 다시 적으면, 위 두
    테스트는 통과하면서 LLM은 다른 어휘를 받는다. 그 경로를 막는다.
    """
    referenced: set[str] = set()
    for node in ast.walk(batch_ast):
        if not isinstance(node, ast.Dict):
            continue
        for key, value in zip(node.keys, node.values):
            if isinstance(key, ast.Constant) and key.value == "enum":
                assert isinstance(value, ast.Name), (
                    "enum에 어휘가 인라인으로 박혔다 — 상수를 참조해야 한다"
                )
                referenced.add(value.id)
    assert referenced == {"PURPOSE_TAGS", "ATMOSPHERE_TAGS"}


# ---------------------------------------------------------------------------
# 배치가 쓰는 컬럼이 DDL에 있는가
# ---------------------------------------------------------------------------


def _ddl_columns(table: str) -> set[str]:
    body = re.search(
        rf"CREATE TABLE IF NOT EXISTS {table} \((.*?)\n\);",
        DDL.read_text(encoding="utf-8"),
        re.S,
    )
    assert body, f"DDL에 {table}이 없다"
    cols: set[str] = set()
    for line in body.group(1).splitlines():
        line = line.strip()
        if not line or line.startswith("--"):
            continue
        token = line.split()[0]
        if token.upper() in {"PRIMARY", "UNIQUE", "CHECK", "FOREIGN", "CONSTRAINT"}:
            continue
        cols.add(token)
    return cols


def test_batch_updates_only_real_poi_columns(batch_ast):
    """`UPDATE poi SET ...`의 컬럼이 전부 DDL에 있어야 한다.

    없는 컬럼이면 배치가 터지므로 이건 A가 먼저 안다. 여기서 보는 것은 반대다 —
    **B가 읽는 컬럼과 A가 쓰는 컬럼이 같은 이름인가.**
    """
    source = BATCH.read_text(encoding="utf-8")
    update = re.search(r"UPDATE poi\s*\n\s*SET\s*\n(.*?)WHERE poi_id", source, re.S)
    assert update, "배치에 UPDATE poi 문이 없다"
    written = {
        m.group(1)
        for m in re.finditer(r"^\s*(\w+)\s*=\s*%s", update.group(1), re.M)
    }
    assert written, "UPDATE에서 컬럼을 하나도 못 읽었다 — 정규식이 낡았다"
    assert written <= _ddl_columns("poi"), written - _ddl_columns("poi")


def test_batch_inserts_only_real_review_chunk_columns(batch_ast):
    source = BATCH.read_text(encoding="utf-8")
    insert = re.search(r"INSERT INTO review_chunk \((.*?)\)", source, re.S)
    assert insert, "배치에 review_chunk INSERT가 없다"
    written = {c.strip() for c in insert.group(1).split(",") if c.strip()}
    assert written <= _ddl_columns("review_chunk"), (
        written - _ddl_columns("review_chunk")
    )


# ---------------------------------------------------------------------------
# A가 실제로 남기는 행 — 리뷰에 근거가 없으면 전부 NULL이다
# ---------------------------------------------------------------------------


def _unobserved_poi() -> dict:
    """A의 프롬프트 규칙 1("확인할 수 없는 속성은 반드시 null")이 그대로 적용된 행.

    T1 800건 중 **다수가 이 모양**이 된다. 블로그 후기는 실내/야외를 명시하지
    않는 쪽이 보통이다.
    """
    return {
        "poi_id": "p-unobserved",
        "name": "근거 없는 가게",
        "category_l1": "카페",
        "category_l2": "커피전문점",
        "outdoor_exposure": None,
        "group_capacity": None,
        "noise_level": None,
        "purpose_tags": None,
        "atmosphere_tags": None,
        "price_band": None,
        "wait_intensity": None,
        "sentiment_score": None,
        "quality_score": None,
        "review_count": 0,
        "attr_confidence": 0.28,
        "dist_m": 400.0,
    }


RAINY = {"rain_prob": 0.9, "pm25_grade": 2, "feels_like": 18.0, "visit_hour": 14}


def test_rain_hard_cut_does_not_drop_unobserved_exposure():
    """야외 노출을 **모르는** POI가 비 오는 날 후보에서 통째로 빠지면 안 된다.

    `p.outdoor_exposure <= 0.7`에 NULL이 들어오면 3값 논리로 WHERE가 NULL이 되어
    그 행이 **항상** 빠진다. 에러도 경고도 없다. group_capacity에서 이미 한 번
    겪었고(`ca51a417`), 그때 outdoor_exposure는 "NULL이 안 생긴다"는 전제로
    일부러 남겨 뒀다. A3-2가 그 전제를 깼다.
    """
    for column in ("rain_prob", "pm25_grade"):
        pattern = re.compile(
            rf"%\({column}\)s\s*<\s*[\d.]+\s*OR\s+COALESCE\(\s*p\.outdoor_exposure",
            re.S,
        )
        assert pattern.search(CANDIDATE_SQL), (
            f"{column} 하드컷이 NULL을 그대로 비교한다 — 미관측 POI가 조용히 사라진다"
        )


def test_unobserved_exposure_scores_neutral_not_indoor():
    """점수에서 미관측은 중립이어야 한다 — 실내로 **우대**해도 안 된다."""
    unknown = context_fit(None, RAINY)
    indoor = context_fit(0.0, RAINY)
    outdoor = context_fit(1.0, RAINY)
    assert unknown == indoor == 1.0, "미관측이 중립(1.0)이 아니다"
    assert outdoor < unknown, "실제 야외는 비 오는 날 깎여야 한다"


def test_unknown_rule_is_shared_by_filter_and_score():
    """필터와 점수가 **같은 상수**를 봐야 한다.

    갈리면 "후보에는 남는데 점수는 다른 세계"가 된다. SNAPSHOT_STALE에서
    상수를 복사해 뒀다가 엔진 90분 / 도구 40분으로 갈린 적이 있다.
    """
    assert "%(outdoor_unknown)s" in CANDIDATE_SQL
    assert context_fit(None, RAINY) == context_fit(OUTDOOR_EXPOSURE_UNKNOWN, RAINY)


def test_unobserved_exposure_is_never_claimed_as_indoor():
    """"실내 위주로 골랐습니다"는 관측을 주장하는 문장이다.

    모르는 것을 실내라고 말하면 근거 없는 단정이 된다. 점수에서 0.0으로 접는
    것과 사용자에게 그렇게 **말하는** 것은 다르다.
    """
    terms = {"segment_affinity": 0.5, "purpose_match": 0.5, "crowd_fit": 1.0}
    reason = template_reason(_unobserved_poi(), RAINY, "데이트", terms)
    assert "실내" not in reason


def test_confirmed_indoor_still_says_indoor():
    """반대쪽도 지킨다 — 관측된 실내까지 조용해지면 차별점이 사라진다."""
    poi = {**_unobserved_poi(), "outdoor_exposure": 0.0}
    terms = {"segment_affinity": 0.5, "purpose_match": 0.5, "crowd_fit": 1.0}
    reason = template_reason(poi, RAINY, "데이트", terms)
    assert "실내" in reason


def test_a_shaped_row_scores_without_collapsing():
    """전 컬럼이 NULL인 행도 점수가 나와야 한다. 0점으로 바닥에 깔리면 안 된다."""
    terms = build_terms(_unobserved_poi(), purpose="데이트", wx=RAINY)
    mandatory = {
        "segment_affinity",
        "purpose_match",
        "taste_similarity",
        "context_fit",
        "quality",
    }
    assert mandatory <= set(terms)
    assert all(terms[k] is not None for k in mandatory), (
        "필수 5항은 관측이 없어도 중립값이 들어가야 한다"
    )
    score, _, _ = total_score(terms, 400.0, "itaewon", "itaewon")
    assert 0.0 < score <= 1.0


def test_chunk_ordering_is_deterministic_without_written_at():
    """A는 `written_at`을 채우지 않는다 — 리뷰 JSONL의 postdate가 INSERT에 안 실린다.

    전 건 NULL이면 `ORDER BY written_at DESC NULLS LAST`는 동점이고, 같은 요청이
    요청마다 다른 문장을 인용할 수 있다. 인용은 재현 가능해야 한다.
    """
    for sql in (EVIDENCE_FALLBACK_SQL, POI_DETAIL_SQL):
        assert re.search(r"written_at DESC NULLS LAST,\s*\n?\s*(rc\.)?chunk_id", sql), (
            "written_at이 전 건 NULL일 때 인용 순서가 비결정적이다"
        )


def test_detail_does_not_fabricate_unobserved_attributes():
    """상세 응답이 미관측을 0.0 / 4로 채워 내보내면 안 된다.

    `noise_level` · `price_band`는 원래 nullable이었는데 `outdoor_exposure`와
    `group_capacity`만 기본값이 있었다. A3-2가 이 둘을 NULL로 남기기 시작하면서
    상세 화면이 "야외노출 0.0(완전 실내) · 4인석"을 **관측인 것처럼** 적게 된다.
    """
    from app.routers.poi import _to_detail

    row = {
        **_unobserved_poi(),
        "lat": 37.53,
        "lng": 126.98,
        "zone": "itaewon",
        "business_hours": None,
        "mention_count": 12,
        "reviews": [],
    }
    detail = _to_detail(row)
    assert detail.outdoor_exposure is None
    assert detail.group_capacity is None

    observed = _to_detail({**row, "outdoor_exposure": 0.0, "group_capacity": 4})
    assert observed.outdoor_exposure == 0.0, "관측된 0.0까지 None으로 접으면 안 된다"
    assert observed.group_capacity == 4
