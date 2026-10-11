#!/usr/bin/env bash
# The platform smoke test: bring the platform up, then run one scripted campaign at live
# depth. The campaign goes through the Campaign API to the real kagent email writer, which
# calls the model through agentgateway, then to approval and a send on the fake Marketo.
# Live depth spends model tokens. Usage: smoke.sh
set -euo pipefail
cd "$(dirname "$0")/.."
make up
ACE_DEPTH=live uv run pytest "tests/api/test_campaign_approval.py::test_run_waits_for_approval_after_draft_and_api_can_approve"
