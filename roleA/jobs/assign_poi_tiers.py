from pathlib import Path

import pandas as pd

ROOT_DIR = Path(__file__).resolve().parents[2]

POI_PATH = ROOT_DIR / "roleA" / "data" / "yongsan_poi_final.csv"

T1_PATH = ROOT_DIR / "roleA" / "data" / "t1_selection_qc.csv"

OUTPUT_PATH = ROOT_DIR / "roleA" / "data" / "yongsan_poi_final_tiered.csv"


T2_DONGS = {
    "이촌1동",
    "남영동",
    "청파동",
    "원효로1동",
}


def main():

    poi = pd.read_csv(
        POI_PATH,
        encoding="utf-8-sig",
        low_memory=False,
    )

    t1 = pd.read_csv(
        T1_PATH,
        encoding="utf-8-sig",
        low_memory=False,
    )

    print("전체 POI:", len(poi))
    print("T1 선정 파일:", len(t1))

    # ------------------------------------------
    # 기본은 tier 3
    # ------------------------------------------

    poi["tier"] = 3

    # ------------------------------------------
    # 준핵심 지역 → tier 2
    # ------------------------------------------

    poi.loc[
        poi["dong"].isin(T2_DONGS),
        "tier",
    ] = 2

    # ------------------------------------------
    # 최종 선정 800건 → tier 1
    # ------------------------------------------

    t1_ids = set(t1["poi_id"].astype(str))

    poi.loc[
        poi["poi_id"].astype(str).isin(t1_ids),
        "tier",
    ] = 1

    # ------------------------------------------
    # QC
    # ------------------------------------------

    print("\n=== tier 분포 ===")
    print(poi["tier"].value_counts().sort_index().to_string())

    print("\n=== T1 QC ===")

    tier1 = poi[poi["tier"] == 1]

    print("T1:", len(tier1))

    print("\n=== T1 카테고리 ===")
    print(tier1["category_l1"].value_counts().to_string())

    print("\n=== T1 행정동 ===")
    print(tier1["dong"].value_counts().to_string())

    print("\n=== 전체 QC ===")

    print("poi_id 중복:", poi["poi_id"].duplicated().sum())

    print("tier NULL:", poi["tier"].isna().sum())

    invalid_tier = (~poi["tier"].isin([1, 2, 3])).sum()

    print(
        "잘못된 tier:",
        invalid_tier,
    )

    # ------------------------------------------
    # 저장
    # ------------------------------------------

    poi.to_csv(
        OUTPUT_PATH,
        index=False,
        encoding="utf-8-sig",
    )

    print("\n저장 완료:")
    print(OUTPUT_PATH)


if __name__ == "__main__":
    main()
