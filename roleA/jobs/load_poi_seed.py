import argparse
import json
from pathlib import Path

from psycopg.types.json import Jsonb

from roleA.common.db import get_conn

ROOT_DIR = Path(__file__).resolve().parents[2]
SEED_PATH = ROOT_DIR / "seeds" / "poi_seed.json"


UPSERT_SQL = """
INSERT INTO poi (
    poi_id,
    name,
    category_l1,
    category_l2,
    geom,
    dong,
    zone,
    commercial_area_id,
    hotspot_code,
    business_hours,
    outdoor_exposure,
    group_capacity,
    noise_level,
    purpose_tags,
    atmosphere_tags,
    price_band,
    wait_intensity,
    sentiment_score,
    mention_count,
    review_count,
    quality_score,
    attr_confidence,
    tier,
    updated_at
)
VALUES (
    %(poi_id)s,
    %(name)s,
    %(category_l1)s,
    %(category_l2)s,
    ST_SetSRID(
        ST_MakePoint(%(longitude)s, %(latitude)s),
        4326
    )::geography,
    %(dong)s,
    %(zone)s,
    %(commercial_area_id)s,
    %(hotspot_code)s,
    %(business_hours)s,
    %(outdoor_exposure)s,
    %(group_capacity)s,
    %(noise_level)s,
    %(purpose_tags)s,
    %(atmosphere_tags)s,
    %(price_band)s,
    %(wait_intensity)s,
    %(sentiment_score)s,
    %(mention_count)s,
    %(review_count)s,
    %(quality_score)s,
    %(attr_confidence)s,
    %(tier)s,
    NOW()
)
ON CONFLICT (poi_id)
DO UPDATE SET
    name = EXCLUDED.name,
    category_l1 = EXCLUDED.category_l1,
    category_l2 = EXCLUDED.category_l2,
    geom = EXCLUDED.geom,
    dong = EXCLUDED.dong,
    zone = EXCLUDED.zone,
    commercial_area_id = EXCLUDED.commercial_area_id,
    hotspot_code = EXCLUDED.hotspot_code,
    business_hours = EXCLUDED.business_hours,
    outdoor_exposure = EXCLUDED.outdoor_exposure,
    group_capacity = EXCLUDED.group_capacity,
    noise_level = EXCLUDED.noise_level,
    purpose_tags = EXCLUDED.purpose_tags,
    atmosphere_tags = EXCLUDED.atmosphere_tags,
    price_band = EXCLUDED.price_band,
    wait_intensity = EXCLUDED.wait_intensity,
    sentiment_score = EXCLUDED.sentiment_score,
    mention_count = EXCLUDED.mention_count,
    review_count = EXCLUDED.review_count,
    quality_score = EXCLUDED.quality_score,
    attr_confidence = EXCLUDED.attr_confidence,
    tier = EXCLUDED.tier,
    updated_at = NOW();
"""


def load_seed():
    with open(SEED_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def get_coord(row, names):
    for name in names:
        if name in row and row[name] is not None:
            return float(row[name])

    return None


def prepare_row(row):
    longitude = get_coord(
        row,
        ["longitude", "lon", "경도"],
    )
    latitude = get_coord(
        row,
        ["latitude", "lat", "위도"],
    )

    if longitude is None or latitude is None:
        raise ValueError(f"{row.get('poi_id')} 좌표가 없습니다.")

    return {
        "poi_id": row["poi_id"],
        "name": row["name"],
        "category_l1": row.get("category_l1"),
        "category_l2": row.get("category_l2"),
        "longitude": longitude,
        "latitude": latitude,
        "dong": row.get("dong"),
        "zone": row.get("zone"),
        "commercial_area_id": row.get("commercial_area_id"),
        "hotspot_code": row.get("hotspot_code"),
        "business_hours": (
            Jsonb(row["business_hours"])
            if row.get("business_hours") is not None
            else None
        ),
        "outdoor_exposure": row.get("outdoor_exposure"),
        "group_capacity": row.get("group_capacity"),
        "noise_level": row.get("noise_level"),
        "purpose_tags": row.get("purpose_tags"),
        "atmosphere_tags": row.get("atmosphere_tags"),
        "price_band": row.get("price_band"),
        "wait_intensity": (
            Jsonb(row["wait_intensity"])
            if row.get("wait_intensity") is not None
            else None
        ),
        "sentiment_score": row.get("sentiment_score"),
        "mention_count": row.get("mention_count"),
        "review_count": row.get("review_count"),
        "quality_score": row.get("quality_score"),
        "attr_confidence": row.get("attr_confidence"),
        "tier": row.get("tier", 1),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
    )
    args = parser.parse_args()

    rows = load_seed()

    if args.limit:
        rows = rows[: args.limit]

    prepared = [prepare_row(row) for row in rows]

    with get_conn() as conn:
        with conn.cursor() as cur:

            for row in prepared:
                cur.execute(
                    UPSERT_SQL,
                    row,
                )

        conn.commit()

    print(f"POI seed 적재 완료: {len(prepared)}건")


if __name__ == "__main__":
    main()
