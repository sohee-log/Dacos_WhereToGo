from pathlib import Path

import pandas as pd

ROOT_DIR = Path(__file__).resolve().parents[2]

INPUT_PATH = ROOT_DIR / "roleA" / "data" / "tourapi_yongsan_raw.csv"

OUTPUT_PATH = ROOT_DIR / "roleA" / "data" / "tourapi_yongsan_final.csv"


CATEGORY_MAP = {
    "A01": "자연",
    "A02": "문화",
}


# 기존 상가정보 POI와 동일 장소로 확인된 TourAPI contentid
DUPLICATE_CONTENT_IDS = {
    2783339,  # 별책부록
    130628,  # 박여숙화랑
    130637,  # 어반아트
    130573,  # 갤러리에스피
}


# 프로젝트 category_l1 기준 수동 보정
CATEGORY_OVERRIDES = {
    126499: "자연",  # 용산가족공원
}


def main():

    df = pd.read_csv(
        INPUT_PATH,
        encoding="utf-8-sig",
        low_memory=False,
    )

    # contentid 숫자형 통일
    df["contentid"] = pd.to_numeric(
        df["contentid"],
        errors="coerce",
    ).astype("Int64")

    print("TourAPI 원본:", len(df))

    # ------------------------------------------
    # category_l1
    # ------------------------------------------

    df["category_l1"] = df["cat1"].map(CATEGORY_MAP)

    for contentid, category in CATEGORY_OVERRIDES.items():
        df.loc[
            df["contentid"] == contentid,
            "category_l1",
        ] = category

    # ------------------------------------------
    # 기존 POI와 중복 제거
    # ------------------------------------------

    df["is_existing_duplicate"] = df["contentid"].isin(DUPLICATE_CONTENT_IDS)

    print(
        "기존 POI 중복:",
        df["is_existing_duplicate"].sum(),
    )

    result = df[~df["is_existing_duplicate"]].copy()

    # ------------------------------------------
    # 프로젝트 POI 필드 생성
    # ------------------------------------------

    result["poi_id"] = "TOUR_" + result["contentid"].astype(str)

    result["name"] = result["title"]

    result["longitude"] = pd.to_numeric(
        result["mapx"],
        errors="coerce",
    )

    result["latitude"] = pd.to_numeric(
        result["mapy"],
        errors="coerce",
    )

    result["category_l2"] = result["content_type_name"]

    # 이후 spatial join에서 채움
    result["dong"] = None
    result["zone"] = None
    result["commercial_area_id"] = None

    # ------------------------------------------
    # QC
    # ------------------------------------------

    print("\n=== TourAPI 최종 신규 POI ===")
    print("총:", len(result))

    print("\n=== category_l1 ===")
    print(result["category_l1"].value_counts(dropna=False).to_string())

    print("\n=== 신규 POI 목록 ===")
    print(
        result[
            [
                "poi_id",
                "name",
                "category_l1",
                "category_l2",
                "longitude",
                "latitude",
            ]
        ].to_string(index=False)
    )

    print("\n좌표 NULL:", result[["longitude", "latitude"]].isna().any(axis=1).sum())

    print("poi_id 중복:", result["poi_id"].duplicated().sum())

    # ------------------------------------------
    # 저장
    # ------------------------------------------

    result.to_csv(
        OUTPUT_PATH,
        index=False,
        encoding="utf-8-sig",
    )

    print("\n저장 완료:")
    print(OUTPUT_PATH)


if __name__ == "__main__":
    main()
