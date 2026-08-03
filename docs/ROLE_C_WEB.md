# ROLE C — 프론트엔드 · 배포 · 평가 작업 지시서

> **이 문서를 받은 LLM에게**
> 당신은 이 프로젝트의 **C 역할(프론트엔드 · 배포 · 평가)** 담당자로 작업한다.
> 이 문서만으로 작업이 가능하도록 필요한 계약·API 스펙·배포 절차가 모두 포함되어 있다.
> 아래 **§1 불변 규칙**을 위반하는 코드는 어떤 이유로도 작성하지 않는다.
> 특히 **비용 0원 제약**과 **public 레포 시크릿 규칙**은 위반 시 되돌릴 수 없는 피해가 발생한다.
> 전체 설계 배경은 같은 디렉터리의 `PLAN.md`에 있다. 판단이 갈리면 `PLAN.md`가 상위 문서다.

---

## 0. 프로젝트 한 줄

> **"지금의 나(나이·성향)와 지금의 상황(목적·인원·날씨·시간)에 맞는 용산의 장소를, 실제 리뷰 근거와 함께 3~5곳 추천한다."**

| 항목 | 값 |
|---|---|
| 대상 | 서울 용산구 전역 |
| 기간 | 6주 (W1~W6) |
| 예산 | **0원** — 결제수단 등록이 필요한 서비스는 전부 금지 |
| 팀 | A(데이터) · B(추천엔진) · C(프론트·배포) |
| 최종 산출물 | **배포된 웹 서비스** ← **C가 최종 책임자다** |

---

## 1. 불변 규칙 (위반 금지)

### 1.1 비용 0원

- **결제수단 등록을 요구하는 화면이 나오면 그 서비스는 즉시 후보에서 제외**한다.
- 커스텀 도메인 **구매 금지**. `*.vercel.app` 서브도메인을 쓴다.
- 무료 티어 조건은 자주 바뀐다. **W1에 가입하면서 §4 표를 실제 화면과 대조**하고 달라진 항목은 `PLAN.md`를 갱신한다.

### 1.2 public 레포 시크릿 규칙

레포는 **public**으로 만든다 (GitHub Actions 분 수 무제한 + 포트폴리오 이점). 따라서:

| 키 | 취급 |
|---|---|
| 카카오 **JavaScript 키** | 프론트 노출 불가피 → **반드시 도메인 제한** 설정 |
| 카카오 **REST API 키** | ❌ 프론트 금지. Render 환경변수만 |
| 네이버 / 기상청 / 열린데이터광장 / LLM 키 | ❌ 프론트 금지. 전부 백엔드 경유 |

- `.env`는 `.gitignore`에, `.env.example`만 커밋한다.
- **W1에 `gitleaks` 프리커밋 훅을 건다.** 이게 첫 커밋보다 먼저다.

### 1.3 배포 규칙

- **W1 안에 prod URL이 살아 있어야 한다.** 빈 앱이라도 상관없다.
- 6주 프로젝트에서 배포를 뒤로 미루면 반드시 실패한다. **배포는 마지막에 하는 일이 아니라 처음에 뚫어놓는 길이다.**

### 1.4 UI 규칙

- 온보딩은 **5문항 이하**. 넘으면 이탈한다.
- 태그는 **§3.3 고정 어휘만** 사용한다. 자유 입력을 만들면 B의 매칭이 전부 깨진다.

---

## 2. 소유 범위

| 구분 | 대상 |
|---|---|
| ✅ **내 소유** | `web/` 전체, `.github/workflows/`, 배포 인프라 전체, 평가 시나리오 |
| 🤝 **공동 (3인 합의)** | `db/migrations/*.sql` (읽기만), `openapi.yaml` (B가 관리, 변경 요청은 PR) |
| ❌ **건드리지 않음** | `api/` (B 소유) · `batch/` (A 소유) |

---

## 3. 계약

### 3.1 레포 구조 (C가 W1에 만든다)

```
yongsan-place-agent/
├── api/                    # B 소유
├── batch/                  # A 소유
├── web/                    ← C 소유
│   ├── app/
│   │   ├── layout.tsx
│   │   ├── page.tsx              # 랜딩 → 온보딩 진입
│   │   ├── onboarding/page.tsx
│   │   ├── recommend/page.tsx    # 요청 폼 + 결과
│   │   └── api/                  # (필요 시 프록시만)
│   ├── components/
│   │   ├── OnboardingForm.tsx
│   │   ├── TagGrid.tsx
│   │   ├── RequestForm.tsx
│   │   ├── ResultCard.tsx
│   │   ├── KakaoMap.tsx
│   │   ├── ContextBanner.tsx     # 날씨·혼잡도 표시
│   │   └── ScoreDebug.tsx        # score_breakdown 시각화
│   ├── lib/
│   │   ├── api.ts                # 백엔드 클라이언트
│   │   ├── types.ts              # openapi.yaml 기반 타입
│   │   └── constants.ts          # 고정 어휘 (B와 동일)
│   ├── .env.example
│   └── package.json
├── db/migrations/          # 공동
├── seeds/                  # A 제공
├── docs/
├── openapi.yaml            # B 관리
├── .github/workflows/      ← C 소유
│   ├── ci.yml
│   ├── batch-citydata.yml
│   └── keepalive.yml
├── .gitleaks.toml          ← C 소유
├── PLAN.md
├── ROLE_A_DATA.md
├── ROLE_B_ENGINE.md
└── ROLE_C_WEB.md
```

### 3.2 API 계약 (B 제공 — 이 형태로 개발한다)

| Method | Endpoint | 용도 |
|---|---|---|
| `POST` | `/api/onboarding` | 온보딩 제출 → `user_id` 발급 |
| `GET` | `/api/context/now` | 날씨·대기질·혼잡도 배너용 |
| `POST` | `/api/recommend` | **메인** |
| `POST` | `/api/feedback` | 클릭·선택·만족도 |
| `GET` | `/api/poi/{id}` | 상세 |
| `GET` | `/health` | UptimeRobot 핑 |

**`POST /api/recommend`**

```typescript
// Request
type RecommendRequest = {
  user_id: string;
  purpose: Purpose;                    // 고정 어휘
  party_size: number;
  budget_band: 1 | 2 | 3 | 4;
  location: { lat: number; lng: number };
  visit_at: string;                    // ISO8601 +09:00
};

// Response
type RecommendResponse = {
  context: {
    weather: string;                   // "비 60%"
    pm25_grade: number;                // 1~4
    feels_like: number;
    hotspot: string | null;            // "이태원 관광특구"
    congest_now: string | null;
    congest_forecast_at_visit: string | null;
    age_mix_top: string | null;        // "20대 31%"
  };
  results: Array<{
    poi_id: string;
    name: string;
    category: string;
    lat: number; lng: number;
    distance_m: number;
    score: number;
    score_breakdown: {                 // live_segment / crowd 는 없을 수 있음
      segment: number; purpose: number; taste: number;
      context: number; quality: number; distance: number;
      live_segment?: number; crowd?: number;
    };
    reason: string;
    evidence: Array<{ text: string; source: string }>;
    is_exploration: boolean;
    explain_mode: "llm" | "cache" | "template";
  }>;
  log_id: number;
};
```

> ⚠️ **`score_breakdown.live_segment` / `crowd`는 없을 수 있다.** 핫스팟 반경 밖 POI다. UI에서 `undefined`를 `0`으로 렌더링하지 말고 **"해당 없음"으로 표시하거나 항목을 숨긴다.**

### 3.3 고정 어휘 (A·B와 공유 — 임의 확장 금지)

```typescript
export const PURPOSES = ["데이트", "친구모임", "혼자", "가족", "작업", "회식"] as const;
export const ATMOSPHERES = [
  "조용한", "활기찬", "감성적인", "트렌디한", "로컬한",
  "넓은", "뷰가좋은", "아늑한", "이국적인", "가성비"
] as const;
export const AGE_BANDS = [10, 20, 30, 40, 50, 60] as const;
export const BUDGET_LABELS = ["1만원 이하", "1~3만원", "3~5만원", "5만원 이상"];
```

---

## 4. 무료 티어 구성 (W1에 실검증)

| 용도 | 서비스 | 무료 한도 | 제약 |
|---|---|---|---|
| 프론트 | **Vercel Hobby** | 무제한 배포, 100GB 대역폭 | **비상업적 용도만** (학생·경진대회는 해당) |
| API | **Render Free** | 750 인스턴스시간/월 | **15분 무접속 시 슬립** → 콜드스타트 ~1분 |
| DB | **Supabase Free** | 500MB, PostGIS·pgvector 지원 | **7일 무접속 시 일시정지** |
| 배치 | **GitHub Actions** | public repo 분 수 무제한 | — |
| 슬립방지 | **UptimeRobot** | 5분 간격, 50 모니터 | — |
| 에러추적 | Sentry Developer | 5,000 이벤트/월 | 선택 |
| 도메인 | `*.vercel.app` | 무료 | 커스텀 도메인은 **사지 않는다** |

**탈락한 대안 (다시 검토하지 말 것)**

- ~~Railway~~ — **무료 티어가 없다** (트라이얼 크레딧 소진 후 유료)
- ~~Fly.io~~ — 결제수단 필수
- ~~Vercel Python Functions로 API~~ — 콜드스타트 + DB 커넥션 풀 유지 불가

**백업안:** Render 가입 화면이 결제수단을 요구하면 즉시 **Hugging Face Spaces (Docker SDK)** 로 전환한다. 무료 CPU 2vCPU/16GB, 슬립 기준이 48시간이라 오히려 유리할 수 있다.

**슬립 대응 2중 장치 (둘 다 필수)**

1. UptimeRobot이 5분마다 `/health` 호출 → Render 상시 가동 (월 ~720시간, 750시간 한도 내)
2. GitHub Actions가 매일 1회 Supabase에 `SELECT 1` → 7일 일시정지 방지

---

## 5. 주차별 작업

---

### W1 — 레포 · 배포 개통 (**이번 주가 프로젝트에서 가장 중요하다**)

🚩 **게이트: prod URL에 빈 앱이라도 떠 있다**

| # | 작업 | 산출물 | 완료 기준 |
|---|---|---|---|
| C1-1 | **public 레포 생성 + 모노레포 구조** | 레포 | §3.1 구조 |
| C1-2 | **`gitleaks` 프리커밋 훅** | `.gitleaks.toml` | 첫 커밋보다 먼저 |
| C1-3 | 무료 티어 계정 개설 + **§4 표 실검증** | 문서 갱신 | 결제수단 요구 시 즉시 교체 |
| C1-4 | Next.js 스캐폴딩 | `web/` | `npm run dev` 동작 |
| C1-5 | **Vercel + Render + Supabase 개통, 빈 앱 prod 배포** | prod URL | **외부에서 접속 가능** |
| C1-6 | CI 워크플로 (lint + build) | `.github/workflows/ci.yml` | PR에서 동작 |

**C1-5가 이번 주 유일한 필수 산출물이다.** 나머지가 밀려도 이것만은 끝낸다. 여기서 막히는 문제(환경변수, CORS, 빌드 설정, 리전)는 **W5에 발견하면 치명적이지만 W1에 발견하면 사소하다.**

**배포 순서**

```
1. Supabase 프로젝트 생성 → DATABASE_URL 확보 → B에게 전달
2. Render 웹서비스 생성 → api/ 디렉터리 지정 → DATABASE_URL 환경변수 주입
3. Vercel 프로젝트 생성 → web/ 디렉터리 지정 → NEXT_PUBLIC_API_BASE 주입
4. Render /health 에 curl → 200 확인
5. Vercel 배포본에서 API 호출 → CORS 확인
```

**`.env.example` (커밋)**

```bash
# web/
NEXT_PUBLIC_API_BASE=https://yongsan-api.onrender.com
NEXT_PUBLIC_KAKAO_JS_KEY=            # 도메인 제한 필수

# api/ (Render 환경변수 — 절대 커밋 금지)
DATABASE_URL=
KAKAO_REST_KEY=
NAVER_CLIENT_ID=
NAVER_CLIENT_SECRET=
SEOUL_OPENDATA_KEY=
KMA_SERVICE_KEY=
LLM_API_KEY=
LLM_DAILY_LIMIT=
```

---

### W2 — 온보딩 UI · 슬립 방지

| # | 작업 | 산출물 | 완료 기준 |
|---|---|---|---|
| C2-1 | `OnboardingForm` — **5문항** | 컴포넌트 | 부록 A 문항 |
| C2-2 | `TagGrid` — 다중선택 태그 그리드 | 컴포넌트 | 고정 어휘만 |
| C2-3 | `lib/api.ts` + `lib/types.ts` | 코드 | openapi.yaml 기반 |
| C2-4 | 상태관리 (user_id 로컬 저장) | 코드 | 새로고침 유지 |
| C2-5 | **UptimeRobot 등록** | 모니터 | `/health` 5분 간격 |
| C2-6 | `keepalive.yml` (Supabase 일일 핑) | 워크플로 | cron 동작 확인 |

**온보딩 5문항 (부록 A — 이 이상 늘리지 않는다)**

1. 성별 / 연령대 — 선택형
2. 선호 분위기 — `ATMOSPHERES` 태그 그리드 다중선택
3. 주로 가는 목적 — `PURPOSES` 다중선택
4. 평소 예산대 — 1~4 밴드
5. **날씨 민감도** — "비 오면 약속을 미루는 편인가?" 3단계
   → B가 `context_fit` 개인 가중치로 사용한다. **빠뜨리면 개인화 항 하나가 죽는다.**

2·3번 태그가 `user_profile.taste_vector`의 재료가 된다. **자유 입력을 만들면 안 된다.**

---

### W3 — 추천 요청 · 결과 UI · 지도

| # | 작업 | 산출물 | 완료 기준 |
|---|---|---|---|
| C3-1 | `RequestForm` — 목적/인원/예산/시각/위치 | 컴포넌트 | `visit_at` 기본값 = 현재+1h |
| C3-2 | `ResultCard` — 이름·거리·이유·인용 | 컴포넌트 | `evidence` 인용 표시 |
| C3-3 | `KakaoMap` — 결과 마커 | 컴포넌트 | JS SDK, 도메인 제한 |
| C3-4 | `ContextBanner` — 날씨·혼잡도 | 컴포넌트 | `context` 필드 표시 |
| C3-5 | 로딩·에러·빈결과 상태 | 컴포넌트 | 3상태 전부 |

**C3-4가 이 서비스의 차별점을 보여주는 자리다.**

```
🌧 비 60% · 체감 27.4° · 미세먼지 보통
📍 이태원 관광특구 · 지금 약간 붐빔 → 19시 붐빔 예상 · 20대 31%
```

*"날씨를 봤다"* 가 아니라 *"날씨를 보고 후보를 바꿨다"* 가 드러나야 한다. 비가 오면 배너에 **"실내 위주로 골랐어요"** 문구를 함께 띄운다.

**C3-3 카카오맵 주의**

- JS 키는 **도메인 제한 필수** (`localhost:3000` + `*.vercel.app`)
- `developers.kakao.com` → 앱 설정 → 플랫폼 → Web 등록 → **카카오맵 활성화 ON**
- 개발용·운영용 앱을 **따로 만든다** (쿼터 분리)

**C3-5 빈 결과 처리**

B가 반경을 넓혀 재시도하므로 빈 결과는 드물지만, 나올 경우 **"조건을 완화해보세요"와 함께 완화 버튼**(예산 +1, 반경 확대)을 제공한다. 빈 화면만 띄우지 않는다.

---

### W4 — 실 API 연동 · 로깅

🚩 **게이트: 온보딩 → 추천 → 피드백 전 흐름이 prod에서 동작**

| # | 작업 | 산출물 | 완료 기준 |
|---|---|---|---|
| C4-1 | 목 API → **실 API 전환** | 코드 | B의 W4 산출물 연동 |
| C4-2 | 클릭·선택 로깅 → `/api/feedback` | 코드 | `log_id` 연결 |
| C4-3 | 사후 만족도 UI (1~5) | 컴포넌트 | 선택 후 노출 |
| C4-4 | `ScoreDebug` — `score_breakdown` 시각화 | 컴포넌트 | **URL 쿼리 `?debug=1`로만 노출** |
| C4-5 | 콜드스타트 대응 UX | 코드 | 첫 요청 로딩 안내 |

**C4-4 — 발표에서 가장 잘 먹히는 화면이다.** 막대그래프로 7개 항 기여도를 보여주면 *"왜 이곳인가"* 가 즉시 설명된다. 다만 일반 사용자에겐 노이즈이므로 `?debug=1`에서만 켠다.

**C4-5 — Render Free 콜드스타트**
UptimeRobot이 있어도 첫 요청이 느릴 수 있다. 3초 넘으면 "서버를 깨우는 중이에요" 안내를 띄운다. 무한 스피너는 고장으로 보인다.

---

### W5 — 통합 · 반응형 · 평가 준비

| # | 작업 | 산출물 | 완료 기준 |
|---|---|---|---|
| C5-1 | 전 기능 prod 반영 | 배포 | W5 금요일까지 |
| C5-2 | 반응형 (모바일 우선) | CSS | 실제 폰에서 확인 |
| C5-3 | 에러 바운더리 · 재시도 | 코드 | API 실패 시 복구 가능 |
| C5-4 | **평가 시나리오 20개 작성** | `docs/scenarios.md` | §6 형식 |
| C5-5 | Sentry 연동 (선택) | 설정 | — |

**C5-2 — 이 서비스는 모바일에서 쓴다.** "나갈 곳을 고르는" 상황은 대부분 밖이거나 나가기 직전이다. 데스크톱 우선으로 만들면 발표 시연에서 어색해진다.

**C5-4 시나리오 20개 — 아래 축을 고르게 덮는다**

| 축 | 커버해야 할 값 |
|---|---|
| 목적 | 6종 전부 |
| 날씨 | 맑음 / 비 / 미세먼지나쁨 / 폭염 |
| 인원 | 1~2 / 3~4 / 5+ |
| zone | 5개 전부 (특히 핫스팟 **밖** 지역 포함) |
| 연령 | 20대 / 30대 / 40대+ |

> **핫스팟 밖 시나리오를 반드시 넣는다.** `live_*` 항이 없는 경로가 정상 동작하는지는 여기서만 검증된다.

시나리오 목록은 **A에게 전달**한다. A가 각 시나리오의 후보 수를 미리 쿼리해서 **빈 결과가 나오지 않는지 확인**한다 (ROLE_A W6).

---

### W6 — 사용자 테스트 · 발표

| # | 작업 | 산출물 | 완료 기준 |
|---|---|---|---|
| C6-1 | 사용자 테스트 (지인 10명+) | 로그 200건 | 실사용 피드백 |
| C6-2 | 버그 수정 | — | 치명 버그 0 |
| C6-3 | **발표 전날 캐시 워밍 실행** | 스크립트 | 시나리오 20개 호출 |
| C6-4 | 발표 리허설 2회 | — | **실제 배포본으로** |
| C6-5 | README + 데모 GIF | 문서 | 포트폴리오용 |

**C6-3 — 무료 티어 데모의 최대 안전장치다.** 전날 밤 시나리오 20개를 호출해 `explanation_cache`를 채워두면 발표 중 LLM 호출이 0회가 되어 쿼터·네트워크 사고가 원천 차단된다. B의 워밍 스크립트를 실행하는 것은 C의 책임이다.

**C6-4 — 반드시 실제 배포본으로 한다.** 로컬에서만 리허설하면 CORS·콜드스타트·환경변수 문제를 발표 당일에 처음 만난다.

---

## 6. 평가 시나리오 형식 (`docs/scenarios.md`)

```markdown
### S01 — 비 오는 금요일 저녁 데이트
- user: 여성 / 20대 후반 / 취향: 조용한, 감성적인 / 날씨민감도: 높음
- request: purpose=데이트, party_size=2, budget_band=3,
           location=이태원1동, visit_at=금 19:00
- weather: 비 70%, 체감 26°
- **기대 동작**: outdoor_exposure 높은 POI 제외 / 실내 카페·레스토랑 상위 /
                 reason에 "비" 언급 / congest 예측 표시
- **실패 조건**: 야외 테라스가 1위 / 빈 결과 / live_* 없는 POI가 전멸
```

---

## 7. 자주 하는 실수 (체크리스트)

- [ ] `score_breakdown.live_segment`가 `undefined`일 때 **0으로 렌더링**하지 않았는가
- [ ] 카카오 **REST API 키**를 프론트에 넣지 않았는가
- [ ] 카카오 JS 키에 **도메인 제한**을 걸었는가
- [ ] `.env`를 커밋하지 않았는가 (**public 레포다**)
- [ ] `gitleaks` 훅이 실제로 동작하는가 (더미 키로 테스트)
- [ ] 온보딩 문항이 5개를 넘지 않았는가
- [ ] 태그를 **고정 어휘 밖**으로 만들지 않았는가
- [ ] UptimeRobot과 Supabase keepalive를 **둘 다** 걸었는가
- [ ] 커스텀 도메인을 구매하지 않았는가
- [ ] 콜드스타트 시 무한 스피너를 보여주지 않는가
- [ ] 모바일에서 확인했는가
- [ ] 리허설을 **실제 배포본**으로 했는가

---

## 8. 로컬 실행

```powershell
cd web
npm install
npm run dev            # http://localhost:3000

# 목 API 사용 시
$env:NEXT_PUBLIC_API_BASE = "https://yongsan-api.onrender.com"
```

---

## 9. 막혔을 때 판단 기준

| 상황 | 판단 |
|---|---|
| B의 API가 늦다 | **목 API로 계속 간다.** UI는 API를 기다리지 않는다 |
| Render가 결제수단을 요구한다 | 즉시 **HF Spaces**로 전환. 고민하지 않는다 |
| 무료 한도가 문서와 다르다 | 문서를 갱신하고 팀에 공유. **한도에 맞춰 설계를 바꾼다** |
| 디자인에 시간이 든다 | **기능 완결 > 디자인.** 6주에서 디자인은 W5 이후에 손댄다 |
| 일정이 밀린다 | Sentry → 반응형 미세조정 → 데모 GIF 순으로 버린다. **prod 가동과 리허설은 절대 못 버린다** |
