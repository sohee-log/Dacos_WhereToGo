// components/ContextBanner.tsx
import { RecommendResponse } from '@/lib/types';

interface ContextBannerProps {
  context: RecommendResponse['context'];
}

export default function ContextBanner({ context }: ContextBannerProps) {
  const getPm25Text = (grade: number) => {
    switch(grade) {
      case 1: return '좋음 🍃';
      case 2: return '보통 ☁️';
      case 3: return '나쁨 😷';
      case 4: return '매우나쁨 🚨';
      default: return '정보없음';
    }
  };

  //  비 소식 여부 체크 로직
  const isRainy = context.weather.includes('비') || context.weather.includes('소나기');

  return (
    <div className="bg-gradient-to-br from-slate-950 to-slate-800 text-white p-5 rounded-3xl shadow-md space-y-3">
      <div className="flex justify-between items-center">
        <p className="text-[10px] font-black tracking-wider bg-white/10 px-2.5 py-1 rounded-full backdrop-blur-sm text-blue-300">
          LIVE 용산 컨텍스트 {context.hotspot ? context.hotspot : '전역'}
        </p>
      </div>

      <div className="flex items-baseline gap-3">
        <span className="text-2xl font-black">{context.weather}</span>
        <span className="text-xs opacity-90">체감 {context.feels_like}°C</span>
      </div>

      <div className="flex flex-wrap gap-x-4 gap-y-1 text-[11px] opacity-75 border-t border-white/10 pt-2">
        <p>미세먼지: {getPm25Text(context.pm25_grade)}</p>
        {context.congest_now && <p>혼잡도: <span className="font-semibold text-blue-300">{context.congest_now}</span></p>}
        {context.congest_forecast_at_visit && <p>방문시 혼잡도: {context.congest_forecast_at_visit}</p>}
        {context.age_mix_top && <p>실시간 연령대: {context.age_mix_top}</p>}
      </div>

      {/* 날씨를 반영하여 결과가 바뀐 뉘앙스 노출 */}
      <div className="border-t border-white/10 pt-2.5 text-[11px] text-slate-300 leading-relaxed">
        {isRainy ? (
          <p className="flex items-start gap-1">
            <span>☔</span>
            <span>
              <strong>"날씨를 보고 실내 위주로 골랐어요!"</strong> 현재 용산구에 비 소식이 확인되어 동선 이동이 최소화되는 <strong>쾌적한 실내 공간 및 대피소형 핫플</strong>을 최상단에 배치했습니다.
            </span>
          </p>
        ) : (
          <p className="flex items-start gap-1">
            <span>☀️</span>
            <span>
              오늘 외부 활동에 적합한 컨텍스트가 확인되어, 취향 벡터에 기반한 <strong>야외 가시성 및 테라스 스팟</strong>을 필터에 결합하여 추천해 드립니다.
            </span>
          </p>
        )}
      </div>
    </div>
  );
}