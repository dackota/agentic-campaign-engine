"""The Slack and Google stand-ins refuse bad credentials the way the real APIs do, so a
wrong token in a test fails loudly instead of passing by accident."""

from fake_google.app import GoogleConfig
from fake_google.app import create_app as create_google
from fake_slack.app import SlackConfig
from fake_slack.app import create_app as create_slack
from fastapi.testclient import TestClient

GOOD = GoogleConfig(client_id="gid", client_secret="gsecret", refresh_token="grefresh")
GOOD_FORM = {
    "grant_type": "refresh_token",
    "client_id": "gid",
    "client_secret": "gsecret",
    "refresh_token": "grefresh",
}


def test_slack_answers_invalid_auth_to_a_wrong_token_and_stores_nothing() -> None:
    client = TestClient(create_slack(SlackConfig(token="right")))

    refused = client.post(
        "/chat.postMessage",
        headers={"Authorization": "Bearer wrong"},
        json={"channel": "#c", "text": "hi"},
    )

    assert refused.json() == {"ok": False, "error": "invalid_auth"}
    assert client.get("/_messages").json() == []


def test_google_refuses_bad_client_credentials() -> None:
    client = TestClient(create_google(GOOD))

    refused = client.post("/token", data={**GOOD_FORM, "client_secret": "nope"})

    assert refused.status_code == 401


def test_google_refuses_a_document_without_an_access_token() -> None:
    client = TestClient(create_google(GOOD))

    refused = client.post("/v1/documents", json={"title": "t"})

    assert refused.status_code == 401
    assert client.get("/_documents").json() == []


def test_google_creates_a_document_after_a_good_token() -> None:
    client = TestClient(create_google(GOOD))
    access = client.post("/token", data=GOOD_FORM).json()["access_token"]
    headers = {"Authorization": f"Bearer {access}"}

    created = client.post("/v1/documents", headers=headers, json={"title": "t"}).json()
    client.post(
        f"/v1/documents/{created['documentId']}:batchUpdate",
        headers=headers,
        json={"requests": [{"insertText": {"text": "hello"}}]},
    )

    assert [d["text"] for d in client.get("/_documents").json()] == ["hello"]
