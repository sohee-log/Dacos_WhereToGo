"""추천 파이프라인 조립 — live 경로 (W2 게이트).

    ① retrieval  후보 200~500  ← retrieval.py
    ② scoring    상위 20       ← scoring.py (재정규화 포함)
    ③ RAG        최종 3~5      ← W5. 지금은 상위 4 + 탐색 슬롯 1로 자른다
    ④ logging    전량 기록     ← W4(B4-4)

목 경로(mock_data.build_recommendation)와 **같은 수식·같은 응답 형태**를 쓴다.
다른 것은 입력 출처뿐이다. 목이 픽스처를 읽는 자리에서 여기는 PostGIS를 읽는다.

아직 임시인 것 (숨기지 않고 표시해 둔다)
  - 날씨: `mock_data.weather_profile_for` 의 결정적 프로파일. W3(B3-3)에서
    citydata + 기상청 병합으로 교체된다.
  - 혼잡도: `hotspot_latest.congest_lvl`(실황). W3에서 `fcst` 기반
    **방문 예정 시각 예측**으로 바뀐다.
  - log_id: 아직 로그 행을 쓰지 않는다. W4(B4-4)에서 실제 INSERT로 바뀐다.
  - explain_mode: 항상 "template". LLM은 W5다.
"""

from __future__ import annotations

import hashlib
import random
from collections.abc import Mapping
from typing import Any

from app.config import Settings
from app.constants import (
    CONGEST_LEVELS,
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
    Evidence,
    Recommendation,
    RecommendRequest,
    RecommendResponse,
    ScoreBreakdown,
)
from app.services import retrieval
from app.services.explain import template_reason
from app.services.scoring import build_terms, total_score
from app.timeutil import parse_visit_at

DEFAULT_WEATHER_SENSITIVITY = 2
DEFAULT_SUNSET_HOUR = 19


class LiveDataUnavailable(RuntimeError):
    """DB는 살아 있는데 추천할 POI가 없다. 대부분 A의 적재가 아직 안 된 상태다."""


def _age_mix_top(age_rates: Mapping[str, Any] | None) -> str | None:
    """{"20": 31.2, ...} → "20대 31%". 값이 없으면 문구를 지어내지 않는다."""
    if not age_rates:
        return None
    try:
        band, rate = max(
            ((k, float(v)) for k, v in age_rates.items()), key=lambda kv: kv[1]
        )
    except (TypeError, ValueError):
        return None
    pct = rate if rate > 1.0 else rate * 100.0
    return f"{band}대 {pct:.0f}%"


def _safe_congest(value: Any) -> str | None:
    """고정 어휘 밖의 값이 오면 버린다. 응답 enum이 깨지는 것보다 낫다."""
    return value if value in CONGEST_LEVELS else None


def _log_id(req: RecommendRequest) -> int:
    """결정적 임시 id. **아직 recommendation_log에 행이 없다** (W4 B4-4에서 대체)."""
    key = f"{req.user_id}|{req.purpose.value}|{req.visit_at}|{req.party_size}"
    return int(hashlib.sha256(key.encode()).hexdigest()[:8], 16) % 900_000 + 100_000


def build_live_recommendation(
    req: RecommendRequest, settings: Settings, executor: retrieval.Executor
) -> RecommendResponse:
    visit_dt = parse_visit_at(req.visit_at)
    lat, lng = req.location.lat, req.location.lng

    # --- 컨텍스트 ----------------------------------------------------------
    _, prof = weather_profile_for(visit_dt, settings)
    near = retrieval.fetch_nearest_hotspot(executor, lat, lng)
    snapshots = retrieval.fetch_hotspot_latest(executor)
    near_snap = snapshots.get(near["code"]) if near else None

    congest_now = _safe_congest(near_snap.get("congest_lvl")) if near_snap else None
    wx: dict[str, Any] = {
        "rain_prob": prof["rain_prob"],
        "pm25_grade": prof["pm25_grade"],
        "feels_like": prof["feels_like"],
        "visit_hour": visit_dt.hour,
        "sunset_hour": DEFAULT_SUNSET_HOUR,
    }
    ctx = Context(
        weather=(
            f"비 {int(prof['rain_prob'] * 100)}%"
            if prof["rain_prob"] >= 0.6
            else prof["label"]
        ),
        pm25_grade=prof["pm25_grade"],
        feels_like=prof["feels_like"],
        rain_prob=prof["rain_prob"],
        sunset=f"{DEFAULT_SUNSET_HOUR}:42",
        hotspot=near["name"] if near else None,
        congest_now=congest_now,
        # W3까지는 실황을 예측 자리에 그대로 넣는다. 예측으로 바뀌면 값이 갈린다.
        congest_forecast_at_visit=congest_now,
        age_mix_top=_age_mix_top(near_snap.get("age_rates")) if near_snap else None,
    )

    # --- ① 후보 생성 -------------------------------------------------------
    q = retrieval.RetrievalQuery(
        lat=lat,
        lng=lng,
        visit_at=visit_dt,
        party_size=req.party_size,
        budget_band=req.budget_band,
        rain_prob=float(prof["rain_prob"]),
        pm25_grade=int(prof["pm25_grade"]),
    )
    found = retrieval.retrieve(executor, q)
    if not found.candidates:
        raise LiveDataUnavailable("poi 테이블에 후보가 없다 (A의 적재 대기)")

    # --- 사용자 · 세그먼트 --------------------------------------------------
    profile = retrieval.fetch_user_profile(executor, req.user_id) or {}
    gender = profile.get("gender")
    age_band = profile.get("age_band")
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
        hotspot_snap = snapshots.get(poi.get("hotspot_code")) if poi.get("hotspot_code") else None
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
            hotspot=hotspot_snap,
        )
        straight = float(poi.get("dist_m") or 0.0)
        score, avail, dist_pen = total_score(
            terms, straight, user_zone, poi.get("zone"), wx["rain_prob"]
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
        context=ctx,
        results=results,
        log_id=_log_id(req),
        low_confidence=found.low_confidence,
        radius_expanded=found.radius_expanded,
    )
