"""기상청 단기예보 클라이언트 (B3-3).

**왜 citydata만으로 안 되는가.** citydata의 날씨는 실황이다. "지금 비가 온다"는
알려주지만 "세 시간 뒤에 올 확률"은 주지 않는다. 이 서비스의 원칙은
*"실측값이 아니라 방문 예정 시각의 예보"* 다(PLAN §3.3.3). 저녁 약속을 지금
고르는 사람에게 지금 날씨로 답하면 추천의 전제가 무너진다.

| 방문 시각 | 소스 |
|---|---|
| 2시간 이내 | citydata `WEATHER_STTS` (실황) |
| 3시간 이상 뒤 | **여기** — 기상청 단기예보 `getVilageFcst` |
| 미세먼지 | 언제나 citydata 실황 — 기상청 단기예보에 대기질이 없다 |

의존성을 늘리지 않으려고 `urllib`(표준 라이브러리)를 쓴다. GET 한 번에
requests/httpx를 얹으면 Render Free의 콜드스타트만 길어진다.

⚠️ **키가 없으면 조용히 None을 반환한다.** 예보가 없다고 추천이 멈추면 안 된다.
호출부는 None일 때 citydata 실황으로 물러선다.
"""

from __future__ import annotations

import json
import logging
import math
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from typing import Any

from app.services.context_fit import apparent_temperature
from app.timeutil import KST

log = logging.getLogger("wheretogo.kma")

ENDPOINT = "https://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getVilageFcst"

# 이 시간 이상 뒤의 방문이면 실황 대신 예보를 쓴다.
FORECAST_LEAD = timedelta(hours=3)

# 발표 시각(정시). 실제 제공은 각 시각 + 10분 이후다.
BASE_TIMES = (2, 5, 8, 11, 14, 17, 20, 23)
BASE_PUBLISH_DELAY = timedelta(minutes=15)   # 여유를 두고 이전 회차를 쓴다

HTTP_TIMEOUT = 4.0            # 무료 티어에서 외부 API가 워커를 잡아먹지 않게
NUM_OF_ROWS = 300             # 카테고리 12종 × 시간대. 넉넉히 받아 로컬에서 고른다

_SKY = {1: "맑음", 3: "구름많음", 4: "흐림"}
_PTY = {0: "없음", 1: "비", 2: "비/눈", 3: "눈", 4: "소나기", 5: "빗방울", 6: "빗방울눈날림", 7: "눈날림"}

# (nx, ny, base_date, base_time) → 파싱 전 items. 발표 회차가 바뀌면 키가 바뀌므로
# TTL이 따로 필요 없다. 무료 티어에서 같은 회차를 반복 호출하지 않기 위한 것이다.
_CACHE: dict[tuple, list[dict[str, Any]]] = {}
_CACHE_MAX = 32


# ============================================================================
# 격자 변환 — 기상청은 위경도가 아니라 자체 격자(nx, ny)를 쓴다
# ============================================================================

# 기상청 표준 Lambert Conformal Conic 파라미터
_RE, _GRID = 6371.00877, 5.0
_SLAT1, _SLAT2, _OLON, _OLAT = 30.0, 60.0, 126.0, 38.0
_XO, _YO = 43, 136


def latlng_to_grid(lat: float, lng: float) -> tuple[int, int]:
    """위경도 → 기상청 격자. 서울시청(37.5665, 126.9780)은 (60, 127)이다."""
    degrad = math.pi / 180.0
    re = _RE / _GRID
    slat1, slat2 = _SLAT1 * degrad, _SLAT2 * degrad
    olon, olat = _OLON * degrad, _OLAT * degrad

    sn = math.tan(math.pi * 0.25 + slat2 * 0.5) / math.tan(math.pi * 0.25 + slat1 * 0.5)
    sn = math.log(math.cos(slat1) / math.cos(slat2)) / math.log(sn)
    sf = math.tan(math.pi * 0.25 + slat1 * 0.5)
    sf = sf**sn * math.cos(slat1) / sn
    ro = math.tan(math.pi * 0.25 + olat * 0.5)
    ro = re * sf / ro**sn

    ra = math.tan(math.pi * 0.25 + lat * degrad * 0.5)
    ra = re * sf / ra**sn
    theta = lng * degrad - olon
    if theta > math.pi:
        theta -= 2.0 * math.pi
    if theta < -math.pi:
        theta += 2.0 * math.pi
    theta *= sn

    nx = int(ra * math.sin(theta) + _XO + 0.5)
    ny = int(ro - ra * math.cos(theta) + _YO + 0.5)
    return nx, ny


def base_datetime(now: datetime) -> tuple[str, str]:
    """가장 최근에 **실제로 제공되는** 발표 회차 (base_date, base_time).

    02시 발표는 02:10쯤부터 조회된다. 정시에 바로 부르면 빈 응답이 온다.
    """
    ref = now.astimezone(KST) - BASE_PUBLISH_DELAY
    for hour in reversed(BASE_TIMES):
        if ref.hour >= hour:
            return ref.strftime("%Y%m%d"), f"{hour:02d}00"
    # 자정~02:15 사이 — 전날 23시 발표가 최신이다
    prev = ref - timedelta(days=1)
    return prev.strftime("%Y%m%d"), "2300"


# ============================================================================
# 파싱
# ============================================================================


def _target_slot(items: list[dict[str, Any]], target: datetime) -> tuple[str, str] | None:
    """예보 항목 중 방문 시각에 가장 가까운 (fcstDate, fcstTime)."""
    best: tuple[timedelta, tuple[str, str]] | None = None
    for it in items:
        d, t = it.get("fcstDate"), it.get("fcstTime")
        if not d or not t:
            continue
        try:
            when = datetime.strptime(f"{d}{t}", "%Y%m%d%H%M").replace(tzinfo=KST)
        except ValueError:
            continue
        gap = abs(when - target)
        if best is None or gap < best[0]:
            best = (gap, (d, t))
    return best[1] if best else None


def parse_forecast(items: list[dict[str, Any]], target: datetime) -> dict[str, Any] | None:
    """단기예보 items → 스코어링이 쓰는 형태. 방문 시각 슬롯만 골라 쓴다."""
    slot = _target_slot(items, target)
    if slot is None:
        return None

    by_cat: dict[str, str] = {
        it["category"]: it.get("fcstValue")
        for it in items
        if it.get("category") and (it.get("fcstDate"), it.get("fcstTime")) == slot
    }
    if not by_cat:
        return None

    def num(cat: str) -> float | None:
        try:
            return float(by_cat[cat])
        except (KeyError, TypeError, ValueError):
            return None

    temp = num("TMP")
    if temp is None:
        return None

    pop = num("POP")
    pty = int(num("PTY") or 0)
    sky = int(num("SKY") or 1)

    return {
        # 예보는 확률이다. 실황(0/1)과 다르다 — context_fit의 비 계수가 여기서 의미를 갖는다
        "rain_prob": (pop / 100.0) if pop is not None else (1.0 if pty else 0.0),
        "feels_like": apparent_temperature(temp, num("REH"), num("WSD")),
        "temp": temp,
        "label": _PTY.get(pty) if pty else _SKY.get(sky, "맑음"),
        "precpt_type": _PTY.get(pty, "없음"),
        "sunset_hour": None,        # 단기예보에는 일몰이 없다. citydata에서 가져온다
        "pm25_grade": None,         # 대기질도 없다. 위와 같다
        "fcst_slot": f"{slot[0]}{slot[1]}",
    }


# ============================================================================
# 호출
# ============================================================================


def _service_key_param(key: str) -> str:
    """포털은 Encoding/Decoding 두 형태의 키를 준다.

    이미 퍼센트 인코딩된 키를 다시 인코딩하면 `%2F`가 `%252F`가 되어 인증이 깨진다.
    이건 공공데이터포털 연동에서 가장 흔한 실패다.
    """
    return key if "%" in key else urllib.parse.quote(key, safe="")


def fetch_forecast(
    service_key: str | None,
    lat: float,
    lng: float,
    target: datetime,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    """방문 시각의 예보. 키가 없거나 호출이 실패하면 None."""
    if not service_key:
        return None

    nx, ny = latlng_to_grid(lat, lng)
    base_date, base_time = base_datetime(now or datetime.now(KST))
    cache_key = (nx, ny, base_date, base_time)

    items = _CACHE.get(cache_key)
    if items is None:
        items = _request(service_key, nx, ny, base_date, base_time)
        if items is None:
            return None
        if len(_CACHE) >= _CACHE_MAX:
            _CACHE.clear()          # 회차가 바뀌면 통째로 버려도 손해가 없다
        _CACHE[cache_key] = items

    return parse_forecast(items, target)


def _request(
    service_key: str, nx: int, ny: int, base_date: str, base_time: str
) -> list[dict[str, Any]] | None:
    query = urllib.parse.urlencode(
        {
            "pageNo": 1,
            "numOfRows": NUM_OF_ROWS,
            "dataType": "JSON",
            "base_date": base_date,
            "base_time": base_time,
            "nx": nx,
            "ny": ny,
        }
    )
    url = f"{ENDPOINT}?serviceKey={_service_key_param(service_key)}&{query}"

    try:
        with urllib.request.urlopen(url, timeout=HTTP_TIMEOUT) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
        # 예보가 없다고 추천이 멈추면 안 된다. 실황으로 물러선다.
        log.warning("기상청 호출 실패 (%s). citydata 실황으로 폴백한다", exc)
        return None

    return extract_items(payload)


def extract_items(payload: Any) -> list[dict[str, Any]] | None:
    """응답 봉투에서 items를 꺼낸다.

    공공데이터포털은 **에러도 HTTP 200**으로 준다. 키가 틀리면 XML 에러 문서가
    오기도 한다. resultCode를 보지 않으면 "예보가 비었다"로 오해하게 된다.
    """
    if not isinstance(payload, dict):
        return None
    response = payload.get("response") or {}
    header = response.get("header") or {}
    code = str(header.get("resultCode", ""))
    if code and code not in ("00", "0"):
        log.warning("기상청 응답 오류 %s: %s", code, header.get("resultMsg"))
        return None

    items = ((response.get("body") or {}).get("items") or {}).get("item")
    if isinstance(items, list):
        return items
    return None


def should_use_forecast(visit_at: datetime, now: datetime | None = None) -> bool:
    """방문이 충분히 멀면 예보를 쓴다. 가까우면 실황이 더 정확하다."""
    reference = now or datetime.now(KST)
    return (visit_at - reference) >= FORECAST_LEAD
