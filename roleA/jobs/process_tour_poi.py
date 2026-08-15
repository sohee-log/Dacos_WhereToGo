import re
from pathlib import Path

import geopandas as gpd
import pandas as pd

ROOT_DIR = Path(__file__).resolve().parents[2]

TOUR_PATH = ROOT_DIR / "roleA" / "data" / "tourapi_yongsan_raw.csv"

EXISTING_POI_PATH = ROOT_DIR / "roleA" / "data" / "yongsan_poi_candidates_final.csv"

OUTPUT_PATH = ROOT_DIR / "roleA" / "data" / "tourapi_duplicate_qc.csv"


CATEGORY_MAP = {
    "A01": "자연",
    "A02": "문화",
}


def normalize_name(name):
    """장소명 비교용 단순 정규화"""
    if pd.isna(name):
        return ""

    name = str(name).lower()

    # 공백/특수문자 제거
    return re.sub(
        r"[^0-9a-z가-힣]",
        "",
        name,
    )


def main():

    # ==========================================
    # 1. TourAPI 데이터 읽기
    # ==========================================

    tour = pd.read_csv(
        TOUR_PATH,
        encoding="utf-8-sig",
        low_memory=False,
    )

    tour["category_l1"] = tour["cat1"].map(CATEGORY_MAP)

    print("=== TourAPI 카테고리 ===")
    print(tour["category_l1"].value_counts(dropna=False).to_string())

    # 좌표 숫자형 변환
    tour["mapx"] = pd.to_numeric(
        tour["mapx"],
        errors="coerce",
    )

    tour["mapy"] = pd.to_numeric(
        tour["mapy"],
        errors="coerce",
    )

    print("TourAPI 좌표 NULL:", tour[["mapx", "mapy"]].isna().any(axis=1).sum())

    # ==========================================
    # 2. 기존 추천 POI
    # ==========================================

    existing = pd.read_csv(
        EXISTING_POI_PATH,
        encoding="utf-8-sig",
        low_memory=False,
    )

    print("기존 추천 POI:", len(existing))

    # ==========================================
    # 3. GeoDataFrame 생성
    # ==========================================

    tour_gdf = gpd.GeoDataFrame(
        tour,
        geometry=gpd.points_from_xy(
            tour["mapx"],
            tour["mapy"],
        ),
        crs="EPSG:4326",
    )

    existing_gdf = gpd.GeoDataFrame(
        existing,
        geometry=gpd.points_from_xy(
            existing["경도"],
            existing["위도"],
        ),
        crs="EPSG:4326",
    )

    # 거리 계산용 투영좌표계
    tour_gdf = tour_gdf.to_crs("EPSG:5179")

    existing_gdf = existing_gdf.to_crs("EPSG:5179")

    # ==========================================
    # 4. 기존 POI 컬럼명 충돌 방지
    # ==========================================

    existing_compare = existing_gdf[
        [
            "상가업소번호",
            "상호명",
            "category_l1",
            "geometry",
        ]
    ].rename(
        columns={
            "상가업소번호": "existing_poi_id",
            "상호명": "existing_name",
            "category_l1": "existing_category",
        }
    )

    # ==========================================
    # 5. 가장 가까운 기존 POI 찾기
    # ==========================================

    nearest = gpd.sjoin_nearest(
        tour_gdf,
        existing_compare,
        how="left",
        distance_col="distance_m",
    )

    # 동일 거리 결과가 여러 개면 1개만
    nearest = (
        nearest.sort_values(
            [
                "contentid",
                "distance_m",
                "existing_poi_id",
            ]
        )
        .drop_duplicates(
            subset=["contentid"],
            keep="first",
        )
        .copy()
    )

    # ==========================================
    # 6. 이름 비교
    # ==========================================

    nearest["tour_name_norm"] = nearest["title"].apply(normalize_name)

    nearest["existing_name_norm"] = nearest["existing_name"].apply(normalize_name)

    nearest["same_name"] = nearest["tour_name_norm"] == nearest["existing_name_norm"]

    # 이름이 같고 100m 이내면 강한 중복 후보
    nearest["likely_duplicate"] = nearest["same_name"] & (nearest["distance_m"] <= 100)

    # 같은 건물/매우 가까운 장소는
    # 이름이 달라도 수동 확인 대상
    nearest["close_review"] = nearest["distance_m"] <= 20

    # ==========================================
    # 7. 결과 출력
    # ==========================================

    print("\n=== TourAPI 중복 QC ===")

    print("강한 중복 후보:", nearest["likely_duplicate"].sum())

    print("20m 이내 장소:", nearest["close_review"].sum())

    print("\n=== 33건 전체 비교 ===")

    cols = [
        "contentid",
        "title",
        "category_l1",
        "existing_name",
        "existing_category",
        "distance_m",
        "same_name",
        "likely_duplicate",
    ]

    print(
        nearest[cols]
        .sort_values(
            [
                "likely_duplicate",
                "distance_m",
            ],
            ascending=[
                False,
                True,
            ],
        )
        .to_string(index=False)
    )

    # ==========================================
    # 8. 저장
    # ==========================================

    output = pd.DataFrame(
        nearest.drop(
            columns=[
                "geometry",
                "index_right",
            ],
            errors="ignore",
        )
    )

    output.to_csv(
        OUTPUT_PATH,
        index=False,
        encoding="utf-8-sig",
    )

    print("\n저장 완료:")
    print(OUTPUT_PATH)


if __name__ == "__main__":
    main()
