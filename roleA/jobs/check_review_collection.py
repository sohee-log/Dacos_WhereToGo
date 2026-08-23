import json
from pathlib import Path

from roleA.common.db import get_conn

ROOT_DIR = Path(__file__).resolve().parents[2]

JSONL_PATH = ROOT_DIR / "roleA" / "data" / "review_candidates_raw.jsonl"


def main():

    records = []

    with JSONL_PATH.open(
        "r",
        encoding="utf-8",
    ) as f:

        for line in f:
            line = line.strip()

            if line:
                records.append(json.loads(line))

    print("JSONL POI:", len(records))

    ids = [str(r["poi_id"]) for r in records]

    conn = get_conn()

    try:

        with conn.cursor() as cur:

            cur.execute(
                """
                SELECT
                    poi_id,
                    name,
                    mention_count
                FROM poi
                WHERE poi_id = ANY(%s)
                ORDER BY name
                """,
                (ids,),
            )

            rows = cur.fetchall()

    finally:
        conn.close()

    print("DB 매칭 POI:", len(rows))

    print("\n=== DB mention_count ===")

    for poi_id, name, mention_count in rows:
        print(
            poi_id,
            "/",
            name,
            "/",
            mention_count,
        )


if __name__ == "__main__":
    main()
