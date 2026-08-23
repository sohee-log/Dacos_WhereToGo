"""개발용 시드 적재 — W2 게이트를 로컬에서 재현하기 위한 도구.

**운영 적재는 A가 한다** (`roleA/jobs/`). 이건 B가 live 경로(PostGIS + 스코어링)를
DB 없이 검증할 수 없어서 두는 최소 도구다. 컬럼도 시드에 있는 것만 채운다.
`quality_score`처럼 배치로 산출되는 값은 **일부러 NULL로 둔다** — 그래야
"값이 없을 때 중립으로 처리하는가"가 실제로 검증된다.

사용:
    docker run -d --name wheretogo-db -p 5432:5432 \
      -e POSTGRES_PASSWORD=devpass -e POSTGRES_DB=wheretogo postgis/postgis:16-3.4
    # pgvector가 없는 이미지라면: apt-get install -y postgresql-16-pgvector
    psql "$DATABASE_URL" -f db/migrations/001_init.sql

    python -m tools.load_seed_db                      # POI만
    python -m tools.load_seed_db --demo-hotspot       # + 가짜 실시간 지점/스냅샷
    python -m tools.load_seed_db --demo-vectors       # + 가짜 태그 임베딩 (취향 축 켜기)
    python -m tools.load_seed_db --scale 5000         # 성능 측정용 합성 POI

`--demo-vectors`는 태그에서 결정적으로 만든 **가짜 벡터**다. bge-m3 임베딩이
아니므로 의미는 없다. 다만 태그가 겹치는 POI끼리 코사인이 높게 나오도록 만들어서,
`<=>` 연산·halfvec 캐스팅·평균 계산이 실제로 도는지 확인할 수 있다.

`--scale`은 시드를 좌표만 흔들어 복제한다. **B4-1의 300ms 목표를 100건짜리
시드로 확인하면 아무 의미가 없다.** 인덱스가 실제로 쓰이는지는 규모가 있어야 보인다.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
import sys
from datetime import datetime, timedelta, timezone
from typing import Any

import psycopg

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_SEED = os.path.join(ROOT, "seeds", "poi_seed.json")

UPSERT_POI = """
INSERT INTO poi (
    poi_id, name, category_l1, category_l2, geom, dong, zone,
    commercial_area_id, hotspot_code, business_hours,
    outdoor_exposure, group_capacity, noise_level,
    purpose_tags, atmosphere_tags, price_band,
    sentiment_score, mention_count, review_count, attr_confidence, tier
) VALUES (
    %(poi_id)s, %(name)s, %(category_l1)s, %(category_l2)s,
    ST_SetSRID(ST_MakePoint(%(lng)s, %(lat)s), 4326)::geography,
    %(dong)s, %(zone)s, %(commercial_area_id)s, %(hotspot_code)s, %(business_hours)s,
    %(outdoor_exposure)s, %(group_capacity)s, %(noise_level)s,
    %(purpose_tags)s, %(atmosphere_tags)s, %(price_band)s,
    %(sentiment_score)s, %(mention_count)s, %(review_count)s, %(attr_confidence)s, %(tier)s
)
ON CONFLICT (poi_id) DO UPDATE SET
    name = EXCLUDED.name,
    geom = EXCLUDED.geom,
    zone = EXCLUDED.zone,
    attr_confidence = EXCLUDED.attr_confidence
"""

# 개발용 가짜 지점. 실제 코드·좌표는 '서울시 주요 121장소 목록.xlsx'에서 A가 확정한다.
DEMO_HOTSPOTS = [
    ("POI_ITW", "이태원 관광특구", 37.5345, 126.9946, "약간 붐빔",
     {"10": 6.0, "20": 34.0, "30": 24.0, "40": 16.0, "50": 12.0, "60": 8.0}),
    ("POI_YSS", "용산역", 37.5299, 126.9648, "붐빔",
     {"10": 8.0, "20": 22.0, "30": 26.0, "40": 20.0, "50": 14.0, "60": 10.0}),
]

# WEATHER_STTS 형태 그대로. 값이 전부 문자열인 것이 핵심이다 —
# 파서가 실제 응답과 같은 모양을 상대하게 해야 한다.
# WEATHER_STTS 실측 형태(V8.5). `SENSIBLE_TEMP`는 **응답에 없다** — 체감온도는
# HUMIDITY·WIND_SPD로 만든다. 개발 DB가 실제와 다른 필드를 쓰면 실황 경로가
# 여기서만 통과하고 운영에서 갈린다.
DEMO_WEATHER = {
    "WEATHER_TIME": "2026-08-23 18:20",
    "TEMP": "28.4",
    "HUMIDITY": "68",
    "WIND_SPD": "1.4",
    "PRECPT_TYPE": "없음",
    "PRECIPITATION": "-",
    "PM10": "42",
    "PM25": "23",
    "SUNRISE": "05:43",
    "SUNSET": "19:42",
    "AIR_IDX": "보통",
    "SKY_STTS": "구름많음",
}

# FCST_PPLTN 형태. 실측은 1시간 간격 12슬롯이다. 실행 시각 기준으로 만든다.
DEMO_FCST_LEVELS = ["보통", "약간 붐빔", "붐빔", "붐빔", "약간 붐빔", "보통",
                    "보통", "여유", "여유", "여유", "여유", "여유"]


def _demo_fcst(now: datetime) -> dict[str, list[dict[str, str]]]:
    """A의 `poll_citydata.py`가 넣는 형태 그대로.

    ⚠️ 배열이 아니라 **객체**다. 인구예측과 날씨예측을 한 컬럼에 함께 담는다.
    개발 DB가 배열로 남아 있으면 `forecast_weather_at`이 여기서만 비어
    "기상청 키가 없을 때의 예보"가 개발에서 검증되지 않는다.
    """
    population = [
        {
            "FCST_TIME": (now + timedelta(hours=i)).strftime("%Y-%m-%d %H:00"),
            "FCST_CONGEST_LVL": level,
        }
        for i, level in enumerate(DEMO_FCST_LEVELS)
    ]
    weather = [
        {
            "FCST_DT": (now + timedelta(hours=i)).strftime("%Y%m%d%H00"),
            "TEMP": f"{28 - i // 3}",
            "PRECIPITATION": "-",
            "PRECPT_TYPE": "없음",
            "RAIN_CHANCE": "20",
            "SKY_STTS": "구름많음",
        }
        for i in range(len(DEMO_FCST_LEVELS))
    ]
    return {"population": population, "weather": weather}


# ============================================================================
# 가짜 벡터 — 의미는 없고 구조만 진짜다
# ============================================================================

VECTOR_DIM = 1024
ATMOSPHERE_TAGS = ("조용한", "활기찬", "감성적인", "트렌디한", "로컬한",
                   "넓은", "뷰가좋은", "아늑한", "이국적인", "가성비")
PURPOSE_TAGS = ("데이트", "친구모임", "혼자", "가족", "작업", "회식")


def _tag_vector(tag: str) -> list[float]:
    """태그 하나의 기저 벡터. 같은 태그는 언제나 같은 벡터다."""
    seed = int(hashlib.sha256(tag.encode()).hexdigest()[:16], 16)
    rng = random.Random(seed)
    v = [rng.gauss(0.0, 1.0) for _ in range(VECTOR_DIM)]
    norm = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / norm for x in v]


def _mean_vector(tags: list[str]) -> list[float] | None:
    """태그들의 평균. 태그가 겹칠수록 코사인이 높아진다."""
    vectors = [_tag_vector(t) for t in tags if t]
    if not vectors:
        return None
    acc = [sum(col) for col in zip(*vectors)]
    norm = math.sqrt(sum(x * x for x in acc)) or 1.0
    return [x / norm for x in acc]


def _to_literal(vector: list[float] | None) -> str | None:
    return None if vector is None else "[" + ",".join(f"{x:.6f}" for x in vector) + "]"


def _row(raw: dict[str, Any]) -> dict[str, Any]:
    bh = raw.get("business_hours")
    return {
        "poi_id": raw["poi_id"],
        "name": raw["name"],
        "category_l1": raw.get("category_l1"),
        "category_l2": raw.get("category_l2"),
        "lat": raw["lat"],
        "lng": raw["lng"],
        "dong": raw.get("dong"),
        "zone": raw.get("zone"),
        "commercial_area_id": raw.get("commercial_area_id"),
        "hotspot_code": raw.get("hotspot_code"),
        "business_hours": json.dumps(bh) if bh else None,
        "outdoor_exposure": raw.get("outdoor_exposure", 0.0),
        "group_capacity": raw.get("group_capacity", 4),
        "noise_level": raw.get("noise_level"),
        "purpose_tags": raw.get("purpose_tags") or [],
        "atmosphere_tags": raw.get("atmosphere_tags") or [],
        "price_band": raw.get("price_band"),
        "sentiment_score": raw.get("sentiment_score"),
        "mention_count": raw.get("mention_count", 0),
        "review_count": raw.get("review_count", 0),
        "attr_confidence": raw.get("attr_confidence", 0.0),
        "tier": raw.get("tier", 3),
    }


WEATHER_STATES = ("맑음", "비", "미세먼지나쁨", "폭염한파")

UPSERT_CHUNK = """
INSERT INTO review_chunk (poi_id, source, text, embedding, is_sponsored, written_at)
SELECT %(poi_id)s, %(source)s, %(text)s, %(embedding)s::halfvec(1024),
       %(is_sponsored)s, %(written_at)s::date
WHERE EXISTS (SELECT 1 FROM poi WHERE poi_id = %(poi_id)s)
  AND NOT EXISTS (
      SELECT 1 FROM review_chunk WHERE poi_id = %(poi_id)s AND text = %(text)s
  )
"""

UPSERT_QUERY_VECTOR = """
INSERT INTO query_vector_cache (purpose, weather_state, party_band, query_text, embedding)
VALUES (%(purpose)s, %(weather_state)s, %(party_band)s, %(query_text)s,
        %(embedding)s::halfvec(1024))
ON CONFLICT (purpose, weather_state, party_band)
DO UPDATE SET embedding = EXCLUDED.embedding, query_text = EXCLUDED.query_text
"""


def _blend(a: list[float], b: list[float], w: float) -> list[float]:
    mixed = [w * x + (1 - w) * y for x, y in zip(a, b)]
    norm = math.sqrt(sum(x * x for x in mixed)) or 1.0
    return [x / norm for x in mixed]


def _scaled(rows: list[dict[str, Any]], target: int) -> list[dict[str, Any]]:
    """시드를 좌표만 흔들어 target개까지 복제한다. **성능 측정 전용이다.**

    용산구 대략 범위 안에서만 흔든다. 반경 필터가 의미를 잃으면 측정도 의미가 없다.
    """
    rng = random.Random(20260810)
    out = list(rows)
    i = 0
    while len(out) < target:
        src = rows[i % len(rows)]
        clone = dict(src)
        clone["poi_id"] = f"{src['poi_id']}_x{len(out)}"
        clone["name"] = f"{src['name']} {len(out)}"
        clone["lat"] = float(src["lat"]) + rng.uniform(-0.018, 0.018)
        clone["lng"] = float(src["lng"]) + rng.uniform(-0.022, 0.022)
        out.append(clone)
        i += 1
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", default=DEFAULT_SEED)
    ap.add_argument("--dsn", default=os.environ.get("DATABASE_URL"))
    ap.add_argument("--demo-hotspot", action="store_true",
                    help="가짜 실시간 지점/스냅샷을 넣어 live_* 경로를 켠다")
    ap.add_argument("--demo-vectors", action="store_true",
                    help="가짜 태그 임베딩을 넣어 취향 축(<=>)을 켠다")
    ap.add_argument("--scale", type=int, default=0,
                    help="합성 POI를 복제해 이 개수까지 늘린다 (성능 측정용)")
    ap.add_argument("--reviews", action="store_true",
                    help="seeds/review_seed.json을 review_chunk에 적재한다 (RAG 인용용)")
    args = ap.parse_args()

    if not args.dsn:
        print("DATABASE_URL이 없다", file=sys.stderr)
        return 2

    with open(args.seed, encoding="utf-8") as f:
        raw = json.load(f)
    rows = raw.get("pois", raw) if isinstance(raw, dict) else raw

    with psycopg.connect(args.dsn) as conn, conn.cursor() as cur:
        if args.reviews:
            review_path = os.path.join(ROOT, "seeds", "review_seed.json")
            with open(review_path, encoding="utf-8") as f:
                chunks = json.load(f)
            # POI 태그 벡터를 기준으로 청크 벡터를 만든다. 같은 POI의 후기끼리
            # 가깝고, 텍스트에 따라 조금씩 갈린다 — 벡터 검색이 순서를 만들 수 있게.
            poi_tags = {
                r["poi_id"]: list(r.get("atmosphere_tags") or [])
                + list(r.get("purpose_tags") or [])
                for r in rows
            }
            for ch in chunks:
                emb = None
                if args.demo_vectors:
                    base = _mean_vector(poi_tags.get(ch["poi_id"], [])) or _tag_vector(
                        ch["poi_id"]
                    )
                    emb = _to_literal(_blend(base, _tag_vector(ch["text"][:40]), 0.7))
                cur.execute(
                    UPSERT_CHUNK,
                    {
                        "poi_id": ch["poi_id"],
                        "source": ch.get("source") or "naver_blog",
                        "text": ch["text"],
                        "embedding": emb,
                        "is_sponsored": bool(ch.get("is_sponsored")),
                        "written_at": ch.get("written_at"),
                    },
                )

            if args.demo_vectors:
                # 목적 6 × 날씨 4 × 인원밴드 3 = 72행 (PLAN §11.3)
                for purpose in PURPOSE_TAGS:
                    for state in WEATHER_STATES:
                        for band in (1, 2, 3):
                            text = f"{band}밴드 인원 / {purpose} / {state}"
                            vec = _blend(_tag_vector(purpose), _tag_vector(state), 0.65)
                            cur.execute(
                                UPSERT_QUERY_VECTOR,
                                {
                                    "purpose": purpose,
                                    "weather_state": state,
                                    "party_band": band,
                                    "query_text": text,
                                    "embedding": _to_literal(vec),
                                },
                            )

        if args.demo_hotspot:
            now = datetime.now(timezone.utc).astimezone()
            fcst = json.dumps(_demo_fcst(now), ensure_ascii=False)
            weather = json.dumps(DEMO_WEATHER, ensure_ascii=False)
            for code, name, lat, lng, congest, ages in DEMO_HOTSPOTS:
                cur.execute(
                    "INSERT INTO hotspot (code, name, category, geom) VALUES "
                    "(%s, %s, '개발용', ST_SetSRID(ST_MakePoint(%s,%s),4326)::geography) "
                    "ON CONFLICT (code) DO NOTHING",
                    (code, name, lng, lat),
                )
                cur.execute(
                    "INSERT INTO hotspot_snapshot "
                    "(hotspot_code, observed_at, congest_lvl, age_rates, weather, fcst) "
                    "VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
                    (code, now, congest, json.dumps(ages), weather, fcst),
                )

        if args.scale and args.scale > len(rows):
            rows = _scaled(rows, args.scale)

        for r in rows:
            cur.execute(UPSERT_POI, _row(r))

        if args.demo_vectors:
            for kind, tags in (("atmosphere", ATMOSPHERE_TAGS), ("purpose", PURPOSE_TAGS)):
                for tag in tags:
                    cur.execute(
                        "INSERT INTO tag_embedding (tag, kind, embedding) "
                        "VALUES (%s, %s, %s::halfvec(1024)) "
                        "ON CONFLICT (tag) DO UPDATE SET embedding = EXCLUDED.embedding",
                        (tag, kind, _to_literal(_tag_vector(tag))),
                    )
            # POI 벡터도 같은 기저로 만든다 — 태그가 겹치는 POI끼리 코사인이 높아진다
            for r in rows:
                vec = _mean_vector(
                    list(r.get("atmosphere_tags") or []) + list(r.get("purpose_tags") or [])
                )
                if vec is None:
                    continue
                cur.execute(
                    "UPDATE poi SET tag_vector = %s::halfvec(1024) WHERE poi_id = %s",
                    (_to_literal(vec), r["poi_id"]),
                )

        if args.demo_hotspot:
            # POI ↔ 최근접 지점 매핑 (반경 1km 이내만). 운영에서는 A의 map_poi_hotspot.
            # **1km 밖은 NULL로 남긴다.** 전부 채우면 §6.4 재정규화 경로가 죽는다.
            cur.execute(
                """
                UPDATE poi p SET hotspot_code = h.code
                FROM hotspot h
                WHERE ST_DWithin(p.geom, h.geom, 1000)
                  AND p.hotspot_code IS NULL
                """
            )

        conn.commit()
        cur.execute("SELECT count(*) FROM poi")
        total = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM poi WHERE hotspot_code IS NOT NULL")
        mapped = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM review_chunk")
        chunks_n = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM query_vector_cache")
        qvec_n = cur.fetchone()[0]

    print(
        f"poi {total}행 (지점 반경 안 {mapped} / 밖 {total - mapped}) · "
        f"review_chunk {chunks_n} · query_vector_cache {qvec_n}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
