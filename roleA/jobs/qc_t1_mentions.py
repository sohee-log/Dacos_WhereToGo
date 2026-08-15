from pathlib import Path

import pandas as pd

ROOT_DIR = Path(__file__).resolve().parents[2]

MENTION_PATH = ROOT_DIR / "roleA" / "data" / "t1_mentions.csv"


def main():

    df = pd.read_csv(
        MENTION_PATH,
        encoding="utf-8-sig",
        low_memory=False,
    )

    print("전체:", len(df))

    # ==========================================
    # mention_count 분포
    # ==========================================

    print("\n=== 분위수 ===")

    quantiles = df["mention_count"].quantile(
        [
            0,
            0.25,
            0.5,
            0.75,
            0.90,
            0.95,
            0.99,
            1.0,
        ]
    )

    print(quantiles.to_string())

    print(
        "\nmention_count = 0:",
        (df["mention_count"] == 0).sum(),
    )

    # ==========================================
    # 상위 POI 확인
    # ==========================================

    print("\n=== mention_count 상위 50 ===")

    print(
        df[
            [
                "name",
                "category_l1",
                "dong",
                "query",
                "mention_count",
            ]
        ]
        .sort_values(
            "mention_count",
            ascending=False,
        )
        .head(50)
        .to_string(index=False)
    )

    # ==========================================
    # 단순 상위 800을 뽑았을 경우 분포 확인
    # 실제 T1 선정은 아직 하지 않음
    # ==========================================

    top800 = (
        df.sort_values(
            "mention_count",
            ascending=False,
        )
        .head(800)
        .copy()
    )

    print("\n=== raw mention_count 상위 800 카테고리 ===")

    print(top800["category_l1"].value_counts().to_string())

    print("\n=== raw mention_count 상위 800 행정동 ===")

    print(top800["dong"].value_counts().to_string())

    print("\n=== 상위 800 최저 mention_count ===")
    print(top800["mention_count"].min())


if __name__ == "__main__":
    main()
