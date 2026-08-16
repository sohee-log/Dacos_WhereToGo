"""목 경로가 실 경로와 같은 규칙을 쓰는가 (A의 W2 시드 기준).

목은 "대충 그럴듯한 값"을 주는 곳이 아니다. C가 목을 보고 만든 화면이
실서버에서 그대로 서야 한다. 그래서 **값이 없을 때의 규칙**이 양쪽에서 같아야
한다. 여기가 갈리면 통합하는 날 "목에서는 되던 게" 미묘하게 달라지는데,
에러가 아니라 순위만 바뀌기 때문에 아무도 못 찾는다.

A의 W2 시드(`seeds/poi_seed.json`)가 실제로 이 두 구멍을 드러냈다.
  · `quality_score`가 없다 (산출이 A4-4다) → 목이 0.6을 채우고 실서버는 0.5
  · `hotspot_code`가 전 건 NULL이다 (매핑이 A3-3이다) → live_* 키가 아예 안 생김
"""

from __future__ import annotations

from app.constants import NEUTRAL_TERM
from app.mock_data import (
    HOTSPOT_RADIUS_M,
    _coerce_seed_row,
    _terms_for,
    nearest_hotspot,
)

# 이태원 관광특구 지점 좌표 근처 / 충분히 먼 곳
IN_HOTSPOT = {"lat": 37.5348, "lng": 126.9984}
OUT_HOTSPOT = {"lat": 37.5170, "lng": 126.9700}

WX = {
    "state": "맑음",
    "rain_prob": 0.05,
    "pm25_grade": 1,
    "feels_like": 22.0,
    "sunset_hour": 19,
    "visit_hour": 19,
    "congest_at_visit": "보통",
}


def _seed_row(**kw) -> dict:
    """A의 W2 시드와 같은 모양. quality_score와 hotspot_code가 없다."""
    row = {
        "poi_id": "MA010120220807797676",
        "name": "볼레로",
        "category_l1": "음식",
        "category_l2": "요리 주점",
        "zone": "itaewon",
        "outdoor_exposure": 0.03,
        "group_capacity": 6,
        "price_band": 1,
        "purpose_tags": ["친구모임", "회식", "데이트"],
        "atmosphere_tags": ["이국적인"],
        "sentiment_score": 0.79,
        "attr_confidence": 0.41,
        "hotspot_code": None,
        **IN_HOTSPOT,
    }
    row.update(kw)
    return row


# ── quality_score ────────────────────────────────────────────────────────


def test_시드에_quality_score가_없으면_None으로_둔다():
    """임의의 상수를 채우지 않는다. 채우면 실서버와 값이 갈린다."""
    got = _coerce_seed_row(_seed_row())
    assert got is not None
    assert got["quality_score"] is None


def test_quality가_없을때_목도_실도_중립이다():
    poi = _coerce_seed_row(_seed_row())
    terms = _terms_for(poi, "데이트", WX)
    assert terms["quality"] == NEUTRAL_TERM


def test_시드에_quality_score가_있으면_그대로_쓴다():
    poi = _coerce_seed_row(_seed_row(quality_score=0.83))
    assert poi["quality_score"] == 0.83
    assert _terms_for(poi, "데이트", WX)["quality"] == 0.83


def test_sentiment_score를_quality로_대신_쓰지_않는다():
    """A의 산출 공식(A4-4)을 B가 흉내 내면 나중에 두 값이 어긋난다."""
    poi = _coerce_seed_row(_seed_row(sentiment_score=0.79))
    assert poi["quality_score"] is None


# ── hotspot ──────────────────────────────────────────────────────────────


def test_지점_반경_안에서_두_경우가_모두_나온다():
    """시드에 hotspot_code가 없어도 목에서는 지점 반경 규칙으로 붙인다.

    다만 반경 안을 **전부** 붙이면 지점 한복판 요청의 결과가 전건 '안'이 되어
    반대쪽 UI(키 없는 카드)를 확인할 수 없다. 한 응답에 두 경우가 같이
    나오는 것이 목의 목적이다.
    """
    pois = [_coerce_seed_row(_seed_row(poi_id=f"MA{i:018d}")) for i in range(40)]
    with_hs = [p for p in pois if p["hotspot"]]
    without = [p for p in pois if not p["hotspot"]]
    assert with_hs, "반경 안인데 지점이 하나도 안 붙었다"
    assert without, "반경 안이 전부 붙어서 키 없는 경우를 볼 수 없다"


def test_유도값은_결정적이다():
    """같은 시드를 다시 읽어도 화면이 바뀌면 안 된다 (목의 계약)."""
    row = _seed_row()
    assert _coerce_seed_row(row)["hotspot"] == _coerce_seed_row(row)["hotspot"]


def test_지점_반경_밖이면_붙이지_않는다():
    """반경 밖은 None이어야 한다. 0도 빈 문자열도 아니다."""
    poi = _coerce_seed_row(_seed_row(**OUT_HOTSPOT))
    assert poi["hotspot"] is None


def test_반경_밖이면_실시간_두_항이_None이다():
    poi = _coerce_seed_row(_seed_row(**OUT_HOTSPOT))
    terms = _terms_for(poi, "데이트", WX)
    assert terms["live_segment_match"] is None
    assert terms["crowd_fit"] is None


def test_반경_안이면_실시간_두_항이_값을_갖는다():
    poi = _coerce_seed_row(_seed_row())
    terms = _terms_for(poi, "데이트", WX)
    assert terms["live_segment_match"] is not None
    assert terms["crowd_fit"] is not None


def test_시드가_hotspot_code를_주면_그것을_쓴다():
    """A가 A3-3에서 채우면 유도값이 아니라 실제 코드가 이긴다."""
    poi = _coerce_seed_row(_seed_row(hotspot_code="POI001"))
    assert poi["hotspot"] == "POI001"


def test_유도_규칙은_목_컨텍스트와_같은_함수다():
    """POI에 붙은 지점과 응답 context.hotspot이 다른 규칙이면 화면이 모순된다."""
    poi = _coerce_seed_row(_seed_row())
    assert poi["hotspot"] == nearest_hotspot(IN_HOTSPOT["lat"], IN_HOTSPOT["lng"])
    assert HOTSPOT_RADIUS_M > 0


# ── 응답 수준 ────────────────────────────────────────────────────────────


def test_위치에_따라_두_경우가_다_나온다(client, recommend_payload):
    """C가 두 UI 상태를 모두 그려볼 수 있어야 한다 (키 있음 / 키 없음)."""
    near = client.post("/api/recommend", json={
        **recommend_payload, "location": {"lat": 37.5345, "lng": 126.9946}})
    far = client.post("/api/recommend", json={
        **recommend_payload, "location": OUT_HOTSPOT})

    assert near.status_code == 200 and far.status_code == 200
    near_keys = [set(r["score_breakdown"]) for r in near.json()["results"]]
    far_keys = [set(r["score_breakdown"]) for r in far.json()["results"]]

    assert any("live_segment" in k for k in near_keys), "지점 안인데 실시간 키가 없다"
    assert all("live_segment" not in k for k in far_keys), "지점 밖인데 실시간 키가 있다"
    # 키가 없는 것이지 null이 아니다 — C가 undefined를 0으로 그리면 안 된다
    assert all(v is not None for k in far.json()["results"]
               for v in k["score_breakdown"].values())
