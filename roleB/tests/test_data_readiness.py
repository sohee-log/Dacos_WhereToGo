"""적재 상태 자가 점검 테스트 (전환 준비).

DB 없이 도는 이유는 test_retrieval.py와 같다 — 여기서 보려는 것은 SQL이 아니라
**판정 규칙**이다. "몇 건 있느냐"를 "순위가 실제로 움직이느냐"로 옮기는 부분이
틀리면, 도구가 초록불을 켜 놓고 순위가 무의미한 서비스를 통과시킨다.

실제 SQL은 DB가 붙은 날 스크립트를 한 번 돌리면 바로 드러난다(테이블이 없으면
조회 실패로 표시된다). 여기서 잡아야 하는 건 그 앞단이다.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.constants import W
from tools import check_data_readiness as rd


class FakeCursor:
    """SQL 문자열의 일부를 키로 정해진 행을 돌려준다. 없으면 예외."""

    def __init__(self, answers: dict[str, dict[str, Any]]):
        self.answers = answers
        self._row: dict[str, Any] | None = None

    def execute(self, sql: str, params: Any = None) -> None:
        for needle, row in self.answers.items():
            if needle in sql:
                self._row = row
                return
        raise RuntimeError('relation "없음" does not exist')

    def fetchone(self) -> dict[str, Any] | None:
        return self._row


def _check(**kw) -> rd.Check:
    base = {"label": "테스트", "term": None, "sql": "SELECT 1 AS filled"}
    return rd.Check(**{**base, **kw})


# ── 판정 규칙 ────────────────────────────────────────────────────────────


def test_비어있는_항은_순위에_기여하지_않는다():
    """0건이면 전 POI가 같은 값이다. 기여가 '적은' 게 아니라 정확히 0이다."""
    c = _check(term="quality", filled=0, total=1000)
    assert c.rate == 0.0
    assert not c.alive


def test_일부만_채워져도_순위는_갈린다():
    """전부 차야 살아 있는 게 아니다. POI 사이에 차이가 생기면 순위가 움직인다."""
    c = _check(term="quality", filled=600, total=1000)
    assert c.alive


def test_절반_미만이면_경고지_통과가_아니다():
    c = _check(term="quality", filled=100, total=1000)
    assert not c.alive
    assert rd.mark_for(c) == "⚠️"


def test_치명_항목은_한_건이라도_있으면_통과():
    """poi 적재·후보 통과는 '많으냐'가 아니라 '있느냐'의 문제다."""
    few = _check(fatal=True, filled=3, total=1000)
    none = _check(fatal=True, filled=0, total=1000)
    assert rd.mark_for(few) == "✅"
    assert rd.mark_for(none) == "❌"


# ── 조회 ────────────────────────────────────────────────────────────────


def test_테이블이_없으면_실패로_표시하고_멈추지_않는다():
    """A가 아직 안 만든 테이블 하나 때문에 점검 전체가 죽으면 안 된다."""
    c = _check(sql="SELECT count(*) FROM 없음")
    rd.run(FakeCursor({}), c, {})
    assert c.error
    assert rd.mark_for(c) == "❌"


def test_조회_결과를_채움_전체로_읽는다():
    c = _check(sql="FROM poi")
    rd.run(FakeCursor({"FROM poi": {"filled": 40, "total": 100}}), c, {})
    assert (c.filled, c.total) == (40, 100)
    assert c.rate == pytest.approx(0.4)


# ── 결론 ────────────────────────────────────────────────────────────────


def test_모든_점검항목의_term은_실제_가중치_키다():
    """오타 하나로 KeyError가 나면 전환일에 도구가 못 돈다."""
    for c in rd.CHECKS + rd.SIDE_CHECKS:
        if c.term is not None:
            assert c.term in W, c.label


def test_outdoor_exposure_점검이_NULL을_채워진_것으로_세지_않는다():
    """A의 A3-2가 근거 없는 POI에 NULL을 남긴다 — 그게 초록불이 되면 안 된다.

    예전 SQL은 `IS DISTINCT FROM 0`이라 **NULL이 걸렸다.** 배치가 돌수록 이
    항목이 초록으로 물드는데 순위는 하나도 안 움직인다. 엔진이 NULL을
    OUTDOOR_EXPOSURE_UNKNOWN(0.0)으로 접어 context_fit이 중립이 되기 때문이다.
    `segment_affinity`가 조인 키를 세다가 거짓 초록불을 준 것과 같은 종류다.
    """
    check = next(c for c in rd.CHECKS if c.term == "context_fit")
    assert "IS DISTINCT FROM 0" not in check.sql, (
        "NULL이 '채워짐'으로 세어진다 — 전환 게이트가 거짓 초록불을 준다"
    )
    assert "IS NOT NULL" in check.sql and "<> 0" in check.sql


def test_A의_W2_적재_상태를_그대로_넣으면_치명으로_잡힌다():
    """지금 DB 상태(속성 전 건 0)를 재현한다. 이 경우를 놓치면 도구가 무의미하다."""
    answers = {
        # poi는 있지만 attr_confidence는 전 건 0이다
        "count(*) AS filled, count(*) AS total FROM poi": {"filled": 6644, "total": 6644},
        "attr_confidence >= ": {"filled": 0, "total": 6644},
        "JOIN segment_affinity s": {"filled": 0, "total": 6644},
        "commercial_area_id IS NOT NULL": {"filled": 6354, "total": 6644},
        "purpose_tags IS NOT NULL": {"filled": 0, "total": 6644},
        "tag_vector IS NOT NULL": {"filled": 0, "total": 6644},
        "outdoor_exposure IS NOT NULL": {"filled": 0, "total": 6644},
        "quality_score IS NOT NULL": {"filled": 0, "total": 6644},
        "hotspot_code IS NOT NULL": {"filled": 0, "total": 6644},
        "fcst->'population'": {"filled": 0, "total": 0},
    }
    cur = FakeCursor(answers)
    checks = [
        rd.Check(label=c.label, term=c.term, sql=c.sql, fatal=c.fatal, note=c.note)
        for c in rd.CHECKS
    ]
    for c in checks:
        rd.run(cur, c, {"conf_min": 0.30})

    # 점검 SQL을 고쳤는데 위 스텁을 안 고치면 그 항목이 '조회 실패'로 빠진다.
    # 조용히 통과해 버리므로 여기서 먼저 잡는다.
    assert not [c for c in checks if c.error], (
        f"스텁이 못 받은 점검: {[c.label for c in checks if c.error]}"
    )

    fatal = [c for c in checks if c.fatal and (c.error or c.filled == 0)]
    assert any("attr_confidence" in c.label for c in fatal), "후보 전멸을 못 잡았다"

    scored = [c for c in checks if c.term]
    live = sum(W[c.term] for c in scored if c.alive)
    # 🔴 예전엔 여기서 segment_affinity가 '살아 있음'으로 잡혔다. 조인 **키**만
    # 세고 있었기 때문이다. 통계 테이블이 0행이면 조인 결과는 전 건 NULL이고
    # 항은 전 POI 중립이다 — 기여가 '적은' 게 아니라 정확히 0이다.
    assert not any(c.term == "segment_affinity" and c.alive for c in checks), (
        "조인 키만 보고 세그먼트 항을 살아 있다고 판정했다 — 전환 게이트의 거짓 초록불"
    )
    assert live == pytest.approx(0.0), "이 상태에서 순위를 움직이는 항은 하나도 없다"


def test_임계값을_낮추면_후보는_남는다():
    """전환 결정의 다른 쪽 — 임계값을 0으로 내렸을 때를 재현한다."""
    c = _check(label="attr_confidence ≥ 임계값", fatal=True, sql="attr_confidence >= ")
    rd.run(FakeCursor({"attr_confidence >= ": {"filled": 6644, "total": 6644}}), c, {})
    assert rd.mark_for(c) == "✅"


# ── 0건은 아닌데 극소수인 경우 ─────────────────────────────────────────
#
# 0건은 최근접 폴백으로 티가 난다. 극소수는 **정상처럼 보이면서** 추천이 그
# 몇 건에만 쏠린다. W1 seed의 난수 속성 100건이 DB에 남아 있으면 정확히
# 이 모양이 되고, 그 100건은 실제 리뷰가 아니라 random으로 만든 값이다.


def test_극소수_통과는_경고로_잡는다():
    c = _check(label="attr_confidence", fatal=True, thin_below=0.10)
    rd.run(FakeCursor({"SELECT 1": {"filled": 100, "total": 6644}}), c, {})
    assert c.thin
    assert rd.mark_for(c) == "⚠️", "치명은 아니지만 통과로 넘기면 안 된다"


def test_충분히_통과하면_경고하지_않는다():
    c = _check(label="attr_confidence", fatal=True, thin_below=0.10)
    rd.run(FakeCursor({"SELECT 1": {"filled": 5000, "total": 6644}}), c, {})
    assert not c.thin
    assert rd.mark_for(c) == "✅"


def test_0건은_극소수가_아니라_치명이다():
    """둘을 같은 것으로 다루면 결론 문구가 뒤바뀐다."""
    c = _check(label="attr_confidence", fatal=True, thin_below=0.10)
    rd.run(FakeCursor({"SELECT 1": {"filled": 0, "total": 6644}}), c, {})
    assert not c.thin
    assert rd.mark_for(c) == "❌"


def test_실제_점검표에_극소수_경고가_걸려있다():
    """설정을 빠뜨리면 이 경로가 영영 안 돈다."""
    conf = next(c for c in rd.CHECKS if "attr_confidence" in c.label)
    assert conf.thin_below is not None
    assert conf.thin_note


# ── A3-2 진척 섹션 ───────────────────────────────────────────────────────


class FakeConn:
    def rollback(self) -> None:
        pass


def _progress_output(capsys, answers) -> str:
    rd.attr_extraction_progress(FakeCursor(answers), FakeConn(), 0.30)
    return capsys.readouterr().out


def test_배치가_한_건도_안_돌았으면_그렇게_말한다(capsys):
    out = _progress_output(
        capsys,
        {
            # 순서가 의미를 갖는다 — FakeCursor는 먼저 걸리는 키를 쓴다.
            # done 쿼리도 "FROM poi WHERE tier = 1"을 포함하므로 좁은 쪽이 먼저다.
            "attr_extracted_at IS NOT NULL": {"n": 0},
            "FROM poi WHERE tier = 1": {"n": 800},
        },
    )
    assert "0/800" in out
    assert "extract_attributes" in out


def test_진척_섹션이_모든_조회를_스텁으로_받는다(capsys):
    """SQL을 고쳤는데 여기 스텁을 안 고치면 '조회 실패'로 조용히 빠진다.

    실패가 출력에 섞여도 스크립트는 계속 돌기 때문에, 전환일에 **없는 줄을
    없는 줄로 못 알아본다.** 그래서 여기서 먼저 잡는다.
    """
    answers = {
        # 좁은 키가 먼저다 — FakeCursor는 먼저 걸리는 것을 쓰고, 넓은 키
        # ("attr_extracted_at IS NOT NULL")는 confidence 쿼리에도 들어 있다.
        "AS pass_min": {
            "pass_min": 80,
            "pass_relaxed": 95,
            "zeros": 3,
            "avg_c": 0.44,
            "med_c": 0.46,
        },
        "attr_extracted_at IS NOT NULL AND (": {"n": 40},
        "attr_extracted_at IS NOT NULL": {"n": 100},
        "FROM poi WHERE tier = 1": {"n": 800},
        "unnest": {"n": 0},
    }
    out = _progress_output(capsys, answers)
    assert "조회 실패" not in out
    assert "100/800" in out
    assert "80/100" in out, "confidence 통과율이 안 찍혔다"
    assert "0.440" in out and "0.460" in out
    assert "고정 어휘 위반 0건" in out


def test_어휘_밖_값이_있으면_매칭_실패로_경고한다(capsys):
    answers = {
        "AS pass_min": {
            "pass_min": 80,
            "pass_relaxed": 95,
            "zeros": 0,
            "avg_c": 0.44,
            "med_c": 0.46,
        },
        "attr_extracted_at IS NOT NULL AND (": {"n": 40},
        "attr_extracted_at IS NOT NULL": {"n": 100},
        "FROM poi WHERE tier = 1": {"n": 800},
        "unnest": {"n": 7},
    }
    out = _progress_output(capsys, answers)
    assert "매칭 실패" in out
