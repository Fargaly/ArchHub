"""Graph admission for social Work: exact preparation and cross-Work attempt reservation.

Nothing here resolves a credential or opens a connection; the injected host
does both, and execute_social_work records its outcome. Preparation rebuilds the exact request from the claimed Work's
graph-held inputs and requests the existing connector delegation. Issuing a
grant for a social write also reserves its attempt key inside the grant's own
commit (cell_connector_execution.create_connector_execution_grant reserve), so
identical effects on one account cannot hold grants from different Works,
delegations or restarts while an earlier attempt is granted, unresolved or
known to have succeeded.

Three separate facts: the connector grant reservation allows one grant per
delegation; the attempt reservation here spans delegations for one attempt
key; neither knows what a provider did. An uncertain attempt stays locked and
this runtime admits no resolution record yet.

Relied-on invariant: every supported social host path commits the cells of
prepare_social_dispatch_marker from its before_dispatch callback, after
revalidating admission and grant expiry and before any connection opens. Only
under that invariant does an expired grant without a dispatch marker prove
that nothing was sent.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import time
from contextlib import contextmanager
from dataclasses import dataclass
from types import MappingProxyType
from urllib.parse import parse_qsl

from .cell_authorization import AuthorizationDenied
from .cell_connector_execution import (
    read_connector_delegation,
    read_connector_execution_grant,
    read_connector_execution_receipt,
)
from .cell_protocols import compose_relation_cells, read_relation
from .cell_value_graph import read_value_graph
from .social_connectors import OPERATIONS, WORK_OPERATIONS, Refusal, social_material_from_values
from .universal_cell import NULL_CELL_ID, Cell, InvalidCell

PREFIX = "app:social-attempt:v1"
VOCABULARY_ROOT = PREFIX + ":root"
ROLE_NAMES = (
    "vocabulary-member", "head-key", "head-current",
    "attempt-key", "attempt-provider", "attempt-account", "attempt-operation",
    "attempt-request-digest", "attempt-work", "attempt-session", "attempt-delegation",
    "attempt-grant", "attempt-predecessor", "dispatch-grant", "dispatch-attempt",
)
ROLES = MappingProxyType({name: PREFIX + ":role:" + name for name in ROLE_NAMES})
_ATTEMPT_ROLES = frozenset(ROLES[name] for name in ROLE_NAMES if name.startswith("attempt-"))
_REVIEW_LIMIT = 16000
_NOTE_LIMIT = 2000


@dataclass(frozen=True, slots=True)
class SocialAttemptProjection:
    root_id: str
    key_root: str
    provider_root: str
    account_id: str
    operation: str
    request_digest: str
    work_root: str
    session_root: str
    delegation_root: str
    grant_root: str
    predecessor_root: str


def _terminal(root_id: str, value: str) -> Cell:
    return Cell(root_id, NULL_CELL_ID, NULL_CELL_ID, value.encode("utf-8"))


def _text(snapshot, root_id: str, label: str) -> str:
    try:
        cell = snapshot.cells[root_id]
    except KeyError:
        raise InvalidCell("%s Cell is missing" % label) from None
    if cell.link0 != NULL_CELL_ID or cell.link1 != NULL_CELL_ID:
        raise InvalidCell("%s must be terminal" % label)
    try:
        return cell.atom.decode("utf-8")
    except UnicodeDecodeError:
        raise InvalidCell("%s must be UTF-8" % label) from None


def social_provider_name(operation: str) -> str:
    return "social-" + operation.replace(".", "-").replace("_", "-")


def social_provider_operation(registry, provider) -> str | None:
    """The admitted Work operation of a released social provider, else None."""
    operation = provider.operation
    if (operation not in WORK_OPERATIONS
            or registry.baboom_connector_provider_roots.get(social_provider_name(operation)) != provider.root_id):
        return None
    return operation


def social_reservation_required(registry, provider) -> bool:
    operation = social_provider_operation(registry, provider)
    return operation is not None and OPERATIONS[operation][1] == "write"


def attempt_root_for(grant_root: str) -> str:
    return grant_root + ":social-attempt"


def dispatch_root_for(grant_root: str) -> str:
    return grant_root + ":social-dispatch"


def receipt_root_for(grant_root: str) -> str:
    return grant_root + ":social-receipt"


def resolution_root_for(grant_root: str) -> str:
    return grant_root + ":social-resolution"


def _key_root(key: str) -> str:
    return PREFIX + ":key:" + key


def _head_root(key: str) -> str:
    return PREFIX + ":head:" + key


def _key_material(provider_root: str, account_id: str, operation: str, request_digest: str) -> str:
    return json.dumps([provider_root, account_id, operation, request_digest],
                      separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def social_attempt_key(provider_root: str, prepared) -> tuple[str, str]:
    """Key over provider, account, operation and request commitment; never vault entry, note or Work."""
    material = _key_material(provider_root, prepared.account_id, prepared.operation, prepared.input_digest)
    return hashlib.sha256(material.encode("utf-8")).hexdigest(), material


def social_material_at(snapshot, registry, work_root: str):
    """Rebuild one Work's exact request from the given snapshot."""
    from . import universal_application as app

    inputs = read_value_graph(snapshot, registry.value_graph_protocol,
                              app._governed_work_interface_target(snapshot, registry, work_root, "inputs"))
    try:
        return social_material_from_values(inputs)
    except Refusal as refusal:
        raise InvalidCell("social Work input refused: %s: %s" % (refusal.state, refusal.reason)) from None


def _review_text(prepared, note: str) -> str:
    content = dict(prepared.headers).get("Content-Type", "")
    body = prepared.body.decode("utf-8")
    if content == "application/x-www-form-urlencoded":
        shown = "\n".join("%s: %s" % pair for pair in parse_qsl(body, keep_blank_values=True))
    elif content == "application/json":
        shown = json.dumps(json.loads(body), indent=2, sort_keys=True, ensure_ascii=False)
    else:
        shown = body
    lines = ["Operation: %s (%s)" % (prepared.operation, prepared.effect),
             "Account: " + prepared.account_id, "Request: %s %s" % (prepared.method, prepared.url)]
    if shown:
        lines += ["", shown]
    if note:
        lines += ["", "Unverified note, not part of the approved request: " + note]
    text = "\n".join(lines)
    if len(text) > _REVIEW_LIMIT:
        raise InvalidCell("social request review exceeds its display bound")
    return text


def prepare_social_work(server, *, work_root: str, session_root: str, context, note: str) -> dict:
    """Prepare the exact graph-held social request; no provider or credential access."""
    from . import universal_application as app

    if type(note) is not str or len(note) > _NOTE_LIMIT:
        raise InvalidCell("social preparation note must be text of at most 2000 characters")
    store, registry = server.universal_store, server.universal_registry
    app._baboom_execution_work_context(store, registry, agent_session_root=session_root, work_root=work_root,
                                       authentication_context=context, purpose="Workshop social preparation")
    snapshot = store.snapshot()
    prepared, raw = social_material_at(snapshot, registry, work_root)
    if store.revision != snapshot.revision:
        raise InvalidCell("social Work changed while its request was prepared")
    review_text = _review_text(prepared, note)
    delegation, operation, _, revision = app.request_universal_baboom_connector_execution(
        store, registry, agent_session_root=session_root, work_root=work_root,
        provider=social_provider_name(prepared.operation), input_digest=hashlib.sha256(raw).hexdigest(),
        input_bytes=len(raw), data_class=prepared.data_class, lifetime_seconds=300.0,
        authentication_context=context, content_service=server.conversation_content)
    if operation != prepared.operation:
        raise InvalidCell("social provider operation changed")
    return {"work": work_root, "worker": session_root, "delegation": delegation.root_id,
            "operation": operation, "input_digest": delegation.input_digest, "review_text": review_text,
            "expires_at": delegation.expires_at, "revision": revision}


def _vocabulary_cells(snapshot) -> tuple[Cell, ...]:
    """Cells creating the social attempt vocabulary, or () once it is verified."""
    if VOCABULARY_ROOT not in snapshot.cells:
        if any(root in snapshot.cells for root in ROLES.values()):
            raise InvalidCell("social attempt vocabulary is partially present")
        relation = compose_relation_cells(
            tuple((ROLES["vocabulary-member"], root) for root in ROLES.values()), relation_id=VOCABULARY_ROOT)
        return (*(_terminal(root, name) for name, root in ROLES.items()), *relation.cells)
    members = read_relation(snapshot, VOCABULARY_ROOT, budget=64)
    if (len(members) != len(ROLES)
            or any(member.role_id != ROLES["vocabulary-member"] for member in members)
            or {member.participant_id for member in members} != set(ROLES.values())
            or any(_text(snapshot, root, "social attempt role") != name for name, root in ROLES.items())):
        raise InvalidCell("social attempt vocabulary drifted")
    return ()


def read_social_attempt(snapshot, attempt_root: str) -> SocialAttemptProjection:
    members = read_relation(snapshot, attempt_root, budget=32)
    if any(member.role_id not in _ATTEMPT_ROLES for member in members):
        raise InvalidCell("social attempt has an undeclared role")

    def one(name: str, optional: bool = False) -> str:
        found = [member.participant_id for member in members if member.role_id == ROLES[name]]
        if optional and not found:
            return ""
        if len(found) != 1:
            raise InvalidCell("social attempt requires exactly one %s" % name)
        return found[0]

    attempt = SocialAttemptProjection(
        attempt_root, one("attempt-key"), one("attempt-provider"),
        _text(snapshot, one("attempt-account"), "social attempt account"),
        _text(snapshot, one("attempt-operation"), "social attempt operation"),
        _text(snapshot, one("attempt-request-digest"), "social attempt request digest"),
        one("attempt-work"), one("attempt-session"), one("attempt-delegation"), one("attempt-grant"),
        one("attempt-predecessor", optional=True))
    material = _key_material(attempt.provider_root, attempt.account_id, attempt.operation, attempt.request_digest)
    if (attempt_root != attempt_root_for(attempt.grant_root)
            or attempt.key_root != _key_root(hashlib.sha256(material.encode("utf-8")).hexdigest())
            or _text(snapshot, attempt.key_root, "social attempt key") != material):
        raise InvalidCell("social attempt identity drifted")
    return attempt


def prepare_social_dispatch_marker(snapshot, grant_root: str) -> tuple[Cell, ...]:
    """Cells a social host path commits from before_dispatch, before any connection opens."""
    attempt = read_social_attempt(snapshot, attempt_root_for(grant_root))
    root = dispatch_root_for(grant_root)
    if root in snapshot.cells:
        raise InvalidCell("social attempt is already marked dispatched")
    return compose_relation_cells(((ROLES["dispatch-grant"], grant_root),
                                   (ROLES["dispatch-attempt"], attempt.root_id)), relation_id=root).cells


def _require_dispatch_marker(snapshot, grant_root: str, attempt_root: str) -> None:
    members = read_relation(snapshot, dispatch_root_for(grant_root), budget=8)
    if (tuple((member.role_id, member.participant_id) for member in members)
            != ((ROLES["dispatch-grant"], grant_root), (ROLES["dispatch-attempt"], attempt_root))):
        raise InvalidCell("social dispatch marker binding drifted")


def _read_head(snapshot, head_root: str, key_root: str) -> str:
    members = read_relation(snapshot, head_root, budget=8)
    if (len(members) != 2 or members[0].role_id != ROLES["head-key"] or members[0].participant_id != key_root
            or members[1].role_id != ROLES["head-current"]
            or members[1].incidence_id != head_root + ":incidence:1"):
        raise InvalidCell("social attempt head drifted")
    return members[1].participant_id


def _prior_attempt_state(snapshot, registry, attempt_root: str, key_root: str) -> str:
    """published, unresolved, granted or released; contradictions refuse."""
    protocol, adapters = registry.baboom_connector_execution_protocol, registry.adapter_protocol
    attempt = read_social_attempt(snapshot, attempt_root)
    if attempt.key_root != key_root:
        raise InvalidCell("social attempt head points at another key")
    grant = read_connector_execution_grant(snapshot, protocol, adapters, attempt.grant_root)
    delegation = read_connector_delegation(snapshot, protocol, adapters, attempt.delegation_root)
    if (grant.delegation_root != delegation.root_id or grant.session_root != attempt.session_root
            or delegation.session_root != attempt.session_root or delegation.work_root != attempt.work_root
            or delegation.provider_root != attempt.provider_root):
        raise InvalidCell("social attempt lineage drifted")
    if resolution_root_for(grant.root_id) in snapshot.cells:
        raise AuthorizationDenied("social attempt resolution is not admitted by this runtime yet")
    dispatched = dispatch_root_for(grant.root_id) in snapshot.cells
    if dispatched:
        _require_dispatch_marker(snapshot, grant.root_id, attempt.root_id)
    receipt_root = receipt_root_for(grant.root_id)
    if receipt_root in snapshot.cells:
        receipt = read_connector_execution_receipt(snapshot, protocol, adapters, receipt_root)
        if (receipt.grant_root != grant.root_id or receipt.delegation_root != delegation.root_id
                or receipt.provider_root != delegation.provider_root
                or receipt.input_digest != delegation.input_digest):
            raise InvalidCell("social attempt receipt lineage drifted")
        if receipt.outcome == "succeeded":
            if not dispatched:
                raise InvalidCell("social success receipt has no dispatch marker")
            return "published"
        return "released"
    if dispatched:
        return "unresolved"
    return "released" if time.time() >= grant.expires_at else "granted"


def social_attempt_reservation(snapshot, registry, *, delegation, provider, grant_id: str):
    """(create, replace, authority roots) reserving one social write attempt with its grant.

    Point reads only: vocabulary, key, head, the current attempt and its exact
    grant, delegation, dispatch marker and receipt. History is predecessor-linked
    and never rewritten; only the head's current incidence is replaced.
    """
    prepared, raw = social_material_at(snapshot, registry, delegation.work_root)
    if hashlib.sha256(raw).hexdigest() != delegation.input_digest or len(raw) != delegation.input_bytes:
        raise AuthorizationDenied("social Work inputs changed after approval")
    if prepared.operation != provider.operation or delegation.provider_root != provider.root_id:
        raise AuthorizationDenied("social provider operation drifted")
    key, material = social_attempt_key(provider.root_id, prepared)
    key_root, head_root, attempt_root = _key_root(key), _head_root(key), attempt_root_for(grant_id)
    if attempt_root in snapshot.cells:
        raise InvalidCell("social attempt already exists for this grant")
    vocabulary = _vocabulary_cells(snapshot)
    create = list(vocabulary)
    replace = []
    roots = [VOCABULARY_ROOT] if vocabulary else []
    predecessor = ""
    if head_root in snapshot.cells:
        if vocabulary or _text(snapshot, key_root, "social attempt key") != material:
            raise InvalidCell("social attempt key record drifted")
        current = _read_head(snapshot, head_root, key_root)
        state = _prior_attempt_state(snapshot, registry, current, key_root)
        if state != "released":
            raise AuthorizationDenied("social attempt already reserved: %s" % state)
        predecessor = current
        replace.append(Cell(head_root + ":incidence:1", ROLES["head-current"], attempt_root, b""))
    else:
        if key_root in snapshot.cells:
            raise InvalidCell("social attempt key exists without its head")
        create.append(_terminal(key_root, material))
        create.extend(compose_relation_cells(((ROLES["head-key"], key_root), (ROLES["head-current"], attempt_root)),
                                             relation_id=head_root).cells)
        roots.extend((key_root, head_root))
    values = {name: attempt_root + ":" + name for name in ("account", "operation", "request-digest")}
    members = [
        (ROLES["attempt-key"], key_root), (ROLES["attempt-provider"], provider.root_id),
        (ROLES["attempt-account"], values["account"]), (ROLES["attempt-operation"], values["operation"]),
        (ROLES["attempt-request-digest"], values["request-digest"]), (ROLES["attempt-work"], delegation.work_root),
        (ROLES["attempt-session"], delegation.session_root), (ROLES["attempt-delegation"], delegation.root_id),
        (ROLES["attempt-grant"], grant_id),
    ]
    if predecessor:
        members.append((ROLES["attempt-predecessor"], predecessor))
    create.extend((_terminal(values["account"], prepared.account_id),
                   _terminal(values["operation"], prepared.operation),
                   _terminal(values["request-digest"], prepared.input_digest)))
    create.extend(compose_relation_cells(members, relation_id=attempt_root).cells)
    roots.append(attempt_root)
    return tuple(create), tuple(replace), tuple(roots)


# ------------------------------------------------------------------ execution --

SOCIAL_EXECUTE_ROUTE = "/api/universal/social-work-execute"
_RESULT_BYTES = 65536
_OUTCOMES = frozenset({"succeeded", "failed", "uncertain"})
_ERROR_CODE = re.compile(r"[a-z0-9]+(?:[._-][a-z0-9]+)*")


def social_result_root_for(grant_root: str) -> str:
    return grant_root + ":social-result"


@contextmanager
def _stable_admission(server, context):
    registry, store = server.universal_registry, server.universal_store
    with server.mutation_lock:
        with registry.authorization.broker.live_context(context):
            with store.stable_snapshot():
                yield


def _pending(server) -> dict:
    # {"state": "in_flight"} while this grant's host call runs, then
    # {"state": "retained", "held": ...} until graph settlement lands. Admission
    # refuses while any entry remains, so at most one exists; process local and
    # only ever recorded, never executed again.
    return vars(server).setdefault("_social_work_pending", {})


def _canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def _consume_capability(server, token: str, capability: dict) -> None:
    with server._connector_execution_capability_lock:
        if server._connector_execution_capabilities.pop(token, None) is not capability:
            raise AuthorizationDenied("Social execution capability was already consumed")


def _admitted_social_grant(server, *, session_root, delegation_root, grant_root, capability, context):
    """Revalidate Work, session, provider, grant token, saved inputs and reservation."""
    from . import universal_application as app
    from .cell_connector_execution import read_connector_provider

    store, registry = server.universal_store, server.universal_registry
    protocol, adapters = registry.baboom_connector_execution_protocol, registry.adapter_protocol
    delegation = app.authorize_universal_baboom_connector_execution(
        store, registry, agent_session_root=session_root, delegation_root=delegation_root,
        authentication_context=context)
    snapshot = store.snapshot()
    provider = read_connector_provider(snapshot, protocol, adapters, delegation.provider_root)
    operation = social_provider_operation(registry, provider)
    if operation is None:
        raise AuthorizationDenied("This grant does not authorize a social provider")
    grant = read_connector_execution_grant(snapshot, protocol, adapters, grant_root)
    if (grant.delegation_root != delegation.root_id or grant.session_root != session_root
            or time.time() >= min(grant.expires_at, delegation.expires_at)
            or not hmac.compare_digest(grant.token_digest,
                                       hashlib.sha256(capability.encode("utf-8")).hexdigest())):
        raise AuthorizationDenied("Social execution grant binding changed or expired")
    app._baboom_execution_work_context(store, registry, agent_session_root=session_root,
        work_root=delegation.work_root, authentication_context=context, purpose="Workshop social execution")
    snapshot = store.snapshot()
    prepared, raw = social_material_at(snapshot, registry, delegation.work_root)
    if (len(raw) != delegation.input_bytes
            or not hmac.compare_digest(hashlib.sha256(raw).hexdigest(), delegation.input_digest)
            or prepared.operation != operation):
        raise AuthorizationDenied("Social request, account or inputs changed after approval")
    write = OPERATIONS[operation][1] == "write"
    if write:
        key, _ = social_attempt_key(provider.root_id, prepared)
        attempt = read_social_attempt(snapshot, attempt_root_for(grant.root_id))
        if (attempt.key_root != _key_root(key)
                or _read_head(snapshot, _head_root(key), attempt.key_root) != attempt.root_id
                or attempt.delegation_root != delegation.root_id or attempt.session_root != session_root
                or attempt.work_root != delegation.work_root or attempt.provider_root != provider.root_id):
            raise AuthorizationDenied("Social attempt is not this grant's current reservation")
    for root in (dispatch_root_for(grant.root_id), receipt_root_for(grant.root_id),
                 social_result_root_for(grant.root_id), resolution_root_for(grant.root_id)):
        if root in snapshot.cells:
            raise AuthorizationDenied("Social grant already has an execution record; read its result instead")
    vault_entry = json.loads(raw.decode("utf-8"))["inputs"]["vault_entry"]
    from .social_custody import require_social_vault_reference
    require_social_vault_reference(snapshot, vault_entry)
    return delegation, grant, prepared, vault_entry, write


def _host_answer(answer, dispatched: bool):
    """(outcome, result, error_code, marker) from one host answer.

    An unusable answer after dispatch, or a host that reports an effect without
    completing the admitted before_dispatch, stays uncertain and marked.
    """
    valid = (type(answer) is dict and set(answer) == {"outcome", "result"}
             and type(answer["outcome"]) is str and answer["outcome"] in _OUTCOMES
             and type(answer["result"]) is dict and type(answer["result"].get("state")) is str)
    if valid:
        outcome, result = answer["outcome"], answer["result"]
        try:
            size = len(_canonical(result))
        except (TypeError, ValueError):
            valid = False
        else:
            valid = size <= _RESULT_BYTES and (
                (outcome == "succeeded" and result.get("ok") is True and result["state"] == "ok")
                or (outcome == "failed" and result.get("ok") is False
                    and result["state"] not in ("ok", "uncertain"))
                or (outcome == "uncertain" and result.get("ok") is not True))
    if not valid:
        if dispatched:
            return ("uncertain", {"ok": False, "state": "uncertain", "reason":
                    "The host answer is unusable after dispatch; reconcile before any new attempt."}, "", True)
        return ("failed", {"ok": False, "state": "host_answer_invalid", "reason":
                "The host answered without a usable result and without dispatch."}, "host_answer_invalid", False)
    if outcome == "failed":
        state = result["state"]
        code = state if len(state) <= 128 and _ERROR_CODE.fullmatch(state) else "provider.failed"
        return outcome, result, code, dispatched
    if not dispatched:
        return ("uncertain", {"ok": False, "state": "uncertain", "reason":
                "The host reported an effect without admitted dispatch; reconcile before any new attempt."},
                "", True)
    return outcome, result, "", True


def _record_social_outcome(server, *, delegation, grant, operation, write, outcome, result, error_code, marker):
    """Record what the host already did; an uncertain outcome gets no receipt."""
    from . import universal_application as app
    from .cell_adapters import read_permission, revoke_permission
    from .cell_connector_execution import create_connector_execution_receipt
    from .cell_value_graph import build_value_graph

    store, registry = server.universal_store, server.universal_registry
    protocol, adapters = registry.baboom_connector_execution_protocol, registry.adapter_protocol
    canonical = _canonical(result)
    value = {"work": delegation.work_root, "session": delegation.session_root, "delegation": delegation.root_id,
             "grant": grant.root_id, "input_digest": delegation.input_digest, "operation": operation,
             "outcome": outcome, "dispatched": bool(marker), "error_code": error_code,
             "output_digest": hashlib.sha256(canonical).hexdigest(), "result": result}
    snapshot = store.snapshot()
    marker_root = dispatch_root_for(grant.root_id)
    if write and marker and marker_root not in snapshot.cells:
        store.commit(snapshot.revision, create=prepare_social_dispatch_marker(snapshot, grant.root_id))
        snapshot = store.snapshot()
    root = social_result_root_for(grant.root_id)
    if root in snapshot.cells:
        if read_value_graph(snapshot, registry.value_graph_protocol, root) != value:
            raise InvalidCell("Recorded social result differs from the retained host outcome")
    else:
        build_value_graph(store, registry.value_graph_protocol, value, root_id=root)
        attached = (root, marker_root) if write and marker else (root,)
        app._attach_connector_authority_roots(store, registry, attached)
    receipt_root = None
    if outcome != "uncertain":
        receipt_root = receipt_root_for(grant.root_id)
        snapshot = store.snapshot()
        if receipt_root in snapshot.cells:
            receipt = read_connector_execution_receipt(snapshot, protocol, adapters, receipt_root)
            if (receipt.grant_root != grant.root_id or receipt.outcome != outcome
                    or receipt.output_digest != value["output_digest"] or receipt.error_code != error_code):
                raise InvalidCell("Recorded social receipt differs from the retained host outcome")
        else:
            create_connector_execution_receipt(store, protocol, adapters, receipt_id=receipt_root,
                delegation_root=delegation.root_id, grant_root=grant.root_id,
                provider_root=delegation.provider_root, input_digest=delegation.input_digest,
                input_bytes=delegation.input_bytes, output_digest=value["output_digest"],
                output_bytes=len(canonical), outcome=outcome, error_code=error_code)
            app._attach_connector_authority_roots(store, registry, (receipt_root,))
        permission = read_permission(store.snapshot(), adapters, delegation.permission_root)
        if permission.lifecycle_root == adapters.states["granted"]:
            revoke_permission(store, adapters, delegation.permission_root)
    return {"work": value["work"], "delegation": value["delegation"], "grant": value["grant"],
            "input_digest": value["input_digest"], "operation": operation, "outcome": outcome,
            "receipt": receipt_root, "result": result, "revision": store.revision}


def execute_social_work(server, request, body, direct, context):
    """Run the injected social host once for one exact issued grant; never replay.

    Body {"grant","capability"} executes; body {"grant"} reads and reconciles
    that grant's recorded outcome. The saved Work inputs are recomputed; no
    caller payload is trusted. The host resolves credentials; before dispatch
    host custody must verify provider, account and vault entry. For writes the
    final before_dispatch action commits the dispatch marker under mutation_lock;
    no lock is held across the provider call. Admission reserves this grant's
    in-flight entry and the existing single-flight execution owner
    (_model_execution_active/_model_execution_idle) before the capability is
    consumed; close() and retention wait on that owner.
    """
    if direct or type(body) is not dict:
        raise AuthorizationDenied("Social execution requires its bound exact grant")
    if set(body) == {"grant"} and type(body["grant"]) is str:
        return read_social_work_result(server, request, body["grant"], context)
    if (set(body) != {"grant", "capability"} or type(body["grant"]) is not str
            or type(body["capability"]) is not str):
        raise AuthorizationDenied("Social execution requires its bound exact grant")
    host = getattr(server, "social_execution_host", None)
    verifier = getattr(server, "social_account_binding_verifier", None)
    registry = server.universal_registry
    with _stable_admission(server, context):
        if (server._model_execution_closing or server._model_execution_active
                or server._project_work_pending is not None):
            raise AuthorizationDenied("Workshop execution is busy or shutting down")
        if _pending(server):
            raise AuthorizationDenied("A social result is pending; read it before any new social execution")
        if server.universal_checkpoint_guard is not None:
            server.universal_checkpoint_guard.require_healthy()
        server.require_universal_http_route("POST", SOCIAL_EXECUTE_ROUTE, authentication_context=context,
                                            revalidate=True)
        if host is None or not callable(getattr(host, "execute", None)):
            raise InvalidCell("Social execution host is unavailable; nothing was sent")
        if not callable(verifier):
            raise InvalidCell("Social account binding verifier is unavailable; nothing was sent")
        session = server._resolve_universal_machine_agent_session(request)
        with server._connector_execution_capability_lock:
            capability = server._connector_execution_capabilities.get(body["capability"])
        if (type(capability) is not dict or capability.get("grant") != body["grant"]
                or capability.get("session") != session or time.time() >= capability.get("expires_at", 0)):
            raise AuthorizationDenied("Social execution capability is invalid, expired or consumed")
        delegation, grant, prepared, vault_entry, write = _admitted_social_grant(
            server, session_root=session, delegation_root=capability["delegation"],
            grant_root=body["grant"], capability=body["capability"], context=context)
        registry.authorization.broker.resolve(context)
        # Reserve the exact in-flight entry and the existing execution owner
        # before consuming; model, project and social execution stay single-flight.
        _pending(server)[grant.root_id] = {"state": "in_flight"}
        server._model_execution_active = True
        server._model_execution_idle.clear()
    operation = prepared.operation
    dispatch = {"done": False}

    def before_dispatch():
        store = server.universal_store
        with server.mutation_lock:
            with registry.authorization.broker.live_context(context):
                if server._model_execution_closing:
                    raise AuthorizationDenied("Social execution is shutting down; nothing was sent")
                if server.universal_checkpoint_guard is not None:
                    server.universal_checkpoint_guard.require_healthy()
                server.require_universal_http_route("POST", SOCIAL_EXECUTE_ROUTE,
                                                    authentication_context=context, revalidate=True)
                current = _admitted_social_grant(server, session_root=session, delegation_root=delegation.root_id,
                    grant_root=grant.root_id, capability=body["capability"], context=context)
                if current[2] != prepared or current[3] != vault_entry:
                    raise AuthorizationDenied("Social request changed before dispatch")
                registry.authorization.broker.resolve(context)
                if write:
                    snapshot = store.snapshot()

                    def usable():
                        if time.time() >= min(grant.expires_at, delegation.expires_at):
                            raise AuthorizationDenied("Social grant expired before dispatch")

                    store.commit(snapshot.revision, create=prepare_social_dispatch_marker(snapshot, grant.root_id),
                                 precommit_guard=usable)
                dispatch["done"] = True

    try:
        try:
            verified = verifier(provider=prepared.provider, account_id=prepared.account_id, vault_entry=vault_entry)
        except Exception:
            verified = False
        if verified is not True:
            raise InvalidCell("Social account binding is unavailable; capability retained and nothing was sent")
        # Custody inspection runs outside graph locks. Re-admit its exact Work
        # after it returns, then consume once; missing credentials spend nothing.
        with _stable_admission(server, context):
            if server._model_execution_closing:
                raise AuthorizationDenied("Social execution is shutting down; nothing was sent")
            if server.universal_checkpoint_guard is not None:
                server.universal_checkpoint_guard.require_healthy()
            server.require_universal_http_route("POST", SOCIAL_EXECUTE_ROUTE,
                                                authentication_context=context, revalidate=True)
            current = _admitted_social_grant(server, session_root=session,
                delegation_root=delegation.root_id, grant_root=grant.root_id,
                capability=body["capability"], context=context)
            if current[2] != prepared or current[3] != vault_entry:
                raise AuthorizationDenied("Social request changed during custody inspection")
            if time.time() >= capability.get("expires_at", 0):
                raise AuthorizationDenied("Social execution capability expired during custody inspection")
            registry.authorization.broker.resolve(context)
            _consume_capability(server, body["capability"], capability)
        try:
            answer = host.execute(prepared, vault_entry, before_dispatch=before_dispatch)
        except Exception as error:
            answer = None if dispatch["done"] else {"outcome": "failed", "result": {
                "ok": False, "state": "dispatch_refused",
                "reason": "The request was refused before dispatch (%s)." % type(error).__name__}}
        outcome, result, error_code, marker = _host_answer(answer, dispatch["done"])
        held = dict(delegation=delegation, grant=grant, operation=operation, write=write, outcome=outcome,
                    result=result, error_code=error_code, marker=marker)
        with server.mutation_lock:
            _pending(server)[grant.root_id] = {"state": "retained", "held": held}
            recorded = _record_social_outcome(server, **held)
            _pending(server).pop(grant.root_id, None)
            return recorded
    finally:
        with server.mutation_lock:
            entry = _pending(server).get(grant.root_id)
            if entry is not None and entry["state"] == "in_flight":
                if dispatch["done"]:
                    # Interrupted after dispatch without any answer: retain it as uncertain.
                    _pending(server)[grant.root_id] = {"state": "retained", "held": dict(
                        delegation=delegation, grant=grant, operation=operation, write=write,
                        outcome="uncertain", result={"ok": False, "state": "uncertain", "reason":
                        "Execution was interrupted after dispatch; reconcile before any new attempt."},
                        error_code="", marker=True)}
                else:
                    _pending(server).pop(grant.root_id, None)
            server._model_execution_active = False
            server._model_execution_idle.set()


def read_social_work_result(server, request, grant_root, context):
    """Reconcile one exact grant from graph records and retained outcomes; never execute."""
    from .cell_connector_execution import read_connector_provider

    store, registry = server.universal_store, server.universal_registry
    protocol, adapters = registry.baboom_connector_execution_protocol, registry.adapter_protocol
    with server.mutation_lock:
        with registry.authorization.broker.live_context(context):
            if server.universal_checkpoint_guard is not None:
                server.universal_checkpoint_guard.require_healthy()
            server.require_universal_http_route("POST", SOCIAL_EXECUTE_ROUTE, authentication_context=context,
                                                revalidate=True)
            session = server._resolve_universal_machine_agent_session(request)
            snapshot = store.snapshot()
            grant = read_connector_execution_grant(snapshot, protocol, adapters, grant_root)
            delegation = read_connector_delegation(snapshot, protocol, adapters, grant.delegation_root)
            provider = read_connector_provider(snapshot, protocol, adapters, delegation.provider_root)
            operation = social_provider_operation(registry, provider)
            if operation is None or grant.session_root != session or delegation.session_root != session:
                raise AuthorizationDenied("Social result belongs to another session or provider")
            registry.authorization.broker.resolve(context)
            write = OPERATIONS[operation][1] == "write"
            entry = _pending(server).get(grant.root_id)
            if entry is not None and entry["state"] == "in_flight":
                # The host call has not settled; report it without executing or recording.
                return {"work": delegation.work_root, "delegation": delegation.root_id, "grant": grant.root_id,
                        "input_digest": delegation.input_digest, "operation": operation, "outcome": "in_flight",
                        "receipt": None, "result": {"ok": False, "state": "in_flight", "reason":
                        "The host call has not settled; nothing is recorded yet."}, "revision": store.revision}
            if entry is not None:
                recorded = _record_social_outcome(server, **entry["held"])
                _pending(server).pop(grant.root_id, None)
                return recorded
            root = social_result_root_for(grant.root_id)
            if root in snapshot.cells:
                value = read_value_graph(snapshot, registry.value_graph_protocol, root)
                if (type(value) is not dict or value.get("grant") != grant.root_id
                        or value.get("delegation") != delegation.root_id or value.get("work") != delegation.work_root
                        or value.get("input_digest") != delegation.input_digest
                        or value.get("operation") != operation):
                    raise InvalidCell("Recorded social result lineage drifted")
                return _record_social_outcome(server, delegation=delegation, grant=grant, operation=operation,
                    write=write, outcome=value["outcome"], result=value["result"],
                    error_code=value["error_code"], marker=value["dispatched"])
            if write and dispatch_root_for(grant.root_id) in snapshot.cells:
                return {"work": delegation.work_root, "delegation": delegation.root_id, "grant": grant.root_id,
                        "input_digest": delegation.input_digest, "operation": operation, "outcome": "uncertain",
                        "receipt": None, "result": {"ok": False, "state": "uncertain", "reason":
                        "Dispatch was marked and no outcome was recorded; reconcile before any new attempt."},
                        "revision": store.revision}
            raise AuthorizationDenied("Social grant has no recorded execution")
