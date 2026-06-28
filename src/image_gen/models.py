"""Pydantic request/response schemas."""

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class AspectRatio(StrEnum):
    """Supported image aspect ratios."""

    SQUARE = "1:1"
    PORTRAIT_2_3 = "2:3"
    LANDSCAPE_3_2 = "3:2"
    PORTRAIT_3_4 = "3:4"
    LANDSCAPE_4_3 = "4:3"
    PORTRAIT_4_5 = "4:5"
    LANDSCAPE_5_4 = "5:4"
    PORTRAIT_9_16 = "9:16"
    LANDSCAPE_16_9 = "16:9"
    ULTRAWIDE_21_9 = "21:9"


class Resolution(StrEnum):
    """Supported image resolutions."""

    ONE_K = "1K"
    TWO_K = "2K"
    FOUR_K = "4K"


class ProviderName(StrEnum):
    """Available image generation providers."""

    GEMINI = "gemini"
    OPENAI = "openai"
    OPENROUTER = "openrouter"


class GenerationStatus(StrEnum):
    """Status of an image generation request."""

    PENDING = "pending"
    GENERATING = "generating"
    COMPLETED = "completed"
    FAILED = "failed"


class GenerationRequest(BaseModel):
    """Request to generate an image."""

    name: str = Field(description="Human-readable name for this generation")
    prompt: str = Field(min_length=1, description="Image generation prompt text")
    aspect_ratio: AspectRatio = Field(default=AspectRatio.SQUARE, description="Image aspect ratio")
    resolution: Resolution = Field(default=Resolution.TWO_K, description="Image resolution")
    provider: ProviderName = Field(
        default=ProviderName.GEMINI, description="Image generation provider"
    )


class GenerationResponse(BaseModel):
    """Response containing generation metadata."""

    id: str = Field(description="ULID identifier")
    user_id: str = Field(description="User who requested the generation")
    name: str
    prompt: str
    aspect_ratio: str
    resolution: str
    provider: ProviderName = ProviderName.GEMINI
    status: GenerationStatus
    error: str | None = None
    file_path: str | None = None
    file_size: int | None = None
    created_at: datetime
    completed_at: datetime | None = None


class QuotaStatus(BaseModel):
    """Current rate limit quota status."""

    user_id: str
    remaining_tokens: float = Field(description="Available tokens for generation")
    max_tokens: int = Field(description="Maximum token capacity")
    refill_rate: float = Field(description="Tokens refilled per second")
    next_token_at: datetime | None = Field(
        default=None, description="When next token becomes available (if depleted)"
    )


class HealthResponse(BaseModel):
    """Liveness check response."""

    status: Literal["ok"] = "ok"


class ReadyResponse(BaseModel):
    """Readiness check response."""

    status: Literal["ok"] = "ok"
    database: Literal["connected"] = "connected"
    default_provider: str
    providers: list[str]
