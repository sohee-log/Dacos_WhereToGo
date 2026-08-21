from roleA.common.db import get_conn


def main():

    conn = get_conn()

    try:
        with conn.cursor() as cur:

            print("=== admin_dong 스키마 ===")

            cur.execute("""
                SELECT
                    column_name,
                    data_type,
                    is_nullable
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'admin_dong'
                ORDER BY ordinal_position
                """)

            for row in cur.fetchall():
                print(row)

            cur.execute("""
                SELECT COUNT(*)
                FROM admin_dong
                """)

            print(
                "\nadmin_dong 전체:",
                cur.fetchone()[0],
            )

            print("\n=== 샘플 5건 ===")

            cur.execute("""
                SELECT *
                FROM admin_dong
                LIMIT 5
                """)

            for row in cur.fetchall():
                print(row)

            print("\n=== geom 실제 타입 ===")

            cur.execute("""
                SELECT
                    a.attname,
                    pg_catalog.format_type(
                        a.atttypid,
                        a.atttypmod
                    )
                FROM pg_attribute a
                JOIN pg_class c
                  ON a.attrelid = c.oid
                JOIN pg_namespace n
                  ON c.relnamespace = n.oid
                WHERE n.nspname = 'public'
                  AND c.relname = 'admin_dong'
                  AND a.attname = 'geom'
                  AND a.attnum > 0
                  AND NOT a.attisdropped
                """)

            print(cur.fetchone())

    finally:
        conn.close()


if __name__ == "__main__":
    main()
