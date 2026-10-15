# Usage metadata — issue #23

Cameron authorized Phase 2 via the cos-imagegen2 GO file. Codex owns this issue branch.

- [x] Capture optional OpenRouter prompt/completion/total tokens and cost_details.
- [x] Store an additive nullable usage_json value; expose usage in generation metadata.
- [x] Persist metadata for REST and MCP generation paths; retain legacy-row compatibility.
- [x] Verify mocked-provider, REST, MCP and migration boundaries locally.
- [x] Independent code review completed with no supported findings.

Delivery (commit, push, ready PR and CI) is recorded in the run report; merging is not authorized.

`uv run --no-sync ruff check .`, `uv run --no-sync ruff format --check .`,
`uv run --no-sync mypy src`, and `uv run --no-sync pytest --cov=src --cov-report=term-missing --cov-fail-under=70`
passed (316 tests, 90.14% coverage). `uv build` produced a wheel and sdist.
The shared cache lives beside worktrees so it cannot enter the source distribution.
Release Please owns CHANGELOG.md; the feature commit supplies its release note.
