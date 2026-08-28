"""쿼리 플랜 점검 도구가 실제로 돌 수 있는 상태인가 (B6-2).

**도구가 점검 대상보다 먼저 죽으면 "점검했다"는 말만 남는다.**

2026-08-28에 실제로 그랬다. `retrieval.CANDIDATE_SQL`에 `outdoor_unknown`
파라미터가 추가됐는데(A3-2의 NULL 대응) `tools/query_plan.py`의 CHECKS가
안 따라갔다. EXPLAIN이 `query parameter missing`으로 터졌고, 그 실패를
`❌`로 출력하려다 cp949 콘솔에서 UnicodeEncodeError로 또 죽었다.

결과: B6-2("쿼리 플랜 확인")가 **한 번도 실제로 돈 적이 없었다.**

DB 없이 도는 테스트다. SQL 문자열만 본다.
"""

from __future__ import annotations

import pytest

from tools import query_plan as qp


@pytest.mark.parametrize("title,sql,params,want_index", qp.CHECKS)
def test_점검항목이_SQL이_요구하는_파라미터를_전부_준다(title, sql, params, want_index):
    """SQL이 바뀌면 여기서 먼저 깨진다. 실 DB 없이도 잡힌다."""
    gap = qp.missing_params(sql, params)
    assert not gap, f"{title}: 파라미터 누락 {gap} — CHECKS의 params에 추가한다"


@pytest.mark.parametrize("title,sql,params,want_index", qp.CHECKS)
def test_남는_파라미터는_없다(title, sql, params, want_index):
    """SQL에서 빠진 파라미터가 params에 남아 있으면 그 항목이 낡은 것이다."""
    extra = sorted(set(params) - qp.required_params(sql))
    assert not extra, f"{title}: SQL이 안 쓰는 파라미터 {extra}"


def test_후보_SQL의_야외노출_상수는_엔진에서_가져온다():
    """숫자를 복사해 두면 필터와 점수가 다른 세계를 본다 (SNAPSHOT_STALE에서 겪었다)."""
    from app.constants import OUTDOOR_EXPOSURE_UNKNOWN

    params = next(p for t, s, p, w in qp.CHECKS if "후보 생성" in t)
    assert params["outdoor_unknown"] == OUTDOOR_EXPOSURE_UNKNOWN


def test_마크는_콘솔이_감당하는_것만_쓴다():
    """cp949 콘솔에서 이모지를 출력하려다 도구가 죽은 적이 있다."""
    assert set(qp.MARKS) == {"ok", "warn", "bad"}
    for value in qp.MARKS.values():
        value.encode("utf-8")   # 최소한 인코딩 가능한 문자열이어야 한다
