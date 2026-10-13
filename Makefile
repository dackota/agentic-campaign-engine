.DEFAULT_GOAL := help
.PHONY: seed-demo evals load smoke help lint fmt test types up down status dev gateway-check gateway-failover-check env-check up-cluster up-platform up-observability up-app status-cluster status-platform

help: ## List the targets
	@grep -E '^[a-z_-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "%-8s %s\n", $$1, $$2}'

lint: ## Run ruff, mypy, shellcheck, and eslint (same as CI)
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy
	git ls-files -z '*.sh' | xargs -0 shellcheck -o check-set-e-suppressed
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

# EVALS_ARGS=--update-baseline rewrites the baseline on purpose; nothing else changes it.
evals: ## Run the golden set at fast depth (needs only Docker) and fail on a drop past the baseline margin
	PYTHONPATH=.:apps/engine:apps/api:apps/worker:services/fakes:services/render:services/mcp uv run python -m tests.harness.run_evals --baseline evals/baseline.json --agreement-out evals/judge_agreement.json $(EVALS_ARGS)

# LOAD_ARGS takes the load script's flags, e.g. --campaigns 20 --out load-test.json.
load: ## Run campaigns at once through the Campaign API and write cost, p50/p95 run time, cache hit rate and 429s (ACE_DEPTH=live for the cluster)
	PYTHONPATH=.:apps/engine:apps/api:apps/worker:services/fakes:services/render:services/mcp uv run python -m tests.harness.load $(LOAD_ARGS)

# SEED_ARGS takes the seed's flags, e.g. --api-url http://... --tokens-file tokens.json.
seed-demo: ## Load the demo data (Acme Security, two teams) through the Campaign API; with no --api-url it seeds a fast stack and prints the summary
	PYTHONPATH=.:apps/engine:apps/api:apps/worker:services/fakes:services/render:services/mcp uv run python -m tests.harness.demo_seed $(SEED_ARGS)

types: ## Regenerate the web app's workflow types from the workflow JSON Schema
	uv run python scripts/gen_workflow_types.py

# FULL=1 adds the OpenTelemetry collector and grafana/otel-lgtm, and points every service at them.
COLLECTOR_ENDPOINT := http://otel-collector.observability.svc.cluster.local:4318
ifeq ($(FULL),1)
export ACE_OTEL_ENDPOINT := $(COLLECTOR_ENDPOINT)
endif

up: env-check up-cluster up-platform $(if $(filter 1,$(FULL)),up-observability) up-app ## Create the ace cluster, install the platform, then build, push, and install our app (FULL=1 adds the collector and Grafana)

env-check:
	platform/install.sh check-env

up-cluster:
	platform/cluster.sh up

up-platform:
	platform/install.sh run

up-observability:
	platform/observability.sh run

up-app:
	platform/app.sh run

down: ## Delete the ace cluster, its registry, and its volume
	platform/cluster.sh down

status: status-cluster status-platform ## Report the ace cluster, platform, and app: ok or FAIL per check

smoke: ## Platform smoke test: make up, then one scripted campaign at live depth (spends model tokens)
	platform/smoke.sh

status-cluster:
	platform/cluster.sh status

status-platform:
	platform/status.sh

dev: ## Run Tilt on the ace cluster: saving a web file rebuilds and replaces the web pod (run make up first)
	platform/dev.sh

gateway-check: ## Live: check agents reach OpenCode Go only through agentgateway (needs the cluster)
	scripts/spike/gateway-check.sh

gateway-failover-check: ## Live: check priority failover and per-team token limits in agentgateway (needs the cluster)
	scripts/spike/gateway-failover-check.sh
