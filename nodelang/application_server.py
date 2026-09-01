"""HTTP host for the node-native ArchHub application super-node."""
from __future__ import annotations

import argparse
import base64
import copy
import hashlib
import hmac
import json
import os
import re
import secrets
import sys
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler
from http.cookies import SimpleCookie
from pathlib import Path
from typing import Mapping
from urllib.parse import parse_qs, urlsplit

from .application_machine_transport import (
    BABOOM_NATIVE_FRAME_PROJECTION,
    BABOOM_NATIVE_REPORT_KIND,
    BABOOM_NATIVE_REPORT_SUMMARY,
    MachineTransportError,
    UniversalRuntimeTransport,
    runtime_device_proof_payload,
    session_proof_payload,
    validate_baboom_native_frame_payload,
)
from .model_execution_broker import ModelExecutionBroker
from .cell_capabilities import CAPABILITIES, missing_capabilities
from .cell_agent_body import read_agent_session
from .cell_baboom_model_execution import read_model_delegation
from .cell_deliberation import (
    append_deliberation_entry,
    append_deliberation_value_entry,
    evaluate_deliberation_gate,
    list_deliberation_entries,
    read_authorized_deliberation_entries,
    read_deliberation_space,
)
from .cell_value_graph import read_value_graph
from .cell_device_custody import (
    ActiveDeviceCustodyVerifier,
    read_device_custody,
)
from .cell_cloud_sessions import CloudSessionBroker, device_root_for_thumbprint
from .cell_dpop import JoseRfc9449ProofVerifier
from .cell_replay_policy_authority import (
    PublishedProofReplayPolicyVerifier,
)
from .cell_dpop_nonce import ResourceServerNonceBroker
from .cell_tenant_authority import PublishedTenantAdmissionVerifier
from .cell_runtime_presence import renew_runtime_presence
from .cell_reactions import ReactionEngine
from .cell_catalog import with_catalog_verification_scope
from .cell_protocols import read_relation, with_relation_projection_scope
from .core import relation_stages
from .domains.cockpit import submit_cockpit_command
from .http_server import QuietThreadingHTTPServer
from .laws_surface import ui_element
from .laws_relation import (append_stage, attach_payload, build_aead_stage,
                             build_json_codec_stage, build_payload_envelope,
                             set_relation_parameter)
from .map_import import resolve_map_path
from .persistence import (default_state_path, export_subgraph, load_snapshot,
                           registry_from_store, save_snapshot,
                           save_snapshot_cooperative)
from .ui_runtime import activate_ui, edit_ui_binding, project_document
from .universal_application import (
    UNIVERSAL_APPLICATION_SCHEMA_VERSION,
    adjudicate_universal_governed_work,
    apply_universal_canvas_gesture,
    append_universal_workshop_entry,
    assign_universal_workshop_work,
    assign_released_universal_theme,
    assign_released_universal_theme_to_audience,
    authorize_universal_cde_write,
    build_universal_application,
    begin_universal_runtime_agent_session,
    bind_universal_runtime_agent_body_device_custody,
    approve_universal_baboom_model_execution,
    _agent_body_catalog_entry_for_runtime,
    _agent_body_catalog_entry_for_session,
    attest_universal_runtime_compliance,
    issue_universal_baboom_model_execution_grant,
    prepare_universal_baboom_model_execution_invocation,
    prepare_universal_baboom_model_cognition_request,
    record_universal_baboom_activity,
    record_universal_baboom_meeting_notes,
    record_universal_baboom_steward_signal,
    record_universal_baboom_cognition_proposal,
    claim_next_universal_governed_work,
    claim_universal_baboom_work_claim_transfer,
    cancel_universal_baboom_work_claim_transfer,
    claim_universal_governed_work,
    create_universal_device_handoff_work,
    create_universal_device_handoff_work_for_device_ref,
    create_universal_governed_work,
    attach_universal_assembly_structured_fields,
    draft_universal_baboom_work_plan,
    submit_universal_composition_interaction,
    submit_universal_history_interaction,
    submit_universal_edit_value_interaction,
    submit_universal_transition_interaction,
    submit_universal_relation_member_interaction,
    submit_universal_topology_interaction,
    submit_universal_instantiation_interaction,
    submit_universal_relation_form_interaction,
    submit_universal_inspector_lens_interaction,
    submit_universal_scope_interaction,
    edit_universal_interface_value,
    edit_universal_lifecycle_content,
    merge_universal_lifecycle_content,
    ensure_universal_properties_panel_interactions,
    ensure_universal_relation_form_interactions,
    ensure_universal_composition_interactions,
    ensure_universal_history_interactions,
    ensure_universal_instantiation_interactions,
    ensure_universal_relation_composer_interactions,
    ensure_universal_property_interactions,
    ensure_universal_operational_transition_interactions,
    ensure_universal_presentation_interactions,
    ensure_universal_interface_value_interactions,
    ensure_universal_relation_member_interactions,
    ensure_universal_topology_interactions,
    ensure_universal_inspector_lens_interactions,
    ensure_universal_scope_interactions,
    follow_universal_theme_audience,
    issue_universal_authority_relationship,
    move_universal_root,
    promote_universal_resource_lifecycle,
    promote_universal_theme_to_published,
    promote_universal_theme_to_shared,
    project_universal_canvas,
    project_universal_scope_transition,
    project_universal_grand_map_work,
    project_universal_roma_requirement_tree_index,
    project_universal_roma_requirement_tree,
    project_universal_machine_canvas,
    project_universal_runtime_handoff_readiness,
    project_universal_baboom_context,
    project_universal_baboom_companion_directive,
    execute_universal_baboom_utterance,
    respond_universal_baboom_utterance,
    resolve_universal_baboom_utterance,
    project_universal_founder_baboom_capability_report,
    project_universal_mcp_broker,
    project_universal_founder_baboom_steward_briefing,
    project_universal_founder_attention_briefing,
    project_universal_founder_device_custody_report,
    project_universal_founder_workshop_report,
    list_universal_workshop_assignments,
    project_universal_device_handoffs,
    project_universal_baboom_work_claim_transfers,
    project_universal_governed_work,
    project_universal_governed_work_index,
    project_universal_governed_work_status,
    project_universal_value_graph,
    _instance_projection,
    instantiate_universal_definition,
    instantiate_universal_relation_definition,
    revoke_universal_authority_relationship,
    revoke_universal_founder_device_custody,
    restore_universal_application,
    request_universal_baboom_connector_execution,
    register_universal_mcp_server,
    negotiate_universal_mcp_server,
    request_universal_baboom_mcp_tool_execution,
    approve_universal_baboom_connector_execution,
    issue_universal_baboom_connector_execution_grant,
    recover_universal_baboom_connector_execution_failure,
    resume_universal_baboom_connector_execution_failure,
    settle_universal_baboom_connector_execution,
    request_universal_baboom_model_execution,
    read_universal_current_claimed_work,
    read_universal_baboom_work_plan,
    record_universal_device_handoff_receipt,
    initiate_universal_baboom_work_claim_transfer,
    recover_universal_baboom_model_execution_failure,
    resume_universal_baboom_model_execution_failure,
    set_universal_selection,
    sync_universal_grand_map_work,
    sync_universal_roma_requirement_tree,
    transition_universal_governed_work,
    transition_universal_operational_state,
    verify_universal_runtime_handoff_work,
    validate_universal_workshop_entry_content,
    settle_universal_baboom_model_execution,
    execute_universal_adapter_request,
    with_session_canvas_roots_scope,
)
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, utils
from .cell_adapters import UserConsentBroker
from .cell_secret_keys import (
    SigningKeyProvider,
    WindowsDpapiSigningKeyProvider,
)
from .cell_revision_checkpoint import (
    RevisionCheckpointGuard,
    RevisionCheckpointSigningAuthority,
)
from .cell_signing_authority import (
    SigningAuthorityDenied,
    build_signing_key_descriptor,
    read_signing_key_descriptor,
    verify_signing_key_descriptor,
)
from .cell_cde_authority import (
    cde_write_permit_identity,
    consume_cde_write_permit,
    issue_cde_write_permit,
)
from .cell_external_graph_binding import bind_external_signing_authority
from .windows_cng_signing_provider import (
    PLATFORM_PROVIDER_ID,
    SOFTWARE_PROVIDER_ID,
    WindowsCngSigningAuthorityProvider,
)


def _legacy_application_module():
    """Load the retired typed runtime only for an explicitly enabled bridge."""
    from . import application
    return application
from .cell_website import (
    PUBLIC_WEBSITE_ROUTES,
    project_universal_website_document,
)
from .site_export import SiteExportError, build_site_export
from .checkpoint_authority_provisioning import (
    provision_windows_revision_checkpoint_authority,
)
from .cell_control_bindings import CAPABILITY_EXECUTE, CAPABILITY_INSTANTIATE
from .clean_browser_authority import (
    CleanBrowserAuthority,
    revise_clean_browser_focus,
    verify_clean_browser_session,
)
from .clean_scope_interactions import (
    clean_scope_source_digest,
    derive_clean_scope_interactions,
    open_clean_scope_interactions,
    submit_clean_scope_interaction,
)
from .clean_visual_authority import open_clean_visual_system
from .clean_visual_projection import project_clean_visual_canvas
from .unified_application_lens import (
    project_unified_scope,
    scope_lens_payload,
)
from .cell_cloud_routes import (
    CloudRouteDenied,
    find_cloud_route,
    resolve_cloud_route,
)
from .unified_authority import (
    UnifiedAuthority,
    validate_composition,
    verify_exact_authority_head,
)


RUNTIME_PRESENCE_LEASE_SECONDS = 300.0
from .cell_browser_sessions import (
    BrowserSessionDenied,
    issue_browser_session as issue_browser_session_relation,
    list_browser_session_roots,
    read_browser_session,
    revoke_browser_session,
    verify_browser_session,
)
from .cell_exclusive_ownership import (
    acquire_ownership,
    read_ownership,
    read_ownership_transition,
    transition_ownership,
    verify_ownership_authority,
)
from .cell_identity import (
    grant_authority_relationship,
    verify_authority_relationship,
)
from .cell_protocols import prepare_append_relation_member, read_relation
from .cell_state_machine import (
    machine_history,
    read_instance_state_machine,
    read_transition,
    transition_machine_with_new_evidence,
)
from .cell_authorization import (
    AuthorizationDenied,
    AuthorizationRequest,
    require_authorization,
)
from .cell_interactions import (
    InteractionProjectionBroker,
    InteractionProjectionDenied,
    InteractionProjectionExpired,
    _read_interactions_with_verified_protocol,
    execute_interaction,
    read_interaction,
    with_interaction_projection_scope,
)
from .cell_relation_forms import read_relation_form_binding
from .cell_control_bindings import (
    CAPABILITY_COMPOSITION,
    CAPABILITY_EDIT_VALUE,
    CAPABILITY_HISTORY,
    CAPABILITY_INSTANTIATE,
    CAPABILITY_RELATION_FORM,
    CAPABILITY_RELATION_MEMBERS,
    CAPABILITY_SCOPE,
    CAPABILITY_TOPOLOGY,
    CAPABILITY_TRANSITION,
    CAPABILITY_VIEW_SECTION,
)
from .universal_cell import (
    NULL_CELL_ID,
    Cell,
    CellStore,
    Conflict,
    InvalidCell,
    RuntimeFenceLease,
)
from .universal_view import project_universal_document
from .runtime_credentials import (
    BrowserCredentialVault,
    BrowserSessionCredentials,
)
from .runtime_compliance_adapter import run_physical_runtime_compliance_court
from .runtime_gateway import BackendGeneration
from .universal_cloud_gateway import (
    UniversalCloudGateway,
    create_application_cloud_gateway,
    validate_universal_cloud_resource_origin,
)
from .universal_cloud_listener import (
    UniversalCloudTlsListener,
    create_universal_cloud_tls_server,
    validate_universal_cloud_tls_listener,
)


MAX_REQUEST_BODY_BYTES = 1_048_576
_INTERACTION_DELTA_MODE = "interaction-delta-v1"
_TOPOLOGY_DELTA_MODE = "topology-delta-v1"
_RECEIPT_MODE = "receipt-v1"
_MACHINE_WORKSHOP_ENTRY_LIMIT = 50
_BROWSER_SCOPE_PROJECTION_LIMIT = 8
_MACHINE_DELIBERATION_PAYLOAD_BYTES = 64 * 1024
_MACHINE_DELIBERATION_RESPONSE_BYTES = 192 * 1024
_TOPOLOGY_DELTA_FIELDS = (
    "authorization",
    "catalog",
)
_INTERACTION_DELTA_FIELDS = (
    "revision",
    "selected",
    "selection",
    "selected_title",
    "focus",
    "obligations",
    "scope",
    "authoring",
    "inspector",
    "properties",
    "selected_relation",
    "selected_interface",
    "selected_interfaces",
    "viewport",
    "selected_definition",
    "selected_assembly",
    "physical",
    "interaction_projection",
    "toolbar_descriptor",
    "canvas_heading_descriptor",
    "canvas_signature",
)


def _bounded_machine_deliberation_payload(payload):
    """Project one large Cell value without changing its graph authority."""
    raw = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    if len(raw) <= _MACHINE_DELIBERATION_PAYLOAD_BYTES:
        return payload, False

    def marker(value_raw, value):
        return {
            "truncated": True,
            "type": type(value).__name__,
            "bytes": len(value_raw),
            "sha256": hashlib.sha256(value_raw).hexdigest(),
        }

    if not isinstance(payload, dict):
        return marker(raw, payload), True

    projected = {}
    for key, value in payload.items():
        value_raw = json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        if len(value_raw) <= 8 * 1024:
            projected[key] = value
        else:
            projected[key] = marker(value_raw, value)
    projected_raw = json.dumps(
        projected,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    if len(projected_raw) > _MACHINE_DELIBERATION_PAYLOAD_BYTES:
        return marker(raw, payload), True
    return projected, True


def _validated_machine_deliberation_response(result):
    """Fail before transport when the complete bounded projection is too large."""
    raw = json.dumps(
        result,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    if len(raw) <= _MACHINE_DELIBERATION_RESPONSE_BYTES:
        return result
    entries = result.get("entries") if isinstance(result, dict) else None
    entry_sizes = tuple(
        len(json.dumps(
            entry,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8"))
        for entry in entries
    ) if isinstance(entries, list) else ()
    raise InvalidCell(
        "machine deliberation projection exceeds its response budget "
        "(bytes=%s, entries=%s, largest_entry_bytes=%s)" % (
            len(raw),
            len(entry_sizes),
            max(entry_sizes, default=0),
        )
    )
_CONFIGURATION_DELTA_FIELDS = (
    "actor",
    "asset",
    "binding",
    "binding_mode",
    "can_promote",
    "can_publish",
    "court",
    "digest",
    "heads",
    "history",
    "parents",
    "personal_asset",
    "pinned",
    "project",
    "project_title",
    "session",
    "workspace",
    "personal_wip_heads",
    "preview_revision",
    "published_revision",
    "shared_revision",
    "state",
    "theme",
    "theme_fields",
)


_CHOICE_FIELDS = frozenset({
    "connect_choices",
    "rewire_choices",
    "source_rewire_choices",
    "target_rewire_choices",
})


def _structural_value(value, *, parent_field=None):
    """Strip the volatile attributes so structure compares as structure."""
    if isinstance(value, dict):
        return {
            key: _structural_value(item, parent_field=key)
            for key, item in value.items()
            if key != "data-context"
            and not (parent_field in _CHOICE_FIELDS and key == "label")
        }
    if isinstance(value, list):
        return [
            _structural_value(item, parent_field=parent_field)
            for item in value
        ]
    return value


def _node_structure(node):
    return {
        key: _structural_value(value, parent_field=key)
        for key, value in node.items()
        if key not in {"selected", "x", "y"}
    }


def _wire_structure(wire):
    return {
        key: _structural_value(value, parent_field=key)
        for key, value in wire.items()
        if key not in {"selected", "context"}
    }


def _node_port_context(node):
    """Which ports are in context, in port order.

    A port's context is one boolean that lives inside a ten-kilobyte
    descriptor. Treating it as structure meant one flipped boolean re-shipped
    every node on the canvas -- 158KB to say "in context: false". It travels
    as state now, next to selected/x/y, where it belongs.
    """
    contexts = []
    for port in (node.get("ports") or ()):
        descriptor = port.get("descriptor") or ()
        first = descriptor[0] if descriptor else {}
        attributes = (first or {}).get("attributes") or {}
        contexts.append(bool(attributes.get("data-context")))
    return contexts


def _interaction_canvas_delta(
    projection: dict[str, object],
    *,
    base_revision: int,
    previous_projection: dict[str, object] | None = None,
) -> dict[str, object]:
    """Return revision-bound interaction state without copying static graph data."""
    configuration = projection["configuration"]
    previous_nodes = {
        str(node["id"]): node
        for node in (previous_projection or {}).get("nodes", ())
    }
    previous_wires = {
        "%s:%s" % (wire["id"], wire["segment"]): wire
        for wire in (previous_projection or {}).get("wires", ())
    }

    node_structure = _node_structure
    wire_structure = _wire_structure

    delta = {
        "projection_mode": _INTERACTION_DELTA_MODE,
        "base_revision": base_revision,
        "connection_count": len(projection["connections"]),
        "node_count": len(projection["nodes"]),
        "wire_count": len(projection["wires"]),
        "node_states": [
            {
                "id": node["id"],
                "selected": node["selected"],
                "x": node["x"],
                "y": node["y"],
                "port_context": _node_port_context(node),
            }
            for node in projection["nodes"]
            if (
                str(node["id"]) not in previous_nodes
                or any(
                    previous_nodes[str(node["id"])].get(field)
                    != node.get(field)
                    for field in ("selected", "x", "y")
                )
                or _node_port_context(previous_nodes[str(node["id"])])
                != _node_port_context(node)
            )
        ],
        "wire_states": [
            {
                "id": wire["id"],
                "segment": wire["segment"],
                "selected": wire["selected"],
                "context": wire["context"],
            }
            for wire in projection["wires"]
            if (
                "%s:%s" % (wire["id"], wire["segment"])
                not in previous_wires
                or any(
                    previous_wires[
                        "%s:%s" % (wire["id"], wire["segment"])
                    ].get(field) != wire.get(field)
                    for field in ("selected", "context")
                )
            )
        ],
        "node_patches": [
            node for node in projection["nodes"]
            if str(node["id"]) not in previous_nodes
            or node_structure(previous_nodes[str(node["id"])])
            != node_structure(node)
        ],
        "wire_patches": [
            wire for wire in projection["wires"]
            if "%s:%s" % (wire["id"], wire["segment"])
            not in previous_wires
            or wire_structure(previous_wires[
                "%s:%s" % (wire["id"], wire["segment"])
            ]) != wire_structure(wire)
        ],
        "control_state": projection["configuration"]["design_system"][
            "control_catalog"
        ],
        "configuration_state": {
            field: configuration[field]
            for field in _CONFIGURATION_DELTA_FIELDS
            if field in configuration
        },
    }
    delta.update({
        field: projection[field]
        for field in _INTERACTION_DELTA_FIELDS
        if field in projection and projection[field] is not None
    })
    return delta


def _topology_canvas_delta(
    projection: dict[str, object],
    *,
    base_revision: int,
    previous_projection: dict[str, object] | None = None,
) -> dict[str, object]:
    """Return a revision-bound topology patch or a complete recovery graph."""
    delta = _interaction_canvas_delta(
        projection,
        base_revision=base_revision,
        previous_projection=previous_projection,
    )
    delta["projection_mode"] = _TOPOLOGY_DELTA_MODE
    # The catalogue and the authorization block are ~200KB together and
    # change on almost no gesture. A patch that re-ships them on every
    # placement is a full projection wearing a delta's name. Ship each only
    # when it differs from what the client already holds; the client keeps
    # its held value when the field is absent.
    for field in _TOPOLOGY_DELTA_FIELDS:
        if field not in projection:
            continue
        if not (
            previous_projection is None
            or previous_projection.get("revision") != base_revision
            or previous_projection.get(field) != projection.get(field)
        ):
            continue
        # Placing one node adds it to every definition's connect choices, so
        # four of fourteen catalogue entries change -- and re-shipping the
        # whole catalogue spent 176KB announcing it. Ship the entries that
        # actually changed, positioned, and let the client splice.
        held = (previous_projection or {}).get(field)
        current = projection[field]
        if (
            field == "catalog"
            and isinstance(held, list)
            and isinstance(current, list)
            and len(held) == len(current)
        ):
            delta["catalog_items"] = [
                {"index": index, "item": item}
                for index, item in enumerate(current)
                if held[index] != item
            ]
            delta["catalog_count"] = len(current)
            continue
        delta[field] = projection[field]
    if (
        previous_projection is None
        or previous_projection.get("revision") != base_revision
    ):
        delta.update({
            "topology_recovery": True,
            "nodes": projection["nodes"],
            "wires": projection["wires"],
        })
    else:
        previous_nodes = {
            str(node["id"]): node
            for node in previous_projection["nodes"]
        }
        next_nodes = {
            str(node["id"]): node for node in projection["nodes"]
        }

        def wire_key(wire: dict[str, object]) -> str:
            return "%s:%s" % (wire["id"], wire["segment"])

        previous_wires = {
            wire_key(wire): wire for wire in previous_projection["wires"]
        }
        next_wires = {
            wire_key(wire): wire for wire in projection["wires"]
        }
        # A node whose only difference is selected / x / y / port context is
        # not a structural change, and shipping the whole node to say so cost
        # 158KB to move one boolean. Structure travels as a full node; state
        # travels as state.
        def node_changed_structurally(node):
            held = previous_nodes.get(str(node["id"]))
            return held is None or _node_structure(held) != _node_structure(node)

        def wire_changed_structurally(wire):
            held = previous_wires.get(wire_key(wire))
            return held is None or _wire_structure(held) != _wire_structure(wire)

        upsert_nodes = [
            node for node in projection["nodes"]
            if node_changed_structurally(node)
        ]
        upsert_wires = [
            wire for wire in projection["wires"]
            if wire_changed_structurally(wire)
        ]
        structural_node_ids = {str(node["id"]) for node in upsert_nodes}
        structural_wire_keys = {wire_key(wire) for wire in upsert_wires}
        delta["topology_patch"] = {
            "node_order": [str(node["id"]) for node in projection["nodes"]],
            "wire_order": [wire_key(wire) for wire in projection["wires"]],
            "remove_nodes": sorted(set(previous_nodes) - set(next_nodes)),
            "remove_wires": sorted(set(previous_wires) - set(next_wires)),
            "upsert_nodes": upsert_nodes,
            "upsert_wires": upsert_wires,
            "state_nodes": [
                {
                    "id": node["id"],
                    "selected": node["selected"],
                    "x": node["x"],
                    "y": node["y"],
                    "port_context": _node_port_context(node),
                }
                for node in projection["nodes"]
                if str(node["id"]) not in structural_node_ids
                and str(node["id"]) in previous_nodes
                and (
                    any(
                        previous_nodes[str(node["id"])].get(field)
                        != node.get(field)
                        for field in ("selected", "x", "y")
                    )
                    or _node_port_context(previous_nodes[str(node["id"])])
                    != _node_port_context(node)
                )
            ],
            "state_wires": [
                {
                    "id": wire["id"],
                    "segment": wire["segment"],
                    "selected": wire["selected"],
                    "context": wire["context"],
                }
                for wire in projection["wires"]
                if wire_key(wire) not in structural_wire_keys
                and wire_key(wire) in previous_wires
                and any(
                    previous_wires[wire_key(wire)].get(field)
                    != wire.get(field)
                    for field in ("selected", "context")
                )
            ],
        }
    delta.pop("node_states", None)
    delta.pop("wire_states", None)
    delta.pop("node_patches", None)
    delta.pop("wire_patches", None)
    return delta


def _bounded_assembly_projection(
    assembly: dict[str, object],
) -> dict[str, object]:
    """Return the machine-safe part of an assembly projection."""
    return {
        "definition": assembly.get("definition"),
        "name": assembly.get("name"),
        "version": assembly.get("version"),
        "interfaces": [
            {
                "id": item.get("id"),
                "name": item.get("name"),
                "target": item.get("target"),
                "value": item.get("value"),
                "editable": bool(item.get("editable")),
                "mode": item.get("mode"),
                "contract_root": item.get("contract_root"),
                "contract": item.get("contract"),
            }
            for item in assembly.get("interfaces", [])
            if isinstance(item, dict)
        ],
        "lifecycle": assembly.get("lifecycle"),
        "operational": assembly.get("operational"),
    }


def _machine_assembly_fields(raw: object) -> dict[str, str]:
    if not isinstance(raw, dict) or len(raw) > 32:
        raise InvalidCell("assembly fields must be a bounded mapping")
    fields: dict[str, str] = {}
    for key, value in raw.items():
        if type(key) is not str or not key.strip():
            raise InvalidCell("assembly field names must be non-empty text")
        if len(key.encode("utf-8")) > 512:
            raise InvalidCell("assembly field name exceeds its bound")
        text = "" if value is None else str(value)
        if len(text.encode("utf-8")) > 65_536:
            raise InvalidCell("assembly field value exceeds its bound")
        fields[key.strip()] = text
    return fields


def _machine_assembly_structured_fields(raw: object) -> dict[str, object]:
    """Admit bounded JSON-shaped values that will become Cell value graphs."""
    if not isinstance(raw, dict) or len(raw) > 32:
        raise InvalidCell("assembly structured fields must be a bounded mapping")
    fields: dict[str, object] = {}
    for key, value in raw.items():
        if type(key) is not str or not key.strip():
            raise InvalidCell("assembly structured field names must be non-empty text")
        if len(key.encode("utf-8")) > 512:
            raise InvalidCell("assembly structured field name exceeds its bound")
        try:
            encoded = json.dumps(value, ensure_ascii=False, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise InvalidCell("assembly structured field is not JSON-shaped") from exc
        if len(encoded.encode("utf-8")) > 65_536:
            raise InvalidCell("assembly structured field exceeds its bound")
        fields[key.strip()] = value
    return fields


@dataclass(frozen=True, slots=True)
class _BrowserSessionBinding:
    session_root: str
    subject_root: str
    view_root: str
    tenant_root: str
    assurance_root: str
    context: object
    csrf_token: str
    interaction_projection_handle: object


@dataclass(frozen=True, slots=True)
class _BrowserCanvasProjectionBinding:
    session_root: str
    subject_root: str
    view_root: str
    tenant_root: str
    assurance_root: str
    projection: dict[str, object]


@dataclass(frozen=True, slots=True)
class _CleanBrowserSessionBinding:
    session_root: str
    subject_root: str
    view_root: str
    tenant_root: str
    assurance_root: str


class CleanGestureRefused(Exception):
    """A gesture carrying facts this path has no signed command for."""


class _CleanAuthorityHttpServer:
    """Bounded clean-graph browser consumer without a second store."""

    def __init__(
        self,
        authority: UnifiedAuthority,
        *,
        browser_authority: CleanBrowserAuthority,
        authority_key_provider: SigningKeyProvider,
        scope_caller,
        scope_root: str,
        host: str = "127.0.0.1",
        port: int = 0,
        host_invoker=None,
    ) -> None:
        self.authority = authority
        # Which machine this runtime may reach is named by whoever stands
        # it up, not decided here. A server given no adapter can refuse
        # honestly; one that acquired a default could touch a host nobody
        # chose.
        self.clean_host_invoker = host_invoker
        self.clean_authority = authority
        self.clean_store = authority.store
        self.browser_authority = browser_authority
        self.clean_browser_authority = browser_authority
        self.authority_key_provider = authority_key_provider
        self.clean_caller = scope_caller
        self.clean_scope_root = scope_root
        # The interaction set is derived from the scope tree and the
        # published catalogue -- the same facts the persisted table merely
        # repeats (equivalence court: test_derived_interactions_equivalence).
        # Deriving here means a publish no longer has to rewrite the table
        # for every scope, and a graph whose table was retired still serves
        # every control. The persisted table, where present, remains the
        # source of interaction CELLS for reads; the derivation is the
        # source of the binding map.
        import time as _time
        _d0 = _time.perf_counter()
        # Only the scope in front of the founder, and the children it can
        # open. Expanding the whole tree derived 31,480 bindings over 318
        # scopes -- 1,290,811 cells, 12.7s of every start -- to serve one
        # screen. A scope is expanded when it is stood in.
        self._derived_scope_roots = (scope_root,)
        try:
            derived, derived_cells = derive_clean_scope_interactions(
                authority,
                browser_authority,
                scope_root,
                caller=scope_caller,
                roots=self._derived_scope_roots,
                depth=1,
            )
        except InvalidCell:
            # A scope root the graph does not hold, or one this caller
            # may not read, derives nothing. The server still stands and
            # every request against that scope is refused where it always
            # was -- at the request, with a 403 that names the scope --
            # rather than the process dying at construction.
            derived, derived_cells = None, ()
        try:
            installed = open_clean_scope_interactions(
                authority,
                caller=scope_caller,
            )
        except Exception:
            installed = None
        # The table covers the whole tree, so its staleness is judged
        # against the whole tree -- never against the one scope this
        # server built cells for, which would call every table stale.
        whole_digest = None
        if installed is not None:
            try:
                whole_digest = clean_scope_source_digest(
                    authority, scope_root, caller=scope_caller,
                )
            except InvalidCell:
                whole_digest = None
        if installed is not None and (
            whole_digest is None or installed.source_digest != whole_digest
        ):
            # The table was written for an older scope tree or catalogue.
            # The derivation reads the graph as it is now; the stale table
            # would refuse controls for everything added since. Serving the
            # derivation is serving the graph.
            installed = None
        # WHICH set is being served decides which digest a rebase must
        # compare against: the installed table's digest describes the whole
        # scope tree, the derivation's describes the scopes actually
        # expanded. Comparing one against the other refused every rebase
        # ("projection_lease_expired" on a click after any unrelated
        # commit), because the two can never be equal.
        self._interactions_are_installed = installed is not None
        self.clean_scope_interactions = installed or derived
        self._derived_interaction_cells = (
            () if installed is not None else derived_cells
        )
        self._record_gesture_timing(
            "boot: derive interactions + open table %.1fs "
            "(derived cells=%d scopes=%d bindings=%d)"
            % (
                _time.perf_counter() - _d0, len(derived_cells or ()),
                len(getattr(derived, "bindings", {}) or {}),
                sum(
                    len(controls)
                    for controls in (
                        getattr(derived, "bindings", {}) or {}
                    ).values()
                ),
            )
        )
        self.clean_interaction_broker = InteractionProjectionBroker()
        self._clean_projection_handles: dict[str, object] = {}
        self._clean_projection_cache: dict[tuple, tuple] = {}
        self._session_index = None
        self._live_sign_in = None
        self._mutation_lock = threading.RLock()
        self.httpd = QuietThreadingHTTPServer((host, port), self._make_handler())
        self.thread = None

    def _clean_sign_in(self):
        """Mint one bounded browser session for an explicit same-origin POST.

        Only reached from a POST carrying a custom header, which a
        cross-origin page cannot send without a preflight this server never
        answers. The token and CSRF go back in the response body -- readable
        only by same-origin script -- and never into a cookie, because
        cookies are ambient and are not port-scoped.
        """
        import secrets as _secrets
        from .clean_browser_authority import issue_clean_browser_session
        # A session is graph state, so minting one moves the revision --
        # and every cache in this process is keyed on the revision. Minting
        # per page load therefore made the act of signing in throw away the
        # work of everyone already signed in, including the projection the
        # new arrival is about to ask for. A live session is handed back
        # instead, and the graph only moves when there is genuinely no
        # session to give.
        held = self._live_sign_in
        if held is not None:
            token, csrf, session_root, revision, expires_at = held
            if time.time() < expires_at - 60.0:
                return {
                    "ok": True,
                    "token": token,
                    "csrf": csrf,
                    "session": session_root,
                    "revision": revision,
                }
        token = _secrets.token_urlsafe(24)
        csrf = _secrets.token_urlsafe(24)
        with self._mutation_lock:
            issued = issue_clean_browser_session(
                self.clean_authority,
                self.clean_browser_authority,
                token=token,
                csrf_token=csrf,
                lifetime_seconds=3600.0,
                caller=self.clean_caller,
                command_id=str(uuid.uuid4()),
            )
        self._live_sign_in = (
            token, csrf, issued.root_id, issued.revision, time.time() + 3600.0
        )
        return {
            "ok": True,
            "token": token,
            "csrf": csrf,
            "session": issued.root_id,
            "revision": issued.revision,
        }

    def _clean_control_capability(self, control_root):
        """What the graph says pressing this control does.

        The answer is the action of the interaction the graph installed for
        it, not a lookup by which control it is: a control's meaning lives
        in the interaction, and reading it there covers a toolbar button and
        a library definition with the same question. A control the graph
        declared no interaction for has no capability, and falls through to
        the path that refuses it.
        """
        from .cell_interactions import read_interaction

        interactions = self.clean_scope_interactions
        if interactions is None or type(control_root) is not str:
            return None
        binding = interactions.binding_for(self.clean_scope_root, control_root)
        if binding is None:
            return None
        interaction = read_interaction(
            self._interaction_snapshot(self.clean_authority.store.snapshot()),
            interactions.protocol,
            binding.interaction_root,
        )
        return interaction.action_root

    def _clean_instantiate_definition(self, binding, body, definition_root):
        """Put one published definition on the canvas of this scope.

        The library offers what the catalogue publishes; placing one is an
        ordinary signed instantiation followed by a placement, so a node
        that appears on the canvas is a node the graph agreed to and knows
        where it sits. Nothing about which definition comes from anywhere
        but the control that was pressed.
        """
        import uuid as _uuid

        from .unified_authority import instantiate_definition, place_composition

        created = instantiate_definition(
            self.clean_authority,
            definition_root,
            {},
            scope_root=self.clean_scope_root,
            caller=self.clean_caller,
            command_id=str(_uuid.uuid4()),
        )
        # A node with no place is a node the canvas cannot draw. It lands
        # where the founder dropped it when the request carries the point
        # (the same event-fact shape every placement interaction uses),
        # and in the corner only when nothing was said.
        drop_x, drop_y = 60.0, 60.0
        facts = body.get("event_facts")
        if isinstance(facts, list):
            for fact in facts:
                if not isinstance(fact, dict):
                    continue
                source = fact.get("source") or fact.get("input")
                value = fact.get("value")
                if type(value) in (int, float):
                    if source == "canvas-point-x":
                        drop_x = float(value)
                    elif source == "canvas-point-y":
                        drop_y = float(value)
        place_composition(
            self.clean_authority,
            self.clean_scope_root,
            created.root_id,
            {"x": drop_x, "y": drop_y},
            caller=self.clean_caller,
            command_id=str(_uuid.uuid4()),
        )
        # What you just placed is what you are holding. The focus was left
        # on whatever had been selected before, so the very next Delete
        # removed THAT -- two cards, in the founder's own graph, while the
        # node just placed stayed. Group already moves the focus to what it
        # produced; placing does the same.
        from .clean_browser_authority import revise_clean_browser_focus
        revise_clean_browser_focus(
            self.clean_authority,
            self.clean_browser_authority,
            binding.session_root,
            scope_root=self.clean_scope_root,
            selected_roots=[created.root_id],
            primary_root=created.root_id,
            caller=self.clean_caller,
            command_id=str(_uuid.uuid4()),
        )
        self._refresh_scope_interactions()
        payload = self._canvas(binding)
        payload.update({
            "definition": definition_root,
            "node": created.root_id,
            "replayed": created.replayed,
        })
        return payload


    def _graph_held_operations(self):
        """The operations whose meaning the graph itself carries.

        An operation with a released expression is computed from that
        expression (SPEC 4.1); the Python engines answer only for the ones
        the vocabulary still cannot say. A graph that holds no expressions
        yet simply gets the engines, so this never refuses a Run.
        """
        from .base_universal_catalogue import GRAPH_EXPRESSIONS
        from .cell_view_template import evaluate_view_expression
        from .clean_visual_authority import open_clean_visual_system

        snapshot = self.authority.store.snapshot()
        held = getattr(self, "_stem_expression_cache", None)
        if held is not None and held[0] == snapshot.revision:
            return held[1]
        try:
            visual = open_clean_visual_system(
                self.clean_authority, caller=self.clean_caller
            )
        except InvalidCell:
            return {}
        protocol = visual.protocol

        def evaluate(expression_root, projection):
            return evaluate_view_expression(
                snapshot, protocol, expression_root, projection
            )

        table = {}
        for engine, (_operation, arguments, output) in GRAPH_EXPRESSIONS.items():
            root = "app:stem-expression:%s:expression" % engine
            if root not in snapshot.cells:
                continue
            table[engine] = (
                evaluate,
                ((output, root),),
                tuple(name for kind, name in arguments if kind == "in"),
            )
        # Branching operations were part of a vocabulary extension that was
        # backed out; the table they were read from no longer exists, and
        # importing it took the whole Run down with a 500. Their engines
        # answer in Python until an expression form exists that a graph can
        # actually say.
        self._stem_expression_cache = (snapshot.revision, table)
        return table

    def _revise_instance_adopting(self, instance_root, changes, *, scope_root):
        """Revise one instance, adopting its definition's current revision.

        An instance names the revision it was made from, and every edit is
        refused once that revision is superseded. Publishing a new Number
        therefore froze every Number already on the canvas -- and a Run
        could not land its answers either, so the graph computed values it
        had nowhere to put. Adopting is a signed act that keeps the node's
        identity and every override the new revision still declares; an
        override it dropped is refused by name and nothing is decided
        behind the founder's back.
        """
        import uuid as _uuid

        from .unified_authority import adopt_definition_revision, revise_instance

        try:
            return revise_instance(
                self.clean_authority,
                instance_root,
                changes,
                scope_root=scope_root,
                caller=self.clean_caller,
                command_id=str(_uuid.uuid4()),
            )
        except InvalidCell as exc:
            if "definition revision is no longer current" not in str(exc):
                raise
        adopt_definition_revision(
            self.clean_authority,
            instance_root,
            scope_root=scope_root,
            caller=self.clean_caller,
            command_id=str(_uuid.uuid4()),
        )
        return revise_instance(
            self.clean_authority,
            instance_root,
            changes,
            scope_root=scope_root,
            caller=self.clean_caller,
            command_id=str(_uuid.uuid4()),
        )

    def _clean_run_stem_graph(self, binding, payload):
        """Evaluate the scope's stem graph and land what it produced.

        Values flow along declared wires (data.constant to
        output.parameter and everything between), and each node that
        produced or refused a value has that answer written onto its
        instance as its status -- the card shows what Run did, and the
        write is the same signed sparse-override command the inspector
        uses. Engines this version cannot run are answered per node
        ("engine ai.master is pending"), never guessed.
        """
        import uuid as _uuid

        from .stem_graph_evaluation import (
            StemNode,
            StemWire,
            evaluate_stem_graph,
        )
        from .unified_authority import revise_instance

        stem_nodes = []
        for item in payload["nodes"]:
            engine = item.get("engine")
            if type(engine) is not str or not engine.strip():
                continue
            overrides = {
                str(row.get("label")): row.get("value")
                for row in (item.get("properties") or ())
                if isinstance(row, dict) and row.get("label")
            }
            parameters = dict(item.get("parameter_defaults") or {})
            parameters.update({
                name: value for name, value in overrides.items()
                if name in parameters
            })
            stem_nodes.append(StemNode(
                item["id"], engine.strip(), parameters
            ))
        stem_wires = []
        for wire in payload.get("wires") or ():
            properties = wire.get("properties") or {}
            source_interface = properties.get("source_interface")
            target_interface = properties.get("target_interface")
            if (
                type(source_interface) is str and source_interface
                and type(target_interface) is str and target_interface
                and type(wire.get("source")) is str
                and type(wire.get("target")) is str
            ):
                stem_wires.append(StemWire(
                    wire["source"], source_interface,
                    wire["target"], target_interface,
                ))
        evaluation = evaluate_stem_graph(
            stem_nodes, stem_wires, self._graph_held_operations()
        )
        written = 0
        stale = {}
        for item in payload["nodes"]:
            root = item["id"]
            answer = evaluation.display.get(root)
            if answer is None and root in evaluation.pending:
                answer = evaluation.pending[root]
            if answer is None:
                continue
            # The write lands on the declared status parameter; a node
            # whose definition never declared one (or predates it) has
            # nowhere to land, and skipping is the honest answer.
            if "status" not in (item.get("parameter_defaults") or {}):
                continue
            rows = {
                str(row.get("label")): row.get("value")
                for row in (item.get("properties") or ())
                if isinstance(row, dict) and row.get("label")
            }
            if rows.get("status") == answer:
                continue
            try:
                self._revise_instance_adopting(
                    root,
                    {"status": answer},
                    scope_root=self.clean_scope_root,
                )
            except InvalidCell as refusal:
                # An instance pinned to a definition revision that
                # predates the status channel has nowhere to land its
                # answer. The run still stands for every other node;
                # the refusal is carried per node, never invented away
                # and never allowed to take the whole run down.
                stale[root] = str(refusal)
                continue
            written += 1
        self._refresh_scope_interactions()
        payload = self._canvas(binding)
        payload.update({
            "ran": "stem-graph",
            "results": dict(evaluation.results),
            "pending": dict(evaluation.pending),
            "written": written,
            "stale": stale,
        })
        return payload

    def _clean_execute_focused(self, binding, body):
        """Run the operation the focused node declares.

        The node names its operation, the operation is declared in the
        graph, and the signed path decides whether it may run. Nothing
        about which operation to run comes from the request: a client that
        could name the operation could ask for one the node it points at
        never offered.
        """
        from .clean_host_execution import execute_host_operation

        payload = self._canvas(binding)
        selected = payload.get("selected")
        if type(selected) is not str or not selected:
            raise InvalidCell("no node is focused to run")
        node = next(
            (item for item in payload["nodes"] if item["id"] == selected),
            None,
        )
        operation = None if node is None else node.get("operation")
        if type(operation) is not str or not operation.strip():
            engine = None if node is None else node.get("engine")
            if type(engine) is str and engine.strip():
                return self._clean_run_stem_graph(binding, payload)
            raise InvalidCell("the focused node declares no host operation")
        command_id = body.get("command_id")
        if type(command_id) is not str or not command_id.strip():
            command_id = str(uuid.uuid4())
        result = execute_host_operation(
            self.clean_authority,
            operation.strip(),
            {},
            caller=self.clean_caller,
            command_id=command_id.strip(),
            invoker=self.clean_host_invoker,
            subject_root=selected,
        )
        # The client reconciles what a mutation returns against what it is
        # showing. Answering with the effect alone left it holding the
        # revision from before the run, so the next press was refused as
        # stale and the founder had to reload between runs. The answer is
        # the canvas as it now stands, carrying what the run produced.
        payload = self._canvas(binding)
        payload.update({
            "operation": operation.strip(),
            "node": selected,
            "effect": result.root_id,
            "receipt": result.receipt_root,
            "replayed": result.replayed,
        })
        return payload

    def _clean_execute_adapter(self, binding, body):
        """Run one operation the graph declares, and answer with its receipt.

        Nothing about which operations exist, what they need, or whether
        one may run is decided here: this route carries a request to the
        signed path and returns what that path committed. A refusal is an
        answer too, and it arrives as a refusal rather than as an empty
        success.
        """
        from .clean_host_execution import execute_host_operation

        admitted = {
            "operation", "arguments", "command_id", "allow_destructive",
            "root",
        }
        unadmitted = sorted(set(body) - admitted)
        if unadmitted:
            raise CleanGestureRefused(
                "execute request carries facts this path cannot sign: %s"
                % ", ".join(unadmitted)
            )
        # A Run control names the node it belongs to, and the node names
        # the operation. The client has always sent the root; this path
        # refused it, so pressing Run was answered with a refusal about a
        # field the client had no other way to express. Which operation
        # runs still comes from the graph, never from the request: naming
        # a node is not naming an operation.
        subject = body.get("root")
        operation = body.get("operation")
        if subject is not None:
            if type(subject) is not str or not subject.strip():
                raise InvalidCell("execute request names no node")
            payload = self._canvas(binding)
            node = next(
                (item for item in payload["nodes"]
                 if item["id"] == subject.strip()),
                None,
            )
            declared = None if node is None else node.get("operation")
            if type(declared) is not str or not declared.strip():
                raise InvalidCell("that node declares no host operation")
            if operation is not None and str(operation).strip() != declared.strip():
                raise InvalidCell(
                    "the request names an operation the node does not declare"
                )
            operation = declared
        if type(operation) is not str or not operation.strip():
            raise InvalidCell("execute request names no operation")
        arguments = body.get("arguments") or {}
        if type(arguments) is not dict:
            raise InvalidCell("execute request arguments are invalid")
        command_id = body.get("command_id")
        if type(command_id) is not str or not command_id.strip():
            raise InvalidCell("execute request carries no command identity")
        result = execute_host_operation(
            self.clean_authority,
            operation.strip(),
            arguments,
            caller=self.clean_caller,
            command_id=command_id.strip(),
            invoker=self.clean_host_invoker,
            allow_destructive=bool(body.get("allow_destructive")),
            subject_root=(
                subject.strip() if isinstance(subject, str) and subject.strip()
                else None
            ),
        )
        return {
            "operation": operation.strip(),
            "effect": result.root_id,
            "receipt": result.receipt_root,
            "revision": result.revision,
            "replayed": result.replayed,
        }

    def _clean_gesture(self, binding, body):
        """Record where the founder put a node.

        A canvas that cannot be rearranged is a picture. The client sends
        the positions it settled on after a drag; each one is written
        through the same signed command that placed the node in the first
        place, so a move is an ordinary revision with a receipt rather
        than a special path, and the projection returned afterwards is
        read back from the graph rather than echoed from the request.
        """
        from .unified_authority import place_composition
        # This path writes exactly one kind of fact: where a node sits.
        # Anything else arriving as a "gesture" -- a viewport, a lifecycle
        # change, a field edit -- has its own signed command and must go
        # through it, so an unadmitted gesture is refused before anything
        # is written rather than quietly interpreted here.
        admitted = {
            "positions",
            # Taking a card off the canvas is a signed act like every
            # other: the scope releases the member, and the wires that
            # ended on it go with it, because a wire to nothing is not
            # a wire.
            "delete",
            # A field edit in the rail is a sparse instance override --
            # the same signed revise-instance the stem runner uses. The
            # gesture only carries WHICH declared parameter of WHICH held
            # node; anything undeclared is refused by the command itself.
            "property",
            # Where the founder is looking is a graph fact too, held on the
            # view session rather than on any node. Admitting only positions
            # meant zoom and pan were refused by this server as facts it
            # could not sign -- a canvas that cannot be zoomed is a picture
            # again. It has its own signed command; this path carries it
            # there rather than interpreting it.
            "viewport",
            "roots",
            "focus",
            # Taking back the last act. It carries no facts of its own --
            # what to reverse is what this owner recorded when it signed
            # the act -- so it needs no control and no declared
            # interaction, which is what kept Undo off this canvas.
            "undo",
            "projection",
            "projection_mode",
            "projection_revision",
            "command_id",
        }
        unadmitted = sorted(set(body) - admitted)
        if unadmitted:
            raise CleanGestureRefused(
                "gesture carries facts this path cannot sign: %s"
                % ", ".join(unadmitted)
            )
        positions = body.get("positions")
        viewport = body.get("viewport")
        roots = body.get("roots")
        if body.get("undo"):
            return self._clean_undo(binding)
        removing = body.get("delete")
        if isinstance(removing, list) and removing:
            import uuid as _uuid

            from .unified_authority import (
                read_scope_level,
                remove_composition_member,
            )

            level = read_scope_level(
                self.clean_authority,
                self.clean_scope_root,
                scope_root=self.clean_scope_root,
                caller=self.clean_caller,
            )
            # A wire is a member of this scope too, and taking one off the
            # canvas was refused outright -- the founder could draw a
            # relation and then had no way to remove it. Both kinds of
            # member leave by the same signed release.
            members = set(level.composition_roots) | set(level.relations)
            visible_selection = self._held_selection(binding)
            wanted = [
                str(root) for root in removing
                if isinstance(root, str) and root in members
            ]
            if not wanted:
                raise CleanGestureRefused(
                    "nothing selected here can be taken off the canvas"
                )
            # A relation whose participant is leaving loses its meaning,
            # so it leaves in the same gesture rather than dangling.
            leaving = set(wanted)
            for relation in level.relations.values():
                participants = {
                    root for _role, root in relation.participants
                }
                if participants & leaving:
                    leaving.add(relation.root_id)
            released = []
            for root in sorted(leaving):
                if root not in members:
                    continue
                remove_composition_member(
                    self.clean_authority,
                    self.clean_scope_root,
                    root,
                    caller=self.clean_caller,
                    command_id=str(_uuid.uuid4()),
                )
                released.append(root)
            # What would reverse this. It is recorded even though the
            # graph will not yet permit the reversal: policy proves an act
            # only on a root REACHABLE within the claimed scope, and a
            # released root belongs nowhere. Folding the roots into one
            # holder first was tried -- the holder is released too, so it
            # is unreachable by exactly the same rule.
            self._undo_entry = {
                "kind": "restore-members",
                "scope": self.clean_scope_root,
                "roots": tuple(released),
                "selection": tuple(visible_selection),
            } if released else None
            # A selection is a claim about what this scope shows, and the
            # projection refuses one that names a root the scope no longer
            # holds -- rightly. Deleting the selected card therefore took
            # the WHOLE canvas down with a 403 ("active focus selection is
            # outside the projected scope") and left the node in place.
            # What was deleted leaves the selection in the same act.
            from .clean_browser_authority import revise_clean_browser_focus

            remaining = [
                root for root in visible_selection if root not in leaving
            ]
            # An empty selection is not a focus this protocol can carry --
            # a primary must be one of the selected -- so when the last
            # selected card leaves, the focus is simply left behind and
            # the projection stops honouring what the scope no longer
            # holds.
            if remaining and len(remaining) != len(visible_selection):
                revise_clean_browser_focus(
                    self.clean_authority,
                    self.clean_browser_authority,
                    binding.session_root,
                    scope_root=self.clean_scope_root,
                    selected_roots=remaining,
                    primary_root=(remaining[-1] if remaining else ""),
                    caller=self.clean_caller,
                    command_id=str(_uuid.uuid4()),
                )
            self._refresh_scope_interactions()
            return self._gesture_answer(binding, body)
        edit = body.get("property")
        if isinstance(edit, dict):
            import uuid as _uuid

            from .unified_authority import (
                adopt_definition_revision,
                read_scope_level,
                revise_instance,
            )

            owner_root = edit.get("owner")
            label = edit.get("label")
            value = edit.get("value")
            if (
                type(owner_root) is not str or not owner_root
                or type(label) is not str or not label
                or type(value) is not str
            ):
                raise CleanGestureRefused("property edit is invalid")
            standing = self._standing_scope(binding)
            self._expand_scope_interactions(standing)
            level = read_scope_level(
                self.clean_authority,
                standing,
                scope_root=standing,
                caller=self.clean_caller,
            )
            if owner_root not in set(level.composition_roots):
                # Name both, or the founder is told only that something is
                # wrong with a card they can see and select.
                raise CleanGestureRefused(
                    "property edit target %s is not held by scope %s "
                    "(members=%d first=%s)"
                    % (
                        owner_root[:12], standing[:12],
                        len(level.composition_roots),
                        ",".join(
                            root[:8] for root in level.composition_roots[:4]
                        ),
                    )
                )
            self._revise_instance_adopting(
                owner_root, {label: value}, scope_root=standing,
            )
            return self._gesture_answer(binding, body)
        if positions is None and viewport is None:
            # A selection is a view fact like the viewport: which roots the
            # founder is holding, and which is primary. The client sends it
            # through the same gesture path as every other canvas act;
            # refusing it painted an error toast on every single click.
            if isinstance(roots, list):
                import uuid as _uuid

                from .clean_browser_authority import (
                    revise_clean_browser_focus,
                )
                focus = body.get("focus")
                primary = (
                    focus if type(focus) is str and focus
                    else (roots[-1] if roots else "")
                )
                # A focus IS a selection of one. Clicking a wire sends the
                # focus alone -- the shape every surface has always used --
                # and the focus protocol requires the primary to be among
                # the selected, so an empty list refused the click.
                if primary and not roots:
                    roots = [primary]
                if not primary:
                    # An empty click clears nothing the graph holds; the
                    # projection the view already has is the answer.
                    return self._gesture_answer(binding, body, view_only=True)
                revise_clean_browser_focus(
                    self.clean_authority,
                    self.clean_browser_authority,
                    binding.session_root,
                    scope_root=self.clean_scope_root,
                    selected_roots=[str(root) for root in roots],
                    primary_root=primary,
                    caller=self.clean_caller,
                    command_id=str(_uuid.uuid4()),
                    expected_revision=self.authority.store.revision,
                )
                return self._gesture_answer(binding, body)
            raise CleanGestureRefused(
                "gesture without positions or viewport is not admitted"
            )
        if viewport is not None:
            if type(viewport) is not dict or not viewport:
                raise InvalidCell("gesture viewport must be a non-empty object")
            from .unified_authority import (
                read_view_session_state,
                revise_view_session_viewport,
            )
            import uuid as _uuid

            held = read_view_session_state(
                self.clean_authority,
                binding.view_root,
                caller=self.clean_caller,
            )
            # The tokens travel with the viewport in one signed revision, so
            # a pan cannot quietly drop the theme the view was carrying.
            revise_view_session_viewport(
                self.clean_authority,
                binding.view_root,
                viewport=dict(viewport),
                design_tokens=dict(held[1] if isinstance(held, tuple) else {}),
                session_root=binding.session_root,
                caller=self.clean_caller,
                command_id=str(_uuid.uuid4()),
            )
            if positions is None:
                return self._gesture_answer(binding, body, view_only=True)
        if type(positions) is not dict or not positions:
            raise InvalidCell("gesture positions must be a non-empty object")
        moved = 0
        for root, place in (positions or {}).items():
            if type(root) is not str or type(place) is not dict:
                raise InvalidCell("gesture position entry is invalid")
            x, y = place.get("x"), place.get("y")
            if type(x) not in (int, float) or type(y) not in (int, float):
                raise InvalidCell("gesture position is not a point")
            place_composition(
                self.clean_authority,
                self.clean_scope_root,
                root,
                {"x": int(x), "y": int(y)},
                caller=self.clean_caller,
                command_id=str(uuid.uuid4()),
            )
            moved += 1
        projection = self._gesture_answer(binding, body)
        projection["moved"] = moved
        return projection

    def _canvas_after_view_commit(self, binding, held_payload):
        """The projection after a commit that touched only this view's
        session state, from the projection the view already holds.

        Measured on a fixture across a viewport commit, the projection
        differs in exactly: viewport.*, revision, interaction_projection
        .revision, and the toolbar descriptor (its zoom text). Rebuilding
        the whole canvas -- 1.3 s on the founder's graph -- to change four
        fields is what made every pan a wait. The held projection is
        patched from the graph (the view session state is READ, the rest
        is what the graph already gave this view) and the toolbar is
        re-rendered from the same template. The court holds this equal to a
        full rebuild; anything it cannot answer from the graph falls back.
        Returns None when the reuse cannot be made exact.
        """
        try:
            from .clean_visual_authority import render_clean_visual_template
            from .clean_visual_projection import _toolbar_projection
            from .unified_authority import read_view_session_state
            snapshot = self.authority.store.snapshot()
            if held_payload.get("root") != self.clean_scope_root:
                return None
            viewport, _tokens = read_view_session_state(
                self.clean_authority,
                binding.view_root,
                caller=self.clean_caller,
                at_revision=snapshot.revision,
            )
            payload = json.loads(json.dumps(held_payload))
            payload.pop("moved", None)
            payload["viewport"] = {
                "pan_x": 0.0, "pan_y": 0.0, "zoom": 1.0,
                **dict(viewport or {}),
            }
            payload["revision"] = snapshot.revision
            payload["interaction_projection"]["revision"] = snapshot.revision
            controls = (
                payload.get("configuration", {})
                .get("design_system", {})
                .get("control_catalog", {})
                .get("controls", [])
            )
            visual = open_clean_visual_system(
                self.clean_authority, caller=self.clean_caller,
            )
            payload["toolbar_descriptor"] = render_clean_visual_template(
                self.clean_authority,
                visual,
                "canvas-toolbar",
                _toolbar_projection(payload, controls),
                caller=self.clean_caller,
            )
        except Exception:
            return None
        # Cache it as this revision's projection and lease it, exactly as a
        # built projection would be.
        lease_key = (
            id(snapshot.cells),
            snapshot.revision,
            self.clean_scope_root,
            binding.view_root,
            binding.session_root,
            None,
        )
        if len(self._clean_projection_cache) >= 4:
            self._clean_projection_cache.pop(
                next(iter(self._clean_projection_cache))
            )
        self._clean_projection_cache[lease_key] = (
            snapshot.cells, json.dumps(payload),
        )
        self._issue_projection_lease(binding, snapshot, payload)
        self._remember_view_projection(binding, payload)
        self._record_gesture_timing(
            "view-only reuse rev=%s scope=%s" % (
                snapshot.revision, self.clean_scope_root[:12],
            )
        )
        return payload

    def _remember_view_projection(self, binding, payload) -> None:
        """Keep the last full projection this view received, so the next
        gesture can be answered as a delta against it."""
        held = getattr(self, "_view_projections", None)
        if held is None:
            held = self._view_projections = {}
        held[binding.view_root] = (payload.get("revision"), payload.get("root"), payload)
        if len(held) > 16:
            held.pop(next(iter(held)))

    def _gesture_answer(self, binding, body, *, view_only=False):
        """A gesture's answer: the full projection, or -- when the client
        says which revision it holds and asks for a delta -- only what
        changed since it.

        Every pan answered with the whole canvas: 841 KB on the founder's
        graph, re-rendered by the client on every wheel notch. A viewport
        commit changes the viewport and nothing a card is drawn from; the
        delta carries the fields and the node states, and the client merges
        it onto what it holds. The delta is computed against the projection
        this server last handed THIS view -- never against a guess -- and
        falls back to the full projection when that base is not in hand.
        """
        # The base the view holds must be read BEFORE the new projection is
        # built: building it records itself as this view's latest.
        held = (getattr(self, "_view_projections", None) or {}).get(
            binding.view_root
        )
        projection = (
            self._canvas_after_view_commit(binding, held[2])
            if view_only and held is not None and held[1] == self.clean_scope_root
            else None
        )
        if projection is None:
            projection = self._canvas(binding)
        wanted = body.get("projection_mode")
        base_revision = body.get("projection_revision")
        if wanted != _INTERACTION_DELTA_MODE or type(base_revision) is not int:
            return projection
        previous = None
        if held is not None and held[0] == base_revision and held[1] == projection.get("root"):
            previous = held[2]
        if previous is None or previous is projection:
            return projection
        try:
            delta = _interaction_canvas_delta(
                {"connections": [], **projection},
                base_revision=base_revision,
                previous_projection={"connections": [], **previous},
            )
        except Exception:
            return projection
        # The clean projection also carries these per-gesture fields the
        # generic delta does not list; a pan moves the viewport.
        for field in ("viewport", "revision", "scope"):
            if field in projection:
                delta[field] = projection[field]
        # What this view now holds is the full projection just built.
        self._remember_view_projection(binding, projection)
        return delta

    def _clean_undo(self, binding):
        """Take back the last canvas act, as its inverse.

        The journal is append-only: nothing is rewound. What the scope
        released is added back by add_composition_member -- the exact
        signed inverse of the remove that released it -- and the selection
        held at the time returns with it.
        """
        import uuid as _uuid

        from .unified_authority import add_composition_member

        entry = getattr(self, "_undo_entry", None)
        if entry is None:
            raise InvalidCell("there is nothing on this canvas to undo")
        if entry["kind"] not in ("restore-members", "restore-group"):
            raise InvalidCell("this act cannot be taken back yet")
        # Policy proves an act on a root REACHABLE within the claimed
        # scope, and a released root belongs nowhere -- which is why
        # ungroup adopts before it releases. Undo cannot reorder history,
        # so it re-adopts in passes: whatever the scope will take makes
        # the next one reachable, and the loop ends when a pass adds
        # nothing. What no pass can reach is reported, not swallowed.
        pending = list(entry["roots"])
        denied = None
        while pending:
            progressed = []
            for root in list(pending):
                try:
                    add_composition_member(
                        self.clean_authority,
                        entry["scope"],
                        root,
                        caller=self.clean_caller,
                        command_id=str(_uuid.uuid4()),
                    )
                except InvalidCell as error:
                    if "already a member" in str(error):
                        progressed.append(root)
                        continue
                    denied = error
                    continue
                progressed.append(root)
            if not progressed:
                raise denied if denied is not None else InvalidCell(
                    "the scope will not take these roots back"
                )
            pending = [root for root in pending if root not in progressed]
            denied = None
        if entry["kind"] == "restore-group":
            # The holder is back in the scope; dissolving it returns every
            # card it was carrying, by the same command Ungroup uses.
            from .unified_authority import ungroup_composition
            for root in entry["roots"]:
                ungroup_composition(
                    self.clean_authority,
                    entry["scope"],
                    root,
                    caller=self.clean_caller,
                    command_id=str(_uuid.uuid4()),
                )
        held = [root for root in entry["selection"] if root]
        if held:
            from .clean_browser_authority import revise_clean_browser_focus
            revise_clean_browser_focus(
                self.clean_authority,
                self.clean_browser_authority,
                binding.session_root,
                scope_root=entry["scope"],
                selected_roots=held,
                primary_root=held[-1],
                caller=self.clean_caller,
                command_id=str(_uuid.uuid4()),
            )
        # One step deep: what was just put back is not itself undoable.
        self._undo_entry = None
        self._refresh_scope_interactions()
        return self._canvas(binding)

    def _clean_group_or_ungroup(self, binding, body, control_root):
        """Group the current selection, or dissolve the focused group.

        Which act is the control's own name -- the catalogue declares
        canvas:group and canvas:ungroup -- and what it acts ON is the
        graph-held browser focus, never a list the client sends: the
        selection the founder sees is the selection the command uses.
        """
        import uuid as _uuid

        from .clean_browser_authority import (
            active_focus, open_attention_protocol,
        )
        from .unified_authority import (
            group_compositions, place_composition, ungroup_composition,
        )

        snapshot = self.authority.store.snapshot()
        protocol = open_attention_protocol(snapshot)
        focus = active_focus(
            snapshot,
            protocol,
            session_root=binding.view_root,
        )
        selected = tuple(focus.selected_roots) if focus is not None else ()
        primary = focus.primary_root if focus is not None else None
        act = str(control_root or "")
        released = ()
        if act.endswith(":ungroup"):
            target = primary or (selected[0] if len(selected) == 1 else None)
            if not target:
                raise InvalidCell("select the group to ungroup first")
            from .cell_protocols import read_relation
            from .unified_authority import COMMAND_BUDGET
            released = tuple(
                member.participant_id
                for member in read_relation(
                    snapshot, target, budget=COMMAND_BUDGET
                )
                if member.role_id == self.clean_authority.role("composition")
            )
            ungroup_composition(
                self.clean_authority,
                self.clean_scope_root,
                target,
                caller=self.clean_caller,
                command_id=str(_uuid.uuid4()),
            )
        else:
            if len(selected) < 2:
                raise InvalidCell("select at least two nodes to group")
            created = group_compositions(
                self.clean_authority,
                self.clean_scope_root,
                selected,
                label="Group of %d" % len(selected),
                caller=self.clean_caller,
                command_id=str(_uuid.uuid4()),
            )
            place_composition(
                self.clean_authority,
                self.clean_scope_root,
                created.root_id,
                {"x": 120.0, "y": 120.0},
                caller=self.clean_caller,
                command_id=str(_uuid.uuid4()),
            )
        # The members the focus held just left the scope (into the group)
        # or the group left (dissolved). A focus over roots the scope no
        # longer shows refuses the next lease, so the selection moves to
        # what the act produced: the group, or nothing.
        from .clean_browser_authority import revise_clean_browser_focus
        follow = None if act.endswith(":ungroup") else created.root_id
        if follow:
            revise_clean_browser_focus(
                self.clean_authority,
                self.clean_browser_authority,
                binding.session_root,
                scope_root=self.clean_scope_root,
                selected_roots=[follow],
                primary_root=follow,
                caller=self.clean_caller,
                command_id=str(_uuid.uuid4()),
            )
        else:
            # No clear-focus command exists; the released members are the
            # honest selection after a dissolve.
            revise_clean_browser_focus(
                self.clean_authority,
                self.clean_browser_authority,
                binding.session_root,
                scope_root=self.clean_scope_root,
                selected_roots=list(released),
                primary_root=released[0],
                caller=self.clean_caller,
                command_id=str(_uuid.uuid4()),
            )
        self._refresh_scope_interactions()
        payload = self._canvas(binding)
        return payload

    def _clean_connect(self, binding, body):
        """Wire two placed nodes: one explicit relation between them.

        The wire is an ordinary relation node -- the same shape every
        imported Grand Map wire already has -- created by the same signed
        command, carrying which declared interface each end used. Both
        ends must be members of this scope; nothing else is admitted.
        """
        import uuid as _uuid

        from .unified_authority import create_relation_node, read_scope_level

        source = body.get("source")
        target = body.get("target")
        source_interface = body.get("source_interface")
        target_interface = body.get("target_interface")
        for value, label in (
            (source, "source"), (target, "target"),
            (source_interface, "source interface"),
            (target_interface, "target interface"),
        ):
            if type(value) is not str or not value:
                raise InvalidCell("connect %s is invalid" % label)
        if source == target:
            raise InvalidCell("a node cannot be wired to itself")
        level = read_scope_level(
            self.clean_authority,
            self.clean_scope_root,
            scope_root=self.clean_scope_root,
            caller=self.clean_caller,
        )
        members = set(level.composition_roots)
        if source not in members or target not in members:
            raise InvalidCell("connect ends must both be members of this scope")
        created = create_relation_node(
            self.clean_authority,
            (("source", source), ("target", target)),
            scope_root=self.clean_scope_root,
            caller=self.clean_caller,
            command_id=str(_uuid.uuid4()),
            properties={
                "source_interface": source_interface,
                "target_interface": target_interface,
            },
        )
        payload = self._canvas(binding)
        payload["created_wire"] = created.root_id
        return payload

    def _clean_stylesheet(self):
        """The appearance the graph holds, served once rather than per read."""
        from .clean_design_catalogue import read_design_catalogue
        catalogue = read_design_catalogue(
            self.clean_authority, caller=self.clean_caller
        )
        if catalogue is None:
            raise InvalidCell("the graph holds no design-system catalogue")
        # Every rule in the stylesheet is written in terms of --bg, --ink,
        # --accent and their siblings. Serving the rules without the values
        # is a page that loads, reports a healthy stylesheet, and paints
        # nothing: white ground, invisible wires, flat panels. A graph that
        # holds no palette must say so here rather than let the browser
        # resolve every colour to nothing.
        tokens = catalogue.get("tokens") or {}
        if not tokens:
            raise InvalidCell("the graph holds no design-system palette")
        declared = "".join(
            "--%s:%s;" % (name, value) for name, value in sorted(tokens.items())
        )
        return ":root{%s}" % declared + catalogue.get("stylesheet", "")

    def _clean_page(self):
        """Serve the page. Pure: no graph write, no session, no cookie.

        The bootstrap script reuses a session already held in ORIGIN-scoped
        storage -- unlike cookies, that is scoped to this exact port -- and
        signs in only when it has none or the one it has no longer answers.
        Reloading therefore costs the graph nothing after the first sign-in.
        """
        from .ui_runtime import UNIVERSAL_CANVAS_SCRIPT
        bootstrap = """
(async () => {
  const KEY='archhub.session.v1';
  function stored() {
    try { return JSON.parse(localStorage.getItem(KEY) || 'null'); }
    catch (error) { return null; }
  }
  function keep(value) {
    try { localStorage.setItem(KEY, JSON.stringify(value)); }
    catch (error) { /* private mode: session lives for this page only */ }
  }
  async function answers(session) {
    if (!session || !session.token) return false;
    try {
      const probe = await fetch('/api/universal/canvas', {
        headers: {
          'X-ArchHub-Session': session.token,
          'X-ArchHub-CSRF': session.csrf,
        },
      });
      return probe.ok;
    } catch (error) { return false; }
  }
  let session = stored();
  if (!await answers(session)) {
    const minted = await fetch('/api/universal/session', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-ArchHub-Sign-In': '1',
      },
      body: '{}',
    });
    if (!minted.ok) {
      document.body.dataset.archhubSignIn = 'refused';
      return;
    }
    session = await minted.json();
    keep(session);
  }
  window.__archhubSession = session;
  const meta = document.querySelector('meta[name="archhub-csrf"]');
  if (meta) meta.content = session.csrf;
  // Appearance comes from the graph like everything else. The page ships
  // only the skeleton the renderers mount on; how any of it LOOKS is a
  // graph fact, so restyling the canvas is a revision, not a deploy.
  try {
    const sheet = await fetch('/api/universal/stylesheet').then(r => r.text());
    if (sheet) {
      const style = document.createElement('style');
      style.textContent = sheet;
      document.head.append(style);
    }
  } catch (error) {
    document.body.dataset.archhubStylesheet = 'unavailable';
  }
  document.body.dataset.archhubSignIn = 'ready';
  // A script element carrying text/plain holds source, it does not run
  // it, and copying that text into a new script element is a document
  // write the browser will not execute either. Evaluating it directly is
  // what actually starts the canvas, and it runs only after a session
  // exists, which is the ordering the sign-in requires.
  (0, eval)(document.getElementById('archhub-canvas-source').text);
})();
"""
        page = (
            "<!doctype html><html><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" "
            "content=\"width=device-width,initial-scale=1\">"
            "<meta name=\"archhub-csrf\" content=\"\">"
            "<title>ArchHub</title>"
            "<link rel=\"preconnect\" href=\"https://fonts.googleapis.com\">"
            "<link rel=\"preconnect\" href=\"https://fonts.gstatic.com\" crossorigin>"
            "<link href=\"https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700"
            "&family=JetBrains+Mono:wght@400;500;600&family=Instrument+Serif:ital@0;1"
            "&family=Architects+Daughter&display=swap\" rel=\"stylesheet\">"
            # The skeleton is not a design. It is exactly the structure the
            # graph-held stylesheet declares -- .archhub-app's two columns,
            # the sidebar's rail and library, the workspace's header, canvas
            # and inspector -- so that CSS lands on the boxes it was written
            # for. An invented shell fights its own stylesheet: the first
            # one here nested the rail beside the sidebar and the canvas
            # measured zero pixels wide.
            "<style>html,body{margin:0;height:100%%}</style>"
            "</head><body>"
            "<div class=\"archhub-app\">"
            "<aside class=\"sidebar\">"
            "<nav class=\"icon-rail\"></nav>"
            "<div class=\"library-panel\"></div>"
            "</aside>"
            "<main class=\"workspace\">"
            "<header class=\"workspace-header\"></header>"
            "<div class=\"canvas\" data-pan-surface=\"true\">"
            "<div class=\"canvas-stage\"></div>"
            "<div class=\"canvas-toolbar\"></div>"
            "</div>"
            "<aside class=\"inspector\"></aside>"
            "</main>"
            # Every refusal a governed control raises is written here.
            # Without the element the client's own status call returns at
            # its first line, so a control that was refused looks exactly
            # like a control that did nothing -- which is how a Run button
            # can be pressed all day and never say why it will not run.
            "<footer class=\"status-strip\">"
            "<span class=\"status-message\" hidden></span>"
            "</footer>"
            "</div>"
            "<script type=\"text/plain\" id=\"archhub-canvas-source\">"
            "%s</script>"
            "<script>%s</script></body></html>"
        ) % (UNIVERSAL_CANVAS_SCRIPT, bootstrap)
        return page

    @property
    def url(self) -> str:
        host, port = self.httpd.server_address[:2]
        return "http://%s:%d" % (host, port)

    def start(self):
        if self.thread is None:
            self.thread = threading.Thread(
                target=self.httpd.serve_forever,
                name="archhub-clean-browser-server",
                daemon=True,
            )
            self.thread.start()
        return self

    def close(self):
        if self.thread is not None:
            self.httpd.shutdown()
            self.httpd.server_close()
            self.thread.join(timeout=5.0)
            self.thread = None

    def _resolve_binding(
        self,
        token: str,
        *,
        csrf_token: str | None = None,
        require_csrf: bool = False,
    ) -> _CleanBrowserSessionBinding:
        if type(token) is not str or not token:
            raise AuthorizationDenied("authenticated browser session required")
        snapshot = self.authority.store.snapshot()
        verify_exact_authority_head(self.authority, snapshot)
        expected_digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        matches = []
        # Every request used to read every browser session ever issued and
        # compare digests one at a time -- a linear scan that grows with the
        # graph forever, and the reason an authenticated request cost more
        # than the drawing it authorised. The digest identifies the session,
        # so it is looked up. The index is rebuilt whenever the graph moves,
        # and holds the mapping it keys on so a recycled address can never
        # answer for a graph that no longer exists.
        index_key = (id(snapshot.cells), snapshot.revision)
        held = self._session_index
        if held is None or held[0] != index_key or held[1] is not snapshot.cells:
            built: dict[str, list[str]] = {}
            for session_root in list_browser_session_roots(
                snapshot, self.browser_authority.protocol
            ):
                candidate = read_browser_session(
                    snapshot, self.browser_authority.protocol, session_root
                )
                try:
                    digest = snapshot.cells[
                        candidate.token_digest_root
                    ].atom.decode("utf-8")
                except (KeyError, UnicodeDecodeError):
                    continue
                built.setdefault(digest, []).append(session_root)
            self._session_index = (index_key, snapshot.cells, built)
            held = self._session_index
        for session_root in held[2].get(expected_digest, ()):
            session = read_browser_session(
                snapshot, self.browser_authority.protocol, session_root
            )
            try:
                stored_digest = snapshot.cells[
                    session.token_digest_root
                ].atom.decode("utf-8")
            except (KeyError, UnicodeDecodeError) as exc:
                raise AuthorizationDenied(
                    "browser credential digest is unreadable"
                ) from exc
            if not secrets.compare_digest(expected_digest, stored_digest):
                continue
            try:
                session = verify_clean_browser_session(
                    self.authority,
                    self.browser_authority,
                    session_root,
                    token=token,
                    csrf_token=csrf_token,
                    require_csrf=require_csrf,
                )
            except (BrowserSessionDenied, InvalidCell) as exc:
                raise AuthorizationDenied(str(exc))
            matches.append(session)
        if len(matches) != 1:
            raise AuthorizationDenied("browser session is unknown")
        session = matches[0]
        expected = (
            self.authority.manifest.principal_root,
            self.authority.manifest.bootstrap_session_root,
            self.authority.manifest.application_root,
            self.browser_authority.root_id,
        )
        actual = (
            session.subject_root,
            session.view_root,
            session.tenant_root,
            session.assurance_root,
        )
        if actual != expected:
            if session.subject_root != expected[0]:
                raise AuthorizationDenied("browser session subject drifted")
            raise AuthorizationDenied("browser session authority drifted")
        return _CleanBrowserSessionBinding(
            session.root_id,
            session.subject_root,
            session.view_root,
            session.tenant_root,
            session.assurance_root,
        )

    # One canvas read walks the same relations many times over -- the
    # Interface composition alone is read by the browser authority, the
    # visual system, the interaction set and the placements, and it now
    # carries a member for every node ever placed. The reuse scope makes
    # those repeats free within a single request and expires with it, so
    # nothing is remembered across a revision.
    @with_relation_projection_scope
    def _canvas(
        self,
        binding: _CleanBrowserSessionBinding,
        *,
        scope_root: str | None = None,
        at_revision: int | None = None,
    ) -> dict[str, object]:
        root_id = self.clean_scope_root if scope_root is None else scope_root
        snapshot = self.authority.store.snapshot()
        if type(root_id) is not str or root_id not in snapshot.cells:
            raise AuthorizationDenied("clean scope root is invalid")
        # A projection is a function of the graph, the scope and the view.
        # Drawing fifteen nodes walks three thousand relations, so reading
        # the same unchanged revision twice paid that twice. The result is
        # kept per revision; any write moves the revision and the next read
        # rebuilds, so a reader after a writer never sees the old graph.
        lease_key = (
            id(snapshot.cells),
            snapshot.revision,
            root_id,
            binding.view_root,
            binding.session_root,
            at_revision,
        )
        held = self._clean_projection_cache.get(lease_key)
        if held is not None:
            cells, cached = held
            if cells is snapshot.cells:
                # The cached projection is plain JSON data, and a fresh copy
                # of it is cheaper to parse than to deep-copy: the lease is
                # stamped into what the caller receives, so the cached value
                # must never be the object handed out.
                import time as _time
                _c0 = _time.perf_counter()
                payload = json.loads(cached)
                _c1 = _time.perf_counter()
                self._issue_projection_lease(binding, snapshot, payload)
                self._remember_view_projection(binding, payload)
                _c2 = _time.perf_counter()
                self._record_gesture_timing(
                    "cached projection rev=%s parse=%.3fs lease=%.3fs"
                    % (snapshot.revision, _c1 - _c0, _c2 - _c1)
                )
                return payload
        # SPEC 11.14 puts numbers on gestures; the owner records what one
        # projection actually cost, phase by phase, so the number a court
        # judges is measured here rather than guessed from outside.
        import time as _time
        _t0 = _time.perf_counter()
        # Standing in a scope is what makes its controls needed, so this is
        # where a scope entered for the first time is derived.
        self._expand_scope_interactions(root_id)
        _e1 = _time.perf_counter()
        # One statement warms this scope's region; without it the first
        # projection after a start pays a round trip per cell.
        warm = getattr(self.authority.store.snapshot().cells, "prefetch_region", None)
        if warm is not None:
            warm(root_id)
        _e2 = _time.perf_counter()
        self._record_gesture_timing(
            "scope entry expand=%.3fs warm=%.3fs" % (_e1 - _t0, _e2 - _e1)
        )
        lens = scope_lens_payload(
            project_unified_scope(
                self.clean_authority,
                root_id,
                caller=self.clean_caller,
                view_root=binding.view_root,
                at_revision=at_revision,
            )
        )
        _t1 = _time.perf_counter()
        visual = open_clean_visual_system(
            self.clean_authority,
            caller=self.clean_caller,
        )
        _t2 = _time.perf_counter()
        payload = project_clean_visual_canvas(
            self.clean_authority,
            visual,
            lens,
            caller=self.clean_caller,
            session_root=binding.session_root,
            subject_root=binding.subject_root,
            interactions=self.clean_scope_interactions,
            door_root=self.clean_scope_root,
            # getattr, not attribute access: this projection is built on
            # more than one owner shape, and an AttributeError here is
            # swallowed by the reuse path's except and retried forever.
            can_undo=getattr(self, "_undo_entry", None) is not None,
            door_label=self._door_label(snapshot),
        )
        _t3 = _time.perf_counter()
        from .unified_application_lens import (
            LAST_LENS_PHASES, LENS_RELATION_DETAIL,
        )
        self._record_gesture_timing(
            "lens phases " + " ".join(
                "%s=%.3fs" % (name, cost)
                for name, cost in sorted(LAST_LENS_PHASES.items())
            )
        )
        if LENS_RELATION_DETAIL:
            self._record_gesture_timing(
                "lens relations read=%.3fs interface=%.3fs over %d relations"
                % (
                    LENS_RELATION_DETAIL.get("relations-read", 0.0),
                    LENS_RELATION_DETAIL.get("relations-interface", 0.0),
                    int(LENS_RELATION_DETAIL.get("relations-count", 0.0)),
                )
            )
        self._record_gesture_timing(
            "projection rev=%s scope=%s lens=%.3fs visual-open=%.3fs "
            "canvas=%.3fs nodes=%s"
            % (
                snapshot.revision, root_id[:12], _t1 - _t0, _t2 - _t1,
                _t3 - _t2, len(payload.get("nodes", ())),
            )
        )
        if len(self._clean_projection_cache) >= 4:
            self._clean_projection_cache.pop(
                next(iter(self._clean_projection_cache))
            )
        self._clean_projection_cache[lease_key] = (
            snapshot.cells,
            json.dumps(payload),
        )
        _l0 = _time.perf_counter()
        self._issue_projection_lease(binding, snapshot, payload)
        self._remember_view_projection(binding, payload)
        self._record_gesture_timing(
            "lease rev=%s issue=%.3fs" % (snapshot.revision, _time.perf_counter() - _l0)
        )
        return payload

    def _projection_handle(
        self,
        binding: _CleanBrowserSessionBinding,
        snapshot,
    ) -> object:
        handle = self._clean_projection_handles.get(binding.session_root)
        if handle is None:
            handle = self.clean_interaction_broker.mint(
                snapshot,
                session_root=binding.session_root,
                subject_root=binding.subject_root,
                view_root=binding.view_root,
            )
            self._clean_projection_handles[binding.session_root] = handle
        return handle

    def _expand_scope_interactions(self, scope_root: str) -> None:
        """Derive the interactions of a scope the founder has just entered.

        Standing in a scope is what makes its controls needed. Deriving it
        on entry costs that scope's own bindings; deriving every scope at
        start cost the whole tree to serve one screen.
        """
        held = self.clean_scope_interactions
        if not scope_root or (held is not None and scope_root in held.bindings):
            return
        if scope_root in self._derived_scope_roots:
            return
        roots = self._derived_scope_roots + (scope_root,)
        try:
            derived, derived_cells = derive_clean_scope_interactions(
                self.clean_authority,
                self.clean_browser_authority,
                self.clean_scope_root,
                caller=self.clean_caller,
                roots=roots,
                depth=1,
            )
        except InvalidCell:
            return
        self._derived_scope_roots = roots
        self._interactions_are_installed = False
        self.clean_scope_interactions = derived
        self._derived_interaction_cells = derived_cells
        self._interaction_snapshot_cache = None
        self._derived_overlay_parts = None
        self._interaction_scope_index = None
        self._verified_interaction_reads = {}
        self._clean_projection_cache.clear()

    def _held_selection(self, binding) -> list[str]:
        """What this view says it is holding, as the graph records it."""
        from .cell_attention import active_focus, open_attention_protocol

        try:
            snapshot = self.clean_authority.store.snapshot()
            protocol = open_attention_protocol(snapshot)
            focus = active_focus(
                snapshot, protocol, session_root=binding.view_root
            )
        except Exception:
            return []
        if focus is None:
            return []
        return [str(root) for root in focus.selected_roots]

    def _standing_scope(self, binding) -> str:
        """The scope the founder is STANDING in, not the one they entered by.

        A gesture is taken where the founder is looking. Every act here
        was checked against the door instead, so editing a property from
        inside any domain was refused -- "property edit target is not
        held by this scope" -- for a card the founder could see, select
        and read. The view's own focus records the scope it was taken in;
        that is the answer, and the door is the answer when there is no
        focus yet.
        """
        from .cell_attention import active_focus, open_attention_protocol

        try:
            snapshot = self.clean_authority.store.snapshot()
            protocol = open_attention_protocol(snapshot)
            focus = active_focus(
                snapshot, protocol, session_root=binding.view_root
            )
        except Exception:
            return self.clean_scope_root
        scope = getattr(focus, "scope_root", None) if focus is not None else None
        if type(scope) is str and scope and scope in snapshot.cells:
            return scope
        return self.clean_scope_root

    def _scope_interaction_bindings(
        self,
        scope_root: str,
    ) -> list[dict[str, object]]:
        """Name the installed interactions reachable from one scope.

        The interaction authority is graph-held, so it is read directly rather
        than recovered from a rendered canvas.
        """
        installed = self.clean_scope_interactions
        return [
            {
                "interaction": item.interaction_root,
                "control": item.control_root,
                "event": installed.event_root,
            }
            for item in installed.bindings.get(scope_root, {}).values()
        ]

    def _issue_scope_lease(
        self,
        binding: _CleanBrowserSessionBinding,
        snapshot,
        scope_root: str,
    ) -> None:
        self._issue_projection_lease(
            binding,
            snapshot,
            {
                "interaction_projection": {
                    "bindings": self._scope_interaction_bindings(scope_root),
                },
            },
        )

    def _refresh_scope_interactions(self) -> None:
        """Re-derive the interaction set after the scope tree changed.

        The set is derived at start and served as a process constant; a
        group created mid-session had a card but no scope-open binding --
        it could not be entered until a restart. A composition-changing
        act calls this: same derivation, swapped atomically, memos keyed
        on the old cells fall away with it.
        """
        try:
            derived, derived_cells = derive_clean_scope_interactions(
                self.clean_authority,
                self.clean_browser_authority,
                self.clean_scope_root,
                caller=self.clean_caller,
                roots=self._derived_scope_roots,
                depth=1,
            )
        except InvalidCell:
            return
        held = self.clean_scope_interactions
        if held is not None and held.source_digest == derived.source_digest:
            return
        self._interactions_are_installed = False
        self.clean_scope_interactions = derived
        self._derived_interaction_cells = derived_cells
        self._interaction_snapshot_cache = None
        self._derived_overlay_parts = None
        self._interaction_scope_index = None
        self._verified_interaction_reads = {}
        self._clean_projection_cache.clear()

    def _scope_of_interaction(self, interaction_root: str) -> str:
        """The scope a derived interaction is taken from; the door if unknown."""
        held = self.clean_scope_interactions
        if held is not None:
            index = getattr(self, "_interaction_scope_index", None)
            if index is None or index[0] is not held:
                index = (held, {
                    item.interaction_root: scope
                    for scope, controls in held.bindings.items()
                    for item in controls.values()
                })
                self._interaction_scope_index = index
            scope = index[1].get(interaction_root)
            if scope is not None:
                return scope
        return self.clean_scope_root

    def _door_label(self, snapshot) -> str | None:
        """The name of the scope the canvas opens on, read as a card would."""
        held = getattr(self, "_door_label_cache", None)
        if held is not None and held[0] is snapshot.cells:
            return held[1]
        try:
            from .unified_application_lens import _scope_title
            from .unified_authority import _optional_label
            label = _scope_title(
                self.clean_authority,
                snapshot,
                self.clean_scope_root,
                _optional_label(self.clean_authority, snapshot, self.clean_scope_root),
                self.clean_caller,
            )
        except Exception:
            label = None
        self._door_label_cache = (snapshot.cells, label)
        return label

    def _record_gesture_timing(self, line: str) -> None:
        """Append one measured line to gesture-timing.log beside boot-timing.log."""
        try:
            import os as _os
            from pathlib import Path as _Path
            root = _Path(_os.environ.get("LOCALAPPDATA", ""))
            root = root / "ArchHub" / "unified-authority"
            if not root.is_dir():
                return
            import time as _time
            with (root / "gesture-timing.log").open("a", encoding="utf-8") as log:
                log.write(_time.strftime("%Y-%m-%d %H:%M:%S") + "  " + line + chr(10))
        except Exception:
            pass

    def _interaction_read_set_unchanged(self, seen_revision, current_revision):
        """Did anything a scope interaction reads change between two heads?

        The read set of a scope-open interaction is the scope tree and the
        published catalogue -- exactly what the derivation's source digest
        summarises. Same digest at both revisions means every binding the
        client acted on still holds, and the request may rebase. Anything
        else -- including any error while looking -- refuses, and the client
        re-projects: fail closed.
        """
        try:
            from .clean_scope_interactions import derive_clean_scope_interactions
            held = self.clean_scope_interactions
            if held is None:
                return False
            if seen_revision > current_revision:
                return False
            # The derivation reads the CURRENT snapshot; the client's view
            # was projected from an installed set whose source digest we
            # remember on the interactions object. Equal digests = same
            # scope tree + catalogue = same read set.
            snapshot = self.clean_authority.store.snapshot()
            cache = getattr(self, "_read_set_digest_cache", None)
            if cache is not None and cache[0] is snapshot.cells:
                fresh_digest = cache[1]
            elif getattr(self, "_interactions_are_installed", False):
                fresh_digest = clean_scope_source_digest(
                    self.clean_authority,
                    self.clean_scope_root,
                    caller=self.clean_caller,
                )
            else:
                fresh, _cells = derive_clean_scope_interactions(
                    self.clean_authority,
                    self.clean_browser_authority,
                    self.clean_scope_root,
                    caller=self.clean_caller,
                    roots=self._derived_scope_roots,
                    depth=1,
                )
                fresh_digest = fresh.source_digest
                self._read_set_digest_cache = (snapshot.cells, fresh_digest)
            return fresh_digest == held.source_digest
        except Exception:
            return False

    def _interaction_snapshot(self, snapshot):
        """The snapshot every interaction READ runs against.

        Bindings come from the derivation; the interaction cells that
        derivation names exist nowhere on disk once the table is retired.
        A reader handed the bare graph snapshot asks for a relation root
        the graph does not hold and refuses the whole projection. The
        derived cells are overlaid for reads only -- never committed -- so
        the law stays visible (SPEC 4.1: the rule is graph-held, its
        expansion is a read) and the graph stays small.
        """
        cells = getattr(self, "_derived_interaction_cells", ())
        if not cells:
            return snapshot
        cached = getattr(self, "_interaction_snapshot_cache", None)
        # Keyed on the MAPPING the snapshot carries, not the Snapshot
        # object: the store hands out a fresh Snapshot per call over the
        # same mapping while nothing commits, and keying on the object
        # rebuilt this overlay -- and cold-started every proof memo keyed
        # on it downstream -- on every request. Measured: a cached canvas
        # answered in 7.8 s while its projection took 0.05 s.
        if (
            cached is not None
            and cached[0] is snapshot.cells
            and cached[2] == snapshot.revision
        ):
            return cached[1]
        from types import MappingProxyType as _Proxy
        from .universal_cell import Snapshot, _BoundedCandidateCellMap
        # 826,233 derived cells on the founder's graph (310 scopes). Folding
        # them into a fresh persistent trie on every revision cost 4-7 s
        # per gesture -- the lease, not the projection, was the wall. The
        # delta is a process constant: it is built once, and the overlay
        # stacks it over whatever mapping the store holds now, O(1) per
        # revision. The split between "new to the graph" and "replacing a
        # graph cell" is recomputed only when a commit touches one of the
        # derived ids (the store reports every touched id).
        held = getattr(self, "_derived_overlay_parts", None)
        if held is None or held[0] is not cells:
            delta = _Proxy({cell.id: cell for cell in cells})
            held = [cells, delta, frozenset(delta), None]
            self._derived_overlay_parts = held
            store = self.clean_authority.store

            def _on_commit(event, _held=held):
                if event.touched & _held[2]:
                    _held[3] = None
            try:
                store.subscribe(_on_commit)
            except Exception:
                pass
        delta = held[1]
        if held[3] is None:
            held[3] = sum(1 for key in delta if key not in snapshot.cells)
        overlaid = Snapshot(
            snapshot.revision,
            _BoundedCandidateCellMap._from_parts(snapshot.cells, delta, held[3]),
        )
        self._interaction_snapshot_cache = (
            snapshot.cells, overlaid, snapshot.revision,
        )
        return overlaid

    def _issue_projection_lease(
        self,
        binding: _CleanBrowserSessionBinding,
        snapshot,
        payload: Mapping[str, object],
    ) -> None:
        bindings = payload["interaction_projection"]["bindings"]
        if not bindings:
            return
        snapshot = self._interaction_snapshot(snapshot)
        handle = self._projection_handle(binding, snapshot)
        protocol = self.clean_scope_interactions.protocol
        interaction_roots = tuple(item["interaction"] for item in bindings)
        # Reading and verifying the leased interactions is a function of
        # the interaction cells (process constants: derived once at boot,
        # or the installed table) and the protocol they conform to. Doing
        # it again for every revision cost 8-10 s per gesture on the
        # founder's graph -- the reads walk a fresh overlay whose proof
        # memos are cold. The reads are kept per (protocol identity, the
        # protocol's reachable-cell fingerprint -- which the store drops
        # the moment a commit touches any of those cells -- and the exact
        # interaction set); the lease itself is still minted per revision
        # and every per-snapshot check in the broker still runs.
        # A protocol the graph holds is gated by its reachable-cell
        # fingerprint (dropped by the store the moment a commit touches
        # any of those cells). A protocol that exists only in the derived
        # overlay -- the live graph, table retired -- is a process constant
        # already keyed by the identity of the derived cells below.
        store = self.clean_authority.store
        protocol_gate = (
            store.fingerprint(protocol.root_id)
            if protocol.root_id in store.snapshot().cells
            else "derived"
        )
        read_key = (
            protocol.root_id,
            protocol_gate,
            interaction_roots,
            id(getattr(self, "_derived_interaction_cells", ())),
        )
        memo = getattr(self, "_verified_interaction_reads", None)
        if memo is None:
            memo = self._verified_interaction_reads = {}
        projected = memo.get(read_key)
        if projected is None:
            from .cell_interactions import (
                _read_interactions_with_verified_protocol,
            )
            projected = _read_interactions_with_verified_protocol(
                snapshot, protocol, interaction_roots,
            )
            if len(memo) >= 16:
                memo.pop(next(iter(memo)))
            memo[read_key] = projected
        # Scope entry is a graph-held capability rather than a transaction
        # step, so the transaction and rule vocabularies are not consulted
        # for it. Admitting the exact capability keeps that explicit.
        self.clean_interaction_broker.issue_with_interactions(
            handle,
            snapshot,
            protocol,
            [item["control"] for item in bindings],
            list(interaction_roots),
            projected_interactions=projected,
            rule_protocol=None,
            transaction_protocol=None,
            # Running a declared operation is the second capability a scope
            # affords. Admitting only scope-entry meant the Run interaction
            # was leased as nothing at all.
            admitted_nontransaction_action_roots=(
                CAPABILITY_SCOPE, CAPABILITY_EXECUTE, CAPABILITY_INSTANTIATE,
                CAPABILITY_COMPOSITION,
            ),
        )

    def _make_handler(self):
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                return

            def _json(self, status: int, payload: Mapping[str, object]):
                raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
                # A canvas answer is three quarters of a megabyte of highly
                # repetitive JSON -- the same keys, the same shapes, once per
                # node and once per port -- and it was going over the wire
                # whole. Compressing it changes no fact the caller receives,
                # only how many bytes carry them, and every browser asks for
                # it. Small answers are left alone: framing them costs more
                # than it saves.
                encoding = None
                if len(raw) >= 2048:
                    accepted = (self.headers.get("Accept-Encoding") or "")
                    if "gzip" in accepted.lower():
                        import gzip as _gzip
                        compressed = _gzip.compress(raw, 6)
                        if len(compressed) < len(raw):
                            raw = compressed
                            encoding = "gzip"
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                if encoding is not None:
                    self.send_header("Content-Encoding", encoding)
                    # A cache keyed on the URL alone would hand a compressed
                    # answer to a caller that cannot read one.
                    self.send_header("Vary", "Accept-Encoding")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def _token(self) -> str:
                # Header only, deliberately. A cookie would be ambient
                # authority -- any request carrying it authenticates itself
                # -- and cookies are NOT port-scoped, so every other
                # loopback service on this host shares the jar and could
                # both read the token and set one of its own. The browser
                # keeps its session in origin-scoped storage and sends it
                # here explicitly.
                token = self.headers.get("X-ArchHub-Session", "")
                if type(token) is not str:
                    return ""
                return token.strip()

            def _csrf(self) -> str | None:
                token = self.headers.get("X-ArchHub-CSRF")
                if token is None:
                    return None
                if type(token) is not str:
                    return ""
                return token.strip()

            def _body(self) -> dict[str, object]:
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0:
                    return {}
                raw = self.rfile.read(length)
                try:
                    body = json.loads(raw.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise InvalidCell("request body is invalid JSON") from exc
                if type(body) is not dict:
                    raise InvalidCell("request body must be an object")
                return body

            def do_GET(self):
                if self.path == "/api/universal/browser-handoff":
                    self._json(403, {
                        "ok": False,
                        "error": "clean browser session is required",
                    })
                    return
                if self.path == "/api/universal/stylesheet":
                    # Appearance changes with a revision, not with a read.
                    # Shipping it inside every canvas projection put forty
                    # kilobytes on the wire for each open and rebuilt it
                    # every time.
                    try:
                        sheet = owner._clean_stylesheet()
                    except Exception as exc:  # noqa: BLE001
                        self._json(500, {"ok": False, "error": str(exc)})
                        return
                    body = sheet.encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "text/css; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                if self.path in ("/", "/index.html"):
                    # Pure. A safe method must not write: any local page
                    # could force a signed graph command with an <img> tag,
                    # and every reload would mint another session in an
                    # append-only graph. The page carries the bootstrap
                    # script; signing in is an explicit POST.
                    body = owner._clean_page().encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type",
                                     "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
                    self.wfile.write(body)
                    return
                if self.path != "/api/universal/canvas":
                    self._json(404, {"ok": False, "error": "not found"})
                    return
                try:
                    import time as _time
                    _r0 = _time.perf_counter()
                    binding = owner._resolve_binding(self._token())
                    _r1 = _time.perf_counter()
                    payload = owner._canvas(binding)
                    _r2 = _time.perf_counter()
                    owner._record_gesture_timing(
                        "GET canvas rev=%s bind=%.3fs canvas=%.3fs"
                        % (payload.get("revision"), _r1 - _r0, _r2 - _r1)
                    )
                except Conflict as exc:
                    self._json(409, {"ok": False, "error": str(exc)})
                    return
                except (
                    AuthorizationDenied,
                    InteractionProjectionDenied,
                    InvalidCell,
                ) as exc:
                    import traceback as _tb
                    owner._record_gesture_timing(
                        "canvas 403: " + str(exc) + " | " + " <- ".join(
                            "%s:%s" % (frame.name, frame.lineno)
                            for frame in _tb.extract_tb(exc.__traceback__)[-6:]
                        )
                    )
                    self._json(403, {"ok": False, "error": str(exc)})
                    return
                except Exception as exc:  # noqa: BLE001
                    # A refusal is an answer. An unanswered socket is a denial
                    # of service, so every escape becomes an honest status.
                    self._json(500, {"ok": False, "error": str(exc)})
                    return
                self._json(200, {"ok": True, **payload})

            def do_POST(self):
                try:
                    body = self._body()
                    csrf_token = self._csrf()
                    if self.path == "/api/universal/gesture":
                        try:
                            with owner._mutation_lock:
                                binding = owner._resolve_binding(
                                    self._token(),
                                    csrf_token=csrf_token,
                                    require_csrf=True,
                                )
                                payload = owner._clean_gesture(binding, body)
                        except CleanGestureRefused as exc:
                            self._json(403, {"ok": False, "error": str(exc)})
                            return
                        self._json(200, {"ok": True, **payload})
                        return
                    if self.path == "/api/universal/connect":
                        with owner._mutation_lock:
                            binding = owner._resolve_binding(
                                self._token(),
                                csrf_token=csrf_token,
                                require_csrf=True,
                            )
                            payload = owner._clean_connect(binding, body)
                        self._json(200, {"ok": True, **payload})
                        return
                    if self.path == "/api/universal/execute-adapter":
                        with owner._mutation_lock:
                            binding = owner._resolve_binding(
                                self._token(),
                                csrf_token=csrf_token,
                                require_csrf=True,
                            )
                            payload = owner._clean_execute_adapter(
                                binding, body
                            )
                        self._json(200, {"ok": True, **payload})
                        return
                    if self.path == "/api/universal/focus":
                        with owner._mutation_lock:
                            binding = owner._resolve_binding(
                                self._token(),
                                csrf_token=csrf_token,
                                require_csrf=True,
                            )
                            scope_root = body.get("scope_root", owner.clean_scope_root)
                            if type(scope_root) is not str or not scope_root:
                                raise InvalidCell("focus scope root is invalid")
                            selected_roots = body.get("selected_roots")
                            if type(selected_roots) is not list:
                                raise InvalidCell("focus selection must be a list")
                            primary_root = body.get("primary_root")
                            if type(primary_root) is not str or not primary_root:
                                raise InvalidCell("focus primary root is invalid")
                            revision = body.get("revision")
                            if type(revision) is not int:
                                raise InvalidCell("focus request revision is invalid")
                            command_id = body.get("command_id")
                            if type(command_id) is not str or not command_id:
                                raise InvalidCell("focus command id is invalid")
                            result = revise_clean_browser_focus(
                                owner.clean_authority,
                                owner.clean_browser_authority,
                                binding.session_root,
                                scope_root=scope_root,
                                selected_roots=selected_roots,
                                primary_root=primary_root,
                                caller=owner.clean_caller,
                                command_id=command_id,
                                expected_revision=revision,
                            )
                            payload = owner._canvas(
                                binding,
                                scope_root=scope_root,
                                at_revision=result.revision,
                            )
                        self._json(200, {
                            "ok": True,
                            **payload,
                            "accepted_revision": result.revision,
                            "receipt": result.receipt_root,
                            "replayed": result.replayed,
                            "focus_root": result.root_id,
                        })
                        return
                    if self.path == "/api/universal/interaction":
                        with owner._mutation_lock:
                            # A control does what the graph says it does.
                            # Execute is not a scope-open, and answering it
                            # with one would open a scope the founder never
                            # asked for instead of running what was pressed.
                            probe = owner._resolve_binding(
                                self._token(),
                                csrf_token=csrf_token,
                                require_csrf=True,
                            )
                            capability = owner._clean_control_capability(
                                body.get("control")
                            )
                            if capability == CAPABILITY_EXECUTE:
                                payload = owner._clean_execute_focused(
                                    probe, body
                                )
                                self._json(200, {"ok": True, **payload})
                                return
                            if capability == CAPABILITY_INSTANTIATE:
                                payload = owner._clean_instantiate_definition(
                                    probe, body, body.get("control")
                                )
                                self._json(200, {"ok": True, **payload})
                                return
                            if capability == CAPABILITY_COMPOSITION:
                                payload = owner._clean_group_or_ungroup(
                                    probe, body, body.get("control")
                                )
                                self._json(200, {"ok": True, **payload})
                                return
                            if capability == CAPABILITY_HISTORY:
                                payload = owner._clean_undo(probe)
                                self._json(200, {"ok": True, **payload})
                                return
                            binding = owner._resolve_binding(
                                self._token(),
                                csrf_token=csrf_token,
                                require_csrf=True,
                            )
                            revision = body.get("revision")
                            if type(revision) is not int:
                                raise InvalidCell(
                                    "interaction request revision is invalid"
                                )
                            # One snapshot for the gate, the lease and the
                            # submit. Reading the head, then snapshotting
                            # later, let another client's commit land in
                            # between: the request rebased onto 916, the
                            # lease was minted at 917, and the submit refused
                            # its own rebase ("expected 916, projected 917").
                            snapshot = owner.authority.store.snapshot()
                            current = snapshot.revision
                            if revision != current:
                                # The client's revision is the head it last
                                # SAW. Refusing every click because the graph
                                # moved anywhere at all -- a viewport pan, a
                                # session mint -- is a global lock, not
                                # conflict detection (SPEC 8: conflicts are
                                # about what changed). A scope-open interaction
                                # reads the scope tree and the catalogue; if
                                # neither moved since the client's revision,
                                # the request rebases onto the current head.
                                # If they did move, the refusal stands and the
                                # client re-projects.
                                if owner._interaction_read_set_unchanged(
                                    revision, current
                                ):
                                    revision = current
                                else:
                                    # Same recovery as an expired lease:
                                    # the client re-projects once and
                                    # retries against the head it now sees.
                                    self._json(409, {
                                        "ok": False,
                                        "error": "expected revision %s, current revision is %s"
                                        % (revision, current),
                                        "code": "projection_lease_expired",
                                    })
                                    return
                            interaction_root = body.get("interaction")
                            control_root = body.get("control")
                            event_root = body.get("event")
                            for value, label in (
                                (interaction_root, "interaction"),
                                (control_root, "control"),
                                (event_root, "event"),
                            ):
                                if type(value) is not str or not value:
                                    raise InvalidCell(
                                        "scope interaction %s is invalid" % label
                                    )
                            # The scope this interaction is taken FROM is a
                            # fact of the interaction itself (its first
                            # input), not always the door: a click inside an
                            # entered domain -- the way back, a nested open --
                            # belongs to that domain's interaction set. Leasing
                            # the door's set for it refused every such click
                            # as "not admitted for the projected control".
                            scope_root = owner._scope_of_interaction(
                                interaction_root
                            )
                            # Renew the interaction lease from the graph-held
                            # interaction set. Rebuilding the whole visual
                            # canvas to recover one scope identity would cost
                            # a second full projection for no added authority.
                            owner._issue_scope_lease(
                                binding,
                                snapshot,
                                scope_root,
                            )
                            result = submit_clean_scope_interaction(
                                owner.clean_authority,
                                owner.clean_browser_authority,
                                owner.clean_scope_interactions,
                                owner.clean_interaction_broker,
                                owner._projection_handle(binding, snapshot),
                                binding.session_root,
                                interaction_root=interaction_root,
                                control_root=control_root,
                                event_root=event_root,
                                expected_revision=revision,
                                projected_canvas={"root": scope_root},
                                caller=owner.clean_caller,
                                read_snapshot=owner._interaction_snapshot(
                                    snapshot
                                ),
                            )
                            payload = owner._canvas(
                                binding,
                                scope_root=result.root_id,
                                at_revision=result.revision,
                            )
                        self._json(200, {
                            "ok": True,
                            **payload,
                            "accepted_revision": result.revision,
                            "receipt": result.receipt_root,
                            "replayed": result.replayed,
                        })
                        return
                    if self.path == "/api/universal/session":
                        # The custom header is the same-origin proof: a
                        # cross-origin page cannot send it without a
                        # preflight this server never answers, so no other
                        # site can make the founder's browser sign in.
                        if not self.headers.get("X-ArchHub-Sign-In"):
                            self._json(403, {
                                "ok": False,
                                "error": "sign-in requires a same-origin "
                                         "request",
                            })
                            return
                        self._json(200, owner._clean_sign_in())
                        return
                    if self.path == "/api/universal/browser-handoff":
                        self._json(403, {
                            "ok": False,
                            "error": "clean browser session is required",
                        })
                        return
                    self._json(404, {"ok": False, "error": "not found"})
                except Conflict as exc:
                    self._json(409, {"ok": False, "error": str(exc)})
                except (
                    AuthorizationDenied,
                    InteractionProjectionDenied,
                    InvalidCell,
                ) as exc:
                    self._json(403, {"ok": False, "error": str(exc)})
                except Exception as exc:  # noqa: BLE001
                    # Never leave the browser waiting on a dead socket.
                    self._json(500, {"ok": False, "error": str(exc)})

        return Handler


@dataclass(slots=True)
class PreparedSharedUniversalRuntime:
    """One fenced shared authority prepared for exact server handoff."""

    store: CellStore
    registry: object
    fence_lease: RuntimeFenceLease
    _transferred: bool = False

    def create_server(self, *args, **kwargs):
        """Construct the sole server owner or release everything on failure."""
        for forbidden in (
            "universal_store",
            "universal_registry",
            "universal_runtime_fence_lease",
        ):
            if forbidden in kwargs:
                raise ValueError(
                    "prepared shared runtime owns " + forbidden
                )
        try:
            server = ApplicationServer(
                *args,
                universal_store=self.store,
                universal_registry=self.registry,
                universal_runtime_fence_lease=self.fence_lease,
                **kwargs,
            )
        except Exception:
            self.close()
            raise
        self._transferred = True
        return server

    def close(self) -> None:
        if self._transferred:
            return
        try:
            self.fence_lease.close()
        finally:
            self.store.close()


def prepare_shared_universal_runtime(
    store: CellStore,
    *,
    map_path: str | Path | None = None,
    key_provider: SigningKeyProvider | None = None,
    court_workspace_root: str | Path | None = None,
    runtime_compliance_runner=None,
) -> PreparedSharedUniversalRuntime:
    """Build or restore one shared Universal Application under its fence."""
    if not isinstance(store, CellStore):
        raise TypeError("shared Universal runtime requires one CellStore")
    if not store.is_durable or not store.supports_shared_writers:
        raise InvalidCell(
            "shared Universal runtime requires a shared durable Cell authority"
        )
    if key_provider is None:
        raise InvalidCell(
            "shared Universal runtime requires an admitted key provider"
        )
    application_root = "app:archhub"
    lease = store.prepare_runtime_fence(application_root)
    try:
        store.refresh()
        selected_map = map_path if map_path is not None else resolve_map_path()
        if application_root in store.snapshot().cells:
            selected_store, registry = restore_universal_application(
                selected_map,
                store,
                key_provider=key_provider,
                court_workspace_root=court_workspace_root,
                runtime_compliance_runner=runtime_compliance_runner,
            )
        else:
            selected_store, registry = build_universal_application(
                selected_map,
                store,
                key_provider=key_provider,
                court_workspace_root=court_workspace_root,
                runtime_compliance_runner=runtime_compliance_runner,
            )
        if selected_store is not store:
            raise InvalidCell(
                "shared Universal bootstrap replaced its Cell authority"
            )
        if registry.application_root != application_root:
            raise InvalidCell(
                "shared Universal bootstrap changed the application root"
            )
        return PreparedSharedUniversalRuntime(store, registry, lease)
    except Exception:
        try:
            lease.close()
        finally:
            store.close()
        raise


def _take_universal_runtime_fence(
    store: CellStore,
    application_root: str,
    prepared_lease: RuntimeFenceLease | None,
):
    if prepared_lease is not None:
        return prepared_lease.consume(store, application_root)
    return store.acquire_runtime_fence(application_root)


_CDE_WRITE_SIGNING_DESCRIPTOR_ROOT = "app:cde-write-signing-key:v1"


def _cde_write_key_name(database_identity) -> str:
    identity = hashlib.sha256(
        str(Path(database_identity).expanduser().resolve()).encode("utf-8")
    ).hexdigest()
    return "ArchHub.CdeWrite.%s.v1" % identity[:32]


def _open_cde_write_signing_provider(
    store: CellStore,
    registry: UniversalApplicationRegistry,
    database_identity,
):
    snapshot = store.snapshot()
    key_name = _cde_write_key_name(database_identity)
    if _CDE_WRITE_SIGNING_DESCRIPTOR_ROOT in snapshot.cells:
        descriptor = read_signing_key_descriptor(
            snapshot,
            registry.cde_signing_protocol,
            _CDE_WRITE_SIGNING_DESCRIPTOR_ROOT,
        )
        provider_ids = (descriptor.values["provider-id"],)
        create = False
    else:
        provider_ids = (PLATFORM_PROVIDER_ID, SOFTWARE_PROVIDER_ID)
        create = True
    failures = []
    for provider_id in provider_ids:
        try:
            return WindowsCngSigningAuthorityProvider(
                provider_id=provider_id,
                key_name=key_name,
                create=create,
            )
        except SigningAuthorityDenied as exc:
            failures.append(exc)
    raise SigningAuthorityDenied(
        "no admitted CDE write signing provider is available"
    ) from failures[-1]


def _ensure_cde_write_signing_authority(
    store: CellStore,
    registry: UniversalApplicationRegistry,
    provider,
    *,
    descriptor_root: str = _CDE_WRITE_SIGNING_DESCRIPTOR_ROOT,
):
    snapshot = store.snapshot()
    authorization_root = registry.authorization.policy_root
    release_root = registry.runtime_ownership_court_root
    if descriptor_root not in snapshot.cells:
        build_signing_key_descriptor(
            store,
            registry.cde_signing_protocol,
            provider,
            descriptor_id=descriptor_root,
            resource_version=provider.current_resource,
            authority_id="archhub.local.cde-write",
            purpose="cde-write-permit",
            authorization_evidence=authorization_root,
            release_evidence=release_root,
        )
        snapshot = store.snapshot()
    descriptor = verify_signing_key_descriptor(
        snapshot,
        registry.cde_signing_protocol,
        provider,
        descriptor_root,
        require_signing=True,
    )
    expected = {
        "authority-id": "archhub.local.cde-write",
        "purpose": "cde-write-permit",
        "authorization-evidence": authorization_root,
        "release-evidence": release_root,
    }
    for name, value in expected.items():
        if not hmac.compare_digest(descriptor.values[name], value):
            raise SigningAuthorityDenied(
                "CDE write signing descriptor %s mismatched" % name
            )
    members = [
        member for member in read_relation(
            snapshot, registry.application_root, budget=100_000
        )
        if member.role_id == registry.roles["member"]
        and member.participant_id == descriptor_root
    ]
    if not members:
        patch = prepare_append_relation_member(
            snapshot,
            registry.application_root,
            registry.roles["member"],
            descriptor_root,
            budget=100_000,
        )
        store.commit(
            snapshot.revision,
            create=patch.create,
            replace=patch.replace,
        )
    elif len(members) != 1:
        raise InvalidCell("CDE write signing authority membership drifted")
    return descriptor_root


class ApplicationServer:
    @classmethod
    def from_unified_authority(
        cls,
        authority,
        *,
        browser_authority=None,
        authority_key_provider=None,
        scope_caller,
        scope_root,
        **kwargs,
    ):
        """Bind one existing clean authority into one HTTP consumer path."""
        if not isinstance(authority, UnifiedAuthority):
            raise TypeError("clean server admission requires one UnifiedAuthority")
        if not isinstance(browser_authority, CleanBrowserAuthority):
            raise TypeError(
                "clean server admission requires one CleanBrowserAuthority"
            )
        if scope_caller is None or not hasattr(scope_caller, "sign"):
            raise TypeError(
                "clean server admission caller capability is invalid"
            )
        if (
            getattr(scope_caller, "actor_root", None)
            != authority.manifest.principal_root
        ):
            raise InvalidCell(
                "clean server caller actor root does not match the authority"
            )
        if (
            getattr(scope_caller, "session_root", None)
            != authority.manifest.bootstrap_session_root
        ):
            raise InvalidCell(
                "clean server caller session root does not match the authority"
            )
        if type(scope_root) is not str or not scope_root:
            raise TypeError("clean server scope root is invalid")
        if (
            authority_key_provider is None
            or not hasattr(authority_key_provider, "sign")
            or not hasattr(authority_key_provider, "current")
        ):
            raise TypeError(
                "clean server admission requires one signing key provider"
            )
        return _CleanAuthorityHttpServer(
            authority,
            browser_authority=browser_authority,
            authority_key_provider=authority_key_provider,
            scope_caller=scope_caller,
            scope_root=scope_root,
            **kwargs,
        )

    def __init__(self, host='127.0.0.1', port=0, store=None, registry=None,
                 state_path=None, fresh=False, live_watch=False,
                 public_server_url=None,
                 runtime_drain_coordinator=None,
                 cloud_host='127.0.0.1', cloud_port=0,
                 universal_store=None, universal_registry=None,
                  universal_state_path=None,
                  universal_runtime_fence_lease:
                  RuntimeFenceLease | None = None,
                  universal_checkpoint_path=None,
                 universal_checkpoint_authority_path=None,
                 universal_checkpoint_key_name=None,
                 universal_checkpoint_provider_id=None,
                 universal_checkpoint_signing_authority:
                 RevisionCheckpointSigningAuthority | None = None,
                 universal_key_provider: SigningKeyProvider | None = None,
                 device_key_factory=None,
                 allow_legacy_mutations=False,
                 pipeline_effect_engines=None,
                 enable_machine_transport=False,
                 enable_universal_cloud_gateway=False,
                 cloud_resource_origin=None,
                 cloud_tls_certificate_file=None,
                 cloud_tls_private_key_file=None,
                 cloud_nonce_key_provider: SigningKeyProvider | None = None,
                 cloud_nonce_key_id='archhub.local.universal-cloud-dpop-nonce',
                 machine_descriptor_path=None,
                 machine_key_provider=None,
                 machine_session_lifetime_seconds=900.0,
                 enable_machine_projection_prewarm=False,
                 machine_projection_prewarm_targets=(
                     "work", "canvas", "baboom"
                 ),
                 universal_workspace_root=None,
                 browser_session_credentials: BrowserSessionCredentials | None = None,
                 runtime_compliance_runner=None,
                 model_execution_broker=None):
        self.allow_legacy_mutations = bool(allow_legacy_mutations)
        # Which effects this runtime may run is named by whoever stands it
        # up -- the same law as the clean host invoker. No default engines.
        self.pipeline_effect_engines = dict(pipeline_effect_engines or {})
        self._public_server_url = self._validate_public_server_url(
            public_server_url
        )
        if (
            runtime_drain_coordinator is not None
            and not callable(runtime_drain_coordinator)
        ):
            raise ValueError("runtime drain coordinator must be callable")
        self._runtime_drain_coordinator = runtime_drain_coordinator
        self.device_key_factory = device_key_factory
        self.cloud_host = cloud_host
        self.cloud_port = cloud_port
        self.universal_cloud_gateway = None
        self.universal_cloud_server = None
        self._universal_cloud_thread = None
        self._validated_universal_cloud_origin = None
        self._validated_universal_cloud_listener = None
        if enable_universal_cloud_gateway:
            # Deployment mistakes must fail before this process claims a graph
            # runtime owner or opens any listening socket.
            self._validated_universal_cloud_origin = (
                validate_universal_cloud_resource_origin(cloud_resource_origin)
            )
            if not isinstance(cloud_nonce_key_id, str) or not cloud_nonce_key_id:
                raise ValueError('Universal cloud nonce key id is required')
            if (
                cloud_tls_certificate_file is None
                or cloud_tls_private_key_file is None
            ):
                raise ValueError(
                    'Universal cloud TLS certificate and key are required'
                )
            self._validated_universal_cloud_listener = (
                validate_universal_cloud_tls_listener(
                    UniversalCloudTlsListener(
                        host=cloud_host,
                        port=cloud_port,
                        certificate_file=Path(cloud_tls_certificate_file),
                        private_key_file=Path(cloud_tls_private_key_file),
                    )
                )
            )
        self.adapter_consent_broker = UserConsentBroker()
        if browser_session_credentials is not None and type(
            browser_session_credentials
        ) is not BrowserSessionCredentials:
            raise TypeError("browser session credentials are invalid")
        self.browser_session_token = (
            browser_session_credentials.token
            if browser_session_credentials is not None
            else secrets.token_urlsafe(32)
        )
        self.browser_csrf_token = (
            browser_session_credentials.csrf_token
            if browser_session_credentials is not None
            else secrets.token_urlsafe(32)
        )
        self.browser_credential_custody_id = (
            browser_session_credentials.custody_id
            if browser_session_credentials is not None else None
        )
        self.browser_bootstrap_token = secrets.token_urlsafe(32)
        self._browser_sessions = {}
        # What the last canvas gesture would take to reverse. The journal is
        # append-only by design, so undo is never a rollback: it is the
        # inverse gesture through the same signed commands.
        self._undo_entry = None
        self._browser_session_lock = threading.RLock()
        self._browser_canvas_projections: dict[
            str, _BrowserCanvasProjectionBinding
        ] = {}
        self._browser_scope_canvas_projections: dict[
            tuple[str, str], _BrowserCanvasProjectionBinding
        ] = {}
        self._browser_scope_canvas_identities: dict[
            tuple[str, str], tuple[
                tuple[str, ...],
                tuple[str, ...],
                tuple[str, ...],
                tuple[str, ...] | None,
            ]
        ] = {}
        self._browser_scope_projection_lineage: dict[str, int] = {}
        self._machine_agent_sessions = {}
        self._machine_agent_recovery_capabilities = {}
        self._machine_agent_session_lock = threading.RLock()
        self._machine_agent_challenges = {}
        self._model_execution_capabilities = {}
        self._model_execution_capability_lock = threading.RLock()
        self._connector_execution_capabilities = {}
        self._connector_execution_capability_lock = threading.RLock()
        self.machine_transport = None
        if (
            type(machine_session_lifetime_seconds) not in (int, float)
            or not 0 < float(machine_session_lifetime_seconds) <= 86_400
        ):
            raise ValueError(
                "machine Agent Session lifetime must be within one day"
            )
        self.machine_session_lifetime_seconds = float(
            machine_session_lifetime_seconds
        )
        self.enable_machine_projection_prewarm = bool(
            enable_machine_projection_prewarm
        )
        if (
            not isinstance(machine_projection_prewarm_targets, (tuple, list))
            or any(
                type(target) is not str
                for target in machine_projection_prewarm_targets
            )
        ):
            raise ValueError("machine projection prewarm targets are invalid")
        prewarm_targets = tuple(machine_projection_prewarm_targets)
        if (
            len(set(prewarm_targets)) != len(prewarm_targets)
            or set(prewarm_targets) - {"work", "canvas", "baboom"}
        ):
            raise ValueError("machine projection prewarm targets are invalid")
        self.machine_projection_prewarm_targets = prewarm_targets
        map_path = resolve_map_path()
        default_workspace_root = map_path.parents[3]
        self.universal_workspace_root = Path(
            universal_workspace_root or default_workspace_root
        ).expanduser().resolve()
        if not self.universal_workspace_root.is_dir():
            raise ValueError("Universal court workspace root is unavailable")
        self.model_execution_broker = (
            model_execution_broker
            if model_execution_broker is not None
            else ModelExecutionBroker(
                workspace_root=self.universal_workspace_root,
                timeout_seconds=60.0,
            )
        )
        requested_state_path = (
            Path(state_path).expanduser().resolve() if state_path else None
        )
        legacy_runtime_enabled = bool(
            self.allow_legacy_mutations or store is not None or registry is not None
        )
        self.state_path = requested_state_path if legacy_runtime_enabled else None
        built = False
        migration_report = None
        if legacy_runtime_enabled:
            if store is None:
                loaded = (
                    None
                    if fresh or self.state_path is None
                    else load_snapshot(self.state_path)
                )
                if (
                    loaded is None
                    and not fresh
                    and self.state_path is not None
                    and self.state_path.exists()
                ):
                    from .migration import migrate_snapshot
                    store, registry, migration_report = migrate_snapshot(
                        self.state_path
                    )
                    loaded = store, registry
                if loaded is None:
                    legacy = _legacy_application_module()
                    store, registry = legacy.build_archhub_application()
                    built = True
                else:
                    store, registry = loaded
            elif registry is None:
                registry = registry_from_store(store)
        else:
            store = None
            registry = None
        self.legacy_runtime_enabled = legacy_runtime_enabled
        self.store = store
        self.registry = registry
        explicit_universal_path = universal_state_path is not None
        if (
            universal_state_path is None
            and requested_state_path is not None
            and not fresh
        ):
            universal_state_path = requested_state_path.with_name(
                requested_state_path.name + ".universal.sqlite3"
            )
        self.universal_state_path = (
            Path(universal_state_path).expanduser().resolve()
            if universal_state_path is not None else None
        )
        self.universal_checkpoint_guard = None
        self.universal_checkpoint_signing_authority = None
        self.universal_checkpoint_protection = None
        self.universal_checkpoint_binding_root = None
        self._owns_universal_checkpoint_signing_authority = False
        guard = None
        guard_bound = False
        signing_authority = None
        owns_signing_authority = False
        # The rollback anchor exists only where OTHER people's rights
        # live: a shared fence, the cloud gateway, or a caller that
        # explicitly provisions checkpoint state. A personal desktop
        # store never has one -- structurally, not by configuration.
        universal_checkpoint_guard_enabled = bool(
            universal_runtime_fence_lease is not None
            or enable_universal_cloud_gateway
            or universal_checkpoint_path is not None
            or universal_checkpoint_authority_path is not None
            or universal_checkpoint_signing_authority is not None
            or universal_checkpoint_key_name is not None
            or universal_checkpoint_provider_id is not None
        )
        checkpoint_path = None
        if (
            self.universal_state_path is not None
            and universal_checkpoint_guard_enabled
        ):
            checkpoint_path = (
                Path(universal_checkpoint_path).expanduser().resolve()
                if universal_checkpoint_path is not None
                else RevisionCheckpointGuard.default_path(
                    self.universal_state_path
                )
            )
            signing_authority = universal_checkpoint_signing_authority
            if signing_authority is None:
                signing_authority = (
                    provision_windows_revision_checkpoint_authority(
                        self.universal_state_path,
                        authority_path=universal_checkpoint_authority_path,
                        provider_id=universal_checkpoint_provider_id,
                        key_name=universal_checkpoint_key_name,
                    )
                )
                owns_signing_authority = True

        owns_universal_store = universal_store is None
        if (
            universal_store is not None
            and universal_store.supports_shared_writers
            and universal_runtime_fence_lease is None
        ):
            raise ValueError(
                "shared Universal authority requires a prepared runtime fence"
            )
        if (
            universal_runtime_fence_lease is not None
            and (
                universal_store is None
                or not universal_store.supports_shared_writers
            )
        ):
            raise ValueError(
                "runtime fence handoff requires its shared Cell authority"
            )
        if universal_store is None:
            if fresh and explicit_universal_path and self.universal_state_path.exists():
                if owns_signing_authority:
                    signing_authority.store.close()
                raise ValueError(
                    "fresh universal state path already exists; refusing to erase history"
                )
            if self.universal_state_path is not None:
                self.universal_state_path.parent.mkdir(parents=True, exist_ok=True)
                universal_store = CellStore(self.universal_state_path)
                if universal_key_provider is None:
                    universal_key_provider = WindowsDpapiSigningKeyProvider(
                        WindowsDpapiSigningKeyProvider.default_path()
                    )
                persisted_application = (
                    "app:archhub" in universal_store.snapshot().cells
                )
                if universal_checkpoint_guard_enabled:
                    guard = RevisionCheckpointGuard(
                        checkpoint_path,
                        database_identity=str(self.universal_state_path),
                        key_provider=universal_key_provider,
                        signing_authority=signing_authority,
                    )
                try:
                    # Existing bytes and the selected external authority are
                    # checked before restore-time migrations are allowed to
                    # publish a successor revision. The checkpoint is not
                    # advanced until the restored graph passes below.
                    if persisted_application and guard is not None:
                        guard.verify_trusted_prefix(universal_store)
                        bind_external_signing_authority(
                            universal_store,
                            application_root='app:archhub',
                            application_member_role='gm:role:member',
                            authorization_root='app:authorization:policy',
                            authority_store=signing_authority.store,
                            signing_protocol=signing_authority.protocol,
                            provider=signing_authority.provider,
                            descriptor_root=signing_authority.descriptor_root,
                            prefix='app:external-graph-binding',
                            expected_purpose=(
                                RevisionCheckpointGuard.SIGNING_PURPOSE
                            ),
                        )
                    if persisted_application:
                        universal_store, universal_registry = (
                            restore_universal_application(
                                resolve_map_path(),
                                universal_store,
                                key_provider=universal_key_provider,
                                court_workspace_root=(
                                    self.universal_workspace_root
                                ),
                                runtime_compliance_runner=(
                                    runtime_compliance_runner
                                ),
                            )
                        )
                    else:
                        universal_store, universal_registry = (
                            build_universal_application(
                                resolve_map_path(),
                                universal_store,
                                key_provider=universal_key_provider,
                                court_workspace_root=(
                                    self.universal_workspace_root
                                ),
                                runtime_compliance_runner=(
                                    runtime_compliance_runner
                                ),
                            )
                        )
                except Exception:
                    if guard_bound:
                        guard.close()
                    universal_store.close()
                    if owns_signing_authority:
                        signing_authority.store.close()
                    raise
            else:
                universal_store, universal_registry = build_universal_application(
                    resolve_map_path(),
                    key_provider=universal_key_provider,
                    court_workspace_root=self.universal_workspace_root,
                    runtime_compliance_runner=runtime_compliance_runner,
                )
        elif universal_registry is None:
            if owns_signing_authority:
                signing_authority.store.close()
            raise ValueError('universal_registry is required with universal_store')

        if (
            self.universal_state_path is not None
            and universal_checkpoint_guard_enabled
            and guard is None
        ):
            guard = RevisionCheckpointGuard(
                checkpoint_path,
                database_identity=str(self.universal_state_path),
                key_provider=universal_key_provider,
                signing_authority=signing_authority,
            )
            try:
                guard.bind(universal_store)
                guard_bound = True
            except Exception:
                if owns_universal_store:
                    universal_store.close()
                if owns_signing_authority:
                    signing_authority.store.close()
                raise

        if signing_authority is not None:
            try:
                checkpoint_binding = bind_external_signing_authority(
                    universal_store,
                    application_root=universal_registry.application_root,
                    application_member_role=universal_registry.roles['member'],
                    authorization_root=(
                        universal_registry.authorization.policy_root
                    ),
                    authority_store=signing_authority.store,
                    signing_protocol=signing_authority.protocol,
                    provider=signing_authority.provider,
                    descriptor_root=signing_authority.descriptor_root,
                    prefix='app:external-graph-binding',
                    expected_purpose=RevisionCheckpointGuard.SIGNING_PURPOSE,
                )
                if not guard_bound:
                    guard.bind(universal_store)
                    guard_bound = True
                guard.require_healthy()
            except Exception:
                if guard_bound:
                    guard.close()
                if owns_universal_store:
                    universal_store.close()
                if owns_signing_authority:
                    signing_authority.store.close()
                raise
            self.universal_checkpoint_binding_root = checkpoint_binding.root_id
            self.universal_checkpoint_guard = guard
            self.universal_checkpoint_signing_authority = signing_authority
            self.universal_checkpoint_protection = (
                read_signing_key_descriptor(
                    signing_authority.store.snapshot(),
                    signing_authority.protocol,
                    signing_authority.descriptor_root,
                ).values['protection-level']
            )
            self._owns_universal_checkpoint_signing_authority = (
                owns_signing_authority
            )
        self.universal_store = universal_store
        self.universal_registry = universal_registry
        self.mutation_lock = threading.RLock()
        self._work_index_cache_lock = threading.RLock()
        self._work_index_cache_ready = threading.Condition(
            self._work_index_cache_lock
        )
        self._work_index_cache_revision = -1
        self._work_index_cache: dict[str, object] | None = None
        self._work_index_cache_inflight_revision: int | None = None
        self._workshop_cache_revision = -1
        self._workshop_cache: dict[str, object] | None = None
        self._canvas_cache_revision = -1
        self._canvas_cache: dict[str, object] | None = None
        self._projection_prewarm_stop = threading.Event()
        self._projection_prewarm_thread: threading.Thread | None = None
        self._projection_prewarm_status: dict[str, object] = {
            "ok": False,
            "revision": -1,
            "status": "not-run",
        }
        self._projection_prewarm_status_lock = threading.RLock()
        self._route_authorization_cache_lock = threading.RLock()
        self._route_authorization_cache: dict[
            tuple[int, str, str, int], object
        ] = {}
        self._runtime_holder_root = "app:runtime-holder:" + uuid.uuid4().hex
        self._runtime_ownership_root = None
        self._runtime_fence_release = None
        self._runtime_handoff_exit = threading.Event()
        self.cde_write_signing_provider = None
        self.cde_write_signing_descriptor_root = None
        try:
            self._runtime_fence_release = _take_universal_runtime_fence(
                self.universal_store,
                self.universal_registry.application_root,
                universal_runtime_fence_lease,
            )
            self._claim_runtime_ownership()
            if self.universal_state_path is not None:
                self.cde_write_signing_provider = (
                    _open_cde_write_signing_provider(
                        self.universal_store,
                        self.universal_registry,
                        self.universal_state_path,
                    )
                )
                self.cde_write_signing_descriptor_root = (
                    _ensure_cde_write_signing_authority(
                        self.universal_store,
                        self.universal_registry,
                        self.cde_write_signing_provider,
                    )
                )
        except Exception:
            if self._runtime_fence_release is not None:
                self._runtime_fence_release()
                self._runtime_fence_release = None
            if self.universal_checkpoint_guard is not None:
                self.universal_checkpoint_guard.close()
            if owns_universal_store:
                self.universal_store.close()
            if (
                owns_signing_authority
                and self.universal_checkpoint_signing_authority is not None
            ):
                self.universal_checkpoint_signing_authority.store.close()
            raise
        self.interaction_projection_broker = InteractionProjectionBroker()
        founder_browser_binding = self._recover_browser_session()
        self._revoke_orphaned_browser_sessions(
            preserve_root=(
                founder_browser_binding.session_root
                if founder_browser_binding is not None else None
            )
        )
        if founder_browser_binding is None:
            founder_browser_binding = self._register_browser_session(
                self.browser_session_token,
                self.browser_csrf_token,
                self.universal_registry.authorization.session.context(),
                lifetime_seconds=3600.0,
            )
        self.browser_session_root = founder_browser_binding.session_root
        ensure_universal_properties_panel_interactions(
            self.universal_store,
            self.universal_registry,
            founder_browser_binding.subject_root,
        )
        self.universal_reaction_engine = ReactionEngine(
            universal_store,
            universal_registry.assembly_protocol,
            universal_registry.standard_library.reaction_protocol,
        )
        self.migration_report = migration_report
        if store is not None:
            store.prepare_runtime_indexes()
        self._snapshot_event = threading.Event()
        self._snapshot_stop = threading.Event()
        self._snapshot_thread = None
        self._snapshot_revision = 0
        if store is not None and self.state_path is not None:
            if built or fresh or not self.state_path.exists():
                save_snapshot(store, self.state_path)
            self._snapshot_thread = threading.Thread(
                target=self._snapshot_loop, name='archhub-snapshot-writer', daemon=True)
            self._snapshot_thread.start()
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, _format, *_args):
                return

            def _json(self, status, payload):
                raw = json.dumps(payload, separators=(',', ':')).encode('utf-8')
                try:
                    self.send_response(status)
                    self.send_header('Content-Type', 'application/json; charset=utf-8')
                    self.send_header('Cache-Control', 'no-store')
                    self.send_header('Content-Length', str(len(raw)))
                    self.end_headers()
                    self.wfile.write(raw)
                    return True
                except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
                    return False

            def _body(self):
                try:
                    length = int(self.headers.get('Content-Length') or 0)
                except ValueError as exc:
                    raise InvalidCell('request content length is invalid') from exc
                if length < 0 or length > MAX_REQUEST_BODY_BYTES:
                    self.close_connection = True
                    raise InvalidCell('request body exceeds the admitted limit')
                raw = self.rfile.read(length)
                if len(raw) != length:
                    raise InvalidCell('request body is incomplete')
                return json.loads(raw.decode('utf-8') or '{}')

            def _discard_admitted_body(self):
                """Drain a bounded denied request so Windows can deliver 403."""
                try:
                    length = int(self.headers.get('Content-Length') or 0)
                except ValueError:
                    self.close_connection = True
                    return
                if length < 0 or length > MAX_REQUEST_BODY_BYTES:
                    self.close_connection = True
                    return
                remaining = length
                while remaining:
                    chunk = self.rfile.read(min(remaining, 65_536))
                    if not chunk:
                        self.close_connection = True
                        return
                    remaining -= len(chunk)

            def _browser_session_binding(self, *, unsafe=False):
                supplied = self.headers.get('X-ArchHub-Session') or ''
                cookie_session = ''
                raw_cookie = self.headers.get('Cookie') or ''
                if raw_cookie:
                    parsed_cookie = SimpleCookie()
                    parsed_cookie.load(raw_cookie)
                    morsel = parsed_cookie.get('ArchHub-Session')
                    cookie_session = morsel.value if morsel is not None else ''
                site = self.headers.get('Sec-Fetch-Site')
                if site not in (None, 'none', 'same-origin'):
                    raise AuthorizationDenied(
                        'cross-site browser request is denied'
                    )
                token = supplied or cookie_session
                if not token:
                    raise AuthorizationDenied(
                        'authenticated browser session required'
                    )
                # A custom session header is already a non-simple same-origin
                # proof. Cookie-authenticated unsafe requests additionally
                # require a synchronizer token bound to this session.
                return (
                    owner._resolve_browser_session(
                        token,
                        csrf_token=self.headers.get('X-ArchHub-CSRF'),
                        require_csrf=unsafe and not bool(supplied),
                    ),
                    token,
                )

            def _set_browser_cookie(self, token):
                attributes = [
                    'ArchHub-Session=%s' % token,
                    'Path=/',
                    'HttpOnly',
                    'SameSite=Strict',
                    'Max-Age=3600',
                ]
                if owner.httpd.server_address[0] not in (
                    '127.0.0.1', 'localhost', '::1'
                ):
                    attributes.append('Secure')
                self.send_header('Set-Cookie', '; '.join(attributes))

            def _universal_integrity(self):
                guard = owner.universal_checkpoint_guard
                if guard is not None:
                    guard.require_healthy()

            def _universal_route(
                self, method, path, binding, *, drain_denied_body=False
            ):
                try:
                    owner.require_universal_http_route(
                        method,
                        path,
                        authentication_context=binding.context,
                    )
                except AuthorizationDenied:
                    if drain_denied_body:
                        self._discard_admitted_body()
                    self._json(403, {
                        'ok': False,
                        'error': 'universal route authorization denied',
                    })
                    return False
                except CloudRouteDenied:
                    if drain_denied_body:
                        self._discard_admitted_body()
                    self._json(404, {
                        'ok': False,
                        'error': 'not found',
                    })
                    return False
                except Exception as exc:
                    if drain_denied_body:
                        self._discard_admitted_body()
                    self._json(503, {
                        'ok': False,
                        'error': 'universal route authority unavailable: '
                                 + str(exc),
                    })
                    return False
                return True

            @with_relation_projection_scope
            @with_catalog_verification_scope
            @with_session_canvas_roots_scope
            def do_GET(self):
                if owner._runtime_handoff_exit.is_set():
                    self._json(503, {
                        'ok': False,
                        'error': 'runtime generation was released',
                    })
                    return
                parsed = urlsplit(self.path)
                if parsed.path == '/favicon.ico':
                    self.send_response(204)
                    self.send_header('Cache-Control', 'no-store')
                    self.end_headers()
                    return
                if (
                    parsed.path == '/'
                    or parsed.path == '/api/state'
                    or parsed.path.startswith('/api/universal')
                    or parsed.path.startswith('/website')
                ):
                    try:
                        self._universal_integrity()
                    except Exception as exc:
                        self._json(503, {
                            'ok': False,
                            'error': 'universal revision integrity unavailable: '
                                     + str(exc),
                        })
                        return
                if parsed.path == '/api/universal/hosts':
                    # The live machine, honestly: which hosts answer right
                    # now. A port scan of the published broker range, never
                    # a remembered list.
                    try:
                        self._browser_session_binding()
                    except AuthorizationDenied as denied:
                        self._json(403, {'ok': False, 'error': str(denied)})
                        return
                    try:
                        from .clean_revit_adapter import live_sessions
                        found = []
                        for item in live_sessions():
                            document = item.get('document')
                            if isinstance(document, dict):
                                document = (
                                    document.get('document_title')
                                    or document.get('document_name')
                                    or ''
                                )
                            name = (
                                item.get('revit_version')
                                or (
                                    'AutoCAD %s' % item['document'].get(
                                        'acad_version', ''
                                    )
                                    if isinstance(item.get('document'), dict)
                                    and item['document'].get('acad_version')
                                    else 'Host'
                                )
                            )
                            found.append({
                                'id': str(item['port']),
                                'name': str(name),
                                'port': str(item['port']),
                                'state': 'connected',
                                'file': str(document or 'no document open'),
                            })
                        self._json(200, {'ok': True, 'hosts': found})
                    except Exception as exc:  # noqa: BLE001
                        self._json(200, {
                            'ok': True, 'hosts': [],
                            'note': str(exc),
                        })
                    return
                if parsed.path == '/api/universal/capabilities':
                    # What this running application can actually reach. A
                    # capability installed in the graph but unreachable from
                    # here is still not part of the product, so the canvas
                    # asks the server rather than trusting a build-time list.
                    try:
                        self._browser_session_binding()
                    except AuthorizationDenied as denied:
                        self._json(403, {'ok': False, 'error': str(denied)})
                        return
                    try:
                        snapshot = owner.universal_store.snapshot()
                        missing = missing_capabilities(snapshot)
                        self._json(200, {
                            'ok': not missing,
                            'revision': snapshot.revision,
                            'capabilities': [
                                {'name': name, 'root': root,
                                 'present': root in snapshot.cells}
                                for name, root, _key in CAPABILITIES
                            ],
                            'missing': list(missing),
                        })
                    except Exception as exc:  # noqa: BLE001
                        self._json(500, {'ok': False, 'error': str(exc)})
                    return
                if parsed.path == '/cockpit':
                    parsed = parsed._replace(path='/studio/cockpit.html')
                if parsed.path == '/studio' or parsed.path.startswith(
                    '/studio/'
                ):
                    # The studio face: the design handoff's own surface,
                    # served same-origin so every fetch is the signed API.
                    studio_binding = None
                    studio_session_token = None
                    try:
                        studio_binding, studio_session_token = (
                            self._browser_session_binding()
                        )
                    except AuthorizationDenied:
                        bootstrap = (
                            parse_qs(parsed.query).get('bootstrap') or ['']
                        )[0]
                        if not owner._consume_browser_bootstrap(bootstrap):
                            self._json(403, {
                                'ok': False,
                                'error': 'desktop bootstrap is required',
                            })
                            return
                        studio_session_token = owner.browser_session_token
                        self._set_browser_cookie(studio_session_token)
                        studio_binding = owner._resolve_browser_session(
                            studio_session_token
                        )
                    import mimetypes as _mimetypes
                    from pathlib import Path as _Path
                    studio_dir = _Path(__file__).resolve().parent / 'studio'
                    name = parsed.path[len('/studio'):].lstrip('/')
                    target = (
                        studio_dir / 'studio.html' if not name
                        else (studio_dir / name)
                    )
                    resolved = target.resolve()
                    inside = studio_dir == resolved.parent or (
                        studio_dir in resolved.parents
                    )
                    if not inside or not resolved.is_file():
                        self._json(404, {'ok': False, 'error': 'no such file'})
                        return
                    if resolved.name == 'map-data.js':
                        # The cockpit map IS the live graph -- brain,
                        # cockpit, grand map: one model. Falls back to
                        # the authored file only if projection refuses.
                        try:
                            from .universal_pipeline import (
                                project_atlas_map,
                            )
                            raw = project_atlas_map(
                                owner.universal_store,
                                owner.universal_registry,
                                authentication_context=(
                                    studio_binding.context
                                    if studio_binding is not None else None
                                ),
                            ).encode('utf-8')
                        except Exception:
                            raw = resolved.read_bytes()
                    else:
                        raw = resolved.read_bytes()
                    if (
                        resolved.suffix == '.html'
                        and studio_binding is not None
                    ):
                        raw = raw.replace(
                            b'/*__ARCHHUB_BOOT__*/ null',
                            json.dumps({
                                'token': studio_session_token,
                                'csrf': studio_binding.csrf_token,
                            }).encode('utf-8'),
                        )
                    kind = (
                        'text/html; charset=utf-8'
                        if resolved.suffix == '.html'
                        else 'text/javascript; charset=utf-8'
                        if resolved.suffix in ('.js', '.jsx')
                        else _mimetypes.guess_type(str(resolved))[0]
                        or 'application/octet-stream'
                    )
                    self.send_response(200)
                    self.send_header('Content-Type', kind)
                    self.send_header('Cache-Control', 'no-store')
                    self.send_header('X-Content-Type-Options', 'nosniff')
                    if resolved.suffix == '.html':
                        self.send_header('Referrer-Policy', 'no-referrer')
                        self.send_header('X-Frame-Options', 'DENY')
                        self.send_header(
                            'Content-Security-Policy',
                            "default-src 'none'; connect-src 'self'; "
                            "img-src 'self' data:; "
                            "style-src 'unsafe-inline' "
                            "https://fonts.googleapis.com; "
                            "font-src https://fonts.gstatic.com; "
                            "script-src 'self' 'unsafe-inline' "
                            "'unsafe-eval'; frame-ancestors 'none'"
                        )
                    self.send_header('Content-Length', str(len(raw)))
                    self.end_headers()
                    self.wfile.write(raw)
                    return
                if parsed.path == '/':
                    try:
                        binding, session_token = \
                            self._browser_session_binding()
                    except AuthorizationDenied:
                        bootstrap = (
                            parse_qs(parsed.query).get('bootstrap') or ['']
                        )[0]
                        if not owner._consume_browser_bootstrap(bootstrap):
                            self._json(403, {
                                'ok': False,
                                'error': 'desktop bootstrap is required',
                            })
                            return
                        session_token = owner.browser_session_token
                        binding = owner._resolve_browser_session(
                            session_token
                        )
                    with owner.mutation_lock:
                        raw = project_universal_document(
                            owner.universal_store,
                            owner.universal_registry,
                            csrf_token=binding.csrf_token,
                            authentication_context=binding.context,
                        ).encode('utf-8')
                    self.send_response(200)
                    self._set_browser_cookie(session_token)
                    self.send_header('Content-Type', 'text/html; charset=utf-8')
                    self.send_header('Cache-Control', 'no-store')
                    self.send_header('X-Content-Type-Options', 'nosniff')
                    self.send_header('Referrer-Policy', 'no-referrer')
                    self.send_header('X-Frame-Options', 'DENY')
                    self.send_header(
                        'Content-Security-Policy',
                        "default-src 'none'; connect-src 'self'; "
                        "img-src 'self' data:; style-src 'unsafe-inline'; "
                        "script-src 'unsafe-inline'; frame-ancestors 'none'"
                    )
                    self.send_header('Content-Length', str(len(raw)))
                    self.end_headers()
                    self.wfile.write(raw)
                    return
                if parsed.path in PUBLIC_WEBSITE_ROUTES:
                    with owner.mutation_lock:
                        try:
                            raw = project_universal_website_document(
                                owner.universal_store,
                                owner.universal_registry.website,
                                parsed.path,
                                application_root=(
                                    owner.universal_registry.application_root
                                ),
                                application_member_role=(
                                    owner.universal_registry.roles['member']
                                ),
                                map_registry=owner.universal_registry.map,
                                cloud_route_protocol=(
                                    owner.universal_registry.cloud_route_protocol
                                ),
                            ).encode('utf-8')
                            stylesheet = owner.universal_store.read(
                                owner.universal_registry.website.stylesheet_root
                            ).atom
                        except InvalidCell:
                            self._json(503, {
                                'ok': False,
                                'error': 'public website graph is unavailable',
                            })
                            return
                    style_digest = base64.b64encode(
                        hashlib.sha256(stylesheet).digest()
                    ).decode('ascii')
                    self.send_response(200)
                    self.send_header('Content-Type', 'text/html; charset=utf-8')
                    self.send_header('Cache-Control', 'no-store')
                    self.send_header('X-Content-Type-Options', 'nosniff')
                    self.send_header('Referrer-Policy', 'no-referrer')
                    self.send_header('X-Frame-Options', 'DENY')
                    self.send_header(
                        'Cross-Origin-Opener-Policy', 'same-origin'
                    )
                    self.send_header(
                        'Cross-Origin-Resource-Policy', 'same-origin'
                    )
                    self.send_header(
                        'Permissions-Policy',
                        'camera=(), microphone=(), geolocation=()'
                    )
                    self.send_header(
                        'Content-Security-Policy',
                        "default-src 'none'; style-src 'sha256-%s'; "
                        "base-uri 'none'; form-action 'none'; "
                        "frame-ancestors 'none'" % style_digest
                    )
                    self.send_header(
                        'X-ArchHub-Graph-Root',
                        owner.universal_registry.website.root_id,
                    )
                    self.send_header('Content-Length', str(len(raw)))
                    self.end_headers()
                    self.wfile.write(raw)
                    return
                if parsed.path.startswith('/website'):
                    self._json(404, {'ok': False, 'error': 'not found'})
                    return
                binding = None
                if parsed.path.startswith('/api/'):
                    try:
                        binding, _session_token = \
                            self._browser_session_binding()
                    except AuthorizationDenied as exc:
                        self._json(403, {
                            'ok': False,
                            'error': str(exc),
                        })
                        return
                if parsed.path == '/api/state':
                    if not self._universal_route(
                        'GET', parsed.path, binding
                    ):
                        return
                    with owner.mutation_lock:
                        payload = owner.project_runtime_state(
                            authentication_context=binding.context
                        )
                    self._json(200, payload)
                    return
                if parsed.path == '/api/universal/canvas':
                    if not self._universal_route('GET', parsed.path, binding):
                        return
                    with owner.mutation_lock:
                        payload = {
                            'ok': True,
                            **owner.project_interaction_canvas(binding),
                        }
                    self._json(200, payload)
                    return
                if parsed.path == '/api/universal/work':
                    if not self._universal_route('GET', parsed.path, binding):
                        return
                    with owner.mutation_lock:
                        payload = {
                            'ok': True,
                            **project_universal_governed_work_status(
                                owner.universal_store,
                                owner.universal_registry,
                                authentication_context=binding.context,
                            ),
                        }
                    self._json(200, payload)
                    return
                if parsed.path == '/api/universal/grand-map-work':
                    if not self._universal_route('GET', parsed.path, binding):
                        return
                    query = parse_qs(parsed.query)
                    raw_limit = query.get('limit', ['50'])[0]
                    raw_include_live = query.get('include_live', ['false'])[0]
                    with owner.mutation_lock:
                        payload = {
                            'ok': True,
                            **project_universal_grand_map_work(
                                owner.universal_store,
                                owner.universal_registry,
                                limit=int(raw_limit),
                                include_live=(
                                    str(raw_include_live).lower()
                                    in {'1', 'true', 'yes'}
                                ),
                                authentication_context=binding.context,
                            ),
                        }
                    self._json(200, payload)
                    return
                if parsed.path == '/api/universal/roma-tree':
                    if not self._universal_route('GET', parsed.path, binding):
                        return
                    query = parse_qs(parsed.query)
                    if set(query) - {'tree_id'}:
                        raise InvalidCell(
                            'ROMA tree projection request contains undeclared facts'
                        )
                    raw_tree_id = query.get('tree_id', [''])[0]
                    with owner.mutation_lock:
                        if raw_tree_id:
                            payload = project_universal_roma_requirement_tree(
                                owner.universal_store,
                                owner.universal_registry,
                                tree_id=raw_tree_id,
                                authentication_context=binding.context,
                            )
                        else:
                            payload = project_universal_roma_requirement_tree_index(
                                owner.universal_store,
                                owner.universal_registry,
                                authentication_context=binding.context,
                            )
                    self._json(200, payload)
                    return
                if parsed.path == '/api/universal/health':
                    if not self._universal_route('GET', parsed.path, binding):
                        return
                    with owner.mutation_lock:
                        snapshot = owner.universal_store.snapshot()
                        session_members = read_relation(
                            snapshot,
                            owner.universal_registry.cloud_session_protocol.root_id,
                            budget=100_000,
                        )
                        native_members = read_relation(
                            snapshot,
                            owner.universal_registry.native_authentication_protocol.root_id,
                            budget=100_000,
                        )
                        payload = {
                            'ok': True,
                            'runtime': owner.universal_registry.application_root,
                            'revision': snapshot.revision,
                            'cells': len(snapshot.cells),
                            'checkpoint': (
                                'anchored'
                                if owner.universal_checkpoint_guard is not None
                                else 'isolated'
                            ),
                            'checkpoint_format': (
                                'v2-asymmetric'
                                if owner.universal_checkpoint_signing_authority
                                is not None
                                else 'none'
                            ),
                            'checkpoint_protection': (
                                owner.universal_checkpoint_protection
                            ),
                            'checkpoint_binding': (
                                owner.universal_checkpoint_binding_root
                            ),
                            'routes': len(
                                owner.universal_registry.application_http_route_roots
                            ),
                            'cloud_sessions': sum(
                                member.role_id
                                == owner.universal_registry.cloud_session_protocol.role(
                                    'session-member'
                                )
                                for member in session_members
                            ),
                            'native_identity_providers': sum(
                                member.role_id
                                == owner.universal_registry.native_authentication_protocol.role(
                                    'client-member'
                                )
                                for member in native_members
                            ),
                            'core_values': {
                                'root': (
                                    owner.universal_registry.core_values.root_id
                                ),
                                'lifecycle': 'WIP',
                                'source_digest': (
                                    owner.universal_registry.core_values.source_digest
                                ),
                                'translation_digest': (
                                    owner.universal_registry.core_values.translation_digest
                                ),
                                'coverage': {
                                    key: item.status
                                    for key, item in (
                                        owner.universal_registry.core_values.coverage.items()
                                    )
                                },
                            },
                            'legacy_parallel_runtime': (
                                owner.legacy_runtime_enabled
                            ),
                            'legacy_runtime_status': (
                                'migration-only; not product authority'
                                if owner.legacy_runtime_enabled
                                else 'not instantiated'
                            ),
                        }
                    self._json(200, payload)
                    return
                if parsed.path == '/api/universal/site-export':
                    if not self._universal_route('GET', parsed.path, binding):
                        return
                    with owner.mutation_lock:
                        try:
                            payload = build_site_export(
                                owner.universal_store,
                                owner.universal_registry,
                            )
                            raw = json.dumps(
                                payload,
                                sort_keys=True,
                                separators=(',', ':'),
                                ensure_ascii=True,
                            ).encode('utf-8')
                        except SiteExportError:
                            self._json(503, {
                                'ok': False,
                                'error': 'universal website export is unavailable',
                            })
                            return
                    self.send_response(200)
                    self.send_header(
                        'Content-Type', 'application/json; charset=utf-8'
                    )
                    self.send_header('Cache-Control', 'no-store')
                    self.send_header('X-Content-Type-Options', 'nosniff')
                    self.send_header(
                        'X-ArchHub-Classification', payload['publication_tier']
                    )
                    self.send_header(
                        'X-ArchHub-Graph-Root', payload['website_root']
                    )
                    self.send_header(
                        'Content-Disposition',
                        'attachment; filename="archhub-public-site-v2.json"',
                    )
                    self.send_header('Content-Length', str(len(raw)))
                    self.end_headers()
                    self.wfile.write(raw)
                    return
                if parsed.path == '/api/export':
                    if (
                        binding.subject_root != owner.universal_registry
                        .authorization.subject_root
                        or not owner.allow_legacy_mutations
                    ):
                        self._json(403, {
                            'ok': False,
                            'error': 'legacy export is founder-only and disabled',
                        })
                        return
                    node_id = (parse_qs(parsed.query).get('node_id') or [''])[0]
                    with owner.mutation_lock:
                        payload = export_subgraph(owner.store, node_id)
                        title = owner.store.nodes[node_id]['title'] or node_id
                        raw = json.dumps(payload, separators=(',', ':')).encode('utf-8')
                    filename = ''.join(ch if ch.isalnum() or ch in '-_' else '-'
                                       for ch in title).strip('-') or 'archhub-graph'
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json; charset=utf-8')
                    self.send_header('Cache-Control', 'no-store')
                    self.send_header('X-ArchHub-Classification', payload['classification'])
                    self.send_header('Content-Disposition',
                                     'attachment; filename="%s.archhub.json"' % filename)
                    self.send_header('Content-Length', str(len(raw)))
                    self.end_headers()
                    self.wfile.write(raw)
                    return
                self._json(404, {'ok': False, 'error': 'not found'})

            @with_relation_projection_scope
            @with_catalog_verification_scope
            @with_session_canvas_roots_scope
            def do_POST(self):
                try:
                    if owner._runtime_handoff_exit.is_set():
                        self._discard_admitted_body()
                        self._json(503, {
                            'ok': False,
                            'error': 'runtime generation was released',
                        })
                        return
                    try:
                        binding, _session_token = \
                            self._browser_session_binding(unsafe=True)
                    except AuthorizationDenied as exc:
                        self._discard_admitted_body()
                        self._json(403, {
                            'ok': False,
                            'error': str(exc),
                        })
                        return
                    if self.path.startswith('/api/universal/'):
                        self._universal_integrity()
                        if not self._universal_route(
                            'POST', self.path, binding,
                            drain_denied_body=True,
                        ):
                            return
                    body = self._body()
                    if self.path == '/api/universal/baboom-command':
                        if set(body) != {'utterance'}:
                            raise InvalidCell(
                                'BABOOM command resolution request shape is invalid'
                            )
                        with owner.mutation_lock:
                            payload = {
                                'ok': True,
                                **resolve_universal_baboom_utterance(
                                    owner.universal_store,
                                    owner.universal_registry,
                                    utterance=body['utterance'],
                                    authentication_context=binding.context,
                                ),
                            }
                        self._json(200, payload)
                        return
                    if self.path == '/api/universal/baboom-command-response':
                        if set(body) != {'utterance'}:
                            raise InvalidCell(
                                'BABOOM command response request shape is invalid'
                            )
                        with owner.mutation_lock:
                            payload = {
                                'ok': True,
                                **respond_universal_baboom_utterance(
                                    owner.universal_store,
                                    owner.universal_registry,
                                    utterance=body['utterance'],
                                    authentication_context=binding.context,
                                ),
                            }
                        self._json(200, payload)
                        return
                    if self.path == '/api/universal/baboom-command-execute':
                        if set(body) != {'utterance'}:
                            raise InvalidCell(
                                'BABOOM command execution request shape is invalid'
                            )
                        with owner.mutation_lock:
                            payload = {
                                'ok': True,
                                **execute_universal_baboom_utterance(
                                    owner.universal_store,
                                    owner.universal_registry,
                                    utterance=body['utterance'],
                                    authentication_context=binding.context,
                                ),
                            }
                        self._json(200, payload)
                        return
                    if self.path == '/api/universal/work':
                        allowed = {
                            'title', 'description', 'priority', 'external_key',
                            'references', 'structured_references', 'x', 'y',
                            'projection',
                        }
                        if set(body) - allowed:
                            raise InvalidCell(
                                'governed work request contains undeclared facts'
                            )
                        with owner.mutation_lock:
                            created_root, membership_wire, revision = (
                                create_universal_governed_work(
                                    owner.universal_store,
                                    owner.universal_registry,
                                    title=body.get('title', ''),
                                    description=body.get('description', ''),
                                    priority=body.get('priority', 0),
                                    external_key=body.get(
                                        'external_key', 'unset'
                                    ),
                                    references=body.get('references'),
                                    structured_references=body.get(
                                        'structured_references'
                                    ),
                                    x=float(body.get('x', 0.0)),
                                    y=float(body.get('y', 0.0)),
                                    authentication_context=binding.context,
                                )
                            )
                            payload = {
                                'ok': True,
                                'created_root': created_root,
                                'membership_wire': membership_wire,
                                'revision': revision,
                            }
                            if body.get('projection', True):
                                payload.update(
                                    project_universal_governed_work_status(
                                        owner.universal_store,
                                        owner.universal_registry,
                                        authentication_context=binding.context,
                                    )
                                )
                        self._json(200, payload)
                        return
                    if self.path == '/api/universal/grand-map-work':
                        allowed = {'limit', 'include_live'}
                        if set(body) - allowed:
                            raise InvalidCell(
                                'Grand Map Work sync request contains undeclared facts'
                            )
                        with owner.mutation_lock:
                            payload = {
                                'ok': True,
                                **sync_universal_grand_map_work(
                                    owner.universal_store,
                                    owner.universal_registry,
                                    limit=int(body.get('limit', 25)),
                                    include_live=bool(
                                        body.get('include_live', False)
                                    ),
                                    authentication_context=binding.context,
                                ),
                            }
                        self._json(200, payload)
                        return
                    if self.path == '/api/universal/roma-tree':
                        allowed = {'tree', 'source'}
                        if set(body) - allowed:
                            raise InvalidCell(
                                'ROMA tree sync request contains undeclared facts'
                            )
                        tree = body.get('tree')
                        if type(tree) is not dict:
                            raise InvalidCell(
                                'ROMA tree sync request tree is invalid'
                            )
                        source = body.get('source', 'browser.roma')
                        if type(source) is not str or not source.strip():
                            raise InvalidCell(
                                'ROMA tree sync request source is invalid'
                            )
                        with owner.mutation_lock:
                            payload = sync_universal_roma_requirement_tree(
                                owner.universal_store,
                                owner.universal_registry,
                                tree,
                                source=source,
                                authentication_context=binding.context,
                            )
                        self._json(200, payload)
                        return
                    if self.path == '/api/universal/interaction':
                        admitted = {
                            'interaction', 'control', 'event', 'revision',
                            'projection_mode', 'event_facts',
                        }
                        if set(body) - admitted:
                            raise InvalidCell(
                                'interaction request contains undeclared facts'
                            )
                        if any(
                            not isinstance(body.get(name), str)
                            or not body.get(name)
                            for name in ('interaction', 'control', 'event')
                        ):
                            raise InvalidCell(
                                'interaction request identities are invalid'
                            )
                        if type(body.get('revision')) is not int:
                            raise InvalidCell(
                                'interaction request revision is invalid'
                            )
                        projection_mode = body.get('projection_mode')
                        if projection_mode not in (
                            None,
                            _INTERACTION_DELTA_MODE,
                            _TOPOLOGY_DELTA_MODE,
                            _RECEIPT_MODE,
                        ):
                            raise InvalidCell(
                                'interaction projection mode is invalid'
                            )
                        with owner.mutation_lock:
                            receipt_started = time.perf_counter()
                            if (
                                projection_mode in (
                                    _INTERACTION_DELTA_MODE,
                                    _TOPOLOGY_DELTA_MODE,
                                    _RECEIPT_MODE,
                                )
                                and body['revision']
                                != owner.universal_store.revision
                            ):
                                raise Conflict(
                                    "expected revision %s, current revision is %s"
                                    % (
                                        body['revision'],
                                        owner.universal_store.revision,
                                    )
                                )
                            previous_projection = (
                                owner._cached_browser_canvas_projection(
                                    binding, body['revision']
                                )
                                if projection_mode in (
                                    _INTERACTION_DELTA_MODE,
                                    _TOPOLOGY_DELTA_MODE,
                                    _RECEIPT_MODE,
                                )
                                else None
                            )
                            if (
                                projection_mode in (
                                    _INTERACTION_DELTA_MODE,
                                    _TOPOLOGY_DELTA_MODE,
                                    _RECEIPT_MODE,
                                )
                                and previous_projection is None
                            ):
                                raise InvalidCell(
                                    'interaction projection cache is unavailable'
                            )
                            created_root = None
                            scope_materialization = None
                            reusable_scope_projection = None
                            reusable_scope_identity = None
                            interaction = read_interaction(
                                owner.universal_store.snapshot(),
                                owner.universal_registry.interaction_protocol,
                                body['interaction'],
                                budget=100_000,
                            )
                            receipt_resolved = time.perf_counter()
                            if (
                                interaction.action_root in (
                                    CAPABILITY_RELATION_MEMBERS,
                                    CAPABILITY_TOPOLOGY,
                                    CAPABILITY_HISTORY,
                                    CAPABILITY_SCOPE,
                                )
                                and projection_mode not in (
                                    _TOPOLOGY_DELTA_MODE,
                                    _RECEIPT_MODE,
                                )
                            ):
                                raise InvalidCell(
                                    'topology-changing interactions require a '
                                    'topology projection delta'
                                )
                            if interaction.action_root in (
                                CAPABILITY_RELATION_FORM,
                                CAPABILITY_INSTANTIATE,
                            ):
                                if 'event_facts' not in body:
                                    raise InvalidCell(
                                        'interaction facts are missing'
                                    )
                                if (
                                    interaction.action_root
                                    == CAPABILITY_RELATION_FORM
                                ):
                                    created_root, touched = (
                                        submit_universal_relation_form_interaction(
                                            owner.universal_store,
                                            owner.universal_registry,
                                            owner.interaction_projection_broker,
                                            binding.interaction_projection_handle,
                                            interaction_root=body['interaction'],
                                            control_root=body['control'],
                                            event_root=body['event'],
                                            event_facts=body['event_facts'],
                                            expected_revision=body['revision'],
                                            projected_canvas=previous_projection,
                                            authentication_context=binding.context,
                                        )
                                    )
                                else:
                                    created_root, touched = (
                                        submit_universal_instantiation_interaction(
                                            owner.universal_store,
                                            owner.universal_registry,
                                            owner.interaction_projection_broker,
                                            binding.interaction_projection_handle,
                                            interaction_root=body['interaction'],
                                            control_root=body['control'],
                                            event_root=body['event'],
                                            event_facts=body['event_facts'],
                                            expected_revision=body['revision'],
                                            projected_canvas=previous_projection,
                                            authentication_context=binding.context,
                                        )
                                    )
                            elif interaction.action_root == CAPABILITY_EDIT_VALUE:
                                if 'event_facts' not in body:
                                    raise InvalidCell(
                                        'interaction facts are missing'
                                    )
                                execution = submit_universal_edit_value_interaction(
                                    owner.universal_store,
                                    owner.universal_registry,
                                    owner.interaction_projection_broker,
                                    binding.interaction_projection_handle,
                                    interaction_root=body['interaction'],
                                    control_root=body['control'],
                                    event_root=body['event'],
                                    event_facts=body['event_facts'],
                                    expected_revision=body['revision'],
                                    projected_canvas=previous_projection,
                                    authentication_context=binding.context,
                                )
                                touched = execution.revision
                            elif (
                                interaction.action_root
                                == CAPABILITY_RELATION_MEMBERS
                            ):
                                execution = (
                                    submit_universal_relation_member_interaction(
                                        owner.universal_store,
                                        owner.universal_registry,
                                        owner.interaction_projection_broker,
                                        binding.interaction_projection_handle,
                                        interaction_root=body['interaction'],
                                        control_root=body['control'],
                                        event_root=body['event'],
                                        event_facts=body.get('event_facts'),
                                        expected_revision=body['revision'],
                                        projected_canvas=previous_projection,
                                        authentication_context=binding.context,
                                    )
                                )
                                touched = execution.revision
                            elif interaction.action_root == CAPABILITY_TOPOLOGY:
                                execution = submit_universal_topology_interaction(
                                    owner.universal_store,
                                    owner.universal_registry,
                                    owner.interaction_projection_broker,
                                    binding.interaction_projection_handle,
                                    interaction_root=body['interaction'],
                                    control_root=body['control'],
                                    event_root=body['event'],
                                    event_facts=body.get('event_facts'),
                                    expected_revision=body['revision'],
                                    projected_canvas=previous_projection,
                                    authentication_context=binding.context,
                                )
                                touched = execution.revision
                                created_root = execution.created_root
                            elif interaction.action_root == CAPABILITY_HISTORY:
                                execution = submit_universal_history_interaction(
                                    owner.universal_store,
                                    owner.universal_registry,
                                    owner.interaction_projection_broker,
                                    binding.interaction_projection_handle,
                                    interaction_root=body['interaction'],
                                    control_root=body['control'],
                                    event_root=body['event'],
                                    event_facts=body.get('event_facts'),
                                    expected_revision=body['revision'],
                                    projected_canvas=previous_projection,
                                    authentication_context=binding.context,
                                )
                                touched = execution.revision
                            elif interaction.action_root == CAPABILITY_TRANSITION:
                                execution = submit_universal_transition_interaction(
                                    owner.universal_store,
                                    owner.universal_registry,
                                    owner.interaction_projection_broker,
                                    binding.interaction_projection_handle,
                                    interaction_root=body['interaction'],
                                    control_root=body['control'],
                                    event_root=body['event'],
                                    event_facts=body.get('event_facts'),
                                    expected_revision=body['revision'],
                                    projected_canvas=previous_projection,
                                    authentication_context=binding.context,
                                )
                                touched = execution.revision
                            elif interaction.action_root == CAPABILITY_COMPOSITION:
                                execution = submit_universal_composition_interaction(
                                    owner.universal_store,
                                    owner.universal_registry,
                                    owner.interaction_projection_broker,
                                    binding.interaction_projection_handle,
                                    interaction_root=body['interaction'],
                                    control_root=body['control'],
                                    event_root=body['event'],
                                    event_facts=body.get('event_facts'),
                                    expected_revision=body['revision'],
                                    projected_canvas=previous_projection,
                                    authentication_context=binding.context,
                                )
                                touched = execution.revision
                                created_root = execution.created_root
                            else:
                                if 'event_facts' in body:
                                    raise InvalidCell(
                                        'interaction carries undeclared event facts'
                                    )
                                if interaction.action_root == CAPABILITY_SCOPE:
                                    if len(interaction.input_roots) == 2:
                                        reusable_scope_projection = (
                                            owner._cached_browser_scope_projection(
                                                binding,
                                                interaction.input_roots[1],
                                                expected_lineage_revision=(
                                                    body['revision']
                                                ),
                                            )
                                        )
                                        if reusable_scope_projection is not None:
                                            reusable_scope_identity = (
                                                owner._cached_browser_scope_identity(
                                                    binding,
                                                    interaction.input_roots[1],
                                                    expected_lineage_revision=(
                                                        body['revision']
                                                    ),
                                                )
                                            )
                                    scope_execution = (
                                        submit_universal_scope_interaction(
                                        owner.universal_store,
                                        owner.universal_registry,
                                        owner.interaction_projection_broker,
                                        binding.interaction_projection_handle,
                                        interaction_root=body['interaction'],
                                        control_root=body['control'],
                                        event_root=body['event'],
                                        expected_revision=body['revision'],
                                        projected_canvas=previous_projection,
                                        reusable_scope_projection=(
                                            reusable_scope_projection
                                        ),
                                        reusable_scope_identity=(
                                            reusable_scope_identity
                                        ),
                                        authentication_context=binding.context,
                                    )
                                    )
                                    touched = scope_execution.revision
                                    scope_materialization = (
                                        scope_execution.materialization
                                    )
                                elif interaction.action_root == CAPABILITY_VIEW_SECTION:
                                    touched = (
                                        submit_universal_inspector_lens_interaction(
                                            owner.universal_store,
                                            owner.universal_registry,
                                            owner.interaction_projection_broker,
                                            binding.interaction_projection_handle,
                                            interaction_root=body['interaction'],
                                            control_root=body['control'],
                                            event_root=body['event'],
                                            expected_revision=body['revision'],
                                            projected_canvas=previous_projection,
                                            authentication_context=binding.context,
                                        )
                                    )
                                else:
                                    execution = execute_interaction(
                                        owner.universal_store,
                                        owner.universal_registry.interaction_protocol,
                                        owner.universal_registry.transaction_protocol,
                                        owner.universal_registry.rule_protocol,
                                        owner.universal_registry.authorization.protocol,
                                        owner.universal_registry.authorization.broker,
                                        binding.context,
                                        owner.interaction_projection_broker,
                                        binding.interaction_projection_handle,
                                        interaction_root=body['interaction'],
                                        control_root=body['control'],
                                        event_root=body['event'],
                                        expected_revision=body['revision'],
                                    )
                                    touched = execution.rewrite.revision
                            receipt_mutated = time.perf_counter()
                            self._universal_integrity()
                            receipt_integrity = time.perf_counter()
                            if projection_mode == _RECEIPT_MODE:
                                projected = {
                                    'projection_mode': _RECEIPT_MODE,
                                    'base_revision': body['revision'],
                                    'committed_revision': (
                                        owner.universal_store.revision
                                    ),
                                    'server_timing_ms': {
                                        'resolve': round(
                                            (receipt_resolved-receipt_started)
                                            * 1000, 3
                                        ),
                                        'mutation': round(
                                            (receipt_mutated-receipt_resolved)
                                            * 1000, 3
                                        ),
                                        'integrity': round(
                                            (receipt_integrity-receipt_mutated)
                                            * 1000, 3
                                        ),
                                        'total': round(
                                            (receipt_integrity-receipt_started)
                                            * 1000, 3
                                        ),
                                    },
                                }
                            else:
                                projection = (
                                    owner._project_interaction_canvas(
                                        binding,
                                        scope_materialization=(
                                            scope_materialization
                                        ),
                                        previous_projection=(
                                            previous_projection
                                        ),
                                        expected_base_revision=(
                                            body['revision']
                                        ),
                                    )
                                    if (
                                        interaction.action_root
                                        == CAPABILITY_SCOPE
                                        and scope_materialization is not None
                                    )
                                    else owner.project_interaction_canvas(
                                        binding
                                    )
                                )
                                if projection_mode == _INTERACTION_DELTA_MODE:
                                    projected = _interaction_canvas_delta(
                                        projection,
                                        base_revision=body['revision'],
                                        previous_projection=previous_projection,
                                    )
                                elif projection_mode == _TOPOLOGY_DELTA_MODE:
                                    projected = _topology_canvas_delta(
                                        projection,
                                        base_revision=body['revision'],
                                        previous_projection=(
                                            previous_projection
                                        ),
                                    )
                                else:
                                    projected = projection
                            payload = {
                                'ok': True,
                                'touched': touched,
                                **projected,
                            }
                            if projection_mode in (
                                _INTERACTION_DELTA_MODE,
                                _TOPOLOGY_DELTA_MODE,
                            ):
                                payload['committed_revision'] = (
                                    owner.universal_store.revision
                                )
                            if created_root is not None:
                                payload['created_root'] = created_root
                        self._json(200, payload)
                        return
                    if self.path == '/api/universal/theme-publish':
                        # The trusted browser court must load this same server.
                        # Do not hold the application lock while its independent
                        # browser request runs; the promotion function rechecks
                        # the exact Shared head and digest afterward.
                        created_root, evidence_root = \
                            promote_universal_theme_to_published(
                                owner.universal_store,
                                owner.universal_registry,
                                source_revision_root=body.get('revision'),
                                authentication_context=binding.context)
                        with owner.mutation_lock:
                            self._universal_integrity()
                            payload = {
                                'ok': True,
                                'touched': owner.universal_store.revision,
                                'created_root': created_root,
                                'evidence_root': evidence_root,
                            }
                            if body.get('projection', True):
                                payload.update(
                                    owner.project_interaction_canvas(binding)
                                )
                        self._json(200, payload)
                        return
                    with owner.mutation_lock:
                        if self.path.startswith('/api/universal/'):
                            created_root = None
                            evidence_root = None
                            projection_mode = body.get('projection_mode')
                            projection_revision = body.get('projection_revision')
                            if projection_mode is not None:
                                if (
                                    projection_mode not in (
                                        _INTERACTION_DELTA_MODE,
                                        _TOPOLOGY_DELTA_MODE,
                                        _RECEIPT_MODE,
                                    )
                                    or type(projection_revision) is not int
                                    or (
                                        projection_mode
                                        == _INTERACTION_DELTA_MODE
                                        and self.path != '/api/universal/gesture'
                                    )
                                    or (
                                        projection_mode == _TOPOLOGY_DELTA_MODE
                                        and self.path == '/api/universal/gesture'
                                    )
                                    or (
                                        projection_mode == _RECEIPT_MODE
                                        and self.path != '/api/universal/gesture'
                                    )
                                ):
                                    raise InvalidCell(
                                        'interaction delta request is invalid'
                                    )
                                if projection_revision != (
                                    owner.universal_store.revision
                                ):
                                    raise InvalidCell(
                                        'interaction delta projection is stale'
                                    )
                            previous_projection = (
                                owner._cached_browser_canvas_projection(
                                    binding, projection_revision
                                )
                                if projection_mode in (
                                    _INTERACTION_DELTA_MODE,
                                    _TOPOLOGY_DELTA_MODE,
                                    _RECEIPT_MODE,
                                )
                                else None
                            )
                            if (
                                projection_mode in (
                                    _INTERACTION_DELTA_MODE,
                                    _TOPOLOGY_DELTA_MODE,
                                    _RECEIPT_MODE,
                                )
                                and previous_projection is None
                            ):
                                raise InvalidCell(
                                    'interaction projection cache is unavailable'
                                )
                            if self.path == '/api/universal/select':
                                touched = set_universal_selection(
                                    owner.universal_store,
                                    owner.universal_registry,
                                    body.get('roots') or [],
                                    focus_root=body.get('focus'),
                                    consent_evidence_root=binding.session_root,
                                    authentication_context=binding.context)
                            elif self.path == '/api/universal/agent':
                                # The agentic composer: intent in, the same
                                # signed gestures out. The model can do
                                # nothing a founder's own click could not.
                                from .agent_composer import (
                                    run_agent_composer,
                                )
                                agent_result = run_agent_composer(
                                    owner.universal_store,
                                    owner.universal_registry,
                                    str(body.get('prompt', '')),
                                    authentication_context=binding.context,
                                )
                                self._json(200, agent_result)
                                return
                            elif self.path == '/api/universal/run-graph':
                                # The run wire: nodes whose graph-held
                                # engine property names an effect evaluate
                                # along their wires; answers land as each
                                # node's status through the governed write.
                                from .universal_pipeline import (
                                    run_universal_pipeline,
                                )
                                def _baboom_presence(_params, _feeds):
                                    presence = (
                                        owner
                                        ._machine_agent_runtime_presence()
                                    )
                                    live = bool(
                                        presence.get("baboom_connected")
                                    )
                                    return (
                                        {"out": presence},
                                        "companion %s · %d signed runtime "
                                        "session(s)" % (
                                            "ATTACHED" if live
                                            else "not attached",
                                            presence[
                                                "active_runtime_sessions"
                                            ],
                                        ),
                                    )
                                run_result = run_universal_pipeline(
                                    owner.universal_store,
                                    owner.universal_registry,
                                    effect_engines={
                                        **(
                                            owner.pipeline_effect_engines
                                            or {}
                                        ),
                                        "baboom.presence": _baboom_presence,
                                    },
                                    authentication_context=binding.context,
                                )
                                self._json(200, run_result)
                                return
                            elif self.path == '/api/universal/login':
                                from .cell_accounts import (
                                    ensure_accounts,
                                    founder_email,
                                    upsert_account,
                                )
                                ensure_accounts(
                                    owner.universal_store,
                                    founder_email=(
                                        'ahmed.fargaly98@gmail.com'
                                    ),
                                )
                                _root, mail, tier = upsert_account(
                                    owner.universal_store,
                                    body.get('email'),
                                )
                                self._json(200, {
                                    'ok': True, 'email': mail, 'tier': tier,
                                    'founder': mail == founder_email(
                                        owner.universal_store.snapshot()
                                    ),
                                })
                                return
                            elif self.path == '/api/universal/accounts':
                                from .cell_accounts import read_accounts
                                self._json(200, {
                                    'ok': True,
                                    'accounts': read_accounts(
                                        owner.universal_store.snapshot()
                                    ),
                                })
                                return
                            elif self.path == '/api/universal/account-tier':
                                from .cell_accounts import set_tier
                                tier = set_tier(
                                    owner.universal_store,
                                    body.get('email'),
                                    str(body.get('tier') or ''),
                                )
                                self._json(200, {'ok': True, 'tier': tier})
                                return
                            elif self.path == '/api/universal/pick-file':
                                picker = getattr(
                                    owner, 'native_file_picker', None
                                )
                                if picker is None:
                                    self._json(200, {
                                        'ok': True, 'path': '',
                                        'note': 'no native picker in this '
                                                'runtime',
                                    })
                                    return
                                chosen = picker(
                                    str(body.get('title') or 'Choose a file'),
                                    str(body.get('filter') or ''),
                                )
                                self._json(200, {
                                    'ok': True, 'path': str(chosen or ''),
                                })
                                return
                            elif self.path == '/api/universal/set-property':
                                from .universal_application import (
                                    edit_universal_property,
                                )
                                value_root = edit_universal_property(
                                    owner.universal_store,
                                    owner.universal_registry,
                                    str(body.get('relation') or ''),
                                    str(body.get('value', '')),
                                    mutation_route=(
                                        '/api/universal/set-property'
                                    ),
                                    authentication_context=binding.context,
                                )
                                self._json(200, {
                                    'ok': True,
                                    'value_root': value_root,
                                    'revision': (
                                        owner.universal_store.revision
                                    ),
                                })
                                return
                            elif self.path == '/api/universal/pipeline-seed':
                                from .universal_pipeline import (
                                    seed_wall_pipeline,
                                )
                                seed_result = seed_wall_pipeline(
                                    owner.universal_store,
                                    owner.universal_registry,
                                    image_path=(
                                        str(body.get('image_path') or '')
                                        or None
                                    ),
                                    authentication_context=binding.context,
                                )
                                self._json(200, seed_result)
                                return
                            elif self.path == '/api/universal/move':
                                touched = move_universal_root(
                                    owner.universal_store,
                                    owner.universal_registry,
                                    body['root'], float(body['x']), float(body['y']),
                                    authentication_context=binding.context)
                            elif self.path == '/api/universal/gesture':
                                touched = apply_universal_canvas_gesture(
                                    owner.universal_store,
                                    owner.universal_registry,
                                    roots=body.get('roots'),
                                    focus_root=body.get('focus'),
                                    positions=body.get('positions'),
                                    viewport=body.get('viewport'),
                                    consent_evidence_root=binding.session_root,
                                    authentication_context=binding.context,
                                    leased_projection=previous_projection)
                            elif self.path == '/api/universal/instantiate':
                                raw_bindings = body.get('bindings')
                                if body.get('primitive') is True:
                                    raise InvalidCell(
                                        'primitive placement requires a graph '
                                        'Interaction lease'
                                    )
                                elif raw_bindings is None:
                                    raise InvalidCell(
                                        'ordinary catalogue placement requires '
                                        'a graph Interaction lease'
                                    )
                                else:
                                    if (
                                        type(raw_bindings) is not list
                                        or not raw_bindings
                                        or len(raw_bindings) > 256
                                    ):
                                        raise InvalidCell(
                                            'relation bindings must be a non-empty bounded list'
                                        )
                                    parsed_bindings = []
                                    for item in raw_bindings:
                                        if (
                                            type(item) is not dict
                                            or set(item) != {'role', 'participant'}
                                            or type(item['role']) is not str
                                            or type(item['participant']) is not str
                                            or not item['role']
                                            or not item['participant']
                                            or len(item['role']) > 4096
                                            or len(item['participant']) > 4096
                                        ):
                                            raise InvalidCell(
                                                'relation binding payload is invalid'
                                            )
                                        parsed_bindings.append((
                                            item['role'], item['participant']
                                        ))
                                    created_root, touched = \
                                        instantiate_universal_relation_definition(
                                            owner.universal_store,
                                            owner.universal_registry,
                                            body['definition'],
                                            tuple(parsed_bindings),
                                            x=float(body['x']),
                                            y=float(body['y']),
                                            authentication_context=binding.context)
                            elif self.path == '/api/universal/lifecycle-wip':
                                created_root, touched = \
                                    edit_universal_lifecycle_content(
                                        owner.universal_store,
                                        owner.universal_registry,
                                        body['root'],
                                        body['interface'],
                                        str(body.get('value', '')),
                                        base_revision_root=body['base'],
                                        authentication_context=binding.context)
                            elif self.path == '/api/universal/lifecycle-merge':
                                created_root, evidence_root, touched = \
                                    merge_universal_lifecycle_content(
                                        owner.universal_store,
                                        owner.universal_registry,
                                        body['root'],
                                        body['interface'],
                                        str(body.get('value', '')),
                                        parent_revision_roots=tuple(
                                            body.get('parents') or ()),
                                        authentication_context=binding.context)
                            elif self.path == '/api/universal/transition':
                                touched = transition_universal_operational_state(
                                    owner.universal_store,
                                    owner.universal_registry,
                                    body['root'], body['event'], body['expected'],
                                    evidence_roots=tuple(body.get('evidence') or ()),
                                    authentication_context=binding.context)
                            elif self.path == '/api/universal/execute-adapter':
                                execution = execute_universal_adapter_request(
                                    owner.universal_store,
                                    owner.universal_registry,
                                    body['root'],
                                    consent_broker=owner.adapter_consent_broker,
                                    key_factory=owner.device_key_factory,
                                    authentication_context=binding.context)
                                touched = execution.revision
                                created_root = execution.custody_root
                                evidence_root = execution.receipt_evidence_root
                            elif self.path == '/api/universal/resource-promote':
                                created_root, evidence_root, touched = \
                                    promote_universal_resource_lifecycle(
                                        owner.universal_store,
                                        owner.universal_registry,
                                        body['root'],
                                        body['target'],
                                        source_revision_root=body.get('source'),
                                        authentication_context=binding.context)
                            elif self.path == '/api/universal/theme-share':
                                created_root, evidence_root = \
                                    promote_universal_theme_to_shared(
                                        owner.universal_store,
                                        owner.universal_registry,
                                        source_revision_root=body.get('revision'),
                                        authentication_context=binding.context)
                                touched = owner.universal_store.revision
                            elif self.path == '/api/universal/authority-issue':
                                expires_at = body.get('expires_at')
                                created_root, touched = \
                                    issue_universal_authority_relationship(
                                        owner.universal_store,
                                        owner.universal_registry,
                                        source_root=body['source'],
                                        target_root=body['target'],
                                        kind=body['kind'],
                                        scope_root=body.get('scope'),
                                        action_roots=tuple(body.get('actions') or ()),
                                        expires_at=(
                                            float(expires_at)
                                            if expires_at is not None else None
                                        ),
                                        reason=str(body.get('reason', '')).strip(),
                                        evidence_roots=tuple(
                                            body.get('evidence') or ()
                                        ),
                                        relationship_root=body.get('relationship'),
                                        authentication_context=binding.context)
                            elif self.path == '/api/universal/authority-revoke':
                                touched = revoke_universal_authority_relationship(
                                    owner.universal_store,
                                    owner.universal_registry,
                                    body['relationship'],
                                    reason=str(body.get('reason', '')).strip(),
                                    authentication_context=binding.context)
                            else:
                                self._json(404, {'ok': False, 'error': 'not found'})
                                return
                            payload = {'ok': True, 'touched': touched}
                            self._universal_integrity()
                            if created_root is not None:
                                payload['created_root'] = created_root
                            if evidence_root is not None:
                                payload['evidence_root'] = evidence_root
                            if projection_mode == _RECEIPT_MODE:
                                payload.update({
                                    'projection_mode': _RECEIPT_MODE,
                                    'base_revision': projection_revision,
                                    'committed_revision': (
                                        owner.universal_store.revision
                                    ),
                                })
                            elif body.get('projection', True):
                                projection = owner.project_interaction_canvas(
                                    binding
                                )
                                if projection_mode == _INTERACTION_DELTA_MODE:
                                    projected = _interaction_canvas_delta(
                                        projection,
                                        base_revision=projection_revision,
                                        previous_projection=previous_projection,
                                    )
                                elif projection_mode == _TOPOLOGY_DELTA_MODE:
                                    projected = _topology_canvas_delta(
                                        projection,
                                        base_revision=projection_revision,
                                        previous_projection=previous_projection,
                                    )
                                else:
                                    projected = projection
                                payload.update(projected)
                            self._json(200, payload)
                            return
                        if binding.subject_root != (
                            owner.universal_registry.authorization.subject_root
                        ):
                            self._json(403, {
                                'ok': False,
                                'error': 'legacy mutation routes are founder-only',
                            })
                            return
                        if not owner.allow_legacy_mutations:
                            self._json(403, {
                                'ok': False,
                                'error': 'legacy mutation routes are disabled; '
                                         'use the governed universal catalogue',
                            })
                            return
                        transaction = body.get('transaction') or uuid.uuid4().hex
                        if self.path == '/api/activate':
                            touched = activate_ui(
                                owner.store, body['ui_id'],
                                command_handler=lambda operation: owner.execute_command(
                                    operation, input_value=body.get('input_value')),
                                transaction=transaction,
                                event=body.get('event', 'activate'))
                        elif self.path == '/api/edit':
                            touched = edit_ui_binding(owner.store, body['ui_id'], body.get('value', ''),
                                                      port=body.get('port', 'value'),
                                                      transaction=transaction)
                        elif self.path == '/api/batch':
                            operations = body.get('operations')
                            if not isinstance(operations, list) or not operations \
                                    or len(operations) > 32:
                                raise ValueError('batch requires 1..32 graph UI operations')
                            touched = []
                            for item in operations:
                                if not isinstance(item, dict):
                                    raise ValueError('batch operation must be a mapping')
                                if item.get('kind') == 'activate':
                                    touched.append(activate_ui(
                                        owner.store, item['ui_id'],
                                        command_handler=lambda operation, item=item:
                                        owner.execute_command(
                                            operation,
                                            input_value=item.get('input_value')),
                                        transaction=transaction,
                                        event=item.get('event', 'activate')))
                                elif item.get('kind') == 'edit':
                                    touched.append(edit_ui_binding(
                                        owner.store, item['ui_id'], item.get('value', ''),
                                        port=item.get('port', 'value'),
                                        transaction=transaction))
                                else:
                                    raise ValueError('unsupported batch operation kind')
                        else:
                            self._json(404, {'ok': False, 'error': 'not found'})
                            return
                        owner.request_snapshot()
                        payload = {'ok': True, 'touched': touched}
                        if body.get('projection', True):
                            payload['projection'] = project_document(
                                owner.store, owner.registry['app'],
                                owner.registry['ui_root'])
                    self._json(200, payload)
                except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
                    return
                except InteractionProjectionExpired as exc:
                    self._json(409, {
                        'ok': False,
                        'error': str(exc),
                        'code': 'projection_lease_expired',
                        'retryable': True,
                    })
                except AuthorizationDenied as exc:
                    self._json(403, {'ok': False, 'error': str(exc)})
                except Exception as exc:
                    self._json(400, {'ok': False, 'error': str(exc)})

        self.httpd = QuietThreadingHTTPServer((host, port), Handler)
        if enable_universal_cloud_gateway:
            (
                self.universal_cloud_gateway,
                self.universal_cloud_server,
            ) = self.build_universal_cloud_tls_server(
                resource_origin=self._validated_universal_cloud_origin,
                certificate_file=(
                    self._validated_universal_cloud_listener.certificate_file
                ),
                private_key_file=(
                    self._validated_universal_cloud_listener.private_key_file
                ),
                nonce_key_provider=cloud_nonce_key_provider,
                nonce_key_id=cloud_nonce_key_id,
            )
        if enable_machine_transport:
            transport_key_provider = machine_key_provider or (
                WindowsDpapiSigningKeyProvider(
                    WindowsDpapiSigningKeyProvider.default_path()
                )
            )
            self.machine_transport = UniversalRuntimeTransport(
                self.dispatch_universal_machine_route,
                application_root=self.universal_registry.application_root,
                agent_session_root=(
                    self.universal_registry.agent_body.session.root_id
                ),
                workshop_root=self.universal_registry.workshop_root,
                work_registry_root=(
                    self.universal_registry.governed_work_registry_root
                ),
                database=(
                    str(self.universal_state_path)
                    if self.universal_state_path is not None else ""
                ),
                descriptor_path=machine_descriptor_path,
                key_provider=transport_key_provider,
                after_response=self._after_universal_machine_response,
            )
        self.thread = None
        self._live_stop = threading.Event()
        self._live_thread = None
        if live_watch and legacy_runtime_enabled:
            self._live_thread = threading.Thread(
                target=self._live_loop, name='archhub-live-watcher', daemon=True)
            self._live_thread.start()

    @staticmethod
    def _browser_token_digest(token: str) -> str:
        return hashlib.sha256(str(token).encode("utf-8")).hexdigest()

    @staticmethod
    def _validate_public_server_url(value):
        if value is None:
            return None
        if type(value) is not str:
            raise ValueError("public runtime origin must be text")
        parsed = urlsplit(value)
        if (
            parsed.scheme != "http"
            or parsed.hostname != "127.0.0.1"
            or parsed.port is None
            or parsed.username
            or parsed.password
            or parsed.path not in ("", "/")
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError(
                "public runtime origin must be a bare numeric loopback URL"
            )
        return "http://127.0.0.1:%d" % int(parsed.port)

    def _runtime_owner_attestation_inputs(
        self, phase: str
    ) -> tuple[dict[str, str], bytes]:
        durable = self.universal_store.is_durable
        authority_identity = (
            self.universal_store.authority_identity
            if durable
            else "isolated-memory"
        )
        parameters = {
            "mode": "persistent" if durable else "memory",
            "databaseIdentity": hashlib.sha256(
                authority_identity.encode("utf-8")
            ).hexdigest(),
            "processId": str(os.getpid()),
            "phase": phase,
        }
        content = (
            self.universal_registry.application_root
            + "\n"
            + self._runtime_holder_root
            + "\n"
            + phase
        ).encode("utf-8")
        return parameters, content

    def _runtime_owner_evidence(self, phase: str) -> str:
        parameters, content = self._runtime_owner_attestation_inputs(phase)
        evidence_root = self.universal_registry.attestation_broker.run(
            self.universal_store,
            self.universal_registry.attestation_protocol,
            self.universal_registry.runtime_ownership_court_root,
            subject_name=self._runtime_holder_root,
            subject_content=content,
            external_parameters=parameters,
        )
        self.universal_registry.attestation_broker.verify(
            self.universal_store.snapshot(),
            self.universal_registry.attestation_protocol,
            evidence_root,
            expected_court_root=(
                self.universal_registry.runtime_ownership_court_root
            ),
            expected_subject_name=self._runtime_holder_root,
            expected_subject_digest=hashlib.sha256(content).hexdigest(),
            expected_parameters=parameters,
            expected_result="pass",
            max_age_seconds=60.0,
        )
        return evidence_root

    def prove_runtime_backend_generation(self) -> BackendGeneration:
        """Read and verify the active Cell owner before gateway admission."""
        if self.thread is None or not self.thread.is_alive():
            raise InvalidCell("runtime backend is not serving")
        if self.universal_store.supports_shared_writers:
            self.universal_store.refresh()
        snapshot = self.universal_store.snapshot()
        ownerships = verify_ownership_authority(
            snapshot, self.universal_registry.ownership_protocol
        )
        current = tuple(
            ownership for ownership in ownerships
            if ownership.root_id == self._runtime_ownership_root
        )
        if len(current) != 1:
            raise InvalidCell("runtime ownership root is not authoritative")
        ownership = current[0]
        if (
            ownership.resource_root != self.universal_registry.application_root
            or ownership.holder_root != self._runtime_holder_root
            or ownership.state_root
            != self.universal_registry.ownership_protocol.states["active"]
        ):
            raise InvalidCell("runtime ownership is not active for this worker")
        parameters, content = self._runtime_owner_attestation_inputs("acquire")
        if not ownership.evidence_roots:
            raise InvalidCell("runtime ownership has no signed evidence")
        self.universal_registry.attestation_broker.verify(
            snapshot,
            self.universal_registry.attestation_protocol,
            ownership.evidence_roots[0],
            expected_court_root=(
                self.universal_registry.runtime_ownership_court_root
            ),
            expected_subject_name=self._runtime_holder_root,
            expected_subject_digest=hashlib.sha256(content).hexdigest(),
            expected_parameters=parameters,
            expected_result="pass",
        )
        if (
            self.universal_store.is_durable
            and not (
                self.universal_store.has_exclusive_database_owner
                or self.universal_store.supports_shared_writers
            )
        ):
            raise InvalidCell("runtime durable authority is not admitted")
        return BackendGeneration(
            self.url, ownership.generation, ownership.root_id
        )

    def _claim_runtime_ownership(self) -> None:
        snapshot = self.universal_store.snapshot()
        live_states = {
            self.universal_registry.ownership_protocol.states["active"],
            self.universal_registry.ownership_protocol.states["draining"],
        }
        stale = tuple(
            ownership for ownership in verify_ownership_authority(
                snapshot,
                self.universal_registry.ownership_protocol,
            )
            if ownership.resource_root
            == self.universal_registry.application_root
            and ownership.state_root in live_states
        )
        if stale and not self.universal_store.is_durable:
            raise InvalidCell(
                "in-memory application already has a live runtime owner"
            )
        evidence_root = self._runtime_owner_evidence("acquire")
        snapshot = self.universal_store.snapshot()
        holder = Cell(
            self._runtime_holder_root,
            NULL_CELL_ID,
            NULL_CELL_ID,
            uuid.uuid4().hex.encode("ascii"),
        )
        self.universal_store.commit(snapshot.revision, create=(holder,))
        if stale:
            recovery_evidence = self._runtime_owner_evidence("recover")
            for ownership in stale:
                event = (
                    "fail-active"
                    if ownership.state_root
                    == self.universal_registry.ownership_protocol.states["active"]
                    else "fail-draining"
                )
                transition_ownership(
                    self.universal_store,
                    self.universal_registry.ownership_protocol,
                    ownership.root_id,
                    event=event,
                    evidence_root=recovery_evidence,
                )
        ownership, _revision = acquire_ownership(
            self.universal_store,
            self.universal_registry.ownership_protocol,
            resource_root=self.universal_registry.application_root,
            holder_root=self._runtime_holder_root,
            evidence_root=evidence_root,
        )
        self._runtime_ownership_root = ownership.root_id

    def _begin_runtime_drain(self) -> None:
        if self._runtime_ownership_root is None:
            return
        ownership = read_ownership(
            self.universal_store.snapshot(),
            self.universal_registry.ownership_protocol,
            self._runtime_ownership_root,
        )
        if ownership.state_root != (
            self.universal_registry.ownership_protocol.states["active"]
        ):
            return
        evidence_root = self._runtime_owner_evidence("drain")
        transition_ownership(
            self.universal_store,
            self.universal_registry.ownership_protocol,
            self._runtime_ownership_root,
            event="drain",
            evidence_root=evidence_root,
        )

    def _release_runtime_ownership(self) -> None:
        if self._runtime_ownership_root is None:
            return
        ownership = read_ownership(
            self.universal_store.snapshot(),
            self.universal_registry.ownership_protocol,
            self._runtime_ownership_root,
        )
        if ownership.state_root != (
            self.universal_registry.ownership_protocol.states["draining"]
        ):
            return
        evidence_root = self._runtime_owner_evidence("release")
        transition_ownership(
            self.universal_store,
            self.universal_registry.ownership_protocol,
            self._runtime_ownership_root,
            event="release",
            evidence_root=evidence_root,
        )

    def _prove_runtime_backend_state(self, state: str) -> BackendGeneration:
        """Verify this worker and every signed transition to one exact state."""
        if state not in {"active", "draining", "released"}:
            raise InvalidCell("runtime backend state is invalid")
        if self.thread is None or not self.thread.is_alive():
            raise InvalidCell("runtime backend is not serving")
        if self.universal_store.supports_shared_writers:
            self.universal_store.refresh()
        snapshot = self.universal_store.snapshot()
        ownerships = verify_ownership_authority(
            snapshot, self.universal_registry.ownership_protocol
        )
        current = tuple(
            ownership for ownership in ownerships
            if ownership.root_id == self._runtime_ownership_root
        )
        if len(current) != 1:
            raise InvalidCell("runtime ownership root is not authoritative")
        ownership = current[0]
        if (
            ownership.resource_root != self.universal_registry.application_root
            or ownership.holder_root != self._runtime_holder_root
            or ownership.state_root
            != self.universal_registry.ownership_protocol.states[state]
        ):
            raise InvalidCell("runtime ownership state does not match this worker")
        if len(ownership.evidence_roots) != 1:
            raise InvalidCell("runtime ownership acquisition evidence is ambiguous")
        parameters, content = self._runtime_owner_attestation_inputs("acquire")
        self.universal_registry.attestation_broker.verify(
            snapshot,
            self.universal_registry.attestation_protocol,
            ownership.evidence_roots[0],
            expected_court_root=(
                self.universal_registry.runtime_ownership_court_root
            ),
            expected_subject_name=self._runtime_holder_root,
            expected_subject_digest=hashlib.sha256(content).hexdigest(),
            expected_parameters=parameters,
            expected_result="pass",
        )
        expected_phases = {
            "active": (),
            "draining": ("drain",),
            "released": ("drain", "release"),
        }[state]
        if len(ownership.transition_roots) != len(expected_phases):
            raise InvalidCell("runtime ownership transition history drifted")
        for transition_root, phase in zip(
            ownership.transition_roots, expected_phases
        ):
            transition = read_ownership_transition(
                snapshot,
                self.universal_registry.ownership_protocol,
                transition_root,
            )
            parameters, content = self._runtime_owner_attestation_inputs(phase)
            self.universal_registry.attestation_broker.verify(
                snapshot,
                self.universal_registry.attestation_protocol,
                transition.evidence_root,
                expected_court_root=(
                    self.universal_registry.runtime_ownership_court_root
                ),
                expected_subject_name=self._runtime_holder_root,
                expected_subject_digest=hashlib.sha256(content).hexdigest(),
                expected_parameters=parameters,
                expected_result="pass",
            )
        if (
            self.universal_store.is_durable
            and not (
                self.universal_store.has_exclusive_database_owner
                or self.universal_store.supports_shared_writers
            )
        ):
            raise InvalidCell("runtime durable authority is not admitted")
        return BackendGeneration(
            self.url, ownership.generation, ownership.root_id
        )

    @property
    def runtime_handoff_exit_requested(self) -> bool:
        return self._runtime_handoff_exit.is_set()

    def _after_universal_machine_response(
        self,
        request: Mapping[str, object],
        response: Mapping[str, object],
    ) -> None:
        result = response.get("result")
        if (
            request.get("method") == "POST"
            and request.get("path") == "/api/universal/runtime-handoff"
            and isinstance(result, Mapping)
            and result.get("phase") == "released"
            and result.get("signal_after_response") is True
        ):
            self._runtime_handoff_exit.set()

    def _register_browser_session(
        self,
        token: str,
        csrf_token: str,
        authentication_context: object,
        *,
        lifetime_seconds: float,
    ) -> _BrowserSessionBinding:
        if lifetime_seconds <= 0 or lifetime_seconds > 3600:
            raise ValueError("browser session lifetime must be within one hour")
        authority = self.universal_registry.authorization
        identity = authority.broker.resolve(authentication_context)
        view = self.universal_registry.view_sessions.get(identity.subject_root)
        if view is None:
            raise AuthorizationDenied(
                "browser subject has no provisioned application view"
            )
        if identity.tenant_root is None:
            raise AuthorizationDenied(
                "browser subject has no authenticated tenant"
            )
        now = time.time()
        effective_lifetime = min(
            float(lifetime_seconds), identity.expires_at - now
        )
        if effective_lifetime <= 0:
            raise AuthorizationDenied("authenticated context expired")
        with self.mutation_lock:
            session_root, _revision = issue_browser_session_relation(
                self.universal_store,
                self.universal_registry.browser_session_protocol,
                subject_root=identity.subject_root,
                view_root=view.root_id,
                tenant_root=identity.tenant_root,
                assurance_root=identity.assurance_root,
                token_digest=self._browser_token_digest(token),
                csrf_digest=self._browser_token_digest(csrf_token),
                issued_at=now,
                lifetime_seconds=effective_lifetime,
            )
            interaction_projection_handle = (
                self.interaction_projection_broker.mint(
                    self.universal_store.snapshot(),
                    session_root=session_root,
                    subject_root=identity.subject_root,
                    view_root=view.root_id,
                    require_released=False,
                )
            )
        binding = _BrowserSessionBinding(
            session_root,
            identity.subject_root,
            view.root_id,
            identity.tenant_root,
            identity.assurance_root,
            authentication_context,
            csrf_token,
            interaction_projection_handle,
        )
        # A binding whose graph session is no longer active is dead weight
        # that never leaves: entries were added here and at recovery, and
        # removed only at shutdown, so every expired sign-in pinned its
        # whole held projection for the life of the process. Minting is
        # when the dict grows, so minting is when the dead are buried.
        protocol = self.universal_registry.browser_session_protocol
        with self._browser_session_lock:
            held = dict(self._browser_sessions)
        stale = []
        snapshot = self.universal_store.snapshot()
        for digest, candidate in held.items():
            try:
                session = read_browser_session(
                    snapshot, protocol, candidate.session_root
                )
            except Exception:
                stale.append(digest)
                continue
            if session.state_root != protocol.states["active"]:
                stale.append(digest)
        with self._browser_session_lock:
            for digest in stale:
                self._browser_sessions.pop(digest, None)
            self._browser_sessions[self._browser_token_digest(token)] = binding
        return binding

    def issue_browser_session(
        self,
        authentication_context: object,
        *,
        lifetime_seconds: float = 900.0,
    ) -> tuple[str, str]:
        """Bind an already-authenticated graph subject to an opaque browser."""
        token = secrets.token_urlsafe(32)
        csrf_token = secrets.token_urlsafe(32)
        self._register_browser_session(
            token,
            csrf_token,
            authentication_context,
            lifetime_seconds=lifetime_seconds,
        )
        return token, csrf_token

    def _recover_browser_session(self) -> _BrowserSessionBinding | None:
        """Rebind one DPAPI-held browser capability to its active graph session."""
        if self.browser_credential_custody_id is None:
            return None
        authority = self.universal_registry.authorization
        context = authority.session.context()
        identity = authority.broker.resolve(context)
        view = self.universal_registry.view_sessions[identity.subject_root]
        recovered = []
        for session_root in list_browser_session_roots(
            self.universal_store.snapshot(),
            self.universal_registry.browser_session_protocol,
        ):
            try:
                session = verify_browser_session(
                    self.universal_store.snapshot(),
                    self.universal_registry.browser_session_protocol,
                    session_root,
                    token=self.browser_session_token,
                    csrf_token=self.browser_csrf_token,
                    require_csrf=True,
                )
            except (BrowserSessionDenied, InvalidCell):
                continue
            if (
                session.subject_root == identity.subject_root
                and session.view_root == view.root_id
                and session.tenant_root == identity.tenant_root
                and session.assurance_root == identity.assurance_root
            ):
                recovered.append(session)
        if len(recovered) > 1:
            raise InvalidCell("browser credential matches multiple active sessions")
        if not recovered:
            return None
        session = recovered[0]
        interaction_handle = self.interaction_projection_broker.mint(
            self.universal_store.snapshot(),
            session_root=session.root_id,
            subject_root=session.subject_root,
            view_root=session.view_root,
            require_released=False,
        )
        binding = _BrowserSessionBinding(
            session.root_id,
            session.subject_root,
            session.view_root,
            session.tenant_root,
            session.assurance_root,
            context,
            self.browser_csrf_token,
            interaction_handle,
        )
        with self._browser_session_lock:
            self._browser_sessions[
                self._browser_token_digest(self.browser_session_token)
            ] = binding
        return binding

    def _revoke_orphaned_browser_sessions(
        self, preserve_root: str | None = None
    ) -> None:
        """Close sessions whose process-held credentials cannot survive restart."""
        protocol = self.universal_registry.browser_session_protocol
        for session_root in list_browser_session_roots(
            self.universal_store.snapshot(), protocol
        ):
            if session_root == preserve_root:
                continue
            session = read_browser_session(
                self.universal_store.snapshot(), protocol, session_root
            )
            if session.state_root == protocol.states["active"]:
                revoke_browser_session(
                    self.universal_store,
                    protocol,
                    session_root,
                    reason="Owning application process ended before recovery",
                )

    def _consume_browser_bootstrap(self, token: str) -> bool:
        with self._browser_session_lock:
            expected = self.browser_bootstrap_token
            if not expected or not token or not secrets.compare_digest(
                token, expected
            ):
                return False
            self.browser_bootstrap_token = None
            return True

    def _resolve_browser_session(
        self,
        token: str,
        *,
        csrf_token: str | None = None,
        require_csrf: bool = False,
    ) -> _BrowserSessionBinding:
        digest = self._browser_token_digest(token)
        with self._browser_session_lock:
            binding = self._browser_sessions.get(digest)
        if binding is None:
            raise AuthorizationDenied("browser session is unknown")
        try:
            session = verify_browser_session(
                self.universal_store.snapshot(),
                self.universal_registry.browser_session_protocol,
                binding.session_root,
                token=token,
                csrf_token=csrf_token,
                require_csrf=require_csrf,
            )
        except (BrowserSessionDenied, InvalidCell) as exc:
            raise AuthorizationDenied(str(exc)) from exc
        identity = self.universal_registry.authorization.broker.resolve(
            binding.context
        )
        expected = (
            binding.subject_root,
            binding.view_root,
            binding.tenant_root,
            binding.assurance_root,
        )
        actual = (
            session.subject_root,
            session.view_root,
            session.tenant_root,
            session.assurance_root,
        )
        identity_authority = (
            identity.subject_root,
            self.universal_registry.view_sessions[
                identity.subject_root
            ].root_id,
            identity.tenant_root,
            identity.assurance_root,
        )
        if actual != expected or identity_authority != expected:
            raise AuthorizationDenied("browser session authority drifted")
        return binding

    def _issue_universal_machine_agent_session_challenge(
        self,
        body: dict[str, object],
        *,
        runtime_id: str,
    ) -> dict[str, object]:
        if set(body) != {"runtime"}:
            raise InvalidCell("Agent Session challenge shape is invalid")
        runtime = body["runtime"]
        if (
            type(runtime) is not str
            or not runtime.strip()
            or len(runtime.encode("utf-8")) > 128
        ):
            raise InvalidCell("Agent Session challenge runtime is invalid")
        entry = _agent_body_catalog_entry_for_runtime(
            self.universal_store.snapshot(),
            self.universal_registry,
            runtime.strip(),
        )
        if entry.credential_mode != "device-proof":
            raise AuthorizationDenied(
                "runtime Agent Body does not require a device-proof challenge"
            )
        now = time.time()
        challenge_id = uuid.uuid4().hex
        nonce = secrets.token_urlsafe(32)
        expires_at = now + 90.0
        with self._machine_agent_session_lock:
            stale = tuple(
                root for root, challenge in self._machine_agent_challenges.items()
                if now >= float(challenge["expires_at"])
            )
            for root in stale:
                self._machine_agent_challenges.pop(root, None)
            self._machine_agent_challenges[challenge_id] = {
                "catalog_entry": entry.root_id,
                "runtime": runtime.strip(),
                "runtime_id": runtime_id,
                "nonce": nonce,
                "expires_at": expires_at,
                "used": False,
            }
        return {
            "challenge_id": challenge_id,
            "nonce": nonce,
            "runtime": runtime.strip(),
            "runtime_id": runtime_id,
            "catalog_entry": entry.root_id,
            "expires_at": expires_at,
        }

    @staticmethod
    def _decode_device_signature(value: object) -> bytes:
        if type(value) is not str or not value or len(value) > 1024:
            raise AuthorizationDenied("runtime device proof signature is invalid")
        try:
            raw = base64.urlsafe_b64decode(
                value + "=" * ((4 - len(value) % 4) % 4)
            )
        except (ValueError, TypeError) as exc:
            raise AuthorizationDenied(
                "runtime device proof signature is invalid"
            ) from exc
        if len(raw) != 64:
            raise AuthorizationDenied("runtime device proof signature is invalid")
        return raw

    def _verify_universal_runtime_device_credential(
        self,
        credential: object,
        *,
        runtime: str,
        external_session_id: str,
        runtime_id: str,
        catalog_entry_root: str,
    ) -> str:
        if type(credential) is not dict or set(credential) != {
            "challenge_id", "custody_root", "signature"
        }:
            raise AuthorizationDenied("runtime device credential is invalid")
        challenge_id = credential["challenge_id"]
        custody_root = credential["custody_root"]
        if type(challenge_id) is not str or type(custody_root) is not str:
            raise AuthorizationDenied("runtime device credential is invalid")
        now = time.time()
        with self._machine_agent_session_lock:
            challenge = self._machine_agent_challenges.get(challenge_id)
            if (
                challenge is None
                or bool(challenge["used"])
                or now >= float(challenge["expires_at"])
                or challenge["catalog_entry"] != catalog_entry_root
                or challenge["runtime"] != runtime
                or challenge["runtime_id"] != runtime_id
            ):
                raise AuthorizationDenied("runtime device proof challenge is invalid")
        snapshot = self.universal_store.snapshot()
        entry = _agent_body_catalog_entry_for_runtime(
            snapshot, self.universal_registry, runtime
        )
        if (
            entry.root_id != catalog_entry_root
            or custody_root not in entry.device_custody_roots
        ):
            raise AuthorizationDenied("runtime device custody is not catalog-bound")
        custody = read_device_custody(
            snapshot, self.universal_registry.device_custody_protocol, custody_root
        )
        if custody.state_root != self.universal_registry.device_custody_protocol.states["active"]:
            raise AuthorizationDenied("runtime device custody is revoked")
        try:
            document = snapshot.cells[custody.public_jwk_root].atom.decode("utf-8")
            public_jwk = json.loads(document)
            x = base64.urlsafe_b64decode(str(public_jwk["x"]) + "==")
            y = base64.urlsafe_b64decode(str(public_jwk["y"]) + "==")
            public_key = ec.EllipticCurvePublicNumbers(
                int.from_bytes(x, "big"),
                int.from_bytes(y, "big"),
                ec.SECP256R1(),
            ).public_key()
            signature = self._decode_device_signature(credential["signature"])
            public_key.verify(
                utils.encode_dss_signature(
                    int.from_bytes(signature[:32], "big"),
                    int.from_bytes(signature[32:], "big"),
                ),
                hashlib.sha256(runtime_device_proof_payload(
                    runtime_id=runtime_id,
                    runtime=runtime,
                    external_session_id=external_session_id,
                    challenge_id=challenge_id,
                    nonce=str(challenge["nonce"]),
                )).digest(),
                ec.ECDSA(utils.Prehashed(hashes.SHA256())),
            )
        except (KeyError, ValueError, TypeError, UnicodeDecodeError, InvalidSignature) as exc:
            raise AuthorizationDenied("runtime device proof is invalid") from exc
        with self._machine_agent_session_lock:
            current = self._machine_agent_challenges.get(challenge_id)
            if current is not challenge or bool(current["used"]):
                raise AuthorizationDenied("runtime device proof was replayed")
            current["used"] = True
        return custody_root

    def _machine_session_surface_values(
        self,
        snapshot,
        session_root: str,
    ) -> dict[str, str]:
        """Read the two released runtime identity properties for one session."""
        values: dict[str, str] = {}
        for member in read_relation(
            snapshot, self.universal_registry.canvas_root, budget=100_000
        ):
            if member.role_id != self.universal_registry.roles["property"]:
                continue
            property_members = read_relation(
                snapshot, member.participant_id, budget=32
            )
            owners = tuple(
                item.participant_id for item in property_members
                if item.role_id == self.universal_registry.roles["owner"]
            )
            if owners != (session_root,):
                continue
            labels = tuple(
                item.participant_id for item in property_members
                if item.role_id == self.universal_registry.roles["label"]
            )
            property_values = tuple(
                item.participant_id for item in property_members
                if item.role_id == self.universal_registry.roles["value"]
            )
            if len(labels) != 1 or len(property_values) != 1:
                raise InvalidCell("runtime Agent Session surface property drifted")
            try:
                label = snapshot.cells[labels[0]].atom.decode("utf-8")
                value = snapshot.cells[property_values[0]].atom.decode("utf-8")
            except (KeyError, UnicodeDecodeError) as exc:
                raise InvalidCell(
                    "runtime Agent Session surface property is malformed"
                ) from exc
            if label in {"runtime", "session fingerprint"}:
                if label in values:
                    raise InvalidCell(
                        "runtime Agent Session surface property is ambiguous"
                    )
                values[label] = value
        return values

    @staticmethod
    def _machine_agent_session_identity_binding_root(
        *,
        entry,
        runtime: str,
        external_session_fingerprint: str,
        custody_root: str | None,
    ) -> str:
        """Derive one collision-resistant relationship identity."""
        digest = hashlib.sha256()
        for value in (
            "archhub-runtime-session-binding-v1",
            entry.root_id,
            entry.control_root,
            runtime,
            external_session_fingerprint,
            custody_root or "",
        ):
            encoded = value.encode("utf-8")
            digest.update(len(encoded).to_bytes(8, "big"))
            digest.update(encoded)
        return "app:authority:runtime-session:%s" % digest.hexdigest()

    def _machine_session_claim_evidence_is_valid(
        self,
        snapshot,
        *,
        session_root: str,
        evidence_root: str,
    ) -> bool:
        """Verify historical claim provenance without making it live authority."""
        roles = self.universal_registry.governed_work_claim_binding_roles
        if evidence_root not in {
            member.participant_id
            for member in read_relation(
                snapshot,
                self.universal_registry.governed_work_claim_binding_registry_root,
                budget=100_000,
            )
            if member.role_id == roles["binding-member"]
        }:
            return False
        members = read_relation(snapshot, evidence_root, budget=32)
        values: dict[str, str] = {}
        admitted_roles = {
            roles["work"],
            roles["agent-session"],
            roles["agent-body"],
            roles["transition"],
        }
        if any(member.role_id not in admitted_roles for member in members):
            return False
        for member in members:
            if member.role_id in values:
                return False
            values[member.role_id] = member.participant_id
        if set(values) != admitted_roles:
            return False
        session = read_agent_session(
            snapshot,
            self.universal_registry.agent_body.protocol,
            self.universal_registry.authorization.protocol,
            session_root,
        )
        if (
            values[roles["agent-session"]] != session_root
            or values[roles["agent-body"]] != session.body_root
        ):
            return False
        machine = read_instance_state_machine(
            snapshot,
            self.universal_registry.assembly_protocol,
            self.universal_registry.standard_library.state_machine_protocol,
            values[roles["work"]],
        )
        return any(
            event.event_root == values[roles["transition"]]
            and evidence_root in event.context_roots
            and session_root in event.context_roots
            for event in machine_history(
                snapshot,
                self.universal_registry.standard_library.state_machine_protocol,
                machine.root_id,
            )
        )

    def _bound_machine_agent_session_identity(
        self,
        *,
        entry,
        runtime: str,
        external_session_fingerprint: str,
        custody_root: str | None,
    ):
        """Resolve one signed external identity binding from canonical Cells."""
        relationship_root = self._machine_agent_session_identity_binding_root(
            entry=entry,
            runtime=runtime,
            external_session_fingerprint=external_session_fingerprint,
            custody_root=custody_root,
        )
        snapshot = self.universal_store.snapshot()
        if relationship_root not in snapshot.cells:
            return None
        authority = self.universal_registry.authorization
        relationship = verify_authority_relationship(
            snapshot,
            authority.identity_protocol,
            authority.relationship_broker,
            relationship_root,
        )
        if (
            relationship.source_root != entry.root_id
            or relationship.kind_root
            != authority.identity_protocol.kinds["membership"]
            or relationship.tenant_root != authority.tenant_root
            or relationship.scope_root != entry.control_root
            or relationship.action_roots
        ):
            raise AuthorizationDenied(
                "runtime Agent Session identity binding drifted"
            )
        evidence = set(relationship.evidence_roots)
        if custody_root is not None:
            if custody_root not in evidence:
                raise AuthorizationDenied(
                    "runtime Agent Session identity custody drifted"
                )
            evidence.remove(custody_root)
        elif any(root in entry.device_custody_roots for root in evidence):
            raise AuthorizationDenied(
                "runtime Agent Session identity credential mode drifted"
            )
        if len(evidence) > 1 or any(
            not self._machine_session_claim_evidence_is_valid(
                snapshot,
                session_root=relationship.target_root,
                evidence_root=root,
            )
            for root in evidence
        ):
            raise AuthorizationDenied(
                "runtime Agent Session identity evidence drifted"
            )
        session = read_agent_session(
            snapshot,
            self.universal_registry.agent_body.protocol,
            authority.protocol,
            relationship.target_root,
        )
        if (
            session.state_root
            != self.universal_registry.agent_body.protocol.state("active")
        ):
            raise AuthorizationDenied(
                "runtime Agent Session identity is not active"
            )
        session_entry = _agent_body_catalog_entry_for_session(
            snapshot, self.universal_registry, session
        )
        surface = self._machine_session_surface_values(snapshot, session.root_id)
        if (
            session_entry.root_id != entry.root_id
            or surface.get("runtime") != runtime
            or surface.get("session fingerprint")
            != external_session_fingerprint
        ):
            raise AuthorizationDenied(
                "runtime Agent Session identity target drifted"
            )
        return session

    def _bind_machine_agent_session_identity(
        self,
        *,
        entry,
        runtime: str,
        external_session_fingerprint: str,
        custody_root: str | None,
        session,
        evidence_roots: tuple[str, ...],
    ) -> str:
        """Mint or verify the durable signed identity-to-session relationship."""
        relationship_root = self._machine_agent_session_identity_binding_root(
            entry=entry,
            runtime=runtime,
            external_session_fingerprint=external_session_fingerprint,
            custody_root=custody_root,
        )
        expected_evidence = tuple(dict.fromkeys((
            *((custody_root,) if custody_root is not None else ()),
            *evidence_roots,
        )))
        snapshot = self.universal_store.snapshot()
        if relationship_root in snapshot.cells:
            bound = self._bound_machine_agent_session_identity(
                entry=entry,
                runtime=runtime,
                external_session_fingerprint=external_session_fingerprint,
                custody_root=custody_root,
            )
            relationship = verify_authority_relationship(
                self.universal_store.snapshot(),
                self.universal_registry.authorization.identity_protocol,
                self.universal_registry.authorization.relationship_broker,
                relationship_root,
            )
            if (
                bound is None
                or bound.root_id != session.root_id
                or set(relationship.evidence_roots) != set(expected_evidence)
            ):
                raise AuthorizationDenied(
                    "runtime Agent Session identity is already bound differently"
                )
            return relationship_root
        surface = self._machine_session_surface_values(snapshot, session.root_id)
        if (
            surface.get("runtime") != runtime
            or surface.get("session fingerprint")
            != external_session_fingerprint
        ):
            raise AuthorizationDenied(
                "runtime Agent Session identity target drifted"
            )
        issue_universal_authority_relationship(
            self.universal_store,
            self.universal_registry,
            source_root=entry.root_id,
            target_root=session.root_id,
            kind="membership",
            scope_root=entry.control_root,
            reason="bind one admitted external runtime identity to its canonical Agent Session",
            evidence_roots=expected_evidence,
            relationship_root=relationship_root,
            authentication_context=(
                self.universal_registry.authorization.session.context()
            ),
        )
        bound = self._bound_machine_agent_session_identity(
            entry=entry,
            runtime=runtime,
            external_session_fingerprint=external_session_fingerprint,
            custody_root=custody_root,
        )
        if bound is None or bound.root_id != session.root_id:
            raise AuthorizationDenied(
                "runtime Agent Session identity binding did not verify"
            )
        return relationship_root

    def _continuable_machine_agent_session(
        self,
        *,
        entry,
        runtime: str,
        external_session_fingerprint: str,
        custody_root: str | None,
    ):
        """Find one exact re-provable graph identity after transport loss.

        Device-proof bodies require one exact custody root. Machine-transport
        bodies may continue only across the same authenticated local pipe and
        exact external-session fingerprint. Other credential modes are denied.
        """
        if entry.credential_mode == "device-proof":
            if (
                type(custody_root) is not str
                or tuple(entry.device_custody_roots) != (custody_root,)
            ):
                return None
        elif entry.credential_mode == "machine-transport":
            if custody_root is not None:
                return None
        else:
            return None
        bound = self._bound_machine_agent_session_identity(
            entry=entry,
            runtime=runtime,
            external_session_fingerprint=external_session_fingerprint,
            custody_root=custody_root,
        )
        if bound is not None:
            return bound
        snapshot = self.universal_store.snapshot()
        candidates = []
        for member in read_relation(
            snapshot, entry.control_root, budget=100_000
        ):
            if (
                member.role_id != self.universal_registry.roles["member"]
                or not member.participant_id.startswith(
                    "app:agent-session:runtime:"
                )
            ):
                continue
            session = read_agent_session(
                snapshot,
                self.universal_registry.agent_body.protocol,
                self.universal_registry.authorization.protocol,
                member.participant_id,
            )
            if (
                session.state_root
                != self.universal_registry.agent_body.protocol.state("active")
            ):
                continue
            session_entry = _agent_body_catalog_entry_for_session(
                snapshot, self.universal_registry, session
            )
            if session_entry.root_id != entry.root_id:
                raise AuthorizationDenied(
                    "runtime Agent Session catalog continuation drifted"
                )
            surface = self._machine_session_surface_values(
                snapshot, session.root_id
            )
            if (
                surface.get("runtime") == runtime
                and surface.get("session fingerprint")
                == external_session_fingerprint
            ):
                candidates.append(session)
        if not candidates:
            return None
        evidence_roots: tuple[str, ...] = ()
        selected = candidates[0]
        if len(candidates) > 1:
            claimed = []
            for candidate in candidates:
                work, _revision = read_universal_current_claimed_work(
                    self.universal_store,
                    self.universal_registry,
                    agent_session_root=candidate.root_id,
                    authentication_context=(
                        self.universal_registry.authorization.session.context()
                    ),
                )
                if work is None:
                    continue
                claim_binding = work.get("claim_binding")
                if type(claim_binding) is not str or not claim_binding:
                    raise InvalidCell(
                        "runtime Agent Session claim evidence is incomplete"
                    )
                claimed.append((
                    self.universal_store.cell_created_revision(claim_binding),
                    claim_binding,
                    candidate,
                ))
            if not claimed:
                raise AuthorizationDenied(
                    "runtime Agent Session continuation is ambiguous"
                )
            latest_revision = max(item[0] for item in claimed)
            latest = tuple(item for item in claimed if item[0] == latest_revision)
            if len(latest) != 1:
                raise AuthorizationDenied(
                    "runtime Agent Session continuation is ambiguous"
                )
            _created_revision, claim_binding, selected = latest[0]
            evidence_roots = (claim_binding,)
        self._bind_machine_agent_session_identity(
            entry=entry,
            runtime=runtime,
            external_session_fingerprint=external_session_fingerprint,
            custody_root=custody_root,
            session=selected,
            evidence_roots=evidence_roots,
        )
        return selected

    def _machine_agent_identity_is_currently_bound(
        self,
        *,
        runtime: str,
        catalog_entry_root: str,
        custody_root: str | None,
        external_session_fingerprint: str,
    ) -> bool:
        """Keep a second process from taking over the same live capability."""
        now = time.time()
        with self._machine_agent_session_lock:
            stale = tuple(
                root for root, binding in self._machine_agent_sessions.items()
                if now >= float(binding["expires_at"])
            )
            for root in stale:
                self._machine_agent_sessions.pop(root, None)
            return any(
                binding.get("runtime") == runtime
                and binding.get("catalog_entry") == catalog_entry_root
                and binding.get("device_custody") == custody_root
                and binding.get("external_session_fingerprint")
                == external_session_fingerprint
                for binding in self._machine_agent_sessions.values()
            )

    def _machine_agent_session_has_live_capability(
        self,
        session_root: str,
    ) -> bool:
        """Return whether this process can still verify the session token."""
        now = time.time()
        with self._machine_agent_session_lock:
            binding = self._machine_agent_sessions.get(session_root)
            if binding is None:
                return False
            if now >= float(binding["expires_at"]):
                self._machine_agent_sessions.pop(session_root, None)
                return False
            return True

    @staticmethod
    def _machine_agent_recovery_access_is_admitted(
        request: dict[str, object],
    ) -> bool:
        """Keep a non-disruptive recovery capability strictly read-only."""
        return (
            str(request.get("method") or "").upper(),
            str(request.get("path") or ""),
        ) in {
            ("GET", "/api/universal/work-current"),
            ("POST", "/api/universal/work-plan-read"),
        }

    def _machine_agent_binding_for_request(
        self,
        request: dict[str, object],
    ) -> tuple[str, dict[str, object]]:
        """Resolve one ephemeral capability to its unchanged graph session."""
        session = request.get("session")
        if type(session) is not dict:
            raise AuthorizationDenied("a bound runtime Agent Session is required")
        fields = set(session)
        if fields not in ({"root", "proof"}, {"root", "capability", "proof"}):
            raise AuthorizationDenied("runtime Agent Session proof is invalid")
        session_root = session["root"]
        proof = session["proof"]
        capability_id = session.get("capability")
        if (
            type(session_root) is not str
            or type(proof) is not str
            or (capability_id is not None and type(capability_id) is not str)
        ):
            raise AuthorizationDenied("runtime Agent Session proof is invalid")
        now = time.time()
        with self._machine_agent_session_lock:
            stale = tuple(
                capability for capability, binding
                in self._machine_agent_recovery_capabilities.items()
                if now >= float(binding["expires_at"])
            )
            for capability in stale:
                self._machine_agent_recovery_capabilities.pop(capability, None)
            if capability_id is None:
                binding = self._machine_agent_sessions.get(session_root)
            else:
                binding = self._machine_agent_recovery_capabilities.get(
                    capability_id
                )
                if binding is not None and binding.get("session_root") != session_root:
                    binding = None
            binding = dict(binding or {})
        if not binding:
            raise AuthorizationDenied("runtime Agent Session is unknown")
        if now >= float(binding["expires_at"]):
            raise AuthorizationDenied("runtime Agent Session capability expired")
        expected = hmac.new(
            str(binding["token"]).encode("utf-8"),
            session_proof_payload(
                runtime_id=str(request.get("runtime_id") or ""),
                request_id=str(request.get("request_id") or ""),
                method=str(request.get("method") or ""),
                path=str(request.get("path") or ""),
                body=dict(request.get("body") or {}),
                session_root=session_root,
                capability_id=capability_id,
            ),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(proof, expected):
            raise AuthorizationDenied("runtime Agent Session proof is invalid")
        if (
            binding.get("access") == "recovery-read"
            and not self._machine_agent_recovery_access_is_admitted(request)
        ):
            raise AuthorizationDenied(
                "recovered runtime Agent Session is read-only"
            )
        projection = read_agent_session(
            self.universal_store.snapshot(),
            self.universal_registry.agent_body.protocol,
            self.universal_registry.authorization.protocol,
            session_root,
        )
        if projection.state_root != self.universal_registry.agent_body.protocol.state("active"):
            raise AuthorizationDenied("runtime Agent Session is not active")
        entry = _agent_body_catalog_entry_for_session(
            self.universal_store.snapshot(),
            self.universal_registry,
            projection,
        )
        if (
            entry.root_id != binding.get("catalog_entry")
            or projection.body_root != entry.body_root
        ):
            raise AuthorizationDenied("runtime Agent Session catalog binding drifted")
        custody_root = binding.get("device_custody")
        if entry.credential_mode == "device-proof":
            if not isinstance(custody_root, str) or custody_root not in entry.device_custody_roots:
                raise AuthorizationDenied("runtime Agent Session device custody drifted")
            custody = read_device_custody(
                self.universal_store.snapshot(),
                self.universal_registry.device_custody_protocol,
                custody_root,
            )
            if custody.state_root != self.universal_registry.device_custody_protocol.states["active"]:
                raise AuthorizationDenied("runtime Agent Session device custody is revoked")
        elif custody_root is not None:
            raise AuthorizationDenied("runtime Agent Session credential mode drifted")
        return session_root, binding

    def _runtime_compliance_for_work_request(
        self,
        request: dict[str, object],
        *,
        authentication_context: object,
    ) -> tuple[str, str | None, str | None]:
        """Bind a fresh signed runtime audit to this exact graph Session."""
        session_root, binding = self._machine_agent_binding_for_request(request)
        session = read_agent_session(
            self.universal_store.snapshot(),
            self.universal_registry.agent_body.protocol,
            self.universal_registry.authorization.protocol,
            session_root,
        )
        entry = _agent_body_catalog_entry_for_session(
            self.universal_store.snapshot(),
            self.universal_registry,
            session,
        )
        if entry.credential_mode == "device-proof":
            return session_root, None, None
        runtime = binding.get("runtime")
        fingerprint = binding.get("external_session_fingerprint")
        if type(runtime) is not str or type(fingerprint) is not str:
            raise AuthorizationDenied(
                "runtime compliance identity is unavailable"
            )
        observation, evidence_root, _revision = (
            attest_universal_runtime_compliance(
                self.universal_store,
                self.universal_registry,
                agent_session_root=session_root,
                runtime=runtime,
                external_session_fingerprint=fingerprint,
                authentication_context=authentication_context,
            )
        )
        return session_root, observation.root_id, evidence_root

    def _machine_agent_runtime_presence(self) -> dict[str, object]:
        """Project bounded live capability state for the BABOOM graph lens.

        The durable Agent Session is already a Cell composition. This only says
        whether this runtime can currently verify a capability for that graph
        session; it never creates a second presence authority or exposes roots,
        device custody, tokens, or external identities.
        """
        now = time.time()
        with self._machine_agent_session_lock:
            stale = tuple(
                root for root, binding in self._machine_agent_sessions.items()
                if now >= float(binding["expires_at"])
            )
            for root in stale:
                self._machine_agent_sessions.pop(root, None)
            runtimes = tuple(
                str(binding.get("runtime") or "")
                for binding in self._machine_agent_sessions.values()
            )
        baboom_device_proven = (
            "baboom" in runtimes or "baboom-execution" in runtimes
        )
        return {
            "active_runtime_sessions": len(runtimes),
            "baboom_connected": "baboom" in runtimes,
            "baboom_action_capability_active": "baboom-execution" in runtimes,
            # The Browser handoff is a released local-server route. The proof
            # bit is about this runtime's admitted session, never the device
            # inventory or its custody root.
            "device_enrollment_handoff_available": True,
            "current_runtime_device_proven": baboom_device_proven,
            "remote_gateway_serving": bool(
                self._universal_cloud_thread is not None
                and self._universal_cloud_thread.is_alive()
            ),
        }

    def _renew_universal_runtime_presence(
        self,
        request: dict[str, object],
    ) -> dict[str, object]:
        """Record one lease from an already verified device-proof session."""
        session_root = self._resolve_universal_machine_agent_session(request)
        with self._machine_agent_session_lock:
            binding = dict(self._machine_agent_sessions.get(session_root) or {})
        runtime = binding.get("runtime")
        custody_root = binding.get("device_custody")
        if type(runtime) is not str or type(custody_root) is not str:
            raise AuthorizationDenied(
                "runtime presence requires a device-proof Agent Session"
            )
        snapshot = self.universal_store.snapshot()
        session = read_agent_session(
            snapshot,
            self.universal_registry.agent_body.protocol,
            self.universal_registry.authorization.protocol,
            session_root,
        )
        entry = _agent_body_catalog_entry_for_session(
            snapshot, self.universal_registry, session
        )
        if (
            entry.credential_mode != "device-proof"
            or custody_root not in entry.device_custody_roots
        ):
            raise AuthorizationDenied(
                "runtime presence Agent Session is not device-proofed"
            )
        presence, revision = renew_runtime_presence(
            self.universal_store,
            self.universal_registry.runtime_presence_protocol,
            agent_session_root=session_root,
            device_custody_root=custody_root,
            runtime=runtime,
            now=time.time(),
            lease_seconds=RUNTIME_PRESENCE_LEASE_SECONDS,
        )
        return {
            "agent_session": session_root,
            "runtime": runtime,
            "expires_at": presence.expires_at,
            "revision": revision,
        }

    def _enroll_universal_machine_agent_session(
        self,
        body: dict[str, object],
        *,
        runtime_id: str,
    ) -> dict[str, object]:
        expected = {"runtime", "external_session_id"}
        if "device_credential" in body:
            expected.add("device_credential")
        if set(body) != expected:
            raise InvalidCell("Agent Session enrollment shape is invalid")
        runtime = body["runtime"]
        external_session_id = body["external_session_id"]
        if (
            type(runtime) is not str
            or not runtime.strip()
            or len(runtime.encode("utf-8")) > 128
            or type(external_session_id) is not str
            or not external_session_id
            or len(external_session_id.encode("utf-8")) > 4096
        ):
            raise InvalidCell("Agent Session enrollment identity is invalid")
        entry = _agent_body_catalog_entry_for_runtime(
            self.universal_store.snapshot(),
            self.universal_registry,
            runtime.strip(),
        )
        custody_root = None
        if entry.credential_mode == "device-proof":
            custody_root = self._verify_universal_runtime_device_credential(
                body.get("device_credential"),
                runtime=runtime.strip(),
                external_session_id=external_session_id,
                runtime_id=runtime_id,
                catalog_entry_root=entry.root_id,
            )
        elif "device_credential" in body:
            raise AuthorizationDenied(
                "runtime Agent Body does not admit a device credential"
            )
        session_root = "app:agent-session:runtime:%s" % uuid.uuid4().hex
        token = secrets.token_urlsafe(48)
        issued_at = time.time()
        expires_at = issued_at + self.machine_session_lifetime_seconds
        fingerprint = hashlib.sha256(
            external_session_id.encode("utf-8")
        ).hexdigest()
        runtime = runtime.strip()
        with self._machine_agent_session_lock:
            if runtime in {"baboom", "baboom-execution"} and (
                self._machine_agent_identity_is_currently_bound(
                    runtime=runtime,
                    catalog_entry_root=entry.root_id,
                    custody_root=custody_root,
                    external_session_fingerprint=fingerprint,
                )
            ):
                raise AuthorizationDenied(
                    "runtime Agent Session identity is already bound; renew it instead"
                )
            session = self._continuable_machine_agent_session(
                entry=entry,
                runtime=runtime,
                external_session_fingerprint=fingerprint,
                custody_root=custody_root,
            )
            continued = session is not None
            if session is None:
                session, revision = begin_universal_runtime_agent_session(
                    self.universal_store,
                    self.universal_registry,
                    session_root=session_root,
                    runtime=runtime,
                    external_session_fingerprint=fingerprint,
                    catalog_entry_root=entry.root_id,
                    authentication_context=(
                        self.universal_registry.authorization.session.context()
                    ),
                )
                self._bind_machine_agent_session_identity(
                    entry=entry,
                    runtime=runtime,
                    external_session_fingerprint=fingerprint,
                    custody_root=custody_root,
                    session=session,
                    evidence_roots=(),
                )
            else:
                revision = self.universal_store.revision
            session_root = session.root_id
            self._machine_agent_sessions[session_root] = {
                "token": token,
                "runtime": runtime.strip(),
                "catalog_entry": entry.root_id,
                "device_custody": custody_root,
                "external_session_fingerprint": fingerprint,
                "issued_at": issued_at,
                "expires_at": expires_at,
            }
        # A runtime session becomes a visible, authorised Workshop participant
        # when it is enrolled.  Posting a plan or research record must never
        # smuggle enrollment side effects into a separate set of revisions.
        self._ensure_universal_workshop_participant(session_root)
        return {
            "agent_session": session.root_id,
            "session_token": token,
            "runtime": runtime.strip(),
            "agent_body": entry.body_root,
            "catalog_entry": entry.root_id,
            "issued_at": issued_at,
            "expires_at": expires_at,
            "continued": continued,
            "revision": self.universal_store.revision,
        }

    def _resume_universal_machine_agent_session(
        self,
        body: dict[str, object],
        *,
        runtime_id: str,
    ) -> dict[str, object]:
        """Issue a read-only recovery capability for one existing graph session."""
        if set(body) != {"runtime", "external_session_id", "device_credential"}:
            raise InvalidCell("Agent Session recovery shape is invalid")
        runtime = body["runtime"]
        external_session_id = body["external_session_id"]
        if (
            type(runtime) is not str
            or runtime.strip() != "baboom-execution"
            or type(external_session_id) is not str
            or not external_session_id
            or len(external_session_id.encode("utf-8")) > 4096
        ):
            raise AuthorizationDenied("Agent Session recovery identity is invalid")
        runtime = runtime.strip()
        entry = _agent_body_catalog_entry_for_runtime(
            self.universal_store.snapshot(), self.universal_registry, runtime
        )
        custody_root = self._verify_universal_runtime_device_credential(
            body["device_credential"],
            runtime=runtime,
            external_session_id=external_session_id,
            runtime_id=runtime_id,
            catalog_entry_root=entry.root_id,
        )
        fingerprint = hashlib.sha256(
            external_session_id.encode("utf-8")
        ).hexdigest()
        session = self._continuable_machine_agent_session(
            entry=entry,
            runtime=runtime,
            external_session_fingerprint=fingerprint,
            custody_root=custody_root,
        )
        if session is None:
            raise AuthorizationDenied(
                "runtime Agent Session has no matching graph identity to recover"
            )
        issued_at = time.time()
        expires_at = issued_at + self.machine_session_lifetime_seconds
        capability_id = "machine-recovery:%s" % uuid.uuid4().hex
        token = secrets.token_urlsafe(48)
        with self._machine_agent_session_lock:
            self._machine_agent_recovery_capabilities[capability_id] = {
                "session_root": session.root_id,
                "token": token,
                "runtime": runtime,
                "catalog_entry": entry.root_id,
                "device_custody": custody_root,
                "external_session_fingerprint": fingerprint,
                "access": "recovery-read",
                "issued_at": issued_at,
                "expires_at": expires_at,
            }
        return {
            "agent_session": session.root_id,
            "session_token": token,
            "capability": capability_id,
            "runtime": runtime,
            "access": "recovery-read",
            "continued": True,
            "issued_at": issued_at,
            "expires_at": expires_at,
            "revision": self.universal_store.revision,
        }

    def _resolve_universal_machine_agent_session(
        self, request: dict[str, object]
    ) -> str:
        session_root, _binding = self._machine_agent_binding_for_request(request)
        return session_root

    def verify_universal_cloud_request_device(
        self,
        request: dict[str, object],
        *,
        cloud_device_root: str,
    ) -> None:
        """Require a remote DPoP device to match the runtime custody device.

        The cloud gateway has already authenticated the Cloud Session and
        injects its graph-held proof-key root.  This check binds that external
        proof to the local runtime capability before the normal dispatch runs;
        it adds no new persisted state or authority.
        """
        prefix = "device-proof-key:sha256:"
        if not isinstance(cloud_device_root, str) or not cloud_device_root.startswith(prefix):
            raise AuthorizationDenied("cloud request device identity is invalid")
        thumbprint = cloud_device_root[len(prefix):]
        try:
            if device_root_for_thumbprint(thumbprint) != cloud_device_root:
                raise ValueError("cloud device root drifted")
        except ValueError as exc:
            raise AuthorizationDenied(
                "cloud request device identity is invalid"
            ) from exc
        expected_custody_root = "device-custody:sha256:" + thumbprint
        body = request.get("body")
        session = request.get("session")
        path = request.get("path")
        if type(body) is not dict or type(session) is not dict or not isinstance(path, str):
            raise AuthorizationDenied("cloud request shape is invalid")
        if session == {}:
            if path in {
                "/api/universal/devices",
                "/api/universal/device-custody-revoke",
            }:
                try:
                    custody = read_device_custody(
                        self.universal_store.snapshot(),
                        self.universal_registry.device_custody_protocol,
                        expected_custody_root,
                    )
                except InvalidCell as exc:
                    raise AuthorizationDenied(
                        "cloud founder device custody is not admitted"
                    ) from exc
                if (
                    custody.state_root
                    != self.universal_registry.device_custody_protocol.states["active"]
                ):
                    raise AuthorizationDenied(
                        "cloud founder device custody is revoked"
                    )
            # Agent enrollment has no runtime capability yet. A device-proof
            # body must therefore prove the exact same custody the Cloud
            # Session's DPoP key identifies before dispatch may create it.
            if path in {
                "/api/universal/agent-session",
                "/api/universal/agent-session-resume",
            }:
                runtime = body.get("runtime")
                if not isinstance(runtime, str) or not runtime.strip():
                    raise AuthorizationDenied("cloud Agent Session runtime is invalid")
                entry = _agent_body_catalog_entry_for_runtime(
                    self.universal_store.snapshot(),
                    self.universal_registry,
                    runtime.strip(),
                )
                if entry.credential_mode == "device-proof":
                    credential = body.get("device_credential")
                    if (
                        type(credential) is not dict
                        or credential.get("custody_root") != expected_custody_root
                    ):
                        raise AuthorizationDenied(
                            "cloud Agent Session custody does not match DPoP device"
                        )
            return
        session_root, binding = self._machine_agent_binding_for_request(request)
        if binding.get("device_custody") != expected_custody_root:
            raise AuthorizationDenied(
                "cloud Agent Session custody does not match DPoP device"
            )

    def _ensure_universal_workshop_participant(
        self, participant_root: str
    ) -> None:
        """Admit one proven runtime Agent Session to Workshop control spaces."""
        if participant_root == self.universal_registry.authorization.subject_root:
            return
        if not participant_root.startswith("app:agent-session:runtime:"):
            raise AuthorizationDenied("Workshop participant is not a runtime Agent Session")
        snapshot = self.universal_store.snapshot()
        session = read_agent_session(
            snapshot,
            self.universal_registry.agent_body.protocol,
            self.universal_registry.authorization.protocol,
            participant_root,
        )
        if session.subject_root != self.universal_registry.authorization.subject_root:
            raise AuthorizationDenied("runtime Agent Session subject is not admitted")
        self._ensure_runtime_workshop_memberships(participant_root)
        snapshot = self.universal_store.snapshot()
        space = read_deliberation_space(
            snapshot,
            self.universal_registry.deliberation_protocol,
            self.universal_registry.workshop_root,
        )
        control_space = read_deliberation_space(
            snapshot,
            self.universal_registry.deliberation_protocol,
            self.universal_registry.brain_control_ledger_root,
        )
        participant_patch = prepare_append_relation_member(
            snapshot,
            self.universal_registry.workshop_root,
            self.universal_registry.deliberation_protocol.role(
                "space-participant"
            ),
            participant_root,
            budget=100_000,
        ) if participant_root not in space.participant_roots else None
        workbench_members = {
            (member.role_id, member.participant_id)
            for member in read_relation(
                snapshot,
                self.universal_registry.workshop_workbench_root,
                budget=100_000,
            )
        }
        workbench_patch = prepare_append_relation_member(
            snapshot,
            self.universal_registry.workshop_workbench_root,
            self.universal_registry.roles["member"],
            participant_root,
            budget=100_000,
        ) if (
            self.universal_registry.roles["member"], participant_root
        ) not in workbench_members else None
        control_participant_patch = prepare_append_relation_member(
            snapshot,
            self.universal_registry.brain_control_ledger_root,
            self.universal_registry.deliberation_protocol.role(
                "space-participant"
            ),
            participant_root,
            budget=100_000,
        ) if participant_root not in control_space.participant_roots else None
        patches = (
            participant_patch,
            workbench_patch,
            control_participant_patch,
        )
        if all(patch is None for patch in patches):
            return
        replacements = {
            cell.id: cell
            for patch in patches
            if patch is not None
            for cell in patch.replace
        }
        self.universal_store.commit(
            snapshot.revision,
            create=tuple(
                cell
                for patch in patches
                if patch is not None
                for cell in patch.create
            ),
            replace=tuple(replacements.values()),
        )

    def _ensure_runtime_workshop_memberships(
        self, session_root: str
    ) -> None:
        """Grant the minimal signed memberships for a runtime session actor."""
        authority = self.universal_registry.authorization
        token = hashlib.sha256(session_root.encode("utf-8")).hexdigest()
        required = (
            (
                "app:authority:runtime-workshop:%s:tenant" % token,
                authority.tenant_root,
                "runtime Agent Session admitted to the application tenant",
            ),
            (
                "app:authority:runtime-workshop:%s:principal" % token,
                authority.principal_root,
                "runtime Agent Session admitted to the application principal",
            ),
        )
        for relationship_root, target_root, reason in required:
            snapshot = self.universal_store.snapshot()
            if relationship_root in snapshot.cells:
                relationship = verify_authority_relationship(
                    snapshot,
                    authority.identity_protocol,
                    authority.relationship_broker,
                    relationship_root,
                )
                if (
                    relationship.source_root != session_root
                    or relationship.target_root != target_root
                    or relationship.kind_root
                    != authority.identity_protocol.kinds["membership"]
                    or relationship.tenant_root != authority.tenant_root
                ):
                    raise InvalidCell(
                        "runtime Workshop membership authority drifted"
                    )
                continue
            grant_authority_relationship(
                self.universal_store,
                authority.identity_protocol,
                authority.relationship_broker,
                authority.relationship_broker.mint_from_trusted_administrator(
                    authority.subject_root
                ),
                relationship_id=relationship_root,
                source_root=session_root,
                target_root=target_root,
                kind="membership",
                tenant_root=authority.tenant_root,
                administrator_root=authority.subject_root,
                reason=reason,
            )

    def _renew_universal_machine_agent_session(
        self, request: dict[str, object]
    ) -> dict[str, object]:
        session_root = self._resolve_universal_machine_agent_session(request)
        token = secrets.token_urlsafe(48)
        issued_at = time.time()
        expires_at = issued_at + self.machine_session_lifetime_seconds
        with self._machine_agent_session_lock:
            binding = self._machine_agent_sessions.get(session_root)
            if binding is None:
                raise AuthorizationDenied("runtime Agent Session is unknown")
            binding.update({
                "token": token,
                "issued_at": issued_at,
                "expires_at": expires_at,
            })
        return {
            "agent_session": session_root,
            "session_token": token,
            "runtime": str(binding["runtime"]),
            "issued_at": issued_at,
            "expires_at": expires_at,
            "revision": self.universal_store.revision,
        }

    def _project_universal_machine_work_index(
        self,
        *,
        authentication_context: object,
    ) -> dict[str, object]:
        """Return a revision-bound work index without creating a second ledger."""
        revision = self.universal_store.revision
        with self._work_index_cache_ready:
            if (
                self._work_index_cache is not None
                and self._work_index_cache_revision == revision
            ):
                # Machine routes serialize this private projection immediately;
                # deep-copying the revision-bound graph index dominates read
                # latency on large authority graphs.
                return self._work_index_cache
            while self._work_index_cache_inflight_revision == revision:
                self._work_index_cache_ready.wait(timeout=0.25)
                if (
                    self._work_index_cache is not None
                    and self._work_index_cache_revision == revision
                ):
                    return self._work_index_cache
            self._work_index_cache_inflight_revision = revision
        try:
            index = project_universal_governed_work_index(
                self.universal_store,
                self.universal_registry,
                authentication_context=authentication_context,
            )
        finally:
            with self._work_index_cache_ready:
                if self._work_index_cache_inflight_revision == revision:
                    self._work_index_cache_inflight_revision = None
                self._work_index_cache_ready.notify_all()
        with self._work_index_cache_ready:
            if self.universal_store.revision == revision:
                self._work_index_cache_revision = revision
                self._work_index_cache = index
                self._work_index_cache_ready.notify_all()
        return index

    def _project_universal_machine_workshop(
        self,
        *,
        request_agent_session: str,
    ) -> dict[str, object]:
        """Return the Workshop read model without taking the mutation lock."""
        snapshot = self.universal_store.snapshot()
        with self._work_index_cache_ready:
            if (
                self._workshop_cache is not None
                and self._workshop_cache_revision == snapshot.revision
            ):
                projection = self._workshop_cache
                return self._filter_universal_machine_workshop(
                    projection,
                    request_agent_session=request_agent_session,
                )
        entries = list_deliberation_entries(
            snapshot,
            self.universal_registry.deliberation_protocol,
            self.universal_registry.workshop_root,
        )
        categories = {
            root: name
            for name, root in (
                self.universal_registry.workshop_category_roots.items()
            )
        }
        projection = {
            "application": self.universal_registry.application_root,
            "workshop": self.universal_registry.workshop_root,
            "revision": snapshot.revision,
            "total": len(entries),
            "categories": dict(self.universal_registry.workshop_category_roots),
            "phases": dict(self.universal_registry.workshop_phase_roots),
            "requirements": list(
                self.universal_registry.workshop_requirement_roots
            ),
            "entries": [
                {
                    "root": entry.root_id,
                    "sequence": entry.sequence,
                    "actor": entry.actor_root,
                    "kind": categories.get(
                        entry.category_root,
                        entry.category_root,
                    ),
                    "category_root": entry.category_root,
                    "recipients": list(entry.recipient_roots),
                    "refs": list(entry.reference_roots),
                    "evidence": list(entry.evidence_roots),
                    "reply_to": entry.reply_to_root,
                    "text": entry.content,
                    "created_at": entry.created_at,
                }
                for entry in entries
            ],
        }
        with self._work_index_cache_ready:
            if self.universal_store.revision == snapshot.revision:
                self._workshop_cache_revision = snapshot.revision
                self._workshop_cache = projection
        return self._filter_universal_machine_workshop(
            projection,
            request_agent_session=request_agent_session,
        )

    def _filter_universal_machine_workshop(
        self,
        projection: Mapping[str, object],
        *,
        request_agent_session: str,
    ) -> dict[str, object]:
        """Apply graph-held Workshop audience relations at the read boundary."""
        founder_session = self.universal_registry.agent_body.session.root_id
        entries = projection.get("entries")
        projected_entries = entries if isinstance(entries, list) else []
        if request_agent_session == founder_session:
            visible = projected_entries
        else:
            visible = [
                entry
                for entry in projected_entries
                if (
                    isinstance(entry, Mapping)
                    and (
                        not entry.get("recipients")
                        or entry.get("actor") == request_agent_session
                        or request_agent_session in entry.get("recipients", ())
                    )
                )
            ]
        return {
            "agent_session": request_agent_session,
            **projection,
            "total": len(visible),
            "entries": visible[-_MACHINE_WORKSHOP_ENTRY_LIMIT:],
        }

    def _project_universal_machine_canvas(
        self,
        *,
        request_agent_session: str,
        authentication_context: object | None,
    ) -> dict[str, object]:
        """Return the bounded machine canvas read model without the UI lock."""
        revision = self.universal_store.revision
        with self._work_index_cache_ready:
            if (
                self._canvas_cache is not None
                and self._canvas_cache_revision == revision
            ):
                return {
                    "ok": True,
                    "application": self.universal_registry.application_root,
                    "agent_session": request_agent_session,
                    **self._canvas_cache,
                }
        projection = project_universal_machine_canvas(
            self.universal_store,
            self.universal_registry,
            authentication_context=authentication_context,
        )
        with self._work_index_cache_ready:
            if self.universal_store.revision == revision:
                self._canvas_cache_revision = revision
                self._canvas_cache = projection
        return {
            "ok": True,
            "application": self.universal_registry.application_root,
            "agent_session": request_agent_session,
            **projection,
        }

    def dispatch_universal_machine_route(
        self, request: dict[str, object]
    ) -> dict[str, object]:
        """Dispatch the narrow machine interface through graph route authority."""
        if type(request) is not dict:
            raise InvalidCell("machine route request is invalid")
        direct = set(request) == {"method", "path", "body"}
        if not direct and set(request) != {
            "runtime_id", "request_id", "method", "path", "body", "session"
        }:
            raise InvalidCell("machine route request shape is invalid")
        method = request.get("method")
        path = request.get("path")
        body = request.get("body")
        if (
            type(method) is not str
            or type(path) is not str
            or type(body) is not dict
        ):
            raise InvalidCell("machine route request values are invalid")
        method = method.upper()
        admitted = {
            ("GET", "/api/universal/canvas"),
            ("GET", "/api/universal/work"),
            ("GET", "/api/universal/work-current"),
            ("GET", "/api/universal/grand-map-work"),
            ("GET", "/api/universal/roma-tree"),
            ("GET", "/api/universal/workshop"),
            ("GET", "/api/universal/workshop-assignments"),
            ("GET", "/api/universal/deliberation"),
            ("GET", "/api/universal/attention"),
            ("GET", "/api/universal/devices"),
            ("GET", "/api/universal/runtime-handoff-readiness"),
            ("GET", "/api/universal/runtime-backend"),
            ("GET", "/api/universal/baboom-context"),
            ("GET", "/api/universal/baboom-presence"),
            ("GET", "/api/universal/baboom-native-frame"),
            ("GET", "/api/universal/baboom-steward-briefing"),
            ("GET", "/api/universal/baboom-capabilities"),
            ("GET", "/api/universal/mcp-broker"),
            ("GET", "/api/universal/work-handoff"),
            ("GET", "/api/universal/work-claim-transfer"),
            ("GET", "/api/universal/browser-handoff"),
            ("POST", "/api/universal/work"),
            ("POST", "/api/universal/grand-map-work"),
            ("POST", "/api/universal/roma-tree"),
            ("POST", "/api/universal/work-handoff"),
            ("POST", "/api/universal/work-handoff-receipt"),
            ("POST", "/api/universal/work-claim-transfer"),
            ("POST", "/api/universal/work-claim-transfer-claim"),
            ("POST", "/api/universal/work-claim-transfer-cancel"),
            ("POST", "/api/universal/workshop"),
            ("POST", "/api/universal/workshop-assignment"),
            ("POST", "/api/universal/deliberation"),
            ("POST", "/api/universal/assembly"),
            ("POST", "/api/universal/assembly-field"),
            ("POST", "/api/universal/work-next"),
            ("POST", "/api/universal/work-claim"),
            ("POST", "/api/universal/work-claim-recover"),
            ("POST", "/api/universal/cde-write-permit"),
            ("POST", "/api/universal/cde-write-receipt"),
            ("POST", "/api/universal/value"),
            ("POST", "/api/universal/agent-session-challenge"),
            ("POST", "/api/universal/agent-session"),
            ("POST", "/api/universal/agent-session-resume"),
            ("POST", "/api/universal/agent-session-renew"),
            ("POST", "/api/universal/baboom-command"),
            ("POST", "/api/universal/baboom-command-response"),
            ("POST", "/api/universal/baboom-command-execute"),
            ("POST", "/api/universal/runtime-presence"),
            ("POST", "/api/universal/browser-handoff"),
            ("POST", "/api/universal/agent-body-device-custody"),
            ("POST", "/api/universal/device-custody-revoke"),
            ("POST", "/api/universal/model-delegation"),
            ("POST", "/api/universal/model-delegation-approve"),
            ("POST", "/api/universal/model-delegation-grant"),
            ("POST", "/api/universal/model-delegation-execute"),
            ("POST", "/api/universal/model-delegation-receipt"),
            ("POST", "/api/universal/model-delegation-recover"),
            ("POST", "/api/universal/model-delegation-resume"),
            ("POST", "/api/universal/model-cognition"),
            ("POST", "/api/universal/baboom-activity"),
            ("POST", "/api/universal/baboom-meeting-notes"),
            ("POST", "/api/universal/baboom-steward-signal"),
            ("POST", "/api/universal/work-plan"),
            ("POST", "/api/universal/work-plan-read"),
            ("POST", "/api/universal/connector-delegation"),
            ("POST", "/api/universal/connector-delegation-approve"),
            ("POST", "/api/universal/connector-delegation-grant"),
            ("POST", "/api/universal/connector-delegation-receipt"),
            ("POST", "/api/universal/connector-delegation-recover"),
            ("POST", "/api/universal/connector-delegation-resume"),
            ("POST", "/api/universal/mcp-server-register"),
            ("POST", "/api/universal/mcp-server-negotiate"),
            ("POST", "/api/universal/mcp-tool-delegation"),
            ("POST", "/api/universal/work-transition"),
            ("POST", "/api/universal/work-court"),
            ("POST", "/api/universal/work-court-recover"),
            ("POST", "/api/universal/runtime-handoff"),
            ("POST", "/api/universal/workshop-gate"),
        }
        if (method, path) not in admitted:
            raise AuthorizationDenied("machine route is not admitted")
        context = self.universal_registry.authorization.session.context()
        if method == "GET" and path == "/api/universal/canvas":
            if body:
                raise InvalidCell("canvas projection request must be empty")
            if self.universal_checkpoint_guard is not None:
                self.universal_checkpoint_guard.require_healthy()
            self.require_universal_http_route(
                method, path, authentication_context=context
            )
            request_agent_session = (
                self.universal_registry.agent_body.session.root_id
                if direct or request.get("session") == {}
                else self._resolve_universal_machine_agent_session(request)
            )
            return self._project_universal_machine_canvas(
                request_agent_session=request_agent_session,
                authentication_context=context,
            )
        if method == "GET" and path == "/api/universal/work":
            if self.universal_checkpoint_guard is not None:
                self.universal_checkpoint_guard.require_healthy()
            self.require_universal_http_route(
                method, path, authentication_context=context
            )
            request_agent_session = (
                self.universal_registry.agent_body.session.root_id
                if direct or request.get("session") == {}
                else self._resolve_universal_machine_agent_session(request)
            )
            if body:
                if set(body) != {"projection"} or body["projection"] != "index":
                    raise InvalidCell(
                        "work projection request shape is invalid"
                    )
                index = self._project_universal_machine_work_index(
                    authentication_context=context,
                )
                return {
                    "agent_session": request_agent_session,
                    "workshop": self.universal_registry.workshop_root,
                    **index,
                }
            status = project_universal_governed_work_status(
                self.universal_store,
                self.universal_registry,
                authentication_context=context,
            )
            snapshot = self.universal_store.snapshot()
            workshop_entries = list_deliberation_entries(
                snapshot,
                self.universal_registry.deliberation_protocol,
                self.universal_registry.workshop_root,
            )
            baboom_entry = _agent_body_catalog_entry_for_runtime(
                snapshot, self.universal_registry, "baboom"
            )
            baboom_execution_entry = _agent_body_catalog_entry_for_runtime(
                snapshot, self.universal_registry, "baboom-execution"
            )
            return {
                "application": self.universal_registry.application_root,
                "agent_session": request_agent_session,
                "brain_scope": self.universal_registry.map.domains["brain"],
                "workshop": self.universal_registry.workshop_root,
                "workshop_status": {
                    "root": self.universal_registry.workshop_root,
                    "entry_count": len(workshop_entries),
                    "categories": dict(
                        self.universal_registry.workshop_category_roots
                    ),
                    "phases": dict(
                        self.universal_registry.workshop_phase_roots
                    ),
                    "requirements": list(
                        self.universal_registry.workshop_requirement_roots
                    ),
                },
                "baboom": {
                    "catalog_entry": baboom_entry.root_id,
                    "agent_body": baboom_entry.body_root,
                    "control": baboom_entry.control_root,
                    "credential_mode": baboom_entry.credential_mode,
                    "runtime": baboom_entry.runtime,
                    "grand_map_node": baboom_entry.grand_map_node_root,
                    "action_capability": {
                        "catalog_entry": baboom_execution_entry.root_id,
                        "control": baboom_execution_entry.control_root,
                        "credential_mode": baboom_execution_entry.credential_mode,
                        "runtime_profile": baboom_execution_entry.runtime,
                        "work_events": list(baboom_execution_entry.work_events),
                    },
                    "model_execution": status["model_execution"],
                },
                **status,
            }
        if method == "GET" and path == "/api/universal/work-current":
            if direct or body:
                raise AuthorizationDenied(
                    "current Work requires its bound empty runtime request"
                )
            if self.universal_checkpoint_guard is not None:
                self.universal_checkpoint_guard.require_healthy()
            self.require_universal_http_route(
                method, path, authentication_context=context
            )
            agent_session_root = self._resolve_universal_machine_agent_session(
                request
            )
            work, revision = read_universal_current_claimed_work(
                self.universal_store,
                self.universal_registry,
                agent_session_root=agent_session_root,
                authentication_context=context,
            )
            projected_work = None
            if work is not None:
                interfaces = work.get("interfaces")
                title_interfaces = tuple(
                    interface for interface in interfaces
                    if (
                        isinstance(interface, dict)
                        and interface.get("name") == "title"
                    )
                ) if isinstance(interfaces, (list, tuple)) else ()
                title_interface = (
                    title_interfaces[0]
                    if len(title_interfaces) == 1
                    else None
                )
                title = (
                    title_interface.get("value")
                    if isinstance(title_interface, dict)
                    else None
                )
                root = work.get("root")
                if (
                    type(root) is not str
                    or not root
                    or type(title) is not str
                    or not title.strip()
                ):
                    raise InvalidCell(
                        "current Work projection is malformed"
                    )
                projected_work = {"root": root, "title": title}
            return {
                "agent_session": agent_session_root,
                "work": projected_work,
                "revision": revision,
            }
        if method == "GET" and path == "/api/universal/grand-map-work":
            if set(body) - {"limit", "include_live"}:
                raise InvalidCell(
                    "Grand Map Work projection request shape is invalid"
                )
            if self.universal_checkpoint_guard is not None:
                self.universal_checkpoint_guard.require_healthy()
            self.require_universal_http_route(
                method, path, authentication_context=context
            )
            request_agent_session = (
                self.universal_registry.agent_body.session.root_id
                if direct or request.get("session") == {}
                else self._resolve_universal_machine_agent_session(request)
            )
            return {
                "ok": True,
                "agent_session": request_agent_session,
                **project_universal_grand_map_work(
                    self.universal_store,
                    self.universal_registry,
                    limit=int(body.get("limit", 50)),
                    include_live=bool(body.get("include_live", False)),
                    authentication_context=context,
                ),
            }
        if method == "GET" and path == "/api/universal/roma-tree":
            if set(body) - {"tree_id"}:
                raise InvalidCell("ROMA tree projection request shape is invalid")
            tree_id = body.get("tree_id", "")
            if type(tree_id) is not str:
                raise InvalidCell("ROMA tree projection request id is invalid")
            if self.universal_checkpoint_guard is not None:
                self.universal_checkpoint_guard.require_healthy()
            self.require_universal_http_route(
                method, path, authentication_context=context
            )
            request_agent_session = (
                self.universal_registry.agent_body.session.root_id
                if direct or request.get("session") == {}
                else self._resolve_universal_machine_agent_session(request)
            )
            if tree_id.strip():
                return {
                    "agent_session": request_agent_session,
                    **project_universal_roma_requirement_tree(
                        self.universal_store,
                        self.universal_registry,
                        tree_id=tree_id,
                        authentication_context=context,
                    ),
                }
            return {
                "agent_session": request_agent_session,
                **project_universal_roma_requirement_tree_index(
                    self.universal_store,
                    self.universal_registry,
                    authentication_context=context,
                ),
            }
        if method == "GET" and path == "/api/universal/baboom-context":
            if body:
                raise InvalidCell("BABOOM context request must be empty")
            if self.universal_checkpoint_guard is not None:
                self.universal_checkpoint_guard.require_healthy()
            self.require_universal_http_route(
                method, path, authentication_context=context
            )
            # This is a content-free, revision-bound read lens. It must not
            # queue behind a long mutation when BABOOM is only observing work.
            runtime_presence = self._machine_agent_runtime_presence()
            work_index = self._project_universal_machine_work_index(
                authentication_context=context
            )
            return project_universal_baboom_context(
                self.universal_store,
                self.universal_registry,
                runtime_presence=runtime_presence,
                authentication_context=context,
                work_index=work_index,
            )
        if method == "GET" and path == "/api/universal/runtime-backend":
            if body:
                raise InvalidCell("runtime backend request must be empty")
            if self.universal_checkpoint_guard is not None:
                self.universal_checkpoint_guard.require_healthy()
            self.require_universal_http_route(
                method, path, authentication_context=context
            )
            backend = self.prove_runtime_backend_generation()
            return {
                "application": self.universal_registry.application_root,
                "server_url": backend.url,
                "generation": backend.generation,
                "ownership_root": backend.ownership_root,
            }
        if method == "GET" and path == "/api/universal/runtime-handoff-readiness":
            if body:
                raise InvalidCell("runtime handoff readiness request must be empty")
            if self.universal_checkpoint_guard is not None:
                self.universal_checkpoint_guard.require_healthy()
            self.require_universal_http_route(
                method, path, authentication_context=context
            )
            # This readiness lens is evidence, not a lifecycle command. The
            # lock only keeps Work and ownership facts at one graph revision.
            with self.mutation_lock:
                work_index = self._project_universal_machine_work_index(
                    authentication_context=context
                )
                return project_universal_runtime_handoff_readiness(
                    self.universal_store,
                    self.universal_registry,
                    authentication_context=context,
                    work_index=work_index,
                )
        if method == "GET" and path == "/api/universal/baboom-presence":
            if body:
                raise InvalidCell("BABOOM companion directive request must be empty")
            if self.universal_checkpoint_guard is not None:
                self.universal_checkpoint_guard.require_healthy()
            self.require_universal_http_route(
                method, path, authentication_context=context
            )
            runtime_presence = self._machine_agent_runtime_presence()
            work_index = self._project_universal_machine_work_index(
                authentication_context=context
            )
            return project_universal_baboom_companion_directive(
                self.universal_store,
                self.universal_registry,
                runtime_presence=runtime_presence,
                authentication_context=context,
                work_index=work_index,
            )
        if method == "GET" and path == "/api/universal/baboom-native-frame":
            if body:
                raise InvalidCell("BABOOM native frame request must be empty")
            if self.universal_checkpoint_guard is not None:
                self.universal_checkpoint_guard.require_healthy()
            self.require_universal_http_route(
                method, path, authentication_context=context
            )
            if not direct and request.get("session") != {}:
                _session_root, binding = self._machine_agent_binding_for_request(
                    request
                )
                if binding.get("runtime") not in {"baboom", "baboom-execution"}:
                    raise AuthorizationDenied(
                        "BABOOM native frame requires the founder or BABOOM body"
                    )
            # The companion needs one coherent graph revision for both its
            # visible report and its active stewardship state. This combines
            # existing Cell projections; it does not create renderer authority.
            with self.mutation_lock:
                runtime_presence = self._machine_agent_runtime_presence()
                work_index = self._project_universal_machine_work_index(
                    authentication_context=context
                )
                baboom_context = project_universal_baboom_context(
                    self.universal_store,
                    self.universal_registry,
                    runtime_presence=runtime_presence,
                    authentication_context=context,
                    work_index=work_index,
                )
                directive = project_universal_baboom_companion_directive(
                    self.universal_store,
                    self.universal_registry,
                    runtime_presence=runtime_presence,
                    authentication_context=context,
                    work_index=work_index,
                )
                revision = self.universal_store.revision
                if (
                    baboom_context.get("revision") != revision
                    or directive.get("revision") != revision
                ):
                    raise InvalidCell("BABOOM native frame revision drifted")
                action = directive.get("action")
                if type(action) is not str:
                    raise InvalidCell("BABOOM native frame action is invalid")
                report = None
                if action:
                    briefing = project_universal_founder_baboom_steward_briefing(
                        self.universal_store,
                        self.universal_registry,
                        authentication_context=context,
                    )
                    if briefing.get("revision") != revision:
                        raise InvalidCell("BABOOM native frame report drifted")
                    report = {
                        "kind": BABOOM_NATIVE_REPORT_KIND,
                        "summary": BABOOM_NATIVE_REPORT_SUMMARY,
                        "revision": revision,
                        "data": briefing,
                    }
                ttl = directive.get("ttl_seconds")
                if type(ttl) not in (int, float) or not 0.0 < float(ttl) <= 60.0:
                    raise InvalidCell("BABOOM native frame TTL is invalid")
                issued_at = time.time()
                frame = {
                    "projection": BABOOM_NATIVE_FRAME_PROJECTION,
                    "revision": revision,
                    "issued_at": issued_at,
                    "expires_at": issued_at + float(ttl),
                    "context": baboom_context,
                    "directive": directive,
                    "report": report,
                }
                try:
                    return validate_baboom_native_frame_payload(
                        frame, now=issued_at
                    )
                except MachineTransportError as exc:
                    raise InvalidCell("BABOOM native frame is invalid") from exc
        if method == "GET" and path == "/api/universal/baboom-steward-briefing":
            if body != {"projection": "founder-briefing"}:
                raise InvalidCell(
                    "BABOOM Steward briefing projection request shape is invalid"
                )
            if self.universal_checkpoint_guard is not None:
                self.universal_checkpoint_guard.require_healthy()
            self.require_universal_http_route(
                method, path, authentication_context=context
            )
            request_agent_session = (
                self.universal_registry.agent_body.session.root_id
                if direct or request.get("session") == {}
                else self._resolve_universal_machine_agent_session(request)
            )
            if request_agent_session != (
                self.universal_registry.agent_body.session.root_id
            ):
                raise AuthorizationDenied(
                    "founder-local BABOOM Steward briefing requires the founder session"
                )
            # The briefing combines three Cell projections. Holding the same
            # server mutation lock gives the desktop one coherent revision
            # without creating a secondary Steward state authority.
            with self.mutation_lock:
                return project_universal_founder_baboom_steward_briefing(
                    self.universal_store,
                    self.universal_registry,
                    authentication_context=context,
                )
        if method == "GET" and path == "/api/universal/baboom-capabilities":
            if body:
                raise InvalidCell(
                    "BABOOM capability projection request must be empty"
                )
            if self.universal_checkpoint_guard is not None:
                self.universal_checkpoint_guard.require_healthy()
            self.require_universal_http_route(
                method, path, authentication_context=context
            )
            # Provider and route identity is graph-held. Host readiness is
            # explicitly separate, transient observation: it cannot grant a
            # provider authority or substitute for an execution receipt.
            report = project_universal_founder_baboom_capability_report(
                self.universal_store,
                self.universal_registry,
            )
            readiness_probe = getattr(
                self.model_execution_broker, "model_provider_readiness", None
            )
            raw_readiness = readiness_probe() if callable(readiness_probe) else {}
            if not isinstance(raw_readiness, dict):
                raise InvalidCell("model provider readiness projection is invalid")
            report["physical_model_readiness"] = {
                provider: {
                    **entry,
                    "released_provider_root": self.universal_registry.baboom_model_provider_roots[
                        provider
                    ],
                }
                for provider, entry in raw_readiness.items()
                if provider in self.universal_registry.baboom_model_provider_roots
                and isinstance(entry, dict)
            }
            report["physical_readiness_authority"] = (
                "transient host observation only; execution still requires graph approval and one-use grant"
            )
            return report
        if method == "POST" and path == "/api/universal/baboom-command":
            if set(body) != {"utterance"}:
                raise InvalidCell(
                    "BABOOM command resolution request shape is invalid"
                )
            if self.universal_checkpoint_guard is not None:
                self.universal_checkpoint_guard.require_healthy()
            self.require_universal_http_route(
                method, path, authentication_context=context
            )
            return resolve_universal_baboom_utterance(
                self.universal_store,
                self.universal_registry,
                utterance=body["utterance"],
                authentication_context=context,
            )
        if method == "POST" and path == "/api/universal/baboom-command-response":
            if set(body) != {"utterance"}:
                raise InvalidCell(
                    "BABOOM command response request shape is invalid"
                )
            if self.universal_checkpoint_guard is not None:
                self.universal_checkpoint_guard.require_healthy()
            self.require_universal_http_route(
                method, path, authentication_context=context
            )
            with self.mutation_lock:
                return respond_universal_baboom_utterance(
                    self.universal_store,
                    self.universal_registry,
                    utterance=body["utterance"],
                    authentication_context=context,
                )
        if method == "POST" and path == "/api/universal/baboom-command-execute":
            if set(body) != {"utterance"}:
                raise InvalidCell(
                    "BABOOM command execution request shape is invalid"
                )
            if self.universal_checkpoint_guard is not None:
                self.universal_checkpoint_guard.require_healthy()
            self.require_universal_http_route(
                method, path, authentication_context=context
            )
            with self.mutation_lock:
                return execute_universal_baboom_utterance(
                    self.universal_store,
                    self.universal_registry,
                    utterance=body["utterance"],
                    authentication_context=context,
                )
        if method == "GET" and path == "/api/universal/mcp-broker":
            if body:
                raise InvalidCell("MCP broker projection request must be empty")
            if self.universal_checkpoint_guard is not None:
                self.universal_checkpoint_guard.require_healthy()
            self.require_universal_http_route(
                method, path, authentication_context=context
            )
            return project_universal_mcp_broker(
                self.universal_store,
                self.universal_registry,
            )
        if method == "GET" and path == "/api/universal/work-handoff":
            if body:
                raise InvalidCell(
                    "device handoff projection request must be empty"
                )
            if self.universal_checkpoint_guard is not None:
                self.universal_checkpoint_guard.require_healthy()
            self.require_universal_http_route(
                method, path, authentication_context=context
            )
            if direct:
                raise AuthorizationDenied(
                    "device handoff projection requires a device-proof Agent Session"
                )
            agent_session_root = self._resolve_universal_machine_agent_session(
                request
            )
            return project_universal_device_handoffs(
                self.universal_store,
                self.universal_registry,
                agent_session_root=agent_session_root,
                authentication_context=context,
            )
        if method == "GET" and path == "/api/universal/work-claim-transfer":
            if body:
                raise InvalidCell(
                    "work claim transfer projection request must be empty"
                )
            if self.universal_checkpoint_guard is not None:
                self.universal_checkpoint_guard.require_healthy()
            self.require_universal_http_route(
                method, path, authentication_context=context
            )
            if direct:
                raise AuthorizationDenied(
                    "work claim transfer projection requires a device-proof Agent Session"
                )
            agent_session_root = self._resolve_universal_machine_agent_session(
                request
            )
            return project_universal_baboom_work_claim_transfers(
                self.universal_store,
                self.universal_registry,
                agent_session_root=agent_session_root,
                authentication_context=context,
            )
        if method == "GET" and path == "/api/universal/browser-handoff":
            if body:
                raise InvalidCell(
                    "browser handoff readiness request shape is invalid"
                )
            if self.universal_checkpoint_guard is not None:
                self.universal_checkpoint_guard.require_healthy()
            self.require_universal_http_route(
                method, path, authentication_context=context
            )
            request_agent_session = (
                self.universal_registry.agent_body.session.root_id
                if direct or request.get("session") == {}
                else self._resolve_universal_machine_agent_session(request)
            )
            return {
                "application": self.universal_registry.application_root,
                "server_url": self.public_url,
                "supported": True,
                "one_use_route": "POST /api/universal/browser-handoff",
                "agent_session": request_agent_session,
                "revision": self.universal_store.revision,
            }
        if method == "GET" and path == "/api/universal/deliberation":
            if set(body) not in (
                {"space", "limit"},
                {"space", "category", "limit"},
            ):
                raise InvalidCell("deliberation read request shape is invalid")
            space_root = body["space"]
            category_root = body.get("category")
            limit = body["limit"]
            if (
                type(space_root) is not str
                or (
                    category_root is not None
                    and (
                        type(category_root) is not str
                        or not category_root
                        or len(category_root.encode("utf-8")) > 4_096
                    )
                )
                or type(limit) is not int
                or not 1 <= limit <= 500
            ):
                raise InvalidCell("deliberation read request values are invalid")
            if self.universal_checkpoint_guard is not None:
                self.universal_checkpoint_guard.require_healthy()
            self.require_universal_http_route(
                method, path, authentication_context=context
            )
            snapshot = self.universal_store.snapshot()
            entries = read_authorized_deliberation_entries(
                snapshot,
                self.universal_registry.deliberation_protocol,
                space_root=space_root,
                read_action_root=(
                    self.universal_registry.authorization.protocol.actions["read"]
                ),
                authorization_protocol=(
                    self.universal_registry.authorization.protocol
                ),
                authentication_broker=(
                    self.universal_registry.authorization.broker
                ),
                authentication_context=context,
            )
            if category_root is not None:
                entries = tuple(
                    entry for entry in entries
                    if entry.category_root == category_root
                )
            projected = []
            for entry in entries[-limit:]:
                payload = None
                payload_truncated = False
                if len(entry.reference_roots) == 1:
                    try:
                        payload = read_value_graph(
                            snapshot,
                            self.universal_registry.value_graph_protocol,
                            entry.reference_roots[0],
                        )
                        payload, payload_truncated = (
                            _bounded_machine_deliberation_payload(payload)
                        )
                    except InvalidCell:
                        payload = None
                item = {
                    "root": entry.root_id,
                    "actor": entry.actor_root,
                    "category_root": entry.category_root,
                    "summary": entry.content,
                    "reference_roots": list(entry.reference_roots),
                    "payload": payload,
                    "created_at": entry.created_at,
                    "sequence": entry.sequence,
                    "idempotency_key": entry.idempotency_key,
                }
                if payload_truncated:
                    item["payload_truncated"] = True
                projected.append(item)
            return _validated_machine_deliberation_response({
                "ok": True,
                "application": self.universal_registry.application_root,
                "space": space_root,
                "total": len(entries),
                "entries": projected,
                "revision": snapshot.revision,
            })
        if method == "GET" and path == "/api/universal/workshop-assignments":
            if body:
                raise InvalidCell(
                    "Workshop assignment projection request must be empty"
                )
            if self.universal_checkpoint_guard is not None:
                self.universal_checkpoint_guard.require_healthy()
            self.require_universal_http_route(
                method, path, authentication_context=context
            )
            assignments = list_universal_workshop_assignments(
                self.universal_store,
                self.universal_registry,
                authentication_context=context,
            )
            return {
                "application": self.universal_registry.application_root,
                "workshop": self.universal_registry.workshop_root,
                "registry": (
                    self.universal_registry.workshop_assignment_registry_root
                ),
                "assignments": [
                    {
                        "root": item.root_id,
                        "work": item.work_root,
                        "agent_session": item.agent_session_root,
                        "obligation": item.obligation_root,
                    }
                    for item in assignments
                ],
                "revision": self.universal_store.revision,
            }
        if method == "GET" and path == "/api/universal/workshop":
            if self.universal_checkpoint_guard is not None:
                self.universal_checkpoint_guard.require_healthy()
            self.require_universal_http_route(
                method, path, authentication_context=context
            )
            request_agent_session = (
                self.universal_registry.agent_body.session.root_id
                if direct or request.get("session") == {}
                else self._resolve_universal_machine_agent_session(request)
            )
            if body:
                if (
                    set(body) != {"projection"}
                    or body["projection"] != "founder-report"
                ):
                    raise InvalidCell(
                        "Workshop report projection request shape is invalid"
                    )
                if request_agent_session != (
                    self.universal_registry.agent_body.session.root_id
                ):
                    raise AuthorizationDenied(
                        "founder-local Workshop report requires the founder session"
                    )
                return {
                    "application": self.universal_registry.application_root,
                    "agent_session": request_agent_session,
                    "workshop": self.universal_registry.workshop_root,
                    **project_universal_founder_workshop_report(
                        self.universal_store,
                        self.universal_registry,
                    ),
                }
            return self._project_universal_machine_workshop(
                request_agent_session=request_agent_session,
            )
        if method == "GET" and path == "/api/universal/devices":
            if body != {"projection": "founder-report"}:
                raise InvalidCell(
                    "device custody projection request shape is invalid"
                )
            if self.universal_checkpoint_guard is not None:
                self.universal_checkpoint_guard.require_healthy()
            self.require_universal_http_route(
                method, path, authentication_context=context
            )
            request_agent_session = (
                self.universal_registry.agent_body.session.root_id
                if direct or request.get("session") == {}
                else self._resolve_universal_machine_agent_session(request)
            )
            if request_agent_session != (
                self.universal_registry.agent_body.session.root_id
            ):
                raise AuthorizationDenied(
                    "founder-local device custody requires the founder session"
                )
            return {
                "application": self.universal_registry.application_root,
                "agent_session": request_agent_session,
                **project_universal_founder_device_custody_report(
                    self.universal_store,
                    self.universal_registry,
                ),
            }
        with self.mutation_lock:
            if self.universal_checkpoint_guard is not None:
                self.universal_checkpoint_guard.require_healthy()
            self.require_universal_http_route(
                method, path, authentication_context=context
            )
            if method == "GET" and path == "/api/universal/canvas":
                projection = project_universal_canvas(
                    self.universal_store,
                    self.universal_registry,
                    authentication_context=context,
                )
                node_limit = 256
                wire_limit = 512
                catalog_limit = 256
                property_limit = 512
                nodes = [
                    {
                        "id": node.get("id"),
                        "label": node.get("label"),
                        "x": node.get("x", 0),
                        "y": node.get("y", 0),
                        "openable": bool(node.get("openable")),
                        "selected": bool(node.get("selected")),
                        "member_count": node.get("member_count", 0),
                        "connection_count": node.get("connection_count", 0),
                        "ports": node.get("ports", []),
                        "physical": node.get("physical", {}),
                    }
                    for node in projection.get("nodes", [])[:node_limit]
                ]
                wires = [
                    {
                        "id": wire.get("id"),
                        "source": wire.get("source"),
                        "source_interface": wire.get("source_interface"),
                        "target": wire.get("target"),
                        "target_interface": wire.get("target_interface"),
                        "source_incidence": wire.get("source_incidence"),
                        "target_incidence": wire.get("target_incidence"),
                        "authority_roots": wire.get("authority_roots", []),
                        "directed": bool(wire.get("directed")),
                        "nary": bool(wire.get("nary")),
                    }
                    for wire in projection.get("wires", [])[:wire_limit]
                ]
                catalog = [
                    {
                        "id": item.get("id"),
                        "label": item.get("label"),
                        "title": item.get("title"),
                    }
                    for item in projection.get("catalog", [])[:catalog_limit]
                ]
                properties = [
                    {
                        "id": item.get("id"),
                        "label": item.get("label"),
                        "name": item.get("name"),
                        "value": item.get("value"),
                    }
                    for item in projection.get("properties", [])[:property_limit]
                ]
                return {
                    "ok": True,
                    "application": self.universal_registry.application_root,
                    "agent_session": (
                        self.universal_registry.agent_body.session.root_id
                        if direct or request.get("session") == {}
                        else self._resolve_universal_machine_agent_session(request)
                    ),
                    "canvas_root": projection["canvas_root"],
                    "application_root": projection["application_root"],
                    "revision": projection["revision"],
                    "scope": projection.get("scope", {}),
                    "nodes": nodes,
                    "wires": wires,
                    "catalog": catalog,
                    "properties": properties,
                    "selection": projection.get("selection", []),
                    "inspector": {
                        "selected": projection.get("inspector", {}).get(
                            "selected"
                        ),
                        "lens": projection.get("inspector", {}).get("lens"),
                    },
                    "viewport": projection.get("viewport", {}),
                    "machine_projection": {
                        "kind": "bounded-canvas-summary",
                        "node_limit": node_limit,
                        "wire_limit": wire_limit,
                        "catalog_limit": catalog_limit,
                        "property_limit": property_limit,
                        "node_count": len(projection.get("nodes", [])),
                        "wire_count": len(projection.get("wires", [])),
                        "catalog_count": len(projection.get("catalog", [])),
                        "property_count": len(projection.get("properties", [])),
                        "truncated": (
                            len(projection.get("nodes", [])) > node_limit
                            or len(projection.get("wires", [])) > wire_limit
                            or len(projection.get("catalog", [])) > catalog_limit
                            or len(projection.get("properties", []))
                            > property_limit
                        ),
                    },
                }
            if method == "GET":
                request_agent_session = (
                    self.universal_registry.agent_body.session.root_id
                    if direct or request.get("session") == {}
                    else self._resolve_universal_machine_agent_session(request)
                )
                if path == "/api/universal/attention":
                    if (
                        set(body) != {"projection"}
                        or body["projection"] != "founder-briefing"
                    ):
                        raise InvalidCell(
                            "Attention briefing projection request shape is invalid"
                        )
                    if request_agent_session != (
                        self.universal_registry.agent_body.session.root_id
                    ):
                        raise AuthorizationDenied(
                            "founder-local attention briefing requires the founder session"
                        )
                    self.require_universal_http_route(
                        method, path, authentication_context=context
                    )
                    return {
                        "application": self.universal_registry.application_root,
                        "agent_session": request_agent_session,
                        **project_universal_founder_attention_briefing(
                            self.universal_store,
                            self.universal_registry,
                        ),
                    }
                if path == "/api/universal/workshop":
                    if body:
                        if (
                            set(body) != {"projection"}
                            or body["projection"] != "founder-report"
                        ):
                            raise InvalidCell(
                                "Workshop report projection request shape is invalid"
                            )
                        if request_agent_session != (
                            self.universal_registry.agent_body.session.root_id
                        ):
                            raise AuthorizationDenied(
                                "founder-local Workshop report requires the founder session"
                            )
                        self.require_universal_http_route(
                            method, path, authentication_context=context
                        )
                        return {
                            "application": self.universal_registry.application_root,
                            "agent_session": request_agent_session,
                            "workshop": self.universal_registry.workshop_root,
                            **project_universal_founder_workshop_report(
                                self.universal_store,
                                self.universal_registry,
                            ),
                        }
                    snapshot = self.universal_store.snapshot()
                    entries = list_deliberation_entries(
                        snapshot,
                        self.universal_registry.deliberation_protocol,
                        self.universal_registry.workshop_root,
                    )
                    categories = {
                        root: name
                        for name, root in (
                            self.universal_registry
                            .workshop_category_roots.items()
                        )
                    }
                    return {
                        "application": (
                            self.universal_registry.application_root
                        ),
                        "agent_session": request_agent_session,
                        "workshop": self.universal_registry.workshop_root,
                        "revision": snapshot.revision,
                        "categories": dict(
                            self.universal_registry.workshop_category_roots
                        ),
                        "phases": dict(
                            self.universal_registry.workshop_phase_roots
                        ),
                        "requirements": list(
                            self.universal_registry
                            .workshop_requirement_roots
                        ),
                        "entries": [
                            {
                                "root": entry.root_id,
                                "sequence": entry.sequence,
                                "actor": entry.actor_root,
                                "kind": categories.get(
                                    entry.category_root,
                                    entry.category_root,
                                ),
                                "category_root": entry.category_root,
                                "recipients": list(entry.recipient_roots),
                                "refs": list(entry.reference_roots),
                                "evidence": list(entry.evidence_roots),
                                "reply_to": entry.reply_to_root,
                                "text": entry.content,
                                "created_at": entry.created_at,
                            }
                            for entry in entries
                        ],
                    }
                if body:
                    if set(body) != {"projection"} or body["projection"] != "index":
                        raise InvalidCell(
                            "work projection request shape is invalid"
                        )
                    index = self._project_universal_machine_work_index(
                        authentication_context=context,
                    )
                    return {
                        "agent_session": request_agent_session,
                        "workshop": self.universal_registry.workshop_root,
                        **index,
                    }
                status = project_universal_governed_work_status(
                    self.universal_store,
                    self.universal_registry,
                    authentication_context=context,
                )
                snapshot = self.universal_store.snapshot()
                workshop_entries = list_deliberation_entries(
                    snapshot,
                    self.universal_registry.deliberation_protocol,
                    self.universal_registry.workshop_root,
                )
                baboom_entry = _agent_body_catalog_entry_for_runtime(
                    snapshot, self.universal_registry, "baboom"
                )
                baboom_execution_entry = _agent_body_catalog_entry_for_runtime(
                    snapshot, self.universal_registry, "baboom-execution"
                )
                return {
                    "application": self.universal_registry.application_root,
                    "agent_session": (
                        request_agent_session
                    ),
                    "brain_scope": self.universal_registry.map.domains["brain"],
                    "workshop": self.universal_registry.workshop_root,
                    "workshop_status": {
                        "root": self.universal_registry.workshop_root,
                        "entry_count": len(workshop_entries),
                        "categories": dict(
                            self.universal_registry.workshop_category_roots
                        ),
                        "phases": dict(
                            self.universal_registry.workshop_phase_roots
                        ),
                        "requirements": list(
                            self.universal_registry.workshop_requirement_roots
                        ),
                    },
                    "baboom": {
                        "catalog_entry": baboom_entry.root_id,
                        "agent_body": baboom_entry.body_root,
                        "control": baboom_entry.control_root,
                        "credential_mode": baboom_entry.credential_mode,
                        "runtime": baboom_entry.runtime,
                        "grand_map_node": baboom_entry.grand_map_node_root,
                        "action_capability": {
                            "catalog_entry": baboom_execution_entry.root_id,
                            "control": baboom_execution_entry.control_root,
                            "credential_mode": baboom_execution_entry.credential_mode,
                            "runtime_profile": baboom_execution_entry.runtime,
                            "work_events": list(baboom_execution_entry.work_events),
                        },
                        "model_execution": status["model_execution"],
                    },
                    **status,
                }
            if path == "/api/universal/agent-session":
                if not direct and request.get("session") != {}:
                    raise AuthorizationDenied(
                        "Agent Session enrollment must be unbound"
                    )
                return self._enroll_universal_machine_agent_session(
                    body,
                    runtime_id=str(request.get("runtime_id") or ""),
                )
            if path == "/api/universal/agent-session-resume":
                if not direct and request.get("session") != {}:
                    raise AuthorizationDenied(
                        "Agent Session recovery must be unbound"
                    )
                return self._resume_universal_machine_agent_session(
                    body,
                    runtime_id=str(request.get("runtime_id") or ""),
                )
            if path == "/api/universal/agent-session-challenge":
                if not direct and request.get("session") != {}:
                    raise AuthorizationDenied(
                        "Agent Session challenge must be unbound"
                    )
                return self._issue_universal_machine_agent_session_challenge(
                    body,
                    runtime_id=str(request.get("runtime_id") or ""),
                )
            if path == "/api/universal/agent-session-renew":
                if direct or body:
                    raise AuthorizationDenied(
                        "Agent Session renewal requires its bound empty request"
                    )
                return self._renew_universal_machine_agent_session(request)
            if path == "/api/universal/runtime-presence":
                if direct or body:
                    raise AuthorizationDenied(
                        "runtime presence requires its bound empty request"
                    )
                return self._renew_universal_runtime_presence(request)
            if path == "/api/universal/runtime-handoff":
                expected_shape = {
                    "phase", "work", "server_url", "generation",
                    "ownership_root",
                }
                if direct or set(body) != expected_shape:
                    raise AuthorizationDenied(
                        "runtime handoff requires its bound exact request"
                    )
                phase = body["phase"]
                if phase not in {"prepare", "finalize"}:
                    raise InvalidCell("runtime handoff phase is invalid")
                if (
                    type(body["work"]) is not str
                    or not body["work"]
                    or type(body["server_url"]) is not str
                    or type(body["generation"]) is not int
                    or body["generation"] <= 0
                    or type(body["ownership_root"]) is not str
                    or not body["ownership_root"]
                ):
                    raise InvalidCell("runtime handoff values are invalid")
                agent_session_root = (
                    self._resolve_universal_machine_agent_session(request)
                )
                expected_state = "active" if phase == "prepare" else "draining"
                backend = self._prove_runtime_backend_state(expected_state)
                if (
                    body["server_url"] != backend.url
                    or body["generation"] != backend.generation
                    or body["ownership_root"] != backend.ownership_root
                ):
                    raise AuthorizationDenied(
                        "runtime handoff generation does not match this worker"
                    )
                verify_universal_runtime_handoff_work(
                    self.universal_store,
                    self.universal_registry,
                    body["work"],
                    agent_session_root=agent_session_root,
                    expected_generation=backend.generation,
                    expected_ownership_root=backend.ownership_root,
                    authentication_context=context,
                )
                if phase == "prepare":
                    if (
                        self._public_server_url is not None
                        and self._runtime_drain_coordinator is None
                    ):
                        raise InvalidCell(
                            "stable runtime handoff requires its parent drain pipe"
                        )
                    if self._runtime_drain_coordinator is not None:
                        try:
                            self._runtime_drain_coordinator(backend)
                        except Exception:
                            self._runtime_handoff_exit.set()
                            raise
                    self._begin_runtime_drain()
                    accepted = self._prove_runtime_backend_state("draining")
                    result_phase = "draining"
                else:
                    self._release_runtime_ownership()
                    accepted = self._prove_runtime_backend_state("released")
                    result_phase = "released"
                result = {
                    "application": self.universal_registry.application_root,
                    "agent_session": agent_session_root,
                    "generation": accepted.generation,
                    "ownership_root": accepted.ownership_root,
                    "phase": result_phase,
                    "work": body["work"],
                }
                if phase == "finalize":
                    result["signal_after_response"] = True
                return result
            if path == "/api/universal/browser-handoff":
                if (not direct and request.get("session") != {}) or body:
                    raise AuthorizationDenied(
                        "browser handoff requires its unbound empty request"
                    )
                with self._browser_session_lock:
                    self.browser_bootstrap_token = secrets.token_urlsafe(32)
                    bootstrap_url = self.bootstrap_url
                return {
                    "application": self.universal_registry.application_root,
                    "server_url": self.public_url,
                    "document_url": bootstrap_url,
                    "schema_version": UNIVERSAL_APPLICATION_SCHEMA_VERSION,
                    "one_use": True,
                    "session_root": self.browser_session_root,
                    "revision": self.universal_store.revision,
                }
            if path == "/api/universal/grand-map-work":
                if set(body) - {"limit", "include_live"}:
                    raise InvalidCell(
                        "Grand Map Work sync request shape is invalid"
                    )
                request_agent_session = (
                    self.universal_registry.agent_body.session.root_id
                    if direct or request.get("session") == {}
                    else self._resolve_universal_machine_agent_session(request)
                )
                return {
                    "ok": True,
                    "agent_session": request_agent_session,
                    **sync_universal_grand_map_work(
                        self.universal_store,
                        self.universal_registry,
                        limit=int(body.get("limit", 25)),
                        include_live=bool(body.get("include_live", False)),
                        authentication_context=context,
                    ),
                }
            if path == "/api/universal/roma-tree":
                if set(body) - {"tree", "source"}:
                    raise InvalidCell("ROMA tree sync request shape is invalid")
                tree = body.get("tree")
                if type(tree) is not dict:
                    raise InvalidCell("ROMA tree sync request tree is invalid")
                source = body.get("source", "machine.roma")
                if type(source) is not str or not source.strip():
                    raise InvalidCell("ROMA tree sync request source is invalid")
                request_agent_session = (
                    self.universal_registry.agent_body.session.root_id
                    if direct or request.get("session") == {}
                    else self._resolve_universal_machine_agent_session(request)
                )
                return {
                    "agent_session": request_agent_session,
                    **sync_universal_roma_requirement_tree(
                        self.universal_store,
                        self.universal_registry,
                        tree,
                        source=source,
                        authentication_context=context,
                    ),
                }
            if path == "/api/universal/agent-body-device-custody":
                if direct or set(body) != {"runtime", "custody_root"}:
                    raise AuthorizationDenied(
                        "runtime device custody binding requires its bound exact request"
                    )
                runtime = body["runtime"]
                custody_root = body["custody_root"]
                if (
                    type(runtime) is not str
                    or not runtime.strip()
                    or len(runtime.encode("utf-8")) > 128
                    or type(custody_root) is not str
                    or not custody_root
                    or len(custody_root.encode("utf-8")) > 512
                ):
                    raise InvalidCell("runtime device custody binding is invalid")
                actor_session_root = self._resolve_universal_machine_agent_session(
                    request
                )
                actor_session = read_agent_session(
                    self.universal_store.snapshot(),
                    self.universal_registry.agent_body.protocol,
                    self.universal_registry.authorization.protocol,
                    actor_session_root,
                )
                actor_entry = _agent_body_catalog_entry_for_session(
                    self.universal_store.snapshot(),
                    self.universal_registry,
                    actor_session,
                )
                if (
                    actor_entry.runtime != "*"
                    or actor_entry.credential_mode != "machine-transport"
                    or actor_entry.body_root
                    != self.universal_registry.agent_body.body.root_id
                ):
                    raise AuthorizationDenied(
                        "only a founder machine Agent Session may bind device custody"
                    )
                target_entry = _agent_body_catalog_entry_for_runtime(
                    self.universal_store.snapshot(),
                    self.universal_registry,
                    runtime.strip(),
                )
                revision = bind_universal_runtime_agent_body_device_custody(
                    self.universal_store,
                    self.universal_registry,
                    runtime=runtime.strip(),
                    custody_root=custody_root,
                    authentication_context=context,
                )
                return {
                    "runtime": runtime.strip(),
                    "catalog_entry": target_entry.root_id,
                    "agent_body": target_entry.body_root,
                    "custody_root": custody_root,
                    "revision": self.universal_store.revision,
                }
            if path == "/api/universal/device-custody-revoke":
                if set(body) != {"device_ref", "reason_code"}:
                    raise InvalidCell(
                        "device custody revocation request shape is invalid"
                    )
                request_agent_session = (
                    self.universal_registry.agent_body.session.root_id
                    if direct or request.get("session") == {}
                    else self._resolve_universal_machine_agent_session(request)
                )
                if request_agent_session != (
                    self.universal_registry.agent_body.session.root_id
                ):
                    raise AuthorizationDenied(
                        "founder device custody revocation requires the founder session"
                    )
                device_ref, revision = revoke_universal_founder_device_custody(
                    self.universal_store,
                    self.universal_registry,
                    device_ref=body["device_ref"],
                    reason_code=body["reason_code"],
                    authentication_context=context,
                )
                return {
                    "application": self.universal_registry.application_root,
                    "agent_session": request_agent_session,
                    "device_ref": device_ref,
                    "state": "revoked",
                    "reason_code": body["reason_code"],
                    "revision": revision,
                }
            if path == "/api/universal/cde-write-receipt":
                expected = {
                    "permit", "operation", "path", "content_digest",
                    "request_id",
                }
                if direct or set(body) != expected:
                    raise AuthorizationDenied(
                        "CDE receipt requires one bound exact write result"
                    )
                if (
                    self.cde_write_signing_provider is None
                    or self.cde_write_signing_descriptor_root is None
                ):
                    raise AuthorizationDenied(
                        "CDE signing authority is unavailable"
                    )
                if self.universal_checkpoint_guard is not None:
                    self.universal_checkpoint_guard.require_healthy()
                self.require_universal_http_route(
                    "POST",
                    path,
                    authentication_context=context,
                )
                agent_session_root = (
                    self._resolve_universal_machine_agent_session(request)
                )
                admission = authorize_universal_cde_write(
                    self.universal_store,
                    self.universal_registry,
                    agent_session_root=agent_session_root,
                    operation=body["operation"],
                    path=body["path"],
                    authentication_context=context,
                )
                snapshot = self.universal_store.snapshot()
                if snapshot.revision != admission.authority_revision:
                    raise AuthorizationDenied(
                        "CDE receipt admission revision drifted"
                    )
                session = read_agent_session(
                    snapshot,
                    self.universal_registry.agent_body.protocol,
                    self.universal_registry.authorization.protocol,
                    agent_session_root,
                )
                runtime = _agent_body_catalog_entry_for_session(
                    snapshot, self.universal_registry, session
                ).runtime
                receipt, revision = consume_cde_write_permit(
                    self.universal_store,
                    self.universal_registry.cde_write_authority_protocol,
                    self.universal_registry.cde_signing_protocol,
                    self.cde_write_signing_provider,
                    body["permit"],
                    runtime=runtime,
                    agent_session_root=agent_session_root,
                    work_root=admission.work_root,
                    container_root=admission.container_root,
                    container_id=admission.container_id,
                    container_digest=admission.container_digest,
                    operation=admission.operation,
                    path=admission.path,
                    content_digest=body["content_digest"],
                    request_id=body["request_id"],
                    authorization_evidence=admission.claim_binding_root,
                    authority_revision=admission.authority_revision,
                    now=time.time(),
                )
                return {
                    "receipt": receipt.root_id,
                    "permit": receipt.permit_root,
                    "kind": "consumed",
                    "receipt_digest": receipt.digest,
                    "agent_session": agent_session_root,
                    "work": admission.work_root,
                    "claim_binding": admission.claim_binding_root,
                    "container_root": admission.container_root,
                    "revision": revision,
                }
            if path == "/api/universal/model-delegation":
                if direct or set(body) != {
                    "root", "provider", "model", "data_class", "cognition_request",
                }:
                    raise AuthorizationDenied(
                        "model delegation requires its bound exact request"
                    )
                agent_session_root = self._resolve_universal_machine_agent_session(
                    request
                )
                delegation, task, revision = request_universal_baboom_model_execution(
                    self.universal_store,
                    self.universal_registry,
                    agent_session_root=agent_session_root,
                    work_root=body["root"],
                    provider=body["provider"],
                    model=body["model"],
                    data_class=body["data_class"],
                    cognition_request_root=body["cognition_request"],
                    authentication_context=context,
                )
                return {
                    "delegation": delegation.root_id,
                    "work": delegation.work_root,
                    "provider": delegation.provider_root,
                    "model": delegation.model,
                    "input_digest": delegation.input_digest,
                    "expires_at": delegation.expires_at,
                    "task": task,
                    "revision": revision,
                }
            if path == "/api/universal/model-delegation-approve":
                if direct or set(body) != {"delegation"}:
                    raise AuthorizationDenied(
                        "model delegation approval requires its bound exact request"
                    )
                founder_session_root = self._resolve_universal_machine_agent_session(
                    request
                )
                delegation, revision = approve_universal_baboom_model_execution(
                    self.universal_store,
                    self.universal_registry,
                    founder_agent_session_root=founder_session_root,
                    delegation_root=body["delegation"],
                    consent_broker=self.adapter_consent_broker,
                    authentication_context=context,
                )
                return {
                    "delegation": delegation.root_id,
                    "work": delegation.work_root,
                    "approved": True,
                    "expires_at": delegation.expires_at,
                    "revision": revision,
                }
            if path == "/api/universal/model-delegation-grant":
                if direct or set(body) != {"delegation"}:
                    raise AuthorizationDenied(
                        "model execution grant requires its bound exact request"
                    )
                agent_session_root = self._resolve_universal_machine_agent_session(
                    request
                )
                capability = secrets.token_urlsafe(48)
                grant_root = "app:baboom-model-grant:%s" % uuid.uuid4().hex
                expires_at = time.time() + 120.0
                delegation, task, revision = issue_universal_baboom_model_execution_grant(
                    self.universal_store,
                    self.universal_registry,
                    agent_session_root=agent_session_root,
                    delegation_root=body["delegation"],
                    grant_id=grant_root,
                    token_digest=hashlib.sha256(
                        capability.encode("utf-8")
                    ).hexdigest(),
                    expires_at=expires_at,
                    authentication_context=context,
                )
                with self._model_execution_capability_lock:
                    self._model_execution_capabilities[capability] = {
                        "grant": grant_root,
                        "delegation": delegation.root_id,
                        "session": agent_session_root,
                        "expires_at": expires_at,
                    }
                return {
                    "delegation": delegation.root_id,
                    "grant": grant_root,
                    "capability": capability,
                    "expires_at": expires_at,
                    "task": task,
                    "revision": revision,
                }
            if path == "/api/universal/model-delegation-execute":
                if direct or set(body) != {"grant", "capability"}:
                    raise AuthorizationDenied(
                        "model broker execution requires its bound exact grant"
                    )
                if type(body["capability"]) is not str:
                    raise InvalidCell("model execution capability is invalid")
                agent_session_root = self._resolve_universal_machine_agent_session(
                    request
                )
                with self._model_execution_capability_lock:
                    capability = self._model_execution_capabilities.get(
                        body["capability"], None
                    )
                if (
                    not isinstance(capability, dict)
                    or capability.get("grant") != body["grant"]
                    or capability.get("session") != agent_session_root
                    or time.time() >= capability.get("expires_at", 0.0)
                ):
                    raise AuthorizationDenied(
                        "model execution capability is invalid, expired, or replayed"
                    )
                invocation, task = prepare_universal_baboom_model_execution_invocation(
                    self.universal_store,
                    self.universal_registry,
                    agent_session_root=agent_session_root,
                    delegation_root=str(capability["delegation"]),
                    grant_root=body["grant"],
                    authentication_context=context,
                )
                delegation = read_model_delegation(
                    self.universal_store.snapshot(),
                    self.universal_registry.baboom_model_execution_protocol,
                    self.universal_registry.adapter_protocol,
                    str(capability["delegation"]),
                )
                if not delegation.cognition_request_root:
                    raise AuthorizationDenied(
                        "model broker execution requires a Cognition request"
                    )
                with self._model_execution_capability_lock:
                    active_capability = self._model_execution_capabilities.pop(
                        body["capability"], None
                    )
                if active_capability is not capability:
                    raise AuthorizationDenied(
                        "model execution capability is invalid, expired, or replayed"
                    )
                try:
                    execution = self.model_execution_broker.execute(
                        provider=invocation["provider"],
                        location=invocation["location"],
                        model=invocation["model"],
                        data_class=invocation["data_class"],
                        task=task,
                    )
                    outcome = execution.outcome
                    output_digest = execution.output_digest
                    output_bytes = execution.output_bytes
                    error_code = execution.error_code
                    proposal_payload = execution.proposal_payload
                except Exception:
                    outcome = "failed"
                    output_digest = hashlib.sha256(b"").hexdigest()
                    output_bytes = 0
                    error_code = "broker_fault"
                    proposal_payload = None
                if (
                    outcome not in {"succeeded", "failed"}
                    or type(output_digest) is not str
                    or len(output_digest) != 64
                    or any(character not in "0123456789abcdef" for character in output_digest)
                    or type(output_bytes) is not int
                    or not 0 <= output_bytes <= 16 * 1024 * 1024
                    or type(error_code) is not str
                    or (outcome == "succeeded" and error_code)
                    or (
                        outcome == "failed"
                        and re.fullmatch(r"[a-z0-9]+(?:[._-][a-z0-9]+)*", error_code)
                        is None
                    )
                ):
                    outcome = "failed"
                    output_digest = hashlib.sha256(b"").hexdigest()
                    output_bytes = 0
                    error_code = "broker_fault"
                    proposal_payload = None
                proposal = None
                if outcome == "succeeded":
                    if type(proposal_payload) is not dict:
                        outcome = "failed"
                        error_code = "invalid_model_output"
                    else:
                        try:
                            proposal, _proposal_revision = (
                                record_universal_baboom_cognition_proposal(
                                    self.universal_store,
                                    self.universal_registry,
                                    agent_session_root=agent_session_root,
                                    delegation_root=str(capability["delegation"]),
                                    cognition_request_root=delegation.cognition_request_root,
                                    output_digest=output_digest,
                                    output_bytes=output_bytes,
                                    proposal_payload=proposal_payload,
                                    authentication_context=context,
                                )
                            )
                        except (AuthorizationDenied, InvalidCell):
                            outcome = "failed"
                            error_code = "proposal_rejected"
                receipt, history_root, revision = settle_universal_baboom_model_execution(
                    self.universal_store,
                    self.universal_registry,
                    agent_session_root=agent_session_root,
                    delegation_root=str(capability["delegation"]),
                    grant_root=body["grant"],
                    output_digest=output_digest,
                    output_bytes=output_bytes,
                    outcome=outcome,
                    error_code=error_code,
                    authentication_context=context,
                )
                status = project_universal_governed_work_status(
                    self.universal_store,
                    self.universal_registry,
                    authentication_context=context,
                )
                result = {
                    "receipt": receipt.root_id,
                    "delegation": receipt.delegation_root,
                    "history_root": history_root,
                    "reconciled": (
                        receipt.outcome == "succeeded" and proposal is not None
                    ),
                    "work_advanced": bool(history_root),
                    "revision": revision,
                    "status": status,
                }
                if proposal is not None:
                    result["proposal"] = proposal.root_id
                return result
            if path == "/api/universal/model-delegation-receipt":
                receipt_fields = {
                    "grant", "capability", "outcome", "output_digest",
                    "output_bytes", "error_code",
                }
                proposal_fields = {"cognition_request", "proposal"}
                fields = set(body)
                if (
                    direct
                    or fields not in (receipt_fields, receipt_fields | proposal_fields)
                ):
                    raise AuthorizationDenied(
                        "model execution receipt requires its bound exact request"
                    )
                if type(body["capability"]) is not str:
                    raise InvalidCell("model execution capability is invalid")
                include_proposal = proposal_fields.issubset(fields)
                if include_proposal and body["outcome"] != "succeeded":
                    raise InvalidCell(
                        "BABOOM Cognition proposal requires a successful model outcome"
                    )
                if include_proposal and (
                    type(body["cognition_request"]) is not str
                    or type(body["proposal"]) is not dict
                ):
                    raise InvalidCell("BABOOM Cognition proposal receipt facts are invalid")
                agent_session_root = self._resolve_universal_machine_agent_session(
                    request
                )
                with self._model_execution_capability_lock:
                    capability = self._model_execution_capabilities.get(
                        body["capability"], None
                    )
                if (
                    not isinstance(capability, dict)
                    or capability.get("grant") != body["grant"]
                    or capability.get("session") != agent_session_root
                    or time.time() >= capability.get("expires_at", 0.0)
                ):
                    raise AuthorizationDenied(
                        "model execution capability is invalid, expired, or replayed"
                    )
                proposal = None
                if include_proposal:
                    proposal, _proposal_revision = (
                        record_universal_baboom_cognition_proposal(
                            self.universal_store,
                            self.universal_registry,
                            agent_session_root=agent_session_root,
                            delegation_root=str(capability["delegation"]),
                            cognition_request_root=body["cognition_request"],
                            output_digest=body["output_digest"],
                            output_bytes=body["output_bytes"],
                            proposal_payload=body["proposal"],
                            authentication_context=context,
                        )
                    )
                receipt, history_root, revision = settle_universal_baboom_model_execution(
                    self.universal_store,
                    self.universal_registry,
                    agent_session_root=agent_session_root,
                    delegation_root=str(capability["delegation"]),
                    grant_root=body["grant"],
                    output_digest=body["output_digest"],
                    output_bytes=body["output_bytes"],
                    outcome=body["outcome"],
                    error_code=body["error_code"],
                    authentication_context=context,
                )
                with self._model_execution_capability_lock:
                    self._model_execution_capabilities.pop(body["capability"], None)
                status = project_universal_governed_work_status(
                    self.universal_store,
                    self.universal_registry,
                    authentication_context=context,
                )
                result = {
                    "receipt": receipt.root_id,
                    "delegation": receipt.delegation_root,
                    "history_root": history_root,
                    "reconciled": (
                        receipt.outcome == "succeeded" and proposal is not None
                    ),
                    "work_advanced": bool(history_root),
                    "revision": revision,
                    "status": status,
                }
                if proposal is not None:
                    result["proposal"] = proposal.root_id
                return result
            if path == "/api/universal/mcp-server-register":
                required = {"transport", "config_digest", "data_classes"}
                if direct or set(body) != required:
                    raise AuthorizationDenied(
                        "MCP server enrollment requires its bound exact request"
                    )
                founder_session_root = self._resolve_universal_machine_agent_session(
                    request
                )
                server, revision = register_universal_mcp_server(
                    self.universal_store,
                    self.universal_registry,
                    founder_agent_session_root=founder_session_root,
                    transport=body["transport"],
                    config_digest=body["config_digest"],
                    data_classes=body["data_classes"],
                    authentication_context=context,
                )
                return {
                    "server": server.root_id,
                    "transport": server.transport,
                    "data_classes": [
                        self.universal_store.snapshot().cells[root].atom.decode("utf-8")
                        for root in server.datatype_roots
                    ],
                    "revision": revision,
                }
            if path == "/api/universal/mcp-server-negotiate":
                required = {
                    "root", "server", "protocol_version", "capabilities_digest",
                    "manifest_digest", "tools",
                }
                if direct or set(body) != required:
                    raise AuthorizationDenied(
                        "MCP negotiation requires its bound exact request"
                    )
                agent_session_root = self._resolve_universal_machine_agent_session(
                    request
                )
                negotiation, tools, revision = negotiate_universal_mcp_server(
                    self.universal_store,
                    self.universal_registry,
                    agent_session_root=agent_session_root,
                    work_root=body["root"],
                    server_root=body["server"],
                    protocol_version=body["protocol_version"],
                    capabilities_digest=body["capabilities_digest"],
                    manifest_digest=body["manifest_digest"],
                    tools=body["tools"],
                    authentication_context=context,
                )
                return {
                    "negotiation": negotiation.root_id,
                    "work": negotiation.work_root,
                    "server": negotiation.server_root,
                    "tools": [tool.root_id for tool in tools],
                    "expires_at": negotiation.expires_at,
                    "revision": revision,
                }
            if path == "/api/universal/mcp-tool-delegation":
                required = {"root", "tool", "input_digest", "input_bytes"}
                if direct or set(body) != required:
                    raise AuthorizationDenied(
                        "MCP tool delegation requires its bound exact request"
                    )
                agent_session_root = self._resolve_universal_machine_agent_session(
                    request
                )
                delegation, negotiation, revision = (
                    request_universal_baboom_mcp_tool_execution(
                        self.universal_store,
                        self.universal_registry,
                        agent_session_root=agent_session_root,
                        work_root=body["root"],
                        tool_root=body["tool"],
                        input_digest=body["input_digest"],
                        input_bytes=body["input_bytes"],
                        authentication_context=context,
                    )
                )
                return {
                    "delegation": delegation.root_id,
                    "work": delegation.work_root,
                    "provider": delegation.provider_root,
                    "negotiation": negotiation.root_id,
                    "expires_at": delegation.expires_at,
                    "revision": revision,
                }
            if path == "/api/universal/connector-delegation":
                required = {
                    "root", "provider", "input_digest", "input_bytes",
                    "data_class",
                }
                if direct or set(body) != required:
                    raise AuthorizationDenied(
                        "connector delegation requires its bound exact request"
                    )
                agent_session_root = self._resolve_universal_machine_agent_session(
                    request
                )
                delegation, operation, meeting_note_publication, revision = (
                    request_universal_baboom_connector_execution(
                        self.universal_store,
                        self.universal_registry,
                        agent_session_root=agent_session_root,
                        work_root=body["root"],
                        provider=body["provider"],
                        input_digest=body["input_digest"],
                        input_bytes=body["input_bytes"],
                        data_class=body["data_class"],
                        authentication_context=context,
                    )
                )
                return {
                    "delegation": delegation.root_id,
                    "work": delegation.work_root,
                    "provider": delegation.provider_root,
                    "operation": operation,
                    "input_digest": delegation.input_digest,
                    "input_bytes": delegation.input_bytes,
                    "meeting_note_publication": meeting_note_publication,
                    "expires_at": delegation.expires_at,
                    "revision": revision,
                }
            if path == "/api/universal/connector-delegation-approve":
                if direct or set(body) != {"delegation"}:
                    raise AuthorizationDenied(
                        "connector delegation approval requires its bound exact request"
                    )
                founder_session_root = self._resolve_universal_machine_agent_session(
                    request
                )
                delegation, revision = approve_universal_baboom_connector_execution(
                    self.universal_store,
                    self.universal_registry,
                    founder_agent_session_root=founder_session_root,
                    delegation_root=body["delegation"],
                    consent_broker=self.adapter_consent_broker,
                    authentication_context=context,
                )
                return {
                    "delegation": delegation.root_id,
                    "work": delegation.work_root,
                    "approved": True,
                    "expires_at": delegation.expires_at,
                    "revision": revision,
                }
            if path == "/api/universal/connector-delegation-grant":
                if direct or set(body) != {"delegation"}:
                    raise AuthorizationDenied(
                        "connector execution grant requires its bound exact request"
                    )
                agent_session_root = self._resolve_universal_machine_agent_session(
                    request
                )
                capability = secrets.token_urlsafe(48)
                grant_root = "app:baboom-connector-grant:%s" % uuid.uuid4().hex
                requested_expires_at = time.time() + 90.0
                delegation, expires_at, revision = issue_universal_baboom_connector_execution_grant(
                    self.universal_store,
                    self.universal_registry,
                    agent_session_root=agent_session_root,
                    delegation_root=body["delegation"],
                    grant_id=grant_root,
                    token_digest=hashlib.sha256(
                        capability.encode("utf-8")
                    ).hexdigest(),
                    expires_at=requested_expires_at,
                    authentication_context=context,
                )
                with self._connector_execution_capability_lock:
                    self._connector_execution_capabilities[capability] = {
                        "grant": grant_root,
                        "delegation": delegation.root_id,
                        "session": agent_session_root,
                        "expires_at": expires_at,
                    }
                return {
                    "delegation": delegation.root_id,
                    "grant": grant_root,
                    "capability": capability,
                    "expires_at": expires_at,
                    "revision": revision,
                }
            if path == "/api/universal/connector-delegation-receipt":
                required = {
                    "grant", "capability", "outcome", "output_digest",
                    "output_bytes", "error_code",
                }
                if direct or set(body) != required:
                    raise AuthorizationDenied(
                        "connector execution receipt requires its bound exact request"
                    )
                if type(body["capability"]) is not str:
                    raise InvalidCell("connector execution capability is invalid")
                agent_session_root = self._resolve_universal_machine_agent_session(
                    request
                )
                with self._connector_execution_capability_lock:
                    capability = self._connector_execution_capabilities.pop(
                        body["capability"], None
                    )
                if (
                    not isinstance(capability, dict)
                    or capability.get("grant") != body["grant"]
                    or capability.get("session") != agent_session_root
                    or time.time() >= capability.get("expires_at", 0.0)
                ):
                    raise AuthorizationDenied(
                        "connector execution capability is invalid, expired, or replayed"
                    )
                receipt, history_root, revision = (
                    settle_universal_baboom_connector_execution(
                        self.universal_store,
                        self.universal_registry,
                        agent_session_root=agent_session_root,
                        delegation_root=str(capability["delegation"]),
                        grant_root=body["grant"],
                        output_digest=body["output_digest"],
                        output_bytes=body["output_bytes"],
                        outcome=body["outcome"],
                        error_code=body["error_code"],
                        authentication_context=context,
                    )
                )
                status = project_universal_governed_work_status(
                    self.universal_store,
                    self.universal_registry,
                    authentication_context=context,
                )
                return {
                    "receipt": receipt.root_id,
                    "delegation": receipt.delegation_root,
                    "history_root": history_root,
                    "revision": revision,
                    "status": status,
                }
            if path == "/api/universal/connector-delegation-recover":
                if direct or set(body) != {"receipt"}:
                    raise AuthorizationDenied(
                        "connector execution recovery requires its bound exact receipt"
                    )
                agent_session_root = self._resolve_universal_machine_agent_session(
                    request
                )
                receipt, history_root, revision = (
                    recover_universal_baboom_connector_execution_failure(
                        self.universal_store,
                        self.universal_registry,
                        agent_session_root=agent_session_root,
                        receipt_root=body["receipt"],
                        authentication_context=context,
                    )
                )
                status = project_universal_governed_work_status(
                    self.universal_store,
                    self.universal_registry,
                    authentication_context=context,
                )
                return {
                    "receipt": receipt.root_id,
                    "history_root": history_root,
                    "revision": revision,
                    "status": status,
                }
            if path == "/api/universal/connector-delegation-resume":
                if direct or set(body) != {"receipt"}:
                    raise AuthorizationDenied(
                        "connector execution resume requires its bound exact receipt"
                    )
                agent_session_root = self._resolve_universal_machine_agent_session(
                    request
                )
                receipt, history_root, revision = (
                    resume_universal_baboom_connector_execution_failure(
                        self.universal_store,
                        self.universal_registry,
                        agent_session_root=agent_session_root,
                        receipt_root=body["receipt"],
                        authentication_context=context,
                    )
                )
                status = project_universal_governed_work_status(
                    self.universal_store,
                    self.universal_registry,
                    authentication_context=context,
                )
                return {
                    "receipt": receipt.root_id,
                    "history_root": history_root,
                    "revision": revision,
                    "status": status,
                }
            if path == "/api/universal/model-delegation-recover":
                if direct or set(body) != {"receipt"}:
                    raise AuthorizationDenied(
                        "model execution recovery requires its bound exact receipt"
                    )
                agent_session_root = self._resolve_universal_machine_agent_session(
                    request
                )
                receipt, history_root, revision = (
                    recover_universal_baboom_model_execution_failure(
                        self.universal_store,
                        self.universal_registry,
                        agent_session_root=agent_session_root,
                        receipt_root=body["receipt"],
                        authentication_context=context,
                    )
                )
                status = project_universal_governed_work_status(
                    self.universal_store,
                    self.universal_registry,
                    authentication_context=context,
                )
                return {
                    "receipt": receipt.root_id,
                    "history_root": history_root,
                    "revision": revision,
                    "status": status,
                }
            if path == "/api/universal/model-delegation-resume":
                if direct or set(body) != {"receipt"}:
                    raise AuthorizationDenied(
                        "model execution resume requires its bound exact receipt"
                    )
                agent_session_root = self._resolve_universal_machine_agent_session(
                    request
                )
                receipt, history_root, revision = (
                    resume_universal_baboom_model_execution_failure(
                        self.universal_store,
                        self.universal_registry,
                        agent_session_root=agent_session_root,
                        receipt_root=body["receipt"],
                        authentication_context=context,
                    )
                )
                status = project_universal_governed_work_status(
                    self.universal_store,
                    self.universal_registry,
                    authentication_context=context,
                )
                return {
                    "receipt": receipt.root_id,
                    "history_root": history_root,
                    "revision": revision,
                    "status": status,
                }
            if path == "/api/universal/model-cognition":
                required = {"root", "provider", "model"}
                allowed = required | {"observation"}
                if direct or set(body) not in (required, allowed):
                    raise AuthorizationDenied(
                        "BABOOM Cognition preparation requires its bound exact request"
                    )
                agent_session_root = self._resolve_universal_machine_agent_session(
                    request
                )
                cognition, revision = (
                    prepare_universal_baboom_model_cognition_request(
                        self.universal_store,
                        self.universal_registry,
                        agent_session_root=agent_session_root,
                        work_root=body["root"],
                        provider=body["provider"],
                        model=body["model"],
                        shadow_observation=body.get("observation"),
                        authentication_context=context,
                    )
                )
                return {
                    "work": body["root"],
                    "request": cognition.root_id,
                    "session": cognition.session_root,
                    "binding": cognition.binding_root,
                    "context": list(cognition.context_roots),
                    "input_digest": cognition.input_digest,
                    "input_bytes": cognition.input_bytes,
                    "state": "prepared",
                    "provider": body["provider"],
                    "model": body["model"],
                    "revision": revision,
                }
            if path == "/api/universal/baboom-activity":
                if direct or set(body) != {"app"}:
                    raise AuthorizationDenied(
                        "BABOOM activity requires its bound exact request"
                    )
                agent_session_root = self._resolve_universal_machine_agent_session(
                    request
                )
                activity_root, app, expires_at, revision = (
                    record_universal_baboom_activity(
                        self.universal_store,
                        self.universal_registry,
                        agent_session_root=agent_session_root,
                        app=body["app"],
                        authentication_context=context,
                    )
                )
                return {
                    "activity": activity_root,
                    "app": app,
                    "expires_at": expires_at,
                    "agent_session": agent_session_root,
                    "revision": revision,
                }
            if path == "/api/universal/baboom-meeting-notes":
                if direct or set(body) != {"action"}:
                    raise AuthorizationDenied(
                        "BABOOM meeting-notes requires its bound exact request"
                    )
                agent_session_root = self._resolve_universal_machine_agent_session(
                    request
                )
                meeting_notes_root, state, expires_at, revision = (
                    record_universal_baboom_meeting_notes(
                        self.universal_store,
                        self.universal_registry,
                        agent_session_root=agent_session_root,
                        action=body["action"],
                        authentication_context=context,
                    )
                )
                return {
                    "meeting_notes": meeting_notes_root,
                    "state": state,
                    "expires_at": expires_at,
                    "agent_session": agent_session_root,
                    "revision": revision,
                }
            if path == "/api/universal/baboom-steward-signal":
                if direct or set(body) != {"fingerprint", "source", "summary"}:
                    raise AuthorizationDenied(
                        "BABOOM Steward observation requires its bound exact request"
                    )
                agent_session_root = self._resolve_universal_machine_agent_session(
                    request
                )
                signal_root, revision = record_universal_baboom_steward_signal(
                    self.universal_store,
                    self.universal_registry,
                    agent_session_root=agent_session_root,
                    fingerprint=body["fingerprint"],
                    source=body["source"],
                    summary=body["summary"],
                    authentication_context=context,
                )
                return {
                    "signal": signal_root,
                    "agent_session": agent_session_root,
                    "revision": revision,
                }
            if path == "/api/universal/work-plan":
                if direct or set(body) != {"root"}:
                    raise AuthorizationDenied(
                        "BABOOM Work planning requires its bound exact request"
                    )
                agent_session_root = self._resolve_universal_machine_agent_session(
                    request
                )
                plan_root, reused, revision = draft_universal_baboom_work_plan(
                    self.universal_store,
                    self.universal_registry,
                    agent_session_root=agent_session_root,
                    work_root=body["root"],
                    authentication_context=context,
                )
                return {
                    "work": body["root"],
                    "plan": plan_root,
                    "state": "draft",
                    "reused": reused,
                    "revision": revision,
                }
            if path == "/api/universal/work-plan-read":
                if direct or set(body) != {"root"}:
                    raise AuthorizationDenied(
                        "BABOOM Work plan read requires its bound exact request"
                    )
                agent_session_root = self._resolve_universal_machine_agent_session(
                    request
                )
                plan_root, plan, revision = read_universal_baboom_work_plan(
                    self.universal_store,
                    self.universal_registry,
                    agent_session_root=agent_session_root,
                    work_root=body["root"],
                    authentication_context=context,
                )
                return {
                    "work": body["root"],
                    "plan": plan,
                    "plan_root": plan_root,
                    "revision": revision,
                }
            if path == "/api/universal/value":
                if set(body) != {"root"}:
                    raise InvalidCell("value projection request shape is invalid")
                return {
                    "root": body["root"],
                    "value": project_universal_value_graph(
                        self.universal_store,
                        self.universal_registry,
                        body["root"],
                        authentication_context=context,
                    ),
                    "revision": self.universal_store.revision,
                }
            if path == "/api/universal/work-next":
                if direct or body:
                    raise AuthorizationDenied(
                        "next work requires its bound empty request"
                    )
                (
                    agent_session_root,
                    compliance_observation_root,
                    compliance_evidence_root,
                ) = self._runtime_compliance_for_work_request(
                    request, authentication_context=context
                )
                result = claim_next_universal_governed_work(
                    self.universal_store,
                    self.universal_registry,
                    agent_session_root=agent_session_root,
                    compliance_observation_root=(
                        compliance_observation_root
                    ),
                    authentication_context=context,
                )
                return {
                    "application": self.universal_registry.application_root,
                    "workshop": self.universal_registry.workshop_root,
                    "compliance_observation": (
                        compliance_observation_root
                    ),
                    "compliance_evidence": compliance_evidence_root,
                    **result,
                }
            if path == "/api/universal/work-claim":
                if direct or set(body) != {"root"}:
                    raise AuthorizationDenied(
                        "exact work claim requires its bound exact request"
                    )
                (
                    agent_session_root,
                    compliance_observation_root,
                    compliance_evidence_root,
                ) = self._runtime_compliance_for_work_request(
                    request, authentication_context=context
                )
                result = claim_universal_governed_work(
                    self.universal_store,
                    self.universal_registry,
                    agent_session_root=agent_session_root,
                    work_root=body["root"],
                    compliance_observation_root=(
                        compliance_observation_root
                    ),
                    authentication_context=context,
                )
                return {
                    "application": self.universal_registry.application_root,
                    "workshop": self.universal_registry.workshop_root,
                    "compliance_observation": (
                        compliance_observation_root
                    ),
                    "compliance_evidence": compliance_evidence_root,
                    **result,
                }
            if path == "/api/universal/work-claim-recover":
                recovery_shape = {"root", "evidence"}
                if direct or set(body) not in (
                    recovery_shape,
                    {*recovery_shape, "projection"},
                ):
                    raise AuthorizationDenied(
                        "stale work claim recovery requires its bound exact request"
                    )
                compact_projection = False
                if "projection" in body:
                    if body["projection"] != "index":
                        raise InvalidCell(
                            "stale work claim recovery projection is invalid"
                        )
                    compact_projection = True
                root = body["root"]
                evidence = body["evidence"]
                if type(root) is not str or not root:
                    raise InvalidCell("stale work claim recovery target is invalid")
                if type(evidence) is not str:
                    raise InvalidCell("stale work claim recovery evidence must be text")
                (
                    agent_session_root,
                    compliance_observation_root,
                    compliance_evidence_root,
                ) = self._runtime_compliance_for_work_request(
                    request, authentication_context=context
                )
                index = self._project_universal_machine_work_index(
                    authentication_context=context,
                )
                target = next(
                    (item for item in index["items"] if item["root"] == root),
                    None,
                )
                if target is None:
                    raise InvalidCell("stale work claim recovery target is not registered")
                state = str(
                    target["operational"]["current_state_label"]
                ).casefold()
                if state != "claimed":
                    raise InvalidCell("stale work claim recovery target is not claimed")
                previous_session = target.get("claimant_session")
                if type(previous_session) is not str or not previous_session:
                    raise InvalidCell("stale work claim recovery has no claimant")
                if previous_session == agent_session_root:
                    raise InvalidCell("stale work claim recovery already owns target")
                if self._machine_agent_session_has_live_capability(
                    previous_session
                ):
                    raise AuthorizationDenied(
                        "claimed Agent Session still has a live capability"
                    )
                recovery_evidence = (
                    evidence
                    + "\n\nRecovered stale claim: previous Agent Session "
                    + previous_session
                    + " has no live machine capability in this authority bridge."
                )
                release_history_root, _release_revision = (
                    transition_universal_governed_work(
                        self.universal_store,
                        self.universal_registry,
                        root,
                        "release",
                        agent_session_root=previous_session,
                        evidence_payload=recovery_evidence,
                        authentication_context=context,
                    )
                )
                claim_history_root, revision = transition_universal_governed_work(
                    self.universal_store,
                    self.universal_registry,
                    root,
                    "claim",
                    agent_session_root=agent_session_root,
                    evidence_payload=evidence,
                    authentication_context=context,
                )
                status = (
                    self._project_universal_machine_work_index(
                        authentication_context=context,
                    )
                    if compact_projection
                    else project_universal_governed_work_status(
                        self.universal_store,
                        self.universal_registry,
                        authentication_context=context,
                    )
                )
                return {
                    "application": self.universal_registry.application_root,
                    "workshop": self.universal_registry.workshop_root,
                    "recovered": True,
                    "projection": "index" if compact_projection else "status",
                    "previous_claimant_session": previous_session,
                    "compliance_observation": (
                        compliance_observation_root
                    ),
                    "compliance_evidence": compliance_evidence_root,
                    "claimant_session": agent_session_root,
                    "release_history_root": release_history_root,
                    "claim_history_root": claim_history_root,
                    "revision": revision,
                    "status": status,
                }
            if path == "/api/universal/work-handoff":
                common = {
                    "title", "description", "priority", "scope",
                    "handoff_key", "payload_digest",
                    "expires_at", "x", "y",
                }
                custody_request = common | {"target_device_custody"}
                selector_request = common | {"target_device_ref"}
                body_keys = set(body)
                if (
                    direct
                    or (
                        body_keys != custody_request
                        and body_keys != selector_request
                    )
                ):
                    raise AuthorizationDenied(
                        "device handoff requires its bound exact request"
                    )
                agent_session_root = self._resolve_universal_machine_agent_session(
                    request
                )
                with self._machine_agent_session_lock:
                    binding = dict(
                        self._machine_agent_sessions.get(agent_session_root) or {}
                    )
                source_custody = binding.get("device_custody")
                if not isinstance(source_custody, str):
                    raise AuthorizationDenied(
                        "device handoff requires a device-proof Agent Session"
                    )
                handoff_arguments = {
                    "title": body["title"],
                    "description": body["description"],
                    "priority": body["priority"],
                    "scope": body["scope"],
                    "handoff_key": body["handoff_key"],
                    "payload_digest": body["payload_digest"],
                    "expires_at": float(body["expires_at"]),
                    "x": float(body["x"]),
                    "y": float(body["y"]),
                    "authentication_context": context,
                }
                if "target_device_ref" in body:
                    work_root, membership_wire, handoff_root, revision = (
                        create_universal_device_handoff_work_for_device_ref(
                            self.universal_store,
                            self.universal_registry,
                            agent_session_root=agent_session_root,
                            target_device_ref=body["target_device_ref"],
                            **handoff_arguments,
                        )
                    )
                else:
                    work_root, membership_wire, handoff_root, revision = (
                        create_universal_device_handoff_work(
                            self.universal_store,
                            self.universal_registry,
                            source_device_custody_root=source_custody,
                            target_device_custody_root=body["target_device_custody"],
                            **handoff_arguments,
                        )
                    )
                return {
                    "work_root": work_root,
                    "membership_wire": membership_wire,
                    "handoff_root": handoff_root,
                    "source_device_custody": source_custody,
                    "revision": revision,
                }
            if path == "/api/universal/work-handoff-receipt":
                if direct or set(body) != {
                    "handoff_key", "kind", "receipt_digest"
                }:
                    raise AuthorizationDenied(
                        "device handoff receipt requires its bound exact request"
                    )
                agent_session_root = self._resolve_universal_machine_agent_session(
                    request
                )
                with self._machine_agent_session_lock:
                    binding = dict(
                        self._machine_agent_sessions.get(agent_session_root) or {}
                    )
                source_custody = binding.get("device_custody")
                if not isinstance(source_custody, str):
                    raise AuthorizationDenied(
                        "device handoff receipt requires a device-proof Agent Session"
                    )
                handoff_root, receipt_root, revision = (
                    record_universal_device_handoff_receipt(
                        self.universal_store,
                        self.universal_registry,
                        handoff_key=body["handoff_key"],
                        source_device_custody_root=source_custody,
                        kind=body["kind"],
                        receipt_digest=body["receipt_digest"],
                    )
                )
                return {
                    "handoff_root": handoff_root,
                    "receipt_root": receipt_root,
                    "revision": revision,
                }
            if path == "/api/universal/work-claim-transfer":
                expected = {
                    "root", "target_device_ref", "transfer_key",
                    "confirmation_digest", "expires_at",
                }
                if direct or set(body) != expected:
                    raise AuthorizationDenied(
                        "work claim transfer requires its bound exact request"
                    )
                (
                    agent_session_root,
                    compliance_observation_root,
                    compliance_evidence_root,
                ) = self._runtime_compliance_for_work_request(
                    request, authentication_context=context
                )
                result = initiate_universal_baboom_work_claim_transfer(
                    self.universal_store,
                    self.universal_registry,
                    agent_session_root=agent_session_root,
                    work_root=body["root"],
                    target_device_ref=body["target_device_ref"],
                    transfer_key=body["transfer_key"],
                    confirmation_digest=body["confirmation_digest"],
                    expires_at=float(body["expires_at"]),
                    authentication_context=context,
                )
                return {
                    "application": self.universal_registry.application_root,
                    "workshop": self.universal_registry.workshop_root,
                    "compliance_observation": compliance_observation_root,
                    "compliance_evidence": compliance_evidence_root,
                    **result,
                }
            if path == "/api/universal/cde-write-permit":
                expected = {
                    "operation", "path", "content_digest", "request_id", "nonce"
                }
                if direct or set(body) != expected:
                    raise AuthorizationDenied(
                        "CDE permit requires one bound exact write request"
                    )
                if (
                    self.cde_write_signing_provider is None
                    or self.cde_write_signing_descriptor_root is None
                ):
                    raise AuthorizationDenied(
                        "CDE signing authority is unavailable"
                    )
                if self.universal_checkpoint_guard is not None:
                    self.universal_checkpoint_guard.require_healthy()
                self.require_universal_http_route(
                    "POST",
                    path,
                    authentication_context=context,
                )
                agent_session_root = (
                    self._resolve_universal_machine_agent_session(request)
                )
                admission = authorize_universal_cde_write(
                    self.universal_store,
                    self.universal_registry,
                    agent_session_root=agent_session_root,
                    operation=body["operation"],
                    path=body["path"],
                    authentication_context=context,
                )
                snapshot = self.universal_store.snapshot()
                if snapshot.revision != admission.authority_revision:
                    raise AuthorizationDenied(
                        "CDE permit admission revision drifted"
                    )
                session = read_agent_session(
                    snapshot,
                    self.universal_registry.agent_body.protocol,
                    self.universal_registry.authorization.protocol,
                    agent_session_root,
                )
                runtime = _agent_body_catalog_entry_for_session(
                    snapshot, self.universal_registry, session
                ).runtime
                now = time.time()
                permit, revision = issue_cde_write_permit(
                    self.universal_store,
                    self.universal_registry.cde_write_authority_protocol,
                    self.universal_registry.cde_signing_protocol,
                    self.cde_write_signing_provider,
                    self.cde_write_signing_descriptor_root,
                    permit_id=cde_write_permit_identity(
                        runtime=runtime,
                        agent_session_root=agent_session_root,
                        work_root=admission.work_root,
                        container_root=admission.container_root,
                        container_id=admission.container_id,
                        container_digest=admission.container_digest,
                        operation=admission.operation,
                        path=admission.path,
                        content_digest=body["content_digest"],
                        request_id=body["request_id"],
                        nonce=body["nonce"],
                        authorization_evidence=admission.claim_binding_root,
                    ),
                    runtime=runtime,
                    agent_session_root=agent_session_root,
                    work_root=admission.work_root,
                    container_root=admission.container_root,
                    container_id=admission.container_id,
                    container_digest=admission.container_digest,
                    operation=admission.operation,
                    path=admission.path,
                    content_digest=body["content_digest"],
                    request_id=body["request_id"],
                    nonce=body["nonce"],
                    issued_at=now,
                    expires_at=now + 60.0,
                    authorization_evidence=admission.claim_binding_root,
                )
                return {
                    "permit": permit.root_id,
                    "agent_session": permit.agent_session_root,
                    "work": permit.work_root,
                    "claim_binding": admission.claim_binding_root,
                    "container_root": permit.container_root,
                    "container_id": permit.container_id,
                    "container_digest": permit.container_digest,
                    "operation": permit.operation,
                    "path": permit.path,
                    "content_digest": permit.content_digest,
                    "request_id": permit.request_id,
                    "authority_revision": permit.authority_revision,
                    "expires_at": permit.expires_at,
                    "revision": revision,
                }
            if path == "/api/universal/work-claim-transfer-claim":
                if direct or set(body) != {"transfer_key"}:
                    raise AuthorizationDenied(
                        "work claim transfer claim requires its bound exact request"
                    )
                (
                    agent_session_root,
                    compliance_observation_root,
                    compliance_evidence_root,
                ) = self._runtime_compliance_for_work_request(
                    request, authentication_context=context
                )
                result = claim_universal_baboom_work_claim_transfer(
                    self.universal_store,
                    self.universal_registry,
                    agent_session_root=agent_session_root,
                    transfer_key=body["transfer_key"],
                    compliance_observation_root=compliance_observation_root,
                    authentication_context=context,
                )
                return {
                    "application": self.universal_registry.application_root,
                    "workshop": self.universal_registry.workshop_root,
                    "compliance_observation": compliance_observation_root,
                    "compliance_evidence": compliance_evidence_root,
                    **result,
                }
            if path == "/api/universal/work-claim-transfer-cancel":
                if direct or set(body) != {"transfer_key", "cancellation_digest"}:
                    raise AuthorizationDenied(
                        "work claim transfer cancellation requires its bound exact request"
                    )
                (
                    agent_session_root,
                    compliance_observation_root,
                    compliance_evidence_root,
                ) = self._runtime_compliance_for_work_request(
                    request, authentication_context=context
                )
                result = cancel_universal_baboom_work_claim_transfer(
                    self.universal_store,
                    self.universal_registry,
                    agent_session_root=agent_session_root,
                    transfer_key=body["transfer_key"],
                    cancellation_digest=body["cancellation_digest"],
                    authentication_context=context,
                )
                return {
                    "application": self.universal_registry.application_root,
                    "workshop": self.universal_registry.workshop_root,
                    "compliance_observation": compliance_observation_root,
                    "compliance_evidence": compliance_evidence_root,
                    **result,
                }
            if path == "/api/universal/work":
                allowed = {
                    "title", "description", "priority", "external_key",
                    "references", "structured_references", "x", "y",
                    "compact_references", "select_created",
                }
                if set(body) - allowed:
                    raise InvalidCell("governed work request shape is invalid")
                created_root, membership_wire, revision = (
                    create_universal_governed_work(
                        self.universal_store,
                        self.universal_registry,
                        title=body.get("title", ""),
                        description=body.get("description", ""),
                        priority=body.get("priority", 0),
                        external_key=body.get("external_key", "unset"),
                        references=body.get("references"),
                        structured_references=body.get(
                            "structured_references"
                        ),
                        x=float(body.get("x", 0.0)),
                        y=float(body.get("y", 0.0)),
                        compact_references=bool(
                            body.get("compact_references", False)
                        ),
                        select_created=bool(
                            body.get("select_created", True)
                        ),
                        authentication_context=context,
                    )
                )
                return {
                    "created_root": created_root,
                    "membership_wire": membership_wire,
                    "revision": revision,
                }
            if path == "/api/universal/assembly":
                allowed = {"definition_key", "fields", "structured_fields", "idempotency_field", "x", "y"}
                if set(body) - allowed:
                    raise InvalidCell("assembly request shape is invalid")
                definition_key = body.get("definition_key")
                if type(definition_key) is not str or not definition_key:
                    raise InvalidCell("assembly definition key is invalid")
                definition = (
                    self.universal_registry
                    .standard_library
                    .governed_domains
                    .definitions
                    .get(definition_key)
                )
                if definition is None:
                    raise InvalidCell("assembly definition is not released")
                fields = _machine_assembly_fields(body.get("fields", {}))
                structured_fields = _machine_assembly_structured_fields(
                    body.get("structured_fields", {})
                )
                if set(fields).intersection(structured_fields):
                    raise InvalidCell(
                        "assembly field cannot be both scalar and structured"
                    )
                idempotency_field = body.get("idempotency_field")
                if idempotency_field is not None:
                    if (
                        type(idempotency_field) is not str
                        or idempotency_field not in fields
                    ):
                        raise InvalidCell(
                            "assembly idempotency field is invalid"
                        )
                    projection = project_universal_canvas(
                        self.universal_store,
                        self.universal_registry,
                        authentication_context=context,
                    )
                    snapshot = self.universal_store.snapshot()
                    for item in projection.get("nodes", []):
                        root = item.get("id") if isinstance(item, dict) else None
                        if type(root) is not str:
                            continue
                        candidate = _instance_projection(
                            snapshot,
                            self.universal_registry,
                            root,
                        )
                        if (
                            candidate is None
                            or candidate.get("definition")
                            != definition.definition_root
                        ):
                            continue
                        by_name = {
                            str(interface.get("name")): interface
                            for interface in candidate.get("interfaces", [])
                            if isinstance(interface, dict)
                        }
                        existing = by_name.get(idempotency_field)
                        if (
                            existing is not None
                            and existing.get("value")
                            == fields[idempotency_field]
                        ):
                            return {
                                "ok": True,
                                "existing": True,
                                "created_root": root,
                                "definition_key": definition_key,
                                "definition_root": definition.definition_root,
                                "assembly": _bounded_assembly_projection(
                                    candidate
                                ),
                                "revision": self.universal_store.revision,
                            }
                created_root, revision = instantiate_universal_definition(
                    self.universal_store,
                    self.universal_registry,
                    definition.definition_root,
                    x=float(body.get("x", 0.0)),
                    y=float(body.get("y", 0.0)),
                    authentication_context=context,
                    interface_values=fields,
                    mutation_route="/api/universal/assembly",
                )
                structured = attach_universal_assembly_structured_fields(
                    self.universal_store,
                    self.universal_registry,
                    created_root,
                    structured_fields,
                    x=float(body.get("x", 0.0)),
                    y=float(body.get("y", 0.0)),
                    mutation_route="/api/universal/assembly",
                    authentication_context=context,
                )
                assembly = _instance_projection(
                    self.universal_store.snapshot(),
                    self.universal_registry,
                    created_root,
                )
                if assembly is None:
                    raise InvalidCell("created assembly is not projectable")
                return {
                    "ok": True,
                    "existing": False,
                    "created_root": created_root,
                    "definition_key": definition_key,
                    "definition_root": definition.definition_root,
                    "assembly": _bounded_assembly_projection(assembly),
                    "structured_fields": structured,
                    "revision": revision,
                }
            if path == "/api/universal/assembly-field":
                if set(body) != {"root", "interface", "value"}:
                    raise InvalidCell("assembly field request shape is invalid")
                root = body["root"]
                interface = body["interface"]
                if type(root) is not str or type(interface) is not str:
                    raise InvalidCell("assembly field target is invalid")
                value = "" if body["value"] is None else str(body["value"])
                revision = edit_universal_interface_value(
                    self.universal_store,
                    self.universal_registry,
                    root,
                    interface,
                    value,
                    mutation_route="/api/universal/assembly-field",
                    authentication_context=context,
                )
                assembly = _instance_projection(
                    self.universal_store.snapshot(),
                    self.universal_registry,
                    root,
                )
                if assembly is None:
                    raise InvalidCell("edited assembly is not projectable")
                return {
                    "ok": True,
                    "root": root,
                    "assembly": _bounded_assembly_projection(assembly),
                    "revision": revision,
                }
            if path == "/api/universal/work-court":
                court_shape = {"root"}
                if direct or set(body) not in (
                    court_shape,
                    {*court_shape, "projection"},
                ):
                    raise AuthorizationDenied(
                        "work court requires its bound exact request"
                    )
                compact_projection = False
                if "projection" in body:
                    if body["projection"] != "index":
                        raise InvalidCell("work court projection is invalid")
                    compact_projection = True
                agent_session_root = (
                    self._resolve_universal_machine_agent_session(request)
                )
                return adjudicate_universal_governed_work(
                    self.universal_store,
                    self.universal_registry,
                    body["root"],
                    requesting_agent_session_root=agent_session_root,
                    workspace_root=self.universal_workspace_root,
                    compact_status=compact_projection,
                    authentication_context=context,
                )
            if path == "/api/universal/work-court-recover":
                court_shape = {"root", "evidence"}
                if direct or set(body) not in (
                    court_shape,
                    {*court_shape, "projection"},
                ):
                    raise AuthorizationDenied(
                        "stale work court recovery requires its bound exact request"
                    )
                compact_projection = False
                if "projection" in body:
                    if body["projection"] != "index":
                        raise InvalidCell(
                            "stale work court recovery projection is invalid"
                        )
                    compact_projection = True
                root = body["root"]
                evidence = body["evidence"]
                if type(root) is not str or not root:
                    raise InvalidCell("stale work court recovery target is invalid")
                if type(evidence) is not str:
                    raise InvalidCell("stale work court recovery evidence must be text")
                requesting_agent_session_root = (
                    self._resolve_universal_machine_agent_session(request)
                )
                index = self._project_universal_machine_work_index(
                    authentication_context=context,
                )
                target = next(
                    (item for item in index["items"] if item["root"] == root),
                    None,
                )
                if target is None:
                    raise InvalidCell("stale work court recovery target is not registered")
                state = str(
                    target["operational"]["current_state_label"]
                ).casefold()
                if state != "review":
                    raise InvalidCell("stale work court recovery target is not in review")
                claimant = target.get("claimant_session")
                if type(claimant) is not str or not claimant:
                    raise InvalidCell("stale work court recovery has no claimant")
                if claimant == requesting_agent_session_root:
                    raise InvalidCell("stale work court recovery already owns target")
                if self._machine_agent_session_has_live_capability(claimant):
                    raise AuthorizationDenied(
                        "submitting Agent Session still has a live capability"
                    )
                try:
                    result = adjudicate_universal_governed_work(
                        self.universal_store,
                        self.universal_registry,
                        root,
                        requesting_agent_session_root=claimant,
                        workspace_root=self.universal_workspace_root,
                        compact_status=compact_projection,
                        authentication_context=context,
                    )
                except InvalidCell as exc:
                    snapshot = self.universal_store.snapshot()
                    operational = (
                        self.universal_registry
                        .standard_library.state_machine_protocol
                    )
                    machine = read_instance_state_machine(
                        snapshot,
                        self.universal_registry.assembly_protocol,
                        operational,
                        root,
                    )
                    candidates = []
                    for transition_root in machine.transition_roots:
                        transition = read_transition(
                            snapshot, operational, transition_root
                        )
                        event_label = snapshot.cells[
                            transition.event_root
                        ].atom.decode("utf-8")
                        if (
                            transition.from_state_root
                            == machine.current_state_root
                            and event_label.casefold() == "return"
                        ):
                            candidates.append(transition)
                    if len(candidates) != 1:
                        raise InvalidCell(
                            "stale work court recovery return transition is missing"
                        ) from exc
                    transition = candidates[0]
                    if len(transition.required_evidence_type_roots) != 1:
                        raise InvalidCell(
                            "stale work court recovery evidence contract drifted"
                        ) from exc
                    payload = json.dumps({
                        "recovery": "stale-review-return",
                        "reason": evidence,
                        "court_error": str(exc),
                    }, sort_keys=True, separators=(",", ":")).encode("utf-8")
                    _decision_evidence_root, return_history_root, _return_revision = (
                        transition_machine_with_new_evidence(
                            self.universal_store,
                            operational,
                            machine.root_id,
                            event_root=transition.event_root,
                            expected_state_root=machine.current_state_root,
                            actor_root=(
                                self.universal_registry
                                .work_completion_court_root
                            ),
                            evidence_id=(
                                "app:work-court-recovery-evidence:%s"
                                % uuid.uuid4().hex
                            ),
                            evidence_type_root=(
                                transition.required_evidence_type_roots[0]
                            ),
                            evidence_payload=payload,
                            evidence_issuer_root=(
                                self.universal_registry
                                .work_completion_court_root
                            ),
                            trusted_issuer_roots=(
                                self.universal_registry
                                .work_completion_court_root,
                            ),
                            context_roots=(
                                claimant,
                                requesting_agent_session_root,
                            ),
                        )
                    )
                    release_history_root, _release_revision = (
                        transition_universal_governed_work(
                            self.universal_store,
                            self.universal_registry,
                            root,
                            "release",
                            agent_session_root=claimant,
                            evidence_payload=evidence,
                            authentication_context=context,
                        )
                    )
                    claim_history_root, revision = (
                        transition_universal_governed_work(
                            self.universal_store,
                            self.universal_registry,
                            root,
                            "claim",
                            agent_session_root=requesting_agent_session_root,
                            evidence_payload=evidence,
                            authentication_context=context,
                        )
                    )
                    status = (
                        self._project_universal_machine_work_index(
                            authentication_context=context,
                        )
                        if compact_projection
                        else project_universal_governed_work_status(
                            self.universal_store,
                            self.universal_registry,
                            authentication_context=context,
                        )
                    )
                    result = {
                        "passed": False,
                        "event": "return",
                        "projection": (
                            "index" if compact_projection else "status"
                        ),
                        "attestation_root": None,
                        "decision_evidence_root": None,
                        "history_root": return_history_root,
                        "release_history_root": release_history_root,
                        "claim_history_root": claim_history_root,
                        "revision": revision,
                        "status": status,
                        "court_error": str(exc),
                    }
                return {
                    "application": self.universal_registry.application_root,
                    "workshop": self.universal_registry.workshop_root,
                    "recovered": True,
                    "recovering_agent_session": requesting_agent_session_root,
                    "submitted_claimant_session": claimant,
                    **result,
                }
            if path == "/api/universal/deliberation":
                expected = {
                    "space", "category", "summary", "payload",
                    "idempotency_key", "created_at",
                }
                if set(body) != expected:
                    raise InvalidCell("deliberation entry request shape is invalid")
                space_root = body["space"]
                category_root = body["category"]
                summary = body["summary"]
                idempotency_key = body["idempotency_key"]
                created_at = body["created_at"]
                if (
                    type(space_root) is not str
                    or type(category_root) is not str
                    or type(summary) is not str
                    or type(idempotency_key) is not str
                    or (
                        created_at is not None
                        and type(created_at) is not str
                    )
                ):
                    raise InvalidCell(
                        "deliberation entry request values are invalid"
                    )
                if not summary.strip():
                    raise InvalidCell("deliberation entry summary is empty")
                actor_root = self.universal_registry.authorization.subject_root
                entry_context = context
                if not direct and request.get("session") != {}:
                    actor_root = self._resolve_universal_machine_agent_session(
                        request
                    )
                    payload = body["payload"]
                    expected_payload = {
                        "operation", "session_fingerprint",
                        "entry_count", "entries", "secret_ref_count",
                        "secret_ref_hashes", "cwd_sha256",
                        "git_remote_sha256",
                    }
                    surface = self._machine_session_surface_values(
                        self.universal_store.snapshot(), actor_root
                    )
                    fingerprint = payload.get("session_fingerprint") \
                        if type(payload) is dict else None
                    evidence_hashes = (
                        payload.get("cwd_sha256"),
                        payload.get("git_remote_sha256"),
                    ) if type(payload) is dict else ()
                    if (
                        space_root
                        != self.universal_registry.brain_control_ledger_root
                        or category_root
                        != self.universal_registry.brain_control_category_roots[
                            "compliance-event"
                        ]
                        or type(payload) is not dict
                        or set(payload) != expected_payload
                        or payload.get("operation")
                        != "brain.hook_session_start"
                        or summary != "Runtime Agent Session wiring"
                        or not isinstance(fingerprint, str)
                        or re.fullmatch(r"[0-9a-f]{64}", fingerprint) is None
                        or fingerprint != surface.get("session fingerprint")
                        or payload.get("entry_count") != 0
                        or payload.get("entries") != []
                        or payload.get("secret_ref_count") != 0
                        or payload.get("secret_ref_hashes") != []
                        or any(
                            not isinstance(value, str)
                            or re.fullmatch(r"[0-9a-f]{64}", value) is None
                            for value in evidence_hashes
                        )
                    ):
                        raise AuthorizationDenied(
                            "runtime session deliberation receipt is not admitted"
                        )
                    entry_context = (
                        self.universal_registry.authorization.broker
                        .mint_authenticated_context(
                            actor_root,
                            principal_roots=(),
                            tenant_root=(
                                self.universal_registry
                                .authorization.tenant_root
                            ),
                            assurance_root=(
                                self.universal_registry
                                .authorization.assurance_root
                            ),
                            lifetime_seconds=60.0,
                        )
                    )
                created = (
                    datetime.now(timezone.utc).isoformat()
                    if created_at is None else created_at
                )
                digest = hashlib.sha256(
                    (space_root + "\0" + idempotency_key).encode("utf-8")
                ).hexdigest()
                payload_root = "app:deliberation-payload:" + digest
                entry, committed_payload_root, revision = (
                    append_deliberation_value_entry(
                        self.universal_store,
                        self.universal_registry.deliberation_protocol,
                        self.universal_registry.value_graph_protocol,
                        space_root=space_root,
                        actor_root=actor_root,
                        category_root=category_root,
                        content=summary.strip(),
                        payload=body["payload"],
                        payload_root=payload_root,
                        idempotency_key=idempotency_key,
                        created_at=created,
                        authorization_protocol=(
                            self.universal_registry.authorization.protocol
                        ),
                        authentication_broker=(
                            self.universal_registry.authorization.broker
                        ),
                        authentication_context=entry_context,
                    )
                )
                return {
                    "ok": True,
                    "space": space_root,
                    "root": entry.root_id,
                    "category_root": entry.category_root,
                    "payload_root": committed_payload_root,
                    "sequence": entry.sequence,
                    "revision": revision,
                }
            if path == "/api/universal/workshop-assignment":
                expected = {"assignment_id", "work", "agent_session"}
                if set(body) != expected:
                    raise InvalidCell(
                        "Workshop assignment request shape is invalid"
                    )
                if not direct:
                    raise AuthorizationDenied(
                        "only the founder desktop session may assign Workshop work"
                    )
                assignment = assign_universal_workshop_work(
                    self.universal_store,
                    self.universal_registry,
                    assignment_id=body["assignment_id"],
                    work_root=body["work"],
                    agent_session_root=body["agent_session"],
                    authentication_context=context,
                )
                return {
                    "ok": True,
                    "root": assignment.root_id,
                    "work": assignment.work_root,
                    "agent_session": assignment.agent_session_root,
                    "obligation": assignment.obligation_root,
                    "revision": self.universal_store.revision,
                }
            if path == "/api/universal/workshop":
                expected = {
                    "category", "text", "refs", "evidence", "recipients",
                    "reply_to", "idempotency_key", "created_at",
                }
                if set(body) != expected:
                    raise InvalidCell("workshop entry request shape is invalid")
                category = body["category"]
                text = body["text"]
                refs = body["refs"]
                evidence = body["evidence"]
                recipients = body["recipients"]
                reply_to = body["reply_to"]
                idempotency_key = body["idempotency_key"]
                created_at = body["created_at"]
                if (
                    type(category) is not str
                    or type(text) is not str
                    or type(idempotency_key) is not str
                    or type(refs) is not list
                    or type(evidence) is not list
                    or type(recipients) is not list
                    or any(type(root) is not str for root in refs)
                    or any(type(root) is not str for root in evidence)
                    or any(type(root) is not str for root in recipients)
                    or (
                        reply_to is not None
                        and type(reply_to) is not str
                    )
                    or (
                        created_at is not None
                        and type(created_at) is not str
                    )
                ):
                    raise InvalidCell("workshop entry request values are invalid")
                text = validate_universal_workshop_entry_content(text)
                created = (
                    datetime.now(timezone.utc).isoformat()
                    if created_at is None else created_at
                )
                category_root = (
                    self.universal_registry
                    .workshop_category_roots.get(category)
                    or category
                )
                actor_root = self.universal_registry.authorization.subject_root
                entry_context = context
                if not direct and request.get("session") != {}:
                    actor_root = self._resolve_universal_machine_agent_session(
                        request
                    )
                    self._ensure_universal_workshop_participant(actor_root)
                    entry_context = (
                        self.universal_registry.authorization.broker
                        .mint_authenticated_context(
                            actor_root,
                            principal_roots=(),
                            tenant_root=(
                                self.universal_registry
                                .authorization.tenant_root
                            ),
                            assurance_root=(
                                self.universal_registry
                                .authorization.assurance_root
                            ),
                            lifetime_seconds=60.0,
                        )
                    )
                entry = append_universal_workshop_entry(
                    self.universal_store,
                    self.universal_registry,
                    actor_root=actor_root,
                    category_root=category_root,
                    content=text,
                    idempotency_key=idempotency_key,
                    created_at=created,
                    authentication_context=entry_context,
                    recipient_roots=tuple(recipients),
                    reference_roots=tuple(refs),
                    reply_to_root=reply_to,
                    evidence_roots=tuple(evidence),
                )
                category_names = {
                    root: name
                    for name, root in (
                        self.universal_registry
                        .workshop_category_roots.items()
                    )
                }
                return {
                    "ok": True,
                    "workshop": self.universal_registry.workshop_root,
                    "root": entry.root_id,
                    "sequence": entry.sequence,
                    "actor": entry.actor_root,
                    "kind": category_names.get(
                        entry.category_root, entry.category_root
                    ),
                    "category_root": entry.category_root,
                    "recipients": list(entry.recipient_roots),
                    "refs": list(entry.reference_roots),
                    "evidence": list(entry.evidence_roots),
                    "reply_to": entry.reply_to_root,
                    "text": entry.content,
                    "created_at": entry.created_at,
                    "idempotency_key": entry.idempotency_key,
                    "revision": self.universal_store.revision,
                }
            if path == "/api/universal/workshop-gate":
                if set(body) != {"ref", "phase"}:
                    raise InvalidCell("workshop gate request shape is invalid")
                ref = body["ref"]
                phase = body["phase"]
                if type(ref) is not str or type(phase) is not str:
                    raise InvalidCell("workshop gate request values are invalid")
                phase_root = (
                    self.universal_registry.workshop_phase_roots.get(phase)
                    or phase
                )
                gate = evaluate_deliberation_gate(
                    self.universal_store.snapshot(),
                    self.universal_registry.deliberation_protocol,
                    self.universal_registry.workshop_root,
                    phase_root=phase_root,
                    reference_root=ref,
                )
                category_names = {
                    root: name
                    for name, root in (
                        self.universal_registry
                        .workshop_category_roots.items()
                    )
                }
                return {
                    "allowed": gate.allowed,
                    "phase": phase,
                    "phase_root": gate.phase_root,
                    "ref": ref,
                    "matching_entries": list(gate.matching_entry_roots),
                    "missing": [
                        category_names.get(root, root)
                        for root in gate.missing_category_roots
                    ],
                    "missing_evidence": [
                        category_names.get(root, root)
                        for root in gate.missing_evidence_category_roots
                    ],
                    "requirements": list(gate.required_category_roots),
                    "evidence_counts": {
                        category_names.get(root, root): count
                        for root, count in gate.observed_evidence_counts.items()
                    },
                    "revision": self.universal_store.revision,
                }
            allowed_transition_shape = {"root", "event", "evidence"}
            if set(body) not in (
                allowed_transition_shape,
                {*allowed_transition_shape, "projection"},
            ):
                raise InvalidCell("work transition request shape is invalid")
            compact_projection = False
            receipt_projection = False
            if "projection" in body:
                if body["projection"] not in {"index", "receipt-v1"}:
                    raise InvalidCell("work transition projection is invalid")
                compact_projection = body["projection"] == "index"
                receipt_projection = body["projection"] == "receipt-v1"
            if direct:
                raise AuthorizationDenied(
                    "work transition requires a bound runtime Agent Session"
                )
            compliance_observation_root = None
            compliance_evidence_root = None
            if body["event"] == "claim":
                (
                    agent_session_root,
                    compliance_observation_root,
                    compliance_evidence_root,
                ) = self._runtime_compliance_for_work_request(
                    request, authentication_context=context
                )
            else:
                agent_session_root = (
                    self._resolve_universal_machine_agent_session(request)
                )
            entry = _agent_body_catalog_entry_for_session(
                self.universal_store.snapshot(),
                self.universal_registry,
                read_agent_session(
                    self.universal_store.snapshot(),
                    self.universal_registry.agent_body.protocol,
                    self.universal_registry.authorization.protocol,
                    agent_session_root,
                ),
            )
            if (
                body["event"] in {"submit", "block", "resume"}
                and entry.runtime == "baboom-execution"
            ):
                raise AuthorizationDenied(
                    "BABOOM execution-body submission and recovery transitions are reserved for model receipt settlement and recovery"
                )
            history_root, revision = transition_universal_governed_work(
                self.universal_store,
                self.universal_registry,
                body["root"],
                body["event"],
                agent_session_root=agent_session_root,
                evidence_payload=body["evidence"],
                authentication_context=context,
            )
            if receipt_projection:
                return {
                    "history_root": history_root,
                    "compliance_observation": compliance_observation_root,
                    "compliance_evidence": compliance_evidence_root,
                    "projection": "receipt-v1",
                    "revision": revision,
                    "work_root": body["root"],
                    "event": body["event"],
                    "agent_session": agent_session_root,
                }
            status = (
                self._project_universal_machine_work_index(
                    authentication_context=context,
                )
                if compact_projection
                else project_universal_governed_work_status(
                    self.universal_store,
                    self.universal_registry,
                    authentication_context=context,
                )
            )
            return {
                "history_root": history_root,
                "compliance_observation": compliance_observation_root,
                "compliance_evidence": compliance_evidence_root,
                "projection": "index" if compact_projection else "status",
                "revision": revision,
                "status": status,
            }

    def require_universal_http_route(
        self,
        method: str,
        path: str,
        *,
        authentication_context: object,
    ):
        """Resolve and authorize one exact immutable route before dispatch."""
        key = "%s %s" % (method, path)
        expected_root = self.universal_registry.application_http_route_roots.get(
            key
        )
        if expected_root is None:
            raise CloudRouteDenied("HTTP interface is not registered")
        snapshot = self.universal_store.snapshot()
        cache_key = (snapshot.revision, method, path, id(authentication_context))
        with self._route_authorization_cache_lock:
            cached = self._route_authorization_cache.get(cache_key)
            if cached is not None:
                return cached
        route = find_cloud_route(
            snapshot,
            self.universal_registry.cloud_route_protocol,
            method=method,
            path_template=path,
        )
        resolved = resolve_cloud_route(snapshot, route)
        if (
            route.root_id != expected_root
            or resolved.object_root
            != self.universal_registry.authorization.route_scope_root
        ):
            raise CloudRouteDenied("HTTP route authority drifted")
        authority = self.universal_registry.authorization
        request = AuthorizationRequest(
            action_root=resolved.action_root,
            object_root=resolved.object_root,
            resource_lineage_roots=resolved.resource_lineage_roots,
            interface_root=resolved.interface_root,
            purpose_root=resolved.purpose_root,
            classification_root=resolved.classification_root,
            audience_root=resolved.audience_root,
            lifecycle_state_root=resolved.lifecycle_state_root,
            operational_state_root=resolved.operational_state_root,
        )
        require_authorization(
            snapshot,
            authority.protocol,
            authority.policy_root,
            authority.broker,
            authentication_context,
            request,
        )
        with self._route_authorization_cache_lock:
            if self.universal_store.revision != snapshot.revision:
                self._route_authorization_cache.clear()
            else:
                self._route_authorization_cache[cache_key] = resolved
                if len(self._route_authorization_cache) > 512:
                    current_revision = self.universal_store.revision
                    self._route_authorization_cache = {
                        item_key: value
                        for item_key, value in self._route_authorization_cache.items()
                        if item_key[0] == current_revision
                    }
        return resolved

    def project_interaction_canvas(self, binding: _BrowserSessionBinding):
        """Project the real canvas and bind its callable controls to one revision."""
        return self._project_interaction_canvas(binding)

    @with_relation_projection_scope
    @with_catalog_verification_scope
    @with_interaction_projection_scope
    def _project_interaction_canvas(
        self,
        binding: _BrowserSessionBinding,
        *,
        scope_materialization=None,
        previous_projection=None,
        expected_base_revision=None,
    ):
        """Bind controls over one exact full or materialized session scope."""
        with self.mutation_lock:
            reusable_scope_projection = None
            if scope_materialization is None:
                self._discard_browser_scope_projections(binding.session_root)
            else:
                target_scope = scope_materialization.trail[-1]
                reusable_scope_projection = (
                    self._cached_browser_scope_projection(
                        binding,
                        target_scope,
                        expected_lineage_revision=expected_base_revision,
                        accepted_scope_materialization=scope_materialization,
                    )
                )
            panel_event_root, panel_interaction_roots = (
                ensure_universal_properties_panel_interactions(
                    self.universal_store,
                    self.universal_registry,
                    binding.subject_root,
                )
            )
            form_event_root, form_interaction_roots = (
                ensure_universal_relation_form_interactions(
                    self.universal_store,
                    self.universal_registry,
                    binding.subject_root,
                )
            )
            projection = (
                project_universal_canvas(
                    self.universal_store,
                    self.universal_registry,
                    authentication_context=binding.context,
                )
                if scope_materialization is None
                else project_universal_scope_transition(
                    self.universal_store,
                    self.universal_registry,
                    authentication_context=binding.context,
                    scope_materialization=scope_materialization,
                    previous_projection=previous_projection,
                    expected_base_revision=expected_base_revision,
                    reusable_scope_projection=reusable_scope_projection,
                )
            )
            (
                instantiate_event_root,
                instantiation_interaction_roots,
                _event_fact_protocol,
                instantiation_fact_specs,
            ) = ensure_universal_instantiation_interactions(
                self.universal_store,
                self.universal_registry,
                binding.subject_root,
                projection,
            )
            (
                relation_composer_interaction_roots,
                _relation_composer_event_fact_protocol,
                relation_composer_fact_specs,
            ) = ensure_universal_relation_composer_interactions(
                self.universal_store,
                self.universal_registry,
                binding.subject_root,
                projection,
                authentication_context=binding.context,
            )
            (
                property_interaction_roots,
                _property_event_fact_protocol,
                property_fact_specs,
            ) = ensure_universal_property_interactions(
                self.universal_store,
                self.universal_registry,
                binding.subject_root,
                projection,
            )
            operational_transition_interaction_roots = (
                ensure_universal_operational_transition_interactions(
                    self.universal_store,
                    self.universal_registry,
                    binding.subject_root,
                    projection,
                )
            )
            (
                presentation_interaction_roots,
                _presentation_event_fact_protocol,
                presentation_fact_specs,
            ) = ensure_universal_presentation_interactions(
                self.universal_store,
                self.universal_registry,
                binding.subject_root,
                projection,
            )
            (
                interface_value_interaction_roots,
                _interface_value_event_fact_protocol,
                interface_value_fact_specs,
            ) = ensure_universal_interface_value_interactions(
                self.universal_store,
                self.universal_registry,
                binding.subject_root,
                projection,
            )
            (
                relation_member_interaction_roots,
                _relation_member_event_fact_protocol,
                relation_member_fact_specs,
            ) = ensure_universal_relation_member_interactions(
                self.universal_store,
                self.universal_registry,
                binding.subject_root,
                projection,
            )
            (
                topology_interaction_roots,
                _topology_event_fact_protocol,
                topology_fact_specs,
            ) = ensure_universal_topology_interactions(
                self.universal_store,
                self.universal_registry,
                binding.subject_root,
                projection,
            )
            composition_event_root, composition_interaction_roots = (
                ensure_universal_composition_interactions(
                    self.universal_store,
                    self.universal_registry,
                    binding.subject_root,
                    projection,
                )
            )
            history_event_root, history_interaction_roots = (
                ensure_universal_history_interactions(
                    self.universal_store,
                    self.universal_registry,
                    binding.subject_root,
                    projection,
                )
            )
            lens_event_root, lens_interaction_roots = (
                ensure_universal_inspector_lens_interactions(
                    self.universal_store,
                    self.universal_registry,
                    binding.subject_root,
                    projection,
                )
            )
            (
                scope_event_root,
                scope_interaction_roots,
                _scope_targets,
            ) = ensure_universal_scope_interactions(
                self.universal_store,
                self.universal_registry,
                binding.subject_root,
                projection,
            )
            panel_controls = tuple(
                panel["id"]
                for panel in projection["inspector"]["presentation"]["panels"]
            )
            form_bindings = tuple(
                read_relation_form_binding(
                    self.universal_store.snapshot(),
                    self.universal_registry.relation_form_protocol,
                    form_root,
                )
                for form_root in self.universal_registry.relation_form_roots.values()
            )
            form_controls = tuple(form.control_root for form in form_bindings)
            scope_controls = tuple(scope_interaction_roots)
            lens_controls = tuple(lens_interaction_roots)
            composition_controls = tuple(composition_interaction_roots)
            history_controls = tuple(history_interaction_roots)
            instantiation_controls = tuple(instantiation_interaction_roots)
            relation_composer_controls = tuple(
                relation_composer_interaction_roots
            )
            property_controls = tuple(property_interaction_roots)
            operational_transition_controls = tuple(
                operational_transition_interaction_roots
            )
            presentation_controls = tuple(presentation_interaction_roots)
            interface_value_controls = tuple(
                interface_value_interaction_roots
            )
            relation_member_controls = tuple(
                relation_member_interaction_roots
            )
            topology_controls = tuple(topology_interaction_roots)
            controls = (
                *panel_controls,
                *form_controls,
                *scope_controls,
                *lens_controls,
                *composition_controls,
                *history_controls,
                *instantiation_controls,
                *relation_composer_controls,
                *property_controls,
                *operational_transition_controls,
                *presentation_controls,
                *interface_value_controls,
                *relation_member_controls,
                *topology_controls,
            )
            if len(controls) != len(set(controls)):
                raise InvalidCell(
                    "projected interaction controls overlap"
                )
            interaction_roots = {
                **panel_interaction_roots,
                **form_interaction_roots,
                **scope_interaction_roots,
                **lens_interaction_roots,
                **composition_interaction_roots,
                **history_interaction_roots,
                **instantiation_interaction_roots,
                **relation_composer_interaction_roots,
                **property_interaction_roots,
                **operational_transition_interaction_roots,
                **presentation_interaction_roots,
                **interface_value_interaction_roots,
                **relation_member_interaction_roots,
                **topology_interaction_roots,
            }
            missing = set(controls) - set(interaction_roots)
            if missing:
                raise InvalidCell(
                    "visible control lacks a graph interaction"
                )
            snapshot = self.universal_store.snapshot()
            # The ensure calls above publish only interaction authority; they
            # do not change the visible canvas. Bind the already-projected
            # surface to their exact committed revision instead of walking the
            # entire visible graph a second time.
            projection["revision"] = snapshot.revision
            issued_projection = (
                self.interaction_projection_broker.issue_with_interactions(
                binding.interaction_projection_handle,
                snapshot,
                self.universal_registry.interaction_protocol,
                controls,
                tuple(interaction_roots[control] for control in controls),
                rule_protocol=self.universal_registry.rule_protocol,
                transaction_protocol=(
                    self.universal_registry.transaction_protocol
                ),
                admitted_nontransaction_action_roots=tuple(
                    (
                        *(form.operation_root for form in form_bindings),
                        CAPABILITY_SCOPE,
                        CAPABILITY_VIEW_SECTION,
                        CAPABILITY_COMPOSITION,
                        CAPABILITY_HISTORY,
                        CAPABILITY_INSTANTIATE,
                        CAPABILITY_EDIT_VALUE,
                        CAPABILITY_TRANSITION,
                        CAPABILITY_RELATION_MEMBERS,
                        CAPABILITY_TOPOLOGY,
                    )
                ),
                require_released=False,
            )
            )
            lease = issued_projection.lease
            form_by_control = {
                form.control_root: form for form in form_bindings
            }
            event_fact_specs_by_root = {
                spec.root_id: spec for spec in instantiation_fact_specs.values()
            }
            event_fact_specs_by_root.update({
                spec.root_id: spec
                for spec in relation_composer_fact_specs.values()
            })
            event_fact_specs_by_root.update({
                spec.root_id: spec
                for spec in property_fact_specs.values()
            })
            event_fact_specs_by_root.update({
                spec.root_id: spec
                for spec in presentation_fact_specs.values()
            })
            event_fact_specs_by_root.update({
                spec.root_id: spec
                for spec in interface_value_fact_specs.values()
            })
            event_fact_specs_by_root.update({
                spec.root_id: spec
                for spec in relation_member_fact_specs.values()
            })
            event_fact_specs_by_root.update({
                spec.root_id: spec for spec in topology_fact_specs.values()
            })
            accepted_interactions = issued_projection.interactions
            resolved_interactions = dict(zip(controls, accepted_interactions))
            projection["interaction_projection"] = {
                "revision": lease.revision,
                "lifecycle": "wip",
                "acknowledgement_mode": _RECEIPT_MODE,
                "bindings": [
                    {
                        "control": control,
                        "interaction": lease.bindings[control],
                        "event": resolved_interactions[control].event_root,
                        "projection_mode": (
                            _TOPOLOGY_DELTA_MODE
                            if resolved_interactions[control].action_root in (
                                CAPABILITY_RELATION_MEMBERS,
                                CAPABILITY_TOPOLOGY,
                                CAPABILITY_HISTORY,
                                CAPABILITY_SCOPE,
                            )
                            else _INTERACTION_DELTA_MODE
                        ),
                        "acknowledgement_mode": (
                            _TOPOLOGY_DELTA_MODE
                            if resolved_interactions[control].action_root
                            == CAPABILITY_SCOPE
                            else _RECEIPT_MODE
                        ),
                        "inputs": list(
                            resolved_interactions[control].input_roots
                        ),
                        "event_facts": [
                            {
                                "input": spec.root_id,
                                "source": spec.source,
                                "value_kind": spec.value_kind,
                                "required": spec.required,
                                "maximum_bytes": spec.maximum_bytes,
                            }
                            for spec in form_by_control[control].input_specs
                            if spec.source == "submitted"
                        ] if control in form_by_control else (
                            [
                                {
                                    "input": root,
                                    "source": event_fact_specs_by_root[root].source,
                                    "value_kind": (
                                        event_fact_specs_by_root[root].value_kind
                                    ),
                                    "required": (
                                        event_fact_specs_by_root[root].required
                                    ),
                                    **(
                                        {
                                            "minimum": event_fact_specs_by_root[
                                                root
                                            ].minimum,
                                            "maximum": event_fact_specs_by_root[
                                                root
                                            ].maximum,
                                        }
                                        if event_fact_specs_by_root[
                                            root
                                        ].value_kind == "number"
                                        else {
                                            "maximum_bytes": (
                                                event_fact_specs_by_root[
                                                    root
                                                ].maximum_bytes
                                            ),
                                        }
                                    ),
                                }
                            for root in resolved_interactions[control].input_roots
                            if root in event_fact_specs_by_root
                            ]
                        ),
                    }
                    for control in controls
                ],
            }
            projected_scope = projection.get("scope")
            scope_identity = None
            if scope_materialization is not None:
                scope_identity = (
                    scope_materialization.visible_roots,
                    scope_materialization.relation_roots,
                    scope_materialization.property_roots,
                    scope_materialization.interface_roots,
                )
            elif (
                isinstance(projected_scope, dict)
                and projected_scope.get("current")
                == self.universal_registry.canvas_root
            ):
                view_session = self.universal_registry.view_sessions[
                    binding.subject_root
                ]
                visibility_members = read_relation(
                    self.universal_store.snapshot(),
                    view_session.visibility_root,
                    budget=100_000,
                )
                interface_role = (
                    self.universal_registry.assembly_protocol.role(
                        "interface"
                    )
                )
                visible_roots = tuple(
                    member.participant_id
                    for member in visibility_members
                    if member.role_id == self.universal_registry.roles["visible"]
                )
                relation_roots = tuple(
                    member.participant_id
                    for member in visibility_members
                    if member.role_id == self.universal_registry.roles["relation"]
                )
                property_roots = tuple(
                    member.participant_id
                    for member in visibility_members
                    if member.role_id == self.universal_registry.roles["property"]
                )
                interface_roots = tuple(
                    member.participant_id
                    for member in visibility_members
                    if member.role_id == interface_role
                )
                projected_roots = tuple(
                    node["id"] for node in projection["nodes"]
                )
                if projected_roots != visible_roots:
                    # "differs" alone cannot be acted on. What differs is
                    # either membership or order, and the two mean
                    # different things: a missing root is a real drift, a
                    # reordering is presentation. The refusal says which --
                    # and it only refuses drift. Order is what the canvas
                    # shows, so a pure permutation is answered by taking
                    # the projected order as the retained one, not by
                    # refusing a mutation that kept every identity.
                    missing = [
                        root for root in visible_roots
                        if root not in projected_roots
                    ]
                    extra = [
                        root for root in projected_roots
                        if root not in visible_roots
                    ]
                    if not missing and not extra:
                        visible_roots = projected_roots
                    else:
                        raise InvalidCell(
                            "retained scope identity differs from its "
                            "projection: %d projected, %d visible, "
                            "%d missing %s, %d unexpected %s" % (
                                len(projected_roots), len(visible_roots),
                                len(missing),
                                [root[:12] for root in missing[:4]],
                                len(extra),
                                [root[:12] for root in extra[:4]],
                            )
                        )
                scope_identity = (
                    visible_roots,
                    relation_roots,
                    property_roots,
                    interface_roots,
                )
            projected_binding = _BrowserCanvasProjectionBinding(
                binding.session_root,
                binding.subject_root,
                binding.view_root,
                binding.tenant_root,
                binding.assurance_root,
                projection,
            )
            with self._browser_session_lock:
                self._browser_canvas_projections[
                    binding.session_root
                ] = projected_binding
                if (
                    isinstance(projected_scope, dict)
                    and type(projected_scope.get("current")) is str
                ):
                    scope_key = (
                        binding.session_root,
                        projected_scope["current"],
                    )
                    self._browser_scope_canvas_projections.pop(
                        scope_key, None
                    )
                    self._browser_scope_canvas_projections[
                        scope_key
                    ] = projected_binding
                    self._browser_scope_projection_lineage[
                        binding.session_root
                    ] = projection["revision"]
                    if scope_identity is not None:
                        self._browser_scope_canvas_identities[
                            scope_key
                        ] = scope_identity
                    else:
                        self._browser_scope_canvas_identities.pop(
                            scope_key, None
                        )
                    self._enforce_browser_scope_projection_limit(
                        binding.session_root
                    )
            return projection

    def _enforce_browser_scope_projection_limit(
        self, session_root: str
    ) -> None:
        """Keep only the newest disposable scope views for one session."""
        with self._browser_session_lock:
            retained_keys = tuple(
                key
                for key in self._browser_scope_canvas_projections
                if key[0] == session_root
            )
            for stale_key in retained_keys[
                :-_BROWSER_SCOPE_PROJECTION_LIMIT
            ]:
                self._browser_scope_canvas_projections.pop(stale_key, None)
                self._browser_scope_canvas_identities.pop(stale_key, None)

    def _discard_browser_scope_projections(self, session_root: str) -> None:
        """Discard disposable scope views without touching graph authority."""
        with self._browser_session_lock:
            self._browser_scope_canvas_projections = {
                key: value
                for key, value in self._browser_scope_canvas_projections.items()
                if key[0] != session_root
            }
            self._browser_scope_canvas_identities = {
                key: value
                for key, value in self._browser_scope_canvas_identities.items()
                if key[0] != session_root
            }
            self._browser_scope_projection_lineage.pop(session_root, None)

    def _cached_browser_scope_projection(
        self,
        binding: _BrowserSessionBinding,
        scope_root: str,
        *,
        expected_lineage_revision: int,
        accepted_scope_materialization=None,
    ) -> dict[str, object] | None:
        """Return one retained private scope only on an observed lineage."""
        if type(scope_root) is not str or type(expected_lineage_revision) is not int:
            return None
        with self._browser_session_lock:
            lineage_revision = self._browser_scope_projection_lineage.get(
                binding.session_root
            )
            cached = self._browser_scope_canvas_projections.get((
                binding.session_root,
                scope_root,
            ))
        if lineage_revision != expected_lineage_revision:
            self._discard_browser_scope_projections(binding.session_root)
            return None
        current_revision = self.universal_store.revision
        if current_revision != expected_lineage_revision:
            materialization = accepted_scope_materialization
            if (
                materialization is None
                or materialization.base_revision != expected_lineage_revision
                or materialization.revision != current_revision
                or materialization.revision != expected_lineage_revision + 1
                or materialization.session_root != binding.view_root
                or materialization.subject_root != binding.subject_root
                or not materialization.trail
                or materialization.trail[-1] != scope_root
                or materialization.changed_roots
                != self.universal_store.revision_changes(current_revision)
            ):
                self._discard_browser_scope_projections(binding.session_root)
                return None
        if (
            cached is None
            or cached.session_root != binding.session_root
            or cached.subject_root != binding.subject_root
            or cached.view_root != binding.view_root
            or cached.tenant_root != binding.tenant_root
            or cached.assurance_root != binding.assurance_root
            or not isinstance(cached.projection.get("scope"), dict)
            or cached.projection["scope"].get("current") != scope_root
        ):
            return None
        return cached.projection

    def _cached_browser_scope_identity(
        self,
        binding: _BrowserSessionBinding,
        scope_root: str,
        *,
        expected_lineage_revision: int,
    ):
        """Return exact retained scope roots after the same identity checks."""
        projection = self._cached_browser_scope_projection(
            binding,
            scope_root,
            expected_lineage_revision=expected_lineage_revision,
        )
        if projection is None:
            return None
        with self._browser_session_lock:
            return self._browser_scope_canvas_identities.get((
                binding.session_root,
                scope_root,
            ))

    def _cached_browser_canvas_projection(
        self,
        binding: _BrowserSessionBinding,
        revision: int,
    ) -> dict[str, object] | None:
        """Return one disposable session projection at its exact revision."""
        with self._browser_session_lock:
            cached = self._browser_canvas_projections.get(
                binding.session_root
            )
        if (
            cached is None
            or cached.session_root != binding.session_root
            or cached.subject_root != binding.subject_root
            or cached.view_root != binding.view_root
            or cached.tenant_root != binding.tenant_root
            or cached.assurance_root != binding.assurance_root
            or cached.projection.get("revision") != revision
        ):
            return None
        return cached.projection

    def project_runtime_state(self, *, authentication_context: object):
        """Project application status from the universal graph authority."""
        canvas = project_universal_canvas(
            self.universal_store,
            self.universal_registry,
            authentication_context=authentication_context,
        )
        snapshot = self.universal_store.snapshot()
        scope = canvas['scope']
        payload = {
            'ok': True,
            'application_node': self.universal_registry.application_root,
            'ui_root': self.universal_registry.presentation.ui_root,
            'focus': canvas['selected'],
            'container': scope['current'],
            'container_title': scope['current_label'],
            'node_count': len(snapshot.cells),
            'schema_version': UNIVERSAL_APPLICATION_SCHEMA_VERSION,
            # A successful authorised semantic projection over a physically
            # validated Cell snapshot is the state validity court here.
            'valid': True,
            'persistent': self.universal_state_path is not None,
            'universal_persistent': self.universal_state_path is not None,
            'universal_checkpoint': (
                'anchored'
                if self.universal_checkpoint_guard is not None
                else 'isolated'
            ),
            'universal_checkpoint_format': (
                'v2-asymmetric'
                if self.universal_checkpoint_signing_authority is not None
                else 'none'
            ),
            'universal_checkpoint_descriptor': (
                self.universal_checkpoint_signing_authority.descriptor_root
                if self.universal_checkpoint_signing_authority is not None
                else None
            ),
            'universal_checkpoint_binding': (
                self.universal_checkpoint_binding_root
            ),
            'universal_checkpoint_protection': (
                self.universal_checkpoint_protection
            ),
            'universal_runtime_url': self.url,
            'universal_runtime_node': (
                self.universal_registry.application_root
            ),
            'universal_application_root': (
                self.universal_registry.application_root
            ),
            'universal_runtime_holder': self._runtime_holder_root,
            'universal_runtime_ownership': self._runtime_ownership_root,
            'universal_revision': snapshot.revision,
            'universal_cell_count': len(snapshot.cells),
            'legacy_parallel_runtime': self.legacy_runtime_enabled,
            'legacy_runtime_status': (
                'migration-only; not product authority'
                if self.legacy_runtime_enabled
                else 'not instantiated'
            ),
        }
        if self.allow_legacy_mutations:
            app = self.store.nodes[self.registry['app']]
            payload['legacy'] = {
                'application_node': self.registry['app'],
                'ui_root': self.registry['ui_root'],
                'focus': self.store.pull(self.registry['focus']),
                'container': self.store.pull(app['params']['container']),
                'container_title': self.store.pull(
                    app['params']['container_title']
                ),
                'node_count': len(self.store.nodes),
                'schema_version': self.store.pull(
                    app['params']['schema_version']
                ),
                'valid': False,
                'authority': 'migration test only',
            }
        return payload

    def _snapshot_loop(self):
        while not self._snapshot_stop.is_set():
            if not self._snapshot_event.wait(timeout=0.5):
                continue
            self._snapshot_event.clear()
            time.sleep(0.15)
            while self._snapshot_event.is_set():
                self._snapshot_event.clear()
                time.sleep(0.15)
            if self._snapshot_stop.is_set():
                break
            self.flush_snapshot(nonblocking=True)

    def request_snapshot(self):
        if self.state_path is not None:
            self._snapshot_revision += 1
            self._snapshot_event.set()

    def refresh_live_state(self, mode=None):
        app = self.store.nodes[self.registry['app']]
        params = app['params']
        mode = mode or self.store.pull(params['mode'])
        if mode == 'brain':
            pairs = [
                (params['brain_report_source'], params['brain_report_snapshot']),
                (params['cde_stage_source'], params['cde_stage_target']),
                (params['cde_scope_source'], params['cde_scope_target']),
                (params['cde_tier_source'], params['cde_tier_target']),
                (params['cde_container_source'], params['cde_container_target']),
                (params['cde_runtime_source'], params['cde_runtime_target']),
                (params['orchestration_brain_source'],
                 params['orchestration_brain_target']),
                (params['orchestration_hooks_source'],
                 params['orchestration_hooks_target']),
            ]
        elif mode == 'cockpit':
            pairs = [
                (params['governance_brain_source'], params['brain_result']),
                (params['governance_hooks_source'], params['hook_result']),
                (params['governance_score_source'], params['governance_result']),
            ]
        else:
            return False
        for source, target in pairs:
            self.store.apply_op({'op': 'sample', 'source': source, 'target': target,
                                 'actor': 'live-watcher'})
        error = params['live_refresh_error']
        if self.store.pull(error):
            self.store._memo.clear()
            self.store.edit(error, ['body', 'floor', 'value'], '', actor='live-watcher')
        self.request_snapshot()
        return True

    def _live_loop(self):
        last = 0.0
        while not self._live_stop.wait(1.0):
            try:
                with self.mutation_lock:
                    app = self.store.nodes[self.registry['app']]
                    params = app['params']
                    if not self.store.pull(params['live_refresh_enabled']):
                        continue
                    mode = self.store.pull(params['mode'])
                    if mode not in ('brain', 'cockpit'):
                        continue
                    interval = max(5.0, float(self.store.pull(
                        params['live_refresh_seconds'])))
                    now = time.monotonic()
                    if now - last < interval:
                        continue
                    self.refresh_live_state(mode)
                    last = now
            except Exception as exc:
                with self.mutation_lock:
                    try:
                        app = self.store.nodes[self.registry['app']]
                        error = app['params']['live_refresh_error']
                        self.store._memo.clear()
                        self.store.edit(error, ['body', 'floor', 'value'],
                                        '%s: %s' % (type(exc).__name__, exc),
                                        actor='live-watcher')
                        self.request_snapshot()
                    except Exception:
                        pass

    def execute_command(self, operation, input_value=None):
        capability = operation['capability']
        if capability == 'application.checkpoint':
            self.flush_snapshot()
            return self.registry['app']
        if capability == 'history.undo':
            return self._undo_user_transaction()
        if capability == 'history.redo':
            return self._redo_user_transaction()
        if capability == 'cockpit.command.submit':
            domain = self.registry.get('cockpit_domain')
            if not isinstance(domain, dict) or domain.get('command') not in self.store.nodes:
                raise ValueError('Cockpit domain is not registered')
            submit_cockpit_command(
                self.store, domain, '' if input_value is None else input_value,
                actor=operation.get('actor') or 'cockpit-ui')
            return domain['command']
        if capability == 'relation.create':
            args = operation['args']
            source_param = args.get('source_param')
            if source_param not in self.store.nodes:
                raise ValueError('relation.create source parameter is missing')
            source = self.store.pull(source_param)
            if not isinstance(source, dict) or source.get('node_id') not in self.store.nodes:
                raise ValueError('select an output port before completing a relation')
            target_node = args.get('target_node')
            if target_node not in self.store.nodes:
                raise ValueError('relation.create target node is missing')
            self.store._memo.clear()
            relation_id = self.store.relation([
                {'role': 'source', 'direction': 'out',
                 'node_id': source['node_id'],
                 'port_id': str(source.get('port_id') or 'value'),
                 'cardinality': 'many'},
                {'role': 'target', 'direction': 'in',
                 'node_id': target_node,
                 'port_id': str(args.get('target_port') or 'value'),
                 'cardinality': 'one'},
            ], title='User relation', actor=operation.get('actor'))
            for name, value in (
                    ('color', '#d97757'), ('width', 2.1), ('dash', ''),
                    ('hidden', False), ('encoding', 'identity'),
                    ('encryption', 'none')):
                set_relation_parameter(self.store, relation_id, name, value,
                                       actor=operation.get('actor'))
            payload = build_payload_envelope(self.store, {
                'logical_type': 'urn:archhub:type:any',
                'media_type': 'application/x-archhub-value',
                'mode': 'inline',
                'value_ref': source['node_id'],
            }, title='Relation payload', actor=operation.get('actor'))
            attach_payload(self.store, relation_id, payload,
                           actor=operation.get('actor'))
            _legacy_application_module().project_relation_on_canvas(
                self.store, relation_id
            )
            self.store.edit(source_param, ['body', 'floor', 'value'],
                            {'node_id': '', 'port_id': ''},
                            actor=operation.get('actor'))
            self.store.edit(self.registry['focus'], ['body', 'floor', 'value'],
                            relation_id, actor=operation.get('actor'))
            return relation_id
        if capability == 'canvas.zoom':
            args = operation['args']
            zoom_param = args.get('zoom_param')
            current = float(self.store.pull(zoom_param))
            value = max(0.25, min(2.0, round(current + float(args.get('delta', 0)), 2)))
            self.store.edit(zoom_param, ['body', 'floor', 'value'], value,
                            actor=operation.get('actor'))
            return zoom_param
        if capability == 'canvas.fit':
            args = operation['args']
            values = ((args.get('zoom_param'), 0.72),
                      (args.get('pan_x_param'), 18.0),
                      (args.get('pan_y_param'), 18.0))
            for param, value in values:
                if param not in self.store.nodes:
                    raise ValueError('canvas.fit parameter is missing')
                self.store.edit(param, ['body', 'floor', 'value'], value,
                                actor=operation.get('actor'))
            return args.get('zoom_param')
        if capability == 'container.open':
            target = operation.get('args', {}).get('container_id')
            return _legacy_application_module().project_container_on_canvas(
                self.store, target
            )
        if capability == 'container.back':
            return _legacy_application_module().navigate_container_back(
                self.store
            )
        if capability == 'container.root':
            return _legacy_application_module().navigate_container_root(
                self.store
            )
        if capability == 'node.create':
            args = operation['args']
            kind = str(self.store.pull(args.get('kind_param')) or 'value')
            allowed = {'value', 'op', 'group', 'param', 'session', 'ui', 'proposal'}
            if kind not in allowed:
                raise ValueError('node.create does not allow role %r' % kind)
            title = str(self.store.pull(args.get('title_param')) or '').strip() or 'Untitled'
            raw_value = self.store.pull(args.get('value_param'))
            value = raw_value
            if isinstance(raw_value, str) and raw_value.strip():
                try:
                    value = json.loads(raw_value)
                except json.JSONDecodeError:
                    value = raw_value
            self.store._memo.clear()
            if kind in {'group', 'session'}:
                node_id = self.store.add(kind, title, inner=[], actor=operation.get('actor'))
            elif kind == 'ui':
                node_id = ui_element(self.store, 'div', text=str(value), title=title)
            else:
                node_id = self.store.add(kind, title,
                                         floor={'op': 'value', 'value': value},
                                         frozen=(kind == 'proposal'),
                                         actor=operation.get('actor'))
            card_count = sum(1 for node in self.store.nodes.values()
                             if node['kind'] == 'ui'
                             and node['title'].startswith('Canvas node: '))
            x = 80 + (card_count % 5) * 232
            y = 100 + (card_count // 5) * 164
            x_param = self.store.add('param', 'position_x',
                                     floor={'op': 'value', 'value': x})
            y_param = self.store.add('param', 'position_y',
                                     floor={'op': 'value', 'value': y})
            params = dict(self.store.nodes[node_id]['params'])
            params.update({'position_x': x_param, 'position_y': y_param})
            self.store.edit(node_id, ['params'], params, actor=operation.get('actor'))
            session = next(nid for nid, node in self.store.nodes.items()
                           if node['kind'] == 'session'
                           and node['title'] == 'ArchHub Operating Graph')
            inner = list(self.store.nodes[session]['body']['inner'])
            self.store.edit(session, ['body', 'inner'], inner + [node_id],
                            actor=operation.get('actor'))
            _legacy_application_module().project_node_on_canvas(
                self.store, node_id
            )
            self.store.edit(self.registry['focus'], ['body', 'floor', 'value'], node_id,
                            actor=operation.get('actor'))
            self.store.edit(self.registry['mode'], ['body', 'floor', 'value'], 'workspace',
                            actor=operation.get('actor'))
            for param_name in ('title_param', 'value_param'):
                param = args.get(param_name)
                self.store.edit(param, ['body', 'floor', 'value'], '',
                                actor=operation.get('actor'))
            return node_id
        if capability == 'selection.toggle':
            args = operation['args']
            selection_param = args.get('selection_param')
            selected = list(self.store.pull(selection_param) or [])
            node_id = args.get('node_id')
            if node_id not in self.store.nodes:
                raise ValueError('selection target is missing')
            if node_id in selected:
                selected.remove(node_id)
            else:
                selected.append(node_id)
            self.store._memo.clear()
            self.store.edit(selection_param, ['body', 'floor', 'value'], selected,
                            actor=operation.get('actor'))
            return selection_param
        if capability == 'selection.group':
            args = operation['args']
            selection_param = args.get('selection_param')
            selected = list(dict.fromkeys(self.store.pull(selection_param) or []))
            if len(selected) < 2 or any(node_id not in self.store.nodes
                                        for node_id in selected):
                raise ValueError('grouping requires at least two selected nodes')
            self.store._memo.clear()
            group_id = self.store.add('group', 'Group (%d nodes)' % len(selected),
                                      inner=selected, actor=operation.get('actor'))
            xs = [float(self.store.pull(self.store.nodes[nid]['params']['position_x']))
                  for nid in selected]
            ys = [float(self.store.pull(self.store.nodes[nid]['params']['position_y']))
                  for nid in selected]
            self.store._memo.clear()
            x_param = self.store.add('param', 'position_x',
                                     floor={'op': 'value', 'value': sum(xs) / len(xs)})
            y_param = self.store.add('param', 'position_y',
                                     floor={'op': 'value', 'value': sum(ys) / len(ys)})
            self.store.edit(group_id, ['params'],
                            {'position_x': x_param, 'position_y': y_param},
                            actor=operation.get('actor'))
            session = next(nid for nid, node in self.store.nodes.items()
                           if node['kind'] == 'session'
                           and node['title'] == 'ArchHub Operating Graph')
            inner = [nid for nid in self.store.nodes[session]['body']['inner']
                     if nid not in selected]
            self.store.edit(session, ['body', 'inner'], inner + [group_id],
                            actor=operation.get('actor'))
            _legacy_application_module().project_node_on_canvas(
                self.store, group_id
            )
            self.store.edit(selection_param, ['body', 'floor', 'value'], [],
                            actor=operation.get('actor'))
            self.store.edit(self.registry['focus'], ['body', 'floor', 'value'], group_id,
                            actor=operation.get('actor'))
            return group_id
        if capability in {'relation.transport.encrypt', 'relation.transport.decrypt'}:
            relation_id = operation['args'].get('relation_id')
            relation = self.store.nodes.get(relation_id)
            if not relation or relation['kind'] != 'wire':
                raise ValueError('transport command requires a relation node')
            if relation_stages(self.store.nodes, relation):
                raise ValueError('relation already has executable transport stages')
            self.store._memo.clear()
            secret_ref = 'op://archhub/relations/aes_key'
            if capability.endswith('encrypt'):
                stages = [
                    build_json_codec_stage(self.store, 'json_encode',
                                           title='JSON encode'),
                    build_aead_stage(self.store, 'encrypt', secret_ref,
                                     aad=relation_id, title='AES-GCM encrypt'),
                ]
                encoding, encryption = 'json', 'AES-GCM'
            else:
                stages = [
                    build_aead_stage(self.store, 'decrypt', secret_ref,
                                     aad=relation_id, title='AES-GCM decrypt'),
                    build_json_codec_stage(self.store, 'json_decode',
                                           title='JSON decode'),
                ]
                encoding, encryption = 'json', 'AES-GCM decrypt'
            for stage in stages:
                append_stage(self.store, relation_id, stage, mode='map',
                             actor=operation.get('actor'))
            set_relation_parameter(self.store, relation_id, 'encoding', encoding,
                                   actor=operation.get('actor'))
            set_relation_parameter(self.store, relation_id, 'encryption', encryption,
                                   actor=operation.get('actor'))
            return relation_id
        raise ValueError('unsupported application capability %r' % capability)

    def _history_entries(self):
        entries = []
        for node_id, node in self.store.nodes.items():
            if node['kind'] != 'history':
                continue
            entry = node['body']['floor'].get('entry', {})
            if isinstance(entry, dict):
                entries.append((node['meta']['seq'], node_id, entry))
        return sorted(entries, reverse=True)

    @staticmethod
    def _inverse_history_op(entry, *, actor, transaction, marker, history_id):
        inverse = {
            'id': entry['id'], 'path': list(entry['path']),
            'actor': actor, 'transaction': transaction,
            marker: history_id,
        }
        if entry.get('op') == 'set' and entry.get('before_missing'):
            inverse['op'] = 'unset'
        elif entry.get('op') in {'set', 'unset'} and 'before' in entry:
            inverse['op'] = 'set'
            inverse['value'] = copy.deepcopy(entry['before'])
        else:
            raise ValueError('history entry is not reversible')
        return inverse

    def _undo_user_transaction(self):
        entries = self._history_entries()
        undone = {entry.get('undo_of') for _seq, _hid, entry in entries
                  if entry.get('undo_of')}
        candidate = next(((seq, hid, entry) for seq, hid, entry in entries
                          if entry.get('op') in {'set', 'unset'}
                          and entry.get('actor') == 'user'
                          and ('before' in entry or entry.get('before_missing'))
                          and not entry.get('undo_of')
                          and hid not in undone), None)
        if candidate is None:
            return []
        _seq, history_id, latest = candidate
        transaction = latest.get('transaction') or history_id
        group = [(hid, entry) for _seq, hid, entry in entries
                 if entry.get('op') in {'set', 'unset'}
                 and entry.get('actor') == 'user'
                 and ('before' in entry or entry.get('before_missing'))
                 and not entry.get('undo_of')
                 and hid not in undone
                 and (entry.get('transaction') or hid) == transaction]
        touched = []
        undo_transaction = 'undo:' + str(transaction)
        for original_id, entry in group:
            inverse = self._inverse_history_op(
                entry, actor='user', transaction=undo_transaction,
                marker='undo_of', history_id=original_id)
            touched.append(self.store.apply_op(inverse))
        return touched

    def _redo_user_transaction(self):
        entries = self._history_entries()
        redone = {entry.get('redo_of') for _seq, _hid, entry in entries
                  if entry.get('redo_of')}
        candidate = next(((seq, hid, entry) for seq, hid, entry in entries
                          if entry.get('op') in {'set', 'unset'}
                          and entry.get('actor') == 'user'
                          and entry.get('undo_of')
                          and hid not in redone), None)
        if candidate is None:
            return []
        candidate_seq, history_id, latest = candidate
        if any(seq > candidate_seq and entry.get('op') in {'set', 'unset'}
               and entry.get('actor') == 'user'
               and not entry.get('undo_of') and not entry.get('redo_of')
               for seq, _hid, entry in entries):
            return []
        transaction = latest.get('transaction') or history_id
        group = [(hid, entry) for _seq, hid, entry in entries
                 if entry.get('op') in {'set', 'unset'}
                 and entry.get('actor') == 'user'
                 and entry.get('undo_of')
                 and hid not in redone
                 and (entry.get('transaction') or hid) == transaction]
        touched = []
        redo_transaction = 'redo:' + str(transaction)
        for undo_id, entry in group:
            inverse = self._inverse_history_op(
                entry, actor='user', transaction=redo_transaction,
                marker='redo_of', history_id=undo_id)
            touched.append(self.store.apply_op(inverse))
        return touched

    def flush_snapshot(self, nonblocking=False):
        if self.state_path is not None:
            if nonblocking:
                with self.mutation_lock:
                    revision = self._snapshot_revision
                return save_snapshot_cooperative(
                    self.store, self.state_path, self.mutation_lock, revision,
                    lambda: self._snapshot_revision)
            with self.mutation_lock:
                save_snapshot(self.store, self.state_path)
            return True
        return False

    @property
    def url(self):
        host, port = self.httpd.server_address[:2]
        return 'http://%s:%d' % (host, port)

    @property
    def public_url(self):
        return self._public_server_url or self.url

    @property
    def bootstrap_url(self):
        token = self.browser_bootstrap_token
        if not token:
            return self.public_url + '/'
        return self.public_url + '/?bootstrap=' + token

    def prewarm_universal_machine_read_projections(self) -> dict[str, object]:
        """Build revision-bound machine read caches from the Cell authority."""
        context = self.universal_registry.authorization.session.context()
        revision = self.universal_store.revision
        targets = self.machine_projection_prewarm_targets
        with self._projection_prewarm_status_lock:
            self._projection_prewarm_status = {
                "ok": False,
                "revision": revision,
                "requested_revision": revision,
                "status": "warming",
                "targets": list(targets),
                "observed_at": time.time(),
            }
        try:
            if self.universal_checkpoint_guard is not None:
                self.universal_checkpoint_guard.require_healthy()
            for path in (
                "/api/universal/work",
                "/api/universal/canvas",
                "/api/universal/baboom-context",
            ):
                self.require_universal_http_route(
                    "GET", path, authentication_context=context
                )
            work_index = None
            if "work" in targets or "baboom" in targets:
                work_index = self._project_universal_machine_work_index(
                    authentication_context=context
                )
            canvas = None
            if "canvas" in targets:
                canvas = self._project_universal_machine_canvas(
                    request_agent_session=(
                        self.universal_registry.agent_body.session.root_id
                    ),
                    authentication_context=context,
                )
            baboom = None
            if "baboom" in targets:
                baboom = project_universal_baboom_context(
                    self.universal_store,
                    self.universal_registry,
                    runtime_presence=self._machine_agent_runtime_presence(),
                    authentication_context=context,
                    work_index=work_index,
                )
            warmed_revision = self.universal_store.revision
            ok = warmed_revision == revision
            status = {
                "ok": ok,
                "revision": warmed_revision,
                "requested_revision": revision,
                "status": "warm" if ok else "stale",
                "targets": list(targets),
                "observed_at": time.time(),
            }
            if work_index is not None:
                status["work_total"] = work_index["total"]
            if canvas is not None:
                status["canvas_roots"] = len(canvas["nodes"])
            if baboom is not None:
                status["baboom_lens"] = baboom["context_lens"]
        except Exception as exc:
            status = {
                "ok": False,
                "revision": self.universal_store.revision,
                "requested_revision": revision,
                "status": "failed",
                "targets": list(targets),
                "reason": "machine read projection prewarm failed",
                "error_type": type(exc).__name__,
                "observed_at": time.time(),
            }
        with self._projection_prewarm_status_lock:
            self._projection_prewarm_status = status
        return dict(status)

    def universal_machine_projection_prewarm_status(self) -> dict[str, object]:
        with self._projection_prewarm_status_lock:
            return dict(self._projection_prewarm_status)

    def _projection_prewarm_loop(self):
        next_revision = -1
        while not self._projection_prewarm_stop.is_set():
            revision = self.universal_store.revision
            if revision == next_revision:
                self._projection_prewarm_stop.wait(0.5)
                continue
            status = self.prewarm_universal_machine_read_projections()
            if status.get("ok") is True:
                status_revision = status.get(
                    "revision", self.universal_store.revision
                )
                next_revision = (
                    status_revision
                    if type(status_revision) is int
                    else self.universal_store.revision
                )
                self._projection_prewarm_stop.wait(0.5)
            else:
                self._projection_prewarm_stop.wait(5.0)

    def _start_projection_prewarm(self):
        if self._projection_prewarm_thread is not None:
            return
        self._projection_prewarm_thread = threading.Thread(
            target=self._projection_prewarm_loop,
            name="archhub-machine-projection-prewarm",
            daemon=True,
        )
        self._projection_prewarm_thread.start()

    def build_universal_cloud_gateway(
        self,
        *,
        resource_origin: str,
        nonce_key_provider: SigningKeyProvider | None = None,
        nonce_key_id: str = 'archhub.local.universal-cloud-dpop-nonce',
    ) -> UniversalCloudGateway:
        """Build the one graph-owned remote surface for this live application.

        The gateway has no copy of the application graph, token store, or
        command queue. Cloud sessions, DPoP verification, route authorization,
        device custody, and dispatch all resolve against this server's one
        Universal Cell store. Building it has no network side effect.
        """
        if not isinstance(resource_origin, str) or not resource_origin:
            raise ValueError('Universal cloud resource origin is required')
        if not isinstance(nonce_key_id, str) or not nonce_key_id:
            raise ValueError('Universal cloud nonce key id is required')
        registry = self.universal_registry
        authorization = registry.authorization
        session_broker = CloudSessionBroker(
            session_protocol=registry.cloud_session_protocol,
            identity_protocol=authorization.identity_protocol,
            relationship_broker=authorization.relationship_broker,
            authentication_broker=authorization.broker,
            request_proof_verifier=JoseRfc9449ProofVerifier(),
            replay_policy_authority_verifier=(
                PublishedProofReplayPolicyVerifier(
                    registry.assembly_protocol,
                    registry.standard_library.lifecycle_protocol,
                    registry.attestation_protocol,
                    registry.attestation_broker,
                    registry.resource_lifecycle_court_root,
                    (
                        registry.cloud_session_protocol
                        .proof_replay_policy_lifecycle_root
                    ),
                )
            ),
            tenant_admission_verifier=PublishedTenantAdmissionVerifier(
                registry.tenant_configuration_protocol,
                registry.assembly_protocol,
                registry.standard_library.lifecycle_protocol,
                authorization.protocol,
                authorization.identity_protocol,
                authorization.relationship_broker,
            ),
            device_custody_verifier=ActiveDeviceCustodyVerifier(
                registry.device_custody_protocol
            ),
            session_issuer_root=authorization.subject_root,
        )
        nonce_provider = nonce_key_provider or WindowsDpapiSigningKeyProvider(
            WindowsDpapiSigningKeyProvider.default_path()
        )
        nonce_broker = ResourceServerNonceBroker(
            key_provider=nonce_provider,
            key_id=nonce_key_id,
            audience=resource_origin,
        )
        return create_application_cloud_gateway(
            self,
            session_broker=session_broker,
            nonce_broker=nonce_broker,
            resource_origin=resource_origin,
            runtime_id=hashlib.sha256(
                self._runtime_holder_root.encode('utf-8')
            ).hexdigest(),
        )

    def build_universal_cloud_tls_server(
        self,
        *,
        resource_origin: str,
        certificate_file: str | os.PathLike[str],
        private_key_file: str | os.PathLike[str],
        nonce_key_provider: SigningKeyProvider | None = None,
        nonce_key_id: str = 'archhub.local.universal-cloud-dpop-nonce',
    ) -> tuple[UniversalCloudGateway, object]:
        """Build the explicit TLS listener without starting a second owner."""
        if not isinstance(self.cloud_host, str) or not self.cloud_host:
            raise ValueError('Universal cloud listener host is required')
        if not isinstance(self.cloud_port, int) or not 1 <= self.cloud_port <= 65535:
            raise ValueError('Universal cloud listener port is invalid')
        if certificate_file is None or private_key_file is None:
            raise ValueError('Universal cloud TLS certificate and key are required')
        gateway = self.build_universal_cloud_gateway(
            resource_origin=resource_origin,
            nonce_key_provider=nonce_key_provider,
            nonce_key_id=nonce_key_id,
        )
        listener = UniversalCloudTlsListener(
            host=self.cloud_host,
            port=self.cloud_port,
            certificate_file=Path(certificate_file),
            private_key_file=Path(private_key_file),
        )
        return gateway, create_universal_cloud_tls_server(gateway, listener)

    def start(self):
        if self.thread is None:
            if self.machine_transport is not None:
                self.machine_transport.start()
            try:
                self.universal_reaction_engine.start()
                self.universal_registry.browser_publish_court.configure(
                    self.url, self.browser_session_token
                )
                self.thread = threading.Thread(
                    target=self.httpd.serve_forever, daemon=True
                )
                self.thread.start()
                if self.universal_cloud_server is not None:
                    self._universal_cloud_thread = threading.Thread(
                        target=self.universal_cloud_server.run,
                        name='archhub-universal-cloud-gateway',
                        daemon=True,
                    )
                    self._universal_cloud_thread.start()
                if (
                    self.machine_transport is not None
                    and self.enable_machine_projection_prewarm
                ):
                    self._start_projection_prewarm()
            except Exception:
                self._projection_prewarm_stop.set()
                if self.machine_transport is not None:
                    self.machine_transport.close()
                raise
        return self

    def close(self, *, preserve_browser_session: bool = False):
        # Cancel an in-flight cooperative snapshot before any final save. A
        # revision bump makes its chunk loop stale; the join proves it cannot
        # race the final atomic replacement or a subsequent server restart.
        with self.mutation_lock:
            self._begin_runtime_drain()
        self._snapshot_stop.set()
        with self.mutation_lock:
            self._snapshot_revision += 1
        self._snapshot_event.set()
        self._live_stop.set()
        self._projection_prewarm_stop.set()
        if self.universal_cloud_server is not None:
            self.universal_cloud_server.should_exit = True
        if self._universal_cloud_thread is not None:
            self._universal_cloud_thread.join(timeout=10)
        if self.machine_transport is not None:
            self.machine_transport.close()
        with self._machine_agent_session_lock:
            self._machine_agent_sessions.clear()
            self._machine_agent_recovery_capabilities.clear()
            self._machine_agent_challenges.clear()
        if self._live_thread:
            self._live_thread.join(timeout=10)
        if self._projection_prewarm_thread:
            self._projection_prewarm_thread.join(timeout=10)
        self.universal_reaction_engine.stop()
        if self.thread is not None:
            self.httpd.shutdown()
        self.httpd.server_close()
        if self.thread:
            self.thread.join(timeout=5)
        if self._snapshot_thread:
            self._snapshot_thread.join(timeout=30)
            if self._snapshot_thread.is_alive():
                raise RuntimeError('snapshot writer did not stop before final save')
        with self.mutation_lock:
            protocol = self.universal_registry.browser_session_protocol
            with self._browser_session_lock:
                bindings = tuple(self._browser_sessions.values())
                self._browser_sessions.clear()
                self._browser_canvas_projections.clear()
                self._browser_scope_canvas_projections.clear()
                self._browser_scope_canvas_identities.clear()
                self._browser_scope_projection_lineage.clear()
            for binding in bindings:
                self.interaction_projection_broker.revoke(
                    binding.interaction_projection_handle
                )
                if (
                    preserve_browser_session
                    and binding.session_root == self.browser_session_root
                ):
                    continue
                revoke_browser_session(
                    self.universal_store,
                    protocol,
                    binding.session_root,
                    reason="Application server closed",
                )
        self.flush_snapshot()
        try:
            with self.mutation_lock:
                self._release_runtime_ownership()
        finally:
            if self._runtime_fence_release is not None:
                self._runtime_fence_release()
                self._runtime_fence_release = None
        if self.universal_checkpoint_guard is not None:
            self.universal_checkpoint_guard.close()
        self.universal_store.close()
        if (
            self._owns_universal_checkpoint_signing_authority
            and self.universal_checkpoint_signing_authority is not None
        ):
            self.universal_checkpoint_signing_authority.store.close()


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8482)
    parser.add_argument(
        '--public-server-url',
        default=os.environ.get('ARCHHUB_PUBLIC_SERVER_URL'),
        help='stable numeric loopback gateway origin advertised to the browser',
    )
    parser.add_argument(
        '--supervisor-control-stdio',
        action='store_true',
        help='use inherited parent-child pipes for the gateway drain handshake',
    )
    parser.add_argument('--state-path', default=os.environ.get('ARCHHUB_STATE_PATH')
                        or str(default_state_path()))
    parser.add_argument('--fresh', action='store_true')
    parser.add_argument(
        '--universal-state-path',
        default=os.environ.get('ARCHHUB_UNIVERSAL_STATE_PATH'),
    )
    parser.add_argument(
        '--universal-checkpoint-path',
        default=os.environ.get('ARCHHUB_UNIVERSAL_CHECKPOINT_PATH'),
    )
    parser.add_argument(
        '--universal-checkpoint-authority-path',
        default=os.environ.get('ARCHHUB_UNIVERSAL_CHECKPOINT_AUTHORITY_PATH'),
    )
    parser.add_argument('--cloud-host', default='127.0.0.1')
    parser.add_argument('--cloud-port', type=int, default=8484)
    parser.add_argument(
        '--enable-universal-cloud-gateway',
        action='store_true',
        help=(
            'serve the graph-owned DPoP Universal cloud gateway over direct TLS'
        ),
    )
    parser.add_argument(
        '--cloud-resource-origin',
        default=os.environ.get('ARCHHUB_UNIVERSAL_CLOUD_RESOURCE_ORIGIN'),
        help='required HTTPS origin for the Universal cloud gateway',
    )
    parser.add_argument(
        '--cloud-tls-certificate-file',
        default=os.environ.get('ARCHHUB_UNIVERSAL_CLOUD_TLS_CERTIFICATE_FILE'),
        help='required direct-TLS certificate path when the cloud gateway is enabled',
    )
    parser.add_argument(
        '--cloud-tls-private-key-file',
        default=os.environ.get('ARCHHUB_UNIVERSAL_CLOUD_TLS_PRIVATE_KEY_FILE'),
        help='required direct-TLS private-key path when the cloud gateway is enabled',
    )
    parser.add_argument(
        '--machine-transport',
        action='store_true',
        help=(
            'make this ApplicationServer the single owner of the signed '
            'Universal machine transport'
        ),
    )
    parser.add_argument(
        '--machine-descriptor-path',
        default=os.environ.get('ARCHHUB_MACHINE_DESCRIPTOR_PATH', ''),
        help='optional signed machine-transport descriptor path',
    )
    args = parser.parse_args(argv)
    runtime_drain_coordinator = None
    if args.supervisor_control_stdio:
        from .runtime_supervisor import RuntimeDrainPipe
        runtime_drain_coordinator = RuntimeDrainPipe(
            reader=sys.stdin,
            writer=sys.stdout,
        ).begin_drain
    server = ApplicationServer(args.host, args.port, state_path=args.state_path,
                               fresh=args.fresh, live_watch=True,
                               public_server_url=args.public_server_url,
                               runtime_drain_coordinator=(
                                   runtime_drain_coordinator
                               ),
                               universal_state_path=args.universal_state_path,
                               universal_checkpoint_path=(
                                   args.universal_checkpoint_path
                               ),
                               universal_checkpoint_authority_path=(
                                   args.universal_checkpoint_authority_path
                               ),
                               browser_session_credentials=(
                                   BrowserCredentialVault(
                                       BrowserCredentialVault.default_path()
                                   ).load_or_create()
                               ),
                               cloud_host=args.cloud_host,
                               cloud_port=args.cloud_port,
                               enable_machine_transport=args.machine_transport,
                               enable_universal_cloud_gateway=(
                                   args.enable_universal_cloud_gateway
                               ),
                               cloud_resource_origin=args.cloud_resource_origin,
                               cloud_tls_certificate_file=(
                                   args.cloud_tls_certificate_file
                               ),
                               cloud_tls_private_key_file=(
                                   args.cloud_tls_private_key_file
                               ),
                                machine_descriptor_path=(
                                    args.machine_descriptor_path or None
                                ),
                                runtime_compliance_runner=(
                                    run_physical_runtime_compliance_court
                                    if args.machine_transport else None
                                )).start()
    # The unauthenticated root is deliberately denied. Hand the launcher the
    # one-use bootstrap URL instead of advertising an unusable bare address.
    print('Node-native ArchHub: %s' % server.bootstrap_url, flush=True)
    try:
        while (
            server.thread.is_alive()
            and not server._runtime_handoff_exit.wait(0.25)
        ):
            pass
    except KeyboardInterrupt:
        pass
    finally:
        if server.runtime_handoff_exit_requested:
            server.close(preserve_browser_session=True)
        else:
            server.close()


if __name__ == '__main__':
    main()
