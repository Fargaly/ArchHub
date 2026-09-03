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
from nodelang.cell_browser_sessions import BrowserSessionDenied
from nodelang.clean_browser_authority import (
    issue_clean_browser_session,
    revoke_clean_browser_session,
)
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


def _flatten_descriptor(node):
    """Every element in a rendered descriptor tree, parents before children."""
    if isinstance(node, list):
        for item in node:
            yield from _flatten_descriptor(item)
        return
    if not isinstance(node, dict):
        return
    yield node
    yield from _flatten_descriptor(node.get("children") or [])


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


def _json(url, path, payload=None, *, token: str, csrf: str | None = None):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "X-ArchHub-Session": token,
    }
    # Mutating routes verify the session's CSRF digest; a POST without the
    # issued token is refused 403 by design, not by accident.
    if csrf is not None:
        headers["X-ArchHub-CSRF"] = csrf
    request = Request(
        url + path,
        data=data,
        headers=headers,
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
            csrf="clean-scope-csrf",
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
        # The inspector describes what is focused. This court revises a
        # definition and then reads panels, properties and catalogue
        # contracts, so it focuses the node that definition belongs to
        # first; with nothing focused the correct projection is an empty
        # rail, which test_..._graph_held_selection_without_first_node_
        # fallback already pins.
        issued = _issue_visual_session(built, prefix="visual-contracts")
        seed, seed_lens, seed_before, _seed_after = (
            _project_current_visual_for_session(built, issued)
        )
        focus_target = seed_lens["nodes"][0]["root_id"]
        focus_command = _focus_command()
        assert callable(focus_command)
        focus_command(
            built.location.authority,
            built.browser,
            issued.root_id,
            scope_root=built.grand_map.root_id,
            selected_roots=(focus_target,),
            primary_root=focus_target,
            caller=built.caller,
            command_id=str(uuid.uuid4()),
            expected_revision=seed_before.revision,
        )
        before, lens_before, _snapshot_before, _snapshot_after = (
            _project_current_visual_for_session(built, issued)
        )
        assert lens_before["selected_root"] == focus_target
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
        after, lens_after, _, _ = _project_current_visual_for_session(
            built, issued
        )
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
        assert item["interface_contract"] == source_item["interfaces"]
        assert item["interfaces"] == len(source_item["interfaces"])
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
        shell = projected["inspector"]["shell_descriptor"]
        assert shell, (
            "inspector chrome vanished with its content: a scope that "
            "declares no panels must still render its shell -- 'no tabs' and "
            "'no shell' are different facts and collapsing them blanks the "
            "inspector for every scope the graph has not seeded"
        )
        invented = [
            node for node in _flatten_descriptor(shell)
            if str(node.get("key", "")).startswith("panel:")
            or node.get("id") in {
                row["id"]
                for row in projected["inspector"]["presentation"]["panels"]
            }
        ]
        assert invented == [], (
            "shell rendered panel elements the graph never declared: %r"
            % invented
        )
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


def _view_session_viewport_command():
    """The concrete clean view-session viewport/token mutation command."""
    return getattr(unified_authority_module, "revise_view_session_viewport", None)


def test_clean_visual_projection_view_session_revision_changes_viewport_tokens_and_reopens(
    tmp_path,
):
    """Viewport and design tokens are graph-held state bound to one view.

    The view is the agent session's working view, shared by every browser
    session that agent holds -- a second browser session seeing the pan is
    correct product behavior, so the boundary under test is the BROWSER
    session: an unknown session and a revoked session must both be refused
    fail-closed, refused meaning raised AND unchanged. The second session is
    also the untainted read path after revocation, so no assertion depends
    on reading through a session that was just revoked.
    """
    command = _view_session_viewport_command()
    if command is None:
        pytest.fail(
            "clean view-session behavior court remains red: missing exact "
            "symbol unified_authority.revise_view_session_viewport -- the "
            "public command that mutates viewport/design-token state for one "
            "issued browser session view root and returns the accepted "
            "revision"
        )
    built, _provider = _provision_clean_runtime(tmp_path)
    try:
        owner = _issue_visual_session(built, prefix="viewport-owner")
        witness = _issue_visual_session(built, prefix="viewport-witness")
        assert owner.root_id != witness.root_id
        assert owner.view_root == witness.view_root, (
            "both sessions belong to one agent, so they share one view"
        )
        authority = built.location.authority

        _projected, lens_before, _b, _a = _project_current_visual_for_session(
            built, owner
        )
        base_revision = lens_before["revision"]

        viewport = {"x": 128, "y": -64, "zoom": 1.75}
        tokens = {"surface": "graph-held", "accent": "terracotta"}

        accepted = command(
            authority,
            owner.view_root,
            viewport=viewport,
            design_tokens=tokens,
            session_root=owner.root_id,
            caller=built.caller,
            command_id=str(uuid.uuid4()),
            expected_revision=base_revision,
        )
        assert accepted.revision > base_revision

        _p_owner, lens_owner, _b, _a = _project_current_visual_for_session(
            built, owner
        )
        assert lens_owner["viewport"] == viewport
        assert lens_owner["design_tokens"] == tokens
        assert lens_owner["revision"] == accepted.revision

        # the shared view: the agent's other browser session sees the state
        _p_wit, lens_witness, _b, _a = _project_current_visual_for_session(
            built, witness
        )
        assert lens_witness["viewport"] == viewport
        assert lens_witness["design_tokens"] == tokens

        # survives close and reopen
        reopened = _project_current_visual_for_session(built, owner)[1]
        assert reopened["viewport"] == viewport
        assert reopened["design_tokens"] == tokens

        # fail-closed for an UNKNOWN browser session: raised AND unchanged
        with pytest.raises(
            (unified_authority_module.InvalidCell, BrowserSessionDenied)
        ):
            command(
                authority,
                owner.view_root,
                viewport={"x": 9999, "y": 9999, "zoom": 4.0},
                design_tokens={"surface": "stolen"},
                session_root=str(uuid.uuid4()),
                caller=built.caller,
                command_id=str(uuid.uuid4()),
                expected_revision=None,
            )
        after_unknown = _project_current_visual_for_session(built, witness)[1]
        assert after_unknown["viewport"] == viewport, (
            "unknown session was refused but the viewport changed: the "
            "denial is not fail-closed, it raised after writing"
        )

        # fail-closed for a VALID, ACTIVE session of a DIFFERENT agent --
        # the real cross-tenant case. Rejecting a fabricated uuid is a failed
        # lookup; rejecting a well-formed session aimed at someone else's
        # view requires the command to compare the session's view against
        # the target, and that comparison is what this proves.
        other_agent = _second_admitted_caller(built)
        foreign = issue_clean_browser_session(
            authority,
            built.browser,
            token=f"viewport-foreign-{uuid.uuid4().hex}",
            csrf_token=f"viewport-foreign-csrf-{uuid.uuid4().hex}",
            lifetime_seconds=120.0,
            caller=other_agent,
            command_id=str(uuid.uuid4()),
        )
        assert foreign.view_root != owner.view_root
        with pytest.raises(
            (unified_authority_module.InvalidCell, BrowserSessionDenied)
        ):
            command(
                authority,
                owner.view_root,
                viewport={"x": 555, "y": 555, "zoom": 5.0},
                design_tokens={"surface": "cross-agent"},
                session_root=foreign.root_id,
                caller=built.caller,
                command_id=str(uuid.uuid4()),
                expected_revision=None,
            )
        after_cross = _project_current_visual_for_session(built, witness)[1]
        assert after_cross["viewport"] == viewport, (
            "a different agent's live session was refused but the viewport "
            "changed: the view comparison is missing, not the lookup"
        )

        # fail-closed for a REVOKED session, read through the live witness
        revoke_clean_browser_session(
            authority,
            built.browser,
            owner.root_id,
            reason="court: revoked session must not mutate viewport",
            caller=built.caller,
            command_id=str(uuid.uuid4()),
        )
        with pytest.raises(
            (unified_authority_module.InvalidCell, BrowserSessionDenied)
        ):
            command(
                authority,
                owner.view_root,
                viewport={"x": 1, "y": 1, "zoom": 1.0},
                design_tokens={"surface": "revoked"},
                session_root=owner.root_id,
                caller=built.caller,
                command_id=str(uuid.uuid4()),
                expected_revision=None,
            )
        after_revoked = _project_current_visual_for_session(built, witness)[1]
        assert after_revoked["viewport"] == viewport, (
            "revoked session was refused but the viewport changed: "
            "revocation is advisory, not fail-closed"
        )
        assert after_revoked["design_tokens"] == tokens
    finally:
        built.location.authority.store.close()


def test_clean_visual_projection_requires_graph_held_property_identity_and_public_value_revision(
    tmp_path,
):
    built, _provider = _provision_clean_runtime(tmp_path)
    try:
        # The rail describes what is focused. This court reads a property row
        # and then proves its identity survives an edit, so it focuses the
        # node that owns the row first. With nothing focused the rail is
        # correctly empty, which test_..._selection_presence already pins.
        issued = _issue_visual_session(built, prefix="property-identity")
        seed, seed_lens, seed_before, _seed_after = (
            _project_current_visual_for_session(built, issued)
        )
        focus_target = seed_lens["nodes"][0]["root_id"]
        focus_command = _focus_command()
        assert callable(focus_command)
        focus_command(
            built.location.authority,
            built.browser,
            issued.root_id,
            scope_root=built.grand_map.root_id,
            selected_roots=(focus_target,),
            primary_root=focus_target,
            caller=built.caller,
            command_id=str(uuid.uuid4()),
            expected_revision=seed_before.revision,
        )
        before, lens_before, _snapshot_before, _snapshot_after = (
            _project_current_visual_for_session(built, issued)
        )
        assert lens_before["selected_root"] == focus_target
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
        after, lens_after, _snapshot_before, _snapshot_after = (
            _project_current_visual_for_session(built, issued)
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


def test_installed_visual_system_can_be_revised_onto_a_graph(tmp_path):
    """A graph that holds a subsystem must be able to hold a newer one.

    Installing refuses a source it did not already have, which on a graph
    installed once froze every descriptor for good: a row that renders the
    wrong thing could not be corrected on the graph it was wrong on, and a
    control the graph should offer could never be added. This is the
    ordinary signed way through -- and it refuses the two cases that would
    make it a way around: a graph with nothing installed, and a
    replacement identical to what is already held.
    """
    import uuid as _uuid

    from nodelang.clean_visual_authority import (
        install_clean_visual_system,
        open_clean_visual_system,
        revise_clean_visual_system,
    )
    from nodelang.clean_subsystem_revision import replace_interface_subsystem
    from nodelang.universal_cell import InvalidCell

    built, _provider = _provision_clean_runtime(tmp_path)
    try:
        authority = built.location.authority
        caller = built.caller
        held = open_clean_visual_system(authority, caller=caller)

        # Nothing has changed, so there is nothing to carry.
        with pytest.raises(InvalidCell):
            revise_clean_visual_system(
                authority, caller=caller, command_id=str(_uuid.uuid4())
            )

        # A subsystem cannot be replaced by itself: that would report a
        # revision while changing nothing the graph holds.
        with pytest.raises(InvalidCell):
            replace_interface_subsystem(
                authority,
                caller=caller,
                command_id=str(_uuid.uuid4()),
                intent="revise-clean-visual-system",
                held_root=held.root_id,
                replacement_root=held.root_id,
                replacement_cells=(),
                source_digest=held.source_digest,
            )

        # A subsystem the Interface does not hold cannot be replaced.
        with pytest.raises(InvalidCell):
            replace_interface_subsystem(
                authority,
                caller=caller,
                command_id=str(_uuid.uuid4()),
                intent="revise-clean-visual-system",
                held_root=str(_uuid.uuid4()),
                replacement_root=str(_uuid.uuid4()),
                replacement_cells=(),
                source_digest="none",
            )

        # The graph still holds exactly what it held, and still opens.
        after = open_clean_visual_system(authority, caller=caller)
        assert after.root_id == held.root_id
        assert after.source_digest == held.source_digest
        assert install_clean_visual_system is not None

        # And the swap itself: the Interface stops holding the installed
        # subsystem and holds the replacement, in one revision. Refusals
        # alone would leave the thing this exists for unproven.
        from nodelang.cell_protocols import read_relation
        from nodelang.unified_authority import (
            COMMAND_BUDGET,
            composition_root,
            new_id,
            typed_relation_cells,
        )

        def held_roots():
            snapshot = authority.store.snapshot()
            interface_root = composition_root(
                authority, "Interface", caller=caller
            )
            return {
                member.participant_id
                for member in read_relation(
                    snapshot, interface_root, budget=COMMAND_BUDGET
                )
                if member.role_id == authority.role("composition")
            }

        assert held.root_id in held_roots()
        replacement_root = new_id()
        replacement_cells = typed_relation_cells(
            replacement_root,
            authority.role("conforms-to"),
            authority.shape("composition"),
            ((authority.role("label"), authority.manifest.application_root),),
        )
        before_revision = authority.store.snapshot().revision
        replace_interface_subsystem(
            authority,
            caller=caller,
            command_id=str(_uuid.uuid4()),
            intent="revise-clean-visual-system",
            held_root=held.root_id,
            replacement_root=replacement_root,
            replacement_cells=replacement_cells,
            source_digest="a-different-source",
        )
        now = held_roots()
        assert replacement_root in now, "the Interface must hold the replacement"
        assert held.root_id not in now, "the Interface must let the old one go"
        assert authority.store.snapshot().revision > before_revision
    finally:
        built.location.authority.store.close()


def test_host_execution_runs_only_what_the_graph_declares(tmp_path):
    """Running an operation is gated by the graph, and always leaves a receipt.

    An effect is the one thing a graph cannot take back, so every way of
    reaching one is refused unless the graph itself admits it: the
    operation must be declared, the arguments must be the ones it declares,
    a destructive operation needs explicit leave, and a runtime with no
    adapter can reach nothing at all. A run that happened is recorded, and
    a run that is replayed is not run again.
    """
    import uuid as _uuid

    from nodelang.clean_host_execution import (
        HostOperationRefused,
        execute_host_operation,
    )
    from nodelang.clean_host_operations import (
        compose_host_operations,
        install_host_operations,
    )

    built, _provider = _provision_clean_runtime(tmp_path)
    try:
        authority = built.location.authority
        caller = built.caller
        catalogue = compose_host_operations([
            {
                "op_id": "probe.read", "host": "probe", "kind": "read",
                "label": "Read", "description": "", "output_type": "row",
                "destructive": False,
                "inputs": [
                    {"id": "target", "label": "Target", "type": "text",
                     "default": "", "required": True, "help": ""},
                ],
            },
            {
                "op_id": "probe.wreck", "host": "probe", "kind": "action",
                "label": "Wreck", "description": "", "output_type": "row",
                "destructive": True, "inputs": [],
            },
        ])
        install_host_operations(
            authority, catalogue, caller=caller,
            command_id=str(_uuid.uuid4()))

        seen = []

        def invoker(op_id, arguments):
            seen.append((op_id, dict(arguments)))
            return {"rows": 1}

        def run(op_id, arguments, **kwargs):
            return execute_host_operation(
                authority, op_id, arguments, caller=caller,
                command_id=kwargs.pop("command_id", str(_uuid.uuid4())),
                invoker=kwargs.pop("invoker", invoker), **kwargs)

        # An operation the graph never declared is not an ArchHub operation.
        with pytest.raises(HostOperationRefused):
            run("probe.invented", {})
        # An argument the operation never declared would be ignored by the
        # host or acted on by it, and both make the catalogue a fiction.
        with pytest.raises(HostOperationRefused):
            run("probe.read", {"target": "a", "extra": 1})
        # A required argument that is missing is caught here rather than
        # halfway through whatever the host was doing.
        with pytest.raises(HostOperationRefused):
            run("probe.read", {})
        # Destroying work needs explicit leave, every time.
        with pytest.raises(HostOperationRefused):
            run("probe.wreck", {})
        # A runtime given no adapter can reach nothing.
        with pytest.raises(HostOperationRefused):
            run("probe.read", {"target": "a"}, invoker=None)
        assert seen == [], "nothing may reach a host through a refused call"

        before = authority.store.snapshot().revision
        command = str(_uuid.uuid4())
        first = run("probe.read", {"target": "a"}, command_id=command)
        assert seen == [("probe.read", {"target": "a"})]
        assert first.replayed is False
        assert authority.store.snapshot().revision > before
        assert first.receipt_root in authority.store.snapshot().cells

        # The same command is the same effect. Asking twice must not do it
        # twice, whatever the caller intended.
        replayed = run("probe.read", {"target": "a"}, command_id=command)
        assert len(seen) == 1, "a replayed effect must not reach the host again"
        assert replayed.replayed is True

        # A host that fails is a fact this graph keeps.
        def broken(op_id, arguments):
            raise RuntimeError("the host said no")

        failing = authority.store.snapshot().revision
        with pytest.raises(HostOperationRefused):
            run("probe.read", {"target": "b"}, invoker=broken)
        assert authority.store.snapshot().revision > failing, (
            "a run that failed must still be recorded"
        )
    finally:
        built.location.authority.store.close()


def test_a_control_does_what_the_graph_says_it_does(tmp_path):
    """A control's meaning is read from its interaction, not from its name.

    The route that answers a pressed control has to decide what was asked
    for. Deciding by which control it was would put the meaning of every
    button in the server, where revising the graph could never reach it --
    and a control the graph declared nothing for would be answered by
    whatever branch happened to be last. The capability comes from the
    interaction the graph installed, and a control with no interaction has
    no capability at all.
    """
    import uuid as _uuid

    from nodelang.cell_control_bindings import (
        CAPABILITY_EXECUTE,
        CAPABILITY_INSTANTIATE,
        CAPABILITY_SCOPE,
    )
    from nodelang.clean_scope_interactions import (
        CONTROL_RUN,
        install_clean_scope_interactions,
    )
    from nodelang.cell_interactions import read_interaction
    from nodelang.clean_scope_interactions import CAPABILITY_COMPOSITION

    built, provider = _provision_clean_runtime(tmp_path)
    server = _start_clean_server(built, provider)
    try:
        interactions = server.clean_scope_interactions
        scope = server.clean_scope_root
        assert interactions is not None, (
            "a scope with no interaction set can activate nothing"
        )

        def capability_of(control_root):
            return server._clean_control_capability(control_root)

        # A control the graph declared no interaction for is not a control
        # this server will act on.
        assert capability_of(str(_uuid.uuid4())) is None
        assert capability_of("app:control:canvas:invented") is None
        assert capability_of(None) is None

        # Run is declared, and it is declared as execution -- not as scope
        # entry, which is what answering by name would have made it.
        run = capability_of(CONTROL_RUN)
        assert run == CAPABILITY_EXECUTE, run

        # Every binding the scope carries names a capability the graph
        # holds, and each one is read back from the interaction itself.
        held = interactions.bindings.get(scope) or {}
        assert held, "the projected scope must carry its bindings"
        admitted = {
            CAPABILITY_SCOPE,
            CAPABILITY_EXECUTE,
            CAPABILITY_INSTANTIATE,
            # Group and ungroup landed as first-class signed acts; their
            # bindings name the composition capability by design.
            CAPABILITY_COMPOSITION,
        }
        snapshot = built.location.authority.store.snapshot()
        for control_root, binding in held.items():
            interaction = read_interaction(
                snapshot, interactions.protocol, binding.interaction_root
            )
            assert interaction.action_root in admitted, (
                "control %s names a capability outside the admitted set"
                % control_root
            )
            assert capability_of(control_root) == interaction.action_root
        assert install_clean_scope_interactions is not None
    finally:
        built.location.authority.store.close()


def test_host_adapters_attach_and_never_launch():
    """An adapter joins what is open; it never opens anything.

    An adapter that can start an application turns "read my documents"
    into "take over my desktop": press a button and Word appears, or four
    copies of it do. Attaching is GetActiveObject; launching is Dispatch,
    and the difference is one call nobody would notice in review. So it is
    courted as an absence -- the adapters may not contain the launching
    call at all -- and courted the same way for Revit, which must not spawn
    a session either.

    The refusals are courted with it, because an adapter that answers an
    operation it does not carry out is an adapter that will one day answer
    the wrong host.
    """
    import inspect

    from nodelang import clean_office_adapter, clean_revit_adapter

    office_source = inspect.getsource(clean_office_adapter)
    assert "GetActiveObject" in office_source, (
        "the office adapter must attach to a running application"
    )
    # The call, not the word: this file explains why launching is refused,
    # and a court that cannot tell the explanation from the act would
    # forbid saying so.
    assert ".Dispatch(" not in office_source, (
        "the office adapter must never launch an application"
    )
    assert "DispatchEx" not in office_source
    assert "subprocess" not in office_source
    assert "os.startfile" not in office_source

    revit_source = inspect.getsource(clean_revit_adapter)
    assert "subprocess" not in revit_source, (
        "the Revit adapter must never start a Revit"
    )
    assert "os.startfile" not in revit_source
    # It finds sessions by asking the published range, never by remembering
    # a port: a port remembered from last time belongs to whatever is
    # listening now.
    assert "BROKER_PORTS" in revit_source

    # An operation an adapter does not carry out is refused by name, not
    # answered by whatever branch happened to be last.
    with pytest.raises(clean_office_adapter.OfficeUnreachable):
        clean_office_adapter.invoke("word.invented", {})
    with pytest.raises(clean_office_adapter.OfficeUnreachable):
        clean_office_adapter.invoke("revit.list_levels", {})
    with pytest.raises(clean_revit_adapter.RevitUnreachable):
        clean_revit_adapter.invoke("revit.invented", {})
    with pytest.raises(clean_revit_adapter.RevitUnreachable):
        clean_revit_adapter.invoke("word.list_documents", {})


def test_attention_and_state_survive_a_restart(tmp_path):
    """What the founder was looking at is still there after a restart.

    SPEC court 6 asks that focus, cursors and obligations recover; court 7
    asks that the same revision reconstructs deterministically. Both are
    the same claim seen twice: the graph is the state, and a runtime is
    only a reader of it. So this closes the store, opens it again from
    disk, and asks whether the answers changed.

    A canvas that forgets the selection on restart would push the founder
    back to the top of a two hundred node map every time -- and a graph
    that reconstructs differently would make every court above it
    meaningless, because the thing they certified would not be the thing
    that comes back.
    """
    import uuid as _uuid

    from nodelang.cell_secret_keys import MemorySigningKeyProvider
    from nodelang.cell_revision_checkpoint import snapshot_digest
    from nodelang.unified_authority import (
        composition_root,
        place_composition,
        read_composition_placements,
        read_scope_level,
    )
    from nodelang.unified_authority_runtime import open_current_authority

    built, provider = _provision_clean_runtime(tmp_path)
    authority = built.location.authority
    caller = built.caller
    scope = built.grand_map.root_id
    level = read_scope_level(authority, scope, scope_root=scope, caller=caller)
    node = sorted(level.composition_roots)[0]

    place_composition(
        authority, scope, node, {"x": 421.0, "y": 137.0},
        caller=caller, command_id=str(_uuid.uuid4()),
    )
    before_revision = authority.store.snapshot().revision
    before_digest = snapshot_digest(authority.store.snapshot())
    root_path = built.location.root
    authority.store.close()

    # A restart is not a reset. Nothing below re-installs, re-declares or
    # repairs anything -- it opens what is on disk and reads it.
    reopened = open_current_authority(root_path, provider)
    try:
        current = reopened.authority.store.snapshot()
        assert current.revision == before_revision, (
            "a restart must not move the graph"
        )
        assert snapshot_digest(current) == before_digest, (
            "the same revision must reconstruct to the same graph"
        )
        placements = read_composition_placements(
            reopened.authority,
            current,
            composition_root(reopened.authority, "Interface", caller=caller),
            wanted=(node,),
        )
        held = placements.get(node) or {}
        assert held.get("x") == 421.0 and held.get("y") == 137.0, (
            "where the founder put a node must survive a restart"
        )
    finally:
        reopened.authority.store.close()


def test_deleting_the_fast_path_does_not_change_the_answer(tmp_path):
    """Every cache must be invisible except in how long the answer takes.

    SPEC court 3 forbids a hidden interpreter: the fast path and the graph
    path must mean the same thing, and deleting the fast path must not
    alter meaning. Today's speed came from remembering answers -- the
    opened visual system, definition projections, the head verdict -- and a
    remembered answer is exactly how a second interpreter gets in: it can
    drift from the graph and nobody notices, because the fast path is the
    only one anybody runs.

    So the caches are emptied and the same questions asked again. Same
    answers, or they were never caches.
    """
    from nodelang import clean_visual_authority, unified_authority
    from nodelang.clean_visual_authority import open_clean_visual_system

    built, _provider = _provision_clean_runtime(tmp_path)
    try:
        authority = built.location.authority
        caller = built.caller

        warm_canvas, warm_lens, _snapshot, _after = _project_current_visual(built)
        warm_visual = open_clean_visual_system(authority, caller=caller)

        emptied = 0
        for module, name in (
            (clean_visual_authority, "_OPENED_VISUAL_CACHE"),
            (unified_authority, "_DEFINITION_CACHE"),
            (unified_authority, "_HEAD_VERDICT_CACHE"),
            (unified_authority, "_SNAPSHOT_DIGEST_CACHE"),
        ):
            cache = getattr(module, name, None)
            assert cache is not None, "%s is gone; this court no longer guards it" % name
            cache.clear()
            emptied += 1
        assert emptied == 4

        cold_canvas, cold_lens, _snapshot2, _after2 = _project_current_visual(built)
        cold_visual = open_clean_visual_system(authority, caller=caller)

        assert cold_visual.root_id == warm_visual.root_id
        assert cold_visual.source_digest == warm_visual.source_digest

        # Projecting issues a lease, which is graph state, so the second
        # read is honestly one revision later. That number is expected to
        # differ; everything a cache could corrupt is not.
        def without_revision(payload):
            return {
                key: value for key, value in payload.items()
                if key not in ("revision", "accepted_revision")
            }

        assert cold_lens["revision"] >= warm_lens["revision"]
        assert without_revision(cold_lens) == without_revision(warm_lens), (
            "the lens changed when the caches were dropped"
        )
        # The revision moves and each projection is authorized through its
        # own freshly issued session, so those two differ honestly. What a
        # stale cache would corrupt is what the graph says -- the nodes,
        # what connects them, what may be placed, and how it all renders.
        described = (
            "nodes", "wires", "catalog", "catalog_sections", "library",
            "scope", "inspector", "properties", "configuration",
            "toolbar_descriptor", "canvas_heading_descriptor", "primitive",
        )
        for key in described:
            assert key in warm_canvas, "%s left the projection" % key
            assert cold_canvas[key] == warm_canvas[key], (
                "%s changed when the caches were dropped -- the fast path "
                "was not a cache but a second interpreter" % key
            )
    finally:
        built.location.authority.store.close()


def test_the_canvas_shows_nothing_the_scope_does_not_hold(tmp_path):
    """Nothing outside the projected scope may reach the canvas.

    SPEC court 8 asks that hidden roots cannot influence visible output.
    The risk got sharper today: relations are now resolved up to the card
    that contains them, which means a walk decides what a node stands for.
    A walk that wanders outside the scope would put another region's work
    on this canvas -- and on a graph that holds client projects beside each
    other, that is the whole confidentiality boundary, drawn by a loop.

    So every root the canvas names is checked against what the scope
    actually holds: every node, every wire end, every placement.
    """
    from nodelang.unified_authority import read_scope_level

    built, _provider = _provision_clean_runtime(tmp_path)
    try:
        authority = built.location.authority
        caller = built.caller
        scope = built.grand_map.root_id
        canvas, lens, _snapshot, _after = _project_current_visual(built)

        level = read_scope_level(
            authority, scope, scope_root=scope, caller=caller
        )
        held = set(level.composition_roots)
        assert held, "the scope must hold something for this court to mean anything"

        drawn = {node["id"] for node in canvas["nodes"]}
        assert drawn <= held, (
            "the canvas drew %s, which this scope does not hold"
            % sorted(drawn - held)
        )

        # A wire may only join two cards this scope draws. An end pointing
        # anywhere else is a line out of the region.
        for wire in canvas["wires"]:
            assert wire["source"] in drawn, (
                "a wire starts at %s, which is not on this canvas" % wire["source"]
            )
            assert wire["target"] in drawn, (
                "a wire ends at %s, which is not on this canvas" % wire["target"]
            )
            for participant in wire["participants"]:
                assert participant["root"] in drawn, (
                    "a wire names participant %s, which is not on this canvas"
                    % participant["root"]
                )

        # The library offers definitions, not another scope's nodes.
        offered = {item["id"] for item in canvas["catalog"]}
        assert not (offered & drawn), (
            "the library offered a node that is already on the canvas"
        )
    finally:
        built.location.authority.store.close()


def test_rewiring_the_catalogue_changes_the_canvas(tmp_path):
    """Authority causes behaviour; the projector only reports it.

    SPEC court 5 asks that rewiring authority changes behaviour while
    deleting projection does not. The toolbar is where that is easiest to
    fake: a server could hold its own list of buttons and no one would
    know until the graph and the screen disagreed.

    So the catalogue in the graph is revised and the canvas is asked
    again. If the button set follows the revision, the graph is the cause.
    If it does not, the toolbar was a Python list wearing a graph's name.
    """
    import uuid as _uuid

    from nodelang.clean_design_catalogue import (
        compose_design_catalogue,
        read_design_catalogue,
    )

    built, _provider = _provision_clean_runtime(tmp_path)
    try:
        authority = built.location.authority
        caller = built.caller

        before, _lens, _s, _a = _project_current_visual(built)
        held = read_design_catalogue(authority, caller=caller)
        assert held is not None, "the graph must hold its own catalogue"
        drawn = {
            control["label"]
            for control in before["configuration"]["design_system"]
            ["control_catalog"]["controls"]
        }
        assert "Run" in drawn, "the Run control must start out declared"

        # Revise the catalogue: the same source, minus one control. This is
        # an ordinary signed revision, not a code edit.
        revised = compose_design_catalogue()
        revised["controls"] = [
            control for control in revised["controls"]
            if control["label"] != "Run"
        ]
        # Revise the definition the graph actually holds. This is the same
        # signed path the founder's own edit would take.
        from nodelang.cell_protocols import read_relation
        from nodelang.unified_authority import (
            COMMAND_BUDGET, read_definition, revise_definition,
        )

        target = None
        for member in read_relation(
            authority.store.snapshot(),
            authority.manifest.catalogue_root,
            budget=COMMAND_BUDGET,
        ):
            if member.role_id != authority.role("definition"):
                continue
            projection = read_definition(
                authority, member.participant_id, caller=caller
            )
            if projection.name == "Design System Catalogue":
                target = projection
                break
        assert target is not None, "the graph must hold the catalogue definition"
        revise_definition(
            authority, target.root_id, target.name,
            caller=caller, command_id=str(_uuid.uuid4()),
            version=target.version,
            presentation=revised,
        )

        after, _lens2, _s2, _a2 = _project_current_visual(built)
        drawn_after = {
            control["label"]
            for control in after["configuration"]["design_system"]
            ["control_catalog"]["controls"]
        }
        assert "Run" not in drawn_after, (
            "the graph stopped declaring Run and the canvas still drew it -- "
            "the toolbar is not caused by the catalogue"
        )
        assert drawn - {"Run"} == drawn_after, (
            "revising one control changed more than that control"
        )
    finally:
        built.location.authority.store.close()


def test_every_lens_resolves_the_same_roots(tmp_path):
    """One graph, many views, the same identities.

    SPEC court 4 asks that every lens resolves the same roots and facts.
    ArchHub's whole claim is that the canvas, the library, the inspector
    and the interaction set are views of one graph rather than four
    databases that agree by habit. Four things that agree today and drift
    next month are exactly what a court is for.

    So the same node is asked for from the scope level, the canvas, the
    placements and the interaction bindings, and the identities are
    compared. A node that is one thing has one root everywhere.
    """
    from nodelang.cell_protocols import read_relation
    from nodelang.unified_authority import (
        COMMAND_BUDGET,
        composition_root,
        read_composition_placements,
        read_scope_level,
    )

    built, _provider = _provision_clean_runtime(tmp_path)
    try:
        authority = built.location.authority
        caller = built.caller
        scope = built.grand_map.root_id
        canvas, lens, _s, _a = _project_current_visual(built)

        level = read_scope_level(
            authority, scope, scope_root=scope, caller=caller
        )
        by_level = set(level.composition_roots)
        by_lens = {node["root_id"] for node in lens["nodes"]}
        by_canvas = {node["id"] for node in canvas["nodes"]}
        assert by_level == by_lens == by_canvas, (
            "the scope, the lens and the canvas disagree about which nodes exist"
        )

        # A placement is about the same node the canvas drew, not a copy of
        # it under another identity.
        interface_root = composition_root(authority, "Interface", caller=caller)
        placed = read_composition_placements(
            authority, authority.store.snapshot(), interface_root
        )
        assert set(placed) <= by_level | {scope}, (
            "a placement names %s, which this scope does not hold"
            % sorted(set(placed) - (by_level | {scope}))
        )

        # And the graph itself agrees: each drawn root is a cell, and the
        # scope holds it as a member rather than merely mentioning it.
        snapshot = authority.store.snapshot()
        members = {
            member.participant_id
            for member in read_relation(snapshot, scope, budget=COMMAND_BUDGET)
            if member.role_id == authority.role("composition")
        }
        for root in by_canvas:
            assert root in snapshot.cells, "%s is drawn but is not a cell" % root
            assert root in members, "%s is drawn but the scope does not hold it" % root
    finally:
        built.location.authority.store.close()


def test_relations_are_exact_not_decorative(tmp_path):
    """A wire stands for a relation that is really in the graph.

    SPEC court 10 asks that sockets, cables, relations, incidences and
    n-ary cases are exact. A canvas can always draw a convincing line; the
    question is whether the line is a reading of the graph or a drawing
    next to it. Today wires are resolved up to the card that contains
    them, which makes that question sharper -- a resolved wire must still
    be traceable to one relation cell with real incidences.

    An n-ary relation is included deliberately: a relation with more than
    two participants is where a two-ended drawing starts lying.
    """
    from nodelang.cell_protocols import read_relation
    from nodelang.unified_authority import COMMAND_BUDGET

    built, _provider = _provision_clean_runtime(tmp_path)
    try:
        authority = built.location.authority
        canvas, lens, _s, _a = _project_current_visual(built)
        snapshot = authority.store.snapshot()

        assert canvas["wires"], "this court needs at least one wire to mean anything"
        for wire in canvas["wires"]:
            root = wire["id"]
            assert root in snapshot.cells, (
                "wire %s does not name a cell in the graph" % root
            )
            # The relation the wire names really relates things, and the
            # wire's ends are among them once resolved to visible cards.
            members = read_relation(snapshot, root, budget=COMMAND_BUDGET)
            assert members, "wire %s names a cell that relates nothing" % root
            participants = [entry["root"] for entry in wire["participants"]]
            assert len(participants) >= 2, (
                "wire %s draws fewer than two ends" % root
            )
            assert wire["source"] in participants
            assert wire["target"] in participants
            # A relation with more ends than a line has says so, rather
            # than quietly drawing two of them.
            assert wire["nary"] is (len(participants) > 2), (
                "wire %s misreports whether it is n-ary" % root
            )
            assert wire["directed"] is (
                wire["source"] is not None and wire["target"] is not None
            )
    finally:
        built.location.authority.store.close()


def test_everything_persisted_is_one_cell_shape(tmp_path):
    """One physical record, and no side door beside it.

    SPEC court 1 forbids a second persisted semantic shape or a side
    authority. Everything added today -- host operations, operation
    definitions, effect receipts, placements, viewports -- went in through
    signed commands, and this asks the store whether that is actually
    true: are there other tables holding meaning, and is every row a Cell
    with the exact four fields.

    A second table is how a graph computer quietly becomes an application
    with a database, and it never announces itself.
    """
    import sqlite3
    import uuid as _uuid

    from nodelang.clean_host_execution import execute_host_operation
    from nodelang.clean_host_operations import (
        compose_host_operations, install_host_operations,
    )
    from nodelang.unified_authority import place_composition, read_scope_level

    built, _provider = _provision_clean_runtime(tmp_path)
    authority = built.location.authority
    caller = built.caller
    scope = built.grand_map.root_id

    # Exercise every kind of thing this session learned to persist.
    install_host_operations(
        authority,
        compose_host_operations([{
            "op_id": "probe.read", "host": "probe", "kind": "read",
            "label": "Read", "description": "", "output_type": "row",
            "destructive": False, "inputs": [],
        }]),
        caller=caller, command_id=str(_uuid.uuid4()),
    )
    execute_host_operation(
        authority, "probe.read", {}, caller=caller,
        command_id=str(_uuid.uuid4()), invoker=lambda op, args: {"rows": 0},
    )
    level = read_scope_level(authority, scope, scope_root=scope, caller=caller)
    place_composition(
        authority, scope, sorted(level.composition_roots)[0],
        {"x": 12.0, "y": 34.0}, caller=caller, command_id=str(_uuid.uuid4()),
    )
    database = built.location.database_path
    authority.store.close()

    connection = sqlite3.connect(database)
    try:
        tables = {
            row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        # The journal, the current index, and the revision chain. Nothing
        # else may hold meaning: a fourth table is a second shape.
        assert tables == {"revisions", "cell_versions", "current_cells"}, (
            "the store grew a table beside the Cell journal: %s"
            % sorted(tables - {"revisions", "cell_versions", "current_cells"})
        )
        for table in ("cell_versions", "current_cells"):
            columns = {
                row[1] for row in connection.execute(
                    "PRAGMA table_info(%s)" % table
                )
            }
            assert {"cell_id", "link0", "link1", "atom"} <= columns, (
                "%s stopped holding the four Cell fields" % table
            )
            extra = columns - {"cell_id", "link0", "link1", "atom", "revision"}
            assert not extra, (
                "%s grew fields beside the Cell shape: %s" % (table, sorted(extra))
            )
        held = connection.execute("SELECT COUNT(*) FROM current_cells").fetchone()[0]
        assert held > 0
    finally:
        connection.close()


def test_the_inspector_has_no_dead_tab(tmp_path):
    """Every panel the inspector offers shows something the graph holds.

    SPEC court 11 asks that panels and editors are graph-projected and no
    tab is dead. A dead tab is worse than a missing one: it tells the
    founder there is something there and then shows nothing, and it looks
    identical to a panel whose data failed to load.

    This session found exactly that failure once already -- rows rendered
    an empty box over a value the graph was holding, because the row never
    said whether its value varied. So each declared panel is checked for a
    descriptor, and the selected node's rows are checked for their values.
    """
    built, _provider = _provision_clean_runtime(tmp_path)
    try:
        authority = built.location.authority
        canvas, lens, _s, _a = _project_current_visual(built)
        inspector = canvas["inspector"]
        panels = inspector["presentation"]["panels"]
        assert panels, "the inspector offers no panel at all"
        # The lenses are tabs too, and a lens with no name is a tab that
        # says nothing.
        for lens_entry in inspector["lenses"]:
            assert lens_entry["label"], "a visibility lens is offered with no name"

        for panel in panels:
            assert panel["label"], "a panel is offered with no name"
            assert panel["components"], (
                "panel %r is offered with nothing in it" % panel["label"]
            )
            for component in panel["components"]:
                assert component["descriptor"], (
                    "panel %r has a component that renders nothing"
                    % panel["label"]
                )
            assert panel["applicability_root"] in authority.store.snapshot().cells, (
                "panel %r is not declared by anything in the graph"
                % panel["label"]
            )
        assert sum(1 for panel in panels if panel["active"]) == 1, (
            "exactly one panel may be the one in front"
        )
    finally:
        built.location.authority.store.close()


def test_an_effect_and_its_receipt_survive_conflict_and_restart(tmp_path):
    """A run that happened stays happened, and is readable afterwards.

    SPEC court 15 asks for independent states, receipts, reconciliation,
    conflicts, recovery. The dangerous half is the one nobody sees: an
    effect reaches a machine, the process dies, and the graph has no idea
    whether it ran. Then someone retries and the building is changed
    twice.

    So a real effect is committed, the store is closed and reopened from
    disk, and the same command is replayed against the recovered graph.
    The receipt must still be there, and the host must not be asked again.
    """
    import uuid as _uuid

    from nodelang.cell_secret_keys import MemorySigningKeyProvider
    from nodelang.clean_host_execution import execute_host_operation
    from nodelang.clean_host_operations import (
        compose_host_operations, install_host_operations,
    )
    from nodelang.unified_authority_runtime import open_current_authority

    built, provider = _provision_clean_runtime(tmp_path)
    authority = built.location.authority
    caller = built.caller
    install_host_operations(
        authority,
        compose_host_operations([{
            "op_id": "probe.touch", "host": "probe", "kind": "action",
            "label": "Touch", "description": "", "output_type": "row",
            "destructive": False, "inputs": [],
        }]),
        caller=caller, command_id=str(_uuid.uuid4()),
    )

    reached = []
    command = str(_uuid.uuid4())
    done = execute_host_operation(
        authority, "probe.touch", {}, caller=caller, command_id=command,
        invoker=lambda op, args: reached.append(op) or {"ok": True},
    )
    assert reached == ["probe.touch"]
    receipt_root = done.receipt_root
    effect_root = done.root_id
    revision = authority.store.snapshot().revision
    root_path = built.location.root
    # The process dies here, exactly as it would mid-run.
    authority.store.close()

    reopened = open_current_authority(root_path, provider)
    try:
        recovered = reopened.authority.store.snapshot()
        assert recovered.revision == revision, "recovery moved the graph"
        assert receipt_root in recovered.cells, (
            "the receipt for a run that happened did not survive the restart"
        )
        assert effect_root in recovered.cells, (
            "the effect a run produced did not survive the restart"
        )

        # The retry a frightened operator would make. It must answer from
        # the receipt, not from the host.
        replayed = execute_host_operation(
            reopened.authority, "probe.touch", {},
            caller=built.caller_for(reopened.authority)
            if hasattr(built, "caller_for") else caller,
            command_id=command,
            invoker=lambda op, args: reached.append(op) or {"ok": True},
        )
        assert reached == ["probe.touch"], (
            "a replayed effect reached the host a second time"
        )
        assert replayed.replayed is True
        assert replayed.receipt_root == receipt_root
        assert reopened.authority.store.snapshot().revision == revision, (
            "a replay must not move the graph"
        )
    finally:
        reopened.authority.store.close()


def test_no_declared_operation_is_a_dead_button():
    """What the catalogue offers is exactly what an adapter can carry out.

    A button that refuses is worse than a button that is absent. The
    person who pressed it now has to work out whether their model is
    wrong, their session is wrong, or the program never could do this at
    all -- and only the last one is true. This is how a working program
    becomes a demo: not by breaking, but by offering.

    So the two sides are held equal in both directions. Nothing may be
    declared without an adapter behind it, and no adapter may hold a
    script for something the catalogue never declared, because power
    nobody declared is power nobody reviewed.
    """
    from nodelang import clean_office_adapter, clean_revit_adapter
    from nodelang.clean_host_catalogue_source import HOST_OPERATION_RECORDS
    from nodelang.clean_host_operations import compose_host_operations

    catalogue = compose_host_operations(HOST_OPERATION_RECORDS)
    declared = {str(entry["op_id"]) for entry in catalogue["operations"]}
    carried_out = (
        set(clean_revit_adapter._READS)
        | set(clean_office_adapter._OPEN_READS)
        | set(clean_office_adapter._INSIDE_READS)
    )
    assert declared, "the catalogue declares nothing at all"
    assert not (declared - carried_out), (
        "declared with no adapter behind it: %s"
        % sorted(declared - carried_out)
    )
    assert not (carried_out - declared), (
        "an adapter carries out what the catalogue never declared: %s"
        % sorted(carried_out - declared)
    )

    for entry in catalogue["operations"]:
        assert entry["kind"] == "read", (
            "%s is declared as %r; this build offers reads only"
            % (entry["op_id"], entry["kind"])
        )
        assert entry["destructive"] is False, (
            "%s is a read and must not be marked destructive"
            % entry["op_id"]
        )
        assert str(entry["label"]).strip(), (
            "%s has no label to show" % entry["op_id"]
        )
        assert str(entry["description"]).strip(), (
            "%s has no description to show" % entry["op_id"]
        )

    # Which machine a host reaches is named where the runtime is stood
    # up, not here. What this court can hold is that the catalogue never
    # names a host the adapters cannot answer for -- proven above by the
    # two sets being equal, operation by operation.
    assert set(catalogue["hosts"]) == {
        str(entry["op_id"]).split(".", 1)[0]
        for entry in catalogue["operations"]
    }


def test_the_operation_catalogue_can_be_revised_not_only_declared(tmp_path):
    """Adding an operation revises the catalogue on the graph.

    This is the whole claim the catalogue makes for itself: that what the
    runtime can do is graph state, so extending it is a revision rather
    than an edit-and-redeploy. The declare path was exercised constantly
    and the revise path never was, and it did not work at all -- it
    raised before it wrote. A branch nobody runs is a branch nobody has.

    So: install, install again with more, and read back what the graph
    then says the runtime can do.
    """
    import uuid as _uuid

    from nodelang.clean_host_operations import (
        compose_host_operations, install_host_operations, read_host_operations,
    )

    built, _provider = _provision_clean_runtime(tmp_path)
    authority = built.location.authority
    caller = built.caller

    def record(op_id):
        return {
            "op_id": op_id, "host": op_id.split(".", 1)[0], "kind": "read",
            "label": op_id, "description": "d", "output_type": "row",
            "destructive": False, "inputs": [],
        }

    first = install_host_operations(
        authority, compose_host_operations([record("probe.one")]),
        caller=caller, command_id=str(_uuid.uuid4()),
    )
    assert len(read_host_operations(authority, caller=caller)["operations"]) == 1

    # The same catalogue again must not churn the graph.
    steady = authority.store.snapshot().revision
    again = install_host_operations(
        authority, compose_host_operations([record("probe.one")]),
        caller=caller, command_id=str(_uuid.uuid4()),
    )
    assert again == first
    assert authority.store.snapshot().revision == steady, (
        "installing an unchanged catalogue moved the graph"
    )

    # And now the branch that had never run.
    revised = install_host_operations(
        authority,
        compose_host_operations([record("probe.one"), record("probe.two")]),
        caller=caller, command_id=str(_uuid.uuid4()),
    )
    assert revised == first, "revising the catalogue moved it to a new root"
    held = read_host_operations(authority, caller=caller)
    assert [entry["op_id"] for entry in held["operations"]] == [
        "probe.one", "probe.two",
    ]
    assert authority.store.snapshot().revision > steady

def test_a_definition_with_nothing_to_compose_can_be_placed(tmp_path):
    """A library card is placeable unless it has participants to choose.

    The client routes a catalogue entry by one fact: whether it carries a
    composition contract. With a contract it goes to the relation
    composer, which demands a placement interaction that is only ever
    bound for entries WITHOUT one. Stamping a contract on every entry
    therefore satisfied both halves of a contradiction and produced a
    library where not one card could be placed -- no error at load, no
    missing button, just a refusal on every click.

    So: an ordinary definition declares no interfaces and must project no
    contract, and a definition that declares interfaces must project one.
    """
    from nodelang.clean_visual_projection import _catalog_projection

    def entry(name, interfaces):
        return {
            "id": "def-" + name, "name": name, "version": "1",
            "kind": "published", "parameters": {}, "interfaces": interfaces,
            "presentation": {"label": name},
        }

    place_control = {
        "owner": "app:control:library:place",
        "title": "Place on canvas",
        "icon": "app:icon:lucide:plus",
        "activation": {
            "binding": "app:control-binding:library:place",
            "capability": "app:device-capability:instantiate",
        },
    }
    projected = _catalog_projection(
        [
            entry("List worksets", {}),
            entry("Relation", {"left": {"direction": "input"}}),
        ],
        place_control,
    )
    by_name = {item["name"]: item for item in projected}
    assert by_name["List worksets"]["composition_contract"] is None, (
        "a definition with no participants was routed to the relation "
        "composer, where it cannot be placed"
    )
    assert by_name["Relation"]["composition_contract"] == {
        "root": "def-Relation"
    }

def test_every_published_definition_is_placeable_in_the_scope_shown(tmp_path):
    """A card in the library has a placement interaction where it is shown.

    The interaction set is computed from the definitions published at the
    moment it is installed, and it binds them per scope. Publish a
    definition afterwards, or install the set walking from a root that is
    not the one the canvas opens on, and the library fills with cards the
    graph declared no way to place. Nothing errors: the buttons render,
    and every click is discarded.

    The canvas scope is therefore the subject here -- not some scope, the
    one being shown -- and the claim is coverage: every published
    definition offered in that scope can be placed in it.
    """
    import uuid as _uuid

    from nodelang.clean_scope_interactions import (
        open_clean_scope_interactions, revise_clean_scope_interactions,
    )
    from nodelang.unified_authority import declare_definition, promote_definition

    built, _provider = _provision_clean_runtime(tmp_path)
    authority = built.location.authority
    caller = built.caller
    scope = built.grand_map.root_id

    def publish(name):
        declared = declare_definition(
            authority, name, {}, caller=caller,
            command_id=str(_uuid.uuid4()), version="1",
            presentation={"label": name, "icon": "play"},
        )
        shared = promote_definition(
            authority, declared.root_id, target_lifecycle="shared",
            version="1-shared", evidence_roots=(declared.receipt_root,),
            caller=caller, command_id=str(_uuid.uuid4()),
        )
        promote_definition(
            authority, declared.root_id, target_lifecycle="published",
            version="1-published", evidence_roots=(shared.receipt_root,),
            caller=caller, command_id=str(_uuid.uuid4()),
        )
        return declared.root_id

    # The runtime is provisioned with a set already installed, which is
    # exactly the situation a growing catalogue is always in.
    first = publish("Placeable one")
    revise_clean_scope_interactions(
        authority, built.browser, scope,
        caller=caller, command_id=str(_uuid.uuid4()),
    )
    held = open_clean_scope_interactions(authority, caller=caller)
    bound = set(held.bindings.get(scope, {}))
    assert scope in held.bindings, (
        "the scope the canvas opens on carries no interactions at all"
    )
    assert first in bound, (
        "a published definition has no way to be placed in the scope that "
        "shows it"
    )

    # Publishing after the set was installed is the ordinary case: a
    # catalogue grows. The set must be revisable to cover it, or every
    # card added from then on is a button that does nothing.
    second = publish("Placeable two")
    revise_clean_scope_interactions(
        authority, built.browser, scope,
        caller=caller, command_id=str(_uuid.uuid4()),
    )
    revised = open_clean_scope_interactions(authority, caller=caller)
    bound_after = set(revised.bindings.get(scope, {}))
    assert first in bound_after and second in bound_after, (
        "revising did not cover both definitions: %s"
        % sorted({first, second} - bound_after)
    )

def test_an_effect_says_which_node_asked_for_it(tmp_path):
    """A run started from a node is recorded against that node.

    Without it the graph holds the answer and no record of what asked the
    question: the rows exist, and nothing can show a node what it last
    returned. The result is present and unreachable, which reads to the
    person at the canvas exactly like a run that did nothing.

    The subject also separates two requests. The same operation run for
    two different nodes is two different questions, so replaying one must
    never answer for the other -- the guard on that is the subject being
    part of the request digest, and it is checked here by reusing one
    command identity across two subjects.
    """
    import uuid as _uuid

    from nodelang.clean_host_execution import execute_host_operation
    from nodelang.clean_host_operations import (
        compose_host_operations, install_host_operations,
    )
    from nodelang.unified_authority import (
        InvalidCell, _decode_data_value, relation_members,
    )

    def effect_record(root):
        """Read back the contract an effect carries, key by key."""
        snapshot = authority.store.snapshot()
        presentation = next(
            member.participant_id
            for member in relation_members(snapshot, root)
            if member.role_id == authority.role("presentation")
        )
        held = {}
        for member in relation_members(snapshot, presentation):
            if member.role_id != authority.role("property"):
                continue
            parts = relation_members(snapshot, member.participant_id)
            name = next(
                _decode_data_value(authority, snapshot, inner.participant_id)
                for inner in parts
                if inner.role_id == authority.role("name")
            )
            value = next(
                _decode_data_value(authority, snapshot, inner.participant_id)
                for inner in parts
                if inner.role_id == authority.role("value")
            )
            held[str(name)] = value
        return held

    built, _provider = _provision_clean_runtime(tmp_path)
    authority = built.location.authority
    caller = built.caller
    install_host_operations(
        authority,
        compose_host_operations([{
            "op_id": "probe.read", "host": "probe", "kind": "read",
            "label": "Read", "description": "d", "output_type": "row",
            "destructive": False, "inputs": [],
        }]),
        caller=caller, command_id=str(_uuid.uuid4()),
    )

    node = "node-" + str(_uuid.uuid4())
    done = execute_host_operation(
        authority, "probe.read", {}, caller=caller,
        command_id=str(_uuid.uuid4()),
        invoker=lambda op, args: {"rows": 3},
        subject_root=node,
    )
    held = effect_record(done.root_id)
    assert held["subject"] == node, (
        "the effect does not say which node ran it: %r" % (held,)
    )

    # One command identity, two subjects: the second is a different
    # request and must not be answered from the first receipt.
    shared = str(_uuid.uuid4())
    execute_host_operation(
        authority, "probe.read", {}, caller=caller, command_id=shared,
        invoker=lambda op, args: {"rows": 1}, subject_root="node-a",
    )
    try:
        execute_host_operation(
            authority, "probe.read", {}, caller=caller, command_id=shared,
            invoker=lambda op, args: {"rows": 1}, subject_root="node-b",
        )
    except InvalidCell as exc:
        assert "idempotency" in str(exc).lower()
    else:
        raise AssertionError(
            "a replay for one node answered with another node's receipt"
        )


def test_a_node_shows_what_it_returned_and_not_what_another_node_did(tmp_path):
    """The last run of a node is found, and only that node's run.

    A receipt names the node that asked for it, and every receipt the
    graph signs hangs off the history root in signing order. Reading
    backwards therefore answers "what did this node last return" using
    the only direction relations walk -- no index, no new relation.

    Two nodes run the same operation here, because that is the case a
    subject check exists for: without it the newest receipt wins and a
    node confidently shows another node's rows, which is worse than
    showing nothing.
    """
    import uuid as _uuid

    from nodelang.clean_host_execution import execute_host_operation
    from nodelang.clean_host_operations import (
        compose_host_operations, install_host_operations,
    )
    from nodelang.clean_visual_projection import latest_run_rows

    built, _provider = _provision_clean_runtime(tmp_path)
    authority = built.location.authority
    caller = built.caller
    install_host_operations(
        authority,
        compose_host_operations([{
            "op_id": "probe.rows", "host": "probe", "kind": "read",
            "label": "Rows", "description": "d", "output_type": "row",
            "destructive": False, "inputs": [],
        }]),
        caller=caller, command_id=str(_uuid.uuid4()),
    )

    first, second = "node-first", "node-second"
    execute_host_operation(
        authority, "probe.rows", {}, caller=caller,
        command_id=str(_uuid.uuid4()), subject_root=first,
        invoker=lambda op, args: {"result": [{"name": "alpha"}]},
    )
    # The second run is newer, so a reader that ignored the subject would
    # hand these rows to the first node.
    execute_host_operation(
        authority, "probe.rows", {}, caller=caller,
        command_id=str(_uuid.uuid4()), subject_root=second,
        invoker=lambda op, args: {"result": [{"name": "beta"}, {"name": "gamma"}]},
    )

    snapshot = authority.store.snapshot()
    operation, rows, returned = latest_run_rows(authority, snapshot, first)
    assert operation == "probe.rows"
    assert [row["name"] for row in rows] == ["alpha"], (
        "a node was shown another node's rows: %s" % (rows,)
    )
    operation, rows, returned = latest_run_rows(authority, snapshot, second)
    assert [row["name"] for row in rows] == ["beta", "gamma"]

    # A node nobody has run reads as no run, rather than as the newest
    # run belonging to somebody else.
    operation, rows, returned = latest_run_rows(authority, snapshot, "node-never-run")
    assert (operation, rows, returned) == ("", [], 0)

    # The walk is bounded, so a node whose run has scrolled out of the
    # bound reads as no run instead of getting slower forever.
    operation, rows, returned = latest_run_rows(authority, snapshot, first, limit=1)
    assert (operation, rows, returned) == ("", [], 0)

def test_a_result_row_shows_every_field_the_host_returned():
    """A row is shown whole, in a stable order, with nothing promoted.

    This build cannot tell a workset from a sheet and should not try. The
    shape of an answer belongs to the host that gave it, so choosing
    which fields to show would be inventing a schema no host stated --
    and the field left out is always the one somebody needed.

    Stability matters as much as completeness: rows arriving with their
    keys in a different order must read the same way down the panel, or
    the same data looks like different data.
    """
    from nodelang.clean_visual_projection import _row_line

    row = {
        "editable": True, "id": 0, "name": "Workset1",
        "open": True, "owner": "ahmed.fargaly",
    }
    line = _row_line(row)
    for key, value in row.items():
        assert ("%s: %s" % (key, value)) in line, (
            "the row dropped %r, which some host thought worth returning"
            % key
        )

    # The same row with its keys in another order reads identically.
    shuffled = {
        "owner": "ahmed.fargaly", "name": "Workset1", "open": True,
        "id": 0, "editable": True,
    }
    assert _row_line(shuffled) == line, (
        "key order changed how the row reads: %r vs %r"
        % (_row_line(shuffled), line)
    )

    # A field this build has never heard of is shown like any other.
    exotic = _row_line({"zeta": 1, "alpha": "x"})
    assert exotic.index("alpha") < exotic.index("zeta")
    assert "zeta: 1" in exotic

def test_publishing_a_card_without_binding_it_is_detectable(tmp_path):
    """A published card nobody can place must be findable before a click.

    This is the trap that produced dead buttons twice in one night, and
    it is invisible by construction: publishing succeeds, the library
    lists the card, and nothing is wrong until somebody presses it. The
    graph knows both facts -- what is published, and what is bound -- and
    the gap between them is the answer.

    So the check is courted from the failing side first. A definition
    published and not yet bound must be REPORTED, because a check that
    only ever returns an empty tuple would pass forever while the canvas
    filled with cards that refuse.
    """
    import uuid as _uuid

    from nodelang.clean_scope_interactions import (
        revise_clean_scope_interactions, unbound_published_definitions,
    )
    from nodelang.unified_authority import declare_definition, promote_definition

    built, _provider = _provision_clean_runtime(tmp_path)
    authority = built.location.authority
    caller = built.caller
    scope = built.grand_map.root_id

    assert unbound_published_definitions(
        authority, scope, caller=caller
    ) == (), "the provisioned runtime already has cards nobody can place"

    declared = declare_definition(
        authority, "Unbound card", {}, caller=caller,
        command_id=str(_uuid.uuid4()), version="1",
        presentation={"label": "Unbound card", "icon": "play"},
    )
    shared = promote_definition(
        authority, declared.root_id, target_lifecycle="shared",
        version="1-shared", evidence_roots=(declared.receipt_root,),
        caller=caller, command_id=str(_uuid.uuid4()),
    )
    promote_definition(
        authority, declared.root_id, target_lifecycle="published",
        version="1-published", evidence_roots=(shared.receipt_root,),
        caller=caller, command_id=str(_uuid.uuid4()),
    )

    # Published, listed, and unplaceable. The check must say so.
    assert declared.root_id in unbound_published_definitions(
        authority, scope, caller=caller
    ), "a card that cannot be placed was reported as fine"

    revise_clean_scope_interactions(
        authority, built.browser, scope,
        caller=caller, command_id=str(_uuid.uuid4()),
    )
    assert unbound_published_definitions(
        authority, scope, caller=caller
    ) == (), "revising did not make the published card placeable"

def test_a_run_that_answers_with_too_much_is_capped_and_says_so(tmp_path):
    """A large answer is bounded, and the graph records that it was.

    A row costs about fifty cells to persist, so a read that finds eight
    thousand of something writes four hundred thousand cells on one
    press. That is not a hypothetical: a card in the library did exactly
    that and the runtime died mid-audit, having answered three questions
    and then nothing.

    Capping alone would be worse than the crash. A graph that quietly
    held the first thousand rows while reading exactly like a graph
    holding all eight thousand gives a confident wrong answer to every
    later question, and nobody knows to doubt it. So both numbers are
    recorded, and the court checks the honesty as hard as the bound.
    """
    import uuid as _uuid

    from nodelang.clean_host_execution import (
        PERSISTED_ROW_LIMIT, execute_host_operation,
    )
    from nodelang.clean_host_operations import (
        compose_host_operations, install_host_operations,
    )
    from nodelang.unified_authority import _decode_data_value, relation_members

    built, _provider = _provision_clean_runtime(tmp_path)
    authority = built.location.authority
    caller = built.caller
    install_host_operations(
        authority,
        compose_host_operations([{
            "op_id": "probe.many", "host": "probe", "kind": "read",
            "label": "Many", "description": "d", "output_type": "row",
            "destructive": False, "inputs": [],
        }]),
        caller=caller, command_id=str(_uuid.uuid4()),
    )

    def fields(root):
        snapshot = authority.store.snapshot()
        presentation = next(
            m.participant_id for m in relation_members(snapshot, root)
            if m.role_id == authority.role("presentation")
        )
        held = {}
        for member in relation_members(snapshot, presentation):
            if member.role_id != authority.role("property"):
                continue
            parts = relation_members(snapshot, member.participant_id)
            key = next(
                _decode_data_value(authority, snapshot, p.participant_id)
                for p in parts if p.role_id == authority.role("name")
            )
            held[str(key)] = next(
                _decode_data_value(authority, snapshot, p.participant_id)
                for p in parts if p.role_id == authority.role("value")
            )
        return held

    oversized = PERSISTED_ROW_LIMIT + 500
    done = execute_host_operation(
        authority, "probe.many", {}, caller=caller,
        command_id=str(_uuid.uuid4()),
        invoker=lambda op, args: {
            "result": [{"id": index} for index in range(oversized)]
        },
    )
    held = fields(done.root_id)
    assert held["rows_returned"] == oversized, (
        "the graph forgot how many rows the host actually found"
    )
    assert held["rows_recorded"] == PERSISTED_ROW_LIMIT
    assert len(held["outcome"]["result"]) == PERSISTED_ROW_LIMIT, (
        "the cap did not hold; one press can still flood the graph"
    )

    # An ordinary answer is untouched, and says so plainly.
    small = execute_host_operation(
        authority, "probe.many", {}, caller=caller,
        command_id=str(_uuid.uuid4()),
        invoker=lambda op, args: {"result": [{"id": 1}, {"id": 2}]},
    )
    held = fields(small.root_id)
    assert held["rows_returned"] == 2 and held["rows_recorded"] == 2
    assert len(held["outcome"]["result"]) == 2

def test_a_capped_result_says_what_it_left_out_where_it_is_read():
    """The panel that shows the rows is where the missing ones are named.

    Capping is recorded in the graph, which protects later reasoning but
    not the person looking at a list. A panel showing a thousand rows and
    reading exactly like a panel showing all eight thousand is the same
    confident wrong answer, just delivered to a human instead of a query.

    So the summary carries both numbers whenever they differ, and carries
    neither pretence nor apology when they do not.
    """
    from nodelang.clean_visual_projection import _run_summary

    capped = _run_summary("revit.list_materials", 1000, 8121)
    assert "1000" in capped and "8121" in capped, (
        "a capped run reads like a whole one: %r" % capped
    )
    assert "revit.list_materials" in capped

    whole = _run_summary("revit.list_floors", 219, 219)
    assert "219" in whole
    assert "showing" not in whole, (
        "an answer that was not capped implied it was: %r" % whole
    )

    # A node that has never run states nothing rather than zero of zero.
    assert _run_summary("", 0, 0) is None

def test_rebinding_cannot_silently_rewrite_the_whole_graph(tmp_path):
    """A revise that would write a million cells says so instead.

    Revising the interaction set rewrites every binding for every scope,
    so its cost tracks the whole catalogue rather than what changed. Four
    of these took a 654 MB graph to 2.3 GB and a two-minute start to
    thirteen minutes, and each one reported success in a second or two --
    the damage only shows up at the NEXT boot, which is the worst place
    for a cost to appear.

    Nothing else in this system can write a million cells on one call.
    The ceiling is not a fix for the shape; it is the thing that makes
    the shape impossible to pay for by accident.
    """
    import uuid as _uuid

    from nodelang.clean_scope_interactions import (
        revise_clean_scope_interactions, unbound_published_definitions,
    )
    from nodelang.unified_authority import (
        InvalidCell, declare_definition, promote_definition,
    )

    built, _provider = _provision_clean_runtime(tmp_path)
    authority = built.location.authority
    caller = built.caller
    scope = built.grand_map.root_id

    declared = declare_definition(
        authority, "Ceiling probe", {}, caller=caller,
        command_id=str(_uuid.uuid4()), version="1",
        presentation={"label": "Ceiling probe", "icon": "play"},
    )
    shared = promote_definition(
        authority, declared.root_id, target_lifecycle="shared",
        version="1-shared", evidence_roots=(declared.receipt_root,),
        caller=caller, command_id=str(_uuid.uuid4()),
    )
    promote_definition(
        authority, declared.root_id, target_lifecycle="published",
        version="1-published", evidence_roots=(shared.receipt_root,),
        caller=caller, command_id=str(_uuid.uuid4()),
    )

    # A ceiling of nothing refuses, and the refusal states the real cost
    # rather than a generic complaint.
    try:
        revise_clean_scope_interactions(
            authority, built.browser, scope,
            caller=caller, command_id=str(_uuid.uuid4()), cell_limit=0,
        )
    except InvalidCell as exc:
        assert "cells" in str(exc), exc
        assert "limit" in str(exc), exc
    else:
        raise AssertionError("a rebind of any size was permitted")

    # Refusing must not half-write: the card is still unplaceable, which
    # is a worse state to be silent about than to be stopped in.
    assert declared.root_id in unbound_published_definitions(
        authority, scope, caller=caller
    )

    # And a caller who accepts the cost deliberately still gets it.
    revise_clean_scope_interactions(
        authority, built.browser, scope,
        caller=caller, command_id=str(_uuid.uuid4()), cell_limit=None,
    )
    assert unbound_published_definitions(
        authority, scope, caller=caller
    ) == ()

def test_rebinding_unchanged_bindings_writes_almost_nothing(tmp_path):
    """Revising with nothing new to bind must not rewrite the graph.

    Identity used to be minted, so every rebind produced a fresh uuid for
    the event, for each interaction and for each entry -- and a binding
    that had not changed was written again as new cells. One rebind on the
    founder graph wrote 1,133,504 of them, four of them made a 654 MB
    graph 2.3 GB, and the bill only arrives at the next start.

    A binding is fully determined by its scope, control, target and
    capability. Two revises over the same bindings therefore produce the
    same cells, and cells the graph already holds are not written again.
    """
    import uuid as _uuid

    from nodelang.clean_scope_interactions import (
        revise_clean_scope_interactions, unbound_published_definitions,
    )
    from nodelang.unified_authority import declare_definition, promote_definition

    built, _provider = _provision_clean_runtime(tmp_path)
    authority = built.location.authority
    caller = built.caller
    scope = built.grand_map.root_id

    def publish(name):
        declared = declare_definition(
            authority, name, {}, caller=caller,
            command_id=str(_uuid.uuid4()), version="1",
            presentation={"label": name, "icon": "play"},
        )
        shared = promote_definition(
            authority, declared.root_id, target_lifecycle="shared",
            version="1-shared", evidence_roots=(declared.receipt_root,),
            caller=caller, command_id=str(_uuid.uuid4()),
        )
        promote_definition(
            authority, declared.root_id, target_lifecycle="published",
            version="1-published", evidence_roots=(shared.receipt_root,),
            caller=caller, command_id=str(_uuid.uuid4()),
        )

    publish("Rebind probe")
    before = authority.store.snapshot().revision
    revise_clean_scope_interactions(
        authority, built.browser, scope,
        caller=caller, command_id=str(_uuid.uuid4()), cell_limit=None,
    )
    first = authority.store.snapshot().revision
    assert unbound_published_definitions(authority, scope, caller=caller) == ()

    def written(from_revision, to_revision):
        store = authority.store
        return sum(
            len(store.at(r).cells) - len(store.at(r - 1).cells)
            for r in range(from_revision + 1, to_revision + 1)
        )

    grew_binding = written(before, first)

    # Nothing has changed since, so a second revise has nothing to write.
    # It is refused as a no-op, which is the honest answer -- or it writes
    # far less than the first did, never the same again.
    try:
        revise_clean_scope_interactions(
            authority, built.browser, scope,
            caller=caller, command_id=str(_uuid.uuid4()), cell_limit=None,
        )
    except Exception as exc:
        assert "already carry this source" in str(exc), exc
    else:
        second = authority.store.snapshot().revision
        grew_again = written(first, second)
        assert grew_again <= max(64, grew_binding // 4), (
            "rebinding unchanged bindings still rewrote the graph: "
            "%d cells against %d for the first bind"
            % (grew_again, grew_binding)
        )