.DEFAULT_GOAL := help
.PHONY: help install ui ui-dev test serve dev seed demo clean dist publish

# --- dev-only convenience (end users use `pip install open-refinery && open-refinery serve`) ---
# Secrets live in .env (gitignored); `make dev` sources it. DB is a local file.
DEV_DB := sqlite:///$(CURDIR)/devtest.db

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'

install: ## Create venv and install with dev deps (uv)
	uv sync --extra dev

ui: ## Build the dashboard into the package (release step; needs bun)
	cd frontend && bun install && bun run build

ui-dev: ## Run the Vite dev server (proxies API to :8000)
	cd frontend && bun run dev

test: ## Run the test suite
	uv run pytest -q

serve: ## Run the HTTP server (background it yourself: make serve &)
	uv run open-refinery serve

dev: ## Dev server: sources .env for secrets, local devtest.db on :8000
	@test -f .env || { echo "no .env — copy .env.example to .env and set SECRET_KEY"; exit 1; }
	set -a; . ./.env; set +a; DATABASE_URL=$(DEV_DB) PORT=8000 uv run open-refinery serve

seed: ## Seed the local devtest.db with sample data + login tokens
	DATABASE_URL=$(DEV_DB) uv run open-refinery seed

demo: ## Produce one artifact and print its provenance record
	uv run open-refinery demo

clean: ## Remove build artifacts and caches
	rm -rf dist build *.egg-info .pytest_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +

dist: ui ## Build the UI then the sdist + wheel (wheel bundles the SPA)
	uv build

publish: dist ## Build and publish to PyPI (needs token)
	uv publish
