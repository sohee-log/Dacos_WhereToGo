from pathlib import Path
import json
import random

import pandas as pd

DATA_PATH = Path("roleA/data/store_info.csv")
OUTPUT_PATH = Path("seeds/poi_seed.json")
REVIEW_OUTPUT_PATH = Path("seeds/review_seed.json")

SEED = 42

ZONE_DONGS = {
    "itaewon": [
        "이태원1동",
        "이태원2동",
        "한남동",
        "보광동",
    ],
    "yongsan_stn": [
        "한강로동",
        "남영동",
    ],
    "huam": [
        "후암동",
        "용산2가동",
    ],
    "ichon": [
        "이촌1동",
        "이촌2동",
        "서빙고동",
    ],
    "cheongpa": [
        "청파동",
        "원효로1동",
        "원효로2동",
        "효창동",
        "용문동",
    ],
}

PURPOSE_TAGS = [
    "데이트",
    "친구모임",
    "혼자",
    "가족",
    "작업",
    "회식",
]

ATMOSPHERE_TAGS = [
    "조용한",
    "활기찬",
    "감성적인",
    "트렌디한",
    "로컬한",
    "넓은",
    "뷰가좋은",
    "아늑한",
    "이국적인",
    "가성비",
]


def load_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"파일을 찾을 수 없습니다: {path}")

    try:
        return pd.read_csv(
            path,
            encoding="utf-8-sig",
            low_memory=False,
        )
    except UnicodeDecodeError:
        return pd.read_csv(
            path,
            encoding="cp949",
            low_memory=False,
        )


def map_category_l1(row):
    large = row["상권업종대분류명"]
    middle = row["상권업종중분류명"]
    small = row["상권업종소분류명"]

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


def map_zone(dong):
    for zone, dongs in ZONE_DONGS.items():
        if dong in dongs:
            return zone

    return None


def make_mock_attributes(index):
    """
    W1 seed 테스트용 속성.
    실제 리뷰/LLM 분석 결과가 아님.
    """

    rng = random.Random(SEED + index)

    purpose_count = rng.randint(1, 3)
    atmosphere_count = rng.randint(1, 3)

    return {
        "business_hours": None,
        # REAL 0~1
        "outdoor_exposure": round(
            rng.uniform(0.0, 1.0),
            2,
        ),
        # INT
        "group_capacity": rng.choice([2, 4, 6, 8, 10]),
        # SMALLINT 1~5
        "noise_level": rng.randint(1, 5),
        "purpose_tags": rng.sample(
            PURPOSE_TAGS,
            purpose_count,
        ),
        "atmosphere_tags": rng.sample(
            ATMOSPHERE_TAGS,
            atmosphere_count,
        ),
        # SMALLINT 1~4
        "price_band": rng.randint(1, 4),
        "sentiment_score": round(
            rng.uniform(0.55, 0.95),
            2,
        ),
        "mention_count": rng.randint(5, 200),
        # review_seed와 나중에 맞출 예정
        "review_count": 2,
        "attr_confidence": round(
            rng.uniform(0.40, 0.90),
            2,
        ),
        "hotspot_code": None,
        # T1 seed
        "tier": 1,
    }


def main():
    df = load_csv(DATA_PATH)

    # 용산구만 추출
    yongsan = df[df["시군구명"] == "용산구"].copy()

    # 추천 카테고리 매핑
    yongsan["category_l1"] = yongsan.apply(
        map_category_l1,
        axis=1,
    )

    # 프로젝트 zone 매핑
    yongsan["zone"] = yongsan["행정동명"].apply(map_zone)

    # 추천 대상 + zone이 있는 POI만 사용
    candidates = yongsan[
        yongsan["category_l1"].notna() & yongsan["zone"].notna()
    ].copy()

    print("=" * 60)
    print("Seed 후보 데이터")
    print("=" * 60)

    print(f"추천 후보 수: " f"{len(candidates):,}")

    print("\n[zone별 후보 수]")
    print(candidates["zone"].value_counts().to_string())

    # zone별 20개씩 추출
    sampled_frames = []

    for zone in ZONE_DONGS:
        zone_df = candidates[candidates["zone"] == zone]

        if len(zone_df) < 20:
            raise ValueError(
                f"{zone}의 후보가 20개 미만입니다. " f"현재 {len(zone_df)}개"
            )

        zone_sample = zone_df.sample(
            n=20,
            random_state=SEED,
        )

        sampled_frames.append(zone_sample)

    seed_df = pd.concat(
        sampled_frames,
        ignore_index=True,
    )

    records = []

    for index, row in seed_df.iterrows():
        record = {
            "poi_id": str(row["상가업소번호"]),
            "name": row["상호명"],
            "category_l1": row["category_l1"],
            "category_l2": row["상권업종소분류명"],
            "longitude": float(row["경도"]),
            "latitude": float(row["위도"]),
            "lat": float(row["위도"]),
            "lng": float(row["경도"]),
            "dong": row["행정동명"],
            "zone": row["zone"],
            "commercial_area_id": None,
        }

        record.update(make_mock_attributes(index))

        records.append(record)

    OUTPUT_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with open(
        OUTPUT_PATH,
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(
            records,
            f,
            ensure_ascii=False,
            indent=2,
        )

    print("\n" + "=" * 60)
    print("POI Seed 생성 완료")
    print("=" * 60)

    print(f"저장 경로: {OUTPUT_PATH}")

    print(f"전체 건수: {len(records)}")

    print("\n[zone별 건수]")
    print(seed_df["zone"].value_counts().to_string())

    print("\n[category_l1별 건수]")
    print(seed_df["category_l1"].value_counts().to_string())

    outdoor_values = [record["outdoor_exposure"] for record in records]

    print("\n[outdoor_exposure]")
    print(f"0.2 이하: " f"{sum(v <= 0.2 for v in outdoor_values)}")
    print(f"0.8 이상: " f"{sum(v >= 0.8 for v in outdoor_values)}")

    hotspot_null_count = sum(record["hotspot_code"] is None for record in records)

    print("\nhotspot_code NULL:" f" {hotspot_null_count}")

    review_templates = [
        "분위기가 편안하고 대화하기 좋아요. 재방문 의사가 있습니다.",
        "위치가 찾기 쉽고 공간이 깔끔해서 이용하기 편했습니다.",
        "전체적으로 만족스러웠고 주변과 함께 들르기 좋은 곳이었습니다.",
    ]

    review_records = []

    for index, record in enumerate(records):
        rng = random.Random(SEED + 1000 + index)

        # POI당 2개의 테스트용 리뷰 청크 생성
        for review_idx in range(2):
            review_records.append(
                {
                    "poi_id": record["poi_id"],
                    "source": "naver_blog",
                    "text": review_templates[
                        (index + review_idx) % len(review_templates)
                    ],
                    "embedding": None,
                    "is_sponsored": rng.random() < 0.1,
                    "written_at": "2026-08-01",
                }
            )

    with open(
        REVIEW_OUTPUT_PATH,
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(
            review_records,
            f,
            ensure_ascii=False,
            indent=2,
        )

    print("\n" + "=" * 60)
    print("Review Seed 생성 완료")
    print("=" * 60)

    print(f"저장 경로: {REVIEW_OUTPUT_PATH}")
    print(f"전체 리뷰 청크 수: {len(review_records)}")


if __name__ == "__main__":
    main()
