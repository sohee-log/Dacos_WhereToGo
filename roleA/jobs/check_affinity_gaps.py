import pandas as pd

from roleA.common.db import get_conn
from roleA.jobs.build_affinity import (
    SALES_PATH,
    SERVICE_TO_CATEGORY,
)


def main():

    sales = pd.read_csv(
        SALES_PATH,
        encoding="cp949",
        dtype={
            "상권_코드": "string",
            "서비스_업종_코드": "string",
        },
        usecols=[
            "상권_코드",
            "서비스_업종_코드",
            "서비스_업종_코드_명",
        ],
    )

    sales["상권_코드"] = sales["상권_코드"].astype(str)

    sales["category_l2"] = sales["서비스_업종_코드"].map(SERVICE_TO_CATEGORY)

    sales_area_ids = set(sales["상권_코드"].unique())

    supported_pairs = set(
        zip(
            sales.loc[
                sales["category_l2"].notna(),
                "상권_코드",
            ],
            sales.loc[
                sales["category_l2"].notna(),
                "category_l2",
            ],
        )
    )

    conn = get_conn()

    try:
        with conn.cursor() as cur:

            cur.execute("""
                SELECT
                    commercial_area_id,
                    category_l2,
                    COUNT(*)
                FROM poi
                WHERE commercial_area_id IS NOT NULL
                  AND category_l2 IS NOT NULL
                GROUP BY
                    commercial_area_id,
                    category_l2
                """)

            rows = cur.fetchall()

    finally:
        conn.close()

    missing_area = {}
    missing_pair = {}

    for area_id, category_l2, count in rows:

        area_id = str(area_id)
        count = int(count)

        if area_id not in sales_area_ids:

            missing_area[category_l2] = (
                missing_area.get(
                    category_l2,
                    0,
                )
                + count
            )

        elif (
            area_id,
            category_l2,
        ) not in supported_pairs:

            missing_pair[category_l2] = (
                missing_pair.get(
                    category_l2,
                    0,
                )
                + count
            )

    print("=== 2025 매출 데이터에 상권 자체가 없는 POI ===")

    print(
        "총:",
        sum(missing_area.values()),
    )

    for category, count in sorted(
        missing_area.items(),
        key=lambda x: -x[1],
    ):
        print(category, count)

    print("\n=== 상권은 있지만 affinity 매칭이 없는 POI ===")

    print(
        "총:",
        sum(missing_pair.values()),
    )

    for category, count in sorted(
        missing_pair.items(),
        key=lambda x: -x[1],
    ):
        print(category, count)

    print("\n=== 아직 category_l2로 매핑하지 않은 서울시 업종 ===")

    unmapped = (
        sales.loc[
            sales["category_l2"].isna(),
            [
                "서비스_업종_코드",
                "서비스_업종_코드_명",
            ],
        ]
        .drop_duplicates()
        .sort_values("서비스_업종_코드")
    )

    print(unmapped.to_string(index=False))


if __name__ == "__main__":
    main()
