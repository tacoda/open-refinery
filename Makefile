.DEFAULT_GOAL := help
.PHONY: help install test run build up down logs shell clean dist publish

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'

install: ## Create venv and install with dev deps (uv)
	uv sync --extra dev

test: ## Run the test suite
	uv run pytest -q

run: ## Run the CLI locally (pass ARGS="--text hi")
	uv run open-refinery $(ARGS)

build: ## Build the Docker image
	docker compose build

up: ## Start the stack (detached)
	docker compose up -d

down: ## Stop the stack
	docker compose down

logs: ## Tail container logs
	docker compose logs -f

shell: ## Open a shell in the running container
	docker compose exec app /bin/bash

clean: ## Remove build artifacts and caches
	rm -rf dist build *.egg-info .pytest_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +

dist: ## Build sdist + wheel
	uv build

publish: dist ## Build and publish to PyPI (needs token)
	uv publish
