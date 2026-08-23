"""추천 파이프라인 조립 — live 경로.

    ① retrieval  후보 200~500  ← retrieval.py
    ② scoring    상위 20       ← scoring.py (재정규화 포함)
    ③ RAG        최종 3~5      ← W5. 지금은 상위 4 + 탐색 슬롯 1로 자른다
    ④ logging    전량 기록     ← W4(B4-4)

목 경로(mock_data.build_recommendation)와 **같은 수식·같은 응답 형태**를 쓴다.
다른 것은 입력 출처뿐이다. 목이 픽스처를 읽는 자리에서 여기는 PostGIS를 읽는다.

컨텍스트 해석(`resolve_context`)은 `/api/context/now`와 공유한다. 배너에 뜨는
날씨와 점수에 쓰인 날씨가 다르면 "왜 이곳인가"의 설명이 무너지기 때문이다.

아직 임시인 것
  - explain_mode: 항상 "template". LLM은 W5다.
  - evidence: 비어 있다. 인용은 W5(B5-1) RAG가 채운다.
"""

from __future__ import annotations

import hashlib
import random
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.config import Settings
from app.constants import (
    EXPLORATION_RANK_RANGE,
    RESULT_MAX,
    TOP_N,
    dow_type,
    hour_band,
    party_band,
    segment_age_bands,
)
from app.mock_data import weather_profile_for
from app.schemas import (
    Context,
    Evidence,
    Recommendation,
    RecommendRequest,
    RecommendResponse,
    ScoreBreakdown,
)
from app.services import explain, kma, live_signals, logging_svc, rag, retrieval
from app.services.context_fit import DEFAULT_WEATHER_SENSITIVITY
from app.services.explain import template_reason
from app.services.live_signals import HotspotSignals
from app.services.scoring import build_terms, total_score
from app.timeutil import parse_visit_at

DEFAULT_SUNSET_HOUR = 19
DEFAULT_PM_GRADE = 2
RAIN_LABEL_THRESHOLD = 0.3


class LiveDataUnavailable(RuntimeError):
    """DB는 살아 있는데 추천할 POI가 없다. 대부분 A의 적재가 아직 안 된 상태다."""


@dataclass
class ResolvedContext:
    """배너용 Context와 스코어링용 wx를 **같은 소스에서** 만든다."""

    ctx: Context
    wx: dict[str, Any]
    signals: dict[str, HotspotSignals]
    nearest_code: str | None = None


# ============================================================================
# 컨텍스트 — citydata(실황) + 기상청(예보) 병합 (B3-3)
# ============================================================================


def _resolve_weather(
    settings: Settings,
    lat: float,
    lng: float,
    visit_at: datetime,
    near: HotspotSignals | None,
) -> tuple[dict[str, Any], str]:
    """방문 시각에 맞는 날씨와 그 출처.

    | 방문 시각 | 강수·기온 | 미세먼지 |
    |---|---|---|
    | 3시간 이상 뒤 | 기상청 단기예보 | citydata 실황 (예보에 대기질이 없다) |
    | 〃 (기상청 키 없음/실패) | **citydata `FCST24HOURS`** | 〃 |
    | 2시간 이내 | citydata 실황 | citydata 실황 |
    | 소스 없음 | 결정적 프로파일 (`mock`) | 〃 |

    기상청이 죽거나 키가 없으면 **먼저 citydata의 24시간 예보로 물러선다.**
    A가 15분마다 적재하는 스냅샷에 이미 들어 있어 추가 호출도, 키도 필요 없다.
    그것마저 없을 때에야 실황이다 — *"저녁에 갈 건데"* 에 지금 날씨로 답하는 것은
    마지막 수단이어야 한다. **예보가 없다고 추천이 멈추지는 않는다.**
    어느 쪽을 썼는지는 응답의 `weather_source`에 실린다.
    """
    live = dict(near.weather) if (near and near.weather) else None

    forecast = None
    source = "kma"
    if kma.should_use_forecast(visit_at):
        forecast = kma.fetch_forecast(
            settings.kma_service_key, lat, lng, visit_at
        )
        if not forecast and near and near.weather_at_visit:
            forecast = dict(near.weather_at_visit)
            source = "citydata_fcst"

    if forecast:
        wx = dict(forecast)
        # 대기질과 일몰은 예보에 없다. 실황에서 채운다.
        wx["pm25_grade"] = (live or {}).get("pm25_grade") or DEFAULT_PM_GRADE
        wx["sunset_hour"] = (live or {}).get("sunset_hour") or DEFAULT_SUNSET_HOUR
        wx["sunset"] = (live or {}).get("sunset")
        if source == "kma":
            return wx, ("kma+citydata" if live else "kma")
        return wx, source

    if live:
        return live, "citydata"

    # 소스가 하나도 없다 — W1부터 쓰던 결정적 프로파일. 가짜라는 것을 출처로 밝힌다.
    _, prof = weather_profile_for(visit_at, settings)
    return (
        {
            "rain_prob": prof["rain_prob"],
            "pm25_grade": prof["pm25_grade"],
            "feels_like": prof["feels_like"],
            "sunset_hour": DEFAULT_SUNSET_HOUR,
            "label": prof["label"],
        },
        "mock",
    )


def _weather_label(wx: dict[str, Any], source: str) -> str:
    """배너 문구. 예보는 확률을, 실황은 사실을 말한다."""
    rain = float(wx.get("rain_prob") or 0.0)
    label = str(wx.get("label") or "맑음")
    if source == "citydata" and rain >= 0.99:
        return "비"                       # 실황에 "비 100%"는 이상하다
    if rain >= RAIN_LABEL_THRESHOLD:
        return f"비 {int(round(rain * 100))}%"
    return label


def resolve_context(
    executor: retrieval.Executor,
    settings: Settings,
    lat: float,
    lng: float,
    visit_at: datetime,
) -> ResolvedContext:
    """`/api/recommend`와 `/api/context/now`가 함께 쓴다."""
    near_row = retrieval.fetch_nearest_hotspot(executor, lat, lng)
    snapshots = retrieval.fetch_hotspot_latest(executor)
    signals = live_signals.build_signal_map(snapshots, visit_at)

    near_code = near_row["code"] if near_row else None
    near = signals.get(near_code) if near_code else None

    wx, source = _resolve_weather(settings, lat, lng, visit_at, near)
    wx["visit_hour"] = visit_at.hour
    wx.setdefault("sunset_hour", DEFAULT_SUNSET_HOUR)

    ctx = Context(
        weather=_weather_label(wx, source),
        pm25_grade=int(wx.get("pm25_grade") or DEFAULT_PM_GRADE),
        feels_like=float(wx.get("feels_like", 20.0)),
        rain_prob=float(wx.get("rain_prob") or 0.0),
        sunset=wx.get("sunset") or f"{int(wx['sunset_hour']):02d}:00",
        hotspot=(near.name if near else (near_row["name"] if near_row else None)),
        congest_now=near.congest_now if near else None,
        congest_forecast_at_visit=near.congest_at_visit if near else None,
        age_mix_top=live_signals.age_mix_top(near.age_rates) if near else None,
        weather_source=source,
    )
    return ResolvedContext(ctx=ctx, wx=wx, signals=signals, nearest_code=near_code)


# ============================================================================
# 추천
# ============================================================================


def _fallback_log_id(req: RecommendRequest) -> int:
    """로그 INSERT가 실패했을 때만 쓰는 결정적 id.

    응답 계약상 `log_id`는 필수라 무언가는 넣어야 한다. 이 값으로 온 피드백은
    `POST /api/feedback`에서 404가 된다 — 그게 "그 추천은 기록되지 않았다"는
    정확한 신호다. 정상 경로에서는 이 함수가 호출되지 않는다.
    """
    key = f"{req.user_id}|{req.purpose.value}|{req.visit_at}|{req.party_size}"
    return int(hashlib.sha256(key.encode()).hexdigest()[:8], 16) % 900_000 + 100_000


def build_live_recommendation(
    req: RecommendRequest, settings: Settings, executor: retrieval.Executor
) -> RecommendResponse:
    started = time.perf_counter()
    visit_dt = parse_visit_at(req.visit_at)
    lat, lng = req.location.lat, req.location.lng

    resolved = resolve_context(executor, settings, lat, lng, visit_dt)
    wx = resolved.wx

    # --- ① 후보 생성 -------------------------------------------------------
    q = retrieval.RetrievalQuery(
        lat=lat,
        lng=lng,
        visit_at=visit_dt,
        party_size=req.party_size,
        budget_band=req.budget_band,
        rain_prob=float(wx.get("rain_prob") or 0.0),
        pm25_grade=int(wx.get("pm25_grade") or DEFAULT_PM_GRADE),
        user_id=req.user_id,          # 취향 유사도를 DB에서 계산하기 위한 키
        conf_min=settings.attr_confidence_min,
        conf_relaxed=settings.attr_confidence_relaxed,
    )
    found = retrieval.retrieve(executor, q)
    if not found.candidates:
        raise LiveDataUnavailable("poi 테이블에 후보가 없다 (A의 적재 대기)")

    # --- 사용자 · 세그먼트 --------------------------------------------------
    profile = retrieval.fetch_user_profile(executor, req.user_id) or {}
    gender = profile.get("gender")
    age_band = profile.get("age_band")
    # 온보딩 5번 문항. 없으면 중간값이며, 그러면 개인화 항 하나가 중립이 된다 (B3-4)
    sensitivity = profile.get("weather_sensitivity") or DEFAULT_WEATHER_SENSITIVITY
    user_zone = retrieval.fetch_user_zone(executor, lat, lng)

    segment_map: dict[tuple[str, str], float] = {}
    if gender and age_band:
        segment_map = retrieval.fetch_segment_affinity(
            executor,
            found.candidates,
            gender=gender,
            age_bands=segment_age_bands(age_band),
            dow_type=dow_type(visit_dt.weekday()),
            hour_band=hour_band(visit_dt.hour),
        )

    # --- ② 스코어링 --------------------------------------------------------
    scored: list[tuple[float, dict[str, Any], dict[str, float], float]] = []
    for poi in found.candidates:
        sig = resolved.signals.get(poi.get("hotspot_code")) if poi.get("hotspot_code") else None
        terms = build_terms(
            poi,
            purpose=req.purpose.value,
            wx=wx,
            affinity=segment_map.get(
                (poi.get("commercial_area_id"), poi.get("category_l2"))
            ),
            # 코사인은 DB가 계산했다(retrieval.CANDIDATE_SQL). None이면 관측 불가.
            taste_sim=poi.get("taste_sim"),
            user_age_band=age_band,
            weather_sensitivity=sensitivity,
            # 지점 밖 POI는 둘 다 None → live 항이 빠지고 재정규화된다 (§6.4)
            congest_lvl=sig.congest_for_scoring if sig else None,
            age_rates=sig.age_rates if sig else None,
        )
        straight = float(poi.get("dist_m") or 0.0)
        score, avail, dist_pen = total_score(
            terms, straight, user_zone, poi.get("zone"), wx.get("rain_prob") or 0.0
        )
        scored.append((score, poi, avail, dist_pen))

    # 동점일 때 순서가 흔들리면 같은 요청이 매번 다른 화면을 준다. poi_id로 고정한다.
    scored.sort(key=lambda x: (-x[0], x[1]["poi_id"]))
    scored = scored[:TOP_N]

    # --- ③ RAG — 상위 20개에만 (ROLE_B §6.8) ----------------------------------
    top20_ids = [poi["poi_id"] for _, poi, _, _ in scored]
    weather_state = rag.weather_state_of(wx)
    qvec = rag.fetch_query_vector(executor, req.purpose.value, weather_state, req.party_size)
    evidence = rag.fetch_evidence(executor, top20_ids, qvec)

    key = explain.cache_key(
        req.purpose.value, party_band(req.party_size), weather_state, user_zone, top20_ids
    )
    explanations, mode = explain.generate(
        settings,
        executor,
        key=key,
        ctx={
            "purpose": req.purpose.value,
            "party_size": req.party_size,
            "budget_band": req.budget_band,
            "visit_at": req.visit_at,
            "weather": resolved.ctx.weather,
            "feels_like": resolved.ctx.feels_like,
            "pm25_grade": resolved.ctx.pm25_grade,
            "hotspot": resolved.ctx.hotspot,
            "congest": resolved.ctx.congest_forecast_at_visit,
        },
        candidates=[poi for _, poi, _, _ in scored],
        evidence=evidence,
    )

    # --- 최종 3~5 + 탐색 슬롯 1 (ROLE_B §6.7) ---------------------------------
    by_id = {poi["poi_id"]: item for item in scored for poi in (item[1],)}
    chosen: list[tuple] = []
    reasons: dict[str, str] = {}
    quotes: dict[str, list[dict[str, str]]] = {}

    for exp in explanations[: RESULT_MAX - 1]:
        item = by_id.get(exp.poi_id)
        if item is None:
            continue
        chosen.append(item)
        reasons[exp.poi_id] = exp.reason
        quotes[exp.poi_id] = exp.evidence

    # LLM이 적게 골랐거나 폴백이면 점수 순으로 채운다. 빈 화면을 만들지 않는다.
    for item in scored:
        if len(chosen) >= RESULT_MAX - 1:
            break
        if item[1]["poi_id"] not in {c[1]["poi_id"] for c in chosen}:
            chosen.append(item)

    lo, hi = EXPLORATION_RANK_RANGE
    picked = {c[1]["poi_id"] for c in chosen}
    pool = [it for it in scored[lo - 1 : hi] if it[1]["poi_id"] not in picked]
    explore = None
    if pool:
        # 시드를 요청에서 만든다. 같은 요청이면 같은 탐색 결과여야 디버깅이 된다.
        rng = random.Random(f"{req.user_id}|{req.purpose.value}|{req.visit_at}|{len(pool)}")
        explore = pool[rng.randrange(len(pool))]

    results: list[Recommendation] = []
    for idx, item in enumerate([*chosen, *([explore] if explore else [])]):
        score, poi, avail, dist_pen = item
        poi_id = poi["poi_id"]
        # 인용은 LLM이 고른 것 → 없으면 RAG 1순위 청크. 어느 쪽이든 **원문 발췌**다.
        cited = quotes.get(poi_id) or [
            {"text": ch["text"], "source": ch.get("source") or "naver_blog"}
            for ch in (evidence.get(poi_id) or [])[:1]
        ]
        results.append(
            Recommendation(
                poi_id=poi_id,
                name=poi["name"],
                category=poi.get("category_l2") or poi.get("category_l1") or "기타",
                lat=float(poi["lat"]),
                lng=float(poi["lng"]),
                distance_m=int(round(float(poi.get("dist_m") or 0.0))),
                score=round(score, 4),
                score_breakdown=ScoreBreakdown(
                    segment=round(avail.get("segment_affinity", 0.0), 3),
                    purpose=round(avail.get("purpose_match", 0.0), 3),
                    taste=round(avail.get("taste_similarity", 0.0), 3),
                    context=round(avail.get("context_fit", 0.0), 3),
                    quality=round(avail.get("quality", 0.0), 3),
                    distance=round(dist_pen, 3),
                    # 관측 안 된 항은 None → 응답에서 키 자체가 빠진다 (§6.4)
                    live_segment=(
                        round(avail["live_segment_match"], 3)
                        if "live_segment_match" in avail
                        else None
                    ),
                    crowd=(round(avail["crowd_fit"], 3) if "crowd_fit" in avail else None),
                ),
                reason=reasons.get(poi_id)
                or template_reason(poi, wx, req.purpose.value, avail),
                evidence=[Evidence(**e) for e in cited],
                is_exploration=explore is not None and idx == len(chosen),
                # 탐색 슬롯은 LLM이 고른 곳이 아니다. 설명도 템플릿이다.
                explain_mode=(
                    "template" if (explore is not None and idx == len(chosen)) else mode
                ),
            )
        )

    # --- ④ 로깅 (B4-4) -----------------------------------------------------
    # 노출된 5건이 아니라 **상위 20건 전부**를 남긴다. 노출됐지만 선택되지 않은
    # 후보가 없으면 나중에 랭킹 모델을 학습할 수 없다.
    shown_ids = {r.poi_id for r in results}
    latency_ms = int((time.perf_counter() - started) * 1000)
    log_id = logging_svc.write_recommendation_log(
        executor,
        user_id=req.user_id,
        context=logging_svc.context_snapshot(
            {
                "purpose": req.purpose.value,
                "party_size": req.party_size,
                "budget_band": req.budget_band,
                "lat": lat,
                "lng": lng,
                "visit_at": req.visit_at,
            },
            wx,
            {
                "weather_source": resolved.ctx.weather_source,
                "hotspot": resolved.nearest_code,
                "user_zone": user_zone,
                "radius_m": found.radius_m,
                "low_confidence": found.low_confidence,
                "strategy": found.strategy,
            },
        ),
        candidates=logging_svc.build_candidate_rows(scored, shown_ids),
        explain_mode=mode,
        latency_ms=latency_ms,
    )

    return RecommendResponse(
        context=resolved.ctx,
        results=results,
        log_id=log_id if log_id is not None else _fallback_log_id(req),
        low_confidence=found.low_confidence,
        radius_expanded=found.radius_expanded,
    )
