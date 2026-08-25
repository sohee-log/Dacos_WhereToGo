// components/KakaoMap.tsx
'use client';

import { useEffect } from 'react';
import Script from 'next/script';

// window.kakao 타입은 lib/global.d.ts (프로젝트 루트 global.d.ts)에서 이미
// 전역으로 선언되어 있다 — 여기서 다시 선언하지 않는다 (중복 방지).

interface KakaoMapProps {
  places: Array<{
    poi_id: string;
    name: string;
    lat: number;
    lng: number;
    category: string;
  }>;
}

export default function KakaoMap({ places }: KakaoMapProps) {
  // ⚠️ 환경변수 이름을 ROLE_C_WEB.md §1.4 / .env.example 기준(NEXT_PUBLIC_KAKAO_JS_KEY)에
  // 맞췄다. 기존 NEXT_PUBLIC_KAKAO_MAP_CLIENT_KEY는 Vercel에 등록된 이름과 달라
  // appkey=undefined로 나가면서 지도가 조용히 안 뜨는 상태였을 가능성이 높다.
  const KAKAO_KEY = process.env.NEXT_PUBLIC_KAKAO_JS_KEY;

  if (!KAKAO_KEY && typeof window !== 'undefined') {
    // 개발 중 바로 눈치채도록 콘솔에만 남긴다 (사용자에게 노출 X)
    console.warn('[KakaoMap] NEXT_PUBLIC_KAKAO_JS_KEY가 비어있습니다. Vercel 환경변수를 확인하세요.');
  }

  const initMap = () => {
    if (!window.kakao || !window.kakao.maps) return;

    window.kakao.maps.load(() => {
      const container = document.getElementById('kakao-map');
      if (!container || !places || places.length === 0) return;

      const centerPlace = places[0];

      const options = {
        center: new window.kakao.maps.LatLng(centerPlace.lat, centerPlace.lng),
        level: 4,
      };

      const map = new window.kakao.maps.Map(container, options);

      // 마커들을 모아서 지도가 한눈에 보이게 반경을 재조정하기 위한 객체
      const bounds = new window.kakao.maps.LatLngBounds();

      places.forEach((place) => {
        const markerPosition = new window.kakao.maps.LatLng(place.lat, place.lng);
        const marker = new window.kakao.maps.Marker({
          position: markerPosition,
        });
        marker.setMap(map);
        bounds.extend(markerPosition);
      });

      // 모든 마커가 다 보이도록 지도 화면 범위 자동으로 맞추기
      map.setBounds(bounds);
    });
  };

  // 💡 데이터가 나중에 로드되어 들어왔을 때(리렌더링 시) 지도를 다시 강제로 그리도록 설정
  useEffect(() => {
    if (window.kakao && window.kakao.maps) {
      initMap();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [places]);

  return (
    <>
      <Script
        src={`//dapi.kakao.com/v2/maps/sdk.js?appkey=${KAKAO_KEY}&autoload=false`}
        strategy="afterInteractive"
        onLoad={initMap}
      />
      <div id="kakao-map" className="w-full h-[250px] bg-slate-100" />
    </>
  );
}
