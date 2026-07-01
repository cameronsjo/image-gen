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

## Providers / Configuration

image-gen supports multiple image generation backends. Set at least one provider API key;
the service will start only the providers whose keys are present.

### Provider API Keys

| Variable | Provider | Description |
|----------|----------|-------------|
| `IMAGEGEN_GOOGLE_API_KEY` | Gemini | Google API key for Gemini 3 Pro |
| `IMAGEGEN_OPENAI_API_KEY` | OpenAI | OpenAI API key (gpt-image-2) |
| `IMAGEGEN_OPENROUTER_API_KEY` | OpenRouter | OpenRouter API key |

### Default Provider

```bash
IMAGEGEN_DEFAULT_PROVIDER=gemini   # gemini | openai | openrouter (default: gemini)
```

The service fails to start if `IMAGEGEN_DEFAULT_PROVIDER` names a provider whose key
is absent.

### Per-Request Provider Selection

Include a `provider` field in `POST /api/generate` or the MCP `generate_image` tool:

```json
{
  "name": "my-image",
  "prompt": "...",
  "provider": "openai"
}
```

Unknown or unconfigured providers return HTTP 422 with `available_providers`.

### Per-Request Model Selection

Include an optional `model` field to override the provider's configured default for a single request:

```json
{
  "name": "my-image",
  "prompt": "...",
  "provider": "gemini",
  "model": "gemini-2.5-flash-image"
}
```

Omitting `model` uses the provider's configured default (see `IMAGEGEN_GEMINI_MODEL` etc. above).
An explicit model is validated against the list discovered at startup; if the requested model is
absent, the API returns HTTP 422 with `available_models`. If discovery degraded for a provider,
the allowlist falls back to the configured default alone (fail-closed) — only the default is
accepted until discovery recovers. The selected model is persisted in the DB and echoed back in
the response.

Available models per provider are advertised on `GET /ready` under `models: { provider: [ids] }`,
with the configured default listed first. The web UI populates its model dropdown from this
endpoint at startup.

### Provider Models

| Variable | Default | Description |
|----------|---------|-------------|
| `IMAGEGEN_GEMINI_MODEL` | `gemini-3-pro-image-preview` | Gemini model |
| `IMAGEGEN_OPENAI_MODEL` | `gpt-image-2` | OpenAI image model |
| `IMAGEGEN_OPENROUTER_MODEL` | `openai/gpt-image-2` | OpenRouter model id |
| `IMAGEGEN_REQUEST_TIMEOUT_SECONDS` | `120.0` | Provider call timeout |

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
| `GET` | `/ready` | No | Readiness probe (DB + providers + discovered models) |
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
