"""Cross-module court against hidden product dispatch in the Cell floor."""
from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
NODELANG = ROOT / "nodelang"

# These modules may interpret only generic graph structure and graph-supplied
# identities. Product behavior belongs in graph assemblies, never in this floor.
EXECUTION_FLOOR_MODULES = {
    "universal_cell.py",
    "cell_adapters.py",
    "cell_attestations.py",
    "cell_authorization.py",
    "cell_catalog.py",
    "cell_change_history.py",
    "cell_composer.py",
    "cell_content_descriptors.py",
    "cell_device_custody.py",
    "cell_device_enrollment.py",
    "cell_device_keys.py",
    "cell_dpop.py",
    "cell_dpop_nonce.py",
    "cell_external_graph_binding.py",
    "cell_exclusive_ownership.py",
    "cell_federated_identity.py",
    "cell_identity.py",
    "cell_interactions.py",
    "cell_lifecycle.py",
    "cell_native_auth.py",
    "cell_oidc.py",
    "cell_oidc_discovery.py",
    "cell_permission_requests.py",
    "cell_protocols.py",
    "cell_reactions.py",
    "cell_relation_contract.py",
    "cell_relation_exposure_policy.py",
    "cell_revision_checkpoint.py",
    "cell_rules.py",
    "cell_runtime_presence.py",
    "cell_secret_keys.py",
    "cell_signing_authority.py",
    "cell_state_machine.py",
    "cell_status_ledger.py",
    "cell_tenant_authority.py",
    "cell_transactions.py",
    "cell_transparency_witness.py",
    "cell_value_graph.py",
    "cell_view_template.py",
}

# These are higher graph assemblies, presenters, or external boundary lenses.
# They may name their domain, but do not expand the physical execution floor.
GRAPH_ASSEMBLY_OR_LENS_MODULES = {
    "cell_agent_body.py",
    "cell_agent_cognition.py",
    "cell_application_ui.py",
    "cell_attention.py",
    "cell_attention_reactions.py",
    "cell_authority_view.py",
    "cell_browser_sessions.py",
    "cell_cloud_gate.py",
    "cell_cloud_routes.py",
    "cell_cloud_sessions.py",
    "cell_control_view.py",
    "cell_core_values.py",
    "cell_domain_catalog.py",
    "cell_evidence_floor_view.py",
    "cell_fastapi_gate.py",
    "cell_focus_view.py",
    "cell_interface_view.py",
    "cell_presentation.py",
    "cell_presentation_view.py",
    "cell_presenter.py",
    "cell_properties_view.py",
    "cell_registry_projection.py",
    "cell_relations_view.py",
    "cell_standard_library.py",
    "cell_timeline_view.py",
    "cell_ui.py",
    "cell_website.py",
    "cell_activity.py",
    "cell_agent_body_catalog.py",
    "cell_baboom_connector_execution.py",
    "cell_baboom_meeting_note_publication.py",
    "cell_baboom_model_execution.py",
    "cell_baboom_steward.py",
    "cell_canvas_card_view.py",
    "cell_canvas_heading_view.py",
    "cell_canvas_interaction_policy.py",
    "cell_canvas_port_view.py",
    "cell_canvas_toolbar_view.py",
    "cell_compliance.py",
    "cell_connector_execution.py",
    "cell_control_bindings.py",
    "cell_control_presentations.py",
    "cell_deliberation.py",
    "cell_design_tokens.py",
    "cell_event_facts.py",
    "cell_icons.py",
    "cell_inspector_controls_view.py",
    "cell_inspector_header_view.py",
    "cell_inspector_shell_view.py",
    "cell_legacy_brain_governance.py",
    "cell_legacy_core_nodes.py",
    "cell_legacy_custom_nodes.py",
    "cell_legacy_self_extension.py",
    "cell_legacy_surface_catalog.py",
    "cell_legacy_webshell_host.py",
    "cell_library_definition_view.py",
    "cell_library_primitive_view.py",
    "cell_library_section_view.py",
    "cell_library_shell_view.py",
    "cell_mcp_broker.py",
    "cell_meeting_notes.py",
    "cell_model_execution.py",
    "cell_relation_composer.py",
    "cell_relation_composer_view.py",
    "cell_relation_forms.py",
    "cell_roma_requirements.py",
    "cell_work_claim_transfer.py",
    "cell_work_handoff.py",
}

REVIEWED_CORE_EXECUTORS = {
    "universal_cell.py",
    "cell_rules.py",
    "cell_interactions.py",
}

PRODUCT_TERMS = {
    "ai-session",
    "bim",
    "brain",
    "catalogue",
    "cloud",
    "cockpit",
    "database",
    "domain",
    "geometry",
    "group",
    "logic",
    "money",
    "panel",
    "payment",
    "properties",
    "publish",
    "selection",
    "session",
    "settings",
    "watcher",
    "website",
}


def _product_words(value: str) -> set[str]:
    normalized = value.casefold().replace("_", " ").replace("-", " ")
    return set(normalized.split()) & PRODUCT_TERMS


def _parent_map(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    return {
        child: parent
        for parent in ast.walk(tree)
        for child in ast.iter_child_nodes(parent)
    }


def _is_graph_identity_lookup(node: ast.Constant, parent: ast.AST | None) -> bool:
    return bool(
        isinstance(parent, ast.Call)
        and isinstance(parent.func, ast.Attribute)
        and parent.func.attr in {"action", "role", "state"}
        and node in parent.args
    )


def _is_record_field_lookup(node: ast.Constant, parent: ast.AST | None) -> bool:
    return bool(
        isinstance(parent, ast.Call)
        and isinstance(parent.func, ast.Attribute)
        and parent.func.attr == "get"
        and parent.args
        and parent.args[0] is node
    )


def _inside_control_predicate(
    node: ast.AST, parents: dict[ast.AST, ast.AST]
) -> bool:
    current = node
    while current in parents:
        parent = parents[current]
        if isinstance(parent, (ast.If, ast.While, ast.Assert, ast.IfExp)):
            if parent.test is current:
                return True
        elif isinstance(parent, ast.comprehension) and current in parent.ifs:
            return True
        elif isinstance(parent, ast.Match):
            if parent.subject is current or any(
                case.pattern is current for case in parent.cases
            ):
                return True
        current = parent
    return False


def _enclosing_function_name(
    node: ast.AST, parents: dict[ast.AST, ast.AST]
) -> str | None:
    current = node
    while current in parents:
        current = parents[current]
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return current.name
    return None


def _module_violations(path: Path) -> list[tuple[int, str, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    parents = _parent_map(tree)
    function_names = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    violations: list[tuple[int, str, str]] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            parent = parents.get(node)
            if (
                _product_words(node.value)
                and not _is_graph_identity_lookup(node, parent)
                and not _is_record_field_lookup(node, parent)
                and _inside_control_predicate(node, parents)
            ):
                violations.append((node.lineno, "product predicate", node.value))

        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                if not (
                    isinstance(key, ast.Constant)
                    and isinstance(key.value, str)
                    and _product_words(key.value)
                ):
                    continue
                callable_value = (
                    isinstance(value, ast.Lambda)
                    or isinstance(value, ast.Name) and value.id in function_names
                    or isinstance(value, ast.Attribute) and value.attr in function_names
                )
                if callable_value:
                    violations.append(
                        (key.lineno, "product callable table", key.value)
                    )

        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in {"compile", "eval", "exec", "__import__"}:
                violations.append((node.lineno, "dynamic execution", node.func.id))
    return violations


def _is_graph_vocabulary_subscript(
    node: ast.Constant, parent: ast.AST | None
) -> bool:
    return bool(
        isinstance(parent, ast.Subscript)
        and parent.slice is node
        and isinstance(parent.value, ast.Name)
        and parent.value.id == "by_label"
    )


def _is_windows_platform_predicate(
    node: ast.Constant, parent: ast.AST | None
) -> bool:
    """Allow only the physical lock implementation's OS branch.

    The Cell floor is portable, but the durable journal must use the host
    operating system's locking primitive. This is not graph or product
    dispatch; any broader string predicate remains a violation.
    """
    return bool(
        node.value == "nt"
        and isinstance(parent, ast.Compare)
        and len(parent.ops) == 1
        and isinstance(parent.ops[0], ast.Eq)
        and len(parent.comparators) == 1
        and parent.comparators[0] is node
        and isinstance(parent.left, ast.Attribute)
        and parent.left.attr == "name"
        and isinstance(parent.left.value, ast.Name)
        and parent.left.value.id == "os"
    )


def _raw_dispatch_violations(path: Path) -> list[tuple[int, str, str]]:
    """Reject semantic dispatch shapes without guessing feature vocabulary."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    parents = _parent_map(tree)
    function_names = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    violations: list[tuple[int, str, str]] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            parent = parents.get(node)
            if (
                _enclosing_function_name(node, parents) != "backup_to"
                and
                not _is_graph_identity_lookup(node, parent)
                and not _is_graph_vocabulary_subscript(node, parent)
                and not _is_record_field_lookup(node, parent)
                and not _is_windows_platform_predicate(node, parent)
                and _inside_control_predicate(node, parents)
            ):
                violations.append((node.lineno, "raw string predicate", node.value))

        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                callable_value = (
                    isinstance(value, ast.Lambda)
                    or isinstance(value, ast.Name) and value.id in function_names
                    or isinstance(value, ast.Attribute) and value.attr in function_names
                )
                if (
                    isinstance(key, ast.Constant)
                    and isinstance(key.value, str)
                    and callable_value
                ):
                    violations.append(
                        (key.lineno, "raw callable dispatch table", key.value)
                    )
    return violations


def test_every_cell_module_is_classified_before_it_can_ship():
    actual = {path.name for path in NODELANG.glob("cell_*.py")}
    actual.add("universal_cell.py")
    classified = EXECUTION_FLOOR_MODULES | GRAPH_ASSEMBLY_OR_LENS_MODULES
    assert EXECUTION_FLOOR_MODULES.isdisjoint(GRAPH_ASSEMBLY_OR_LENS_MODULES)
    assert classified == actual


def test_entire_execution_floor_has_no_hidden_product_dispatch():
    violations = {
        module: found
        for module in sorted(EXECUTION_FLOOR_MODULES)
        if (found := _module_violations(NODELANG / module))
    }
    assert violations == {}


def test_reviewed_core_executors_have_no_raw_string_dispatch_shape():
    violations = {
        module: found
        for module in sorted(REVIEWED_CORE_EXECUTORS)
        if (found := _raw_dispatch_violations(NODELANG / module))
    }
    assert violations == {}


def test_windows_locking_exception_is_narrow_and_not_a_dispatch_escape_hatch():
    allowed_tree = ast.parse('if os.name == "nt":\n    pass\n')
    allowed_node = allowed_tree.body[0].test.comparators[0]
    assert _is_windows_platform_predicate(
        allowed_node, _parent_map(allowed_tree)[allowed_node]
    )

    denied_tree = ast.parse('if platform.name == "nt":\n    pass\n')
    denied_node = denied_tree.body[0].test.comparators[0]
    assert not _is_windows_platform_predicate(
        denied_node, _parent_map(denied_tree)[denied_node]
    )


def test_application_presentation_lens_does_not_import_retired_typed_runtime():
    for module in ("cell_application_ui.py", "universal_presentation_seed.py"):
        tree = ast.parse((NODELANG / module).read_text(encoding="utf-8"))
        imports = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        }
        assert "application" not in imports
        assert "nodelang.application" not in imports
