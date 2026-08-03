-- ============================================================================
-- WhereToGo — 초기 스키마
--
-- 요구사항: PostgreSQL 15+ / PostGIS 3.x / pgvector 0.7.0 이상
--   pgvector 0.7 미만이면 HALFVEC 를 쓸 수 없다. 그 경우 아래 두 가지를 바꾼다.
--     HALFVEC(1024)          -> VECTOR(1024)
--     halfvec_cosine_ops     -> vector_cosine_ops
--   다만 저장 용량이 두 배가 되어 Supabase Free 500MB 여유가 줄어든다.
--   먼저 SELECT extversion FROM pg_extension WHERE extname='vector'; 로 확인할 것.
--
-- 적용:
--   psql "$DATABASE_URL" -f db/migrations/001_init.sql
-- ============================================================================

BEGIN;

CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS vector;

-- ============================================================================
-- 1. 지오 참조 테이블 (A가 적재)
-- ============================================================================

-- 행정동 경계. poi.dong 공간조인용
CREATE TABLE IF NOT EXISTS admin_dong (
    adm_cd      TEXT PRIMARY KEY,
    adm_nm      TEXT NOT NULL,
    zone        TEXT,                       -- itaewon / yongsan_stn / huam / ichon / cheongpa
    geom        GEOMETRY(MULTIPOLYGON, 4326) NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_admin_dong_geom ON admin_dong USING GIST (geom);

-- 상권 영역 폴리곤. poi.commercial_area_id 공간조인용
-- 이게 없으면 상권분석 추정매출(segment_affinity)을 POI에 연결할 방법이 없다
CREATE TABLE IF NOT EXISTS commercial_area (
    commercial_area_id  TEXT PRIMARY KEY,
    name                TEXT,
    area_type           TEXT,               -- 골목상권 / 발달상권 / 전통시장 / 관광특구
    geom                GEOMETRY(MULTIPOLYGON, 4326) NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_comm_area_geom ON commercial_area USING GIST (geom);

-- 서울시 실시간 도시데이터 121장소 중 용산 해당 지점 (5~7개)
-- 목록은 '서울시 주요 121장소 목록.xlsx' 에서 확정한다
CREATE TABLE IF NOT EXISTS hotspot (
    code        TEXT PRIMARY KEY,           -- 예: POI014
    name        TEXT NOT NULL,              -- 예: 이태원 관광특구
    category    TEXT,
    geom        GEOGRAPHY(POINT, 4326) NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_hotspot_geom ON hotspot USING GIST (geom);

-- ============================================================================
-- 2. POI — 추천 대상 백본 (A가 적재, B가 읽음)
-- ============================================================================

CREATE TABLE IF NOT EXISTS poi (
    poi_id              TEXT PRIMARY KEY,   -- 상가업소번호 / TourAPI는 'tour_' 접두
    name                TEXT NOT NULL,
    category_l1         TEXT,               -- 음식 / 카페 / 문화 / 쇼핑 / 자연
    category_l2         TEXT,               -- 상권분석 업종코드와 조인 가능해야 함
    geom                GEOGRAPHY(POINT, 4326) NOT NULL,

    -- 지오 태깅 (A: W2 게이트 = zone NULL 0건)
    dong                TEXT,
    zone                TEXT,
    commercial_area_id  TEXT REFERENCES commercial_area(commercial_area_id),
    hotspot_code        TEXT REFERENCES hotspot(code),  -- NULL = 핫스팟 1km 밖. 0으로 채우지 말 것

    business_hours      JSONB,              -- {"mon": ["10:00","22:00"], ...} NULL 허용

    -- LLM 배치로 추출하는 속성 (R3: 온라인에서 리뷰를 읽지 않기 위한 핵심)
    outdoor_exposure    REAL     DEFAULT 0.0 CHECK (outdoor_exposure BETWEEN 0 AND 1),
    group_capacity      INT      DEFAULT 4  CHECK (group_capacity > 0),
    noise_level         SMALLINT            CHECK (noise_level BETWEEN 1 AND 5),
    purpose_tags        TEXT[],             -- 고정 어휘 6종
    atmosphere_tags     TEXT[],             -- 고정 어휘 10종
    price_band          SMALLINT            CHECK (price_band BETWEEN 1 AND 4),
    wait_intensity      JSONB,
    tag_vector          HALFVEC(1024),      -- atmosphere+purpose 태그 임베딩 평균

    -- 품질 (별점 데이터가 없으므로 직접 산출 — PLAN.md §3.4.1)
    sentiment_score     REAL                CHECK (sentiment_score BETWEEN 0 AND 1),
    mention_count       INT      DEFAULT 0,
    review_count        INT      DEFAULT 0,
    quality_score       REAL,

    -- 운영 메타
    attr_confidence     REAL     DEFAULT 0.0 CHECK (attr_confidence BETWEEN 0 AND 1),
    tier                SMALLINT DEFAULT 3  CHECK (tier IN (1, 2, 3)),
    attr_extracted_at   TIMESTAMPTZ,        -- NULL = 미처리. 배치 체크포인트의 기준
    created_at          TIMESTAMPTZ DEFAULT now(),
    updated_at          TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_poi_geom    ON poi USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_poi_tagvec  ON poi USING hnsw (tag_vector halfvec_cosine_ops);
CREATE INDEX IF NOT EXISTS idx_poi_area    ON poi (commercial_area_id, category_l2);
CREATE INDEX IF NOT EXISTS idx_poi_hotspot ON poi (hotspot_code);
CREATE INDEX IF NOT EXISTS idx_poi_zone    ON poi (zone);

-- LLM 배치 체크포인트 전용. mention_count DESC 정렬이 붙는 이유는
-- 쿼터가 소진되어도 유명한 곳부터 처리되게 하기 위함이다
CREATE INDEX IF NOT EXISTS idx_poi_pending
    ON poi (tier, mention_count DESC)
    WHERE attr_extracted_at IS NULL;

-- ============================================================================
-- 3. 리뷰 청크 (A가 적재, B가 RAG 인용에 사용)
--    무료 DB 500MB 제약 때문에 POI당 최대 3청크로 압축한다
-- ============================================================================

CREATE TABLE IF NOT EXISTS review_chunk (
    chunk_id      BIGSERIAL PRIMARY KEY,
    poi_id        TEXT NOT NULL REFERENCES poi(poi_id) ON DELETE CASCADE,
    source        TEXT NOT NULL DEFAULT 'naver_blog',
    text          TEXT NOT NULL,            -- 인용용 발췌, 최대 300자
    embedding     HALFVEC(1024),
    is_sponsored  BOOLEAN NOT NULL DEFAULT FALSE,  -- 협찬글. 감성 집계에서 제외
    written_at    DATE,
    created_at    TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_chunk_poi ON review_chunk (poi_id);
CREATE INDEX IF NOT EXISTS idx_chunk_vec ON review_chunk USING hnsw (embedding halfvec_cosine_ops);

-- ============================================================================
-- 4. 세그먼트 선호도 (A가 적재, B가 읽음)
--    협업 필터링을 대체하는 개인화 근거. 서울시 상권분석 추정매출에서 산출
-- ============================================================================

CREATE TABLE IF NOT EXISTS segment_affinity (
    commercial_area_id  TEXT     NOT NULL,
    category_l2         TEXT     NOT NULL,
    gender              CHAR(1)  NOT NULL CHECK (gender IN ('M', 'F')),
    age_band            SMALLINT NOT NULL,           -- 5세 단위: 20, 25, 30 ...
    dow_type            SMALLINT NOT NULL CHECK (dow_type IN (0, 1)),   -- 0=평일 1=주말
    hour_band           SMALLINT NOT NULL CHECK (hour_band BETWEEN 0 AND 5), -- 4시간 단위
    affinity            REAL     NOT NULL CHECK (affinity BETWEEN 0 AND 1),
    sample_weight       REAL,                        -- 원본 표본 규모 (희소 셀 신뢰도)
    PRIMARY KEY (commercial_area_id, category_l2, gender, age_band, dow_type, hour_band)
);

-- ============================================================================
-- 5. 실시간 도시데이터 스냅샷 (A가 15분마다 폴링, B가 읽음)
--    사용자 요청마다 citydata API를 직접 호출하면 쿼터가 즉시 소진된다
-- ============================================================================

CREATE TABLE IF NOT EXISTS hotspot_snapshot (
    hotspot_code  TEXT        NOT NULL REFERENCES hotspot(code) ON DELETE CASCADE,
    observed_at   TIMESTAMPTZ NOT NULL,
    congest_lvl   TEXT,                     -- 여유 / 보통 / 약간 붐빔 / 붐빔
    ppltn_min     INT,
    ppltn_max     INT,
    age_rates     JSONB,                    -- {"20": 31.2, "30": 24.8, ...}
    male_rate     REAL,
    female_rate   REAL,
    weather       JSONB,                    -- TEMP, SENSIBLE_TEMP, PRECIPITATION, PM10, PM25, SUNSET ...
    fcst          JSONB,                    -- 12시간 예측 배열 (2시간 단위)
    PRIMARY KEY (hotspot_code, observed_at)
);

CREATE INDEX IF NOT EXISTS idx_snapshot_recent
    ON hotspot_snapshot (hotspot_code, observed_at DESC);

-- 지점별 최신 스냅샷. B는 이 뷰만 조회하면 된다
CREATE OR REPLACE VIEW hotspot_latest AS
SELECT DISTINCT ON (s.hotspot_code)
       s.hotspot_code, h.name AS hotspot_name,
       s.observed_at, s.congest_lvl, s.ppltn_min, s.ppltn_max,
       s.age_rates, s.male_rate, s.female_rate, s.weather, s.fcst
FROM hotspot_snapshot s
JOIN hotspot h ON h.code = s.hotspot_code
ORDER BY s.hotspot_code, s.observed_at DESC;

-- ============================================================================
-- 6. 사용자 (B가 씀)
-- ============================================================================

CREATE TABLE IF NOT EXISTS user_profile (
    user_id             TEXT PRIMARY KEY,
    gender              CHAR(1)  CHECK (gender IN ('M', 'F')),
    age_band            SMALLINT,                    -- 10 / 20 / 30 / 40 / 50 / 60
    taste_tags          TEXT[],
    taste_vector        HALFVEC(1024),               -- 온보딩 태그 임베딩 평균
    weather_sensitivity SMALLINT CHECK (weather_sensitivity BETWEEN 1 AND 3),
    created_at          TIMESTAMPTZ DEFAULT now()
);

-- ============================================================================
-- 7. 캐시 (무료 티어 운용의 핵심)
-- ============================================================================

-- 쿼리 벡터 사전계산: 목적 6 × 날씨 4 × 인원밴드 3 = 72행
-- 이게 있어야 임베딩 모델을 서버에 올리지 않고도 RAG가 돌아간다
CREATE TABLE IF NOT EXISTS query_vector_cache (
    purpose        TEXT     NOT NULL,
    weather_state  TEXT     NOT NULL,       -- 맑음 / 비 / 미세먼지나쁨 / 폭염한파
    party_band     SMALLINT NOT NULL CHECK (party_band BETWEEN 1 AND 3),
    query_text     TEXT     NOT NULL,
    embedding      HALFVEC(1024) NOT NULL,
    PRIMARY KEY (purpose, weather_state, party_band)
);

-- LLM 설명 캐시. 호출 전 반드시 여기를 먼저 조회한다
CREATE TABLE IF NOT EXISTS explanation_cache (
    cache_key   TEXT PRIMARY KEY,           -- sha256(purpose|party|weather|zone|top20_ids)
    payload     JSONB NOT NULL,
    hit_count   INT DEFAULT 0,
    created_at  TIMESTAMPTZ DEFAULT now()
);

-- ============================================================================
-- 8. 추천 로그 (B가 씀)
--    candidates 에 '노출됐지만 선택되지 않은 후보'까지 남겨야
--    나중에 랭킹 모델을 학습할 수 있다. 6주 안에 학습은 안 하지만 구조는 지금 만든다
-- ============================================================================

CREATE TABLE IF NOT EXISTS recommendation_log (
    log_id        BIGSERIAL PRIMARY KEY,
    user_id       TEXT REFERENCES user_profile(user_id) ON DELETE SET NULL,
    requested_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    context       JSONB NOT NULL,           -- 목적·인원·예산·좌표(격자)·날씨 스냅샷
    candidates    JSONB NOT NULL,           -- [{poi_id, rank, score, terms, shown}]
    clicked       TEXT[],
    selected      TEXT,
    feedback      SMALLINT CHECK (feedback BETWEEN 1 AND 5),
    explain_mode  TEXT CHECK (explain_mode IN ('llm', 'cache', 'template')),
    latency_ms    INT
);

CREATE INDEX IF NOT EXISTS idx_log_user ON recommendation_log (user_id, requested_at DESC);
CREATE INDEX IF NOT EXISTS idx_log_time ON recommendation_log (requested_at DESC);

-- ============================================================================
-- 9. 함수
-- ============================================================================

-- 영업시간 판정.
-- business_hours 가 없으면 TRUE 를 반환한다. 정보가 없다는 이유로 후보에서
-- 떨어뜨리면 커버리지가 무너지기 때문이다 (닫혀 있다고 단정하지 않는다).
CREATE OR REPLACE FUNCTION is_open_at(hours JSONB, ts TIMESTAMPTZ)
RETURNS BOOLEAN
LANGUAGE plpgsql
STABLE
PARALLEL SAFE
AS $$
DECLARE
    local_ts TIMESTAMP;
    dow_key  TEXT;
    rng      JSONB;
    open_t   TIME;
    close_t  TIME;
    now_t    TIME;
BEGIN
    IF hours IS NULL OR hours = '{}'::jsonb THEN
        RETURN TRUE;
    END IF;

    local_ts := ts AT TIME ZONE 'Asia/Seoul';
    dow_key  := (ARRAY['sun','mon','tue','wed','thu','fri','sat'])
                [EXTRACT(DOW FROM local_ts)::INT + 1];
    rng := hours -> dow_key;

    IF rng IS NULL
       OR jsonb_typeof(rng) <> 'array'
       OR jsonb_array_length(rng) < 2 THEN
        RETURN TRUE;
    END IF;

    open_t  := (rng ->> 0)::TIME;
    close_t := (rng ->> 1)::TIME;
    now_t   := local_ts::TIME;

    IF close_t <= open_t THEN               -- 자정을 넘겨 영업하는 경우
        RETURN now_t >= open_t OR now_t < close_t;
    END IF;

    RETURN now_t >= open_t AND now_t < close_t;
EXCEPTION WHEN OTHERS THEN
    RETURN TRUE;                            -- 형식이 깨져도 후보에서 떨구지 않는다
END;
$$;

-- updated_at 자동 갱신
CREATE OR REPLACE FUNCTION touch_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_poi_touch ON poi;
CREATE TRIGGER trg_poi_touch
    BEFORE UPDATE ON poi
    FOR EACH ROW EXECUTE FUNCTION touch_updated_at();

COMMIT;

-- ============================================================================
-- 적용 확인
-- ============================================================================
-- SELECT extname, extversion FROM pg_extension WHERE extname IN ('postgis','vector');
-- SELECT is_open_at('{"mon":["10:00","22:00"]}'::jsonb, now());
-- SELECT is_open_at(NULL, now());          -- TRUE 여야 한다
-- \dt
