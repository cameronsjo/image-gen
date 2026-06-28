# ADR 0003 — Engineering Standards Baseline

**Date:** 2026-06-27
**Status:** Accepted

## Context

image-gen v0.1.5 is MVP-grade: no static type checking, no coverage gate, no pre-commit hooks,
no request tracing, and missing dotfiles that every contributor relies on. Before adding
multi-provider support (ADR 0002) and security hardening, these gaps should be closed so
defects surface at authoring time rather than in production.

## Decisions

### 1. Type checking — mypy, pragmatic strict

`mypy` runs in pragmatic strict mode: `disallow_untyped_defs`, `warn_unused_ignores`,
`warn_redundant_casts`, `no_implicit_optional`, `check_untyped_defs`. Full `strict` mode is
excluded because FastAPI and pydantic use heavy generic machinery whose stubs have gaps; the
chosen flags catch real bugs without fighting the framework.

### 2. Coverage gate — 70% floor in CI

`pytest-cov` enforces `--cov-fail-under=70` in the CI test step. The threshold is intentionally
conservative: it is realistic for the current codebase (service integrations require mocking
that the initial pass deferred), and it is designed to be ratcheted upward in subsequent PRs.
The gate is CI-only; local and pre-commit pytest runs omit it to stay fast.

### 3. Pre-commit hooks

`.pre-commit-config.yaml` wires four hooks:

| Hook | Purpose |
|---|---|
| `ruff` (with `--fix`) | Auto-fix linting violations |
| `ruff-format` | Enforce formatting |
| `mypy` (local) | Type-check `src/` |
| `pytest -q` (local, no cov-fail) | Fast smoke test |

### 4. Request-ID middleware — raw ASGI

`RequestIDMiddleware` is implemented as a raw ASGI middleware (class with `__init__` / `__call__`)
rather than Starlette's `BaseHTTPMiddleware`. `BaseHTTPMiddleware` buffers the response body,
which breaks the MCP server's SSE streaming at `/mcp` — the same reason `MCPSlashRewrite` is
raw ASGI. The middleware reads an incoming `X-Request-ID` header (falling back to a `uuid4` hex),
binds it to structlog context-vars for automatic log correlation, and echoes it in the response.

### 5. Dotfiles

- `.editorconfig` — utf-8, LF line endings, 4-space indent for Python, trim trailing whitespace.
- `.env.example` — canonical list of all `IMAGEGEN_*` variables with comments; includes the new
  provider keys from ADR 0002 (`IMAGEGEN_OPENAI_API_KEY`, `IMAGEGEN_OPENROUTER_API_KEY`,
  `IMAGEGEN_DEFAULT_PROVIDER`, `IMAGEGEN_REQUEST_TIMEOUT_SECONDS`).

## Consequences

- mypy and coverage failures block CI merges.
- New code must carry type annotations; third-party stubs are `ignore_missing_imports = true`
  to keep iteration velocity high.
- Contributors get a consistent editor experience without manual setup.
- Every HTTP response carries a `X-Request-ID` for log correlation at zero application-code cost.
