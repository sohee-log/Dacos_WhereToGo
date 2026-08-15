from pathlib import Path

import pandas as pd

from roleA.common.db import get_conn

ROOT_DIR = Path(__file__).resolve().parents[2]

POI_PATH = ROOT_DIR / "roleA" / "data" / "yongsan_poi_final_tiered.csv"


def main():

    # ==========================================
    # 1. 로컬 최종 데이터
    # ==========================================

    local = pd.read_csv(
        POI_PATH,
        encoding="utf-8-sig",
        low_memory=False,
        dtype={
            "poi_id": "string",
        },
    )

    # loader와 동일하게 TourAPI ID 정규화
    local["poi_id"] = (
        local["poi_id"]
        .astype(str)
        .str.replace(
            r"^TOUR_",
            "tour_",
            regex=True,
        )
    )

    local_ids = set(local["poi_id"])

    print("로컬 최종 POI:", len(local))

    # ==========================================
    # 2. DB 데이터 읽기
    # ==========================================

    conn = get_conn()

    try:

        with conn.cursor() as cur:

            cur.execute("""
                SELECT
                    poi_id,
                    name,
                    category_l1,
                    dong,
                    zone,
                    commercial_area_id,
                    tier,
                    mention_count,
                    review_count,
                    attr_confidence
                FROM poi
                """)

            rows = cur.fetchall()

            columns = [
                "poi_id",
                "name",
                "category_l1",
                "dong",
                "zone",
                "commercial_area_id",
                "tier",
                "mention_count",
                "review_count",
                "attr_confidence",
            ]

            db = pd.DataFrame(
                rows,
                columns=columns,
            )

    finally:

        conn.close()

    db["poi_id"] = db["poi_id"].astype(str)

    db_ids = set(db["poi_id"])

    # ==========================================
    # 3. ID 비교
    # ==========================================

    missing = local_ids - db_ids
    extra = db_ids - local_ids

    print("\n=== ID QC ===")
    print("DB 전체 POI:", len(db))
    print("DB에 없는 최종 POI:", len(missing))
    print("최종 파일에 없는 DB POI:", len(extra))

    if missing:
        print("\nDB 누락 예시:")
        print(list(sorted(missing))[:20])

    if extra:
        print("\nDB 추가 POI 예시:")
        print(list(sorted(extra))[:20])

    # 최종 데이터에 속하는 DB row만 QC
    final_db = db[db["poi_id"].isin(local_ids)].copy()

    # ==========================================
    # 4. 기본 QC
    # ==========================================

    print("\n=== 기본 QC ===")

    print("poi_id 중복:", final_db["poi_id"].duplicated().sum())

    print("name NULL:", final_db["name"].isna().sum())

    print("dong NULL:", final_db["dong"].isna().sum())

    print("zone NULL:", final_db["zone"].isna().sum())

    print("category_l1 NULL:", final_db["category_l1"].isna().sum())

    # ==========================================
    # 5. tier
    # ==========================================

    print("\n=== tier ===")

    print(final_db["tier"].value_counts().sort_index().to_string())

    # ==========================================
    # 6. 상권
    # ==========================================

    mapped = final_db["commercial_area_id"].notna().sum()

    print("\n=== 상권 ===")
    print("매핑:", mapped)
    print("NULL:", final_db["commercial_area_id"].isna().sum())

    if len(final_db):
        print("매핑률:", f"{mapped / len(final_db) * 100:.2f}%")

    # ==========================================
    # 7. W1 mock 속성 잔존 여부
    # ==========================================

    mock_remaining = final_db[
        (final_db["mention_count"].fillna(0) != 0)
        | (final_db["review_count"].fillna(0) != 0)
        | (final_db["attr_confidence"].fillna(0) != 0)
    ]

    print("\n=== W1 mock 속성 QC ===")
    print(
        "mock 값 의심 POI:",
        len(mock_remaining),
    )


if __name__ == "__main__":
    main()
