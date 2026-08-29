# segment_affinity 미지원 category_l2
#
# 서울시 2025 추정매출 서비스업종과 의미가 명확히 대응되지 않는
# 아래 업종은 임의 매핑하지 않는다.
#
# - 장식품 소매
# - 동남아시아
# - 구내식당·뷔페
# - 도서관·사적지
# - 관광지
# - 문화시설
# - 기타 외국
#
# 해당 POI는 추천 엔진에서 segment_affinity를
# 관측 불가(중립)로 처리한다.

import argparse

from sentence_transformers import SentenceTransformer

from roleA.common.db import get_conn
from roleB.app.constants import (
    PURPOSE_TAGS,
    WEATHER_STATES,
    PARTY_BANDS,
)

MODEL_NAME = "BAAI/bge-m3"
EMBEDDING_DIM = 1024
BATCH_SIZE = 32


PARTY_LABELS = {
    1: "1~2명",
    2: "3~4명",
    3: "5명 이상",
}


def vector_to_pg(vector):
    """
    numpy 벡터를 pgvector/halfvec 입력 문자열로 변환.
    """
    return "[" + ",".join(f"{float(x):.8f}" for x in vector) + "]"


def build_query_rows():
    """
    목적 6 × 날씨 4 × 인원밴드 3 = 72개 query 생성.
    """

    rows = []

    for purpose in PURPOSE_TAGS:
        for weather_state in WEATHER_STATES:
            for party_band in PARTY_BANDS.keys():

                party_label = PARTY_LABELS[party_band]

                query_text = (
                    f"{party_label}이서 " f"{purpose}하기 좋은 곳, " f"{weather_state}"
                )

                rows.append(
                    {
                        "purpose": purpose,
                        "weather_state": weather_state,
                        "party_band": party_band,
                        "query_text": query_text,
                    }
                )

    return rows


def load_model():
    print("BGE-M3 모델 로딩...")

    model = SentenceTransformer(
        MODEL_NAME,
        device="cpu",
    )

    print("모델 로딩 완료")

    return model


def embed_queries(model, rows):

    texts = [row["query_text"] for row in rows]

    vectors = model.encode(
        texts,
        batch_size=BATCH_SIZE,
        show_progress_bar=True,
        normalize_embeddings=True,
        convert_to_numpy=True,
    )

    if vectors.shape != (
        len(rows),
        EMBEDDING_DIM,
    ):
        raise RuntimeError("임베딩 shape 오류: " f"{vectors.shape}")

    for row, vector in zip(
        rows,
        vectors,
    ):
        row["embedding"] = vector

    return rows


def validate_rows(rows):

    expected = len(PURPOSE_TAGS) * len(WEATHER_STATES) * len(PARTY_BANDS)

    if expected != 72:
        raise RuntimeError(f"B 상수 기준 예상 행이 72가 아님: {expected}")

    if len(rows) != expected:
        raise RuntimeError(f"생성 행 오류: {len(rows)} != {expected}")

    keys = {
        (
            row["purpose"],
            row["weather_state"],
            row["party_band"],
        )
        for row in rows
    }

    if len(keys) != expected:
        raise RuntimeError("query cache key 중복이 있습니다.")


def print_preview(rows):

    print("\n=== query_vector_cache QC ===")

    print(
        "목적:",
        len(PURPOSE_TAGS),
        list(PURPOSE_TAGS),
    )

    print(
        "날씨:",
        len(WEATHER_STATES),
        list(WEATHER_STATES),
    )

    print(
        "인원밴드:",
        len(PARTY_BANDS),
        dict(PARTY_BANDS),
    )

    print(
        "생성 행:",
        len(rows),
    )

    print("\n=== query_text 예시 ===")

    for row in rows[:8]:
        print(
            (
                row["purpose"],
                row["weather_state"],
                row["party_band"],
                row["query_text"],
            )
        )


def save_to_db(conn, rows):
    """
    전체 72행을 한 트랜잭션에서 재생성.

    이 테이블은 고정 어휘의 완전한 Cartesian product이므로
    기존 내용을 지우고 다시 만드는 방식이 멱등적이다.
    """

    records = [
        (
            row["purpose"],
            row["weather_state"],
            row["party_band"],
            row["query_text"],
            vector_to_pg(row["embedding"]),
        )
        for row in rows
    ]

    try:
        with conn.cursor() as cur:

            cur.execute("""
                DELETE FROM query_vector_cache
                """)

            cur.executemany(
                """
                INSERT INTO query_vector_cache (
                    purpose,
                    weather_state,
                    party_band,
                    query_text,
                    embedding
                )
                VALUES (
                    %s,
                    %s,
                    %s,
                    %s,
                    %s::halfvec
                )
                """,
                records,
            )

        conn.commit()

    except Exception:
        conn.rollback()
        raise


def verify_db(conn):

    with conn.cursor() as cur:

        cur.execute("""
            SELECT COUNT(*)
            FROM query_vector_cache
            """)

        total = cur.fetchone()[0]

        cur.execute("""
            SELECT
                purpose,
                COUNT(*)
            FROM query_vector_cache
            GROUP BY purpose
            ORDER BY purpose
            """)

        by_purpose = cur.fetchall()

        cur.execute("""
            SELECT
                weather_state,
                COUNT(*)
            FROM query_vector_cache
            GROUP BY weather_state
            ORDER BY weather_state
            """)

        by_weather = cur.fetchall()

        cur.execute("""
            SELECT
                party_band,
                COUNT(*)
            FROM query_vector_cache
            GROUP BY party_band
            ORDER BY party_band
            """)

        by_party = cur.fetchall()

    print("\n=== DB 저장 확인 ===")

    print(
        "전체:",
        total,
    )

    print(
        "목적별:",
        by_purpose,
    )

    print(
        "날씨별:",
        by_weather,
    )

    print(
        "인원밴드별:",
        by_party,
    )

    if total != 72:
        raise RuntimeError(f"DB 행 수 오류: {total} != 72")


def main():

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--apply",
        action="store_true",
        help="실제 DB에 query_vector_cache를 저장",
    )

    args = parser.parse_args()

    rows = build_query_rows()

    validate_rows(rows)

    print_preview(rows)

    model = load_model()

    rows = embed_queries(
        model,
        rows,
    )

    print(
        "\n임베딩 shape:",
        (
            len(rows),
            len(rows[0]["embedding"]),
        ),
    )

    if not args.apply:
        print("\n[DRY RUN] " "DB에는 저장하지 않았습니다.")
        return

    conn = get_conn()

    try:
        save_to_db(
            conn,
            rows,
        )

        verify_db(conn)

        print("\nquery_vector_cache 생성 완료")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
