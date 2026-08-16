'use client';

import { useState } from 'react';
import { PURPOSES, AGE_BANDS, BUDGET_LABELS } from '../lib/constants';
import TagGrid from './TagGrid';

export default function OnboardingForm() {
  // 1. 연령대 상태
  const [ageBand, setAgeBand] = useState<number>(20); // 기본값 20대
  
  // 2. 선호 분위기 상태 (TagGrid 연동)
  const [selectedAtmospheres, setSelectedAtmospheres] = useState<string[]>([]);
  
  // 3. 주로 가는 목적 상태
  const [selectedPurposes, setSelectedPurposes] = useState<string[]>([]);
  
  // 4. 평소 예산대 상태 (인덱스 기반 1~4)
  const [budgetBand, setBudgetBand] = useState<number>(2); // 기본값 1~3만원
  
  // 5. 날씨 민감도 상태 (지시서 필수: 1~3 단계)
  const [weatherSensitivity, setWeatherSensitivity] = useState<number>(2); 

  // 목적(PURPOSES) 토글 함수
  const togglePurpose = (purpose: string) => {
    if (selectedPurposes.includes(purpose)) {
      setSelectedPurposes(selectedPurposes.filter((p) => p !== purpose));
    } else {
      setSelectedPurposes([...selectedPurposes, purpose]);
    }
  };

  // 완료 제출 핸들러
  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    
    // 지시서의 백엔드 계약 규격에 맞게 데이터 포맷팅
    const onboardingData = {
      age_band: ageBand,
      atmospheres: selectedAtmospheres,
      purposes: selectedPurposes,
      budget_band: budgetBand,
      weather_sensitivity: weatherSensitivity,
    };

    alert('🎉 온보딩 데이터 수집 완료!\n' + JSON.stringify(onboardingData, null, 2));
    // TODO: W4에서 실 API(/api/onboarding) 연동 예정
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-8 pb-12 text-gray-900">
      {/* 문항 1: 연령대 */}
      <div className="space-y-3">
        <label className="block text-lg font-bold">1. 연령대를 선택해 주세요.</label>
        <div className="flex flex-wrap gap-2">
          {AGE_BANDS.map((age) => (
            <button
              key={age}
              type="button"
              onClick={() => setAgeBand(age)}
              className={`px-4 py-2 rounded-xl border text-sm font-medium transition-all ${
                ageBand === age
                  ? 'bg-blue-600 text-white border-blue-600 shadow-sm'
                  : 'bg-white text-gray-700 border-gray-200 hover:border-gray-300'
              }`}
            >
              {age}대
            </button>
          ))}
        </div>
      </div>

      {/* 문항 2: 분위기 (TagGrid) */}
      <div className="space-y-3">
        <label className="block text-lg font-bold">2. 어떤 분위기를 선호하시나요? (다중 선택)</label>
        <TagGrid selectedTags={selectedAtmospheres} onChange={setSelectedAtmospheres} />
      </div>

      {/* 문항 3: 방문 목적 */}
      <div className="space-y-3">
        <label className="block text-lg font-bold">3. 주로 어떤 목적으로 방문하시나요? (다중 선택)</label>
        <div className="grid grid-cols-3 gap-3 p-4 bg-gray-50 rounded-2xl">
          {PURPOSES.map((purpose) => {
            const isSelected = selectedPurposes.includes(purpose);
            return (
              <button
                key={purpose}
                type="button"
                onClick={() => togglePurpose(purpose)}
                className={`p-3 rounded-xl border text-sm font-medium transition-all duration-200 active:scale-95 ${
                  isSelected
                    ? 'bg-blue-600 text-white border-blue-600 shadow-md shadow-blue-100'
                    : 'bg-white text-gray-700 border-gray-200 hover:border-gray-300'
                }`}
              >
                {purpose}
              </button>
            );
          })}
        </div>
      </div>

      {/* 문항 4: 예산대 */}
      <div className="space-y-3">
        <label className="block text-lg font-bold">4. 평소 1인당 예산대는 어느 정도인가요?</label>
        <div className="grid grid-cols-2 gap-2">
          {BUDGET_LABELS.map((label, index) => (
            <button
              key={label}
              type="button"
              onClick={() => setBudgetBand(index + 1)} // 지시서 스펙상 1~4 밴드
              className={`p-3 rounded-xl border text-sm font-medium transition-all ${
                budgetBand === index + 1
                  ? 'bg-blue-600 text-white border-blue-600 shadow-sm'
                  : 'bg-white text-gray-700 border-gray-200 hover:border-gray-300'
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {/* 문항 5: 날씨 민감도 (B의 개인화 랭킹에 치명적인 요소) */}
      <div className="space-y-3">
        <label className="block text-lg font-bold">
          5. 비가 오면 원래 잡았던 약속을 미루거나 취소하는 편인가요?
        </label>
        <div className="grid grid-cols-3 gap-2">
          {[
            { level: 1, text: '상관없음 (그냥 감)' },
            { level: 2, text: '약간 고민함' },
            { level: 3, text: '무조건 미룸 (실내 필수)' },
          ].map((item) => (
            <button
              key={item.level}
              type="button"
              onClick={() => setWeatherSensitivity(item.level)}
              className={`p-3 rounded-xl border text-xs font-medium transition-all ${
                weatherSensitivity === item.level
                  ? 'bg-blue-600 text-white border-blue-600 shadow-sm'
                  : 'bg-white text-gray-700 border-gray-200 hover:border-gray-300'
              }`}
            >
              {item.text}
            </button>
          ))}
        </div>
      </div>

      {/* 제출 버튼 */}
      <button
        type="submit"
        className="w-full p-4 bg-blue-600 hover:bg-blue-700 text-white font-bold rounded-xl shadow-lg shadow-blue-100 transition-all active:scale-[0.99]"
      >
        선호도 저장하고 맞춤 장소 찾기
      </button>
    </form>
  );
}