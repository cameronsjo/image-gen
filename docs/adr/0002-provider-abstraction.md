# ADR 0002: Provider Abstraction

**Date:** 2026-06-27
**Status:** Accepted
**Track:** B (Providers)

## Context

`image-gen` v0.1.5 hardcodes Google Gemini as the sole image generation backend. The
service layer (`GeminiService`) is called directly from the API endpoint and MCP tool,
making it impossible to select a different provider without code changes. Users also have
no way to route a single request to a specific backend.

## Decision

Replace the hardcoded `GeminiService` with a **provider abstraction layer** consisting of:

1. **`ImageProvider` ABC** (`services/provider.py`) with a single async method
   `generate_image(prompt, aspect_ratio, resolution) -> ProviderResult`.  All providers
   implement this contract.

2. **`ProviderResult` dataclass** — replaces `GeminiResult`; carries `image_data: bytes`
   and `mime_type: str`.

3. **Three concrete providers:**
   - `GeminiProvider` (refactored from `GeminiService`) — Google Gemini direct.
   - `OpenAIProvider` — OpenAI `gpt-image-2` via the official async Python SDK.
   - `OpenRouterProvider` — Any OpenRouter image model via plain `httpx`.

4. **`build_registry(settings) -> dict[str, ImageProvider]`** — instantiates only
   providers whose API key is present; fails fast if `settings.default_provider` is not
   in the resulting registry.

5. **Per-request provider selection** — `GenerationRequest.provider: ProviderName`
   (default: `ProviderName.GEMINI`); the API endpoint and MCP tool look up the provider
   in `app.state.provider_registry`.

6. **`ProviderName(StrEnum)`** — `GEMINI | OPENAI | OPENROUTER`; added to
   `GenerationRequest`, `GenerationResponse`, and the `generations` DB table
   (idempotent `ALTER TABLE … ADD COLUMN provider TEXT NOT NULL DEFAULT 'gemini'`).

## Consequences

**Positive:**
- Providers are interchangeable at request time with zero code change.
- New providers need only implement `ImageProvider` and register an API key.
- Misconfiguration (missing key for default provider) surfaces at startup, not at
  request time.
- `GeminiProvider` now retries on typed `genai_errors.ServerError` (not substring
  matching) and wraps the blocking SDK call in `asyncio.timeout(settings.request_timeout_seconds)`.
- `ReadyResponse` reports available providers and the configured default instead of a
  hardcoded Gemini model name.

**Trade-offs:**
- `app.state.gemini` is removed; callers that referenced it directly must update to
  `app.state.provider_registry["gemini"]`. (`test_auth.py` required a one-line update.)
- `ProviderNotConfiguredError` at startup means the service will not start if the
  configured default provider's API key is absent — intentional fail-fast behaviour.
- OpenAI `gpt-image-2` always returns base64 regardless of `response_format`; we
  request `b64_json` explicitly for clarity. The SDK (v2.44.0) natively accepts a
  `timeout` parameter, used in preference to `asyncio.timeout` wrapping.
- OpenRouter has no official Python SDK; `httpx.AsyncClient` is used directly with
  bearer auth. The response shape (`data[0].b64_json`) is the same as OpenAI's.

## Param Mapping

| Canonical | OpenAI | OpenRouter |
|-----------|--------|------------|
| 1K | quality=`low`, ~1024 long edge | quality=`low`, ~1024 long edge |
| 2K | quality=`medium`, ~2048 long edge | quality=`medium`, ~2048 long edge |
| 4K | quality=`high`, ~3840 long edge (capped) | quality=`high`, ~3840 long edge (capped) |
| aspect_ratio | `WxH` (divisible by 16, long edge = base) | `WxH` (same computation) |

All canonical `AspectRatio` values (1:1 through 21:9) fall within OpenAI's supported
1:3–3:1 range. `UnsupportedParameterError` is raised only for unknown ratio/resolution
strings.

## Rejected Alternatives

- **Alias `app.state.gemini`** — The spec prohibits aliases; it would hide the fact that
  the architecture changed and confuse future readers.
- **OpenRouter-only multi-provider** — Loses full OpenAI parameter surface (arbitrary
  size, background control, output format). Keeping both provides maximum control.
- **Per-provider quotas** — YAGNI; quota stays per-user across all providers.
