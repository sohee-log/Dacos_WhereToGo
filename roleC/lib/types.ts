// lib/types.ts
import { PURPOSES, ATMOSPHERES } from "./constants"; // 1. ATMOSPHERES 추가

export type Purpose = typeof PURPOSES[number];
export type Atmosphere = typeof ATMOSPHERES[number]; // 2. 분위기 타입 추가

// 3. 온보딩 요청/응답 타입 추가 (Form 연동용)
export interface OnboardingRequest {
  gender: 'M' | 'F';
  age_band: number;
  atmosphere_tags: Atmosphere[]; 
  purpose_tags: Purpose[];      
  budget_band: number;
  weather_sensitivity: number;
}

export interface OnboardingResponse {
  user_id: string;
}

// 클릭 → 선택 → 만족도를 여러 번에 나눠 보낼 수 있다 (핸드오프 §3-4)
// 빈 값은 서버가 덮어쓰지 않으므로 매번 전체를 다시 보낼 필요 없음
export interface FeedbackRequest {
  log_id: number;
  poi_id?: string;
  clicked?: boolean;
  selected?: boolean;
  satisfaction?: number; // 1~5
}

// 표준 에러 응답 (422 / 429 / 503 / 404)
// 429는 code:"rate_limited" + Retry-After 헤더가 함께 온다 (핸드오프 §2-2)
export interface ApiErrorBody {
  detail: string;
  code?: string;
}

// api.ts가 던지는 에러 — 상태코드별로 화면 분기하기 위해 status를 들고 있다
export class ApiError extends Error {
  status: number;
  code?: string;
  retryAfter?: number; // 초 단위, 429일 때만

  constructor(status: number, body: ApiErrorBody, retryAfter?: number) {
    super(body.detail);
    this.status = status;
    this.code = body.code;
    this.retryAfter = retryAfter;
  }
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

// weather_source: 값 하나가 늘었다 (핸드오프 §10-1) — citydata_fcst
// citydata: 실황(사실) / citydata_fcst: citydata 24h예보(확률) /
// kma, kma+citydata: 기상청 단기예보(확률) / mock: 소스 없음(가짜)
export type WeatherSource =
  | "citydata"
  | "citydata_fcst"
  | "kma"
  | "kma+citydata"
  | "mock";

// 추천 결과 (Response) 타입
export type RecommendResponse = {
  context: {
    weather: string; // "비 60%"
    pm25_grade: number; // 1~4
    feels_like: number;
    hotspot: string | null; // "이태원 관광특구"
    congest_now: string | null;
    congest_forecast_at_visit: string | null;
    age_mix_top: string | null; // "20대 31%" | "10대 미만 12%" | "70대 이상 9%"
    weather_source?: WeatherSource; // ?debug=1 화면용, 화면에 그릴 필요는 없음
    sunset?: string; // "19:42" — 분 단위까지 온다
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