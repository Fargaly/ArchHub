"""Issuer-pinned OpenID Connect discovery and rotating JWKS resolution.

The issuer is administrator configuration, never a token input.  Discovery and
JWKS responses are bounded, redirects are refused, the metadata issuer must be
an exact match, and the JWKS origin must be explicitly allowlisted.  Only
public asymmetric signing keys enter the in-memory JOSE cache.
"""
from __future__ import annotations

from dataclasses import dataclass
import hmac
import json
import re
import threading
import time
from typing import Callable, Mapping
from urllib.parse import urlsplit

import httpx


class OidcDiscoveryDenied(PermissionError):
    pass


_PRIVATE_JWK_MEMBERS = frozenset({
    "d", "k", "p", "q", "dp", "dq", "qi", "oth",
})
_KID = re.compile(r"^[\x21-\x7E]{1,128}$")
_MAX_JSON_BYTES = 1024 * 1024


@dataclass(frozen=True, slots=True)
class OidcDiscoverySnapshot:
    issuer: str
    discovery_url: str
    jwks_uri: str
    key_ids: tuple[str, ...]
    metadata_expires_at: float
    jwks_expires_at: float
    authorization_endpoint: str | None = None
    token_endpoint: str | None = None
    response_types: tuple[str, ...] = ()
    code_challenge_methods: tuple[str, ...] = ()
    authorization_response_issuer_supported: bool = False


_DISCOVERY_AUTHORITY_KEY = object()


class VerifiedOidcDiscovery:
    """Resolver-only, short-lived authority for native client registration."""

    __slots__ = ("snapshot",)

    def __init__(self, key: object, snapshot: OidcDiscoverySnapshot) -> None:
        if key is not _DISCOVERY_AUTHORITY_KEY:
            raise TypeError("verified OIDC discovery is resolver authority")
        self.snapshot = snapshot

    def __reduce_ex__(self, protocol):
        raise TypeError("verified OIDC discovery cannot be serialized")


def _origin(url: str) -> str:
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except (TypeError, ValueError) as exc:
        raise OidcDiscoveryDenied("OIDC URL is invalid") from exc
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise OidcDiscoveryDenied("OIDC URL must use an HTTPS authority")
    host = parsed.hostname.encode("idna").decode("ascii").lower()
    if ":" in host:
        host = "[" + host + "]"
    authority = host if port in (None, 443) else "%s:%s" % (host, port)
    return "https://" + authority


def _discovery_url(issuer: str) -> str:
    parsed = urlsplit(issuer)
    if parsed.query or parsed.fragment:
        raise OidcDiscoveryDenied("OIDC issuer may not contain query or fragment")
    _origin(issuer)
    return issuer.rstrip("/") + "/.well-known/openid-configuration"


def _cache_seconds(headers: httpx.Headers, *, default: int) -> int:
    cache_control = headers.get("cache-control", "")
    for directive in cache_control.split(","):
        name, separator, value = directive.strip().partition("=")
        if separator and name.lower() == "max-age":
            try:
                return max(30, min(int(value.strip('"')), 3600))
            except ValueError:
                break
    return max(30, min(default, 3600))


class OidcDiscoveryKeyResolver:
    """Callable joserfc key resolver with bounded discovery/JWKS rotation."""

    def __init__(
        self,
        *,
        issuer: str,
        allowed_jwks_origins: tuple[str, ...] = (),
        allowed_endpoint_origins: tuple[str, ...] = (),
        allowed_algorithms: tuple[str, ...] = (
            "ES256", "PS256", "RS256", "EdDSA"
        ),
        client: httpx.Client | None = None,
        clock: Callable[[], float] = time.time,
        default_cache_seconds: int = 300,
        forced_refresh_interval_seconds: int = 10,
    ) -> None:
        self.issuer = issuer
        self.discovery_url = _discovery_url(self.issuer)
        issuer_origin = _origin(self.issuer)
        origins = allowed_jwks_origins or (issuer_origin,)
        normalized = tuple(dict.fromkeys(_origin(value) for value in origins))
        endpoint_origins = allowed_endpoint_origins or (issuer_origin,)
        normalized_endpoints = tuple(dict.fromkeys(
            _origin(value) for value in endpoint_origins
        ))
        if not allowed_algorithms or any(
            algorithm == "none" or algorithm.startswith("HS")
            for algorithm in allowed_algorithms
        ):
            raise ValueError("OIDC discovery requires asymmetric algorithms")
        if default_cache_seconds < 30 or default_cache_seconds > 3600:
            raise ValueError("OIDC discovery cache bound is invalid")
        if not (1 <= forced_refresh_interval_seconds <= 300):
            raise ValueError("OIDC JWKS refresh interval is invalid")
        self.allowed_jwks_origins = frozenset(normalized)
        self.allowed_endpoint_origins = frozenset(normalized_endpoints)
        self.allowed_algorithms = tuple(dict.fromkeys(allowed_algorithms))
        self._client = client or httpx.Client(
            timeout=httpx.Timeout(5.0, connect=3.0),
            follow_redirects=False,
        )
        self._owns_client = client is None
        self._clock = clock
        self._default_cache_seconds = int(default_cache_seconds)
        self._forced_refresh_interval = int(forced_refresh_interval_seconds)
        self._lock = threading.RLock()
        self._jwks_uri = ""
        self._authorization_endpoint: str | None = None
        self._token_endpoint: str | None = None
        self._response_types: tuple[str, ...] = ()
        self._code_challenge_methods: tuple[str, ...] = ()
        self._authorization_response_issuer_supported = False
        self._metadata_expires_at = 0.0
        self._jwks_expires_at = 0.0
        self._last_forced_refresh = float("-inf")
        self._key_ids: frozenset[str] = frozenset()
        self._key_set: object | None = None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def _fetch_json(
        self, url: str, *, content_types: frozenset[str]
    ) -> tuple[Mapping[str, object], int]:
        try:
            with self._client.stream(
                "GET",
                url,
                headers={"Accept": ", ".join(sorted(content_types))},
                follow_redirects=False,
            ) as response:
                if response.status_code != 200:
                    raise OidcDiscoveryDenied(
                        "OIDC metadata endpoint did not return 200"
                    )
                content_type = response.headers.get(
                    "content-type", ""
                ).split(";", 1)[0].strip().lower()
                if content_type not in content_types:
                    raise OidcDiscoveryDenied(
                        "OIDC metadata content type is invalid"
                    )
                length = response.headers.get("content-length")
                if length:
                    try:
                        if int(length) > _MAX_JSON_BYTES:
                            raise OidcDiscoveryDenied(
                                "OIDC metadata response is too large"
                            )
                    except ValueError as exc:
                        raise OidcDiscoveryDenied(
                            "OIDC metadata Content-Length is invalid"
                        ) from exc
                body = bytearray()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body) > _MAX_JSON_BYTES:
                        raise OidcDiscoveryDenied(
                            "OIDC metadata response is too large"
                        )
                content = bytes(body)
                response_headers = response.headers
        except httpx.HTTPError as exc:
            raise OidcDiscoveryDenied("OIDC metadata transport failed") from exc
        try:
            payload = json.loads(content)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise OidcDiscoveryDenied("OIDC metadata JSON is invalid") from exc
        if not isinstance(payload, dict):
            raise OidcDiscoveryDenied("OIDC metadata must be a JSON object")
        return payload, _cache_seconds(
            response_headers, default=self._default_cache_seconds
        )

    def _refresh_metadata(self, now: float) -> None:
        payload, cache_seconds = self._fetch_json(
            self.discovery_url, content_types=frozenset({"application/json"})
        )
        discovered_issuer = payload.get("issuer")
        if not isinstance(discovered_issuer, str) or not hmac.compare_digest(
            discovered_issuer, self.issuer
        ):
            raise OidcDiscoveryDenied("discovery issuer mismatched configured issuer")
        jwks_uri = payload.get("jwks_uri")
        if not isinstance(jwks_uri, str) or _origin(jwks_uri) not in self.allowed_jwks_origins:
            raise OidcDiscoveryDenied("discovery JWKS origin is not allowlisted")
        algorithms = payload.get("id_token_signing_alg_values_supported")
        if (
            not isinstance(algorithms, list)
            or not algorithms
            or not all(isinstance(value, str) for value in algorithms)
            or not set(algorithms).intersection(self.allowed_algorithms)
        ):
            raise OidcDiscoveryDenied("discovery has no allowed ID-token algorithm")
        authorization_endpoint = payload.get("authorization_endpoint")
        token_endpoint = payload.get("token_endpoint")
        for name, value in (
            ("authorization", authorization_endpoint),
            ("token", token_endpoint),
        ):
            if value is not None and (
                not isinstance(value, str)
                or _origin(value) not in self.allowed_endpoint_origins
            ):
                raise OidcDiscoveryDenied(
                    "discovery %s endpoint origin is not allowlisted" % name
                )
        response_types = payload.get("response_types_supported", ())
        if not isinstance(response_types, list) or not all(
            isinstance(value, str) and value for value in response_types
        ):
            raise OidcDiscoveryDenied(
                "discovery response types are invalid"
            )
        challenge_methods = payload.get(
            "code_challenge_methods_supported", ()
        )
        if not isinstance(challenge_methods, list) or not all(
            isinstance(value, str) and value for value in challenge_methods
        ):
            raise OidcDiscoveryDenied(
                "discovery PKCE methods are invalid"
            )
        response_issuer = payload.get(
            "authorization_response_iss_parameter_supported", False
        )
        if not isinstance(response_issuer, bool):
            raise OidcDiscoveryDenied(
                "discovery authorization-response issuer support is invalid"
            )
        self._jwks_uri = jwks_uri
        self._authorization_endpoint = authorization_endpoint
        self._token_endpoint = token_endpoint
        self._response_types = tuple(dict.fromkeys(response_types))
        self._code_challenge_methods = tuple(dict.fromkeys(challenge_methods))
        self._authorization_response_issuer_supported = response_issuer
        self._metadata_expires_at = now + cache_seconds

    def _refresh_jwks(self, now: float) -> None:
        if not self._jwks_uri or now >= self._metadata_expires_at:
            self._refresh_metadata(now)
        payload, cache_seconds = self._fetch_json(
            self._jwks_uri,
            content_types=frozenset({
                "application/json", "application/jwk-set+json"
            }),
        )
        keys = payload.get("keys")
        if not isinstance(keys, list) or not (1 <= len(keys) <= 100):
            raise OidcDiscoveryDenied("OIDC JWKS key count is invalid")
        accepted: list[dict[str, object]] = []
        key_ids: set[str] = set()
        for raw_key in keys:
            if not isinstance(raw_key, dict):
                raise OidcDiscoveryDenied("OIDC JWKS contains a non-object key")
            if _PRIVATE_JWK_MEMBERS.intersection(raw_key):
                raise OidcDiscoveryDenied("OIDC JWKS contains private or symmetric material")
            if raw_key.get("kty") not in {"RSA", "EC", "OKP"}:
                raise OidcDiscoveryDenied("OIDC JWKS contains a non-asymmetric key")
            use = raw_key.get("use")
            if use not in (None, "sig"):
                continue
            operations = raw_key.get("key_ops")
            if operations is not None and (
                not isinstance(operations, list)
                or "verify" not in operations
                or any(value != "verify" for value in operations)
            ):
                continue
            algorithm = raw_key.get("alg")
            if algorithm is not None and algorithm not in self.allowed_algorithms:
                continue
            key_id = raw_key.get("kid")
            if not isinstance(key_id, str) or not _KID.fullmatch(key_id):
                raise OidcDiscoveryDenied("OIDC signing key has no valid kid")
            if key_id in key_ids:
                raise OidcDiscoveryDenied("OIDC JWKS contains duplicate kid values")
            key_ids.add(key_id)
            accepted.append(raw_key)
        if not accepted:
            raise OidcDiscoveryDenied("OIDC JWKS contains no allowed signing key")
        try:
            from joserfc.jwk import KeySet

            key_set = KeySet.import_key_set({"keys": accepted})
        except Exception as exc:
            raise OidcDiscoveryDenied("OIDC JWKS key import failed") from exc
        self._key_set = key_set
        self._key_ids = frozenset(key_ids)
        self._jwks_expires_at = now + cache_seconds

    def preload(self) -> OidcDiscoverySnapshot:
        with self._lock:
            now = self._clock()
            self._refresh_jwks(now)
            return self.snapshot()

    def native_client_authority(self) -> VerifiedOidcDiscovery:
        """Refresh discovery/JWKS and mint one process-local authority."""
        return VerifiedOidcDiscovery(_DISCOVERY_AUTHORITY_KEY, self.preload())

    def snapshot(self) -> OidcDiscoverySnapshot:
        with self._lock:
            if self._key_set is None:
                raise OidcDiscoveryDenied("OIDC discovery keys are not loaded")
            return OidcDiscoverySnapshot(
                self.issuer,
                self.discovery_url,
                self._jwks_uri,
                tuple(sorted(self._key_ids)),
                self._metadata_expires_at,
                self._jwks_expires_at,
                self._authorization_endpoint,
                self._token_endpoint,
                self._response_types,
                self._code_challenge_methods,
                self._authorization_response_issuer_supported,
            )

    def __call__(self, obj: object) -> object:
        try:
            headers = obj.headers()  # type: ignore[attr-defined]
        except Exception as exc:
            raise OidcDiscoveryDenied("OIDC JOSE headers are unavailable") from exc
        if not isinstance(headers, dict):
            raise OidcDiscoveryDenied("OIDC JOSE headers are invalid")
        if "jku" in headers or "x5u" in headers or "jwk" in headers:
            raise OidcDiscoveryDenied("OIDC token may not select verification keys")
        algorithm = headers.get("alg")
        key_id = headers.get("kid")
        if algorithm not in self.allowed_algorithms:
            raise OidcDiscoveryDenied("OIDC token algorithm is not allowed")
        if not isinstance(key_id, str) or not _KID.fullmatch(key_id):
            raise OidcDiscoveryDenied("OIDC token kid is invalid")
        with self._lock:
            now = self._clock()
            if self._key_set is None or now >= self._jwks_expires_at:
                self._refresh_jwks(now)
            if key_id not in self._key_ids:
                if now - self._last_forced_refresh < self._forced_refresh_interval:
                    raise OidcDiscoveryDenied("OIDC token kid is not in the current JWKS")
                self._last_forced_refresh = now
                self._refresh_jwks(now)
            if key_id not in self._key_ids or self._key_set is None:
                raise OidcDiscoveryDenied("OIDC token kid is not in the refreshed JWKS")
            return self._key_set


__all__ = [
    "OidcDiscoveryDenied",
    "OidcDiscoveryKeyResolver",
    "OidcDiscoverySnapshot",
    "VerifiedOidcDiscovery",
]
