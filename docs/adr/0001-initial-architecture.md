# ADR 0001: Initial Architecture

## Status

Accepted

## Context

Starting a new image generation project. Need to establish the foundational tooling, language, and project structure.

## Decision

- **Language:** Python 3.12+ with uv for package management
- **Linting/Formatting:** Ruff
- **CI/CD:** GitHub Actions with Release Please for automated versioning
- **Structure:** `src/` for application code, `docs/` for documentation

## Consequences

- uv provides fast, reliable dependency resolution
- Ruff replaces multiple tools (flake8, black, isort) with a single fast linter/formatter
- Release Please automates changelog and version bumps from conventional commits
