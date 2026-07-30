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
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler
from http.cookies import SimpleCookie
from pathlib import Path
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
from .cell_protocols import with_relation_projection_scope
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
    read_universal_baboom_current_claimed_work,
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
from .cell_signing_authority import read_signing_key_descriptor
from .cell_external_graph_binding import bind_external_signing_authority


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
from .cell_cloud_routes import (
    CloudRouteDenied,
    find_cloud_route,
    resolve_cloud_route,
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
    transition_ownership,
    verify_ownership_authority,
)
from .cell_identity import (
    grant_authority_relationship,
    verify_authority_relationship,
)
from .cell_protocols import prepare_append_relation_member, read_relation
from .cell_state_machine import (
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
    InteractionProjectionExpired,
    _read_interactions_with_verified_protocol,
    execute_interaction,
    read_interaction,
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
_INTERACTION_DELTA_FIELDS = (
    "revision",
    "selected",
    "selection",
    "selected_title",
    "focus",
    "obligations",
    "authorization",
    "catalog",
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
    "personal_wip_heads",
    "preview_revision",
    "published_revision",
    "shared_revision",
    "state",
    "theme",
    "theme_fields",
)


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

    choice_fields = {
        "connect_choices",
        "rewire_choices",
        "source_rewire_choices",
        "target_rewire_choices",
    }

    def structural_value(
        value: object, *, parent_field: str | None = None
    ) -> object:
        if isinstance(value, dict):
            return {
                key: structural_value(item, parent_field=key)
                for key, item in value.items()
                if key != "data-context"
                and not (parent_field in choice_fields and key == "label")
            }
        if isinstance(value, list):
            return [
                structural_value(item, parent_field=parent_field)
                for item in value
            ]
        return value

    def node_structure(node: dict[str, object]) -> dict[str, object]:
        return {
            key: structural_value(value, parent_field=key)
            for key, value in node.items()
            if key not in {"selected", "x", "y"}
        }

    def wire_structure(wire: dict[str, object]) -> dict[str, object]:
        return {
            key: structural_value(value, parent_field=key)
            for key, value in wire.items()
            if key not in {"selected", "context"}
        }

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
            }
            for node in projection["nodes"]
            if (
                str(node["id"]) not in previous_nodes
                or any(
                    previous_nodes[str(node["id"])].get(field)
                    != node.get(field)
                    for field in ("selected", "x", "y")
                )
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
            field: configuration.get(field)
            for field in _CONFIGURATION_DELTA_FIELDS
        },
    }
    delta.update({
        field: projection.get(field)
        for field in _INTERACTION_DELTA_FIELDS
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
        delta["topology_patch"] = {
            "node_order": [str(node["id"]) for node in projection["nodes"]],
            "wire_order": [wire_key(wire) for wire in projection["wires"]],
            "remove_nodes": sorted(set(previous_nodes) - set(next_nodes)),
            "remove_wires": sorted(set(previous_wires) - set(next_wires)),
            "upsert_nodes": [
                node for node in projection["nodes"]
                if previous_nodes.get(str(node["id"])) != node
            ],
            "upsert_wires": [
                wire for wire in projection["wires"]
                if previous_wires.get(wire_key(wire)) != wire
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


class ApplicationServer:
    def __init__(self, host='127.0.0.1', port=0, store=None, registry=None,
                 state_path=None, fresh=False, live_watch=False,
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
        self._browser_session_lock = threading.RLock()
        self._browser_canvas_projections: dict[
            str, _BrowserCanvasProjectionBinding
        ] = {}
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
        checkpoint_path = None
        if self.universal_state_path is not None:
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
                    if persisted_application:
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

        if self.universal_state_path is not None and guard is None:
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
        try:
            self._runtime_fence_release = _take_universal_runtime_fence(
                self.universal_store,
                self.universal_registry.application_root,
                universal_runtime_fence_lease,
            )
            self._claim_runtime_ownership()
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
                            'legacy_parallel_runtime': True,
                            'legacy_runtime_status': (
                                'migration-only; not product authority'
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
                            elif self.path == '/api/universal/theme-assign':
                                touched = assign_released_universal_theme(
                                    owner.universal_store,
                                    owner.universal_registry,
                                    body['subject'],
                                    body['revision'],
                                    authentication_context=binding.context)
                            elif self.path == '/api/universal/theme-audience':
                                created_root, touched = \
                                    assign_released_universal_theme_to_audience(
                                        owner.universal_store,
                                        owner.universal_registry,
                                        body['audience'],
                                        body['revision'],
                                        reason=str(body.get('reason', '')).strip(),
                                        authentication_context=binding.context)
                            elif self.path == '/api/universal/theme-follow-audience':
                                touched = follow_universal_theme_audience(
                                    owner.universal_store,
                                    owner.universal_registry,
                                    authentication_context=binding.context)
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
        with self._browser_session_lock:
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
        if len(candidates) > 1:
            raise AuthorizationDenied(
                "runtime Agent Session continuation is ambiguous"
            )
        return candidates[0] if candidates else None

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
        else:
            revision = self.universal_store.revision
        session_root = session.root_id
        with self._machine_agent_session_lock:
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
        """Admit one proven runtime Agent Session into app:workshop."""
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
        if participant_patch is None and workbench_patch is None:
            return
        replacements = {
            cell.id: cell
            for patch in (participant_patch, workbench_patch)
            if patch is not None
            for cell in patch.replace
        }
        self.universal_store.commit(
            snapshot.revision,
            create=tuple(
                cell
                for patch in (participant_patch, workbench_patch)
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
                return {
                    "agent_session": request_agent_session,
                    **self._workshop_cache,
                }
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
        return {"agent_session": request_agent_session, **projection}

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
            work, revision = read_universal_baboom_current_claimed_work(
                self.universal_store,
                self.universal_registry,
                agent_session_root=agent_session_root,
                authentication_context=context,
            )
            return {
                "agent_session": agent_session_root,
                "work": work,
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
                "server_url": self.url,
                "supported": True,
                "one_use_route": "POST /api/universal/browser-handoff",
                "agent_session": request_agent_session,
                "revision": self.universal_store.revision,
            }
        if method == "GET" and path == "/api/universal/deliberation":
            if set(body) != {"space", "limit"}:
                raise InvalidCell("deliberation read request shape is invalid")
            space_root = body["space"]
            limit = body["limit"]
            if (
                type(space_root) is not str
                or type(limit) is not int
                or not 1 <= limit <= 500
            ):
                raise InvalidCell("deliberation read request values are invalid")
            if self.universal_checkpoint_guard is not None:
                self.universal_checkpoint_guard.require_healthy()
            self.require_universal_http_route(
                method, path, authentication_context=context
            )
            entries = read_authorized_deliberation_entries(
                self.universal_store.snapshot(),
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
            projected = []
            for entry in entries[-limit:]:
                payload = None
                if len(entry.reference_roots) == 1:
                    try:
                        payload = read_value_graph(
                            self.universal_store.snapshot(),
                            self.universal_registry.value_graph_protocol,
                            entry.reference_roots[0],
                        )
                    except InvalidCell:
                        payload = None
                projected.append({
                    "root": entry.root_id,
                    "actor": entry.actor_root,
                    "category_root": entry.category_root,
                    "summary": entry.content,
                    "reference_roots": list(entry.reference_roots),
                    "payload": payload,
                    "created_at": entry.created_at,
                    "sequence": entry.sequence,
                    "idempotency_key": entry.idempotency_key,
                })
            return {
                "ok": True,
                "application": self.universal_registry.application_root,
                "space": space_root,
                "entries": projected,
                "revision": self.universal_store.revision,
            }
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
                    "server_url": self.url,
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
                if not direct and request.get("session") != {}:
                    raise AuthorizationDenied(
                        "generic deliberation append requires a founder or explicitly admitted session"
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
                        authentication_context=context,
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
            if "projection" in body:
                if body["projection"] != "index":
                    raise InvalidCell("work transition projection is invalid")
                compact_projection = True
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
            with self._browser_session_lock:
                self._browser_canvas_projections[
                    binding.session_root
                ] = _BrowserCanvasProjectionBinding(
                    binding.session_root,
                    binding.subject_root,
                    binding.view_root,
                    binding.tenant_root,
                    binding.assurance_root,
                    projection,
                )
            return projection

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
    def bootstrap_url(self):
        token = self.browser_bootstrap_token
        if not token:
            return self.url + '/'
        return self.url + '/?bootstrap=' + token

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
    server = ApplicationServer(args.host, args.port, state_path=args.state_path,
                               fresh=args.fresh, live_watch=True,
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
                               )).start()
    # The unauthenticated root is deliberately denied. Hand the launcher the
    # one-use bootstrap URL instead of advertising an unusable bare address.
    print('Node-native ArchHub: %s' % server.bootstrap_url, flush=True)
    try:
        server.thread.join()
    except KeyboardInterrupt:
        pass
    finally:
        server.close()


if __name__ == '__main__':
    main()
