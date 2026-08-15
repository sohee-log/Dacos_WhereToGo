from roleA.common.db import get_conn


def main():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    poi_id,
                    name,
                    category_l1,
                    dong,
                    zone,
                    tier
                FROM poi
                ORDER BY updated_at DESC
                LIMIT 10;
            """)

            print("=== POI 확인 ===")

            for row in cur.fetchall():
                print(row)


if __name__ == "__main__":
    main()
