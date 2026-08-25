// global.d.ts
// 카카오맵 SDK는 공식 타입 패키지가 없어서, KakaoMap.tsx에서 실제로 쓰는
// 메서드만 최소한으로 타입을 잡아둔다. `any`를 피하면서도 진짜 SDK 전체를
// 흉내 내려고 하지 않는다 (거짓 타입 안정성 방지).
interface KakaoLatLng {
  // 카카오 SDK 내부 구현 세부사항 — 여기서는 불투명한 값으로만 다룬다
  getLat(): number;
  getLng(): number;
}

interface KakaoLatLngBounds {
  extend(latlng: KakaoLatLng): void;
}

interface KakaoMapInstance {
  setBounds(bounds: KakaoLatLngBounds): void;
}

interface KakaoMarker {
  setMap(map: KakaoMapInstance | null): void;
}

interface KakaoMapsNamespace {
  load(callback: () => void): void;
  LatLng: new (lat: number, lng: number) => KakaoLatLng;
  LatLngBounds: new () => KakaoLatLngBounds;
  Map: new (
    container: HTMLElement,
    options: { center: KakaoLatLng; level: number }
  ) => KakaoMapInstance;
  Marker: new (options: { position: KakaoLatLng }) => KakaoMarker;
}

interface Window {
  kakao: {
    maps: KakaoMapsNamespace;
  };
}
