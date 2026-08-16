'use client';

import OnboardingForm from '../../components/OnboardingForm';

export default function OnboardingPage() {
  return (
    <main className="max-w-md mx-auto p-6 min-h-screen bg-white">
      <div className="mb-8">
        <h1 className="text-2xl font-bold mb-2 text-gray-900">반가워요! 당신의 성향을 알려주세요</h1>
        <p className="text-gray-500 text-sm">지금 상황에 딱 맞는 용산 맛집/장소를 찾기 위한 5가지 질문입니다.</p>
      </div>
      
      {/* 온보딩 통합 폼 */}
      <OnboardingForm />
    </main>
  );
}