"""The visible application canvas is a lens over universal Cells."""
from html.parser import HTMLParser
import pytest
import nodelang.cell_agent_body as agent_body_module
import nodelang.universal_application as universal_application_module

from nodelang.cell_authorization import (
	AuthorizationDenied,
	AuthorizationRequest,
	require_authorization,
)
from nodelang.cell_change_history import read_change_transaction
from nodelang.cell_interactions import InteractionProjectionBroker
from nodelang.cell_design_tokens import (
	SYSTEM_ROOT as DESIGN_TOKEN_SYSTEM_ROOT,
	ensure_archhub_design_token_system,
	project_dtcg_format,
)
from nodelang.cell_reactions import ReactionEngine, reaction_events
from nodelang.cell_protocols import (
	compose_relation_cells,
	prepare_append_relation_members,
	read_relation,
)
from nodelang.cell_roma_requirements import roma_node_root, roma_tree_root
from nodelang.map_import import resolve_map_path
from nodelang.universal_application import (
	CAPABILITY_EDIT_VALUE,
	apply_universal_canvas_gesture,
	assign_released_universal_theme_to_audience,
	assign_shared_universal_theme,
	build_universal_application,
	connect_universal_roots,
	disconnect_universal_connection,
	create_universal_governed_work,
	create_universal_interface,
	create_universal_interfaces,
	create_universal_property,
	edit_universal_cell_atom,
	edit_universal_interface_collection,
	edit_universal_lifecycle_content,
	edit_universal_property,
	ensure_universal_property_interactions,
	follow_universal_theme_audience,
	group_universal_selection,
	move_universal_root,
	preview_universal_presentation_color,
	preview_universal_theme,
	promote_universal_resource_lifecycle,
	promote_universal_theme_to_shared,
	project_universal_canvas,
	project_universal_grand_map_work,
	project_universal_roma_requirement_tree,
	project_universal_governed_work_index,
	project_universal_governed_work_status,
	provision_universal_view_session,
	read_universal_theme,
	restore_universal_theme_revision,
	reset_universal_presentation_color,
	instantiate_universal_definition,
	instantiate_universal_primitive,
	instantiate_universal_relation_definition,
	issue_universal_authority_relationship,
	merge_universal_lifecycle_content,
	rewire_universal_connection,
	redo_universal_change,
	revoke_universal_authority_relationship,
	select_universal_root,
	set_universal_inspector_lens,
	set_universal_properties_panel,
	set_universal_scope,
	set_universal_selection,
	submit_universal_edit_value_interaction,
	sync_universal_grand_map_work,
	sync_universal_roma_requirement_tree,
	ungroup_universal_composition,
	undo_universal_change,
)
from nodelang.cell_identity import (
	read_authority_relationship,
	verify_authority_relationship,
)
from nodelang.cell_attestations import read_court_attestation
from nodelang.cell_replay_policy_authority import (
	PublishedProofReplayPolicyVerifier,
)
from nodelang.cell_lifecycle import (
	read_lifecycle_instance,
	read_revision,
	state_heads,
)
from nodelang.cell_value_graph import read_value_graph
from nodelang.cell_tenant_authority import (
	PublishedTenantAdmissionVerifier,
	TenantAuthorityDenied,
)
from nodelang.cell_cloud_routes import find_cloud_route, resolve_cloud_route
from nodelang.universal_cell import (
	NULL_CELL_ID,
	Cell,
	Conflict,
	InvalidCell,
)
from nodelang.universal_view import project_universal_document
from nodelang.cell_authority_view import AUTHORITY_LIST_TEMPLATE_ROOT
from nodelang.cell_view_template import render_view_template


@pytest.fixture(scope="module")
def application():
	return build_universal_application(resolve_map_path())


def test_design_system_projects_the_cell_native_icon_catalog(application):
	store, registry = application
	projection = project_universal_canvas(store, registry)
	icons = projection["configuration"]["design_system"]["icon_catalog"]
	assert icons["root"] == registry.icon_catalog_root
	assert icons["source"] == {
		"root": registry.icon_source_root,
		"package": "lucide-static",
		"version": "1.25.0",
		"license": "ISC",
		"homepage": "https://lucide.dev",
		"repository": "https://github.com/lucide-icons/lucide.git",
		"source_sha256": "03aa38fc8e15ef5a50bae81ba46071cd7faf93bbe71a3dd0744e54e651ef6cae",
		"selected_geometry_sha256": "3bb7ea074cb71c46dea70f996cf193839d6d3c863e8af61f98e4f3a59b612c27",
	}
	assert set(icons["icons"]) == set(registry.icon_roots)
	assert icons["icons"]["plus"]["root"] == registry.icon_roots["plus"]
	assert icons["icons"]["plus"]["primitives"][0] == {
		"root": registry.icon_roots["plus"] + ":primitive:0",
		"tag": "path",
		"attributes": {"d": "M5 12h14"},
	}
	controls = projection["configuration"]["design_system"]["control_catalog"]
	assert controls["root"] == registry.control_catalog_root
	assert [control["owner"] for control in controls["controls"]] == [
		"app:control:rail:home",
		"app:control:rail:search",
		"app:control:rail:share",
		"app:control:rail:settings",
		"app:control:canvas:scope-up",
		"app:control:canvas:zoom-out",
		"app:control:canvas:zoom-in",
		"app:control:canvas:fit",
		"app:control:canvas:undo",
		"app:control:canvas:redo",
		"app:control:canvas:group",
		"app:control:canvas:ungroup",
		"app:control:inspector:add-interface",
		"app:control:inspector:add-property",
		"app:control:library:place",
	]
	assert all(control["icon"] in registry.icon_roots.values()
	           for control in controls["controls"])


def test_visible_controls_project_cell_native_activation_and_applicability(application):
	store, _registry = application
	projection = project_universal_canvas(store, _registry)
	controls = projection["configuration"]["design_system"]["control_catalog"][
		"controls"
	]
	assert len(controls) == 15
	for control in controls:
		assert control["activation"]["root"]
		assert control["activation"]["capability"]
		assert control["condition"]
		assert type(control["applicable"]) is bool
	by_owner = {control["owner"]: control for control in controls}
	assert by_owner["app:control:canvas:scope-up"]["applicable"] is False
	assert by_owner["app:control:canvas:undo"]["applicable"] is False
	assert by_owner["app:control:canvas:redo"]["applicable"] is False
	assert by_owner["app:control:canvas:group"]["applicable"] is False
	assert by_owner["app:control:canvas:ungroup"]["applicable"] is False


class _ClassParentParser(HTMLParser):
	_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input",
			 "link", "meta", "param", "source", "track", "wbr"}

	def __init__(self):
		super().__init__()
		self.stack = []
		self.parents = {}

	def handle_starttag(self, tag, attrs):
		attributes = dict(attrs)
		classes = set(attributes.get("class", "").split())
		parent_classes = self.stack[-1][1] if self.stack else frozenset()
		for class_name in classes:
			self.parents.setdefault(class_name, []).append(parent_classes)
		if tag not in self._VOID:
			self.stack.append((tag, frozenset(classes)))

	def handle_endtag(self, tag):
		for index in range(len(self.stack) - 1, -1, -1):
			if self.stack[index][0] == tag:
				del self.stack[index:]
				break


def test_application_canvas_and_map_are_compositions_in_one_uniform_store(application):
	store, registry = application
	assert store.revision > 2
	assert set(Cell.__dataclass_fields__) == {"id", "link0", "link1", "atom"}
	assert registry.application_root in store.snapshot().cells
	assert registry.canvas_root in store.snapshot().cells
	assert registry.properties_lens_root in store.snapshot().cells
	assert all(type(cell) is Cell for cell in store.snapshot().cells.values())


def test_application_stages_replay_policy_without_self_publishing(application):
	store, registry = application
	protocol = registry.cloud_session_protocol
	assert protocol.proof_replay_policy_lifecycle_root is not None
	lifecycle = registry.standard_library.lifecycle_protocol
	instance = read_lifecycle_instance(
		store.snapshot(),
		registry.assembly_protocol,
		lifecycle,
		protocol.proof_replay_policy_lifecycle_root,
	)
	wip_heads = state_heads(
		store.snapshot(),
		lifecycle,
		instance.state_pointers[lifecycle.states["wip"]],
	)
	assert len(wip_heads) == 1
	assert (
		read_revision(store.snapshot(), lifecycle, wip_heads[0]).content_root
		== protocol.proof_replay_policy_root
	)
	assert state_heads(
		store.snapshot(),
		lifecycle,
		instance.state_pointers[lifecycle.states["shared"]],
	) == ()
	assert state_heads(
		store.snapshot(),
		lifecycle,
		instance.state_pointers[lifecycle.states["published"]],
	) == ()
	verifier = PublishedProofReplayPolicyVerifier(
		registry.assembly_protocol,
		lifecycle,
		registry.attestation_protocol,
		registry.attestation_broker,
		registry.resource_lifecycle_court_root,
		protocol.proof_replay_policy_lifecycle_root,
	)
	with pytest.raises(InvalidCell, match="one Published revision"):
		verifier.verify(store.snapshot(), protocol)


def test_canvas_move_undo_and_redo_are_session_scoped_cell_transactions():
	store, registry = build_universal_application(resolve_map_path())
	view = registry.view_sessions[registry.authorization.subject_root]
	root = registry.visible_roots[0]
	position = registry.position_properties[root]
	x_root = position["position_x"].value_root
	y_root = position["position_y"].value_root
	original = (store.read(x_root).atom, store.read(y_root).atom)
	identity = frozenset(store.snapshot().cells)

	move_revision = move_universal_root(store, registry, root, 431.0, 287.0)
	assert move_revision == store.revision
	assert (store.read(x_root).atom, store.read(y_root).atom) == (b"431.0", b"287.0")
	transactions = read_relation(store.snapshot(), view.action_history_root)
	assert len(transactions) == 1
	assert transactions[0].role_id == registry.change_history_protocol.role(
		"transaction"
	)
	transaction = read_change_transaction(
		store.snapshot(),
		registry.change_history_protocol,
		transactions[0].participant_id,
	)
	assert transaction.authority_root == registry.composer_protocol.command(
		"canvas.arrange"
	)
	assert transaction.scope_roots == (root,)
	controls = {
		control["owner"]: control
		for control in project_universal_canvas(store, registry)["configuration"]
		["design_system"]["control_catalog"]["controls"]
	}
	assert controls["app:control:canvas:undo"]["applicable"] is True
	assert controls["app:control:canvas:redo"]["applicable"] is False

	undo_revision = undo_universal_change(store, registry)
	assert undo_revision == move_revision + 1
	assert (store.read(x_root).atom, store.read(y_root).atom) == original
	controls = {
		control["owner"]: control
		for control in project_universal_canvas(store, registry)["configuration"]
		["design_system"]["control_catalog"]["controls"]
	}
	assert controls["app:control:canvas:undo"]["applicable"] is False
	assert controls["app:control:canvas:redo"]["applicable"] is True

	redo_revision = redo_universal_change(store, registry)
	assert redo_revision == undo_revision + 1
	assert (store.read(x_root).atom, store.read(y_root).atom) == (b"431.0", b"287.0")
	assert identity.issubset(store.snapshot().cells)
	assert len(read_relation(store.snapshot(), view.action_history_root)) == 3


def test_primitive_creation_undo_and_redo_preserve_one_cell_identity():
	store, registry = build_universal_application(resolve_map_path())
	before = project_universal_canvas(store, registry)
	root, _ = instantiate_universal_primitive(
		store, registry, x=480, y=320, title="Recoverable Cell", atom="value"
	)
	created = project_universal_canvas(store, registry)
	assert any(node["id"] == root for node in created["nodes"])
	created_cells = frozenset(store.snapshot().cells)

	undo_universal_change(store, registry)
	undone = project_universal_canvas(store, registry)
	assert root in store.snapshot().cells
	assert all(node["id"] != root for node in undone["nodes"])
	assert {node["id"] for node in undone["nodes"]} == {
		node["id"] for node in before["nodes"]
	}

	redo_universal_change(store, registry)
	redone = project_universal_canvas(store, registry)
	restored = next(node for node in redone["nodes"] if node["id"] == root)
	assert restored["label"] == "Recoverable Cell"
	assert (float(restored["x"]), float(restored["y"])) == (480.0, 320.0)
	assert created_cells.issubset(store.snapshot().cells)


def test_group_undo_and_redo_preserve_members_wires_and_composition_identity():
	store, registry = build_universal_application(resolve_map_path())
	before = project_universal_canvas(store, registry)
	selected = tuple(node["id"] for node in before["nodes"][:2])
	wire_identity = {
		wire["id"]: (
			wire["source_incidence"], wire["target_incidence"],
			wire["source_interface"], wire["target_interface"],
		)
		for wire in before["wires"]
	}
	set_universal_selection(store, registry, selected, focus_root=selected[-1])
	composition_root, _ = group_universal_selection(
		store, registry, title="Recoverable composition"
	)
	grouped = project_universal_canvas(store, registry)
	assert composition_root in {node["id"] for node in grouped["nodes"]}
	assert set(selected).isdisjoint(node["id"] for node in grouped["nodes"])
	created_cells = frozenset(store.snapshot().cells)

	undo_universal_change(store, registry)
	undone = project_universal_canvas(store, registry)
	assert composition_root in store.snapshot().cells
	assert composition_root not in {node["id"] for node in undone["nodes"]}
	assert tuple(node["id"] for node in undone["nodes"]) == tuple(
		node["id"] for node in before["nodes"]
	)
	assert wire_identity == {
		wire["id"]: (
			wire["source_incidence"], wire["target_incidence"],
			wire["source_interface"], wire["target_interface"],
		)
		for wire in undone["wires"]
	}

	redo_universal_change(store, registry)
	redone = project_universal_canvas(store, registry)
	restored = next(
		node for node in redone["nodes"] if node["id"] == composition_root
	)
	assert restored["composition"] is True
	assert restored["member_count"] == len(selected)
	assert set(selected).isdisjoint(node["id"] for node in redone["nodes"])
	assert created_cells.issubset(store.snapshot().cells)


def test_ungroup_undo_and_redo_preserve_authority_and_composition_identity():
	store, registry = build_universal_application(resolve_map_path())
	before = project_universal_canvas(store, registry)
	selected = tuple(node["id"] for node in before["nodes"][:2])
	set_universal_selection(store, registry, selected, focus_root=selected[-1])
	composition_root, _ = group_universal_selection(
		store, registry, title="Ungroup recovery"
	)
	ungroup_universal_composition(store, registry, composition_root)
	ungrouped = project_universal_canvas(store, registry)
	assert composition_root not in {node["id"] for node in ungrouped["nodes"]}
	assert set(selected).issubset(node["id"] for node in ungrouped["nodes"])

	undo_universal_change(store, registry)
	restored_group = project_universal_canvas(store, registry)
	group = next(
		node for node in restored_group["nodes"]
		if node["id"] == composition_root
	)
	assert group["composition"] is True
	assert group["member_count"] == len(selected)
	assert set(selected).isdisjoint(
		node["id"] for node in restored_group["nodes"]
	)

	redo_universal_change(store, registry)
	restored_members = project_universal_canvas(store, registry)
	assert composition_root not in {
		node["id"] for node in restored_members["nodes"]
	}
	assert set(selected).issubset(
		node["id"] for node in restored_members["nodes"]
	)


def test_property_edit_and_creation_are_reversible_without_identity_loss():
	store, registry = build_universal_application(resolve_map_path())
	root, _ = instantiate_universal_primitive(
		store, registry, x=480, y=320, title="Property history", atom="before"
	)
	projection = project_universal_canvas(store, registry)
	value = next(
		row for row in projection["properties"]
		if row["owner"] == root and row["label"] == "value"
	)
	assert edit_universal_property(
		store, registry, value["relation"], "after"
	) == root
	assert store.read(root).atom == b"after"
	undo_universal_change(store, registry)
	assert store.read(root).atom == b"before"
	redo_universal_change(store, registry)
	assert store.read(root).atom == b"after"

	property_root, _ = create_universal_property(
		store, registry, root, "discipline", "architecture"
	)
	created = project_universal_canvas(store, registry)
	assert any(
		row["relation"] == property_root and row["value"] == "architecture"
		for row in created["properties"]
	)
	created_cells = frozenset(store.snapshot().cells)
	undo_universal_change(store, registry)
	assert property_root in store.snapshot().cells
	assert all(
		row["relation"] != property_root
		for row in project_universal_canvas(store, registry)["properties"]
	)
	redo_universal_change(store, registry)
	assert any(
		row["relation"] == property_root and row["value"] == "architecture"
		for row in project_universal_canvas(store, registry)["properties"]
	)
	assert created_cells.issubset(store.snapshot().cells)


def test_property_compensation_rechecks_its_recorded_capability(monkeypatch):
	store, registry = build_universal_application(resolve_map_path())
	root, _ = instantiate_universal_primitive(
		store, registry, x=480, y=320, title="Capability history", atom="before"
	)
	value = next(
		row for row in project_universal_canvas(store, registry)["properties"]
		if row["owner"] == root and row["label"] == "value"
	)
	edit_universal_property(store, registry, value["relation"], "after")
	view = registry.view_sessions[registry.authorization.subject_root]
	transaction_root = read_relation(
		store.snapshot(), view.action_history_root
	)[-1].participant_id
	transaction = read_change_transaction(
		store.snapshot(), registry.change_history_protocol, transaction_root
	)
	assert transaction.authority_root == registry.composer_protocol.command(
		"catalog.configure"
	)
	assert transaction.scope_roots == (value["relation"],)

	calls = []
	original_authorize = universal_application_module._authorize

	def record_authority(*args, **kwargs):
		calls.append((args[2], kwargs.get("object_root")))
		return original_authorize(*args, **kwargs)

	monkeypatch.setattr(
		universal_application_module, "_authorize", record_authority
	)
	undo_universal_change(store, registry)
	assert calls == [("catalog.configure", value["relation"])]
	assert store.read(root).atom == b"before"


def test_history_panel_projects_real_session_actions_in_plain_language():
	store, registry = build_universal_application(resolve_map_path())
	root = registry.visible_roots[0]
	move_universal_root(store, registry, root, 420, 260)
	set_universal_properties_panel(
		store, registry, registry.properties_panel_roots["history"]
	)
	projection = project_universal_canvas(store, registry)
	action = projection["action_history"]["transactions"][0]
	assert action["operation"] == "Move"
	assert action["state"] == "applied"
	assert action["change_count"] == 2
	assert action["capability"] == "canvas.arrange"
	assert action["scope_count"] == 1
	presentation = projection["inspector"]["presentation"]
	assert presentation["active"] == registry.properties_panel_roots["history"]
	history_panel = next(
		panel for panel in presentation["panels"]
		if panel["id"] == registry.properties_panel_roots["history"]
	)
	descriptor = history_panel["components"][0]["descriptor"]
	pending = list(descriptor)
	visible_text = []
	while pending:
		item = pending.pop()
		if "text" in item:
			visible_text.append(item["text"])
		pending.extend(item.get("children", ()))
	assert "SESSION ACTIONS / 1" in visible_text
	assert "APPLIED / Move" in visible_text
	assert "2 changes" in visible_text
	assert action["root"] not in visible_text


def test_interface_creation_undo_and_redo_restore_the_same_socket_identity():
	store, registry = build_universal_application(resolve_map_path())
	root, _ = instantiate_universal_primitive(
		store, registry, x=480, y=320, title="Interface history"
	)
	projection = project_universal_canvas(store, registry)
	presentation = next(
		item["id"] for item in projection["authoring"]["interface_presentations"]
		if item["side"] == "source"
	)
	interface_root, _ = create_universal_interface(
		store,
		registry,
		root,
		"Result",
		presentation,
		registry.assembly_protocol.root_id,
	)
	created = next(
		node for node in project_universal_canvas(store, registry)["nodes"]
		if node["id"] == root
	)
	assert interface_root in {port["id"] for port in created["ports"]}
	created_cells = frozenset(store.snapshot().cells)

	undo_universal_change(store, registry)
	undone = next(
		node for node in project_universal_canvas(store, registry)["nodes"]
		if node["id"] == root
	)
	assert interface_root in store.snapshot().cells
	assert interface_root not in {port["id"] for port in undone["ports"]}
	redo_universal_change(store, registry)
	redone = next(
		node for node in project_universal_canvas(store, registry)["nodes"]
		if node["id"] == root
	)
	assert interface_root in {port["id"] for port in redone["ports"]}
	assert created_cells.issubset(store.snapshot().cells)


def test_founder_agent_body_is_an_unbound_authorized_graph_region(application):
	store, registry = application
	agent = registry.agent_body
	assert agent.body.identity_root == registry.authorization.subject_root
	assert agent.body.model_binding_root is None
	assert agent.session.model_binding_root is None
	assert agent.session.focus_root == agent.protocol.state("unbound")
	assert agent.session.assignment_root == agent.protocol.state("unbound")
	assert agent.session.view_session_root == registry.view_sessions[
		registry.authorization.subject_root
	].root_id
	assert {
		registry.authorization.founder_tenant_membership_root,
		registry.authorization.founder_principal_membership_root,
	}.issubset(agent.relationship_evidence_roots)
	models_members = read_relation(
		store.snapshot(), registry.map.domains["models"], budget=100_000
	)
	model_roots = {member.participant_id for member in models_members}
	assert {
		agent.control_root,
		agent.body.root_id,
		agent.session.root_id,
	}.issubset(model_roots)
	assert set(registry.root_properties).issuperset({
		agent.control_root,
		agent.body.root_id,
		agent.session.root_id,
	})
	assert not {
		"compose_agent_body",
		"begin_agent_session",
		"append_context_entry",
		"close_agent_session",
	}.intersection(agent_body_module.__all__)


def test_top_canvas_is_the_application_scope_and_every_wire_uses_real_interfaces(
	application,
):
	store, registry = application
	projection = project_universal_canvas(store, registry)
	node_ids = {node["id"] for node in projection["nodes"]}
	assert node_ids == {
		*registry.map.domains.values(),
		registry.core_values.root_id,
		registry.governed_work_registry_root,
	}
	assert registry.application_root not in node_ids
	assert registry.library_root not in node_ids
	assert projection["scope"]["current"] == registry.canvas_root

	ports = {
		(node["id"], port["id"])
		for node in projection["nodes"]
		for port in node["ports"]
	}
	assert projection["wires"]
	for wire in projection["wires"]:
		assert wire["source_interface"]
		assert wire["target_interface"]
		assert wire["source_incidence"]
		assert wire["target_incidence"]
		assert (wire["source"], wire["source_interface"]) in ports
		assert (wire["target"], wire["target_interface"]) in ports
		source_port = next(port for node in projection["nodes"] if node["id"] == wire["source"] for port in node["ports"] if port["id"] == wire["source_interface"])
		target_port = next(port for node in projection["nodes"] if node["id"] == wire["target"] for port in node["ports"] if port["id"] == wire["target_interface"])
		assert wire["source_incidence"] in source_port["endpoint_incidences"]
		assert wire["target_incidence"] in target_port["endpoint_incidences"]
		assert wire["id"] in source_port["relation_roots"]
		assert wire["id"] in target_port["relation_roots"]
		assert source_port["connectable"] is True
		assert target_port["connectable"] is False
		assert source_port["name"] == "Outgoing relations"
		assert target_port["name"] == "Incoming relations"

	page = project_universal_document(store, registry)
	assert "[{id:'',name:'input'}]" not in page
	assert "data-source-interface" in page
	assert "data-target-interface" in page


def test_exact_interface_migration_preserves_and_connects_legacy_history(application):
	store, registry = application
	before_projection = project_universal_canvas(store, registry)
	wire = before_projection["wires"][0]
	relation_before = tuple((m.incidence_id, m.role_id, m.participant_id) for m in read_relation(store.snapshot(), wire["id"], budget=256))
	legacy_root = universal_application_module._domain_canvas_interface_root(wire["source"], "source")
	assert legacy_root not in store.snapshot().cells
	snapshot = store.snapshot()
	name_root = legacy_root + ":name"
	legacy = compose_relation_cells(((registry.assembly_protocol.role("interface-target"), wire["source"]), (registry.assembly_protocol.role("name"), name_root), (registry.assembly_protocol.role("interface-contract"), registry.assembly_protocol.root_id), (registry.assembly_protocol.role("interface-presentation"), "app:canvas-interface:presentation:source")), relation_id=legacy_root)
	patch = prepare_append_relation_members(snapshot, registry.application_root, ((registry.assembly_protocol.role("interface"), legacy_root),), budget=100_000)
	store.commit(snapshot.revision, create=(Cell(name_root, NULL_CELL_ID, NULL_CELL_ID, b"Provides"), *legacy.cells, *patch.create), replace=patch.replace)
	registered = next(m for m in read_relation(store.snapshot(), registry.application_root, budget=100_000) if m.role_id == registry.assembly_protocol.role("interface") and m.participant_id == legacy_root)
	cell_ids = frozenset(store.snapshot().cells)
	roots, relation_roots, _ = universal_application_module._canvas_roots(store.snapshot(), registry)
	universal_application_module._ensure_canvas_domain_interfaces(store, registry.assembly_protocol, registry.roles, registry.application_root, roots, relation_roots)
	snapshot = store.snapshot()
	assert cell_ids.issubset(snapshot.cells)
	assert registered.incidence_id in snapshot.cells
	assert tuple((m.incidence_id, m.role_id, m.participant_id) for m in read_relation(snapshot, wire["id"], budget=256)) == relation_before
	assert not any(m.role_id == registry.assembly_protocol.role("interface") and m.participant_id == legacy_root for m in read_relation(snapshot, registry.application_root, budget=100_000))
	assert any(m.role_id == registry.roles["migration"] and m.participant_id == universal_application_module._CANVAS_INTERFACE_MIGRATION_ROOT for m in read_relation(snapshot, registry.application_root, budget=100_000))
	members = read_relation(snapshot, universal_application_module._CANVAS_INTERFACE_MIGRATION_ROOT, budget=100_000)
	assert any(m.role_id == registry.roles["source"] and m.participant_id == legacy_root for m in members)
	exact_root = universal_application_module._relation_canvas_interface_root(
		wire["id"], "source"
	)
	assert any(m.role_id == registry.roles["target"] and m.participant_id == exact_root for m in members)
	assert any(m.role_id == registry.roles["authority"] and m.participant_id == registered.incidence_id for m in members)
	exact_interface = universal_application_module._project_canvas_interface(
		snapshot, registry.assembly_protocol, exact_root
	)
	assert exact_interface["previous_roots"] == [legacy_root]


def test_domain_public_interfaces_own_every_exact_visible_incidence(application):
	store, registry = application
	projection = project_universal_canvas(store, registry)
	snapshot = store.snapshot()
	nodes = {node["id"]: node for node in projection["nodes"]}
	application_members = read_relation(
		snapshot, registry.application_root, budget=100_000
	)
	registered_interfaces = {
		member.participant_id
		for member in application_members
		if member.role_id == registry.assembly_protocol.role("interface")
	}

	for domain_root in registry.map.domains.values():
		node = nodes[domain_root]
		incoming = tuple(
			wire for wire in projection["wires"]
			if wire["target"] == domain_root and not wire["nary"]
		)
		outgoing = tuple(
			wire for wire in projection["wires"]
			if wire["source"] == domain_root and not wire["nary"]
		)
		for side, wires, expected_name in (
			("target", incoming, "Incoming relations"),
			("source", outgoing, "Outgoing relations"),
		):
			if not wires:
				continue
			incidence_key = "%s_incidence" % side
			interface_key = "%s_interface" % side
			ports = tuple(
				port for port in node["ports"]
				if port["side"] == side and port["endpoint_incidences"]
			)
			assert len(ports) == 1
			port = ports[0]
			assert port["id"] in registered_interfaces
			assert port["name"] == expected_name
			assert port["connectable"] is (side == "source")
			assert set(port["relation_roots"]) == {
				wire["id"] for wire in wires
			}
			assert set(port["endpoint_incidences"]) == {
				wire[incidence_key] for wire in wires
			}
			assert {wire[interface_key] for wire in wires} == {port["id"]}
			assert all(
				snapshot.cells[wire[incidence_key]].link1 == port["id"]
				for wire in wires
			)
			members = read_relation(snapshot, port["id"], budget=100_000)
			assert {
				member.participant_id for member in members
				if member.role_id == registry.roles["authority"]
			} == set(port["endpoint_incidences"])
			assert {
				member.participant_id for member in members
				if member.role_id == registry.roles["seed"]
			} == set(port["relation_roots"])
			previous = {
				member.participant_id for member in members
				if member.role_id == registry.roles["previous"]
			}
			assert len(previous) == len(wires)
			assert previous.issubset(snapshot.cells)
			assert all(
				root.startswith("app:canvas-interface:relation:")
				for root in previous
			)


def test_domain_public_interfaces_reconcile_when_live_canvas_relations_grow():
	store, registry = build_universal_application(resolve_map_path())
	project_universal_canvas(store, registry)
	brain_root = registry.map.domains["brain"]
	before = project_universal_canvas(store, registry)
	before_brain = next(node for node in before["nodes"] if node["id"] == brain_root)
	before_source_port = next(
		port for port in before_brain["ports"]
		if port["side"] == "source" and port["endpoint_incidences"]
	)
	before_incidence_count = len(before_source_port["endpoint_incidences"])

	create_universal_governed_work(
		store,
		registry,
		title="Reconcile live canvas relation growth",
		x=10,
		y=10,
		description="A growing graph must update public boundaries.",
		priority=1,
		external_key="court:public-boundary-growth",
		references={"scope": brain_root},
	)
	roots, relation_roots, _properties = universal_application_module._canvas_roots(
		store.snapshot(),
		registry,
	)
	universal_application_module._ensure_canvas_domain_interfaces(
		store,
		registry.assembly_protocol,
		registry.roles,
		registry.application_root,
		roots,
		relation_roots,
	)
	universal_application_module._ensure_canvas_domain_public_interfaces(
		store,
		registry.assembly_protocol,
		registry.roles,
		registry.application_root,
		roots,
		relation_roots,
	)

	after = project_universal_canvas(store, registry)
	after_brain = next(node for node in after["nodes"] if node["id"] == brain_root)
	after_source_port = next(
		port for port in after_brain["ports"]
		if port["id"] == before_source_port["id"]
	)
	assert len(after_source_port["endpoint_incidences"]) > before_incidence_count
	assert after_source_port["id"] == before_source_port["id"]


def test_governed_work_creation_accepts_declared_default_interface_values():
	store, registry = build_universal_application(resolve_map_path())
	root, _membership_wire, revision = create_universal_governed_work(
		store,
		registry,
		title="Default-preserving governed work",
		x=10,
		y=10,
	)
	status = project_universal_governed_work_status(store, registry)
	item = next(value for value in status["items"] if value["root"] == root)
	assert item["interfaces"]["description"]["value"] == ""
	assert item["interfaces"]["priority"]["value"] == "0"
	assert item["interfaces"]["external-key"]["value"] == "unset"
	assert revision == store.revision


def test_compact_governed_work_keeps_evidence_as_cells_without_canvas_fanout():
	store, registry = build_universal_application(resolve_map_path())
	brain_root = registry.map.domains["brain"]
	before_canvas = project_universal_canvas(store, registry)
	before_revision = store.revision
	created_root, _membership_wire, _revision = create_universal_governed_work(
		store,
		registry,
		title="Compact migration leaf",
		x=10,
		y=10,
		description="compact",
		priority=55,
		external_key="court:compact-work",
		references={"scope": brain_root},
		structured_references={
			"requirements": {
				"gate": {
					"kind": "pytest",
					"spec": {"path": "tests/court.py"},
				},
			},
			"cde-container": {"container_id": "10.PRODUCT/12.PRODUCTION"},
		},
		compact_references=True,
		select_created=False,
	)
	assert store.revision - before_revision <= 4
	after_canvas = project_universal_canvas(store, registry)
	assert after_canvas["selected"] == before_canvas["selected"]
	assert after_canvas["selection"] == before_canvas["selection"]
	status = project_universal_governed_work_status(store, registry)
	item = next(
		value for value in status["items"]
		if value["interfaces"]["external-key"]["value"] == "court:compact-work"
	)
	assert item["root"] == created_root
	assert item["interfaces"]["title"]["value"] == "Compact migration leaf"
	assert item["interfaces"]["description"]["value"] == "compact"
	assert item["interfaces"]["priority"]["value"] == "55"
	requirements_root = item["interfaces"]["requirements"]["target"]
	cde_root = item["interfaces"]["cde-container"]["target"]
	assert read_value_graph(
		store.snapshot(),
		registry.value_graph_protocol,
		requirements_root,
	) == {
		"gate": {
			"kind": "pytest",
			"spec": {"path": "tests/court.py"},
		},
	}
	assert read_value_graph(
		store.snapshot(),
		registry.value_graph_protocol,
		cde_root,
	) == {"container_id": "10.PRODUCT/12.PRODUCTION"}
	assert item["interfaces"]["scope"]["target"] == brain_root
	canvas_roots, _relations, _properties = (
		universal_application_module._canvas_roots(store.snapshot(), registry)
	)
	assert requirements_root not in canvas_roots
	assert cde_root not in canvas_roots


def test_grand_map_work_sync_creates_bounded_cell_native_work_without_brain_meta():
	store, registry = build_universal_application(resolve_map_path())
	preview = project_universal_grand_map_work(store, registry, limit=3)

	assert preview["schema"] == "archhub-universal-grand-map-work/v1"
	assert preview["grand_map"] == registry.map.grand_map_root
	assert preview["work_registry"] == registry.governed_work_registry_root
	assert preview["missing_count"] > 3
	assert len(preview["items"]) == 3
	assert all(
		item["external_key"].startswith("grand-map:")
		for item in preview["items"]
	)
	assert all(item["exists"] is False for item in preview["items"])
	assert project_universal_governed_work_index(store, registry)["total"] == 0

	synced = sync_universal_grand_map_work(store, registry, limit=2)
	assert synced["created_count"] == 2
	assert synced["missing_count_before"] == preview["missing_count"]
	assert synced["remaining_missing_count"] == preview["missing_count"] - 2
	index = project_universal_governed_work_index(store, registry)
	external_keys = {
		item["interfaces"]["external-key"]["value"]: item
		for item in index["items"]
	}
	assert set(external_keys) == {
		item["external_key"] for item in preview["items"][:2]
	}
	status_items = project_universal_governed_work_status(store, registry)[
		"items"
	]
	full_by_external_key = {
		item["interfaces"]["external-key"]["value"]: item
		for item in status_items
	}
	first = full_by_external_key[preview["items"][0]["external_key"]]
	requirements = read_value_graph(
		store.snapshot(),
		registry.value_graph_protocol,
		first["interfaces"]["requirements"]["target"],
	)
	cde = read_value_graph(
		store.snapshot(),
		registry.value_graph_protocol,
		first["interfaces"]["cde-container"]["target"],
	)
	policy = read_value_graph(
		store.snapshot(),
		registry.value_graph_protocol,
		first["interfaces"]["applicable-policy"]["target"],
	)
	assert requirements["gate"]["kind"] == "grand-map-cell-sync"
	assert requirements["gate"]["spec"]["authority"] == registry.map.grand_map_root
	assert cde["sync_authority"] == registry.map.grand_map_root
	assert policy == {
		"authority": "10.PRODUCT/13.NODE-LANGUAGE",
		"source": "Universal Cell Grand Map",
		"source_root": registry.map.grand_map_root,
		"promotion_allowed": False,
		"legacy_brain_meta_write": False,
	}
	after = project_universal_grand_map_work(store, registry, limit=3)
	assert after["existing_count"] == 2
	assert after["missing_count"] == preview["missing_count"] - 2
	assert not (
		{item["external_key"] for item in after["items"]}
		& set(external_keys)
	)


def _roma_tree_payload(state="open", claimed_by=None):
	return {
		"tree_id": "rt-app",
		"root_id": "root",
		"owner_user": "founder",
		"title": "Cell-native requirement route",
		"created_at": "2026-07-20T00:00:00+00:00",
		"updated_at": "2026-07-20T00:00:00+00:00",
		"nodes": {
			"root": {
				"node_id": "root",
				"parent": None,
				"title": "Cell-native requirement route",
				"children": ["leaf"],
				"state": "open",
				"gate_kind": "manual",
				"gate_spec": {},
				"created_at": "2026-07-20T00:00:00+00:00",
				"updated_at": "2026-07-20T00:00:00+00:00",
			},
			"leaf": {
				"node_id": "leaf",
				"parent": "root",
				"title": "Store ROMA tree as Cells",
				"predicate": "requirement tree has explicit Cell relations",
				"children": [],
				"state": state,
				"claimed_by": claimed_by,
				"past_claimants": [claimed_by] if claimed_by else [],
				"gate_kind": "pytest",
				"gate_spec": {
					"path": "tests_replica/test_cell_roma_requirements.py",
					"selector": "test_sync_creates_addressable_tree",
				},
				"created_at": "2026-07-20T00:00:00+00:00",
				"updated_at": "2026-07-20T00:01:00+00:00",
			},
		},
	}


def test_roma_requirement_tree_syncs_as_application_brain_region():
	store, registry = build_universal_application(resolve_map_path())

	synced = sync_universal_roma_requirement_tree(
		store,
		registry,
		_roma_tree_payload(),
		source="brain.roma_atomize",
	)

	assert synced["ok"] is True
	assert synced["schema"] == "archhub-roma-requirement-tree-cell-sync/v1"
	assert synced["application"] == registry.application_root
	assert synced["brain_scope"] == registry.map.domains["brain"]
	assert synced["tree_root"] == roma_tree_root("rt-app")
	assert synced["node_count"] == 2
	assert synced["edge_count"] == 1
	snapshot = store.snapshot()
	application_members = read_relation(
		snapshot, registry.application_root, budget=100_000
	)
	brain_members = read_relation(
		snapshot, registry.map.domains["brain"], budget=100_000
	)
	assert any(
		member.participant_id == synced["protocol"]
		for member in application_members
	)
	assert any(
		member.participant_id == synced["registry"]
		for member in brain_members
	)

	projected = project_universal_roma_requirement_tree(
		store, registry, tree_id="rt-app"
	)
	leaf_root = roma_node_root("rt-app", "leaf")
	assert projected["node_count"] == 2
	assert projected["root_node"] == roma_node_root("rt-app", "root")
	assert projected["frontier"][0]["root"] == leaf_root
	assert projected["nodes"][leaf_root]["gate_spec"]["selector"] == (
		"test_sync_creates_addressable_tree"
	)
	assert not any(
		cell.atom.startswith(b"{") or cell.atom.startswith(b"[")
		for cell_id, cell in snapshot.cells.items()
		if cell_id.startswith("app:roma-tree:")
	)

	before_revision = store.revision
	sync_universal_roma_requirement_tree(
		store,
		registry,
		_roma_tree_payload(state="claimed", claimed_by="agent-a"),
		source="brain.roma_claim",
	)
	assert store.revision == before_revision + 1
	claimed = project_universal_roma_requirement_tree(
		store, registry, tree_id="rt-app"
	)
	assert claimed["nodes"][leaf_root]["state"] == "claimed"
	assert claimed["nodes"][leaf_root]["claimed_by"] == "agent-a"


def test_background_governed_work_creation_does_not_activate_canvas_view(
	monkeypatch,
):
	store, registry = build_universal_application(resolve_map_path())
	brain_root = registry.map.domains["brain"]

	def deny_view_activation(*_args, **_kwargs):
		raise AssertionError("background work creation activated the canvas view")

	monkeypatch.setattr(
		universal_application_module,
		"_prepare_active_top_scope_exposure_extension",
		deny_view_activation,
	)
	monkeypatch.setattr(
		universal_application_module,
		"_prepare_selection_transition",
		deny_view_activation,
	)
	created_root, _membership_wire, _revision = create_universal_governed_work(
		store,
		registry,
		title="Background authority leaf",
		x=10,
		y=10,
		description="registry only",
		priority=5,
		external_key="court:background-work",
		references={"scope": brain_root},
		compact_references=True,
		select_created=False,
	)
	index = project_universal_governed_work_index(store, registry)
	assert any(
		item["root"] == created_root
		and item["interfaces"]["external-key"]["value"] == "court:background-work"
		for item in index["items"]
	)


def test_work_index_reuses_verified_authority_snapshot(monkeypatch):
	store, registry = build_universal_application(resolve_map_path())
	calls = {"count": 0}
	original = (
		universal_application_module.verify_relationship_authority_snapshot
	)

	def counted(*args, **kwargs):
		calls["count"] += 1
		return original(*args, **kwargs)

	monkeypatch.setattr(
		universal_application_module,
		"verify_relationship_authority_snapshot",
		counted,
	)
	first = project_universal_governed_work_index(store, registry)
	second = project_universal_governed_work_index(store, registry)
	assert first["revision"] == second["revision"] == store.revision
	assert calls["count"] == 1


def test_visible_public_interface_is_an_independently_selectable_graph_root(
	application,
):
	store, registry = application
	initial = project_universal_canvas(store, registry)
	ui_root = registry.map.domains["ui"]
	ui_node = next(node for node in initial["nodes"] if node["id"] == ui_root)
	interface = next(
		port for port in ui_node["ports"]
		if port["name"] == "Incoming relations"
	)

	apply_universal_canvas_gesture(
		store,
		registry,
		roots=(),
		focus_root=interface["id"],
	)
	selected = project_universal_canvas(store, registry)
	assert selected["selected"] == interface["id"]
	assert selected["selection"] == []
	assert selected["selected_title"] == "Incoming relations"
	assert selected["selected_interface"]["id"] == interface["id"]
	assert selected["selected_interface"]["owner"] == ui_root
	assert selected["selected_interface"]["side"] == "target"
	assert {
		wire["id"] for wire in selected["wires"] if wire["context"]
	} == set(interface["relation_roots"])
	connections_by_role = {}
	for connection in selected["connections"]:
		connections_by_role.setdefault(connection["role"], []).append(connection)
	assert all(
		" to " in connection["participant_label"]
		for connection in connections_by_role["seed"]
	)
	assert all(
		" endpoint / " in connection["participant_label"]
		for connection in connections_by_role["authority"]
	)
	assert all(
		connection["participant_label"].startswith("Exact target endpoint / ")
		for connection in connections_by_role["previous"]
	)


def test_core_values_are_openable_wired_governance_not_a_side_document(application):
	store, registry = application
	top = project_universal_canvas(store, registry)
	core = next(
		node for node in top["nodes"]
		if node["id"] == registry.core_values.root_id
	)
	assert core["label"] == "Core Values and Governance"
	governing_wires = tuple(
		wire for wire in top["wires"]
		if wire["source"] == registry.core_values.root_id
	)
	assert {wire["target"] for wire in governing_wires} == {
		registry.map.domains[key]
		for key in ("brain", "orchestration", "nodes", "ui", "cockpit")
	}
	assert all(wire["authority_roots"] for wire in governing_wires)
	assert len({wire["source_interface"] for wire in governing_wires}) == 1
	public_interface = next(iter({
		wire["source_interface"] for wire in governing_wires
	}))
	public_port = next(
		port for port in core["ports"] if port["id"] == public_interface
	)
	assert set(public_port["relation_roots"]) == {
		wire["id"] for wire in governing_wires
	}
	assert set(public_port["endpoint_incidences"]) == {
		wire["source_incidence"] for wire in governing_wires
	}

	set_universal_scope(store, registry, registry.core_values.root_id)
	opened = project_universal_canvas(store, registry)
	assert opened["scope"]["current"] == registry.core_values.root_id
	assert {node["id"] for node in opened["nodes"]} == {
		registry.core_values.source_root,
		registry.core_values.anchor_root,
		registry.core_values.systems_root,
		registry.core_values.pillars_root,
		registry.core_values.control_map_root,
		registry.core_values.conflicts_root,
		registry.core_values.adoption_decision_root,
	}
	set_universal_scope(store, registry)


def test_catalogue_placement_inside_a_domain_wires_into_that_scope(application):
	store, registry = application
	scope_root = registry.map.domains["ui"]
	set_universal_scope(store, registry, scope_root)
	before = project_universal_canvas(store, registry)
	created_root, _revision = instantiate_universal_definition(
		store,
		registry,
		registry.standard_library.definition_roots[0],
		x=420,
		y=240,
	)
	after = project_universal_canvas(store, registry)

	assert after["scope"]["current"] == scope_root
	assert created_root not in {node["id"] for node in before["nodes"]}
	assert created_root in {node["id"] for node in after["nodes"]}
	assert any(
		member.role_id == registry.roles["member"]
		and member.participant_id == created_root
		for member in read_relation(store.snapshot(), scope_root, budget=100_000)
	)


def test_founder_wip_constitution_is_not_broadcast_to_members():
	store, registry = build_universal_application(resolve_map_path())
	member_root = "test:identity:core-values-member"
	store.commit(store.revision, create=(
		Cell(member_root, NULL_CELL_ID, NULL_CELL_ID, b"Core Values member"),
	))
	with pytest.raises(InvalidCell, match="WIP resource"):
		provision_universal_view_session(
			store,
			registry,
			member_root,
			visible_roots=(registry.core_values.root_id,),
		)


def test_drawn_domain_wire_preserves_both_selected_interfaces():
	store, registry = build_universal_application(resolve_map_path())
	source_root, _ = instantiate_universal_primitive(store, registry, x=420, y=260, title="Source Cell")
	target_root, _ = instantiate_universal_primitive(store, registry, x=720, y=260, title="Target Cell")
	projection = project_universal_canvas(store, registry)
	presentations = {item["side"]: item["id"] for item in projection["authoring"]["interface_presentations"]}
	source_interface, _ = create_universal_interface(store, registry, source_root, "Result", presentations["source"], registry.assembly_protocol.root_id)
	target_interface, _ = create_universal_interface(store, registry, target_root, "Input", presentations["target"], registry.assembly_protocol.root_id)
	relation_root, _ = connect_universal_roots(store, registry, source_root, target_root, source_interface=source_interface, target_interface=target_interface)
	members = read_relation(store.snapshot(), relation_root, budget=256)
	assert next(m.participant_id for m in members if m.role_id == registry.roles["source"]) == source_interface
	assert next(m.participant_id for m in members if m.role_id == registry.roles["target"]) == target_interface
	created = next(w for w in project_universal_canvas(store, registry)["wires"] if w["id"] == relation_root)
	assert created["source_interface"] == source_interface
	assert created["target_interface"] == target_interface
	with pytest.raises(InvalidCell, match="duplicate connection"):
		connect_universal_roots(store, registry, source_root, target_root, source_interface=source_interface, target_interface=target_interface)


def test_drawn_wire_is_owned_and_projected_by_the_open_canvas_scope():
	store, registry = build_universal_application(resolve_map_path())
	scope_root = registry.map.domains["ui"]
	set_universal_scope(store, registry, scope_root)
	source_root, _ = instantiate_universal_primitive(
		store, registry, x=420, y=260, title="Scoped source"
	)
	target_root, _ = instantiate_universal_primitive(
		store, registry, x=720, y=260, title="Scoped target"
	)
	projection = project_universal_canvas(store, registry)
	presentations = {
		item["side"]: item["id"]
		for item in projection["authoring"]["interface_presentations"]
	}
	source_interface, _ = create_universal_interface(
		store, registry, source_root, "Result", presentations["source"],
		registry.assembly_protocol.root_id,
	)
	target_interface, _ = create_universal_interface(
		store, registry, target_root, "Input", presentations["target"],
		registry.assembly_protocol.root_id,
	)
	relation_root, _ = connect_universal_roots(
		store,
		registry,
		source_root,
		target_root,
		source_interface=source_interface,
		target_interface=target_interface,
	)
	connected = project_universal_canvas(store, registry)

	assert any(wire["id"] == relation_root for wire in connected["wires"])
	assert any(
		member.role_id == registry.roles["scope"]
		and member.participant_id == scope_root
		for member in read_relation(
			store.snapshot(), relation_root, budget=256
		)
	)
	assert any(
		member.role_id == registry.roles["relation"]
		and member.participant_id == relation_root
		for member in read_relation(
			store.snapshot(), scope_root, budget=100_000
		)
	)

	disconnect_universal_connection(store, registry, relation_root)
	detached = project_universal_canvas(store, registry)
	assert all(wire["id"] != relation_root for wire in detached["wires"])
	assert not any(
		member.role_id == registry.roles["relation"]
		and member.participant_id == relation_root
		for member in read_relation(
			store.snapshot(), scope_root, budget=100_000
		)
	)


def test_wire_connect_rewire_and_disconnect_undo_preserve_one_relation_identity():
	store, registry = build_universal_application(resolve_map_path())
	source_root, _ = instantiate_universal_primitive(
		store, registry, x=420, y=260, title="History source"
	)
	replacement_root, _ = instantiate_universal_primitive(
		store, registry, x=420, y=500, title="History replacement"
	)
	target_root, _ = instantiate_universal_primitive(
		store, registry, x=760, y=260, title="History target"
	)
	projection = project_universal_canvas(store, registry)
	presentations = {
		item["side"]: item["id"]
		for item in projection["authoring"]["interface_presentations"]
	}
	source_interface, _ = create_universal_interface(
		store, registry, source_root, "Result", presentations["source"],
		registry.assembly_protocol.root_id,
	)
	replacement_interface, _ = create_universal_interface(
		store, registry, replacement_root, "Result", presentations["source"],
		registry.assembly_protocol.root_id,
	)
	target_interface, _ = create_universal_interface(
		store, registry, target_root, "Input", presentations["target"],
		registry.assembly_protocol.root_id,
	)
	relation_root, _ = connect_universal_roots(
		store, registry, source_root, target_root,
		source_interface=source_interface, target_interface=target_interface,
	)
	created_cells = frozenset(store.snapshot().cells)
	wire = next(
		item for item in project_universal_canvas(store, registry)["wires"]
		if item["id"] == relation_root
	)
	source_incidence = wire["source_incidence"]

	undo_universal_change(store, registry)
	assert all(
		item["id"] != relation_root
		for item in project_universal_canvas(store, registry)["wires"]
	)
	assert relation_root in store.snapshot().cells
	redo_universal_change(store, registry)
	restored = next(
		item for item in project_universal_canvas(store, registry)["wires"]
		if item["id"] == relation_root
	)
	assert restored["source_interface"] == source_interface
	assert restored["target_interface"] == target_interface

	rewire_universal_connection(
		store, registry, source_incidence, replacement_interface
	)
	assert next(
		item for item in project_universal_canvas(store, registry)["wires"]
		if item["id"] == relation_root
	)["source_interface"] == replacement_interface
	undo_universal_change(store, registry)
	assert next(
		item for item in project_universal_canvas(store, registry)["wires"]
		if item["id"] == relation_root
	)["source_interface"] == source_interface
	redo_universal_change(store, registry)
	assert next(
		item for item in project_universal_canvas(store, registry)["wires"]
		if item["id"] == relation_root
	)["source_interface"] == replacement_interface

	disconnect_universal_connection(store, registry, relation_root)
	assert all(
		item["id"] != relation_root
		for item in project_universal_canvas(store, registry)["wires"]
	)
	undo_universal_change(store, registry)
	restored = next(
		item for item in project_universal_canvas(store, registry)["wires"]
		if item["id"] == relation_root
	)
	assert restored["source_interface"] == replacement_interface
	assert restored["target_interface"] == target_interface
	redo_universal_change(store, registry)
	assert all(
		item["id"] != relation_root
		for item in project_universal_canvas(store, registry)["wires"]
	)
	assert created_cells.issubset(store.snapshot().cells)


def test_detaching_a_drawn_wire_is_one_reversible_history_preserving_revision():
	store, registry = build_universal_application(resolve_map_path())
	source_root, _ = instantiate_universal_primitive(
		store, registry, x=420, y=260, title="Detachable source"
	)
	target_root, _ = instantiate_universal_primitive(
		store, registry, x=720, y=260, title="Detachable target"
	)
	projection = project_universal_canvas(store, registry)
	presentations = {
		item["side"]: item["id"]
		for item in projection["authoring"]["interface_presentations"]
	}
	source_interface, _ = create_universal_interface(
		store, registry, source_root, "Result", presentations["source"],
		registry.assembly_protocol.root_id,
	)
	target_interface, _ = create_universal_interface(
		store, registry, target_root, "Input", presentations["target"],
		registry.assembly_protocol.root_id,
	)
	relation_root, _ = connect_universal_roots(
		store, registry, source_root, target_root,
		source_interface=source_interface, target_interface=target_interface,
	)
	connected = project_universal_canvas(store, registry)
	property_roots = {
		row["relation"] for row in connected["properties"]
		if row["owner"] == relation_root
	}
	assert property_roots
	before = store.snapshot()
	before_revision = store.revision

	disconnect_universal_connection(store, registry, relation_root)
	after = store.snapshot()
	detached = project_universal_canvas(store, registry)
	assert store.revision == before_revision + 1
	assert set(before.cells).issubset(after.cells)
	assert relation_root in after.cells
	assert store.at(before_revision).cells == before.cells
	assert all(wire["id"] != relation_root for wire in detached["wires"])
	assert detached["selected"] == source_root
	canvas_participants = {
		member.participant_id for member in read_relation(
			after, registry.canvas_root, budget=100_000
		)
	}
	assert relation_root not in canvas_participants
	assert property_roots.isdisjoint(canvas_participants)
	for interface_root in (source_interface, target_interface):
		members = read_relation(after, interface_root, budget=100_000)
		assert not any(
			member.role_id == registry.roles["seed"]
			and member.participant_id == relation_root
			for member in members
		)

	replacement_root, _ = connect_universal_roots(
		store, registry, source_root, target_root,
		source_interface=source_interface, target_interface=target_interface,
	)
	assert replacement_root != relation_root


def test_rewire_and_detach_keep_an_assembly_input_equal_to_the_visible_wire():
	store, registry = build_universal_application(resolve_map_path())
	watcher_root, _ = instantiate_universal_definition(
		store,
		registry,
		registry.standard_library.definition_roots[1],
		x=700,
		y=180,
	)
	projection = project_universal_canvas(store, registry)
	watcher = next(
		node["assembly"] for node in projection["nodes"]
		if node["id"] == watcher_root
	)
	target_interface = watcher["interfaces"][0]["id"]
	original_target = watcher["interfaces"][0]["target"]
	source_root = registry.map.domains["ui"]
	source_node = next(
		node for node in projection["nodes"] if node["id"] == source_root
	)
	source_interface = next(
		port["id"] for port in source_node["ports"]
		if port["side"] == "source" and port["connectable"]
	)
	relation_root, _ = connect_universal_roots(
		store, registry, source_root, watcher_root,
		source_interface=source_interface, target_interface=target_interface,
	)
	connected = project_universal_canvas(store, registry)
	assert next(
		node["assembly"]["interfaces"][0]["target"]
		for node in connected["nodes"] if node["id"] == watcher_root
	) == source_root

	replacement_root = registry.map.domains["nodes"]
	replacement_node = next(
		node for node in connected["nodes"] if node["id"] == replacement_root
	)
	replacement_interface = next(
		port["id"] for port in replacement_node["ports"]
		if port["side"] == "source" and port["connectable"]
	)
	with pytest.raises(InvalidCell, match="already has a connection"):
		connect_universal_roots(
			store, registry, replacement_root, watcher_root,
			source_interface=replacement_interface,
			target_interface=target_interface,
		)
	wire = next(
		item for item in connected["wires"] if item["id"] == relation_root
	)
	rewire_universal_connection(
		store, registry, wire["source_incidence"], replacement_interface
	)
	rewired = project_universal_canvas(store, registry)
	assert next(
		node["assembly"]["interfaces"][0]["target"]
		for node in rewired["nodes"] if node["id"] == watcher_root
	) == replacement_root
	disconnect_universal_connection(store, registry, relation_root)
	detached = project_universal_canvas(store, registry)
	assert next(
		node["assembly"]["interfaces"][0]["target"]
		for node in detached["nodes"] if node["id"] == watcher_root
	) == original_target


def test_inspector_visibility_levels_are_graph_relations_and_personal_bindings():
	store, registry = build_universal_application(resolve_map_path())
	snapshot = store.snapshot()
	projection = project_universal_canvas(store, registry)
	assert [lens["label"] for lens in projection["inspector"]["lenses"]] == [
		"Use", "Build", "Govern", "Floor"
	]
	assert (
		projection["inspector"]["active"]
		== registry.inspector_lens_roots["use"]
	)
	for lens in projection["inspector"]["lenses"]:
		members = read_relation(snapshot, lens["id"], budget=64)
		assert {
			snapshot.cells[member.participant_id].atom.decode("ascii")
			for member in members
			if member.role_id == registry.roles["member"]
		} == set(lens["sections"])

	before = store.revision
	set_universal_inspector_lens(
		store, registry, registry.inspector_lens_roots["govern"]
	)
	governed = project_universal_canvas(store, registry)
	assert store.revision == before + 1
	assert (
		governed["inspector"]["active"]
		== registry.inspector_lens_roots["govern"]
	)

	authority = registry.authorization
	member_root = "test:identity:inspector-member"
	store.commit(store.revision, create=(
		Cell(member_root, NULL_CELL_ID, NULL_CELL_ID, b"Inspector member"),
	))
	provision_universal_view_session(
		store, registry, member_root, visible_roots=registry.visible_roots[:2]
	)
	context = authority.broker.mint_authenticated_context(
		member_root,
		principal_roots=(authority.member_principal_root,),
		tenant_root=authority.tenant_root,
		assurance_root=authority.assurance_root,
		lifetime_seconds=120,
	)
	member_projection = project_universal_canvas(
		store, registry, authentication_context=context
	)
	assert [
		lens["label"] for lens in member_projection["inspector"]["lenses"]
	] == ["Use", "Build"]
	set_universal_inspector_lens(
		store,
		registry,
		registry.inspector_lens_roots["build"],
		authentication_context=context,
	)
	with pytest.raises(InvalidCell, match="outside identity authority"):
		set_universal_inspector_lens(
			store,
			registry,
			registry.inspector_lens_roots["floor"],
			authentication_context=context,
		)


def test_selected_card_color_is_a_personal_versioned_binding_with_reset():
	store, registry = build_universal_application(resolve_map_path())
	target, other = registry.visible_roots[:2]
	select_universal_root(store, registry, target)
	before = project_universal_canvas(store, registry)
	color = next(
		row for row in before["properties"] if row["label"] == "color"
	)
	other_before = next(
		node["color"] for node in before["nodes"] if node["id"] == other
	)
	source_before = store.read(color["value_root"])
	revision_before = store.revision

	with pytest.raises(
		InvalidCell, match="personal WIP binding"
	):
		edit_universal_property(
			store, registry, color["relation"], "#2f80ed"
		)
	assert store.revision == revision_before

	revision = preview_universal_presentation_color(
		store, registry, target, "#2f80ed"
	)
	after = project_universal_canvas(store, registry)
	after_color = next(
		row for row in after["properties"] if row["label"] == "color"
	)
	assert next(
		node["color"] for node in after["nodes"] if node["id"] == target
	) == "#2f80ed"
	assert next(
		node["color"] for node in after["nodes"] if node["id"] == other
	) == other_before
	assert after_color["presentation_binding"]
	assert after_color["presentation_revision"] == revision
	assert after_color["presentation_source"] == "Personal appearance draft"
	assert after_color["presentation_source_root"] == color["relation"]
	assert after_color["presentation_source_mode"] == "personal-wip"
	assert after_color["presentation_reset"] is True
	assert store.read(color["value_root"]) == source_before


	binding_members = read_relation(
		store.snapshot(), after_color["presentation_binding"], budget=64
	)
	by_role = {
		member.role_id: member.participant_id for member in binding_members
	}
	assert by_role[registry.roles["owner"]] == target
	assert store.read(by_role[registry.roles["label"]]).atom == b"color"
	assert by_role[registry.roles["source"]] == color["relation"]
	assert by_role[registry.roles["scope"]] == (
		registry.view_sessions[registry.authorization.subject_root].root_id
	)
	assert by_role[registry.roles["authority"]] == (
		registry.authorization.subject_root
	)
	asset_root = by_role[registry.roles["value"]]
	instance = read_lifecycle_instance(
		store.snapshot(),
		registry.assembly_protocol,
		registry.standard_library.lifecycle_protocol,
		asset_root,
	)
	assert state_heads(
		store.snapshot(),
		registry.standard_library.lifecycle_protocol,
		instance.state_pointers[
			registry.standard_library.lifecycle_protocol.states["wip"]
		],
	) == (revision,)
	projected_revision = read_revision(
		store.snapshot(),
		registry.standard_library.lifecycle_protocol,
		revision,
	)
	assert projected_revision.actor_root == registry.authorization.subject_root

	reset_revision = reset_universal_presentation_color(
		store,
		registry,
		target,
		base_revision_root=revision,
	)
	reset = project_universal_canvas(store, registry)
	reset_color = next(
		row for row in reset["properties"] if row["label"] == "color"
	)
	assert reset_color["presentation_revision"] == reset_revision
	assert reset_color["presentation_source_mode"] == "inherited"
	assert reset_color["presentation_reset"] is False
	assert len(reset_color["presentation_history"]) == 2
	assert next(
		node["color"] for node in reset["nodes"] if node["id"] == target
	) == color["value"]
	assert store.read(color["value_root"]) == source_before


def test_personal_presentation_wip_never_broadcasts_between_subjects():
	store, registry = build_universal_application(resolve_map_path())
	target = registry.visible_roots[0]
	preview_universal_presentation_color(
		store, registry, target, "#2f80ed"
	)

	member_root = "test:identity:presentation-member"
	store.commit(store.revision, create=(
		Cell(member_root, NULL_CELL_ID, NULL_CELL_ID, b"Presentation member"),
	))
	provision_universal_view_session(
		store, registry, member_root, visible_roots=(target,)
	)
	authority = registry.authorization
	context = authority.broker.mint_authenticated_context(
		member_root,
		principal_roots=(authority.member_principal_root,),
		tenant_root=authority.tenant_root,
		assurance_root=authority.assurance_root,
		lifetime_seconds=120,
	)
	member_before = project_universal_canvas(
		store, registry, authentication_context=context
	)
	assert member_before["nodes"][0]["color"] != "#2f80ed"

	preview_universal_presentation_color(
		store,
		registry,
		target,
		"#18a66b",
		authentication_context=context,
	)
	member_after = project_universal_canvas(
		store, registry, authentication_context=context
	)
	founder_after = project_universal_canvas(store, registry)
	assert member_after["nodes"][0]["color"] == "#18a66b"
	assert next(
		node["color"] for node in founder_after["nodes"]
		if node["id"] == target
	) == "#2f80ed"
	founder_view = registry.view_sessions[authority.subject_root]
	member_view = registry.view_sessions[member_root]
	founder_bindings = [
		member.participant_id for member in read_relation(
			store.snapshot(), founder_view.root_id, budget=100_000
		)
		if member.role_id == registry.roles["presentation-binding"]
	]
	member_bindings = [
		member.participant_id for member in read_relation(
			store.snapshot(), member_view.root_id, budget=100_000
		)
		if member.role_id == registry.roles["presentation-binding"]
	]
	assert len(founder_bindings) == len(member_bindings) == 1
	assert founder_bindings != member_bindings


@pytest.mark.parametrize(("role_name", "error_text"), (
	("source", "source binding drifted"),
	("scope", "crossed its view"),
))
def test_personal_presentation_binding_tampering_fails_closed(
	role_name, error_text
):
	store, registry = build_universal_application(resolve_map_path())
	target = registry.visible_roots[0]
	select_universal_root(store, registry, target)
	preview_universal_presentation_color(
		store, registry, target, "#2f80ed"
	)
	projection = project_universal_canvas(store, registry)
	color = next(
		row for row in projection["properties"] if row["label"] == "color"
	)
	binding_members = read_relation(
		store.snapshot(), color["presentation_binding"], budget=64
	)
	incidence = next(
		member.incidence_id for member in binding_members
		if member.role_id == registry.roles[role_name]
	)
	replacement = (
		next(
			row["relation"] for row in projection["properties"]
			if row["relation"] != color["relation"]
		)
		if role_name == "source"
		else registry.application_root
	)
	universal_application_module.rewire_incidence(
		store, incidence, replacement
	)
	with pytest.raises(InvalidCell, match=error_text):
		project_universal_canvas(store, registry)


def test_released_application_policy_is_visible_and_member_power_is_limited():
	store, registry = build_universal_application(resolve_map_path())
	authority = registry.authorization
	app_members = read_relation(
		store.snapshot(), registry.application_root, budget=100_000
	)
	assert {
		authority.protocol.root_id,
		authority.policy_root,
		authority.scope_root,
		authority.subject_root,
		authority.principal_root,
		authority.member_principal_root,
	}.issubset({member.participant_id for member in app_members})

	member_root = "test:identity:member"
	store.commit(store.revision, create=(
		Cell(member_root, NULL_CELL_ID, NULL_CELL_ID, b"Member"),
	))
	provision_universal_view_session(store, registry, member_root)
	member_context = authority.broker.mint_authenticated_context(
		member_root,
		principal_roots=(authority.member_principal_root,),
		tenant_root=authority.tenant_root,
		assurance_root=authority.assurance_root,
		lifetime_seconds=120,
	)
	projection = project_universal_canvas(
		store, registry, authentication_context=member_context
	)
	assert projection["authorization"]["default"] == "deny"
	assert projection["authorization"]["state"] == "released"
	assert projection["authorization"]["subject"] == member_root
	assert projection["nodes"] == []
	assert len(projection["catalog"]) == 14
	member_view = registry.view_sessions[member_root]
	set_universal_selection(
		store,
		registry,
		(),
		focus_root=member_view.root_id,
		authentication_context=member_context,
	)
	session_projection = project_universal_canvas(
		store, registry, authentication_context=member_context
	)
	assert session_projection["selected"] == member_view.root_id
	assert {
		"session owner", "principal", "tenant", "assurance", "scope",
		"lens", "relation", "property",
	} <= {item["role"] for item in session_projection["connections"]}
	with pytest.raises(InvalidCell, match="Properties focus"):
		set_universal_selection(
			store,
			registry,
			(),
			focus_root=authority.session.root_id,
			authentication_context=member_context,
		)
	founder_property = registry.root_properties[registry.visible_roots[0]][0]
	with pytest.raises(AuthorizationDenied):
		edit_universal_property(
			store,
			registry,
			founder_property,
			"Denied member edit",
			authentication_context=member_context,
		)


def test_application_users_are_admitted_by_the_selected_published_tenant():
	store, registry = build_universal_application(resolve_map_path())
	authority = registry.authorization
	tenant = registry.tenant_authority
	verifier = PublishedTenantAdmissionVerifier(
		registry.tenant_configuration_protocol,
		registry.assembly_protocol,
		registry.standard_library.lifecycle_protocol,
		authority.protocol,
		authority.identity_protocol,
		authority.relationship_broker,
	)
	assert tenant.tenant_root == authority.tenant_root
	assert tenant.catalogue_root == registry.standard_library.catalog_root
	assert tenant.policy_root == authority.policy_root
	assert (
		registry.tenant_release_selection.selected_revision_root
		== tenant.published_revision_root
	)
	founder_admission = verifier.verify(
		store.snapshot(),
		tenant_root=authority.tenant_root,
		subject_root=authority.subject_root,
		now=registry.tenant_release_selection.selected_at,
	)
	assert founder_admission.published_revision_root == tenant.published_revision_root

	member_root = "test:identity:published-tenant-member"
	store.commit(store.revision, create=(
		Cell(member_root, NULL_CELL_ID, NULL_CELL_ID, b"Tenant member"),
	))
	view, _ = provision_universal_view_session(store, registry, member_root)
	member_admission = verifier.verify(
		store.snapshot(),
		tenant_root=authority.tenant_root,
		subject_root=member_root,
		now=registry.tenant_release_selection.selected_at,
	)
	assert member_admission.published_revision_root == tenant.published_revision_root

	revoke_universal_authority_relationship(
		store,
		registry,
		view.tenant_role_membership_root,
		reason="remove the subject from the tenant release",
	)
	with pytest.raises(TenantAuthorityDenied, match="active role"):
		verifier.verify(
			store.snapshot(),
			tenant_root=authority.tenant_root,
			subject_root=member_root,
			now=registry.tenant_release_selection.selected_at,
		)


def test_every_universal_http_interface_is_an_immutable_graph_route():
	store, registry = build_universal_application(resolve_map_path())
	snapshot = store.snapshot()
	current_route_keys = {
		"%s %s" % (method, path)
		for method, path, _action in (
			universal_application_module._APPLICATION_HTTP_ROUTE_SPECS
		)
	}
	assert not (
		current_route_keys
		& universal_application_module._RETIRED_APPLICATION_HTTP_ROUTE_KEYS
	)
	assert len(registry.application_http_route_roots) == (
		len(universal_application_module._APPLICATION_HTTP_ROUTE_SPECS)
		+ len(registry.website.route_roots)
	)
	assert "POST /api/universal/properties-panel" not in (
		registry.application_http_route_roots
	)
	assert "POST /api/universal/property-create" not in (
		registry.application_http_route_roots
	)
	assert "POST /api/universal/interface-create" not in (
		registry.application_http_route_roots
	)
	assert "POST /api/universal/interface" not in (
		registry.application_http_route_roots
	)
	assert "POST /api/universal/theme-preview" not in (
		registry.application_http_route_roots
	)
	assert "POST /api/universal/theme-restore" not in (
		registry.application_http_route_roots
	)
	assert "POST /api/universal/cell" not in (
		registry.application_http_route_roots
	)
	for retired_topology_route in (
		"POST /api/universal/connect",
		"POST /api/universal/disconnect",
		"POST /api/universal/rewire",
	):
		assert retired_topology_route not in registry.application_http_route_roots
	for retired_history_route in (
		"POST /api/universal/control",
		"POST /api/universal/undo",
		"POST /api/universal/redo",
	):
		assert retired_history_route not in registry.application_http_route_roots
	assert "POST /api/universal/interaction" in (
		registry.application_http_route_roots
	)
	assert (
		"POST /api/universal/presentation-preview"
		not in registry.application_http_route_roots
	)
	assert (
		"POST /api/universal/presentation-reset"
		not in registry.application_http_route_roots
	)
	assert (
		"GET /api/universal/remote-runtime"
		in registry.application_http_route_roots
	)
	for key, route_root in registry.application_http_route_roots.items():
		method, path = key.split(" ", 1)
		route = find_cloud_route(
			snapshot,
			registry.cloud_route_protocol,
			method=method,
			path_template=path,
		)
		resolved = resolve_cloud_route(snapshot, route)
		assert route.root_id == route_root
		if path in registry.website.route_roots:
			assert method == "GET"
			assert resolved.object_root == registry.website.page_roots[path]
			assert resolved.interface_root == registry.ui_protocol.root_id
			assert resolved.purpose_root == registry.website.purpose_root
			assert resolved.audience_root == registry.website.audience_root
			assert (
				resolved.classification_root
				== registry.website.classification_root
			)
			assert resolved.lifecycle_state_root == registry.website.lifecycle_root
			assert resolved.resource_lineage_roots == (
				registry.application_root,
				registry.website.root_id,
			)
			continue
		assert resolved.object_root == registry.authorization.route_scope_root
		assert registry.authorization.scope_root in (
			resolved.resource_lineage_roots
		)
		assert resolved.interface_root == registry.ui_protocol.root_id
		assert resolved.purpose_root == registry.authorization.purpose_root
		assert resolved.audience_root == registry.authorization.audience_root
		assert (
			resolved.classification_root
			== registry.authorization.classification_root
		)
		assert resolved.lifecycle_state_root == (
			registry.standard_library.lifecycle_protocol.states["published"]
		)
		assert resolved.resource_lineage_roots == (
			registry.authorization.scope_root,
			registry.authorization.route_scope_root,
		)


def test_application_membership_is_graph_derived_visible_and_live_revocable():
	store, registry = build_universal_application(resolve_map_path())
	authority = registry.authorization
	member_root = "test:identity:relationship-member"
	project_group = "test:audience:project-alpha"
	store.commit(store.revision, create=(
		Cell(member_root, NULL_CELL_ID, NULL_CELL_ID, b"Relationship member"),
		Cell(project_group, NULL_CELL_ID, NULL_CELL_ID, b"Project Alpha"),
	))
	view, _ = provision_universal_view_session(store, registry, member_root)
	# No principal is copied into the credential. The signed graph derives it.
	member_context = authority.broker.mint_authenticated_context(
		member_root,
		tenant_root=authority.tenant_root,
		assurance_root=authority.assurance_root,
		lifetime_seconds=120,
	)
	projection = project_universal_canvas(
		store, registry, authentication_context=member_context
	)
	assert authority.member_principal_root in projection["authorization"]["principals"]
	assert authority.tenant_root in projection["authorization"]["principals"]
	assert {
		view.tenant_membership_root,
		view.principal_membership_root,
	}.issubset({
		item["root"] for item in projection["authorization"]["relationships"]
	})

	project_membership, _ = issue_universal_authority_relationship(
		store,
		registry,
		source_root=member_root,
		target_root=project_group,
		kind="membership",
		reason="assigned to Project Alpha",
	)
	projection = project_universal_canvas(
		store, registry, authentication_context=member_context
	)
	assert project_group in projection["authorization"]["principals"]
	assert any(
		item["root"] == project_membership
		and item["verified"]
		and item["state"] == "active"
		for item in projection["authorization"]["relationships"]
	)
	apply_universal_canvas_gesture(
		store,
		registry,
		roots=[],
		focus_root=project_membership,
		authentication_context=member_context,
	)
	inspected = project_universal_canvas(
		store, registry, authentication_context=member_context
	)
	assert inspected["selected"] == project_membership
	assert inspected["physical"]["identity"] == project_membership
	assert inspected["selected_title"].startswith("membership:")
	assert {item["role"] for item in inspected["connections"]} >= {
		"source", "target", "kind", "tenant", "state", "signature"
	}
	assert all(item["editable"] is False for item in inspected["connections"])
	with pytest.raises(InvalidCell, match="outside the active lens"):
		apply_universal_canvas_gesture(
			store,
			registry,
			roots=[],
			focus_root=authority.founder_principal_membership_root,
			authentication_context=member_context,
		)
	with pytest.raises(AuthorizationDenied):
		issue_universal_authority_relationship(
			store,
			registry,
			source_root=member_root,
			target_root=project_group,
			kind="membership",
			reason="member cannot grant their own authority",
			relationship_root="test:forged:membership",
			authentication_context=member_context,
		)

	revoke_universal_authority_relationship(
		store,
		registry,
		view.principal_membership_root,
		reason="application access removed",
	)
	with pytest.raises(AuthorizationDenied, match="default-deny"):
		project_universal_canvas(
			store, registry, authentication_context=member_context
		)
	founder_projection = project_universal_canvas(store, registry)
	revoked = next(
		item for item in founder_projection["authorization"]["relationships"]
		if item["root"] == view.principal_membership_root
	)
	assert revoked["state"] == "revoked"
	assert revoked["verified"] is True
	assert revoked["changed_by"] == authority.subject_root


def test_desktop_authentication_session_is_visible_and_renews_after_revocation():
	store, registry = build_universal_application(resolve_map_path())
	authority = registry.authorization
	members = read_relation(
		store.snapshot(), authority.session.root_id, budget=64
	)
	participants = {member.participant_id for member in members}
	assert {
		authority.subject_root,
		authority.principal_root,
		authority.tenant_root,
		authority.assurance_root,
		registry.application_root,
		registry.canvas_root,
		registry.selection_state_root,
		registry.properties_lens_root,
		registry.view_sessions[authority.subject_root].visibility_root,
	}.issubset(participants)

	first = authority.session.context()
	authority.broker.revoke(first)
	with pytest.raises(AuthorizationDenied):
		authority.broker.resolve(first)
	projection = project_universal_canvas(store, registry)
	renewed = authority.session.context()
	assert renewed is not first
	assert projection["authorization"]["session"] == authority.session.root_id
	assert projection["authorization"]["subject"] == authority.subject_root


def test_member_view_selection_and_viewport_do_not_mutate_another_users_view():
	store, registry = build_universal_application(resolve_map_path())
	authority = registry.authorization
	subjects = ("test:identity:member-a", "test:identity:member-b")
	store.commit(store.revision, create=tuple(
		Cell(root, NULL_CELL_ID, NULL_CELL_ID, root.encode("ascii"))
		for root in subjects
	))
	sessions = {
		root: provision_universal_view_session(
			store,
			registry,
			root,
			visible_roots=list(registry.map.domains.values()),
		)[0]
		for root in subjects
	}
	contexts = {
		root: authority.broker.mint_authenticated_context(
			root,
			principal_roots=(authority.member_principal_root,),
			tenant_root=authority.tenant_root,
			assurance_root=authority.assurance_root,
			lifetime_seconds=120,
		)
		for root in subjects
	}
	selected = registry.visible_roots[4]
	set_universal_selection(
		store, registry, [selected], focus_root=selected,
		authentication_context=contexts[subjects[0]],
	)
	apply_universal_canvas_gesture(
		store, registry,
		viewport={"pan_x": 81, "pan_y": 42, "zoom": 1.25},
		authentication_context=contexts[subjects[0]],
	)
	preview_universal_theme(
		store, registry, {"accent": "#1188cc"},
		authentication_context=contexts[subjects[0]],
	)

	first = project_universal_canvas(
		store, registry, authentication_context=contexts[subjects[0]]
	)
	second = project_universal_canvas(
		store, registry, authentication_context=contexts[subjects[1]]
	)
	founder = project_universal_canvas(store, registry)
	first_theme, _ = read_universal_theme(
		store, registry, authentication_context=contexts[subjects[0]]
	)
	second_theme, _ = read_universal_theme(
		store, registry, authentication_context=contexts[subjects[1]]
	)
	founder_theme, _ = read_universal_theme(store, registry)
	assert first["authorization"]["session"] == sessions[subjects[0]].root_id
	assert first["selection"] == [selected]
	assert first["viewport"] == {"pan_x": 81.0, "pan_y": 42.0, "zoom": 1.25}
	assert second["authorization"]["session"] == sessions[subjects[1]].root_id
	assert second["selection"] == []
	assert second["viewport"] == {"pan_x": 18.0, "pan_y": 18.0, "zoom": 0.82}
	assert founder["authorization"]["session"] == authority.session.root_id
	assert founder["viewport"] == {"pan_x": 18.0, "pan_y": 18.0, "zoom": 0.82}
	assert first_theme["accent"] == "#1188cc"
	assert second_theme["accent"] == founder_theme["accent"] == "#d97757"
	with pytest.raises(AuthorizationDenied):
		move_universal_root(
			store, registry, selected, 999, 999,
			authentication_context=contexts[subjects[0]],
		)


def test_projection_reads_all_domain_cards_and_explicit_relation_cells(application):
	store, registry = build_universal_application(resolve_map_path())
	projection = project_universal_canvas(store, registry)
	assert {node["id"] for node in projection["nodes"]} == set(registry.visible_roots)
	assert set(registry.visible_roots) == {
		*registry.map.domains.values(), registry.core_values.root_id,
		registry.governed_work_registry_root,
	}
	assert registry.application_root not in {
		node["id"] for node in projection["nodes"]
	}
	assert registry.library_root not in {
		node["id"] for node in projection["nodes"]
	}
	assert projection["scope"]["current"] == registry.canvas_root
	select_universal_root(store, registry, registry.application_root)
	application = project_universal_canvas(store, registry)
	assert {
		registry.canvas_root,
		registry.library_root,
		registry.authorization.policy_root,
		registry.authorization.identity_protocol.root_id,
		registry.tenant_configuration_protocol.root_id,
		registry.cloud_route_protocol.root_id,
		registry.cloud_session_protocol.root_id,
		registry.native_authentication_protocol.root_id,
	}.issubset({item["participant"] for item in application["connections"]})
	assert application["authorization"]["native_identity"] == {
		"protocol": registry.native_authentication_protocol.root_id,
		"configured_clients": 0,
		"transactions": 0,
		"completions": 0,
		"provider_status": "not-configured",
		"device_custody": {
			"protocol": registry.device_custody_protocol.root_id,
			"registered": 0,
			"active": 0,
			"hardware_backed": 0,
			"production_requirement": "TPM-backed",
		},
	}
	select_universal_root(store, registry, registry.library_root)
	library = project_universal_canvas(store, registry)
	assert library["selected"] == registry.library_root
	assert len(read_relation(
		store.snapshot(), registry.library_root, budget=16
	)) == 5
	assert {(item["role"], item["participant"])
			for item in library["connections"]} == {
		("seed", registry.primitive_root),
		("catalog", registry.standard_library.catalog_root),
		*(("relation", section["id"])
		  for section in library["catalog_sections"]),
	}
	assert {item["participant_label"] for item in library["connections"]} == {
		"Universal cell", "Released node catalogue",
		*(section["label"] for section in library["catalog_sections"]),
	}
	top_wires = {wire["id"] for wire in projection["wires"]}
	assert top_wires == set(registry.relation_roots) - {registry.workshop_work_wire_root}
	set_universal_scope(store, registry, registry.map.domains["brain"])
	brain = project_universal_canvas(store, registry)
	assert registry.workshop_workbench_root in {
		node["id"] for node in brain["nodes"]
	}
	assert registry.workshop_work_wire_root not in {
		wire["id"] for wire in brain["wires"]
	}
	set_universal_scope(store, registry)
	assert all(wire["id"] in store.snapshot().cells for wire in projection["wires"])
	assert projection["primitive"]["fields"] == ["identity", "link 0", "link 1", "atom"]


def test_properties_projection_materializes_only_the_active_panel(application):
	store, registry = application
	projection = project_universal_canvas(store, registry)
	panels = projection["inspector"]["presentation"]["panels"]
	active = [panel for panel in panels if panel["active"]]
	inactive = [panel for panel in panels if not panel["active"]]
	assert len(active) == 1
	assert active[0]["components"]
	assert inactive
	assert all(panel["components"] == [] for panel in inactive)


def test_founder_descends_only_through_direct_relation_participants():
	store, registry = build_universal_application(resolve_map_path())
	select_universal_root(store, registry, registry.library_root)
	library = project_universal_canvas(store, registry)
	assert all(item["navigable"] for item in library["connections"])

	set_universal_selection(
		store,
		registry,
		[],
		focus_root=registry.standard_library.catalog_root,
	)
	catalog = project_universal_canvas(store, registry)
	assert catalog["selected"] == registry.standard_library.catalog_root
	assert catalog["connections"]
	assert all(item["navigable"] for item in catalog["connections"])

	arbitrary_root = registry.map.nodes["ui_design_tokens"]
	assert arbitrary_root not in {
		item["participant"] for item in catalog["connections"]
	}
	with pytest.raises(InvalidCell, match="outside the active canvas"):
		set_universal_selection(
			store,
			registry,
			[],
			focus_root=arbitrary_root,
		)


def test_member_cannot_descend_through_founder_application_internals():
	store, registry = build_universal_application(resolve_map_path())
	authority = registry.authorization
	member_root = "test:identity:bounded-navigation-member"
	store.commit(store.revision, create=(
		Cell(member_root, NULL_CELL_ID, NULL_CELL_ID, b"Bounded member"),
	))
	provision_universal_view_session(
		store,
		registry,
		member_root,
		visible_roots=list(registry.map.domains.values()),
	)
	context = authority.broker.mint_authenticated_context(
		member_root,
		principal_roots=(authority.member_principal_root,),
		tenant_root=authority.tenant_root,
		assurance_root=authority.assurance_root,
		lifetime_seconds=120,
	)
	select_universal_root(
		store,
		registry,
		registry.application_root,
		authentication_context=context,
	)
	projection = project_universal_canvas(
		store, registry, authentication_context=context
	)
	assert projection["connections"] == []
	with pytest.raises(InvalidCell, match="outside the active canvas"):
		set_universal_selection(
			store,
			registry,
			[],
			focus_root=registry.authorization.policy_root,
			authentication_context=context,
		)


def test_member_visibility_requires_an_exact_active_signed_projection_grant():
	store, registry = build_universal_application(resolve_map_path())
	authority = registry.authorization
	subject_root = "test:identity:signed-projection-member"
	store.commit(store.revision, create=(
		Cell(subject_root, NULL_CELL_ID, NULL_CELL_ID, b"Projection member"),
	))
	assigned_root, resource_root, tamper_root, injected_root = (
		registry.visible_roots[:4]
	)
	_view, _ = provision_universal_view_session(
		store,
		registry,
		subject_root,
		visible_roots=(assigned_root,),
	)
	context = authority.broker.mint_authenticated_context(
		subject_root,
		tenant_root=authority.tenant_root,
		assurance_root=authority.assurance_root,
		lifetime_seconds=120,
	)
	read_request = AuthorizationRequest(
		action_root=authority.protocol.actions["read"],
		object_root=assigned_root,
		resource_lineage_roots=(authority.scope_root,),
		purpose_root=authority.purpose_root,
		classification_root=authority.classification_root,
		audience_root=authority.audience_root,
	)
	decision = require_authorization(
		store.snapshot(),
		authority.protocol,
		authority.policy_root,
		authority.broker,
		context,
		read_request,
	)
	assert decision.allowed is True
	assert decision.determining_rule_roots == (
		"app:authorization:rule:resource-reader:read",
	)
	with pytest.raises(AuthorizationDenied, match="default-deny"):
		require_authorization(
			store.snapshot(),
			authority.protocol,
			authority.policy_root,
			authority.broker,
			context,
			AuthorizationRequest(
				action_root=authority.protocol.actions["read"],
				object_root=resource_root,
				resource_lineage_roots=(authority.scope_root,),
				purpose_root=authority.purpose_root,
				classification_root=authority.classification_root,
				audience_root=authority.audience_root,
			),
		)
	projection = project_universal_canvas(
		store, registry, authentication_context=context
	)
	assert [node["id"] for node in projection["nodes"]] == [assigned_root]
	grants = [
		relationship
		for relationship in projection["authorization"]["relationships"]
		if relationship["kind"] == "delegation"
		and relationship["source"]
		== authority.resource_reader_principal_root
		and relationship["target"] == subject_root
	]
	assert len(grants) == 1
	assert grants[0]["scope"] == assigned_root
	assert grants[0]["state"] == "active"
	assert grants[0]["verified"] is True
	apply_universal_canvas_gesture(
		store,
		registry,
		roots=[],
		focus_root=grants[0]["root"],
		authentication_context=context,
	)
	inspected = project_universal_canvas(
		store, registry, authentication_context=context
	)
	assert inspected["selected_title"] == (
		"delegation: Authorized resource reader -> Projection member"
	)
	revoke_universal_authority_relationship(
		store,
		registry,
		grants[0]["root"],
		reason="remove this resource from the member's projection",
	)
	with pytest.raises(AuthorizationDenied, match="default-deny"):
		require_authorization(
			store.snapshot(),
			authority.protocol,
			authority.policy_root,
			authority.broker,
			context,
			read_request,
		)
	with pytest.raises(InvalidCell, match="signed projection grants"):
		project_universal_canvas(
			store, registry, authentication_context=context
		)

	resource_subject_root = "test:identity:resource-binding-member"
	store.commit(store.revision, create=(
		Cell(
			resource_subject_root,
			NULL_CELL_ID,
			NULL_CELL_ID,
			b"Resource binding member",
		),
	))
	provision_universal_view_session(
		store,
		registry,
		resource_subject_root,
		visible_roots=(resource_root,),
	)
	resource_context = authority.broker.mint_authenticated_context(
		resource_subject_root,
		tenant_root=authority.tenant_root,
		assurance_root=authority.assurance_root,
		lifetime_seconds=120,
	)
	assert project_universal_canvas(
		store, registry, authentication_context=resource_context
	)["nodes"][0]["id"] == resource_root
	resource_binding = next(
		relationship
		for relationship in project_universal_canvas(
			store, registry
		)["authorization"]["relationships"]
		if relationship["kind"] == "audience-binding"
		and relationship["source"] == resource_root
		and relationship["target"] == authority.audience_root
	)
	revoke_universal_authority_relationship(
		store,
		registry,
		resource_binding["root"],
		reason="withdraw this resource from the workspace audience",
	)
	with pytest.raises(InvalidCell, match="active signed audience binding"):
		project_universal_canvas(
			store, registry, authentication_context=resource_context
		)

	tamper_subject_root = "test:identity:tampered-projection-member"
	store.commit(store.revision, create=(
		Cell(
			tamper_subject_root,
			NULL_CELL_ID,
			NULL_CELL_ID,
			b"Tampered projection member",
		),
	))
	tampered_view, _ = provision_universal_view_session(
		store,
		registry,
		tamper_subject_root,
		visible_roots=(tamper_root,),
	)
	tampered_context = authority.broker.mint_authenticated_context(
		tamper_subject_root,
		tenant_root=authority.tenant_root,
		assurance_root=authority.assurance_root,
		lifetime_seconds=120,
	)

	snapshot = store.snapshot()
	patch = prepare_append_relation_members(
		snapshot,
		tampered_view.visibility_root,
		((registry.roles["visible"], injected_root),),
		budget=100_000,
	)
	store.commit(
		snapshot.revision,
		create=patch.create,
		replace=patch.replace,
	)
	with pytest.raises(InvalidCell, match="signed projection grants"):
		project_universal_canvas(
			store, registry, authentication_context=tampered_context
		)


def test_wip_resource_projection_is_limited_to_its_owner_or_founder():
	store, registry = build_universal_application(resolve_map_path())
	definition_root = next(
		item["id"]
		for item in project_universal_canvas(store, registry)["catalog"]
		if item["name"] == "Ordered List"
	)
	wip_root, _ = instantiate_universal_definition(
		store,
		registry,
		definition_root,
		x=180.0,
		y=220.0,
	)
	assert wip_root in {
		node["id"] for node in project_universal_canvas(store, registry)["nodes"]
	}

	subject_root = "test:identity:foreign-wip-member"
	store.commit(store.revision, create=(
		Cell(subject_root, NULL_CELL_ID, NULL_CELL_ID, b"Foreign WIP member"),
	))
	revision_before = store.revision
	with pytest.raises(InvalidCell, match="WIP resource"):
		provision_universal_view_session(
			store,
			registry,
			subject_root,
			visible_roots=(wip_root,),
		)
	assert store.revision == revision_before
	assert subject_root not in registry.view_sessions


def test_relation_contract_projects_and_commits_one_atomic_visible_wip():
	store, registry = build_universal_application(resolve_map_path())
	initial = project_universal_canvas(store, registry)
	definition = next(
		item for item in initial["catalog"]
		if item["name"] == "Model Descriptor"
	)
	contract = definition["composition_contract"]
	assert contract and len(contract["roles"]) > 10
	assert any(role["fixed"] for role in contract["roles"])

	participant_root = "test:visual-contract:participant"
	store.commit(store.revision, create=(
		Cell(participant_root, NULL_CELL_ID, NULL_CELL_ID, b"1"),
	))
	canvas_patch = prepare_append_relation_members(
		store.snapshot(),
		registry.canvas_root,
		((registry.roles["member"], participant_root),),
		budget=100_000,
	)
	store.commit(
		store.revision,
		create=canvas_patch.create,
		replace=canvas_patch.replace,
	)
	view = registry.view_sessions[registry.authorization.subject_root]
	administrator = registry.authorization.subject_root
	universal_application_module._issue_resource_audience_bindings(
		store,
		registry.authorization,
		resource_roots=(participant_root,),
		lifecycle_root=registry.standard_library.lifecycle_protocol.states["wip"],
		owner_root=view.subject_root,
		administrator_root=administrator,
	)
	grants = universal_application_module._issue_view_projection_grants(
		store,
		registry.authorization,
		subject_root=view.subject_root,
		visibility_root=view.visibility_root,
		target_roots=(participant_root,),
		administrator_root=administrator,
	)
	snapshot = store.snapshot()
	visibility_patch = prepare_append_relation_members(
		snapshot,
		view.visibility_root,
		((registry.roles["visible"], participant_root),),
		budget=100_000,
	)
	session_patch = prepare_append_relation_members(
		snapshot,
		view.root_id,
		((registry.roles["relation"], root) for root in grants),
		budget=100_000,
	)
	store.commit(
		snapshot.revision,
		create=(
			*visibility_patch.create,
			*session_patch.create,
		),
		replace=(
			*visibility_patch.replace,
			*session_patch.replace,
		),
	)

	bindings = tuple(
		(
			role["role"],
			role["fixed"]["id"] if role["fixed"] else participant_root,
		)
		for role in contract["roles"]
		for _ in range(role["minimum"])
	)
	hidden_bindings = tuple(
		(
			role["role"],
			role["fixed"]["id"] if role["fixed"] else registry.assembly_protocol.root_id,
		)
		for role in contract["roles"]
		for _ in range(role["minimum"])
	)
	rejected_revision = store.revision
	with pytest.raises(InvalidCell, match="outside the authorized canvas"):
		instantiate_universal_relation_definition(
			store,
			registry,
			definition["id"],
			hidden_bindings,
			x=420.0,
			y=260.0,
		)
	assert store.revision == rejected_revision
	before = store.revision
	created_root, revision = instantiate_universal_relation_definition(
		store,
		registry,
		definition["id"],
		bindings,
		x=420.0,
		y=260.0,
	)
	assert revision == before + 1
	created_cells = frozenset(store.snapshot().cells)
	undo_universal_change(store, registry)
	assert created_root in store.snapshot().cells
	assert created_root not in {
		node["id"] for node in project_universal_canvas(store, registry)["nodes"]
	}
	redo_universal_change(store, registry)
	assert created_root in {
		node["id"] for node in project_universal_canvas(store, registry)["nodes"]
	}
	assert created_cells.issubset(store.snapshot().cells)
	set_universal_inspector_lens(
		store, registry, registry.inspector_lens_roots["build"]
	)
	set_universal_properties_panel(
		store, registry, registry.properties_panel_roots["interfaces"]
	)
	projected = project_universal_canvas(store, registry)
	assert created_root in {node["id"] for node in projected["nodes"]}
	instance_members = read_relation(
		store.snapshot(), created_root, budget=100_000
	)
	part_roots = {
		member.participant_id for member in instance_members
		if member.role_id == registry.assembly_protocol.role("part")
	}
	relation_root = next(
		root for root in part_roots
		if root.startswith("app:wip-relation:")
	)
	nary_wires = [
		wire for wire in projected["wires"]
		if wire["id"] == relation_root
	]
	assert nary_wires
	assert all(wire["nary"] is True for wire in nary_wires)
	assert all(wire["target"] == created_root for wire in nary_wires)
	assert all(wire["target_interface"] for wire in nary_wires)
	assert len({wire["segment"] for wire in nary_wires}) == len(nary_wires)
	assert all(
		wire["source_interface"] == wire["segment"]
		for wire in nary_wires
	)
	node_by_root = {node["id"]: node for node in projected["nodes"]}
	for wire in nary_wires:
		incidence_port = next(
			port for port in node_by_root[wire["source"]]["ports"]
			if port["id"] == wire["segment"]
		)
		assert incidence_port["mode"] == "relation-incidence"
		assert incidence_port["relation"] == relation_root
		assert incidence_port["interface"] == wire["target_interface"]
		assert incidence_port["incidence"] == wire["segment"]
	assembly = projected["selected_assembly"]
	role_interfaces = [
		interface for interface in assembly["interfaces"]
		if interface["mode"] == "relation-role"
	]
	assert len(role_interfaces) == len(contract["roles"])
	assert {
		interface["member_role"] for interface in role_interfaces
	} == {role["role"] for role in contract["roles"]}
	assert all(
		item["role"] == interface["member_role"]
		for interface in role_interfaces
		for item in interface["items"]
	)
	descriptors = [
		descriptor
		for panel in projected["inspector"]["presentation"]["panels"]
		for component in panel["components"]
		for descriptor in component["descriptor"]
	]
	pending = list(descriptors)
	rendered = []
	while pending:
		descriptor = pending.pop()
		rendered.append(descriptor)
		pending.extend(descriptor.get("children", ()))
	role_selects = [
		descriptor for descriptor in rendered
		if (
			descriptor["tag"] == "select"
			and descriptor["attributes"].get("data-universal-control")
			and descriptor["attributes"].get(
				"data-universal-event-fact-input"
			)
		)
	]
	assert role_selects
	assert {
		descriptor["attributes"]["data-universal-control"]
		for descriptor in role_selects
	} == {
		item["replace_control"]
		for interface in role_interfaces
		for item in interface["items"]
	}
	assert {
		descriptor["attributes"]["data-universal-event-fact-input"]
		for descriptor in role_selects
	} == {
		item["replace_event_fact_input"]
		for interface in role_interfaces
		for item in interface["items"]
	}
	apply_universal_canvas_gesture(
		store, registry, roots=(), focus_root=relation_root
	)
	relation_projection = project_universal_canvas(store, registry)
	assert relation_projection["selected"] == relation_root
	assert relation_projection["selected_relation"]["nary"] is True
	assert relation_projection["selected_relation"]["participant_count"] == len(
		read_relation(store.snapshot(), relation_root, budget=100_000)
	)
	assert relation_projection["selected_title"].startswith("Relation / ")
	select_universal_root(store, registry, created_root)

	required = next(
		interface for interface in role_interfaces
		if (
			interface["fixed_participant"] is None
			and interface["minimum"] > 0
			and interface["items"]
		)
	)
	rejected_revision = store.revision
	with pytest.raises(InvalidCell, match="exact visible canvas root"):
		edit_universal_interface_collection(
			store,
			registry,
			created_root,
			required["id"],
			"edit",
			value=registry.assembly_protocol.root_id,
			incidence_id=required["items"][0]["incidence"],
		)
	assert store.revision == rejected_revision
	with pytest.raises(InvalidCell, match="below minimum cardinality"):
		edit_universal_interface_collection(
			store,
			registry,
			created_root,
			required["id"],
			"remove",
			incidence_id=required["items"][0]["incidence"],
		)
	assert store.revision == rejected_revision

	replacement = next(
		choice["id"] for choice in required["choices"]
		if choice["id"] != required["items"][0]["participant"]
	)
	edited_revision = edit_universal_interface_collection(
		store,
		registry,
		created_root,
		required["id"],
		"edit",
		value=replacement,
		incidence_id=required["items"][0]["incidence"],
	)
	assert edited_revision == rejected_revision + 1
	edited = project_universal_canvas(store, registry)
	edited_interface = next(
		interface for interface in edited["selected_assembly"]["interfaces"]
		if interface["id"] == required["id"]
	)
	assert edited_interface["items"][0]["participant"] == replacement


def test_browser_shell_theme_and_stylesheet_are_projected_from_application_cells(application):
	store, registry = application
	projection = project_universal_canvas(store, registry)
	page = project_universal_document(store, registry)
	assert registry.presentation.ui_root in store.snapshot().cells
	assert registry.presentation.stylesheet_root in store.snapshot().cells
	assert all(root in store.snapshot().cells
			   for root in registry.presentation.theme_roots.values())
	token_system = ensure_archhub_design_token_system(store, registry.presentation.theme_roots)
	assert DESIGN_TOKEN_SYSTEM_ROOT in store.snapshot().cells
	token_document = project_dtcg_format(store.snapshot(), token_system.protocol, token_system.token_set_root)
	assert token_document["action"]["primary"]["$value"] == "{color.accent}"
	assert 'class="archhub-app"' in page
	assert 'class="library-panel"' in page
	assert 'class="canvas-stage"' in page
	assert 'class="inspector"' in page
	parser = _ClassParentParser()
	parser.feed(page)
	assert "canvas" in parser.parents["selection-box"][0]
	assert "canvas-stage" not in parser.parents["selection-box"][0]
	assert "stage.append(box)" not in page
	authority_descriptor = render_view_template(
		store.snapshot(),
		registry.view_template_protocol,
		AUTHORITY_LIST_TEMPLATE_ROOT,
		projection,
	)
	pending = list(authority_descriptor)
	descriptor_text = []
	while pending:
		item = pending.pop()
		if "text" in item:
			descriptor_text.append(item["text"])
		pending.extend(item.get("children", ()))
	assert any(
		text.startswith("CURRENT AUTHORITY GRAPH")
		for text in descriptor_text
	)
	assert registry.authority_migration_root is None
	assert {
		registry.standard_library.catalog_root,
		registry.adapter_catalog_root,
		registry.device_custody_adapter_root,
		registry.composer_authority.root_id,
		registry.tenant_authority.configuration_root,
		registry.tenant_authority.published_revision_root,
		registry.tenant_release_selection.root_id,
	} == {item["root"] for item in projection["authority_stack"]}
	assert len(page.encode("utf-8")) < 250_000


def test_theme_edit_is_an_immutable_personal_wip_preview_not_a_broadcast():
	store, registry = build_universal_application(resolve_map_path())
	initial, initial_meta = read_universal_theme(store, registry)
	released_accent = store.read(
		registry.presentation.theme_roots["accent"]
	).atom
	revision = preview_universal_theme(
		store, registry, {"accent": "#00aa88"}
	)
	preview, preview_meta = read_universal_theme(store, registry)
	page = project_universal_document(store, registry)

	assert initial["accent"] == "#d97757"
	assert preview["accent"] == "#00aa88"
	assert preview_meta["preview_revision"] == revision
	assert preview_meta["parents"] == [initial_meta["preview_revision"]]
	assert preview_meta["wip_heads"] == [revision]
	assert store.read(registry.presentation.theme_roots["accent"]).atom == released_accent
	assert "--accent:#00aa88;" in page
	restored = restore_universal_theme_revision(
		store,
		registry,
		initial_meta["preview_revision"],
		base_revision_root=revision,
	)
	restored_theme, restored_meta = read_universal_theme(store, registry)
	assert restored_theme["accent"] == initial["accent"]
	assert restored_meta["preview_revision"] == restored
	assert set(restored_meta["parents"]) == {
		revision, initial_meta["preview_revision"]
	}
	with pytest.raises(InvalidCell, match="unknown token"):
		preview_universal_theme(store, registry, {"invented": "#ffffff"})


def test_theme_share_requires_exact_signed_court_and_does_not_broadcast():
	store, registry = build_universal_application(resolve_map_path())
	source = preview_universal_theme(
		store, registry, {"accent": "#1188cc"}
	)
	promoted, evidence = promote_universal_theme_to_shared(
		store, registry, source_revision_root=source
	)
	snapshot = store.snapshot()
	lifecycle = registry.standard_library.lifecycle_protocol
	founder_view = registry.view_sessions[registry.authorization.subject_root]
	instance = read_lifecycle_instance(
		snapshot,
		registry.assembly_protocol,
		lifecycle,
		founder_view.settings_root,
	)
	shared_heads = state_heads(
		snapshot,
		lifecycle,
		instance.state_pointers[lifecycle.states["shared"]],
	)
	revision = read_revision(snapshot, lifecycle, promoted)
	attestation = read_court_attestation(
		snapshot, registry.attestation_protocol, evidence
	)
	assert shared_heads == (promoted,)
	assert revision.state_root == lifecycle.states["shared"]
	assert revision.predecessor_roots == (source,)
	assert revision.evidence_roots == (evidence,)
	assert attestation.court_root == registry.theme_court_root
	assert attestation.result_root == registry.attestation_protocol.states["passed"]
	assert store.read(
		registry.presentation.theme_roots["accent"]
	).atom == b"#d97757"

	member = "test:identity:share-denied-member"
	store.commit(store.revision, create=(
		Cell(member, NULL_CELL_ID, NULL_CELL_ID, b"Member"),
	))
	provision_universal_view_session(store, registry, member)
	context = registry.authorization.broker.mint_authenticated_context(
		member,
		principal_roots=(registry.authorization.member_principal_root,),
		tenant_root=registry.authorization.tenant_root,
		assurance_root=registry.authorization.assurance_root,
		lifetime_seconds=120,
	)
	member_theme, _ = read_universal_theme(
		store, registry, authentication_context=context
	)
	assert member_theme["accent"] == "#d97757"
	with pytest.raises(AuthorizationDenied):
		promote_universal_theme_to_shared(
			store, registry, authentication_context=context
		)

	projection = project_universal_canvas(store, registry)
	shared = next(
		item for item in projection["configuration"]["history"]
		if item["revision"] == promoted
	)
	assert shared["state"] == "SHARED"
	assert len(shared["evidence"]) == 1
	assert shared["evidence"][0]["root"] == evidence
	assert shared["evidence"][0]["court"] == registry.theme_court_root
	assert shared["evidence"][0]["result"] == "passed"
	assert all(shared["evidence"][0]["checks"].values())


def test_shared_theme_reaches_only_the_explicitly_wired_audience():
	store, registry = build_universal_application(resolve_map_path())
	source = preview_universal_theme(
		store, registry, {"accent": "#2266aa"}
	)
	shared, _ = promote_universal_theme_to_shared(
		store, registry, source_revision_root=source
	)
	subjects = (
		"test:identity:theme-audience-a",
		"test:identity:theme-audience-b",
	)
	store.commit(store.revision, create=tuple(
		Cell(root, NULL_CELL_ID, NULL_CELL_ID, root.encode("ascii"))
		for root in subjects
	))
	for root in subjects:
		provision_universal_view_session(store, registry, root)
	contexts = {
		root: registry.authorization.broker.mint_authenticated_context(
			root,
			principal_roots=(registry.authorization.member_principal_root,),
			tenant_root=registry.authorization.tenant_root,
			assurance_root=registry.authorization.assurance_root,
			lifetime_seconds=120,
		)
		for root in subjects
	}

	assign_shared_universal_theme(store, registry, subjects[0], shared)
	first, first_meta = read_universal_theme(
		store, registry, authentication_context=contexts[subjects[0]]
	)
	second, second_meta = read_universal_theme(
		store, registry, authentication_context=contexts[subjects[1]]
	)
	assert first["accent"] == "#2266aa"
	assert first_meta["binding_mode"] == "direct-release"
	assert first_meta["preview_revision"] == shared
	assert second["accent"] == "#d97757"
	assert second_meta["binding_mode"] == "audience-fallback-personal"

	with pytest.raises(AuthorizationDenied):
		assign_shared_universal_theme(
			store,
			registry,
			subjects[1],
			shared,
			authentication_context=contexts[subjects[0]],
		)

	personal = preview_universal_theme(
		store,
		registry,
		{"accent": "#885522"},
		authentication_context=contexts[subjects[0]],
	)
	first, first_meta = read_universal_theme(
		store, registry, authentication_context=contexts[subjects[0]]
	)
	assert first["accent"] == "#885522"
	assert first_meta["binding_mode"] == "personal-wip"
	assert first_meta["preview_revision"] == personal


def test_one_signed_group_binding_reaches_members_without_per_user_release_copies():
	store, registry = build_universal_application(resolve_map_path())
	authority = registry.authorization
	source = preview_universal_theme(
		store, registry, {"accent": "#2255aa"}
	)
	shared, _ = promote_universal_theme_to_shared(
		store, registry, source_revision_root=source
	)
	project_group = "test:audience:project-group"
	subjects = (
		"test:identity:project-member-a",
		"test:identity:project-member-b",
		"test:identity:project-outsider",
	)
	store.commit(store.revision, create=(
		Cell(project_group, NULL_CELL_ID, NULL_CELL_ID, b"Project group"),
		*(Cell(root, NULL_CELL_ID, NULL_CELL_ID, root.encode("ascii"))
		  for root in subjects),
	))
	for subject in subjects:
		provision_universal_view_session(store, registry, subject)
	contexts = {
		subject: authority.broker.mint_authenticated_context(
			subject,
			tenant_root=authority.tenant_root,
			assurance_root=authority.assurance_root,
			lifetime_seconds=120,
		)
		for subject in subjects
	}
	membership_roots = []
	for subject in subjects[:2]:
		relationship_root, _ = issue_universal_authority_relationship(
			store,
			registry,
			source_root=subject,
			target_root=project_group,
			kind="membership",
			reason="assigned to the project",
		)
		membership_roots.append(relationship_root)

	audience_binding, _ = assign_released_universal_theme_to_audience(
		store,
		registry,
		project_group,
		shared,
		reason="Project group receives the tested Shared configuration",
	)
	member_a, member_a_meta = read_universal_theme(
		store, registry, authentication_context=contexts[subjects[0]]
	)
	member_b, member_b_meta = read_universal_theme(
		store, registry, authentication_context=contexts[subjects[1]]
	)
	outsider, outsider_meta = read_universal_theme(
		store, registry, authentication_context=contexts[subjects[2]]
	)
	assert member_a["accent"] == member_b["accent"] == "#2255aa"
	assert member_a_meta["binding_mode"] == "audience-release"
	assert member_b_meta["binding_mode"] == "audience-release"
	assert outsider["accent"] == "#d97757"
	assert outsider_meta["binding_mode"] == "audience-fallback-personal"

	snapshot = store.snapshot()
	for subject in subjects[:2]:
		view = registry.view_sessions[subject]
		binding = read_relation(snapshot, view.theme_binding_root, budget=8)
		assert next(
			item.participant_id for item in binding
			if item.role_id == registry.roles["binding-mode"]
		) == registry.theme_binding_modes["audience-release"]
		assert next(
			item.participant_id for item in binding
			if item.role_id == registry.roles["target"]
		) == view.settings_root
	audience_relations = [
		item for item in project_universal_canvas(store, registry)[
			"authorization"
		]["relationships"]
		if item["kind"] == "audience-binding"
		and item["state"] == "active"
		and item["target"] == project_group
	]
	assert [item["root"] for item in audience_relations] == [audience_binding]

	preview_universal_theme(
		store,
		registry,
		{"accent": "#bb3344"},
		authentication_context=contexts[subjects[0]],
	)
	member_a, member_a_meta = read_universal_theme(
		store, registry, authentication_context=contexts[subjects[0]]
	)
	member_b, _ = read_universal_theme(
		store, registry, authentication_context=contexts[subjects[1]]
	)
	assert member_a["accent"] == "#bb3344"
	assert member_a_meta["binding_mode"] == "personal-wip"
	assert member_b["accent"] == "#2255aa"

	follow_universal_theme_audience(
		store, registry, authentication_context=contexts[subjects[0]]
	)
	member_a, member_a_meta = read_universal_theme(
		store, registry, authentication_context=contexts[subjects[0]]
	)
	assert member_a["accent"] == "#2255aa"
	assert member_a_meta["binding_mode"] == "audience-release"

	revoke_universal_authority_relationship(
		store,
		registry,
		membership_roots[0],
		reason="removed from the project",
	)
	removed, removed_meta = read_universal_theme(
		store, registry, authentication_context=contexts[subjects[0]]
	)
	remaining, remaining_meta = read_universal_theme(
		store, registry, authentication_context=contexts[subjects[1]]
	)
	assert removed["accent"] == "#bb3344"
	assert removed_meta["binding_mode"] == "audience-fallback-personal"
	assert remaining["accent"] == "#2255aa"
	assert remaining_meta["binding_mode"] == "audience-release"


def test_library_primitive_is_floor_only_and_raw_floor_edit_is_denied(application):
	store, registry = application
	members = read_relation(store.snapshot(), registry.library_root, budget=8)
	projection = project_universal_canvas(store, registry)
	assert [(m.role_id, m.participant_id) for m in members] == [
		(registry.roles["seed"], registry.primitive_root),
		(registry.roles["catalog"], registry.standard_library.catalog_root),
		*((registry.roles["relation"], section["id"])
		  for section in projection["catalog_sections"]),
	]
	select_universal_root(store, registry, registry.primitive_root)
	projection = project_universal_canvas(store, registry)
	assert projection["selected"] == registry.primitive_root
	assert projection["primitive"]["visible"] is False
	set_universal_inspector_lens(store, registry, registry.inspector_lens_roots["floor"])
	projection = project_universal_canvas(store, registry)
	assert projection["primitive"]["visible"] is True
	assert projection["physical"] == {
		"identity": registry.primitive_root,
		"link0": NULL_CELL_ID,
		"link1": NULL_CELL_ID,
		"atom": "Universal cell",
		"editable": False,
		"control": None,
		"event_fact_input": None,
	}
	with pytest.raises(InvalidCell, match="closed grammar"):
		edit_universal_cell_atom(store, registry, registry.primitive_root, b"Stem")
	assert project_universal_canvas(store, registry)["physical"]["atom"] == "Universal cell"
	set_universal_inspector_lens(store, registry, registry.inspector_lens_roots["use"])


def test_primitive_drag_target_creates_one_atomic_editable_wip_cell():
	store, registry = build_universal_application(resolve_map_path())
	before = store.revision
	root_id, revision = instantiate_universal_primitive(
		store,
		registry,
		x=360.0,
		y=220.0,
		title="Design value",
		atom="concept",
	)
	assert revision == before + 1
	assert root_id.startswith("app:wip-cell:")
	created = store.read(root_id)
	assert (created.link0, created.link1, created.atom) == (
		NULL_CELL_ID, NULL_CELL_ID, b"concept"
	)
	projection = project_universal_canvas(store, registry)
	assert projection["selected"] == root_id
	assert root_id in {node["id"] for node in projection["nodes"]}
	assert projection["selected_title"] == "Design value"
	value = next(
		row for row in projection["properties"] if row["label"] == "value"
	)
	assert value["value_root"] == root_id
	assert value["editable"] is True
	color = next(
		row for row in projection["properties"] if row["label"] == "color"
	)
	assert color["presentation_editable"] is True
	assert color["editable"] is False
	color_revision = preview_universal_presentation_color(
		store, registry, root_id, "#2f80ed"
	)
	colored = project_universal_canvas(store, registry)
	assert next(
		node["color"] for node in colored["nodes"] if node["id"] == root_id
	) == "#2f80ed"
	assert next(
		row for row in colored["properties"] if row["label"] == "color"
	)["presentation_revision"] == color_revision
	edited = edit_universal_property(
		store, registry, value["relation"], "approved concept"
	)
	assert edited == root_id
	assert store.read(root_id).atom == b"approved concept"
	assert project_universal_canvas(store, registry)["physical"]["atom"] == (
		"approved concept"
	)


def test_selecting_a_card_rewires_the_properties_lens(application):
	store, registry = build_universal_application(resolve_map_path())
	target = registry.visible_roots[3]
	before = store.revision
	select_universal_root(store, registry, target)
	projection = project_universal_canvas(store, registry)
	assert store.revision == before + 1
	assert projection["selected"] == target
	assert {row["label"] for row in projection["properties"]} >= {
		"key", "title", "position_x", "position_y"
	}


def test_multi_selection_is_explicit_incidence_state_not_a_hidden_array(application):
	store, registry = build_universal_application(resolve_map_path())
	roots = list(registry.visible_roots[1:4])
	before = store.revision
	set_universal_selection(store, registry, roots, focus_root=roots[-1])
	projection = project_universal_canvas(store, registry)
	assert store.revision == before + 1
	assert set(projection["selection"]) == set(roots)
	assert projection["selected"] == roots[-1]
	selected_incidences = [
		store.read(registry.selection_incidences[root_id])
		for root_id in roots
	]
	assert all(cell.link0 == registry.roles["selected"] for cell in selected_incidences)


def test_multi_selection_properties_are_common_graph_controls_and_edit_atomically():
	store, registry = build_universal_application(resolve_map_path())
	first, _ = instantiate_universal_primitive(
		store, registry, x=420, y=180, title="First Cell", atom="first"
	)
	second, _ = instantiate_universal_primitive(
		store, registry, x=760, y=360, title="Second Cell", atom="second"
	)
	create_universal_property(
		store, registry, first, "first_only", "must not be projected"
	)
	set_universal_selection(store, registry, (first, second), focus_root=second)

	projection = project_universal_canvas(store, registry)
	properties = {row["label"]: row for row in projection["properties"]}
	assert "first_only" not in properties
	assert properties["title"]["mixed"] is True
	assert properties["title"]["value"] == "Varies"
	assert properties["title"]["owners"] == sorted((first, second))
	assert len(properties["title"]["relations"]) == 2
	assert len(properties["title"]["value_roots"]) == 2

	interactions, _fact_protocol, _fact_specs = (
		ensure_universal_property_interactions(
			store, registry, registry.authorization.subject_root, projection
		)
	)
	projection = project_universal_canvas(store, registry)
	title = next(row for row in projection["properties"] if row["label"] == "title")
	control_root = title["control"]
	assert control_root in store.snapshot().cells
	control_members = read_relation(store.snapshot(), control_root)
	assert {
		member.participant_id for member in control_members
		if member.role_id == registry.roles["selected"]
	} == {first, second}
	assert {
		member.participant_id for member in control_members
		if member.role_id == registry.roles["property"]
	} == set(title["relations"])
	assert {
		member.participant_id for member in control_members
		if member.role_id == registry.roles["value"]
	} == set(title["value_roots"])

	view = registry.view_sessions[registry.authorization.subject_root]
	browser_session_root = "test:multi-property-browser-session"
	store.commit(store.revision, create=(Cell(
		browser_session_root, NULL_CELL_ID, NULL_CELL_ID,
		b"multi property browser session",
	),))
	broker = InteractionProjectionBroker()
	handle = broker.mint(
		store.snapshot(),
		session_root=browser_session_root,
		subject_root=registry.authorization.subject_root,
		view_root=view.root_id,
	)
	broker.issue(
		handle,
		store.snapshot(),
		registry.interaction_protocol,
		tuple(interactions),
		tuple(interactions.values()),
		rule_protocol=registry.rule_protocol,
		transaction_protocol=registry.transaction_protocol,
		admitted_nontransaction_action_roots=(CAPABILITY_EDIT_VALUE,),
	)
	original_atoms = {
		root: store.read(root).atom for root in title["value_roots"]
	}
	before_revision = store.revision
	before_history = len(read_relation(store.snapshot(), view.action_history_root))
	execution = submit_universal_edit_value_interaction(
		store,
		registry,
		broker,
		handle,
		interaction_root=interactions[control_root],
		control_root=control_root,
		event_root="app:interaction-event:change",
		event_facts=[{
			"input": title["event_fact_input"],
			"value": "Shared title",
		}],
		expected_revision=before_revision,
		authentication_context=registry.authorization.session.context(),
	)
	assert execution.revision == before_revision + 1
	assert all(store.read(root).atom == b"Shared title" for root in title["value_roots"])
	assert len(read_relation(store.snapshot(), view.action_history_root)) == before_history + 1
	updated = project_universal_canvas(store, registry)
	updated_title = next(
		row for row in updated["properties"] if row["label"] == "title"
	)
	assert updated_title["mixed"] is False
	assert updated_title["value"] == "Shared title"

	undo_universal_change(store, registry)
	assert {
		root: store.read(root).atom for root in title["value_roots"]
	} == original_atoms


def test_property_edit_replaces_the_value_cell_and_reprojects(application):
	store, registry = build_universal_application(resolve_map_path())
	target = registry.visible_roots[3]
	select_universal_root(store, registry, target)
	projection = project_universal_canvas(store, registry)
	title = next(row for row in projection["properties"] if row["label"] == "title")
	value_root = title["value_root"]
	before_identity = store.read(value_root).id
	edit_universal_property(store, registry, title["relation"], "Editable domain")
	updated = project_universal_canvas(store, registry)
	assert store.read(value_root).id == before_identity
	assert store.read(value_root).atom == b"Editable domain"
	assert next(node for node in updated["nodes"] if node["id"] == target)["label"] == "Editable domain"


def test_dragging_a_card_commits_both_position_atoms_atomically(application):
	store, registry = build_universal_application(resolve_map_path())
	target = registry.visible_roots[2]
	before = store.revision
	move_universal_root(store, registry, target, 321.5, 654.25)
	projection = project_universal_canvas(store, registry)
	node = next(node for node in projection["nodes"] if node["id"] == target)
	assert store.revision == before + 1
	assert (node["x"], node["y"]) == (321.5, 654.25)


def test_whole_canvas_gesture_is_one_atomic_revision(application):
	store, registry = build_universal_application(resolve_map_path())
	roots = list(registry.visible_roots[4:7])
	before = store.revision
	apply_universal_canvas_gesture(
		store, registry,
		roots=roots,
		focus_root=roots[-1],
		positions={roots[0]: {"x": 111, "y": 222}},
		viewport={"pan_x": 12, "pan_y": 18, "zoom": 0.8},
	)
	projection = project_universal_canvas(store, registry)
	moved = next(node for node in projection["nodes"] if node["id"] == roots[0])
	assert store.revision == before + 1
	assert set(projection["selection"]) == set(roots)
	assert (moved["x"], moved["y"]) == (111, 222)
	assert projection["viewport"] == {"pan_x": 12.0, "pan_y": 18.0, "zoom": 0.8}


def test_selecting_a_wire_inspects_its_real_incidence_cells(application):
	store, registry = build_universal_application(resolve_map_path())
	relation_root = registry.relation_roots[0]
	select_universal_root(store, registry, relation_root)
	projection = project_universal_canvas(store, registry)
	assert projection["selected"] == relation_root
	assert {item["role"] for item in projection["connections"]} >= {
		"source", "target", "authority"
	}
	source = next(item for item in projection["connections"] if item["role"] == "source")
	target = next(item for item in projection["connections"] if item["role"] == "target")
	authority = next(
		item for item in projection["connections"] if item["role"] == "authority"
	)
	relation = projection["selected_relation"]
	wire = next(item for item in projection["wires"] if item["id"] == relation_root)
	assert relation["id"] == relation_root
	assert source["participant_owner"] == wire["source"]
	assert target["participant_owner"] == wire["target"]
	assert source["participant_interface"] == wire["source_interface"]
	assert target["participant_interface"] == wire["target_interface"]
	assert authority["editable"] is False
	assert authority["navigable"] is True
	assert relation["gates"] == [authority]
	assert projection["selected_title"] == "%s -> %s" % (
		source["participant_label"], target["participant_label"]
	)
	assert {item["label"] for item in projection["properties"]} >= {
		"color", "width", "dash"
	}
	replacement = registry.map.domains["nodes"]
	replacement_node = next(n for n in projection["nodes"] if n["id"] == replacement)
	replacement_interface = next(p["id"] for p in replacement_node["ports"] if p["side"] == "source" and p["connectable"])
	previous_interface = wire["source_interface"]
	before_rewire = store.revision
	rewire_universal_connection(store, registry, source["incidence"], replacement_interface)
	assert store.revision == before_rewire + 1
	rewired = next(wire for wire in project_universal_canvas(store, registry)["wires"]
				   if wire["id"] == relation_root)
	assert rewired["source"] == replacement
	assert rewired["source_interface"] == replacement_interface
	snapshot = store.snapshot()
	previous_members = read_relation(
		snapshot, previous_interface, budget=100_000
	)
	replacement_members = read_relation(
		snapshot, replacement_interface, budget=100_000
	)
	assert not any(
		member.role_id == registry.roles["seed"]
		and member.participant_id == relation_root
		for member in previous_members
	)
	assert not any(
		member.role_id == registry.roles["authority"]
		and member.participant_id == source["incidence"]
		for member in previous_members
	)
	assert any(
		member.role_id == registry.roles["seed"]
		and member.participant_id == relation_root
		for member in replacement_members
	)
	assert any(
		member.role_id == registry.roles["authority"]
		and member.participant_id == source["incidence"]
		for member in replacement_members
	)


def test_lens_rejects_hidden_or_fabricated_targets(application):
	store, registry = build_universal_application(resolve_map_path())
	with pytest.raises(InvalidCell):
		select_universal_root(store, registry, registry.map.nodes["ui_design_tokens"])
	with pytest.raises(InvalidCell):
		edit_universal_property(store, registry, "fabricated", "x")
	with pytest.raises(InvalidCell):
		move_universal_root(store, registry, registry.relation_roots[0], 0, 0)


def test_catalogue_assemblies_drop_inspect_wire_and_run_on_the_same_canvas():
	store, registry = build_universal_application(resolve_map_path())
	initial = project_universal_canvas(store, registry)
	assert [item["name"] for item in initial["catalog"]] == [
		"Ordered List", "Watcher", "Versioned Asset",
		"Database Transaction", "Monetary Intent", "Geometry Asset",
		"CDE Governed Asset", "Knowledge Branch", "Governed Work", "Permission Request",
		"Model Descriptor", "Model Binding", "Cognition Request", "Proposal",
	]
	assert [section["label"] for section in initial["catalog_sections"]] == [
		"Core Assemblies", "Governed Data & Work", "Agents & Cognition",
	]
	assert [
		definition
		for section in initial["catalog_sections"]
		for definition in section["definitions"]
	] == [item["id"] for item in initial["catalog"]]
	snapshot = store.snapshot()
	library_sections = [
		member.participant_id
		for member in read_relation(snapshot, registry.library_root, budget=16)
		if member.role_id == registry.roles["relation"]
	]
	assert library_sections == [
		section["id"] for section in initial["catalog_sections"]
	]
	for section in initial["catalog_sections"]:
		members = read_relation(snapshot, section["id"], budget=64)
		assert [
			member.participant_id for member in members
			if member.role_id == registry.roles["member"]
		] == section["definitions"]
		label_roots = [
			member.participant_id for member in members
			if member.role_id == registry.roles["label"]
		]
		assert len(label_roots) == 1
		assert snapshot.cells[label_roots[0]].atom.decode("utf-8") == section["label"]


def test_catalogue_section_label_is_live_graph_data():
	store, registry = build_universal_application(resolve_map_path())
	initial = project_universal_canvas(store, registry)
	section_root = initial["catalog_sections"][0]["id"]
	snapshot = store.snapshot()
	label_root = next(
		member.participant_id
		for member in read_relation(snapshot, section_root, budget=64)
		if member.role_id == registry.roles["label"]
	)
	current = snapshot.cells[label_root]
	store.commit(snapshot.revision, replace=(Cell(
		label_root, current.link0, current.link1, b"Reusable Foundations"
	),))
	updated = project_universal_canvas(store, registry)
	assert updated["catalog_sections"][0]["label"] == "Reusable Foundations"
	assert "reusable foundations" in updated["catalog"][0]["search_text"]


def test_catalogue_entry_metadata_is_one_inspectable_graph_relation():
	store, registry = build_universal_application(resolve_map_path())
	projection = project_universal_canvas(store, registry)
	snapshot = store.snapshot()
	role_roots = universal_application_module._NODE_LIBRARY_ENTRY_ROLE_ROOTS
	contract_root = universal_application_module._NODE_LIBRARY_ENTRY_CONTRACT_ROOT
	seen = []
	for section in projection["catalog_sections"]:
		assert len(section["entries"]) == len(section["definitions"])
		for order, entry in enumerate(section["entries"]):
			definition = projection["catalog"][len(seen)]
			assert entry["definition"] == definition["id"]
			assert definition["metadata_root"] == entry["root"]
			assert definition["category_root"] == section["id"]
			assert definition["category"] == section["label"]
			assert definition["order"] == order
			assert definition["documentation"]
			assert definition["search_roots"]
			assert definition["search_text"] == definition["search_text"].casefold()
			assert definition["icon_root"] == registry.icon_roots["plus"]
			members = read_relation(snapshot, entry["root"], budget=256)
			by_role = {}
			for member in members:
				by_role.setdefault(member.role_id, []).append(member.participant_id)
			assert by_role[role_roots["contract"]] == [contract_root]
			assert by_role[role_roots["definition"]] == [definition["id"]]
			assert by_role[role_roots["category"]] == [section["id"]]
			assert by_role[role_roots["icon"]] == [registry.icon_roots["plus"]]
			assert len(by_role[role_roots["order"]]) == 1
			assert by_role[role_roots["search-term"]] == definition["search_roots"]
			seen.append(definition["id"])
	assert seen == [item["id"] for item in projection["catalog"]]

	before_list = store.revision
	list_root, list_revision = instantiate_universal_definition(
		store,
		registry,
		registry.standard_library.definition_roots[0],
		x=420,
		y=180,
	)
	assert list_revision == before_list + 1
	before_watcher = store.revision
	watcher_viewport = {"pan_x": -512, "pan_y": 96, "zoom": 0.82}
	watcher_root, watcher_revision = instantiate_universal_definition(
		store,
		registry,
		registry.standard_library.definition_roots[1],
		x=700,
		y=180,
		viewport=watcher_viewport,
	)
	assert watcher_revision == before_watcher + 1
	placed = project_universal_canvas(store, registry)
	assert placed["viewport"] == {
		"pan_x": -512.0, "pan_y": 96.0, "zoom": 0.82,
	}
	assert {list_root, watcher_root}.issubset(
		{node["id"] for node in placed["nodes"]}
	)
	assert placed["selected"] == watcher_root
	assert {row["label"] for row in placed["properties"]} == {
		"title", "position_x", "position_y", "color", "definition", "version"
	}
	color = next(
		row for row in placed["properties"] if row["label"] == "color"
	)
	assert color["presentation_editable"] is True
	assert color["editable"] is False
	color_revision = preview_universal_presentation_color(
		store, registry, watcher_root, "#2f80ed"
	)
	placed = project_universal_canvas(store, registry)
	assert next(
		node["color"] for node in placed["nodes"]
		if node["id"] == watcher_root
	) == "#2f80ed"
	assert next(
		row for row in placed["properties"] if row["label"] == "color"
	)["presentation_revision"] == color_revision
	assert next(
		row for row in placed["properties"] if row["label"] == "version"
	)["editable"] is False
	assert placed["selected_assembly"]["interfaces"][0]["name"] == "source"

	source_root = registry.map.domains["ui"]
	source_node = next(n for n in placed["nodes"] if n["id"] == source_root)
	source_interface = next(p["id"] for p in source_node["ports"] if p["side"] == "source" and p["connectable"])
	target_interface = placed["selected_assembly"]["interfaces"][0]["id"]
	before_connect = store.revision
	relation_root, _ = connect_universal_roots(store, registry, source_root, watcher_root, source_interface=source_interface, target_interface=target_interface)
	assert store.revision == before_connect + 1
	connected = project_universal_canvas(store, registry)
	wire = next(item for item in connected["wires"] if item["id"] == relation_root)
	assert (wire["source"], wire["target"]) == (source_root, watcher_root)
	assert wire["source_interface"] == source_interface
	assert any(
		port["id"] == source_interface
		and port["side"] == "source"
		and port["connectable"]
		for port in source_node["ports"]
	)
	assert wire["target_interface"] == target_interface
	relation = read_relation(store.snapshot(), relation_root, budget=256)
	source_incidence = next(
		member.incidence_id for member in relation
		if member.role_id == registry.roles["source"]
	)
	public_members = read_relation(
		store.snapshot(), source_interface, budget=100_000
	)
	assert any(
		member.role_id == registry.roles["seed"]
		and member.participant_id == relation_root
		for member in public_members
	)
	assert any(
		member.role_id == registry.roles["authority"]
		and member.participant_id == source_incidence
		for member in public_members
	)
	assert next(
		member.participant_id for member in relation
		if member.role_id == registry.roles["source"]
	) == source_interface
	assert next(
		member.participant_id for member in relation
		if member.role_id == registry.roles["target"]
	) == target_interface
	watcher = next(
		node["assembly"] for node in connected["nodes"]
		if node["id"] == watcher_root
	)
	assert watcher["interfaces"][0]["target"] == source_root

	engine = ReactionEngine(
		store,
		registry.assembly_protocol,
		registry.standard_library.reaction_protocol,
	)
	engine.drain()
	source = store.read(source_root)
	store.commit(store.revision, replace=(
		Cell(source.id, source.link0, source.link1, b"changed source"),
	))
	engine.drain()
	reaction_root = watcher["rules"][0]["id"]
	assert len(reaction_events(
		store.snapshot(),
		registry.standard_library.reaction_protocol,
		reaction_root,
	)) == 1


def test_versioned_asset_projects_real_heads_into_the_properties_lens():
	store, registry = build_universal_application(resolve_map_path())
	before = store.revision
	asset_root, revision = instantiate_universal_definition(
		store,
		registry,
		registry.standard_library.definition_roots[2],
		x=420,
		y=180,
	)
	assert revision == before + 1
	projected = project_universal_canvas(store, registry)
	assert projected["selected"] == asset_root
	lifecycle = projected["selected_assembly"]["lifecycle"]
	assert lifecycle is not None
	wip = next(item for item in lifecycle["states"] if item["name"] == "WIP")
	assert wip["head_count"] == 1
	assert len(wip["heads"]) == 1
	head = wip["heads"][0]
	assert head["revision"] == wip["revision"]
	assert head["content_digest"]
	assert head["branch_label"] == "main"
	assert head["parents"] == []
	assert head["actor"]
	assert head["evidence"] == []
	assert lifecycle["history"][0]["revision"] == head["revision"]


def test_lifecycle_content_port_appends_immutable_wip_and_preserves_branches():
	store, registry = build_universal_application(resolve_map_path())
	asset_root, _ = instantiate_universal_definition(
		store,
		registry,
		registry.standard_library.definition_roots[2],
		x=420,
		y=180,
	)
	before = project_universal_canvas(store, registry)["selected_assembly"]
	lifecycle_projection = before["lifecycle"]
	initial_wip = next(
		row for row in lifecycle_projection["states"] if row["name"] == "WIP"
	)["revision"]
	content_interface = lifecycle_projection["content_interface"]
	lifecycle = registry.standard_library.lifecycle_protocol
	initial_revision = read_revision(store.snapshot(), lifecycle, initial_wip)
	initial_content = store.read(initial_revision.content_root).atom
	store_revision = store.revision

	first_wip, committed = edit_universal_lifecycle_content(
		store,
		registry,
		asset_root,
		content_interface,
		"owner draft one",
		base_revision_root=initial_wip,
	)
	assert committed == store_revision + 1
	assert store.read(initial_revision.content_root).atom == initial_content
	assert store.read(
		read_revision(store.snapshot(), lifecycle, first_wip).content_root
	).atom == b"owner draft one"
	projected = project_universal_canvas(store, registry)["selected_assembly"]
	assert next(
		row for row in projected["interfaces"]
		if row["id"] == content_interface
	)["value"] == "owner draft one"
	assert [row["revision"] for row in projected["lifecycle"]["history"]][-1] \
		== first_wip

	# A concurrent save from the same old base becomes a visible branch. It
	# cannot overwrite the first draft or masquerade as a single current head.
	second_wip, _ = edit_universal_lifecycle_content(
		store,
		registry,
		asset_root,
		content_interface,
		"owner concurrent draft",
		base_revision_root=initial_wip,
	)
	instance = read_lifecycle_instance(
		store.snapshot(), registry.assembly_protocol, lifecycle, asset_root
	)
	assert set(state_heads(
		store.snapshot(),
		lifecycle,
		instance.state_pointers[lifecycle.states["wip"]],
	)) == {first_wip, second_wip}
	assert store.read(
		read_revision(store.snapshot(), lifecycle, first_wip).content_root
	).atom == b"owner draft one"
	assert store.read(
		read_revision(store.snapshot(), lifecycle, second_wip).content_root
	).atom == b"owner concurrent draft"

	merged_wip, evidence_root, _ = merge_universal_lifecycle_content(
		store,
		registry,
		asset_root,
		content_interface,
		"owner resolved draft",
		parent_revision_roots=(first_wip, second_wip),
	)
	instance = read_lifecycle_instance(
		store.snapshot(), registry.assembly_protocol, lifecycle, asset_root
	)
	assert state_heads(
		store.snapshot(),
		lifecycle,
		instance.state_pointers[lifecycle.states["wip"]],
	) == (merged_wip,)
	merged = read_revision(store.snapshot(), lifecycle, merged_wip)
	assert merged.predecessor_roots == (first_wip, second_wip)
	assert merged.evidence_roots == (evidence_root,)
	assert store.read(merged.content_root).atom == b"owner resolved draft"
	merge_evidence = read_court_attestation(
		store.snapshot(), registry.attestation_protocol, evidence_root
	)
	assert merge_evidence.court_root == registry.resource_lifecycle_court_root
	assert merge_evidence.result_root == registry.attestation_protocol.states[
		"passed"
	]

	rejected_at = store.revision
	with pytest.raises(InvalidCell, match="lifecycle content port"):
		edit_universal_lifecycle_content(
			store,
			registry,
			asset_root,
			registry.canvas_root,
			"misrouted edit",
			base_revision_root=merged_wip,
		)
	assert store.revision == rejected_at


def test_resource_promotion_atomically_changes_revision_and_signed_audience():
	store, registry = build_universal_application(resolve_map_path())
	asset_root, _ = instantiate_universal_definition(
		store,
		registry,
		registry.standard_library.definition_roots[2],
		x=420,
		y=180,
	)
	authority = registry.authorization
	protocol = authority.identity_protocol
	lifecycle = registry.standard_library.lifecycle_protocol
	binding_root = next(
		row["root"]
		for row in project_universal_canvas(store, registry)[
			"authorization"
		]["relationships"]
		if row["kind"] == "audience-binding"
		and row["source"] == asset_root
	)
	before = verify_authority_relationship(
		store.snapshot(), protocol, authority.relationship_broker, binding_root
	)
	initial_instance = read_lifecycle_instance(
		store.snapshot(), registry.assembly_protocol, lifecycle, asset_root
	)
	initial_revision = state_heads(
		store.snapshot(),
		lifecycle,
		initial_instance.state_pointers[lifecycle.states["wip"]],
	)[0]
	assert before.evidence_roots == (
		lifecycle.states["wip"], authority.subject_root, initial_revision,
	)

	promoted, evidence, committed = promote_universal_resource_lifecycle(
		store, registry, asset_root, "shared"
	)
	intermediate = store.at(committed - 1)
	prior_instance = read_lifecycle_instance(
		intermediate,
		registry.assembly_protocol,
		lifecycle,
		asset_root,
	)
	assert state_heads(
		intermediate,
		lifecycle,
		prior_instance.state_pointers[lifecycle.states["shared"]],
	) == ()
	assert read_authority_relationship(
		intermediate, protocol, binding_root
	).evidence_roots == (
		lifecycle.states["wip"], authority.subject_root,
		before.evidence_roots[2],
	)

	after = store.at(committed)
	active_instance = read_lifecycle_instance(
		after,
		registry.assembly_protocol,
		lifecycle,
		asset_root,
	)
	assert state_heads(
		after,
		lifecycle,
		active_instance.state_pointers[lifecycle.states["shared"]],
	) == (promoted,)
	relationship = verify_authority_relationship(
		after, protocol, authority.relationship_broker, binding_root
	)
	assert relationship.evidence_roots == (
		lifecycle.states["shared"], authority.subject_root,
		before.evidence_roots[2],
	)
	assert after.cells[relationship.generation_root].atom == b"2"
	attestation = read_court_attestation(
		after, registry.attestation_protocol, evidence
	)
	assert attestation.court_root == registry.resource_lifecycle_court_root
	assert read_revision(after, lifecycle, promoted).evidence_roots == (
		evidence,
	)
	projected_shared = next(
		item for item in project_universal_canvas(
			store, registry
		)["selected_assembly"]["lifecycle"]["states"]
		if item["name"] == "SHARED"
	)["heads"][0]
	assert projected_shared["evidence_details"][0]["court"] \
		== registry.resource_lifecycle_court_root
	assert projected_shared["evidence_details"][0]["result"] == "passed"
	assert all(projected_shared["evidence_details"][0]["checks"].values())

	member_root = "test:identity:released-resource-not-auto-granted"
	store.commit(store.revision, create=(
		Cell(member_root, NULL_CELL_ID, NULL_CELL_ID, b"Member"),
	))
	provision_universal_view_session(store, registry, member_root)
	context = authority.broker.mint_authenticated_context(
		member_root,
		tenant_root=authority.tenant_root,
		assurance_root=authority.assurance_root,
		lifetime_seconds=120,
	)
	assert project_universal_canvas(
		store, registry, authentication_context=context
	)["nodes"] == []


def test_resource_promotion_conflict_cannot_leave_half_promoted_state(monkeypatch):
	store, registry = build_universal_application(resolve_map_path())
	asset_root, _ = instantiate_universal_definition(
		store,
		registry,
		registry.standard_library.definition_roots[2],
		x=420,
		y=180,
	)
	authority = registry.authorization
	protocol = authority.identity_protocol
	lifecycle = registry.standard_library.lifecycle_protocol
	binding_root = next(
		row["root"]
		for row in project_universal_canvas(store, registry)[
			"authorization"
		]["relationships"]
		if row["kind"] == "audience-binding"
		and row["source"] == asset_root
	)
	relationship = verify_authority_relationship(
		store.snapshot(), protocol, authority.relationship_broker, binding_root
	)
	original_commit = store.commit
	injected = False

	def inject_conflict(expected_revision, *, create=(), replace=()):
		nonlocal injected
		created = tuple(create)
		replaced = tuple(replace)
		if (
			not injected
			and any(
				cell.id == relationship.generation_root for cell in replaced
			)
		):
			injected = True
			original_commit(
				store.revision,
				create=(Cell(
					"test:promotion:conflict-marker",
					NULL_CELL_ID,
					NULL_CELL_ID,
					b"interleaving commit",
				),),
			)
		return original_commit(
			expected_revision, create=created, replace=replaced
		)

	monkeypatch.setattr(store, "commit", inject_conflict)
	with pytest.raises(Conflict):
		promote_universal_resource_lifecycle(
			store, registry, asset_root, "shared"
		)
	assert injected is True
	snapshot = store.snapshot()
	instance = read_lifecycle_instance(
		snapshot,
		registry.assembly_protocol,
		lifecycle,
		asset_root,
	)
	assert state_heads(
		snapshot,
		lifecycle,
		instance.state_pointers[lifecycle.states["shared"]],
	) == ()
	unchanged = verify_authority_relationship(
		snapshot, protocol, authority.relationship_broker, binding_root
	)
	assert unchanged.evidence_roots == (
		lifecycle.states["wip"], authority.subject_root,
		relationship.evidence_roots[2],
	)
	assert snapshot.cells[unchanged.generation_root].atom == b"1"


def test_shared_member_projection_cannot_see_later_owner_wip():
	store, registry = build_universal_application(resolve_map_path())
	asset_root, _ = instantiate_universal_definition(
		store,
		registry,
		registry.standard_library.definition_roots[2],
		x=420,
		y=180,
	)
	shared_root, _evidence, _revision = (
		promote_universal_resource_lifecycle(
			store, registry, asset_root, "shared"
		)
	)
	authority = registry.authorization
	member_root = "test:identity:shared-release-member"
	store.commit(store.revision, create=(
		Cell(member_root, NULL_CELL_ID, NULL_CELL_ID, b"Shared member"),
	))
	provision_universal_view_session(
		store, registry, member_root, visible_roots=(asset_root,)
	)
	context = authority.broker.mint_authenticated_context(
		member_root,
		tenant_root=authority.tenant_root,
		assurance_root=authority.assurance_root,
		lifetime_seconds=120,
	)

	lifecycle = registry.standard_library.lifecycle_protocol
	founder_before = project_universal_canvas(store, registry)[
		"selected_assembly"
	]
	wip_before = next(
		row for row in founder_before["lifecycle"]["states"]
		if row["name"] == "WIP"
	)["revision"]
	later_wip, _ = edit_universal_lifecycle_content(
		store,
		registry,
		asset_root,
		founder_before["lifecycle"]["content_interface"],
		"private owner work after sharing",
		base_revision_root=wip_before,
	)
	founder = project_universal_canvas(store, registry)["selected_assembly"]
	assert founder["interfaces"][0]["value"] \
		== "private owner work after sharing"
	assert next(
		row for row in founder["lifecycle"]["states"]
		if row["name"] == "WIP"
	)["revision"] == later_wip

	member = project_universal_canvas(
		store, registry, authentication_context=context
	)["selected_assembly"]
	assert member["lifecycle"]["release_scoped"] is True
	assert [row["name"] for row in member["lifecycle"]["states"]] == [
		"SHARED"
	]
	assert member["lifecycle"]["states"][0]["revision"] == shared_root
	assert [row["revision"] for row in member["lifecycle"]["history"]] == [
		shared_root
	]
	assert member["lifecycle"]["transitions"] == []
	assert member["interfaces"][0]["value"] == ""
	assert "private owner work after sharing" not in str(member)


def test_collection_interface_is_edited_by_graph_contract_not_definition_name():
	store, registry = build_universal_application(resolve_map_path())
	root, _ = instantiate_universal_definition(
		store,
		registry,
		registry.standard_library.definition_roots[0],
		x=300,
		y=200,
	)
	interface = project_universal_canvas(
		store, registry
	)["selected_assembly"]["interfaces"][0]
	assert interface["mode"] == "collection"
	edit_universal_interface_collection(
		store, registry, root, interface["id"], "append", value="Alpha"
	)
	edit_universal_interface_collection(
		store, registry, root, interface["id"], "append", value="Beta"
	)
	projected = project_universal_canvas(store, registry)
	items = projected["selected_assembly"]["interfaces"][0]["items"]
	assert [item["value"] for item in items] == ["Alpha", "Beta"]
	edit_universal_interface_collection(
		store,
		registry,
		root,
		interface["id"],
		"reorder",
		incidence_order=(items[1]["incidence"], items[0]["incidence"]),
	)
	reordered = project_universal_canvas(
		store, registry
	)["selected_assembly"]["interfaces"][0]["items"]
	edit_universal_interface_collection(
		store,
		registry,
		root,
		interface["id"],
		"edit",
		incidence_id=reordered[0]["incidence"],
		value="Edited",
	)
	edit_universal_interface_collection(
		store,
		registry,
		root,
		interface["id"],
		"remove",
		incidence_id=reordered[1]["incidence"],
	)
	final = project_universal_canvas(
		store, registry
	)["selected_assembly"]["interfaces"][0]["items"]
	assert [item["value"] for item in final] == ["Edited"]
	undo_universal_change(store, registry)
	restored_after_remove = project_universal_canvas(
		store, registry
	)["selected_assembly"]["interfaces"][0]["items"]
	assert [item["value"] for item in restored_after_remove] == [
		"Edited", "Alpha"
	]
	assert {
		item["incidence"] for item in restored_after_remove
	} == {item["incidence"] for item in reordered}
	redo_universal_change(store, registry)
	assert [
		item["value"] for item in project_universal_canvas(
			store, registry
		)["selected_assembly"]["interfaces"][0]["items"]
	] == ["Edited"]


def test_scope_navigation_is_a_bounded_graph_relation_not_browser_state():
	store, registry = build_universal_application(resolve_map_path())
	top = project_universal_canvas(store, registry)
	top_ids = tuple(item["id"] for item in top["nodes"])
	ui_root = registry.map.domains["ui"]
	assert top["scope"] == {
		"current": registry.canvas_root,
		"current_label": "ArchHub",
		"parent": None,
		"trail": [{
			"root": registry.canvas_root,
			"label": "ArchHub",
			"current": True,
		}],
	}

	set_universal_scope(store, registry, ui_root)
	nested = project_universal_canvas(store, registry)
	expected = tuple(
		member.participant_id
		for member in read_relation(store.snapshot(), ui_root, budget=10_000)
		if member.role_id == registry.roles["member"]
	)
	assert nested["scope"]["current"] == ui_root
	assert [item["root"] for item in nested["scope"]["trail"]] == [
		registry.canvas_root, ui_root,
	]
	assert tuple(item["id"] for item in nested["nodes"]) == expected
	assert not set(top_ids).intersection(expected)
	assert nested["selected"] == expected[0]
	assert nested["wires"]
	trail_members = read_relation(
		store.snapshot(),
		registry.view_sessions[registry.authorization.subject_root].scope_trail_root,
		budget=32,
	)
	assert [member.participant_id for member in trail_members] == [
		registry.canvas_root, ui_root,
	]
	with pytest.raises(InvalidCell, match="terminal"):
		set_universal_scope(store, registry, expected[0])

	set_universal_scope(store, registry)
	restored = project_universal_canvas(store, registry)
	assert tuple(item["id"] for item in restored["nodes"]) == top_ids
	assert restored["scope"]["current"] == registry.canvas_root


def test_scope_return_to_ancestor_is_one_atomic_graph_commit():
	store, registry = build_universal_application(resolve_map_path())
	ui_root = registry.map.domains["ui"]
	field_list_root = "app:properties-presenter:field-list"

	set_universal_scope(store, registry, ui_root)
	set_universal_scope(store, registry, registry.design_system_root)
	set_universal_scope(store, registry, field_list_root)
	before = store.revision

	revision = set_universal_scope(store, registry, registry.canvas_root)

	assert revision == before + 1
	projection = project_universal_canvas(store, registry)
	assert projection["scope"]["current"] == registry.canvas_root
	assert [item["root"] for item in projection["scope"]["trail"]] == [
		registry.canvas_root,
	]
	assert projection["selected"] == projection["nodes"][0]["id"]


def test_relation_backed_catalog_placement_extends_the_active_nested_scope():
	store, registry = build_universal_application(resolve_map_path())
	ui_root = registry.map.domains["ui"]
	set_universal_scope(store, registry, ui_root)
	nested = project_universal_canvas(store, registry)
	participant_root = nested["nodes"][0]["id"]
	definition = next(
		item for item in nested["catalog"]
		if item["name"] == "Model Descriptor"
	)
	bindings = tuple(
		(
			role["role"],
			role["fixed"]["id"] if role["fixed"] else participant_root,
		)
		for role in definition["composition_contract"]["roles"]
		for _ in range(role["minimum"])
	)
	before = store.revision

	created_root, revision = instantiate_universal_relation_definition(
		store,
		registry,
		definition["id"],
		bindings,
		x=420.0,
		y=260.0,
	)

	assert revision == before + 1
	snapshot = store.snapshot()
	scope_members = read_relation(snapshot, ui_root, budget=10_000)
	assert any(
		member.role_id == registry.roles["member"]
		and member.participant_id == created_root
		for member in scope_members
	)
	projected = project_universal_canvas(store, registry)
	assert projected["scope"]["current"] == ui_root
	assert created_root in {node["id"] for node in projected["nodes"]}
	assert projected["selected"] == created_root
	assert projected["authoring"]["add_property"] is True
	assert projected["authoring"]["add_interface"] is True
	assert projected["authoring"]["owner"] == created_root


def test_nested_catalog_placement_does_not_escape_its_composition_after_history():
	store, registry = build_universal_application(resolve_map_path())
	top = project_universal_canvas(store, registry)
	selected = tuple(node["id"] for node in top["nodes"][:2])
	set_universal_selection(store, registry, selected, focus_root=selected[-1])
	composition_root, _ = group_universal_selection(
		store, registry, title="Placement history court"
	)
	ungroup_universal_composition(store, registry, composition_root)

	ui_root = registry.map.domains["ui"]
	set_universal_scope(store, registry, ui_root)
	nested = project_universal_canvas(store, registry)
	definition = next(
		item for item in nested["catalog"]
		if item["name"] == "Ordered List"
	)
	created_root, _ = instantiate_universal_definition(
		store,
		registry,
		definition["id"],
		x=420.0,
		y=260.0,
		mutation_route="/api/universal/interaction",
	)

	projected = project_universal_canvas(store, registry)
	assert created_root in {node["id"] for node in projected["nodes"]}
	assert projected["authoring"]["add_property"] is True
	assert projected["authoring"]["add_interface"] is True
	assert projected["authoring"]["owner"] == created_root
	snapshot = store.snapshot()
	assert created_root in {
		member.participant_id
		for member in read_relation(snapshot, ui_root, budget=10_000)
		if member.role_id == registry.roles["member"]
	}
	assert created_root not in {
		member.participant_id
		for member in read_relation(
			snapshot, registry.canvas_root, budget=100_000
		)
		if member.role_id == registry.roles["member"]
	}

	set_universal_scope(store, registry, registry.canvas_root)
	top_after = project_universal_canvas(store, registry)
	assert created_root not in {node["id"] for node in top_after["nodes"]}
	assert ui_root in {node["id"] for node in top_after["nodes"]}


def test_visual_property_authoring_is_one_atomic_graph_transaction():
	store, registry = build_universal_application(resolve_map_path())
	owner_root, _ = instantiate_universal_primitive(
		store,
		registry,
		x=360,
		y=240,
		title="Property owner",
		atom="seed",
	)
	before = store.revision
	initial = project_universal_canvas(store, registry)
	assert initial["authoring"]["add_property"] is True
	assert initial["authoring"]["add_interface"] is True
	assert initial["authoring"]["owner"] == owner_root

	relation_root, revision = create_universal_property(
		store,
		registry,
		owner_root,
		"Fire rating",
		"60 minutes",
	)
	assert revision == before + 1
	members = read_relation(store.snapshot(), relation_root, budget=16)
	assert len(members) == 3
	by_role = {member.role_id: member for member in members}
	assert by_role[registry.roles["owner"]].participant_id == owner_root
	label_root = by_role[registry.roles["label"]].participant_id
	value_root = by_role[registry.roles["value"]].participant_id
	assert store.snapshot().cells[label_root].atom == b"Fire rating"
	assert store.snapshot().cells[value_root].atom == b"60 minutes"
	assert len({member.incidence_id for member in members}) == 3

	projected = project_universal_canvas(store, registry)
	row = next(
		item for item in projected["properties"]
		if item["relation"] == relation_root
	)
	assert row == {
		"relation": relation_root,
		"owner": owner_root,
		"label": "Fire rating",
		"value": "60 minutes",
		"value_root": value_root,
		"editable": True,
		"batch": False,
		"mixed": False,
		"control": relation_root,
		"event_fact_input": "app:event-fact:submitted-value:v1",
		"presentation_editable": False,
		"presentation_control": None,
		"presentation_event_fact_input": None,
		"presentation_binding": None,
		"presentation_source": "Inherited node appearance",
		"presentation_source_root": relation_root,
		"presentation_source_mode": "inherited",
		"presentation_revision": None,
		"presentation_reset": False,
		"presentation_reset_control": None,
		"presentation_history": [],
	}
	edit_universal_property(store, registry, relation_root, "90 minutes")
	edited = next(
		item for item in project_universal_canvas(store, registry)["properties"]
		if item["relation"] == relation_root
	)
	assert edited["value"] == "90 minutes"
	assert edited["value_root"] == value_root


def test_visual_property_authoring_rejections_leave_no_partial_graph():
	store, registry = build_universal_application(resolve_map_path())
	owner_root, _ = instantiate_universal_primitive(
		store, registry, x=320, y=220, title="Bounded owner"
	)
	create_universal_property(
		store, registry, owner_root, "Discipline", "Architecture"
	)
	for label, value, error in (
		("discipline", "Structure", "already exists"),
		(" ", "value", "non-empty"),
		("x" * 513, "value", "bounded interface"),
		("Large", "x" * 65_537, "bounded interface"),
	):
		before = store.revision
		with pytest.raises(InvalidCell, match=error):
			create_universal_property(
				store, registry, owner_root, label, value
			)
		assert store.revision == before

	released_root, _ = instantiate_universal_definition(
		store,
		registry,
		registry.standard_library.definition_roots[2],
		x=620,
		y=220,
	)
	promote_universal_resource_lifecycle(
		store, registry, released_root, "shared"
	)
	before = store.revision
	with pytest.raises(InvalidCell, match="only to WIP"):
		create_universal_property(
			store, registry, released_root, "Forbidden", "value"
		)
	assert store.revision == before
	projection = project_universal_canvas(store, registry)
	assert projection["selected"] == released_root
	assert projection["authoring"]["add_property"] is False
	assert projection["authoring"]["add_interface"] is False
	assert projection["authoring"]["owner"] is None


def test_visual_interface_authoring_is_registered_and_identity_exact():
	store, registry = build_universal_application(resolve_map_path())
	owner_root, _ = instantiate_universal_primitive(
		store, registry, x=340, y=210, title="Interface owner"
	)
	initial = project_universal_canvas(store, registry)
	output = next(
		item for item in initial["authoring"]["interface_presentations"]
		if item["side"] == "source"
	)
	universal_contract = next(
		item for item in initial["authoring"]["interface_contracts"]
		if item["id"] == registry.assembly_protocol.root_id
	)
	before = store.revision
	interface_root, revision = create_universal_interface(
		store,
		registry,
		owner_root,
		"Geometry out",
		output["id"],
		universal_contract["id"],
	)
	assert revision == before + 1
	assert not interface_root.startswith(
		"app:canvas-interface:%s:" % owner_root.replace(":", "-")
	)

	snapshot = store.snapshot()
	members = read_relation(snapshot, interface_root, budget=16)
	by_role = {member.role_id: member.participant_id for member in members}
	assert by_role[
		registry.assembly_protocol.role("interface-target")
	] == owner_root
	assert by_role[
		registry.assembly_protocol.role("interface-presentation")
	] == output["id"]
	assert by_role[
		registry.assembly_protocol.role("interface-contract")
	] == registry.assembly_protocol.root_id
	application_interfaces = {
		member.participant_id
		for member in read_relation(
			snapshot, registry.application_root, budget=100_000
		)
		if member.role_id == registry.assembly_protocol.role("interface")
	}
	assert interface_root in application_interfaces

	projected = project_universal_canvas(store, registry)
	owner = next(node for node in projected["nodes"] if node["id"] == owner_root)
	port = next(item for item in owner["ports"] if item["id"] == interface_root)
	assert port["owner"] == owner_root
	assert port["side"] == "source"
	assert port["name"] == "Geometry out"
	assert port["contract_root"] == registry.assembly_protocol.root_id
	assert any(
		item["id"] == interface_root
		for item in projected["selected_interfaces"]
	)


def test_visual_interface_batch_folds_staged_relation_tail_rewrites():
	store, registry = build_universal_application(resolve_map_path())
	owner_a, _ = instantiate_universal_primitive(
		store, registry, x=340, y=210, title="Interface batch A"
	)
	owner_b, _ = instantiate_universal_primitive(
		store, registry, x=560, y=210, title="Interface batch B"
	)
	projection = project_universal_canvas(store, registry)
	output = next(
		item for item in projection["authoring"]["interface_presentations"]
		if item["side"] == "source"
	)
	universal_contract = next(
		item for item in projection["authoring"]["interface_contracts"]
		if item["id"] == registry.assembly_protocol.root_id
	)
	before = store.revision
	interface_roots, revision = create_universal_interfaces(
		store,
		registry,
		(
			(owner_a, "Batch output A", output["id"], universal_contract["id"]),
			(owner_b, "Batch output B", output["id"], universal_contract["id"]),
		),
	)
	assert revision == before + 1
	assert len(interface_roots) == 2

	snapshot = store.snapshot()
	application_interfaces = {
		member.participant_id
		for member in read_relation(
			snapshot, registry.application_root, budget=100_000
		)
		if member.role_id == registry.assembly_protocol.role("interface")
	}
	assert set(interface_roots).issubset(application_interfaces)


def test_visual_interface_authoring_rejects_partial_and_mismatched_graphs():
	store, registry = build_universal_application(resolve_map_path())
	owner_root, _ = instantiate_universal_primitive(
		store, registry, x=300, y=210, title="Source owner"
	)
	target_root, _ = instantiate_universal_primitive(
		store, registry, x=620, y=210, title="Target owner"
	)
	watcher_root, _ = instantiate_universal_definition(
		store,
		registry,
		registry.standard_library.definition_roots[1],
		x=300,
		y=430,
	)
	list_root, _ = instantiate_universal_definition(
		store,
		registry,
		registry.standard_library.definition_roots[0],
		x=620,
		y=430,
	)
	projection = project_universal_canvas(store, registry)
	presentations = {
		item["side"]: item["id"]
		for item in projection["authoring"]["interface_presentations"]
	}
	assemblies = {
		node["id"]: node["assembly"] for node in projection["nodes"]
		if node["assembly"] is not None
	}
	source_contract = assemblies[watcher_root]["interfaces"][0]["contract_root"]
	target_contract = assemblies[list_root]["interfaces"][0]["contract_root"]
	assert source_contract != target_contract

	source_interface, _ = create_universal_interface(
		store,
		registry,
		owner_root,
		"Strict out",
		presentations["source"],
		source_contract,
	)
	target_interface, _ = create_universal_interface(
		store,
		registry,
		target_root,
		"Strict in",
		presentations["target"],
		target_contract,
	)
	before = store.revision
	with pytest.raises(InvalidCell, match="contracts are incompatible"):
		connect_universal_roots(
			store,
			registry,
			owner_root,
			target_root,
			source_interface=source_interface,
			target_interface=target_interface,
		)
	assert store.revision == before

	for name, presentation, contract, error in (
		("strict out", presentations["source"], source_contract, "already exists"),
		(" ", presentations["source"], source_contract, "non-empty"),
		("x" * 513, presentations["source"], source_contract, "bounded"),
		("Unknown side", "missing:presentation", source_contract, "presentation"),
		("Unknown contract", presentations["source"], "missing:contract", "contract"),
	):
		before = store.revision
		with pytest.raises(InvalidCell, match=error):
			create_universal_interface(
				store,
				registry,
				owner_root,
				name,
				presentation,
				contract,
			)
		assert store.revision == before


def test_group_and_ungroup_are_lossless_personal_wip_compositions():
	store, registry = build_universal_application(resolve_map_path())
	authority = registry.authorization
	member_root = "test:identity:composition-observer"
	store.commit(store.revision, create=(
		Cell(member_root, NULL_CELL_ID, NULL_CELL_ID, b"Composition observer"),
	))
	provision_universal_view_session(
		store,
		registry,
		member_root,
		visible_roots=tuple(registry.map.domains.values()),
	)
	member_context = authority.broker.mint_authenticated_context(
		member_root,
		principal_roots=(authority.member_principal_root,),
		tenant_root=authority.tenant_root,
		assurance_root=authority.assurance_root,
		lifetime_seconds=120,
	)
	before = project_universal_canvas(store, registry)
	member_before = project_universal_canvas(
		store, registry, authentication_context=member_context
	)
	selected = tuple(node["id"] for node in before["nodes"][:2])
	wire_identity = {
		wire["id"]: (
			wire["source_incidence"],
			wire["target_incidence"],
			wire["source_interface"],
			wire["target_interface"],
		)
		for wire in before["wires"]
	}

	set_universal_selection(
		store, registry, selected, focus_root=selected[-1]
	)
	selected_projection = project_universal_canvas(store, registry)
	selected_controls = {
		control["owner"]: control
		for control in selected_projection["configuration"]["design_system"]
		["control_catalog"]["controls"]
	}
	assert selected_controls["app:control:canvas:group"]["applicable"] is True
	assert selected_controls["app:control:canvas:ungroup"]["applicable"] is False
	group_start_revision = store.revision
	composition_root, _revision = group_universal_selection(
		store, registry, title="Selected systems"
	)
	assert store.revision == group_start_revision + 1
	grouped = project_universal_canvas(store, registry)
	group = next(
		node for node in grouped["nodes"]
		if node["id"] == composition_root
	)
	assert group["composition"] is True
	assert group["member_count"] == 2
	assert group["selected"] is True
	grouped_controls = {
		control["owner"]: control
		for control in grouped["configuration"]["design_system"]
		["control_catalog"]["controls"]
	}
	assert grouped_controls["app:control:canvas:group"]["applicable"] is False
	assert grouped_controls["app:control:canvas:ungroup"]["applicable"] is True
	assert len(grouped["nodes"]) == len(before["nodes"]) - 1
	assert set(selected).isdisjoint(node["id"] for node in grouped["nodes"])
	boundary_ports = {
		port["id"]: port for port in group["ports"]
		if port.get("derived")
	}
	used_boundaries = {
		interface
		for wire in grouped["wires"]
		if wire["source"] == composition_root
		or wire["target"] == composition_root
		for interface in (
			wire["source_interface"], wire["target_interface"]
		)
		if interface in boundary_ports
	}
	assert used_boundaries == set(boundary_ports)
	assert boundary_ports
	assert not any(port["connectable"] for port in boundary_ports.values())
	assert [
		node["id"] for node in project_universal_canvas(
			store, registry, authentication_context=member_context
		)["nodes"]
	] == [node["id"] for node in member_before["nodes"]]

	boundary = next(iter(boundary_ports))
	side = boundary_ports[boundary]["side"]
	other_node = next(
		node for node in grouped["nodes"]
		if node["id"] != composition_root
	)
	other_source = next(
		port["id"] for port in other_node["ports"]
		if port["side"] == "source"
	)
	other_target = next(
		port["id"] for port in other_node["ports"]
		if port["side"] == "target"
	)
	with pytest.raises(InvalidCell, match="derived composition boundaries"):
		connect_universal_roots(
			store,
			registry,
			composition_root if side == "source" else other_node["id"],
			other_node["id"] if side == "source" else composition_root,
			source_interface=boundary if side == "source" else other_source,
			target_interface=other_target if side == "source" else boundary,
		)

	set_universal_scope(store, registry, composition_root)
	nested = project_universal_canvas(store, registry)
	assert tuple(node["id"] for node in nested["nodes"]) == selected
	nested_controls = {
		control["owner"]: control
		for control in nested["configuration"]["design_system"]
		["control_catalog"]["controls"]
	}
	assert nested_controls["app:control:canvas:scope-up"]["applicable"] is True
	set_universal_scope(store, registry, registry.canvas_root)
	ungroup_start_revision = store.revision
	ungroup_universal_composition(store, registry, composition_root)
	assert store.revision == ungroup_start_revision + 1
	restored = project_universal_canvas(store, registry)
	assert tuple(node["id"] for node in restored["nodes"]) == tuple(
		node["id"] for node in before["nodes"]
	)
	assert composition_root not in {
		node["id"] for node in restored["nodes"]
	}
	assert wire_identity == {
		wire["id"]: (
			wire["source_incidence"],
			wire["target_incidence"],
			wire["source_interface"],
			wire["target_interface"],
		)
		for wire in restored["wires"]
	}
	history_root = registry.view_sessions[
		authority.subject_root
	].composition_history_root
	history = read_relation(store.snapshot(), history_root, budget=100_000)
	assert len(history) == 2
	assert {
		store.snapshot().cells[next(
			member.participant_id for member in read_relation(
				store.snapshot(), item.participant_id, budget=32
			) if member.role_id == registry.roles["why"]
		)].atom.decode("ascii")
		for item in history
	} == {"group", "ungroup"}

	placed_root, _revision = instantiate_universal_definition(
		store,
		registry,
		registry.standard_library.definition_roots[0],
		x=420,
		y=180,
	)
	after_place = project_universal_canvas(store, registry)
	assert placed_root in {node["id"] for node in after_place["nodes"]}
	assert len(after_place["nodes"]) == len(before["nodes"]) + 1


def test_member_scope_inherits_the_signed_assignment_without_broadening_it():
	store, registry = build_universal_application(resolve_map_path())
	authority = registry.authorization
	member_root = "test:identity:scoped-member"
	store.commit(store.revision, create=(
		Cell(member_root, NULL_CELL_ID, NULL_CELL_ID, b"Scoped member"),
	))
	ui_root = registry.map.domains["ui"]
	provision_universal_view_session(
		store, registry, member_root, visible_roots=(ui_root,)
	)
	context = authority.broker.mint_authenticated_context(
		member_root,
		tenant_root=authority.tenant_root,
		assurance_root=authority.assurance_root,
		lifetime_seconds=120,
	)
	set_universal_scope(
		store, registry, ui_root, authentication_context=context
	)
	nested = project_universal_canvas(
		store, registry, authentication_context=context
	)
	assert nested["scope"]["current"] == ui_root
	assert nested["nodes"]
	with pytest.raises(InvalidCell, match="outside the active graph level"):
		set_universal_scope(
			store,
			registry,
			registry.map.domains["brain"],
			authentication_context=context,
		)
