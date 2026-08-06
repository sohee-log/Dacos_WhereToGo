"""LLM 무료 티어 한도 실측 (B1-5).

**이 숫자 하나로 A의 속성추출 배치 소요일이 결정된다.** 늦게 알면 A의 일정이 통째로 밀린다.
그래서 W1에 잰다.

무료 티어의 병목은 비용이 아니라 분당(RPM)·일일(RPD) 호출 제한이다. 문서에 적힌
공식 한도와 실제로 계정에 걸린 한도가 다른 경우가 흔하므로 **직접 때려 보고 확인**한다.

사용법
------
    # OpenAI 호환 엔드포인트면 무엇이든 된다 (Gemini OpenAI-compat, Groq, OpenRouter …)
    export LLM_API_KEY=...
    export LLM_BASE_URL=https://.../v1
    export LLM_MODEL=...

    python tools/llm_quota_probe.py --rpm-probe 20 --confirm
    python tools/llm_quota_probe.py --rpm-probe 20 --confirm --out docs/llm_quota_report.json

주의
----
- **실제 호출이 나간다.** 그래서 `--confirm` 없이는 아무것도 보내지 않는다.
- 하루 한도까지 태우면 그날 배치가 막힌다. 처음엔 작은 값(10~20)으로 시작한다.
- 일일 한도(RPD)는 한 번의 실행으로 알 수 없다. 응답 헤더에 있으면 읽고,
  없으면 배치를 하루 돌려 보고 `docs/LLM_QUOTA.md`에 실측치를 적는다.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Any

try:
    import httpx
except ImportError:  # pragma: no cover
    print("httpx가 필요하다: pip install -r requirements-dev.txt", file=sys.stderr)
    raise SystemExit(1)

# 속성추출 프롬프트와 비슷한 길이로 때려야 의미 있는 수치가 나온다.
PROBE_PROMPT = (
    "다음 후기에서 야외 노출도(0~1)와 단체 수용 인원을 JSON으로만 답하라. "
    "근거가 없으면 null. 후기: 창가 자리가 넓고 4인석이 여러 개 있었습니다."
)

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
)


def call_once(client: httpx.Client, base_url: str, model: str, api_key: str) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        r = client.post(
            f"{base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": model,
                "messages": [{"role": "user", "content": PROBE_PROMPT}],
                "max_tokens": 64,
                "temperature": 0,
            },
        )
        elapsed = time.perf_counter() - started
        headers = {k: v for k, v in r.headers.items() if k.lower() in RATE_HEADER_HINTS}
        return {
            "status": r.status_code,
            "elapsed_s": round(elapsed, 3),
            "rate_headers": headers,
            "error": None if r.status_code < 400 else r.text[:200],
        }
    except httpx.HTTPError as e:
        return {
            "status": None,
            "elapsed_s": round(time.perf_counter() - started, 3),
            "rate_headers": {},
            "error": f"{type(e).__name__}: {e}",
        }


def batch_days(rpd: int | None, rpm: int | None, poi_count: int, calls_per_poi: int) -> str:
    """실측 한도 → A의 속성추출 배치 소요일. 이게 이 스크립트의 존재 이유다."""
    total_calls = poi_count * calls_per_poi
    if rpd:
        return f"{total_calls / rpd:.1f}일 (일일 한도 {rpd}회 기준)"
    if rpm:
        per_night = rpm * 60 * 8  # 밤 8시간 무인 배치 가정
        return f"{total_calls / per_night:.1f}일 (분당 {rpm}회 × 야간 8시간 기준)"
    return "한도 미확인 — 산정 불가"


def main() -> int:
    ap = argparse.ArgumentParser(description="LLM 무료 티어 한도 실측")
    ap.add_argument("--rpm-probe", type=int, default=15, help="1분 안에 보낼 요청 수")
    ap.add_argument("--interval", type=float, default=1.0, help="요청 간격(초)")
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
            "실제 API 호출이 나간다. 무료 쿼터를 소모한다.\n"
            f"  대상: {model} @ {base_url}\n"
            f"  요청: {args.rpm_probe}회 ({args.interval}초 간격)\n"
            "진행하려면 --confirm 을 붙인다."
        )
        return 0

    results: list[dict[str, Any]] = []
    first_429_at: int | None = None

    with httpx.Client(timeout=60.0) as client:
        for i in range(args.rpm_probe):
            res = call_once(client, base_url, model, api_key)
            res["index"] = i + 1
            results.append(res)
            flag = "OK " if res["status"] == 200 else f"!! {res['status']}"
            print(f"[{i + 1:>3}/{args.rpm_probe}] {flag} {res['elapsed_s']}s "
                  f"{res['rate_headers'] or ''}")
            if res["status"] == 429 and first_429_at is None:
                first_429_at = i + 1
                print("→ 429. 여기가 분당 상한이다. 중단한다.")
                break
            if i < args.rpm_probe - 1:
                time.sleep(args.interval)

    ok = [r for r in results if r["status"] == 200]
    observed_rpm = first_429_at - 1 if first_429_at else None
    latencies = sorted(r["elapsed_s"] for r in ok)

    # 헤더에서 일일 한도를 알 수 있으면 줍는다
    rpd_header = None
    for r in results:
        for k, v in r["rate_headers"].items():
            if "limit-requests" in k:
                try:
                    rpd_header = int(v)
                except ValueError:
                    pass

    report = {
        "model": model,
        "base_url": base_url,
        "sent": len(results),
        "ok": len(ok),
        "first_429_at": first_429_at,
        "observed_rpm_floor": observed_rpm,
        "rpd_from_header": rpd_header,
        "latency_s": {
            "min": latencies[0] if latencies else None,
            "median": latencies[len(latencies) // 2] if latencies else None,
            "max": latencies[-1] if latencies else None,
        },
        "batch_estimate": batch_days(
            rpd_header, observed_rpm, args.poi_count, args.calls_per_poi
        ),
        "rate_headers_seen": sorted({k for r in results for k in r["rate_headers"]}),
    }

    print("\n--- 결과 ---")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(
        "\n429가 한 번도 안 났으면 분당 상한을 아직 못 찾은 것이다. "
        "--rpm-probe 를 올려 다시 잰다."
    )
    print("이 숫자를 docs/LLM_QUOTA.md 표에 적고 A에게 전달한다.")

    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump({"report": report, "raw": results}, f, ensure_ascii=False, indent=2)
        print(f"\n저장: {args.out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
