from roleA.common.db import get_conn


def print_table_schema(cur, table_name):

    print(f"\n=== {table_name} 스키마 ===")

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
        (table_name,),
    )

    rows = cur.fetchall()

    for column_name, data_type, is_nullable in rows:
        print(f"{column_name:25} " f"{data_type:25} " f"nullable={is_nullable}")


def main():

    conn = get_conn()

    try:

        with conn.cursor() as cur:

            # ----------------------------------
            # hotspot
            # ----------------------------------

            print_table_schema(
                cur,
                "hotspot",
            )

            cur.execute("""
                SELECT COUNT(*)
                FROM hotspot
                """)

            print(
                "\nhotspot 전체:",
                cur.fetchone()[0],
            )

            cur.execute("""
                SELECT *
                FROM hotspot
                LIMIT 5
                """)

            rows = cur.fetchall()

            print("\n=== hotspot 샘플 5건 ===")

            for row in rows:
                print(row)

            # ----------------------------------
            # poi의 hotspot 관련 컬럼 확인
            # ----------------------------------

            print_table_schema(
                cur,
                "poi",
            )

            cur.execute("""
                SELECT
                    COUNT(*) AS total,
                    COUNT(hotspot_code) AS mapped
                FROM poi
                """)

            total, mapped = cur.fetchone()

            print(
                "\nPOI 전체:",
                total,
            )

            print(
                "현재 hotspot_code 있음:",
                mapped,
            )

            print("\n=== hotspot geometry 타입 ===")

            cur.execute("""
                SELECT
                    f_geometry_column,
                    type,
                    srid
                FROM geometry_columns
                WHERE f_table_schema = 'public'
                  AND f_table_name = 'hotspot'
                """)

            for row in cur.fetchall():
                print(row)

            print("\n=== hotspot geom 실제 타입 ===")

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
                AND c.relname = 'hotspot'
                AND a.attname = 'geom'
                AND a.attnum > 0
                AND NOT a.attisdropped
                """)

            print(cur.fetchone())

    finally:
        conn.close()


if __name__ == "__main__":
    main()
