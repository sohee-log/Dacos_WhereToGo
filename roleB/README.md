# roleB — 추천 엔진 · 백엔드

담당 문서: [docs/ROLE_B_ENGINE.md](../docs/ROLE_B_ENGINE.md) · 설계 배경: [docs/PLAN.md](../docs/PLAN.md)

후보 생성 · 스코어링 · RAG · API를 담당한다. Render 배포 루트가 이 폴더다.

---

## 지금 상태 (W5 완료 — RAG · 설명 생성)

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

| # | W4 작업 | 상태 | 산출물 |
|---|---|---|---|
| B4-1 | `/api/recommend` 실동작 · 300ms 이내 | ✅ | **POI 5,000건에서 p50 46ms / p95 53ms** |
| B4-2 | 탐색 슬롯 | ✅ | 6~20위에서 1건, `is_exploration: true` |
| B4-3 | `template_reason()` 폴백 | ✅ | [`app/services/explain.py`](app/services/explain.py) |
| B4-4 | `recommendation_log` 기록 | ✅ | [`app/services/logging_svc.py`](app/services/logging_svc.py) — **노출 안 된 후보까지** |
| B4-5 | `/api/onboarding` · `/api/feedback` | ✅ | [`app/services/user_svc.py`](app/services/user_svc.py) + 라우터 |

🚩 **게이트: 실데이터로 추천이 나온다. LLM을 한 번도 부르지 않는다.** ✅
`llm_api_key` 없이 전 경로가 돌고, 5개 엔드포인트가 모두 DB를 본다.

**LLM 없이 완결된 것이 W4의 요점이다.** 그래야 ⓐ W5에서 RAG가 실제로 얼마나
기여하는지 잴 수 있고 ⓑ 발표 당일 쿼터가 터져도 서비스가 죽지 않는다.

### 성능 (B4-1)

| 측정 | p50 | p95 | 비고 |
|---|---|---|---|
| 5,000건 (W4, 인프로세스) | 46ms | 53ms | — |
| 5,000건 + RAG (W5, 인프로세스) | 105ms | 119ms | 인용 검색·캐시 조회가 붙었다 |
| **5,000건 + RAG (W6, 실 HTTP)** | **114ms** | **149ms** | 목표 300ms · 시나리오 20 × 3회 |

실행 계획도 함께 확인했다 — `poi` 5,000행에서 `idx_poi_geom` Bitmap Index Scan,
전체 스캔으로 떨어지는 쿼리 없음. **자세한 기록과 재측정 방법은
[docs/PERF.md](docs/PERF.md)** 에 있다.

> ⚠️ 측정할 때 두 가지를 조심한다. 둘 다 **틀린 숫자를 그럴듯하게** 만든다.
> - `RATE_LIMIT_PER_MIN=0`으로 두지 않으면 11번째부터 429가 섞여 **p50이 1ms**로 나온다
> - `--url`에 `localhost`를 쓰면 IPv6 폴백으로 요청당 **2초**가 붙는다. `127.0.0.1`을 쓴다
>
> `perf_probe`가 `/health`로 전송 바닥을 먼저 재서 이 둘을 잡아낸다.

쿼리 플랜도 확인했다 — `idx_poi_geom`(GIST) Bitmap Index Scan, 실행 12.9ms.
전체 스캔으로 떨어지지 않는다. 규모를 늘리는 방법은
`python -m tools.load_seed_db --scale 5000` (합성 데이터, 개발 전용).

| # | W5 작업 | 상태 | 산출물 |
|---|---|---|---|
| B5-1 | pgvector **사전필터** 검색 | ✅ | [`app/services/rag.py`](app/services/rag.py) |
| B5-2 | LLM 설명 생성 (JSON 스키마 강제) | ⚠️ 키 대기 | [`app/services/llm.py`](app/services/llm.py) · [`explain.py`](app/services/explain.py) |
| B5-3 | `explanation_cache` | ✅ | 히트 시 LLM 호출 0회 |
| B5-4 | **인용 원문 검증** | ✅ | 원문에 없으면 버리고 가장 가까운 청크로 대체 |
| B5-5 | 쿼터 소진 → 템플릿 자동 전환 | ✅ | `LLM_FORCE_FAIL=true`로 강제 테스트 |
| B5-6 | 레이트 리밋 (IP당 분당 10회) | ✅ | [`app/ratelimit.py`](app/ratelimit.py) |

**B5-2만 반쪽이다.** `LLM_API_KEY`가 없어 실제 호출을 확인하지 못했다. 호출 규약은
B1-5 실측(docs/LLM_QUOTA.md) 그대로이고, 응답 파싱·스키마·실패 처리·쿼터 카운터는
전부 테스트로 덮었다. **키가 없어도 서비스는 돈다** — `explain_mode`가 `template`이 될 뿐이다.

### 설명이 만들어지는 순서

```
explanation_cache 조회  →  히트하면 LLM 호출 0회       (explain_mode: cache)
미스면 LLM 호출         →  성공하면 캐시에 저장         (explain_mode: llm)
키 없음 · 쿼터 · 타임아웃 →  점수 성분 기반 템플릿        (explain_mode: template)
```

인용은 **어느 경로에서도 원문 발췌**다. LLM이 반환한 문장이 실제 `review_chunk.text`
안에 없으면 버리고 가장 가까운 원문으로 바꾼다. 대체할 것도 없으면 인용 없이 내보낸다.
그럴듯하게 지어낸 후기 한 줄이 서비스 전체의 신뢰를 깎는다.

### 발표 전날 할 일 (B6-4)

```powershell
python -m tools.warm_cache --url https://dacos-wheretogo.onrender.com
```

시나리오 20개를 두 번씩 호출한다. 두 번째가 `explain_mode: cache`로 나오면
발표 중 LLM 호출이 **0회**가 된다. 무료 티어 데모의 최대 안전장치다.

기본값이 레이트 리밋(분당 10회)에 맞춰 간격을 벌리므로 그대로 실행하면 되고,
서버에서 `RATE_LIMIT_PER_MIN=0`을 켰다면 `--no-pace`로 빨리 끝낸다.
**간격 없이 그냥 쏘면 11번째부터 429라 절반만 데워지고, 그걸 모른 채 발표장에 간다.**

> **`LLM_API_KEY`가 없으면 워밍할 것이 없다.** 설명이 템플릿으로 나가고 저장할
> LLM 결과가 없기 때문이다. 스크립트가 그 상태를 감지해 알려준다 —
> 템플릿은 LLM 없이 즉시 나가므로 **데모 자체는 그대로 가능하다.**

워밍하면서 스모크 체크도 같이 한다. 200인가 · 빈 결과가 없는가 · 인용이 붙는가.
인용이 없는 시나리오가 나오면 그 지역 POI에 `review_chunk`가 없다는 뜻이므로 A에게 알린다.

---

## 실데이터 전환 준비 (A의 W2 적재 이후)

A가 Supabase에 POI 6,644건을 넣었다. **그런데 지금 `MOCK_MODE=false`로 내리면
추천이 "가까운 곳 3건"으로 주저앉는다.** 에러가 아니라 200이 나가면서
순위만 사라지는 종류라 눈으로는 안 보인다.

```
기본 필터 (attr_confidence >= 0.30)  → 0건
반경 1.6배 두 번 확대                 → 0건
조건 완화 (0.15)                      → 0건
최근접 폴백 (하드필터 해제, 거리순)   → 3건   ← 여기까지 밀린다
```

원인은 A의 잘못이 아니다. 속성 추출이 A3-2/A4-1이라 `attr_confidence`가 아직
전 건 0인 게 **계약대로**다. 순서를 맞추면 되는 일이라 두 가지를 준비했다.

### 1. 지금 켜면 무엇이 죽는지 먼저 본다

```powershell
$env:DATABASE_URL = "postgresql://..."
python -m tools.check_data_readiness
```

B가 읽는 입력을 전부 훑어서 두 가지를 답한다.

| | |
|---|---|
| 후보가 남는가 | 하나라도 0이면 최근접 폴백으로 주저앉는다 (종료 코드 1) |
| **순위를 실제로 움직이는 가중치가 몇 %인가** | 항이 중립으로 쉬면 기여가 '적은' 게 아니라 **정확히 0**이다 |

두 번째가 이 도구의 핵심이다. "적재 끝났다"와 "추천이 의미 있다" 사이의
거리를 숫자로 만든다. 전환일에 이걸 먼저 돌리고 결정한다.

### 2. 임계값을 환경변수로 뺐다

```
ATTR_CONFIDENCE_MIN=0.30       # 기본값. 평상시 건드리지 않는다
ATTR_CONFIDENCE_RELAXED=0.15
```

화면을 먼저 확인해야 하면 Render 환경변수만 내려서 전환하고, A의 추출이
끝나면 되돌린다. **코드 수정과 재배포가 필요 없다.** 완화한 채로 두면 속성
없는 POI가 그대로 추천에 섞이므로(응답의 `low_confidence`로 드러난다)
되돌리는 것을 잊지 않는 게 먼저다.

### 3. 목과 실 경로가 갈리던 곳 두 군데를 맞췄다

A의 시드를 읽으면서 드러난 것이다. 둘 다 **에러 없이 순위만 바뀌는** 종류라
통합할 때 찾기 어렵다.

| | 전 | 후 |
|---|---|---|
| `quality_score`가 없을 때 | 목은 0.6, 실서버는 중립 0.5 — 같은 POI의 순위가 갈렸다 | 양쪽 다 중립 0.5 (`quality_term` 공용) |
| `hotspot_code`가 전 건 NULL일 때 | 목 응답에 `live_segment`/`crowd` 키가 **한 건도** 안 생겼다 | 지점 반경 규칙으로 유도해 **한 응답에 두 경우를 섞는다** |

두 번째는 C에게 직접 영향이 있다. 시드를 읽는 순간 "실시간 신호 있는 카드"가
사라져서, C가 그 배지와 `undefined` 처리(§3.3)를 화면에서 확인할 수 없었다.
A가 `hotspot_code`를 채우면 유도값은 쓰이지 않는다.

### 4. 하드필터의 NULL 안전성

`group_capacity >= :party_size`에 NULL이 들어오면 3값 논리로 WHERE가 NULL이
되어 **그 POI가 인원 수와 무관하게 항상 빠진다.** 에러도 경고도 없다.
A의 `--clear-seed-mock`이 실제로 이 컬럼을 NULL로 되돌리므로 가상의 걱정이 아니다.

인원 수를 **모르는** 것과 인원이 **안 되는** 것은 다르다. 속성 미확보는
배제가 아니라 순위 강등으로 다룬다(§1.3) — 그 역할은 `attr_confidence`가 한다.
`price_band`와 같은 규칙으로 맞췄다.

```sql
AND (p.group_capacity IS NULL OR p.group_capacity >= :party_size)
```

> `outdoor_exposure`도 같은 모양이지만 **일부러 두었다.** 우천 하드컷은
> "야외일지 모르는 곳"을 비 오는 날 빼는 것이 목적이라, 여기서 NULL을 통과시키면
> 필터의 취지가 사라진다. DDL 기본값이 `0.0`이라 실제 NULL은
> `--clear-seed-mock`이 지난 자리에만 생긴다.

---

**아직 임시인 것 (숨기지 않는다)**

| | 지금 | 언제 바뀌나 |
|---|---|---|
| 취향 유사도 | `tag_embedding`이 비면 중립 0.5 | A가 16행을 채우면 즉시 동작 |
| `explain_mode` | `LLM_API_KEY`가 없어 항상 `template` | 키가 생기면 `llm`/`cache` |
| 설명 모델 | 미정 (`gpt-5.4-nano` 기본값) | W6에 nano/mini/sonnet 비교 |

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
docker cp ..\db\migrations\ wheretogo-db:/tmp/
docker exec wheretogo-db psql -U postgres -d wheretogo -v ON_ERROR_STOP=1 -f /tmp/migrations/001_init.sql
docker exec wheretogo-db psql -U postgres -d wheretogo -v ON_ERROR_STOP=1 -f /tmp/migrations/002_tag_embedding.sql

# 개발용 적재 (운영 적재는 A). --demo-* 는 전부 가짜 데이터다
python -m tools.load_seed_db --demo-hotspot --demo-vectors
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
│       ├── logging_svc.py   # ④ recommendation_log — 노출 안 된 후보까지 (W4)
│       ├── user_svc.py      # 온보딩 프로필 + taste_vector (W4)
│       ├── rag.py           # ③ 사전필터 벡터 검색 (W5)
│       ├── llm.py           # OpenAI 호환 게이트웨이 · 쿼터 카운터 (W5)
│       └── explain.py       # 캐시 → LLM → 템플릿 · 인용 검증 (W5)
├── ratelimit.py             # IP당 분당 N회 (W5 B5-6)
├── tests/                   # 276개. test_live_db.py는 실 DB가 있을 때만 돈다
├── scenarios/               # 워밍·측정용 시나리오 20개 (C의 docs/scenarios.md 실행본)
├── tools/
│   ├── check_data_readiness.py  # 적재 상태 자가 점검 — 전환일에 먼저 돌린다
│   ├── load_seed_db.py      # 개발용 시드 적재 (운영 적재는 A)
│   ├── scenarios.py         # 시나리오 로딩 · 페이싱 · 퍼센타일 (W6 공용)
│   ├── perf_probe.py        # 응답 지연 측정 (W6 B6-2)
│   ├── query_plan.py        # 실행 계획 점검 (W6 B6-2)
│   ├── warm_cache.py        # 발표 전날 캐시 워밍 (W6 B6-4)
│   └── llm_quota_probe.py   # B1-5 측정 스크립트
├── docs/                    # 배포 절차 · LLM 한도 기록
├── openapi.yaml             # C와의 계약. 변경은 PR
└── requirements.txt         # 임베딩 모델은 여기 들어가지 않는다
```

**남은 것:** W6 — 가중치 조정(B6-1, C의 시나리오 20개 대기) ·
LLM-as-judge(B6-3, LLM 키 대기)

---

## C가 알아야 할 것

> 📄 **인수 메모: [docs/HANDOFF_TO_C.md](docs/HANDOFF_TO_C.md)** — W1~W6에서 늘어난
> 계약, C가 해야 할 인프라 작업, 화면별 변경점, 발표 전날 절차가 한 곳에 있다.
> 아래는 그중 자주 틀리는 것만 남긴 요약이다.

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

### 7. W5에 생긴 것 — `429`와 진짜 인용

- `POST /api/recommend`가 **IP당 분당 10회**로 묶인다. 넘으면 `429` + `Retry-After` 헤더다.
  서버를 지키는 게 아니라 무료 LLM 쿼터를 지키는 장치다. 다른 엔드포인트는 제한이 없다
- `evidence`가 이제 채워진다. **전부 `review_chunk`의 원문 발췌**이고, 리뷰가
  아직 없는 POI는 빈 배열이다 — 문장을 지어내지 않는다
- `explain_mode`가 실제로 갈린다: `template`(키 없음·쿼터) / `llm` / `cache`.
  지금은 키가 없어 전부 `template`이다

### 6. W4에 생긴 것 — `log_id`가 진짜다

`POST /api/recommend`의 `log_id`가 이제 **실제 `recommendation_log` 행**을 가리킨다.
`POST /api/feedback`에 그대로 실어 보내면 된다.

- 클릭 → 선택 → 만족도를 **여러 번에 나눠 보내도 된다.** 빈 값은 덮어쓰지 않는다.
  매번 전체를 다시 보낼 필요가 없다
- `404`가 오면 그 추천이 기록되지 않았다는 뜻이다. **무시하고 넘어가면 된다** —
  피드백 한 건이 빠질 뿐 사용자 흐름은 막히지 않는다
- `POST /api/onboarding`도 이제 저장한다. 같은 답을 다시 내면 같은 `user_id`가 나오고
  프로필이 갱신된다 (재제출이 안전하다)
- `GET /api/poi/{id}`가 실데이터를 준다. `reviews`에 후기 최대 5건이 실리고
  **협찬 글은 뒤로 밀린다**

---

## A가 알아야 할 것

> 📄 **인수 메모: [docs/HANDOFF_TO_A.md](docs/HANDOFF_TO_A.md)** — 무엇이 비었을 때
> 무엇이 죽는지, 조회 축의 정확한 규약, 적재 후 자가 점검 쿼리가 한 곳에 있다.
> **현재 시드로는 가용 가중치의 약 57%가 모든 POI에서 같은 값(0.5)이다.**
> 아래는 그중 자주 틀리는 것만 남긴 요약이다.

- 내가 읽는 테이블: `poi` · `segment_affinity` · `review_chunk` · `hotspot_snapshot` ·
  `query_vector_cache` · **`tag_embedding`(신규, `db/migrations/002_tag_embedding.sql`)**
- 🔴 **`tag_embedding` 16행을 채워달라.** 분위기 10 + 목적 6이고 어휘는
  `app/constants.py`와 정확히 같아야 한다. 이게 없으면 온보딩의 `taste_vector`가
  NULL이 되고 **취향 항(가중치 0.16)이 통째로 중립으로 쉰다.** 16번만 임베딩하면 된다
- `poi.tag_vector`도 같은 임베딩 공간이어야 한다. 다른 모델로 만들면 코사인이 무의미해진다
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
