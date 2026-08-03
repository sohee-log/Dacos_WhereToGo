# db — 스키마 (공동 소유)

세 역할이 모두 읽고 쓰는 영역이다. **변경은 PR + 3인 리뷰**를 거친다.
혼자 컬럼을 바꾸면 다른 역할의 코드가 조용히 깨진다.

## 적용

```bash
# 로컬 (PostGIS + pgvector)
docker run -d --name wheretogo-db -p 5432:5432 \
  -e POSTGRES_PASSWORD=devpass -e POSTGRES_DB=wheretogo \
  postgis/postgis:16-3.4

psql "postgresql://postgres:devpass@localhost:5432/wheretogo" \
  -f db/migrations/001_init.sql

# prod (Supabase)
psql "$DATABASE_URL" -f db/migrations/001_init.sql
```

`postgis/postgis` 이미지에는 pgvector가 없을 수 있다. `CREATE EXTENSION vector`가
실패하면 `pgvector/pgvector:pg16`으로 바꾸고 PostGIS를 따로 설치하거나,
두 확장이 모두 들어 있는 이미지를 쓴다. **W1에 어느 쪽으로 갈지 확정해 팀에 공유한다.**

## 확인

```sql
SELECT extname, extversion FROM pg_extension WHERE extname IN ('postgis','vector');
SELECT is_open_at('{"mon":["10:00","22:00"]}'::jsonb, now());
SELECT is_open_at(NULL, now());   -- TRUE 여야 한다
\dt
```

## HALFVEC 주의

임베딩 컬럼은 `HALFVEC(1024)`(2바이트/차원)를 쓴다. `VECTOR`(4바이트) 대비 용량이
절반이고, 이게 Supabase Free 500MB 안에 들어가기 위한 전제다.

**pgvector 0.7.0 이상이 필요하다.** 버전이 낮으면 `001_init.sql` 안의
`HALFVEC(1024)` → `VECTOR(1024)`, `halfvec_cosine_ops` → `vector_cosine_ops`로
바꿔야 한다. 적용 전에 버전부터 확인할 것.

## 테이블

| 테이블 | 채우는 쪽 | 읽는 쪽 |
|---|---|---|
| `admin_dong`, `commercial_area`, `hotspot` | A | A |
| `poi` | A | B |
| `review_chunk` | A | B |
| `segment_affinity` | A | B |
| `hotspot_snapshot` (+ `hotspot_latest` 뷰) | A (15분 폴링) | B |
| `query_vector_cache` | A | B |
| `user_profile`, `explanation_cache`, `recommendation_log` | B | B, C |

## 설계상 의도적인 것 (건드리기 전에 읽을 것)

**`poi.hotspot_code`는 NULL을 허용한다.**
실시간 도시데이터 지점 반경 1km 밖이라는 뜻이다. NOT NULL로 바꾸거나 기본값을
채우면 엔진이 실시간 항을 "0점"으로 해석해 해당 POI들이 전멸한다.

**`is_open_at()`은 영업시간을 모를 때 TRUE를 반환한다.**
정보가 없다는 이유로 후보에서 떨어뜨리면 커버리지가 무너진다. 닫혀 있다고
단정하지 않는다.

**`idx_poi_pending`에 `mention_count DESC`가 붙어 있다.**
LLM 배치가 쿼터 소진으로 중간에 끊겨도 유명한 곳부터 처리되도록 하기 위함이다.

**`recommendation_log.candidates`에 노출만 되고 선택되지 않은 후보도 남긴다.**
6주 안에 랭킹 모델을 학습하지는 않지만, 이 구조가 없으면 나중에 로그를 아무리
모아도 학습이 불가능하다.
