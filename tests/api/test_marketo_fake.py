"""Seam 1 at fast depth: the fake Marketo speaks OAuth2 client credentials, holds programs,
and takes A/B sends. One approval publishes one program with one send of both variants,
and a retried publish never sends twice. Read on the fake's own REST API."""

import httpx

from tests.api.helpers import (
    MARKETO_HTTP_TIMEOUT_SECONDS,
    MARKETO_PROGRAMS_PATH,
    SENT,
    create,
    marketo_programs,
    marketo_sends,
    marketo_token,
    settle,
    until_status,
)
from tests.harness.stack import Stack


def test_token_route_issues_a_token_for_good_client_credentials(stack: Stack) -> None:
    response = marketo_token(
        stack.marketo_url, stack.marketo_client_id, stack.marketo_client_secret
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["access_token"]
    assert body["token_type"].lower() == "bearer"
    assert body["expires_in"] > 0


def test_token_route_rejects_bad_client_credentials(stack: Stack) -> None:
    wrong_secret = marketo_token(stack.marketo_url, stack.marketo_client_id, "not-the-secret")
    wrong_client = marketo_token(stack.marketo_url, "someone-else", stack.marketo_client_secret)

    assert wrong_secret.status_code == 401
    assert wrong_client.status_code == 401
    assert "access_token" not in wrong_secret.text


def test_rest_calls_without_a_token_are_401(stack: Stack) -> None:
    url = f"{stack.marketo_url}{MARKETO_PROGRAMS_PATH}"

    no_token = httpx.get(url, timeout=MARKETO_HTTP_TIMEOUT_SECONDS)
    bad_token = httpx.get(
        url,
        headers={"Authorization": "Bearer made-up"},
        timeout=MARKETO_HTTP_TIMEOUT_SECONDS,
    )
    no_token_send = httpx.post(
        f"{stack.marketo_url}/rest/asset/v1/program/1/abSend.json",
        json={"variants": []},
        timeout=MARKETO_HTTP_TIMEOUT_SECONDS,
    )

    assert no_token.status_code == 401
    assert bad_token.status_code == 401
    assert no_token_send.status_code == 401


def test_approval_sends_both_variants_in_one_program(stack: Stack, api: httpx.Client) -> None:
    campaign_id = create(api)["id"]
    waiting = settle(api, campaign_id)
    assert waiting["draft"] and waiting["variant_b"]
    assert waiting["variant_b"] != waiting["draft"]

    assert api.post(f"/campaigns/{campaign_id}/approve").status_code == 202
    sent = until_status(api, campaign_id, SENT)

    programs = marketo_programs(stack, campaign_id)
    assert len(programs) == 1
    [send] = programs[0]["sends"]
    assert send["receiptId"] == sent["receipt"]
    assert [v["label"] for v in send["variants"]] == ["A", "B"]
    assert send["variants"][0]["subject"] == sent["draft"]["subject"]
    assert send["variants"][1]["subject"] == sent["variant_b"]["subject"]


def test_a_retried_publish_after_a_lost_reply_sends_once(stack: Stack, api: httpx.Client) -> None:
    campaign_id = create(api)["id"]
    settle(api, campaign_id)

    stack.marketo_drop_next_send_reply()
    try:
        assert api.post(f"/campaigns/{campaign_id}/approve").status_code == 202
        sent = until_status(api, campaign_id, SENT)
    finally:
        stack.marketo_fault()

    assert len(marketo_programs(stack, campaign_id)) == 1
    [send] = marketo_sends(stack, campaign_id)
    assert send["receiptId"] == sent["receipt"]
