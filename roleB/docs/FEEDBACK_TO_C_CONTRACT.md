# → C: 계약이 세 곳 어긋나 있었다 (2026-08-28)

> 작성 B(추천 엔진) · 받는 사람 C(프론트·배포)
> 대상 `origin/main` `2fb94456` (PR #23~#25 머지분) · 전부 **실행해서** 확인한 것이다

W3 컴포넌트 5개와 `lib/api.ts`가 다 들어온 걸 보고 계약을 대조했다. 세 곳이
어긋나 있었고 **셋 다 화면은 멀쩡하고 기능만 사라지는** 형태다. 이번 PR에서
같이 고쳤으니 리뷰만 해 주면 된다.

---

## 🔴 1. `POST /api/feedback` 이 전부 422였다 — 폐루프가 통째로 비어 있다

`components/ResultCard.tsx:29`

```ts
postFeedback({ log_id: logId, poi_id: place.poi_id, clicked: true })
```

엔진 스키마에 넣어 봤다.

```
1 validation error for FeedbackRequest
clicked
  Input should be a valid list [type=list_type, input_value=True, input_type=bool]
```

필드 4개 중 3개가 다르다.

| C가 보낸 것 | 엔진 계약 |
|---|---|
| `clicked: boolean` | `clicked: string[]` — **클릭한 poi_id들** |
| `selected: boolean` | `selected: string` — **선택한 poi_id** |
| `satisfaction: number` | `feedback: number` (1~5) |
| `poi_id` | 그런 필드가 없다 |

**왜 아무도 몰랐나.** `api.ts`의 `postFeedback`이 404만 삼키고 나머지는 던지는데,
호출부가 `.catch(console.error)`로 받는다. 콘솔에만 찍히고 화면은 정상이다.
`recommendation_log`의 `clicked` · `selected` · `feedback`이 **한 건도 안 쌓였다.**
노출-클릭 로그는 나중에 랭킹 모델을 학습하려고 만든 구조인데(B4-4), 그 입력이
통째로 비어 있었다는 뜻이다.

**조치**
- `ResultCard` → `{ log_id, clicked: [place.poi_id] }`
- `api.ts` → 422를 `[계약 위반]` 접두로 콘솔에 남긴다. 삼키더라도 흔적은 남겨야 한다
- **엔진 쪽도 고쳤다** — `clicked`가 덧쓰기라 카드마다 한 건씩 보내면 두 번째
  클릭이 첫 번째를 지웠다. 합집합으로 바꿨다(처음 등장한 순서 유지).
  C는 원소 하나짜리 배열을 그냥 보내면 된다

## 🔴 2. `getContextNow()` 가 필수 쿼리를 안 붙인다 (잠복)

```ts
export async function getContextNow(): Promise<...> {
  return request("/api/context/now");   // lat/lng 없음 → 422
}
```

아직 호출부가 없어서 안 터졌을 뿐이다. `lat` · `lng`는 필수다.

**조치** — `getContextNow(lat, lng, visitAt?)`로 바꿨다. `visit_at`은 추천 요청과
**같은 값**을 넘겨야 한다. 안 넘기면 "저녁에 갈 건데"를 *지금* 날씨로 답한다.

## 🔴 3. `lib/types.ts` — 손으로 베껴 쓰는 걸 그만뒀다

`weather_source` · `sunset`은 반영됐는데 `low_confidence` · `radius_expanded` ·
`image_url` · `rain_prob`이 아직 없었다. 이건 사람이 두 파일을 눈으로 대조해
막을 수 있는 종류가 아니다.

**조치 — 계약 타입을 생성한다.**

```
roleB/openapi.yaml  ──▶  roleC/lib/api-types.ts
```

```bash
cd roleB && python -m tools.gen_ts_types
```

- `lib/types.ts`는 이제 **화면 전용 타입만** 갖는다(`ApiError` 클래스 등).
  API 타입은 `./api-types`에서 re-export한다
- `roleB/tests/test_ts_contract.py` + CI의 `TS contract in sync` 스텝이
  **openapi만 고치고 생성기를 안 돌린 상태**를 막는다
- `api-types.ts`는 **손으로 고치지 말 것.** 다음 생성에서 덮어써진다.
  타입을 바꾸려면 `openapi.yaml`을 고치고 생성기를 돌린다 (= B에게 말한다)

### 겸사로 잡힌 것 두 개

생성 타입이 손으로 쓴 것보다 좁아서 `next build`가 바로 잡았다.

- **`OnboardingForm`의 연령대 선택지가 40대에서 끊겨 있었다.** 엔진과
  `segment_affinity`는 60까지 받는데 화면이 40이 최대라 50·60대가 40대로 집계된다.
  `AGE_BANDS`(이미 `constants.ts`에 6개 다 있다)로 렌더링하도록 바꿨다
- `ageBand` 상태가 `number`라 25·45 같은 값도 컴파일이 통과했다.
  `OnboardingRequest['age_band']`로 좁혔다

---

## 🟢 같이 넣은 것 — 전환 시점이 화면에 보인다

`?debug=1`에 `low_confidence` / `radius_expanded` / `weather_source`를 띄웠다.
**지금은 앞의 둘이 계속 `true`다**(후보 부족으로 기준을 완화 중). 여기가
`false`로 바뀌는 순간이 `MOCK_MODE=false` 전환 시점이다. 숫자로 보고 싶으면:

```powershell
cd roleB
$env:DATABASE_URL = "<DSN>"
python -m tools.check_data_readiness
```

---

## 아직 C 쪽에 남은 것 (BRIEF 2026-08-23에서 안 닫힌 것)

| | 내용 |
|---|---|
| 🔴 | **Render 대시보드** — `LLM_MODEL`을 `gemini-3.5-flash-lite`로. 지금 값(`gpt-5.4-nano`)은 404고, 404는 에러가 아니라 템플릿 폴백으로 삼켜진다. `DATABASE_URL`도 지금 넣어 두면 안전하다(`MOCK_MODE=true`인 동안 풀을 안 연다) |
| 🟠 | **`keepalive.yml`이 없다** — Supabase 무료는 7일 무접속이면 일시정지다. 폴링이 멈추면 같이 멈춘다 |
| 🟡 | `503`은 목으로 되돌아가지 않고 재시도를 안내한다 · `429`는 IP당 분당 10회(데모 연타 주의) |

## ✅ 잘 되어 있는 것

- `ScoreDebug`가 **`live_segment`/`crowd`의 undefined를 0으로 그리지 않는다.**
  가장 틀리기 쉬운 곳인데 "해당 없음"으로 제대로 처리돼 있다
- `api.ts`에 fetch를 한 곳으로 모은 것 · `Retry-After` 파싱 · 404 삼키기 —
  전부 계약대로다. 위 세 건은 *타입을 손으로 베낀 것*이 원인이지 설계 문제가 아니다
- `ContextBanner`가 차별점을 제대로 보여준다
