"""The fake Marketo: a send returns a receipt, repeating a send for the same campaign does
not send twice, and its own API lists what it delivered."""

from fake_marketo.app import create_app
from fastapi.testclient import TestClient

DRAFT = {"subject": "s", "preheader": "p", "body": "b", "call_to_action": "c"}


def test_send_returns_receipt_and_is_listed() -> None:
    client = TestClient(create_app())
    response = client.post("/rest/v1/emails/send", json={"campaign_id": "a", **DRAFT})
    assert response.status_code == 200
    receipt = response.json()["result"][0]["receiptId"]
    assert [s["receipt"] for s in client.get("/_sends").json()] == [receipt]


def test_resending_the_same_campaign_returns_the_same_receipt_without_a_second_send() -> None:
    client = TestClient(create_app())
    body = {"campaign_id": "a", **DRAFT}
    first = client.post("/rest/v1/emails/send", json=body).json()
    second = client.post("/rest/v1/emails/send", json=body).json()
    assert first == second
    assert len(client.get("/_sends").json()) == 1
