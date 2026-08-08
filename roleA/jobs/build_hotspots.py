from pathlib import Path

import pandas as pd

DATA_PATH = Path("roleA/data/서울시 주요 121장소 목록.xlsx")

YONGSAN_HOTSPOT_CODES = [
    "POI004",  # 이태원 관광특구
    "POI030",  # 삼각지역
    "POI046",  # 용산역
    "POI047",  # 이태원역
    "POI076",  # 용리단길
    "POI077",  # 이태원 앤틱가구거리
    "POI082",  # 해방촌·경리단길
]

OUTPUT_PATH = Path("roleA/data/yongsan_hotspots.json")


def main():
    if not DATA_PATH.exists():
        raise FileNotFoundError(f"파일을 찾을 수 없습니다: {DATA_PATH}")

    # 엑셀 파일의 시트 목록 확인
    excel_file = pd.ExcelFile(DATA_PATH)

    # 첫 번째 시트 읽기
    df = pd.read_excel(DATA_PATH, sheet_name=excel_file.sheet_names[0])

    # 프로젝트에서 사용할 용산 핵심 핫스팟 7개 추출
    yongsan = df[df["AREA_CD"].isin(YONGSAN_HOTSPOT_CODES)].copy()

    print("\n" + "=" * 60)
    print("용산 핵심 핫스팟")
    print("=" * 60)

    print(yongsan[["CATEGORY", "AREA_CD", "AREA_NM", "ENG_NM"]].to_string(index=False))

    # JSON 저장
    records = (
        yongsan[["AREA_CD", "AREA_NM", "CATEGORY", "ENG_NM"]]
        .rename(
            columns={
                "AREA_CD": "code",
                "AREA_NM": "name",
                "CATEGORY": "category",
                "ENG_NM": "eng_name",
            }
        )
        .to_dict(orient="records")
    )

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    pd.DataFrame(records).to_json(
        OUTPUT_PATH,
        orient="records",
        force_ascii=False,
        indent=2,
    )

    print(f"\n저장 완료: {OUTPUT_PATH}")
    print(f"저장 건수: {len(records)}")


if __name__ == "__main__":
    main()
