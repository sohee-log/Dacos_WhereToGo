"""사용자 프로필 — 온보딩 저장 + taste_vector 구성 (B4-5).

**서버에서 임베딩하지 않는다.** bge-m3는 2GB라 Render Free에 올라가지 않는다
(ROLE_B §1.2). 대신 온보딩 태그가 유한 집합(분위기 10 + 목적 6 = 16종)이라는
성질을 쓴다 — A가 배치로 한 번 임베딩해 `tag_embedding`에 넣어두면
온라인에서는 **평균만 내면 된다**. `query_vector_cache`와 같은 발상이다.

`tag_embedding`이 비어 있으면 `taste_vector`는 NULL이 된다. 그래도 서비스는
돈다 — `taste_similarity`가 중립(0.5)이 되고 취향 축 하나가 쉴 뿐이다.
**빈 벡터나 영벡터를 넣지 않는다.** 그러면 모든 POI와의 코사인이 0이 되어
"취향이 정반대"라는 뜻이 된다.

user_id는 요청 내용의 해시다. 같은 답을 하면 같은 id가 나온다 — 목 모드와
같은 규칙이라 C가 두 모드를 오가도 로컬 저장값이 깨지지 않는다.
개인 식별자를 새로 만들지 않는 것이기도 하다 (PLAN.md §8.3 개인정보 최소화).
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Sequence
from typing import Any

log = logging.getLogger("wheretogo.user")

# 태그 벡터의 평균. halfvec은 집계 함수가 없으므로 vector로 캐스팅해 평균 낸 뒤 되돌린다.
# 조회된 태그가 하나도 없으면 0행이 나오고, 그때는 taste_vector를 NULL로 둔다.
TASTE_VECTOR_SQL = """
SELECT AVG(embedding::vector)::halfvec(1024) AS taste_vector,
       count(*) AS matched
FROM tag_embedding
WHERE tag = ANY(%(tags)s)
"""

UPSERT_PROFILE_SQL = """
INSERT INTO user_profile
    (user_id, gender, age_band, taste_tags, taste_vector, weather_sensitivity)
VALUES
    (%(user_id)s, %(gender)s, %(age_band)s, %(taste_tags)s,
     %(taste_vector)s, %(weather_sensitivity)s)
ON CONFLICT (user_id) DO UPDATE SET
    gender              = EXCLUDED.gender,
    age_band            = EXCLUDED.age_band,
    taste_tags          = EXCLUDED.taste_tags,
    -- 새 값이 NULL이면 기존 벡터를 지우지 않는다. tag_embedding이 잠시 비어 있는
    -- 사이에 재제출하면 애써 만든 벡터가 날아간다.
    taste_vector        = COALESCE(EXCLUDED.taste_vector, user_profile.taste_vector),
    weather_sensitivity = EXCLUDED.weather_sensitivity
RETURNING user_id
"""


def make_user_id(
    gender: str,
    age_band: int,
    atmosphere_tags: Sequence[str],
    purpose_tags: Sequence[str],
    budget_band: int,
    weather_sensitivity: int,
) -> str:
    """요청 내용으로부터 결정적으로 만든 id. 목 경로와 규칙이 같아야 한다."""
    key = "|".join(
        [
            gender,
            str(age_band),
            ",".join(sorted(atmosphere_tags)),
            ",".join(sorted(purpose_tags)),
            str(budget_band),
            str(weather_sensitivity),
        ]
    )
    return "u_" + hashlib.sha256(key.encode()).hexdigest()[:6]


def build_taste_vector(executor, tags: Sequence[str]) -> Any | None:
    """취향 태그 → 평균 벡터. 태그가 하나도 매칭되지 않으면 None."""
    if not tags:
        return None
    try:
        rows = executor(TASTE_VECTOR_SQL, {"tags": list(tags)})
    except Exception as exc:
        # 테이블이 아직 없을 수도 있다(002 마이그레이션 미적용). 온보딩은 계속된다.
        log.warning("taste_vector 계산 실패: %s", exc)
        return None

    if not rows or not rows[0].get("matched"):
        log.info("tag_embedding에 매칭되는 태그가 없다 (%s) — taste_vector는 NULL", tags)
        return None
    return rows[0]["taste_vector"]


def upsert_profile(
    executor,
    *,
    user_id: str,
    gender: str,
    age_band: int,
    taste_tags: Sequence[str],
    weather_sensitivity: int,
) -> str:
    """user_profile 저장. 같은 답을 다시 내면 덮어쓴다."""
    taste_vector = build_taste_vector(executor, taste_tags)
    rows = executor(
        UPSERT_PROFILE_SQL,
        {
            "user_id": user_id,
            "gender": gender,
            "age_band": age_band,
            "taste_tags": list(taste_tags),
            "taste_vector": taste_vector,
            "weather_sensitivity": weather_sensitivity,
        },
    )
    return rows[0]["user_id"] if rows else user_id
