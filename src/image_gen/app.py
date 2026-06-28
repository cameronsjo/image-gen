"""FastAPI application factory with lifespan management."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import Depends, FastAPI
from starlette.types import ASGIApp, Receive, Scope, Send

from image_gen.api import generate, health, images
from image_gen.auth import get_current_user
from image_gen.config import Settings
from image_gen.db import engine, migrations
from image_gen.mcp.server import create_mcp_server
from image_gen.mcp.tools import set_app_ref
from image_gen.middleware import RequestIDMiddleware
from image_gen.services.quota import QuotaService
from image_gen.services.registry import build_registry
from image_gen.services.storage import StorageService

logger = structlog.get_logger()


class MCPSlashRewrite:
    """Rewrite /mcp → /mcp/ to avoid Starlette's mount trailing-slash 307 redirect.

    Raw ASGI middleware (not BaseHTTPMiddleware) to preserve SSE streaming.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["path"] == "/mcp":
            scope = dict(scope, path="/mcp/")
        await self.app(scope, receive, send)


def configure_logging(settings: Settings) -> None:
    """Set up structlog with JSON rendering."""
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer()
            if settings.log_level == "DEBUG"
            else structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelName(settings.log_level)
        ),
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Initialize and tear down application services.

    Composes the MCP sub-app's lifespan (which starts the
    StreamableHTTPSessionManager task group) with FastAPI's own lifespan.
    """
    settings: Settings = app.state.settings
    mcp_app = app.state.mcp_app

    # Start the MCP sub-app lifespan (initializes session manager task group)
    async with mcp_app.lifespan(mcp_app):
        # Initialize database
        db = await engine.connect(settings.resolved_db_path)
        await migrations.run_migrations(db)
        app.state.db = db

        # Build provider registry — fails fast if default_provider not configured
        app.state.provider_registry = build_registry(settings)

        # Initialize remaining services
        app.state.storage = StorageService(settings)
        app.state.quota = QuotaService(db, settings)

        # Wire MCP tools to app state
        set_app_ref(app)

        logger.info(
            "Application started",
            port=settings.port,
            default_provider=settings.default_provider,
            providers=sorted(app.state.provider_registry.keys()),
            data_dir=str(settings.data_dir),
            auth_enabled=settings.auth_enabled,
        )

        yield

        # Cleanup — close pooled provider clients, then the DB. One provider's
        # close failure must not strand the others or the DB handle.
        logger.debug(
            "Preparing to close providers",
            count=len(app.state.provider_registry),
        )
        for name, provider in app.state.provider_registry.items():
            try:
                await provider.aclose()
            except Exception as exc:
                logger.warning("Provider close failed", provider=name, error=str(exc))
        await db.close()
        logger.info("Application stopped")


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the FastAPI application with all routes and middleware."""
    if settings is None:
        settings = Settings()

    configure_logging(settings)

    app = FastAPI(
        title="image-gen",
        description="Image generation toolkit powered by multiple providers",
        version="0.1.0",
        lifespan=lifespan,
    )

    # Store settings for lifespan access
    app.state.settings = settings

    # Track A: request-ID middleware
    app.add_middleware(RequestIDMiddleware)

    # Register routers — health is unauthenticated, API routes require auth
    app.include_router(health.router)
    app.include_router(generate.router, dependencies=[Depends(get_current_user)])
    app.include_router(images.router, dependencies=[Depends(get_current_user)])

    # Mount MCP server at /mcp — store the sub-app on state so the
    # lifespan can compose the MCP session manager lifecycle
    mcp = create_mcp_server(settings)
    mcp_starlette = mcp.http_app(path="/")
    app.state.mcp_app = mcp_starlette
    app.mount("/mcp", mcp_starlette)

    # Rewrite /mcp → /mcp/ so POST requests hit the mount directly
    # instead of getting a 307 trailing-slash redirect
    app.add_middleware(MCPSlashRewrite)

    return app
