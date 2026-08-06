"""openapi.yaml ↔ schemas.py 대조.

**openapi.yaml이 원본이고 schemas.py가 구현이다.** 둘이 어긋나면 C의 화면이 깨진다.
어느 한쪽만 고치는 사고를 여기서 막는다.
"""

from __future__ import annotations

import os

import pytest
import yaml

from app.constants import ATMOSPHERE_TAGS, CONGEST_LEVELS, PURPOSE_TAGS, ZONES
from app.schemas import (
    Atmosphere,
    CongestLevel,
    ExplainMode,
    Purpose,
    RecommendRequest,
    RecommendResponse,
    ScoreBreakdown,
)

SPEC_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "openapi.yaml"
)


@pytest.fixture(scope="module")
def spec() -> dict:
    with open(SPEC_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _schema(spec: dict, name: str) -> dict:
    return spec["components"]["schemas"][name]


# --- 고정 어휘 -------------------------------------------------------------


def test_purpose_enum_matches(spec):
    assert _schema(spec, "Purpose")["enum"] == list(PURPOSE_TAGS)
    assert [e.value for e in Purpose] == list(PURPOSE_TAGS)


def test_atmosphere_enum_matches(spec):
    assert _schema(spec, "Atmosphere")["enum"] == list(ATMOSPHERE_TAGS)
    assert [e.value for e in Atmosphere] == list(ATMOSPHERE_TAGS)


def test_congest_enum_matches(spec):
    assert _schema(spec, "CongestLevel")["enum"] == list(CONGEST_LEVELS)
    assert [e.value for e in CongestLevel] == list(CONGEST_LEVELS)


def test_explain_mode_enum_matches(spec):
    assert _schema(spec, "ExplainMode")["enum"] == [e.value for e in ExplainMode]


def test_zone_enum_matches(spec):
    spec_zones = _schema(spec, "PoiDetail")["properties"]["zone"]["enum"]
    assert spec_zones == list(ZONES)


# --- 엔드포인트 ------------------------------------------------------------


def test_all_contracted_paths_exist(spec, client):
    """스펙에 있는 5개 엔드포인트 + /health가 앱에 전부 있어야 한다."""
    app_paths = set(client.app.openapi()["paths"].keys())
    for path in spec["paths"]:
        assert path in app_paths, f"{path} 가 앱에 없다"


# --- 필드 ------------------------------------------------------------------


def test_recommend_request_required_fields_match(spec):
    assert set(_schema(spec, "RecommendRequest")["required"]) == set(
        RecommendRequest.model_fields
    )


def test_recommend_response_fields_match(spec):
    assert set(_schema(spec, "RecommendResponse")["properties"]) == set(
        RecommendResponse.model_fields
    )


def test_score_breakdown_required_fields_are_always_present(spec):
    """live_segment/crowd는 required가 아니다 — 나머지 6개는 항상 있어야 한다."""
    required = set(_schema(spec, "ScoreBreakdown")["required"])
    assert required == {"segment", "purpose", "taste", "context", "quality", "distance"}
    assert "live_segment" not in required
    assert "crowd" not in required
    assert set(_schema(spec, "ScoreBreakdown")["properties"]) == set(
        ScoreBreakdown.model_fields
    )
