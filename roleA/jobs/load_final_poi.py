import argparse
import json
from pathlib import Path

import pandas as pd

from roleA.common.db import get_conn

ROOT_DIR = Path(__file__).resolve().parents[2]

POI_PATH = ROOT_DIR / "roleA" / "data" / "yongsan_poi_final_tiered.csv"

SEED_PATH = ROOT_DIR / "seeds" / "poi_seed.json"


def nullable_text(value):
    if pd.isna(value):
        return None

    value = str(value).strip()

    if not value:
        return None

    # CSV에서 숫자 ID가 3110001.0처럼 읽히는 경우 방지
    if value.endswith(".0"):
        base = value[:-2]

        if base.isdigit():
            return base

    return value


def clear_seed_mock_data(conn):
    """
    W1 테스트 seed에 들어 있던 mock 속성을 제거한다.

    반드시 실데이터 최초 적재 전에 한 번만 실행한다.
    W3 이후에는 사용하지 않는다.
    """

    with open(
        SEED_PATH,
        "r",
        encoding="utf-8",
    ) as f:
        seeds = json.load(f)

    seed_ids = [str(row["poi_id"]) for row in seeds]

    with conn.cursor() as cur:

        # 혹시 mock review seed가 적재돼 있다면 제거
        cur.execute(
            """
            DELETE FROM review_chunk
            WHERE poi_id = ANY(%s)
            """,
            (seed_ids,),
        )

        # W1 mock 속성 초기화
        cur.execute(
            """
            UPDATE poi
            SET
                business_hours = NULL,
                outdoor_exposure = NULL,
                group_capacity = NULL,
                noise_level = NULL,
                purpose_tags = NULL,
                atmosphere_tags = NULL,
                price_band = NULL,
                wait_intensity = NULL,
                tag_vector = NULL,
                sentiment_score = NULL,
                mention_count = 0,
                review_count = 0,
                quality_score = NULL,
                attr_confidence = 0,
                hotspot_code = NULL,
                attr_extracted_at = NULL
            WHERE poi_id = ANY(%s)
            """,
            (seed_ids,),
        )

    print(
        "W1 seed mock 데이터 초기화:",
        len(seed_ids),
    )


def main():

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--limit",
        type=int,
        default=None,
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
    )

    parser.add_argument(
        "--clear-seed-mock",
        action="store_true",
    )

    args = parser.parse_args()

    df = pd.read_csv(
        POI_PATH,
        encoding="utf-8-sig",
        low_memory=False,
        dtype={
            "poi_id": "string",
            "commercial_area_id": "string",
        },
    )

    # DB 계약에 맞춰 TourAPI 접두어 통일
    df["poi_id"] = (
        df["poi_id"]
        .astype(str)
        .str.replace(
            r"^TOUR_",
            "tour_",
            regex=True,
        )
    )

    if args.limit is not None:
        df = df.head(args.limit)

    print("적재 대상:", len(df))

    if args.dry_run:

        print("\n=== DRY RUN ===")

        print(
            df[
                [
                    "poi_id",
                    "name",
                    "category_l1",
                    "dong",
                    "zone",
                    "commercial_area_id",
                    "tier",
                ]
            ]
            .head(20)
            .to_string(index=False)
        )

        return

    conn = get_conn()

    try:

        # 최초 실데이터 적재 때만 사용
        if args.clear_seed_mock:
            clear_seed_mock_data(conn)

        with conn.cursor() as cur:

            for i, row in enumerate(
                df.itertuples(index=False),
                start=1,
            ):

                cur.execute(
                    """
                    INSERT INTO poi (
                        poi_id,
                        name,
                        category_l1,
                        category_l2,
                        geom,
                        dong,
                        zone,
                        commercial_area_id,
                        mention_count,
                        review_count,
                        attr_confidence,
                        tier,
                        attr_extracted_at
                    )
                    VALUES (
                        %s,
                        %s,
                        %s,
                        %s,
                        ST_SetSRID(
                            ST_MakePoint(%s, %s),
                            4326
                        )::geography,
                        %s,
                        %s,
                        %s,
                        0,
                        0,
                        0,
                        %s,
                        NULL
                    )
                    ON CONFLICT (poi_id)
                    DO UPDATE SET
                        name = EXCLUDED.name,
                        category_l1 = EXCLUDED.category_l1,
                        category_l2 = EXCLUDED.category_l2,
                        geom = EXCLUDED.geom,
                        dong = EXCLUDED.dong,
                        zone = EXCLUDED.zone,
                        commercial_area_id =
                            EXCLUDED.commercial_area_id,
                        tier = EXCLUDED.tier,
                        updated_at = NOW()
                    """,
                    (
                        str(row.poi_id),
                        row.name,
                        row.category_l1,
                        nullable_text(row.category_l2),
                        float(row.longitude),
                        float(row.latitude),
                        row.dong,
                        row.zone,
                        nullable_text(row.commercial_area_id),
                        int(row.tier),
                    ),
                )

                if i % 500 == 0:
                    print(f"{i} / {len(df)}")

        conn.commit()

        print(
            "\n실 POI 적재 완료:",
            len(df),
        )

    except Exception:

        conn.rollback()
        raise

    finally:

        conn.close()


if __name__ == "__main__":
    main()
