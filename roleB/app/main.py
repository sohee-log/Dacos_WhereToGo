"""WhereToGo 추천 API.

W1의 목적은 기능이 아니라 **계약**이다. 이 앱은 DB 없이도 뜬다.
그래야 C가 A의 데이터와 B의 로직을 기다리지 않고 UI를 만들 수 있다.

목 모드일 때 모든 응답에 `X-Mock-Response: true` 헤더를 붙인다.
C가 실서버와 목서버를 화면에서 구분할 수 있어야 통합 때 혼선이 없다.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.requests import Request

from app.config import get_settings
from app.routers import context, feedback, onboarding, poi, recommend
from app.schemas import HealthResponse

settings = get_settings()

app = FastAPI(
    title="WhereToGo API",
    version=settings.app_version,
    description=(
        "용산 컨텍스트 기반 장소 추천 API.\n\n"
        "계약 원본은 roleB/openapi.yaml이다. 이 문서와 어긋나면 openapi.yaml이 맞다."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


@app.middleware("http")
async def tag_mock_responses(request: Request, call_next):
    response = await call_next(request)
    if settings.mock_mode:
        response.headers["X-Mock-Response"] = "true"
    return response


@app.get("/health", response_model=HealthResponse, tags=["system"], summary="헬스체크")
def health() -> HealthResponse:
    """UptimeRobot이 5분마다 호출한다 (Render Free 15분 슬립 방지).

    W2에 DB가 붙으면 여기서 `SELECT 1`까지 확인한다.
    """
    return HealthResponse(
        status="ok",
        db=bool(settings.database_url) and not settings.mock_mode,
        mode="mock" if settings.mock_mode else "live",
        version=settings.app_version,
    )


@app.get("/", include_in_schema=False)
def root() -> JSONResponse:
    return JSONResponse(
        {
            "service": "WhereToGo API",
            "mode": "mock" if settings.mock_mode else "live",
            "docs": "/docs",
            "contract": "roleB/openapi.yaml",
        }
    )


app.include_router(onboarding.router)
app.include_router(context.router)
app.include_router(recommend.router)
app.include_router(feedback.router)
app.include_router(poi.router)
