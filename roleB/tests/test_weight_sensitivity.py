"""가중치 민감도 도구가 프로덕션과 **같은 수식**을 쓰는가 (B6-1).

이 도구는 과거 로그를 다시 채점해 "가중치를 바꾸면 화면이 달라지는가"를 잰다.
수식이 프로덕션과 어긋나면 도구가 다른 세계를 재게 되고, 그 위에서 내린
가중치 판단이 통째로 무의미해진다. B6-2에서 이미 겪었다 — 점검 도구가 먼저
깨져 있어서 "점검했다"는 말만 남은 적이 있다(query_plan 파라미터 드리프트).

그래서 도구를 믿기 전에 도구를 검사한다.
"""

from __future__ import annotations

import pytest

from app.constants import W
from app.services.scoring import total_score
from tools.weight_sensitivity import CANDIDATE_WEIGHTS, ranked, rescore

FULL = {
    "segment_affinity": 0.7, "purpose_match": 0.9, "taste_similarity": 0.4,
    "context_fit": 1.0, "quality": 0.6, "live_segment_match": 0.8, "crowd_fit": 0.5,
}
# 핫스팟 밖 — live 두 항이 없다. 재정규화 경로를 같이 태운다 (§6.4).
PARTIAL = {k: v for k, v in FULL.items()
           if k not in ("live_segment_match", "crowd_fit")}


@pytest.mark.parametrize("terms", [FULL, PARTIAL], ids=["핫스팟_안", "핫스팟_밖"])
def test_프로덕션_가중치면_프로덕션_점수와_같다(terms):
    score, _avail, dist_pen = total_score(
        dict(terms), 800.0, "itaewon", "huam", rain_prob=0.4
    )
    assert rescore(terms, dist_pen, W) == pytest.approx(score, abs=1e-9)


def test_후보_가중치안은_전부_같은_항을_다룬다():
    """항 이름이 하나 어긋나면 그 항이 조용히 빠진 채로 채점된다."""
    for name, weights in CANDIDATE_WEIGHTS.items():
        assert set(weights) == set(W), f"{name}의 항 구성이 W와 다르다"
        assert all(v > 0 for v in weights.values()), f"{name}에 0 이하 가중치가 있다"
        assert sum(weights.values()) == pytest.approx(1.0, abs=1e-6), (
            f"{name}의 합이 1.00이 아니다 — 사람이 비교할 때 헷갈린다"
        )


def test_동점은_poi_id로_끊는다():
    """프로덕션(`scored.sort`)과 같은 규칙이어야 비교가 성립한다."""
    same = {"terms": FULL, "distance_penalty": 0.0}
    cands = [{**same, "poi_id": "pb"}, {**same, "poi_id": "pa"}]
    assert ranked(cands, W) == ["pa", "pb"]


def test_가중치를_바꾸면_점수가_바뀐다():
    """도구가 실제로 무언가를 재는지 본다 — 늘 같은 답이면 쓸모가 없다."""
    base = rescore(FULL, 0.0, W)
    moved = [rescore(FULL, 0.0, w) for w in CANDIDATE_WEIGHTS.values()]
    assert any(abs(m - base) > 1e-6 for m in moved)


def test_품질_쪽으로_기울이면_순위가_뒤집힌다():
    """`quality_up`은 품질 0.09 → 0.15이되 **목적(0.19)을 넘지는 않는다.**

    그래서 품질만 높고 목적이 낮은 곳이 이 안에서도 1위가 되지는 않는다 —
    그 사실 자체를 못박아 둔다. 실제로 뒤집으려면 품질이 목적을 넘어야 한다.
    """
    hi_quality = {"terms": {**FULL, "quality": 1.0, "purpose_match": 0.1},
                  "distance_penalty": 0.0, "poi_id": "q"}
    hi_purpose = {"terms": {**FULL, "quality": 0.1, "purpose_match": 1.0},
                  "distance_penalty": 0.0, "poi_id": "p"}
    cands = [hi_quality, hi_purpose]

    assert ranked(cands, W)[0] == "p"                        # 설계값은 목적 우선
    assert ranked(cands, CANDIDATE_WEIGHTS["quality_up"])[0] == "p"   # 여전히 목적

    quality_first = {**W, "quality": 0.30, "purpose_match": 0.01}
    assert ranked(cands, quality_first)[0] == "q"
