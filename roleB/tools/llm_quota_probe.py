"""LLM 무료 티어 한도 실측 (B1-5).

**이 숫자 하나로 A의 속성추출 배치 소요일이 결정된다.** 늦게 알면 A의 일정이 통째로 밀린다.
그래서 W1에 잰다.

무료 티어의 병목은 비용이 아니라 분당(RPM)·일일(RPD) 호출 제한이다. 문서에 적힌
공식 한도와 실제로 계정에 걸린 한도가 다른 경우가 흔하고, 게이트웨이는 rate limit
헤더를 아예 내려주지 않기도 한다. 그래서 **직접 때려 보고 확인**한다.

사용법
------
    # OpenAI 호환 엔드포인트면 무엇이든 된다
    export LLM_API_KEY=...
    export LLM_BASE_URL=https://factchat-cloud.mindlogic.ai/v1/gateway
    export LLM_MODEL=gpt-5.4-nano

    python tools/llm_quota_probe.py --seq 20 --burst 15 --confirm
    python tools/llm_quota_probe.py --seq 20 --burst 15 --confirm --out docs/llm_quota_report.json

두 가지를 잰다.
  1. 직렬(--seq)  — 순차 호출의 지연과 실질 처리량. 야간 배치의 속도가 이 값이다
  2. 동시(--burst) — 동시성 상한. 배치를 병렬화할 수 있는지가 여기서 갈린다

주의
----
- **실제 호출이 나간다.** 그래서 `--confirm` 없이는 아무것도 보내지 않는다.
- 프롬프트와 `max_tokens`를 일부러 최소로 잡았다. 한도를 재는 데 긴 응답은 필요 없다.
- 일일 한도(RPD)는 한 번의 실행으로 알 수 없다. 헤더에 있으면 읽고, 없으면 배치를
  하루 돌려 보고 `docs/LLM_QUOTA.md`에 실측치를 적는다.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

try:
    import httpx
except ImportError:  # pragma: no cover
    print("httpx가 필요하다: pip install -r requirements-dev.txt", file=sys.stderr)
    raise SystemExit(1)

# 한도를 재는 것이 목적이므로 프롬프트는 최소로 유지한다.
# 속성추출 실제 프롬프트는 이보다 훨씬 길다 — 지연은 여기서 잰 값보다 커진다.
PROBE_PROMPT = "JSON만 답하라: {\"ok\":1}"
PROBE_MAX_TOKENS = 16

# 제공자마다 이름이 다르다. 있는 것만 주워 담는다.
RATE_HEADER_HINTS = (
    "x-ratelimit-limit-requests",
    "x-ratelimit-remaining-requests",
    "x-ratelimit-reset-requests",
    "x-ratelimit-limit-tokens",
    "x-ratelimit-remaining-tokens",
    "ratelimit-limit",
    "ratelimit-remaining",
    "ratelimit-reset",
    "retry-after",
    "x-quota-remaining",
)


def call_once(client: httpx.Client, base_url: str, model: str, api_key: str) -> dict[str, Any]:
    """1회 호출. 예외를 올리지 않고 결과를 dict로 돌려준다."""
    started = time.perf_counter()
    try:
        r = client.post(
            # 게이트웨이는 끝 슬래시를 요구할 수 있다. 붙이는 쪽이 안전하다.
            f"{base_url.rstrip('/')}/chat/completions/",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": model,
                "messages": [{"role": "user", "content": PROBE_PROMPT}],
                "max_tokens": PROBE_MAX_TOKENS,
            },
        )
        elapsed = time.perf_counter() - started
        headers = {k: v for k, v in r.headers.items() if k.lower() in RATE_HEADER_HINTS}
        usage: dict[str, Any] = {}
        if r.status_code == 200:
            try:
                usage = r.json().get("usage") or {}
            except ValueError:
                pass
        return {
            "status": r.status_code,
            "elapsed_s": round(elapsed, 3),
            "rate_headers": headers,
            "usage": usage,
            "error": None if r.status_code < 400 else r.text[:200],
        }
    except httpx.HTTPError as e:
        return {
            "status": None,
            "elapsed_s": round(time.perf_counter() - started, 3),
            "rate_headers": {},
            "usage": {},
            "error": f"{type(e).__name__}: {e}",
        }


def run_sequential(
    client: httpx.Client, base_url: str, model: str, api_key: str,
    count: int, interval: float,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for i in range(count):
        res = call_once(client, base_url, model, api_key)
        res["index"] = i + 1
        results.append(res)
        flag = "OK " if res["status"] == 200 else f"!! {res['status']}"
        print(f"  [{i + 1:>3}/{count}] {flag} {res['elapsed_s']}s {res['rate_headers'] or ''}")
        if res["status"] == 429:
            print("  → 429. 직렬 호출에서 분당 상한에 닿았다. 중단한다.")
            break
        if interval > 0 and i < count - 1:
            time.sleep(interval)
    return results


def run_burst(
    base_url: str, model: str, api_key: str, count: int
) -> list[dict[str, Any]]:
    """동시 호출. 배치를 병렬화할 수 있는지가 여기서 갈린다."""
    def one(_: int) -> dict[str, Any]:
        with httpx.Client(timeout=90.0) as c:
            return call_once(c, base_url, model, api_key)

    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=count) as pool:
        results = list(pool.map(one, range(count)))
    wall = time.perf_counter() - started

    for i, r in enumerate(results, 1):
        r["index"] = i
    ok = sum(1 for r in results if r["status"] == 200)
    print(f"  동시 {count}건 → 성공 {ok} / 429 "
          f"{sum(1 for r in results if r['status'] == 429)} / 벽시계 {wall:.2f}s")
    return results


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    ok = [r for r in results if r["status"] == 200]
    lat = sorted(r["elapsed_s"] for r in ok)
    tok = [r["usage"].get("total_tokens", 0) for r in ok if r.get("usage")]
    return {
        "sent": len(results),
        "ok": len(ok),
        "http_429": sum(1 for r in results if r["status"] == 429),
        "other_errors": sorted(
            {str(r["status"]) for r in results if r["status"] not in (200, 429)}
        ),
        "latency_s": {
            "min": lat[0] if lat else None,
            "median": lat[len(lat) // 2] if lat else None,
            "max": lat[-1] if lat else None,
        },
        "tokens_per_call": round(sum(tok) / len(tok), 1) if tok else None,
    }


def batch_days(rpd: int | None, rpm: int | None, poi_count: int, calls_per_poi: int) -> str:
    """실측 한도 → A의 속성추출 배치 소요일. 이게 이 스크립트의 존재 이유다."""
    total_calls = poi_count * calls_per_poi
    if rpd:
        return f"{total_calls / rpd:.1f}일 (일일 한도 {rpd}회 기준)"
    if rpm:
        per_night = rpm * 60 * 8  # 밤 8시간 무인 배치 가정
        return f"{total_calls / per_night:.2f}일 (분당 {rpm}회 × 야간 8시간 기준)"
    return "한도 미확인 — 산정 불가"


def main() -> int:
    ap = argparse.ArgumentParser(description="LLM 무료 티어 한도 실측")
    ap.add_argument("--seq", type=int, default=20, help="직렬 호출 수")
    ap.add_argument("--interval", type=float, default=0.0, help="직렬 호출 간격(초)")
    ap.add_argument("--burst", type=int, default=0, help="동시 호출 수 (0이면 생략)")
    ap.add_argument("--poi-count", type=int, default=800, help="T1 목표 POI 수")
    ap.add_argument("--calls-per-poi", type=int, default=1, help="POI당 LLM 호출 수")
    ap.add_argument("--out", default=None, help="JSON 리포트 저장 경로")
    ap.add_argument("--confirm", action="store_true", help="실제 호출을 허용한다")
    args = ap.parse_args()

    api_key = os.getenv("LLM_API_KEY")
    base_url = os.getenv("LLM_BASE_URL")
    model = os.getenv("LLM_MODEL")
    missing = [n for n, v in
               (("LLM_API_KEY", api_key), ("LLM_BASE_URL", base_url), ("LLM_MODEL", model))
               if not v]
    if missing:
        print(f"환경변수가 없다: {', '.join(missing)}", file=sys.stderr)
        return 2

    if not args.confirm:
        print(
            "실제 API 호출이 나간다. 쿼터를 소모한다.\n"
            f"  대상: {model} @ {base_url}\n"
            f"  직렬 {args.seq}회 · 동시 {args.burst}회\n"
            "진행하려면 --confirm 을 붙인다."
        )
        return 0

    seq_results: list[dict[str, Any]] = []
    burst_results: list[dict[str, Any]] = []

    with httpx.Client(timeout=90.0) as client:
        if args.seq:
            print(f"[1] 직렬 {args.seq}회 (간격 {args.interval}s)")
            seq_results = run_sequential(
                client, base_url, model, api_key, args.seq, args.interval
            )

    if args.burst:
        print(f"[2] 동시 {args.burst}회")
        burst_results = run_burst(base_url, model, api_key, args.burst)

    all_results = seq_results + burst_results
    seq_sum = summarize(seq_results) if seq_results else None
    burst_sum = summarize(burst_results) if burst_results else None

    # 헤더에서 한도를 알 수 있으면 줍는다 (게이트웨이는 안 주는 경우가 많다)
    rpd_header = None
    for r in all_results:
        for k, v in r["rate_headers"].items():
            if "limit-requests" in k:
                try:
                    rpd_header = int(v)
                except ValueError:
                    pass

    # 직렬 처리량 → 관측 RPM 하한
    observed_rpm = None
    if seq_sum and seq_sum["ok"] and seq_sum["latency_s"]["median"]:
        observed_rpm = int(60 / seq_sum["latency_s"]["median"])

    report = {
        "model": model,
        "base_url": base_url,
        "sequential": seq_sum,
        "burst": burst_sum,
        "rpd_from_header": rpd_header,
        "observed_seq_rpm": observed_rpm,
        "hit_429": any(r["status"] == 429 for r in all_results),
        "batch_estimate": batch_days(
            rpd_header, observed_rpm, args.poi_count, args.calls_per_poi
        ),
        "rate_headers_seen": sorted({k for r in all_results for k in r["rate_headers"]}),
    }

    print("\n--- 결과 ---")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["hit_429"]:
        print(
            "\n429가 한 번도 안 났다. 분당 상한을 아직 못 찾은 것이다.\n"
            "다만 상한을 끝까지 찾겠다고 쿼터를 태울 이유는 없다. "
            "배치가 실제로 끊기는 지점을 A가 W3에 기록하면 된다."
        )
    print("이 숫자를 docs/LLM_QUOTA.md 표에 적고 A에게 전달한다.")

    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump({"report": report, "raw": all_results}, f, ensure_ascii=False, indent=2)
        print(f"\n저장: {args.out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
