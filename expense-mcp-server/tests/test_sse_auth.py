"""SSE transport authentication tests.

The SSE boundary verifies bearer tokens cryptographically — signature,
expiry, audience, and (optionally) issuer must all check out against a
JWKS document. These tests build a synthetic JWKS from a locally
generated RSA key pair and drive the middleware through a Starlette
test client, so:

* no real IdP is contacted;
* no real JWT/JWKS artifact is committed;
* both key pairs are generated fresh per test session.

A second RSA key pair (the "attacker" key) is generated so we can prove
a token signed with the wrong private key is rejected without ever
committing forged material to the tree.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt import PyJWK, PyJWKClient
from mcp import McpError
from starlette.testclient import TestClient

from expense_mcp_server.auth import (
    RequestContext,
    assert_tenant_matches,
    clear_context,
    parse_bearer,
    set_context,
)
from expense_mcp_server.errors import CODE_FORBIDDEN
from expense_mcp_server.jwt_verifier import JwtVerifier, VerificationError
from expense_mcp_server.transports.sse import (
    SseAuthNotConfiguredError,
    _build_verifier,
    build_app,
)

_AUDIENCE = "expense-mcp-server-test"
_ISSUER = "https://idp.test.local/issuer"


# ---------------------------------------------------------------------------
# Key + JWKS helpers
# ---------------------------------------------------------------------------


def _make_keypair() -> rsa.RSAPrivateKey:
    # 2048 bits keeps test runtimes low while still exercising the real
    # signing pipeline; production JWKS keys will typically be 2048/3072.
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _private_pem(key: rsa.RSAPrivateKey) -> bytes:
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    )


def _jwk_from_public_key(public_key: rsa.RSAPublicKey, kid: str) -> dict[str, Any]:
    numbers = public_key.public_numbers()

    def _b64(value: int) -> str:
        # PyJWT's PyJWK.from_dict parses n/e via base64url without padding.
        import base64

        b = value.to_bytes((value.bit_length() + 7) // 8, "big")
        return base64.urlsafe_b64encode(b).rstrip(b"=").decode()

    return {
        "kty": "RSA",
        "kid": kid,
        "use": "sig",
        "alg": "RS256",
        "n": _b64(numbers.n),
        "e": _b64(numbers.e),
    }


class _FakeJwkClient:
    """Stand-in for ``PyJWKClient`` that serves keys from an in-memory JWKS.

    The real client fetches a JWKS URL and caches the parsed document; we
    bypass the network entirely so tests can never accidentally hit an
    external service.
    """

    def __init__(self, jwks: dict[str, Any]) -> None:
        self._by_kid: dict[str, PyJWK] = {}
        for entry in jwks.get("keys", []):
            key = PyJWK.from_dict(entry)
            if key.key_id is not None:
                self._by_kid[key.key_id] = key

    def get_signing_key_from_jwt(self, token: str) -> PyJWK:
        header = jwt.get_unverified_header(token)
        kid = header.get("kid")
        if not isinstance(kid, str) or kid not in self._by_kid:
            # Match ``PyJWKClient``'s failure mode so ``JwtVerifier`` maps
            # it to the same ``unknown_kid`` reason.
            from jwt.exceptions import PyJWKClientError

            raise PyJWKClientError(f"no key for kid={kid!r}")
        return self._by_kid[kid]


@pytest.fixture(scope="module")
def trusted_key() -> rsa.RSAPrivateKey:
    return _make_keypair()


@pytest.fixture(scope="module")
def attacker_key() -> rsa.RSAPrivateKey:
    # A completely independent key pair. Same algorithm and same ``kid``
    # header, different private key — this is the classic forged-token
    # shape we must reject.
    return _make_keypair()


@pytest.fixture(scope="module")
def jwks_document(trusted_key: rsa.RSAPrivateKey) -> dict[str, Any]:
    public = trusted_key.public_key()
    return {"keys": [_jwk_from_public_key(public, kid="trusted-kid-1")]}


@pytest.fixture
def verifier(monkeypatch: pytest.MonkeyPatch, jwks_document: dict[str, Any]) -> JwtVerifier:
    v = JwtVerifier(
        jwks_url="https://idp.test.local/.well-known/jwks.json",
        audience=_AUDIENCE,
        issuer=_ISSUER,
        cache_ttl_s=900.0,
    )

    def _fake_client(self: JwtVerifier) -> PyJWKClient:
        return _FakeJwkClient(jwks_document)  # type: ignore[return-value]

    monkeypatch.setattr(JwtVerifier, "_new_client", _fake_client)
    return v


def _mint_token(
    private_key: rsa.RSAPrivateKey,
    *,
    kid: str = "trusted-kid-1",
    audience: str = _AUDIENCE,
    issuer: str | None = _ISSUER,
    tenant_id: str | None = "tenant-a",
    exp_delta_s: int = 300,
    include_exp: bool = True,
    algorithm: str = "RS256",
) -> str:
    now = int(time.time())
    payload: dict[str, Any] = {
        "sub": "user-" + uuid.uuid4().hex[:8],
        "iat": now,
        "aud": audience,
    }
    if include_exp:
        payload["exp"] = now + exp_delta_s
    if issuer is not None:
        payload["iss"] = issuer
    if tenant_id is not None:
        payload["tenant_id"] = tenant_id
    return jwt.encode(
        payload,
        _private_pem(private_key),
        algorithm=algorithm,
        headers={"kid": kid},
    )


# ---------------------------------------------------------------------------
# Verifier-level tests (unit)
# ---------------------------------------------------------------------------


def test_verifier_accepts_trusted_token(
    verifier: JwtVerifier, trusted_key: rsa.RSAPrivateKey
) -> None:
    token = _mint_token(trusted_key)
    claims = verifier.verify(token)
    assert claims["aud"] == _AUDIENCE
    assert claims["tenant_id"] == "tenant-a"


def test_verifier_rejects_wrong_key(verifier: JwtVerifier, attacker_key: rsa.RSAPrivateKey) -> None:
    # Same ``kid`` as the trusted key, but signed with a completely
    # independent private key. The signature check must fail.
    forged = _mint_token(attacker_key, kid="trusted-kid-1")
    with pytest.raises(VerificationError) as excinfo:
        verifier.verify(forged)
    assert excinfo.value.reason == "bad_signature"


def test_verifier_rejects_expired_token(
    verifier: JwtVerifier, trusted_key: rsa.RSAPrivateKey
) -> None:
    token = _mint_token(trusted_key, exp_delta_s=-600)
    with pytest.raises(VerificationError) as excinfo:
        verifier.verify(token)
    assert excinfo.value.reason == "expired"


def test_verifier_rejects_wrong_audience(
    verifier: JwtVerifier, trusted_key: rsa.RSAPrivateKey
) -> None:
    token = _mint_token(trusted_key, audience="some-other-audience")
    with pytest.raises(VerificationError) as excinfo:
        verifier.verify(token)
    assert excinfo.value.reason == "bad_audience"


def test_verifier_rejects_missing_exp(
    verifier: JwtVerifier, trusted_key: rsa.RSAPrivateKey
) -> None:
    token = _mint_token(trusted_key, include_exp=False)
    with pytest.raises(VerificationError) as excinfo:
        verifier.verify(token)
    assert excinfo.value.reason == "missing_exp"


def test_verifier_rejects_unknown_kid(
    verifier: JwtVerifier, trusted_key: rsa.RSAPrivateKey
) -> None:
    token = _mint_token(trusted_key, kid="not-in-the-jwks")
    with pytest.raises(VerificationError) as excinfo:
        verifier.verify(token)
    assert excinfo.value.reason == "unknown_kid"


def test_verifier_rejects_alg_none(verifier: JwtVerifier, trusted_key: rsa.RSAPrivateKey) -> None:
    # A raw ``alg=none`` header is one of the classic JWT attacks; the
    # verifier's algorithm allow-list must short-circuit before signature
    # verification runs.
    unsigned = jwt.encode(
        {"aud": _AUDIENCE, "exp": int(time.time()) + 60},
        key="",
        algorithm="none",
        headers={"kid": "trusted-kid-1"},
    )
    with pytest.raises(VerificationError) as excinfo:
        verifier.verify(unsigned)
    assert excinfo.value.reason == "bad_algorithm"


def test_verifier_rejects_wrong_issuer(
    verifier: JwtVerifier, trusted_key: rsa.RSAPrivateKey
) -> None:
    token = _mint_token(trusted_key, issuer="https://attacker.example/")
    with pytest.raises(VerificationError) as excinfo:
        verifier.verify(token)
    assert excinfo.value.reason == "bad_issuer"


def test_verifier_rejects_malformed_token(verifier: JwtVerifier) -> None:
    with pytest.raises(VerificationError) as excinfo:
        verifier.verify("not-even-a-jwt")
    assert excinfo.value.reason == "malformed_token"


# ---------------------------------------------------------------------------
# Middleware/transport tests
# ---------------------------------------------------------------------------


def test_build_app_requires_jwt_config(monkeypatch: pytest.MonkeyPatch) -> None:
    from expense_mcp_server.settings import Settings, get_settings

    get_settings.cache_clear()
    # Explicitly wipe the JWT config so we prove fail-closed startup.
    monkeypatch.setenv("EXPENSE_MCP_JWKS_URL", "")
    monkeypatch.setenv("EXPENSE_MCP_JWT_AUDIENCE", "")
    with pytest.raises(SseAuthNotConfiguredError):
        _build_verifier(Settings())


def test_sse_valid_token_authorized(verifier: JwtVerifier, trusted_key: rsa.RSAPrivateKey) -> None:
    """A trusted-key token traverses the middleware and reaches the app.

    We hit ``/messages/`` (FastMCP's message endpoint) with a valid
    bearer; the auth middleware must let it pass. Whatever the SSE
    subsystem then returns for an unknown session id is fine — the
    invariant we care about is *not 401*, i.e. the forged-token oracle
    stays silent for legitimate callers.
    """
    app = build_app(verifier=verifier)
    token = _mint_token(trusted_key)
    with TestClient(app) as client:
        r = client.post(
            "/messages/?session_id=nope",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert r.status_code != 401


def test_sse_missing_bearer_rejected(verifier: JwtVerifier) -> None:
    app = build_app(verifier=verifier)
    with TestClient(app) as client:
        r = client.get("/sse")
    assert r.status_code == 401
    body = r.json()
    assert body["error"]["code"] == CODE_FORBIDDEN
    assert body["error"]["message"] == "forbidden"


def test_sse_malformed_bearer_rejected(verifier: JwtVerifier) -> None:
    app = build_app(verifier=verifier)
    with TestClient(app) as client:
        r = client.get("/sse", headers={"Authorization": "NotBearer abc"})
    assert r.status_code == 401
    assert r.json()["error"]["code"] == CODE_FORBIDDEN


def test_sse_forged_token_rejected(verifier: JwtVerifier, attacker_key: rsa.RSAPrivateKey) -> None:
    forged = _mint_token(attacker_key)
    app = build_app(verifier=verifier)
    with TestClient(app) as client:
        r = client.get("/sse", headers={"Authorization": f"Bearer {forged}"})
    assert r.status_code == 401
    # External reason is stable so an attacker can't oracle which check failed.
    assert r.json()["error"]["message"] == "forbidden"


def test_sse_expired_token_rejected(verifier: JwtVerifier, trusted_key: rsa.RSAPrivateKey) -> None:
    expired = _mint_token(trusted_key, exp_delta_s=-600)
    app = build_app(verifier=verifier)
    with TestClient(app) as client:
        r = client.get("/sse", headers={"Authorization": f"Bearer {expired}"})
    assert r.status_code == 401
    assert r.json()["error"]["message"] == "forbidden"


def test_sse_wrong_audience_token_rejected(
    verifier: JwtVerifier, trusted_key: rsa.RSAPrivateKey
) -> None:
    bad_aud = _mint_token(trusted_key, audience="not-us")
    app = build_app(verifier=verifier)
    with TestClient(app) as client:
        r = client.get("/sse", headers={"Authorization": f"Bearer {bad_aud}"})
    assert r.status_code == 401


def test_sse_unknown_kid_token_rejected(
    verifier: JwtVerifier, trusted_key: rsa.RSAPrivateKey
) -> None:
    bad_kid = _mint_token(trusted_key, kid="not-in-jwks")
    app = build_app(verifier=verifier)
    with TestClient(app) as client:
        r = client.get("/sse", headers={"Authorization": f"Bearer {bad_kid}"})
    assert r.status_code == 401


def test_sse_missing_exp_token_rejected(
    verifier: JwtVerifier, trusted_key: rsa.RSAPrivateKey
) -> None:
    no_exp = _mint_token(trusted_key, include_exp=False)
    app = build_app(verifier=verifier)
    with TestClient(app) as client:
        r = client.get("/sse", headers={"Authorization": f"Bearer {no_exp}"})
    assert r.status_code == 401


def test_healthz_is_public(verifier: JwtVerifier) -> None:
    app = build_app(verifier=verifier)
    with TestClient(app) as client:
        r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


# ---------------------------------------------------------------------------
# Tenant-context tests (unchanged)
# ---------------------------------------------------------------------------


def test_parse_bearer_happy_path() -> None:
    assert parse_bearer("Bearer synthetic-test-token") == "synthetic-test-token"


def test_assert_tenant_matches_rejects_mismatch() -> None:
    set_context(RequestContext(tenant_id="tenant-a", bearer="synthetic"))
    try:
        assert_tenant_matches("tenant-a")
        raised = False
        try:
            assert_tenant_matches("tenant-b")
        except McpError as exc:
            raised = True
            assert exc.error.code == CODE_FORBIDDEN
        assert raised
    finally:
        clear_context()


def test_assert_tenant_matches_noop_without_context() -> None:
    clear_context()
    assert_tenant_matches("tenant-a")
