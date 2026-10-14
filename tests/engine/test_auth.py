"""Roles and sign-in claims: owners create and run campaigns, approvers approve, viewers
read, and nobody approves a campaign they created. A login in no team, or in several, may do
nothing."""

import itertools

import pytest
from campaign_api.auth import Action, Role, User, _user_from_claims, authorize
from fastapi import HTTPException

SUBJECT = "user-1"
ROLE_SETS = {
    "owner": {Role.OWNER},
    "approver": {Role.APPROVER},
    "viewer": {Role.VIEWER},
    "owner and approver": {Role.OWNER, Role.APPROVER},
    "no role": set(),
}
# What each role set may do, from the rules in the docs: everyone in a team reads; only an
# owner creates; only an approver approves.
MAY = {
    "owner": {Action.READ, Action.CREATE},
    "approver": {Action.READ, Action.APPROVE},
    "viewer": {Action.READ},
    "owner and approver": {Action.READ, Action.CREATE, Action.APPROVE},
    "no role": set(),
}
CASES = list(itertools.product(ROLE_SETS, Action, ["a team", "no team"], [True, False]))


def _user(roles: set[Role], team: str | None) -> User:
    return User(subject=SUBJECT, email="u@demo.example", team=team, roles=frozenset(roles))


@pytest.mark.parametrize(
    ("role_set", "action", "membership", "is_creator"),
    CASES,
    ids=[f"{r}-{a}-{m}-{'own' if c else 'other'}" for r, a, m, c in CASES],
)
def test_authorize_allows_exactly_what_the_role_may_do(
    role_set: str, action: Action, membership: str, is_creator: bool
) -> None:
    user = _user(ROLE_SETS[role_set], "demand-gen" if membership == "a team" else None)
    created_by = SUBJECT if is_creator else "someone-else"
    if membership == "no team":
        expected = "not in a team"
    elif action not in MAY[role_set]:
        expected = "role cannot"
    elif action is Action.APPROVE and is_creator:
        expected = "own campaign"
    else:
        expected = None

    if expected is None:
        authorize(user, action, created_by=created_by)
        return
    with pytest.raises(HTTPException) as refused:
        authorize(user, action, created_by=created_by)
    assert refused.value.status_code == 403
    assert expected in str(refused.value.detail)


def test_an_owner_who_is_also_an_approver_cannot_approve_their_own_campaign() -> None:
    lead = _user({Role.OWNER, Role.APPROVER}, "demand-gen")

    with pytest.raises(HTTPException) as refused:
        authorize(lead, Action.APPROVE, created_by=lead.subject)

    assert refused.value.status_code == 403
    assert "you cannot approve your own campaign" == refused.value.detail
    authorize(lead, Action.APPROVE, created_by="the-owner")


def _claims(*groups: object, **extra: object) -> dict[str, object]:
    return {"sub": SUBJECT, "email": "u@demo.example", "groups": list(groups), **extra}


def test_claims_with_one_team_and_roles_make_a_user_of_that_team() -> None:
    user = _user_from_claims(_claims("team:demand-gen", "role:owner", "role:approver"))

    assert user == User(
        SUBJECT, "u@demo.example", "demand-gen", frozenset({Role.OWNER, Role.APPROVER})
    )


@pytest.mark.parametrize(
    "claims",
    [
        _claims("role:owner"),
        _claims("team:a", "team:b", "role:owner"),
        _claims(),
        {"sub": SUBJECT},
        {"sub": SUBJECT, "groups": "team:a"},
    ],
    ids=["no team", "two teams", "no groups", "no groups claim", "groups is a string"],
)
def test_a_login_in_no_team_or_in_several_belongs_to_no_team(claims: dict[str, object]) -> None:
    assert _user_from_claims(claims).team is None


def test_unknown_roles_and_non_text_groups_are_ignored() -> None:
    user = _user_from_claims(_claims("team:a", "role:owner", "role:admin", 7, None, "role:"))

    assert (user.team, user.roles) == ("a", frozenset({Role.OWNER}))


def test_a_claim_set_without_an_email_has_an_empty_one() -> None:
    claims = {"sub": SUBJECT, "groups": ["team:a"], "email": 5}

    assert _user_from_claims(claims).email == ""
