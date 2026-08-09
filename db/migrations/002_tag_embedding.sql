-- ============================================================================
-- 002 — 태그 임베딩 (온보딩 taste_vector의 재료)
--
-- ⚠️ 공동 소유 영역이다. 초안은 B가 쓰되 **PR + 3인 리뷰**로 반영한다.
--    기존 테이블을 바꾸지 않는다. 추가만 한다.
--
-- 왜 필요한가
--   온보딩은 취향 태그를 받아 `user_profile.taste_vector`를 만들어야 한다
--   (ROLE_B §5.1 · W4 B4-5). 그런데 **임베딩 모델을 서버에 올릴 수 없다** —
--   bge-m3는 2GB고 Render Free 메모리에 들어가지 않는다 (ROLE_B §1.2).
--
--   다행히 온보딩 태그는 유한 집합이다. 분위기 10종 + 목적 6종 = 16행.
--   A가 배치로 한 번 임베딩해 두면 온라인에서는 **평균만 내면 된다.**
--   `query_vector_cache`(72행)와 같은 발상이다 (PLAN.md §11.3).
--
--   이 테이블이 비어 있어도 서비스는 돈다. `taste_vector`가 NULL이 되고
--   `taste_similarity`가 중립(0.5)으로 계산된다. 취향 축 하나가 쉬는 것뿐이다.
--
-- A가 채울 것 (16행)
--   INSERT INTO tag_embedding (tag, kind, embedding) VALUES ('조용한','atmosphere', ...);
--   어휘는 roleB/app/constants.py 의 ATMOSPHERE_TAGS · PURPOSE_TAGS 와 정확히 같아야 한다.
--   임의로 늘리면 온보딩에서 조회되지 않고 조용히 빠진다.
--
-- 적용:
--   psql "$DATABASE_URL" -f db/migrations/002_tag_embedding.sql
-- ============================================================================

BEGIN;

CREATE TABLE IF NOT EXISTS tag_embedding (
    tag         TEXT PRIMARY KEY,
    kind        TEXT NOT NULL CHECK (kind IN ('atmosphere', 'purpose')),
    embedding   HALFVEC(1024) NOT NULL,
    created_at  TIMESTAMPTZ DEFAULT now()
);

-- 16행짜리 테이블이라 인덱스가 필요 없다. 벡터 검색 대상도 아니다
-- (POI를 찾는 것은 poi.tag_vector의 HNSW가 한다).

COMMIT;

-- ============================================================================
-- 적용 확인
-- ============================================================================
-- SELECT kind, count(*) FROM tag_embedding GROUP BY kind;   -- atmosphere 10 / purpose 6
-- SELECT vector_dims(embedding::vector) FROM tag_embedding LIMIT 1;   -- 1024
