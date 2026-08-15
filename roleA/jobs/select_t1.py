import math
import re
from pathlib import Path

import numpy as np
import pandas as pd

ROOT_DIR = Path(__file__).resolve().parents[2]

CANDIDATE_PATH = ROOT_DIR / "roleA" / "data" / "t1_candidates_filtered.csv"

MENTION_PATH = ROOT_DIR / "roleA" / "data" / "t1_mentions.csv"

OUTPUT_PATH = ROOT_DIR / "roleA" / "data" / "t1_selection_qc.csv"

T1_TARGET = 800


def normalize_name(name):
    if pd.isna(name):
        return ""

    return re.sub(
        r"[^0-9a-z가-힣]",
        "",
        str(name).lower(),
    )


def name_specificity(name):
    """
    검색어가 짧을수록 일반 단어와 충돌할 가능성이 높으므로
    blog search total의 신뢰도를 낮춘다.

    1글자: 0.20
    2글자: 0.40
    3글자: 0.60
    4글자: 0.80
    5글자 이상: 1.00
    """

    length = len(normalize_name(name))

    if length <= 1:
        return 0.20
    elif length == 2:
        return 0.40
    elif length == 3:
        return 0.60
    elif length == 4:
        return 0.80

    return 1.00


def main():

    candidates = pd.read_csv(
        CANDIDATE_PATH,
        encoding="utf-8-sig",
        low_memory=False,
    )

    mentions = pd.read_csv(
        MENTION_PATH,
        encoding="utf-8-sig",
        low_memory=False,
    )

    # 이름 혼동 방지를 위해 실제 의미에 가까운 이름으로 변경
    mentions = mentions.rename(
        columns={
            "mention_count": "blog_search_total",
        }
    )

    df = candidates.merge(
        mentions[
            [
                "poi_id",
                "blog_search_total",
            ]
        ],
        on="poi_id",
        how="left",
    )

    # ==========================================
    # 완전히 동일한 POI 중복 제거
    # 같은 이름 + 같은 좌표인 경우에만 중복으로 판단
    # ==========================================

    df["name_norm"] = df["name"].apply(normalize_name)

    df["longitude_round"] = pd.to_numeric(df["longitude"], errors="coerce").round(6)

    df["latitude_round"] = pd.to_numeric(df["latitude"], errors="coerce").round(6)

    before_dedup = len(df)

    # 동일한 장소 레코드가 여러 개라면
    # poi_id 기준으로 하나만 결정적으로 유지
    df = (
        df.sort_values("poi_id")
        .drop_duplicates(
            subset=[
                "name_norm",
                "longitude_round",
                "latitude_round",
                "category_l1",
            ],
            keep="first",
        )
        .copy()
    )

    print(
        "완전 동일 POI 중복 제거:",
        before_dedup - len(df),
    )

    print("T1 후보:", len(df))
    print(
        "검색량 NULL:",
        df["blog_search_total"].isna().sum(),
    )

    df["blog_search_total"] = df["blog_search_total"].fillna(0)

    # ------------------------------------------
    # 극단값 완화
    # ------------------------------------------

    cap = df["blog_search_total"].quantile(0.95)

    df["blog_search_capped"] = df["blog_search_total"].clip(upper=cap)

    # log 변환
    df["blog_score"] = np.log1p(df["blog_search_capped"])

    # ------------------------------------------
    # 이름 구체성 보정
    # ------------------------------------------

    df["name_specificity"] = df["name"].apply(name_specificity)

    df["selection_score"] = df["blog_score"] * df["name_specificity"]

    # ------------------------------------------
    # 동 × 카테고리 비율을 유지하여
    # 800개 quota 계산
    # ------------------------------------------

    group_counts = (
        df.groupby(["dong", "category_l1"]).size().reset_index(name="candidate_count")
    )

    group_counts["raw_quota"] = group_counts["candidate_count"] / len(df) * T1_TARGET

    group_counts["quota"] = np.floor(group_counts["raw_quota"]).astype(int)

    # floor 때문에 부족해진 자리를
    # 소수점이 큰 그룹부터 채움
    remainder = T1_TARGET - group_counts["quota"].sum()

    group_counts["fraction"] = group_counts["raw_quota"] - group_counts["quota"]

    add_idx = (
        group_counts.sort_values(
            "fraction",
            ascending=False,
        )
        .head(remainder)
        .index
    )

    group_counts.loc[
        add_idx,
        "quota",
    ] += 1

    # ------------------------------------------
    # 그룹별 score 상위 선택
    # ------------------------------------------

    selected_parts = []

    for _, group_info in group_counts.iterrows():

        dong = group_info["dong"]
        category = group_info["category_l1"]
        quota = int(group_info["quota"])

        group = df[(df["dong"] == dong) & (df["category_l1"] == category)].copy()

        group = group.sort_values(
            [
                "selection_score",
                "blog_search_total",
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

    selected["selected_t1"] = True

    # ------------------------------------------
    # QC
    # ------------------------------------------

    print("\n=== T1 선정 결과 ===")
    print("선정:", len(selected))

    print("\n=== 카테고리 ===")
    print(selected["category_l1"].value_counts().to_string())

    print("\n=== 행정동 ===")
    print(selected["dong"].value_counts().to_string())

    print("\n=== 상위 50 ===")

    print(
        selected[
            [
                "name",
                "category_l1",
                "dong",
                "blog_search_total",
                "name_specificity",
                "selection_score",
            ]
        ]
        .sort_values(
            "selection_score",
            ascending=False,
        )
        .head(50)
        .to_string(index=False)
    )

    print("\n=== 선정된 짧은 이름 확인 ===")

    selected["name_length"] = selected["name"].apply(lambda x: len(normalize_name(x)))

    print(
        selected[selected["name_length"] <= 2][
            [
                "name",
                "category_l1",
                "dong",
                "blog_search_total",
                "selection_score",
            ]
        ]
        .sort_values(
            "selection_score",
            ascending=False,
        )
        .head(100)
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
