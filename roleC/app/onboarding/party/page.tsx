// app/onboarding/party/page.tsx
'use client';

import { useState, Suspense } from 'react';
import { useSearchParams } from 'next/navigation';

// 온보딩(5문항) 뒤, /recommend로 넘어가기 전에 딱 하나만 더 묻는 화면.
// party_size는 "이 사람이 어떤 사람인가"(프로필)가 아니라 "이번엔 누구랑 가는가"
// (매번 다른 occasion 정보)라서 5문항 온보딩에는 안 넣고 여기서 따로 받는다.
// 이게 없으면 첫 추천 요청이 사용자에게 묻지도 않고 조용히 party_size=2로
// 나가서, 실제 인원과 다르면 첫 결과부터 어긋난다.

const PARTY_SIZE_PRESETS = [1, 2, 3, 4, 5, 6];

function PartyStepContent() {
  const searchParams = useSearchParams();
  const userId = searchParams.get('user_id');
  const mood = searchParams.get('mood');

  const [partySize, setPartySize] = useState<number>(2);
  const [customMode, setCustomMode] = useState(false);

  const handleNext = () => {
    const params = new URLSearchParams();
    if (userId) params.set('user_id', userId);
    if (mood) params.set('mood', mood);
    params.set('party_size', String(partySize));
    window.location.href = `/recommend?${params.toString()}`;
  };

  if (!userId) {
    return (
      <main className="max-w-md mx-auto p-6 min-h-screen bg-white flex flex-col items-center justify-center text-center">
        <p className="text-sm text-slate-500 mb-4">
          유저 정보가 없습니다. 온보딩을 다시 진행해주세요.
        </p>
        <a
          href="/onboarding"
          className="text-xs font-bold text-white bg-slate-900 px-4 py-2 rounded-xl"
        >
          온보딩으로 가기
        </a>
      </main>
    );
  }

  return (
    <main className="max-w-md mx-auto p-6 min-h-screen bg-white flex flex-col justify-center">
      <div className="mb-8">
        <h1 className="text-2xl font-bold mb-2 text-gray-900">
          이번엔 몇 분이서 가세요? 👥
        </h1>
        <p className="text-gray-500 text-sm">
          같이 가는 인원에 맞춰 좌석·규모가 맞는 곳 위주로 골라드려요.
        </p>
      </div>

      <div className="bg-white p-6 rounded-3xl border border-slate-100 shadow-sm space-y-6">
        {!customMode ? (
          <div className="grid grid-cols-3 gap-3">
            {PARTY_SIZE_PRESETS.map((n) => (
              <button
                key={n}
                type="button"
                onClick={() => setPartySize(n)}
                className={`py-4 rounded-xl border text-sm font-bold transition-all ${
                  partySize === n
                    ? 'bg-blue-600 border-blue-600 text-white shadow-sm'
                    : 'bg-slate-50 border-slate-100 text-slate-700 hover:bg-slate-100'
                }`}
              >
                {n}명{n === 6 ? '+' : ''}
              </button>
            ))}
          </div>
        ) : (
          <div className="space-y-2">
            <label className="block text-xs font-bold text-slate-700">
              정확한 인원 수
            </label>
            <input
              type="number"
              min={1}
              max={99}
              value={partySize}
              onChange={(e) => setPartySize(Number(e.target.value))}
              className="w-full text-sm p-3 rounded-xl bg-slate-50 border border-slate-100 font-semibold text-slate-800 focus:outline-none focus:border-blue-500"
              autoFocus
            />
          </div>
        )}

        <button
          type="button"
          onClick={() => setCustomMode((v) => !v)}
          className="text-[11px] text-slate-400 underline"
        >
          {customMode ? '프리셋에서 고르기' : '정확한 숫자로 입력할게요'}
        </button>
      </div>

      <button
        type="button"
        onClick={handleNext}
        className="w-full bg-blue-600 hover:bg-blue-700 text-white font-black py-4 rounded-2xl shadow-md text-sm transition-colors mt-6"
      >
        맞춤 장소 보러 가기 🚀
      </button>
    </main>
  );
}

export default function PartyStepPage() {
  return (
    <Suspense fallback={<div className="p-6 text-center text-xs">로딩 중...</div>}>
      <PartyStepContent />
    </Suspense>
  );
}
