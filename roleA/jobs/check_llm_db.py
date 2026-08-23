from roleA.common.db import get_conn

TABLES = [
    "poi",
    "review_chunk",
]


def main():
    conn = get_conn()

    try:
        with conn.cursor() as cur:
            for table in TABLES:
                print(f"\n=== {table} ===")

                cur.execute(
                    """
                    SELECT
                        column_name,
                        data_type,
                        is_nullable
                    FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name = %s
                    ORDER BY ordinal_position
                    """,
                    (table,),
                )

                for row in cur.fetchall():
                    print(row)
            print("\n=== A3-2 저장 현황 ===")

            cur.execute("""
                SELECT COUNT(*)
                FROM poi
                WHERE tier = 1
                AND attr_extracted_at IS NOT NULL
                """)

            print(
                "추출 완료 T1:",
                cur.fetchone()[0],
            )

            cur.execute("""
                SELECT
                    poi_id,
                    name,
                    noise_level,
                    purpose_tags,
                    atmosphere_tags,
                    sentiment_score,
                    review_count,
                    attr_confidence,
                    attr_extracted_at
                FROM poi
                WHERE tier = 1
                AND attr_extracted_at IS NOT NULL
                ORDER BY attr_extracted_at DESC
                LIMIT 5
                """)

            for row in cur.fetchall():
                print(row)

            cur.execute("""
                SELECT COUNT(*)
                FROM review_chunk
                """)

            print(
                "review_chunk 전체:",
                cur.fetchone()[0],
            )

    finally:
        conn.close()


if __name__ == "__main__":
    main()
