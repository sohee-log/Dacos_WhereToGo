from pathlib import Path

import geopandas as gpd
from shapely.geometry import MultiPolygon, Polygon

from roleA.common.db import get_conn

ROOT_DIR = Path(__file__).resolve().parents[2]

SHP_PATH = ROOT_DIR / "roleA" / "data" / "admin_dong" / "bnd_dong_11030_2025_2Q.shp"


ZONE_MAP = {
    # 이태원권
    "이태원1동": "itaewon",
    "이태원2동": "itaewon",
    "한남동": "itaewon",
    "보광동": "itaewon",
    # 용산역권
    "한강로동": "yongsan_stn",
    "남영동": "yongsan_stn",
    # 후암/해방촌권
    "후암동": "huam",
    "용산2가동": "huam",
    # 이촌권
    "이촌1동": "ichon",
    "이촌2동": "ichon",
    "서빙고동": "ichon",
    # 청파/원효권
    "청파동": "cheongpa",
    "원효로1동": "cheongpa",
    "원효로2동": "cheongpa",
    "효창동": "cheongpa",
    "용문동": "cheongpa",
}


def to_multipolygon(geom):

    if isinstance(geom, MultiPolygon):
        return geom

    if isinstance(geom, Polygon):
        return MultiPolygon([geom])

    raise ValueError(f"지원하지 않는 geometry 타입: {geom.geom_type}")


def main():

    # ==========================================
    # SHP 읽기
    # ==========================================

    gdf = gpd.read_file(SHP_PATH)

    print("원본 행정동:", len(gdf))
    print("원본 CRS:", gdf.crs)
    print("컬럼:", gdf.columns.tolist())

    # 컬럼명을 소문자로 통일
    gdf.columns = [col.lower() for col in gdf.columns]

    # SGIS 파일
    # adm_cd / adm_nm 사용
    required = {
        "adm_cd",
        "adm_nm",
        "geometry",
    }

    missing = required - set(gdf.columns)

    if missing:
        raise ValueError(f"필수 컬럼 없음: {missing}")

    # ==========================================
    # 좌표계 EPSG:4326
    # ==========================================

    gdf = gdf.to_crs(epsg=4326)

    # 우리가 사용하는 16개 행정동만
    gdf = gdf[gdf["adm_nm"].isin(ZONE_MAP.keys())].copy()

    gdf["zone"] = gdf["adm_nm"].map(ZONE_MAP)

    gdf["geometry"] = gdf["geometry"].apply(to_multipolygon)

    print(
        "\n적재 대상 행정동:",
        len(gdf),
    )

    print(
        gdf[
            [
                "adm_cd",
                "adm_nm",
                "zone",
            ]
        ].to_string(index=False)
    )

    if len(gdf) != 16:
        raise ValueError(f"행정동이 16개가 아닙니다: {len(gdf)}")

    # ==========================================
    # DB 적재
    # ==========================================

    conn = get_conn()

    try:

        with conn.cursor() as cur:

            for row in gdf.itertuples(index=False):

                cur.execute(
                    """
                    INSERT INTO admin_dong (
                        adm_cd,
                        adm_nm,
                        zone,
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
                    ON CONFLICT (adm_cd)
                    DO UPDATE SET
                        adm_nm = EXCLUDED.adm_nm,
                        zone = EXCLUDED.zone,
                        geom = EXCLUDED.geom
                    """,
                    (
                        str(row.adm_cd),
                        row.adm_nm,
                        row.zone,
                        row.geometry.wkt,
                    ),
                )

        conn.commit()

        # ======================================
        # QC
        # ======================================

        with conn.cursor() as cur:

            cur.execute("""
                SELECT COUNT(*)
                FROM admin_dong
                """)

            count = cur.fetchone()[0]

            print(
                "\nadmin_dong DB:",
                count,
            )

            cur.execute("""
                SELECT
                    adm_nm,
                    zone
                FROM admin_dong
                ORDER BY adm_nm
                """)

            print("\n=== DB 행정동 ===")

            for adm_nm, zone in cur.fetchall():
                print(f"{adm_nm:10} → {zone}")

        if count != 16:
            raise ValueError(f"DB 행정동이 16개가 아닙니다: {count}")

        print("\nadmin_dong 적재 완료")

    except Exception:

        conn.rollback()
        raise

    finally:

        conn.close()


if __name__ == "__main__":
    main()
