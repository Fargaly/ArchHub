from __future__ import annotations

import hashlib
import json
import pytest
import uuid
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from nodelang.cell_attention import active_focus, open_attention_protocol
import nodelang.clean_browser_authority as clean_browser_authority
import nodelang.unified_authority as unified_authority_module
from nodelang.cell_protocols import read_relation
from nodelang.application_server import ApplicationServer
from nodelang.cell_secret_keys import MemorySigningKeyProvider
from nodelang.clean_browser_authority import issue_clean_browser_session
from nodelang.clean_visual_projection import project_clean_visual_canvas
from nodelang.clean_runtime_bootstrap import provision_clean_runtime
from nodelang.runtime_caller_capability import WindowsDpapiCallerKeyStore
from nodelang.unified_application_lens import (
    project_unified_scope,
    scope_lens_payload,
)
from nodelang.unified_authority import (
    read_definition,
    revise_definition,
    revise_instance,
)


def _map_source() -> bytes:
    return json.dumps(
        [
            {
                "key": "brain",
                "title": "Brain and Memory",
                "nodes": [
                    {
                        "id": "brain_attention",
                        "cat": "behavior",
                        "title": "Persistent Attention",
                        "sub": "Keep accepted work visible across sessions",
                        "status": "partial",
                        "params": [
                            {"k": "mode", "v": "steady"},
                            {"k": "window_ms", "v": "150"},
                        ],
                        "evidence_ref": "court:clean-server-visual-projection",
                        "authority_source": "founder",
                    },
                    {
                        "id": "brain_focus",
                        "cat": "logic",
                        "title": "Focus Contract",
                        "sub": "Carry one live focus through the graph",
                        "status": "partial",
                        "params": [
                            {"k": "selection_policy", "v": "exact"},
                        ],
                        "evidence_ref": "court:clean-server-visual-projection",
                        "authority_source": "founder",
                    },
                ],
                "wires": [
                    ["brain_attention", "brain_focus"],
                ],
                "cross": [
                    {
                        "from": "brain_attention",
                        "to_domain": "ui",
                        "why": "Attention must stay visible in the interface",
                    }
                ],
            },
            {
                "key": "ui",
                "title": "UI and Design System",
                "nodes": [
                    {
                        "id": "ui_properties",
                        "cat": "interface",
                        "title": "Properties Rail",
                        "sub": "Edit graph-held parameters",
                        "status": "partial",
                        "params": [
                            {"k": "tabs", "v": ["Use", "Build", "Govern"]},
                        ],
                        "evidence_ref": "court:clean-server-visual-projection",
                        "authority_source": "founder",
                    }
                ],
                "wires": [],
                "cross": [],
            },
        ],
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


def _provision_clean_runtime(tmp_path):
    root = tmp_path / "clean-server-visual-projection"
    provider = MemorySigningKeyProvider(
        "archhub.unified.bootstrap",
        b"clean-server-visual-projection" + b"0" * 3,
    )
    caller_keys = WindowsDpapiCallerKeyStore(root / "callers.dpapi.json")
    specification = (Path(__file__).parents[1] / "SPEC.md").read_bytes()
    grand_map = _map_source()
    built = provision_clean_runtime(
        root,
        provider,
        caller_keys,
        caller_key_id="founder.bootstrap",
        specification_source=specification,
        specification_sha256=hashlib.sha256(specification).hexdigest(),
        grand_map_source=grand_map,
        grand_map_sha256=hashlib.sha256(grand_map).hexdigest(),
    )
    return built, provider


def _start_clean_server(built, provider):
    return ApplicationServer.from_unified_authority(
        built.location.authority,
        browser_authority=built.browser,
        scope_caller=built.caller,
        scope_root=built.grand_map.root_id,
        authority_key_provider=provider,
    ).start()


def _issue_clean_session(built, *, token: str, csrf: str):
    return issue_clean_browser_session(
        built.location.authority,
        built.browser,
        token=token,
        csrf_token=csrf,
        lifetime_seconds=120.0,
        caller=built.caller,
        command_id=str(uuid.uuid4()),
    )


def _issue_visual_session(built, *, prefix: str = "clean-visual"):
    token = f"{prefix}-token-{uuid.uuid4().hex}"
    csrf = f"{prefix}-csrf-{uuid.uuid4().hex}"
    return _issue_clean_session(built, token=token, csrf=csrf)


class _EphemeralCaller:
    def __init__(self, actor_root: str, session_root: str, private_key):
        self.actor_root = actor_root
        self.session_root = session_root
        self.public_key = private_key.public_key().public_bytes(
            serialization.Encoding.Raw,
            serialization.PublicFormat.Raw,
        )
        self._private_key = private_key

    def sign(self, payload: bytes) -> bytes:
        return self._private_key.sign(payload)


def _second_admitted_caller(built):
    private_key = Ed25519PrivateKey.generate()
    session_root = unified_authority_module.enroll_session(
        built.location.authority,
        "Clean visual primitive second caller",
        private_key.public_key().public_bytes(
            serialization.Encoding.Raw,
            serialization.PublicFormat.Raw,
        ),
        session_container_root=unified_authority_module.composition_root(
            built.location.authority,
            "Agent Sessions",
            caller=built.caller,
        ),
        caller=built.caller,
        command_id=str(uuid.uuid4()),
    ).root_id
    return _EphemeralCaller(
        built.location.authority.manifest.principal_root,
        session_root,
        private_key,
    )


def _plain(value):
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(item) for item in value]
    return value


def _project_scope_payload(built, scope_root=None):
    root = built.grand_map.root_id if scope_root is None else scope_root
    lens = project_unified_scope(
        built.location.authority,
        root,
        caller=built.caller,
    )
    return scope_lens_payload(lens)


def _project_scope_lens(built, scope_root=None, *, view_root=None):
    root = built.grand_map.root_id if scope_root is None else scope_root
    return project_unified_scope(
        built.location.authority,
        root,
        caller=built.caller,
        view_root=view_root,
    )


def _project_current_visual_for_session(built, session, scope_root=None):
    lens = scope_lens_payload(
        _project_scope_lens(built, scope_root, view_root=session.view_root)
    )
    before = built.location.authority.store.snapshot()
    projected = project_clean_visual_canvas(
        built.location.authority,
        built.visual,
        lens,
        caller=built.caller,
        session_root=session.root_id,
        subject_root=session.subject_root,
    )
    after = built.location.authority.store.snapshot()
    return projected, lens, before, after


def _project_current_visual(built, scope_root=None):
    session = _issue_visual_session(built)
    return _project_current_visual_for_session(
        built,
        session,
        scope_root=scope_root,
    )


def _focus_command():
    return getattr(clean_browser_authority, "revise_clean_browser_focus", None)


def _projected_node_by_root(projected, root_id: str):
    return next(node for node in projected["nodes"] if node["id"] == root_id)


def _projected_property_row(projected, label: str):
    return next(row for row in projected["properties"] if row["label"] == label)


def _generic_relation_revision_command():
    return getattr(unified_authority_module, "revise_relation_node", None)


def _relation_revision_members(snapshot, relation_root: str):
    return [
        {
            "incidence_id": member.incidence_id,
            "role_root": member.role_id,
            "participant_root": member.participant_id,
        }
        for member in read_relation(snapshot, relation_root, budget=256)
    ]


def _revise_scope_definition(
    built,
    definition_root: str,
    *,
    version_suffix: str,
    parameters=None,
    interfaces=None,
    presentation=None,
):
    current = read_definition(
        built.location.authority,
        definition_root,
        caller=built.caller,
    )
    return revise_definition(
        built.location.authority,
        definition_root,
        current.name,
        caller=built.caller,
        command_id=str(uuid.uuid4()),
        version=current.version + version_suffix,
        lifecycle="wip",
        defaults=_plain(current.contracts["defaults"]),
        parameters=(
            _plain(current.contracts["parameters"])
            if parameters is None else _plain(parameters)
        ),
        interfaces=(
            _plain(current.contracts["interfaces"])
            if interfaces is None else _plain(interfaces)
        ),
        rules=_plain(current.contracts["rules"]),
        presentation=(
            _plain(current.contracts["presentation"])
            if presentation is None else _plain(presentation)
        ),
        courts=_plain(current.contracts["courts"]),
        provenance=_plain(current.contracts["provenance"]),
    )


def _json(url, path, payload=None, *, token: str):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(
        url + path,
        data=data,
        headers={
            "Content-Type": "application/json",
            "X-ArchHub-Session": token,
        },
        method="GET" if payload is None else "POST",
    )
    try:
        with urlopen(request, timeout=30) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        return error.code, json.loads(error.read().decode("utf-8"))


def test_clean_server_canvas_uses_existing_graph_visual_descriptors(tmp_path):
    built, provider = _provision_clean_runtime(tmp_path)
    server = _start_clean_server(built, provider)
    try:
        issued = _issue_clean_session(
            built,
            token="clean-visual-token",
            csrf="clean-visual-csrf",
        )
        status, canvas = _json(
            server.url,
            "/api/universal/canvas",
            token="clean-visual-token",
        )
        assert status == 200
        assert canvas["graph_id"] == built.location.authority.manifest.graph_id
        assert canvas["root"] == built.grand_map.root_id
        assert canvas["revision"] == built.location.authority.store.revision
        assert canvas["authorization"]["browser_sessions"] == [
            {"root": issued.root_id}
        ]
        assert canvas.get("toolbar_descriptor"), (
            "clean canvas must expose the existing toolbar graph descriptor"
        )
        assert canvas.get("canvas_heading_descriptor"), (
            "clean canvas must expose the existing heading graph descriptor"
        )
        assert canvas.get("library", {}).get("descriptor"), (
            "clean canvas must expose the existing library shell descriptor"
        )
        assert canvas.get("primitive", {}).get("descriptor"), (
            "clean canvas must expose the existing primitive descriptor"
        )
        assert canvas.get("catalog_sections"), (
            "clean canvas must expose non-empty library sections"
        )
        assert all(
            section.get("descriptor") for section in canvas["catalog_sections"]
        ), "every clean library section must carry a graph descriptor"
        assert canvas.get("inspector", {}).get("shell_descriptor"), (
            "clean canvas must expose the existing inspector shell descriptor"
        )
        assert canvas.get("inspector", {}).get("header_descriptor"), (
            "clean canvas must expose the existing inspector header descriptor"
        )
        assert canvas.get("inspector", {}).get("controls_descriptor"), (
            "clean canvas must expose the existing inspector controls descriptor"
        )
        assert all(
            node.get("card_descriptor") for node in canvas["nodes"]
        ), "every clean canvas node must carry a graph card descriptor"
        assert any(node["ports"] for node in canvas["nodes"])
        assert all(
            port.get("descriptor")
            for node in canvas["nodes"]
            for port in node["ports"]
        ), "every clean canvas port must carry a graph port descriptor"
        assert all(
            item.get("descriptor") for item in canvas["catalog"]
        ), "every clean catalogue item must carry a graph descriptor"
    finally:
        server.close()
        built.location.authority.store.close()


def test_clean_server_scope_interaction_enters_child_scope_with_same_visual_contract(
    tmp_path,
):
    built, provider = _provision_clean_runtime(tmp_path)
    server = _start_clean_server(built, provider)
    try:
        _issue_clean_session(
            built,
            token="clean-scope-token",
            csrf="clean-scope-csrf",
        )
        status, canvas = _json(
            server.url,
            "/api/universal/canvas",
            token="clean-scope-token",
        )
        assert status == 200
        target = next(node for node in canvas["nodes"] if node["openable"])
        binding = next(
            item
            for item in canvas["interaction_projection"]["bindings"]
            if item["control"] == target["id"]
        )
        status, entered = _json(
            server.url,
            "/api/universal/interaction",
            {
                "interaction": binding["interaction"],
                "control": binding["control"],
                "event": binding["event"],
                "revision": canvas["interaction_projection"]["revision"],
                "projection_mode": "topology-delta-v1",
            },
            token="clean-scope-token",
        )
        assert status == 200
        assert entered["root"] == target["id"], (
            "clean scope interaction must return the selected child scope"
        )
        assert entered["scope"]["current"] == target["id"]
        assert entered.get("toolbar_descriptor")
        assert entered.get("canvas_heading_descriptor")
        assert entered.get("library", {}).get("descriptor")
        assert entered.get("inspector", {}).get("shell_descriptor")
        assert all(
            node.get("card_descriptor") for node in entered["nodes"]
        ), "entered clean scope must keep card descriptors"
    finally:
        server.close()
        built.location.authority.store.close()


@pytest.mark.xfail(
    strict=True,
    reason=(
        "session-persistent clean browser scope is frozen until the visual "
        "projection is graph-native and admitted"
    ),
)
def test_clean_server_scope_entry_persists_for_the_same_browser_session(tmp_path):
    built, provider = _provision_clean_runtime(tmp_path)
    server = _start_clean_server(built, provider)
    try:
        _issue_clean_session(
            built,
            token="clean-persist-token",
            csrf="clean-persist-csrf",
        )
        status, canvas = _json(
            server.url,
            "/api/universal/canvas",
            token="clean-persist-token",
        )
        assert status == 200
        target = next(node for node in canvas["nodes"] if node["openable"])
        binding = next(
            item
            for item in canvas["interaction_projection"]["bindings"]
            if item["control"] == target["id"]
        )
        status, entered = _json(
            server.url,
            "/api/universal/interaction",
            {
                "interaction": binding["interaction"],
                "control": binding["control"],
                "event": binding["event"],
                "revision": canvas["interaction_projection"]["revision"],
                "projection_mode": "topology-delta-v1",
            },
            token="clean-persist-token",
        )
        assert status == 200
        assert entered["root"] == target["id"]
        status, reopened = _json(
            server.url,
            "/api/universal/canvas",
            token="clean-persist-token",
        )
        assert status == 200
        assert reopened["root"] == target["id"], (
            "clean browser session must reopen on the entered child scope"
        )
        assert reopened["scope"]["current"] == target["id"]
        assert reopened.get("toolbar_descriptor")
        assert reopened.get("canvas_heading_descriptor")
    finally:
        server.close()
        built.location.authority.store.close()


def test_clean_visual_projection_uses_graph_held_panels_properties_and_catalogue_contracts(
    tmp_path,
):
    built, _provider = _provision_clean_runtime(tmp_path)
    try:
        before, lens_before, _snapshot_before, _snapshot_after = _project_current_visual(
            built
        )
        definition_root = lens_before["nodes"][0]["definition_root"]
        assert isinstance(definition_root, str)
        revised_parameters = {
            "key": {
                "editor": "choice",
                "options": ["brain", "ui"],
                "type": "text",
            },
            "title": {
                "editor": "multiline",
                "minimum_length": 3,
                "type": "text",
            },
        }
        revised_interfaces = {
            "capability": {
                "direction": "output",
                "multiple": True,
            }
        }
        revised_presentation = {
            "label": "Domain composition",
            "panels": ["Overview", "Govern", "Wires"],
        }
        _revise_scope_definition(
            built,
            definition_root,
            version_suffix="-visual-contracts",
            parameters=revised_parameters,
            interfaces=revised_interfaces,
            presentation=revised_presentation,
        )
        after, lens_after, _, _ = _project_current_visual(built)
        panels = after["inspector"]["presentation"]["panels"]
        assert [panel["label"] for panel in panels] == revised_presentation["panels"]
        assert [panel["label"] for panel in before["inspector"]["presentation"]["panels"]] != [
            panel["label"] for panel in panels
        ]
        row = after["properties"][0]
        source_row = lens_after["nodes"][0]["properties"][0]
        assert row["editor"] == source_row["editor"] == "choice"
        assert row["constraints"] == source_row["constraints"] == {
            "options": ["brain", "ui"],
            "type": "text",
        }
        assert row["editable"] is True
        item = next(
            candidate
            for candidate in after["catalog"]
            if candidate["id"] == definition_root
        )
        source_item = next(
            candidate
            for candidate in lens_after["catalogue"]
            if candidate["root_id"] == definition_root
        )
        assert item["parameters"] == source_item["parameters"]
        assert item["interfaces"] == source_item["interfaces"]
        assert item["presentation"] == source_item["presentation"]
    finally:
        built.location.authority.store.close()


def test_clean_visual_projection_removes_deleted_panels_without_python_fallback(
    tmp_path,
):
    built, _provider = _provision_clean_runtime(tmp_path)
    try:
        initial_lens = _project_scope_payload(built)
        definition_root = initial_lens["nodes"][0]["definition_root"]
        assert isinstance(definition_root, str)
        _revise_scope_definition(
            built,
            definition_root,
            version_suffix="-panel-added",
            presentation={"label": "Domain composition", "panels": ["Overview"]},
        )
        _revise_scope_definition(
            built,
            definition_root,
            version_suffix="-panel-deleted",
            presentation={},
        )
        projected, _lens, _before, _after = _project_current_visual(built)
        assert projected["inspector"]["presentation"]["panels"] == []
        assert projected["inspector"]["shell_descriptor"] == []
    finally:
        built.location.authority.store.close()


def test_clean_visual_projection_rewiring_changes_target(tmp_path):
    built, _provider = _provision_clean_runtime(tmp_path)
    try:
        lens = _project_scope_payload(built)
        assert len(lens["nodes"]) >= 2
        source_root = lens["nodes"][0]["root_id"]
        target_root = lens["nodes"][1]["root_id"]
        rewired_target = source_root
        created = unified_authority_module.create_relation_node(
            built.location.authority,
            (("source", source_root), ("target", target_root)),
            scope_root=built.grand_map.root_id,
            caller=built.caller,
            command_id=str(uuid.uuid4()),
            properties={"connection": "selection"},
        )
        snapshot_before = built.location.authority.store.snapshot()
        command = _generic_relation_revision_command()
        assert command is not None
        members = _relation_revision_members(snapshot_before, created.root_id)
        target_role_root = built.location.authority.role("target")
        revised_members = [
            {
                **member,
                "participant_root": rewired_target,
            }
            if member["role_root"] == target_role_root else dict(member)
            for member in members
        ]
        result = command(
            built.location.authority,
            created.root_id,
            revised_members,
            scope_root=built.grand_map.root_id,
            caller=built.caller,
            command_id=str(uuid.uuid4()),
            expected_revision=snapshot_before.revision,
        )
        snapshot_after = built.location.authority.store.snapshot()
        projected = unified_authority_module.read_relation_node(
            built.location.authority,
            created.root_id,
            scope_root=built.grand_map.root_id,
            caller=built.caller,
        )
        members_after = read_relation(snapshot_after, created.root_id, budget=256)
        assert result.root_id == created.root_id
        assert result.revision == snapshot_before.revision + 1
        assert not result.replayed
        assert tuple(member.incidence_id for member in members_after) == tuple(
            member["incidence_id"] for member in revised_members
        )
        assert dict(projected.participants)["source"] == source_root
        assert dict(projected.participants)["target"] == rewired_target
        assert dict(projected.properties)["connection"] == "selection"
        target_incidence = next(
            member["incidence_id"]
            for member in revised_members
            if member["role_root"] == target_role_root
        )
        updated_target = next(
            member for member in members_after if member.incidence_id == target_incidence
        )
        assert updated_target.participant_id == rewired_target
    finally:
        built.location.authority.store.close()


def test_clean_visual_projection_adds_zero_cells_and_preserves_root_and_revision(
    tmp_path,
):
    built, _provider = _provision_clean_runtime(tmp_path)
    try:
        projected, lens, snapshot_before, snapshot_after = _project_current_visual(
            built
        )
        assert snapshot_after.revision == snapshot_before.revision
        assert set(snapshot_after.cells) == set(snapshot_before.cells)
        assert projected["graph_id"] == lens["graph_id"]
        assert projected["revision"] == lens["revision"]
        assert projected["root"] == lens["scope_root"]
    finally:
        built.location.authority.store.close()


def test_clean_visual_projection_requires_generic_relation_revision_for_selection(
    tmp_path,
):
    built, _provider = _provision_clean_runtime(tmp_path)
    try:
        issued = _issue_visual_session(built, prefix="selection-presence")
        projected, lens_payload, before_focus, _after = _project_current_visual_for_session(
            built,
            issued,
        )
        assert projected["graph_id"] == lens_payload["graph_id"]
        assert projected["root"] == lens_payload["scope_root"]
        assert projected["revision"] == lens_payload["revision"]
        assert len(lens_payload["nodes"]) >= 2
        second = lens_payload["nodes"][1]["root_id"]
        assert lens_payload["selected_root"] is None
        assert lens_payload["selected_roots"] == []
        assert projected.get("selected") is None
        assert projected.get("selection") == []
        assert projected.get("properties") == []
        command = _focus_command()
        assert callable(command)
        focused = command(
            built.location.authority,
            built.browser,
            issued.root_id,
            scope_root=built.grand_map.root_id,
            selected_roots=(second,),
            primary_root=second,
            caller=built.caller,
            command_id=str(uuid.uuid4()),
            expected_revision=before_focus.revision,
        )
        protocol = open_attention_protocol(built.location.authority.store.snapshot())
        active = active_focus(
            built.location.authority.store.snapshot(),
            protocol,
            session_root=issued.view_root,
        )
        assert active is not None
        assert active.root_id == focused.root_id
        assert active.primary_root == second
        assert active.selected_roots == (second,)
        projected_after, lens_after, _before_after, after_focus = _project_current_visual_for_session(
            built,
            issued,
        )
        assert after_focus.revision == focused.revision
        assert lens_after["selected_root"] == second
        assert lens_after["selected_roots"] == [second]
        assert projected_after["selected"] == second
        assert projected_after["selection"] == [second]
        assert projected_after["focus"] == second
        selected_node = _projected_node_by_root(projected_after, second)
        assert selected_node["selected"] is True
        assert selected_node["focused"] is True
        assert projected_after["selected_title"] == selected_node["label"]
        expected_labels = [
            row["name"]
            for row in next(
                node for node in lens_after["nodes"] if node["root_id"] == second
            )["properties"]
        ]
        assert [row["label"] for row in projected_after["properties"]] == expected_labels
    finally:
        built.location.authority.store.close()


@pytest.mark.skipif(
    _generic_relation_revision_command() is None,
    reason="blocked by missing generic public relation/view-session revision command",
)
def test_clean_visual_projection_generic_relation_revision_adds_removes_reorders_and_replays(
    tmp_path,
):
    built, _provider = _provision_clean_runtime(tmp_path)
    try:
        lens_before = _project_scope_payload(built)
        assert len(lens_before["nodes"]) >= 2
        command = _generic_relation_revision_command()
        if command is None:
            pytest.skip(
                "blocked by exact missing symbol unified_authority.revise_relation_node"
            )
        first = lens_before["nodes"][0]["root_id"]
        second = lens_before["nodes"][1]["root_id"]
        created = unified_authority_module.create_relation_node(
            built.location.authority,
            (("source", first), ("target", second)),
            scope_root=built.grand_map.root_id,
            caller=built.caller,
            command_id=str(uuid.uuid4()),
            properties={"connection": "selection"},
        )
        snapshot_before = built.location.authority.store.snapshot()
        members = _relation_revision_members(snapshot_before, created.root_id)
        assert len(members) == 4
        command_id = str(uuid.uuid4())
        protocol_role_root = built.location.authority.role("conforms-to")
        source_role_root = built.location.authority.role("source")
        target_role_root = built.location.authority.role("target")
        property_role_root = built.location.authority.role("property")
        object_role_root = built.location.authority.role("object")
        protocol_member = next(
            member for member in members if member["role_root"] == protocol_role_root
        )
        source_member = next(
            member for member in members if member["role_root"] == source_role_root
        )
        target_member = next(
            member for member in members if member["role_root"] == target_role_root
        )
        property_member = next(
            member for member in members if member["role_root"] == property_role_root
        )
        sibling_scope_root = unified_authority_module.composition_root(
            built.location.authority,
            "Workshop",
            caller=built.caller,
        )
        prior_head_members = unified_authority_module.relation_members(
            snapshot_before,
            built.location.authority.manifest.head_index_root,
        )
        prior_head_root = next(
            member.participant_id
            for member in prior_head_members
            if member.role_id == built.location.authority.role("current-head")
        )
        revised_members = [
            dict(protocol_member),
            {
                **target_member,
                "participant_root": first,
            },
            {
                "role_root": object_role_root,
                "participant_root": second,
            },
            dict(source_member),
        ]
        result = command(
            built.location.authority,
            created.root_id,
            revised_members,
            scope_root=built.grand_map.root_id,
            caller=built.caller,
            command_id=command_id,
            expected_revision=snapshot_before.revision,
        )
        snapshot_after = built.location.authority.store.snapshot()
        projected = unified_authority_module.read_relation_node(
            built.location.authority,
            created.root_id,
            scope_root=built.grand_map.root_id,
            caller=built.caller,
        )
        members_after = read_relation(snapshot_after, created.root_id, budget=256)
        assert result.root_id == created.root_id
        assert result.revision == snapshot_before.revision + 1
        assert ("source", first) in projected.participants
        assert ("target", first) in projected.participants
        assert ("object", second) in projected.participants
        assert dict(projected.properties) == {}
        assert tuple(member.role_id for member in members_after) == (
            protocol_role_root,
            target_role_root,
            object_role_root,
            source_role_root,
        )
        assert target_member["incidence_id"] in {
            member.incidence_id for member in members_after
        }
        assert property_member["incidence_id"] not in {
            member.incidence_id for member in members_after
        }
        old_ids = {
            member["incidence_id"] for member in members if member["incidence_id"] is not None
        }
        assert any(
            member.incidence_id not in old_ids
            and member.role_id == object_role_root
            and member.participant_id == second
            for member in members_after
        )
        history = read_relation(
            snapshot_after,
            built.location.authority.manifest.history_root,
            budget=256,
        )
        assert any(
            member.role_id == built.location.authority.role("receipt")
            and member.participant_id == result.receipt_root
            for member in history
        )
        receipt = unified_authority_module._receipt_projection(
            built.location.authority,
            built.location.authority.store.at(result.revision),
            result.receipt_root,
        )
        assert receipt.result_root == created.root_id
        assert receipt.result_revision == result.revision
        assert receipt.root_id == result.receipt_root
        next_head_members = unified_authority_module.relation_members(
            snapshot_after,
            built.location.authority.manifest.head_index_root,
        )
        next_head_root = next(
            member.participant_id
            for member in next_head_members
            if member.role_id == built.location.authority.role("current-head")
        )
        assert next_head_root != prior_head_root
        next_head_relation = unified_authority_module.relation_members(
            snapshot_after,
            next_head_root,
        )
        parent_heads = tuple(
            member.participant_id
            for member in next_head_relation
            if member.role_id == built.location.authority.role("parent-head")
        )
        assert parent_heads == (prior_head_root,)
        unified_authority_module.audit_authority_history(
            built.location.authority
        )
        replay = command(
            built.location.authority,
            created.root_id,
            revised_members,
            scope_root=built.grand_map.root_id,
            caller=built.caller,
            command_id=command_id,
            expected_revision=snapshot_before.revision,
        )
        assert replay.root_id == result.root_id
        assert replay.revision == result.revision
        assert replay.replayed
        assert built.location.authority.store.snapshot().revision == snapshot_after.revision
        with pytest.raises(unified_authority_module.InvalidCell):
            command(
                built.location.authority,
                created.root_id,
                [
                    {
                        **protocol_member,
                        "participant_root": first,
                    },
                    dict(target_member),
                    dict(source_member),
                ],
                scope_root=built.grand_map.root_id,
                caller=built.caller,
                command_id=str(uuid.uuid4()),
                expected_revision=snapshot_after.revision,
            )
        with pytest.raises(unified_authority_module.InvalidCell):
            command(
                built.location.authority,
                created.root_id,
                revised_members,
                scope_root=built.grand_map.root_id,
                caller=built.caller,
                command_id=str(uuid.uuid4()),
                expected_revision=snapshot_before.revision,
            )
        with pytest.raises(unified_authority_module.InvalidCell):
            command(
                built.location.authority,
                created.root_id,
                [
                    dict(protocol_member),
                    {
                        **target_member,
                        "participant_root": second,
                    },
                    {
                        "role_root": object_role_root,
                        "participant_root": first,
                    },
                    dict(source_member),
                ],
                scope_root=built.grand_map.root_id,
                caller=built.caller,
                command_id=command_id,
                expected_revision=snapshot_before.revision,
            )
        missing_session_caller = _EphemeralCaller(
            built.caller.actor_root,
            str(uuid.uuid4()),
            Ed25519PrivateKey.generate(),
        )
        with pytest.raises(unified_authority_module.InvalidCell):
            command(
                built.location.authority,
                created.root_id,
                revised_members,
                scope_root=built.grand_map.root_id,
                caller=missing_session_caller,
                command_id=str(uuid.uuid4()),
                expected_revision=snapshot_after.revision,
            )
        sibling_command_id = str(uuid.uuid4())
        with pytest.raises(
            unified_authority_module.AuthorizationDenied
        ) as denied_scope:
            command(
                built.location.authority,
                created.root_id,
                revised_members,
                scope_root=sibling_scope_root,
                caller=built.caller,
                command_id=sibling_command_id,
                expected_revision=snapshot_after.revision,
            )
        denied_snapshot = built.location.authority.store.at(denied_scope.value.revision)
        denied_receipt = unified_authority_module._receipt_projection(
            built.location.authority,
            denied_snapshot,
            denied_scope.value.receipt_root,
        )
        denied_command = unified_authority_module._command_projection(
            built.location.authority,
            denied_snapshot,
            sibling_command_id,
        )
        assert denied_receipt.decision == "deny"
        assert denied_receipt.root_id == denied_scope.value.receipt_root
        assert denied_receipt.result_root == created.root_id
        assert denied_receipt.result_revision == denied_scope.value.revision
        assert denied_receipt.idempotency_key == sibling_command_id
        assert denied_command.object_root == created.root_id
        assert denied_command.scope_root == sibling_scope_root
        assert built.location.authority.store.snapshot().revision == denied_scope.value.revision
        closed_relation_root = built.location.authority.manifest.head_index_root
        closed_snapshot = built.location.authority.store.snapshot()
        closed_members = _relation_revision_members(
            closed_snapshot,
            closed_relation_root,
        )
        with pytest.raises(unified_authority_module.InvalidCell):
            command(
                built.location.authority,
                closed_relation_root,
                [
                    *closed_members,
                    {
                        "role_root": object_role_root,
                        "participant_root": first,
                    },
                ],
                scope_root=built.location.authority.manifest.application_root,
                caller=built.caller,
                command_id=str(uuid.uuid4()),
                expected_revision=closed_snapshot.revision,
            )
        second_caller = _second_admitted_caller(built)
        revoke_result = unified_authority_module.revoke_session(
            built.location.authority,
            second_caller.session_root,
            caller=built.caller,
            command_id=str(uuid.uuid4()),
        )
        post_revoke_snapshot = built.location.authority.store.snapshot()
        assert revoke_result.revision == post_revoke_snapshot.revision
        with pytest.raises(
            unified_authority_module.InvalidCell,
            match="caller credential binding is invalid or revoked",
        ):
            command(
                built.location.authority,
                created.root_id,
                revised_members,
                scope_root=built.grand_map.root_id,
                caller=second_caller,
                command_id=str(uuid.uuid4()),
                expected_revision=post_revoke_snapshot.revision,
            )
        assert revoke_result.revision <= post_revoke_snapshot.revision
    finally:
        built.location.authority.store.close()


def test_clean_visual_projection_requires_graph_held_node_presentation_contract(
    tmp_path,
):
    built, _provider = _provision_clean_runtime(tmp_path)
    try:
        before, lens_before, _snapshot_before, _snapshot_after = _project_current_visual(
            built
        )
        definition_root = lens_before["nodes"][0]["definition_root"]
        node_root = lens_before["nodes"][0]["root_id"]
        assert isinstance(definition_root, str)
        revised_presentation = {
            "label": "Brain Governor",
            "icon": "cpu",
            "color": "#00ffaa",
            "token": "graph/presentation/brain-governor",
            "position": {"x": 640, "y": 320},
            "panels": ["Use", "Govern"],
        }
        _revise_scope_definition(
            built,
            definition_root,
            version_suffix="-node-presentation",
            presentation=revised_presentation,
        )
        after, lens_after, _snapshot_before, _snapshot_after = _project_current_visual(
            built
        )
        before_node = _projected_node_by_root(before, node_root)
        after_node = _projected_node_by_root(after, node_root)
        assert after["graph_id"] == lens_after["graph_id"] == before["graph_id"]
        assert after["root"] == lens_after["scope_root"] == before["root"]
        assert after["revision"] == lens_after["revision"]
        assert after["revision"] > before["revision"]
        assert after_node["label"] == revised_presentation["label"]
        assert before_node["label"] != after_node["label"]
        missing = [
            name for name in (
                "icon",
                "color_token",
                "resolved_color",
                "position",
                "presentation_root",
                "icon_root",
                "color_token_root",
                "position_root",
            )
            if name not in after_node
        ]
        if missing:
            pytest.fail(
                "clean visual node-presentation court remains red: public "
                "definition revision changed the visible label, but the visual "
                "projection still has no graph-held %s output" % ", ".join(missing)
            )
        assert after_node["icon"] == revised_presentation["icon"]
        assert after_node["color_token"] == revised_presentation["token"]
        assert after_node["resolved_color"] == revised_presentation["color"]
        assert after_node["position"] == revised_presentation["position"]
        snapshot = built.location.authority.store.snapshot()
        for root in (
            after_node["presentation_root"],
            after_node["icon_root"],
            after_node["color_token_root"],
            after_node["position_root"],
        ):
            assert root in snapshot.cells
    finally:
        built.location.authority.store.close()


def test_clean_visual_projection_requires_public_interface_metadata_for_visible_sockets(
    tmp_path,
):
    built, _provider = _provision_clean_runtime(tmp_path)
    try:
        projected, lens_payload, _before, _after = _project_current_visual(built)
        snapshot = built.location.authority.store.snapshot()
        lens_ports = [
            (node["root_id"], port)
            for node in lens_payload["nodes"]
            for port in node["ports"]
        ]
        projected_ports = [
            (node["id"], port)
            for node in projected["nodes"]
            for port in node["ports"]
        ]
        assert lens_ports
        assert projected_ports
        assert len(projected_ports) == len(lens_ports)
        lens_index = {
            (
                owner_root,
                port["relation_root"],
                port["participant_role"],
                tuple(port["other_roots"]),
            ): port
            for owner_root, port in lens_ports
        }
        projected_index = {
            (
                owner_root,
                port["relation_root"],
                port["participant_role"],
                tuple(port["other_roots"]),
            ): port
            for owner_root, port in projected_ports
        }
        assert set(projected_index) == set(lens_index)
        for key, lens_port in lens_index.items():
            projected_port = projected_index[key]
            assert projected_port["relation_root"] == lens_port["relation_root"]
            assert projected_port["participant_role"] == lens_port["participant_role"]
            assert projected_port["other_roots"] == list(lens_port["other_roots"])
        required = (
            "interface_root",
            "direction",
            "multiple",
            "permission",
            "editable",
            "source_incidence",
            "target_incidence",
            "authority_roots",
        )
        missing = sorted({
            field
            for _owner_root, port in projected_ports
            for field in required
            if field not in port
        })
        if missing:
            pytest.fail(
                "clean visual socket court remains red: %s visible sockets have "
                "exact relation identity, but the projection still omits public "
                "interface metadata %s, stable source/target incidences, and "
                "authority/cardinality/direction bindings"
                % (len(projected_ports), ", ".join(missing))
            )
        for _owner_root, port in projected_ports:
            assert port["interface_root"] in snapshot.cells
            assert port["relation_root"] in snapshot.cells
            assert port["source_incidence"] in snapshot.cells
            assert port["target_incidence"] in snapshot.cells
            assert port["source_incidence"] != port["target_incidence"]
            assert port["authority_roots"]
            assert all(root in snapshot.cells for root in port["authority_roots"])
            members = read_relation(snapshot, port["relation_root"], budget=256)
            incidences = {member.incidence_id for member in members}
            assert port["source_incidence"] in incidences
            assert port["target_incidence"] in incidences
            assert port["relation_root"] in snapshot.cells
            role_ids = {member.role_id for member in members}
            participant_ids = {member.participant_id for member in members}
            assert port["interface_root"] in participant_ids or port["interface_root"] in snapshot.cells
            assert role_ids, "visible socket relation must expose graph role identities"
        for owner_root, projected_port in projected_ports:
            lens_node = next(
                node for node in lens_payload["nodes"]
                if node["root_id"] == owner_root
            )
            definition_root = lens_node.get("definition_root")
            assert definition_root in snapshot.cells
            assert isinstance(projected_port["direction"], str)
            assert type(projected_port["multiple"]) is bool
            assert projected_port["permission"] is None or isinstance(
                projected_port["permission"], str
            )
            assert type(projected_port["editable"]) is bool
    finally:
        built.location.authority.store.close()


def test_clean_visual_projection_requires_graph_held_view_session_viewport_and_tokens(
    tmp_path,
):
    built, _provider = _provision_clean_runtime(tmp_path)
    try:
        issued = _issue_visual_session(built, prefix="viewport-presence")
        projected, lens_payload, _before, _after = _project_current_visual_for_session(
            built,
            issued,
        )
        assert projected["graph_id"] == lens_payload["graph_id"]
        assert projected["root"] == lens_payload["scope_root"]
        assert projected["revision"] == lens_payload["revision"]
        missing = [key for key in ("viewport", "design_tokens") if key not in lens_payload]
        assert "view_root" not in lens_payload
        if missing:
            pytest.fail(
                "clean visual viewport/token court remains red: projection emits "
                "viewport/design output for issued browser session %s view %s, but "
                "the clean scope lens has no graph-held %s and no public generic "
                "view-session mutation path exposes accepted revisions for them."
                % (issued.root_id, issued.view_root, ", ".join(missing))
            )
    finally:
        built.location.authority.store.close()


@pytest.mark.skipif(
    _generic_relation_revision_command() is None,
    reason="blocked by missing generic public relation/view-session revision command",
)
def test_clean_visual_projection_view_session_revision_changes_viewport_tokens_and_reopens(
    tmp_path,
):
    built, _provider = _provision_clean_runtime(tmp_path)
    try:
        issued = _issue_visual_session(built, prefix="viewport-command")
        projected_before, lens_before, _before, _after = _project_current_visual_for_session(
            built,
            issued,
        )
        assert projected_before["graph_id"] == lens_before["graph_id"]
        assert projected_before["root"] == lens_before["scope_root"]
        assert projected_before["revision"] == lens_before["revision"]
        command = _generic_relation_revision_command()
        if command is None:
            pytest.skip(
                "blocked by exact missing symbol unified_authority.revise_relation_node"
            )
        pytest.fail(
            "clean visual viewport behavior remains red: the public generic "
            "relation/view-session revision symbol now exists, but this court still "
            "needs the concrete clean command call that mutates viewport/design-token "
            "state for the issued browser session/view root, survives close/reopen "
            "recovery, and denies foreign or revoked sessions fail-closed"
        )
    finally:
        built.location.authority.store.close()


def test_clean_visual_projection_requires_graph_held_property_identity_and_public_value_revision(
    tmp_path,
):
    built, _provider = _provision_clean_runtime(tmp_path)
    try:
        before, lens_before, _snapshot_before, _snapshot_after = _project_current_visual(
            built
        )
        instance_root = lens_before["nodes"][0]["root_id"]
        row_before = before["properties"][0]
        property_name = row_before["label"]
        current_value = row_before["value"]
        next_value = (
            str(current_value) + "-updated"
            if current_value is not None else "updated"
        )
        revise_instance(
            built.location.authority,
            instance_root,
            {property_name: next_value},
            scope_root=built.grand_map.root_id,
            caller=built.caller,
            command_id=str(uuid.uuid4()),
            expected_revision=lens_before["revision"],
        )
        after, lens_after, _snapshot_before, _snapshot_after = _project_current_visual(
            built
        )
        row_after = _projected_property_row(after, property_name)
        assert after["graph_id"] == lens_after["graph_id"] == before["graph_id"]
        assert after["root"] == lens_after["scope_root"] == before["root"]
        assert after["revision"] == lens_after["revision"]
        assert after["revision"] > before["revision"]
        assert row_after["value"] == next_value
        assert row_before["value"] != row_after["value"]
        required = (
            "relation",
            "owner",
            "value_root",
            "name_root",
            "presentation_root",
            "property_root",
        )
        missing_before = [field for field in required if field not in row_before]
        if missing_before:
            pytest.fail(
                "clean visual property court remains red: projected Properties rows "
                "still omit pre-edit identity fields %s, so the visual layer cannot "
                "prove before/after continuity of the same graph-held property/value"
                % ", ".join(missing_before)
            )
        missing_after = [field for field in required if field not in row_after]
        if missing_after:
            pytest.fail(
                "clean visual property court remains red: public revise_instance "
                "changes the visible value, but the projected Properties row still "
                "omits post-edit identity fields %s"
                % ", ".join(missing_after)
            )
        snapshot = built.location.authority.store.snapshot()
        assert row_after["relation"] in snapshot.cells
        assert row_after["owner"] == instance_root
        for root in (
            row_after["relation"],
            row_after["owner"],
            row_after["value_root"],
            row_after["name_root"],
            row_after["presentation_root"],
            row_after["property_root"],
        ):
            assert root in snapshot.cells
        members = read_relation(snapshot, row_after["relation"], budget=256)
        role_map = {
            member.role_id: member.participant_id for member in members
        }
        assert built.location.authority.role("owner") in role_map
        assert built.location.authority.role("name") in role_map
        assert built.location.authority.role("value") in role_map
        assert role_map[built.location.authority.role("owner")] == row_after["owner"]
        assert role_map[built.location.authority.role("name")] == row_after["name_root"]
        assert role_map[built.location.authority.role("value")] == row_after["value_root"]
        continuity_required = ("history_root", "predecessor_root")
        continuity_missing = [field for field in continuity_required if field not in row_after]
        if continuity_missing:
            pytest.fail(
                "clean visual property court remains red: value mutation is real, "
                "but the row still omits unconditional predecessor/history continuity "
                "fields %s when visual property roots change"
                % ", ".join(continuity_missing)
            )
        assert row_after["history_root"] in snapshot.cells
        assert row_after["predecessor_root"] in snapshot.cells
        if row_after["property_root"] != row_before["property_root"]:
            assert row_after["predecessor_root"] == row_before["property_root"]
    finally:
        built.location.authority.store.close()


def test_clean_visual_projection_requires_graph_held_panel_definition_roots_and_applicability(
    tmp_path,
):
    built, _provider = _provision_clean_runtime(tmp_path)
    try:
        before, lens_before, _snapshot_before, _snapshot_after = _project_current_visual(
            built
        )
        definition_root = lens_before["nodes"][0]["definition_root"]
        assert isinstance(definition_root, str)
        revised_presentation = {
            "label": "Domain composition",
            "panels": ["Overview", "Govern"],
        }
        _revise_scope_definition(
            built,
            definition_root,
            version_suffix="-panel-roots",
            presentation=revised_presentation,
        )
        after, lens_after, _snapshot_before, _snapshot_after = _project_current_visual(
            built
        )
        assert after["graph_id"] == lens_after["graph_id"] == before["graph_id"]
        assert after["root"] == lens_after["scope_root"] == before["root"]
        assert after["revision"] == lens_after["revision"]
        assert after["revision"] > before["revision"]
        panels = after["inspector"]["presentation"]["panels"]
        if [panel["label"] for panel in panels] != revised_presentation["panels"]:
            pytest.fail(
                "clean visual panel court remains red: public definition revision "
                "changed panel labels in authority, but projection still falls back "
                "to inline Python panels"
            )
        missing = sorted({
            field for panel in panels for field in ("id", "applicability_root")
            if field not in panel
        })
        if missing:
            pytest.fail(
                "clean visual panel court remains red: visible inspector tabs now "
                "match the revised labels, but still omit graph-held %s identity"
                % ", ".join(missing)
            )
        if _generic_relation_revision_command() is None:
            pytest.fail(
                "clean visual panel court remains red: no public authenticated "
                "same-root relation revision/removal command exists yet for panel "
                "applicability, so tab removal and audience/lens applicability "
                "cannot be proven through the clean command boundary"
            )
        snapshot = built.location.authority.store.snapshot()
        for panel in panels:
            assert panel["id"] in snapshot.cells
            assert panel["applicability_root"] in snapshot.cells
            members = read_relation(snapshot, panel["applicability_root"], budget=256)
            participants = {member.participant_id for member in members}
            role_ids = {member.role_id for member in members}
            assert panel["id"] in participants
            assert after["root"] in participants or after.get("selected") in participants
            if len(participants) < 3 or len(role_ids) < 3:
                pytest.fail(
                    "clean visual panel court remains red: panel applicability still "
                    "looks like copied string membership, not a graph-held panel "
                    "definition with lens/audience applicability roles"
                )
    finally:
        built.location.authority.store.close()
