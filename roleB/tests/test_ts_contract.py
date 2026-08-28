"""roleC/lib/api-types.ts ↔ openapi.yaml 대조.

**왜 이 테스트가 있나**

C의 타입은 지금까지 손으로 베껴 쓴 계약이었다. 2026-08-28 실측으로 세 곳이
어긋나 있었고, 셋 다 *화면은 멀쩡하고 기능만 사라지는* 형태였다.

  · `POST /api/feedback` 이 전부 422 — `clicked`를 boolean으로 보냈다.
    `api.ts`가 404만 삼키고 나머지는 던지는데 호출부가 `.catch()`로 받아서
    아무도 몰랐다. `recommendation_log`의 클릭·선택·만족도가 통째로 비었다.
  · `GET /api/context/now` 가 필수 쿼리 `lat`/`lng`를 안 붙인다 (잠복 422).
  · `low_confidence` · `radius_expanded` · `image_url` · `rain_prob` 누락.

사람이 두 파일을 눈으로 대조해 막을 수 있는 종류가 아니다. 그래서 생성으로
바꿨고(`tools/gen_ts_types.py`), 이 테스트가 **생성을 안 돌린 채 openapi만
고치는 것**을 막는다. CI의 `roleB tests` 잡에서 돈다.

깨졌다면 고치는 법:

    cd roleB && python -m tools.gen_ts_types
"""

from __future__ import annotations

import pytest

from tools.gen_ts_types import TARGET, generate


@pytest.fixture(scope="module")
def generated() -> str:
    return generate()


def test_generated_file_is_committed():
    assert TARGET.exists(), (
        f"{TARGET} 가 없다. `cd roleB && python -m tools.gen_ts_types` 를 돌린다"
    )


def test_committed_file_matches_openapi(generated: str):
    """openapi.yaml을 고쳤으면 생성기도 돌려야 한다."""
    current = TARGET.read_text(encoding="utf-8").replace("\r\n", "\n")
    assert current == generated, (
        "roleC/lib/api-types.ts 가 openapi.yaml 과 어긋났다.\n"
        "  cd roleB && python -m tools.gen_ts_types"
    )


# --- 실제로 틀렸던 것들이 다시 틀리지 않는가 --------------------------------
#
# 위 대조가 이미 전부를 덮지만, 무엇을 왜 지키는지가 진단 이름에 남아야
# 다음 사람이 같은 실수를 반복하지 않는다.


def test_feedback_clicked_is_a_string_array(generated: str):
    """boolean으로 보내면 422다. 클릭한 poi_id들의 배열이다."""
    assert "clicked?: string[];" in generated
    assert "clicked?: boolean" not in generated


def test_feedback_uses_feedback_not_satisfaction(generated: str):
    """만족도 필드 이름은 `feedback`이다. `satisfaction`이 아니다."""
    assert "feedback?: number | null;" in generated
    assert "satisfaction" not in generated


def test_recommend_response_always_carries_the_two_flags(generated: str):
    """전환 전까지 둘 다 true다. 옵셔널로 그리면 디버그 화면이 비어 보인다."""
    assert "low_confidence: boolean;" in generated
    assert "radius_expanded: boolean;" in generated


def test_recommendation_carries_image_url(generated: str):
    assert "image_url: string | null;" in generated


def test_live_terms_stay_optional(generated: str):
    """live_segment/crowd는 **없을 수 있다.** 0으로 그리면 안 된다 (ROLE_B §6.4)."""
    assert "live_segment?: number;" in generated
    assert "crowd?: number;" in generated


def test_error_schema_is_not_named_Error(generated: str):
    """TS 전역 `Error`를 가리면 `class ApiError extends Error`가 자기 자신을 상속한다."""
    assert "export interface ApiErrorBody {" in generated
    assert "export interface Error {" not in generated
