"""Sign-in and roles for the Campaign API.

Every route but /healthz needs a token from the OIDC provider (Dex). The token's
`groups` claim carries the team (`team:<id>`) and the roles (`role:owner`,
`role:approver`, `role:viewer`). `authorize` holds the role rules: owners create and run
campaigns, approvers approve, viewers read, and nobody approves a campaign they created.
"""

import logging
from dataclasses import dataclass
from enum import StrEnum
from typing import Annotated, Any

import jwt
from fastapi import Depends, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

log = logging.getLogger(__name__)

TEAM_PREFIX = "team:"
ROLE_PREFIX = "role:"
SIGNING_ALGORITHMS = ["RS256", "ES256"]
REQUIRED_CLAIMS = ["exp", "iat", "iss", "aud", "sub"]
# Dex serves its signing keys here; the key set is cached and refetched on an unknown key id.
JWKS_PATH = "/keys"
JWKS_CACHE_SECONDS = 300
NOT_SIGNED_IN = "sign in first: send a valid bearer token"


class Role(StrEnum):
    OWNER = "owner"
    APPROVER = "approver"
    VIEWER = "viewer"


class Action(StrEnum):
    READ = "read"
    CREATE = "create"
    APPROVE = "approve"


ALLOWED_ROLES: dict[Action, frozenset[Role]] = {
    Action.READ: frozenset(Role),
    Action.CREATE: frozenset({Role.OWNER}),
    Action.APPROVE: frozenset({Role.APPROVER}),
}


@dataclass(frozen=True)
class User:
    subject: str
    email: str
    team: str | None
    roles: frozenset[Role]


def _user_from_claims(claims: dict[str, Any]) -> User:
    groups = claims.get("groups")
    names = [g for g in groups if isinstance(g, str)] if isinstance(groups, list) else []
    teams = {g.removeprefix(TEAM_PREFIX) for g in names if g.startswith(TEAM_PREFIX)}
    known_roles = {r.value for r in Role}
    roles = frozenset(
        Role(g.removeprefix(ROLE_PREFIX))
        for g in names
        if g.startswith(ROLE_PREFIX) and g.removeprefix(ROLE_PREFIX) in known_roles
    )
    # A login in no team, or in several, belongs to no team: it may do nothing.
    team = teams.pop() if len(teams) == 1 else None
    email = claims.get("email")
    return User(
        subject=str(claims["sub"]),
        email=email if isinstance(email, str) else "",
        team=team,
        roles=roles,
    )


def _unauthorized(detail: str = NOT_SIGNED_IN) -> HTTPException:
    return HTTPException(status_code=401, detail=detail, headers={"WWW-Authenticate": "Bearer"})


class TokenVerifier:
    """Checks a token's signature against the issuer's keys, then its issuer, audience,
    and expiry, and reads the user from its claims."""

    def __init__(self, issuer: str, client_id: str) -> None:
        if not issuer.strip():
            raise ValueError("oidc_issuer is required: set it to the OIDC provider's issuer URL")
        self._issuer = issuer
        self._client_id = client_id
        self._keys = jwt.PyJWKClient(f"{issuer}{JWKS_PATH}", lifespan=JWKS_CACHE_SECONDS)

    def verify(self, token: str) -> User:
        try:
            key = self._keys.get_signing_key_from_jwt(token).key
            claims: dict[str, Any] = jwt.decode(
                token,
                key,
                algorithms=SIGNING_ALGORITHMS,
                audience=self._client_id,
                issuer=self._issuer,
                options={"require": REQUIRED_CLAIMS},
            )
        except jwt.PyJWKClientConnectionError as exc:
            log.error("cannot fetch the OIDC signing keys from %s: %s", self._issuer, exc)
            raise HTTPException(status_code=503, detail="sign-in is unavailable") from exc
        except jwt.PyJWTError as exc:
            raise _unauthorized(f"{NOT_SIGNED_IN} ({exc})") from exc
        return _user_from_claims(claims)


_bearer = HTTPBearer(auto_error=False)
Bearer = Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)]


async def _verified(request: Request, token: str | None) -> User:
    if not token:
        raise _unauthorized()
    verifier: TokenVerifier = request.app.state.verifier
    return await run_in_threadpool(verifier.verify, token)


async def current_user(request: Request, credentials: Bearer) -> User:
    """The signed-in user, from the `Authorization: Bearer` header."""
    return await _verified(request, credentials.credentials if credentials else None)


async def stream_user(
    request: Request,
    credentials: Bearer,
    access_token: Annotated[str | None, Query()] = None,
) -> User:
    """Like `current_user`, but a browser EventSource cannot send headers, so the event
    stream also takes the token as the `access_token` query parameter."""
    token = credentials.credentials if credentials else access_token
    return await _verified(request, token)


CurrentUser = Annotated[User, Depends(current_user)]
StreamUser = Annotated[User, Depends(stream_user)]


def authorize(user: User, action: Action, created_by: str | None = None) -> None:
    """Allow, or raise 403 naming why. `created_by` is the campaign's creator, for approve."""
    if user.team is None:
        raise HTTPException(status_code=403, detail="your login is not in a team")
    if not user.roles & ALLOWED_ROLES[action]:
        raise HTTPException(status_code=403, detail=f"your role cannot {action} campaigns")
    if action is Action.APPROVE and created_by == user.subject:
        raise HTTPException(status_code=403, detail="you cannot approve your own campaign")
