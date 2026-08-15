import argparse
from pathlib import Path

import geopandas as gpd
from shapely.geometry import MultiPolygon, Polygon

from roleA.common.db import get_conn

ROOT_DIR = Path(__file__).resolve().parents[2]

SHP_PATH = (
    ROOT_DIR
    / "roleA"
    / "data"
    / "commercial_area"
    / "서울시 상권분석서비스(영역-상권).shp"
)


def to_multipolygon(geom):
    """
    DB geom 컬럼이 MULTIPOLYGON이므로
    Polygon은 MultiPolygon으로 변환한다.
    """

    if geom is None:
        return None

    if isinstance(geom, MultiPolygon):
        return geom

    if isinstance(geom, Polygon):
        return MultiPolygon([geom])

    raise ValueError(f"지원하지 않는 geometry type: {geom.geom_type}")


def main():

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--dry-run",
        action="store_true",
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=None,
    )

    args = parser.parse_args()

    # ==========================================
    # 1. 서울시 상권 SHP 읽기
    # ==========================================

    commercial = gpd.read_file(SHP_PATH)

    print(
        "원본 상권:",
        len(commercial),
    )

    print(
        "원본 CRS:",
        commercial.crs,
    )

    # ==========================================
    # 2. 용산구만 필터링
    # ==========================================

    commercial = commercial[commercial["SIGNGU_CD_"] == "용산구"].copy()

    print(
        "용산구 상권:",
        len(commercial),
    )

    # ==========================================
    # 3. DB 좌표계 EPSG:4326으로 변환
    # ==========================================

    commercial = commercial.to_crs("EPSG:4326")

    commercial["geometry"] = commercial["geometry"].apply(to_multipolygon)

    if args.limit is not None:
        commercial = commercial.head(args.limit).copy()

    # ==========================================
    # 4. QC
    # ==========================================

    print("\n=== 적재 대상 ===")
    print("건수:", len(commercial))

    print("\n=== geometry type ===")
    print(commercial.geometry.geom_type.value_counts().to_string())

    print("\n=== 샘플 ===")

    print(
        commercial[
            [
                "TRDAR_CD",
                "TRDAR_CD_N",
                "TRDAR_SE_1",
            ]
        ]
        .head(20)
        .to_string(index=False)
    )

    if args.dry_run:

        print("\nDRY RUN - DB에는 저장하지 않았습니다.")
        return

    # ==========================================
    # 5. Supabase 적재
    # ==========================================

    conn = get_conn()

    try:

        with conn.cursor() as cur:

            for i, row in enumerate(
                commercial.itertuples(index=False),
                start=1,
            ):

                cur.execute(
                    """
                    INSERT INTO commercial_area (
                        commercial_area_id,
                        name,
                        area_type,
                        geom
                    )
                    VALUES (
                        %s,
                        %s,
                        %s,
                        ST_GeomFromText(
                            %s,
                            4326
                        )
                    )
                    ON CONFLICT (
                        commercial_area_id
                    )
                    DO UPDATE SET
                        name = EXCLUDED.name,
                        area_type =
                            EXCLUDED.area_type,
                        geom = EXCLUDED.geom
                    """,
                    (
                        str(row.TRDAR_CD),
                        row.TRDAR_CD_N,
                        row.TRDAR_SE_1,
                        row.geometry.wkt,
                    ),
                )

                print(
                    f"[{i}/{len(commercial)}] " f"{row.TRDAR_CD} " f"{row.TRDAR_CD_N}"
                )

        conn.commit()

        print(
            "\ncommercial_area 적재 완료:",
            len(commercial),
        )

    except Exception:

        conn.rollback()
        raise

    finally:

        conn.close()


if __name__ == "__main__":
    main()
