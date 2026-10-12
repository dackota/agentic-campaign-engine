"""Slack notices and the Google Doc export: both off unless their credentials are set.

Both are best effort. A campaign must run the same with them off, and a Slack or Google
outage must not fail a run, so every call here logs the problem (never a token) and
returns. The credentials come from `Settings`.
"""

import logging
from typing import Any

import httpx
from ace_engine.settings import Settings

log = logging.getLogger(__name__)

DOC_URL_TEMPLATE = "https://docs.google.com/document/d/{document_id}/edit"
SUMMARY_LINE_LIMIT = 120
# Google Docs counts characters from 1 at the start of a new document body.
DOC_BODY_START_INDEX = 1


def first_line(report: str) -> str:
    line = next((ln.strip() for ln in report.splitlines() if ln.strip()), "")
    return line[:SUMMARY_LINE_LIMIT]


def inbox_link(settings: Settings, campaign_id: str) -> str:
    """Where an approver opens the campaign's assets; empty when the web app's URL is not set."""
    base = settings.web_url.strip().rstrip("/")
    return f"{base}/?inbox={campaign_id}" if base else ""


async def post_to_slack(client: httpx.AsyncClient, settings: Settings, text: str) -> bool:
    """Post `text` to the configured channel. False when Slack is off or the post failed."""
    if not settings.slack_enabled:
        return False
    try:
        response = await client.post(
            f"{settings.slack_url}/chat.postMessage",
            headers={"Authorization": f"Bearer {settings.slack_token}"},
            json={"channel": settings.slack_channel, "text": text},
        )
        response.raise_for_status()
        body = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("slack post failed: %s", type(exc).__name__)
        return False
    if not isinstance(body, dict) or body.get("ok") is not True:
        error = body.get("error") if isinstance(body, dict) else None
        log.warning("slack refused the post: %s", error)
        return False
    return True


def doc_text(report: str, drafts: list[dict[str, Any]]) -> str:
    """The brief, then each draft in A/B order."""
    parts = ["Brief", report.strip()]
    for label, draft in zip("AB", drafts, strict=False):
        parts += [
            f"Variant {label}",
            f"Subject: {draft.get('subject', '')}",
            f"Preheader: {draft.get('preheader', '')}",
            str(draft.get("body", "")),
            f"Call to action: {draft.get('call_to_action', '')}",
        ]
    return "\n\n".join(parts) + "\n"


async def export_to_google_doc(
    client: httpx.AsyncClient, settings: Settings, title: str, text: str
) -> str | None:
    """Create one Google Doc holding `text`; its URL, or None when Google is off or failed."""
    if not settings.google_enabled:
        return None
    try:
        access = await _access_token(client, settings)
        headers = {"Authorization": f"Bearer {access}"}
        created = await client.post(
            f"{settings.google_docs_url}/v1/documents", headers=headers, json={"title": title}
        )
        created.raise_for_status()
        document_id = str(created.json()["documentId"])
        update = await client.post(
            f"{settings.google_docs_url}/v1/documents/{document_id}:batchUpdate",
            headers=headers,
            json={
                "requests": [
                    {"insertText": {"location": {"index": DOC_BODY_START_INDEX}, "text": text}}
                ]
            },
        )
        update.raise_for_status()
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        log.warning("google doc export failed: %s", type(exc).__name__)
        return None
    return DOC_URL_TEMPLATE.format(document_id=document_id)


async def _access_token(client: httpx.AsyncClient, settings: Settings) -> str:
    response = await client.post(
        settings.google_token_url,
        data={
            "grant_type": "refresh_token",
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "refresh_token": settings.google_refresh_token,
        },
    )
    response.raise_for_status()
    return str(response.json()["access_token"])
