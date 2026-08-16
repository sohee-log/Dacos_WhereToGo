"""응답 성능 점검 (B6-2).

시나리오 20개를 실제 HTTP로 태워 p50/p95/p99를 낸다. `time.perf_counter()`를
파이썬 안에서 재는 것과 달리 ASGI·직렬화·네트워크가 포함된 숫자다.

목표는 ROLE_B §W4 B4-1의 **300ms**다. 넘으면 §10 판단표대로 물러선다.
    후보 수를 줄인다(반경 축소) → 인덱스 확인 → 상위 N을 20→12로

주의할 것 세 가지
-----------------
1. **레이트 리밋을 풀지 않으면 429 응답 시간을 재게 된다.** 그러면 p50이 1ms로
   나오고 "빠르다"고 착각한다. 기본값은 리밋에 맞춰 간격을 벌리고,
   `--no-pace`를 주면 서버에서 `RATE_LIMIT_PER_MIN=0`을 켰다고 가정한다.
2. **목 서버를 재면 아무 의미가 없다.** 응답에 `X-Mock-Response` 헤더가 있으면
   경고한다. 목은 DB를 안 보므로 항상 빠르다.
3. **전송 구간을 먼저 잰다.** `/health`는 DB 한 줄만 보는 엔드포인트라 그 지연이
   곧 "서버 로직과 무관한 바닥"이다. 이걸 안 재면 환경 문제를 파이프라인 탓으로
   돌리게 된다 — 실제로 겪었다. Windows에서 `localhost`가 IPv6(::1)로 먼저 풀리면
   요청마다 **2초**가 붙는데, 그걸 모르면 "p95 2.2초"라는 틀린 결론이 나온다.
   **`localhost` 대신 `127.0.0.1`을 쓴다.**

사용:
    python -m tools.perf_probe --url http://127.0.0.1:8000 --repeat 3
    python -m tools.perf_probe --url https://dacos-wheretogo.onrender.com --repeat 1
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from typing import Any

from tools import scenarios as sc

TIMEOUT = 20.0          # 콜드스타트를 기다린다. Render Free는 첫 요청이 1분까지 간다


def _post(url: str, payload: dict[str, Any]) -> tuple[int, float, dict[str, str], Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"}, method="POST"
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return resp.status, (time.perf_counter() - started) * 1000, dict(resp.headers), data
    except urllib.error.HTTPError as exc:
        return exc.code, (time.perf_counter() - started) * 1000, dict(exc.headers or {}), None
    except Exception as exc:  # noqa: BLE001 - 측정 도구다. 원인만 보이면 된다
        return 0, (time.perf_counter() - started) * 1000, {}, str(exc)


def _get(url: str) -> float:
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT) as resp:
            resp.read()
    except Exception:  # noqa: BLE001
        return float("nan")
    return (time.perf_counter() - started) * 1000


def transport_floor(base_url: str, n: int = 5) -> dict[str, float]:
    """`/health` 지연 = 서버 로직과 무관한 바닥.

    이 값이 크면 문제는 파이프라인이 아니라 전송 구간이다. 이걸 빼지 않고
    추천 지연을 해석하면 엉뚱한 곳을 최적화하게 된다.
    """
    samples = [ms for ms in (_get(base_url.rstrip("/") + "/health") for _ in range(n))
               if ms == ms]      # NaN 제외
    return sc.percentiles(samples)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8000")
    ap.add_argument("--repeat", type=int, default=3, help="시나리오당 반복 횟수")
    ap.add_argument("--file", default=None, help="시나리오 JSON 경로")
    ap.add_argument("--rate-limit", type=int, default=10,
                    help="서버의 RATE_LIMIT_PER_MIN. 이에 맞춰 간격을 벌린다")
    ap.add_argument("--no-pace", action="store_true",
                    help="간격 없이 쏜다 (서버에서 RATE_LIMIT_PER_MIN=0을 켠 경우)")
    ap.add_argument("--warmup", type=int, default=2, help="측정에서 제외할 선행 호출")
    args = ap.parse_args()

    rows = sc.load(args.file)
    endpoint = args.url.rstrip("/") + "/api/recommend"
    interval = 0.0 if args.no_pace else sc.pacing_interval(args.rate_limit)
    now = datetime.now(sc.KST)

    print(f"대상 {endpoint} · 시나리오 {len(rows)} × {args.repeat}회 "
          f"· 간격 {interval:.1f}s")
    if interval == 0.0:
        print("  ⚠️ 간격 없이 쏜다. 서버에 RATE_LIMIT_PER_MIN=0 이 켜져 있어야 한다")

    floor = transport_floor(args.url)
    if floor:
        print(f"전송 바닥(/health): p50={floor['p50']:.0f}ms p95={floor['p95']:.0f}ms")
        if floor["p50"] > 500 and "localhost" in args.url:
            print("  ⚠️ localhost가 IPv6(::1)로 먼저 풀리며 지연을 만들고 있다."
                  " --url을 127.0.0.1로 바꿔라")
        elif floor["p50"] > 500:
            print("  ⚠️ 전송 구간이 느리다. 아래 숫자에서 이만큼을 빼고 읽어야 한다")

    # 콜드스타트와 첫 쿼리 플랜 캐시를 측정에서 뺀다
    for _ in range(args.warmup):
        _post(endpoint, sc.to_payload(rows[0], now))
        if interval:
            time.sleep(interval)

    per_scenario: dict[str, list[float]] = {}
    all_ms: list[float] = []
    errors: dict[int, int] = {}
    mock_seen = False
    empty_results = 0

    for _ in range(args.repeat):
        for s in rows:
            status, ms, headers, data = _post(endpoint, sc.to_payload(s, now))
            if headers.get("X-Mock-Response") == "true":
                mock_seen = True
            if status == 200:
                per_scenario.setdefault(s.id, []).append(ms)
                all_ms.append(ms)
                if isinstance(data, dict) and not data.get("results"):
                    empty_results += 1
            else:
                errors[status] = errors.get(status, 0) + 1
            if interval:
                time.sleep(interval)

    stats = sc.percentiles(all_ms)
    print("\n=== 전체 ===")
    if stats:
        print(f"n={int(stats['n'])} min={stats['min']:.0f} p50={stats['p50']:.0f} "
              f"p95={stats['p95']:.0f} p99={stats['p99']:.0f} max={stats['max']:.0f} (ms)")
        if floor:
            print(f"전송 바닥을 뺀 서버 시간: p50≈{stats['p50'] - floor['p50']:.0f}ms "
                  f"p95≈{stats['p95'] - floor['p95']:.0f}ms")

    print("\n=== 시나리오별 p95 (느린 순) ===")
    ranked = sorted(
        ((sid, sc.percentiles(v)) for sid, v in per_scenario.items()),
        key=lambda kv: kv[1].get("p95", 0.0),
        reverse=True,
    )
    by_id = {s.id: s for s in rows}
    for sid, st in ranked[:8]:
        print(f"  {sid} p95={st['p95']:6.0f}ms  {by_id[sid].desc}")

    print()
    if errors:
        print(f"❌ 에러 {errors}")
        if 429 in errors:
            print("   429가 섞였다 — 간격이 부족하다. --rate-limit 값을 서버 설정과 맞춰라")
    if mock_seen:
        print("⚠️ 목 서버를 쟀다 (X-Mock-Response). 이 숫자는 의미가 없다")
    if empty_results:
        print(f"❌ 빈 결과 {empty_results}건 — 어떤 경로로도 빈 배열을 내지 않아야 한다")

    target = 300.0
    if stats and stats["p95"] <= target and not errors and not mock_seen:
        print(f"✅ p95 {stats['p95']:.0f}ms ≤ {target:.0f}ms")
        return 0
    if stats and stats["p95"] > target:
        print(f"❌ p95 {stats['p95']:.0f}ms > {target:.0f}ms "
              "→ 반경 축소 · 인덱스 확인 · 상위 N 20→12 (ROLE_B §10)")
    return 1


if __name__ == "__main__":
    sys.exit(main())
