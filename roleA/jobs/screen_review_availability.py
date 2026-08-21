import argparse
import html
import json
import os
import re
import time
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[2]

CANDIDATE_PATH = ROOT_DIR / "roleA" / "data" / "t1_candidates_filtered.csv"

OUTPUT_PATH = ROOT_DIR / "roleA" / "data" / "review_availability_screen.csv"

BASE_URL = "https://naverapihub.apigw.ntruss.com/" "search/v1/blog"


LOCATION_TERMS = {
    "한남동": [
        "한남동",
        "한남",
        "한강진",
        "이태원",
        "용산",
    ],
    "이태원1동": [
        "이태원",
        "녹사평",
        "용산",
    ],
    "이태원2동": [
        "이태원",
        "경리단길",
        "녹사평",
        "용산",
    ],
    "한강로동": [
        "한강로",
        "삼각지",
        "신용산",
        "용산역",
        "용리단길",
        "용산",
    ],
    "후암동": [
        "후암",
        "서울역",
        "용산",
    ],
}


load_dotenv()

NAVER_CLIENT_ID = os.getenv("NAVER_CLIENT_ID")

NAVER_CLIENT_SECRET = os.getenv("NAVER_CLIENT_SECRET")


def clean_text(text):

    if not text:
        return ""

    text = html.unescape(str(text))

    text = re.sub(
        r"<[^>]+>",
        "",
        text,
    )

    text = re.sub(
        r"\s+",
        " ",
        text,
    )

    return text.strip()


def normalize_text(text):

    return re.sub(
        r"[^0-9a-z가-힣]",
        "",
        clean_text(text).lower(),
    )


def is_relevant_item(
    item,
    poi_name,
    dong,
):

    poi_norm = normalize_text(poi_name)

    title = normalize_text(item.get("title", ""))

    description = normalize_text(item.get("description", ""))

    if not poi_norm:
        return False

    score = 0

    if poi_norm in title:
        score += 3

    elif poi_norm in description:
        score += 1

    else:
        return False

    location_terms = LOCATION_TERMS.get(
        dong,
        [dong, "용산"],
    )

    title_location = False
    description_location = False

    for term in location_terms:

        term_norm = normalize_text(term)

        if term_norm in title:
            title_location = True

        if term_norm in description:
            description_location = True

    if title_location:
        score += 2

    elif description_location:
        score += 1

    return score >= 4


def search_blog(
    name,
    dong,
):

    # 스크리닝용 1개 검색어
    query = f'"{name}" {dong}'

    headers = {
        "X-NCP-APIGW-API-KEY-ID": NAVER_CLIENT_ID,
        "X-NCP-APIGW-API-KEY": NAVER_CLIENT_SECRET,
    }

    params = {
        "query": query,
        "display": 20,
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

            return (
                query,
                response.json(),
            )

        except requests.RequestException:

            if attempt == 2:
                raise

            time.sleep(2**attempt)


def main():

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--limit",
        type=int,
        default=None,
    )

    args = parser.parse_args()

    df = pd.read_csv(
        CANDIDATE_PATH,
        encoding="utf-8-sig",
        low_memory=False,
    )

    # ------------------------------------------
    # 기존 스크리닝 결과
    # ------------------------------------------

    if OUTPUT_PATH.exists():

        old = pd.read_csv(
            OUTPUT_PATH,
            encoding="utf-8-sig",
        )

        completed_ids = set(old["poi_id"].astype(str))

        print(
            "이미 스크리닝:",
            len(completed_ids),
        )

    else:

        old = pd.DataFrame()

        completed_ids = set()

    pending = df[~df["poi_id"].astype(str).isin(completed_ids)].copy()

    if args.limit is not None:
        pending = pending.head(args.limit)

    print(
        "전체 후보:",
        len(df),
    )

    print(
        "이번 실행:",
        len(pending),
    )

    rows = []

    for i, row in enumerate(
        pending.itertuples(index=False),
        start=1,
    ):

        try:

            query, data = search_blog(
                row.name,
                row.dong,
            )

            items = data.get(
                "items",
                [],
            )

            relevant = [
                item
                for item in items
                if is_relevant_item(
                    item,
                    row.name,
                    row.dong,
                )
            ]

            result = {
                "poi_id": row.poi_id,
                "name": row.name,
                "dong": row.dong,
                "zone": row.zone,
                "category_l1": row.category_l1,
                "query": query,
                "search_total": int(
                    data.get(
                        "total",
                        0,
                    )
                ),
                "relevant_count": len(relevant),
                "review_available": len(relevant) > 0,
            }

            rows.append(result)

            print(
                f"[{i}/{len(pending)}] " f"{row.name} " f"→ 관련 " f"{len(relevant)}건"
            )

        except Exception as e:

            print(f"[ERROR] " f"{row.poi_id} " f"{row.name}: {e}")

        time.sleep(0.05)

        # 50건마다 저장
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

    # 마지막 잔여 저장
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

    # ------------------------------------------
    # QC
    # ------------------------------------------

    result = pd.read_csv(
        OUTPUT_PATH,
        encoding="utf-8-sig",
    )

    available = result["review_available"].sum()

    print("\n=== 리뷰 존재 스크리닝 ===")

    print(
        "스크리닝 완료:",
        len(result),
    )

    print(
        "리뷰 후보 있음:",
        available,
    )

    print("확보 가능률:", f"{available / len(result) * 100:.2f}%")


if __name__ == "__main__":
    main()
