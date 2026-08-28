// lib/api-types.ts
//
// ⚠️ 생성 파일이다. 손으로 고치지 말 것 — 다음 생성에서 덮어써진다.
//
//   원본:  roleB/openapi.yaml
//   생성:  cd roleB && python -m tools.gen_ts_types
//   검증:  roleB/tests/test_ts_contract.py (CI에서 돈다)
//
// 계약을 손으로 베껴 쓰다가 POST /api/feedback 이 통째로 422가 난 적이 있다.
// 화면은 멀쩡했고 recommendation_log만 비어 있었다. 그래서 생성으로 바꿨다.

export type Purpose = "데이트" | "친구모임" | "혼자" | "가족" | "작업" | "회식";

export type Atmosphere = "조용한" | "활기찬" | "감성적인" | "트렌디한" | "로컬한" | "넓은" | "뷰가좋은" | "아늑한" | "이국적인" | "가성비";

export type CongestLevel = "여유" | "보통" | "약간 붐빔" | "붐빔";

/**
 * llm      — 실시간 생성
 * cache    — explanation_cache 히트
 * template — LLM 쿼터 소진으로 템플릿 폴백
 */
export type ExplainMode = "llm" | "cache" | "template";

export interface Location {
  lat: number;
  lng: number;
}

export interface ApiErrorBody {
  detail: string;
  code?: string;
}

export interface OnboardingRequest {
  gender: "M" | "F";
  age_band: 10 | 20 | 30 | 40 | 50 | 60;
  atmosphere_tags: Atmosphere[];
  purpose_tags: Purpose[];
  budget_band: number;
  /** 비 오면 약속을 미루는 편인가. context_fit 개인 가중치로 쓰인다 */
  weather_sensitivity: number;
}

export interface Context {
  weather: string;
  /** 1 좋음 / 2 보통 / 3 나쁨 / 4 매우나쁨 */
  pm25_grade: number;
  feels_like: number;
  rain_prob: number | null;
  sunset: string | null;
  /** 가장 가까운 실시간 도시데이터 지점. 없으면 null */
  hotspot: string | null;
  congest_now: CongestLevel | null;
  congest_forecast_at_visit: CongestLevel | null;
  age_mix_top: string | null;
  /**
   * 날씨 출처. 방문 시각이 3시간 이상 뒤면 기상청 단기예보가, 2시간 이내면
   * citydata 실황이 쓰인다. 미세먼지는 언제나 citydata다(단기예보에 대기질이 없다).
   *
   * `citydata_fcst`는 **기상청 키가 없거나 호출이 실패했을 때** 쓰는 두 번째
   * 예보다. citydata 스냅샷의 `FCST24HOURS`라 추가 호출이 없다. 값의 의미는
   * `kma`와 같다(강수는 확률이다).
   *
   * **`mock`인데 실서버라면 키가 없거나 적재가 안 된 것이다.** 화면에 그릴
   * 필요는 없지만 디버그 화면(`?debug=1`)에는 띄워 두면 원인 파악이 빨라진다.
   */
  weather_source: "citydata" | "citydata_fcst" | "kma" | "kma+citydata" | "mock" | null;
}

export interface RecommendRequest {
  user_id: string;
  purpose: Purpose;
  party_size: number;
  budget_band: number;
  location: Location;
  /** 방문 예정 시각. 실측이 아니라 이 시각의 예보로 판단한다 */
  visit_at: string;
}

/**
 * live_segment와 crowd는 **없을 수 있다.**
 * 해당 POI가 실시간 도시데이터 지점 반경 1km 밖이라는 뜻이며,
 * 이때 엔진은 두 항을 빼고 나머지 가중치를 재정규화한다.
 * UI에서 undefined를 0으로 렌더링하면 안 된다.
 */
export interface ScoreBreakdown {
  segment: number;
  purpose: number;
  taste: number;
  context: number;
  quality: number;
  distance: number;
  live_segment?: number;
  crowd?: number;
}

/** review_chunk.text에서 그대로 발췌한 문장. 생성문이 아니다 */
export interface Evidence {
  text: string;
  source: string;
}

export interface Recommendation {
  poi_id: string;
  name: string;
  category: string;
  lat: number;
  lng: number;
  /** 직선거리. 점수에는 zone 배율이 반영된다 */
  distance_m: number;
  score: number;
  score_breakdown: ScoreBreakdown;
  reason: string;
  evidence: Evidence[];
  /** 6~20위에서 무작위로 뽑은 탐색 슬롯. 인기 쏠림 방지용 */
  is_exploration: boolean;
  explain_mode: ExplainMode;
  /** TourAPI 제공 대표 이미지 (있는 경우) */
  image_url: string | null;
}

export interface RecommendResponse {
  context: Context;
  results: Recommendation[];
  /** 피드백 전송 시 이 값을 함께 보낸다 */
  log_id: number;
  /** 후보가 부족해 attr_confidence 기준을 완화한 경우 true */
  low_confidence: boolean;
  /** 후보 부족으로 검색 반경을 넓힌 경우 true */
  radius_expanded: boolean;
}

export interface FeedbackRequest {
  log_id: number;
  clicked?: string[];
  selected?: string | null;
  feedback?: number | null;
}

export interface PoiDetail {
  poi_id: string;
  name: string;
  category_l1: string | null;
  category_l2: string | null;
  lat: number;
  lng: number;
  dong: string | null;
  zone: "itaewon" | "yongsan_stn" | "huam" | "ichon" | "cheongpa" | null;
  business_hours: Record<string, unknown> | null;
  outdoor_exposure: number | null;
  group_capacity: number | null;
  noise_level: number | null;
  price_band: number | null;
  purpose_tags: Purpose[];
  atmosphere_tags: Atmosphere[];
  quality_score: number | null;
  mention_count: number;
  attr_confidence: number;
  /** 광고 판정되지 않은 청크 우선 */
  reviews: Evidence[];
  image_url: string | null;
}
