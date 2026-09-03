"""Read-only evidence policy for a controlled Universal authority handoff.

This is a physical-runtime adapter, not a second authority.  It consumes only
transient descriptor, endpoint, and graph-activity observations and never opens
a CellStore, starts a listener, or writes a handoff decision.  A founder still
has to authorize any real owner transition through the released graph path.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AuthorityHandoffEvidence:
    """Bounded observations required before a handoff can be proposed."""

    graph_available: bool
    descriptor_verified: bool
    descriptor_active: bool | None
    descriptor_owner_alive: bool | None
    visible_endpoint_occupied: bool
    active_task_count: int | None
    active_host_count: int | None
    activity_revision: int | None
    durable_journal_revision: int | None = None


def _require_bool(value: object, label: str) -> bool:
    if type(value) is not bool:
        raise ValueError("authority handoff %s must be a boolean" % label)
    return value


def _require_count(value: object, label: str) -> int | None:
    if value is None:
        return None
    if type(value) is not int or value < 0:
        raise ValueError("authority handoff %s must be a non-negative integer" % label)
    return value


def _require_revision(value: object) -> int | None:
    if value is None:
        return None
    if type(value) is not int or value < 0:
        raise ValueError("authority handoff activity revision is invalid")
    return value


def evaluate_universal_authority_handoff(
    evidence: AuthorityHandoffEvidence,
) -> dict[str, object]:
    """Evaluate only whether a founder may review a graph-owner handoff.

    An unavailable graph cannot supply a fresh activity revision.  Advisory
    local process scans may therefore add blockers, but may never prove that
    the canonical graph has no live Work or Agent Sessions.
    """
    graph_available = _require_bool(evidence.graph_available, "graph availability")
    descriptor_verified = _require_bool(
        evidence.descriptor_verified, "descriptor verification"
    )
    endpoint_occupied = _require_bool(
        evidence.visible_endpoint_occupied, "endpoint occupancy"
    )
    tasks = _require_count(evidence.active_task_count, "active task count")
    hosts = _require_count(evidence.active_host_count, "active host count")
    activity_revision = _require_revision(evidence.activity_revision)
    durable_journal_revision = _require_revision(
        evidence.durable_journal_revision
    )

    if descriptor_verified:
        descriptor_active = _require_bool(
            evidence.descriptor_active, "descriptor activity"
        )
        owner_alive = _require_bool(
            evidence.descriptor_owner_alive, "descriptor owner liveness"
        )
    elif (
        evidence.descriptor_active is not None
        or evidence.descriptor_owner_alive is not None
    ):
        raise ValueError("unverified authority descriptor cannot expose owner state")
    else:
        descriptor_active = None
        owner_alive = None

    handoff_required = not graph_available and descriptor_verified
    blockers: list[str] = []
    if graph_available:
        blockers.append("the canonical Universal graph is already available")
    elif not descriptor_verified:
        blockers.append("the signed Universal runtime descriptor is unavailable or invalid")
    elif descriptor_active and owner_alive:
        blockers.append("the signed Universal owner is still alive")
    if endpoint_occupied:
        blockers.append("the visible ArchHub endpoint is occupied")
    if tasks:
        blockers.append(
            "%s %s Work item(s)" % (
                tasks,
                "active governed" if activity_revision is not None else "observed active",
            )
        )
    if hosts:
        blockers.append(
            "%s %s host session(s)" % (
                hosts,
                "live graph" if activity_revision is not None else "observed live",
            )
        )
    if activity_revision is None:
        blockers.append(
            "canonical graph activity proof is unavailable; automatic handoff is forbidden"
        )
    elif tasks is None or hosts is None:
        blockers.append("canonical activity proof is incomplete")

    if graph_available:
        owner_state = "live-canonical-runtime"
    elif not descriptor_verified:
        owner_state = "descriptor-unverified"
    elif descriptor_active and owner_alive:
        owner_state = "active-owner-unreachable"
    elif descriptor_active:
        owner_state = "stale-active-descriptor"
    else:
        owner_state = "stopped-owner"

    return {
        "action": "read-only-universal-authority-handoff-preflight",
        "execution_performed": False,
        "founder_approval_required": True,
        "handoff_required": handoff_required,
        "eligible_for_founder_approval": handoff_required and not blockers,
        "blockers": blockers,
        "visible_endpoint_occupied": endpoint_occupied,
        "owner": {
            "descriptor_verified": descriptor_verified,
            "active": descriptor_active,
            "owner_alive": owner_alive,
            "state": owner_state,
        },
        "activity": {
            "revision": activity_revision,
            "proven": activity_revision is not None,
            "active_tasks": tasks,
            "active_hosts": hosts,
        },
        "durable_journal": {
            "available": durable_journal_revision is not None,
            "revision": durable_journal_revision,
            "authorizes_handoff": False,
        },
    }


__all__ = [
    "AuthorityHandoffEvidence",
    "evaluate_universal_authority_handoff",
]
