"""Run one graph-declared host operation and record what happened.

The canvas could name nineteen hosts and a hundred and fifty five things
it could ask them for, and had no way to ask. Every gesture ended inside
the graph; nothing ever left it. This is the path out, and the path back.

Three rules hold it together:

The operation must be one the graph declares. An operation named only by
the caller is not an ArchHub operation, and running it would make the
catalogue a suggestion rather than the authority.

The arguments must satisfy what that operation declares it needs. A
missing required input is refused here rather than discovered by the host
halfway through changing a model.

An attempt is reserved in a signed receipt before reaching the host. Its
outcome is settled in a later signed receipt. An interruption can leave only
the reservation: that means outcome unknown and requires reconciliation,
not an automatic second invocation.

Nothing here knows how to reach a host. The bridge is supplied by
whoever owns the runtime -- an entry point naming its adapter is a
declaration, the same decision buried in a library would be a trap -- so
this module cannot quietly acquire the ability to touch a machine.
"""
from __future__ import annotations

from typing import Callable, Mapping
import uuid
import re

from .clean_host_operations import read_host_operations
from .cell_protocols import read_relation
from .unified_authority import (
    COMMAND_BUDGET,
    CallerCommandCapability,
    CommandResult,
    UnifiedAuthority,
    build_contract,
    commit_with_receipt,
    digest,
    find_receipt,
    new_id,
    typed_relation_cells,
    validate_command_participants,
    composition_root,
    validate_composition,
    _property_values,
    read_instance,
)
from .universal_cell import Cell, InvalidCell


HostInvoker = Callable[[str, Mapping[str, object]], Mapping[str, object]]


class HostOperationRefused(InvalidCell):
    """Execution was refused or failed; uncertainty has a distinct subtype."""


class HostOperationUncertain(HostOperationRefused):
    """An attempt was reserved; reconcile it instead of invoking it again."""


class HostOperationFailed(HostOperationRefused):
    """A committed failed outcome, including on replay."""
    def __init__(self, message, *, receipt_root, result_root, revision, replayed):
        super().__init__(message)
        self.receipt_root = receipt_root
        self.result_root = result_root
        self.revision = revision
        self.replayed = replayed


class HostInvocationFailure(InvalidCell):
    """A failed physical call with bounded, non-content response evidence."""
    def __init__(self, error_code: str, output_digest: str, output_bytes: int):
        if (type(error_code) is not str or len(error_code) > 160 or
                re.fullmatch(r"[a-z0-9]+(?:[._-][a-z0-9]+)*", error_code) is None or
                type(output_digest) is not str or
                re.fullmatch(r"[0-9a-f]{64}", output_digest) is None or
                type(output_bytes) is not int or not 0 <= output_bytes <= 16 * 1024 * 1024):
            raise InvalidCell("host failure evidence is invalid")
        super().__init__(error_code)
        self.output_digest = output_digest
        self.output_bytes = output_bytes
        self.error_code = error_code


def _attempt_command(command_id: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL,
        "archhub:execute-host-operation:attempt:v1:" + command_id))


def _declared_operation(
    authority: UnifiedAuthority,
    caller: CallerCommandCapability,
    op_id: str,
) -> Mapping[str, object]:
    catalogue = read_host_operations(authority, caller=caller)
    if catalogue is None:
        raise HostOperationRefused(
            "the graph declares no host operations to run"
        )
    for entry in catalogue["operations"]:
        if entry["op_id"] == op_id:
            return entry
    raise HostOperationRefused(
        "the graph declares no operation named %r" % op_id
    )


def _checked_arguments(
    operation: Mapping[str, object],
    arguments: Mapping[str, object],
) -> dict[str, object]:
    """The arguments this operation declared, and nothing else.

    An undeclared argument is refused rather than passed along: the host
    would either ignore it, which makes the request a lie, or act on it,
    which makes the catalogue incomplete.
    """
    declared = {str(field["id"]): field for field in operation["inputs"]}
    unknown = sorted(set(arguments) - set(declared))
    if unknown:
        raise HostOperationRefused(
            "operation %s does not declare %s"
            % (operation["op_id"], ", ".join(unknown))
        )
    checked: dict[str, object] = {}
    for name, field in declared.items():
        if name in arguments:
            checked[name] = arguments[name]
            continue
        if field.get("required"):
            raise HostOperationRefused(
                "operation %s requires %s" % (operation["op_id"], name)
            )
        default = field.get("default")
        if default not in (None, ""):
            checked[name] = default
    return checked


# What one run may persist. A row costs about fifty cells, so this is
# roughly fifty thousand cells for a single press -- already heavy, and
# far more rows than anyone reads in a panel. A host that answers with
# more is not refused: the answer is capped and the cap is recorded.
PERSISTED_ROW_LIMIT = 1000


def _recorded_host_outcome(authority, receipt):
    """Read the effect at its receipted revision, not mutable current state."""
    snapshot = authority.store.at(receipt.result_revision)
    effect = validate_composition(authority, snapshot, receipt.result_root)
    if effect.protocol_root != authority.shape("relation"):
        raise InvalidCell("host receipt result has the wrong structural protocol")
    presentations = [member.participant_id for member in
        read_relation(snapshot, receipt.result_root, budget=10_000)
        if member.role_id == authority.role("presentation")]
    if len(presentations) != 1:
        raise InvalidCell("host receipt result requires one presentation")
    contract = validate_composition(authority, snapshot, presentations[0])
    if contract.protocol_root != authority.shape("contract"):
        raise InvalidCell("host receipt presentation has the wrong structural protocol")
    return _property_values(authority, snapshot, presentations[0])


def node_host_arguments(authority, op_id, node_root, *, scope_root, caller):
    """Select only declared operation inputs from the saved node values."""
    revision = authority.store.revision
    operation = _declared_operation(authority, caller, op_id)
    instance = read_instance(authority, node_root, scope_root=scope_root, caller=caller)
    values = instance.get("values")
    if not isinstance(values, Mapping):
        raise InvalidCell("host node values are invalid")
    declared = {field["id"] for field in operation["inputs"]}
    arguments = _checked_arguments(operation, {key: value for key, value in values.items()
        if key in declared})
    if authority.store.revision != revision:
        raise InvalidCell("host node changed while reading its arguments")
    return arguments, revision


def execute_host_operation(
    authority: UnifiedAuthority,
    op_id: str,
    arguments: Mapping[str, object],
    *,
    caller: CallerCommandCapability,
    command_id: str,
    invoker: HostInvoker | None,
    allow_destructive: bool = False,
    subject_root: str | None = None,
    expected_revision: int | None = None,
) -> CommandResult:
    """Run a declared operation and commit the receipt for it.

    A run started from the canvas is a run of one node, and the effect
    says so. Without that the graph holds the answer and no record of
    what asked the question, so nothing can show a node what it last
    returned -- the result exists and is unreachable.
    """
    operation = _declared_operation(authority, caller, op_id)
    checked = _checked_arguments(operation, arguments)
    if operation.get("destructive") and not allow_destructive:
        raise HostOperationRefused(
            "operation %s destroys work and was not explicitly allowed"
            % op_id
        )
    if invoker is None:
        raise HostOperationRefused(
            "this runtime was given no adapter, so it can reach no host"
        )
    if subject_root is not None and (
        type(subject_root) is not str or not subject_root.strip()
    ):
        raise InvalidCell("execute subject is invalid")
    # The subject belongs in the digest: the same operation run for two
    # different nodes is two different requests, and replaying one must
    # not answer for the other.
    request_digest = digest({
        "intent": "execute-host-operation",
        "operation": op_id,
        "arguments": dict(sorted(checked.items())),
        "subject": subject_root or "",
    })
    snapshot = authority.store.snapshot()
    if expected_revision is not None and (
            type(expected_revision) is not int or expected_revision != snapshot.revision):
        raise InvalidCell("host execution base revision changed")
    interface_root = composition_root(authority, "Interface", caller=caller)
    authenticated, policy_proof = validate_command_participants(
        authority,
        snapshot,
        caller,
        command_id,
        intent="execute-host-operation",
        request_digest=request_digest,
        object_root=interface_root,
        scope_root=interface_root,
        budget=COMMAND_BUDGET,
    )
    existing = find_receipt(
        authority,
        snapshot,
        authenticated.actor_root,
        authenticated.session_root,
        command_id,
    )
    if existing is not None:
        # An effect replayed is an effect performed twice. The receipt
        # that already exists is the answer, and the host is not asked
        # again.
        if existing.request_digest != request_digest:
            raise InvalidCell("idempotency key was reused with another request")
        record = _recorded_host_outcome(authority, existing)
        if (digest({"intent":"execute-host-operation",
                "operation":record.get("operation"), "arguments":record.get("arguments"),
                "subject":record.get("subject")}) != request_digest or
                type(record.get("succeeded")) is not bool):
            raise InvalidCell("host receipt outcome does not match the request")
        if not record["succeeded"]:
            raise HostOperationFailed(
                "recorded host operation failed; receipt %s; no new invocation"
                % existing.root_id, receipt_root=existing.root_id,
                result_root=existing.result_root, revision=existing.result_revision,
                replayed=True)
        return CommandResult(
            existing.result_root, existing.result_revision, True, 0, 0,
            existing.root_id,
        )
    # A final receipt alone cannot prevent duplicate effects after a crash
    # between invocation and persistence. Reserve one attempt first, through
    # the same signed execution permission and optimistic commit boundary.
    attempt_id = _attempt_command(command_id)
    attempt_digest = digest({
        "phase": "host-attempt-reserved-v1", "command": command_id,
        "request_digest": request_digest, "actor": authenticated.actor_root,
        "session": authenticated.session_root, "subject": subject_root or "",
    })
    attempt = find_receipt(authority, snapshot, authenticated.actor_root,
        authenticated.session_root, attempt_id)
    if attempt is not None:
        if attempt.request_digest != attempt_digest:
            raise InvalidCell("host attempt identity was reused with another request")
        raise HostOperationUncertain(
            "host attempt already reserved; outcome unknown, reconciliation required"
        )
    attempt_auth, attempt_proof = validate_command_participants(authority, snapshot,
        caller, attempt_id, intent="execute-host-operation", request_digest=attempt_digest,
        object_root=interface_root, scope_root=interface_root, budget=COMMAND_BUDGET)
    attempt_root, attempt_cells = build_contract(authority, {
        "phase": "reserved", "command": command_id, "request_digest": request_digest,
        "operation": op_id, "subject": subject_root or "",
    })
    # The reservation is a contract, not a completed host-effect presentation.
    # Existing result lenses therefore cannot mistake it for a successful run.
    commit_with_receipt(authority, snapshot, resource_create=tuple(attempt_cells),
        resource_replace=(), authenticated=attempt_auth, result_root=attempt_root,
        policy_proof=attempt_proof)
    # Refresh authority after reserving, before allowing the external attempt.
    validate_command_participants(authority, authority.store.snapshot(), caller,
        command_id, intent="execute-host-operation", request_digest=request_digest,
        object_root=interface_root, scope_root=interface_root, budget=COMMAND_BUDGET)
    try:
        outcome = invoker(op_id, checked)
        succeeded = True
    except Exception as exc:  # noqa: BLE001
        # A host that failed is a fact about this graph, not an exception
        # for the caller to lose. It is recorded and then re-raised.
        outcome = {"error": "%s: %s" % (type(exc).__name__, exc)}
        if isinstance(exc, HostInvocationFailure):
            outcome.update(output_digest=exc.output_digest, output_bytes=exc.output_bytes,
                           error_code=exc.error_code)
        succeeded = False
    held = dict(outcome) if isinstance(outcome, Mapping) else {"value": outcome}
    returned = held.get("result")
    recorded = len(returned) if isinstance(returned, list) else 0
    if isinstance(returned, list) and len(returned) > PERSISTED_ROW_LIMIT:
        # Persisting a row costs about fifty cells, so a read that finds
        # eight thousand of something adds four hundred thousand cells to
        # the graph on one press -- which is how a card in the library
        # took the runtime down mid-audit. The rows are capped, and the
        # cap is RECORDED: a graph that quietly held part of an answer
        # while reading like the whole of it would be worse than one that
        # fell over, because nobody would know to doubt it.
        held["result"] = returned[:PERSISTED_ROW_LIMIT]
        recorded = PERSISTED_ROW_LIMIT
    record = {
        "attempt_root": attempt_root,
        "operation": op_id,
        "host": operation["host"],
        "kind": operation["kind"],
        "arguments": dict(sorted(checked.items())),
        "subject": subject_root or "",
        "succeeded": succeeded,
        "rows_returned": len(returned) if isinstance(returned, list) else 0,
        "rows_recorded": recorded,
        "outcome": held,
    }
    outcome_root, outcome_cells = build_contract(authority, record)
    effect_root = new_id()
    create: list[Cell] = list(outcome_cells)
    create.extend(typed_relation_cells(
        effect_root,
        authority.role("conforms-to"),
        authority.shape("relation"),
        ((authority.role("presentation"), outcome_root),),
    ))
    # The graph may have advanced during the host call. Sign settlement against
    # its current head; any refusal leaves the reservation for reconciliation.
    # Never retry the external invocation to repair a persistence failure.
    snapshot = authority.store.snapshot()
    authenticated, policy_proof = validate_command_participants(authority, snapshot,
        caller, command_id, intent="execute-host-operation", request_digest=request_digest,
        object_root=interface_root, scope_root=interface_root, budget=COMMAND_BUDGET)
    result = commit_with_receipt(
        authority,
        snapshot,
        resource_create=tuple(create),
        resource_replace=(),
        authenticated=authenticated,
        result_root=effect_root,
        policy_proof=policy_proof,
    )
    if not succeeded:
        raise HostOperationFailed(
            "operation %s failed on %s: %s"
            % (op_id, operation["host"], record["outcome"].get("error")),
            receipt_root=result.receipt_root, result_root=effect_root,
            revision=result.revision, replayed=False,
        )
    # The revision and the receipt both come from the commit itself. Reading
    # the store again would answer with whatever a later writer had done, and
    # result.root_id is the effect, not the receipt for it.
    return CommandResult(
        effect_root, result.revision, False, len(create),
        result.receipt_cell_count, result.receipt_root,
    )


__all__ = [
    "HostInvoker",
    "HostOperationRefused",
    "HostOperationUncertain",
    "HostOperationFailed",
    "HostInvocationFailure",
    "execute_host_operation",
]
