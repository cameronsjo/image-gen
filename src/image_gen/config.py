"""Application configuration via environment variables."""

from pathlib import Path

from pydantic import Field, computed_field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """All settings use the IMAGEGEN_ prefix."""

    model_config = {"env_prefix": "IMAGEGEN_"}

    google_api_key: str = Field(description="Google API key for Gemini")
    port: int = Field(default=8000, description="HTTP server port")
    data_dir: Path = Field(
        default=Path("/app/data"), description="Base directory for image storage"
    )
    db_path: Path | None = Field(
        default=None, description="SQLite database path (defaults to {data_dir}/image-gen.db)"
    )
    gemini_model: str = Field(
        default="gemini-3-pro-image-preview", description="Gemini model identifier"
    )

    # Auth
    auth_enabled: bool = Field(default=True, description="Enable authentication")
    oidc_issuer: str = Field(default="https://auth.sjo.lol", description="OIDC issuer URL")
    oidc_client_id: str = Field(default="image-gen", description="OIDC client identifier")

    # Quota
    quota_max_tokens: int = Field(default=10, description="Maximum burst tokens for rate limiting")
    quota_refill_rate: float = Field(
        default=0.033, description="Token refill rate per second (~2/min)"
    )

    # Logging
    log_level: str = Field(default="INFO", description="Log level")

    @computed_field  # type: ignore[prop-decorator]
    @property
    def resolved_db_path(self) -> Path:
        """Resolve the database path, falling back to data_dir/image-gen.db."""
        return self.db_path if self.db_path is not None else self.data_dir / "image-gen.db"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def images_dir(self) -> Path:
        """Directory where generated images are stored."""
        return self.data_dir / "images"
