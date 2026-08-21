import argparse

from roleA.common.db import get_conn

MAX_DISTANCE_M = 1000.0


def main():

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--dry-run",
        action="store_true",
    )

    args = parser.parse_args()

    conn = get_conn()

    try:

        with conn.cursor() as cur:

            # ==========================================
            # 기본 개수 확인
            # ==========================================

            cur.execute("""
                SELECT COUNT(*)
                FROM poi
                """)

            poi_count = cur.fetchone()[0]

            cur.execute("""
                SELECT COUNT(*)
                FROM hotspot
                """)

            hotspot_count = cur.fetchone()[0]

            print(
                "POI 전체:",
                poi_count,
            )

            print(
                "hotspot 전체:",
                hotspot_count,
            )

            if hotspot_count == 0:
                raise ValueError("hotspot 테이블이 비어 있습니다.")

            # ==========================================
            # 최근접 hotspot 계산
            # ==========================================
            #
            # POI 하나당 hotspot 11개와의 거리를 계산하고
            # 가장 가까운 1개만 선택
            #
            # geography 거리 단위 = meter
            # ==========================================

            cur.execute(
                """
                WITH nearest AS (
                    SELECT
                        p.poi_id,
                        n.code AS hotspot_code,
                        n.distance_m
                    FROM poi p
                    CROSS JOIN LATERAL (
                        SELECT
                            h.code,
                            ST_Distance(
                                p.geom::geography,
                                h.geom
                            ) AS distance_m
                        FROM hotspot h
                        ORDER BY
                            ST_Distance(
                                p.geom::geography,
                                h.geom
                            )
                        LIMIT 1
                    ) n
                )
                SELECT
                    COUNT(*) AS total,
                    COUNT(*) FILTER (
                        WHERE distance_m <= %s
                    ) AS within_1km,
                    COUNT(*) FILTER (
                        WHERE distance_m > %s
                    ) AS over_1km,
                    MIN(distance_m),
                    AVG(distance_m),
                    MAX(distance_m)
                FROM nearest
                """,
                (
                    MAX_DISTANCE_M,
                    MAX_DISTANCE_M,
                ),
            )

            (
                total,
                within_1km,
                over_1km,
                min_distance,
                avg_distance,
                max_distance,
            ) = cur.fetchone()

            print("\n=== 매핑 사전 QC ===")

            print(
                "최근접 계산 POI:",
                total,
            )

            print(
                "1km 이내:",
                within_1km,
            )

            print(
                "1km 초과:",
                over_1km,
            )

            print(
                "매핑률:",
                f"{within_1km / total * 100:.2f}%" if total else "0.00%",
            )

            print(
                "최소 거리:",
                f"{min_distance:.1f} m",
            )

            print(
                "평균 거리:",
                f"{avg_distance:.1f} m",
            )

            print(
                "최대 거리:",
                f"{max_distance:.1f} m",
            )

            # ==========================================
            # dry-run이면 DB 변경 없이 종료
            # ==========================================

            if args.dry_run:

                print("\n[DRY RUN] DB 업데이트 생략")

                return

            # ==========================================
            # 실제 hotspot_code 업데이트
            # ==========================================

            cur.execute(
                """
                WITH nearest AS (
                    SELECT
                        p.poi_id,
                        n.code AS hotspot_code,
                        n.distance_m
                    FROM poi p
                    CROSS JOIN LATERAL (
                        SELECT
                            h.code,
                            ST_Distance(
                                p.geom::geography,
                                h.geom
                            ) AS distance_m
                        FROM hotspot h
                        ORDER BY
                            ST_Distance(
                                p.geom::geography,
                                h.geom
                            )
                        LIMIT 1
                    ) n
                )
                UPDATE poi p
                SET
                    hotspot_code = CASE
                        WHEN n.distance_m <= %s
                        THEN n.hotspot_code
                        ELSE NULL
                    END,
                    updated_at = NOW()
                FROM nearest n
                WHERE p.poi_id = n.poi_id
                """,
                (MAX_DISTANCE_M,),
            )

            updated = cur.rowcount

            print(
                "\n업데이트 POI:",
                updated,
            )

        conn.commit()

        # ==========================================
        # 최종 QC
        # ==========================================

        with conn.cursor() as cur:

            cur.execute("""
                SELECT
                    COUNT(*) AS total,
                    COUNT(hotspot_code) AS mapped,
                    COUNT(*) - COUNT(hotspot_code) AS unmapped
                FROM poi
                """)

            total, mapped, unmapped = cur.fetchone()

            print("\n=== 최종 QC ===")

            print(
                "POI 전체:",
                total,
            )

            print(
                "hotspot 매핑:",
                mapped,
            )

            print(
                "NULL:",
                unmapped,
            )

            print(
                "매핑률:",
                f"{mapped / total * 100:.2f}%" if total else "0.00%",
            )

            # hotspot별 연결 POI 수
            cur.execute("""
                SELECT
                    h.code,
                    h.name,
                    COUNT(p.poi_id) AS poi_count
                FROM hotspot h
                LEFT JOIN poi p
                  ON p.hotspot_code = h.code
                GROUP BY
                    h.code,
                    h.name
                ORDER BY
                    poi_count DESC,
                    h.code
                """)

            print("\n=== hotspot별 매핑 POI ===")

            for (
                code,
                name,
                count,
            ) in cur.fetchall():

                print(f"{code} / " f"{name} / " f"{count}")

        print("\nPOI ↔ hotspot 매핑 완료")

    except Exception:

        conn.rollback()

        print("\n오류 발생 → rollback")

        raise

    finally:

        conn.close()


if __name__ == "__main__":
    main()
