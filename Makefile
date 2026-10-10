.DEFAULT_GOAL := help
.PHONY: help lint fmt test up down gateway-check

help: ## List the targets
	@grep -E '^[a-z_-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "%-8s %s\n", $$1, $$2}'

lint: ## Run ruff, mypy, and eslint (same as CI)
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy
	pnpm install --frozen-lockfile
	pnpm --filter web lint

fmt: ## Format Python and fix lint
	uv run ruff check --fix .
	uv run ruff format .

test: ## Run both seams at fast depth (needs only Docker) and the web unit tests
	uv run pytest
	pnpm install --frozen-lockfile
	pnpm --filter web test
	pnpm --filter web exec playwright install --with-deps chromium
	pnpm --filter web e2e

up: ## Stub: start the local cluster (a later ticket fills it)
	@echo "up: not implemented yet"

down: ## Stub: stop the local cluster (a later ticket fills it)
	@echo "down: not implemented yet"

gateway-check: ## Live: check agents reach OpenCode Go only through agentgateway (needs the cluster)
	scripts/spike/gateway-check.sh
