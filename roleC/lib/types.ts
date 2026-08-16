// lib/types.ts
import { PURPOSES, ATMOSPHERES } from "./constants"; // 1. ATMOSPHERES 추가

export type Purpose = typeof PURPOSES[number];
export type Atmosphere = typeof ATMOSPHERES[number]; // 2. 분위기 타입 추가

// 3. 온보딩 요청/응답 타입 추가 (Form 연동용)
export interface OnboardingRequest {
  age_band: number;
  atmospheres: Atmosphere[];
  purposes: Purpose[];
  budget_band: number;
  weather_sensitivity: number;
}

export interface OnboardingResponse {
  user_id: string;
}

// 추천 요청 (Request) 타입
export type RecommendRequest = {
  user_id: string;
  purpose: Purpose;
  party_size: number;
  budget_band: 1 | 2 | 3 | 4;
  location: { lat: number; lng: number };
  visit_at: string; // ISO8601 +09:00
};

// 추천 결과 (Response) 타입
export type RecommendResponse = {
  context: {
    weather: string; // "비 60%"
    pm25_grade: number; // 1~4
    feels_like: number;
    hotspot: string | null; // "이태원 관광특구"
    congest_now: string | null;
    congest_forecast_at_visit: string | null;
    age_mix_top: string | null; // "20대 31%"
  };
  results: Array<{
    poi_id: string;
    name: string;
    category: string;
    lat: number; 
    lng: number;
    distance_m: number;
    score: number;
    score_breakdown: {
      segment: number; 
      purpose: number; 
      taste: number;
      context: number; 
      quality: number; 
      distance: number;
      live_segment?: number; // 없을 수 있음
      crowd?: number;        // 없을 수 있음
    };
    reason: string;
    evidence: Array<{ text: string; source: string }>;
    is_exploration: boolean;
    explain_mode: "llm" | "cache" | "template";
  }>;
  log_id: number;
};