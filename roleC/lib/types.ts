// lib/types.ts
//
// API 계약 타입은 **손으로 쓰지 않는다.** roleB/openapi.yaml에서 생성한
// `./api-types`가 원본이고, 이 파일은 거기에 없는 화면 전용 타입만 갖는다.
//
//   생성:  cd roleB && python -m tools.gen_ts_types
//   검증:  roleB/tests/test_ts_contract.py (CI에서 돈다)
//
// 손으로 베껴 쓰던 시절 POST /api/feedback 이 전부 422였는데, 화면은 멀쩡하고
// recommendation_log만 비어 있어서 아무도 몰랐다. 그래서 생성으로 바꿨다.
import type { ApiErrorBody } from './api-types';

export type {
  Purpose,
  Atmosphere,
  CongestLevel,
  ExplainMode,
  Location,
  ApiErrorBody,
  OnboardingRequest,
  Context,
  RecommendRequest,
  ScoreBreakdown,
  Evidence,
  Recommendation,
  RecommendResponse,
  FeedbackRequest,
  PoiDetail,
} from './api-types';

// 온보딩 응답은 스키마가 인라인이라(openapi의 /api/onboarding 200) 생성 대상이 아니다.
export interface OnboardingResponse {
  user_id: string;
}

// 날씨 출처. Context['weather_source']에서 null을 걷어낸 것 — ?debug=1 화면에서 쓴다.
export type WeatherSource = NonNullable<
  import('./api-types').Context['weather_source']
>;

// api.ts가 던지는 에러 — 상태코드별로 화면을 분기하려고 status를 들고 있다.
// 422 = 계약 위반(이쪽 타입을 먼저 의심한다) / 429 = 레이트 리밋 / 503 = DB 미가용
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
