from pathlib import Path
import re

import pandas as pd

ROOT_DIR = Path(__file__).resolve().parents[2]

POI_PATH = ROOT_DIR / "roleA" / "data" / "yongsan_poi_final.csv"


def normalize_name(name):
    if pd.isna(name):
        return ""

    return re.sub(
        r"[^0-9a-z가-힣]",
        "",
        str(name).lower(),
    )


def main():

    df = pd.read_csv(
        POI_PATH,
        encoding="utf-8-sig",
        low_memory=False,
    )

    df["name_norm"] = df["name"].apply(normalize_name)

    df["longitude_round"] = pd.to_numeric(
        df["longitude"],
        errors="coerce",
    ).round(6)

    df["latitude_round"] = pd.to_numeric(
        df["latitude"],
        errors="coerce",
    ).round(6)

    duplicate_mask = df.duplicated(
        subset=[
            "name_norm",
            "longitude_round",
            "latitude_round",
            "category_l1",
        ],
        keep=False,
    )

    duplicates = df[duplicate_mask].sort_values(
        [
            "name_norm",
            "longitude_round",
            "latitude_round",
        ]
    )

    print("전체 POI:", len(df))

    print(
        "중복 그룹에 포함된 레코드:",
        len(duplicates),
    )

    print(
        "제거 가능한 중복 레코드:",
        df.duplicated(
            subset=[
                "name_norm",
                "longitude_round",
                "latitude_round",
                "category_l1",
            ],
            keep="first",
        ).sum(),
    )

    if len(duplicates):

        print("\n=== 동일 이름 + 동일 좌표 ===")

        print(
            duplicates[
                [
                    "poi_id",
                    "name",
                    "category_l1",
                    "dong",
                    "longitude",
                    "latitude",
                    "source",
                ]
            ].to_string(index=False)
        )


if __name__ == "__main__":
    main()
