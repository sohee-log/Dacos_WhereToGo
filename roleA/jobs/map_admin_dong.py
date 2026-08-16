from pathlib import Path

import geopandas as gpd
import pandas as pd

ROOT_DIR = Path(__file__).resolve().parents[2]

STORE_PATH = ROOT_DIR / "roleA" / "data" / "store_info.csv"

DONG_SHP_PATH = (
    ROOT_DIR / "roleA" / "data" / "admin_dong" / "bnd_dong_11030_2025_2Q.shp"
)

OUTPUT_PATH = ROOT_DIR / "roleA" / "data" / "yongsan_poi_with_dong.csv"


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


def read_store_csv(path):
    """상가정보 CSV 읽기"""

    for encoding in ["utf-8-sig", "cp949"]:
        try:
            return pd.read_csv(
                path,
                encoding=encoding,
                low_memory=False,
            )
        except UnicodeDecodeError:
            continue

    raise RuntimeError("CSV 인코딩을 확인해주세요.")


def map_zone(dong):
    """행정동명을 프로젝트 zone으로 변환"""

    # 공간조인에 실패해서 행정동이 없는 경우
    if pd.isna(dong):
        return None

    for zone, dongs in ZONE_DONGS.items():
        if dong in dongs:
            return zone

    return None


def main():

    # ==========================================
    # 1. 상가정보 읽기
    # ==========================================

    stores = read_store_csv(STORE_PATH)

    print("전체 상가 수:", len(stores))

    # 용산구만 사용
    yongsan = stores[stores["시군구명"] == "용산구"].copy()

    print("용산구 상가 수:", len(yongsan))

    # 좌표 없는 데이터 제거
    before = len(yongsan)

    yongsan = yongsan.dropna(subset=["경도", "위도"]).copy()

    print("좌표 있는 상가 수:", len(yongsan), f"(제거 {before - len(yongsan)}건)")

    # ==========================================
    # 2. POI → GeoDataFrame
    # ==========================================

    # 상가정보 좌표는 경도/위도(WGS84)
    poi_gdf = gpd.GeoDataFrame(
        yongsan,
        geometry=gpd.points_from_xy(
            yongsan["경도"],
            yongsan["위도"],
        ),
        crs="EPSG:4326",
    )

    # ==========================================
    # 3. 행정동 경계 읽기
    # ==========================================

    dong_gdf = gpd.read_file(DONG_SHP_PATH)

    print("\n행정동 경계 수:", len(dong_gdf))
    print("행정동 CRS:", dong_gdf.crs)

    print("\n=== SGIS 행정동 ===")
    print(dong_gdf[["ADM_CD", "ADM_NM"]].to_string(index=False))

    # ==========================================
    # 4. 좌표계 통일
    # ==========================================

    # SGIS 경계가 EPSG:5179이므로
    # POI도 5179로 변환
    poi_gdf = poi_gdf.to_crs(dong_gdf.crs)

    # ==========================================
    # 5. Spatial Join
    # ==========================================

    joined = gpd.sjoin(
        poi_gdf,
        dong_gdf[["ADM_CD", "ADM_NM", "geometry"]],
        how="left",
        predicate="within",
    )

    # ==========================================
    # 공간조인 실패 POI의 가장 가까운 행정동 확인
    # ==========================================

    unmatched = joined[joined["ADM_NM"].isna()].copy()

    if len(unmatched) > 0:

        nearest = gpd.sjoin_nearest(
            unmatched.drop(
                columns=["ADM_CD", "ADM_NM", "index_right"],
                errors="ignore",
            ),
            dong_gdf[["ADM_CD", "ADM_NM", "geometry"]],
            how="left",
            distance_col="distance_m",
        )

        print("\n=== 공간조인 실패 POI - 가장 가까운 행정동 ===")

        cols = [
            "상가업소번호",
            "상호명",
            "행정동명",
            "ADM_NM",
            "distance_m",
            "경도",
            "위도",
        ]

        print(nearest[cols].to_string(index=False))

    # ==========================================
    # 공간조인 실패 POI nearest 보정
    # ==========================================

    joined["dong"] = joined["ADM_NM"].astype("string")

    unmatched_mask = joined["ADM_NM"].isna()

    if unmatched_mask.any():

        unmatched = joined.loc[unmatched_mask].drop(
            columns=["ADM_CD", "ADM_NM", "index_right"],
            errors="ignore",
        )

        nearest = gpd.sjoin_nearest(
            unmatched,
            dong_gdf[["ADM_CD", "ADM_NM", "geometry"]],
            how="left",
            distance_col="distance_m",
        )

        # 30m 이내일 때만 자동 보정
        nearest_valid = nearest[nearest["distance_m"] <= 30]

        for idx, row in nearest_valid.iterrows():
            joined.loc[idx, "ADM_CD"] = row["ADM_CD"]
            joined.loc[idx, "ADM_NM"] = row["ADM_NM"]
            joined.loc[idx, "dong"] = row["ADM_NM"]

    # ADM_NM이
    # "서울특별시 용산구 후암동" 형태여도
    # 마지막 '후암동'만 가져오도록 처리
    joined["dong"] = joined["ADM_NM"].astype("string").str.strip().str.split().str[-1]

    joined["zone"] = joined["dong"].apply(map_zone)

    # ==========================================
    # 6. QC
    # ==========================================

    print("\n=== 공간조인 결과 ===")

    print("전체:", len(joined))
    print("행정동 매핑 성공:", joined["ADM_NM"].notna().sum())
    print("행정동 매핑 실패:", joined["ADM_NM"].isna().sum())
    print("zone 매핑 성공:", joined["zone"].notna().sum())
    print("zone 매핑 실패:", joined["zone"].isna().sum())

    print("\n=== 행정동별 POI 수 ===")
    print(joined["dong"].value_counts(dropna=False).to_string())

    print("\n=== zone별 POI 수 ===")
    print(joined["zone"].value_counts(dropna=False).to_string())

    print("\n=== 최종 행정동 매핑 결과 ===")
    print("전체:", len(joined))
    print("dong 매핑 성공:", joined["dong"].notna().sum())
    print("dong 매핑 실패:", joined["dong"].isna().sum())
    print("zone 매핑 성공:", joined["zone"].notna().sum())
    print("zone 매핑 실패:", joined["zone"].isna().sum())

    # ==========================================
    # 7. 기존 행정동명과 공간조인 결과 비교
    # ==========================================

    if "행정동명" in joined.columns:

        joined["dong_match"] = joined["행정동명"] == joined["dong"]

        print("\n=== 원본 행정동명 vs 공간조인 비교 ===")

        print(joined["dong_match"].value_counts(dropna=False).to_string())

        mismatch = joined[joined["dong_match"] == False]

        print("불일치 건수:", len(mismatch))

        print("\n=== 불일치 POI 상세 ===")

        check_cols = [
            "상가업소번호",
            "상호명",
            "행정동명",
            "dong",
            "ADM_CD",
            "경도",
            "위도",
        ]

        check_cols = [col for col in check_cols if col in mismatch.columns]

        print(mismatch[check_cols].to_string(index=False))

        # QC용 파일 저장
        mismatch[check_cols].to_csv(
            ROOT_DIR / "roleA" / "data" / "admin_dong_mismatch.csv",
            index=False,
            encoding="utf-8-sig",
        )

    # ==========================================
    # 8. CSV 저장
    # ==========================================

    # geometry는 DB 적재 시 경도/위도로 다시 만들 수 있으므로
    # CSV에서는 제거
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
