from pathlib import Path

import pandas as pd

from roleA.common.db import get_conn

ROOT_DIR = Path(__file__).resolve().parents[2]

HOTSPOT_PATH = ROOT_DIR / "roleA" / "data" / "yongsan_hotspots.csv"

EXPECTED_COUNT = 11


def main():

    df = pd.read_csv(
        HOTSPOT_PATH,
        encoding="utf-8-sig",
    )

    print(
        "로컬 hotspot:",
        len(df),
    )

    required = {
        "code",
        "name",
        "category",
        "longitude",
        "latitude",
    }

    missing = required - set(df.columns)

    if missing:
        raise ValueError(f"필수 컬럼 없음: {missing}")

    if len(df) != EXPECTED_COUNT:
        raise ValueError(f"hotspot이 {EXPECTED_COUNT}개가 아닙니다: " f"{len(df)}")

    if df["code"].duplicated().any():
        raise ValueError("중복 hotspot code가 있습니다.")

    print("\n=== 적재 대상 ===")

    print(
        df[
            [
                "code",
                "name",
                "category",
                "longitude",
                "latitude",
            ]
        ].to_string(index=False)
    )

    conn = get_conn()

    try:

        with conn.cursor() as cur:

            for row in df.itertuples(index=False):

                cur.execute(
                    """
                    INSERT INTO hotspot (
                        code,
                        name,
                        category,
                        geom
                    )
                    VALUES (
                        %s,
                        %s,
                        %s,
                        ST_SetSRID(
                            ST_MakePoint(
                                %s,
                                %s
                            ),
                            4326
                        )::geography
                    )
                    ON CONFLICT (code)
                    DO UPDATE SET
                        name = EXCLUDED.name,
                        category = EXCLUDED.category,
                        geom = EXCLUDED.geom
                    """,
                    (
                        str(row.code),
                        row.name,
                        row.category,
                        float(row.longitude),
                        float(row.latitude),
                    ),
                )

        conn.commit()

        # ======================================
        # QC
        # ======================================

        with conn.cursor() as cur:

            cur.execute("""
                SELECT COUNT(*)
                FROM hotspot
                """)

            count = cur.fetchone()[0]

            print(
                "\nhotspot DB:",
                count,
            )

            cur.execute("""
                SELECT
                    code,
                    name,
                    category,
                    ST_X(geom::geometry) AS longitude,
                    ST_Y(geom::geometry) AS latitude
                FROM hotspot
                ORDER BY code
                """)

            rows = cur.fetchall()

            print("\n=== DB hotspot ===")

            for (
                code,
                name,
                category,
                longitude,
                latitude,
            ) in rows:

                print(
                    f"{code} / "
                    f"{name} / "
                    f"{category} / "
                    f"{longitude:.6f}, "
                    f"{latitude:.6f}"
                )

        if count != EXPECTED_COUNT:
            raise ValueError(f"DB hotspot이 {EXPECTED_COUNT}개가 아닙니다: " f"{count}")

        print("\nhotspot 적재 완료")

    except Exception:

        conn.rollback()

        print("\n오류 발생 → rollback")

        raise

    finally:

        conn.close()


if __name__ == "__main__":
    main()
