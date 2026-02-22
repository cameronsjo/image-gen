# image-gen

Image generation toolkit powered by Gemini 3 Pro.

## Commands

```bash
uv sync              # Install dependencies
uv run pytest        # Run tests
uv run ruff check .  # Lint
uv run ruff format . # Format
make help            # Show available targets
```

## Project Structure

```
image-gen/
  src/           # Application source code
  docs/          # Documentation
  docs/adr/      # Architecture Decision Records
```

## Conventions

- Python 3.12+, managed with uv
- Ruff for linting and formatting
- Conventional Commits for git messages
- Release Please for versioning

## Landing the Plane (Session Completion)

**When ending a work session**, you MUST complete ALL steps below. Work is NOT complete until `git push` succeeds.

**MANDATORY WORKFLOW:**

1. **File issues for remaining work** - Create issues for anything that needs follow-up
2. **Run quality gates** (if code changed) - Tests, linters, builds
3. **Update issue status** - Close finished work, update in-progress items
4. **PUSH TO REMOTE** - This is MANDATORY:
   ```bash
   git pull --rebase
   bd sync
   git push
   git status  # MUST show "up to date with origin"
   ```
5. **Clean up** - Clear stashes, prune remote branches
6. **Verify** - All changes committed AND pushed
7. **Hand off** - Provide context for next session

**CRITICAL RULES:**
- Work is NOT complete until `git push` succeeds
- NEVER stop before pushing - that leaves work stranded locally
- NEVER say "ready to push when you are" - YOU must push
- If push fails, resolve and retry until it succeeds
