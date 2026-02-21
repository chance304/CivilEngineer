"""
FastAPI application factory.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from civilengineer.api.middleware.firm_context import FirmContextMiddleware
from civilengineer.api.routers import admin, auth, design, plots, projects, users, ws
from civilengineer.core.config import get_settings

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # Startup: nothing required here — migrations via Alembic CLI
    yield
    # Shutdown: nothing to clean up


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        docs_url="/api/docs" if settings.DEBUG else None,
        redoc_url="/api/redoc" if settings.DEBUG else None,
        openapi_url="/api/openapi.json" if settings.DEBUG else None,
        lifespan=lifespan,
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Firm context (sets request.state.firm_id from JWT)
    app.add_middleware(FirmContextMiddleware)

    # Routers
    prefix = "/api/v1"
    app.include_router(auth.router, prefix=prefix)
    app.include_router(projects.router, prefix=prefix)
    app.include_router(plots.router, prefix=prefix)
    app.include_router(design.router, prefix=prefix)
    app.include_router(users.router, prefix=prefix)
    app.include_router(admin.router, prefix=prefix)
    app.include_router(ws.router, prefix=prefix)

    @app.get("/health", tags=["health"])
    async def health() -> dict:
        return {"status": "ok", "version": settings.APP_VERSION}

    return app


app = create_app()
