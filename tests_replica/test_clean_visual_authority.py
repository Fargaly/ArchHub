from __future__ import annotations

from pathlib import Path
import threading
import uuid

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from nodelang.cell_canvas_card_view import (
    CANVAS_CARD_TEMPLATE_ROOT,
    compose_canvas_card_template,
)
from nodelang.cell_canvas_heading_view import (
    CANVAS_HEADING_TEMPLATE_ROOT,
    compose_canvas_heading_template,
)
from nodelang.cell_canvas_port_view import (
    CANVAS_PORT_TEMPLATE_ROOT,
    compose_canvas_port_template,
)
from nodelang.cell_canvas_toolbar_view import (
    CANVAS_TOOLBAR_TEMPLATE_ROOT,
    compose_canvas_toolbar_template,
)
from nodelang.cell_inspector_controls_view import (
    INSPECTOR_CONTROLS_TEMPLATE_ROOT,
    compose_inspector_controls_template,
)
from nodelang.cell_inspector_header_view import (
    INSPECTOR_HEADER_TEMPLATE_ROOT,
    compose_inspector_header_template,
)
from nodelang.cell_inspector_shell_view import (
    INSPECTOR_SHELL_TEMPLATE_ROOT,
    compose_inspector_shell_template,
)
from nodelang.cell_library_definition_view import (
    LIBRARY_DEFINITION_TEMPLATE_ROOT,
    compose_library_definition_template,
)
from nodelang.cell_library_primitive_view import (
    LIBRARY_PRIMITIVE_TEMPLATE_ROOT,
    compose_library_primitive_template,
)
from nodelang.cell_library_section_view import (
    LIBRARY_SECTION_TEMPLATE_ROOT,
    compose_library_section_template,
)
from nodelang.cell_library_shell_view import (
    LIBRARY_SHELL_TEMPLATE_ROOT,
    compose_library_shell_template,
)
from nodelang.cell_properties_view import (
    FIELD_LIST_TEMPLATE_ROOT,
    VIEW_TEMPLATE_PREFIX,
    compose_field_list_template,
)
from nodelang.cell_authority_view import (
    AUTHORITY_LIST_TEMPLATE_ROOT,
    compose_authority_list_template,
)
from nodelang.cell_control_view import (
    CONTROL_LIST_TEMPLATE_ROOT,
    compose_control_list_template,
)
from nodelang.cell_evidence_floor_view import (
    CELL_FLOOR_TEMPLATE_ROOT,
    EVIDENCE_LIST_TEMPLATE_ROOT,
    compose_cell_floor_template,
    compose_evidence_list_template,
)
from nodelang.cell_focus_view import (
    FOCUS_LIST_TEMPLATE_ROOT,
    compose_focus_list_template,
)
from nodelang.cell_interface_view import (
    INTERFACE_LIST_TEMPLATE_ROOT,
    compose_interface_list_template,
)
from nodelang.cell_presentation_view import (
    PRESENTATION_LIST_TEMPLATE_ROOT,
    compose_presentation_list_template,
)
from nodelang.cell_relations_view import (
    RELATION_LIST_TEMPLATE_ROOT,
    compose_relation_list_template,
)
from nodelang.cell_timeline_view import (
    TIMELINE_TEMPLATE_ROOT,
    compose_timeline_template,
)
from nodelang.cell_protocols import CellBatch
from nodelang.cell_relation_composer_view import (
    RELATION_COMPOSER_VIEW_TEMPLATE_ROOT,
    compose_relation_composer_view_template,
)
from nodelang.cell_secret_keys import MemorySigningKeyProvider
from nodelang.cell_view_template import (
    compose_view_template_protocol,
    render_view_template,
)
from nodelang.unified_authority import (
    composition_root,
    create_unified_authority,
    enroll_session,
)
from nodelang.universal_cell import Conflict, NULL_CELL_ID, CellStore
from nodelang.universal_application import (
    _CANVAS_CARD_VIEW_COURT,
    _CANVAS_HEADING_VIEW_COURT,
    _CANVAS_PORT_VIEW_COURT,
    _CANVAS_TOOLBAR_VIEW_COURT,
    _GRAPH_PROPERTIES_PRESENTER_COURTS,
    _INSPECTOR_CONTROLS_VIEW_COURT,
    _INSPECTOR_HEADER_VIEW_COURT,
    _INSPECTOR_SHELL_VIEW_COURT,
    _LIBRARY_DEFINITION_VIEW_COURT,
    _LIBRARY_PRIMITIVE_VIEW_COURT,
    _LIBRARY_SECTION_VIEW_COURT,
    _LIBRARY_SHELL_VIEW_COURT,
    _RELATION_COMPOSER_VIEW_COURT,
)


PRIVATE = Ed25519PrivateKey.from_private_bytes(bytes(range(1, 33)))
PUBLIC = PRIVATE.public_key().public_bytes(
    serialization.Encoding.Raw,
    serialization.PublicFormat.Raw,
)
COMMAND_ID = "5bcbd16d-8b45-4558-a328-634d9b18388e"


class _Caller:
    def __init__(self, authority):
        self.actor_root = authority.manifest.principal_root
        self.session_root = authority.manifest.bootstrap_session_root
        self.public_key = PUBLIC

    def sign(self, payload: bytes) -> bytes:
        return PRIVATE.sign(payload)


class _SessionCaller:
    def __init__(self, authority, session_root: str, private_key):
        self.actor_root = authority.manifest.principal_root
        self.session_root = session_root
        self.public_key = private_key.public_key().public_bytes(
            serialization.Encoding.Raw,
            serialization.PublicFormat.Raw,
        )
        self._private_key = private_key

    def sign(self, payload: bytes) -> bytes:
        return self._private_key.sign(payload)


def _authority():
    return create_unified_authority(
        CellStore(),
        MemorySigningKeyProvider(
            "clean-visual-authority", b"clean-visual-authority-key" + b"0" * 6
        ),
        key_id="clean-visual-authority",
        application_label="ArchHub",
        principal_label="Founder",
        bootstrap_session_label="Clean visual authority court",
        bootstrap_session_public_key=PUBLIC,
        composition_labels=("Interface", "Workshop", "Agent Sessions"),
    )


def _legacy_descriptor(compose, root: str, projection):
    store = CellStore()
    batch = CellBatch(store)
    protocol = compose_view_template_protocol(
        batch, prefix=VIEW_TEMPLATE_PREFIX
    )
    compose(batch, protocol)
    batch.commit()
    return render_view_template(
        store.snapshot(), protocol, root, projection
    )


TEMPLATE_CASES = (
    (
        "canvas-card",
        compose_canvas_card_template,
        CANVAS_CARD_TEMPLATE_ROOT,
        {
            "id": "node-a",
            "label": "Plan",
            "assembly": None,
            "composition": False,
            "openable": True,
            "member_count": 3,
            "connection_count": 2,
        },
    ),
    (
        "canvas-port",
        compose_canvas_port_template,
        CANVAS_PORT_TEMPLATE_ROOT,
        {
            "id": "port-a",
            "name": "Evidence",
            "side": "target",
            "mode": "connection",
            "node_id": "node-a",
            "connectable": True,
            "read_only": False,
            "selected": True,
            "context": True,
        },
    ),
    (
        "properties",
        compose_field_list_template,
        FIELD_LIST_TEMPLATE_ROOT,
        {
            "selected": "node-a",
            "properties": [{
                "relation": "property:state",
                "label": "state",
                "value": "working",
                "editable": True,
                "control": "control:state",
                "event_fact_input": "event:submitted-value",
            }],
        },
    ),
    (
        "inspector-controls",
        compose_inspector_controls_template,
        INSPECTOR_CONTROLS_TEMPLATE_ROOT,
        {
            "inspector": {
                "lenses": [{"id": "use", "label": "Use", "active": True}],
                "presentation": {
                    "panels": [{
                        "id": "properties",
                        "label": "Properties",
                        "active": True,
                    }],
                },
            },
        },
    ),
    (
        "inspector-shell",
        compose_inspector_shell_template,
        INSPECTOR_SHELL_TEMPLATE_ROOT,
        {
            "selected": "node-a",
            "panels": [{
                "id": "properties",
                "key": "inspector-tabpanel:properties",
                "panel_id": "inspector-panel-0",
                "tab_id": "inspector-tab-0",
                "active": True,
            }],
        },
    ),
    (
        "library-shell",
        compose_library_shell_template,
        LIBRARY_SHELL_TEMPLATE_ROOT,
        {"title": "Node Library", "count_text": "1 node"},
    ),
    (
        "library-definition",
        compose_library_definition_template,
        LIBRARY_DEFINITION_TEMPLATE_ROOT,
        {
            "id": "definition-a",
            "name": "Plan",
            "version": "1",
            "parts": 2,
            "interfaces": 3,
            "category": "Workshop",
            "description": "Reusable planning assembly",
            "search_text": "plan workshop reusable",
            "selected": False,
            "control": {
                "owner": "control:place",
                "title": "Place assembly",
                "icon": "plus",
                "activation": {
                    "binding": "binding:place",
                    "capability": "capability:instantiate",
                },
            },
        },
    ),
    (
        "canvas-toolbar",
        compose_canvas_toolbar_template,
        CANVAS_TOOLBAR_TEMPLATE_ROOT,
        {
            "trail": [{
                "root": "scope-a",
                "label": "Workshop",
                "key": "toolbar:scope:item:scope-a",
                "current": True,
                "show_divider": False,
            }],
            "controls": [{
                "owner": "control:undo",
                "title": "Undo",
                "icon": "undo-2",
                "activation": {
                    "binding": "binding:undo",
                    "capability": "capability:history",
                    "arguments": {"operation": "undo"},
                },
            }],
            "zoom_percent": 100,
            "selection_count": 1,
        },
    ),
    (
        "relation-composer",
        compose_relation_composer_view_template,
        RELATION_COMPOSER_VIEW_TEMPLATE_ROOT,
        {
            "definition": "relation-definition-a",
            "name": "Connect work",
            "complete": False,
            "roles": [],
            "submit": None,
        },
    ),
)

EXPECTED_TEMPLATES = {
    "properties",
    "focus",
    "interfaces",
    "relations",
    "controls",
    "presentation",
    "authority",
    "timeline",
    "evidence",
    "cell-floor",
    "inspector-header",
    "canvas-card",
    "inspector-controls",
    "inspector-shell",
    "canvas-port",
    "canvas-toolbar",
    "canvas-heading",
    "library-definition",
    "library-primitive",
    "library-section",
    "library-shell",
    "relation-composer",
}

CANONICAL_EQUIVALENCE_CASES = (
    (
        "properties",
        compose_field_list_template,
        FIELD_LIST_TEMPLATE_ROOT,
        _GRAPH_PROPERTIES_PRESENTER_COURTS["field-list"],
    ),
    (
        "focus",
        compose_focus_list_template,
        FOCUS_LIST_TEMPLATE_ROOT,
        _GRAPH_PROPERTIES_PRESENTER_COURTS["focus-list"],
    ),
    (
        "interfaces",
        compose_interface_list_template,
        INTERFACE_LIST_TEMPLATE_ROOT,
        _GRAPH_PROPERTIES_PRESENTER_COURTS["interface-list"],
    ),
    (
        "relations",
        compose_relation_list_template,
        RELATION_LIST_TEMPLATE_ROOT,
        _GRAPH_PROPERTIES_PRESENTER_COURTS["relation-list"],
    ),
    (
        "controls",
        compose_control_list_template,
        CONTROL_LIST_TEMPLATE_ROOT,
        _GRAPH_PROPERTIES_PRESENTER_COURTS["control-list"],
    ),
    (
        "presentation",
        compose_presentation_list_template,
        PRESENTATION_LIST_TEMPLATE_ROOT,
        _GRAPH_PROPERTIES_PRESENTER_COURTS["presentation-list"],
    ),
    (
        "authority",
        compose_authority_list_template,
        AUTHORITY_LIST_TEMPLATE_ROOT,
        _GRAPH_PROPERTIES_PRESENTER_COURTS["authority-list"],
    ),
    (
        "timeline",
        compose_timeline_template,
        TIMELINE_TEMPLATE_ROOT,
        _GRAPH_PROPERTIES_PRESENTER_COURTS["timeline"],
    ),
    (
        "evidence",
        compose_evidence_list_template,
        EVIDENCE_LIST_TEMPLATE_ROOT,
        _GRAPH_PROPERTIES_PRESENTER_COURTS["evidence-list"],
    ),
    (
        "cell-floor",
        compose_cell_floor_template,
        CELL_FLOOR_TEMPLATE_ROOT,
        _GRAPH_PROPERTIES_PRESENTER_COURTS["cell-floor"],
    ),
    (
        "inspector-header",
        compose_inspector_header_template,
        INSPECTOR_HEADER_TEMPLATE_ROOT,
        _INSPECTOR_HEADER_VIEW_COURT,
    ),
    (
        "canvas-card",
        compose_canvas_card_template,
        CANVAS_CARD_TEMPLATE_ROOT,
        _CANVAS_CARD_VIEW_COURT,
    ),
    (
        "inspector-controls",
        compose_inspector_controls_template,
        INSPECTOR_CONTROLS_TEMPLATE_ROOT,
        _INSPECTOR_CONTROLS_VIEW_COURT,
    ),
    (
        "inspector-shell",
        compose_inspector_shell_template,
        INSPECTOR_SHELL_TEMPLATE_ROOT,
        _INSPECTOR_SHELL_VIEW_COURT,
    ),
    (
        "canvas-port",
        compose_canvas_port_template,
        CANVAS_PORT_TEMPLATE_ROOT,
        _CANVAS_PORT_VIEW_COURT,
    ),
    (
        "canvas-toolbar",
        compose_canvas_toolbar_template,
        CANVAS_TOOLBAR_TEMPLATE_ROOT,
        _CANVAS_TOOLBAR_VIEW_COURT,
    ),
    (
        "canvas-heading",
        compose_canvas_heading_template,
        CANVAS_HEADING_TEMPLATE_ROOT,
        _CANVAS_HEADING_VIEW_COURT,
    ),
    (
        "library-definition",
        compose_library_definition_template,
        LIBRARY_DEFINITION_TEMPLATE_ROOT,
        _LIBRARY_DEFINITION_VIEW_COURT,
    ),
    (
        "library-primitive",
        compose_library_primitive_template,
        LIBRARY_PRIMITIVE_TEMPLATE_ROOT,
        _LIBRARY_PRIMITIVE_VIEW_COURT,
    ),
    (
        "library-section",
        compose_library_section_template,
        LIBRARY_SECTION_TEMPLATE_ROOT,
        _LIBRARY_SECTION_VIEW_COURT,
    ),
    (
        "library-shell",
        compose_library_shell_template,
        LIBRARY_SHELL_TEMPLATE_ROOT,
        _LIBRARY_SHELL_VIEW_COURT,
    ),
    (
        "relation-composer",
        compose_relation_composer_view_template,
        RELATION_COMPOSER_VIEW_TEMPLATE_ROOT,
        _RELATION_COMPOSER_VIEW_COURT,
    ),
)


def test_rejected_parallel_shell_and_browser_tokens_are_unreachable():
    root = Path(__file__).parents[1] / "nodelang"
    rejected = {
        root / "clean_application_view.py",
        root / "clean_application_server.py",
    }
    for path in root.glob("*.py"):
        if path in rejected:
            continue
        source = path.read_text(encoding="utf-8")
        assert "clean_application_server" not in source
        assert "clean_application_view" not in source
    assert rejected <= set(root.glob("*.py"))


def test_visual_templates_install_once_in_the_clean_graph_and_match_existing():
    from nodelang.clean_visual_authority import (
        install_clean_visual_system,
        open_clean_visual_system,
        render_clean_visual_template,
    )

    authority = _authority()
    caller = _Caller(authority)
    first = install_clean_visual_system(
        authority,
        caller=caller,
        command_id=COMMAND_ID,
    )
    revision = authority.store.revision
    cells = dict(authority.store.snapshot().cells)
    replay = install_clean_visual_system(
        authority,
        caller=caller,
        command_id=COMMAND_ID,
    )
    opened = open_clean_visual_system(authority, caller=caller)

    assert replay.replayed is True
    assert authority.store.revision == revision
    assert dict(authority.store.snapshot().cells) == cells
    assert opened.root_id == first.root_id
    assert opened.protocol.root_id == first.protocol.root_id
    assert opened.template_roots == first.template_roots
    assert opened.revision == revision
    assert opened.graph_id == authority.manifest.graph_id
    assert set(opened.template_roots) == EXPECTED_TEMPLATES
    assert {case[0] for case in TEMPLATE_CASES} <= set(opened.template_roots)

    for root_id in (
        opened.root_id,
        opened.protocol.root_id,
        *opened.protocol.roles.values(),
        *opened.protocol.operations.values(),
        *opened.template_roots.values(),
    ):
        assert str(uuid.UUID(root_id)) == root_id
        assert root_id in cells
        assert not root_id.startswith("app:")

    for name, compose, legacy_root, projection in TEMPLATE_CASES:
        assert render_clean_visual_template(
            authority,
            opened,
            name,
            projection,
            caller=caller,
        ) == _legacy_descriptor(compose, legacy_root, projection)


def test_clean_visual_binding_owns_no_parallel_browser_token_state():
    source = (
        Path(__file__).parents[1] / "nodelang" / "clean_visual_authority.py"
    ).read_text(encoding="utf-8")
    for forbidden in (
        "session_token",
        "csrf_token",
        "bootstrap_token",
        "session_valid",
        "clean_application_view",
        "clean_application_server",
    ):
        assert forbidden not in source
    assert "render_view_template" in source
    assert "CellStore(" not in source
    assert "ApplicationServer" not in source
    assert "sqlite3" not in source
    assert "jsonl" not in source


def test_identical_visual_source_cannot_clone_under_another_command():
    from nodelang.clean_visual_authority import install_clean_visual_system

    authority = _authority()
    caller = _Caller(authority)
    first = install_clean_visual_system(
        authority,
        caller=caller,
        command_id=COMMAND_ID,
    )
    revision = authority.store.revision
    cell_count = len(authority.store.snapshot().cells)
    second = install_clean_visual_system(
        authority,
        caller=caller,
        command_id="25f25f38-3442-4483-956f-e2c8d19c77c6",
    )
    assert second.root_id == first.root_id
    assert second.replayed is True
    assert authority.store.revision == revision
    assert len(authority.store.snapshot().cells) == cell_count


def test_concurrent_sessions_cannot_clone_the_visual_system(monkeypatch):
    import nodelang.clean_visual_authority as visual_module

    authority = _authority()
    founder = _Caller(authority)
    session_private = Ed25519PrivateKey.generate()
    enrolled = enroll_session(
        authority,
        "Concurrent visual installer",
        session_private.public_key().public_bytes(
            serialization.Encoding.Raw,
            serialization.PublicFormat.Raw,
        ),
        session_container_root=composition_root(
            authority, "Agent Sessions", caller=founder
        ),
        caller=founder,
        command_id="e2ca0d3d-3229-4374-838e-41a71464f04c",
    )
    session = _SessionCaller(authority, enrolled.root_id, session_private)
    barrier = threading.Barrier(2)
    original = visual_module._compile_visual_source

    def synchronized_compile():
        barrier.wait(timeout=10)
        return original()

    monkeypatch.setattr(
        visual_module, "_compile_visual_source", synchronized_compile
    )
    results = []
    failures = []

    def install(caller, command_id):
        try:
            results.append(visual_module.install_clean_visual_system(
                authority,
                caller=caller,
                command_id=command_id,
            ))
        except Exception as exc:  # the losing optimistic commit must fail closed
            failures.append(exc)

    threads = (
        threading.Thread(target=install, args=(founder, COMMAND_ID)),
        threading.Thread(
            target=install,
            args=(session, "7ae9b831-e18d-4db7-b7c8-4ff553494f7a"),
        ),
    )
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
        assert not thread.is_alive()
    assert len(results) == 1
    assert len(failures) == 1
    assert isinstance(failures[0], Conflict)
    winning_root = results[0].root_id
    revision = authority.store.revision
    cell_count = len(authority.store.snapshot().cells)

    monkeypatch.setattr(visual_module, "_compile_visual_source", original)
    recovered = visual_module.install_clean_visual_system(
        authority,
        caller=session,
        command_id="7ae9b831-e18d-4db7-b7c8-4ff553494f7a",
    )
    assert recovered.root_id == winning_root
    assert recovered.replayed is True
    assert authority.store.revision == revision
    assert len(authority.store.snapshot().cells) == cell_count


def test_every_required_template_matches_the_existing_canonical_descriptor():
    from nodelang.clean_visual_authority import (
        install_clean_visual_system,
        render_clean_visual_template,
    )

    authority = _authority()
    caller = _Caller(authority)
    visual = install_clean_visual_system(
        authority,
        caller=caller,
        command_id=COMMAND_ID,
    )
    assert {case[0] for case in CANONICAL_EQUIVALENCE_CASES} == (
        EXPECTED_TEMPLATES
    )
    for name, compose, legacy_root, projection in CANONICAL_EQUIVALENCE_CASES:
        assert render_clean_visual_template(
            authority,
            visual,
            name,
            projection,
            caller=caller,
        ) == _legacy_descriptor(compose, legacy_root, projection)
