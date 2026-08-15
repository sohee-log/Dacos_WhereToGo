from pathlib import Path

import pandas as pd

ROOT_DIR = Path(__file__).resolve().parents[2]

POI_PATH = ROOT_DIR / "roleA" / "data" / "yongsan_poi_final.csv"

OUTPUT_PATH = ROOT_DIR / "roleA" / "data" / "t1_candidates_filtered.csv"


T1_DONGS = [
    "이태원1동",
    "이태원2동",
    "한남동",
    "한강로동",
    "후암동",
]


# 업종 자체가 추천 POI로 적절하지 않은 경우
EXCLUDE_CATEGORY_L2 = {
    "구내식당·뷔페",
}


# 상가정보에서 '도서관·사적지'로 분류됐지만
# 실제로는 독서실/스터디카페인 경우가 확인됨
EXCLUDE_STORE_CATEGORY_L2 = {
    "도서관·사적지",
}


# 종합소매 중 생활형 편의시설 제외
GENERAL_RETAIL_PATTERNS = [
    r"GS25",
    r"지에스25",
    r"\bCU\b",
    r"^CU",  # CU이태원1동점 같은 형태
    r"씨유",
    r"이마트24",
    r"세븐일레븐",
    r"미니스톱",
    r"편의점",  # 우리편의점, 역 승강장 편의점 등
    r"슈퍼",
    r"마트",
    r"가판점",
]


# 관광/여가 추천과 거리가 먼 오락 업종
ENTERTAINMENT_EXCLUDE_PATTERNS = [
    r"스포츠토토",
    r"토토",
    r"복권",
]


def contains_pattern(series, patterns):

    pattern = "|".join(patterns)

    return (
        series.fillna("")
        .astype(str)
        .str.contains(
            pattern,
            case=False,
            regex=True,
        )
    )


def main():

    df = pd.read_csv(
        POI_PATH,
        encoding="utf-8-sig",
        low_memory=False,
    )

    # ------------------------------------------
    # T1 지역 후보
    # ------------------------------------------

    t1 = df[df["dong"].isin(T1_DONGS)].copy()

    print("T1 원본 후보:", len(t1))

    # 제외 이유를 따로 기록
    t1["exclude_reason"] = None

    # ------------------------------------------
    # 1. 구내식당·뷔페 제외
    # ------------------------------------------

    mask = t1["category_l2"].isin(EXCLUDE_CATEGORY_L2)

    t1.loc[
        mask,
        "exclude_reason",
    ] = "institutional_food"

    # ------------------------------------------
    # 2. 상가정보의 잘못 분류된 도서관·사적지
    # ------------------------------------------

    mask = (
        t1["category_l2"].isin(EXCLUDE_STORE_CATEGORY_L2)
        & (t1["source"] == "store_info")
        & t1["exclude_reason"].isna()
    )

    t1.loc[
        mask,
        "exclude_reason",
    ] = "misclassified_cultural"

    # ------------------------------------------
    # 3. 종합소매 중 편의점/슈퍼 등
    # ------------------------------------------

    retail_pattern_mask = contains_pattern(
        t1["name"],
        GENERAL_RETAIL_PATTERNS,
    )

    mask = (
        (t1["category_l2"] == "종합 소매")
        & retail_pattern_mask
        & t1["exclude_reason"].isna()
    )

    t1.loc[
        mask,
        "exclude_reason",
    ] = "general_convenience_retail"

    # ------------------------------------------
    # 4. 복권/토토 등 제외
    # ------------------------------------------

    entertainment_pattern_mask = contains_pattern(
        t1["name"],
        ENTERTAINMENT_EXCLUDE_PATTERNS,
    )

    mask = (
        (t1["category_l2"] == "유원지·오락")
        & entertainment_pattern_mask
        & t1["exclude_reason"].isna()
    )

    t1.loc[
        mask,
        "exclude_reason",
    ] = "lottery_betting"

    # ------------------------------------------
    # 결과
    # ------------------------------------------

    excluded = t1[t1["exclude_reason"].notna()].copy()

    result = t1[t1["exclude_reason"].isna()].copy()

    print("\n=== 1차 정제 결과 ===")

    print("원본:", len(t1))
    print("제외:", len(excluded))
    print("남은 후보:", len(result))

    print("\n=== 제외 이유 ===")

    print(excluded["exclude_reason"].value_counts().to_string())

    print("\n=== 남은 카테고리 ===")

    print(result["category_l1"].value_counts().to_string())

    print("\n=== 남은 category_l2 ===")

    print(result["category_l2"].value_counts().to_string())

    print("\n=== 제외 POI 예시 ===")

    print(
        excluded[
            [
                "name",
                "category_l1",
                "category_l2",
                "dong",
                "exclude_reason",
            ]
        ]
        .head(100)
        .to_string(index=False)
    )

    result.to_csv(
        OUTPUT_PATH,
        index=False,
        encoding="utf-8-sig",
    )

    print("\n저장 완료:")
    print(OUTPUT_PATH)


if __name__ == "__main__":
    main()
