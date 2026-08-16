import os
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[2]

OUTPUT_PATH = ROOT_DIR / "roleA" / "data" / "tourapi_yongsan_raw.csv"

load_dotenv()

SERVICE_KEY = os.getenv("PUBLIC_DATA_API_KEY")

BASE_URL = "https://apis.data.go.kr/" "B551011/KorService2/locationBasedList2"

# 용산구 중심부 정도
MAP_X = 126.981
MAP_Y = 37.535

# 용산구 전체를 넉넉하게 포함하도록 조회 후
# 주소로 다시 용산구만 필터링
RADIUS_M = 10000

CONTENT_TYPES = {
    "12": "관광지",
    "14": "문화시설",
}


def fetch_content_type(content_type_id, content_type_name):
    rows = []

    page = 1

    while True:
        params = {
            "serviceKey": SERVICE_KEY,
            "MobileOS": "ETC",
            "MobileApp": "DacosWhereToGo",
            "_type": "json",
            "mapX": MAP_X,
            "mapY": MAP_Y,
            "radius": RADIUS_M,
            "contentTypeId": content_type_id,
            "arrange": "E",
            "numOfRows": 100,
            "pageNo": page,
        }

        response = requests.get(
            BASE_URL,
            params=params,
            timeout=30,
        )

        response.raise_for_status()

        data = response.json()

        header = data["response"]["header"]

        if header["resultCode"] != "0000":
            raise RuntimeError(
                f"TourAPI 오류: " f"{header['resultCode']} " f"{header['resultMsg']}"
            )

        body = data["response"]["body"]

        items = body.get("items", {})

        if not items:
            break

        page_rows = items.get("item", [])

        if isinstance(page_rows, dict):
            page_rows = [page_rows]

        for row in page_rows:
            row["content_type_name"] = content_type_name

        rows.extend(page_rows)

        total_count = int(body.get("totalCount", 0))

        print(f"{content_type_name}: " f"{len(rows)} / {total_count}")

        if len(rows) >= total_count:
            break

        page += 1

    return rows


def main():
    if not SERVICE_KEY:
        raise RuntimeError("PUBLIC_DATA_API_KEY가 .env에 없습니다.")

    all_rows = []

    for content_type_id, name in CONTENT_TYPES.items():
        rows = fetch_content_type(
            content_type_id,
            name,
        )

        all_rows.extend(rows)

    df = pd.DataFrame(all_rows)

    print("\nAPI 전체 수집:", len(df))

    # 주소가 명확히 용산구인 데이터만 남김
    yongsan = df[df["addr1"].fillna("").str.contains("용산구")].copy()

    print("용산구 필터 후:", len(yongsan))

    if len(yongsan) > 0:
        print("\n=== 유형별 ===")
        print(yongsan["content_type_name"].value_counts().to_string())

        print("\n=== 일부 데이터 ===")

        cols = [
            "contentid",
            "title",
            "content_type_name",
            "addr1",
            "mapx",
            "mapy",
        ]

        print(yongsan[cols].head(30).to_string(index=False))

    print("\n=== TourAPI 카테고리 확인 ===")

    category_cols = [
        "contentid",
        "title",
        "content_type_name",
        "cat1",
        "cat2",
        "cat3",
    ]

    category_cols = [c for c in category_cols if c in yongsan.columns]

    print(
        yongsan[category_cols]
        .sort_values(["content_type_name", "title"])
        .to_string(index=False)
    )

    print("\n=== cat1/cat2/cat3 조합 ===")

    available_cat_cols = [c for c in ["cat1", "cat2", "cat3"] if c in yongsan.columns]

    if available_cat_cols:
        print(yongsan[available_cat_cols].value_counts(dropna=False).to_string())
    yongsan.to_csv(
        OUTPUT_PATH,
        index=False,
        encoding="utf-8-sig",
    )

    print("\n저장 완료:")
    print(OUTPUT_PATH)


if __name__ == "__main__":
    main()
