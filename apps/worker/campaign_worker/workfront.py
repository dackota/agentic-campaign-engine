"""The Workfront publisher adapter: OAuth2 client credentials, one project, and one task per
campaign, with one approval on the task. Every write is idempotent on Workfront's side (the
project and the task by their external id, the approval by its task), so a retry updates the
same task and never makes a second."""

from typing import Any

import httpx
from ace_engine.settings import Settings
from temporalio.exceptions import ApplicationError

from campaign_worker.publisher import ApprovedCampaign, Receipt

TARGET = "workfront"
WORKFRONT_REPLY_INVALID = "WorkfrontReplyInvalid"
WORKFRONT_AUTH_FAILED = "WorkfrontAuthFailed"
TOKEN_PATH = "/oauth2/token"
API_PATH = "/attask/api/v15.0"
PROJECT_NAME = "Campaigns"
PROJECT_EXTERNAL_ID = "ace-campaigns"
MAX_NAME_CHARS = 255
REPLY_EXCERPT_CHARS = 200


class WorkfrontAdapter:
    target = TARGET

    def __init__(self, settings: Settings) -> None:
        self._url = settings.workfront_url
        self._client_id = settings.workfront_client_id
        self._client_secret = settings.workfront_client_secret

    async def publish(
        self, client: httpx.AsyncClient, campaign: ApprovedCampaign, idempotency_key: str
    ) -> Receipt:
        headers = {"Authorization": f"Bearer {await self._token(client)}"}
        project = await self._write(
            client, "/proj", {"name": PROJECT_NAME, "externalID": PROJECT_EXTERNAL_ID}, headers
        )
        task = await self._write(
            client,
            "/task",
            {
                "name": _task_name(campaign),
                "externalID": campaign.campaign_id,
                "projectID": project["ID"],
                "description": f"publish {idempotency_key}",
            },
            headers,
        )
        await self._write(client, "/appr", {"taskID": task["ID"]}, headers)
        task_id = str(task["ID"])
        return Receipt(
            target=TARGET, receipt_id=task_id, url=f"{self._url}{API_PATH}/task/{task_id}"
        )

    async def _write(
        self, client: httpx.AsyncClient, path: str, body: dict[str, Any], headers: dict[str, str]
    ) -> dict[str, Any]:
        response = await client.post(f"{self._url}{API_PATH}{path}", json=body, headers=headers)
        if response.status_code == httpx.codes.UNAUTHORIZED:
            raise ApplicationError(
                "Workfront rejected the access token",
                type=WORKFRONT_AUTH_FAILED,
                non_retryable=True,
            )
        response.raise_for_status()
        return _data(response)

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
                "Workfront rejected the client credentials",
                type=WORKFRONT_AUTH_FAILED,
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


def _task_name(campaign: ApprovedCampaign) -> str:
    subject = str(campaign.emails[0].get("subject", "")) if campaign.emails else ""
    return f"Campaign: {subject}"[:MAX_NAME_CHARS].strip()


def _data(response: httpx.Response) -> dict[str, Any]:
    """The `data` object of a Workfront reply, with a usable ID, or a non-retryable error."""
    try:
        data = response.json()["data"]
        object_id = data["ID"]
    except (ValueError, KeyError, TypeError) as exc:
        raise _invalid(response, "data.ID") from exc
    if not isinstance(object_id, str) or not object_id:
        raise _invalid(response, "data.ID")
    return dict(data)


def _invalid(response: httpx.Response, key: str) -> ApplicationError:
    return ApplicationError(
        f"Workfront reply has no {key}: {response.text[:REPLY_EXCERPT_CHARS]!r}",
        type=WORKFRONT_REPLY_INVALID,
        non_retryable=True,
    )
