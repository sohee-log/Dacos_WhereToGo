# roleA — 데이터 엔지니어링

담당 문서: [docs/ROLE_A_DATA.md](../docs/ROLE_A_DATA.md)

수집 · 적재 · LLM 속성 추출 · 임베딩 · 세그먼트 통계를 담당한다.
파이썬 배치 작업이 전부 여기 들어간다.

## 구조

```
roleA/
├── common/
│   ├── db.py            # psycopg 커넥션, upsert 헬퍼
│   ├── http.py          # 재시도 · 백오프 래퍼
│   ├── llm.py           # LLM 호출 + rate limit 대응
│   ├── checkpoint.py    # 배치 재개 로직
│   └── config.py
├── jobs/
│   ├── ingest_poi.py            # 상가정보 → poi
│   ├── tag_geo.py               # 행정동 · zone · 상권 공간조인
│   ├── collect_reviews.py       # 네이버 블로그 수집
│   ├── extract_attributes.py    # LLM 속성 추출 (야간 배치)
│   ├── embed_chunks.py          # bge-m3 임베딩
│   ├── map_poi_hotspot.py       # POI ↔ 핫스팟 매핑
│   ├── poll_citydata.py         # 실시간 도시데이터 15분 폴링
│   ├── build_affinity.py        # 상권분석 → segment_affinity
│   ├── compute_quality.py       # 품질 점수 산출
│   ├── build_query_cache.py     # 쿼리 벡터 72종
│   └── keepalive_db.py          # Supabase 일시정지 방지
├── data/                # 원본 CSV · GeoJSON (gitignore)
├── reports/             # 커버리지 · 품질 리포트
└── requirements.txt
```

## 실행

```bash
python -m roleA.jobs.ingest_poi --dry-run
python -m roleA.jobs.extract_attributes --limit 50
```

DB 적재 및 외부 API 수집 배치는 가능한 한 `--dry-run`, `--limit N`을 지원하고
재실행해도 결과가 깨지지 않도록 멱등성을 유지한다.

## 다른 폴더와의 관계

| | |
|---|---|
| `../db/` | 스키마. **읽기만.** 변경은 PR + 3인 리뷰 |
| `../seeds/` | **내가 채운다.** B가 소비한다 |
| `../roleB/`, `../roleC/` | 건드리지 않는다 |

## 잊지 말 것

- 속성이 없는 POI를 **삭제하지 않는다.** `attr_confidence`를 낮춰 순위에서 내린다
- `hotspot_code`가 없으면 **NULL로 남긴다.** 0을 넣으면 핫스팟 밖 POI가 전멸한다
- LLM 배치는 건별로 커밋한다. 끊겨도 이어서 재개돼야 한다
- 태그는 고정 어휘만 쓴다 (`docs/ROLE_A_DATA.md` §4.3)
- **레포가 public이다.** 키를 코드에 넣지 않는다


### W2 주요 작업 파일

| 파일 | 역할 |
|---|---|
| `map_admin_dong.py` | SGIS 행정동 경계 기반 `dong`, `zone` 매핑 |
| `map_commercial_area.py` | 서울시 상권 polygon 공간조인 |
| `qc_commercial_area.py` | 상권 미매핑 POI 거리 분포 QC |
| `finalize_commercial_area.py` | nearest 60m 보정 적용 |
| `collect_tour_poi.py` | TourAPI 문화·자연 후보 수집 |
| `tag_tour_geo.py` | TourAPI POI 행정동·상권 매핑 |
| `build_final_poi.py` | 상가정보 + TourAPI 통합 및 중복 제거 |
| `filter_t1_candidates.py` | T1 후보 1차 품질 필터 |
| `collect_t1_mentions.py` | T1 선정용 네이버 블로그 검색량 수집 |
| `select_t1.py` | 동·카테고리 균형을 고려한 T1 800건 선정 |
| `assign_poi_tiers.py` | 최종 tier 1/2/3 부여 |
| `load_commercial_area.py` | Supabase `commercial_area` 적재 |
| `load_final_poi.py` | Supabase 최종 POI 적재 |
| `qc_final_poi_db.py` | 로컬 ↔ DB 최종 일치 여부 QC |

## W2 지리 매핑 규칙

### 행정동 · zone

- SGIS 2025년 2분기 행정동 경계(SHP)를 기준으로 POI 좌표를 공간조인한다.
- 좌표계는 POI(WGS84, EPSG:4326)를 행정동 경계 좌표계(EPSG:5179)로 변환한 뒤 조인한다.
- polygon 내부 매핑에 실패한 경계 인접 POI는 가장 가까운 행정동이 30m 이내인 경우에만 nearest 방식으로 보정한다.
- W2 QC 결과: 용산구 16,301건 모두 `dong`, `zone` 매핑 완료.

### 상권 (`commercial_area_id`)

서울시 상권분석서비스 영역-상권(SHP, EPSG:5181)을 사용한다.

매핑 규칙:

1. POI가 상권 polygon 내부에 있으면 해당 `TRDAR_CD`를 `commercial_area_id`로 사용한다.
2. 하나의 POI가 여러 상권과 겹치면 면적이 가장 작은 상권을 선택한다.
3. polygon에 직접 매핑되지 않은 POI는 가장 가까운 상권까지의 거리가 60m 이하인 경우에만 보정한다.
4. 60m를 초과하면 `commercial_area_id = NULL`로 유지한다.

60m는 W2 QC에서 목표 매핑률 95%를 충족하는 최소 임계값으로 선택했다.

### W2 최종 POI 결과

- 최종 추천 POI: 6,644건
- `dong` 매핑률: 100%
- `zone` 매핑률: 100%
- 상권 매핑: 6,354건
- 상권 미매핑: 290건
- 상권 매핑률: 95.64%
- POI ID 중복: 0

### Tier

- Tier 1: 800건
- Tier 2: 1,792건
- Tier 3: 4,052건

Tier 1은 핵심 지역 후보 중 네이버 블로그 검색량을 보조 지표로 사용하고,
행정동 및 카테고리 비율을 유지하여 800건을 선정하였다.

네이버 블로그 검색 결과 수는 Tier 1 선정용 보조 지표로만 사용하며,
DB의 `mention_count`는 W3 실제 리뷰 수집 단계에서 별도로 갱신한다.

### TourAPI 보완

상가정보에서 부족한 문화·자연 POI를 TourAPI로 보완하였다.

- 용산구 수집: 33건
- 기존 POI 중복 제거: 4건
- 신규 추가: 29건
- `문화`: TourAPI `cat1=A02`를 프로젝트 `문화` 카테고리로 매핑
- `자연`: TourAPI `cat1=A01`을 기본으로 하며, 프로젝트 기준에 따라 일부 수동 보정