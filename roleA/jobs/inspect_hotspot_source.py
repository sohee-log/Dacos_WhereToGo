from pathlib import Path

import pandas as pd

ROOT_DIR = Path(__file__).resolve().parents[2]

SOURCE_PATH = ROOT_DIR / "roleA" / "data" / "서울시 주요 121장소 목록.xlsx"


def main():

    df = pd.read_excel(
        SOURCE_PATH,
        engine="openpyxl",
    )

    print("전체 행:", len(df))

    print("\n=== 컬럼 ===")
    print(df.columns.tolist())

    print("\n=== 앞 10개 ===")
    print(df.head(10).to_string(index=False))

    print("\n=== CATEGORY 분포 ===")

    if "CATEGORY" in df.columns:
        print(df["CATEGORY"].value_counts(dropna=False).to_string())

    # ------------------------------------------
    # 용산 관련 이름 1차 검색
    # ------------------------------------------

    keywords = [
        "용산",
        "이태원",
        "한남",
        "한강",
        "삼각지",
        "서울역",
        "후암",
        "경리단",
        "해방촌",
        "효창",
        "이촌",
    ]

    if "AREA_NM" in df.columns:

        mask = False

        for keyword in keywords:
            mask = mask | df["AREA_NM"].astype(str).str.contains(
                keyword,
                na=False,
            )

        candidates = df[mask].copy()

        print("\n=== 용산 관련 이름 후보 ===")

        print(candidates.to_string(index=False))

        print(
            "\n후보 수:",
            len(candidates),
        )


if __name__ == "__main__":
    main()
