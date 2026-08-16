"""적재 상태 자가 점검 — "지금 실데이터로 켜면 무엇이 죽는가".

`MOCK_MODE=false`로 내리는 날에 제일 위험한 것은 **500이 나는 것이 아니라
200이 나면서 순위가 조용히 무의미해지는 것**이다. 컬럼이 비어 있으면 그 항은
중립값으로 계산되고, 응답은 정상처럼 보이는데 모든 POI의 점수가 같아진다.

이 스크립트는 B가 읽는 입력을 전부 훑어서 두 가지를 답한다.

    1. 후보가 남기는 하는가            (하나라도 0이면 추천이 최근접 폴백으로 주저앉는다)
    2. 지금 순위를 실제로 움직이는 가중치가 몇 %인가

②가 이 도구의 핵심이다. "적재 끝났다"와 "추천이 의미 있다" 사이의 거리를
숫자로 만든다. 항이 중립으로 쉬면 그 가중치는 순위에 아무 기여를 못 한다.

사용:
    $env:DATABASE_URL = "postgresql://..."
    python -m tools.check_data_readiness
    python -m tools.check_data_readiness --conf-min 0.0   # 임계값을 낮췄을 때의 전망

종료 코드: 0 정상 · 1 치명(후보가 안 남음) · 2 DB에 못 붙음
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass

import psycopg
from psycopg.rows import dict_row

from app.constants import W

# 스냅샷이 이보다 오래되면 15분 폴링이 죽은 것이다 (live_signals와 같은 기준).
SNAPSHOT_STALE_MIN = 40

# A가 채워야 하는 고정 행수. 어휘가 유한하다는 성질에서 나온 숫자다.
TAG_EMBEDDING_ROWS = 16          # 분위기 10 + 목적 6
QUERY_VECTOR_ROWS = 72           # 목적 6 × 날씨 4 × 인원밴드 3


def _init_marks() -> dict[str, str]:
    """콘솔이 감당하는 기호를 고른다.

    Windows 기본 콘솔은 cp949라 이모지에서 UnicodeEncodeError로 **죽는다.**
    점검 도구가 점검 대상보다 먼저 죽으면 곤란하다. UTF-8로 바꿔 보고,
    안 되면 ASCII로 내려간다 — 판정만 읽히면 되는 출력이다.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")     # type: ignore[union-attr]
        except (AttributeError, OSError, ValueError):
            pass
    try:
        "✅⚠️❌".encode(sys.stdout.encoding or "utf-8")
        return {"ok": "✅", "warn": "⚠️", "bad": "❌"}
    except (UnicodeEncodeError, LookupError):
        return {"ok": "[ OK ]", "warn": "[WARN]", "bad": "[FAIL]"}


MARKS = _init_marks()


@dataclass
class Check:
    """점수 항 하나가 살아 있는지, 죽었으면 무엇이 사라지는지."""

    label: str
    term: str | None            # 이 입력이 없으면 쉬는 점수 항 (constants.W의 키)
    sql: str
    owner: str = "A"
    fatal: bool = False         # 비면 후보 자체가 안 남는가
    # 0은 아닌데 이만큼도 안 되면 경고한다. 0건보다 **더 위험할 수 있다** —
    # 0건은 최근접 폴백으로 티가 나지만, 극소수면 정상처럼 보이면서 추천이
    # 그 몇 건에만 쏠린다. W1 seed의 난수 속성이 남아 있는 경우가 정확히 이것이다.
    thin_below: float | None = None
    note: str = ""
    thin_note: str = ""
    filled: int = 0
    total: int = 0
    error: str = ""

    @property
    def rate(self) -> float:
        return self.filled / self.total if self.total else 0.0

    @property
    def alive(self) -> bool:
        """절반 넘게 채워졌으면 그 항이 순위를 가른다고 본다.

        전부 차야 하는 게 아니다. 일부만 차 있어도 POI 사이에 차이가 생기면
        순위는 움직인다. 반대로 0건이면 전 POI가 같은 값이라 기여가 정확히 0이다.
        """
        return self.total > 0 and self.rate >= 0.5

    @property
    def thin(self) -> bool:
        """0건은 아닌데 후보 풀이라고 부르기 민망한 수준인가."""
        if self.thin_below is None or self.error:
            return False
        return 0 < self.rate < self.thin_below


# 채움률은 전부 poi 전체를 분모로 잡는다. "몇 건 있느냐"가 아니라
# "몇 %의 POI가 이 축에서 서로 구분되느냐"가 순위를 결정한다.
CHECKS: list[Check] = [
    Check(
        label="poi 적재",
        term=None,
        fatal=True,
        sql="SELECT count(*) AS filled, count(*) AS total FROM poi",
        note="0이면 503이다. 그 앞은 볼 것도 없다",
    ),
    Check(
        label="attr_confidence ≥ 임계값",
        term=None,
        fatal=True,
        sql=(
            "SELECT count(*) FILTER (WHERE attr_confidence >= %(conf_min)s) AS filled,"
            " count(*) AS total FROM poi"
        ),
        thin_below=0.10,
        note="0이면 하드필터가 전멸 → 최근접 폴백(순위 없는 3건)",
        thin_note=(
            "통과가 극소수다. 추천이 이 몇 건에만 쏠리는데 겉보기는 정상이라 "
            "0건보다 알아채기 어렵다. W1 seed의 난수 속성이 남아 있지 않은지 "
            "확인한다 (roleA `qc_final_poi_db.py` → 'mock 값 의심 POI')"
        ),
    ),
    Check(
        label="segment_affinity 조인",
        term="segment_affinity",
        sql=(
            "SELECT count(*) FILTER (WHERE p.commercial_area_id IS NOT NULL) AS filled,"
            " count(*) AS total FROM poi p"
        ),
        note="상권 코드가 없으면 세그먼트 통계를 붙일 축이 없다",
    ),
    Check(
        label="purpose_tags",
        term="purpose_match",
        sql=(
            "SELECT count(*) FILTER (WHERE purpose_tags IS NOT NULL"
            " AND cardinality(purpose_tags) > 0) AS filled,"
            " count(*) AS total FROM poi"
        ),
        note="LLM 속성 추출(A3-2) 산출물",
    ),
    Check(
        label="tag_vector (취향 축)",
        term="taste_similarity",
        sql=(
            "SELECT count(*) FILTER (WHERE tag_vector IS NOT NULL) AS filled,"
            " count(*) AS total FROM poi"
        ),
        note="tag_embedding 16행도 함께 있어야 한다 (아래 참조)",
    ),
    Check(
        label="outdoor_exposure (날씨 축)",
        term="context_fit",
        sql=(
            "SELECT count(*) FILTER (WHERE outdoor_exposure IS DISTINCT FROM 0) AS filled,"
            " count(*) AS total FROM poi"
        ),
        note="전 건이 기본값 0이면 실내/야외 구분이 없어 날씨가 순위를 못 바꾼다",
    ),
    Check(
        label="quality_score",
        term="quality",
        sql=(
            "SELECT count(*) FILTER (WHERE quality_score IS NOT NULL) AS filled,"
            " count(*) AS total FROM poi"
        ),
        note="A4-4 산출물. sentiment_score만 있고 이게 없으면 아직이다",
    ),
    Check(
        label="hotspot_code (실시간 축)",
        term="live_segment_match",
        sql=(
            "SELECT count(*) FILTER (WHERE hotspot_code IS NOT NULL) AS filled,"
            " count(*) AS total FROM poi"
        ),
        note="반경 밖은 NULL이 정상이다. 다만 전 건 NULL이면 매핑(A3-3)이 아직이다",
    ),
    Check(
        label="hotspot_snapshot (혼잡 예보)",
        term="crowd_fit",
        sql=(
            "SELECT count(*) FILTER (WHERE fcst IS NOT NULL) AS filled,"
            " count(*) AS total FROM hotspot_snapshot"
        ),
        note="fcst가 비면 방문 시각 예보가 사라지고 실황으로 물러선다",
    ),
]

# 점수 항과 직접 이어지지는 않지만 비면 티가 나는 것들.
SIDE_CHECKS: list[Check] = [
    Check(
        label="tag_embedding",
        term=None,
        sql="SELECT count(*) AS filled, %(tag_rows)s AS total FROM tag_embedding",
        note=f"{TAG_EMBEDDING_ROWS}행이어야 한다. 없으면 온보딩 taste_vector가 NULL",
    ),
    Check(
        label="query_vector_cache",
        term=None,
        sql="SELECT count(*) AS filled, %(qv_rows)s AS total FROM query_vector_cache",
        note=f"{QUERY_VECTOR_ROWS}행. 없어도 인용은 나간다(최신순 폴백) — 정확도만 떨어진다",
    ),
    Check(
        label="review_chunk 임베딩",
        term=None,
        sql=(
            "SELECT count(*) FILTER (WHERE embedding IS NOT NULL) AS filled,"
            " count(*) AS total FROM review_chunk"
        ),
        note="임베딩이 없는 청크도 인용에는 쓴다. 벡터 정렬만 못 한다",
    ),
]


def run(cur, check: Check, params: dict) -> None:
    try:
        cur.execute(check.sql, params)
        row = cur.fetchone() or {}
        check.filled = int(row.get("filled") or 0)
        check.total = int(row.get("total") or 0)
    except Exception as exc:  # 테이블 자체가 없는 경우가 대부분이다
        check.error = str(exc).strip().splitlines()[0]


def mark_for(check: Check) -> str:
    if check.error:
        return MARKS["bad"]
    if check.thin:
        return MARKS["warn"]
    if check.fatal:
        return MARKS["ok"] if check.filled > 0 else MARKS["bad"]
    if check.filled == 0:
        return MARKS["bad"]
    return MARKS["ok"] if check.alive else MARKS["warn"]


def render(checks: list[Check]) -> None:
    width = max(len(c.label) for c in checks)
    for c in checks:
        if c.error:
            print(f"  {MARKS['bad']} {c.label:<{width}}  조회 실패 — {c.error}")
            continue
        pct = f"{c.rate * 100:5.1f}%"
        counts = f"{c.filled:,}/{c.total:,}"
        weight = f"  가중치 {W[c.term]:.2f}" if c.term else ""
        print(f"  {mark_for(c)} {c.label:<{width}}  {pct}  ({counts}){weight}")
        note = c.thin_note if (c.thin and c.thin_note) else c.note
        if note and mark_for(c) != MARKS["ok"]:
            print(f"      └ {note}")


def snapshot_age(cur) -> str:
    try:
        cur.execute(
            "SELECT extract(epoch FROM now() - max(observed_at)) / 60 AS m"
            " FROM hotspot_snapshot"
        )
        row = cur.fetchone() or {}
        minutes = row.get("m")
    except Exception as exc:
        return f"{MARKS['bad']} 조회 실패 — {str(exc).strip().splitlines()[0]}"

    if minutes is None:
        return f"{MARKS['bad']} 스냅샷이 한 건도 없다 — 15분 폴링(A3-4) 미가동"
    minutes = float(minutes)
    mark = MARKS["ok"] if minutes <= SNAPSHOT_STALE_MIN else MARKS["warn"]
    tail = "" if minutes <= SNAPSHOT_STALE_MIN else f" (>{SNAPSHOT_STALE_MIN}분 — 폴링이 멈췄다)"
    return f"{mark} 최근 스냅샷 {minutes:.0f}분 전{tail}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dsn", default=os.environ.get("DATABASE_URL"))
    ap.add_argument(
        "--conf-min",
        type=float,
        default=float(os.environ.get("ATTR_CONFIDENCE_MIN", 0.30)),
        help="후보 필터의 신뢰도 하한. 서버 설정과 같은 값을 넣어야 의미가 있다",
    )
    ap.add_argument("--connect-timeout", type=int, default=10, help="접속 대기 상한(초)")
    args = ap.parse_args()

    if not args.dsn:
        print("DATABASE_URL이 없다", file=sys.stderr)
        return 2

    params = {
        "conf_min": args.conf_min,
        "tag_rows": TAG_EMBEDDING_ROWS,
        "qv_rows": QUERY_VECTOR_ROWS,
    }

    try:
        # 상한을 안 두면 닿지 않는 DSN에서 그냥 멈춘다. 전환일에 제일 곤란한 건
        # 실패가 아니라 **응답 없는 도구**다. app/db.py와 같은 규약으로 끊는다.
        conn = psycopg.connect(
            args.dsn, row_factory=dict_row, connect_timeout=args.connect_timeout
        )
    except Exception as exc:
        print(f"DB에 닿지 못했다: {exc}", file=sys.stderr)
        return 2

    with conn, conn.cursor() as cur:
        for c in CHECKS + SIDE_CHECKS:
            run(cur, c, params)
            conn.rollback()      # 실패한 문장이 트랜잭션을 막지 않게

        print(f"\n후보 필터 기준: attr_confidence >= {args.conf_min}\n")
        print("점수 항에 직결되는 것")
        render(CHECKS)
        print("\n그 밖에")
        render(SIDE_CHECKS)
        print(f"\n  {snapshot_age(cur)}")

    # --- 결론 ---------------------------------------------------------------
    fatal = [c for c in CHECKS if c.fatal and (c.error or c.filled == 0)]
    thin = [c for c in CHECKS if c.thin]
    scored = [c for c in CHECKS if c.term]
    live_w = sum(W[c.term] for c in scored if c.alive)
    total_w = sum(W[c.term] for c in scored)
    dead = [c for c in scored if not c.alive]

    print("\n" + "─" * 60)
    if fatal:
        print(f"{MARKS['bad']} 지금 MOCK_MODE=false로 내리면 안 된다.")
        for c in fatal:
            print(f"   {c.label}: {c.note}")
        print("   → 최근접 폴백으로 밀려 '순위 없는 3건'이 나간다.")
    elif thin:
        print(f"{MARKS['warn']} 후보는 남지만 **극소수다.** 0건보다 알아채기 어렵다.")
        for c in thin:
            print(f"   {c.label}: {c.filled:,}/{c.total:,} ({c.rate * 100:.1f}%)")
            print(f"      {c.thin_note or c.note}")
        print("   → 겉보기는 정상인데 추천이 그 몇 건에만 쏠린다. 먼저 확인한다.")
    else:
        print(f"{MARKS['ok']} 후보는 남는다. 추천이 최근접 폴백으로 주저앉지는 않는다.")

    print(
        f"\n순위를 실제로 움직이는 가중치: {live_w:.2f} / {total_w:.2f}"
        f" ({live_w / total_w * 100:.0f}%)"
    )
    if dead:
        print("쉬고 있는 항 (전 POI가 같은 값 → 순위 기여 0):")
        for c in dead:
            print(f"   · {c.label} — 가중치 {W[c.term]:.2f} · 담당 {c.owner}")

    return 1 if fatal else 0


if __name__ == "__main__":
    raise SystemExit(main())
