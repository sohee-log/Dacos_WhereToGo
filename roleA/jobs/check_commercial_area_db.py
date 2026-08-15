from roleA.common.db import get_conn


def main():

    conn = get_conn()

    try:

        with conn.cursor() as cur:

            cur.execute("""
                SELECT COUNT(*)
                FROM commercial_area
                """)

            count = cur.fetchone()[0]

            print(
                "commercial_area 전체:",
                count,
            )

            cur.execute("""
                SELECT column_name, data_type
                FROM information_schema.columns
                WHERE table_name = 'commercial_area'
                ORDER BY ordinal_position
                """)

            print("\n=== commercial_area 스키마 ===")

            for row in cur.fetchall():
                print(row)

            cur.execute("""
                SELECT
                    f_geometry_column,
                    type,
                    srid
                FROM geometry_columns
                WHERE f_table_name = 'commercial_area'
                """)

            print("\n=== commercial_area geometry ===")

            for row in cur.fetchall():
                print(row)

            cur.execute("""
                SELECT *
                FROM commercial_area
                LIMIT 10
                """)

            rows = cur.fetchall()

            print("\n=== 샘플 ===")

            for row in rows:
                print(row)

    finally:

        conn.close()


if __name__ == "__main__":
    main()
