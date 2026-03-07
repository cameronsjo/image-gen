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

## License

MIT
