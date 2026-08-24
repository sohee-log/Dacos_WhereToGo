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
import { postRecommend, ApiError } from '@/lib/api';

const DEFAULT_LOCATION = { lat: 37.5340, lng: 126.9946 }; // 이태원 인근 폴백

// visit_at 기본값 = 현재 + 1시간 (ROLE_C §C3-1)
function defaultVisitAt(): string {
  const d = new Date(Date.now() + 60 * 60 * 1000);
  return d.toISOString();
}

function RecommendContent() {
  const searchParams = useSearchParams();
  const userId = searchParams.get('user_id');
  const debug = searchParams.get('debug') === '1'; // C4-4: ?debug=1 로만 노출

  const [data, setData] = useState<RecommendResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  // 503(DB 미연결/콜드스타트)과 429(레이트리밋)는 일반 에러와 다르게 취급한다 (핸드오프 §2)
  const [errorKind, setErrorKind] = useState<'none' | 'retryable' | 'rate_limited' | 'fatal'>('none');
  const [retryAfterSec, setRetryAfterSec] = useState<number | null>(null);

  // ── 요청 폼 상태 (지금까지는 하드코딩되어 RequestForm이 무용지물이었다) ──
  const [purpose, setPurpose] = useState<Purpose>('데이트');
  const [partySize, setPartySize] = useState<number>(2);
  const [budgetBand, setBudgetBand] = useState<number>(2);
  const [visitAt, setVisitAt] = useState<string>(defaultVisitAt());
  const [location, setLocation] = useState(DEFAULT_LOCATION);

  // 사용자 위치. 실패하면 조용히 폴백 좌표를 쓴다 (권한 거부가 흔함).
  useEffect(() => {
    if (!navigator.geolocation) return;
    navigator.geolocation.getCurrentPosition(
      (pos) => setLocation({ lat: pos.coords.latitude, lng: pos.coords.longitude }),
      () => {
        /* 폴백 좌표 유지 */
      },
      { timeout: 3000 }
    );
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

    const budgetBandClamped = Math.min(Math.max(budgetBand, 1), 4) as 1 | 2 | 3 | 4;

    const requestBody: RecommendRequest = {
      user_id: userId,
      purpose,
      party_size: partySize,
      budget_band: budgetBandClamped,
      location,
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
    // location은 useEffect에서 비동기로 갱신되므로 의도적으로 의존성에서 제외 —
    // 최초 1회 + 사용자가 폼을 다시 제출할 때만 재요청한다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [userId, purpose, partySize, budgetBand, visitAt]);

  useEffect(() => {
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
        <p className="text-xs text-slate-400 mt-1">서버를 깨우고 있으니 잠시만 기다려주세요.</p>
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
