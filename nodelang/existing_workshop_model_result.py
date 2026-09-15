"""Publish an existing model receipt as Workshop evidence, never execute a model.

The owner must authenticate and bind its machine caller before invoking this
helper. All claims and message content below come from the same graph revision.
Publication requires the worker's still-claimed Work; completion is separate.
"""
import hashlib
import json
from typing import Mapping

from .cell_authorization import AuthorizationDenied
from .cell_deliberation import read_deliberation_space
from .cell_model_execution import read_model_delegation, read_model_execution_receipt
from .universal_cell import InvalidCell, NULL_CELL_ID


def _identity(value):
    if type(value) is not str or not value or len(value) > 4096:
        raise InvalidCell("Workshop model-result identity is invalid")
    return value


def publish_verified_model_result(store, registry, *, agent_session_root, receipt_root,
        proposal_root, recipient_root, reply_to_root, authentication_context, inspect_only=False,
        content_service=None):
    """Resolve receipt/proposal provenance before one revision-bound append."""
    from . import universal_application as app
    for root in (agent_session_root, receipt_root, recipient_root):
        _identity(root)
    for root in (proposal_root, reply_to_root):
        if root is not None:
            _identity(root)
    if authentication_context is None:
        raise AuthorizationDenied("Workshop result publication requires explicit authentication")
    snapshot = store.snapshot()
    protocol = registry.baboom_model_execution_protocol
    receipt = read_model_execution_receipt(snapshot, protocol, registry.adapter_protocol, receipt_root)
    delegation = read_model_delegation(snapshot, protocol, registry.adapter_protocol, receipt.delegation_root)
    if delegation.session_root != agent_session_root:
        raise AuthorizationDenied("Workshop receipt belongs to another worker")
    if (receipt.provider_root != delegation.provider_root or receipt.model != delegation.model or
            receipt.input_digest != delegation.input_digest):
        raise InvalidCell("Workshop receipt and delegation evidence disagree")
    required_state = "claimed"
    if receipt.outcome == "failed":
        machine = app.read_instance_state_machine(snapshot, registry.assembly_protocol,
            registry.standard_library.state_machine_protocol, delegation.work_root)
        required_state = app._text(snapshot, machine.current_state_root).casefold()
        if required_state not in {"claimed", "blocked"}:
            raise AuthorizationDenied("Failed Workshop result requires the worker's claimed or blocked Work")
    session, _body, work = app._baboom_execution_work_context(store, registry,
        agent_session_root=agent_session_root, work_root=delegation.work_root,
        authentication_context=authentication_context, required_state=required_state,
        purpose="Workshop model result publication")
    for root in (delegation.work_root, receipt_root):
        app._require_application_authorization(snapshot, registry, "read", root,
            authentication_context=authentication_context)
    # Match the existing shared peer-review lens's confidentiality boundary.
    data_class = app._text(snapshot, delegation.datatype_root)
    interfaces = work.get("interfaces")
    title = interfaces.get("title") if isinstance(interfaces, Mapping) else None
    _title, protected = app._founder_governed_work_title(
        title.get("value") if isinstance(title, Mapping) else None)
    if protected or data_class not in {"public-text", "internal-text"}:
        raise AuthorizationDenied("Protected model evidence cannot enter the shared Workshop")
    # A recipient must remain within the authenticated owner's participant set.
    # Cross-owner disclosure needs its own admitted audience contract.
    if recipient_root != session.subject_root:
        recipient = app._runtime_agent_session(snapshot, registry, recipient_root)
        if recipient.subject_root != session.subject_root:
            raise AuthorizationDenied("Workshop result recipient belongs to another owner")
    space = read_deliberation_space(snapshot, registry.deliberation_protocol, registry.workshop_root)
    if agent_session_root not in space.participant_roots or recipient_root not in space.participant_roots:
        raise AuthorizationDenied("Workshop model result requires existing participants")

    evidence = [receipt_root]
    if receipt.outcome == "succeeded":
        if proposal_root is None or not delegation.cognition_request_root:
            raise InvalidCell("Successful model result requires its Cognition proposal")
        app._require_application_authorization(snapshot, registry, "read", proposal_root,
            authentication_context=authentication_context)
        proposal = app.read_proposal(store, registry.assembly_protocol,
            registry.standard_library.catalog_root, registry.agent_body.cognition_protocol,
            registry.agent_body.cognition_definitions, registry.adapter_protocol,
            registry.baboom_cognition_adapter_catalog_root, registry.agent_body.protocol,
            registry.authorization.protocol, proposal_root,
            model_binding_verifier=app._baboom_cognition_model_binding_verifier(registry))
        if proposal.request_root != delegation.cognition_request_root:
            raise InvalidCell("Workshop proposal belongs to another Cognition request")
        cell = snapshot.cells.get(proposal.payload_root)
        if (cell is None or cell.link0 != NULL_CELL_ID or cell.link1 != NULL_CELL_ID or
                not 0 < len(cell.atom) <= 65536):
            raise InvalidCell("Workshop proposal payload is not a bounded terminal")
        try:
            payload = json.loads(cell.atom.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise InvalidCell("Workshop proposal payload is invalid") from exc
        if type(payload) is not dict or set(payload) != {
                "kind", "summary", "next_actions", "risks", "uncertainty",
                "provider", "model", "output_digest", "output_bytes"}:
            raise InvalidCell("Workshop proposal payload fields are invalid")
        provider = next((name for name, root in registry.baboom_model_provider_roots.items()
            if root == delegation.provider_root), None)
        if (provider is None or payload["kind"] != "baboom-model-review-proposal/v1" or
                payload["provider"] != provider or payload["model"] != receipt.model or
                payload["output_digest"] != receipt.output_digest or
                type(payload["output_bytes"]) is not int or payload["output_bytes"] != receipt.output_bytes):
            raise InvalidCell("Workshop proposal output does not match the execution receipt")
        review = {name:payload[name] for name in ("summary", "next_actions", "risks", "uncertainty")}
        normalized, _summary, _uncertainty = app._bounded_baboom_cognition_review_payload(
            review, provider=provider, model=receipt.model, output_digest=receipt.output_digest,
            output_bytes=receipt.output_bytes)
        if normalized != payload:
            raise InvalidCell("Workshop proposal review is not normalized")
        content = "Model review evidence. Independent review is still required.\n" + json.dumps(
            review, ensure_ascii=False, indent=2)
        evidence.append(proposal_root)
    elif receipt.outcome == "failed":
        if proposal_root is not None:
            raise InvalidCell("Failed model receipt cannot publish a proposal")
        content = "Model execution failed. Review the recorded receipt before another execution."
    else:
        raise InvalidCell("Workshop receipt outcome is invalid")
    content = app.validate_universal_workshop_entry_content(content)
    if len(content.encode("utf-8")) > 12000:
        raise InvalidCell("Workshop model review exceeds its bounded message size")
    if store.revision != snapshot.revision:
        raise AuthorizationDenied("Workshop result source changed; refresh before publishing")
    identity = registry.authorization.broker.resolve(authentication_context)
    if identity.subject_root != session.subject_root:
        raise AuthorizationDenied("Workshop result caller changed")
    if inspect_only:
        return {"receipt":receipt_root, "proposal":proposal_root,
            "reconciled":receipt.outcome == "succeeded",
            "review_text":json.dumps(review, ensure_ascii=False, indent=2)
                if receipt.outcome == "succeeded" else ""}
    actor_context = registry.authorization.broker.mint_authenticated_context(agent_session_root,
        principal_roots=(), tenant_root=identity.tenant_root, assurance_root=identity.assurance_root,
        lifetime_seconds=60.0)
    key = hashlib.sha256(json.dumps([receipt_root, recipient_root, reply_to_root],
        separators=(",", ":")).encode("utf-8")).hexdigest()
    try:
        entry = app.append_universal_workshop_entry(store, registry,
            actor_root=agent_session_root, category_root=registry.workshop_category_roots["note"],
            content=content, idempotency_key="model-result:" + key,
            created_at=None, recipient_roots=(recipient_root,),
            reference_roots=(delegation.work_root,), reply_to_root=reply_to_root,
            evidence_roots=tuple(evidence), authentication_context=actor_context,
            source_authentication_context=authentication_context,
            content_service=content_service,
            expected_revision=snapshot.revision)
    finally:
        registry.authorization.broker.revoke(actor_context)
    from .conversation_content import workshop_message_identity
    return {"ok":True, "workshop":registry.workshop_root, **workshop_message_identity(entry),
        "receipt":receipt_root, "proposal":proposal_root, "idempotency_key":entry.idempotency_key,
        "revision":store.revision}
