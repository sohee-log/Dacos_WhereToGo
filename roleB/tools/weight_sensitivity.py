"""가중치 민감도 (B6-1).

가중치를 바꾸기 전에 답해야 할 질문은 "얼마로 바꿀까"가 아니라
**"바꾸면 화면이 실제로 달라지는가"** 다.

`recommendation_log.candidates`에는 상위 20개의 `terms`가 전부 남아 있다.
`logging_svc.build_candidate_rows`가 그러라고 남긴 것이다 — *"나중에 가중치를
바꿔도 과거 로그를 다시 채점할 수 있게."* 이 도구가 그걸 회수한다.

무엇을 재는가
-------------
후보 집합은 그대로 두고 **가중치만 바꿔** 다시 채점한 뒤, 상위 5개가 얼마나
달라지는지 센다.

    top5 유지율   바뀐 가중치에서도 상위 5에 남는 비율
    1위 변경률    1위가 다른 POI로 바뀐 요청의 비율

읽는 법
-------
- **유지율이 높다(≈100%)** → 그 조정은 화면을 거의 바꾸지 않는다. 근거 없이
  숫자만 만지는 셈이니, 하지 않는 편이 낫다.
- **유지율이 낮다** → 화면이 실제로 바뀐다. 그러면 **바뀐 쪽이 더 나은지**를
  판정할 도구가 있어야 한다(`tools/llm_judge.py`, LLM 키 필요). 판정 없이
  적용하면 튜닝이 아니라 추측이다.

즉 이 도구는 "얼마로 바꿀지"를 알려주지 않는다. **바꿀 자격이 있는지**를 알려준다.

사용:
    $env:DATABASE_URL = "postgresql://..."
    python -m tools.weight_sensitivity
    python -m tools.weight_sensitivity --md > docs/WEIGHT_SENSITIVITY.md
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Mapping
from typing import Any

from app.constants import PENALTY, W

TOP_K = 5

# 로그를 몇 건이나 볼 것인가. 최근 것일수록 지금 데이터 상태를 반영한다.
DEFAULT_LIMIT = 200

LOG_SQL = """
SELECT log_id, candidates
FROM recommendation_log
WHERE candidates IS NOT NULL
  AND jsonb_array_length(candidates) >= %(top_k)s
ORDER BY log_id DESC
LIMIT %(limit)s
"""


# ============================================================================
# 후보군 — 각 안이 무엇을 주장하는가
# ============================================================================
#
# 셋 다 합이 1.00이다. 재정규화(§6.4)가 가중치 합으로 나누므로 합 자체는
# 점수에 영향을 주지 않지만, 사람이 비교할 때 헷갈리지 않도록 맞춰 둔다.

CANDIDATE_WEIGHTS: dict[str, dict[str, float]] = {
    # 실제 기여가 설계 의도의 2배(9% → 18%)인 유일한 항을 되돌린다.
    # "품질은 동점을 가르는 값이지 순위를 끄는 값이 아니다"는 설계 의도 쪽.
    "quality_down": {**W, "quality": 0.05, "segment_affinity": 0.24,
                     "purpose_match": 0.24},
    # 반대 주장. 실제로 후보를 가장 잘 가르는 항이니 그만큼 준다.
    "quality_up": {**W, "quality": 0.15, "segment_affinity": 0.19,
                   "purpose_match": 0.19},
    # 데이터가 얇은 축(맥락·실시간)을 가중치로 밀어 올려 본다.
    # 얇은 데이터를 증폭하는 것이 무슨 결과를 내는지 숫자로 본다.
    "context_up": {**W, "context_fit": 0.20, "live_segment_match": 0.13,
                   "crowd_fit": 0.10, "segment_affinity": 0.18,
                   "purpose_match": 0.18, "taste_similarity": 0.12,
                   "quality": 0.09},
}


def rescore(
    terms: Mapping[str, Any], dist_pen: float, weights: Mapping[str, float]
) -> float:
    """`scoring.total_score`와 **같은 수식**이다. 가중치만 인자로 받는다.

    여기서 수식이 어긋나면 도구가 프로덕션과 다른 세계를 재게 된다.
    `tests/test_weight_sensitivity.py`가 프로덕션 가중치로 두 값이 같은지 본다.
    """
    avail = {k: float(v) for k, v in terms.items() if v is not None and k in weights}
    if not avail:
        return 0.0
    wsum = sum(weights[k] for k in avail)
    if wsum <= 0:
        return 0.0
    base = sum(weights[k] * v for k, v in avail.items()) / wsum
    return max(0.0, min(base - PENALTY["distance"] * float(dist_pen), 1.0))


def ranked(cands: list[dict[str, Any]], weights: Mapping[str, float]) -> list[str]:
    """가중치를 적용한 순위. 동점은 프로덕션과 같이 poi_id로 끊는다."""
    scored = [
        (rescore(c.get("terms") or {}, c.get("distance_penalty") or 0.0, weights),
         c["poi_id"])
        for c in cands
    ]
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [pid for _, pid in scored]


def compare(logs: list[dict[str, Any]], weights: Mapping[str, float]) -> dict[str, Any]:
    kept, total, first_changed = 0, 0, 0
    for row in logs:
        cands = row["candidates"]
        base = ranked(cands, W)[:TOP_K]
        alt = ranked(cands, weights)[:TOP_K]
        kept += len(set(base) & set(alt))
        total += len(base)
        if base and alt and base[0] != alt[0]:
            first_changed += 1
    return {
        "n": len(logs),
        "top5_kept": kept / total if total else 0.0,
        "first_changed": first_changed / len(logs) if logs else 0.0,
    }


def render(results: dict[str, dict[str, Any]], n: int) -> None:
    print(f"\n최근 추천 로그 {n}건을 후보 그대로 다시 채점했다 (상위 {TOP_K} 비교)\n")
    print(f"  {'가중치 안':<16}{'top5 유지율':>12}{'1위 변경률':>12}")
    for name, r in results.items():
        print(f"  {name:<16}{r['top5_kept']:11.1%}{r['first_changed']:12.1%}")
    print(
        "\n  유지율이 100%에 가까우면 그 조정은 화면을 바꾸지 않는다 — 만질 이유가 없다."
        "\n  유지율이 낮으면 화면이 바뀐다 — 바뀐 쪽이 나은지 판정할 도구가 먼저다"
        "\n  (tools/llm_judge.py · LLM 키 필요)."
    )


def render_md(results: dict[str, dict[str, Any]], n: int) -> None:
    print("# 가중치 민감도 (B6-1)")
    print()
    print("> `python -m tools.weight_sensitivity --md` 로 생성. 실 Supabase 대조.")
    print(f"> 최근 추천 로그 **{n}건**을 후보 그대로 다시 채점했다.")
    print()
    print("| 가중치 안 | top5 유지율 | 1위 변경률 |")
    print("|---|---:|---:|")
    for name, r in results.items():
        print(f"| `{name}` | {r['top5_kept']:.1%} | {r['first_changed']:.1%} |")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dsn", default=os.environ.get("DATABASE_URL"))
    ap.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    ap.add_argument("--md", action="store_true")
    args = ap.parse_args()

    if not args.dsn:
        print("DATABASE_URL이 없다", file=sys.stderr)
        return 2

    from app.config import Settings
    from app.db import Database

    db = Database(Settings(mock_mode=False, database_url=args.dsn))
    db.open()
    if not db.available:
        print("DB에 붙지 못했다", file=sys.stderr)
        return 2
    try:
        logs = db.fetch_all(LOG_SQL, {"limit": args.limit, "top_k": TOP_K})
    finally:
        db.close()

    if not logs:
        print("다시 채점할 로그가 없다", file=sys.stderr)
        return 1

    results = {n: compare(logs, w) for n, w in CANDIDATE_WEIGHTS.items()}
    (render_md if args.md else render)(results, len(logs))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
