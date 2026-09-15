"""Project repair execution through the existing Work and connector authority.

The graph owns the task, selected input, approval, reservation and result. The
explicitly supplied host generates an artifact; it cannot edit source files.
An issued connector grant reserves one attempt, including after response loss.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import time
from contextlib import contextmanager

from .cell_authorization import AuthorizationDenied
from .cell_connector_execution import (
    create_connector_execution_receipt, read_connector_execution_grant,
    read_connector_execution_receipt, read_connector_provider, read_connector_delegation,
)
from .cell_value_graph import build_value_graph, read_value_graph
from .universal_cell import InvalidCell


PROVIDER = "workshop-project-repair"
OPERATION = "workshop.project.repair"


def project_saved_artifacts(snapshot, registry, work_root, *, receipt_root=None):
    """Project durable results for an already read-admitted Work; never invoke.

    Receipt/grant/delegation readers retain their registered graph validation.
    This is a bounded selected-Work projection, not another artifact registry.
    """
    from .cell_protocols import read_relation
    protocol = registry.baboom_connector_execution_protocol
    if receipt_root is None:
        members = read_relation(snapshot, protocol.registry("receipt"), budget=8192,
                                retain_projection=False)
        roots = [member.participant_id for member in members
                 if member.role_id == protocol.role("registry-member")]
        if len(roots) > 256 or len(set(roots)) != len(roots):
            raise InvalidCell("Saved artifact receipt selection exceeds its bounded registry")
    else:
        roots = [receipt_root]
    artifacts = []
    for root in roots:
        receipt = read_connector_execution_receipt(snapshot, protocol, registry.adapter_protocol, root)
        delegation = read_connector_delegation(snapshot, protocol, registry.adapter_protocol,
                                                receipt.delegation_root)
        if delegation.work_root != work_root:
            if receipt_root is not None:
                raise AuthorizationDenied("Artifact receipt belongs to another Work")
            continue
        if (receipt.provider_root != registry.baboom_connector_provider_roots.get(PROVIDER)
                or receipt.operation != OPERATION or receipt.outcome != "succeeded"):
            if receipt_root is not None:
                raise InvalidCell("Receipt is not a successful project artifact")
            continue
        grant = read_connector_execution_grant(snapshot, protocol, registry.adapter_protocol, receipt.grant_root)
        result_root = grant.root_id + ":project-result"
        value = read_value_graph(snapshot, registry.value_graph_protocol, result_root, max_depth=4)
        expected = {"work", "session", "delegation", "grant", "input_digest", "outcome",
                    "artifact_name", "output_digest", "output_bytes", "error_code", "summary"}
        if (type(value) is not dict or set(value) != expected
                or value["work"] != work_root or value["session"] != delegation.session_root
                or value["delegation"] != delegation.root_id or value["grant"] != grant.root_id
                or grant.session_root != delegation.session_root or grant.delegation_root != delegation.root_id
                or value["input_digest"] != delegation.input_digest
                or value["input_digest"] != receipt.input_digest
                or value["outcome"] != "succeeded" or value["error_code"] != receipt.error_code
                or value["output_digest"] != receipt.output_digest
                or type(value["output_bytes"]) is not int or value["output_bytes"] != receipt.output_bytes
                or not 0 < value["output_bytes"] <= 262144
                or type(value["artifact_name"]) is not str
                or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*\.patch", value["artifact_name"]) is None
                or len(value["artifact_name"]) > 128
                or type(value["summary"]) is not str or len(value["summary"].encode("utf-8")) > 8192):
            raise InvalidCell("Saved project artifact disagrees with its execution receipt")
        artifacts.append({"work":work_root, "result":result_root, "receipt":receipt.root_id,
            "name":value["artifact_name"], "digest":receipt.output_digest, "bytes":receipt.output_bytes,
            "summary":value["summary"], "outcome":"succeeded"})
        if len(artifacts) > 32:
            raise InvalidCell("Selected Work has too many artifacts for one bounded projection")
    return artifacts


@contextmanager
def _stable_admission(server, context):
    registry, store = server.universal_registry, server.universal_store
    with server.mutation_lock:
        with registry.authorization.broker.live_context(context):
            with store.stable_snapshot():
                yield


def project_material_from_values(inputs, requirements, *, title, description):
    """Validate draft values with the same contract used at physical dispatch."""
    from .project_work_execution_broker import canonical_project_work_bytes
    if (type(inputs) is not dict or set(inputs) != {"model", "files", "artifact_name", "data_class"}
            or inputs["data_class"] != "public-text"):
        raise InvalidCell("Project work requires explicitly selected public input files")
    if type(requirements) is not dict or set(requirements) != {"acceptance_criteria"}:
        raise InvalidCell("Project work requires connected acceptance criteria")
    rows = requirements["acceptance_criteria"]
    if type(rows) is not list or not 1 <= len(rows) <= 8 or any(
        type(row) is not dict or set(row) != {"criterion", "verification"}
        or any(type(row[key]) is not str or not row[key].strip() for key in row)
        for row in rows
    ):
        raise InvalidCell("Project work criteria require an outcome and a verification method")
    if type(title) is not str or type(description) is not str or not description.strip():
        raise InvalidCell("Project work requires its requested change")
    request = {
        "model": inputs["model"], "task": title + "\n\n" + description,
        "criteria": [row["criterion"] + "\nVerification: " + row["verification"] for row in rows],
        "inputs": inputs["files"], "artifact_name": inputs["artifact_name"],
    }
    raw = canonical_project_work_bytes(request)
    return request, raw


def _material(store, registry, work_root, work):
    from . import universal_application as app

    snapshot = store.snapshot()
    inputs = read_value_graph(snapshot, registry.value_graph_protocol,
        app._governed_work_interface_target(snapshot, registry, work_root, "inputs"))
    requirements = read_value_graph(snapshot, registry.value_graph_protocol,
        app._governed_work_interface_target(snapshot, registry, work_root, "requirements"))
    interfaces = work.get("interfaces") or {}
    request, raw = project_material_from_values(inputs, requirements,
        title=(interfaces.get("title") or {}).get("value"),
        description=(interfaces.get("description") or {}).get("value"))
    if store.revision != snapshot.revision:
        raise InvalidCell("Project work changed while preparing its input")
    return request, raw


def prepare_project_work(server, *, work_root, session_root, context):
    """Prepare the exact graph-held task; no provider or filesystem invocation."""
    from . import universal_application as app

    store, registry = server.universal_store, server.universal_registry
    _, _, work = app._baboom_execution_work_context(store, registry,
        agent_session_root=session_root, work_root=work_root,
        authentication_context=context, purpose="Workshop project preparation")
    request, raw = _material(store, registry, work_root, work)
    delegation, operation, _, revision = app.request_universal_baboom_connector_execution(
        store, registry, agent_session_root=session_root, work_root=work_root,
        provider=PROVIDER, input_digest=hashlib.sha256(raw).hexdigest(),
        input_bytes=len(raw), data_class="public-text", lifetime_seconds=300.0,
        authentication_context=context)
    if operation != OPERATION:
        raise InvalidCell("Project work provider operation changed")
    return {"work":work_root, "worker":session_root, "delegation":delegation.root_id,
        "input_digest":delegation.input_digest, "model":request["model"],
        "review_text":json.dumps(request, ensure_ascii=False, indent=2),
        "artifact_name":request["artifact_name"], "revision":revision, "expires_at":delegation.expires_at}


def _record_result(server, delegation, grant, result):
    """Record what an admitted host already did, even after admission expires.

This is not an invocation authorization path. Its inputs are retained by the
owner across the physical call; neither a client nor a model reports a receipt.
"""
    from . import universal_application as app
    from .cell_adapters import read_permission, revoke_permission

    store, registry = server.universal_store, server.universal_registry
    root = grant.root_id + ":project-result"
    value = {"work":delegation.work_root, "session":delegation.session_root,
        "delegation":delegation.root_id, "grant":grant.root_id,
        "input_digest":delegation.input_digest, "outcome":result.outcome,
        "artifact_name":result.artifact_name, "output_digest":result.output_digest,
        "output_bytes":result.output_bytes, "error_code":result.error_code,
        "summary":result.summary}
    snapshot = store.snapshot()
    if root in snapshot.cells:
        if read_value_graph(snapshot, registry.value_graph_protocol, root) != value:
            raise InvalidCell("Recorded project result differs from the retained host outcome")
    else:
        build_value_graph(store, registry.value_graph_protocol, value, root_id=root)
        app._attach_connector_authority_roots(store, registry, (root,))
    receipt_root = None
    if result.outcome != "uncertain":
        protocol = registry.baboom_connector_execution_protocol
        receipt_root = grant.root_id + ":project-receipt"
        if receipt_root in store.snapshot().cells:
            receipt = read_connector_execution_receipt(store.snapshot(), protocol,
                registry.adapter_protocol, receipt_root)
            if (receipt.grant_root != grant.root_id or receipt.outcome != result.outcome
                    or receipt.output_digest != result.output_digest or receipt.output_bytes != result.output_bytes
                    or receipt.error_code != result.error_code):
                raise InvalidCell("Recorded project receipt differs from the retained host outcome")
        else:
            receipt = create_connector_execution_receipt(store, protocol, registry.adapter_protocol,
                receipt_id=receipt_root, delegation_root=delegation.root_id, grant_root=grant.root_id,
                provider_root=delegation.provider_root, input_digest=delegation.input_digest,
                input_bytes=delegation.input_bytes, output_digest=result.output_digest,
                output_bytes=result.output_bytes, outcome=result.outcome, error_code=result.error_code)
            app._attach_connector_authority_roots(store, registry, (receipt.root_id,))
        permission = read_permission(store.snapshot(), registry.adapter_protocol, delegation.permission_root)
        if permission.lifecycle_root == registry.adapter_protocol.states["granted"]:
            revoke_permission(store, registry.adapter_protocol, delegation.permission_root)
    return {"work":delegation.work_root, "delegation":delegation.root_id,
        "result":root, "receipt":receipt_root, "revision":store.revision, **value}


def execute_project_work(server, request, body, direct, context):
    """Invoke the owner-supplied host once, outside the graph mutation lock."""
    from . import universal_application as app

    with _stable_admission(server, context):
        if (server._model_execution_closing or server._model_execution_active
                or server._project_work_pending is not None):
            raise AuthorizationDenied("Workshop execution is busy or shutting down")
        if server.universal_checkpoint_guard is not None:
            server.universal_checkpoint_guard.require_healthy()
        server.require_universal_http_route("POST", "/api/universal/project-work-execute",
            authentication_context=context, revalidate=True)
        if direct or type(body) is not dict or set(body) != {"grant", "capability"}:
            raise AuthorizationDenied("Project execution requires its bound exact grant")
        if type(body["capability"]) is not str or type(body["grant"]) is not str:
            raise InvalidCell("Project execution grant is invalid")
        host = server.project_work_execution_broker
        if host is None:
            raise InvalidCell("This application has no connected project artifact host")
        session = server._resolve_universal_machine_agent_session(request)
        with server._connector_execution_capability_lock:
            capability = server._connector_execution_capabilities.get(body["capability"])
        if (type(capability) is not dict or capability.get("grant") != body["grant"]
                or capability.get("session") != session or time.time() >= capability.get("expires_at", 0)):
            raise AuthorizationDenied("Project execution capability is invalid, expired or consumed")
        store, registry = server.universal_store, server.universal_registry
        delegation = app.authorize_universal_baboom_connector_execution(store, registry,
            agent_session_root=session, delegation_root=capability["delegation"],
            authentication_context=context)
        if delegation.provider_root != registry.baboom_connector_provider_roots.get(PROVIDER):
            raise AuthorizationDenied("This grant does not authorize project artifact creation")
        snapshot = store.snapshot()
        provider = read_connector_provider(snapshot, registry.baboom_connector_execution_protocol,
            registry.adapter_protocol, delegation.provider_root)
        grant = read_connector_execution_grant(snapshot, registry.baboom_connector_execution_protocol,
            registry.adapter_protocol, body["grant"])
        if (provider.operation != OPERATION or grant.delegation_root != delegation.root_id
                or grant.session_root != session or time.time() >= grant.expires_at
                or not hmac.compare_digest(grant.token_digest,
                    hashlib.sha256(body["capability"].encode("utf-8")).hexdigest())):
            raise AuthorizationDenied("Project execution graph binding changed")
        _, _, work = app._baboom_execution_work_context(store, registry,
            agent_session_root=session, work_root=delegation.work_root,
            authentication_context=context, purpose="Workshop project execution")
        material, raw = _material(store, registry, delegation.work_root, work)
        if len(raw) != delegation.input_bytes or not hmac.compare_digest(
                hashlib.sha256(raw).hexdigest(), delegation.input_digest):
            raise AuthorizationDenied("Project task, criteria or selected input changed after approval")
        registry.authorization.broker.resolve(context)
        if time.time() >= min(grant.expires_at, delegation.expires_at, capability["expires_at"]):
            raise AuthorizationDenied("Project execution expired before invocation admission")
        with server._connector_execution_capability_lock:
            if server._connector_execution_capabilities.pop(body["capability"], None) is not capability:
                raise AuthorizationDenied("Project execution capability was already consumed")
        server._model_execution_active = True
        server._model_execution_idle.clear()
    @contextmanager
    def admit_publication():
        with _stable_admission(server, context):
            if server.universal_checkpoint_guard is not None:
                server.universal_checkpoint_guard.require_healthy()
            server.require_universal_http_route("POST", "/api/universal/project-work-execute",
                authentication_context=context, revalidate=True)
            current = app.authorize_universal_baboom_connector_execution(store, registry,
                agent_session_root=session, delegation_root=delegation.root_id,
                authentication_context=context)
            if current != delegation or time.time() >= grant.expires_at:
                raise AuthorizationDenied("Project publication permission changed or expired")
            _, _, current_work = app._baboom_execution_work_context(store, registry,
                agent_session_root=session, work_root=delegation.work_root,
                authentication_context=context, purpose="Workshop artifact publication")
            _, current_raw = _material(store, registry, delegation.work_root, current_work)
            if current_raw != raw:
                raise AuthorizationDenied("Project workflow changed before artifact publication")
            registry.authorization.broker.resolve(context)
            if time.time() >= grant.expires_at:
                raise AuthorizationDenied("Project publication grant expired before its physical effect")
            yield

    try:
        result = host.execute(material, before_publish=admit_publication)
        with server.mutation_lock:
            # Retain the actual result if graph settlement is interrupted. A new
            # grant cannot repeat the call, and the artifact is never overwritten.
            server._project_work_pending = (delegation, grant, result)
            recorded = _record_result(server, delegation, grant, result)
            server._project_work_pending = None
            return recorded
    finally:
        with server.mutation_lock:
            server._model_execution_active = False
            server._model_execution_idle.set()


__all__ = ["prepare_project_work", "execute_project_work"]
