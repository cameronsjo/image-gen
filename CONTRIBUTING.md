# Contributing to image-gen

Thanks for your interest in contributing! This guide will help you get started.

## Code of Conduct

Be respectful and constructive. We follow the [Contributor Covenant](https://www.contributor-covenant.org/version/2/1/code_of_conduct/).

## Getting Started

1. Fork the repository
2. Clone your fork:

   ```bash
   git clone https://github.com/<your-username>/image-gen.git
   cd image-gen
   ```

3. Set up the development environment:

   ```bash
   uv sync
   ```

4. Create a branch for your work:

   ```bash
   git checkout -b feat/your-feature
   ```

## Development Setup

### Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) for package management
- [mise](https://mise.jdx.dev/) for runtime version management (optional)

### Running Tests

```bash
uv run pytest
```

### Linting

```bash
uv run ruff check .
uv run ruff format .
```

## Commit Format

We use [Conventional Commits](https://www.conventionalcommits.org/):

```
type(scope): description

[optional body]
```

Types: `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`, `ci`

## Pull Requests

- Keep PRs focused on a single change
- Reference related issues with closing keywords (`Closes #123`)
- Ensure CI passes before requesting review
- Write descriptive PR titles using conventional commit format
