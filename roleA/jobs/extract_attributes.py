import argparse
import html
import json
import os
import re
import time
from pathlib import Path

import requests
from dotenv import load_dotenv
from psycopg.types.json import Jsonb

from roleA.common.db import get_conn

load_dotenv()


# =========================================================
# 설정
# =========================================================

LLM_API_KEY = os.getenv("LLM_API_KEY")
LLM_BASE_URL = os.getenv("LLM_BASE_URL")
LLM_MODEL = os.getenv("LLM_MODEL")

REVIEW_PATH = (
    Path(__file__).resolve().parents[1] / "data" / "review_candidates_raw.jsonl"
)


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


class QuotaStop(Exception):
    pass


# =========================================================
# 리뷰 로드
# =========================================================


def load_review_records():

    records = {}

    with REVIEW_PATH.open(
        "r",
        encoding="utf-8",
    ) as f:

        for line in f:

            line = line.strip()

            if not line:
                continue

            row = json.loads(line)

            records[row["poi_id"]] = row

    return records


def clean_text(text):

    if not text:
        return ""

    text = re.sub(
        r"<[^>]+>",
        "",
        text,
    )

    return html.unescape(text).strip()


# =========================================================
# LLM JSON Schema
# =========================================================


def build_schema(n_reviews):

    return {
        "type": "object",
        "properties": {
            "outdoor_exposure": {
                "type": ["number", "null"],
                "minimum": 0,
                "maximum": 1,
            },
            "group_capacity": {
                "type": ["integer", "null"],
                "minimum": 1,
            },
            "noise_level": {
                "type": ["integer", "null"],
                "minimum": 1,
                "maximum": 5,
            },
            "purpose_tags": {
                "type": ["array", "null"],
                "items": {
                    "type": "string",
                    "enum": PURPOSE_TAGS,
                },
                "uniqueItems": True,
            },
            "atmosphere_tags": {
                "type": ["array", "null"],
                "items": {
                    "type": "string",
                    "enum": ATMOSPHERE_TAGS,
                },
                "uniqueItems": True,
            },
            "price_band": {
                "type": ["integer", "null"],
                "minimum": 1,
                "maximum": 4,
            },
            "wait_intensity": {
                "type": ["object", "null"],
                "properties": {
                    "weekday": {
                        "type": ["string", "null"],
                    },
                    "weekend": {
                        "type": ["string", "null"],
                    },
                },
                "required": [
                    "weekday",
                    "weekend",
                ],
                "additionalProperties": False,
            },
            "business_hours_hint": {
                "type": ["string", "null"],
            },
            "sentiment_score": {
                "type": ["number", "null"],
                "minimum": 0,
                "maximum": 1,
            },
            # 원본 리뷰 각각의 광고 여부
            "review_sponsorship": {
                "type": "array",
                "items": {
                    "type": "boolean",
                },
                "minItems": n_reviews,
                "maxItems": n_reviews,
            },
            "review_relevance": {
                "type": "array",
                "items": {
                    "type": "boolean",
                },
                "minItems": n_reviews,
                "maxItems": n_reviews,
            },
            # DB에 저장할 핵심 근거 최대 3개
            "chunk_indices": {
                "type": "array",
                "maxItems": 3,
                "uniqueItems": True,
                "items": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": n_reviews,
                },
            },
        },
        "required": [
            "outdoor_exposure",
            "group_capacity",
            "noise_level",
            "purpose_tags",
            "atmosphere_tags",
            "price_band",
            "wait_intensity",
            "business_hours_hint",
            "sentiment_score",
            "review_sponsorship",
            "review_relevance",
            "chunk_indices",
        ],
        "additionalProperties": False,
    }


# =========================================================
# 프롬프트
# =========================================================


def build_prompt(
    poi,
    review_record,
):

    review_texts = []

    for i, item in enumerate(
        review_record["items"],
        start=1,
    ):

        title = clean_text(item.get("title"))

        description = clean_text(item.get("description"))

        postdate = item.get(
            "postdate",
            "",
        )

        review_texts.append(f"""
[리뷰 {i}]
제목: {title}
내용: {description}
작성일: {postdate}
""".strip())

    joined_reviews = "\n\n".join(review_texts)

    return f"""
당신은 장소 리뷰 분석기다.

아래 장소와 네이버 블로그 후기들을 분석하여
제공된 JSON Schema에 맞는 JSON만 반환하라.

장소명: {poi["name"]}
행정동: {poi["dong"]}
대분류: {poi["category_l1"]}
소분류: {poi["category_l2"]}

[핵심 규칙]

1. 리뷰에서 확인할 수 없는 속성은 반드시 null로 반환한다.
추측해서 값을 만들지 않는다.

2. outdoor_exposure:
0은 완전 실내, 1은 완전 야외다.

3. group_capacity:
실제로 수용 가능한 인원에 대한 근거가 있을 때만 숫자로 반환한다.

4. noise_level:
1은 매우 조용함, 5는 매우 시끄럽거나 활기참이다.

5. purpose_tags는 아래 어휘에서만 선택한다.
{PURPOSE_TAGS}

6. atmosphere_tags는 아래 어휘에서만 선택한다.
{ATMOSPHERE_TAGS}

7. price_band:
리뷰에 가격 정보 또는 저렴함/비쌈에 대한 근거가 있을 때만 판단한다.
1=저렴, 2=보통 이하, 3=다소 비쌈, 4=고가.
절대 금액 근거가 없고 판단하기 어려우면 null이다.

8. wait_intensity:
평일과 주말 웨이팅에 대한 리뷰 근거가 있을 때만 작성한다.
근거가 없으면 각 값 또는 전체를 null 처리한다.

9. business_hours_hint:
리뷰에서 영업시간 또는 휴무일이 명시된 경우에만 짧게 적는다.

10. review_relevance:
각 리뷰가 정말 현재 분석 대상 장소에 대한 리뷰인지 판정한다.
입력 리뷰 순서와 정확히 대응하는 boolean 배열로 반환한다.

- 현재 장소명이 짧거나 일반적인 단어일 경우 특히 엄격하게 판단한다.
- 리뷰의 중심 내용이 명백히 다른 업체에 관한 것이면 false다.
- 검색 결과에 장소명이 우연히 포함된 것만으로 true로 판단하지 않는다.
- 확실하게 현재 장소에 대한 리뷰일 때만 true다.

11. review_sponsorship:
각 입력 리뷰가 협찬 또는 광고성인지 판정한다.
입력 리뷰 순서와 정확히 대응하는 boolean 배열로 반환한다.

광고 판단 근거 예:
- 협찬
- 제공받아
- 원고료
- 체험단
- 광고

근거가 부족하면 임의로 광고라고 단정하지 않는다.

12. 모든 장소 속성은 review_relevance=true인 리뷰만 근거로 판단한다.
관련 리뷰가 없으면 속성을 추측하지 말고 null로 반환한다.

13. sentiment_score:
review_relevance=true 이면서 review_sponsorship=false인 리뷰만 사용하여
전반적인 긍정도를 0~1로 평가한다.
사용 가능한 리뷰가 없으면 null이다.

14. chunk_indices:
추천 설명의 근거로 유용한 리뷰 번호를 최대 3개 선택한다.
반드시 review_relevance=true인 리뷰만 선택한다.
가능하면 review_sponsorship=false인 리뷰를 우선한다.
리뷰 문장을 직접 다시 작성하지 말고 리뷰 번호만 반환한다.

[리뷰]

{joined_reviews}
""".strip()


# =========================================================
# LLM 호출
# =========================================================


def call_llm(
    poi,
    review_record,
):

    items = review_record["items"]

    schema = build_schema(len(items))

    url = f"{LLM_BASE_URL.rstrip('/')}" "/chat/completions/"

    headers = {
        "Authorization": (f"Bearer {LLM_API_KEY}"),
        "Content-Type": "application/json",
    }

    payload = {
        "model": LLM_MODEL,
        "messages": [
            {
                "role": "system",
                "content": (
                    "장소 리뷰를 근거 중심으로 "
                    "구조화하는 분석기다. "
                    "추측하지 말고 JSON Schema를 "
                    "엄격하게 준수하라."
                ),
            },
            {
                "role": "user",
                "content": build_prompt(
                    poi,
                    review_record,
                ),
            },
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "poi_attributes",
                "strict": True,
                "schema": schema,
            },
        },
    }

    waits = [
        0,
        2,
        4,
        8,
        16,
    ]

    for attempt, wait in enumerate(waits):

        if wait:
            print(f"  재시도 대기 {wait}초...")

            time.sleep(wait)

        response = requests.post(
            url,
            headers=headers,
            json=payload,
            timeout=90,
        )

        if response.status_code == 200:

            data = response.json()

            content = data["choices"][0]["message"]["content"]

            attrs = json.loads(content)

            return (
                attrs,
                data.get("usage", {}),
            )

        if response.status_code == 402:

            raise QuotaStop("LLM 사용 한도 또는 크레딧 종료")

        if response.status_code == 429:

            if attempt == len(waits) - 1:

                raise QuotaStop("429가 계속 발생하여 " "배치를 안전하게 종료합니다.")

            continue

        if response.status_code >= 500:

            if attempt < len(waits) - 1:
                continue

        raise RuntimeError(
            f"LLM API 오류 " f"{response.status_code}: " f"{response.text[:500]}"
        )

    raise RuntimeError("LLM 호출 실패")


# =========================================================
# 결과 검증
# =========================================================


def validate_result(
    attrs,
    n_reviews,
):

    sponsorship = attrs.get("review_sponsorship")

    relevance = attrs.get("review_relevance")

    if not isinstance(sponsorship, list):
        raise ValueError("review_sponsorship이 배열이 아님")

    if not isinstance(relevance, list):
        raise ValueError("review_relevance가 배열이 아님")

    if len(sponsorship) != n_reviews:
        raise ValueError("review_sponsorship 길이가 " "입력 리뷰 수와 다름")

    if len(relevance) != n_reviews:
        raise ValueError("review_relevance 길이가 " "입력 리뷰 수와 다름")

    clean_relevant = [
        i for i in range(n_reviews) if relevance[i] and not sponsorship[i]
    ]

    if not clean_relevant:
        attrs["sentiment_score"] = None

    if attrs["purpose_tags"] is not None:
        attrs["purpose_tags"] = [
            tag for tag in attrs["purpose_tags"] if tag in PURPOSE_TAGS
        ]

    if attrs["atmosphere_tags"] is not None:
        attrs["atmosphere_tags"] = [
            tag for tag in attrs["atmosphere_tags"] if tag in ATMOSPHERE_TAGS
        ]

    valid_indices = []

    for idx in attrs.get(
        "chunk_indices",
        [],
    )[:3]:

        zero_idx = idx - 1

        if (
            0 <= zero_idx < n_reviews
            and relevance[zero_idx]
            and idx not in valid_indices
        ):
            valid_indices.append(idx)

    attrs["chunk_indices"] = valid_indices

    return attrs


def build_original_chunks(
    attrs,
    review_record,
):

    chunks = []

    sponsorship = attrs["review_sponsorship"]

    for idx in attrs["chunk_indices"]:

        item = review_record["items"][idx - 1]

        text = clean_text(item.get("description"))

        if not text:
            text = clean_text(item.get("title"))

        if not text:
            continue

        chunks.append(
            {
                "text": text[:300],
                "is_sponsored": (sponsorship[idx - 1]),
            }
        )

    attrs["chunks"] = chunks

    return attrs


# =========================================================
# attr_confidence
# =========================================================
def is_effectively_null(value):

    if value is None:
        return True

    if isinstance(value, str):
        return not value.strip()

    if isinstance(value, (list, tuple, set)):
        return len(value) == 0

    if isinstance(value, dict):
        return all(is_effectively_null(v) for v in value.values())

    return False


def calculate_confidence(
    attrs,
):

    sponsorship = attrs["review_sponsorship"]

    relevance = attrs["review_relevance"]

    n_clean_reviews = sum(
        relevant and not sponsored
        for relevant, sponsored in zip(
            relevance,
            sponsorship,
        )
    )

    fields = [
        "outdoor_exposure",
        "group_capacity",
        "noise_level",
        "purpose_tags",
        "atmosphere_tags",
        "price_band",
        "wait_intensity",
        "business_hours_hint",
        "sentiment_score",
    ]

    n_null_fields = sum(is_effectively_null(attrs.get(field)) for field in fields)

    base = min(
        n_clean_reviews / 8.0,
        1.0,
    )

    penalty = n_null_fields * 0.08

    confidence = max(
        0.0,
        round(
            base - penalty,
            3,
        ),
    )

    return (
        confidence,
        n_clean_reviews,
        n_null_fields,
    )


# =========================================================
# DB
# =========================================================


def get_pending_pois(
    conn,
    limit,
):

    with conn.cursor() as cur:

        cur.execute(
            """
            SELECT
                poi_id,
                name,
                dong,
                category_l1,
                category_l2
            FROM poi
            WHERE tier = 1
              AND attr_extracted_at IS NULL
            ORDER BY
                mention_count DESC NULLS LAST
            LIMIT %s
            """,
            (limit,),
        )

        rows = cur.fetchall()

    return [
        {
            "poi_id": row[0],
            "name": row[1],
            "dong": row[2],
            "category_l1": row[3],
            "category_l2": row[4],
        }
        for row in rows
    ]


def save_result(
    conn,
    poi_id,
    attrs,
    confidence,
):

    chunks = attrs["chunks"]

    try:

        with conn.cursor() as cur:

            # 멱등성:
            # 기존 chunk 제거 후 다시 저장
            cur.execute(
                """
                DELETE FROM review_chunk
                WHERE poi_id = %s
                """,
                (poi_id,),
            )

            for chunk in chunks:

                cur.execute(
                    """
                    INSERT INTO review_chunk (
                        poi_id,
                        source,
                        text,
                        is_sponsored
                    )
                    VALUES (
                        %s,
                        'naver_blog',
                        %s,
                        %s
                    )
                    """,
                    (
                        poi_id,
                        chunk["text"],
                        chunk["is_sponsored"],
                    ),
                )

            wait_value = (
                Jsonb(attrs["wait_intensity"])
                if attrs["wait_intensity"] is not None
                else None
            )

            cur.execute(
                """
                UPDATE poi
                SET
                    outdoor_exposure = %s,
                    group_capacity = %s,
                    noise_level = %s,
                    purpose_tags = %s,
                    atmosphere_tags = %s,
                    price_band = %s,
                    wait_intensity = %s,
                    sentiment_score = %s,
                    review_count = %s,
                    attr_confidence = %s,
                    attr_extracted_at = NOW(),
                    updated_at = NOW()
                WHERE poi_id = %s
                """,
                (
                    attrs["outdoor_exposure"],
                    attrs["group_capacity"],
                    attrs["noise_level"],
                    attrs["purpose_tags"],
                    attrs["atmosphere_tags"],
                    attrs["price_band"],
                    wait_value,
                    attrs["sentiment_score"],
                    len(chunks),
                    confidence,
                    poi_id,
                ),
            )

        # POI 하나 성공할 때마다 즉시 commit
        conn.commit()

    except Exception:

        conn.rollback()

        raise


# =========================================================
# 리뷰 없는 POI
# =========================================================


def empty_result():

    return {
        "outdoor_exposure": None,
        "group_capacity": None,
        "noise_level": None,
        "purpose_tags": None,
        "atmosphere_tags": None,
        "price_band": None,
        "wait_intensity": None,
        "business_hours_hint": None,
        "sentiment_score": None,
        "review_sponsorship": [],
        "chunks": [],
    }


# =========================================================
# 실행
# =========================================================


def main():

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--limit",
        type=int,
        default=50,
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
    )

    parser.add_argument(
        "--summary-only",
        action="store_true",
        help="개별 JSON 출력 없이 결과 요약만 출력",
    )

    args = parser.parse_args()

    if not LLM_API_KEY:
        raise RuntimeError("LLM_API_KEY가 없습니다.")

    if not LLM_BASE_URL:
        raise RuntimeError("LLM_BASE_URL이 없습니다.")

    if not LLM_MODEL:
        raise RuntimeError("LLM_MODEL이 없습니다.")

    review_records = load_review_records()

    conn = get_conn()

    total_tokens = 0

    processed_count = 0
    high_conf_count = 0
    confidence_values = []

    try:

        pending = get_pending_pois(
            conn,
            args.limit,
        )

        print(f"처리 대상: {len(pending)}개")

        for i, poi in enumerate(
            pending,
            start=1,
        ):

            poi_id = poi["poi_id"]

            review_record = review_records.get(poi_id)

            if review_record is None:

                print(
                    f"[{i}/{len(pending)}] "
                    f"{poi['name']} "
                    "→ 리뷰 JSONL 없음, 건너뜀"
                )

                continue

            items = review_record.get("items") or []

            print(f"\n[{i}/{len(pending)}] " f"{poi['name']} " f"(리뷰 {len(items)}건)")

            try:

                if not items:

                    attrs = empty_result()

                    confidence = 0.0
                    n_clean = 0
                    n_null = 9

                    usage = {}

                else:

                    attrs, usage = call_llm(
                        poi,
                        review_record,
                    )

                    attrs = validate_result(
                        attrs,
                        len(items),
                    )

                    attrs = build_original_chunks(
                        attrs,
                        review_record,
                    )

                    (
                        confidence,
                        n_clean,
                        n_null,
                    ) = calculate_confidence(attrs)

                total_tokens += usage.get(
                    "total_tokens",
                    0,
                )

                processed_count += 1
                confidence_values.append(confidence)

                if confidence >= 0.5:
                    high_conf_count += 1

                print(f"  clean reviews: " f"{n_clean}")

                print(f"  null fields: " f"{n_null}")

                print(f"  chunks: " f"{len(attrs['chunks'])}")

                print(f"  confidence: " f"{confidence}")

                if args.dry_run:

                    if not args.summary_only:
                        print(
                            json.dumps(
                                attrs,
                                ensure_ascii=False,
                                indent=2,
                            )
                        )

                    continue

                save_result(
                    conn,
                    poi_id,
                    attrs,
                    confidence,
                )

                print("  DB 저장 완료")

            except QuotaStop as e:

                print(f"\n{e}")

                print("현재까지 성공한 결과는 " "DB에 저장되어 있습니다.")

                break

            except Exception as e:

                print(f"  ERROR: {e}")

                conn.rollback()

                # 한 POI 오류 때문에
                # 전체 배치를 죽이지 않음
                continue

    finally:

        conn.close()

    if processed_count > 0:

        high_conf_rate = high_conf_count / processed_count * 100

        avg_confidence = sum(confidence_values) / len(confidence_values)

        print("\n=== A3-2 품질 요약 ===")

        print(f"처리 완료: " f"{processed_count}개")

        print(
            f"confidence >= 0.5: "
            f"{high_conf_count}"
            f"/{processed_count} "
            f"({high_conf_rate:.1f}%)"
        )

        print(f"평균 confidence: " f"{avg_confidence:.3f}")

        print("W4 목표(70% 이상): " + ("PASS" if high_conf_rate >= 70 else "FAIL"))
    print(f"\n사용량 total_tokens: " f"{total_tokens}")


if __name__ == "__main__":
    main()
