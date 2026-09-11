# Dynamic model selection via provider discovery

## Context

The designed web UI has a **model** dropdown, but the backend has no concept of a
model: each provider is hardwired to one configured model (`settings.gemini_model`
etc.), `generate_image()` takes no model argument, `/ready` reports no models, and
there is no `model` column. Cameron wants to select among a provider's image models.

Rather than hardcode model IDs (a wrong ID 500s at the provider), **discover them at
runtime** from each provider's list-models API. Verified feasible:

- **OpenRouter** — `GET https://openrouter.ai/api/v1/models` (public); keep entries
  whose `architecture.output_modalities` contains `"image"` (9 today).
- **OpenAI** — `client.models.list()` has no capability field; filter ids matching
  `gpt-image*` / `dall-e*`.
- **Gemini** — `client.models.list()` exposes `supported_actions`; filter models whose
  `name` contains `image`/`imagen` (Imagen deprecates 2026-08 → `gemini-2.5-flash-image`).

The configured default model is always unioned in, so discovery failure never removes
the working default. The design's `loadReady()` already reads `data.models`, so
surfacing models on `/ready` lights up the dropdown with **no UI change**.

## Approach

Discovery runs **once at startup** (best-effort, per-provider try/except + timeout),
cached in `app.state.provider_models`. This keeps `/ready` cheap (no per-call network);
a restart refreshes. The configured default is placed first in each list.

### Changes

1. **`models.py`** — `GenerationRequest.model: str | None = None`;
   `GenerationResponse.model: str | None = None`; `ReadyResponse.models: dict[str, list[str]] = {}`.

2. **`services/provider.py`** — `ImageProvider`:
   - `generate_image(..., model: str | None = None)` (new trailing arg).
   - `async def list_models(self) -> list[str]` with a default returning `[self.model_name]`;
     each provider overrides with discovery.

3. **Providers** (`gemini.py`, `openai_provider.py`, `openrouter_provider.py`):
   - At the top of `generate_image`, resolve `model = model or self._model` and use it
     where `self._model` is currently passed.
   - Implement `list_models()` using the provider's existing client:
     - OpenAI: `await self._client.models.list()`, filter id `^(gpt-image|dall-e)`.
     - OpenRouter: GET the public models URL via the pooled `httpx` client, filter by
       `output_modalities` containing `"image"`.
     - Gemini: `await asyncio.to_thread(self._client.models.list)`, filter by name.
   - Each wraps its own call so a failure returns `[self.model_name]`; union the
     configured default in, first.

4. **`services/registry.py`** — add
   `async def discover_models(registry, timeout) -> dict[str, list[str]]` that calls each
   provider's `list_models()` under `asyncio.timeout`, falling back to `[model_name]` on
   error/timeout. Pure orchestration; keeps `app.py` lean.

5. **`app.py`** (lifespan) — after `build_registry`, call `discover_models` and store
   `app.state.provider_models`. Non-fatal.

6. **`api/health.py`** (`/ready`) — return `models=request.app.state.provider_models`.

7. **`api/generate.py`** — resolve `model = body.model or provider.model_name`; if
   `body.model` is set and the provider's cached list is non-empty and excludes it →
   `HTTPException(422, {error, available_models})` (mirrors the provider-not-configured
   shape). Pass `model` to `generate_image`; pass `model=model` to `create_generation`.

8. **`db/migrations.py`** — add `_add_model_column` mirroring `_add_provider_column`
   (idempotent `PRAGMA table_info` guard, `ADD COLUMN model TEXT`).

9. **`db/repository.py`** — `create_generation(..., model: str | None = None)` inserts
   `model`; `_row_to_response` reads it defensively (`"model" in row.keys()`); include in
   both returned `GenerationResponse`s.

### Reuse

- Idempotent-column pattern: `db/migrations.py:_add_provider_column`.
- 422 detail shape: `api/generate.py:41` (provider-not-configured).
- Defensive row read: `db/repository.py:_row_to_response`.
- Per-provider clients already pooled (`AsyncOpenAI`, `httpx.AsyncClient`, `genai.Client`).

## Verification

- **Unit**: each provider's `list_models()` filters a mocked list response correctly and
  falls back to `[model_name]` on error; `discover_models` tolerates a failing provider.
- **API** (existing async `client` fixture, `tests/test_*`): `/ready` includes `models`
  with the gemini default; `POST /api/generate` persists + echoes `model`; bad `model` →
  422 with `available_models`; omitted `model` uses the provider default.
- **Migration**: `model` column added idempotently; pre-migration rows read back with
  `model=None`.
- **Gates**: `uv run pytest`, `uv run ruff check .`, `uv run mypy src`.
- **Live** (`make dev`, real key): `/ready` lists discovered models → UI dropdown
  populated per provider → generate with a chosen model → metadata/history show it.

## Notes / risks

- Startup discovery adds best-effort network calls to boot; bounded by `asyncio.timeout`
  and per-provider try/except — a down list-API degrades to `[default]`, never blocks boot.
- OpenAI/Gemini filters are heuristic (id/name); the configured default is always present.
- Test mocks (MagicMock gemini client) make discovery raise → fallback `[default]`; the
  try/except keeps the suite green.
- Repo-side `index.html` edits are clobbered on the next design re-export, but this work is
  backend + `/ready`; the page needs no change.
