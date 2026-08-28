"""LLM-as-judge 평가 (B6-3).

`scenario_report`(B6-1)가 **점수가 갈리는가**를 재는 도구라면, 이건 **그 순위가
사람이 보기에 말이 되는가**를 잰다. 정답 라벨이 없는 추천에서 품질을 숫자로
만드는 유일한 현실적 방법이다.

무엇을 묻나
-----------
시나리오 하나와 그 결과 5건을 통째로 LLM에 주고 네 축으로 점수를 받는다.

    relevance   요청(목적·인원·예산)에 맞는 곳들인가
    context_fit 날씨·시간·혼잡도 같은 상황이 반영됐는가
    diversity   비슷한 곳만 5개 나열하지 않았는가
    explanation 이유 문장이 근거를 갖고 있는가 (인용과 어긋나지 않는가)

각 1~5. 함께 **가장 부적절한 한 건과 그 이유**도 받는다 — 총점보다 이쪽이
가중치를 어디로 옮길지 알려준다.

⚠️ 판정자를 믿는 방식에 대해
----------------------------
- **판정 LLM은 추천을 만든 LLM과 같은 모델이다.** 자기가 쓴 이유 문장을 자기가
  채점하면 후하게 준다. 그래서 `reason`을 **빼고** 물어보는 모드(`--blind`)를
  기본으로 둔다. 설명 축만 `reason`을 함께 준다.
- **절대 점수를 신뢰하지 않는다.** 4.2가 "좋다"는 뜻이 아니다. 의미가 있는 것은
  **가중치를 바꾸기 전후의 차이**와 **시나리오 사이의 상대 순위**다.
- 실패는 조용히 넘기지 않는다. 판정이 안 된 시나리오는 리포트에 그대로 남긴다.

사용:
    $env:DATABASE_URL = "postgresql://..."
    $env:LLM_API_KEY  = "..."
    python -m tools.llm_judge
    python -m tools.llm_judge --md > docs/LLM_JUDGE_REPORT.md
    python -m tools.llm_judge --limit 5          # 쿼터를 아낄 때

종료 코드: 0 정상 · 1 판정 실패가 있다 · 2 DB/키 없음
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from datetime import datetime, timedelta, timezone

from app.config import Settings
from app.db import Database
from app.schemas import Location, Purpose, RecommendRequest
from app.services import llm, user_svc
from app.services.pipeline import build_live_recommendation
from tools import scenarios as sc

KST = timezone(timedelta(hours=9))

AXES = ("relevance", "context_fit", "diversity", "explanation")

JUDGE_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "relevance": {"type": "integer", "minimum": 1, "maximum": 5},
        "context_fit": {"type": "integer", "minimum": 1, "maximum": 5},
        "diversity": {"type": "integer", "minimum": 1, "maximum": 5},
        "explanation": {"type": "integer", "minimum": 1, "maximum": 5},
        "worst_poi_id": {"type": "string"},
        "worst_reason": {"type": "string"},
    },
    "required": [*AXES, "worst_poi_id", "worst_reason"],
    "additionalProperties": False,
}


def build_prompt(scenario: sc.Scenario, res, ctx, blind: bool) -> str:
    """판정 프롬프트. 점수 성분은 주지 않는다 — 엔진의 판단을 그대로 따라가게 된다."""
    lines = [
        "너는 서울 용산구의 장소 추천 결과를 평가하는 심사자다.",
        "아래 요청과 추천 결과를 보고 네 축으로 1~5점을 매겨라.",
        "",
        "## 요청",
        f"- 상황: {scenario.desc}",
        f"- 목적: {scenario.purpose} · 인원: {scenario.party_size}명 · 예산대: {scenario.budget_band}/4",
        f"- 사용자: {scenario.age_band}대 {'여성' if scenario.gender == 'F' else '남성'}",
        f"- 방문 시각: {scenario.hour}시 ({'주말' if scenario.weekday >= 5 else '평일'})",
        "",
        "## 그때의 상황(컨텍스트)",
        f"- 날씨: {ctx.weather} · 체감 {ctx.feels_like}도 · 미세먼지 등급 {ctx.pm25_grade}/4",
        f"- 지점: {ctx.hotspot or '지점 반경 밖'} · 혼잡: {ctx.congest_now or '알 수 없음'}",
        "",
        "## 추천 결과",
    ]
    for i, r in enumerate(res.results, 1):
        lines.append(f"{i}. [{r.poi_id}] {r.name} · {r.category} · {r.distance_m}m")
        if not blind:
            lines.append(f"   이유: {r.reason}")
        for ev in r.evidence[:1]:
            lines.append(f"   인용: {ev.text[:120]}")
    lines += [
        "",
        "## 채점 기준",
        "- relevance   : 목적·인원·예산에 맞는 곳들인가",
        "- context_fit : 날씨·시간·혼잡 같은 상황이 반영된 선택인가",
        "- diversity   : 비슷한 곳만 나열하지 않았는가",
        "- explanation : "
        + ("인용이 그 장소를 뒷받침하는가" if blind else "이유 문장이 인용과 어긋나지 않는가"),
        "",
        "3점이 '무난함'이다. 후하게 주지 마라.",
        "worst_poi_id 에는 위 목록의 poi_id 중 가장 부적절한 하나를 그대로 적어라.",
    ]
    return "\n".join(lines)


def run(dsn: str, limit: int | None, blind: bool) -> tuple[list[dict], dict]:
    settings = Settings(mock_mode=False, database_url=dsn)
    if not llm.available(settings):
        raise RuntimeError("LLM_API_KEY가 없다 — 판정은 LLM 호출이 필요하다")

    db = Database(settings)
    db.open()
    now = datetime.now(KST)
    rows: list[dict] = []

    try:
        for s in sc.load()[: limit or None]:
            onboarding = sc.onboarding_payload(s)
            if onboarding:
                # 프로필이 없으면 개인화 항 3개가 중립이 되고, 그걸 채점하면
                # "개인화가 약하다"가 아니라 "측정이 틀린" 결과가 나온다.
                user_svc.upsert_profile(
                    db.fetch_all,
                    user_id=s.user_id(),
                    gender=onboarding["gender"],
                    age_band=onboarding["age_band"],
                    taste_tags=[*onboarding["atmosphere_tags"], *onboarding["purpose_tags"]],
                    weather_sensitivity=onboarding["weather_sensitivity"],
                )
            p = sc.to_payload(s, now)
            req = RecommendRequest(
                user_id=p["user_id"],
                purpose=Purpose(p["purpose"]),
                party_size=p["party_size"],
                budget_band=p["budget_band"],
                location=Location(**p["location"]),
                visit_at=p["visit_at"],
            )
            try:
                res = build_live_recommendation(req, settings, db.fetch_all)
            except Exception as exc:  # noqa: BLE001
                rows.append({"id": s.id, "desc": s.desc, "error": f"추천 실패: {exc}"[:120]})
                continue

            started = time.perf_counter()
            verdict = llm.chat_json(
                settings,
                build_prompt(s, res, res.context, blind),
                JUDGE_SCHEMA,
                schema_name="recommendation_judgement",
                max_tokens=400,
            )
            elapsed = (time.perf_counter() - started) * 1000

            if not verdict:
                # 판정 실패를 평균에서 빼면 점수가 좋아 보인다. 그대로 남긴다.
                rows.append({"id": s.id, "desc": s.desc, "error": "판정 실패(LLM None)"})
                continue

            worst = verdict.get("worst_poi_id", "")
            worst_name = next((r.name for r in res.results if r.poi_id == worst), worst)
            rows.append(
                {
                    "id": s.id,
                    "desc": s.desc,
                    "modes": sorted({r.explain_mode.value for r in res.results}),
                    "ms": elapsed,
                    **{a: int(verdict[a]) for a in AXES},
                    "mean": statistics.fmean(int(verdict[a]) for a in AXES),
                    "worst": worst_name,
                    "worst_reason": verdict.get("worst_reason", ""),
                    "error": "",
                }
            )
    finally:
        db.close()

    ok = [r for r in rows if not r.get("error")]
    summary = {
        a: statistics.fmean(r[a] for r in ok) if ok else 0.0 for a in AXES
    }
    summary["mean"] = statistics.fmean(r["mean"] for r in ok) if ok else 0.0
    summary["judged"] = len(ok)
    summary["total"] = len(rows)
    return rows, summary


def render_text(rows: list[dict], summary: dict, blind: bool) -> None:
    print(f"\n판정 {summary['judged']}/{summary['total']} · blind={blind}\n")
    for r in rows:
        if r.get("error"):
            print(f"  {r['id']}  ❌ {r['error']}")
            continue
        print(
            f"  {r['id']}  rel {r['relevance']} ctx {r['context_fit']} "
            f"div {r['diversity']} exp {r['explanation']}  평균 {r['mean']:.2f}"
            f"  [{'/'.join(r['modes'])}]  {r['desc']}"
        )
        print(f"        최약 {r['worst']} — {r['worst_reason'][:70]}")
    print("\n축별 평균")
    for a in AXES:
        print(f"  {a:<12} {summary[a]:.2f}")
    print(f"  {'전체':<12} {summary['mean']:.2f}")
    print("\n※ 절대값은 의미가 없다. 가중치를 바꾸기 전후의 차이로만 읽는다.")


def render_md(rows: list[dict], summary: dict, blind: bool) -> None:
    print("# LLM-as-judge 평가 (B6-3)")
    print()
    print("> `python -m tools.llm_judge --md` 로 생성. 실 Supabase + 실 LLM 호출.")
    print(f"> 판정 {summary['judged']}/{summary['total']} · `blind={blind}`")
    print()
    print("**절대 점수를 신뢰하지 않는다.** 판정 LLM이 추천 설명을 만든 모델과 같아서")
    print("자기 문장을 자기가 채점하면 후해진다. 그래서 기본은 `reason`을 빼고 묻는")
    print("`blind` 모드다. 의미가 있는 것은 **가중치 변경 전후의 차이**와")
    print("**시나리오 사이의 상대 순위**다.")
    print()
    print("## 축별 평균")
    print()
    print("| 축 | 점수 | 무엇을 보는가 |")
    print("|---|---:|---|")
    labels = {
        "relevance": "목적·인원·예산에 맞는가",
        "context_fit": "날씨·시간·혼잡이 반영됐는가",
        "diversity": "비슷한 곳만 나열하지 않았는가",
        "explanation": "인용이 그 장소를 뒷받침하는가",
    }
    for a in AXES:
        print(f"| `{a}` | **{summary[a]:.2f}** | {labels[a]} |")
    print(f"| **전체** | **{summary['mean']:.2f}** | |")
    print()

    # 해석은 사람이 아니라 데이터가 정한다. 리포트를 다시 뽑을 때마다 같이 갱신된다.
    lowest = min(AXES, key=lambda a: summary[a])
    print("## 어디를 손봐야 하나")
    print()
    print(f"가장 낮은 축은 **`{lowest}` ({summary[lowest]:.2f})** 이다.")
    print()
    hints = {
        "relevance": "`purpose_match`(0.22) 가중치와 `poi.purpose_tags` 커버리지를 본다.",
        "context_fit": (
            "`context_fit`(0.13)이 실제로 후보를 바꾸려면 `poi.outdoor_exposure`가 있어야 한다. "
            "지금 실제 관측은 2.1%뿐이고 나머지는 DDL 기본값 0.0이라 **날씨가 순위를 못 바꾼다** "
            "— 가중치가 아니라 데이터 문제다 (A 대기)."
        ),
        "diversity": (
            "같은 업종이 5건에 몰린다는 지적이 반복된다. 지금 최종 선정은 점수 순 + 탐색 슬롯 "
            "1개(§6.7)뿐이고 **업종 다양성 제약이 없다.** B6-1에서 다룰 후보다."
        ),
        "explanation": "인용(`review_chunk`)의 질과 `verify_results`의 통과율을 본다.",
    }
    print(hints[lowest])
    print()
    worst_names = [r["worst"] for r in rows if not r.get("error")]
    repeated = sorted(
        {n: worst_names.count(n) for n in set(worst_names) if worst_names.count(n) > 1}.items(),
        key=lambda x: -x[1],
    )
    if repeated:
        print("여러 시나리오에서 반복해서 '최약'으로 지목된 후보 — 하드필터를 의심한다.")
        print()
        for name, n in repeated:
            print(f"- **{name}** ({n}회)")
        print()
    print("## 시나리오별")
    print()
    print("| ID | 설명 | rel | ctx | div | exp | 평균 | 최약 후보 |")
    print("|---|---|---:|---:|---:|---:|---:|---|")
    for r in rows:
        if r.get("error"):
            print(f"| {r['id']} | {r['desc']} | — | — | — | — | — | ❌ {r['error']} |")
            continue
        print(
            f"| {r['id']} | {r['desc']} | {r['relevance']} | {r['context_fit']} "
            f"| {r['diversity']} | {r['explanation']} | {r['mean']:.2f} "
            f"| {r['worst']} — {r['worst_reason'][:60]} |"
        )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dsn", default=os.environ.get("DATABASE_URL"))
    ap.add_argument("--limit", type=int, default=None, help="앞의 N개만 (쿼터 절약)")
    ap.add_argument(
        "--with-reason",
        action="store_true",
        help="추천 이유 문장까지 보여주고 채점한다 (자기채점 편향이 생긴다)",
    )
    ap.add_argument("--md", action="store_true")
    args = ap.parse_args()

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        except (AttributeError, OSError, ValueError):
            pass

    if not args.dsn:
        print("DATABASE_URL이 없다", file=sys.stderr)
        return 2

    blind = not args.with_reason
    try:
        rows, summary = run(args.dsn, args.limit, blind)
    except Exception as exc:  # noqa: BLE001
        print(f"판정을 시작하지 못했다: {exc}", file=sys.stderr)
        return 2

    (render_md if args.md else render_text)(rows, summary, blind)
    return 0 if summary["judged"] == summary["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
