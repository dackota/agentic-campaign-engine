"""Seam 1 at fast depth: sign-in. A demo user's real token from Dex carries their team and
roles in its `groups` claim, and the Campaign API reads them back through `/me`. What each
role may do on every route is proved in process in tests/engine/test_api_access.py and
tests/engine/test_auth.py."""

from tests.api.conftest import SignIn

# Every demo user, their team and roles as the token should carry them.
USERS = {
    "dg-owner@demo.example": ("demand-gen", ["owner"]),
    "dg-approver@demo.example": ("demand-gen", ["approver"]),
    "dg-viewer@demo.example": ("demand-gen", ["viewer"]),
    "dg-lead@demo.example": ("demand-gen", ["approver", "owner"]),
    "pm-owner@demo.example": ("product-marketing", ["owner"]),
    "pm-approver@demo.example": ("product-marketing", ["approver"]),
    "pm-viewer@demo.example": ("product-marketing", ["viewer"]),
}


def test_every_demo_user_signs_in_with_team_and_roles(sign_in: SignIn) -> None:
    for email, (team, roles) in USERS.items():
        response = sign_in(email).get("/me")

        assert response.status_code == 200, response.text
        me = response.json()
        assert (me["email"], me["team"], me["roles"]) == (email, team, roles)
        assert me["subject"]
