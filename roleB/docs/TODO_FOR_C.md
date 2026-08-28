# C(프론트·배포)가 해야 할 것 — 2026-08-28 기준

> 작성 B(추천 엔진) · 받는 사람 C(프론트·배포)
> `origin/main` 기준 · 배포·DB는 **실제로 호출해서** 확인한 값이다.
> 계약 원문은 [`HANDOFF_TO_C.md`](HANDOFF_TO_C.md), 이번 계약 수정 내역은 [`FEEDBACK_TO_C_CONTRACT.md`](FEEDBACK_TO_C_CONTRACT.md), 전체 상황은 [`BRIEF_2026-08-28.md`](BRIEF_2026-08-28.md).

---

## 먼저 — 잘 되어 있는 것

W3 컴포넌트가 전부 들어와서 화면은 사실상 완성이다.

```
✅ 온보딩 5문항 · TagGrid
✅ RequestForm · ResultCard · KakaoMap · ContextBanner
✅ 로딩 / 에러 / 빈결과 3상태 (예산 완화 버튼까지)
✅ 503 재시도 · 429 카운트다운 · 콜드스타트 안내
✅ ?debug=1 의 ScoreDebug
✅ keepalive.yml (오늘 추가됨)
✅ CI lint + build 계속 통과
```

특히 `ScoreDebug`가 **`live_segment`/`crowd`의 `undefined`를 0으로 그리지 않는 것** —
가장 틀리기 쉬운 자리인데 정확하게 되어 있다. 모르는 것과 0은 다르다.

---

## 우선순위 요약

| 순 | 항목 | 없으면 | 예상 |
|---|---|---|---|
| 🔴 **1** | [C-1 Render 환경변수 2개](#c-1-render-환경변수--코드-0줄-최대-효과) | **배포된 데모가 목 데이터로 돈다** | 5분 |
| 🔴 **2** | [C-2 계약 타입 생성 규칙 숙지](#c-2-libapi-typests-는-생성-파일이다-손으로-고치지-말-것) | `npm run build`가 CI에서 깨진다 | 읽기만 |
| 🔴 **3** | [C-3 만족도 UI (1~5)](#c-3-사후-만족도-ui-1-5--c4-3-미구현) | 폐루프의 마지막 칸이 빈다 | 1시간 |
| 🟠 **4** | [C-4 `user_id` 로컬 저장](#c-4-user_id-가-url-쿼리에만-있다-c2-4) | 새로고침·직접진입에서 온보딩으로 튕긴다 | 30분 |
| 🟠 **5** | [C-5 UptimeRobot](#c-5-uptimerobot-등록-c2-5) | 데모 첫 요청이 콜드스타트 1분 | 10분 |
| 🟡 **6** | [C-6 시나리오 20개 확정](#c-6-평가-시나리오-20개-c5-4) | M8 리허설의 입력이 없다 | 30분 |
| 🟡 **7** | [C-7 사용자 테스트](#c-7-사용자-테스트-c6-1) | 로그 208건이 전부 B의 테스트다 | 반나절 |
| 🟡 **8** | [C-8 캐시 워밍 + 리허설 2회](#c-8-캐시-워밍-c6-3--리허설-2회-c6-4) | 발표 당일 LLM 쿼터 사고 | 2시간 |
| ⚪ **9** | [C-9 README + 데모 GIF](#c-9-readme--데모-gif-c6-5) | 포트폴리오 | 1시간 |

---

## C-1. Render 환경변수 — 코드 0줄, 최대 효과

### 지금 상태 (방금 호출한 결과)

```
GET https://dacos-wheretogo.onrender.com/health
{"status":"ok","db":false,"mode":"mock","version":"0.1.0"}
                ^^^^^^^^^^^^^^^^^^^^^^^^
```

**배포된 데모가 목 데이터로 돈다.** A가 넣은 POI 6,644건도, `segment_affinity` 44,064행도,
B가 고친 개인화도 **화면에 하나도 안 나오고 있다.**

DB에는 다 들어 있다. Render가 안 보고 있을 뿐이다.

### 무엇을 바꾸나

Render 대시보드 → 서비스 → **Environment**

| 키 | 지금 | 바꿀 값 |
|---|---|---|
| `DATABASE_URL` | 미설정 | Supabase **Session pooler** DSN |
| `LLM_API_KEY` | 미설정 | 팀 조달 키 (B가 갖고 있다) |
| `LLM_MODEL` | `gpt-5.4-nano` (404) | `gemini-3.5-flash-lite` |
| `MOCK_MODE` | `true` | **아직 그대로 둔다.** 아래 순서 참고 |

> ✅ **`LLM_API_KEY`를 넣으면 설명이 템플릿에서 LLM 문장으로 바뀐다.** 2026-08-28에
> 로컬에서 실동작을 확인했다 — *"이태원 중심에 위치해 있어 2인 데이트 코스로
> 방문하기에 좋습니다"* 같은 문장이 나온다. 지금 배포본은 키가 없어 전부 템플릿이다.
>
> 같은 날 **`explanation_cache`가 한 번도 저장되지 않던 버그도 고쳤다**(PR #33).
> 그래서 이제 캐시 워밍(C-8)이 실제로 먹는다 — 같은 요청 2회차가 **3,586ms → 405ms**다.
> 키가 없으면 워밍은 무의미하다(저장할 LLM 결과가 없다).

> ⚠️ **`render.yaml`을 고쳐도 대시보드에 값이 들어가 있으면 대시보드가 이긴다.**
> 반드시 대시보드에서 확인할 것.

> ⚠️ **DSN은 Session pooler 쪽을 쓴다.** Direct connection(`db.<ref>.supabase.co`)은
> IPv6 전용이라 환경에 따라 `getaddrinfo failed`가 난다. 실제로 이 환경에서 안 붙었다.
> `aws-0-ap-northeast-2.pooler.supabase.com` 쪽이 안전하다.

> ⚠️ **비밀번호에 `!` 같은 특수문자가 있으면 URL 인코딩한다** (`!` → `%21`).
> 안 하면 파싱이 조용히 어긋난다.

### 전환 순서 (이 순서를 지킬 것)

```
1. DATABASE_URL · LLM_API_KEY · LLM_MODEL 입력   ← MOCK_MODE=true 인 동안은 풀을 안 연다. 안전하다
2. 재배포 후 /health 확인                        → {"db": true, "db_reason": "MOCK_MODE=true · DSN 연결 OK"}
3. B에게 알린다 → B가 check_data_readiness 로 전환 판정
4. MOCK_MODE=false                               → {"db": true, "mode": "live"}
5. 화면에서 ?debug=1 로 low_confidence / radius_expanded 확인
```

`MOCK_MODE=false`를 먼저 내리지 말 것. DB가 안 붙은 상태에서 내리면 **503이 아니라
200이 나가면서 순위만 사라지는** 경로로 갈 수 있다.

### `/health` 로 원인을 구분한다

`db`는 **목 모드에서도 실제 연결을 확인한 결과**다(2026-08-28 추가). `db_reason`이
왜 그 값인지 말해 준다. 이 네 가지를 구분할 수 있다.

| `/health` 응답 | 뜻 | 할 일 |
|---|---|---|
| `db:true` · `MOCK_MODE=true · DSN 연결 OK` | **설정 완료.** 전환만 남았다 | 3번으로 |
| `db:false` · `MOCK_MODE=true · DATABASE_URL 없음` | 환경변수가 안 들어갔다 | 대시보드 확인. **`render.yaml`을 고쳐도 대시보드가 이긴다** |
| `db:false` · `... password authentication failed ...` | 비밀번호가 틀렸다 | 특수문자 URL 인코딩 확인 (`!` → `%21`) |
| `db:false` · `... getaddrinfo failed ...` | 호스트를 못 찾는다 | **Direct connection(IPv6) 대신 Session pooler DSN**을 쓴다 |

> 이전에는 `db`를 `MOCK_MODE=false`일 때만 검사해서, **DSN이 정확해도 목 모드면
> 무조건 `db:false`** 였다. 설정이 틀린 것과 구분이 안 됐다.

### 완료 기준

```
GET /health  →  {"status":"ok","db":true,"mode":"live","version":"0.1.0"}
```

---

## C-2. `lib/api-types.ts` 는 생성 파일이다 — 손으로 고치지 말 것

PR #27이 머지되면서 **API 계약 타입이 생성 파일로 바뀌었다.**

```
roleB/openapi.yaml  ──(roleB/tools/gen_ts_types.py)──▶  roleC/lib/api-types.ts
```

### 알아야 할 것

- **`roleC/lib/api-types.ts`를 직접 수정하면 다음 생성에서 덮어써진다.**
- **`roleC/lib/types.ts`는 화면 전용 타입만** 갖는다(`ApiError` 클래스 등). API 타입은 re-export.
- 타입을 바꾸려면 → `openapi.yaml`을 고치고 생성기를 돌린다 = **B에게 말한다.**
- CI에 `TS contract in sync` 스텝이 있다. **openapi만 고치고 생성기를 안 돌리면 CI가 막는다.**

### 왜 이렇게 됐나

손으로 베껴 쓰던 시절 세 곳이 어긋나 있었고 **셋 다 화면은 멀쩡하고 기능만 사라지는** 형태였다.

- `POST /api/feedback`이 전부 **422** — `clicked`를 boolean으로 보냈다.
  `.catch()`가 삼켜서 콘솔에만 찍혔고 `recommendation_log`가 통째로 비었다
- `getContextNow()`가 필수 쿼리 `lat`/`lng`를 안 붙였다 (잠복)
- `low_confidence` · `radius_expanded` · `image_url` · `rain_prob` 누락

같은 PR에서 **온보딩 연령대가 40대에서 끊겨 있던 것**도 고쳤다.
엔진과 `segment_affinity`는 60까지 받는데 화면이 40이 최대라 **50·60대가 40대로 집계되고 있었다.**

### 피드백 계약 (지금 형태)

```ts
postFeedback({ log_id, clicked?: string[], selected?: string, feedback?: 1|2|3|4|5 })
```

- `clicked` — **클릭한 poi_id들의 배열.** boolean이 아니다
- `selected` — **선택한 poi_id 문자열.** boolean이 아니다
- `feedback` — 만족도 1~5. 필드명이 `satisfaction`이 아니다
- **나눠 보내도 된다.** 빈 값은 서버가 덮어쓰지 않고, `clicked`는 **합집합**으로 누적된다
  (카드마다 한 건씩 보내도 앞선 클릭이 안 지워진다)

---

## C-3. 사후 만족도 UI (1~5) — C4-3 미구현

### 지금 상태

`ResultCard.tsx`에 주석만 있고 UI가 없다.
`recommendation_log.feedback`은 **영원히 NULL**이다.

이게 폐루프의 마지막 칸이다. M7(온보딩 → 추천 → 피드백 전 흐름)이 여기서 닫힌다.

### 무엇을 만드나

**결과 카드를 클릭(선택)한 뒤** 1~5 별점/버튼을 노출한다.

```tsx
// components/ResultCard.tsx — 개략
const [rated, setRated] = useState<number | null>(null);

const handleRate = (score: number) => {
  setRated(score);
  postFeedback({
    log_id: logId,
    selected: place.poi_id,   // 선택한 poi_id (문자열)
    feedback: score,          // 1~5  (satisfaction 아니다)
  }).catch((err) => console.error('만족도 전송 실패', err));
};

{clicked && (
  <div className="flex items-center gap-2 border-t border-slate-100 pt-3">
    <span className="text-[10px] text-slate-400">이 추천 어땠나요?</span>
    {[1, 2, 3, 4, 5].map((n) => (
      <button
        key={n}
        onClick={(e) => { e.stopPropagation(); handleRate(n); }}
        disabled={rated !== null}
        aria-label={`${n}점`}
        className={rated !== null && n <= rated ? 'text-amber-400' : 'text-slate-300'}
      >
        ★
      </button>
    ))}
    {rated !== null && <span className="text-[10px] text-emerald-500">감사합니다</span>}
  </div>
)}
```

### 주의 세 가지

1. **`e.stopPropagation()`** — 카드 전체에 `onClick`(클릭 로깅)이 걸려 있다. 안 막으면 별점을
   누를 때마다 클릭 로그가 또 나간다.
2. **`selected`와 `feedback`을 같이 보낸다.** 만족도를 남긴다는 건 그 POI를 골랐다는 뜻이다.
3. **실패해도 화면을 막지 않는다.** 404("그 추천이 기록되지 않았다")는 `api.ts`가 이미 삼킨다.

### 완료 기준

```sql
SELECT count(*) FILTER (WHERE feedback IS NOT NULL) FROM recommendation_log;
-- 실제 사용자 테스트 후 0보다 커야 한다
```

브라우저 콘솔에 `[계약 위반] POST /api/feedback 422` 가 **안 찍혀야** 한다.
찍히면 필드 이름이 틀린 것이니 위 계약을 다시 본다.

---

## C-4. `user_id` 가 URL 쿼리에만 있다 (C2-4)

### 지금 상태

```ts
// app/recommend/page.tsx:24
const userId = searchParams.get('user_id');
```

```ts
// components/OnboardingForm.tsx:73
window.location.href = `/recommend?user_id=${data.user_id}&mood=...`;
```

`localStorage`를 쓰는 곳이 한 군데도 없다. 그래서:

- 사용자가 `/recommend`를 북마크했다가 다시 들어오면 **`user_id`가 없어서 튕긴다**
- 주소창을 정리하거나 링크를 공유하면 프로필이 사라진다
- **데모 중에 실수로 URL을 잃으면 온보딩부터 다시 해야 한다**

### 무엇을 하나

```ts
// lib/session.ts (신규)
const KEY = 'wheretogo.user_id';

export function saveUserId(id: string) {
  try { localStorage.setItem(KEY, id); } catch { /* 프라이빗 모드 등 — 무시 */ }
}

export function loadUserId(): string | null {
  try { return localStorage.getItem(KEY); } catch { return null; }
}

export function clearUserId() {
  try { localStorage.removeItem(KEY); } catch { /* 무시 */ }
}
```

```ts
// OnboardingForm — 성공 직후
saveUserId(data.user_id);

// recommend/page.tsx — URL 우선, 없으면 로컬
const userId = searchParams.get('user_id') ?? loadUserId();
```

**`try/catch`를 반드시 감싼다.** 프라이빗 브라우징이나 사이트 데이터 차단 설정에서
`localStorage` 접근 자체가 예외를 던진다. 발표 중에 그걸로 화면이 죽으면 안 된다.

> URL 파라미터를 없애지는 말 것. 지금 온보딩 → 추천 흐름이 그걸로 돌고, 디버깅에도 편하다.
> **URL이 있으면 URL, 없으면 로컬** 순서면 충분하다.

### 완료 기준

온보딩을 마친 뒤 `/recommend`로 **직접** 들어가도 추천이 나온다.
새로고침·탭 재개에서도 유지된다.

---

## C-5. UptimeRobot 등록 (C2-5)

Render Free는 **15분 무접속이면 슬립**한다. 다음 첫 요청이 최대 1분 걸린다.

**발표 당일 첫 시연이 그 1분에 걸리면 가장 나쁘다.** 화면은 로딩만 돌고, 심사위원은
서비스가 느리다고 판단한다. `keepalive.yml`은 Supabase용이지 Render용이 아니다.

- 모니터 종류: HTTP(s)
- URL: `https://dacos-wheretogo.onrender.com/health`
- 간격: **5분**

무료 플랜으로 충분하다. 등록 후 Render 로그에 5분 간격 요청이 찍히는지 확인한다.

---

## C-6. 평가 시나리오 20개 (C5-4)

`docs/scenarios.md`가 없다. 그런데 **새로 쓸 필요가 없다** —
B가 `roleB/scenarios/warm_scenarios.json`에 20개를 이미 만들어 뒀고,
`perf_probe`·`warm_cache`·`scenario_report` 세 도구가 전부 그걸 태운다.

**측정·워밍·평가가 같은 시나리오를 봐야 의미가 있다.** 따로 만들면 어긋난다.

### 지금 20개의 축

```
목적 6종 전부 · 인원 1~2 / 3~4 / 5+ · zone 5종 전부
연령 6종(10~60) · 성별 2종 · 날씨민감도 3종
시간대 08 / 10~14 / 15~20 / 22시
```

**실 DB에서 20/20이 전부 결과 5건을 반환한다**(A6-4 통과, 인용도 전부 붙는다).
`roleB/docs/SCENARIO_REPORT.md`에 실측 결과가 있다.

### C가 할 일

1. `warm_scenarios.json`의 20개를 **사람이 읽을 형태로** `docs/scenarios.md`에 옮긴다
   (ID · 상황 설명 · 기대 결과 · 시연 포인트)
2. **좌표가 실제 위치와 맞는지 확인한다.** 사람은 "이태원역 1번 출구"로 생각하는데
   API는 좌표를 받는다. 이 매핑이 틀리면 시나리오가 엉뚱한 동네를 가리킨다
3. 바꾸고 싶은 게 있으면 **JSON을 고치고 B에게 알린다.** 테스트가 축 커버리지를 검증한다

---

## C-7. 사용자 테스트 (C6-1)

### 지금 상태

```
recommendation_log   208건
  clicked 있음        16건
  feedback 있음       14건
  distinct user_id    1~2명 (전부 B의 테스트)
```

목표는 **지인 10명 이상 · 로그 200건**인데, 지금 208건은 전부 개발 중 테스트다.

### 전제 조건

- **C-1(Render 환경변수)이 먼저다.** 목 데이터로 사용자 테스트를 하면 아무 의미가 없다
- **C-3(만족도 UI)도 먼저다.** 만족도가 안 쌓이면 절반짜리 로그가 된다

### 확인할 것

테스트 뒤 이 쿼리로 진짜 사용자 데이터가 쌓였는지 본다.

```sql
SELECT date_trunc('day', requested_at) d, count(*) n,
       count(DISTINCT user_id) users,
       count(*) FILTER (WHERE clicked IS NOT NULL)  clicked,
       count(*) FILTER (WHERE feedback IS NOT NULL) rated
FROM recommendation_log GROUP BY 1 ORDER BY 1 DESC;
```

`users`가 10 이상이어야 한다.

---

## C-8. 캐시 워밍 (C6-3) + 리허설 2회 (C6-4)

### 왜 하나

발표 중 LLM 호출을 **0회**로 만든다. 무료 티어 데모가 실패하는 경로는 거의 항상
**쿼터 소진**과 **콜드스타트** 둘이다. 워밍이 앞의 것을 막는다.

### 도구는 B가 만들어 뒀다

```powershell
cd roleB
python -m tools.warm_cache --url https://dacos-wheretogo.onrender.com
```

- 시나리오 20개를 **온보딩부터** 태우고, 각 시나리오를 2회 부른다
- 두 번째 회차가 `explain_mode: cache`면 성공이다
- 레이트 리밋(분당 10회)에 맞춰 간격을 벌린다. 20 × 2 = 40호출이라 **약 5분** 걸린다

> ⚠️ **`LLM_API_KEY`가 없으면 캐시는 안 채워진다.** 설명이 템플릿으로 나가 저장할 게 없다.
> 스크립트가 그 상태를 감지해서 알려준다. **키 없이 데모한다면 워밍은 불필요하다** —
> 템플릿은 언제나 즉시 나온다.

> ⚠️ **워밍은 발표 전날 밤에 한다.** 그리고 그 뒤로 `explanation_cache`를 비우지 않는다.

### 리허설 2회 (C6-4)

**실제 배포본으로** 한다. 로컬에서 도는 것과 Render Free에서 도는 것은 다르다.

체크리스트:

```
□ 첫 요청 콜드스타트가 안 나는가 (UptimeRobot 등록 후)
□ 온보딩 → 추천 → 클릭 → 만족도가 한 번에 통과하는가
□ 같은 좌표에서 시각을 바꾸면 결과가 실제로 바뀌는가   ← 차별점 시연의 핵심
□ 비 예보 시나리오에서 실내 위주로 바뀌는가
□ ?debug=1 에서 low_confidence / radius_expanded 가 false 인가
□ 인용(evidence)이 카드마다 붙는가
□ 20개 시나리오 전부 결과가 나오는가
```

세 번째 항목이 이 서비스의 핵심이다. **시각·날씨를 바꿔 결과가 달라지는 걸 보여주는 게
발표에서 가장 강한 카드다.** B가 실측으로 확인해 뒀다 — 13시와 19시의 추천이 서로 다르다.

---

## C-9. README + 데모 GIF (C6-5)

포트폴리오용. 최소한 이것만 있으면 된다.

- 서비스가 무엇인지 3줄
- **차별점 3개** — ① 실시간 인구·날씨로 후보를 바꾼다 ② CF 없이 공공 소비통계로 개인화한다
  ③ 리뷰를 온라인 LLM에 태우지 않고 구조화 속성으로 미리 뽑는다
- 아키텍처 다이어그램 (A가 A6-2에서 만든다)
- **데모 GIF** — 온보딩 → 추천 → 시각 변경 → 결과가 바뀌는 장면
- 무료 티어로 어떻게 돌렸는지 (이게 의외로 평가에서 잘 먹힌다)

---

## 부록 — 배포 확인 명령

```bash
# 백엔드가 실데이터를 보고 있는가
curl -s https://dacos-wheretogo.onrender.com/health
#   목표: {"status":"ok","db":true,"mode":"live","version":"0.1.0"}

# 프론트가 살아 있는가
curl -s -o /dev/null -w "%{http_code}\n" https://dacos-wheretogo-web.vercel.app

# 추천이 실제로 나오는가 (user_id 는 온보딩 응답의 값)
curl -s -X POST https://dacos-wheretogo.onrender.com/api/recommend \
  -H "Content-Type: application/json" \
  -d '{"user_id":"<온보딩으로 받은 id>","purpose":"데이트","party_size":2,
       "budget_band":2,"location":{"lat":37.5340,"lng":126.9946},
       "visit_at":"2026-08-29T19:00:00+09:00"}'
```

```powershell
# 전환해도 되는가 (B의 판정 도구)
cd roleB; $env:DATABASE_URL = "<DSN>"; python -m tools.check_data_readiness

# 시나리오 20개가 전부 도는가
cd roleB; $env:DATABASE_URL = "<DSN>"; python -m tools.scenario_report

# HTTP 포함 응답시간
cd roleB; python -m tools.perf_probe --url https://dacos-wheretogo.onrender.com --repeat 1
```

---

## 응답 계약 — 화면에서 놓치기 쉬운 것

| 필드 | 주의 |
|---|---|
| `score_breakdown.live_segment` / `.crowd` | **키 자체가 없을 수 있다.** 지점 반경 1km 밖 POI다. **0으로 그리면 안 된다** — 이미 잘 처리돼 있다 |
| `context.congest_forecast_at_visit` | `null`일 수 있다(예보 구간 밖). 없으면 줄을 지운다 |
| `context.weather_source` | `citydata_fcst`는 기상청 키 없이 쓰는 두 번째 예보다. 이 값일 때 `rain_prob`은 **확률**이다. `citydata`(실황)일 때만 0 또는 1 |
| `context.age_mix_top` | `"10대 미만 12%"` / `"70대 이상 9%"` 가 나올 수 있다 |
| `low_confidence` / `radius_expanded` | 지금 실 DB에서 대부분 `false`다. `true`면 후보가 빠듯했다는 뜻 |
| `503` | DB가 죽은 것이다. **목으로 되돌아가지 않는다.** 재시도를 안내한다 |
| `429` | IP당 분당 10회. 데모 중 연타로 걸릴 수 있다 |
| `422` | **계약 위반이다.** `lib/types.ts`가 아니라 `openapi.yaml`을 봐야 한다 → B에게 알린다 |
