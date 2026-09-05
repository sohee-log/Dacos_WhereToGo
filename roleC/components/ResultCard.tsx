// components/ResultCard.tsx
'use client';

import { useState } from 'react';
import { RecommendResponse } from '@/lib/types';
import { postFeedback } from '@/lib/api';

type Place = RecommendResponse['results'][number];

// score/score_breakdown은 0~1 스케일이다 (PLAN.md 예시: score: 0.87). 화면엔
// "0.36점"처럼 헷갈리게 보여주지 않고 퍼센트로 환산해서 보여준다.
const toPercent = (v: number) => Math.round(v * 100);

interface ResultCardProps {
  place: Place;
  logId: number; // C4-2: /api/feedback 연동에 필요
}


export default function ResultCard({ place, logId }: ResultCardProps) {
  const { score_breakdown } = place;
  const [clicked, setClicked] = useState(false);
  const [rated, setRated] = useState<number | null>(null);

  // 클릭 로깅 — clicked는 boolean이 아니라 poi_id 배열이다 (TODO_FOR_C §C-2).
  // 실패해도(404 포함) 화면 흐름은 막지 않는다 (postFeedback이 내부에서 처리)
  const handleClick = () => {
    if (clicked) return;
    setClicked(true);
    postFeedback({ log_id: logId, clicked: [place.poi_id] }).catch((err) => {
      console.error('피드백 전송 실패', err);
    });
  };

  // 만족도 별점 — C4-3. selected는 poi_id 문자열, feedback은 1~5 (satisfaction 아님).
  const handleRate = (score: number) => {
    if (rated !== null) return;
    setRated(score);
    postFeedback({
      log_id: logId,
      selected: place.poi_id,
      feedback: score as 1 | 2 | 3 | 4 | 5,
    }).catch((err) => {
      console.error('만족도 전송 실패', err);
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
          <span className="text-xs font-black text-indigo-600 block">{toPercent(place.score)}점</span>
        </div>
      </div>

      <p className="text-xs text-slate-600 bg-slate-50 p-3 rounded-xl leading-relaxed">
        {place.reason}
      </p>

      <div className="text-[10px] text-slate-400 grid grid-cols-2 gap-1 bg-slate-50/50 p-2.5 rounded-xl border border-slate-100/60">
        <div>🎯 목적 적합도: {toPercent(score_breakdown.purpose)}%</div>
        <div>😋 취향 일치도: {toPercent(score_breakdown.taste)}%</div>
        <div>🗺️ 거리 적합도: {toPercent(score_breakdown.distance)}%</div>

        {score_breakdown.live_segment !== undefined ? (
          <div>⚡ 실시간 매칭률: {toPercent(score_breakdown.live_segment)}%</div>
        ) : (
          <div className="text-slate-300">⚡ 실시간 매칭률: 해당 없음</div>
        )}

        {score_breakdown.crowd !== undefined ? (
          <div>👥 혼잡도 가중치: {toPercent(score_breakdown.crowd)}%</div>
        ) : (
          <div className="text-slate-300">👥 혼잡도 가중치: 해당 없음</div>
        )}
      </div>

      {/* evidence가 빈 배열이면 인용 영역을 통째로 숨긴다 */}
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

      {/* C4-3: 만족도 별점 — 카드를 클릭(선택)한 뒤에만 노출 */}
      {clicked && (
        <div className="flex items-center gap-2 border-t border-slate-100 pt-3">
          <span className="text-[10px] text-slate-400">이 추천 어땠나요?</span>
          {[1, 2, 3, 4, 5].map((n) => (
            <button
              key={n}
              type="button"
              onClick={(e) => {
                e.stopPropagation(); // 카드 전체 onClick(클릭 로깅) 재발화 방지
                handleRate(n);
              }}
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
    </div>
  );
}
