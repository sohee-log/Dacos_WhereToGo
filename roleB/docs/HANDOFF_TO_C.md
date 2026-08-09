# B → C 인수 메모 (W1~W6)

> 작성 2026-08-10 · 보내는 사람 B(추천 엔진) · 받는 사람 C(프론트·배포)
> 계약 원본은 [`roleB/openapi.yaml`](../openapi.yaml)이다. 이 문서와 어긋나면 **openapi.yaml이 맞다.**

---

## 한 줄

**엔진은 W1~W5가 끝났고 W6은 절반(성능·워밍) 했다. 키가 없어 못 켠 것 두 개를 빼면
전 경로가 실데이터로 돈다.** C가 확인할 것은 **① 인프라 3개**와 **② 늘어난 응답 계약**이다.

---

## 0. 지금 prod 상태 — 아직 목이다

```
GET https://dacos-wheretogo.onrender.com/health
{"status":"ok","db":false,"mode":"mock","version":"0.1.0"}
```

`mode: mock`이다. **지금 프론트를 붙이면 픽스처 응답을 받는다.** 형태는 진짜와
같으니 UI 개발에는 문제가 없고, 목 응답에는 `X-Mock-Response: true` 헤더가 붙는다.
**이 헤더가 사라지는 시점이 실데이터로 넘어간 순간이다.**

실모드로 넘어가려면 세 가지가 필요하다. 전부 C의 손에 있다 (§1).

---

## 1. C가 해야 하는 것

### 🔴 1-1. Supabase를 붙여야 아무것도 시작되지 않는다

지금 이것 하나가 A와 B의 산출물을 전부 막고 있다.

1. SQL Editor에서 **익스텐션 먼저** — 기본 비활성이라 안 켜면 마이그레이션이 통째로 실패한다
   ```sql
   CREATE EXTENSION IF NOT EXISTS postgis;
   CREATE EXTENSION IF NOT EXISTS vector;
   ```
2. `db/migrations/001_init.sql` 적용
3. `db/migrations/002_tag_embedding.sql` 적용 — **단, 3인 리뷰 후에.**
   공동 소유 영역이라 A·B·C가 보고 나서 적용한다 (추가만 하고 기존 테이블은 안 건드린다)
4. Connection string → **Render 환경변수 `DATABASE_URL`** (`render.yaml`에 `sync: false`라 대시보드 전용)
5. A가 POI를 적재한 뒤 **Render `MOCK_MODE=false`** 로 내린다
   → `/health`가 `{"db": true, "mode": "live"}`가 되면 성공이다

> `db/README.md`에 미결로 남아 있던 "PostGIS 이미지에 pgvector가 없으면?"의 답은
> 로컬 도커 한정 문제이고 `apt-get install postgresql-16-pgvector` 한 줄이다.
> **Supabase는 둘 다 기본 제공한다.**

### 🔴 1-2. CORS — 대시보드 값이 우선한다

`render.yaml`은 이미 고쳐뒀지만 **Render 대시보드 값이 그보다 우선**한다. 양쪽을 맞춰야 한다.

```
CORS_ORIGINS = http://localhost:3000,http://127.0.0.1:3000,https://dacos-wheretogo-web.vercel.app
```

preview 배포는 도메인이 매번 바뀌어 화이트리스트로 커버되지 않는다. **검증은 prod 도메인에서** 한다.

### 🟠 1-3. Vercel 환경변수 스코프

`NEXT_PUBLIC_API_BASE`가 **Production / Preview / Development 각각**에 들어 있는지.
하나만 넣고 넘어가는 실수가 흔하다. 값은 `https://dacos-wheretogo.onrender.com`.

### 🟠 1-4. 끝나면 이걸로 확인한다

`https://dacos-wheretogo-web.vercel.app`을 열고 콘솔에서:
```js
fetch("https://dacos-wheretogo.onrender.com/health").then(r=>r.json()).then(console.log)
```
CORS 에러 없이 `{db:true, mode:"live"}`가 나오면 W1 게이트가 진짜로 닫힌다.

### 🟡 1-5. 사소하지만 남아 있는 것

- 랜딩(`roleC/app/page.tsx`)이 아직 **create-next-app 기본 화면**이다. `/onboarding` 진입 링크가 없다
- 각자 `git config core.hooksPath .githooks` 1회 (레포가 public이다)
- `ROLE_C_WEB.md` §4 검증표의 빈칸 3개 (Render 결제수단 요구 여부 / Supabase 한도 / 열린데이터 한도)
- `render.yaml`의 서비스 이름이 `wheretogo-api`인데 **실제 서비스는 `dacos-wheretogo`** 다.
  Blueprint를 다시 돌리면 두 번째 서비스가 생겨 무료 750시간을 나눠 쓰게 된다.
  Blueprint 연결인지 수동 생성인지 확인이 필요하다

---

## 2. 응답 계약 — W1 이후 늘어난 것

**전부 추가·선택 필드다. 기존 화면은 깨지지 않는다.** 다만 상태 코드 두 개는 처리해야 한다.

| 엔드포인트 | 상태 코드 | W1 대비 |
|---|---|---|
| `POST /api/recommend` | 200 · 422 · **429** · **503** | 429·503 신규 |
| `GET /api/context/now` | 200 · **503** | 503 신규 |
| `POST /api/onboarding` | 200 · 422 · **503** | 503 신규 |
| `POST /api/feedback` | 204 · 404 · **503** | 503 신규 |
| `GET /api/poi/{id}` | 200 · 404 · **503** | 503 신규 |

### 2-1. `503` — 목으로 되돌아가지 않는다

실모드에서 DB에 닿지 못하거나 POI가 아직 적재되지 않으면 **503**이다.

```jsonc
{ "detail": "추천 데이터를 사용할 수 없습니다: DB에 닿지 못했다: ..." }
```

목 응답으로 대신하지 않는다 — **가짜 장소를 진짜처럼 띄우지 않기 위해서**다.
**콜드스타트 안내(C4-5)와 같은 자리**에서 "잠시 후 다시 시도"로 처리하면 된다.
무한 스피너나 빈 화면이 아니라 재시도 버튼이 필요하다. 응답은 3초 안에 온다.

### 2-2. `429` — 분당 10회

`POST /api/recommend`만 **IP당 분당 10회**다. 넘으면 `429` + `Retry-After` 헤더.

```jsonc
{ "detail": "요청이 너무 잦습니다. 잠시 후 다시 시도해 주세요.", "code": "rate_limited" }
```

서버를 지키는 게 아니라 **무료 LLM 쿼터**를 지키는 장치다. 다른 엔드포인트는 제한이 없고
`/health`는 절대 막지 않는다. 검색 조건을 바꿀 때마다 자동 재요청하는 UI라면 디바운스가 필요하다.

### 2-3. `context.weather_source` (신규)

날씨를 어디서 가져왔는지 응답에 실린다.

| 값 | 뜻 |
|---|---|
| `citydata` | 실시간 도시데이터 실황 (방문이 2시간 이내) |
| `kma` / `kma+citydata` | 기상청 단기예보 (방문이 3시간 이상 뒤) |
| `mock` | **소스가 없어 만들어낸 값** |

**화면에 그릴 필요는 없다.** 다만 `?debug=1` 화면(C4-4)에 한 줄 띄워 두면
배너 날씨가 이상할 때 원인이 즉시 보인다. **실서버에서 `mock`이 뜨면 키가 없거나
적재가 안 된 것**이다.

### 2-4. `context.sunset`이 분까지 온다

`"19:00"`이 아니라 `"19:42"`다. 해질녘 야외를 고를 때 체감이 다르다.

---

## 3. 화면별로 달라지는 것

### 3-1. `ContextBanner` (C3-4) — 이제 값이 진짜다

```
🌧 {weather} · 체감 {feels_like}° · 미세먼지 {pm25_grade}
📍 {hotspot} · 지금 {congest_now} → {congest_forecast_at_visit} 예상 · {age_mix_top}
```

- `congest_forecast_at_visit`은 **방문 예정 시각의 예측**이다. `congest_now`와
  **값이 갈리는 것이 정상**이고, 갈릴 때가 이 서비스의 차별점이 보이는 순간이다
- 둘 다 `null`이면 그 좌표가 실시간 지점 반경 **밖**이라는 뜻이다. 용산 POI의
  상당수가 여기 해당한다 — **문구를 지어내지 말고 그 줄을 통째로 숨긴다**
- `age_mix_top`도 같다. `null`이면 표시하지 않는다

### 3-2. `ResultCard` — `evidence`가 채워진다

```jsonc
"evidence": [{ "text": "비 오는 날 창가 자리에서 보는 뷰가 좋아요", "source": "naver_blog" }]
```

**전부 실제 후기 원문의 발췌다.** LLM이 지어낸 문장은 후처리에서 걸러진다.
리뷰가 아직 없는 POI는 **빈 배열**이므로 인용 영역을 통째로 숨겨야 한다.

`explain_mode`도 실제로 갈린다.

| 값 | 뜻 |
|---|---|
| `template` | 점수 성분으로 만든 문장 (LLM 없이) |
| `llm` | LLM이 생성 |
| `cache` | 캐시 히트 (LLM 호출 0회) |

**지금은 `LLM_API_KEY`가 없어 전부 `template`이다.** 배지를 그린다면 세 값을 다 그려두면 된다.

### 3-3. `ScoreDebug` (C4-4) — `live_segment`/`crowd`는 **키가 없을 수 있다**

W1부터 말한 것이지만 실데이터에서 실제로 그렇게 나온다. 로컬 시드 기준
**지점 반경 안 38 / 밖 62** 로 갈렸다.

```jsonc
// 지점 반경 안
"score_breakdown": { "segment":0.83, ..., "live_segment":0.79, "crowd":0.50 }

// 반경 밖 — 키 자체가 없다. null도 0도 아니다
"score_breakdown": { "segment":0.79, "purpose":0.95, "taste":0.77, "context":0.95,
                     "quality":0.72, "distance":0.36 }
```

`undefined`를 0으로 렌더링하면 "실시간 신호 없음"이 "실시간 점수 0점"으로 뒤바뀐다.
**항목을 숨기거나 "해당 없음"으로 표시한다.**

### 3-4. `log_id`가 진짜다 — 피드백 연동 (C4-2)

`POST /api/recommend`의 `log_id`가 실제 로그 행을 가리킨다. 그대로 실어 보내면 된다.

- **클릭 → 선택 → 만족도를 여러 번에 나눠 보내도 된다.** 빈 값은 덮어쓰지 않으므로
  매번 전체를 다시 보낼 필요가 없다
- `404`는 "그 추천이 기록되지 않았다"는 뜻이다. **무시하고 넘어가면 된다** —
  피드백 한 건이 빠질 뿐 사용자 흐름은 막히지 않는다

### 3-5. 온보딩 (C2-1)

`POST /api/onboarding`이 이제 저장한다. **같은 답을 다시 내면 같은 `user_id`가
나오고 프로필이 갱신된다** — 재제출이 안전하다. 목/실 모드에서 규칙이 같아
모드를 오가도 로컬 저장값이 깨지지 않는다.

5번 문항(`weather_sensitivity`)은 실제로 점수를 바꾼다. 민감하다고 답한 사용자는
같은 강수확률에서 야외 장소가 더 크게 내려간다. **빠뜨리면 개인화 항 하나가 죽는다.**

### 3-6. 상세 (`GET /api/poi/{id}`)

실데이터를 준다. `reviews`에 후기 최대 5건이 실리고 **협찬 글은 뒤로 밀린다**.

---

## 4. C에게 부탁하는 것 하나 — 시나리오 파일

`roleB/scenarios/warm_scenarios.json`을 **성능 측정(B6-2)과 캐시 워밍(B6-4)이 함께
쓴다.** 지금은 내가 축을 덮어 20개를 채워뒀다 — 목적 6종 · zone 5개 전부 ·
인원 3밴드 · 지점 반경 밖 5개 이상.

**`docs/scenarios.md`(C5-4)가 확정되면 이 파일을 갱신해 달라.**
원본은 위치를 `이태원1동`처럼 동 이름으로 적는데 API는 좌표를 받아서, 20줄을
한 번 옮기는 작업이 필요하다.

같은 시나리오를 태워야 "측정한 것"과 "데워 둔 것"이 어긋나지 않는다.

---

## 5. 발표 전날 (C6-3) — 워밍은 C가 실행한다

```powershell
cd roleB
python -m tools.warm_cache --url https://dacos-wheretogo.onrender.com
```

시나리오 20개를 두 번씩 호출한다. 두 번째가 `explain_mode: cache`로 나오면
**발표 중 LLM 호출이 0회**가 된다. 무료 티어 데모의 최대 안전장치다.

> ⚠️ **간격 없이 그냥 쏘면 11번째부터 429다.** 절반만 데워지고 그걸 모른 채
> 발표장에 간다. 기본값이 레이트 리밋에 맞춰 간격을 벌리므로 **그대로 실행**하면 되고,
> 서버에서 `RATE_LIMIT_PER_MIN=0`을 켰다면 `--no-pace`로 빨리 끝낸다.

`LLM_API_KEY`가 없으면 캐시를 채울 것이 없다 — 스크립트가 그 상태를 감지해 알려준다.
템플릿 설명은 LLM 없이 즉시 나가므로 **데모 자체는 그대로 가능하다.**

워밍하면서 스모크 체크도 한다(200 / 빈 결과 / 인용). 인용이 없는 시나리오가
나오면 그 지역 POI에 후기가 없다는 뜻이니 A에게 알린다.

---

## 6. 성능 — 프론트 쪽 기대치

로컬 실측(POI 5,000건, 실 HTTP): **p50 114ms · p95 149ms** (목표 300ms).
자세한 것은 [`docs/PERF.md`](PERF.md).

다만 **Render Free는 이보다 느리다.** 인스턴스가 작고 Supabase가 네트워크 너머에 있다.
그리고 15분 무접속이면 슬립하므로 **첫 요청이 1분까지 갈 수 있다** — 콜드스타트
안내(C4-5)는 반드시 필요하다. UptimeRobot(C2-5)을 걸면 크게 줄어든다.

---

## 7. 아직 못 켠 것 두 개 — C가 기다릴 필요는 없다

| 필요한 키 | 켜지는 것 | 없을 때 |
|---|---|---|
| `KMA_SERVICE_KEY` | 3시간 뒤 방문의 **강수확률 예보** | citydata 실황으로 자동 폴백 |
| `LLM_API_KEY` | `explain_mode: llm`/`cache`, LLM이 고른 3~5곳 | 템플릿 + RAG 인용 |

**둘 다 없어도 모든 화면이 정상 동작한다.** 코드는 이미 들어가 있어서, 키가
Render 환경변수에 꽂히면 프론트 변경 없이 켜진다. 공공데이터포털 승인이 1~2일
걸리니 신청만 먼저 해두면 된다.

---

## 8. 한 장 체크리스트

- [ ] Supabase 익스텐션(`postgis`, `vector`) → `001_init.sql` → (3인 리뷰 후) `002_tag_embedding.sql`
- [ ] Render `DATABASE_URL` 입력 → A 적재 후 `MOCK_MODE=false`
- [ ] Render `CORS_ORIGINS`에 Vercel prod 도메인 (대시보드 값이 우선)
- [ ] Vercel `NEXT_PUBLIC_API_BASE` 3개 스코프 확인
- [ ] prod에서 fetch 왕복 200 확인 (`X-Mock-Response` 헤더가 사라졌는지)
- [ ] `503` 처리 (재시도 안내) · `429` 처리 (디바운스)
- [ ] `live_segment`/`crowd` 키 부재 처리 — 0으로 렌더링 금지
- [ ] `evidence` 빈 배열 처리 (인용 영역 숨김)
- [ ] `congest_*`·`age_mix_top`이 `null`일 때 배너 줄 숨김
- [ ] `log_id` 피드백 연동 (분할 전송 가능, 404는 무시)
- [ ] `docs/scenarios.md` 확정 → `roleB/scenarios/warm_scenarios.json` 갱신
- [ ] 발표 전날 `python -m tools.warm_cache`

막히면 `openapi.yaml`을 먼저 보고, 그래도 다르면 B에게. 계약 변경은 PR로 한다.
