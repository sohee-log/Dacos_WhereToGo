// components/OnboardingForm.tsx
'use client';

import { useState } from 'react';
import { Purpose, Atmosphere, OnboardingRequest, OnboardingResponse } from '@/lib/types';
import { PURPOSES, ATMOSPHERES } from '@/lib/constants';
import { submitOnboarding, ApiError } from '@/lib/api';

interface OnboardingFormProps {
  onSuccess?: (userId: string, moods: string[]) => void;
}

export default function OnboardingForm({ onSuccess }: OnboardingFormProps) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // 1. 온보딩 상태 관리 (5문항 이하 제약 준수)
  const [gender, setGender] = useState<'M' | 'F'>('M');
  const [ageBand, setAgeBand] = useState<number>(20);
  const [selectedAtmospheres, setSelectedAtmospheres] = useState<Atmosphere[]>([]);
  const [selectedPurposes, setSelectedPurposes] = useState<Purpose[]>([]);
  const [budgetBand, setBudgetBand] = useState<number>(2);
  // 5번 문항: 날씨 민감도. B가 context_fit 개인 가중치로 쓰는 유일한 개인화 항이라
  // 하드코딩하면 안 되고 실제로 물어봐야 한다 (핸드오프 §9-1, ROLE_C §부록A-5).
  // 1=미루지 않음 · 2=보통 · 3=많이 미룸
  const [weatherSensitivity, setWeatherSensitivity] = useState<number>(2);

  const toggleAtmosphere = (tag: Atmosphere) => {
    setSelectedAtmospheres(prev => 
      prev.includes(tag) ? prev.filter(t => t !== tag) : [...prev, tag]
    );
  };

  const togglePurpose = (tag: Purpose) => {
    setSelectedPurposes(prev => 
      prev.includes(tag) ? prev.filter(t => t !== tag) : [...prev, tag]
    );
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);

    // openapi 계약서 (OnboardingRequest) 양식 완벽 충족
    const payload: OnboardingRequest = {
      gender,
      age_band: ageBand,
      atmosphere_tags: selectedAtmospheres,
      purpose_tags: selectedPurposes,
      budget_band: budgetBand,
      weather_sensitivity: weatherSensitivity
    };

    try {
      const data: OnboardingResponse = await submitOnboarding(payload);
      
      // 💡 [핵심] 유저가 선택한 분위기 태그(#)와 목적 단어들을 하나의 한글 단어 배열로 깔끔하게 정리합니다.
      const collectedMoods = [
        ...selectedAtmospheres,
        ...selectedPurposes
      ].filter(Boolean);

      // 부모에게 콜백을 넘겨주되, 둘 다 무드가 태워지도록 고도화합니다.
      if (onSuccess && typeof onSuccess === 'function') {
        onSuccess(data.user_id, collectedMoods);
      } else {
        // 백업용 다이렉트 이동 시에도 주소창 뒤에 무드 리스트를 강제로 태웁니다.
        const moodQuery = collectedMoods.join(',');
        window.location.href = `/recommend?user_id=${data.user_id}&mood=${encodeURIComponent(moodQuery)}`;
      }
    } catch (err: unknown) {
      console.error(err);
      if (err instanceof ApiError && err.status === 422) {
        // 여기가 뜨면 필드명/필수값이 openapi.yaml과 다시 어긋난 것이다
        setError('입력값을 확인해주세요. (문항이 서버 규격과 맞지 않습니다)');
      } else if (err instanceof Error) {
        setError(err.message || '오류가 발생했습니다.');
      } else {
        setError('오류가 발생했습니다.');
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-6 max-w-md mx-auto bg-white p-6 rounded-3xl border border-slate-100 shadow-sm">
      <div className="space-y-1">
        <h2 className="text-xl font-black text-slate-900">반가워요! ⚡</h2>
        <p className="text-xs text-slate-400">당신의 성향을 기반으로 용산구 핫플을 큐레이션합니다.</p>
      </div>

      {error && <p className="text-xs text-red-500 font-medium">⚠️ {error}</p>}

      {/* 문항 1: 성별 & 나이대 */}
      <div className="space-y-2">
        <label className="block text-xs font-bold text-slate-700">1. 본인의 성별과 나이대를 알려주세요</label>
        <div className="grid grid-cols-2 gap-3">
          <div className="flex bg-slate-50 p-1 rounded-xl border border-slate-100">
            <button
              key="gender-M"
              type="button"
              onClick={() => setGender('M')}
              className={`flex-1 text-xs font-bold py-2 rounded-lg transition-all ${gender === 'M' ? 'bg-white text-blue-600 shadow-sm' : 'text-slate-400'}`}
            >
              남성
            </button>
            <button
              key="gender-F"
              type="button"
              onClick={() => setGender('F')}
              className={`flex-1 text-xs font-bold py-2 rounded-lg transition-all ${gender === 'F' ? 'bg-white text-blue-600 shadow-sm' : 'text-slate-400'}`}
            >
              여성
            </button>
          </div>
          <select
            value={ageBand}
            onChange={(e) => setAgeBand(Number(e.target.value))}
            className="text-xs p-2.5 rounded-xl bg-slate-50 border border-slate-100 font-semibold text-slate-700 focus:outline-none"
          >
            <option value={10}>10대</option>
            <option value={20}>20대</option>
            <option value={30}>30대</option>
            <option value={40}>40대 이상</option>
          </select>
        </div>
      </div>

      {/* 문항 2: 선호 분위기 태그 */}
      <div className="space-y-2">
        <label className="block text-xs font-bold text-slate-700">2. 선호하는 공간 분위기 (복수 선택)</label>
        <div className="flex flex-wrap gap-1.5">
          {ATMOSPHERES.map((tag) => {
            const isSelected = selectedAtmospheres.includes(tag);
            return (
              <button
                key={`atmosphere-${tag}`}
                type="button"
                onClick={() => toggleAtmosphere(tag)}
                className={`text-xs px-3 py-1.5 rounded-xl border font-medium transition-all ${
                  isSelected 
                    ? 'bg-blue-600 border-blue-600 text-white font-bold shadow-sm' 
                    : 'bg-slate-50 border-slate-100 text-slate-600 hover:bg-slate-100'
                }`}
              >
                #{tag}
              </button>
            );
          })}
        </div>
      </div>

      {/* 문항 3: 주된 방문 목적 */}
      <div className="space-y-2">
        <label className="block text-xs font-bold text-slate-700">3. 용산에 주로 누구와 어떤 목적으로 가시나요?</label>
        <div className="flex flex-wrap gap-1.5">
          {PURPOSES.map((tag) => {
            const isSelected = selectedPurposes.includes(tag);
            return (
              <button
                key={`purpose-${tag}`}
                type="button"
                onClick={() => togglePurpose(tag)}
                className={`text-xs px-3 py-1.5 rounded-xl border font-medium transition-all ${
                  isSelected 
                    ? 'bg-indigo-600 border-indigo-600 text-white font-bold shadow-sm' 
                    : 'bg-slate-50 border-slate-100 text-slate-600 hover:bg-slate-100'
                }`}
              >
                {tag}
              </button>
            );
          })}
        </div>
      </div>

      {/* 문항 4: 예산 범위 */}
      <div className="space-y-2">
        <label className="block text-xs font-bold text-slate-700">4. 선호하는 1인당 예산대</label>
        <div className="grid grid-cols-2 gap-2">
          {[
            { band: 1, label: '1단계 (1만 원대)', desc: '가성비 맛집' },
            { band: 2, label: '2단계 (2~3만 원대)', desc: '평범한 식사·카페' },
            { band: 3, label: '3단계 (4~5만 원대)', desc: '분위기 내는 데이트' },
            { band: 4, label: '4단계 (럭셔리)', desc: '파인데이닝·오마카세' },
          ].map((item) => (
            <button
              key={`budget-${item.band}`}
              type="button"
              onClick={() => setBudgetBand(item.band)}
              className={`text-left p-3 rounded-xl border transition-all flex flex-col justify-between ${
                budgetBand === item.band 
                  ? 'bg-slate-900 border-slate-900 text-white' 
                  : 'bg-slate-50 border-slate-100 text-slate-700 hover:bg-slate-100'
              }`}
            >
              <span className="text-xs font-bold">{item.label}</span>
              <span className={`text-[10px] mt-0.5 ${budgetBand === item.band ? 'text-slate-300' : 'text-slate-400'}`}>
                {item.desc}
              </span>
            </button>
          ))}
        </div>
      </div>

      {/* 문항 5: 날씨 민감도 — 비 오면 약속을 미루는 편인가? (부록 A-5) */}
      <div className="space-y-2">
        <label className="block text-xs font-bold text-slate-700">5. 비가 오면 약속을 미루는 편인가요?</label>
        <div className="flex bg-slate-50 p-1 rounded-xl border border-slate-100">
          {[
            { value: 1, label: '전혀 안 미룸' },
            { value: 2, label: '보통' },
            { value: 3, label: '거의 미룸' },
          ].map((item) => (
            <button
              key={`weather-sensitivity-${item.value}`}
              type="button"
              onClick={() => setWeatherSensitivity(item.value)}
              className={`flex-1 text-xs font-bold py-2 rounded-lg transition-all ${
                weatherSensitivity === item.value
                  ? 'bg-white text-blue-600 shadow-sm'
                  : 'text-slate-400'
              }`}
            >
              {item.label}
            </button>
          ))}
        </div>
      </div>

      <button
        type="submit"
        disabled={loading}
        className="w-full bg-blue-600 text-white font-black py-3 rounded-2xl shadow-md text-sm hover:bg-blue-700 transition-colors disabled:bg-slate-200"
      >
        {loading ? '프로필 엔진 생성 중...' : '맞춤 맛집 탐색 시작하기 🚀'}
      </button>
    </form>
  );
}