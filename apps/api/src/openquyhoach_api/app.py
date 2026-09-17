"""FastAPI application factory."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from openquyhoach_core.errors import OQHError
from openquyhoach_core.logging import configure_logging, get_logger
from openquyhoach_core.settings import get_settings

from .routers import browse, georef, ingest, publish, query

log = get_logger(__name__)

DESCRIPTION = """\
OpenQuyHoach — open, verifiable planning-data infrastructure for Vietnam.

Every entity carries provenance (source artifact sha256, retrieval time,
transformation steps, review state). Derived data is never presented as
official.
"""


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format)

    app = FastAPI(
        title="OpenQuyHoach API",
        version="0.1.0",
        description=DESCRIPTION,
        openapi_url="/v1/openapi.json",
        docs_url="/docs",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "X-Admin-Key"],
        max_age=600,
    )

    @app.exception_handler(OQHError)
    async def oqh_error(_req: Request, exc: OQHError):
        return JSONResponse(
            status_code=exc.http_status,
            content={"error": exc.code, "message": str(exc), "detail": exc.detail},
        )

    @app.exception_handler(Exception)
    async def unhandled(_req: Request, exc: Exception):
        log.exception("api.unhandled", error=str(exc))
        return JSONResponse(
            status_code=500,
            content={"error": "internal_error", "message": "internal error"},
        )

    app.include_router(browse.router)
    app.include_router(query.router)
    app.include_router(ingest.router)
    app.include_router(publish.router)
    app.include_router(georef.router)

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    @app.get("/readyz")
    def readyz():
        from openquyhoach_core.db import get_engine
        from sqlalchemy import text

        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "ready"}

    # FastAPI >=0.141 registers include_router lazily — force materialisation
    app.setup()
    return app


app = create_app()
