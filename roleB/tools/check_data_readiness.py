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

from app.constants import (
    ATMOSPHERE_TAGS,
    ATTR_CONFIDENCE_RELAXED,
    PURPOSE_TAGS,
    W,
)
from app.services.live_signals import SNAPSHOT_STALE_AFTER

# 스냅샷이 이보다 오래되면 폴링이 죽은 것이다.
# **상수를 복사하지 않는다.** 엔진(`live_signals`)이 실제로 쓰는 값을 그대로 가져온다.
# 복사해 뒀더니 엔진은 90분, 도구는 40분으로 갈려서 같은 DB를 보고 서로 다른 판정을
# 냈다. 전환 게이트가 도구 쪽이라, 갈리면 잘못된 쪽을 믿게 된다.
SNAPSHOT_STALE_MIN = int(SNAPSHOT_STALE_AFTER.total_seconds() // 60)

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
        label="segment_affinity 통계",
        term="segment_affinity",
        # ⚠️ 예전엔 `poi.commercial_area_id IS NOT NULL`을 셌다. 그건 **조인 키**지
        # 통계가 아니다. 키가 95.6% 차 있어도 `segment_affinity`가 0행이면 조인
        # 결과는 전 건 NULL이고 항은 전 POI 중립(0.5)이다 — 즉 기여 0인데
        # 도구는 "살아 있음"이라고 답했다. **전환 게이트의 거짓 초록불이었다.**
        # 실제로 채워지는 쪽을 센다.
        sql=(
            "SELECT count(DISTINCT p.poi_id) AS filled, (SELECT count(*) FROM poi) AS total"
            " FROM poi p JOIN segment_affinity s"
            "   ON s.commercial_area_id = p.commercial_area_id"
            "  AND s.category_l2 = p.category_l2"
        ),
        note="상권코드×업종으로 실제 조인되는 POI 수. 0이면 개인화 근거(0.22)가 통째로 상수다",
    ),
    Check(
        label="commercial_area_id (조인 키)",
        term=None,
        sql=(
            "SELECT count(*) FILTER (WHERE commercial_area_id IS NOT NULL) AS filled,"
            " count(*) AS total FROM poi"
        ),
        note="위 통계를 붙일 축. 이것만 차 있고 통계가 비면 조인 결과는 전 건 NULL이다",
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
        # ⚠️ 예전엔 `IS DISTINCT FROM 0`이었다. **NULL이 여기에 걸린다.**
        # A의 A3-2는 리뷰에 근거가 없으면 이 컬럼을 NULL로 남기므로, 배치가 돌수록
        # 이 체크가 초록으로 물드는데 정작 순위는 하나도 안 움직인다 —
        # NULL은 엔진에서 OUTDOOR_EXPOSURE_UNKNOWN(0.0)으로 접혀 중립이 된다.
        # segment_affinity 때와 같은 종류의 거짓 초록불이라 실측만 센다.
        sql=(
            "SELECT count(*) FILTER (WHERE outdoor_exposure IS NOT NULL"
            "   AND outdoor_exposure <> 0) AS filled,"
            " count(*) AS total FROM poi"
        ),
        note=(
            "관측된 야외노출(NULL도 0도 아닌 값)만 센다. 0과 NULL은 둘 다 "
            "context_fit이 1.0(중립)이라 순위를 못 바꾼다"
        ),
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
        # ⚠️ `fcst IS NOT NULL`로는 부족하다. A가 이 컬럼을
        # `{"population": [], "weather": []}`로 넣으면 NOT NULL이면서 **빈 예보**다.
        # 슬롯 수를 직접 센다. 배열(개발용 목)과 객체(운영) 둘 다 받는다.
        sql=(
            "SELECT count(*) FILTER (WHERE jsonb_array_length("
            "  CASE jsonb_typeof(fcst)"
            "    WHEN 'array'  THEN fcst"
            "    WHEN 'object' THEN COALESCE(fcst->'population', '[]'::jsonb)"
            "    ELSE '[]'::jsonb END) > 0) AS filled,"
            " count(*) AS total FROM hotspot_latest"
        ),
        note="비면 '19시 붐빔 예상'이 사라지고 실황으로 물러선다 (FCST_PPLTN)",
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
        label="review_chunk 적재",
        term=None,
        # 임베딩 체크는 review_chunk가 **0행이면 0/0 = 0%**로 나와서 "임베딩이
        # 없다"처럼 읽힌다. 실제로는 인용할 문장 자체가 없는 것이고, 그게 훨씬
        # 나쁘다. 본체와 임베딩을 갈라서 센다. A3-2가 POI당 최대 3청크를 넣는다.
        sql=(
            "SELECT count(DISTINCT poi_id) AS filled,"
            " (SELECT count(*) FROM poi WHERE tier = 1) AS total FROM review_chunk"
        ),
        note="0이면 인용(RAG)이 전부 빈다. T1 대비 청크가 있는 POI 비율",
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
    Check(
        label="citydata 날씨 예보",
        term=None,
        # `KMA_SERVICE_KEY`가 아직 없다. 그동안 '3시간 뒤 방문'의 날씨는
        # 이 `FCST24HOURS`가 담당한다 (weather_source="citydata_fcst").
        sql=(
            "SELECT count(*) FILTER (WHERE jsonb_typeof(fcst) = 'object'"
            "   AND jsonb_array_length(COALESCE(fcst->'weather', '[]'::jsonb)) > 0"
            " ) AS filled, count(*) AS total FROM hotspot_latest"
        ),
        note="비면 '저녁에 갈 건데'가 지금 날씨로 답한다 (기상청 키가 없는 동안의 유일한 예보)",
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


# ============================================================================
# A3-2(LLM 속성 추출) 진척 — "돌긴 돌았는가"와 "돌아서 쓸 만한가"는 다르다
# ============================================================================
#
# 위 CHECKS는 poi 전체(6,644)를 분모로 잡는다. 그런데 A3-2는 **T1 800건만**
# 대상이라, 완주해도 채움률은 12%가 최대다. 그 숫자만 보면 배치가 실패한 것처럼
# 읽힌다. 여기서는 분모를 "추출이 끝난 T1"으로 바꿔서 다른 질문에 답한다 —
# 배치가 얼마나 갔고, 나온 값이 실제로 순위를 움직일 만한가.

_ATTR_COLUMNS: list[tuple[str, str]] = [
    ("outdoor_exposure", "outdoor_exposure IS NOT NULL AND outdoor_exposure <> 0"),
    ("purpose_tags", "purpose_tags IS NOT NULL AND cardinality(purpose_tags) > 0"),
    (
        "atmosphere_tags",
        "atmosphere_tags IS NOT NULL AND cardinality(atmosphere_tags) > 0",
    ),
    ("noise_level", "noise_level IS NOT NULL"),
    ("price_band", "price_band IS NOT NULL"),
    ("group_capacity", "group_capacity IS NOT NULL"),
    ("sentiment_score", "sentiment_score IS NOT NULL"),
    # ⚠️ `IS NOT NULL`로는 부족하다. LLM이 근거가 없을 때 null이 아니라
    # `{"weekday": null, "weekend": null}` **객체**를 돌려주고, A는 그걸 그대로
    # Jsonb로 넣는다(실측: 추출 10건 중 7건이 이 모양, 실제 값이 든 건 0건).
    # 컬럼은 NOT NULL인데 내용은 비어 있다 — hotspot_snapshot.fcst와 같은 함정이다.
    (
        "wait_intensity",
        "wait_intensity IS NOT NULL AND (wait_intensity->>'weekday' IS NOT NULL"
        " OR wait_intensity->>'weekend' IS NOT NULL)",
    ),
    ("business_hours", "business_hours IS NOT NULL"),
]


def _scalar(cur, sql: str, params: dict | None = None):
    cur.execute(sql, params or {})
    row = cur.fetchone() or {}
    return next(iter(row.values()), None)


def attr_extraction_progress(cur, conn, conf_min: float) -> None:
    """A3-2가 어디까지 갔고, 그 산출물이 후보 필터를 통과하는가."""
    try:
        t1 = int(_scalar(cur, "SELECT count(*) AS n FROM poi WHERE tier = 1") or 0)
        done = int(
            _scalar(
                cur,
                "SELECT count(*) AS n FROM poi"
                " WHERE tier = 1 AND attr_extracted_at IS NOT NULL",
            )
            or 0
        )
    except Exception as exc:
        conn.rollback()
        print(f"  {MARKS['bad']} 조회 실패 — {str(exc).strip().splitlines()[0]}")
        return

    if not t1:
        print(f"  {MARKS['bad']} T1 POI가 0건이다 — 티어 부여(A2)가 아직이다")
        return

    mark = MARKS["ok"] if done >= t1 else (MARKS["warn"] if done else MARKS["bad"])
    print(f"  {mark} 추출 완료  {done:,}/{t1:,}  ({done / t1 * 100:.1f}%)")
    if not done:
        print("      └ 배치가 아직 한 건도 안 돌았다 (roleA `extract_attributes.py`)")
        return

    # 분모를 "추출이 끝난 건"으로 바꾼다. 미처리분을 섞으면 품질이 진척에 가려진다.
    print(f"\n  컬럼별 관측률 (추출 완료 {done:,}건 기준 · NULL = 리뷰에 근거 없음)")
    width = max(len(name) for name, _ in _ATTR_COLUMNS)
    for name, cond in _ATTR_COLUMNS:
        try:
            n = int(
                _scalar(
                    cur,
                    "SELECT count(*) AS n FROM poi WHERE tier = 1"
                    f" AND attr_extracted_at IS NOT NULL AND ({cond})",
                )
                or 0
            )
        except Exception as exc:
            conn.rollback()
            print(f"    {MARKS['bad']} {name:<{width}}  조회 실패 — {exc}")
            continue
        rate = n / done
        m = MARKS["ok"] if rate >= 0.5 else (MARKS["warn"] if n else MARKS["bad"])
        print(f"    {m} {name:<{width}}  {rate * 100:5.1f}%  ({n:,}/{done:,})")

    # attr_confidence — 후보 하드필터가 실제로 이 값을 자른다.
    try:
        cur.execute(
            "SELECT"
            "  count(*) FILTER (WHERE attr_confidence >= %(conf_min)s) AS pass_min,"
            "  count(*) FILTER (WHERE attr_confidence >= %(relaxed)s) AS pass_relaxed,"
            "  count(*) FILTER (WHERE attr_confidence = 0) AS zeros,"
            "  avg(attr_confidence) AS avg_c,"
            "  percentile_cont(0.5) WITHIN GROUP (ORDER BY attr_confidence) AS med_c"
            " FROM poi WHERE tier = 1 AND attr_extracted_at IS NOT NULL",
            {"conf_min": conf_min, "relaxed": ATTR_CONFIDENCE_RELAXED},
        )
        row = cur.fetchone() or {}
    except Exception as exc:
        conn.rollback()
        print(f"  {MARKS['bad']} attr_confidence 조회 실패 — {exc}")
        row = {}

    if row:
        pass_min = int(row.get("pass_min") or 0)
        pass_relaxed = int(row.get("pass_relaxed") or 0)
        zeros = int(row.get("zeros") or 0)
        avg_c = float(row.get("avg_c") or 0.0)
        med_c = float(row.get("med_c") or 0.0)
        rate = pass_min / done
        m = MARKS["ok"] if rate >= 0.7 else (MARKS["warn"] if pass_min else MARKS["bad"])
        print("\n  attr_confidence (후보 하드필터가 이 값을 자른다)")
        print(
            f"    {m} >= {conf_min:.2f} (기본)   {rate * 100:5.1f}%"
            f"  ({pass_min:,}/{done:,})"
        )
        print(
            f"      >= {ATTR_CONFIDENCE_RELAXED:.2f} (완화)  "
            f"{pass_relaxed / done * 100:5.1f}%  ({pass_relaxed:,}/{done:,})"
        )
        print(f"      평균 {avg_c:.3f} · 중앙값 {med_c:.3f} · 정확히 0인 건 {zeros:,}")
        if rate < 0.7:
            print(
                "      └ A의 W4 목표는 confidence 0.5 이상이 70%다. 여기가 낮으면"
                " 배치가 끝난 뒤에도"
            )
            print("        후보가 얇아 low_confidence로 나간다")

    # 고정 어휘 위반 — 어휘 밖 문자열은 에러가 아니라 **영원한 매칭 실패**다.
    vocab_checks = (
        ("purpose_tags", PURPOSE_TAGS),
        ("atmosphere_tags", ATMOSPHERE_TAGS),
    )
    for col, vocab in vocab_checks:
        try:
            n = int(
                _scalar(
                    cur,
                    f"SELECT count(*) AS n FROM poi WHERE {col} IS NOT NULL"
                    f"   AND EXISTS (SELECT 1 FROM unnest({col}) t"
                    "               WHERE t <> ALL(%(vocab)s))",
                    {"vocab": list(vocab)},
                )
                or 0
            )
        except Exception as exc:
            conn.rollback()
            print(f"  {MARKS['bad']} {col} 어휘 검사 실패 — {exc}")
            continue
        if n:
            print(
                f"  {MARKS['bad']} {col}에 고정 어휘 밖 값이 든 POI {n:,}건 —"
                " 조인 실패가 아니라 **영원한 매칭 실패**다 (constants.py와 대조)"
            )
        else:
            print(f"  {MARKS['ok']} {col} 고정 어휘 위반 0건")


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

        print("\nA3-2 LLM 속성 추출 (T1 전용 · 분모가 위와 다르다)")
        attr_extraction_progress(cur, conn, args.conf_min)

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
