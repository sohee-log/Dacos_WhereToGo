"""쿼리 플랜 점검 (B6-2).

p95만 보면 **왜** 빠른지 모른다. 데이터가 적어서 빠른 것과 인덱스를 타서 빠른
것은 규모가 커지는 순간 갈린다. 그래서 실행 계획을 함께 본다.

**`retrieval.py`의 SQL 상수를 그대로 가져다 EXPLAIN한다.** 여기에 SQL을 다시
적으면 코드가 바뀔 때 조용히 어긋나고, 그러면 "옛날 쿼리는 인덱스를 탔다"를
확인하게 된다.

사용:
    $env:DATABASE_URL = "postgresql://..."
    python -m tools.query_plan
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import datetime, timedelta, timezone

import psycopg
from psycopg.rows import dict_row

from app.services import rag, retrieval

KST = timezone(timedelta(hours=9))

# 인덱스를 탔다고 볼 수 있는 노드. 하나도 없으면 전체 스캔이다.
INDEX_NODES = ("Index Scan", "Index Only Scan", "Bitmap Index Scan")

# 이 행수 아래의 테이블은 Seq Scan이 정상이다. 플래너가 인덱스를 안 쓰는 게 아니라
# **쓸 이유가 없는 것**이다. 여기를 실패로 잡으면 도구가 늑대소년이 된다.
SEQ_SCAN_TOLERANCE = 1_000

_SEQ_SCAN = re.compile(r"Seq Scan on (\w+)")

CHECKS = [
    (
        "후보 생성 (poi + PostGIS)",
        retrieval.CANDIDATE_SQL,
        {
            "lat": 37.5340, "lng": 126.9946, "radius_m": 1200,
            "visit_at": datetime.now(KST), "party_size": 2, "budget_band": 3,
            "rain_prob": 0.1, "pm25_grade": 2, "conf_min": 0.30,
            "limit": 500, "user_id": "u_plan_probe",
        },
        "idx_poi_geom",
    ),
    (
        "인용 검색 (review_chunk, 사전필터)",
        rag.EVIDENCE_FALLBACK_SQL,
        {"poi_ids": ["p_1", "p_2"], "per_poi": 3},
        "idx_chunk_poi",
    ),
    (
        "최신 지점 스냅샷",
        retrieval.HOTSPOT_LATEST_SQL,
        {},
        None,
    ),
]


def explain(cur, sql: str, params: dict) -> str:
    cur.execute("EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT) " + sql, params)
    return "\n".join(r["QUERY PLAN"] for r in cur.fetchall())


def table_rows(cur, name: str) -> int:
    """실제 행수. reltuples는 VACUUM 전이면 -1이라 믿을 수 없다."""
    try:
        cur.execute(f'SELECT count(*) AS n FROM "{name}"')  # noqa: S608 - 플랜에서 온 식별자
        return int(cur.fetchone()["n"])
    except Exception:
        return 0


def heavy_seq_scans(cur, plan: str) -> list[tuple[str, int]]:
    """규모가 있는데 전체 스캔으로 떨어진 테이블만 골라낸다."""
    out = []
    for name in sorted(set(_SEQ_SCAN.findall(plan))):
        n = table_rows(cur, name)
        if n > SEQ_SCAN_TOLERANCE:
            out.append((name, n))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dsn", default=os.environ.get("DATABASE_URL"))
    ap.add_argument("--verbose", action="store_true", help="플랜 전문을 출력한다")
    args = ap.parse_args()

    if not args.dsn:
        print("DATABASE_URL이 없다", file=sys.stderr)
        return 2

    failed = 0
    with psycopg.connect(args.dsn, row_factory=dict_row) as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) AS n FROM poi")
        print(f"poi {cur.fetchone()['n']}행 기준\n")

        for title, sql, params, want_index in CHECKS:
            try:
                plan = explain(cur, sql, params)
            except Exception as exc:
                print(f"❌ {title}: EXPLAIN 실패 — {exc}\n")
                failed += 1
                conn.rollback()
                continue

            exec_ms = 0.0
            for line in plan.splitlines():
                if line.strip().startswith("Execution Time:"):
                    exec_ms = float(line.split(":")[1].strip().split()[0])

            heavy = heavy_seq_scans(cur, plan)
            index_ok = want_index is None or want_index in plan

            mark = "✅"
            notes: list[str] = []
            if heavy:
                mark = "❌"
                failed += 1
                notes.append(
                    "전체 스캔: " + ", ".join(f"{t}({n:,}행)" for t, n in heavy)
                )
            elif not index_ok:
                mark = "⚠️"
                notes.append(f"기대 인덱스 {want_index}를 쓰지 않았다")
            elif want_index:
                notes.append(f"{want_index} 사용")

            small_seq = [t for t in set(_SEQ_SCAN.findall(plan))
                         if not any(t == h[0] for h in heavy)]
            if small_seq:
                notes.append(
                    f"작은 테이블 Seq Scan(정상): {', '.join(sorted(small_seq))}"
                )

            print(f"{mark} {title}: {exec_ms:.1f}ms")
            for note in notes:
                print(f"    {note}")
            if args.verbose:
                print("    " + plan.replace("\n", "\n    ") + "\n")

    print()
    if failed:
        print(f"❌ 규모 있는 테이블이 전체 스캔으로 떨어졌다 ({failed}건). "
              "규모가 커지면 300ms를 넘긴다")
        return 1
    print(f"✅ {SEQ_SCAN_TOLERANCE:,}행을 넘는 테이블은 전부 인덱스를 탄다")
    return 0


if __name__ == "__main__":
    sys.exit(main())
