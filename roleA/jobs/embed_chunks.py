import argparse
import math

import numpy as np
from sentence_transformers import SentenceTransformer

from roleA.common.db import get_conn

MODEL_NAME = "BAAI/bge-m3"
EMBEDDING_DIM = 1024
BATCH_SIZE = 32


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


def vector_to_pg(vector):
    """
    numpy vector를 pgvector/halfvec 입력 문자열로 변환.
    """
    return "[" + ",".join(f"{float(x):.8f}" for x in vector) + "]"


def normalize(vector):
    norm = np.linalg.norm(vector)

    if norm == 0:
        return vector

    return vector / norm


def load_model():
    print("BGE-M3 모델 로딩...")

    model = SentenceTransformer(
        MODEL_NAME,
        device="cpu",
    )

    print("모델 로딩 완료")

    return model


def encode_texts(
    model,
    texts,
):
    vectors = model.encode(
        texts,
        batch_size=BATCH_SIZE,
        show_progress_bar=True,
        normalize_embeddings=True,
        convert_to_numpy=True,
    )

    if vectors.shape[1] != EMBEDDING_DIM:
        raise RuntimeError(
            f"임베딩 차원 오류: " f"{vectors.shape[1]} != {EMBEDDING_DIM}"
        )

    return vectors


# =========================================================
# 1. tag_embedding
# =========================================================


def build_tag_embeddings(model):

    rows = []

    purpose_vectors = encode_texts(
        model,
        PURPOSE_TAGS,
    )

    for tag, vector in zip(
        PURPOSE_TAGS,
        purpose_vectors,
    ):
        rows.append(
            {
                "tag": tag,
                "kind": "purpose",
                "vector": vector,
            }
        )

    atmosphere_vectors = encode_texts(
        model,
        ATMOSPHERE_TAGS,
    )

    for tag, vector in zip(
        ATMOSPHERE_TAGS,
        atmosphere_vectors,
    ):
        rows.append(
            {
                "tag": tag,
                "kind": "atmosphere",
                "vector": vector,
            }
        )

    return rows


def save_tag_embeddings(
    conn,
    rows,
):
    with conn.cursor() as cur:

        for row in rows:

            cur.execute(
                """
                INSERT INTO tag_embedding (
                    tag,
                    kind,
                    embedding
                )
                VALUES (
                    %s,
                    %s,
                    %s::halfvec
                )
                ON CONFLICT (tag)
                DO UPDATE SET
                    kind = EXCLUDED.kind,
                    embedding = EXCLUDED.embedding
                """,
                (
                    row["tag"],
                    row["kind"],
                    vector_to_pg(row["vector"]),
                ),
            )

    conn.commit()


# =========================================================
# 2. poi.tag_vector
# =========================================================


def load_t1_pois(conn):

    with conn.cursor() as cur:

        cur.execute("""
            SELECT
                poi_id,
                purpose_tags,
                atmosphere_tags
            FROM poi
            WHERE tier = 1
              AND attr_extracted_at IS NOT NULL
            ORDER BY poi_id
            """)

        return cur.fetchall()


def build_poi_vectors(
    pois,
    tag_lookup,
):

    output = []
    skipped = 0

    for (
        poi_id,
        purpose_tags,
        atmosphere_tags,
    ) in pois:

        tags = []

        if purpose_tags:
            tags.extend(purpose_tags)

        if atmosphere_tags:
            tags.extend(atmosphere_tags)

        vectors = []

        for tag in tags:

            vector = tag_lookup.get(tag)

            if vector is not None:
                vectors.append(vector)

        if not vectors:
            skipped += 1
            continue

        mean_vector = np.mean(
            np.stack(vectors),
            axis=0,
        )

        mean_vector = normalize(mean_vector)

        output.append(
            (
                poi_id,
                mean_vector,
            )
        )

    return output, skipped


def save_poi_vectors(
    conn,
    rows,
):

    with conn.cursor() as cur:

        for poi_id, vector in rows:

            cur.execute(
                """
                UPDATE poi
                SET
                    tag_vector = %s::halfvec,
                    updated_at = NOW()
                WHERE poi_id = %s
                """,
                (
                    vector_to_pg(vector),
                    poi_id,
                ),
            )

    conn.commit()


# =========================================================
# 3. review_chunk.embedding
# =========================================================


def load_pending_chunks(conn):

    with conn.cursor() as cur:

        cur.execute("""
            SELECT
                chunk_id,
                text
            FROM review_chunk
            WHERE embedding IS NULL
              AND text IS NOT NULL
              AND BTRIM(text) <> ''
            ORDER BY chunk_id
            """)

        return cur.fetchall()


def embed_review_chunks(
    conn,
    model,
    chunks,
):

    total = len(chunks)

    if total == 0:
        print("임베딩할 review_chunk 없음")
        return

    for start in range(
        0,
        total,
        BATCH_SIZE,
    ):

        batch = chunks[start : start + BATCH_SIZE]

        chunk_ids = [row[0] for row in batch]

        texts = [row[1] for row in batch]

        vectors = encode_texts(
            model,
            texts,
        )

        try:

            with conn.cursor() as cur:

                for (
                    chunk_id,
                    vector,
                ) in zip(
                    chunk_ids,
                    vectors,
                ):

                    cur.execute(
                        """
                        UPDATE review_chunk
                        SET embedding = %s::halfvec
                        WHERE chunk_id = %s
                        """,
                        (
                            vector_to_pg(vector),
                            chunk_id,
                        ),
                    )

            conn.commit()

        except Exception:
            conn.rollback()
            raise

        done = min(
            start + BATCH_SIZE,
            total,
        )

        print(f"review_chunk: " f"{done}/{total}")


# =========================================================
# QC
# =========================================================


def print_db_status(conn):

    with conn.cursor() as cur:

        cur.execute("""
            SELECT COUNT(*)
            FROM tag_embedding
            """)
        tag_total = cur.fetchone()[0]

        cur.execute("""
            SELECT COUNT(*)
            FROM poi
            WHERE tier = 1
              AND tag_vector IS NOT NULL
            """)
        poi_vectors = cur.fetchone()[0]

        cur.execute("""
            SELECT COUNT(*)
            FROM review_chunk
            """)
        chunks_total = cur.fetchone()[0]

        cur.execute("""
            SELECT COUNT(*)
            FROM review_chunk
            WHERE embedding IS NOT NULL
            """)
        chunks_embedded = cur.fetchone()[0]

    print("\n=== A4-2 DB 현황 ===")

    print(
        "tag_embedding:",
        tag_total,
    )

    print(
        "T1 tag_vector:",
        poi_vectors,
    )

    print(
        "review_chunk:",
        chunks_total,
    )

    print(
        "review_chunk embedding:",
        chunks_embedded,
    )


def main():

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--apply",
        action="store_true",
        help="실제 DB에 임베딩 저장",
    )

    args = parser.parse_args()

    conn = get_conn()

    try:

        print_db_status(conn)

        model = load_model()

        # -------------------------
        # tag_embedding 16개 생성
        # -------------------------

        tag_rows = build_tag_embeddings(model)

        print(
            "\n고정 tag embedding:",
            len(tag_rows),
        )

        if len(tag_rows) != 16:
            raise RuntimeError("고정 태그가 16개가 아닙니다.")

        tag_lookup = {row["tag"]: row["vector"] for row in tag_rows}

        # -------------------------
        # poi.tag_vector 생성
        # -------------------------

        pois = load_t1_pois(conn)

        poi_vectors, skipped = build_poi_vectors(
            pois,
            tag_lookup,
        )

        print(
            "T1 POI:",
            len(pois),
        )

        print(
            "tag_vector 생성 가능:",
            len(poi_vectors),
        )

        print(
            "태그 없음:",
            skipped,
        )

        # -------------------------
        # review chunks
        # -------------------------

        chunks = load_pending_chunks(conn)

        print(
            "embedding 없는 review_chunk:",
            len(chunks),
        )

        if not args.apply:

            print("\n[DRY RUN]")

            print("DB에는 저장하지 않았습니다.")

            return

        # -------------------------
        # 실제 저장
        # -------------------------

        print("\ntag_embedding 저장...")

        save_tag_embeddings(
            conn,
            tag_rows,
        )

        print("poi.tag_vector 저장...")

        save_poi_vectors(
            conn,
            poi_vectors,
        )

        print("review_chunk.embedding 저장...")

        embed_review_chunks(
            conn,
            model,
            chunks,
        )

        print_db_status(conn)

        print("\nA4-2 완료")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
