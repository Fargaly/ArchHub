"""OpenID Connect ID-token court runner using joserfc JOSE verification."""
from __future__ import annotations

import hashlib
import hmac
import time
from types import MappingProxyType
from typing import Callable, Mapping

from .cell_attestations import CourtInvocation, CourtResult
from .cell_federated_identity import federated_subject_reference


OIDC_COURT_CHECKS = (
    "signature",
    "issuer",
    "audience",
    "expiry",
    "nonce",
    "subject",
    "issued-time",
    "authentication-time",
    "assurance",
)


class OidcConfigurationError(ValueError):
    pass


def _numeric(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


class OidcAssertionCourtRunner:
    """Verify one configured OIDC issuer without trusting token-selected URLs."""

    def __init__(
        self,
        *,
        issuer: str,
        audience: str,
        public_key_set: object,
        assurance_by_acr: Mapping[str, str],
        allowed_algorithms: tuple[str, ...] = ("ES256", "PS256", "RS256", "EdDSA"),
        max_assertion_age_seconds: float = 300.0,
        future_skew_seconds: float = 5.0,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if not issuer.startswith("https://") or not audience:
            raise OidcConfigurationError(
                "OIDC issuer must be HTTPS and audience must be explicit"
            )
        if not assurance_by_acr:
            raise OidcConfigurationError("OIDC assurance mapping is required")
        if not allowed_algorithms or any(
            algorithm == "none" or algorithm.startswith("HS")
            for algorithm in allowed_algorithms
        ):
            raise OidcConfigurationError(
                "OIDC ID-token algorithms must be asymmetric"
            )
        if max_assertion_age_seconds <= 0 or future_skew_seconds < 0:
            raise OidcConfigurationError("OIDC time windows are invalid")
        self.issuer = issuer
        self.audience = audience
        self.public_key_set = public_key_set
        self.assurance_by_acr = MappingProxyType(dict(assurance_by_acr))
        self.allowed_algorithms = tuple(dict.fromkeys(allowed_algorithms))
        self.max_assertion_age_seconds = max_assertion_age_seconds
        self.future_skew_seconds = future_skew_seconds
        self.clock = clock

    def __call__(self, invocation: CourtInvocation) -> CourtResult:
        parameters = invocation.external_parameters
        configured = (
            parameters.get("expected_issuer") == self.issuer
            and parameters.get("expected_audience") == self.audience
            and bool(parameters.get("expected_nonce_sha256"))
        )
        claims: Mapping[str, object] = {}
        signature_ok = False
        if configured:
            try:
                from joserfc import jwt

                compact = invocation.subject_content.decode("ascii")
                token = jwt.decode(
                    compact,
                    self.public_key_set,
                    algorithms=self.allowed_algorithms,
                )
                header = token.header
                signature_ok = (
                    header.get("alg") in self.allowed_algorithms
                    and "jku" not in header
                    and "x5u" not in header
                    and "jwk" not in header
                )
                claims = token.claims
            except Exception:
                claims = {}
                signature_ok = False
        now = self.clock()
        issuer_ok = (
            signature_ok
            and isinstance(claims.get("iss"), str)
            and hmac.compare_digest(str(claims["iss"]), self.issuer)
        )
        raw_audience = claims.get("aud")
        audiences = (
            (raw_audience,)
            if isinstance(raw_audience, str)
            else tuple(raw_audience)
            if isinstance(raw_audience, list)
            and all(isinstance(value, str) for value in raw_audience)
            else ()
        )
        audience_ok = signature_ok and self.audience in audiences
        if len(audiences) > 1:
            audience_ok = audience_ok and claims.get("azp") == self.audience
        issued_at = _numeric(claims.get("iat"))
        expires_at = _numeric(claims.get("exp"))
        auth_time = _numeric(claims.get("auth_time"))
        issued_ok = (
            issued_at is not None
            and now - issued_at <= self.max_assertion_age_seconds
            and issued_at - now <= self.future_skew_seconds
        )
        expiry_ok = expires_at is not None and expires_at > now
        auth_time_ok = (
            auth_time is not None
            and auth_time - now <= self.future_skew_seconds
            and auth_time <= (issued_at or now) + self.future_skew_seconds
        )
        nonce = claims.get("nonce")
        nonce_ok = (
            isinstance(nonce, str)
            and hmac.compare_digest(
                hashlib.sha256(nonce.encode("utf-8")).hexdigest(),
                str(parameters.get("expected_nonce_sha256", "")),
            )
        )
        subject = claims.get("sub")
        subject_ok = (
            isinstance(subject, str)
            and 0 < len(subject) <= 255
            and subject.isascii()
        )
        acr = claims.get("acr")
        assurance = (
            self.assurance_by_acr.get(acr)
            if isinstance(acr, str) else None
        )
        assurance_ok = assurance is not None
        checks = {
            "signature": signature_ok,
            "issuer": issuer_ok,
            "audience": audience_ok,
            "expiry": expiry_ok,
            "nonce": nonce_ok,
            "subject": subject_ok,
            "issued-time": issued_ok,
            "authentication-time": auth_time_ok,
            "assurance": assurance_ok,
        }
        methods = claims.get("amr")
        authentication_method = (
            "+".join(value for value in methods if isinstance(value, str))
            if isinstance(methods, list) else "oidc"
        ) or "oidc"
        details = {
            "issuer": self.issuer if issuer_ok else "invalid",
            "subject_reference": (
                federated_subject_reference(self.issuer, subject)
                if issuer_ok and subject_ok else "invalid"
            ),
            "audience": self.audience if audience_ok else "invalid",
            "assurance": assurance or "invalid",
            "authentication_method": authentication_method,
            "issued_at": str(issued_at if issued_at is not None else "invalid"),
            "auth_time": str(auth_time if auth_time is not None else "invalid"),
            "expires_at": str(expires_at if expires_at is not None else "invalid"),
        }
        return CourtResult(all(checks.values()), checks, details)


__all__ = [
    "OIDC_COURT_CHECKS",
    "OidcConfigurationError",
    "OidcAssertionCourtRunner",
]
