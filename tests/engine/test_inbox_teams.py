"""The approval inbox on real Postgres: row-level security is the only team filter, so an
approver sees only their own team's waiting assets, and a decision on another team's campaign
is a 404. The decision rules (who may decide, what is refused) run against the same database."""

import uuid
from typing import Literal

import pytest
from ace_engine import db, row_security
from campaign_api import inbox
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.engine import Engine

from tests.support.app import StubVerifier
from tests.support.dag import APPROVER, AWAITING, OWNER
from tests.support.scripted_outputs import scripted_output
from tests.support.seed import DEMAND_GEN, CampaignSeed, seed_campaign

PRODUCT_MARKETING = "product-marketing"
PM_APPROVER = "pm-approver@demo.example"
PM_OWNER = "pm-owner@demo.example"
LEAD = "dg-lead@demo.example"
ASSETS = {"landing_page", "social", "one_pager", "email_writer", "design"}
OUTPUTS = {step: scripted_output(step) for step in ASSETS}


def waiting(engine: Engine, team: str, created_by: str, status: str = AWAITING) -> uuid.UUID:
    return seed_campaign(
        engine, CampaignSeed(team=team, created_by=created_by, status=status, outputs=OUTPUTS)
    )


def ask(
    campaign: uuid.UUID, step: str, decision: Literal["approved", "rejected"], comment: str = ""
) -> inbox.AssetDecision:
    return inbox.AssetDecision(campaign, step, decision, comment)


def decide(engine: Engine, email: str, asked: inbox.AssetDecision) -> inbox.Decided:
    """The decision as the API takes it: on the approver's own team's view of the database."""
    approver = StubVerifier().verify(email)
    return inbox._decide(row_security.for_team(engine, approver.team), approver, asked)


def refusal(engine: Engine, email: str, asked: inbox.AssetDecision) -> int:
    with pytest.raises(HTTPException) as refused:
        decide(engine, email, asked)
    return refused.value.status_code


def test_an_approver_sees_the_waiting_assets_of_their_own_team_only(
    postgres_engine: Engine,
) -> None:
    demand_gen = waiting(postgres_engine, DEMAND_GEN, OWNER)
    product_marketing = waiting(postgres_engine, PRODUCT_MARKETING, PM_OWNER)

    def seen_by(email: str) -> list[inbox.AssetOut]:
        user = StubVerifier().verify(email)
        return inbox._inbox(row_security.for_team(postgres_engine, user.team), user)

    dg_items, pm_items = seen_by(APPROVER), seen_by(PM_APPROVER)

    assert {i.step for i in dg_items if i.campaign_id == demand_gen} == ASSETS
    assert {i.step for i in pm_items if i.campaign_id == product_marketing} == ASSETS
    assert {i.campaign_id for i in dg_items} == {demand_gen}
    assert {i.campaign_id for i in pm_items} == {product_marketing}
    assert {i.team for i in dg_items} == {DEMAND_GEN}


def test_a_rejection_must_carry_a_comment() -> None:
    for blank in ("", "  ", "\n\t"):
        with pytest.raises(ValidationError):
            inbox.Rejection(comment=blank)
    assert inbox.Rejection(comment="  Drop the hype ").comment == "Drop the hype"


def test_a_decision_that_is_not_the_approvers_to_make_is_refused(postgres_engine: Engine) -> None:
    campaign = waiting(postgres_engine, DEMAND_GEN, OWNER)
    own = waiting(postgres_engine, DEMAND_GEN, LEAD)

    refused = {
        "an owner cannot approve": refusal(
            postgres_engine, OWNER, ask(campaign, "social", "approved")
        ),
        "another team's approver sees no campaign": refusal(
            postgres_engine, PM_APPROVER, ask(campaign, "social", "approved")
        ),
        "a step that is not an asset": refusal(
            postgres_engine, APPROVER, ask(campaign, "strategist", "approved")
        ),
        "a campaign that does not exist": refusal(
            postgres_engine, APPROVER, ask(uuid.uuid4(), "social", "approved")
        ),
        "a campaign's own creator": refusal(postgres_engine, LEAD, ask(own, "social", "approved")),
    }

    assert refused == {
        "an owner cannot approve": 403,
        "another team's approver sees no campaign": 404,
        "a step that is not an asset": 404,
        "a campaign that does not exist": 404,
        "a campaign's own creator": 403,
    }


def test_an_asset_cannot_be_decided_twice(postgres_engine: Engine) -> None:
    campaign = waiting(postgres_engine, DEMAND_GEN, OWNER)
    first = decide(postgres_engine, APPROVER, ask(campaign, "social", "approved"))

    again = refusal(postgres_engine, APPROVER, ask(campaign, "social", "approved"))
    then_reject = refusal(
        postgres_engine, APPROVER, ask(campaign, "social", "rejected", "too late")
    )

    assert first == inbox.Decided(db.AWAITING_APPROVAL, should_signal=False)
    assert (again, then_reject) == (409, 409)


@pytest.mark.parametrize("status", [db.DRAFTING, db.SENDING, db.SENT, db.FAILED, db.FINISHED])
def test_a_campaign_that_is_not_waiting_takes_no_decision(
    postgres_engine: Engine, status: str
) -> None:
    campaign = waiting(postgres_engine, DEMAND_GEN, OWNER, status)

    assert refusal(postgres_engine, APPROVER, ask(campaign, "social", "approved")) == 409
