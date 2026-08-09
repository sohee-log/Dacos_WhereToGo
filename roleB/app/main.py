"""WhereToGo 추천 API.

W1의 목적은 기능이 아니라 **계약**이다. 이 앱은 DB 없이도 뜬다.
그래야 C가 A의 데이터와 B의 로직을 기다리지 않고 UI를 만들 수 있다.

목 모드일 때 모든 응답에 `X-Mock-Response: true` 헤더를 붙인다.
C가 실서버와 목서버를 화면에서 구분할 수 있어야 통합 때 혼선이 없다.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.requests import Request

from app.config import get_settings
from app.db import init_db, shutdown_db
from app.routers import context, feedback, onboarding, poi, recommend
from app.schemas import HealthResponse

settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    """커넥션 풀은 프로세스 수명과 같이 간다.

    Render Free는 슬립에서 깨어날 때 프로세스를 새로 띄우므로 여기가 매번 돈다.
    `init_db`는 실패해도 예외를 올리지 않는다 — DB가 없어도 앱은 떠야 한다.
    """
    init_db(settings)
    try:
        yield
    finally:
        shutdown_db()


app = FastAPI(
    title="WhereToGo API",
    version=settings.app_version,
    description=(
        "용산 컨텍스트 기반 장소 추천 API.\n\n"
        "계약 원본은 roleB/openapi.yaml이다. 이 문서와 어긋나면 openapi.yaml이 맞다."
    ),
    lifespan=lifespan,
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

    `db`는 설정값이 아니라 **실제 `SELECT 1` 결과**다 (W2). DATABASE_URL이
    꽂혀 있는데 Supabase가 일시정지된 상태를 여기서 구분할 수 있어야 한다.
    DB가 죽어도 status는 ok로 둔다 — 목 모드로는 서비스가 계속 돌기 때문이고,
    여기서 500을 내면 UptimeRobot이 슬립 방지 핑을 실패로 기록한다.
    """
    from app.db import get_db

    db_ok = False
    if not settings.mock_mode:
        try:
            db_ok = get_db().healthy()
        except Exception:  # 풀 미초기화 등. 헬스체크는 어떤 경우에도 200이다
            db_ok = False

    return HealthResponse(
        status="ok",
        db=db_ok,
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
