// app/recommend/page.tsx
'use client';

import { useEffect, useState, useCallback, Suspense } from 'react';
import { useSearchParams } from 'next/navigation';
import ContextBanner from '@/components/ContextBanner';
import ResultCard from '@/components/ResultCard';
import KakaoMap from '@/components/KakaoMap';
import RequestForm from '@/components/RequestForm';
import ScoreDebug from '@/components/ScoreDebug';
import { Purpose, RecommendRequest, RecommendResponse } from '@/lib/types';
import { PURPOSES } from '@/lib/constants';
import { postRecommend, ApiError } from '@/lib/api';
import { loadUserId } from '@/lib/session';

const DEFAULT_LOCATION = { lat: 37.5340, lng: 126.9946 }; // 이태원 인근 폴백

// visit_at 기본값 = 현재 + 1시간 (ROLE_C §C3-1)
function defaultVisitAt(): string {
  const d = new Date(Date.now() + 60 * 60 * 1000);
  return d.toISOString();
}

// 온보딩에서 넘어온 mood(분위기+목적 태그, 쉼표 구분)에서 실제 Purpose 값을 골라낸다.
// ⚠️ 예전엔 이 값을 아예 안 읽고 무조건 '데이트'로 고정했었다 — 그래서 온보딩에서
// 뭘 고르든 첫 추천은 항상 "데이트용 2인" 조건으로 나갔다. purpose_tags는 온보딩에서
// 다중 선택이 가능하므로, 그중 PURPOSES에 실제로 속하는 첫 값을 초기 occasion으로 쓴다.
function pickInitialPurpose(mood: string | null): Purpose {
  if (!mood) return '데이트';
  const tags = mood.split(',');
  const matched = tags.find((t): t is Purpose => (PURPOSES as readonly string[]).includes(t));
  return matched ?? '데이트';
}

function RecommendContent() {
  const searchParams = useSearchParams();
  // URL이 있으면 URL 우선, 없으면 로컬 저장값 (TODO_FOR_C §C-4)
  const userId = searchParams.get('user_id') ?? loadUserId();
  const debug = searchParams.get('debug') === '1'; // C4-4: ?debug=1 로만 노출

  const [data, setData] = useState<RecommendResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  // 503(DB 미연결/콜드스타트)과 429(레이트리밋)는 일반 에러와 다르게 취급한다 (핸드오프 §2)
  const [errorKind, setErrorKind] = useState<'none' | 'retryable' | 'rate_limited' | 'fatal'>('none');
  const [retryAfterSec, setRetryAfterSec] = useState<number | null>(null);

  // ── 요청 폼 상태 ──
  // purpose 초기값은 온보딩에서 고른 mood(=atmosphere+purpose 태그)에서 뽑는다.
  // party_size/budget_band/visit_at/location은 "이번 방문"에 특화된 값이라
  // 온보딩(프로필)이 아니라 여기(occasion)에서 매번 새로 받는 게 설계 의도다 —
  // 다만 party_size는 첫 요청부터 기본값(2)으로 조용히 나가니, 인원이 다른
  // 사람은 첫 결과가 부정확할 수 있다는 점은 감안할 것 (개선 여지 있음).
  const [purpose, setPurpose] = useState<Purpose>(() =>
    pickInitialPurpose(searchParams.get('mood'))
  );
  // /onboarding/party에서 넘어온 값이 있으면 그걸 쓰고, 없으면(직접 URL 진입 등) 2로 폴백
  const [partySize, setPartySize] = useState<number>(() => {
    const fromUrl = Number(searchParams.get('party_size'));
    return Number.isFinite(fromUrl) && fromUrl > 0 ? fromUrl : 2;
  });
  const [budgetBand, setBudgetBand] = useState<number>(2);
  const [visitAt, setVisitAt] = useState<string>(defaultVisitAt());
  const [location, setLocation] = useState(DEFAULT_LOCATION);
  // GPS 시도가 끝났는지(성공/실패 무관) — 화면에 "위치 확인 중" 표시용으로만 쓴다.
  const [locatingGps, setLocatingGps] = useState(false);

  // 용산구 대략 경계 (평가 시나리오 좌표 범위 기준: 이태원~청파~이촌~후암).
  // 서비스가 용산구 전용이라, 이 밖의 좌표는 실제 GPS라도 신뢰하지 않는다.
  const isWithinYongsan = (lat: number, lng: number) =>
    lat >= 37.51 && lat <= 37.56 && lng >= 126.95 && lng <= 127.02;

  // GPS를 한 번 시도해서 좌표를 Promise로 반환한다. 성공/실패/타임아웃/미지원
  // 어느 경우든 항상 값을 resolve한다(reject 안 함) — 폴백은 항상 DEFAULT_LOCATION.
  //
  // ⚠️ 예전엔 마운트 시점에 딱 한 번만 시도했다. 그 한 번이 실내 등에서
  // 타임아웃(3초)으로 실패하면, 그 세션 내내 "재검색"을 눌러도 다시 시도를
  // 안 해서 이태원에 영구적으로 갇혔다. 이제는 fetchRecommend를 부를 때마다
  // (첫 진입이든 재검색이든) 매번 새로 시도한다. 타임아웃도 8초로 늘렸다.
  const resolveLocation = useCallback((): Promise<{ lat: number; lng: number }> => {
    return new Promise((resolve) => {
      if (!navigator.geolocation) {
        resolve(DEFAULT_LOCATION);
        return;
      }
      setLocatingGps(true);
      navigator.geolocation.getCurrentPosition(
        (pos) => {
          setLocatingGps(false);
          const { latitude, longitude } = pos.coords;
          resolve(
            isWithinYongsan(latitude, longitude)
              ? { lat: latitude, lng: longitude }
              : DEFAULT_LOCATION // 용산구 밖이면 무시
          );
        },
        () => {
          setLocatingGps(false);
          resolve(DEFAULT_LOCATION); // 거부/실패 — 이번 요청만 폴백, 다음 시도는 다시 함
        },
        { timeout: 8000, enableHighAccuracy: false, maximumAge: 60000 }
      );
    });
  }, []);

  const fetchRecommend = useCallback(async () => {
    if (!userId) {
      setErrorMessage('유저 ID가 유효하지 않습니다. 온보딩을 다시 진행해주세요.');
      setErrorKind('fatal');
      setLoading(false);
      return;
    }

    setLoading(true);
    setErrorMessage(null);
    setErrorKind('none');

    // 호출될 때마다(재검색 포함) GPS를 새로 시도 — state가 아니라 이 값을 바로 요청에 쓴다.
    const resolvedLocation = await resolveLocation();
    setLocation(resolvedLocation);

    const budgetBandClamped = Math.min(Math.max(budgetBand, 1), 4) as 1 | 2 | 3 | 4;

    const requestBody: RecommendRequest = {
      user_id: userId,
      purpose,
      party_size: partySize,
      budget_band: budgetBandClamped,
      location: resolvedLocation,
      visit_at: visitAt,
    };

    try {
      const resData = await postRecommend(requestBody);
      setData(resData);
    } catch (err) {
      console.error(err);
      if (err instanceof ApiError) {
        if (err.status === 503) {
          // 목 응답으로 대신하지 않는다 — 재시도 버튼을 보여준다 (핸드오프 §2-1)
          setErrorKind('retryable');
          setErrorMessage('추천 데이터를 아직 사용할 수 없어요. 서버가 준비 중일 수 있습니다.');
        } else if (err.status === 429) {
          setErrorKind('rate_limited');
          setRetryAfterSec(err.retryAfter ?? 60);
          setErrorMessage('요청이 너무 잦습니다. 잠시 후 다시 시도해 주세요.');
        } else {
          setErrorKind('fatal');
          setErrorMessage(err.message);
        }
      } else {
        setErrorKind('fatal');
        setErrorMessage('추천 데이터를 가져오는데 실패했습니다.');
      }
    } finally {
      setLoading(false);
    }
    // resolveLocation을 fetchRecommend 안에서 매번 새로 부르므로 location을
    // 의존성에 넣을 필요가 없다 (넣으면 오히려 무한루프 위험).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [userId, purpose, partySize, budgetBand, visitAt, resolveLocation]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- 최초 데이터 로드 패턴
    fetchRecommend();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [userId]);

  // 429 카운트다운 — 다시 누를 수 있는 시점을 보여준다 (디바운스)
  useEffect(() => {
    if (errorKind !== 'rate_limited' || retryAfterSec === null) return;
    if (retryAfterSec <= 0) return;
    const t = setTimeout(() => setRetryAfterSec((s) => (s !== null ? s - 1 : s)), 1000);
    return () => clearTimeout(t);
  }, [errorKind, retryAfterSec]);

  // [C4-5] 콜드스타트 및 로딩 안내 UX
  if (loading) {
    return (
      <div className="min-h-screen bg-slate-50 flex flex-col items-center justify-center p-6 text-slate-900">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600 mb-4"></div>
        <p className="font-semibold text-sm">용산의 실시간 날씨와 핫플 분석 중... 🧭</p>
        <p className="text-xs text-slate-400 mt-1">
          {locatingGps ? '내 위치를 확인하는 중이에요...' : '서버를 깨우고 있으니 잠시만 기다려주세요.'}
        </p>
      </div>
    );
  }

  // 503 / 429 — 재시도 UI (무한 스피너·빈 화면 금지)
  if (errorKind === 'retryable' || errorKind === 'rate_limited') {
    const canRetry = errorKind === 'retryable' || (retryAfterSec ?? 0) <= 0;
    return (
      <div className="min-h-screen bg-slate-50 flex flex-col items-center justify-center p-6 text-slate-900 text-center">
        <p className="text-amber-500 font-bold mb-2">⏳ 잠시만요</p>
        <p className="text-sm text-slate-500 mb-4">{errorMessage}</p>
        {errorKind === 'rate_limited' && !canRetry && (
          <p className="text-xs text-slate-400 mb-4">{retryAfterSec}초 후 다시 시도할 수 있어요</p>
        )}
        <button
          onClick={fetchRecommend}
          disabled={!canRetry}
          className="bg-slate-900 disabled:bg-slate-300 text-white text-xs px-4 py-2 rounded-xl font-bold"
        >
          다시 시도하기
        </button>
      </div>
    );
  }

  // 그 외 치명적 에러
  if (errorKind === 'fatal' || !data) {
    return (
      <div className="min-h-screen bg-slate-50 flex flex-col items-center justify-center p-6 text-slate-900">
        <p className="text-red-500 font-bold mb-2">⚠️ 에러 발생</p>
        <p className="text-sm text-slate-500 mb-4">{errorMessage || '데이터를 불러올 수 없습니다.'}</p>
        <button onClick={() => window.location.href = '/'} className="bg-slate-900 text-white text-xs px-4 py-2 rounded-xl font-bold">
          처음으로 가기
        </button>
      </div>
    );
  }

  // [C3-5] 빈 결과 상태 핸들링 (조건 완화 UI)
  const isEmpty = !data.results || data.results.length === 0;

  return (
    <main className="min-h-screen bg-slate-50 text-slate-900 pb-12">
      <div className="bg-white border-b border-slate-100 px-5 py-6 sticky top-0 z-50 shadow-sm backdrop-blur-md bg-white/90">
        <div className="max-w-xl mx-auto flex justify-between items-center">
          <div>
            <h1 className="text-xl font-black text-slate-950 flex items-center gap-1.5">
              WhereToGo 용산 🗺️
            </h1>
            <p className="text-[11px] text-slate-400 font-medium mt-0.5">분석 로그 ID: #{data.log_id}</p>
          </div>
          <button
            onClick={() => window.location.href = '/'}
            className="text-xs font-bold text-slate-500 bg-slate-100 hover:bg-slate-200 transition-colors px-3 py-2 rounded-xl"
          >
            다시 선택 🔄
          </button>
        </div>
      </div>

      <div className="max-w-xl mx-auto px-4 mt-6 space-y-6">
        <ContextBanner context={data.context} />

        {/* 실제로 폼 값이 요청에 반영되도록 연결 — 이전엔 렌더링조차 안 됐다 */}
        <RequestForm
          purpose={purpose}
          setPurpose={setPurpose}
          partySize={partySize}
          setPartySize={setPartySize}
          budgetBand={budgetBand}
          setBudgetBand={setBudgetBand}
          visitAt={visitAt}
          setVisitAt={setVisitAt}
          onSubmit={fetchRecommend}
        />

        {isEmpty ? (
          <div className="bg-white p-8 rounded-3xl border border-slate-100 shadow-sm space-y-6 w-full text-center">
            <div className="text-4xl">🔍😢</div>
            <div className="space-y-2">
              <h2 className="text-sm font-black text-slate-900">조건에 맞는 장소가 없습니다</h2>
              <p className="text-[11px] text-slate-400 leading-relaxed">
                현재 설정된 조건 내에서는 딱 맞는 용산 핫플을 찾지 못했습니다. 조건을 완화하여 재시도해 보세요.
              </p>
            </div>
            <div className="space-y-2 pt-2">
              <button
                onClick={() => setBudgetBand((b) => Math.min(b + 1, 4))}
                className="w-full bg-slate-900 hover:bg-slate-800 text-white text-xs font-bold py-3 rounded-xl transition-all shadow-sm"
              >
                💵 예산 기준 +1단계 완화해보기
              </button>
              <button
                onClick={fetchRecommend}
                className="w-full bg-blue-600 hover:bg-blue-700 text-white text-xs font-bold py-3 rounded-xl transition-all shadow-sm"
              >
                🔁 같은 조건으로 다시 찾기
              </button>
            </div>
          </div>
        ) : (
          <>
            <div className="rounded-3xl overflow-hidden shadow-sm border border-slate-100">
              <KakaoMap places={data.results} />
            </div>

            <div className="pt-2">
              <h2 className="text-md font-black text-slate-900 flex items-center gap-1.5">
                🔥 당신의 성향을 저격할 맞춤 플레이스
              </h2>
              <p className="text-xs text-slate-400 mt-0.5">AI가 리뷰를 기반으로 선별한 공간입니다.</p>
            </div>

            <div className="space-y-4">
              {data.results.map((place) => (
                <div key={place.poi_id}>
                  <ResultCard place={place} logId={data.log_id} />
                  {/* [C4-4] score_breakdown 시각화 — ?debug=1 에서만 노출 */}
                  {debug && (
                    <ScoreDebug
                      scoreBreakdown={place.score_breakdown}
                      score={place.score}
                      explainMode={place.explain_mode}
                    />
                  )}
                </div>
              ))}
            </div>
          </>
        )}
      </div>
    </main>
  );
}

export default function RecommendPage() {
  return (
    <Suspense fallback={<div className="p-6 text-center text-xs">페이지 로딩 중...</div>}>
      <RecommendContent />
    </Suspense>
  );
}
