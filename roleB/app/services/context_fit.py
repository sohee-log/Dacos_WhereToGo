"""날씨 적합도 — 비선형 (B3-1).

**이 함수를 선형 가중합으로 바꾸면 이 서비스의 핵심이 사라진다.**

사람의 행동은 기온에 비례하지 않는다. 15~25도 사이에서 가장 활발하고 양쪽으로
꺾인다(U자형). 미세먼지는 농도 수치보다 "나쁨" 등급이 발표되는 순간에 꺾인다.
그래서 각 조건은 **야외 노출도(e)에 곱해지는 계수**로 들어간다. 실내(e=0)는
어떤 날씨에도 값이 변하지 않고, 완전 야외(e=1)만 온전히 영향을 받는다.

개인화 훅 (B3-4)
----------------
`weather_sensitivity`(온보딩 5번 문항, 1~3)가 비 계수를 스케일한다.
"비 오면 약속을 미루는 편"이라고 답한 사람은 같은 강수확률에서 야외를 더 깎는다.
이 문항이 죽으면 개인화 항 하나가 통째로 사라진다 (ROLE_C 부록 A).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.constants import (
    AFTER_SUNSET_COEF,
    COLD_FEELS_LIKE,
    CONTEXT_FIT_MAX,
    EXTREME_TEMP_COEF,
    HEAT_FEELS_LIKE,
    IS_CLEAR_RAIN_PROB,
    PLEASANT_BONUS,
    PLEASANT_RANGE,
    PM_BAD_GRADE,
    PM_COEF,
    RAIN_COEF,
    RAIN_TRIGGER,
    WEATHER_SENSITIVITY_RAIN_COEF,
)

DEFAULT_WEATHER_SENSITIVITY = 2


def context_fit(
    outdoor_exposure: float,
    wx: Mapping[str, Any],
    weather_sensitivity: int = DEFAULT_WEATHER_SENSITIVITY,
) -> float:
    """0.0 ~ 1.5. 1.0이 중립이고, 쾌적한 날의 야외만 1.0을 넘는다.

    wx 키: rain_prob / pm25_grade / feels_like / visit_hour / sunset_hour
    (없는 키는 중립값으로 본다 — 날씨를 모른다고 추천이 멈추면 안 된다)
    """
    s = 1.0
    e = float(outdoor_exposure or 0.0)
    rain_prob = float(wx.get("rain_prob", 0.0) or 0.0)
    pm25_grade = int(wx.get("pm25_grade", 1) or 1)
    feels_like = float(wx.get("feels_like", 20.0))
    visit_hour = int(wx.get("visit_hour", 12))
    sunset_hour = int(wx.get("sunset_hour", 19))

    rain_coef = WEATHER_SENSITIVITY_RAIN_COEF.get(
        weather_sensitivity, RAIN_COEF
    )

    if rain_prob > RAIN_TRIGGER:
        s *= 1 - rain_coef * e * min(rain_prob, 1.0)
    if pm25_grade >= PM_BAD_GRADE:
        s *= 1 - PM_COEF * e
    if feels_like > HEAT_FEELS_LIKE or feels_like < COLD_FEELS_LIKE:
        s *= 1 - EXTREME_TEMP_COEF * e
    if rain_prob < IS_CLEAR_RAIN_PROB and PLEASANT_RANGE[0] <= feels_like <= PLEASANT_RANGE[1]:
        s *= 1 + PLEASANT_BONUS * e          # 맑고 선선하면 야외가 오히려 유리하다
    if visit_hour >= sunset_hour:
        s *= 1 - AFTER_SUNSET_COEF * e

    return max(0.0, min(s, CONTEXT_FIT_MAX))


def apparent_temperature(
    temp_c: float, humidity_pct: float | None = None, wind_ms: float | None = None
) -> float:
    """체감온도 근사.

    citydata의 `SENSIBLE_TEMP`가 있으면 **그걸 쓴다.** 이 함수는 기상청 단기예보처럼
    체감온도를 주지 않는 소스를 위한 대체재다. `context_fit`의 임계값(31°/-5°)이
    기온이 아니라 체감 기준이라, 여기서 습도·바람을 무시하면 한여름 예보가
    폭염 임계를 넘지 못한다.

    - 27도 이상: 열지수(Rothfusz 근사)
    - 10도 이하 & 풍속 1.3m/s 이상: 풍속냉각(JAG/TI)
    - 그 사이: 기온 그대로
    """
    t = float(temp_c)

    if t >= 27.0 and humidity_pct is not None:
        r = float(humidity_pct)
        f = t * 9 / 5 + 32
        hi = (
            -42.379 + 2.04901523 * f + 10.14333127 * r
            - 0.22475541 * f * r - 6.83783e-3 * f * f
            - 5.481717e-2 * r * r + 1.22874e-3 * f * f * r
            + 8.5282e-4 * f * r * r - 1.99e-6 * f * f * r * r
        )
        return round((hi - 32) * 5 / 9, 1)

    if t <= 10.0 and wind_ms is not None and float(wind_ms) >= 1.3:
        v = (float(wind_ms) * 3.6) ** 0.16       # km/h 로 바꾼 뒤 지수 적용
        return round(13.12 + 0.6215 * t - 11.37 * v + 0.3965 * t * v, 1)

    return round(t, 1)
