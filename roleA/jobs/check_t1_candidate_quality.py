from pathlib import Path

import pandas as pd

ROOT_DIR = Path(__file__).resolve().parents[2]

POI_PATH = ROOT_DIR / "roleA" / "data" / "yongsan_poi_final.csv"


T1_DONGS = [
    "이태원1동",
    "이태원2동",
    "한남동",
    "한강로동",
    "후암동",
]


def main():

    df = pd.read_csv(
        POI_PATH,
        encoding="utf-8-sig",
        low_memory=False,
    )

    t1 = df[df["dong"].isin(T1_DONGS)].copy()

    print("T1 후보:", len(t1))

    print("\n=== category_l2 전체 분포 ===")
    print(t1["category_l2"].value_counts(dropna=False).to_string())

    print("\n=== category_l1 × category_l2 ===")

    counts = (
        t1.groupby(
            ["category_l1", "category_l2"],
            dropna=False,
        )
        .size()
        .reset_index(name="count")
        .sort_values(
            ["category_l1", "count"],
            ascending=[True, False],
        )
    )

    print(counts.to_string(index=False))

    print("\n=== category_l2별 상호명 예시 ===")

    for category_l2, group in t1.groupby(
        "category_l2",
        dropna=False,
    ):

        print(f"\n[{category_l2}] " f"{len(group)}건")

        print(group["name"].dropna().head(10).to_string(index=False))


if __name__ == "__main__":
    main()
