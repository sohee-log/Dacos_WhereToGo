import argparse
from pathlib import Path

import pandas as pd

DATA_PATH = Path("roleA/data/store_info.csv")

T1_DONGS = [
    "이태원1동",
    "이태원2동",
    "한남동",
    "한강로동",
    "후암동",
]


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=20)
    return parser.parse_args()


def load_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"파일을 찾을 수 없습니다: {path}")

    # 공공데이터 CSV는 인코딩이 UTF-8 또는 CP949인 경우가 많아서 둘 다 시도
    try:
        return pd.read_csv(path, encoding="utf-8-sig", low_memory=False)
    except UnicodeDecodeError:
        return pd.read_csv(path, encoding="cp949", low_memory=False)


def map_category_l1(row):
    large = row["상권업종대분류명"]
    middle = row["상권업종중분류명"]
    small = row["상권업종소분류명"]

    # 카페를 음식에서 분리
    if small == "카페":
        return "카페"

    # 일반 음식점
    if large == "음식":
        return "음식"

    # 여가/문화 후보
    if middle in [
        "스포츠 서비스",
        "유원지·오락",
        "도서관·사적지",
    ]:
        return "문화"

    # 쇼핑 후보는 우선 일부만
    if middle in [
        "종합 소매",
        "오락용품 소매",
        "식물 소매",
        "장식품 소매",
    ]:
        return "쇼핑"

    return None


def main():
    args = parse_args()

    df = load_csv(DATA_PATH)

    print("=" * 60)
    print("상가정보 CSV 로드 완료")
    print("=" * 60)

    print(f"전체 행 수: {len(df):,}")
    print(f"전체 컬럼 수: {len(df.columns)}")

    print("\n[컬럼 목록]")
    for col in df.columns:
        print("-", col)

    # 용산구 데이터 확인
    if "시군구명" in df.columns:
        yongsan = df[df["시군구명"] == "용산구"]

        print("\n" + "=" * 60)
        print("용산구 데이터")
        print("=" * 60)

        print(f"용산구 행 수: {len(yongsan):,}")

        print("\n" + "=" * 60)
        print("용산구 업종 대분류")
        print("=" * 60)

        print(yongsan["상권업종대분류명"].value_counts().to_string())

        print("\n" + "=" * 60)
        print("용산구 업종 중분류")
        print("=" * 60)

        print(yongsan["상권업종중분류명"].value_counts().to_string())

        print("\n" + "=" * 60)
        print("용산구 업종 소분류 목록")
        print("=" * 60)

        for category in sorted(yongsan["상권업종소분류명"].dropna().unique()):
            print("-", category)

        print("\n" + "=" * 60)
        print("좌표 결측")
        print("=" * 60)

        print(f"경도 결측: {yongsan['경도'].isna().sum():,}")
        print(f"위도 결측: {yongsan['위도'].isna().sum():,}")

        t1 = yongsan[yongsan["행정동명"].isin(T1_DONGS)]

        print("\n" + "=" * 60)
        print("T1 업종 대분류")
        print("=" * 60)
        print(t1["상권업종대분류명"].value_counts().to_string())

        print("\n" + "=" * 60)
        print("T1 음식 중분류")
        print("=" * 60)

        t1_food = t1[t1["상권업종대분류명"] == "음식"]

        print(t1_food["상권업종중분류명"].value_counts().to_string())

        t1 = t1.copy()
        t1["category_l1"] = t1.apply(map_category_l1, axis=1)

        recommendable = t1[t1["category_l1"].notna()]

        # 1차 추천 대상
        print("\n" + "=" * 60)
        print("1차 추천 대상")
        print("=" * 60)

        print(f"추천 후보 수: {len(recommendable):,}")
        print(recommendable["category_l1"].value_counts().to_string())

        print("\n" + "=" * 60)
        print("동별 × 추천 카테고리")
        print("=" * 60)

        print(
            pd.crosstab(
                recommendable["행정동명"],
                recommendable["category_l1"],
            ).to_string()
        )

        print("\n" + "=" * 60)
        print("T1 현황")
        print("=" * 60)

        print(f"T1 전체 상가 수: {len(t1):,}")
        print(t1["행정동명"].value_counts().to_string())

        if args.dry_run:
            print("\n[용산구 샘플]")
            print(yongsan.head(args.limit).to_string())

    else:
        print("\n'시군구명' 컬럼이 없습니다.")
        print("위 컬럼 목록을 확인해주세요.")


if __name__ == "__main__":
    main()
