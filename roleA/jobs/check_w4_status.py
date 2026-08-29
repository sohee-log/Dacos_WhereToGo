from roleA.common.db import get_conn


def count(cur, sql):
    cur.execute(sql)
    return cur.fetchone()[0]


def main():
    conn = get_conn()

    try:
        with conn.cursor() as cur:

            print("=== W4 DB 상태 ===")

            print("POI 전체:", count(cur, "SELECT COUNT(*) FROM poi"))

            print("T1:", count(cur, "SELECT COUNT(*) FROM poi WHERE tier = 1"))

            print(
                "commercial_area_id 있음:",
                count(
                    cur,
                    """
                    SELECT COUNT(*)
                    FROM poi
                    WHERE commercial_area_id IS NOT NULL
                    """,
                ),
            )

            print(
                "segment_affinity 행 수:",
                count(cur, "SELECT COUNT(*) FROM segment_affinity"),
            )

            print(
                "quality_score 있음:",
                count(
                    cur,
                    """
                    SELECT COUNT(*)
                    FROM poi
                    WHERE quality_score IS NOT NULL
                    """,
                ),
            )

            print(
                "tag_vector 있음:",
                count(
                    cur,
                    """
                    SELECT COUNT(*)
                    FROM poi
                    WHERE tag_vector IS NOT NULL
                    """,
                ),
            )

            print("review_chunk 전체:", count(cur, "SELECT COUNT(*) FROM review_chunk"))

            print(
                "review_chunk embedding 있음:",
                count(
                    cur,
                    """
                    SELECT COUNT(*)
                    FROM review_chunk
                    WHERE embedding IS NOT NULL
                    """,
                ),
            )

            print(
                "attr 추출 완료 T1:",
                count(
                    cur,
                    """
                    SELECT COUNT(*)
                    FROM poi
                    WHERE tier = 1
                      AND attr_extracted_at IS NOT NULL
                    """,
                ),
            )

            print(
                "T1 confidence >= 0.5:",
                count(
                    cur,
                    """
                    SELECT COUNT(*)
                    FROM poi
                    WHERE tier = 1
                      AND attr_confidence >= 0.5
                    """,
                ),
            )

    finally:
        conn.close()


if __name__ == "__main__":
    main()
