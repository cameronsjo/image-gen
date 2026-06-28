# image-gen: standards + multi-provider + bug-hunt

> Approved plan, executed 2026-06-27. Three parallel git worktrees behind a frozen
> interface contract; orchestrator commits the foundation, dispatches, and resolves
> conflicts at integration.

## Context

`image-gen` (v0.1.5) is a self-hosted FastAPI + FastMCP service that generates images
via Google Gemini, persisting metadata to SQLite and files to disk. MVP-grade: Gemini
hardcoded into the service layer, several real bugs (including a multi-tenant data leak),
engineering-standards gaps (no type checking, no coverage gate, no custom error model).

Three things at once, in three parallel worktrees:

1. **Standards** — tooling/tests/error-handling to a production bar.
2. **Providers** — OpenAI (`gpt-image-2`) *and* an OpenRouter adapter behind a provider
   abstraction, selectable **per request** with a configured default.
3. **Bugs / polish** — fix verified defects (security-critical first).

### Decisions

| Decision | Choice |
|---|---|
| OpenAI reach | Build both — OpenAI-direct provider + OpenRouter adapter |
| Provider selection | Per request, with a configured default |
| Standards scope | Full pragmatic pass (no PyPI/py.typed/console-scripts — it's a service) |
| Rollout | Full parallel worktrees, orchestrator resolves conflicts |

### Verified findings (read at file:line)

- **Data leak (Critical):** `api/images.py:21,28,40` — `list_images`/`get_image`/`get_image_file`
  ignore the user; any authed user can read any image. `repository.list_generations` has a
  `user_id` filter callers never pass.
- **Quota TOCTOU (Critical):** `services/quota.py:52-85` — `consume_token` is read→refill→UPDATE
  across separate autocommits; concurrent calls all pass the `tokens < 1.0` gate.
- **MCP identity (High):** `mcp/tools.py:166` hardcodes `"mcp-user"`; `list_images` never filters.
- **Gemini retry (High):** `services/gemini.py:92` retries on substring `"503"`/`"UNAVAILABLE"`.
- **No call timeout (High):** `services/gemini.py:72` `asyncio.to_thread(...)` has no timeout.
- **Health (Med):** `api/health.py` runs `SELECT 1` but never `fetchone()`s it.
- **Path containment (Med):** image download trusts the id is a ULID.

## Frozen interface contract

`src/image_gen/exceptions.py` (foundation commit): `ImageGenError` base + `ProviderError`,
`ProviderNotConfiguredError`, `UnsupportedParameterError`, `QuotaExceededError`, `StorageError`.

`src/image_gen/services/provider.py` (Track B): `@dataclass ProviderResult(image_data: bytes,
mime_type: str)`; `ImageProvider(ABC)` with `name`, `model_name` property, and
`async generate_image(prompt, aspect_ratio="1:1", resolution="2K") -> ProviderResult`.
`ProviderResult` *replaces* `GeminiResult` (rename). Canonical request vocab stays the
existing `AspectRatio` + `Resolution` enums; providers map canonical→own params and raise
`UnsupportedParameterError` for combos they can't honor.

`provider: ProviderName` added to `GenerationRequest`, `GenerationResponse`, MCP
`generate_image` params, `generations` table. `ProviderName(StrEnum) = {GEMINI, OPENAI, OPENROUTER}`.

Config: `google_api_key: str | None = None` (now optional), `openai_api_key`, `openrouter_api_key`,
`default_provider: ProviderName = GEMINI`, `request_timeout_seconds: float = 120.0`. Startup builds
a registry of providers whose key is present; fails fast if `default_provider` unavailable;
per-request provider not in registry → 422.

`app.state.provider_registry: dict[str, ImageProvider]` replaces `app.state.gemini` (no alias).

### Orchestrator-frozen signatures (keep call-sites stable across worktrees)

- `QuotaService.consume_token(user_id) -> bool` — **signature frozen** (True=consumed,
  False=denied). C makes it atomic internally; callers (B-owned generate.py/mcp) unchanged.
- `repository.create_generation(..., provider: str = "gemini")` — provider defaults so
  A's repository tests and existing callers stay valid.
- `conftest.py` `client` / `settings` / `tmp_data_dir` fixture contracts preserved by B.

### Ownership reassignments from the plan (orchestrator's "resolve conflicts" mandate)

- `health.py` → **Track B** (builds `ReadyResponse`, reads `app.state.gemini` — both B contracts;
  B folds the `fetchone()` fix into the `ready()` rewrite). C does not touch it.
- `quota.py` + `storage.py` tests → **Track C** (owns those files). `repository.py` CRUD tests → **Track A**.
- Shared test files are single-owner: only B edits `conftest.py`; C/A add *new* test files.

## Track ownership

- **B (providers, Sonnet, `feat/providers`):** `services/gemini.py`, `services/provider.py` (new),
  `services/openai_provider.py` (new), `services/openrouter_provider.py` (new), `services/registry.py`
  (new), `api/generate.py`, `api/health.py`, `models.py`, `db/repository.py` (provider column),
  `db/migrations.py`, provider parts of `config.py`/`app.py`/`mcp/tools.py`, `conftest.py`,
  B-owned tests, README provider section, ADR `0002-provider-abstraction.md`. Adds only `openai`
  to `[project].dependencies`.
- **C (hardening/security, Opus, `fix/hardening`):** `api/images.py`, `services/quota.py`,
  `services/storage.py`, security parts of `mcp/tools.py`. New tests: isolation, quota concurrency,
  storage containment. Does NOT touch gemini/generate/health/models/config/app.
- **A (standards, Sonnet, `chore/standards`):** `pyproject.toml` (tooling/dev sections only),
  `.pre-commit-config.yaml` (new), `.editorconfig` (new), `.env.example` (new), `ci.yml`,
  `middleware.py` (new) + 1 `add_middleware` line, `test_repository.py` (new), README/docs/ADR.

## Conflict map & integration order

| File | Owner(s) | Risk |
|---|---|---|
| gemini/generate/provider*/models/registry/health | B only | none |
| images/quota/storage | C only | none |
| pyproject/ci/dotfiles/middleware | A only (disjoint sections) | none |
| exceptions.py | foundation | none |
| **mcp/tools.py** | B + C | **2-way — real** |
| app.py | B (lifespan/factory) + A (1 middleware line) | minor |
| config.py | B | none |

**Merge order: foundation → B → C → A.** C rebases onto B (resolve mcp/tools.py). A rebases
onto B+C (cross-tree mypy fix pass + coverage only meaningful once all code present). Final:
`cadence-forge:security-reviewer` on C's diff, `cadence:code-reviewer` over integrated diff,
full suite green, then PR.

**Mechanism:** three `Agent` dispatches with `isolation: "worktree"` (branch from
foundation-committed `origin/main`), C=Opus. Orchestrator verifies each diff against the
filesystem before merging — not self-reports. One integration branch; commits grouped by track.

## Verification

```bash
uv sync
uv run ruff check . && uv run ruff format --check .
uv run mypy src
uv run pytest --cov=src --cov-report=term-missing
```

E2E (auth off): `POST /api/generate` per provider → 201 + file; unknown/unconfigured → 422;
two `Remote-User` headers confirm `/api/images` + `/file` only return the caller's own;
`quota_max_tokens + 5` concurrent generates → no over-grant; `/ready` 200 only when DB responds;
MCP `generate_image`/`list_images`/`get_quota_status` per-user scoped + provider choice.

## Out of scope (YAGNI)

PyPI publication, `py.typed`, console-script entry points; admin/group-wide image visibility;
per-provider quotas (quota stays per-user across providers); streaming image responses.
