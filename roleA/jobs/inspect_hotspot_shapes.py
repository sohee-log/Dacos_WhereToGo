from pathlib import Path
import zipfile

import geopandas as gpd

ROOT_DIR = Path(__file__).resolve().parents[2]

ZIP_PATH = ROOT_DIR / "roleA" / "data" / "서울시 주요 121장소 영역.zip"

EXTRACT_DIR = ROOT_DIR / "roleA" / "data" / "hotspot_121_source"


def main():

    # ==========================================
    # ZIP 압축 해제
    # ==========================================

    EXTRACT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    with zipfile.ZipFile(
        ZIP_PATH,
        "r",
    ) as z:
        z.extractall(EXTRACT_DIR)

    # shp 파일 자동 탐색
    shp_files = list(EXTRACT_DIR.rglob("*.shp"))

    if not shp_files:
        raise FileNotFoundError("ZIP 안에서 shp 파일을 찾지 못했습니다.")

    shp_path = shp_files[0]

    print("SHP:")
    print(shp_path)

    # ==========================================
    # 읽기
    # ==========================================

    gdf = gpd.read_file(shp_path)

    print(
        "\n전체 영역:",
        len(gdf),
    )

    print(
        "\nCRS:",
        gdf.crs,
    )

    print("\n=== 컬럼 ===")

    print(gdf.columns.tolist())

    print("\n=== Geometry 타입 ===")

    print(gdf.geometry.geom_type.value_counts().to_string())

    print("\n=== 앞 10건 ===")

    print(gdf.head(10).drop(columns="geometry").to_string(index=False))

    # ==========================================
    # 용산 관련 이름 1차 확인
    # ==========================================

    name_columns = [
        col
        for col in gdf.columns
        if col.lower()
        in {
            "area_nm",
            "name",
            "area_name",
        }
    ]

    if name_columns:

        name_col = name_columns[0]

        keywords = [
            "용산",
            "이태원",
            "한남",
            "삼각지",
            "서울역",
            "후암",
            "경리단",
            "해방촌",
            "이촌",
        ]

        mask = False

        for keyword in keywords:

            mask = mask | gdf[name_col].astype(str).str.contains(
                keyword,
                na=False,
            )

        candidates = gdf[mask].copy()

        print("\n=== 용산 관련 이름 후보 ===")

        print(candidates.drop(columns="geometry").to_string(index=False))

        print(
            "\n이름 기준 후보:",
            len(candidates),
        )


if __name__ == "__main__":
    main()
