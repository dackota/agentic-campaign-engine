.DEFAULT_GOAL := help
.PHONY: help lint fmt test types up down status gateway-check gateway-failover-check env-check up-cluster up-platform status-cluster status-platform

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

up: env-check up-cluster up-platform ## Create the ace cluster and install Substrate, kagent, and agentgateway on it

env-check:
	platform/install.sh check-env

up-cluster:
	platform/cluster.sh up

up-platform:
	platform/install.sh run

down: ## Delete the ace cluster, its registry, and its volume
	platform/cluster.sh down

status: status-cluster status-platform ## Report the ace cluster and platform: ok or FAIL per check

status-cluster:
	platform/cluster.sh status

status-platform:
	platform/status.sh

gateway-check: ## Live: check agents reach OpenCode Go only through agentgateway (needs the cluster)
	scripts/spike/gateway-check.sh

gateway-failover-check: ## Live: check priority failover and per-team token limits in agentgateway (needs the cluster)
	scripts/spike/gateway-failover-check.sh
