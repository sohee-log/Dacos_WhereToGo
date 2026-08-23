from roleA.common.db import get_conn


def main():
    conn = get_conn()

    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    poi_id,
                    name,
                    dong,
                    category_l1,
                    category_l2,
                    mention_count
                FROM poi
                WHERE tier = 1
                ORDER BY mention_count DESC NULLS LAST
                """)

            rows = cur.fetchall()

        print("=== T1 전체 ===")
        print(len(rows))

        print("\n=== 이름 1~2글자 ===")

        for row in rows:
            name = (row[1] or "").strip()

            if len(name) <= 2:
                print(row)

        generic_words = {
            "맛집",
            "카페",
            "식당",
            "음식점",
            "술집",
            "주점",
            "매장",
            "스토어",
            "쇼핑",
        }

        print("\n=== 일반명사 의심 POI ===")

        for row in rows:
            name = (row[1] or "").strip()

            if name in generic_words:
                print(row)

        print("\n=== mention_count 상위 30개 ===")

        for row in rows[:30]:
            print(row)

    finally:
        conn.close()


if __name__ == "__main__":
    main()
