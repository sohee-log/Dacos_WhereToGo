// components/RequestForm.tsx
import { Purpose } from '@/lib/types';
import { PURPOSES } from '@/lib/constants'; // ⚠️ 기존 PURPOSE_LIST → PURPOSES로 통일
                                             // (OnboardingForm 등 다른 파일과 이름이 달랐음.
                                             //  constants.ts에 PURPOSE_LIST가 실제로 존재한다면
                                             //  이 줄만 되돌리면 됨)

interface RequestFormProps {
  purpose: Purpose;
  setPurpose: (p: Purpose) => void;
  partySize: number;
  setPartySize: (s: number) => void;
  budgetBand: number;
  setBudgetBand: (b: number) => void;
  visitAt: string; // ISO8601
  setVisitAt: (v: string) => void;
  onSubmit: () => void;
}

const BUDGET_LABELS: Record<number, string> = {
  1: '1만원 이하',
  2: '1~3만원',
  3: '3~5만원',
  4: '5만원 이상',
};

// <input type="datetime-local">은 로컬 시각 문자열(YYYY-MM-DDTHH:mm)을 쓰고
// 서버는 ISO8601(+09:00)을 기대하므로 여기서 변환한다.
function toDatetimeLocalValue(iso: string): string {
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function fromDatetimeLocalValue(local: string): string {
  // datetime-local 값은 타임존 정보가 없으므로 로컬(KST 가정)로 해석해 ISO로 변환
  return new Date(local).toISOString();
}

export default function RequestForm({
  purpose,
  setPurpose,
  partySize,
  setPartySize,
  budgetBand,
  setBudgetBand,
  visitAt,
  setVisitAt,
  onSubmit,
}: RequestFormProps) {
  return (
    <div className="bg-white p-4 rounded-2xl border border-slate-100 shadow-sm space-y-3">
      <p className="text-xs font-bold text-slate-700">🎯 조건 변경하여 재검색</p>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="block text-[11px] text-slate-400 font-medium mb-1">방문 목적</label>
          <select
            value={purpose}
            onChange={(e) => setPurpose(e.target.value as Purpose)}
            className="w-full text-xs p-2 rounded-xl bg-slate-50 border border-slate-100 focus:outline-none focus:border-blue-500 text-slate-800"
          >
            {PURPOSES.map((p) => <option key={p} value={p}>{p}</option>)}
          </select>
        </div>
        <div>
          <label className="block text-[11px] text-slate-400 font-medium mb-1">동행 인원</label>
          <input
            type="number"
            min={1}
            max={99}
            value={partySize}
            onChange={(e) => setPartySize(Number(e.target.value))}
            className="w-full text-xs p-2 rounded-xl bg-slate-50 border border-slate-100 focus:outline-none focus:border-blue-500 text-slate-800"
          />
        </div>
        <div>
          <label className="block text-[11px] text-slate-400 font-medium mb-1">예산대</label>
          <select
            value={budgetBand}
            onChange={(e) => setBudgetBand(Number(e.target.value))}
            className="w-full text-xs p-2 rounded-xl bg-slate-50 border border-slate-100 focus:outline-none focus:border-blue-500 text-slate-800"
          >
            {[1, 2, 3, 4].map((b) => (
              <option key={b} value={b}>{BUDGET_LABELS[b]}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-[11px] text-slate-400 font-medium mb-1">방문 예정 시각</label>
          <input
            type="datetime-local"
            value={toDatetimeLocalValue(visitAt)}
            onChange={(e) => setVisitAt(fromDatetimeLocalValue(e.target.value))}
            className="w-full text-xs p-2 rounded-xl bg-slate-50 border border-slate-100 focus:outline-none focus:border-blue-500 text-slate-800"
          />
        </div>
      </div>
      <button
        onClick={onSubmit}
        className="w-full bg-slate-900 text-white text-xs font-bold py-2.5 rounded-xl hover:bg-slate-800 transition-colors"
      >
        새로운 맞춤 장소 가져오기
      </button>
    </div>
  );
}
