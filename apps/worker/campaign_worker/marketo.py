"""The Marketo publisher adapter: OAuth2 client credentials, one program per campaign, and
one A/B send of the approved variants. Both writes are idempotent on Marketo's side
(the program by its external id, the send by its program), so a retry never sends twice."""

from typing import Any

import httpx
from ace_engine.settings import Settings
from temporalio.exceptions import ApplicationError

from campaign_worker.publisher import ApprovedCampaign, Receipt

TARGET = "marketo"
MARKETO_REPLY_INVALID = "MarketoReplyInvalid"
TOKEN_PATH = "/identity/oauth/token"
PROGRAMS_PATH = "/rest/asset/v1/programs.json"
VARIANT_LABELS = ("A", "B")
REPLY_EXCERPT_CHARS = 200


class MarketoAdapter:
    target = TARGET

    def __init__(self, settings: Settings) -> None:
        self._url = settings.marketo_url
        self._client_id = settings.marketo_client_id
        self._client_secret = settings.marketo_client_secret

    async def publish(
        self, client: httpx.AsyncClient, campaign: ApprovedCampaign, idempotency_key: str
    ) -> Receipt:
        headers = {"Authorization": f"Bearer {await self._token(client)}"}
        program = await client.post(
            f"{self._url}{PROGRAMS_PATH}",
            json={"name": idempotency_key, "externalId": campaign.campaign_id},
            headers=headers,
        )
        program.raise_for_status()
        program_id = _first(program, "id")
        send = await client.post(
            f"{self._url}/rest/asset/v1/program/{program_id}/abSend.json",
            json={"variants": _variants(campaign.emails)},
            headers=headers,
        )
        send.raise_for_status()
        receipt_id = _first(send, "receiptId")
        return Receipt(
            target=TARGET,
            receipt_id=str(receipt_id),
            url=f"{self._url}/rest/asset/v1/program/{program_id}.json",
        )

    async def _token(self, client: httpx.AsyncClient) -> str:
        response = await client.post(
            f"{self._url}{TOKEN_PATH}",
            data={
                "grant_type": "client_credentials",
                "client_id": self._client_id,
                "client_secret": self._client_secret,
            },
        )
        if response.status_code == httpx.codes.UNAUTHORIZED:
            raise ApplicationError(
                "Marketo rejected the client credentials",
                type="MarketoAuthFailed",
                non_retryable=True,
            )
        response.raise_for_status()
        try:
            token = response.json()["access_token"]
        except (ValueError, KeyError, TypeError) as exc:
            raise _invalid(response, "access_token") from exc
        if not isinstance(token, str) or not token:
            raise _invalid(response, "access_token")
        return token


def _variants(emails: tuple[dict[str, Any], ...]) -> list[dict[str, Any]]:
    return [
        {
            "label": label,
            "subject": email["subject"],
            "preheader": email["preheader"],
            "body": email["body"],
            "callToAction": email["call_to_action"],
        }
        for label, email in zip(VARIANT_LABELS, emails, strict=True)
    ]


def _first(response: httpx.Response, key: str) -> Any:
    """`result[0][key]` of a Marketo reply, or a non-retryable error naming what is wrong."""
    try:
        value = response.json()["result"][0][key]
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise _invalid(response, key) from exc
    if value is None or value == "" or isinstance(value, bool | dict | list):
        raise ApplicationError(
            f"Marketo reply has an invalid {key}: {value!r}",
            type=MARKETO_REPLY_INVALID,
            non_retryable=True,
        )
    return value


def _invalid(response: httpx.Response, key: str) -> ApplicationError:
    return ApplicationError(
        f"Marketo reply has no {key}: {response.text[:REPLY_EXCERPT_CHARS]!r}",
        type=MARKETO_REPLY_INVALID,
        non_retryable=True,
    )
