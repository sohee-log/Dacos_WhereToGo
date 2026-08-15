from pathlib import Path

import geopandas as gpd
import pandas as pd

ROOT_DIR = Path(__file__).resolve().parents[2]

POI_PATH = ROOT_DIR / "roleA" / "data" / "yongsan_poi_with_dong.csv"

COMMERCIAL_SHP_PATH = (
    ROOT_DIR
    / "roleA"
    / "data"
    / "commercial_area"
    / "서울시 상권분석서비스(영역-상권).shp"
)

OUTPUT_PATH = ROOT_DIR / "roleA" / "data" / "yongsan_poi_with_commercial_area.csv"


def main():

    # ==========================================
    # 1. 행정동/zone 매핑 완료 POI 읽기
    # ==========================================

    poi = pd.read_csv(
        POI_PATH,
        encoding="utf-8-sig",
        low_memory=False,
    )

    print("=== POI ===")
    print("POI 수:", len(poi))

    # ==========================================
    # 2. POI → GeoDataFrame
    # ==========================================

    poi_gdf = gpd.GeoDataFrame(
        poi,
        geometry=gpd.points_from_xy(
            poi["경도"],
            poi["위도"],
        ),
        crs="EPSG:4326",
    )

    # ==========================================
    # 3. 상권 폴리곤 읽기
    # ==========================================

    commercial = gpd.read_file(COMMERCIAL_SHP_PATH)
    commercial["area_m2"] = commercial.geometry.area  # 면적 추가

    print("\n=== 전체 상권 데이터 ===")
    print("전체 상권 수:", len(commercial))
    print("CRS:", commercial.crs)

    print("\n=== 시군구명 확인 ===")
    print(commercial["SIGNGU_CD_"].value_counts().head(30).to_string())

    # ==========================================
    # 4. 용산구 상권만 필터링
    # ==========================================

    yongsan_commercial = commercial[commercial["SIGNGU_CD_"] == "용산구"].copy()

    if len(yongsan_commercial) == 0:
        raise RuntimeError(
            "SIGNGU_CD_에서 '용산구'를 찾지 못했습니다. "
            "위 시군구명 출력을 확인해주세요."
        )

    print("\n=== 용산구 상권 ===")
    print("상권 수:", len(yongsan_commercial))

    print("\n=== 상권 구분 ===")
    print(
        yongsan_commercial[["TRDAR_SE_C", "TRDAR_SE_1"]]
        .drop_duplicates()
        .sort_values("TRDAR_SE_C")
        .to_string(index=False)
    )

    print("\n=== 용산구 상권 일부 ===")
    print(
        yongsan_commercial[
            [
                "TRDAR_CD",
                "TRDAR_CD_N",
                "TRDAR_SE_1",
                "ADSTRD_CD_",
            ]
        ]
        .head(20)
        .to_string(index=False)
    )

    # ==========================================
    # 5. 좌표계 통일
    # ==========================================

    # 상권 SHP가 EPSG:5181이므로
    # POI를 같은 좌표계로 변환
    poi_gdf = poi_gdf.to_crs(yongsan_commercial.crs)

    # ==========================================
    # 6. Spatial Join
    # ==========================================

    joined = gpd.sjoin(
        poi_gdf,
        yongsan_commercial[
            [
                "TRDAR_CD",
                "TRDAR_CD_N",
                "TRDAR_SE_C",
                "TRDAR_SE_1",
                "area_m2",
                "geometry",
            ]
        ],
        how="left",
        predicate="within",
    )

    # ==========================================
    # 7. 중복 매핑 확인
    # ==========================================

    # 상권 폴리곤이 서로 겹치는 경우
    # 하나의 POI가 여러 상권에 들어갈 수 있으므로 먼저 확인
    if "상가업소번호" in joined.columns:

        match_counts = joined.groupby("상가업소번호").size()

        multiple_match = match_counts[match_counts > 1]

        print("\n=== 복수 상권 매핑 확인 ===")
        print(
            "2개 이상 상권에 매핑된 POI:",
            len(multiple_match),
        )

    # ==========================================
    # 복수 상권 → 가장 작은 상권 1개 선택
    # ==========================================

    before_dedup = len(joined)

    joined = (
        joined.sort_values(
            ["상가업소번호", "area_m2", "TRDAR_CD"],
            na_position="last",
        )
        .drop_duplicates(
            subset=["상가업소번호"],
            keep="first",
        )
        .copy()
    )

    print("\n=== 복수 상권 정리 ===")
    print("정리 전 행:", before_dedup)
    print("정리 후 POI:", len(joined))
    print("제거된 중복 행:", before_dedup - len(joined))
    # ==========================================
    # 8. commercial_area_id 생성
    # ==========================================

    joined["commercial_area_id"] = joined["TRDAR_CD"].astype("string")

    joined["commercial_area_name"] = joined["TRDAR_CD_N"].astype("string")

    # ==========================================
    # 9. QC
    # ==========================================

    mapped = joined["commercial_area_id"].notna().sum()

    total = len(joined)

    print("\n=== 상권 공간조인 결과 ===")
    print("전체 행:", total)
    print("상권 매핑 성공:", mapped)
    print("상권 매핑 실패:", joined["commercial_area_id"].isna().sum())

    print("매핑률:", f"{mapped / total * 100:.2f}%")

    print("\n=== 상권 구분별 매핑 POI ===")
    print(joined["TRDAR_SE_1"].value_counts(dropna=False).to_string())

    # ==========================================
    # 10. 미매핑 POI 일부 확인
    # ==========================================

    unmatched = joined[joined["commercial_area_id"].isna()]

    print("\n=== 상권 미매핑 POI 예시 ===")

    cols = [
        "상가업소번호",
        "상호명",
        "dong",
        "zone",
        "경도",
        "위도",
    ]

    cols = [c for c in cols if c in unmatched.columns]

    print(unmatched[cols].head(30).to_string(index=False))

    # ==========================================
    # 11. 저장
    # ==========================================

    output = pd.DataFrame(
        joined.drop(
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
