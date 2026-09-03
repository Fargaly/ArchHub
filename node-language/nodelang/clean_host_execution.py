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

Whatever happens becomes a receipt. Success and failure both land as one
signed revision, so a run that broke is as readable afterwards as a run
that worked, and no effect is ever invisible.

Nothing here knows how to reach a host. The bridge is supplied by
whoever owns the runtime -- an entry point naming its adapter is a
declaration, the same decision buried in a library would be a trap -- so
this module cannot quietly acquire the ability to touch a machine.
"""
from __future__ import annotations

from typing import Callable, Mapping

from .clean_host_operations import read_host_operations
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
)
from .universal_cell import Cell, InvalidCell


HostInvoker = Callable[[str, Mapping[str, object]], Mapping[str, object]]


class HostOperationRefused(InvalidCell):
    """The operation was not run, and the graph says why."""


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
        return CommandResult(
            existing.result_root, existing.result_revision, True, 0, 0,
            existing.root_id,
        )
    try:
        outcome = invoker(op_id, checked)
        succeeded = True
    except Exception as exc:  # noqa: BLE001
        # A host that failed is a fact about this graph, not an exception
        # for the caller to lose. It is recorded and then re-raised.
        outcome = {"error": "%s: %s" % (type(exc).__name__, exc)}
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
        raise HostOperationRefused(
            "operation %s failed on %s: %s"
            % (op_id, operation["host"], record["outcome"].get("error"))
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
    "execute_host_operation",
]
