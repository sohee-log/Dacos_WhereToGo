from pathlib import Path

import pandas as pd

from roleA.common.db import get_conn

ROOT_DIR = Path(__file__).resolve().parents[2]

SELECTION_PATH = ROOT_DIR / "roleA" / "data" / "t1_selection_w3.csv"

EXPECTED_T1 = 800


def main():

    selected = pd.read_csv(
        SELECTION_PATH,
        encoding="utf-8-sig",
        low_memory=False,
    )

    selected_ids = selected["poi_id"].astype(str).drop_duplicates().tolist()

    print(
        "W3 T1 선택 파일:",
        len(selected),
    )

    print(
        "고유 poi_id:",
        len(selected_ids),
    )

    if len(selected_ids) != EXPECTED_T1:
        raise ValueError(f"T1이 {EXPECTED_T1}개가 아닙니다: " f"{len(selected_ids)}")

    conn = get_conn()

    # ==========================================
    # 선택된 800개가 실제 DB에 모두 존재하는지 확인
    # ==========================================

    with conn.cursor() as cur:

        cur.execute(
            """
            SELECT poi_id
            FROM poi
            WHERE poi_id = ANY(%s)
            """,
            (selected_ids,),
        )

        existing_ids = {row[0] for row in cur.fetchall()}

    missing_ids = [poi_id for poi_id in selected_ids if poi_id not in existing_ids]

    print(
        "DB에 존재하는 선택 POI:",
        len(existing_ids),
    )

    print(
        "DB에 없는 선택 POI:",
        len(missing_ids),
    )

    if missing_ids:

        print("\n=== DB에 없는 POI ===")

        missing_rows = selected[selected["poi_id"].astype(str).isin(missing_ids)]

        print(
            missing_rows[
                [
                    "poi_id",
                    "name",
                    "dong",
                    "category_l1",
                    "relevant_count",
                ]
            ].to_string(index=False)
        )

        raise ValueError("DB에 없는 POI가 있으므로 " "tier 변경을 중단합니다.")

    try:

        with conn.cursor() as cur:

            # ----------------------------------
            # 현재 T1은 우선 T2로 내림
            # ----------------------------------
            cur.execute("""
                UPDATE poi
                SET tier = 2,
                    updated_at = NOW()
                WHERE tier = 1
                """)

            old_demoted = cur.rowcount

            print(
                "기존 T1 → T2:",
                old_demoted,
            )

            # ----------------------------------
            # 새 W3 T1 800개 지정
            # ----------------------------------
            cur.execute(
                """
                UPDATE poi
                SET tier = 1,
                    updated_at = NOW()
                WHERE poi_id = ANY(%s)
                """,
                (selected_ids,),
            )

            promoted = cur.rowcount

            print(
                "새 T1 지정:",
                promoted,
            )

            if promoted != EXPECTED_T1:
                raise ValueError(
                    "DB에서 실제 변경된 POI가 "
                    f"{EXPECTED_T1}개가 아닙니다: "
                    f"{promoted}"
                )

            # ----------------------------------
            # QC
            # ----------------------------------
            cur.execute("""
                SELECT tier, COUNT(*)
                FROM poi
                GROUP BY tier
                ORDER BY tier
                """)

            counts = cur.fetchall()

            print("\n=== 변경 후 tier 분포 ===")

            for tier, count in counts:
                print(f"Tier {tier}: {count}")

            cur.execute("""
                SELECT COUNT(*)
                FROM poi
                WHERE tier = 1
                """)

            t1_count = cur.fetchone()[0]

            if t1_count != EXPECTED_T1:
                raise ValueError(f"최종 T1 수 오류: {t1_count}")

        conn.commit()

        print("\nW3 T1 적용 완료")

    except Exception:

        conn.rollback()

        print("\n오류 발생 → 전체 rollback")

        raise

    finally:

        conn.close()


if __name__ == "__main__":
    main()
