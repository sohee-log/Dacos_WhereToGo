"""시나리오 20개 실주행 리포트 (B6-1 가중치 튜닝 근거 · A6-4 데이터 검증).

`perf_probe`(B6-2)가 **얼마나 빠른가**를 재는 도구라면, 이건 **무엇이 순위를
가르는가**를 재는 도구다. 둘 다 `scenarios/warm_scenarios.json` 같은 20개를 태운다.

왜 필요한가
-----------
가중치를 조정하려면 "어떤 항이 실제로 후보를 구분하는가"를 알아야 한다.
그런데 항이 죽는 방식이 **에러가 아니다.** 입력이 비면 그 항은 전 POI에서
같은 값(중립)이 되고, 응답은 200으로 정상이다. 겉으로는 순위가 나오지만
그 순위는 살아 있는 항 몇 개만으로 만들어진 것이다.

그래서 항마다 **후보 집합 안의 표준편차**를 잰다.

    표준편차 ≈ 0  →  전 POI가 같은 값 = 그 가중치는 순위에 기여하지 못한다
    표준편차 > 0  →  실제로 후보를 가른다

`check_data_readiness`가 **입력(테이블·컬럼)** 쪽에서 같은 질문에 답한다면,
이 도구는 **출력(점수)** 쪽에서 답한다. 둘이 어긋나면 배선이 끊긴 것이다 —
실제로 그런 적이 있다(`segment_affinity`가 44,064행인데 항은 전부 중립이었다).

함께 답하는 것
--------------
- **A6-4** — 시나리오 20개가 *전부 결과를 반환하는가*. 데모 중에 빈 화면이
  나오는 경로가 있는지 미리 본다.
- `low_confidence` / `radius_expanded` 비율 — 후보 풀이 얼마나 빠듯한가.
- `explain_mode` 분포 · 인용(evidence) 확보율.

사용:
    $env:DATABASE_URL = "postgresql://..."
    python -m tools.scenario_report
    python -m tools.scenario_report --md > docs/SCENARIO_REPORT.md

종료 코드: 0 정상 · 1 결과가 안 나온 시나리오가 있다 · 2 DB에 못 붙음
"""

from __future__ import annotations

import argparse
import os
import statistics
import sys
import time
from datetime import datetime, timedelta, timezone

from app.config import Settings
from app.constants import TERM_TO_BREAKDOWN, W
from app.db import Database
from app.schemas import Location, Purpose, RecommendRequest
from app.services import user_svc
from app.services.pipeline import build_live_recommendation
from tools import scenarios as sc

KST = timezone(timedelta(hours=9))

# 이 밑이면 "전 POI가 같은 값"으로 본다. 부동소수 오차와 구분하기 위한 하한이다.
FLAT_STDEV = 1e-6


def _mark(ok: bool, warn: bool = False) -> str:
    if warn:
        return "WARN"
    return "OK" if ok else "DEAD"


def run(dsn: str) -> tuple[list[dict], dict]:
    """시나리오 20개를 파이프라인에 직접 태운다.

    HTTP를 거치지 않는다. 여기서 재려는 것은 지연이 아니라 **점수의 분포**이고,
    HTTP를 끼우면 레이트 리밋 페이싱 때문에 20개에 2분이 걸린다.
    """
    settings = Settings(mock_mode=False, database_url=dsn)
    db = Database(settings)
    db.open()

    now = datetime.now(KST)
    rows: list[dict] = []
    # 항 이름 -> 시나리오별 표준편차 목록
    spread: dict[str, list[float]] = {t: [] for t in W}
    no_profile: list[str] = []

    try:
        for s in sc.load():
            # 프로필을 먼저 만든다. 이게 없으면 segment_affinity(0.22) ·
            # taste_similarity(0.16) · live_segment_match(0.10)가 통째로 중립이
            # 되고, 리포트가 "항이 죽었다"고 답한다 — 죽은 건 데이터가 아니라
            # 측정이다. 2026-08-28에 실제로 그렇게 읽을 뻔했다.
            onboarding = sc.onboarding_payload(s)
            if onboarding is None:
                no_profile.append(s.id)
            else:
                user_svc.upsert_profile(
                    db.fetch_all,
                    user_id=s.user_id(),
                    gender=onboarding["gender"],
                    age_band=onboarding["age_band"],
                    taste_tags=[
                        *onboarding["atmosphere_tags"],
                        *onboarding["purpose_tags"],
                    ],
                    weather_sensitivity=onboarding["weather_sensitivity"],
                )

            payload = sc.to_payload(s, now)
            req = RecommendRequest(
                user_id=payload["user_id"],
                purpose=Purpose(payload["purpose"]),
                party_size=payload["party_size"],
                budget_band=payload["budget_band"],
                location=Location(**payload["location"]),
                visit_at=payload["visit_at"],
            )
            started = time.perf_counter()
            error = ""
            try:
                res = build_live_recommendation(req, settings, db.fetch_all)
            except Exception as exc:  # noqa: BLE001 - 리포트다. 한 건이 죽어도 계속 돈다
                rows.append(
                    {"id": s.id, "desc": s.desc, "n": 0, "error": str(exc)[:120]}
                )
                continue
            elapsed = (time.perf_counter() - started) * 1000

            # 항별 분산 — 결과 5건이 아니라 **점수 성분**을 본다
            per_term: dict[str, float] = {}
            for term, key in TERM_TO_BREAKDOWN.items():
                vals = [
                    v
                    for v in (getattr(r.score_breakdown, key) for r in res.results)
                    if v is not None
                ]
                if len(vals) >= 2:
                    sd = statistics.pstdev(vals)
                    per_term[term] = sd
                    spread[term].append(sd)

            rows.append(
                {
                    "id": s.id,
                    "desc": s.desc,
                    "zone": s.zone or "-",
                    "n": len(res.results),
                    "ms": elapsed,
                    "low_conf": res.low_confidence,
                    "expanded": res.radius_expanded,
                    "explain": res.results[0].explain_mode.value if res.results else "-",
                    "evidence": sum(len(r.evidence) for r in res.results),
                    "terms": per_term,
                    "error": error,
                }
            )
    finally:
        db.close()

    # --- 항별 종합 ---------------------------------------------------------
    summary: dict[str, dict] = {}
    for term, weight in W.items():
        sds = spread.get(term) or []
        mean_sd = statistics.fmean(sds) if sds else 0.0
        alive = mean_sd > FLAT_STDEV
        summary[term] = {
            "weight": weight,
            "mean_stdev": mean_sd,
            "alive": alive,
            "observed_in": len(sds),
        }
    if no_profile:
        print(
            f"[warn] 프로필 축이 없는 시나리오 {len(no_profile)}건: "
            f"{', '.join(no_profile)} — gender/age_band 없이 태우면 "
            "개인화 항 3개가 중립으로 죽는다",
            file=sys.stderr,
        )
    return rows, summary


def render_text(rows: list[dict], summary: dict) -> None:
    ok = [r for r in rows if r["n"] > 0]
    print(f"\n시나리오 {len(rows)}개 · 결과 반환 {len(ok)}개")
    if len(ok) < len(rows):
        print("  결과가 없는 시나리오:")
        for r in rows:
            if r["n"] == 0:
                print(f"    {r['id']}  {r['desc']}  {r.get('error','')}")

    print("\n시나리오별")
    for r in ok:
        flags = []
        if r["low_conf"]:
            flags.append("low_confidence")
        if r["expanded"]:
            flags.append("radius_expanded")
        print(
            f"  {r['id']}  {r['n']}건  {r['ms']:6.0f}ms  {r['explain']:<8}"
            f"  인용 {r['evidence']:2d}  {r['zone']:<12} {' '.join(flags)}"
        )

    print("\n항별 — 후보 안에서 실제로 순위를 가르는가 (표준편차 평균)")
    live_w = 0.0
    for term, d in sorted(summary.items(), key=lambda x: -x[1]["weight"]):
        mark = _mark(d["alive"])
        if d["alive"]:
            live_w += d["weight"]
        print(
            f"  {mark:<5} {term:<20} 가중치 {d['weight']:.2f}"
            f"  표준편차 {d['mean_stdev']:.4f}  (관측 {d['observed_in']}/{len(rows)} 시나리오)"
        )
    total_w = sum(d["weight"] for d in summary.values())
    print(f"\n  순위를 실제로 가르는 가중치: {live_w:.2f} / {total_w:.2f}")

    lat = [r["ms"] for r in ok]
    if lat:
        p = sc.percentiles(sorted(lat))
        print(
            f"  파이프라인 지연(HTTP 제외): p50 {p['p50']:.0f} / p95 {p['p95']:.0f} ms"
        )


def render_md(rows: list[dict], summary: dict) -> None:
    ok = [r for r in rows if r["n"] > 0]
    print("# 시나리오 20개 실주행 리포트")
    print()
    print("> `python -m tools.scenario_report --md` 로 생성. 실 Supabase 대조.")
    print("> B6-1(가중치 튜닝 근거) · A6-4(데모 시나리오 데이터 검증)")
    print()
    print(f"**결과 반환 {len(ok)}/{len(rows)}**")
    print()
    print("## 항별 — 실제로 순위를 가르는가")
    print()
    print("항이 죽는 방식은 에러가 아니다. 입력이 비면 전 POI가 같은 값(중립)이 되고")
    print("응답은 200이다. 그래서 **후보 집합 안의 표준편차**를 잰다 — 0이면 기여 0이다.")
    print()
    print("| | 항 | 가중치 | 표준편차 평균 | 관측 |")
    print("|---|---|---:|---:|---|")
    live_w = 0.0
    for term, d in sorted(summary.items(), key=lambda x: -x[1]["weight"]):
        if d["alive"]:
            live_w += d["weight"]
        icon = "✅" if d["alive"] else "❌"
        print(
            f"| {icon} | `{term}` | {d['weight']:.2f} | {d['mean_stdev']:.4f} "
            f"| {d['observed_in']}/{len(rows)} |"
        )
    total_w = sum(d["weight"] for d in summary.values())
    print()
    print(f"**순위를 실제로 가르는 가중치: {live_w:.2f} / {total_w:.2f}**")
    print()
    print("## 시나리오별")
    print()
    print("| ID | 설명 | zone | 결과 | 지연 | 설명모드 | 인용 | 플래그 |")
    print("|---|---|---|---:|---:|---|---:|---|")
    for r in rows:
        if r["n"] == 0:
            print(f"| {r['id']} | {r['desc']} | - | **0** | - | - | - | ❌ {r.get('error','')} |")
            continue
        flags = []
        if r["low_conf"]:
            flags.append("`low_confidence`")
        if r["expanded"]:
            flags.append("`radius_expanded`")
        print(
            f"| {r['id']} | {r['desc']} | {r['zone']} | {r['n']} | {r['ms']:.0f}ms "
            f"| {r['explain']} | {r['evidence']} | {' '.join(flags) or '—'} |"
        )
    lat = [r["ms"] for r in ok]
    if lat:
        p = sc.percentiles(sorted(lat))
        print()
        print(f"지연은 **파이프라인 내부**만이다(HTTP·직렬화 제외). p50 {p['p50']:.0f} / p95 {p['p95']:.0f} ms.")
        print("HTTP 포함 실측은 `tools/perf_probe.py`가 낸다.")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dsn", default=os.environ.get("DATABASE_URL"))
    ap.add_argument("--md", action="store_true", help="마크다운으로 출력")
    args = ap.parse_args()

    if not args.dsn:
        print("DATABASE_URL이 없다", file=sys.stderr)
        return 2

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        except (AttributeError, OSError, ValueError):
            pass

    try:
        rows, summary = run(args.dsn)
    except Exception as exc:  # noqa: BLE001
        print(f"DB에 닿지 못했다: {exc}", file=sys.stderr)
        return 2

    (render_md if args.md else render_text)(rows, summary)
    return 0 if all(r["n"] > 0 for r in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
