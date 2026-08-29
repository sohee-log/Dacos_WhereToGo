import argparse
import math

import numpy as np

from roleA.common.db import get_conn

C = 8.0


def load_quality_inputs(conn):
    """
    quality_score 계산에 필요한 POI별 데이터를 읽는다.

    n_clean:
        review_chunk 중 is_sponsored = false인 청크 수
    """

    with conn.cursor() as cur:
        cur.execute("""
            SELECT
                p.poi_id,
                p.sentiment_score,
                COALESCE(p.mention_count, 0) AS mention_count,
                COUNT(rc.chunk_id) FILTER (
                    WHERE rc.is_sponsored = FALSE
                ) AS n_clean
            FROM poi p
            LEFT JOIN review_chunk rc
                ON rc.poi_id = p.poi_id
            WHERE p.tier = 1
              AND p.attr_extracted_at IS NOT NULL
              AND p.attr_confidence >= 0.3
            GROUP BY
                p.poi_id,
                p.sentiment_score,
                p.mention_count
            ORDER BY p.poi_id
            """)

        return cur.fetchall()


def compute_global_values(rows):
    """
    m:
        sentiment_score가 존재하는 POI들의 전체 평균

    MENTION_P95:
        전체 POI mention_count의 95퍼센타일
    """

    sentiments = [
        float(sentiment)
        for (
            _,
            sentiment,
            _,
            _,
        ) in rows
        if sentiment is not None
    ]

    if not sentiments:
        raise RuntimeError("sentiment_score가 존재하는 POI가 없습니다.")

    m = float(np.mean(sentiments))

    mentions = np.array(
        [
            max(
                0,
                int(mention_count or 0),
            )
            for (
                _,
                _,
                mention_count,
                _,
            ) in rows
        ],
        dtype=float,
    )

    mention_p95 = float(
        np.percentile(
            mentions,
            95,
        )
    )

    if mention_p95 <= 0:
        raise RuntimeError("MENTION_P95가 0 이하입니다.")

    return m, mention_p95


def build_quality_rows(
    rows,
    m,
    mention_p95,
):
    """
    프로젝트 정의:

    s_bayes
      = (C*m + sentiment_score*n_clean)
        / (C+n_clean)

    quality_score
      = s_bayes
        * log1p(clipped mention_count)
        / log1p(MENTION_P95)

    mention_count는 P95에서 상한 clipping한다.
    """

    output = []

    for (
        poi_id,
        sentiment_score,
        mention_count,
        n_clean,
    ) in rows:

        mention_count = max(
            0,
            int(mention_count or 0),
        )

        n_clean = max(
            0,
            int(n_clean or 0),
        )

        # sentiment가 없는 경우에는
        # 전체 평균 m을 prior로 사용한다.
        #
        # 리뷰 근거가 없다는 사실은 n_clean=0으로
        # 베이지안 보정에 반영된다.
        sentiment = float(sentiment_score) if sentiment_score is not None else m

        s_bayes = (C * m + sentiment * n_clean) / (C + n_clean)

        clipped_mentions = min(
            mention_count,
            mention_p95,
        )

        popularity = math.log1p(clipped_mentions) / math.log1p(mention_p95)

        quality_score = s_bayes * popularity

        # DB/랭킹에서 사용할 값이므로
        # 안전하게 0~1 범위 보장
        quality_score = max(
            0.0,
            min(
                1.0,
                quality_score,
            ),
        )

        output.append(
            (
                poi_id,
                quality_score,
                s_bayes,
                n_clean,
                mention_count,
            )
        )

    return output


def print_qc(
    rows,
    m,
    mention_p95,
):
    scores = [row[1] for row in rows]

    nonzero = sum(score > 0 for score in scores)

    print("\n=== A4-4 quality QC ===")

    print(
        "전체 POI:",
        len(rows),
    )

    print(
        "전체 평균 감성 m:",
        round(
            m,
            4,
        ),
    )

    print(
        "MENTION_P95:",
        round(
            mention_p95,
            2,
        ),
    )

    print(
        "quality > 0:",
        nonzero,
    )

    print(
        "quality = 0:",
        len(rows) - nonzero,
    )

    print(
        "quality min:",
        round(
            min(scores),
            6,
        ),
    )

    print(
        "quality max:",
        round(
            max(scores),
            6,
        ),
    )

    print(
        "quality avg:",
        round(
            sum(scores) / len(scores),
            6,
        ),
    )


def save_quality(
    conn,
    rows,
):
    records = [
        (
            quality_score,
            poi_id,
        )
        for (
            poi_id,
            quality_score,
            _,
            _,
            _,
        ) in rows
    ]

    try:
        with conn.cursor() as cur:

            # B에서 attr_confidence < 0.3은 추천 후보에서 제외한다.
            # 따라서 근거가 부족한 POI에는 quality_score를
            # 임의로 생성하지 않고 NULL로 유지한다.
            cur.execute("""
                UPDATE poi
                SET
                    quality_score = NULL,
                    updated_at = NOW()
                WHERE tier = 1
                  AND (
                      attr_confidence IS NULL
                      OR attr_confidence < 0.3
                  )
                """)

            cur.executemany(
                """
                UPDATE poi
                SET
                    quality_score = %s,
                    updated_at = NOW()
                WHERE poi_id = %s
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
            SELECT
                COUNT(*) AS total_t1,
                COUNT(*) FILTER (
                    WHERE attr_confidence >= 0.3
                ) AS eligible,
                COUNT(quality_score) AS filled,
                MIN(quality_score),
                MAX(quality_score),
                AVG(quality_score)
            FROM poi
            WHERE tier = 1
            """)

        row = cur.fetchone()

    print("\n=== DB 저장 확인 ===")

    print("T1 전체:", row[0])
    print("quality 대상:", row[1])
    print("quality_score 채움:", row[2])
    print("min/max/avg:", row[3:])


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--apply",
        action="store_true",
        help="실제 DB에 quality_score 저장",
    )

    args = parser.parse_args()

    conn = get_conn()

    try:
        raw_rows = load_quality_inputs(conn)

        m, mention_p95 = compute_global_values(raw_rows)

        quality_rows = build_quality_rows(
            raw_rows,
            m,
            mention_p95,
        )

        print_qc(
            quality_rows,
            m,
            mention_p95,
        )

        if not args.apply:
            print("\n[DRY RUN] " "DB에는 저장하지 않았습니다.")
            return

        save_quality(
            conn,
            quality_rows,
        )

        verify_db(conn)

        print("\nA4-4 완료")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
