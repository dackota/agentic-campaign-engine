.DEFAULT_GOAL := help
.PHONY: help lint fmt test types up down status gateway-check gateway-failover-check

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

test: ## Run both seams at fast depth (needs only Docker) and the web unit tests; live spike tests also run when k3d-ace-spike is up (they spend OpenCode Go tokens)
	uv run pytest
	pnpm install --frozen-lockfile
	pnpm --filter web test
	pnpm --filter web exec playwright install --with-deps chromium
	pnpm --filter web e2e

types: ## Regenerate the web app's workflow types from the workflow JSON Schema
	uv run python scripts/gen_workflow_types.py

up: ## Create the ace cluster (checks tools, .env, and free Docker memory first)
	platform/cluster.sh up

down: ## Delete the ace cluster, its registry, and its volume
	platform/cluster.sh down

status: ## Report the ace cluster: ok or FAIL per check
	platform/cluster.sh status

gateway-check: ## Live: check agents reach OpenCode Go only through agentgateway (needs the cluster)
	scripts/spike/gateway-check.sh

gateway-failover-check: ## Live: check priority failover and per-team token limits in agentgateway (needs the cluster)
	scripts/spike/gateway-failover-check.sh
