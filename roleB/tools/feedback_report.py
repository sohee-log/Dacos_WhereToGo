"""피드백 로그 분석 (B6-1의 두 번째 근거 · B4-4의 회수).

`recommendation_log`에는 노출된 후보가 **선택되지 않은 것까지** 남는다(B4-4).
가중치를 실측으로 조정하려면 결국 이 데이터를 봐야 한다 — 시나리오 리포트는
"항이 후보를 가르는가"를 답하지만, "가른 방향이 맞았는가"는 답하지 못한다.

이 도구가 먼저 답하는 것은 **그 데이터를 믿어도 되는가**다.

    ① 표본이 몇 개인가
    ② 선택이 순위 1·2번에 몰려 있지 않은가  ← 몰려 있으면 위치 편향이다

②가 중요하다. 사람은 맨 위 카드를 누른다. 순위를 정한 것이 점수이므로,
"선택된 것의 점수 성분"을 그대로 읽으면 **점수가 만든 결과를 점수의 근거로
쓰는 순환논증**이 된다. 위치 편향이 큰 표본에서는 항별 차이를 해석하지 않는다.

사용:
    $env:DATABASE_URL = "postgresql://..."
    python -m tools.feedback_report
    python -m tools.feedback_report --md > docs/FEEDBACK_REPORT.md
"""

from __future__ import annotations

import argparse
import os
import statistics
import sys
from collections import Counter
from typing import Any

from app.constants import W

# 이 밑이면 항별 평균 차이를 해석하지 않는다. 무작위로도 이 정도는 갈린다.
MIN_SAMPLES = 200
# 선택의 이만큼이 1·2위에 몰려 있으면 위치 편향으로 본다.
POSITION_BIAS_TOP2 = 0.7

LOG_SQL = """
SELECT log_id, user_id, clicked, selected, feedback, candidates
FROM recommendation_log
WHERE clicked IS NOT NULL OR selected IS NOT NULL
ORDER BY log_id
"""


def split_shown(rows: list[dict[str, Any]]) -> tuple[list[dict], list[dict]]:
    """(선택된 후보, 노출됐지만 선택 안 된 후보).

    후자가 이 로그의 존재 이유다. 없으면 아무리 모아도 학습이 불가능하다.
    """
    picked_rows, passed_rows = [], []
    for row in rows:
        picked = set(row["clicked"] or [])
        if row["selected"]:
            picked.add(row["selected"])
        for cand in row["candidates"] or []:
            if not cand.get("shown"):
                continue
            (picked_rows if cand["poi_id"] in picked else passed_rows).append(cand)
    return picked_rows, passed_rows


def rank_histogram(picked: list[dict]) -> Counter:
    return Counter(c["rank"] for c in picked if c.get("rank"))


def term_gap(picked: list[dict], passed: list[dict]) -> list[tuple[str, float, float, int]]:
    """항마다 (이름, 선택 평균, 미선택 평균, 표본수)."""
    out = []
    for term in W:
        a = [c["terms"][term] for c in picked
             if (c.get("terms") or {}).get(term) is not None]
        b = [c["terms"][term] for c in passed
             if (c.get("terms") or {}).get(term) is not None]
        if not a or not b:
            continue
        out.append((term, statistics.fmean(a), statistics.fmean(b), len(a) + len(b)))
    return out


def satisfaction(rows: list[dict[str, Any]]) -> list[int]:
    return [r["feedback"] for r in rows if r["feedback"] is not None]


def analyze(rows: list[dict[str, Any]]) -> dict[str, Any]:
    picked, passed = split_shown(rows)
    hist = rank_histogram(picked)
    total_ranked = sum(hist.values())
    top2 = (hist[1] + hist[2]) / total_ranked if total_ranked else 0.0
    return {
        "logs": len(rows),
        "picked": len(picked),
        "passed": len(passed),
        "hist": hist,
        "top2_share": top2,
        "position_biased": top2 >= POSITION_BIAS_TOP2,
        "enough": len(picked) + len(passed) >= MIN_SAMPLES,
        "terms": term_gap(picked, passed),
        "satisfaction": satisfaction(rows),
    }


def verdict(a: dict[str, Any]) -> tuple[bool, str]:
    """(가중치 조정에 쓸 수 있는가, 이유)."""
    if not a["enough"]:
        return False, (
            f"표본이 {a['picked'] + a['passed']}건이다 (최소 {MIN_SAMPLES}). "
            "이 크기에서는 항별 평균 차이가 잡음과 구분되지 않는다."
        )
    if a["position_biased"]:
        return False, (
            f"선택의 {a['top2_share']:.0%}가 1·2위에 몰려 있다. "
            "사람이 맨 위를 누른 것이고 순위를 정한 것은 점수이므로, "
            "이 표본으로 점수를 조정하면 순환논증이 된다."
        )
    return True, "표본 크기와 순위 분포가 해석 가능한 범위다."


def render(a: dict[str, Any]) -> None:
    print(f"\n피드백이 있는 로그 {a['logs']}건")
    print(f"  노출·선택됨   {a['picked']}건")
    print(f"  노출·미선택   {a['passed']}건   ← B4-4가 남기는 negative sample")

    fb = a["satisfaction"]
    if fb:
        print(f"  만족도        {len(fb)}건 · 평균 {statistics.fmean(fb):.2f} / 5")

    print("\n선택된 카드의 순위 분포 (위치 편향 점검)")
    for rank, n in sorted(a["hist"].items()):
        print(f"  {rank:>3}위  {n:>3}건  {'█' * n}")
    print(f"  1·2위 비중 {a['top2_share']:.0%}")

    ok, why = verdict(a)
    print(f"\n{'✅' if ok else '❌'} 가중치 조정 근거로 {'쓸 수 있다' if ok else '쓸 수 없다'} — {why}")

    if a["terms"]:
        print("\n항별 평균 (참고용 — 위 판정이 ❌면 해석하지 않는다)")
        print(f"  {'항':<22}{'선택됨':>9}{'미선택':>9}{'차이':>9}")
        for term, hi, lo, _n in a["terms"]:
            print(f"  {term:<22}{hi:9.4f}{lo:9.4f}{hi - lo:+9.4f}")


def render_md(a: dict[str, Any]) -> None:
    ok, why = verdict(a)
    print("# 피드백 로그 분석 (B6-1 · B4-4)")
    print()
    print("> `python -m tools.feedback_report --md` 로 생성. 실 Supabase 대조.")
    print()
    print(f"- 피드백이 있는 로그 **{a['logs']}건**")
    print(f"- 노출·선택됨 **{a['picked']}** · 노출·미선택 **{a['passed']}**")
    fb = a["satisfaction"]
    if fb:
        print(f"- 만족도 **{len(fb)}건** · 평균 **{statistics.fmean(fb):.2f} / 5**")
    print()
    print("## 위치 편향")
    print()
    print("| 순위 | 선택 수 |")
    print("|---|---:|")
    for rank, n in sorted(a["hist"].items()):
        print(f"| {rank} | {n} |")
    print()
    print(f"1·2위 비중 **{a['top2_share']:.0%}**")
    print()
    print(f"## 판정 — 가중치 조정 근거로 {'쓸 수 있다' if ok else '**쓸 수 없다**'}")
    print()
    print(why)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dsn", default=os.environ.get("DATABASE_URL"))
    ap.add_argument("--md", action="store_true", help="마크다운으로 출력")
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
        rows = db.fetch_all(LOG_SQL)
    finally:
        db.close()

    a = analyze(rows)
    (render_md if args.md else render)(a)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
