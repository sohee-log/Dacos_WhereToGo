This is a [Next.js](https://nextjs.org) project bootstrapped with [`create-next-app`](https://nextjs.org/docs/app/api-reference/cli/create-next-app).

## Getting Started

First, run the development server:

```bash
npm run dev
# or
yarn dev
# or
pnpm dev
# or
bun dev
```

Open [http://localhost:3000](http://localhost:3000) with your browser to see the result.

You can start editing the page by modifying `app/page.tsx`. The page auto-updates as you edit the file.

This project uses [`next/font`](https://nextjs.org/docs/app/building-your-application/optimizing/fonts) to automatically optimize and load [Geist](https://vercel.com/font), a new font family for Vercel.

## Learn More

To learn more about Next.js, take a look at the following resources:

- [Next.js Documentation](https://nextjs.org/docs) - learn about Next.js features and API.
- [Learn Next.js](https://nextjs.org/learn) - an interactive Next.js tutorial.

You can check out [the Next.js GitHub repository](https://github.com/vercel/next.js) - your feedback and contributions are welcome!

## Deploy on Vercel

The easiest way to deploy your Next.js app is to use the [Vercel Platform](https://vercel.com/new?utm_medium=default-template&filter=next.js&utm_source=create-next-app&utm_campaign=create-next-app-readme) from the creators of Next.js.

Check out our [Next.js deployment documentation](https://nextjs.org/docs/app/building-your-application/deploying) for more details.
# roleC — 프론트엔드 · 배포 · 평가

담당 문서: [docs/ROLE_C_WEB.md](../docs/ROLE_C_WEB.md)

웹 클라이언트와 배포 인프라 전체를 담당한다. Vercel 배포 루트가 이 폴더다.
**최종 산출물이 배포된 웹 서비스이므로 배포의 최종 책임자는 C다.**

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
├── ci.yml                # lint + build
├── batch-citydata.yml    # 15분 폴링
└── keepalive.yml         # Supabase 일일 핑
../.gitleaks.toml
```

## 실행

```bash
cd roleC
npm install
npm run dev          # http://localhost:3000
```

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
