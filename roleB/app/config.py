"""환경변수 설정.

시크릿은 코드에 들어가지 않는다. 레포가 public이므로 예외가 없다.
로컬은 roleB/.env, prod는 Render 환경변수로만 넣는다.
"""

from __future__ import annotations

import os
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


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

    # --- CORS ----------------------------------------------------------
    # 쉼표 구분. prod에서는 Vercel 도메인만 남긴다.
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

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
