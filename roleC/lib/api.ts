// lib/api.ts
// 백엔드(Render) 클라이언트. 모든 fetch는 이 파일을 거친다 — 컴포넌트에서 직접
// fetch()를 호출하지 않는다. (핸드오프 §9-2, §2)
import {
  OnboardingRequest,
  OnboardingResponse,
  RecommendRequest,
  RecommendResponse,
  FeedbackRequest,
  Context,
  PoiDetail,
  ApiError,
  ApiErrorBody,
} from "./types";

// NEXT_PUBLIC_API_BASE는 Vercel Production/Preview/Development 세 스코프
// 모두에 들어있어야 한다 (핸드오프 §1-3). 로컬 개발 시 fallback.
const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

/**
 * 공통 요청 헬퍼.
 * - 422/429/503/404 등 에러 상태코드는 ApiError로 던진다 (본문의 detail 포함)
 * - 429는 Retry-After 헤더를 초 단위로 파싱해 실어준다
 * - 목 응답은 X-Mock-Response 헤더로 판별 가능 (디버깅용, 반환값에 얹어준다)
 */
async function request<TResponse>(
  path: string,
  init?: RequestInit
): Promise<TResponse> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  });

  if (!res.ok) {
    let body: ApiErrorBody;
    try {
      body = await res.json();
    } catch {
      body = { detail: `요청 실패 (HTTP ${res.status})` };
    }

    const retryAfterHeader = res.headers.get("Retry-After");
    const retryAfter = retryAfterHeader ? Number(retryAfterHeader) : undefined;

    throw new ApiError(res.status, body, retryAfter);
  }

  // 204 No Content (피드백 성공)
  if (res.status === 204) {
    return undefined as unknown as TResponse;
  }

  return (await res.json()) as TResponse;
}

/**
 * GET /health — UptimeRobot과 동일한 핑.
 *
 * - `mode: "mock"` 이면 아직 목 데이터다 (`MOCK_MODE=false` 전).
 * - `db` 는 **목 모드에서도 실제 연결을 확인한 결과**다. 그래서 전환 전에
 *   DSN이 맞는지 알 수 있다. `db_reason` 에 왜 그 값인지가 들어 있다.
 *
 *   {"db": true,  "db_reason": "MOCK_MODE=true · DSN 연결 OK"}      → 전환 준비 완료
 *   {"db": false, "db_reason": "MOCK_MODE=true · DATABASE_URL 없음"} → 환경변수 미설정
 *   {"db": false, "db_reason": "... DSN 연결 실패: ..."}            → DSN이 틀렸다
 */
export async function checkHealth(): Promise<{
  status: string;
  db: boolean;
  db_reason: string | null;
  mode: "mock" | "live";
  version: string;
}> {
  return request("/health");
}

/**
 * POST /api/onboarding
 * 같은 답을 다시 내면 같은 user_id가 나오고 프로필이 갱신된다 — 재제출 안전.
 * 422가 나면 필드명이 openapi.yaml과 어긋난 것이니 이 함수보다 types.ts를 먼저 의심한다.
 */
export async function submitOnboarding(
  payload: OnboardingRequest
): Promise<OnboardingResponse> {
  return request("/api/onboarding", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

/**
 * GET /api/context/now — 배너용 날씨·대기질·혼잡도. 503이면 재시도 UI로 처리.
 *
 * ⚠️ `lat` · `lng`는 **필수 쿼리**다. 빼면 200이 아니라 422가 온다.
 * `visit_at`을 주면 그 시각의 예보로 답한다(생략하면 지금). "저녁에 갈 건데"를
 * 지금 날씨로 답하지 않으려면 추천 요청과 **같은 값**을 넘겨야 한다.
 */
export async function getContextNow(
  lat: number,
  lng: number,
  visitAt?: string
): Promise<Context> {
  const qs = new URLSearchParams({ lat: String(lat), lng: String(lng) });
  if (visitAt) qs.set("visit_at", visitAt);
  return request(`/api/context/now?${qs.toString()}`);
}

/**
 * POST /api/recommend — 메인 엔드포인트.
 * IP당 분당 10회 제한(429). 검색 조건이 바뀔 때마다 자동 재요청하는 UI라면
 * 호출부에서 반드시 디바운스할 것 — 여기서는 막지 않는다.
 */
export async function postRecommend(
  payload: RecommendRequest
): Promise<RecommendResponse> {
  return request("/api/recommend", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

/**
 * POST /api/feedback — 클릭·선택·만족도.
 *
 * ⚠️ `clicked`는 **클릭한 poi_id들의 배열**이고 `selected`는 **선택한 poi_id 문자열**이다.
 * boolean으로 보내면 422다 (2026-08-28까지 그렇게 보내고 있었고, 아래 catch가
 * 삼켜서 recommendation_log가 통째로 비어 있었다). 만족도 필드명은 `feedback`이다.
 *
 * 한 번에 다 보낼 필요는 없다 — 빈 값은 서버가 덮어쓰지 않는다.
 * 404("그 추천이 기록되지 않았다")는 사용자 흐름을 막지 않도록 여기서 삼킨다.
 * 호출부는 실패를 신경 쓸 필요 없이 fire-and-forget으로 쓰면 된다.
 */
export async function postFeedback(payload: FeedbackRequest): Promise<void> {
  try {
    await request<void>("/api/feedback", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) {
      // 무시: 피드백 한 건이 빠질 뿐 흐름은 막지 않는다 (핸드오프 §3-4)
      return;
    }
    // 422는 이쪽이 계약을 어긴 것이다. 호출부가 .catch()로 받아 넘기더라도
    // 콘솔에는 반드시 남긴다 — 이걸 안 남겨서 몇 주를 몰랐다.
    if (err instanceof ApiError && err.status === 422) {
      console.error("[계약 위반] POST /api/feedback 422 —", err.message, payload);
      return;
    }
    throw err;
  }
}

/**
 * GET /api/poi/{id} — 상세. reviews 최대 5건, 협찬 글은 뒤로 밀려서 온다.
 *
 * `outdoor_exposure` · `group_capacity` · `noise_level` · `price_band`의 **null은
 * "아직 모른다"**는 뜻이다(A3-2). 0이나 4로 그리면 없는 사실을 지어내는 것이 된다.
 */
export async function getPoi(poiId: string): Promise<PoiDetail> {
  return request(`/api/poi/${encodeURIComponent(poiId)}`);
}

export { ApiError };
