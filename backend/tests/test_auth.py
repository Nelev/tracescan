"""Clerk session tokens on the API (auth.session), verified for real: each test signs JWTs with an
RSA key generated for the run and gives the app its public half as `CLERK_JWT_KEY`, so nothing
calls Clerk. Every other test is signed in through the `sign_in` fixture in conftest.py instead.
"""

import re
import time
from functools import cache

import jwt
import pytest
from clerk_backend_api.security import TokenVerificationError, TokenVerificationErrorReason
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

import auth.session
from auth import AuthSettings, session_claims
from auth.session import auth_settings, current_user
from db.models import NAME_MAX
from main import app

ORIGIN = "http://localhost:3010"


@cache
def key(name: str) -> rsa.RSAPrivateKey:
    """`clerk`, the key the app trusts, or any other name for a key it does not; made once, on
    first use, not when the module is collected."""
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def public_pem() -> str:
    return (
        key("clerk")
        .public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )


def token(signer: str = "clerk", **overrides) -> str:
    """A session token as Clerk mints one, with `overrides` on its claims (None drops one)."""
    now = int(time.time())
    claims = {
        "sub": "user_ana",
        "sid": "sess_1",
        "azp": ORIGIN,
        "iss": "https://clerk.example.test",
        "iat": now,
        "nbf": now - 5,
        "exp": now + 60,
        "name": "Ana Rossi",
    }
    claims.update(overrides)
    claims = {k: v for k, v in claims.items() if v is not None}
    return jwt.encode(claims, key(signer), algorithm="RS256")


def bearer(value: str) -> dict:
    return {"Authorization": f"Bearer {value}"}


class UntouchableRuns:
    """The runs module of a test where no request may get as far as it."""

    def __getattr__(self, name):
        raise AssertionError(f"reached the runs module ({name}) without a valid session")


@pytest.fixture
async def anon(collector):
    """An HTTP client on the app, with nobody signed in and the test key as Clerk's."""
    settings = AuthSettings("sk_test_placeholder", public_pem(), (ORIGIN,))
    del app.dependency_overrides[session_claims]  # set by the autouse `sign_in`
    app.dependency_overrides[auth_settings] = lambda: settings
    # Restored by hand: app.state is the shared app's, like every API test's.
    before = getattr(app.state, "runs", None)
    app.state.runs = UntouchableRuns()
    yield collector
    app.state.runs = before
    del app.dependency_overrides[auth_settings]


# The only routes anyone may call without a session.
PUBLIC = {("GET", "/health"), ("POST", "/v1/traces")}
# A well-formed value for each path parameter, so a route refused for its path would not pass.
PATH_PARAMS = {
    "run_id": "00000000-0000-0000-0000-000000000000",
    "trace_id": "0af7651916cd43dd8448eb211c80319c",
}


def routes() -> list[tuple[str, str]]:
    """Every method and path the app serves, path parameters filled in, as its OpenAPI schema
    lists them (app.routes holds included routers unexpanded)."""
    return sorted(
        (method.upper(), re.sub(r"{(\w+)}", lambda m: PATH_PARAMS[m[1]], path))
        for path, operations in app.openapi()["paths"].items()
        for method in operations
    )


@pytest.mark.anyio
@pytest.mark.parametrize(("method", "path"), [r for r in routes() if r not in PUBLIC])
async def test_every_route_but_the_collector_and_health_needs_a_session(anon, method, path):
    # A valid run request: the 401 comes before a run (and its trace server) would start.
    response = await anon.request(method, path, json={"target_app": "medas"})
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert response.json() == {"detail": "Not signed in"}


def test_the_public_routes_are_still_served():
    assert PUBLIC <= set(routes())


@pytest.mark.anyio
async def test_health_and_the_collector_stay_open(anon):
    assert (await anon.get("/health")).status_code == 200
    # Refused for its content type, not for want of a session: the collector is for Medas's
    # exporter, which has none.
    assert (await anon.post("/v1/traces", content=b"{}")).status_code == 415


class NoRuns:
    """A runs module with no runs at all."""

    async def count(self) -> int:
        return 0

    async def list(self, limit: int, offset: int) -> list:
        return []


@pytest.mark.anyio
async def test_a_valid_session_token_gets_through(anon):
    app.state.runs = NoRuns()
    response = await anon.get("/v1/runs", headers=bearer(token()))
    assert response.status_code == 200 and response.json() == []


BAD_TOKENS = {
    "signed by another key": lambda: token("other"),
    "expired": lambda: token(exp=int(time.time()) - 60),
    "not active yet": lambda: token(nbf=int(time.time()) + 60),
    "issued for another site": lambda: token(azp="https://evil.example"),
    "without an azp": lambda: token(azp=None),
    "without a session": lambda: token(sid=None),
    "without a user": lambda: token(sub=None),
    "not a JWT": lambda: "garbage",
    "a machine token": lambda: "mt_" + token(),
    "an API key": lambda: "ak_123",
}


@pytest.mark.anyio
@pytest.mark.parametrize("make", BAD_TOKENS.values(), ids=BAD_TOKENS.keys())
async def test_a_bad_token_is_401(anon, make):
    response = await anon.get("/v1/runs", headers=bearer(make()))
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"


@pytest.mark.anyio
async def test_a_token_that_cannot_be_checked_is_503_not_401(anon, monkeypatch):
    async def unreachable(token, options):
        raise TokenVerificationError(TokenVerificationErrorReason.JWK_FAILED_TO_LOAD)

    monkeypatch.setattr(auth.session, "verify_token_async", unreachable)
    response = await anon.get("/v1/runs", headers=bearer(token()))
    assert response.status_code == 503
    assert response.json() == {"detail": "Could not verify the session"}


def test_the_name_is_the_name_claim_else_the_email_else_the_user_id():
    base = {"sub": "user_ana", "sid": "s"}
    assert current_user({**base, "name": " Ana ", "email": "a@x.test"}).name == "Ana"
    assert current_user({**base, "name": "  ", "email": "a@x.test"}).name == "a@x.test"
    assert current_user({**base, "name": 7}).name == "user_ana"
    long = current_user({**base, "name": "x" * (NAME_MAX + 10)})
    assert len(long.name) == NAME_MAX and long.user_id == "user_ana"


def test_settings_read_the_authorized_parties_as_a_json_list(monkeypatch):
    monkeypatch.setenv("CLERK_SECRET_KEY", "sk_test_x")
    monkeypatch.delenv("CLERK_JWT_KEY", raising=False)
    monkeypatch.delenv("CLERK_AUTHORIZED_PARTIES", raising=False)
    default = AuthSettings.from_env()
    assert default.authorized_parties == auth.session.DEFAULT_AUTHORIZED_PARTIES
    assert default.jwt_key is None

    monkeypatch.setenv("CLERK_AUTHORIZED_PARTIES", '["https://tracescan.example"]')
    assert AuthSettings.from_env().authorized_parties == ("https://tracescan.example",)
    monkeypatch.setenv("CLERK_AUTHORIZED_PARTIES", "https://tracescan.example")
    with pytest.raises(ValueError):
        AuthSettings.from_env()
    monkeypatch.setenv("CLERK_AUTHORIZED_PARTIES", '"https://tracescan.example"')
    with pytest.raises(ValueError):
        AuthSettings.from_env()


@pytest.mark.anyio
async def test_the_app_refuses_to_start_without_the_clerk_secret_key(monkeypatch):
    monkeypatch.delenv("CLERK_SECRET_KEY", raising=False)
    monkeypatch.delenv("DRY_RUN", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)  # refused before the database is needed
    with pytest.raises(KeyError, match="CLERK_SECRET_KEY"):
        async with app.router.lifespan_context(app):
            pass
