// components/ResultCard.tsx
'use client';

import { useState } from 'react';
import { RecommendResponse } from '@/lib/types';
import { postFeedback } from '@/lib/api';

type Place = RecommendResponse['results'][number];

interface ResultCardProps {
  place: Place;
  logId: number; // C4-2: /api/feedback 연동에 필요
}

const EXPLAIN_MODE_LABEL: Record<Place['explain_mode'], string> = {
  template: '템플릿',
  llm: 'AI 생성',
  cache: '캐시',
};

export default function ResultCard({ place, logId }: ResultCardProps) {
  const { score_breakdown } = place;
  const [clicked, setClicked] = useState(false);

  // 클릭 로깅 — 실패해도(404 포함) 화면 흐름은 막지 않는다 (postFeedback이 내부에서 처리)
  const handleClick = () => {
    if (clicked) return;
    setClicked(true);
    postFeedback({ log_id: logId, poi_id: place.poi_id, clicked: true }).catch((err) => {
      console.error('피드백 전송 실패', err);
    });
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

      {/* evidence가 빈 배열이면 인용 영역을 통째로 숨긴다 (핸드오프 §3-2) */}
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
    </div>
  );
}
