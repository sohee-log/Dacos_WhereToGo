from pathlib import Path

import pandas as pd

ROOT_DIR = Path(__file__).resolve().parents[2]

T1_PATH = ROOT_DIR / "roleA" / "data" / "t1_selection_qc.csv"


def main():

    df = pd.read_csv(
        T1_PATH,
        encoding="utf-8-sig",
        low_memory=False,
    )

    print("T1:", len(df))

    # 편의점 계열이 남았는지
    convenience = df[
        df["name"]
        .fillna("")
        .str.contains(
            "편의점|GS25|지에스25|씨유|CU|세븐일레븐|이마트24",
            case=False,
            regex=True,
        )
    ]

    print("\n=== 편의점 잔여 ===")
    print("건수:", len(convenience))

    if len(convenience):
        print(
            convenience[
                [
                    "poi_id",
                    "name",
                    "dong",
                    "category_l1",
                ]
            ].to_string(index=False)
        )

    # 같은 동에서 이름이 완전히 동일한 경우
    duplicate_names = df[
        df.duplicated(
            subset=["name", "dong"],
            keep=False,
        )
    ].sort_values(["dong", "name"])

    print("\n=== 동일 이름 + 동일 동 중복 후보 ===")
    print("건수:", len(duplicate_names))

    if len(duplicate_names):
        print(
            duplicate_names[
                [
                    "poi_id",
                    "name",
                    "dong",
                    "longitude",
                    "latitude",
                    "category_l1",
                ]
            ].to_string(index=False)
        )


if __name__ == "__main__":
    main()
