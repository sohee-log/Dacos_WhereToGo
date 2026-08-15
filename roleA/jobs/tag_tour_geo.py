from pathlib import Path

import geopandas as gpd
import pandas as pd

ROOT_DIR = Path(__file__).resolve().parents[2]

TOUR_PATH = ROOT_DIR / "roleA" / "data" / "tourapi_yongsan_final.csv"

DONG_SHP_PATH = (
    ROOT_DIR / "roleA" / "data" / "admin_dong" / "bnd_dong_11030_2025_2Q.shp"
)

COMMERCIAL_SHP_PATH = (
    ROOT_DIR
    / "roleA"
    / "data"
    / "commercial_area"
    / "서울시 상권분석서비스(영역-상권).shp"
)

OUTPUT_PATH = ROOT_DIR / "roleA" / "data" / "tourapi_yongsan_geotagged.csv"

ADMIN_NEAREST_THRESHOLD_M = 30
COMMERCIAL_NEAREST_THRESHOLD_M = 60


ZONE_DONGS = {
    "itaewon": [
        "이태원1동",
        "이태원2동",
        "한남동",
        "보광동",
    ],
    "yongsan_stn": [
        "한강로동",
        "남영동",
    ],
    "huam": [
        "후암동",
        "용산2가동",
    ],
    "ichon": [
        "이촌1동",
        "이촌2동",
        "서빙고동",
    ],
    "cheongpa": [
        "청파동",
        "원효로1동",
        "원효로2동",
        "효창동",
        "용문동",
    ],
}


def map_zone(dong):
    if pd.isna(dong):
        return None

    for zone, dongs in ZONE_DONGS.items():
        if dong in dongs:
            return zone

    return None


def main():

    # ==========================================
    # 1. TourAPI 신규 POI
    # ==========================================

    tour = pd.read_csv(
        TOUR_PATH,
        encoding="utf-8-sig",
        low_memory=False,
    )

    print("TourAPI 신규 POI:", len(tour))

    tour_gdf = gpd.GeoDataFrame(
        tour,
        geometry=gpd.points_from_xy(
            tour["longitude"],
            tour["latitude"],
        ),
        crs="EPSG:4326",
    )

    # ==========================================
    # 2. 행정동 공간조인
    # ==========================================

    dong = gpd.read_file(DONG_SHP_PATH)

    tour_admin = tour_gdf.to_crs(dong.crs)

    joined = gpd.sjoin(
        tour_admin,
        dong[
            [
                "ADM_CD",
                "ADM_NM",
                "geometry",
            ]
        ],
        how="left",
        predicate="within",
    )

    joined["dong"] = joined["ADM_NM"].astype("string")

    # 행정동 polygon에 들어가지 않은 경우
    # 30m 이내 nearest 행정동으로 보정
    unmatched_mask = joined["ADM_NM"].isna()

    if unmatched_mask.any():

        unmatched = joined.loc[unmatched_mask].drop(
            columns=[
                "ADM_CD",
                "ADM_NM",
                "index_right",
            ],
            errors="ignore",
        )

        nearest = gpd.sjoin_nearest(
            unmatched,
            dong[
                [
                    "ADM_CD",
                    "ADM_NM",
                    "geometry",
                ]
            ],
            how="left",
            distance_col="admin_distance_m",
        )

        nearest = nearest.sort_values(
            [
                "poi_id",
                "admin_distance_m",
                "ADM_CD",
            ]
        ).drop_duplicates(
            subset=["poi_id"],
            keep="first",
        )

        nearest = nearest[nearest["admin_distance_m"] <= ADMIN_NEAREST_THRESHOLD_M]

        for idx, row in nearest.iterrows():
            joined.loc[idx, "ADM_CD"] = row["ADM_CD"]
            joined.loc[idx, "ADM_NM"] = row["ADM_NM"]
            joined.loc[idx, "dong"] = row["ADM_NM"]

    joined["zone"] = joined["dong"].apply(map_zone)

    print("\n=== 행정동 / zone ===")
    print("dong 매핑:", joined["dong"].notna().sum())
    print("dong NULL:", joined["dong"].isna().sum())
    print("zone 매핑:", joined["zone"].notna().sum())
    print("zone NULL:", joined["zone"].isna().sum())

    print("\n=== TourAPI 행정동별 ===")
    print(joined["dong"].value_counts(dropna=False).to_string())

    # ==========================================
    # 3. 상권 공간조인
    # ==========================================

    commercial = gpd.read_file(COMMERCIAL_SHP_PATH)

    commercial = commercial[commercial["SIGNGU_CD_"] == "용산구"].copy()

    commercial["area_m2"] = commercial.geometry.area

    # 행정동 공간조인 결과에서
    # 행정동 polygon 컬럼 제거
    base = joined.drop(
        columns=[
            "index_right",
            "geometry",
        ],
        errors="ignore",
    )

    base_gdf = gpd.GeoDataFrame(
        base,
        geometry=gpd.points_from_xy(
            base["longitude"],
            base["latitude"],
        ),
        crs="EPSG:4326",
    )

    base_gdf = base_gdf.to_crs(commercial.crs)

    area_joined = gpd.sjoin(
        base_gdf,
        commercial[
            [
                "TRDAR_CD",
                "TRDAR_CD_N",
                "TRDAR_SE_1",
                "area_m2",
                "geometry",
            ]
        ],
        how="left",
        predicate="within",
    )

    # 여러 상권에 포함되는 경우
    # 가장 작은 polygon을 선택
    area_joined = (
        area_joined.sort_values(
            [
                "poi_id",
                "area_m2",
                "TRDAR_CD",
            ],
            na_position="last",
        )
        .drop_duplicates(
            subset=["poi_id"],
            keep="first",
        )
        .copy()
    )

    area_joined["commercial_area_id"] = area_joined["TRDAR_CD"].astype("string")

    area_joined["commercial_area_name"] = area_joined["TRDAR_CD_N"].astype("string")

    area_joined["commercial_area_match_method"] = "polygon"

    # ==========================================
    # 4. 상권 미매핑 → 60m nearest 보정
    # ==========================================

    unmatched_mask = area_joined["commercial_area_id"].isna()

    if unmatched_mask.any():

        unmatched = area_joined.loc[unmatched_mask].drop(
            columns=[
                "TRDAR_CD",
                "TRDAR_CD_N",
                "TRDAR_SE_1",
                "area_m2",
                "index_right",
            ],
            errors="ignore",
        )

        commercial_nearest = commercial[
            [
                "TRDAR_CD",
                "TRDAR_CD_N",
                "TRDAR_SE_1",
                "geometry",
            ]
        ].rename(
            columns={
                "TRDAR_CD": "nearest_area_id",
                "TRDAR_CD_N": "nearest_area_name",
                "TRDAR_SE_1": "nearest_area_type",
            }
        )

        nearest = gpd.sjoin_nearest(
            unmatched,
            commercial_nearest,
            how="left",
            distance_col="commercial_distance_m",
        )

        nearest = nearest.sort_values(
            [
                "poi_id",
                "commercial_distance_m",
                "nearest_area_id",
            ]
        ).drop_duplicates(
            subset=["poi_id"],
            keep="first",
        )

        nearest = nearest[
            nearest["commercial_distance_m"] <= COMMERCIAL_NEAREST_THRESHOLD_M
        ]

        for idx, row in nearest.iterrows():

            area_joined.loc[
                idx,
                "commercial_area_id",
            ] = row["nearest_area_id"]

            area_joined.loc[
                idx,
                "commercial_area_name",
            ] = row["nearest_area_name"]

            area_joined.loc[
                idx,
                "commercial_area_match_method",
            ] = "nearest_60m"

    area_joined.loc[
        area_joined["commercial_area_id"].isna(),
        "commercial_area_match_method",
    ] = "unmapped"

    # ==========================================
    # 5. QC
    # ==========================================

    print("\n=== TourAPI 상권 매핑 ===")

    mapped = area_joined["commercial_area_id"].notna().sum()

    total = len(area_joined)

    print("전체:", total)
    print("매핑 성공:", mapped)
    print("매핑 실패:", total - mapped)

    if total:
        print("매핑률:", f"{mapped / total * 100:.2f}%")

    print("\n=== 매핑 방법 ===")
    print(area_joined["commercial_area_match_method"].value_counts().to_string())

    print("\n=== 최종 TourAPI POI ===")

    print(
        area_joined[
            [
                "poi_id",
                "name",
                "category_l1",
                "dong",
                "zone",
                "commercial_area_id",
                "commercial_area_match_method",
            ]
        ].to_string(index=False)
    )

    print("\npoi_id 중복:", area_joined["poi_id"].duplicated().sum())

    # ==========================================
    # 6. 저장
    # ==========================================

    output = pd.DataFrame(
        area_joined.drop(
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
