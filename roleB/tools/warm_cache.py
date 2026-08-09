"""발표 전날 캐시 워밍 (B6-4).

시나리오 20개를 미리 호출해 `explanation_cache`를 채운다. 그러면 발표 중
LLM 호출이 **0회**가 되어 쿼터·네트워크 사고가 원천 차단된다. 무료 티어
데모의 최대 안전장치다 (PLAN.md §9.3 · ROLE_B §W6 B6-4).

두 가지를 함께 한다.
  1. **워밍** — 각 시나리오를 두 번 부른다. 두 번째가 `explain_mode: cache`면
     성공이다. 한 번만 부르면 "캐시에 들어갔는지" 확인할 방법이 없다.
  2. **스모크 체크** — 200인가, 결과가 비지 않았는가, 인용이 붙었는가.
     어차피 20개를 태우는 김에 본다. 발표 전날 밤에 알아야 할 것들이다.

⚠️ 반드시 알아야 할 것 두 개
----------------------------
- **`LLM_API_KEY`가 없으면 캐시는 채워지지 않는다.** 설명이 템플릿으로 나가고
  저장할 LLM 결과가 없기 때문이다. 이 스크립트는 그 상태를 감지해 알려준다.
  키 없이 데모한다면 워밍은 불필요하다 — 템플릿은 언제나 즉시 나온다.
- **레이트 리밋(분당 10회)에 걸린다.** 20개 × 2회 = 40호출이다. 기본값은
  간격을 벌려서 간다. 서버에서 `RATE_LIMIT_PER_MIN=0`을 켰다면 `--no-pace`.

사용:
    python -m tools.warm_cache --url https://dacos-wheretogo.onrender.com
    python -m tools.warm_cache --url http://localhost:8000 --no-pace
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from datetime import datetime
from typing import Any

from tools import scenarios as sc

TIMEOUT = 60.0          # 콜드스타트 + LLM 생성. 첫 호출은 오래 걸린다


def _post(url: str, payload: dict[str, Any]) -> tuple[int, dict[str, Any] | None, str]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8")), ""
    except urllib.error.HTTPError as exc:
        return exc.code, None, exc.reason or ""
    except Exception as exc:  # noqa: BLE001
        return 0, None, str(exc)


def _modes(data: dict[str, Any] | None) -> list[str]:
    if not data:
        return []
    return [r.get("explain_mode", "?") for r in data.get("results", [])]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8000")
    ap.add_argument("--file", default=None, help="시나리오 JSON 경로")
    ap.add_argument("--rate-limit", type=int, default=10,
                    help="서버의 RATE_LIMIT_PER_MIN. 이에 맞춰 간격을 벌린다")
    ap.add_argument("--no-pace", action="store_true")
    ap.add_argument("--passes", type=int, default=2,
                    help="시나리오당 호출 횟수. 2면 두 번째로 캐시 적중을 확인한다")
    args = ap.parse_args()

    rows = sc.load(args.file)
    endpoint = args.url.rstrip("/") + "/api/recommend"
    interval = 0.0 if args.no_pace else sc.pacing_interval(args.rate_limit)
    now = datetime.now(sc.KST)

    total_calls = len(rows) * args.passes
    eta = total_calls * interval
    print(f"대상 {endpoint}")
    print(f"시나리오 {len(rows)} × {args.passes}회 = {total_calls}호출 "
          f"· 간격 {interval:.1f}s · 예상 {eta / 60:.1f}분\n")

    mode_counter: Counter[str] = Counter()
    errors: Counter[int] = Counter()
    empty: list[str] = []
    no_evidence: list[str] = []
    last_modes: dict[str, list[str]] = {}

    for p in range(args.passes):
        label = "워밍" if p == 0 else f"확인 {p}"
        for s in rows:
            status, data, reason = _post(endpoint, sc.to_payload(s, now))
            if status != 200:
                errors[status] += 1
                print(f"  ❌ {s.id} {status} {reason}")
            else:
                modes = _modes(data)
                last_modes[s.id] = modes
                if p == args.passes - 1:
                    mode_counter.update(modes)
                    if not data.get("results"):
                        empty.append(s.id)
                    elif not any(r.get("evidence") for r in data["results"]):
                        no_evidence.append(s.id)
            if interval:
                time.sleep(interval)
        print(f"[{label}] {len(rows)}건 완료")

    print("\n=== 마지막 회차 explain_mode ===")
    for mode, n in mode_counter.most_common():
        print(f"  {mode:9s} {n}")

    if errors:
        print(f"\n❌ 에러 {dict(errors)}")
        if errors.get(429):
            print("   429 — 간격이 부족하다. --rate-limit을 서버 설정과 맞춰라")
    if empty:
        print(f"\n❌ 빈 결과: {', '.join(empty)}")
        print("   어떤 조건에서도 빈 배열을 내지 않아야 한다 (ROLE_B §1.3)")
    if no_evidence:
        print(f"\n⚠️ 인용이 하나도 없는 시나리오: {', '.join(no_evidence)}")
        print("   그 지역 POI에 review_chunk가 없다는 뜻이다. 데모 시나리오라면 A에게")

    cached = mode_counter.get("cache", 0)
    llm_calls = mode_counter.get("llm", 0)
    template = mode_counter.get("template", 0)

    print()
    if template and not cached and not llm_calls:
        print("⚠️ 전부 template이다 — LLM_API_KEY가 없거나 쿼터가 소진됐다.")
        print("   이 상태에서는 캐시를 채울 것이 없다. 워밍이 필요 없다는 뜻이기도 하다")
        print("   (템플릿 설명은 LLM 없이 즉시 나가므로 데모는 그대로 가능하다)")
        return 0
    if llm_calls and not errors:
        print(f"⚠️ 마지막 회차에도 LLM 호출이 {llm_calls}건 남았다.")
        print("   캐시 키가 매번 달라지는 것일 수 있다 — 후보 목록이 요청마다 바뀌면")
        print("   (탐색 슬롯이 아니라 상위 20이 바뀌면) 캐시가 안 맞는다")
        return 1
    if cached and not errors:
        print(f"✅ 워밍 완료 — 마지막 회차 {cached}건이 캐시에서 나왔다. "
              "발표 중 LLM 호출 0회")
        return 0
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
