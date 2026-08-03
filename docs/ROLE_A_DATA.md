# ROLE A — 데이터 엔지니어링 작업 지시서

> **이 문서를 받은 LLM에게**
> 당신은 이 프로젝트의 **A 역할(데이터 엔지니어링)** 담당자로 작업한다.
> 이 문서만으로 작업이 가능하도록 필요한 계약·스키마·규칙이 모두 포함되어 있다.
> 아래 **§1 불변 규칙**을 위반하는 코드는 어떤 이유로도 작성하지 않는다.
> 작업 지시가 모호하면 §2 소유 범위를 기준으로 판단하고, 소유 밖이면 손대지 말고 해당 역할에 넘긴다.
> 전체 설계 배경은 같은 디렉터리의 `PLAN.md`에 있다. 판단이 갈리면 `PLAN.md`가 상위 문서다.

---

## 0. 프로젝트 한 줄

> **"지금의 나(나이·성향)와 지금의 상황(목적·인원·날씨·시간)에 맞는 용산의 장소를, 실제 리뷰 근거와 함께 3~5곳 추천한다."**

| 항목 | 값 |
|---|---|
| 대상 | 서울 용산구 전역 (16개 행정동), T1 커버리지 800 POI |
| 기간 | 6주 (W1~W6) |
| 예산 | **0원** — 결제수단 등록이 필요한 서비스는 전부 금지 |
| 팀 | A(데이터) · B(추천엔진) · C(프론트·배포) |
| 최종 산출물 | 배포된 웹 서비스 |

---

## 1. 불변 규칙 (위반 금지)

### 1.1 설계 3대 결정

| # | 규칙 | 이유 |
|---|---|---|
| **R1** | **협업 필터링(CF)을 쓰지 않는다.** 개인화 근거는 `segment_affinity`(성별×연령×요일×시간대 소비 통계)다 | 개인 단위 방문 로그가 공공에 없고 서비스 초기 로그도 0건 |
| **R2** | **좌표/지역을 먼저 확정하지 않는다.** 상권 인기도는 점수 항일 뿐 필터가 아니다 | 경계 밖 우수 후보 소실 + 1단계 오차가 복구 불가 |
| **R3** | **리뷰를 온라인에서 LLM에 태우지 않는다.** 리뷰는 **오프라인 배치로 구조화 속성**으로 뽑아 SQL 필터/점수로 쓴다 | 요청당 수백 리뷰를 LLM에 넣으면 응답 10초+·무료 쿼터 즉시 소진 |

**R3가 A 역할의 존재 이유다.** A가 만드는 `poi` 속성 컬럼이 곧 온라인 추천의 필터와 점수가 된다.

### 1.2 비용 규칙

- **결제수단 등록을 요구하는 서비스는 즉시 후보에서 제외**한다.
- ~~Google Places API~~ **사용 금지** (유료 SKU). 리뷰는 **네이버 검색 API 단독**.
- 지도 리뷰 스크래핑 **금지** (약관 위반).
- LLM은 무료 티어 가정 → **rate limit이 병목**. 모든 LLM 배치는 **체크포인트 재개**가 필수.

### 1.3 데이터 규칙

- **속성이 없는 POI를 삭제하지 않는다.** `attr_confidence`를 낮춰 **순위에서 내린다.**
  (삭제하면 커버리지가 붕괴하고, B의 후보 생성이 빈 결과를 반환한다.)
- 모든 배치는 **멱등(idempotent)** 이어야 한다. 두 번 돌려도 결과가 같아야 한다.
- 좌표계는 **WGS84 (EPSG:4326)** 로 통일한다.

---

## 2. 소유 범위

| 구분 | 대상 |
|---|---|
| ✅ **내 소유** | `roleA/` 전체, `seeds/`, `poi` · `review_chunk` · `segment_affinity` · `hotspot_snapshot` 테이블의 **데이터 적재** |
| 🤝 **공동 (3인 합의 필요)** | `db/migrations/*.sql` (스키마 변경 시 반드시 PR + 3인 리뷰) |
| ❌ **건드리지 않음** | `roleB/` (B 소유) · `roleC/` (C 소유) · `openapi.yaml` (B 소유) |

---

## 3. 레포 구조 (A 담당 부분)

> **폴더는 역할 기준으로 나뉜다.** `roleA/`(데이터) · `roleB/`(엔진) · `roleC/`(웹).
> `db/`와 `seeds/`는 루트에 두고 공유한다. 각 폴더의 `README.md`에 소유 규칙이 요약되어 있다.

```
Dacos_WhereToGo/
├── roleA/                         ← A 소유 (데이터 파이프라인)
│   ├── common/
│   │   ├── db.py                  # psycopg 커넥션, upsert 헬퍼
│   │   ├── http.py                # 재시도·백오프 래퍼
│   │   ├── llm.py                 # LLM 호출 + rate limit 대응
│   │   ├── checkpoint.py          # 배치 재개 로직
│   │   └── config.py              # 환경변수 로드
│   ├── jobs/
│   │   ├── ingest_poi.py
│   │   ├── tag_geo.py
│   │   ├── collect_reviews.py
│   │   ├── extract_attributes.py
│   │   ├── embed_chunks.py
│   │   ├── map_poi_hotspot.py
│   │   ├── poll_citydata.py
│   │   ├── build_affinity.py
│   │   ├── compute_quality.py
│   │   ├── build_query_cache.py
│   │   └── keepalive_db.py
│   ├── data/                      # 원본 CSV/GeoJSON (gitignore, 용량 큼)
│   ├── reports/                   # 커버리지·품질 리포트 출력
│   ├── requirements.txt
│   └── README.md
├── seeds/                         ← A가 W1에 제공 (B가 소비)
│   ├── poi_seed.json
│   └── review_seed.json
├── db/migrations/                 ← 공동 (읽기만, 변경은 PR)
├── roleB/                         ← B 소유. 건드리지 않음
├── roleC/                         ← C 소유. 건드리지 않음
└── docs/                          ← 설계 문서
```

**실행 규약:** 모든 job은 `python -m roleA.jobs.<job_name> [--dry-run] [--limit N]` 형태로 실행 가능해야 한다.

---

## 4. 데이터 계약 (내가 채워야 하는 스키마)

> 정본은 `db/migrations/001_init.sql`. 아래는 A가 책임지는 컬럼의 **의미 정의**다.

### 4.1 `poi` — POI 백본

| 컬럼 | 타입 | 출처 | A의 책임 |
|---|---|---|---|
| `poi_id` | TEXT PK | 상가정보 상가업소번호 (TourAPI는 `tour_` 접두) | 유일성 보장 |
| `name` | TEXT | 상가정보 | — |
| `category_l1` | TEXT | 매핑표 | 음식/카페/문화/쇼핑/자연 **5종으로 정규화** |
| `category_l2` | TEXT | 상가정보 소분류 | 상권분석 업종코드와 **조인 가능해야 함** |
| `geom` | GEOGRAPHY(POINT,4326) | 상가정보 경도·위도 | — |
| `dong` | TEXT | 행정동 GeoJSON 공간조인 | 100% 채움 |
| `zone` | TEXT | §5 zone 매핑 | 100% 채움 (B의 거리 로직이 의존) |
| `commercial_area_id` | TEXT | 상권 폴리곤 공간조인 | 매핑률 95%+ |
| `business_hours` | JSONB | 카카오 로컬 / 리뷰 추출 | 결측 허용 |
| `outdoor_exposure` | REAL 0~1 | **LLM 추출** | 0=완전실내, 1=완전야외 |
| `group_capacity` | INT | **LLM 추출** | 기본값 4 |
| `noise_level` | SMALLINT 1~5 | **LLM 추출** | 1=조용 5=시끌 |
| `purpose_tags` | TEXT[] | **LLM 추출** | §4.3 고정 어휘만 |
| `atmosphere_tags` | TEXT[] | **LLM 추출** | §4.3 고정 어휘만 |
| `price_band` | SMALLINT 1~4 | **LLM 추출** | — |
| `wait_intensity` | JSONB | **LLM 추출** | 결측 허용 |
| `tag_vector` | HALFVEC(1024) | bge-m3 | atmosphere+purpose 태그 임베딩 평균 |
| `sentiment_score` | REAL 0~1 | **LLM 추출** | `is_sponsored=false` 청크만 집계 |
| `mention_count` | INT | 네이버 검색 `total` | — |
| `review_count` | INT | 수집 청크 수 | — |
| `quality_score` | REAL | `compute_quality.py` | §6.7 공식 |
| `attr_confidence` | REAL 0~1 | 리뷰 수 기반 | **§4.4 규칙 준수** |
| `hotspot_code` | TEXT NULL | 최근접 핫스팟 | **1km 밖이면 NULL 유지 (0 아님)** |
| `tier` | SMALLINT | 1/2/3 | T1=수집완료 |
| `attr_extracted_at` | TIMESTAMPTZ NULL | 체크포인트 | **NULL이면 미처리** |

### 4.2 `review_chunk`

```
chunk_id BIGSERIAL PK · poi_id · source('naver_blog') · text(최대 300자 발췌)
embedding HALFVEC(1024) · is_sponsored BOOL · written_at DATE
```

**POI당 최대 3청크.** 무료 DB 500MB 제약 때문이다 (`PLAN.md` §9.4). 원문을 통째로 저장하지 않는다.

### 4.3 태그 고정 어휘 (LLM이 자유 생성하면 안 됨)

```python
PURPOSE_TAGS    = ["데이트", "친구모임", "혼자", "가족", "작업", "회식"]
ATMOSPHERE_TAGS = ["조용한", "활기찬", "감성적인", "트렌디한", "로컬한", "넓은",
                   "뷰가좋은", "아늑한", "이국적인", "가성비"]
CATEGORY_L1     = ["음식", "카페", "문화", "쇼핑", "자연"]
```

> 어휘를 고정하는 이유: B의 `purpose_match` 점수와 C의 온보딩 태그 그리드가 **같은 어휘를 전제**한다. 자유 생성하면 매칭이 전부 깨진다. 어휘를 늘리려면 3인 합의가 필요하다.

### 4.4 `attr_confidence` 산출 규칙

```python
def attr_confidence(n_clean_chunks: int, n_null_fields: int) -> float:
    base = min(n_clean_chunks / 8.0, 1.0)      # 청크 8개면 만점
    penalty = n_null_fields * 0.08             # LLM이 null 반환한 필드 수만큼 감점
    return max(0.0, round(base - penalty, 3))
```

- `attr_confidence < 0.3` → B의 후보 생성 SQL에서 **자동 제외**된다.
- 즉 **이 값이 A의 실질 산출 지표**다. W4 게이트는 "T1 800 POI 중 70%+ 가 ≥ 0.5".

---

## 5. 용산 zone 매핑 (B의 거리 로직이 의존)

```python
ZONE_BY_DONG = {
    "이태원1동": "itaewon", "이태원2동": "itaewon", "한남동": "itaewon", "보광동": "itaewon",
    "한강로동": "yongsan_stn", "남영동": "yongsan_stn",
    "후암동": "huam", "용산2가동": "huam",
    "이촌1동": "ichon", "이촌2동": "ichon", "서빙고동": "ichon",
    "청파동": "cheongpa", "원효로1동": "cheongpa", "원효로2동": "cheongpa",
    "효창동": "cheongpa", "용문동": "cheongpa",
}
```

- 행정동 GeoJSON으로 `dong`을 먼저 채우고, 위 표로 `zone`을 유도한다.
- **`zone`이 NULL인 POI가 하나라도 있으면 W2 게이트 미달**이다. B의 `ZONE_BARRIER` 조회가 KeyError로 터진다.

---

## 6. 주차별 작업

---

### W1 — 준비 · 시드 제공 (B의 대기를 푸는 주)

**이번 주의 목적은 내 진도가 아니라 B의 진도를 푸는 것이다.** `seeds/poi_seed.json`이 없으면 B가 W2 내내 아무것도 못 한다.

| # | 작업 | 산출물 | 완료 기준 |
|---|---|---|---|
| A1-1 | API 키 발급 신청 (전부) | `.env.example` 갱신 | 아래 키 6종 발급 완료 |
| A1-2 | **`서울시 주요 121장소 목록.xlsx` 다운로드 → 용산 지점 확정** | `roleA/data/yongsan_hotspots.json` | 지점명·코드 목록 확정 |
| A1-3 | 상가정보 CSV 다운로드 · 컬럼 확인 | `roleA/data/store_info.csv` | 용산구 행 수 확인 |
| A1-4 | `roleA/` 스캐폴딩 + `common/` 4개 모듈 | 코드 | `python -m roleA.jobs.ingest_poi --dry-run` 이 에러 없이 종료 |
| A1-5 | **시드 POI 100건 + 시드 리뷰 커밋** | `seeds/*.json` | **B가 즉시 사용 가능** |

**발급할 키 6종**

| 키 | 발급처 | 비고 |
|---|---|---|
| 서울 열린데이터광장 인증키 | data.seoul.go.kr | **일일 한도를 반드시 메모** → 폴링 주기 결정 |
| 공공데이터포털 (상가정보·기상청·TourAPI) | data.go.kr | 승인 1~2일 소요 |
| 카카오 REST API 키 | developers.kakao.com/console/app | 백엔드용, 노출 금지 |
| 카카오 JavaScript 키 | 동일 | C에게 전달, 도메인 제한 필수 |
| 네이버 검색 API (Client ID/Secret) | developers.naver.com | 일 25,000 |
| LLM 키 | (팀 조달) | B가 한도 실측 |

**`seeds/poi_seed.json` 형식 (B와의 계약 — 이 형식을 지켜야 B가 W2를 시작한다)**

```json
[
  {
    "poi_id": "seed_0001",
    "name": "예시카페",
    "category_l1": "카페",
    "category_l2": "베이커리카페",
    "lat": 37.5340, "lng": 126.9946,
    "dong": "이태원1동",
    "zone": "itaewon",
    "commercial_area_id": "3110001",
    "business_hours": {"mon": ["10:00", "22:00"], "tue": ["10:00", "22:00"]},
    "outdoor_exposure": 0.1,
    "group_capacity": 6,
    "noise_level": 2,
    "purpose_tags": ["데이트", "작업"],
    "atmosphere_tags": ["조용한", "감성적인"],
    "price_band": 3,
    "sentiment_score": 0.82,
    "mention_count": 143,
    "review_count": 8,
    "attr_confidence": 0.86,
    "hotspot_code": "POI014",
    "tier": 1
  }
]
```

> 시드 100건은 **손으로 채워도 된다.** 정확성보다 **형식 준수와 값의 다양성**이 중요하다.
> 반드시 포함할 것: `outdoor_exposure`가 0에 가까운 것과 1에 가까운 것 **양쪽**, `hotspot_code`가 `null`인 것 **최소 20건** (B가 재정규화 로직을 검증해야 함), 5개 zone **전부**.

**`common/checkpoint.py` 최소 구현**

```python
def pending_pois(conn, limit: int) -> list[str]:
    """attr_extracted_at IS NULL 인 T1 POI만 반환 — 배치 재개의 핵심"""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT poi_id FROM poi
            WHERE tier = 1 AND attr_extracted_at IS NULL
            ORDER BY mention_count DESC NULLS LAST
            LIMIT %s
        """, (limit,))
        return [r[0] for r in cur.fetchall()]
```

`mention_count DESC` 정렬이 중요하다. **쿼터가 소진되어도 유명한 곳부터 처리**되어 데모 품질이 보장된다.

---

### W2 — POI 전역 적재 · 지오 태깅

🚩 **게이트: 용산 전역 POI 5,000건± 적재, `zone`·`dong` 100% 채움**

| # | 작업 | 산출물 | 완료 기준 |
|---|---|---|---|
| A2-1 | `ingest_poi.py` — 상가정보 CSV → `poi` upsert | 코드 | 용산구 필터, 추천대상 카테고리만 |
| A2-2 | `tag_geo.py` — 행정동 GeoJSON 공간조인 → `dong`, `zone` | 코드 | `SELECT count(*) FROM poi WHERE zone IS NULL` = **0** |
| A2-3 | 상권 폴리곤 공간조인 → `commercial_area_id` | 코드 | 매핑률 95%+ |
| A2-4 | TourAPI 문화·관광 POI 병합 | 코드 | 국립중앙박물관·전쟁기념관·용산가족공원 포함 확인 |
| A2-5 | T1 지정 (`tier=1`) | SQL | 이태원1·2동, 한남동, 한강로동, 후암동 → 약 800건 |

**A2-1 핵심 로직**

```python
RECOMMEND_CATEGORIES = {  # 상가정보 대분류 → category_l1
    "음식": "음식", "카페": "카페",           # 실제 코드값은 CSV 확인 후 매핑
    "관광/여가/오락": "문화", "소매": "쇼핑",
}
# 제외: 부동산, 학문/교육, 의료, 생활서비스, 숙박 등
```

> **주의:** 상가정보 CSV의 대분류 코드값은 버전마다 다르다. 하드코딩 전에 **실제 파일의 unique 값을 출력해서 확인**할 것.

**A2-2 공간조인 SQL**

```sql
UPDATE poi p SET dong = d.adm_nm
FROM admin_dong d
WHERE ST_Contains(d.geom::geometry, p.geom::geometry) AND p.dong IS NULL;
```

**A2-4 TourAPI를 넣는 이유**
상가정보에는 **국립중앙박물관·전쟁기념관·용산가족공원 같은 비상업 시설이 없다.** 용산은 이런 곳의 추천 가치가 큰 지역이라 빠지면 안 된다. TourAPI는 대표 이미지도 무료 제공하므로 C의 UI 품질에도 직결된다. `poi_id`는 `tour_` 접두로 구분한다.

---

### W3 — 리뷰 수집 · LLM 추출 착수 (**가장 위험한 주**)

🚩 **게이트: T1 리뷰 500 POI 확보**

**이 주가 프로젝트 최대 리스크 구간이다.** 리뷰 수집과 LLM 추출이 동시에 걸리고, 무료 쿼터 제약을 처음 만난다. W2에 여유가 생기면 **A3-1을 W2로 당겨 시작**한다.

| # | 작업 | 산출물 | 완료 기준 |
|---|---|---|---|
| A3-1 | `collect_reviews.py` — 네이버 블로그 4쿼리 변형 | 코드 | POI당 목표 8~10청크 |
| A3-2 | `extract_attributes.py` — LLM 배치 (야간 실행) | 코드 | 체크포인트 재개 동작 확인 |
| A3-3 | `map_poi_hotspot.py` — POI ↔ 최근접 핫스팟 | 코드 | 1km 밖은 **NULL 유지** |
| A3-4 | `poll_citydata.py` — 15분 폴링 | 코드 + GH Actions | `hotspot_snapshot` 적재 |

**A3-1 쿼리 다변화 (단일 소스 리스크 대응)**

```python
QUERY_TEMPLATES = [
    '"{name}"',
    '"{name}" {dong}',
    '"{name}" 후기',
    '"{name}" 웨이팅',
]
# 결과 병합 → 중복 제거 → 상위 10건 → LLM 요약으로 3청크 압축
# mention_count = 첫 번째 쿼리 응답의 total 값
```

**A3-2 LLM 추출 프롬프트 (JSON 스키마 강제)**

```
당신은 장소 리뷰 분석기다. 아래 블로그 후기들을 읽고 JSON만 출력하라.

규칙:
- 근거가 없는 필드는 반드시 null. 추측 금지.
- purpose_tags / atmosphere_tags 는 주어진 어휘에서만 선택.
- 각 후기가 협찬·광고성인지 is_sponsored 로 판정하라.
  (판정 근거: "협찬", "제공받아", "소정의 원고료" 등 표기 / 과도한 미사여구 / 단점 언급 전무)

출력 스키마:
{
  "outdoor_exposure": 0.0~1.0 | null,   // 0=완전실내 1=완전야외
  "group_capacity": int | null,
  "noise_level": 1~5 | null,
  "purpose_tags": [PURPOSE_TAGS 중], "atmosphere_tags": [ATMOSPHERE_TAGS 중],
  "price_band": 1~4 | null,
  "wait_intensity": {"weekday": str|null, "weekend": str|null} | null,
  "business_hours_hint": str | null,
  "sentiment_score": 0.0~1.0 | null,    // 광고 판정 후기는 제외하고 산출
  "chunks": [ {"text": "인용용 발췌 300자 이내", "is_sponsored": bool} ]  // 최대 3개
}
```

> **`is_sponsored` 판정을 빠뜨리면 안 된다.** 네이버 블로그는 협찬 글 비중이 높아, 거르지 않으면 `sentiment_score`가 전부 0.9대로 붕괴해서 변별력이 사라진다. 단, **광고 글도 시설 정보(단체석·주차 등) 추출에는 계속 사용**한다. 감성 집계에서만 뺀다.

**A3-2 rate limit 대응 (필수)**

```python
# 429 → exponential backoff (2, 4, 8, 16초)
# 일일 한도 도달 → 정상 종료 (crash 금지), 다음 실행이 이어받음
# 처리 성공 시 즉시 attr_extracted_at = now() 커밋 (배치 끝에 한 번에 커밋 금지)
```

**A3-3 핫스팟 매핑 — NULL을 0으로 바꾸지 말 것**

```sql
UPDATE poi p SET hotspot_code = h.code
FROM hotspot h
WHERE ST_DWithin(p.geom, h.geom, 1000)      -- 1km 이내만
  AND h.code = (SELECT code FROM hotspot ORDER BY p.geom <-> geom LIMIT 1);
-- 1km 밖 POI는 hotspot_code = NULL 로 남는다. 이게 정상이다.
```

B의 점수 로직이 `NULL`을 "신호 없음"으로 처리해 **가중치를 재정규화**한다. 0으로 채우면 핫스팟 밖 POI가 전멸한다.

**A3-4 폴링 주기**

| 주기 | 일일 호출 (7지점) | 판정 |
|---|---|---|
| 5분 | 2,016 | ❌ |
| 10분 | 1,008 | ⚠️ |
| **15분** | **672** | ✅ 채택 |

API는 **한 번에 1지점씩만** 호출된다. 인증키 실제 한도가 더 낮으면 30분으로 낮춘다.

---

### W4 — 추출 완료 · 임베딩 · 세그먼트

🚩 **게이트: T1 800 POI 중 70%+ 가 `attr_confidence ≥ 0.5`**

| # | 작업 | 산출물 | 완료 기준 |
|---|---|---|---|
| A4-1 | `extract_attributes.py` 완주 | 데이터 | 게이트 지표 달성 |
| A4-2 | `embed_chunks.py` — bge-m3 임베딩 | 코드 | **로컬/Colab 실행**, 결과만 적재 |
| A4-3 | `build_affinity.py` — 상권분석 → `segment_affinity` | 코드 | 용산 전 상권×세그먼트 커버 |
| A4-4 | `compute_quality.py` — 품질 점수 | 코드 | `quality_score` 전 POI 채움 |

**A4-2 — 임베딩 모델을 서버에 올리지 않는다**

bge-m3는 약 2GB다. Render Free 메모리로는 **애초에 뜨지 않는다.** 팀원 PC 또는 Colab 무료 GPU에서 돌리고 **결과 벡터만 DB에 적재**한다.

```python
# HALFVEC(1024) 로 저장 — VECTOR 대비 용량 절반, 품질 손실은 무시할 수준
# poi.tag_vector = mean(embed(atmosphere_tags + purpose_tags))
# review_chunk.embedding = embed(chunk.text)
```

**A4-3 — `segment_affinity` 정규화**

```python
# 상권분석 추정매출 원본 → 상권×업종 내에서 세그먼트 비중으로 정규화
# affinity = 해당 세그먼트 매출 / 해당 상권·업종 전체 매출  → 0~1
# sample_weight = 원본 표본 규모 (희소 셀 신뢰도 판단용)
```

축: `commercial_area_id × category_l2 × gender × age_band × dow_type × hour_band`
`age_band`는 5세 단위, `hour_band`는 4시간 단위 6구간, `dow_type`은 평일0/주말1.

**A4-4 — 품질 점수 (별점이 없으므로 직접 만든다)**

```python
s_bayes = (C * m + sentiment_score * n_clean) / (C + n_clean)
#   C = 8, m = 전체 POI 평균 감성, n_clean = is_sponsored=false 청크 수
quality_score = s_bayes * (log1p(mention_count) / log1p(MENTION_P95))
#   MENTION_P95 = 전체 언급량 95퍼센타일 (상한 클리핑)
```

> 온라인에서 계산하지 않는다. 배치에서 `poi.quality_score`에 저장한다.

---

### W5 — 쿼리벡터 · 품질 점검

| # | 작업 | 산출물 | 완료 기준 |
|---|---|---|---|
| A5-1 | `build_query_cache.py` — 쿼리 72종 사전 임베딩 | `query_vector_cache` | 72행 적재 |
| A5-2 | 결측 보정 — 리뷰 부족 POI 기본값 채움 | SQL/코드 | `attr_confidence` 재계산 |
| A5-3 | `keepalive_db.py` + GH Actions 일일 cron | 워크플로 | Supabase 7일 일시정지 방지 |
| A5-4 | 커버리지·품질 리포트 | `roleA/reports/coverage.md` | W6 발표 자료용 수치 |

**A5-1 — 왜 72개인가**

```
목적 6종 × 날씨상태 4종 × 인원밴드 3종 = 72
```

사용자 쿼리는 유한 조합이므로 **미리 임베딩해두면 온라인 임베딩 서버가 아예 필요 없다.** 이게 무료 티어에서 RAG를 돌리는 핵심 트릭이다.

```python
PURPOSES      = ["데이트", "친구모임", "혼자", "가족", "작업", "회식"]
WEATHER_STATES = ["맑음", "비", "미세먼지나쁨", "폭염한파"]
PARTY_BANDS   = [1, 2, 3]   # 1~2명 / 3~4명 / 5명이상
# 쿼리 문장 예: "3~4명이서 데이트하기 좋은 곳, 비 오는 날"
```

**A5-2 — 결측 보정 원칙**

카테고리 기본값으로 채우되 **`attr_confidence`는 낮게 유지**한다. "채웠으니 신뢰할 수 있다"가 아니라 "채웠지만 근거는 약하다"를 값으로 표현해야 B의 랭킹이 올바르게 동작한다.

---

### W6 — 리포트 · 발표 지원

| # | 작업 | 산출물 |
|---|---|---|
| A6-1 | 최종 커버리지 통계 | POI 수, T1 비율, `attr_confidence` 분포 히스토그램 |
| A6-2 | 데이터 파이프라인 다이어그램 | 발표 슬라이드용 |
| A6-3 | B의 가중치 튜닝 지원 | 세그먼트별 실제 분포 근거 제공 |
| A6-4 | 데모 시나리오용 데이터 검증 | C의 시나리오 20개가 **전부 결과를 반환하는지** 확인 |

**A6-4가 실질적으로 가장 중요하다.** 데모 시나리오 중 하나라도 빈 결과가 나오면 발표가 무너진다. C의 시나리오 목록을 받아 **각각 후보 수를 직접 쿼리해서 확인**한다.

---

## 7. 자주 하는 실수 (체크리스트)

- [ ] `hotspot_code`가 없을 때 `NULL` 대신 `''`나 `0`을 넣지 않았는가
- [ ] 리뷰 없는 POI를 **삭제**하지 않았는가 (→ `attr_confidence`만 낮춘다)
- [ ] `purpose_tags` / `atmosphere_tags`를 고정 어휘 밖 값으로 채우지 않았는가
- [ ] LLM 배치가 중간에 끊겼을 때 **처음부터 다시 돌지** 않는가 (체크포인트)
- [ ] `attr_extracted_at`을 배치 끝에 한 번에 커밋하지 않았는가 (건별 커밋)
- [ ] `zone`이 NULL인 POI가 남아 있지 않은가
- [ ] `is_sponsored` 판정 결과를 감성 집계에서 실제로 제외했는가
- [ ] 좌표계를 EPSG:4326으로 통일했는가
- [ ] **API 키를 코드/커밋에 넣지 않았는가** (레포는 public이다)
- [ ] 배치를 두 번 돌렸을 때 결과가 같은가 (멱등성)

---

## 8. 로컬 실행 환경

```powershell
# PostGIS + pgvector 로컬 DB
docker run -d --name yongsan-db -p 5432:5432 `
  -e POSTGRES_PASSWORD=devpass -e POSTGRES_DB=yongsan `
  pgvector/pgvector:pg16

# 확장 설치 후 마이그레이션 적용
psql -h localhost -U postgres -d yongsan -f db/migrations/001_init.sql

# 배치 실행
python -m roleA.jobs.ingest_poi --dry-run
python -m roleA.jobs.extract_attributes --limit 50
```

> `pgvector/pgvector` 이미지에 PostGIS가 없으면 `postgis/postgis:16-3.4` 로 시작해 `CREATE EXTENSION vector;`를 수동 설치한다. **W1에 어느 쪽으로 갈지 확정해서 B·C에게 공유**할 것.

---

## 9. 막혔을 때 판단 기준

| 상황 | 판단 |
|---|---|
| 리뷰가 목표만큼 안 모인다 | **T1 범위를 줄인다** (이태원·한남 2개 동). 넓고 얕은 것보다 좁고 깊은 것이 데모에서 이긴다 |
| LLM 쿼터가 부족하다 | POI 수를 줄인다. `mention_count DESC` 정렬 덕분에 **유명한 곳부터 처리**되어 있다 |
| 스키마를 바꾸고 싶다 | **혼자 바꾸지 않는다.** PR + 3인 리뷰 + 마이그레이션 파일 |
| 상권분석 데이터 축이 안 맞는다 | 축을 줄여서라도 채운다 (예: `hour_band` 생략). **비어 있는 것보다 거친 것이 낫다** |
| 일정이 밀린다 | 커버리지(T2)를 먼저 버린다. 속성 품질은 마지막까지 지킨다 |
