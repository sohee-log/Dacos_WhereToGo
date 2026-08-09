"""설명 문장 — 템플릿 폴백.

**LLM 없이도 서비스가 돈다**는 것이 무료 티어의 전제다 (ROLE_B §1.2).
W5에 LLM 설명 생성과 `explanation_cache`가 이 모듈에 붙지만, 그전에도
추천 결과에는 이유가 붙어야 한다. 그래서 템플릿이 먼저 있다.

문장은 **점수 성분에서만** 만든다. 리뷰 원문을 여기서 요약하지 않는다 —
그건 W5의 RAG 인용이 할 일이고, 온라인에서 리뷰를 읽는 것은 R3 위반이다.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

# 이 임계값들은 "말할 만한 근거인가"의 기준이다. 점수 계산에는 쓰이지 않는다.
STRONG_TERM = 0.8
WEAK_CROWD = 0.4
HEAVY_RAIN = 0.5
INDOOR_EXPOSURE = 0.3


def template_reason(
    poi: Mapping[str, Any],
    wx: Mapping[str, Any],
    purpose: str,
    terms: Mapping[str, float],
) -> str:
    """근거가 있는 항만 골라 문장으로 만든다. 근거가 없으면 지어내지 않는다."""
    outdoor = float(poi.get("outdoor_exposure", 0.0) or 0.0)
    parts: list[str] = []

    if float(wx.get("rain_prob", 0.0) or 0.0) > HEAVY_RAIN and outdoor < INDOOR_EXPOSURE:
        parts.append("비 예보가 있어 실내 공간 위주로 골랐습니다")
    if int(wx.get("pm25_grade", 1) or 1) >= 3 and outdoor < INDOOR_EXPOSURE:
        parts.append("미세먼지 나쁨 예보를 반영해 실내를 우선했습니다")
    if terms.get("segment_affinity", 0.0) > STRONG_TERM:
        parts.append("이 시간대에 또래 방문 비중이 높은 곳입니다")
    if terms.get("purpose_match", 0.0) > STRONG_TERM:
        parts.append(f"{purpose}에 적합하다는 후기가 많습니다")
    if terms.get("crowd_fit", 1.0) < WEAK_CROWD:
        parts.append("다만 방문 시각에 다소 붐빌 수 있습니다")

    if not parts:
        return "요청하신 조건에 가장 근접한 장소입니다."
    return ". ".join(parts) + "."
