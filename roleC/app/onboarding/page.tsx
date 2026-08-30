// app/onboarding/page.tsx
'use client';

import OnboardingForm from '../../components/OnboardingForm';

export default function OnboardingPage() {
  // 💡 onSuccess가 userId와 함께 유저가 선택한 무드 배열(string[])도 받도록 수정합니다.
  // ⚠️ /recommend로 바로 안 보내고 /onboarding/party를 한 번 거친다 —
  // party_size(인원수)는 5문항 온보딩엔 안 넣었지만, 첫 추천 요청부터 정확히
  // 반영되도록 여기서 한 스텝 더 받는다 (party_size가 조용히 2로 나가던 문제 해결).
  const handleSuccess = (userId: string, moods: string[]) => {
    console.log("온보딩 성공! 전달받은 ID:", userId, "무드 리스트:", moods);

    const moodQuery = moods.join(',');

    // 브라우저 주소창에 유저 고유 ID와 수집된 성향 데이터를 완벽하게 믹스해서 출발시킵니다.
    window.location.href = `/onboarding/party?user_id=${userId}&mood=${encodeURIComponent(moodQuery)}`;
  };

  return (
    <main className="max-w-md mx-auto p-6 min-h-screen bg-white">
      <div className="mb-8">
        <h1 className="text-2xl font-bold mb-2 text-gray-900">반가워요! 당신의 성향을 알려주세요</h1>
        <p className="text-gray-500 text-sm">지금 상황에 딱 맞는 용산 맛집/장소를 찾기 위한 5가지 질문입니다.</p>
      </div>

      <OnboardingForm onSuccess={handleSuccess} />
    </main>
  );
}
