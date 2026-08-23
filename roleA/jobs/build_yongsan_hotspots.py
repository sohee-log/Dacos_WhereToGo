from pathlib import Path

import geopandas as gpd
import pandas as pd

ROOT_DIR = Path(__file__).resolve().parents[2]

HOTSPOT_SHP = (
    ROOT_DIR
    / "roleA"
    / "data"
    / "hotspot_121_source"
    / "서울시 주요 121장소 영역"
    / "서울시 주요 121장소 영역.shp"
)

ADMIN_SHP = ROOT_DIR / "roleA" / "data" / "admin_dong" / "bnd_dong_11030_2025_2Q.shp"

OUTPUT_PATH = ROOT_DIR / "roleA" / "data" / "yongsan_hotspots.csv"

MIN_OVERLAP_RATIO = 0.10


def main():

    # ==========================================
    # 데이터 읽기
    # ==========================================

    hotspots = gpd.read_file(HOTSPOT_SHP)

    admin = gpd.read_file(ADMIN_SHP)

    hotspots.columns = [col.lower() for col in hotspots.columns]

    admin.columns = [col.lower() for col in admin.columns]

    print(
        "전체 hotspot:",
        len(hotspots),
    )

    print(
        "용산 행정동:",
        len(admin),
    )

    # ==========================================
    # 면적 계산용 좌표계
    # EPSG:5179
    # ==========================================

    hotspots_proj = hotspots.to_crs(epsg=5179)

    admin_proj = admin.to_crs(epsg=5179)

    # 용산구 16개 행정동을 하나의 영역으로 합침
    yongsan_geom = admin_proj.geometry.union_all()

    # ==========================================
    # hotspot별 용산구 overlap 계산
    # ==========================================

    rows = []

    for row in hotspots_proj.itertuples(index=False):

        geom = row.geometry

        hotspot_area = geom.area

        intersection = geom.intersection(yongsan_geom)

        overlap_area = intersection.area if not intersection.is_empty else 0

        overlap_ratio = overlap_area / hotspot_area if hotspot_area > 0 else 0

        # 단순 경계 접촉(area=0)은 제외
        overlap_ratio = overlap_area / hotspot_area if hotspot_area > 0 else 0

        if overlap_ratio < MIN_OVERLAP_RATIO:
            continue

        # 원래 hotspot Polygon 내부의 대표점
        # DB에는 Point를 넣어야 함
        # 용산구와 실제로 겹치는 부분의 대표점을 사용한다.
        # 남산공원처럼 일부만 용산에 포함되는 hotspot의
        # 대표점이 다른 구에 찍히는 문제를 방지한다.

        intersection_4326 = (
            gpd.GeoSeries(
                [intersection],
                crs="EPSG:5179",
            )
            .to_crs(epsg=4326)
            .iloc[0]
        )

        point = intersection_4326.representative_point()

        rows.append(
            {
                "code": row.area_cd,
                "name": row.area_nm,
                "category": row.category,
                "overlap_ratio": overlap_ratio,
                "longitude": point.x,
                "latitude": point.y,
            }
        )

    result = pd.DataFrame(rows)

    result = result.sort_values(
        [
            "overlap_ratio",
            "name",
        ],
        ascending=[
            False,
            True,
        ],
    ).reset_index(drop=True)

    # ==========================================
    # 출력
    # ==========================================

    print("\n=== 용산구와 실제 면적이 겹치는 hotspot ===")

    print(
        result.to_string(
            index=False,
            formatters={"overlap_ratio": lambda x: f"{x:.3f}"},
        )
    )

    print(
        "\n선정 hotspot:",
        len(result),
    )

    print("\n=== overlap 비율 ===")

    print(
        result[
            [
                "code",
                "name",
                "overlap_ratio",
            ]
        ].to_string(
            index=False,
            formatters={"overlap_ratio": lambda x: f"{x:.3%}"},
        )
    )

    # ==========================================
    # 저장
    # ==========================================

    result.to_csv(
        OUTPUT_PATH,
        index=False,
        encoding="utf-8-sig",
    )

    print("\n저장 완료:")

    print(OUTPUT_PATH)


if __name__ == "__main__":
    main()
