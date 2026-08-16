def pending_pois(conn, limit: int) -> list[str]:
    """attr_extracted_at IS NULL인 T1 POI만 반환한다."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT poi_id
            FROM poi
            WHERE tier = 1
              AND attr_extracted_at IS NULL
            ORDER BY mention_count DESC NULLS LAST
            LIMIT %s
            """,
            (limit,),
        )
        return [row[0] for row in cur.fetchall()]
