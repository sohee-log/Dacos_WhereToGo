import json
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]

OLD_PATH = ROOT_DIR / "roleA" / "data" / "review_candidates_raw.jsonl"

NEW_PATH = ROOT_DIR / "roleA" / "data" / "review_candidates_w4.jsonl"

OUTPUT_PATH = ROOT_DIR / "roleA" / "data" / "review_candidates_merged.jsonl"

MAX_RESULTS = 15


def load_jsonl(path):

    rows = {}

    with open(
        path,
        "r",
        encoding="utf-8",
    ) as f:

        for line in f:

            line = line.strip()

            if not line:
                continue

            row = json.loads(line)

            rows[str(row["poi_id"])] = row

    return rows


def main():

    old_rows = load_jsonl(OLD_PATH)

    new_rows = load_jsonl(NEW_PATH)

    all_ids = sorted(set(old_rows) | set(new_rows))

    merged_rows = []

    for poi_id in all_ids:

        old = old_rows.get(poi_id)

        new = new_rows.get(poi_id)

        # 최신 W4 레코드를 기본 메타데이터로 사용
        base = dict(new) if new is not None else dict(old)

        items = []
        seen_links = set()

        # W4 결과를 먼저 사용하고,
        # 부족한 리뷰는 W3 결과로 보완
        for source in [
            new,
            old,
        ]:

            if source is None:
                continue

            for item in source.get(
                "items",
                [],
            ):

                link = str(
                    item.get(
                        "link",
                        "",
                    )
                ).strip()

                if not link:
                    continue

                if link in seen_links:
                    continue

                seen_links.add(link)
                items.append(item)

                if len(items) >= MAX_RESULTS:
                    break

            if len(items) >= MAX_RESULTS:
                break

        base["items"] = items
        base["result_count"] = len(items)

        merged_rows.append(base)

    with open(
        OUTPUT_PATH,
        "w",
        encoding="utf-8",
    ) as f:

        for row in merged_rows:

            f.write(
                json.dumps(
                    row,
                    ensure_ascii=False,
                )
                + "\n"
            )

    counts = [row["result_count"] for row in merged_rows]

    print(
        "전체 POI:",
        len(merged_rows),
    )

    print(
        "리뷰 >= 1:",
        sum(n >= 1 for n in counts),
    )

    print(
        "리뷰 >= 3:",
        sum(n >= 3 for n in counts),
    )

    print(
        "리뷰 >= 5:",
        sum(n >= 5 for n in counts),
    )

    print(
        "리뷰 >= 8:",
        sum(n >= 8 for n in counts),
    )

    print(
        "리뷰 >= 10:",
        sum(n >= 10 for n in counts),
    )

    print(
        "리뷰 = 15:",
        sum(n == 15 for n in counts),
    )

    print(
        "리뷰 = 0:",
        sum(n == 0 for n in counts),
    )

    print(
        "\n저장:",
        OUTPUT_PATH,
    )


if __name__ == "__main__":
    main()
