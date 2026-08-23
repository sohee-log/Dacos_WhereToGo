from roleA.common.db import get_conn


def main():

    conn = get_conn()

    try:

        with conn.cursor() as cur:

            # 현재 데이터 수
            cur.execute("""
                SELECT COUNT(*)
                FROM review_chunk
                """)

            print(
                "review_chunk 전체:",
                cur.fetchone()[0],
            )

            # 실제 스키마 확인
            cur.execute("""
                SELECT
                    column_name,
                    data_type,
                    is_nullable
                FROM information_schema.columns
                WHERE table_name = 'review_chunk'
                ORDER BY ordinal_position
                """)

            print("\n=== review_chunk 스키마 ===")

            for row in cur.fetchall():
                print(row)

            # tier 1 확인
            cur.execute("""
                SELECT COUNT(*)
                FROM poi
                WHERE tier = 1
                """)

            print(
                "\nTier 1 POI:",
                cur.fetchone()[0],
            )

            # 아직 리뷰 없는 Tier 1
            cur.execute("""
                SELECT COUNT(*)
                FROM poi p
                WHERE p.tier = 1
                  AND NOT EXISTS (
                      SELECT 1
                      FROM review_chunk r
                      WHERE r.poi_id = p.poi_id
                  )
                """)

            print(
                "리뷰 없는 Tier 1:",
                cur.fetchone()[0],
            )

    finally:

        conn.close()


if __name__ == "__main__":
    main()
