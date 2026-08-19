from pathlib import Path

import numpy as np
import pandas as pd

ROOT_DIR = Path(__file__).resolve().parents[2]

SCREEN_PATH = ROOT_DIR / "roleA" / "data" / "review_availability_screen.csv"

OUTPUT_PATH = ROOT_DIR / "roleA" / "data" / "t1_selection_w3.csv"

T1_TARGET = 800


def main():

    df = pd.read_csv(
        SCREEN_PATH,
        encoding="utf-8-sig",
        low_memory=False,
    )

    # bool 문자열 대응
    if df["review_available"].dtype == object:
        df["review_available"] = (
            df["review_available"]
            .astype(str)
            .str.lower()
            .map(
                {
                    "true": True,
                    "false": False,
                }
            )
        )

    # 리뷰 확보 가능한 POI만
    available = df[df["review_available"] == True].copy()

    print("리뷰 확보 가능 POI:", len(available))

    # ==========================================
    # W3 T1 최소 리뷰 근거
    # ==========================================
    # 관련 리뷰 후보가 1건뿐인 POI는 제외하고,
    # 2건 이상 확인된 POI만 T1 선정 풀로 사용한다.

    strong = available[available["relevant_count"] >= 2].copy()

    print(
        "관련 리뷰 2건 이상:",
        len(strong),
    )

    # ------------------------------------------
    # 동 × 카테고리 quota
    # ------------------------------------------

    groups = (
        strong.groupby(["dong", "category_l1"])
        .size()
        .reset_index(name="candidate_count")
    )

    groups["raw_quota"] = groups["candidate_count"] / len(strong) * T1_TARGET

    groups["quota"] = np.floor(groups["raw_quota"]).astype(int)

    # floor로 부족한 개수 채우기
    remainder = T1_TARGET - groups["quota"].sum()

    groups["fraction"] = groups["raw_quota"] - groups["quota"]

    add_idx = (
        groups.sort_values(
            "fraction",
            ascending=False,
        )
        .head(remainder)
        .index
    )

    groups.loc[
        add_idx,
        "quota",
    ] += 1

    # ------------------------------------------
    # 각 그룹에서 리뷰 근거가 많은 POI 우선
    # ------------------------------------------

    selected_parts = []

    for _, info in groups.iterrows():

        dong = info["dong"]
        category = info["category_l1"]
        quota = int(info["quota"])

        group = strong[
            (strong["dong"] == dong) & (strong["category_l1"] == category)
        ].copy()

        # relevant_count 우선
        # 같은 경우 search_total은 보조 tie-breaker
        group = group.sort_values(
            [
                "relevant_count",
                "search_total",
                "name",
            ],
            ascending=[
                False,
                False,
                True,
            ],
        )

        selected_parts.append(group.head(quota))

    selected = pd.concat(
        selected_parts,
        ignore_index=True,
    )

    # ------------------------------------------
    # QC
    # ------------------------------------------

    print("\n=== W3 T1 선정 ===")
    print("선정:", len(selected))

    print("\n=== 카테고리 ===")
    print(selected["category_l1"].value_counts().to_string())

    print("\n=== 행정동 ===")
    print(selected["dong"].value_counts().to_string())

    print("\n=== relevant_count ===")
    print(selected["relevant_count"].describe().to_string())

    print(
        "\nrelevant_count = 1:",
        (selected["relevant_count"] == 1).sum(),
    )

    print(
        "relevant_count >= 2:",
        (selected["relevant_count"] >= 2).sum(),
    )

    print("\n=== 가장 약한 후보 50 ===")

    print(
        selected[
            [
                "poi_id",
                "name",
                "dong",
                "category_l1",
                "relevant_count",
                "search_total",
            ]
        ]
        .sort_values(
            [
                "relevant_count",
                "search_total",
            ],
            ascending=[
                True,
                True,
            ],
        )
        .head(50)
        .to_string(index=False)
    )

    selected.to_csv(
        OUTPUT_PATH,
        index=False,
        encoding="utf-8-sig",
    )

    print("\n저장 완료:")
    print(OUTPUT_PATH)


if __name__ == "__main__":
    main()
