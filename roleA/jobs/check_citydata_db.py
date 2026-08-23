from roleA.common.db import get_conn

TABLES = [
    "hotspot_snapshot",
    "hotspot_latest",
]


def print_schema(cur, table_name):

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

    for (
        column_name,
        data_type,
        is_nullable,
    ) in rows:

        print(f"{column_name:25} " f"{data_type:25} " f"nullable={is_nullable}")

    cur.execute(f"""
        SELECT COUNT(*)
        FROM {table_name}
        """)

    print(
        f"\n{table_name} 전체:",
        cur.fetchone()[0],
    )


def main():

    conn = get_conn()

    try:

        with conn.cursor() as cur:

            for table in TABLES:
                print_schema(
                    cur,
                    table,
                )

            # 최신 도시데이터 확인
            print("\n=== hotspot_latest 최신 데이터 ===")

            cur.execute("""
                SELECT
                    hotspot_code,
                    hotspot_name,
                    observed_at,
                    congest_lvl,
                    ppltn_min,
                    ppltn_max
                FROM hotspot_latest
                ORDER BY hotspot_code
                """)

            for row in cur.fetchall():
                print(row)

    finally:
        conn.close()


if __name__ == "__main__":
    main()
