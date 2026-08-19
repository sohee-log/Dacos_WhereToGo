import argparse
import html
import json
import os
import re
import time
from datetime import datetime
from pathlib import Path

import requests
from dotenv import load_dotenv

from roleA.common.db import get_conn

ROOT_DIR = Path(__file__).resolve().parents[2]

OUTPUT_PATH = ROOT_DIR / "roleA" / "data" / "review_candidates_raw.jsonl"

BASE_URL = "https://naverapihub.apigw.ntruss.com/" "search/v1/blog"

QUERY_TEMPLATES = [
    '"{name}"',
    '"{name}" {dong}',
    '"{name}" 후기',
    '"{name}" 웨이팅',
]

MAX_RESULTS_PER_POI = 10


load_dotenv()

NAVER_CLIENT_ID = os.getenv("NAVER_CLIENT_ID")
NAVER_CLIENT_SECRET = os.getenv("NAVER_CLIENT_SECRET")


def clean_text(text):
    """
    네이버 검색 결과의 <b> 태그 등 HTML 표현 제거.
    """

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
    """
    장소명 비교용 정규화.
    공백/특수문자 제거 + 소문자화.
    """

    text = clean_text(text)

    return re.sub(
        r"[^0-9a-z가-힣]",
        "",
        text.lower(),
    )


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


def is_relevant_item(
    item,
    poi_name,
    dong,
):
    """
    검색 결과의 상호명/지역 일치 정도를 점수화한다.

    - 제목에 POI명: +3
    - description에 POI명: +1
    - 제목에 지역명: +2
    - description에 지역명: +1

    총점 4점 이상만 리뷰 후보로 사용한다.
    """

    poi_norm = normalize_text(poi_name)

    if not poi_norm:
        return False

    title = normalize_text(item.get("title", ""))

    description = normalize_text(item.get("description", ""))

    # ------------------------------------------
    # POI 이름 점수
    # ------------------------------------------

    score = 0

    if poi_norm in title:
        score += 3

    elif poi_norm in description:
        score += 1

    else:
        # 이름 자체가 어디에도 없으면 즉시 제외
        return False

    # ------------------------------------------
    # 지역 점수
    # ------------------------------------------

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

    # ------------------------------------------
    # 최종 판단
    # ------------------------------------------

    return score >= 4


def search_blog(query):
    """
    네이버 블로그 검색 API 1회 호출.
    """

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

    # 일시적 네트워크/API 오류 대응
    for attempt in range(3):

        try:

            response = requests.get(
                BASE_URL,
                headers=headers,
                params=params,
                timeout=30,
            )

            response.raise_for_status()

            return response.json()

        except requests.RequestException:

            if attempt == 2:
                raise

            wait_seconds = 2**attempt

            print(f"  API 오류 - " f"{wait_seconds}초 후 재시도")

            time.sleep(wait_seconds)


def load_completed_ids():
    """
    이미 수집 완료한 POI ID를 읽어서
    중간에 끊겨도 이어서 실행할 수 있게 한다.
    """

    if not OUTPUT_PATH.exists():
        return set()

    completed = set()

    with open(
        OUTPUT_PATH,
        "r",
        encoding="utf-8",
    ) as f:

        for line in f:

            line = line.strip()

            if not line:
                continue

            try:
                row = json.loads(line)

                completed.add(str(row["poi_id"]))

            except (
                json.JSONDecodeError,
                KeyError,
            ):
                continue

    return completed


def collect_one_poi(
    poi_id,
    name,
    dong,
):
    """
    한 POI에 대해 4개 쿼리 실행 후,
    검색 결과의 title/description에 실제 POI명이
    포함된 결과만 유지한다.

    이후 URL 기준 중복 제거 → 최대 10개 유지.
    """

    merged = {}

    query_totals = {}

    mention_count = 0

    total_items = 0
    relevant_items = 0

    for query_index, template in enumerate(QUERY_TEMPLATES):

        query = template.format(
            name=name,
            dong=dong,
        )

        data = search_blog(query)

        total = int(data.get("total", 0))

        query_totals[query] = total

        # 첫 번째 "{상호명}" 검색의 total
        if query_index == 0:
            mention_count = total

        items = data.get(
            "items",
            [],
        )

        total_items += len(items)

        for item in items:

            # ==================================
            # 실제 POI 이름이 검색 결과에
            # 등장하는 경우만 사용
            # ==================================

            if not is_relevant_item(
                item,
                name,
                dong,
            ):
                continue

            relevant_items += 1

            link = str(
                item.get(
                    "link",
                    "",
                )
            ).strip()

            if not link:
                continue

            # 동일 URL 중복 제거
            if link in merged:
                continue

            merged[link] = {
                "title": clean_text(
                    item.get(
                        "title",
                        "",
                    )
                ),
                "link": link,
                "description": clean_text(
                    item.get(
                        "description",
                        "",
                    )
                ),
                "bloggername": clean_text(
                    item.get(
                        "bloggername",
                        "",
                    )
                ),
                "bloggerlink": str(
                    item.get(
                        "bloggerlink",
                        "",
                    )
                ).strip(),
                "postdate": str(
                    item.get(
                        "postdate",
                        "",
                    )
                ).strip(),
                "matched_query": query,
            }

        time.sleep(0.05)

    results = list(merged.values())[:MAX_RESULTS_PER_POI]

    # QC용
    print(f"  검색 결과 {total_items}건 중 " f"관련 후보 {relevant_items}건")

    return {
        "poi_id": str(poi_id),
        "name": name,
        "dong": dong,
        "mention_count": mention_count,
        "query_totals": query_totals,
        "result_count": len(results),
        "items": results,
        "collected_at": (datetime.now().astimezone().isoformat()),
    }


def update_mention_count(
    conn,
    poi_id,
    mention_count,
):
    """
    검색 첫 번째 쿼리의 total을
    poi.mention_count에 저장.
    """

    with conn.cursor() as cur:

        cur.execute(
            """
            UPDATE poi
            SET
                mention_count = %s,
                updated_at = NOW()
            WHERE poi_id = %s
            """,
            (
                int(mention_count),
                str(poi_id),
            ),
        )

    conn.commit()


def main():

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--limit",
        type=int,
        default=None,
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
    )

    args = parser.parse_args()

    if not NAVER_CLIENT_ID:
        raise RuntimeError("NAVER_CLIENT_ID가 " ".env에 없습니다.")

    if not NAVER_CLIENT_SECRET:
        raise RuntimeError("NAVER_CLIENT_SECRET가 " ".env에 없습니다.")

    # ==========================================
    # Tier 1 POI 조회
    # ==========================================

    conn = get_conn()

    try:

        with conn.cursor() as cur:

            cur.execute("""
                SELECT
                    poi_id,
                    name,
                    dong
                FROM poi
                WHERE tier = 1
                ORDER BY poi_id
                """)

            pois = cur.fetchall()

        print(
            "Tier 1 전체:",
            len(pois),
        )

        completed_ids = load_completed_ids()

        print(
            "이미 수집 완료:",
            len(completed_ids),
        )

        pending = [row for row in pois if str(row[0]) not in completed_ids]

        if args.limit is not None:
            pending = pending[: args.limit]

        print(
            "이번 실행 대상:",
            len(pending),
        )

        # ======================================
        # 수집
        # ======================================

        collected_poi = 0

        poi_with_reviews = 0

        for i, (
            poi_id,
            name,
            dong,
        ) in enumerate(
            pending,
            start=1,
        ):

            try:

                result = collect_one_poi(
                    poi_id,
                    name,
                    dong,
                )

                print(
                    f"[{i}/{len(pending)}] "
                    f"{name} / {dong} "
                    f"→ {result['result_count']}건 "
                    f"(mention="
                    f"{result['mention_count']})"
                )

                if result["result_count"] > 0:
                    poi_with_reviews += 1

                collected_poi += 1

                # dry-run에서는
                # 파일/DB 수정하지 않음
                if args.dry_run:

                    print("  [DRY RUN] " "저장 생략")

                    # 테스트 결과 일부 확인
                    for item in result["items"][:3]:
                        print(
                            "   -",
                            item["title"],
                        )

                    continue

                # ==================================
                # 로컬 raw 후보 저장
                # ==================================

                OUTPUT_PATH.parent.mkdir(
                    parents=True,
                    exist_ok=True,
                )

                with open(
                    OUTPUT_PATH,
                    "a",
                    encoding="utf-8",
                ) as f:

                    f.write(
                        json.dumps(
                            result,
                            ensure_ascii=False,
                        )
                        + "\n"
                    )

                # ==================================
                # DB mention_count 갱신
                # ==================================

                update_mention_count(
                    conn,
                    poi_id,
                    result["mention_count"],
                )

            except Exception as e:

                print(f"[ERROR] " f"{poi_id} " f"{name}: {e}")

        print("\n=== 이번 실행 결과 ===")

        print(
            "처리 POI:",
            collected_poi,
        )

        print(
            "리뷰 후보 1건 이상:",
            poi_with_reviews,
        )

        if collected_poi:

            print("확보율:", f"{poi_with_reviews / collected_poi * 100:.2f}%")

    finally:

        conn.close()


if __name__ == "__main__":
    main()
