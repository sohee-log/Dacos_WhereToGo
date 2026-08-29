# 2025 서울시 추정매출 데이터에 존재하지 않는 상권은
# 임의 매핑하지 않고 segment_affinity를 생성하지 않는다.
import argparse
from itertools import product
from pathlib import Path

import pandas as pd

from roleA.common.db import get_conn

ROOT_DIR = Path(__file__).resolve().parents[2]

SALES_PATH = (
    ROOT_DIR
    / "roleA"
    / "data"
    / "commercial_area"
    / "서울시 상권분석서비스(추정매출-상권)_2025년.csv"
)

QC_PATH = ROOT_DIR / "roleA" / "data" / "segment_affinity_qc.csv"


# =========================================================
# 서울시 서비스업종 → 우리 category_l2
# =========================================================
#
# B는 segment_affinity.category_l2와
# poi.category_l2를 문자열 exact match로 조인한다.
#
# 따라서 서울시 업종명을 그대로 저장하지 않고
# 우리 DB의 category_l2로 통합한다.
#
# 대응이 불명확한 업종은 억지로 매핑하지 않는다.
# =========================================================

SERVICE_TO_CATEGORY = {
    # 음식
    "CS100001": "한식",
    "CS100002": "중식",
    "CS100003": "일식",
    "CS100004": "서양식",
    # 간이 음식
    "CS100005": "기타 간이",  # 제과점
    "CS100006": "기타 간이",  # 패스트푸드점
    "CS100007": "기타 간이",  # 치킨전문점
    "CS100008": "기타 간이",  # 분식전문점
    # 주점 / 카페
    "CS100009": "주점",
    "CS100010": "비알코올",
    # 문화·스포츠
    "CS200005": "스포츠 서비스",  # 스포츠 강습
    "CS200016": "스포츠 서비스",  # 당구장
    "CS200017": "스포츠 서비스",  # 골프연습장
    "CS200024": "스포츠 서비스",  # 스포츠클럽
    "CS200019": "유원지·오락",  # PC방
    "CS200037": "유원지·오락",  # 노래방
    # 쇼핑
    "CS300001": "종합 소매",  # 슈퍼마켓
    "CS300002": "종합 소매",  # 편의점
    "CS300024": "오락용품 소매",  # 운동/경기용품
    "CS300025": "오락용품 소매",  # 자전거 등
    "CS300026": "오락용품 소매",  # 완구
    "CS300028": "식물 소매",  # 화초
}


# =========================================================
# 세그먼트 축
# =========================================================
#
# B와 합의한 새 규약:
#
# age_band:
#   10, 20, 30, 40, 50, 60
#
# hour_band:
#   0 = 00~06
#   1 = 06~11
#   2 = 11~14
#   3 = 14~17
#   4 = 17~21
#   5 = 21~24
#
# 원본보다 임의로 세분화하지 않는다.
# =========================================================

GENDER_COLS = {
    "M": "남성_매출_금액",
    "F": "여성_매출_금액",
}

AGE_COLS = {
    10: "연령대_10_매출_금액",
    20: "연령대_20_매출_금액",
    30: "연령대_30_매출_금액",
    40: "연령대_40_매출_금액",
    50: "연령대_50_매출_금액",
    60: "연령대_60_이상_매출_금액",
}

DOW_COLS = {
    0: "주중_매출_금액",
    1: "주말_매출_금액",
}

HOUR_COLS = {
    0: "시간대_00~06_매출_금액",
    1: "시간대_06~11_매출_금액",
    2: "시간대_11~14_매출_금액",
    3: "시간대_14~17_매출_금액",
    4: "시간대_17~21_매출_금액",
    5: "시간대_21~24_매출_금액",
}


NUMERIC_COLS = [
    "당월_매출_금액",
    "당월_매출_건수",
    *GENDER_COLS.values(),
    *AGE_COLS.values(),
    *DOW_COLS.values(),
    *HOUR_COLS.values(),
]


def load_db_info(conn):
    """
    DB에서 실제로 사용 중인 상권코드와 POI category_l2를 가져온다.
    """

    with conn.cursor() as cur:

        cur.execute("""
            SELECT DISTINCT commercial_area_id
            FROM poi
            WHERE commercial_area_id IS NOT NULL
            """)

        commercial_area_ids = {str(row[0]) for row in cur.fetchall()}

        cur.execute("""
            SELECT
                commercial_area_id,
                category_l2,
                COUNT(*)
            FROM poi
            WHERE commercial_area_id IS NOT NULL
              AND category_l2 IS NOT NULL
            GROUP BY
                commercial_area_id,
                category_l2
            """)

        poi_groups = cur.fetchall()

    return commercial_area_ids, poi_groups


def load_sales():
    """
    2025년 서울시 추정매출 원본 로드.
    """

    usecols = [
        "기준_년분기_코드",
        "상권_코드",
        "상권_코드_명",
        "서비스_업종_코드",
        "서비스_업종_코드_명",
        *NUMERIC_COLS,
    ]

    df = pd.read_csv(
        SALES_PATH,
        encoding="cp949",
        dtype={
            "상권_코드": "string",
            "서비스_업종_코드": "string",
        },
        usecols=usecols,
    )

    for col in NUMERIC_COLS:
        df[col] = pd.to_numeric(
            df[col],
            errors="coerce",
        ).fillna(0.0)

    return df


def prepare_sales(
    sales,
    db_area_ids,
):
    """
    1. DB에서 실제 사용하는 상권만 유지
    2. 서울시 업종 → 우리 category_l2 매핑
    3. 2025년 각 분기를 상권×category_l2 단위로 합산
    """

    sales = sales.copy()

    sales["category_l2"] = sales["서비스_업종_코드"].map(SERVICE_TO_CATEGORY)

    # 매핑할 수 없는 서비스업종은 사용하지 않는다.
    sales = sales[sales["category_l2"].notna()].copy()

    sales["상권_코드"] = sales["상권_코드"].astype(str)

    # 2025 서울시 추정매출 데이터에 존재하지 않는 상권은
    # 임의 매핑하지 않고 segment_affinity를 생성하지 않는다.
    sales = sales[sales["상권_코드"].isin(db_area_ids)].copy()

    grouped = sales.groupby(
        [
            "상권_코드",
            "category_l2",
        ],
        as_index=False,
    )[NUMERIC_COLS].sum()

    return grouped


def safe_shares(
    row,
    mapping,
):
    """
    한 축의 매출값을 합이 1인 비율로 변환한다.

    예:
      남성 40 / 여성 60
      → M 0.4 / F 0.6
    """

    values = {key: float(row[col]) for key, col in mapping.items()}

    total = sum(values.values())

    if total <= 0:
        return None

    return {key: value / total for key, value in values.items()}


def build_affinity_rows(
    grouped,
):
    """
    서울시 원본에는

      성별 × 연령 × 요일 × 시간

    의 교차 매출이 없다.

    따라서 각 주변분포가 서로 독립이라고 가정하여
    joint segment share를 근사한다.

    estimated_segment_share
        = gender_share
        × age_share
        × dow_share
        × hour_share

    그리고 프로젝트 원래 정의:

      affinity
        = 해당 세그먼트 매출
        / 해당 상권·업종 전체 매출

    을 적용하면, 독립근사 하에서는 위 joint share가
    곧 affinity가 된다.

    이 값은 실제 교차표 관측값이 아니라
    서울시 공개 주변분포를 이용한 근사값이다.
    """

    output = []
    skipped_groups = []

    for _, row in grouped.iterrows():

        area_id = str(row["상권_코드"])

        category_l2 = row["category_l2"]

        total_sales = float(row["당월_매출_금액"])

        total_count = float(row["당월_매출_건수"])

        gender_share = safe_shares(
            row,
            GENDER_COLS,
        )

        age_share = safe_shares(
            row,
            AGE_COLS,
        )

        dow_share = safe_shares(
            row,
            DOW_COLS,
        )

        hour_share = safe_shares(
            row,
            HOUR_COLS,
        )

        # 한 축이라도 관측값이 전혀 없다면
        # 0으로 채우지 않고 해당 상권×업종을 건너뛴다.
        if (
            total_sales <= 0
            or gender_share is None
            or age_share is None
            or dow_share is None
            or hour_share is None
        ):
            skipped_groups.append(
                (
                    area_id,
                    category_l2,
                )
            )
            continue

        for (
            gender,
            age_band,
            dow_type,
            hour_band,
        ) in product(
            GENDER_COLS.keys(),
            AGE_COLS.keys(),
            DOW_COLS.keys(),
            HOUR_COLS.keys(),
        ):

            affinity = (
                gender_share[gender]
                * age_share[age_band]
                * dow_share[dow_type]
                * hour_share[hour_band]
            )

            # true joint transaction count는 공개되지 않는다.
            # 전체 거래건수 × 추정 segment share로
            # 해당 셀의 sample_weight를 근사한다.
            sample_weight = total_count * affinity

            output.append(
                {
                    "commercial_area_id": (area_id),
                    "category_l2": (category_l2),
                    "gender": gender,
                    "age_band": age_band,
                    "dow_type": dow_type,
                    "hour_band": hour_band,
                    "affinity": float(affinity),
                    "sample_weight": float(sample_weight),
                }
            )

    result = pd.DataFrame(output)

    return result, skipped_groups


def validate_result(df):
    """
    DB 적재 전 QC.
    """

    if df.empty:
        raise RuntimeError("생성된 segment_affinity가 없습니다.")

    if (
        not df["affinity"]
        .between(
            0,
            1,
            inclusive="both",
        )
        .all()
    ):
        raise RuntimeError("affinity 0~1 범위를 벗어난 값이 있습니다.")

    duplicated = df.duplicated(
        subset=[
            "commercial_area_id",
            "category_l2",
            "gender",
            "age_band",
            "dow_type",
            "hour_band",
        ]
    )

    if duplicated.any():
        raise RuntimeError("segment_affinity PK 중복이 있습니다.")

    # 독립근사된 세그먼트 비율은
    # 각 상권×업종 내에서 합이 약 1이어야 한다.
    sums = df.groupby(
        [
            "commercial_area_id",
            "category_l2",
        ]
    )["affinity"].sum()

    max_error = sums.sub(1.0).abs().max()

    if max_error > 1e-6:
        raise RuntimeError(
            "상권×업종별 affinity 합이 " f"1에서 벗어납니다. max_error={max_error}"
        )

    return max_error


def print_coverage(
    df,
    db_area_ids,
    poi_groups,
):
    """
    생성 데이터가 실제 POI를 얼마나 커버하는지 출력.
    """

    generated_pairs = set(
        zip(
            df["commercial_area_id"],
            df["category_l2"],
        )
    )

    total_pois = 0
    covered_pois = 0

    unsupported_categories = {}

    for (
        area_id,
        category_l2,
        count,
    ) in poi_groups:

        count = int(count)

        total_pois += count

        key = (
            str(area_id),
            category_l2,
        )

        if key in generated_pairs:

            covered_pois += count

        else:

            unsupported_categories[category_l2] = (
                unsupported_categories.get(
                    category_l2,
                    0,
                )
                + count
            )

    generated_areas = set(df["commercial_area_id"])

    print("\n=== segment_affinity QC ===")

    print(
        "DB commercial_area:",
        len(db_area_ids),
    )

    print(
        "affinity 생성 상권:",
        len(generated_areas),
    )

    print(
        "상권×category 그룹:",
        len(generated_pairs),
    )

    print(
        "최종 affinity 행:",
        len(df),
    )

    print(
        "affinity 최소:",
        round(
            float(df["affinity"].min()),
            8,
        ),
    )

    print(
        "affinity 최대:",
        round(
            float(df["affinity"].max()),
            8,
        ),
    )

    print(
        "POI affinity 커버:",
        f"{covered_pois}/{total_pois}",
        (f"({covered_pois / total_pois * 100:.2f}%)" if total_pois else ""),
    )

    print("\n=== affinity 미지원 category_l2 ===")

    for category, count in sorted(
        unsupported_categories.items(),
        key=lambda x: -x[1],
    ):
        print(
            category,
            count,
        )


def save_to_db(
    conn,
    df,
):
    """
    멱등 적재.

    이 job이 생성하는 상권×category 범위만 기존 행을 지우고
    다시 INSERT한다.

    다른 범위의 segment_affinity 데이터는 건드리지 않는다.
    """

    area_ids = sorted(df["commercial_area_id"].unique().tolist())

    categories = sorted(df["category_l2"].unique().tolist())

    records = list(
        df[
            [
                "commercial_area_id",
                "category_l2",
                "gender",
                "age_band",
                "dow_type",
                "hour_band",
                "affinity",
                "sample_weight",
            ]
        ].itertuples(
            index=False,
            name=None,
        )
    )

    try:

        with conn.cursor() as cur:

            # 이 build가 관리하는 영역만 초기화
            cur.execute(
                """
                DELETE FROM segment_affinity
                WHERE commercial_area_id = ANY(%s)
                  AND category_l2 = ANY(%s)
                """,
                (
                    area_ids,
                    categories,
                ),
            )

            cur.executemany(
                """
                INSERT INTO segment_affinity (
                    commercial_area_id,
                    category_l2,
                    gender,
                    age_band,
                    dow_type,
                    hour_band,
                    affinity,
                    sample_weight
                )
                VALUES (
                    %s, %s, %s, %s,
                    %s, %s, %s, %s
                )
                ON CONFLICT (
                    commercial_area_id,
                    category_l2,
                    gender,
                    age_band,
                    dow_type,
                    hour_band
                )
                DO UPDATE SET
                    affinity = EXCLUDED.affinity,
                    sample_weight = EXCLUDED.sample_weight
                """,
                records,
            )

        conn.commit()

    except Exception:

        conn.rollback()
        raise


def main():

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--apply",
        action="store_true",
        help=("실제 DB에 저장한다. " "없으면 QC만 수행한다."),
    )

    args = parser.parse_args()

    if not SALES_PATH.exists():
        raise FileNotFoundError(f"추정매출 파일 없음: {SALES_PATH}")

    conn = get_conn()

    try:

        db_area_ids, poi_groups = load_db_info(conn)

        sales = load_sales()

        print(
            "원본 행:",
            len(sales),
        )

        print(
            "분기:",
            sorted(sales["기준_년분기_코드"].astype(str).unique().tolist()),
        )

        sales_area_ids = set(sales["상권_코드"].astype(str).unique())

        matched_areas = db_area_ids & sales_area_ids

        unmatched_areas = db_area_ids - sales_area_ids

        print(
            "DB 상권:",
            len(db_area_ids),
        )

        print(
            "매출 데이터와 일치:",
            len(matched_areas),
        )

        print(
            "매출 데이터 미존재:",
            sorted(unmatched_areas),
        )

        grouped = prepare_sales(
            sales,
            db_area_ids,
        )

        print(
            "상권×category 집계:",
            len(grouped),
        )

        result, skipped_groups = build_affinity_rows(grouped)

        max_error = validate_result(result)

        print(
            "affinity 합 검증 max error:",
            max_error,
        )

        print(
            "데이터 부족으로 skip한 " "상권×category:",
            len(skipped_groups),
        )

        print_coverage(
            result,
            db_area_ids,
            poi_groups,
        )

        # 로컬 QC 산출물
        QC_PATH.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        result.to_csv(
            QC_PATH,
            index=False,
            encoding="utf-8-sig",
        )

        print(
            "\nQC 파일:",
            QC_PATH,
        )

        if not args.apply:

            print("\n[DRY RUN] " "DB에는 저장하지 않았습니다.")

            print("확인 후 --apply로 실행하세요.")

            return

        save_to_db(
            conn,
            result,
        )

        with conn.cursor() as cur:

            cur.execute("""
                SELECT COUNT(*)
                FROM segment_affinity
                """)

            db_count = cur.fetchone()[0]

        print("\nDB 저장 완료")

        print(
            "segment_affinity 전체:",
            db_count,
        )

    finally:

        conn.close()


if __name__ == "__main__":
    main()
