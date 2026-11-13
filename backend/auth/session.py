"""Who a request is from: the Clerk session token on it, verified.

`session_claims` verifies the token once per request; `current_user` reads from it who is asking,
as a `Principal`. Each is its own dependency, so either can be overridden alone (the tests sign
everyone in by overriding `session_claims`); FastAPI runs `session_claims` once per request however many
depend on it. Identity comes only from the token: nothing a request says about who it is from
is read.

The settings are read once at startup (`AuthSettings.from_env`, in the lifespan) into
`app.state.auth`, so a missing `CLERK_SECRET_KEY` stops the app rather than failing each request.
Which routes need a session is decided in one place, main.py.
"""

import json
import os
from dataclasses import dataclass
from typing import Annotated, Any

from clerk_backend_api.security import (
    TokenVerificationError,
    TokenVerificationErrorReason,
    VerifyTokenOptions,
    verify_token_async,
)
from clerk_backend_api.security.machine import get_token_type
from clerk_backend_api.security.types import TokenType
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from db.models import NAME_MAX

# The origins a token may be issued for by default: the UI as `frontend-3010` and `npm run dev`
# serve it.
DEFAULT_AUTHORIZED_PARTIES = ("http://localhost:3010", "http://localhost:3000")


@dataclass(frozen=True)
class AuthSettings:
    """Clerk settings, from the environment."""

    # The same secret key the UI has. Fetches the public key tokens are verified against when
    # `jwt_key` is not set.
    secret_key: str
    # A PEM public key (Clerk dashboard: API keys -> JWT public key), to verify tokens without a
    # network call. The tests use one they generate.
    jwt_key: str | None
    # The origins a token may have been issued for (its `azp` claim): a token minted for some
    # other site that uses Clerk is refused even though its signature is good.
    authorized_parties: tuple[str, ...]

    @classmethod
    def from_env(cls) -> "AuthSettings":
        """`CLERK_SECRET_KEY` (required), `CLERK_JWT_KEY`, and `CLERK_AUTHORIZED_PARTIES` as a
        JSON list. Raises `KeyError` without the secret key and `ValueError` for a list that is
        not one."""
        secret_key = os.environ["CLERK_SECRET_KEY"]
        parties = os.environ.get("CLERK_AUTHORIZED_PARTIES")
        if parties is None:
            authorized = DEFAULT_AUTHORIZED_PARTIES
        else:
            loaded = json.loads(parties)
            if not isinstance(loaded, list) or not all(isinstance(p, str) for p in loaded):
                raise ValueError("CLERK_AUTHORIZED_PARTIES must be a JSON list of origins")
            authorized = tuple(loaded)
        return cls(secret_key, os.environ.get("CLERK_JWT_KEY") or None, authorized)


@dataclass(frozen=True)
class Principal:
    """The person a request is from: Clerk's id for them, and the name runs and reviews are
    recorded under."""

    user_id: str
    name: str


# auto_error=False so a missing header is our 401, the same shape as a bad token. The trace
# collector reads its app tokens with it too (api.traces).
bearer_scheme = HTTPBearer(auto_error=False)

# Failures that are ours or Clerk's, not the caller's: the same token could pass on a retry, so
# a 503 rather than a 401.
_UNAVAILABLE = {
    TokenVerificationErrorReason.JWK_FAILED_TO_LOAD,
    TokenVerificationErrorReason.SECRET_KEY_MISSING,
    TokenVerificationErrorReason.SERVER_ERROR,
}


def auth_settings(request: Request) -> AuthSettings:
    """The settings the lifespan read (a dependency, so a test can override it)."""
    return request.app.state.auth


def unauthorized(detail: str) -> HTTPException:
    """A 401 that asks for a bearer token."""
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


async def session_claims(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    settings: Annotated[AuthSettings, Depends(auth_settings)],
) -> dict[str, Any]:
    """The claims of the request's session token, once it has verified."""
    if credentials is None:
        raise unauthorized("Not signed in")
    token = credentials.credentials

    # verify_token_async also takes API keys, OAuth and machine tokens, which it checks against
    # Clerk's API. This API answers only a person's session, so those are refused before
    # verification, by the same classification the SDK dispatches on.
    if get_token_type(token) != TokenType.SESSION_TOKEN:
        raise unauthorized("Not a session token")

    try:
        claims = await verify_token_async(
            token,
            VerifyTokenOptions(
                secret_key=settings.secret_key,
                jwt_key=settings.jwt_key,
                authorized_parties=list(settings.authorized_parties),
            ),
        )
    except TokenVerificationError as exc:
        if exc.reason in _UNAVAILABLE:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Could not verify the session",
            ) from None
        raise unauthorized("Invalid session token") from None

    # A session token always names its session and its user. One without either verified, but
    # is nothing this API knows how to answer.
    subject = claims.get("sub")
    if not claims.get("sid") or not isinstance(subject, str) or not subject:
        raise unauthorized("Not a session token")
    return claims


def _claim(claims: dict[str, Any], key: str) -> str | None:
    value = claims.get(key)
    if not isinstance(value, str):
        return None
    return value.strip() or None


def current_user(claims: Annotated[dict[str, Any], Depends(session_claims)]) -> Principal:
    """Who is asking, from the verified claims; no call to Clerk.

    The name is the `name` claim, else `email`, else Clerk's user id: the first two exist only
    once the Clerk dashboard adds them to the session token (Sessions -> Customize session token:
    `{"name": "{{user.full_name}}", "email": "{{user.primary_email_address}}"}`). Cut to the
    width of the column it is stored in.
    """
    user_id = claims["sub"]
    name = _claim(claims, "name") or _claim(claims, "email") or user_id
    return Principal(user_id=user_id, name=name[:NAME_MAX])


CurrentUser = Annotated[Principal, Depends(current_user)]
