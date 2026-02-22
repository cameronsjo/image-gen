"""MCP tool definitions for image generation.

Tools are registered on a FastMCP instance via the register() function,
which is called during server creation. Each tool accesses the shared
service layer through the FastAPI app state.
"""

from typing import Annotated

from fastmcp import Context, FastMCP
from pydantic import Field

# These will be populated by register() with references to the app
_app_ref = None


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
        ctx: Context | None = None,
    ) -> str:
        """Generate an image using Gemini 3 Pro.

        Provide a detailed prompt (minimum 50 words) describing the image you want.
        The prompt should include subject, style, lighting, composition, and any
        specific details for best results.
        """
        from image_gen.services.prompt import ParsedPrompt, validate_prompt

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
        gemini = app.state.gemini
        storage = app.state.storage
        quota = app.state.quota
        db = app.state.db

        # Resolve user from MCP context
        user_id = "mcp-user"
        if ctx and ctx.request_context and hasattr(ctx.request_context, "access_token"):
            token = ctx.request_context.access_token
            if token and hasattr(token, "sub"):
                user_id = token.sub

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
        from datetime import UTC, datetime

        from image_gen.db import repository
        from image_gen.models import GenerationStatus

        record = await repository.create_generation(
            db,
            user_id=user_id,
            name=name,
            prompt=prompt,
            aspect_ratio=aspect_ratio,
            resolution=resolution,
        )
        await repository.update_generation(db, record.id, status=GenerationStatus.GENERATING)

        try:
            result = await gemini.generate_image(
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
                f"File size: {file_size:,} bytes\n"
                f"Path: {file_path}"
            )

        except Exception as e:
            await repository.update_generation(
                db,
                record.id,
                status=GenerationStatus.FAILED,
                error=str(e),
                completed_at=datetime.now(UTC),
            )
            return f"Image generation failed: {e}"

    @mcp.tool
    async def list_images(
        limit: Annotated[
            int, Field(default=20, description="Maximum number of images to return")
        ] = 20,
    ) -> str:
        """List recent image generations with their metadata."""
        if _app_ref is None:
            return "Service not initialized"

        from image_gen.db import repository

        records = await repository.list_generations(_app_ref.state.db, limit=limit)
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
    async def get_quota_status() -> str:
        """Check your current rate limit quota for image generation."""
        if _app_ref is None:
            return "Service not initialized"

        from image_gen.services.quota import QuotaService

        quota: QuotaService = _app_ref.state.quota
        status = await quota.get_status("mcp-user")

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
