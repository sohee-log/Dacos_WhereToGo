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

모든 job은 `--dry-run`, `--limit N`을 지원하고 **멱등**해야 한다. 두 번 돌려도 결과가 같아야 한다.

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
