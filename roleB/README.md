# roleB — 추천 엔진 · 백엔드

담당 문서: [docs/ROLE_B_ENGINE.md](../docs/ROLE_B_ENGINE.md) · 설계 배경: [docs/PLAN.md](../docs/PLAN.md)

후보 생성 · 스코어링 · RAG · API를 담당한다. Render 배포 루트가 이 폴더다.

---

## 지금 상태 (W3 완료)

**`MOCK_MODE` 하나로 두 경로가 갈린다.**

| | |
|---|---|
| `MOCK_MODE=true` (기본) | 픽스처/시드 JSON. DB 없이 뜬다. C의 개발을 막지 않는다 |
| `MOCK_MODE=false` | PostGIS 후보 생성 + 7항 스코어링. DB가 없으면 **503** |

DB가 없을 때 목으로 조용히 되돌아가지 않는다. 그러면 "실데이터로 동작한다"가
거짓으로 통과하고, 화면에는 가짜 장소가 진짜처럼 뜬다.

| # | W2 작업 | 상태 | 산출물 |
|---|---|---|---|
| B2-1 | DB 커넥션 풀 | ✅ | [`app/db.py`](app/db.py) — psycopg_pool · 대여 직전 생존 확인 · 죽으면 503 |
| B2-2 | 후보 생성 (PostGIS) | ✅ | [`app/services/retrieval.py`](app/services/retrieval.py) — 반경 확대 → 신뢰도 완화 → 최근접 폴백 |
| B2-3 | 7항 스코어링 + 재정규화 | ✅ | [`app/services/scoring.py`](app/services/scoring.py) · 조립은 [`pipeline.py`](app/services/pipeline.py) |
| B2-4 | `ZONE_BARRIER` 10개 값 | ✅ | [`app/constants.py`](app/constants.py) — 5×5 대칭 전 조합 |
| B2-5 | `is_open_at()` SQL 함수 | ✅ | [`db/migrations/001_init.sql`](../db/migrations/001_init.sql) §9 (W1에 이미 들어갔다) |

🚩 **게이트 확인:** 시드 100건을 실제 PostGIS(3.4.3 + pgvector 0.8.6)에 적재해
`POST /api/recommend`가 점수 내림차순 5건을 반환하는 것까지 확인했다.
지점 반경 안 38 / 밖 62로 갈려 있어 §6.4 재정규화 경로가 양쪽 다 실행된다.

| # | W3 작업 | 상태 | 산출물 |
|---|---|---|---|
| B3-1 | 비선형 날씨 로직 | ✅ | [`app/services/context_fit.py`](app/services/context_fit.py) — U자형·임계값 테스트 15개 |
| B3-2 | `hotspot_snapshot` 소비 | ✅ | [`app/services/live_signals.py`](app/services/live_signals.py) — `fcst`로 **방문 시각** 혼잡 예측 |
| B3-3 | `GET /api/context/now` | ⚠️ 키 대기 | [`app/services/kma.py`](app/services/kma.py) + [`routers/context.py`](app/routers/context.py) |
| B3-4 | `weather_sensitivity` 개인화 훅 | ✅ | `context_fit(..., weather_sensitivity)` — DB 경로까지 테스트 |

**B3-3만 반쪽이다.** `KMA_SERVICE_KEY`가 없어 실제 호출을 확인하지 못했다.
격자 변환·발표 회차 계산·응답 파싱·에러 처리는 전부 순수 함수로 테스트했고,
키가 생기면 `KMA_SERVICE_KEY=... pytest tests/test_kma.py`로 실호출 1건이 켜진다.
**키가 없어도 서비스는 돈다** — 조용히 citydata 실황으로 물러선다.

### 날씨가 어디서 오는가 (`weather_source`)

| 방문 시각 | 강수·기온 | 미세먼지 |
|---|---|---|
| 3시간 이상 뒤 | 기상청 단기예보 | citydata 실황 (단기예보에 대기질이 없다) |
| 2시간 이내 | citydata 실황 | citydata 실황 |
| 소스 없음 | 결정적 프로파일 → `weather_source: "mock"` | 〃 |

응답의 `weather_source`가 **실서버에서 `mock`이면 키가 없거나 적재가 안 된 것이다.**

> ⚠️ **citydata의 `rain_prob`은 0 또는 1이다.** 실황은 확률이 아니라 사실이다.
> 확률이 필요한 건 3시간 뒤 방문이고 그건 기상청이 담당한다.

**아직 임시인 것 (숨기지 않는다)**

| | 지금 | 언제 바뀌나 |
|---|---|---|
| 취향 유사도 | 항상 중립 0.5 (온보딩 임베딩이 없다) | W4 B4-5 |
| `log_id` | 결정적 해시. **로그 행이 아직 없다** | W4 B4-4 |
| `explain_mode` | 항상 `template` | W5 |
| `evidence` | 빈 배열 | W5 B5-1 (RAG 인용) |

---

## W1에 한 것

| # | W1 작업 | 상태 | 산출물 |
|---|---|---|---|
| B1-1 | DDL 초안 | ✅ | [`db/migrations/001_init.sql`](../db/migrations/001_init.sql) |
| B1-2 | OpenAPI 스펙 | ✅ | [`openapi.yaml`](openapi.yaml) |
| B1-3 | Pydantic 모델 | ✅ | [`app/schemas.py`](app/schemas.py) — 계약 대조 테스트 포함 |
| B1-4 | 목 API | ✅ 코드 완료 / ⏳ 배포 대기 | [`app/`](app) · [`../render.yaml`](../render.yaml) · [배포 절차](docs/DEPLOY_MOCK.md) |
| B1-5 | LLM 한도 실측 | ✅ | [실측 결과](docs/LLM_QUOTA.md) · [처리량](tools/llm_quota_probe.py) · [1건 실비용](tools/extract_cost_probe.py) |

> **B1-5 결과 요약 (A에게):** FactChat 게이트웨이 · `gpt-5.4-nano` · POI당 **1,038토큰 / 2.3초**.
> T1 800 POI가 **직렬 31분, 동시 8이면 4분**이다. §8.2의 "야간 배치 2~3일" 전제는 폐기해도 된다.
> 대신 **`response_format`을 `json_schema` + `strict: true`로 강제해야 한다** — 안 하면 nano가
> 스키마를 지어낸다. 자세한 실패 모드와 호출 형식은 [docs/LLM_QUOTA.md](docs/LLM_QUOTA.md).

---

## 실행

```powershell
cd roleB
python -m venv .venv; .\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt

uvicorn app.main:app --reload --port 8000    # 목 모드. http://localhost:8000/docs
pytest tests/ -v                             # DB 없이 도는 것만
```

### live 경로를 로컬에서 켜기 (W2 게이트 재현)

```powershell
docker run -d --name wheretogo-db -p 5432:5432 `
  -e POSTGRES_PASSWORD=devpass -e POSTGRES_DB=wheretogo postgis/postgis:16-3.4
# 이 이미지에는 pgvector가 없다. HALFVEC 컬럼 때문에 필요하다
docker exec wheretogo-db bash -c "apt-get update -qq && apt-get install -y -qq postgresql-16-pgvector"

$env:DATABASE_URL = "postgresql://postgres:devpass@localhost:5432/wheretogo"
docker cp ..\db\migrations\001_init.sql wheretogo-db:/tmp/
docker exec wheretogo-db psql -U postgres -d wheretogo -v ON_ERROR_STOP=1 -f /tmp/001_init.sql

python -m tools.load_seed_db --demo-hotspot   # 개발용 적재 (운영 적재는 A)
$env:MOCK_MODE = "false"
uvicorn app.main:app --reload --port 8000

$env:TEST_DATABASE_URL = $env:DATABASE_URL
pytest tests/test_live_db.py -v               # 실 PostGIS 통합 테스트
```

> `db/README.md`에 남아 있던 "PostGIS 이미지에 pgvector가 없으면 어떻게 하나"의 답이
> 위 `apt-get` 한 줄이다. 이미지를 바꾸지 않아도 되고, prod(Supabase)는 둘 다 기본 제공한다.

배포는 [docs/DEPLOY_MOCK.md](docs/DEPLOY_MOCK.md).

---

## 구조

```
roleB/
├── app/
│   ├── main.py              # FastAPI 앱, CORS, /health, 풀 lifespan
│   ├── config.py            # 환경변수 (시크릿은 코드에 없다)
│   ├── constants.py         # 고정 어휘 · 가중치 · ZONE_BARRIER
│   ├── schemas.py           # Pydantic — C와의 계약
│   ├── db.py                # 커넥션 풀 (W2)
│   ├── timeutil.py          # visit_at 파싱 — 판단 기준은 항상 방문 예정 시각이다
│   ├── mock_data.py         # 목 데이터 (MOCK_MODE=true 경로)
│   ├── routers/             # 5개 엔드포인트
│   └── services/
│       ├── retrieval.py     # ① 후보 생성 SQL + 물러서는 순서 (W2)
│       ├── scoring.py       # ② 7항 + 재정규화 + 거리 (W2)
│       ├── pipeline.py      # ①→②→③ 조립 + 컨텍스트 병합 (W2·W3)
│       ├── context_fit.py   # 비선형 날씨 + 체감온도 근사 (W3)
│       ├── live_signals.py  # hotspot_snapshot 해석 · 방문시각 혼잡 예측 (W3)
│       ├── kma.py           # 기상청 단기예보 클라이언트 (W3)
│       └── explain.py       # 템플릿 설명 (W5에 LLM·캐시가 붙는다)
├── tests/                   # 170개. test_live_db.py는 실 DB가 있을 때만 돈다
├── tools/
│   ├── load_seed_db.py      # 개발용 시드 적재 (운영 적재는 A)
│   └── llm_quota_probe.py   # B1-5 측정 스크립트
├── docs/                    # 배포 절차 · LLM 한도 기록
├── openapi.yaml             # C와의 계약. 변경은 PR
└── requirements.txt         # 임베딩 모델은 여기 들어가지 않는다
```

**아직 없는 것 (주차별로 채운다):** `logging_svc.py`(W4) · `rag.py`(W5)

---

## C가 알아야 할 것

목 응답에는 **`X-Mock-Response: true`** 헤더가 붙는다. 실서버로 바뀌면 사라진다.

### 1. `score_breakdown`의 `live_segment` / `crowd`는 **없을 수 있다**

```jsonc
// 실시간 도시데이터 지점 반경 1km 안
"score_breakdown": { "segment": 0.83, ..., "live_segment": 0.79, "crowd": 0.50 }

// 반경 밖 — 키 자체가 없다. null도 0도 아니다
"score_breakdown": { "segment": 0.79, "purpose": 0.95, "taste": 0.77, ... }
```

용산 POI의 상당수가 여기 해당한다. **`undefined`를 0으로 렌더링하면 "실시간 신호 없음"이
"실시간 점수 0점"으로 뒤바뀐다.** 목 응답에 두 경우가 섞여 있으니 지금 화면에서 확인할 수 있다.

### 2. 목 응답은 결정적이다

같은 요청 → 항상 같은 결과. 서버를 재시작해도 화면이 바뀌지 않는다.
날씨는 `visit_at` 날짜로 정해지고, `MOCK_WEATHER_STATE=비` 로 고정할 수 있다.

### 3. UI 커버리지를 위해 일부러 섞어 둔 것

| | |
|---|---|
| `explain_mode` | `template` → `cache` → `llm` 순환. 세 배지를 다 그려볼 수 있다 |
| `is_exploration` | 마지막 결과 1개가 탐색 슬롯이다 |
| `low_confidence` · `radius_expanded` | 인원 9명 · 예산 1밴드로 요청하면 켜진다 |
| 빈 결과 | **없다.** 어떤 조건에서도 최소 1개는 반환한다 |

POI와 후기 문장은 전부 **가상 데이터**다. 실재하는 상호가 아니다.
A가 `seeds/poi_seed.json`을 커밋하면 서버가 자동으로 그쪽을 읽는다.

### 4. W2에 생긴 것 — `503`을 처리해야 한다

실모드에서 DB에 닿지 못하거나 POI가 아직 적재되지 않으면 **503**이 나간다.
목 응답으로 대신하지 않는다 — 가짜 장소를 진짜처럼 띄우지 않기 위해서다.

```jsonc
{ "detail": "추천 데이터를 사용할 수 없습니다: DB에 닿지 못했다: ..." }
```

C의 **콜드스타트 안내(C4-5)와 같은 자리**에서 "잠시 후 다시 시도"로 처리하면 된다.
무한 스피너나 빈 화면이 아니라 재시도 버튼이 필요하다. 응답은 3초 안에 온다
(커넥션 대기 상한 3초 — 사용자를 10초 세워두지 않는다).
`GET /api/context/now`도 같은 조건에서 503이다.

### 5. W3에 생긴 것 — `context.weather_source`

날씨를 어디서 가져왔는지 응답에 실린다. `citydata`(실황) · `kma`(기상청 예보) ·
`kma+citydata` · `mock`(소스 없음). **화면에 그릴 필요는 없다.** 다만
`?debug=1` 화면(C4-4)에 한 줄 띄워 두면, 배너 날씨가 이상할 때 원인이 즉시 보인다.

`ContextBanner`(C3-4)에 쓸 값이 W3부터 진짜다.

```
🌧 {weather} · 체감 {feels_like}° · 미세먼지 {pm25_grade}
📍 {hotspot} · 지금 {congest_now} → {congest_forecast_at_visit} 예상 · {age_mix_top}
```

`congest_forecast_at_visit`은 **방문 예정 시각**의 예측이다. 지금 혼잡도와 값이
갈리는 것이 정상이고, 갈릴 때가 이 서비스의 차별점이 보이는 순간이다.
둘 다 `null`이면 그 좌표가 실시간 지점 반경 밖이라는 뜻이다 — 문구를 지어내지 않는다.

---

## A가 알아야 할 것

- 내가 읽는 테이블: `poi` · `segment_affinity` · `review_chunk` · `hotspot_snapshot` · `query_vector_cache`
- **`hotspot_snapshot.fcst`를 반드시 채워달라.** W3부터 혼잡도는 실황이 아니라
  `FCST_PPLTN`의 **방문 예정 시각 슬롯**을 쓴다. `fcst`가 비면 실황으로 물러서는데,
  그러면 "19시에 붐빌 예정"이라는 배너 문구가 사라진다. 형태는 그대로 넣으면 된다 —
  `[{"FCST_TIME": "2026-08-03 19:00", "FCST_CONGEST_LVL": "붐빔"}, ...]`
- `weather`(WEATHER_STTS)도 원본 키·문자열 그대로 넣으면 된다. 파서가 `"-"`·`""`·
  `"1.5mm"`를 전부 받아낸다. 소문자로 정규화해 넣어도 읽힌다
- 스냅샷이 **40분 이상 오래되면** 응답에 stale로 잡힌다. 15분 폴링이 죽으면 여기서 보인다
- `hotspot_code`는 **NULL을 그대로 둔다.** 반경 밖 POI에 임의의 코드를 채우면 실시간 신호가 거짓이 된다
- `attr_confidence < 0.3` POI는 후보에서 자동 제외된다. 별도 분기 코드가 필요 없다
- `query_vector_cache`는 72행(목적 6 × 날씨 4 × 인원밴드 3)이다. 어휘는 `app/constants.py` 참조
- **LLM 한도 실측치가 나오면 [docs/LLM_QUOTA.md](docs/LLM_QUOTA.md)에 적는다.** 배치 소요일 계산식이 같이 있다

---

## 다른 폴더와의 관계

| | |
|---|---|
| `../db/` | 스키마. **초안은 내가 쓰되** 변경은 PR + 3인 리뷰 |
| `../seeds/` | A가 채운다. 없으면 내장 픽스처로 돈다 |
| `../roleC/` | `openapi.yaml`로만 소통한다 |
| `../roleA/` | 건드리지 않는다 |

---

## 잊지 말 것

- `hotspot_code`가 NULL이면 `live_*` 항은 **None** — 0이 아니다. 가중치를 재정규화한다
- `context_fit`은 **비선형**이다. 기온은 U자형, 미세먼지는 임계값
- 거리에 직선거리만 쓰지 않는다. `ZONE_BARRIER` 10개 조합을 전부 채운다
- pgvector는 **사전 필터** 후 검색한다. 사후 필터는 정확도가 붕괴한다
- 쿼리 벡터는 `query_vector_cache`에서 **조회**한다. 온라인에서 임베딩하지 않는다
- LLM 호출 전 `explanation_cache`를 먼저 본다. 쿼터가 떨어지면 템플릿으로 폴백한다
- `recommendation_log`에 **노출됐지만 선택 안 된 후보**도 남긴다
