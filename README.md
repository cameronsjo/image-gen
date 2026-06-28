# image-gen

Image generation toolkit powered by Gemini 3 Pro. Exposes a REST API and MCP server for generating images with rate limiting, OIDC authentication, and SQLite-backed persistence.

## Quick Start

```bash
# Install dependencies
uv sync

# Run locally (auth disabled, debug logging)
make dev

# Run tests
make test
```

## Configuration

All settings use the `IMAGEGEN_` prefix:

| Variable | Default | Description |
|----------|---------|-------------|
| `IMAGEGEN_GOOGLE_API_KEY` | *required* | Google API key for Gemini |
| `IMAGEGEN_PORT` | `8000` | HTTP server port |
| `IMAGEGEN_DATA_DIR` | `/app/data` | Base directory for image storage |
| `IMAGEGEN_AUTH_ENABLED` | `true` | Enable OIDC/forward-auth |
| `IMAGEGEN_OIDC_ISSUER` | `https://auth.sjo.lol` | OIDC issuer URL |
| `IMAGEGEN_LOG_LEVEL` | `INFO` | Log level |

## Docker

```bash
# Build locally
make docker-build

# Pull from GHCR
docker pull ghcr.io/cameronsjo/image-gen:latest
```

### Verify Image Provenance

Container images are signed with [Cosign](https://github.com/sigstore/cosign) (keyless OIDC) and include SLSA build provenance attestations.

```bash
# Verify build provenance attestation
gh attestation verify oci://ghcr.io/cameronsjo/image-gen:latest \
  --owner cameronsjo
```

## API Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/health` | No | Liveness probe |
| `GET` | `/ready` | No | Readiness probe (DB + model check) |
| `POST` | `/api/generate` | Yes | Generate an image from a text prompt |
| `GET` | `/api/images` | Yes | List generation records |
| `GET` | `/api/images/{id}` | Yes | Get generation metadata |
| `GET` | `/api/images/{id}/file` | Yes | Download generated image |
| `POST` | `/mcp` | JWT | MCP server (Streamable HTTP) |

## MCP Tools

- **`generate_image`** — Generate an image with Gemini 3 Pro (50+ word prompt required)
- **`list_images`** — List recent generations with metadata
- **`get_quota_status`** — Check rate limit quota

## Development / Tooling

### Prerequisites

[uv](https://docs.astral.sh/uv/) manages the Python version and virtual environment.

```bash
uv sync          # Install all runtime + dev dependencies
```

### Linting & Formatting

[Ruff](https://docs.astral.sh/ruff/) handles both linting and formatting:

```bash
uv run ruff check .          # Lint (report only)
uv run ruff check --fix .    # Lint and auto-fix
uv run ruff format .         # Format
uv run ruff format --check . # Format check (CI mode)
```

### Type Checking

[mypy](https://mypy.readthedocs.io/) runs in pragmatic strict mode (untyped defs disallowed, redundant casts warned, implicit optionals rejected):

```bash
uv run mypy src
```

### Tests & Coverage

```bash
uv run pytest                              # Run all tests
uv run pytest --cov=src --cov-report=term-missing   # With coverage report
```

The CI gate requires ≥ 70% coverage across `src/`. This floor is intended to be ratcheted upward as the test suite grows.

### Interactive API Docs

When running locally, the OpenAPI docs are available at:

- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

### Pre-commit Hooks

Install once to run ruff, mypy, and pytest automatically before each commit:

```bash
uv run pre-commit install
```

Run against all files manually:

```bash
uv run pre-commit run --all-files
```

### Quota Notes

Rate limiting uses a token-bucket per user (`IMAGEGEN_QUOTA_MAX_TOKENS` burst, `IMAGEGEN_QUOTA_REFILL_RATE` tokens/second). Quota spans all providers — there are no per-provider buckets. See `.env.example` for all configurable variables.

## License

MIT
