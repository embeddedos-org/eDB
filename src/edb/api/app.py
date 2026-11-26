"""FastAPI application factory and dependencies for eDB."""

from __future__ import annotations

import logging
import math
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from edb import __version__
from edb.api.dependencies import AppState
from edb.api.middleware import RateLimitMiddleware, RequestLoggingMiddleware
from edb.api.routes import admin, auth, documents, ebot, graph, kv, sql
from edb.config import EDBConfig

logger = logging.getLogger("edb.api")


def _json_safe(value: Any) -> Any:
    """Replace NaN and infinities, which JSON cannot encode, with their string form."""
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    return value


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    config: EDBConfig = app.state.config
    state = AppState(config)
    app.state.edb = state

    logging.basicConfig(level=getattr(logging, config.log_level.upper(), logging.INFO))

    yield
    state.database.close()


def create_app(config: EDBConfig | None = None) -> FastAPI:
    if config is None:
        config = EDBConfig()

    app = FastAPI(
        title="eDB API",
        description="Unified Multi-Model Database API — SQL, Document, Key-Value, Graph",
        version=__version__,
        lifespan=lifespan,
    )
    # lifespan() builds the database and services from this same config.
    app.state.config = config

    @app.exception_handler(RequestValidationError)
    async def request_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        # FastAPI's default handler echoes each rejected input back in the 422
        # body. Python's JSON parser accepts NaN and Infinity, but JSONResponse
        # refuses to encode them, so a rejected NaN would turn the 422 into a 500.
        # The same failure shows up for a deeply nested rejected input (~500+
        # levels): encoding the echoed input recurses past the limit, so the
        # 422 itself becomes a 500 (eDB#220). Then the failure is reported
        # without the input.
        try:
            detail = _json_safe(jsonable_encoder(exc.errors()))
        except Exception:
            logger.warning("could not encode validation errors; returning a generic 422")
            detail = [{"type": "value_error", "msg": "Request validation failed"}]
        return JSONResponse(status_code=422, content={"detail": detail})

    origins = [o.strip() for o in config.cors_origins.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
        allow_headers=["Authorization", "Content-Type"],
    )

    if config.rate_limit_enabled:
        app.add_middleware(
            RateLimitMiddleware,
            max_requests=config.rate_limit_requests,
            window_seconds=config.rate_limit_window_seconds,
        )
    app.add_middleware(RequestLoggingMiddleware)

    app.include_router(auth.router, prefix="/auth", tags=["Authentication"])
    app.include_router(sql.router, prefix="/sql", tags=["SQL"])
    app.include_router(documents.router, prefix="/docs", tags=["Documents"])
    app.include_router(kv.router, prefix="/kv", tags=["Key-Value"])
    app.include_router(graph.router, prefix="/graph", tags=["Graph"])
    app.include_router(admin.router, prefix="/admin", tags=["Admin"])
    app.include_router(ebot.router, prefix="/ebot", tags=["ebot AI"])

    @app.get("/health", tags=["Health"])
    def health_check() -> dict[str, str]:
        return {"status": "healthy", "version": __version__}

    return app
