# 상권 폴리곤 직접 매핑 실패 시 nearest 보정 기준.
# W2 QC 결과:
# - 50m: 94.96%
# - 60m: 95.75%
# 프로젝트 목표 매핑률 95%를 충족하는 최소 임계값으로 60m 선택.

from pathlib import Path

import pandas as pd

ROOT_DIR = Path(__file__).resolve().parents[2]

POI_PATH = ROOT_DIR / "roleA" / "data" / "yongsan_poi_candidates.csv"
QC_PATH = ROOT_DIR / "roleA" / "data" / "commercial_area_unmatched_qc.csv"
OUTPUT_PATH = ROOT_DIR / "roleA" / "data" / "yongsan_poi_candidates_final.csv"

# 상권 폴리곤 직접 매핑 실패 시 nearest 보정 기준.
# W2 QC 결과:
# - 50m: 94.96%
# - 60m: 95.75%
# 프로젝트 목표 매핑률 95%를 충족하는 최소 임계값으로 60m 선택.

NEAREST_THRESHOLD_M = 60


def main():

    poi = pd.read_csv(
        POI_PATH,
        encoding="utf-8-sig",
        low_memory=False,
    )

    qc = pd.read_csv(
        QC_PATH,
        encoding="utf-8-sig",
        low_memory=False,
    )

    print("추천대상 POI:", len(poi))

    # 상권 polygon에 직접 매핑되지 않은 POI 중
    # 가장 가까운 상권이 60m 이내인 POI만 보정 후보로 선택
    correction = qc[qc["distance_m"] <= NEAREST_THRESHOLD_M][
        [
            "상가업소번호",
            "nearest_area_id",
            "nearest_area_name",
            "nearest_area_type",
            "distance_m",
        ]
    ].copy()

    print(
        f"{NEAREST_THRESHOLD_M}m 이내 보정 대상:",
        len(correction),
    )

    # 원본 POI와 합치기
    result = poi.merge(
        correction,
        on="상가업소번호",
        how="left",
    )

    # 직접 polygon 매핑에 실패한 POI에 한해서
    # 60m 이내 nearest 상권의 ID/이름으로 commercial_area를 보정
    mask = result["commercial_area_id"].isna() & result["nearest_area_id"].notna()

    result.loc[
        mask,
        "commercial_area_id",
    ] = result.loc[
        mask,
        "nearest_area_id",
    ]

    result.loc[
        mask,
        "commercial_area_name",
    ] = result.loc[
        mask,
        "nearest_area_name",
    ]

    # 매핑 방식 기록
    result["commercial_area_match_method"] = "polygon"

    result.loc[
        mask,
        "commercial_area_match_method",
    ] = "nearest_60m"

    result.loc[
        result["commercial_area_id"].isna(),
        "commercial_area_match_method",
    ] = "unmapped"

    # ==========================================
    # QC
    # ==========================================

    total = len(result)

    mapped = result["commercial_area_id"].notna().sum()

    unmapped = total - mapped

    print("\n=== 최종 상권 매핑 결과 ===")
    print("전체:", total)
    print("매핑 성공:", mapped)
    print("매핑 실패:", unmapped)
    print("매핑률:", f"{mapped / total * 100:.2f}%")

    print("\n=== 매핑 방법 ===")
    print(result["commercial_area_match_method"].value_counts().to_string())

    # 중복 확인
    duplicates = result["상가업소번호"].duplicated().sum()

    print("\nPOI ID 중복:", duplicates)

    # dong / zone QC
    print("dong NULL:", result["dong"].isna().sum())

    print("zone NULL:", result["zone"].isna().sum())

    # 저장
    result.to_csv(
        OUTPUT_PATH,
        index=False,
        encoding="utf-8-sig",
    )

    print("\n저장 완료:")
    print(OUTPUT_PATH)


if __name__ == "__main__":
    main()
