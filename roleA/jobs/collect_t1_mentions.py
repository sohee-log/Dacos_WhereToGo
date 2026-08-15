import argparse
import os
import time
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[2]

POI_PATH = ROOT_DIR / "roleA" / "data" / "t1_candidates_filtered.csv"
OUTPUT_PATH = ROOT_DIR / "roleA" / "data" / "t1_mentions.csv"


T1_DONGS = [
    "이태원1동",
    "이태원2동",
    "한남동",
    "한강로동",
    "후암동",
]


BASE_URL = "https://naverapihub.apigw.ntruss.com/" "search/v1/blog"


load_dotenv()

NAVER_CLIENT_ID = os.getenv("NAVER_CLIENT_ID")
NAVER_CLIENT_SECRET = os.getenv("NAVER_CLIENT_SECRET")


def search_blog_total(name, dong):
    query = f"{name} 용산 {dong}"

    headers = {
        "X-NCP-APIGW-API-KEY-ID": NAVER_CLIENT_ID,
        "X-NCP-APIGW-API-KEY": NAVER_CLIENT_SECRET,
    }

    params = {
        "query": query,
        "display": 1,
        "start": 1,
        "sort": "sim",
        "format": "json",
    }

    for attempt in range(3):
        try:
            response = requests.get(
                BASE_URL,
                headers=headers,
                params=params,
                timeout=30,
            )

            response.raise_for_status()
            break

        except requests.RequestException:
            if attempt == 2:
                raise

            time.sleep(2**attempt)

    response.raise_for_status()

    data = response.json()

    return {
        "query": query,
        "mention_count": int(data.get("total", 0)),
    }


def main():

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--limit",
        type=int,
        default=None,
    )

    args = parser.parse_args()

    if not NAVER_CLIENT_ID:
        raise RuntimeError("NAVER_CLIENT_ID가 .env에 없습니다.")

    if not NAVER_CLIENT_SECRET:
        raise RuntimeError("NAVER_CLIENT_SECRET가 .env에 없습니다.")

    poi = pd.read_csv(
        POI_PATH,
        encoding="utf-8-sig",
        low_memory=False,
    )

    t1 = poi.copy()

    print("T1 후보:", len(t1))

    # ==========================================
    # 기존 결과가 있으면 이어서 실행
    # ==========================================

    if OUTPUT_PATH.exists():

        existing = pd.read_csv(
            OUTPUT_PATH,
            encoding="utf-8-sig",
        )

        completed_ids = set(existing["poi_id"].astype(str))

        print(
            "이미 수집 완료:",
            len(completed_ids),
        )

    else:

        existing = pd.DataFrame()

        completed_ids = set()

    pending = t1[~t1["poi_id"].astype(str).isin(completed_ids)].copy()

    if args.limit is not None:
        pending = pending.head(args.limit)

    print(
        "이번 실행 대상:",
        len(pending),
    )

    # ==========================================
    # 네이버 블로그 언급량 수집
    # ==========================================

    rows = []

    for i, row in enumerate(
        pending.itertuples(index=False),
        start=1,
    ):

        try:

            result = search_blog_total(
                row.name,
                row.dong,
            )

            output_row = {
                "poi_id": row.poi_id,
                "name": row.name,
                "category_l1": row.category_l1,
                "dong": row.dong,
                "zone": row.zone,
                "query": result["query"],
                "mention_count": (result["mention_count"]),
            }

            rows.append(output_row)

            print(
                f"[{i}/{len(pending)}] "
                f"{row.name} / "
                f"{row.dong} → "
                f"{result['mention_count']}"
            )

        except Exception as e:

            print(f"[ERROR] " f"{row.name}: {e}")

        # 너무 빠르게 연속 호출하지 않도록
        # 짧은 간격
        time.sleep(0.05)

        # 50건마다 중간 저장
        if len(rows) >= 50:

            chunk = pd.DataFrame(rows)

            if OUTPUT_PATH.exists():

                old = pd.read_csv(
                    OUTPUT_PATH,
                    encoding="utf-8-sig",
                )

                chunk = pd.concat(
                    [old, chunk],
                    ignore_index=True,
                )

                chunk = chunk.drop_duplicates(
                    subset=["poi_id"],
                    keep="last",
                )

            chunk.to_csv(
                OUTPUT_PATH,
                index=False,
                encoding="utf-8-sig",
            )

            rows = []

    # ==========================================
    # 마지막 남은 결과 저장
    # ==========================================

    if rows:

        chunk = pd.DataFrame(rows)

        if OUTPUT_PATH.exists():

            old = pd.read_csv(
                OUTPUT_PATH,
                encoding="utf-8-sig",
            )

            chunk = pd.concat(
                [old, chunk],
                ignore_index=True,
            )

            chunk = chunk.drop_duplicates(
                subset=["poi_id"],
                keep="last",
            )

        chunk.to_csv(
            OUTPUT_PATH,
            index=False,
            encoding="utf-8-sig",
        )

    print("\n수집 완료")

    if OUTPUT_PATH.exists():

        result = pd.read_csv(
            OUTPUT_PATH,
            encoding="utf-8-sig",
        )

        print(
            "현재 저장된 POI:",
            len(result),
        )

        print("\n=== mention_count 요약 ===")

        print(result["mention_count"].describe().to_string())


if __name__ == "__main__":
    main()
