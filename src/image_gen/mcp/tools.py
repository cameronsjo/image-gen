"""MCP tool definitions for image generation.

Tools are registered on a FastMCP instance via the register() function,
which is called during server creation. Each tool accesses the shared
service layer through the FastAPI app state.
"""

from datetime import UTC, datetime
from typing import Annotated

import structlog
from fastmcp import Context, FastMCP
from pydantic import Field

from image_gen.db import repository
from image_gen.exceptions import (
    ImageGenError,
    ProviderError,
    ProviderNotConfiguredError,
    QuotaExceededError,
    StorageError,
    UnsupportedParameterError,
)
from image_gen.models import GenerationStatus
from image_gen.services.prompt import ParsedPrompt, validate_prompt

logger = structlog.get_logger()

# These will be populated by register() with references to the app
_app_ref = None


def _resolve_user(ctx: Context | None) -> str:
    """Resolve the calling user from the MCP context.

    Reads the OAuth subject from the validated access token when present and
    falls back to ``"anonymous"`` when no token is attached — mirroring the
    REST auth-disabled path so identities line up across the two surfaces.
    """
    if ctx and ctx.request_context and hasattr(ctx.request_context, "access_token"):
        token = ctx.request_context.access_token
        if token and hasattr(token, "sub"):
            return str(token.sub)
    return "anonymous"


def _missing_services(app: object, *names: str) -> list[str]:
    """Return the names of required ``app.state`` services that are absent."""
    state = getattr(app, "state", None)
    return [name for name in names if state is None or getattr(state, name, None) is None]


def _categorize(exc: Exception) -> tuple[str, str]:
    """Map a domain error to a (log category, user-facing phrase) pair."""
    if isinstance(exc, ProviderNotConfiguredError):
        return "provider_not_configured", "the requested provider is not configured"
    if isinstance(exc, UnsupportedParameterError):
        return (
            "unsupported_parameter",
            "the requested aspect-ratio / resolution combination is not supported",
        )
    if isinstance(exc, ProviderError):
        return "provider_error", "the image provider returned an error"
    if isinstance(exc, QuotaExceededError):
        return "quota_exceeded", "the quota for this user is exhausted"
    if isinstance(exc, StorageError):
        return "storage_error", "the image could not be stored or retrieved"
    if isinstance(exc, ImageGenError):
        return "domain_error", "an internal image-gen error occurred"
    return "unexpected_error", "an unexpected error occurred"


def register(mcp: FastMCP) -> None:
    """Register all MCP tools on the server instance."""

    @mcp.tool
    async def generate_image(
        name: Annotated[str, Field(description="Human-readable name for this image")],
        prompt: Annotated[str, Field(description="Detailed image generation prompt (50+ words)")],
        aspect_ratio: Annotated[
            str, Field(default="1:1", description="Image aspect ratio (e.g. 1:1, 16:9, 9:16)")
        ] = "1:1",
        resolution: Annotated[
            str, Field(default="2K", description="Image resolution: 1K, 2K, or 4K")
        ] = "2K",
        provider: Annotated[
            str,
            Field(
                default="gemini",
                description="Image generation provider: gemini, openai, or openrouter",
            ),
        ] = "gemini",
        ctx: Context | None = None,
    ) -> str:
        """Generate an image using a configured provider.

        Provide a detailed prompt (minimum 50 words) describing the image you want.
        The prompt should include subject, style, lighting, composition, and any
        specific details for best results.
        """
        # Pre-flight validation
        parsed = ParsedPrompt(
            name=name,
            body=prompt,
            aspect_ratio=aspect_ratio,
            resolution=resolution,
        )
        errors = validate_prompt(parsed)
        if errors:
            return f"Validation failed: {'; '.join(errors)}"

        if _app_ref is None:
            return "Service not initialized — app reference not set"

        app = _app_ref
        # Null-safety: every service this tool touches must be wired up.
        missing = _missing_services(app, "provider_registry", "storage", "quota", "db")
        if missing:
            return f"Service not initialized — missing: {', '.join(missing)}"

        registry = app.state.provider_registry
        storage = app.state.storage
        quota = app.state.quota
        db = app.state.db

        # Validate provider selection
        if provider not in registry:
            available = ", ".join(sorted(registry.keys()))
            return f"Unknown or unconfigured provider {provider!r}. Available: {available}"
        selected_provider = registry[provider]

        # Resolve the calling user from the MCP context (no hardcoded identity).
        user_id = _resolve_user(ctx)

        # Rate limit
        if not await quota.consume_token(user_id):
            status = await quota.get_status(user_id)
            next_at = status.next_token_at
            next_str = next_at.isoformat() if next_at else "soon"
            return (
                f"Rate limit exceeded. "
                f"Remaining: {status.remaining_tokens:.1f}. "
                f"Try again at: {next_str}"
            )

        # Create DB record
        record = await repository.create_generation(
            db,
            user_id=user_id,
            name=name,
            prompt=prompt,
            aspect_ratio=aspect_ratio,
            resolution=resolution,
            provider=provider,
        )
        await repository.update_generation(db, record.id, status=GenerationStatus.GENERATING)

        try:
            result = await selected_provider.generate_image(
                prompt=prompt,
                aspect_ratio=aspect_ratio,
                resolution=resolution,
            )
            file_path = await storage.save_image(result.image_data, record.id)
            file_size = len(result.image_data)

            await repository.update_generation(
                db,
                record.id,
                status=GenerationStatus.COMPLETED,
                file_path=str(file_path),
                file_size=file_size,
                completed_at=datetime.now(UTC),
            )

            return (
                f"Image generated successfully!\n"
                f"ID: {record.id}\n"
                f"Name: {name}\n"
                f"Provider: {provider}\n"
                f"File size: {file_size:,} bytes\n"
                f"Path: {file_path}"
            )

        except Exception as exc:
            await repository.update_generation(
                db,
                record.id,
                status=GenerationStatus.FAILED,
                error=str(exc),
                completed_at=datetime.now(UTC),
            )
            category, detail = _categorize(exc)
            logger.error(
                "MCP image generation failed",
                generation_id=record.id,
                user_id=user_id,
                category=category,
                error=str(exc),
            )
            return f"Image generation failed: {detail} ({exc})"

    @mcp.tool
    async def list_images(
        limit: Annotated[
            int, Field(default=20, description="Maximum number of images to return")
        ] = 20,
        ctx: Context | None = None,
    ) -> str:
        """List your recent image generations with their metadata."""
        if _app_ref is None:
            return "Service not initialized"

        app = _app_ref
        missing = _missing_services(app, "db")
        if missing:
            return f"Service not initialized — missing: {', '.join(missing)}"

        user_id = _resolve_user(ctx)

        try:
            records = await repository.list_generations(app.state.db, user_id=user_id, limit=limit)
        except Exception as exc:
            category, detail = _categorize(exc)
            logger.error(
                "MCP list_images failed", user_id=user_id, category=category, error=str(exc)
            )
            return f"Failed to list images: {detail} ({exc})"

        if not records:
            return "No images found."

        lines = [f"Found {len(records)} image(s):\n"]
        for r in records:
            status_icon = {"completed": "done", "failed": "FAIL", "pending": "..."}.get(
                r.status.value, r.status.value
            )
            created = r.created_at.isoformat()
            lines.append(
                f"[{status_icon}] {r.id} | {r.name} | {r.aspect_ratio} {r.resolution} | {created}"
            )
        return "\n".join(lines)

    @mcp.tool
    async def get_quota_status(ctx: Context | None = None) -> str:
        """Check your current rate limit quota for image generation."""
        if _app_ref is None:
            return "Service not initialized"

        app = _app_ref
        missing = _missing_services(app, "quota")
        if missing:
            return f"Service not initialized — missing: {', '.join(missing)}"

        user_id = _resolve_user(ctx)

        try:
            status = await app.state.quota.get_status(user_id)
        except Exception as exc:
            category, detail = _categorize(exc)
            logger.error(
                "MCP get_quota_status failed", user_id=user_id, category=category, error=str(exc)
            )
            return f"Failed to retrieve quota status: {detail} ({exc})"

        next_at = status.next_token_at
        next_str = next_at.isoformat() if next_at else "available now"
        return (
            f"Quota Status:\n"
            f"  Remaining: {status.remaining_tokens:.1f}/{status.max_tokens}\n"
            f"  Refill rate: {status.refill_rate * 60:.1f} tokens/min\n"
            f"  Next token at: {next_str}"
        )


def set_app_ref(app: object) -> None:
    """Set the FastAPI app reference for MCP tools to access services."""
    global _app_ref
    _app_ref = app
