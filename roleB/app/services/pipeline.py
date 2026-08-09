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
  - log_id: 아직 로그 행을 쓰지 않는다. W4(B4-4)에서 실제 INSERT로 바뀐다.
  - explain_mode: 항상 "template". LLM은 W5다.
  - evidence: 비어 있다. 인용은 W5(B5-1) RAG가 채운다.
"""

from __future__ import annotations

import hashlib
import random
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
    segment_age_bands,
)
from app.mock_data import weather_profile_for
from app.schemas import (
    Context,
    Recommendation,
    RecommendRequest,
    RecommendResponse,
    ScoreBreakdown,
)
from app.services import kma, live_signals, retrieval
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
    | 2시간 이내 | citydata 실황 | citydata 실황 |
    | 소스 없음 | 결정적 프로파일 (`mock`) | 〃 |

    기상청이 죽거나 키가 없으면 조용히 실황으로 물러선다. **예보가 없다고
    추천이 멈추지는 않는다.** 대신 출처를 응답에 실어 원인이 보이게 한다.
    """
    live = dict(near.weather) if (near and near.weather) else None

    forecast = None
    if kma.should_use_forecast(visit_at):
        forecast = kma.fetch_forecast(
            settings.kma_service_key, lat, lng, visit_at
        )

    if forecast:
        wx = dict(forecast)
        # 대기질과 일몰은 예보에 없다. 실황에서 채운다.
        wx["pm25_grade"] = (live or {}).get("pm25_grade") or DEFAULT_PM_GRADE
        wx["sunset_hour"] = (live or {}).get("sunset_hour") or DEFAULT_SUNSET_HOUR
        wx["sunset"] = (live or {}).get("sunset")
        return wx, ("kma+citydata" if live else "kma")

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


def _log_id(req: RecommendRequest) -> int:
    """결정적 임시 id. **아직 recommendation_log에 행이 없다** (W4 B4-4에서 대체)."""
    key = f"{req.user_id}|{req.purpose.value}|{req.visit_at}|{req.party_size}"
    return int(hashlib.sha256(key.encode()).hexdigest()[:8], 16) % 900_000 + 100_000


def build_live_recommendation(
    req: RecommendRequest, settings: Settings, executor: retrieval.Executor
) -> RecommendResponse:
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
            user_vector=None,          # 온보딩 임베딩은 W4(B4-5)
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

    # --- ③ 상위 4 + 탐색 슬롯 1 (ROLE_B §6.7) --------------------------------
    top = scored[: RESULT_MAX - 1]
    lo, hi = EXPLORATION_RANK_RANGE
    pool = scored[lo - 1 : hi]
    explore = None
    if pool:
        # 시드를 요청에서 만든다. 같은 요청이면 같은 탐색 결과여야 디버깅이 된다.
        rng = random.Random(f"{req.user_id}|{req.purpose.value}|{req.visit_at}|{len(pool)}")
        explore = pool[rng.randrange(len(pool))]

    results: list[Recommendation] = []
    for idx, item in enumerate([*top, *([explore] if explore else [])]):
        score, poi, avail, dist_pen = item
        results.append(
            Recommendation(
                poi_id=poi["poi_id"],
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
                reason=template_reason(poi, wx, req.purpose.value, avail),
                evidence=[],           # 인용은 W5(B5-1) RAG가 채운다
                is_exploration=explore is not None and idx == len(top),
                explain_mode="template",
            )
        )

    return RecommendResponse(
        context=resolved.ctx,
        results=results,
        log_id=_log_id(req),
        low_confidence=found.low_confidence,
        radius_expanded=found.radius_expanded,
    )
