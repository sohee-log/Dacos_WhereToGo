from pathlib import Path

import geopandas as gpd
import pandas as pd

ROOT_DIR = Path(__file__).resolve().parents[2]

POI_PATH = ROOT_DIR / "roleA" / "data" / "yongsan_poi_candidates.csv"

COMMERCIAL_SHP_PATH = (
    ROOT_DIR
    / "roleA"
    / "data"
    / "commercial_area"
    / "서울시 상권분석서비스(영역-상권).shp"
)

OUTPUT_PATH = ROOT_DIR / "roleA" / "data" / "commercial_area_unmatched_qc.csv"


def main():

    # --------------------------
    # 1. 추천대상 POI
    # --------------------------

    df = pd.read_csv(
        POI_PATH,
        encoding="utf-8-sig",
        low_memory=False,
    )

    unmatched = df[df["commercial_area_id"].isna()].copy()

    print("추천대상 전체:", len(df))
    print("상권 미매핑:", len(unmatched))

    # --------------------------
    # 2. 미매핑 POI 공간데이터화
    # --------------------------

    poi_gdf = gpd.GeoDataFrame(
        unmatched,
        geometry=gpd.points_from_xy(
            unmatched["경도"],
            unmatched["위도"],
        ),
        crs="EPSG:4326",
    )

    # --------------------------
    # 3. 용산구 상권 읽기
    # --------------------------

    commercial = gpd.read_file(COMMERCIAL_SHP_PATH)

    commercial = commercial[commercial["SIGNGU_CD_"] == "용산구"].copy()

    # EPSG:5181에서 거리 계산
    poi_gdf = poi_gdf.to_crs(commercial.crs)

    # --------------------------
    # 4. 가장 가까운 상권 찾기
    # --------------------------

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
        poi_gdf,
        commercial_nearest,
        how="left",
        distance_col="distance_m",
    )

    # 동일 거리의 상권이 여러 개 잡힐 경우
    # POI당 1개만 남김
    nearest = (
        nearest.sort_values(
            [
                "상가업소번호",
                "distance_m",
                "nearest_area_id",
            ]
        )
        .drop_duplicates(
            subset=["상가업소번호"],
            keep="first",
        )
        .copy()
    )

    # --------------------------
    # 5. 거리 구간 QC
    # --------------------------

    bins = [
        -1,
        10,
        30,
        50,
        100,
        200,
        500,
        float("inf"),
    ]

    labels = [
        "0~10m",
        "10~30m",
        "30~50m",
        "50~100m",
        "100~200m",
        "200~500m",
        "500m+",
    ]

    nearest["distance_bin"] = pd.cut(
        nearest["distance_m"],
        bins=bins,
        labels=labels,
    )

    print("\n=== 가장 가까운 상권까지 거리 ===")
    print(nearest["distance_bin"].value_counts(sort=False).to_string())

    print("\n=== 거리 통계 ===")
    print(nearest["distance_m"].describe().to_string())

    # --------------------------
    # 6. zone별
    # --------------------------

    print("\n=== zone별 미매핑 ===")
    print(nearest["zone"].value_counts().to_string())

    # --------------------------
    # 7. category별
    # --------------------------

    print("\n=== 카테고리별 미매핑 ===")
    print(nearest["category_l1"].value_counts().to_string())

    # --------------------------
    # 8. 멀리 떨어진 POI 예시
    # --------------------------

    print("\n=== 100m 초과 POI 예시 ===")

    cols = [
        "상가업소번호",
        "상호명",
        "category_l1",
        "dong",
        "zone",
        "nearest_area_id",
        "nearest_area_name",
        "nearest_area_type",
        "distance_m",
        "경도",
        "위도",
    ]

    print(
        nearest[nearest["distance_m"] > 100][cols]
        .sort_values(
            "distance_m",
            ascending=False,
        )
        .head(30)
        .to_string(index=False)
    )

    print("\n=== 거리 임계값별 예상 매핑률 ===")

    base_mapped = 5625
    total_poi = 6663

    for threshold in [30, 50, 60, 75, 100]:
        added = (nearest["distance_m"] <= threshold).sum()
        final_mapped = base_mapped + added
        rate = final_mapped / total_poi * 100

        print(
            f"{threshold}m 이내: "
            f"추가 {added}건 / "
            f"최종 {final_mapped}건 / "
            f"{rate:.2f}%"
        )

    # --------------------------
    # 9. 저장
    # --------------------------

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
