# roleB — 추천 엔진 · 백엔드

담당 문서: [docs/ROLE_B_ENGINE.md](../docs/ROLE_B_ENGINE.md) · 설계 배경: [docs/PLAN.md](../docs/PLAN.md)

후보 생성 · 스코어링 · RAG · API를 담당한다. Render 배포 루트가 이 폴더다.

---

## 지금 상태 (W1 완료)

**목(mock) 모드로 동작한다. DB가 없어도 뜬다.** W1의 산출물은 기능이 아니라 계약이기 때문이다.

| # | W1 작업 | 상태 | 산출물 |
|---|---|---|---|
| B1-1 | DDL 초안 | ✅ | [`db/migrations/001_init.sql`](../db/migrations/001_init.sql) |
| B1-2 | OpenAPI 스펙 | ✅ | [`openapi.yaml`](openapi.yaml) |
| B1-3 | Pydantic 모델 | ✅ | [`app/schemas.py`](app/schemas.py) — 계약 대조 테스트 포함 |
| B1-4 | 목 API | ✅ 코드 완료 / ⏳ 배포 대기 | [`app/`](app) · [`../render.yaml`](../render.yaml) · [배포 절차](docs/DEPLOY_MOCK.md) |
| B1-5 | LLM 한도 실측 | ⏳ **키 조달 후 측정** | [측정 스크립트](tools/llm_quota_probe.py) · [기록 문서](docs/LLM_QUOTA.md) |

> B1-5는 LLM 제공자와 키가 정해져야 잴 수 있다. **스크립트와 기록 양식은 준비되어 있고,
> 키가 생기면 명령 한 줄로 끝난다.** 이 숫자가 A의 W3 배치 일정을 결정하므로 우선순위가 높다.

---

## 실행

```powershell
cd roleB
python -m venv .venv; .\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt

uvicorn app.main:app --reload --port 8000    # http://localhost:8000/docs
pytest tests/ -v
```

배포는 [docs/DEPLOY_MOCK.md](docs/DEPLOY_MOCK.md).

---

## 구조

```
roleB/
├── app/
│   ├── main.py              # FastAPI 앱, CORS, /health
│   ├── config.py            # 환경변수 (시크릿은 코드에 없다)
│   ├── constants.py         # 고정 어휘 · 가중치 · ZONE_BARRIER
│   ├── schemas.py           # Pydantic — C와의 계약
│   ├── mock_data.py         # W1 목 데이터 (W2에 제거된다)
│   ├── routers/             # 5개 엔드포인트
│   └── services/
│       └── scoring.py       # 재정규화 + 거리 수식 (W2에 항 계산이 채워진다)
├── tests/                   # 51개 — 계약 대조 · 재정규화 · 목 API 형태
├── tools/llm_quota_probe.py # B1-5 측정 스크립트
├── docs/                    # 배포 절차 · LLM 한도 기록
├── openapi.yaml             # C와의 계약. 변경은 PR
└── requirements.txt         # 임베딩 모델은 여기 들어가지 않는다
```

**아직 없는 것 (주차별로 채운다):** `db.py`(W2) · `retrieval.py`(W2) · `context_fit.py`(W3) ·
`live_signals.py`(W3) · `rag.py`(W5) · `explain.py`(W5) · `logging_svc.py`(W4)

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

---

## A가 알아야 할 것

- 내가 읽는 테이블: `poi` · `segment_affinity` · `review_chunk` · `hotspot_snapshot` · `query_vector_cache`
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
