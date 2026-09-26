"""Physical hook observation adapter for the Cell runtime compliance court.

This module observes vendor client wiring only. The signed court attestation and
the compliance relation written into the Universal Cell graph remain the sole
authority for admitting write-capable Work.
"""
from __future__ import annotations

from .cell_attestations import CourtInvocation, CourtResult


RUNTIME_COMPLIANCE_CHECKS = (
    "runtime-detected",
    "required-hooks",
    "schema-valid",
    "brain-connected",
    "scope-gate",
    "workshop-authority",
)


def run_physical_runtime_compliance_court(
    invocation: CourtInvocation,
) -> CourtResult:
    """Observe vendor wiring; leave policy and evidence in the Cell court."""
    failed = {name: False for name in RUNTIME_COMPLIANCE_CHECKS}
    runtime = invocation.external_parameters.get("runtime", "")
    try:
        # The observer ships in this application package (nodelang). It reads
        # the client's own hook config: the landed governance gates, never the
        # retired Brain MCP or brainwrap. Any error fails closed below.
        from .runtime_hook_observer import observe_runtime_compliance

        observation = observe_runtime_compliance(runtime)
        checks = observation.get("checks")
        if (
            type(checks) is not dict
            or set(checks) != set(RUNTIME_COMPLIANCE_CHECKS)
            or any(type(value) is not bool for value in checks.values())
        ):
            raise RuntimeError(
                "runtime hook observer returned an invalid observation"
            )
        return CourtResult(
            passed=all(checks.values()),
            checks=checks,
            details={
                "adapter": "native-hook-observer-v1",
                "client": str(observation.get("client") or "unknown"),
                "status": str(observation.get("status") or "red"),
                "issueCount": str(observation.get("issue_count") or 0),
                **{"note:" + str(key): str(value)
                   for key, value in dict(observation.get("notes") or {}).items()},
            },
        )
    except Exception as exc:
        return CourtResult(
            passed=False,
            checks=failed,
            details={
                "adapter": "native-hook-observer-v1",
                "status": "red",
                "errorType": type(exc).__name__,
            },
        )


__all__ = [
    "RUNTIME_COMPLIANCE_CHECKS",
    "run_physical_runtime_compliance_court",
]
