"""RFC 9449 DPoP verification using the maintained joserfc JOSE library."""
from __future__ import annotations

import base64
import hashlib
import hmac
import re
from urllib.parse import SplitResult, urlsplit, urlunsplit


class DpopProofDenied(PermissionError):
    pass


_PRIVATE_JWK_MEMBERS = frozenset({
    "d", "k", "p", "q", "dp", "dq", "qi", "oth",
})
_UNRESERVED = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~"
)
_PERCENT_ESCAPE = re.compile(r"%([0-9A-Fa-f]{2})")


def _base64url_sha256(value: bytes) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(value).digest()).rstrip(
        b"="
    ).decode("ascii")


def _normalize_percent_encoding(value: str) -> str:
    def replace(match: re.Match[str]) -> str:
        char = chr(int(match.group(1), 16))
        return char if char in _UNRESERVED else "%" + match.group(1).upper()

    return _PERCENT_ESCAPE.sub(replace, value)


def _normalized_http_uri(value: str, *, claim: bool) -> str:
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except (TypeError, ValueError) as exc:
        raise DpopProofDenied("DPoP target URI is invalid") from exc
    scheme = parsed.scheme.lower()
    if not parsed.hostname or parsed.username is not None or parsed.password is not None:
        raise DpopProofDenied("DPoP target URI authority is invalid")
    host = parsed.hostname.encode("idna").decode("ascii").lower()
    if scheme != "https" and not (
        scheme == "http" and host in {"localhost", "127.0.0.1", "::1"}
    ):
        raise DpopProofDenied("DPoP target URI requires HTTPS")
    if claim and (parsed.query or parsed.fragment):
        raise DpopProofDenied("DPoP htu must omit query and fragment")
    if ":" in host and not host.startswith("["):
        host = "[" + host + "]"
    default_port = (scheme == "https" and port == 443) or (
        scheme == "http" and port == 80
    )
    authority = host if port is None or default_port else "%s:%s" % (host, port)
    path = _normalize_percent_encoding(parsed.path or "/")
    if "/./" in path or "/../" in path or path.endswith(("/.", "/..")):
        raise DpopProofDenied("DPoP target URI contains dot segments")
    return urlunsplit(SplitResult(scheme, authority, path, "", ""))


def normalize_dpop_target_uri(value: str) -> str:
    """Return the RFC 9449 request URI form used in an `htu` claim."""
    return _normalized_http_uri(value, claim=False)


class JoseRfc9449ProofVerifier:
    """Strict embedded-public-JWK DPoP proof verifier.

    Replay storage belongs to ``CloudSessionBroker`` because it must commit in
    the same universal authority as the session. This class verifies the JOSE
    proof and returns its `jti` for that atomic replay record.
    """

    def __init__(
        self,
        *,
        allowed_algorithms: tuple[str, ...] = ("ES256", "PS256", "EdDSA"),
        max_age_seconds: float = 60.0,
        future_skew_seconds: float = 5.0,
    ) -> None:
        if not allowed_algorithms:
            raise ValueError("DPoP requires an asymmetric algorithm allowlist")
        if any(
            algorithm == "none" or algorithm.startswith("HS")
            for algorithm in allowed_algorithms
        ):
            raise ValueError("DPoP algorithms must be asymmetric")
        if max_age_seconds <= 0 or future_skew_seconds < 0:
            raise ValueError("DPoP time windows are invalid")
        self._allowed_algorithms = tuple(dict.fromkeys(allowed_algorithms))
        self._max_age_seconds = max_age_seconds
        self._future_skew_seconds = future_skew_seconds

    def verify(
        self,
        proof: bytes,
        *,
        access_token: str,
        expected_thumbprint: str,
        http_method: str,
        target_uri: str,
        expected_nonce: str,
        now: float,
    ) -> str:
        try:
            from joserfc import jwk, jwt
        except ImportError as exc:  # pragma: no cover - deployment fault
            raise DpopProofDenied("joserfc DPoP verifier is unavailable") from exc
        try:
            compact = bytes(proof).decode("ascii")
        except UnicodeDecodeError as exc:
            raise DpopProofDenied("DPoP proof is not compact ASCII JWS") from exc
        if not access_token or not expected_nonce:
            raise DpopProofDenied("DPoP token and nonce are required")
        resolved: dict[str, object] = {}

        def embedded_public_key(obj):
            header = obj.headers()
            if header.get("typ") != "dpop+jwt":
                raise DpopProofDenied("DPoP typ is invalid")
            algorithm = header.get("alg")
            if algorithm not in self._allowed_algorithms:
                raise DpopProofDenied("DPoP algorithm is not allowed")
            value = header.get("jwk")
            if not isinstance(value, dict):
                raise DpopProofDenied("DPoP proof has no embedded public JWK")
            if _PRIVATE_JWK_MEMBERS.intersection(value):
                raise DpopProofDenied("DPoP proof contains private JWK material")
            if "jku" in header or "x5u" in header:
                raise DpopProofDenied("DPoP proof may not select a remote key")
            thumbprint = jwk.thumbprint(value)
            if not hmac.compare_digest(thumbprint, expected_thumbprint):
                raise DpopProofDenied("DPoP proof key is not session-bound")
            resolved["thumbprint"] = thumbprint
            return jwk.import_key(value)

        try:
            token = jwt.decode(
                compact,
                embedded_public_key,
                algorithms=self._allowed_algorithms,
            )
        except DpopProofDenied:
            raise
        except Exception as exc:
            raise DpopProofDenied("DPoP signature verification failed") from exc
        if resolved.get("thumbprint") != expected_thumbprint:
            raise DpopProofDenied("DPoP proof key was not resolved")
        claims = token.claims
        required = ("jti", "htm", "htu", "iat", "ath", "nonce")
        if any(name not in claims for name in required):
            raise DpopProofDenied("DPoP proof is missing required claims")
        proof_id = claims["jti"]
        if (
            not isinstance(proof_id, str)
            or len(proof_id) < 16
            or len(proof_id) > 256
        ):
            raise DpopProofDenied("DPoP jti is invalid")
        if not isinstance(claims["htm"], str) or claims["htm"].upper() != http_method.upper():
            raise DpopProofDenied("DPoP HTTP method mismatched")
        if not isinstance(claims["htu"], str) or _normalized_http_uri(
            claims["htu"], claim=True
        ) != _normalized_http_uri(target_uri, claim=False):
            raise DpopProofDenied("DPoP target URI mismatched")
        issued_at = claims["iat"]
        if isinstance(issued_at, bool) or not isinstance(issued_at, (int, float)):
            raise DpopProofDenied("DPoP iat is invalid")
        age = now - float(issued_at)
        if age < -self._future_skew_seconds or age > self._max_age_seconds:
            raise DpopProofDenied("DPoP proof is outside its time window")
        if not isinstance(claims["nonce"], str) or not hmac.compare_digest(
            claims["nonce"], expected_nonce
        ):
            raise DpopProofDenied("DPoP server nonce mismatched")
        expected_ath = _base64url_sha256(access_token.encode("ascii"))
        if not isinstance(claims["ath"], str) or not hmac.compare_digest(
            claims["ath"], expected_ath
        ):
            raise DpopProofDenied("DPoP access-token hash mismatched")
        return proof_id


__all__ = [
    "DpopProofDenied",
    "JoseRfc9449ProofVerifier",
    "normalize_dpop_target_uri",
]
