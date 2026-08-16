from pathlib import Path

import re
import pandas as pd

ROOT_DIR = Path(__file__).resolve().parents[2]

STORE_POI_PATH = ROOT_DIR / "roleA" / "data" / "yongsan_poi_candidates_final.csv"

TOUR_POI_PATH = ROOT_DIR / "roleA" / "data" / "tourapi_yongsan_geotagged.csv"

OUTPUT_PATH = ROOT_DIR / "roleA" / "data" / "yongsan_poi_final.csv"


def normalize_name(name):
    if pd.isna(name):
        return ""

    return re.sub(
        r"[^0-9a-z가-힣]",
        "",
        str(name).lower(),
    )


def main():

    store = pd.read_csv(
        STORE_POI_PATH,
        encoding="utf-8-sig",
        low_memory=False,
    )

    tour = pd.read_csv(
        TOUR_POI_PATH,
        encoding="utf-8-sig",
        low_memory=False,
    )

    print("기존 상가 POI:", len(store))
    print("TourAPI POI:", len(tour))

    # ------------------------------------------
    # 기존 상가 데이터 → 공통 컬럼
    # ------------------------------------------

    store_final = pd.DataFrame(
        {
            "poi_id": store["상가업소번호"],
            "name": store["상호명"],
            "category_l1": store["category_l1"],
            "category_l2": store["상권업종중분류명"],
            "longitude": store["경도"],
            "latitude": store["위도"],
            "dong": store["dong"],
            "zone": store["zone"],
            "commercial_area_id": store["commercial_area_id"],
            "hotspot_code": None,
            "source": "store_info",
            "tier": 1,
        }
    )

    # ------------------------------------------
    # TourAPI 데이터 → 같은 컬럼
    # ------------------------------------------

    tour_final = pd.DataFrame(
        {
            "poi_id": tour["poi_id"],
            "name": tour["name"],
            "category_l1": tour["category_l1"],
            "category_l2": tour["category_l2"],
            "longitude": tour["longitude"],
            "latitude": tour["latitude"],
            "dong": tour["dong"],
            "zone": tour["zone"],
            "commercial_area_id": tour["commercial_area_id"],
            "hotspot_code": None,
            "source": "tourapi",
            "tier": 1,
        }
    )

    # ------------------------------------------
    # 통합
    # ------------------------------------------

    final = pd.concat(
        [
            store_final,
            tour_final,
        ],
        ignore_index=True,
    )

    # ==========================================
    # 동일 장소 중복 제거
    # ==========================================

    final["name_norm"] = final["name"].apply(normalize_name)

    final["longitude_round"] = pd.to_numeric(
        final["longitude"],
        errors="coerce",
    ).round(6)

    final["latitude_round"] = pd.to_numeric(
        final["latitude"],
        errors="coerce",
    ).round(6)

    before_dedup = len(final)

    # 같은 이름 + 같은 좌표 + 같은 대분류인 경우
    # 동일 장소로 간주하고 poi_id 기준으로 하나만 유지
    final = (
        final.sort_values("poi_id")
        .drop_duplicates(
            subset=[
                "name_norm",
                "longitude_round",
                "latitude_round",
                "category_l1",
            ],
            keep="first",
        )
        .copy()
    )

    removed_duplicates = before_dedup - len(final)

    print(
        "\n동일 장소 중복 제거:",
        removed_duplicates,
    )

    print("\n=== 최종 POI ===")
    print("총:", len(final))

    print("\n=== source ===")
    print(final["source"].value_counts().to_string())

    print("\n=== category_l1 ===")
    print(final["category_l1"].value_counts(dropna=False).to_string())

    print("\n=== zone ===")
    print(final["zone"].value_counts(dropna=False).to_string())

    # ------------------------------------------
    # QC
    # ------------------------------------------

    print("\n=== 최종 QC ===")

    print("poi_id 중복:", final["poi_id"].duplicated().sum())

    print("poi_id NULL:", final["poi_id"].isna().sum())

    print("name NULL:", final["name"].isna().sum())

    print("좌표 NULL:", final[["longitude", "latitude"]].isna().any(axis=1).sum())

    print("dong NULL:", final["dong"].isna().sum())

    print("zone NULL:", final["zone"].isna().sum())

    mapped = final["commercial_area_id"].notna().sum()

    print("commercial_area_id 매핑:", mapped)

    print("commercial_area_id NULL:", final["commercial_area_id"].isna().sum())

    print("상권 매핑률:", f"{mapped / len(final) * 100:.2f}%")

    allowed_categories = {
        "음식",
        "카페",
        "문화",
        "쇼핑",
        "자연",
    }

    invalid_categories = final[~final["category_l1"].isin(allowed_categories)]

    print("잘못된 category_l1:", len(invalid_categories))

    final = final.drop(
        columns=[
            "name_norm",
            "longitude_round",
            "latitude_round",
        ],
        errors="ignore",
    )

    # ------------------------------------------
    # 저장
    # ------------------------------------------

    final.to_csv(
        OUTPUT_PATH,
        index=False,
        encoding="utf-8-sig",
    )

    print("\n저장 완료:")
    print(OUTPUT_PATH)


if __name__ == "__main__":
    main()
