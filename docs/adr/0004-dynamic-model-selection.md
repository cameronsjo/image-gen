# ADR 0004: Dynamic Model Selection via Provider Discovery

**Date:** 2026-06-28
**Status:** Accepted

## Context

ADR 0002 made the image-generation *provider* selectable per request, but each
provider stayed pinned to a single configured model (`settings.gemini_model` etc.).
The web UI (ADR 0003 / the `/ui` page) ships a **model** dropdown with no backend to
feed it: `generate_image()` took no model argument, `/ready` reported no models, and
the `generations` table had no `model` column.

Hardcoding a per-provider model list is brittle — a wrong or retired id 500s at the
provider, and the lists drift as providers add and deprecate models (Imagen deprecates
2026-08 in favour of `gemini-2.5-flash-image`). We want the dropdown populated from
*what each provider actually serves*, without a code change every time that set moves.

## Decision

Discover each provider's image models **at runtime** and let a request select one.

1. **`ImageProvider.list_models() -> list[str]`** (ADR 0002) — each provider queries
   its own list-models API and filters to image-capable models using the only
   capability signal that API exposes:
   - **OpenAI** — `client.models.list()` has no capability field; filter ids matching
     `^(gpt-image|dall-e)`.
   - **OpenRouter** — public `GET /api/v1/models`; keep entries whose
     `architecture.output_modalities` contains `"image"`.
   - **Gemini** — `client.models.list()` (run in a worker thread, fully materialised
     there so lazy paging never blocks the event loop); keep names containing
     `image`/`imagen`, stripping the `models/` prefix.

   Every override wraps its own call so any failure degrades to `[self.model_name]`
   (via `models_with_default`, which guarantees the configured default leads the list
   and de-duplicates). Discovery failure therefore never removes the working default.

2. **`registry.discover_models(registry, timeout)`** — runs every provider's
   `list_models()` **concurrently** (`asyncio.gather`), each bounded by its own
   `asyncio.timeout`; on error or timeout that provider degrades to `[model_name]`.
   Concurrency means boot waits at most one timeout, not the sum across providers.

3. **Startup cache** — the FastAPI lifespan calls `discover_models` once after
   `build_registry` and stores the result in `app.state.provider_models`
   (`dict[str, list[str]]`). Discovery is best-effort and non-fatal: a total failure
   logs and falls back to `{}`. The per-provider bound is `_MODEL_DISCOVERY_TIMEOUT =
   10.0` s — well under the (longer) generation timeout. A restart refreshes the cache;
   `/ready` stays cheap (no per-request network).

4. **`/ready` advertises models** — `ReadyResponse.models: dict[str, list[str]]`
   returns the cache (configured default first per provider). The UI's `loadReady()`
   already reads `data.models`, so the dropdown lights up with **no UI change**.

5. **Per-request model + fail-closed validation** — `GenerationRequest.model: str |
   None` (omit → provider default). The endpoint validates against the discovered list,
   or — when discovery degraded to an empty list — against `[provider.model_name]`
   alone. An explicit model outside that allowlist returns **HTTP 422** with
   `available_models` (mirroring the provider-not-configured 422 shape). The resolved
   model is passed to `generate_image()` and persisted.

6. **`model` DB column** — `GenerationResponse.model: str | None`; an idempotent
   `ALTER TABLE generations ADD COLUMN model TEXT` (nullable) added via the shared
   `_add_column_if_missing` migration helper. Rows written before the migration — and
   MCP-initiated rows, which carry no model — read back as `model=None`.

## Consequences

**Positive:**
- The model dropdown reflects each provider's live catalogue; new models appear on a
  restart with no code change.
- A wrong/retired model id is rejected with a 422 listing valid models, instead of a
  500 from the provider.
- Discovery is resilient: a down list-API degrades that provider to its configured
  default and never blocks boot or removes a working model.

**Trade-offs:**
- Startup makes best-effort network calls (bounded, concurrent, per-provider
  try/except). A slow list-API costs up to `_MODEL_DISCOVERY_TIMEOUT` at boot.
- The OpenAI and Gemini filters are heuristic (id prefix / name substring); the
  configured default is always unioned in, so a heuristic miss never hides it.
- The model set is a startup snapshot, not live — a model added after boot is invisible
  until restart. Acceptable: keeps `/ready` and the request path free of network I/O.
- MCP generation is unchanged (no model argument); MCP rows persist `model=None` and use
  the provider default. Threading a model through the MCP tool is a possible follow-up.

## Rejected Alternatives

- **Hardcode per-provider model lists** — brittle and drifts; a retired id 500s at the
  provider and lists rot without maintenance. Runtime discovery is self-maintaining.
- **Discover per request** — adds a network round-trip (and its failure modes) to every
  generation. The startup cache keeps the hot path local; a restart is the refresh.
- **Fail *open* on degraded discovery** (the original plan) — when the cache was empty,
  accept any model string and let the provider reject it. Rejected after security
  review: an arbitrary string would reach the provider API on the server's key and be
  persisted. Failing closed to the configured default is the conservative default; the
  cost (only the default is usable while discovery is fully degraded) is acceptable
  because per-provider failures already degrade to `[default]`, never `[]`.
