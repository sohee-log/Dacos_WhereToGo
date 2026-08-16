"""환경변수 설정.

시크릿은 코드에 들어가지 않는다. 레포가 public이므로 예외가 없다.
로컬은 roleB/.env, prod는 Render 환경변수로만 넣는다.
"""

from __future__ import annotations

import os
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

from app.constants import ATTR_CONFIDENCE_MIN, ATTR_CONFIDENCE_RELAXED


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # --- 동작 모드 -----------------------------------------------------
    # W1은 목 모드로 뜬다. DB가 아직 없어도 C가 즉시 개발에 착수할 수 있어야 한다.
    # W2에 DATABASE_URL이 붙으면 MOCK_MODE=false로 내린다.
    mock_mode: bool = True
    app_version: str = "0.1.0"

    # --- DB (W2~) ------------------------------------------------------
    database_url: str | None = None
    db_pool_min: int = 1
    db_pool_max: int = 5          # Supabase Free 커넥션 한도를 고려한 보수적 값
    db_pool_timeout: float = 10.0 # 풀 기본 대기 상한(초)
    # 요청 하나가 커넥션을 기다리는 상한. 짧아야 한다 —
    # DB가 죽었을 때 사용자를 10초 세워두고 500을 주느니 3초 만에 503이 낫다.
    db_acquire_timeout: float = 3.0
    # 느린 쿼리 하나가 무료 티어 워커를 잡아먹지 않게 한다.
    # 목표 응답은 300ms다 (ROLE_B W4 B4-1). 여유를 두되 무한대는 두지 않는다.
    db_statement_timeout_ms: int = 4000

    # --- CORS ----------------------------------------------------------
    # 쉼표 구분. prod에서는 Vercel 도메인만 남긴다.
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    # --- 후보 필터 임계값 (전환기 조정용) --------------------------------
    # 기본값은 constants의 설계값(0.30 / 0.15)이다. 평상시 건드릴 이유가 없다.
    #
    # 여기를 환경변수로 뺀 이유: A의 LLM 속성 추출(A3-2/A4-1)이 끝나기 전에는
    # `poi.attr_confidence`가 전 건 0이라, 0.30 기준으로는 후보가 한 건도 남지
    # 않는다. 그러면 최근접 폴백까지 밀려 **순위 없는 3건**이 나간다.
    # 화면을 먼저 확인해야 하는 상황이면 Render 환경변수만 내려서 전환하고,
    # 추출이 끝나면 되돌린다. **코드 수정과 재배포가 필요 없어야 한다.**
    #
    # 완화한 채로 두면 속성 없는 POI가 그대로 추천에 섞인다. 응답의
    # `low_confidence`로 드러나긴 하지만, 되돌리는 것을 잊지 않는 게 먼저다.
    attr_confidence_min: float = ATTR_CONFIDENCE_MIN
    attr_confidence_relaxed: float = ATTR_CONFIDENCE_RELAXED

    # --- 목 데이터 -----------------------------------------------------
    # A가 seeds/poi_seed.json을 커밋하면 자동으로 그걸 읽는다.
    # 없으면 내장 픽스처로 폴백한다 — B는 A를 기다리지 않는다 (ROLE_B §10).
    seed_path: str = "../seeds/poi_seed.json"
    # 목 응답의 날씨를 고정하고 싶을 때. 맑음 / 비 / 미세먼지나쁨 / 폭염한파
    mock_weather_state: str | None = None

    # --- 외부 API (W3~. 값이 없어도 앱은 떠야 한다) ----------------------
    seoul_citydata_key: str | None = None
    kma_service_key: str | None = None
    # 게이트웨이는 OpenAI 호환. 경로에 끝 슬래시가 필요하다 (/chat/completions/).
    # 키만 시크릿이다. URL과 모델명은 공개해도 무방하므로 기본값을 둔다.
    llm_api_key: str | None = None
    llm_base_url: str = "https://factchat-cloud.mindlogic.ai/v1/gateway"
    llm_model: str = "gpt-5.4-nano"
    # 강제 폴백 스위치. W5의 템플릿 폴백 테스트(B5-5)에서 쓴다.
    llm_force_fail: bool = False
    llm_max_tokens: int = 700
    # 무료 티어에서 외부 API가 워커를 오래 잡지 않게. 설명 생성은 2~3초면 끝난다.
    llm_timeout: float = 8.0
    # 게이트웨이가 rate limit 헤더를 주지 않아 남은 양을 알 수 없다(docs/LLM_QUOTA.md).
    # 프로세스 안에서 세다가 이 값에 닿으면 템플릿으로 내려간다. 0 이하면 제한 없음.
    llm_daily_limit: int = 500

    # --- 레이트 리밋 (B5-6) ---------------------------------------------
    # IP당 분당 허용 횟수. 무료 LLM 쿼터를 한 사람이 태우는 것을 막는다.
    rate_limit_per_min: int = 10

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


def seed_file_path(settings: Settings) -> str:
    """seed_path를 roleB/ 기준 절대경로로 바꾼다."""
    if os.path.isabs(settings.seed_path):
        return settings.seed_path
    roleb_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.normpath(os.path.join(roleb_root, settings.seed_path))
