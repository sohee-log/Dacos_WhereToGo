"""실시간 도시데이터 소비 (B3-2).

**B는 citydata API를 부르지 않는다.** A가 15분마다 폴링해 `hotspot_snapshot`에
적재한 것을 읽는다. 요청마다 API를 부르면 하루 쿼터가 몇 시간 만에 마른다
(ROLE_B §6.5 · PLAN §3.3.4).

이 모듈이 하는 일은 **JSONB 해석**이다. 원본은 서울시 실시간 도시데이터
매뉴얼 V8.5의 응답 형태 그대로 들어오고, 필드명이 대문자에 값이 문자열이다.
숫자처럼 생겼지만 `"-"`, `""`, `"1.5mm"` 같은 값이 섞여 온다.
**하나라도 파싱에 실패했다고 추천이 멈추면 안 된다.** 전부 None-안전하게 읽는다.

없을 때의 규칙은 W2와 같다 — **0이 아니라 None이다.**
지점 반경 밖 POI에 혼잡도 0을 주면 §6.4 재정규화가 무의미해진다.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from app.constants import CONGEST_LEVELS
from app.timeutil import KST

# 스냅샷이 이보다 오래되면 "실시간"이라고 부르지 않는다.
# 폴링 주기 15분의 두 배 + 여유. A의 배치가 죽은 것을 여기서 알 수 있다.
SNAPSHOT_STALE_AFTER = timedelta(minutes=40)

# FCST_PPLTN은 2시간 간격이다. 방문 시각이 이보다 멀면 예측을 쓰지 않는다.
FORECAST_MATCH_TOLERANCE = timedelta(minutes=90)

# 환경부 PM2.5 등급 경계 (㎍/㎥). WHO 기준이 아니다 — 사용자가 뉴스에서 보는 등급과
# 같아야 "미세먼지 나쁨이라 실내로 골랐습니다"가 납득된다.
PM25_GRADE_BOUNDS = (15, 35, 75)
PM10_GRADE_BOUNDS = (30, 80, 150)

_AIR_IDX_TO_GRADE = {"좋음": 1, "보통": 2, "나쁨": 3, "매우나쁨": 4}
_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")


# ============================================================================
# 값 해석 — citydata는 전부 문자열로 온다
# ============================================================================


def as_float(value: Any) -> float | None:
    """`"27.4"`, `"1.5mm"`, `"-"`, `""`, None 을 모두 받아 float 또는 None."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    m = _NUMBER.search(str(value))
    return float(m.group()) if m else None


def pm_grade(value: Any, bounds: Sequence[int] = PM25_GRADE_BOUNDS) -> int | None:
    """농도 → 1~4 등급. 값이 없으면 None (2 '보통'으로 채우지 않는다)."""
    v = as_float(value)
    if v is None or v < 0:
        return None
    for i, b in enumerate(bounds, start=1):
        if v <= b:
            return i
    return 4


def sunset_hour(value: Any, default: int = 19) -> int:
    """`"19:42"` → 19. 형식이 깨지면 기본값."""
    if not value:
        return default
    m = re.match(r"\s*(\d{1,2})", str(value))
    if not m:
        return default
    hour = int(m.group(1))
    return hour if 0 <= hour <= 23 else default


def parse_citydata_weather(weather: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """`hotspot_snapshot.weather`(WEATHER_STTS) → 스코어링이 쓰는 형태.

    ⚠️ **실황은 확률이 아니다.** citydata는 "지금 비가 오는가"를 주지 `POP`(강수확률)를
    주지 않는다. 그래서 `rain_prob`은 0 또는 1이다. 확률이 필요한 건 3시간 뒤
    방문이고, 그건 기상청 단기예보(kma.py)가 담당한다.
    """
    if not weather:
        return None

    def pick(*keys: str) -> Any:
        for k in keys:
            for cand in (k, k.lower(), k.upper()):
                if cand in weather:
                    return weather[cand]
        return None

    feels = as_float(pick("SENSIBLE_TEMP")) or as_float(pick("TEMP"))
    if feels is None:
        return None

    precpt_type = str(pick("PRECPT_TYPE") or "").strip()
    raining = bool(precpt_type) and precpt_type not in ("없음", "-", "0")
    # 일부 버전은 강수확률을 함께 준다. 있으면 그쪽이 정확하다.
    chance = as_float(pick("RAIN_CHANCE"))

    grade = pm_grade(pick("PM25"))
    if grade is None:
        grade = pm_grade(pick("PM10"), PM10_GRADE_BOUNDS)
    if grade is None:
        grade = _AIR_IDX_TO_GRADE.get(str(pick("AIR_IDX") or "").strip())

    return {
        "rain_prob": (chance / 100.0 if chance is not None else (1.0 if raining else 0.0)),
        "pm25_grade": grade or 2,
        "feels_like": feels,
        "sunset_hour": sunset_hour(pick("SUNSET")),
        # 점수에는 시(hour)만 쓰지만 배너에는 원문을 그대로 보여준다.
        # "19:00"과 "19:42"는 해질녘 야외를 고를 때 체감이 다르다.
        "sunset": (str(pick("SUNSET")).strip() or None) if pick("SUNSET") else None,
        "label": ("비" if raining else str(pick("SKY_STTS") or "맑음")),
        "precpt_type": precpt_type or "없음",
    }


# ============================================================================
# 혼잡도 — 실황이 아니라 방문 예정 시각의 예측을 쓴다
# ============================================================================


def _parse_fcst_time(value: Any) -> datetime | None:
    """`"2026-08-03 20:00"` 형태. 타임존이 없으면 KST로 본다."""
    if not value:
        return None
    text = str(value).strip().replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y%m%d%H%M"):
        try:
            dt = datetime.strptime(text[: len(fmt) + 2].strip(), fmt)
        except ValueError:
            continue
        return dt.replace(tzinfo=KST)
    return None


def _valid_level(value: Any) -> str | None:
    v = str(value).strip() if value is not None else ""
    return v if v in CONGEST_LEVELS else None


def forecast_congest_at(
    fcst: Sequence[Mapping[str, Any]] | None, visit_at: datetime
) -> str | None:
    """FCST_PPLTN(12시간 · 2시간 간격)에서 방문 시각에 가장 가까운 예측.

    예측 구간을 벗어난 방문 시각(12시간 뒤 등)이면 None이다.
    가까운 값을 억지로 늘려 쓰면 "밤 11시에 붐빔"처럼 틀린 근거가 화면에 뜬다.
    """
    if not fcst:
        return None

    best: tuple[timedelta, str] | None = None
    for item in fcst:
        if not isinstance(item, Mapping):
            continue
        when = _parse_fcst_time(
            item.get("FCST_TIME") or item.get("fcst_time") or item.get("time")
        )
        level = _valid_level(
            item.get("FCST_CONGEST_LVL") or item.get("fcst_congest_lvl") or item.get("level")
        )
        if when is None or level is None:
            continue
        gap = abs(when - visit_at)
        if best is None or gap < best[0]:
            best = (gap, level)

    if best is None or best[0] > FORECAST_MATCH_TOLERANCE:
        return None
    return best[1]


# ============================================================================
# 스냅샷 묶음
# ============================================================================


@dataclass(frozen=True)
class HotspotSignals:
    """지점 하나의 실시간 신호. 스코어링과 배너가 함께 쓴다."""

    code: str
    name: str | None = None
    observed_at: datetime | None = None
    congest_now: str | None = None
    congest_at_visit: str | None = None
    age_rates: Mapping[str, Any] | None = None
    weather: Mapping[str, Any] | None = None
    is_stale: bool = False

    @property
    def congest_for_scoring(self) -> str | None:
        """예측이 있으면 예측, 없으면 실황. 둘 다 없으면 None.

        사람은 지금이 아니라 **도착할 때**를 기준으로 결정한다(PLAN §3.3.3).
        그래서 예측이 우선이다.
        """
        return self.congest_at_visit or self.congest_now


def build_signals(
    snapshot: Mapping[str, Any] | None, visit_at: datetime, now: datetime | None = None
) -> HotspotSignals | None:
    """`hotspot_latest` 한 행 → HotspotSignals. 행이 없으면 None."""
    if not snapshot or not snapshot.get("hotspot_code"):
        return None

    observed = snapshot.get("observed_at")
    stale = False
    if isinstance(observed, datetime):
        reference = now or datetime.now(observed.tzinfo or KST)
        stale = (reference - observed) > SNAPSHOT_STALE_AFTER

    return HotspotSignals(
        code=snapshot["hotspot_code"],
        name=snapshot.get("hotspot_name"),
        observed_at=observed if isinstance(observed, datetime) else None,
        congest_now=_valid_level(snapshot.get("congest_lvl")),
        congest_at_visit=forecast_congest_at(snapshot.get("fcst"), visit_at),
        age_rates=snapshot.get("age_rates"),
        weather=parse_citydata_weather(snapshot.get("weather")),
        is_stale=stale,
    )


def build_signal_map(
    snapshots: Mapping[str, Mapping[str, Any]], visit_at: datetime
) -> dict[str, HotspotSignals]:
    """{code: HotspotSignals}. 스코어링이 POI의 hotspot_code로 바로 찾는다."""
    out: dict[str, HotspotSignals] = {}
    for code, row in snapshots.items():
        sig = build_signals(row, visit_at)
        if sig is not None:
            out[code] = sig
    return out


def age_mix_top(age_rates: Mapping[str, Any] | None) -> str | None:
    """{"20": 31.2, ...} → "20대 31%". 값이 없으면 문구를 지어내지 않는다."""
    if not age_rates:
        return None
    pairs = [(k, as_float(v)) for k, v in age_rates.items()]
    pairs = [(k, v) for k, v in pairs if v is not None]
    if not pairs:
        return None
    band, rate = max(pairs, key=lambda kv: kv[1])
    pct = rate if rate > 1.0 else rate * 100.0
    return f"{band}대 {pct:.0f}%"
