from pathlib import Path

import pandas as pd

ROOT_DIR = Path(__file__).resolve().parents[2]

INPUT_PATH = ROOT_DIR / "roleA" / "data" / "yongsan_poi_with_commercial_area.csv"

OUTPUT_PATH = ROOT_DIR / "roleA" / "data" / "yongsan_poi_candidates.csv"


def map_category_l1(row):

    large = row.get("상권업종대분류명")
    middle = row.get("상권업종중분류명")
    small = row.get("상권업종소분류명")

    # 카페는 음식과 분리
    if small == "카페":
        return "카페"

    if large == "음식":
        return "음식"

    if middle in [
        "스포츠 서비스",
        "유원지·오락",
        "도서관·사적지",
    ]:
        return "문화"

    if middle in [
        "종합 소매",
        "오락용품 소매",
        "식물 소매",
        "장식품 소매",
    ]:
        return "쇼핑"

    return None


def main():

    df = pd.read_csv(
        INPUT_PATH,
        encoding="utf-8-sig",
        low_memory=False,
    )

    print("용산 전체 상가:", len(df))

    # 프로젝트 category_l1 생성
    df["category_l1"] = df.apply(
        map_category_l1,
        axis=1,
    )

    # 추천대상만 남김
    candidates = df[df["category_l1"].notna()].copy()

    print("\n=== 추천대상 POI ===")
    print("총:", len(candidates))

    print("\n=== 카테고리별 ===")
    print(candidates["category_l1"].value_counts().to_string())

    # 상권 매핑 QC
    mapped = candidates["commercial_area_id"].notna().sum()

    total = len(candidates)
    unmapped = total - mapped

    print("\n=== 추천대상 상권 매핑 ===")
    print("추천대상:", total)
    print("매핑 성공:", mapped)
    print("매핑 실패:", unmapped)

    if total > 0:
        print("매핑률:", f"{mapped / total * 100:.2f}%")

    # zone별 확인
    print("\n=== zone별 추천대상 ===")
    print(candidates["zone"].value_counts(dropna=False).to_string())

    # 카테고리별 상권 매핑률
    print("\n=== 카테고리별 상권 매핑률 ===")

    category_qc = candidates.groupby("category_l1")["commercial_area_id"].agg(
        total="size",
        mapped=lambda x: x.notna().sum(),
    )

    category_qc["mapping_rate"] = (
        category_qc["mapped"] / category_qc["total"] * 100
    ).round(2)

    print(category_qc.to_string())

    # 저장
    candidates.to_csv(
        OUTPUT_PATH,
        index=False,
        encoding="utf-8-sig",
    )

    print("\n저장 완료:")
    print(OUTPUT_PATH)


if __name__ == "__main__":
    main()
