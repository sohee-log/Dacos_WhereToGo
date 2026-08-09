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
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", default=DEFAULT_SEED)
    ap.add_argument("--dsn", default=os.environ.get("DATABASE_URL"))
    ap.add_argument("--demo-hotspot", action="store_true",
                    help="가짜 실시간 지점/스냅샷을 넣어 live_* 경로를 켠다")
    args = ap.parse_args()

    if not args.dsn:
        print("DATABASE_URL이 없다", file=sys.stderr)
        return 2

    with open(args.seed, encoding="utf-8") as f:
        raw = json.load(f)
    rows = raw.get("pois", raw) if isinstance(raw, dict) else raw

    with psycopg.connect(args.dsn) as conn, conn.cursor() as cur:
        if args.demo_hotspot:
            for code, name, lat, lng, congest, ages in DEMO_HOTSPOTS:
                cur.execute(
                    "INSERT INTO hotspot (code, name, category, geom) VALUES "
                    "(%s, %s, '개발용', ST_SetSRID(ST_MakePoint(%s,%s),4326)::geography) "
                    "ON CONFLICT (code) DO NOTHING",
                    (code, name, lng, lat),
                )
                cur.execute(
                    "INSERT INTO hotspot_snapshot "
                    "(hotspot_code, observed_at, congest_lvl, age_rates) "
                    "VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING",
                    (code, datetime.now(timezone.utc), congest, json.dumps(ages)),
                )

        for r in rows:
            cur.execute(UPSERT_POI, _row(r))

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

    print(f"poi {total}행 (지점 반경 안 {mapped} / 밖 {total - mapped})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
