# image-gen Makefile

.DEFAULT_GOAL := help

## Development

# Install all dependencies
.PHONY: install
install:
	uv sync --all-extras --dev

# Run the application
.PHONY: run
run:
	uv run python -m image_gen

# Run tests
.PHONY: test
test:
	uv run pytest

# Run linter
.PHONY: lint
lint:
	uv run ruff check .

# Fix lint issues automatically
.PHONY: lint-fix
lint-fix:
	uv run ruff check --fix .

# Format code
.PHONY: format
format:
	uv run ruff format .

# Check formatting without changing files
.PHONY: format-check
format-check:
	uv run ruff format --check .

## Utilities

# Show available targets
.PHONY: help
help:
	@echo "Available targets:"
	@echo ""
	@grep -E '^# .+' Makefile | grep -v '^##' | sed 's/^# /  /' | while read -r line; do \
		read -r target < /dev/stdin || true; \
		printf "  %-20s %s\n" "$$(echo $$target | sed 's/:.*//')" "$$line"; \
	done < /dev/null
	@echo ""
	@awk '/^## /{section=$$0; next} /^# /{desc=substr($$0,3); next} /^\.PHONY:/{next} /^[a-zA-Z_-]+:/{if(desc){if(section){print section; section=""} printf "  %-20s %s\n", $$1, desc; desc=""}}' $(MAKEFILE_LIST) | sed 's/:$$//'
