# roleC — 프론트엔드 · 배포 · 평가

담당 문서: [docs/ROLE_C_WEB.md](../docs/ROLE_C_WEB.md)

웹 클라이언트와 배포 인프라 전체를 담당한다. Vercel 배포 루트가 이 폴더다.
**최종 산출물이 배포된 웹 서비스이므로 배포의 최종 책임자는 C다.**

| | |
|---|---|
| 웹 (Vercel) | https://dacos-wheretogo-web.vercel.app |
| API (Render) | https://dacos-wheretogo.onrender.com · [`/health`](https://dacos-wheretogo.onrender.com/health) |

## 구조

```
roleC/
├── app/
│   ├── layout.tsx
│   ├── page.tsx                 # 랜딩 → 온보딩
│   ├── onboarding/page.tsx
│   └── recommend/page.tsx       # 요청 폼 + 결과
├── components/
│   ├── OnboardingForm.tsx
│   ├── TagGrid.tsx
│   ├── RequestForm.tsx
│   ├── ResultCard.tsx
│   ├── KakaoMap.tsx
│   ├── ContextBanner.tsx        # 날씨 · 혼잡도
│   └── ScoreDebug.tsx           # ?debug=1 에서만 노출
├── lib/
│   ├── api.ts
│   ├── types.ts                 # openapi.yaml 기반
│   └── constants.ts             # 고정 어휘 (B와 동일)
├── .env.example
└── package.json
```

배포·CI 설정은 레포 루트에 둔다.

```
../.github/workflows/
├── ci.yml                # 시크릿 스캔 + lint + build
├── batch-citydata.yml    # 15분 폴링          (W2)
└── keepalive.yml         # Supabase 일일 핑   (W2)
../.gitleaks.toml
../.githooks/pre-commit
../render.yaml            # Render Blueprint (API 서버)
```

## 클론 후 1회

```bash
# 1) 시크릿 프리커밋 훅 — 레포가 public이다. 이게 첫 커밋보다 먼저다
git config core.hooksPath .githooks
#    gitleaks 설치: https://github.com/gitleaks/gitleaks/releases (v8.19+)
#    Windows: scoop install gitleaks   /   macOS: brew install gitleaks

# 2) 환경변수
cd roleC
cp .env.example .env.local     # .env.local 은 커밋되지 않는다
```

## 실행

```bash
cd roleC
npm ci               # npm install 이 아니라 ci — 락파일 그대로 재현한다
npm run dev          # http://localhost:3000

npm run lint         # CI와 같은 검사
npm run build
```

## 환경변수

| 키 | 어디에 | 비고 |
|---|---|---|
| `NEXT_PUBLIC_API_BASE` | 로컬 `.env.local` · Vercel 프로젝트 설정 | Vercel은 **Production / Preview / Development 스코프 각각** 넣어야 한다 |
| `NEXT_PUBLIC_KAKAO_JS_KEY` | 위와 같음 | JavaScript 키만. **REST 키는 절대 금지.** 도메인 제한 필수 |

`NEXT_PUBLIC_*` 는 브라우저 번들에 그대로 박힌다. 비밀값을 넣지 않는다.

## CORS

API는 화이트리스트 방식이다 (`render.yaml` 의 `CORS_ORIGINS`).
**새 프론트 도메인이 생기면 Render 환경변수에 추가하지 않는 한 브라우저가 전부 차단한다.**
preview 배포는 도메인이 매번 바뀌므로 화이트리스트로 커버되지 않는다 — 검증은 prod 도메인에서 한다.

## 다른 폴더와의 관계

| | |
|---|---|
| `../roleB/openapi.yaml` | 타입의 출처. 변경 요청은 PR |
| `../docs/scenarios.md` | 평가 시나리오 20개. **내가 작성하고 A에게 전달한다** |
| `../roleA/`, `../roleB/` | 건드리지 않는다 |

## 잊지 말 것

- `score_breakdown.live_segment`가 `undefined`일 때 **0으로 렌더링하지 않는다.** 항목을 숨기거나 "해당 없음"으로 표시한다
- 카카오 **REST API 키는 프론트 금지.** JavaScript 키만 쓰고 도메인 제한을 건다
- 레포가 public이다. `.env`를 커밋하지 않는다. **gitleaks 훅이 첫 커밋보다 먼저다**
- 온보딩은 5문항 이하. 태그는 고정 어휘만
- Render Free는 콜드스타트가 있다. 무한 스피너 대신 안내를 띄운다
- UptimeRobot과 Supabase keepalive를 **둘 다** 건다
- 모바일 우선. 이 서비스는 나가기 직전에 쓴다
- 리허설은 **실제 배포본으로** 한다
