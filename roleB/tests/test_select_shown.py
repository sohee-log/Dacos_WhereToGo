"""노출 대상 선정과 **정렬** (`pipeline.select_shown`) — 2026-08-30.

이 파일이 있는 이유
-------------------
배포본에서 1번 카드 0.8603 · 4번 카드 0.8808이 나왔다. live 경로가
`explain.generate`가 돌려준 순서를 그대로 화면에 실었기 때문이다.

**기존 테스트가 이걸 못 잡은 이유**가 중요하다. 로컬과 CI에는 LLM 키가 없다.
그러면 `explanations`가 빈 리스트가 되고, 폴백이 점수 순으로 채우므로 순서가
저절로 맞는다 — 즉 **깨진 경로가 한 번도 실행되지 않았다.** 실 DB 테스트도
같은 이유로 통과했다.

그래서 선정·정렬만 순수 함수로 떼어 여기서 직접 태운다. LLM도 DB도 필요 없다.
"""

from __future__ import annotations

from app.constants import RESULT_MAX
from app.services.explain import Explanation
from app.services.pipeline import select_shown


def _scored(*pairs: tuple[str, float]):
    """(poi_id, score) → 파이프라인이 쓰는 (score, poi, avail, dist_pen) 튜플."""
    return [(score, {"poi_id": pid}, {}, 0.0) for pid, score in pairs]


def _exp(*poi_ids: str):
    return [Explanation(poi_id=p, reason=f"{p} 이유", evidence=[]) for p in poi_ids]


SCORED = _scored(("p1", 0.90), ("p2", 0.88), ("p3", 0.86), ("p4", 0.84), ("p5", 0.82))


def test_LLM이_뒤섞어_돌려줘도_점수_순으로_세운다():
    """이게 배포본에서 실제로 난 버그다. 인자 순서가 화면 순서가 되면 안 된다."""
    chosen, _, _ = select_shown(SCORED, _exp("p4", "p3", "p2", "p1"))
    assert [c[1]["poi_id"] for c in chosen] == ["p1", "p2", "p3", "p4"]
    scores = [c[0] for c in chosen]
    assert scores == sorted(scores, reverse=True)


def test_LLM이_고른_곳이_노출_대상이다():
    """정렬은 점수가 하지만, **무엇을 보여줄지**는 LLM 선택을 존중한다.

    LLM은 인용 후보가 있는 곳만 고르도록 프롬프트가 걸려 있다. 점수 상위를
    무조건 밀어 넣으면 근거 없는 카드가 화면에 오른다.
    """
    chosen, reasons, _ = select_shown(SCORED, _exp("p5", "p3"))
    ids = [c[1]["poi_id"] for c in chosen]
    assert "p5" in ids and "p3" in ids
    assert reasons["p5"] == "p5 이유"
    # 남은 자리는 점수 순으로 채운다 — 빈 화면을 만들지 않는다
    assert len(chosen) == RESULT_MAX - 1
    scores = [c[0] for c in chosen]
    assert scores == sorted(scores, reverse=True)


def test_설명이_없으면_점수_순_상위로_채운다():
    """쿼터가 끝나 template으로 떨어져도 화면은 나온다 (B5-5)."""
    chosen, reasons, _ = select_shown(SCORED, [])
    assert [c[1]["poi_id"] for c in chosen] == ["p1", "p2", "p3", "p4"]
    assert reasons == {}


def test_후보에_없는_poi_id는_버린다():
    """LLM 환각. `verify_results`가 1차로 거르지만 여기서도 뚫리지 않아야 한다."""
    chosen, _, _ = select_shown(SCORED, _exp("없는곳", "p2"))
    ids = [c[1]["poi_id"] for c in chosen]
    assert "없는곳" not in ids
    assert "p2" in ids


def test_같은_곳을_두_번_고르면_한_번만_넣는다():
    chosen, _, _ = select_shown(SCORED, _exp("p2", "p2", "p3"))
    ids = [c[1]["poi_id"] for c in chosen]
    assert len(ids) == len(set(ids))


def test_동점은_poi_id로_끊는다():
    """같은 요청이 매번 다른 화면을 주면 디버깅이 안 된다."""
    tied = _scored(("pb", 0.8), ("pa", 0.8), ("pc", 0.7))
    a, _, _ = select_shown(tied, _exp("pc", "pa", "pb"))
    b, _, _ = select_shown(tied, _exp("pb", "pc", "pa"))
    assert [x[1]["poi_id"] for x in a] == [x[1]["poi_id"] for x in b] == ["pa", "pb", "pc"]


def test_후보가_적어도_그만큼만_돌려준다():
    chosen, _, _ = select_shown(_scored(("p1", 0.9), ("p2", 0.8)), [])
    assert [c[1]["poi_id"] for c in chosen] == ["p1", "p2"]
