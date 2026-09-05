// app/page.tsx
'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';

// PLAN.md §1.3 핵심 차별점 3줄을 그대로 반영한 시그니처 요소.
// "날씨/시간이 바뀌면 후보 집합 자체가 바뀐다"는 이 서비스의 핵심 주장을
// 문장으로 설명하지 않고, 실제로 상황이 바뀌는 걸 보여준다.
const CONTEXT_SCENARIOS = [
  {
    tag: '☔ 비 · 저녁 7시',
    weather: '비 68% · 체감 21°',
    picks: ['남영동 실내 오마카세', '한강로 아이파크몰 카페'],
    note: '"실내 위주로 골랐어요" — 야외 테라스는 후보에서 빠졌습니다',
  },
  {
    tag: '🔥 폭염 · 낮 2시',
    weather: '체감 35° · 미세먼지 나쁨',
    picks: ['용산역 실내 전시', '이촌 냉방 완비 브런치'],
    note: '더위·미세먼지 조건에서 쾌적한 실내 시설 위주로 추천합니다',
  },
  {
    tag: '☀️ 맑음 · 밤 8시',
    weather: '맑음 · 체감 19°',
    picks: ['이태원 루프탑 바', '한남 야외 정원 카페'],
    note: '해질녘 야외 뷰 스팟이 상단으로 올라옵니다',
  },
];

const DIFFERENTIATORS = [
  {
    icon: '📊',
    title: '평점이 아니라 소비 데이터',
    desc: '"당신 세그먼트가 이 시간대에 실제로 소비하는 곳"을 서울시 상권분석 데이터로 판단합니다.',
  },
  {
    icon: '🌦️',
    title: '날씨가 후보를 바꿉니다',
    desc: '비·미세먼지·폭염이 오면 추천하는 장소 집합이 달라집니다.',
  },
  {
    icon: '📝',
    title: '실제 후기가 보여줍니다',
    desc: '추천마다 실제 블로그 후기 문장을 그대로 인용합니다.',
  },
];

export default function Home() {
  const [scenarioIdx, setScenarioIdx] = useState(0);

  useEffect(() => {
    const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (prefersReducedMotion) return; // 모션 최소화 설정 존중 — 자동 순환 끔

    const interval = setInterval(() => {
      setScenarioIdx((i) => (i + 1) % CONTEXT_SCENARIOS.length);
    }, 3200);
    return () => clearInterval(interval);
  }, []);

  const scenario = CONTEXT_SCENARIOS[scenarioIdx];

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900">
      <main className="max-w-xl mx-auto px-5 pt-16 pb-24 sm:pt-24">
        {/* 헤더 */}
        <div className="flex items-center gap-2 mb-10">
          <span className="text-lg">🗺️</span>
          <span className="text-sm font-black tracking-tight text-slate-900">WhereToGo 용산</span>
        </div>

        {/* 히어로 */}
        <div className="space-y-4 mb-10">
          <h1 className="text-3xl sm:text-4xl font-black leading-tight tracking-tight text-slate-950">
            지금의 나와<br />지금의 상황에 맞는,<br />용산의 장소.
          </h1>
          <p className="text-sm text-slate-500 leading-relaxed max-w-sm">
            나이·성향과 목적·인원·날씨·시간을 함께 읽고, 실제 리뷰 근거와 함께 맞춤 장소를 추천합니다.
          </p>
        </div>

        {/* 시그니처: 라이브 컨텍스트 캡슐 — 상황이 바뀌면 추천이 바뀐다는 걸 직접 보여준다 */}
        <div
          key={scenarioIdx}
          className="bg-gradient-to-br from-slate-950 to-slate-800 text-white p-5 rounded-3xl shadow-md space-y-3 mb-3 transition-opacity duration-500"
        >
          <div className="flex justify-between items-center">
            <span className="text-[10px] font-black tracking-wider bg-white/10 px-2.5 py-1 rounded-full backdrop-blur-sm text-blue-300">
              {scenario.tag}
            </span>
            <span className="text-[10px] text-slate-400">{scenario.weather}</span>
          </div>
          <div className="space-y-1.5">
            {scenario.picks.map((p) => (
              <p key={p} className="text-sm font-bold">→ {p}</p>
            ))}
          </div>
          <p className="text-[11px] text-slate-300 border-t border-white/10 pt-2.5 leading-relaxed">
            {scenario.note}
          </p>
        </div>
        <div className="flex justify-center gap-1.5 mb-10">
          {CONTEXT_SCENARIOS.map((_, i) => (
            <span
              key={i}
              className={`h-1 rounded-full transition-all ${
                i === scenarioIdx ? 'w-5 bg-slate-900' : 'w-1.5 bg-slate-200'
              }`}
            />
          ))}
        </div>

        {/* CTA */}
        <Link
          href="/onboarding"
          className="block w-full text-center bg-blue-600 hover:bg-blue-700 text-white font-black py-4 rounded-2xl shadow-md text-sm transition-colors mb-14"
        >
          지금 나에게 맞는 곳 찾기 🚀
        </Link>

        {/* 차별점 3가지 — PLAN.md §1.3 */}
        <div className="space-y-3">
          {DIFFERENTIATORS.map((d) => (
            <div
              key={d.title}
              className="bg-white p-4 rounded-2xl border border-slate-100 shadow-sm flex gap-3"
            >
              <span className="text-xl leading-none">{d.icon}</span>
              <div>
                <p className="text-xs font-bold text-slate-900">{d.title}</p>
                <p className="text-[11px] text-slate-400 mt-1 leading-relaxed">{d.desc}</p>
              </div>
            </div>
          ))}
        </div>
      </main>
    </div>
  );
}
