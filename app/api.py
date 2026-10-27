from __future__ import annotations

import logging
import re
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.agent import Agent, RuleBasedRouter
from app.config import BASE_DIR, ConfigError, Settings, get_settings
from app.llm import build_llm
from app.models import ChatRequest, ChatResponse, HealthResponse
from app.providers.base import RailwayProvider
from app.providers.local import LocalTimetableProvider
from app.sessions import SessionStore

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).resolve().parent / "static"
SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_-]{4,64}$")


def create_app(
    settings: Settings | None = None,
    provider: RailwayProvider | None = None,
    llm_provider=None,
    sessions: SessionStore | None = None,
    router=None,
) -> FastAPI:
    settings = settings or get_settings()
    provider = provider or LocalTimetableProvider(settings.railway_db_path)
    sessions = sessions or SessionStore(settings.max_sessions, settings.history_limit)

    config_error: str | None = None
    if llm_provider is None and settings.llm_provider != "none":
        try:
            llm_provider = build_llm(settings)
        except ConfigError as exc:
            config_error = str(exc)
            llm_provider = None

    if router is None and llm_provider is None and config_error is None:
        router = RuleBasedRouter(provider, sessions)

    agent = Agent(llm_provider, provider, settings, sessions, router=router)

    app = FastAPI(
        title="Indian Railways Information Agent",
        description=(
            "Independent train-information assistant. Not an official Indian Railways "
            "or IRCTC service."
        ),
        version="0.1.0",
    )
    app.state.settings = settings
    app.state.provider = provider
    app.state.agent = agent
    app.state.sessions = sessions
    app.state.config_error = config_error

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'"
        )
        return response

    @app.exception_handler(Exception)
    async def unhandled_exception(request: Request, exc: Exception):
        logger.exception("Unhandled error on %s", request.url.path)
        return JSONResponse(status_code=500, content={"detail": "Internal server error."})

    @app.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        dataset = provider.health()
        if llm_provider is None and settings.llm_provider == "none":
            llm_status = {"status": "disabled", "detail": "Deterministic router (no LLM)."}
        elif llm_provider is None:
            llm_status = {"status": "error", "detail": config_error}
        else:
            llm_status = await llm_provider.health()

        ok = dataset.get("status") == "ok" and config_error is None
        if llm_status.get("status") not in ("ok", "disabled"):
            ok = False
        return HealthResponse(
            status="ok" if ok else "degraded",
            llm_provider=settings.llm_provider,
            llm_model=settings.llm_model or None,
            railway_provider=provider.name,
            dataset=dataset,
            detail=config_error or llm_status.get("detail"),
        )

    @app.post("/chat", response_model=ChatResponse)
    async def chat(request: ChatRequest) -> ChatResponse:
        if config_error:
            raise HTTPException(status_code=503, detail=config_error)
        message = request.message.strip()
        if not message:
            raise HTTPException(status_code=400, detail="Message must not be empty.")
        if len(message) > settings.max_message_chars:
            raise HTTPException(
                status_code=400,
                detail=f"Message is too long (limit {settings.max_message_chars} characters).",
            )
        if request.session_id and not SESSION_ID_RE.match(request.session_id):
            raise HTTPException(status_code=400, detail="Invalid session id.")

        session_obj = sessions.get(request.session_id)
        return await agent.chat(session_obj, message)

    @app.get("/", include_in_schema=False)
    async def index():
        return FileResponse(STATIC_DIR / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    return app


app = create_app()
