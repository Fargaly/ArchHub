"""A submitted Work's step for its submitter, read through the court's own admission (live 717 and Ping, 2026-09-30).

A Work in review has no accepted verdict until its submitter requests the court
(native.work_request_court). The court runs synchronously: it moves the Work, or
it refuses and commits nothing. So every submitted Work holds its submitter's
turn. This module only names the step, and it reads it through the court's own
admission (_governed_work_court_admission, with the court's artifact review
verifier), never through a weaker copy:

- "court": the court admits this submission; request it.
- "reconcile": the court refuses this submission as it stands; the reason is
  the court's own.
- "unknown": the admission could not be read here; the court's answer decides.

Nothing submitted waits on someone else. The court verifies the approved
independent review that the submission names, and the reviewer mints that
review's identity when it reviews, so the review comes before the submission
(the reviewer's step falls while the Work is still claimed). A founder's
disposition is the Work's cancel transition, which takes it out of review.
"""
from .cell_authorization import AuthorizationDenied
from .universal_cell import InvalidCell

WAITS = ("court", "reconcile", "unknown")
REASON_CHARS = 300


def review_wait(server, work_root, claimant, *, context):
    """{"wait", "reason"} for one submitted Work; it never attests or commits."""
    from .cell_state_machine import read_instance_state_machine
    from .universal_application import _governed_work_court_admission, _governed_work_interface_target

    snapshot, registry = server.universal_store.snapshot(), server.universal_registry
    try:
        machine = read_instance_state_machine(snapshot, registry.assembly_protocol,
                                              registry.standard_library.state_machine_protocol, work_root)
        targets = {name: _governed_work_interface_target(snapshot, registry, work_root, name)
                   for name in ("requirements", "cde-container")}
        _governed_work_court_admission(snapshot, registry, work_root, machine, claimant, targets,
                                       context=context,
                                       artifact_review_verifier=server._verify_work_artifact_review)
    except (InvalidCell, AuthorizationDenied) as exc:
        return {"wait": "reconcile", "reason": str(exc)[:REASON_CHARS]}
    except Exception as exc:        # a verifier or storage failure is not an admission
        return {"wait": "unknown", "reason": type(exc).__name__[:REASON_CHARS]}
    return {"wait": "court", "reason": ""}


def review_waits(server, *, agent_session_root, items, context):
    """{root: wait} for every Work in review that agent_session_root submitted."""
    return {item["root"]: review_wait(server, item["root"], agent_session_root, context=context)
            for item in items
            if item.get("claimant_session") == agent_session_root
            and str(item["operational"]["current_state_label"]).casefold() == "review"}
