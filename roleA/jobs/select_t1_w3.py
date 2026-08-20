from pathlib import Path

import numpy as np
import pandas as pd

from roleA.common.db import get_conn

ROOT_DIR = Path(__file__).resolve().parents[2]

SCREEN_PATH = ROOT_DIR / "roleA" / "data" / "review_availability_screen.csv"

OUTPUT_PATH = ROOT_DIR / "roleA" / "data" / "t1_selection_w3.csv"

T1_TARGET = 800


def main():

    # ==========================================
    # 리뷰 스크리닝 결과 불러오기
    # ==========================================

    df = pd.read_csv(
        SCREEN_PATH,
        encoding="utf-8-sig",
        low_memory=False,
    )

    # review_available이 문자열로 읽히는 경우 대응
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

    # ==========================================
    # 리뷰가 하나라도 확보 가능한 POI
    # ==========================================

    available = df[df["review_available"] == True].copy()

    print(
        "리뷰 확보 가능 POI:",
        len(available),
    )

    # ==========================================
    # 관련 리뷰 후보가 2건 이상인 POI만 사용
    # ==========================================

    strong = available[available["relevant_count"] >= 2].copy()

    print(
        "관련 리뷰 2건 이상:",
        len(strong),
    )

    # ==========================================
    # 실제 Supabase poi 테이블에 존재하는지 확인
    # ==========================================

    conn = get_conn()

    try:

        candidate_ids = strong["poi_id"].astype(str).tolist()

        with conn.cursor() as cur:

            cur.execute(
                """
                SELECT poi_id
                FROM poi
                WHERE poi_id = ANY(%s)
                """,
                (candidate_ids,),
            )

            db_ids = {str(row[0]) for row in cur.fetchall()}

    finally:
        conn.close()

    # DB에 없는 후보 확인
    missing = strong[~strong["poi_id"].astype(str).isin(db_ids)].copy()

    print(
        "DB 존재 strong 후보:",
        len(strong) - len(missing),
    )

    print(
        "DB 미존재 strong 후보:",
        len(missing),
    )

    if not missing.empty:

        print("\n=== 선정 풀에서 제외되는 DB 미존재 POI ===")

        print(
            missing[
                [
                    "poi_id",
                    "name",
                    "dong",
                    "category_l1",
                    "relevant_count",
                ]
            ].to_string(index=False)
        )

    # 실제 DB에 존재하는 후보만 남김
    strong = strong[strong["poi_id"].astype(str).isin(db_ids)].copy()

    print(
        "\n최종 T1 선정 가능 풀:",
        len(strong),
    )

    if len(strong) < T1_TARGET:
        raise ValueError(
            f"T1 {T1_TARGET}개를 뽑기에 " f"후보가 부족합니다: {len(strong)}"
        )

    # ==========================================
    # 행정동 × 카테고리별 quota 계산
    # ==========================================

    groups = (
        strong.groupby(
            [
                "dong",
                "category_l1",
            ]
        )
        .size()
        .reset_index(name="candidate_count")
    )

    groups["raw_quota"] = groups["candidate_count"] / len(strong) * T1_TARGET

    groups["quota"] = np.floor(groups["raw_quota"]).astype(int)

    # floor 때문에 부족한 수량 계산
    remainder = T1_TARGET - groups["quota"].sum()

    groups["fraction"] = groups["raw_quota"] - groups["quota"]

    # 소수점이 큰 그룹부터 1개씩 추가
    if remainder > 0:

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

    # ==========================================
    # 각 그룹에서 리뷰 근거가 강한 POI 우선
    # ==========================================

    selected_parts = []

    for _, info in groups.iterrows():

        dong = info["dong"]
        category = info["category_l1"]
        quota = int(info["quota"])

        group = strong[
            (strong["dong"] == dong) & (strong["category_l1"] == category)
        ].copy()

        # relevant_count 우선
        # 동일하면 search_total을 보조 기준으로 사용
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

    # ==========================================
    # 최종 검증
    # ==========================================

    if len(selected) != T1_TARGET:
        raise ValueError(f"최종 T1이 {T1_TARGET}개가 아닙니다: " f"{len(selected)}")

    if selected["poi_id"].astype(str).duplicated().any():
        raise ValueError("T1에 중복 poi_id가 있습니다.")

    # ==========================================
    # QC 출력
    # ==========================================

    print("\n=== W3 T1 선정 ===")

    print(
        "선정:",
        len(selected),
    )

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

    # ==========================================
    # 저장
    # ==========================================

    selected.to_csv(
        OUTPUT_PATH,
        index=False,
        encoding="utf-8-sig",
    )

    print("\n저장 완료:")

    print(OUTPUT_PATH)


if __name__ == "__main__":
    main()
