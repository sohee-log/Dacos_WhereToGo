from roleA.common.db import get_conn


def main():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public'
                ORDER BY table_name;
            """)

            print("DB 연결 성공!")
            print("=== 현재 테이블 ===")

            for row in cur.fetchall():
                print(row[0])


if __name__ == "__main__":
    main()
