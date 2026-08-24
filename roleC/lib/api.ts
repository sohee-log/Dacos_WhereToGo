// lib/api.ts
// 백엔드(Render) 클라이언트. 모든 fetch는 이 파일을 거친다 — 컴포넌트에서 직접
// fetch()를 호출하지 않는다. (핸드오프 §9-2, §2)
import {
  OnboardingRequest,
  OnboardingResponse,
  RecommendRequest,
  RecommendResponse,
  FeedbackRequest,
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

/** GET /health — UptimeRobot과 동일한 핑. mode:"mock"이면 아직 목 모드다. */
export async function checkHealth(): Promise<{
  status: string;
  db: boolean;
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

/** GET /api/context/now — 배너용 날씨·대기질·혼잡도. 503이면 재시도 UI로 처리. */
export async function getContextNow(): Promise<
  RecommendResponse["context"]
> {
  return request("/api/context/now");
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
    throw err;
  }
}

/** GET /api/poi/{id} — 상세. reviews 최대 5건, 협찬 글은 뒤로 밀려서 온다. */
export async function getPoi(poiId: string): Promise<any> {
  return request(`/api/poi/${encodeURIComponent(poiId)}`);
}

export { ApiError };
