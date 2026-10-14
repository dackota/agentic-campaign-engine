"""The preview routes on the real Campaign API in-process: which steps feed each kind, the
content type it answers with, and the 404 and 409 answers."""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine

from tests.support.dag import OWNER
from tests.support.scripted_outputs import scripted_output
from tests.support.seed import CampaignSeed, seed_campaign

AS_OWNER = {"Authorization": f"Bearer {OWNER}"}
PPTX = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
# kind -> (the steps it renders, its content type)
KINDS = {
    "one-pager": (("one_pager",), "application/pdf"),
    "deck": (("one_pager", "landing_page"), PPTX),
    "landing-page": (("landing_page",), "text/html"),
    "cards": (("design",), "text/html"),
    "social": (("social",), "text/html"),
    "graphic": (("one_pager",), "image/svg+xml"),
}
EVERY_STEP = ("one_pager", "landing_page", "design", "social")
ALL_PREVIEW_PATHS = ["preview", *(f"preview/{kind}" for kind in KINDS), "preview/poster"]


def _outputs(*steps: str) -> dict[str, object]:
    return {step: scripted_output(step) for step in steps}


@pytest.mark.parametrize("kind", KINDS)
def test_a_preview_renders_from_its_own_steps_alone_with_its_content_type(
    app_client: TestClient, sqlite_engine: Engine, kind: str
) -> None:
    steps, content_type = KINDS[kind]
    campaign_id = seed_campaign(sqlite_engine, CampaignSeed(outputs=_outputs(*steps)))

    response = app_client.get(f"/campaigns/{campaign_id}/preview/{kind}", headers=AS_OWNER)

    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith(content_type)
    assert response.content


# (kind, the one step whose output is missing): every other step has output
MISSING_ONE_STEP = [
    ("one-pager", "one_pager"),
    ("deck", "one_pager"),
    ("deck", "landing_page"),
    ("landing-page", "landing_page"),
    ("cards", "design"),
    ("social", "social"),
    ("graphic", "one_pager"),
]


@pytest.mark.parametrize(("kind", "missing"), MISSING_ONE_STEP)
def test_a_preview_is_409_while_a_step_it_renders_has_no_output(
    app_client: TestClient, sqlite_engine: Engine, kind: str, missing: str
) -> None:
    campaign_id = seed_campaign(
        sqlite_engine, CampaignSeed(outputs=_outputs(*(s for s in EVERY_STEP if s != missing)))
    )

    response = app_client.get(f"/campaigns/{campaign_id}/preview/{kind}", headers=AS_OWNER)

    assert response.status_code == 409
    assert response.json()["detail"] == f"campaign has no {kind} content yet"


def test_a_preview_of_a_kind_that_does_not_exist_is_404(
    app_client: TestClient, sqlite_engine: Engine
) -> None:
    campaign_id = seed_campaign(sqlite_engine, CampaignSeed(outputs=_outputs(*EVERY_STEP)))

    response = app_client.get(f"/campaigns/{campaign_id}/preview/poster", headers=AS_OWNER)

    assert response.status_code == 404


@pytest.mark.parametrize("path", ALL_PREVIEW_PATHS)
def test_a_preview_of_an_unknown_campaign_is_404(app_client: TestClient, path: str) -> None:
    response = app_client.get(f"/campaigns/{uuid.uuid4()}/{path}", headers=AS_OWNER)

    assert response.status_code == 404


def test_the_email_preview_is_html_made_from_the_draft(
    app_client: TestClient, sqlite_engine: Engine
) -> None:
    draft = scripted_output("email_writer")
    campaign_id = seed_campaign(sqlite_engine, CampaignSeed(draft=draft))

    response = app_client.get(f"/campaigns/{campaign_id}/preview", headers=AS_OWNER)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert draft["subject"] in response.text


def test_the_email_preview_is_409_for_a_campaign_with_no_draft(
    app_client: TestClient, sqlite_engine: Engine
) -> None:
    campaign_id = seed_campaign(sqlite_engine)

    response = app_client.get(f"/campaigns/{campaign_id}/preview", headers=AS_OWNER)

    assert response.status_code == 409
    assert response.json()["detail"] == "campaign has no draft yet"
