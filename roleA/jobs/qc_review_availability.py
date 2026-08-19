from pathlib import Path

import pandas as pd

ROOT_DIR = Path(__file__).resolve().parents[2]

SCREEN_PATH = ROOT_DIR / "roleA" / "data" / "review_availability_screen.csv"


def main():

    df = pd.read_csv(
        SCREEN_PATH,
        encoding="utf-8-sig",
        low_memory=False,
    )

    # bool이 문자열로 읽히는 경우까지 대응
    if df["review_available"].dtype == object:
        df["review_available"] = (
            df["review_available"]
            .astype(str)
            .str.lower()
            .map(
                {
                    "true": True,
                    "false": False,
                }
            )
        )

    available = df[df["review_available"] == True].copy()

    print("스크리닝 전체:", len(df))
    print("리뷰 확보 가능:", len(available))

    print("\n=== 카테고리별 ===")
    print(available["category_l1"].value_counts().to_string())

    print("\n=== 행정동별 ===")
    print(available["dong"].value_counts().to_string())

    print("\n=== 행정동 × 카테고리 ===")

    cross = pd.crosstab(
        available["dong"],
        available["category_l1"],
    )

    print(cross.to_string())

    print("\n=== relevant_count 분포 ===")
    print(
        available["relevant_count"]
        .describe(
            percentiles=[
                0.25,
                0.5,
                0.75,
                0.9,
            ]
        )
        .to_string()
    )

    print("\n=== relevant_count별 POI 수 ===")

    print(
        pd.cut(
            available["relevant_count"],
            bins=[
                0,
                1,
                2,
                3,
                5,
                10,
                20,
            ],
            include_lowest=True,
        )
        .value_counts()
        .sort_index()
        .to_string()
    )


if __name__ == "__main__":
    main()
