// components/ResultCard.tsx
'use client';

import { useState } from 'react';
import { RecommendResponse } from '@/lib/types';
import { postFeedback } from '@/lib/api';

type Place = RecommendResponse['results'][number];

interface ResultCardProps {
  place: Place;
  logId: number; 
}

const EXPLAIN_MODE_LABEL: Record<Place['explain_mode'], string> = {
  template: '템플릿',
  llm: 'AI 생성',
  cache: '캐시',
};

export default function ResultCard({ place, logId }: ResultCardProps) {
  const { score_breakdown } = place;
  
  // 상태 관리
  const [clicked, setClicked] = useState(false);
  const [rated, setRated] = useState<number | null>(null); // 별점 상태 추가

  // 1. 카드 클릭 로깅 (계약 위반 수정 완료)
  const handleClick = () => {
    if (clicked) return;
    setClicked(true);
    
    // 수정됨: clicked를 boolean이 아닌 string[] 배열로 전송[cite: 1]
    postFeedback({ 
      log_id: logId, 
      clicked: [place.poi_id] 
    }).catch((err) => {
      console.error('클릭 로깅 실패', err);
    });
  };

  // 2. 별점(만족도) 전송 핸들러[cite: 1]
  const handleRate = (score: number) => {
    setRated(score);
    
    postFeedback({
      log_id: logId,
      selected: place.poi_id, // 선택한 poi_id (문자열)[cite: 1]
      feedback: score,        // 1~5점 (satisfaction 아님)[cite: 1]
    }).catch((err) => console.error('만족도 전송 실패', err)); // 실패해도 화면 멈춤 방지[cite: 1]
  };

  const hasEvidence = place.evidence && place.evidence.length > 0;

  return (
    <div
      onClick={handleClick}
      className="bg-white rounded-3xl border border-slate-100 p-4 shadow-sm space-y-4 cursor-pointer"
    >
      <div className="flex justify-between items-start">
        <div>
          <h4 className="text-sm font-black text-slate-900">{place.name}</h4>
          <p className="text-[11px] text-slate-400 mt-0.5">{place.category} · 도보 {place.distance_m}m</p>
        </div>
        <div className="text-right space-y-1">
          <span className="text-xs font-black text-indigo-600 block">{place.score}점</span>
          <span className="text-[9px] text-slate-300">{EXPLAIN_MODE_LABEL[place.explain_mode]}</span>
        </div>
      </div>

      <p className="text-xs text-slate-600 bg-slate-50 p-3 rounded-xl leading-relaxed">
        {place.reason}
      </p>

      <div className="text-[10px] text-slate-400 grid grid-cols-2 gap-1 bg-slate-50/50 p-2.5 rounded-xl border border-slate-100/60">
        <div>🎯 목적 적합도: {score_breakdown.purpose}점</div>
        <div>😋 취향 일치도: {score_breakdown.taste}점</div>
        <div>🗺️ 거리 점수: {score_breakdown.distance}점</div>

        {score_breakdown.live_segment !== undefined ? (
          <div>⚡ 실시간 매칭: {score_breakdown.live_segment}점</div>
        ) : (
          <div className="text-slate-300">⚡ 실시간 매칭: 해당 없음</div>
        )}

        {score_breakdown.crowd !== undefined ? (
          <div>👥 혼잡도 가중: {score_breakdown.crowd}점</div>
        ) : (
          <div className="text-slate-300">👥 혼잡도 가중: 해당 없음</div>
        )}
      </div>

      {hasEvidence && (
        <div className="space-y-1.5 border-t border-slate-100 pt-3">
          <span className="text-[10px] font-bold text-slate-400 block">리뷰 근거 (Evidence)</span>
          {place.evidence.map((ev, idx) => (
            <blockquote key={idx} className="text-[11px] text-slate-500 border-l-2 border-slate-200 pl-2 leading-relaxed italic">
              &ldquo;{ev.text}&rdquo; <span className="text-[9px] text-slate-400 not-italic">({ev.source})</span>
            </blockquote>
          ))}
        </div>
      )}

      {/* --- 사후 만족도 UI (카드를 클릭했을 때만 나타남) --- */}
      {clicked && (
        <div className="flex items-center gap-2 border-t border-slate-100 pt-3 mt-1">
          <span className="text-[10px] text-slate-400">이 추천 어땠나요?</span>
          {[1, 2, 3, 4, 5].map((n) => (
            <button
              key={n}
              onClick={(e) => { 
                e.stopPropagation(); // ⭐️ 중요: 카드 전체 클릭 이벤트와 중복 방지[cite: 1]
                handleRate(n); 
              }}
              disabled={rated !== null}
              aria-label={`${n}점`}
              className={`text-lg transition-colors ${
                rated !== null && n <= rated ? 'text-amber-400' : 'text-slate-200 hover:text-amber-200'
              }`}
            >
              ★
            </button>
          ))}
          {rated !== null && <span className="text-[10px] text-emerald-500 ml-1">감사합니다</span>}
        </div>
      )}
    </div>
  );
}