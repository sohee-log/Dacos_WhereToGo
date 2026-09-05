// components/ScoreDebug.tsx
import { RecommendResponse } from '@/lib/types';

interface ScoreDebugProps {
  scoreBreakdown: RecommendResponse['results'][number]['score_breakdown'];
  score: number;
  explainMode: RecommendResponse['results'][number]['explain_mode'];
}

// score/score_breakdown은 0~1 스케일이다 (PLAN.md 예시: score: 0.87). "0.36점"처럼
// 헷갈리게 보여주지 않고 퍼센트로 환산한다.
const toPercent = (v: number) => Math.round(v * 100);

export default function ScoreDebug({ scoreBreakdown, score, explainMode }: ScoreDebugProps) {
  return (
    <div className="mt-3 p-3 bg-slate-900 text-emerald-400 rounded-xl font-mono text-[11px] space-y-2 border border-slate-800 shadow-inner">
      <div className="flex justify-between items-center border-b border-slate-800 pb-1.5 font-bold">
        <span>🛠️ 점수 브레이크다운 (DEBUG_MODE)</span>
        <span className="bg-emerald-500/10 px-1.5 py-0.5 rounded text-emerald-300">
          모드: {explainMode}
        </span>
      </div>

      <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-slate-300">
        <p>🎯 총점: <span className="text-white font-bold">{toPercent(score)}점</span></p>
        <p>👥 세그먼트: <span>{toPercent(scoreBreakdown.segment)}%</span></p>
        <p>🍢 목적성 일치: <span>{toPercent(scoreBreakdown.purpose)}%</span></p>
        <p>👅 취향(Taste): <span>{toPercent(scoreBreakdown.taste)}%</span></p>
        <p>⛅ 상황 매칭: <span>{toPercent(scoreBreakdown.context)}%</span></p>
        <p>⭐ 장소 퀄리티: <span>{toPercent(scoreBreakdown.quality)}%</span></p>
        <p>📍 거리 적합도: <span>{toPercent(scoreBreakdown.distance)}%</span></p>

        {/* ⚠️ 리드미 절대 규칙: undefined일 때 0으로 조작하지 않고 "해당 없음" 처리 */}
        <p>⚡ 실시간 세그먼트: {' '}
          <span className={scoreBreakdown.live_segment === undefined ? 'text-slate-500 italic' : 'text-amber-400 font-bold'}>
            {scoreBreakdown.live_segment !== undefined ? `${toPercent(scoreBreakdown.live_segment)}%` : '해당 없음'}
          </span>
        </p>

        <p>🎪 혼잡도 가중치: {' '}
          <span className={scoreBreakdown.crowd === undefined ? 'text-slate-500 italic' : 'text-amber-400 font-bold'}>
            {scoreBreakdown.crowd !== undefined ? `${toPercent(scoreBreakdown.crowd)}%` : '해당 없음'}
          </span>
        </p>
      </div>
    </div>
  );
}
