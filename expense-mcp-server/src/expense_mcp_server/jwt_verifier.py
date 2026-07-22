"""Cryptographic JWT verification for the SSE transport.

The SSE boundary must reject any bearer token whose signature, expiry,
or audience cannot be verified against a trusted JWKS. This module
owns that check. It is used exclusively by
:mod:`expense_mcp_server.transports.sse`; the stdio transport does not
receive external requests and therefore does not need verification.

Design goals:

* **Fail closed on missing configuration.** If ``EXPENSE_MCP_JWKS_URL``
  or ``EXPENSE_MCP_JWT_AUDIENCE`` is unset, the SSE app refuses to build
  — see :func:`transports.sse.build_app`. There is no presence-only
  fallback.
* **RS256 only by default.** The algorithm allow-list is passed to
  ``jwt.decode(algorithms=...)`` so a token with ``alg=none``, ``HS256``
  key confusion, or any other unlisted algorithm is rejected before the
  signature check even runs.
* **Bounded JWKS cache.** The JWKS document is fetched once at first use
  and reused for ``jwks_cache_ttl_s`` seconds. A single refresh is
  triggered when an unknown ``kid`` is seen, so a legitimate key
  rotation resolves without a restart; a second unknown-``kid`` failure
  in the same window rejects the token.
* **No token in logs.** The middleware logs a coarse ``reason`` category
  (``expired``, ``bad_audience``, ``bad_signature``, …). It never logs
  the raw token, and the externally-visible response is identical for
  every rejection so a caller cannot probe which check failed.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import httpx
import jwt
from jwt import PyJWKClient
from jwt.exceptions import (
    DecodeError,
    ExpiredSignatureError,
    InvalidAudienceError,
    InvalidIssuerError,
    InvalidSignatureError,
    InvalidTokenError,
    MissingRequiredClaimError,
    PyJWKClientError,
)
from jwt.types import Options

# Algorithms accepted by :meth:`JwtVerifier.verify`. RS256 covers most
# OIDC providers; ES256 is included as a common ECDSA option. HS* is
# deliberately absent — a symmetric secret shipped in server settings
# would let anyone with read access to the deployment forge tokens.
DEFAULT_ALLOWED_ALGS: tuple[str, ...] = ("RS256", "RS384", "RS512", "ES256")


class VerificationError(Exception):
    """Raised by :class:`JwtVerifier` when a token cannot be verified.

    The ``reason`` attribute is a short, stable category suitable for
    stderr logs and metrics. It is never surfaced verbatim to the
    caller so an attacker cannot use rejection strings as an oracle.
    """

    __slots__ = ("reason",)

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass
class _CachedJwks:
    client: PyJWKClient
    fetched_at: float
    seen_kids: set[str] = field(default_factory=set)


class JwtVerifier:
    """Verify a bearer JWT against a JWKS document with bounded caching.

    ``PyJWKClient`` handles the JWKS fetch and per-``kid`` public-key
    selection. We wrap it so we can (a) enforce a TTL on the cached
    document, (b) trigger one deliberate refresh when an unknown
    ``kid`` is encountered, and (c) present a uniform
    :class:`VerificationError` to the middleware.
    """

    def __init__(
        self,
        *,
        jwks_url: str,
        audience: str,
        issuer: str | None,
        allowed_algorithms: Sequence[str] = DEFAULT_ALLOWED_ALGS,
        cache_ttl_s: float = 900.0,
        http_timeout_s: float = 5.0,
        clock_skew_s: int = 30,
    ) -> None:
        if not jwks_url:
            # This constructor invariant complements the config check in
            # transports/sse.py — building a verifier without a JWKS URL
            # is an internal bug, not a runtime request condition.
            raise ValueError("jwks_url is required")
        if not audience:
            raise ValueError("audience is required")
        self._jwks_url = jwks_url
        self._audience = audience
        self._issuer = issuer or None
        self._allowed_algorithms = tuple(allowed_algorithms)
        self._cache_ttl_s = cache_ttl_s
        self._http_timeout_s = http_timeout_s
        self._clock_skew_s = clock_skew_s
        self._lock = threading.Lock()
        self._cache: _CachedJwks | None = None

    def _new_client(self) -> PyJWKClient:
        # Explicit timeout so a hung IdP cannot stall the request path.
        return PyJWKClient(self._jwks_url, cache_keys=True, timeout=self._http_timeout_s)

    def _get_client(self, *, force_refresh: bool = False) -> PyJWKClient:
        now = time.monotonic()
        with self._lock:
            cache = self._cache
            expired = cache is None or (now - cache.fetched_at) > self._cache_ttl_s
            if force_refresh or expired:
                self._cache = _CachedJwks(client=self._new_client(), fetched_at=now)
            assert self._cache is not None
            return self._cache.client

    def _signing_key(self, token: str, *, force_refresh: bool) -> Any:
        client = self._get_client(force_refresh=force_refresh)
        try:
            return client.get_signing_key_from_jwt(token).key
        except PyJWKClientError as exc:
            # Distinguish network failure from unknown-``kid`` so the
            # caller can decide whether to trigger a JWKS refresh.
            raise VerificationError("unknown_kid") from exc
        except (httpx.HTTPError, ValueError) as exc:  # pragma: no cover - network path
            raise VerificationError("jwks_unavailable") from exc

    def verify(self, token: str) -> dict[str, Any]:
        """Verify ``token`` and return its claims.

        Raises :class:`VerificationError` if any check fails. The
        ``reason`` attribute is intended for internal logs only.
        """
        # Reject alg=none and unlisted algorithms before we even fetch a
        # key. ``jwt.get_unverified_header`` does not verify the signature;
        # we use it strictly to guide key selection.
        try:
            header = jwt.get_unverified_header(token)
        except (DecodeError, InvalidTokenError) as exc:
            raise VerificationError("malformed_token") from exc

        alg = header.get("alg")
        if not isinstance(alg, str) or alg not in self._allowed_algorithms:
            raise VerificationError("bad_algorithm")

        kid = header.get("kid")
        if not isinstance(kid, str) or not kid:
            raise VerificationError("missing_kid")

        # If the ``kid`` is not in our cached document, do exactly one
        # refresh — the common cause is a legitimate key rotation on the
        # IdP. A second unknown-``kid`` after refresh is fatal.
        key = self._try_key(token, force_refresh=False)
        if key is None:
            key = self._try_key(token, force_refresh=True)
            if key is None:
                raise VerificationError("unknown_kid")

        # Every rejection path is enumerated explicitly so a future
        # library default cannot silently loosen validation.
        options: Options = {
            "require": ["exp", "aud"],
            "verify_signature": True,
            "verify_exp": True,
            "verify_aud": True,
            "verify_iss": self._issuer is not None,
            "verify_nbf": True,
            "verify_iat": False,
        }
        try:
            claims: dict[str, Any] = jwt.decode(
                token,
                key=key,
                algorithms=list(self._allowed_algorithms),
                audience=self._audience,
                issuer=self._issuer,
                leeway=self._clock_skew_s,
                options=options,
            )
        except ExpiredSignatureError as exc:
            raise VerificationError("expired") from exc
        except InvalidAudienceError as exc:
            raise VerificationError("bad_audience") from exc
        except InvalidIssuerError as exc:
            raise VerificationError("bad_issuer") from exc
        except InvalidSignatureError as exc:
            raise VerificationError("bad_signature") from exc
        except MissingRequiredClaimError as exc:
            # Distinguish the two required claims we care about so
            # log-based diagnostics stay useful; the wire response is
            # still identical.
            claim = getattr(exc, "claim", "")
            reason = "missing_exp" if claim == "exp" else "missing_aud"
            raise VerificationError(reason) from exc
        except InvalidTokenError as exc:
            raise VerificationError("invalid_token") from exc
        return claims

    def _try_key(self, token: str, *, force_refresh: bool) -> Any | None:
        try:
            return self._signing_key(token, force_refresh=force_refresh)
        except VerificationError as exc:
            if exc.reason == "unknown_kid":
                return None
            raise
