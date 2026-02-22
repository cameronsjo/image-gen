FROM python:3.12-slim AS builder

# Install uv for fast dependency resolution
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Install dependencies first (cached layer)
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

# Copy source and install the project
COPY src/ src/
RUN uv sync --frozen --no-dev

# --- Runtime stage ---
FROM python:3.12-slim

LABEL org.opencontainers.image.source="https://github.com/cameronsjo/image-gen"
LABEL org.opencontainers.image.description="Image generation toolkit powered by Gemini 3 Pro"
LABEL org.opencontainers.image.licenses="MIT"

# Non-root user
RUN groupadd --gid 1000 appuser && \
    useradd --uid 1000 --gid 1000 --create-home appuser

WORKDIR /app

# Copy the virtual environment from builder
COPY --from=builder /app/.venv /app/.venv

# Default data directory
RUN mkdir -p /app/data/images && chown -R appuser:appuser /app/data

ENV PATH="/app/.venv/bin:$PATH" \
    IMAGEGEN_DATA_DIR=/app/data \
    IMAGEGEN_PORT=8000

EXPOSE 8000

USER appuser

HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:8000/health').raise_for_status()"

ENTRYPOINT ["python", "-m", "image_gen"]
