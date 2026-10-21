from __future__ import annotations

from nodelang.cell_protocols import CellBatch, read_relation, rewire_incidence
from nodelang.cell_view_template import (
    OPERATION_NAMES,
    ROLE_NAMES,
    ViewTemplateBuilder,
    compose_view_template_protocol,
)
from nodelang.cell_presenter import (
    compose_presenter,
    compose_presenter_protocol,
    read_presenter,
)
from nodelang.cell_properties_view import (
    FIELD_LIST_TEMPLATE_MEMBER_ROOTS,
    GRAPH_FORM_FIELD_LIST_TEMPLATE_MEMBER_ROOTS,
    GRAPH_FORM_FIELD_LIST_TEMPLATE_ROOT,
    LEGACY_FIELD_LIST_TEMPLATE_MEMBER_ROOTS,
    LEGACY_FIELD_LIST_TEMPLATE_ROOT,
    VIEW_TEMPLATE_PREFIX,
)
from nodelang.cell_interface_view import (
    GRAPH_FORM_INTERFACE_LIST_TEMPLATE_MEMBER_ROOTS,
    GRAPH_FORM_INTERFACE_LIST_TEMPLATE_ROOT,
    INTERFACE_LIST_TEMPLATE_MEMBER_ROOTS,
    LEGACY_INTERFACE_LIST_TEMPLATE_MEMBER_ROOTS,
    LEGACY_INTERFACE_LIST_TEMPLATE_ROOT,
)
from nodelang.cell_relations_view import (
    LEGACY_RELATION_LIST_PREFIX,
    LEGACY_RELATION_LIST_TEMPLATE_MEMBER_ROOTS,
    LEGACY_RELATION_LIST_TEMPLATE_ROOT,
    RELATION_LIST_PREFIX,
    RELATION_LIST_TEMPLATE_MEMBER_ROOTS,
    RELATION_LIST_TEMPLATE_ROOT,
)
from nodelang.cell_presentation_view import (
    LEGACY_PRESENTATION_LIST_TEMPLATE_MEMBER_ROOTS,
    LEGACY_PRESENTATION_LIST_TEMPLATE_ROOT,
    PREAPPEARANCE_PRESENTATION_LIST_TEMPLATE_MEMBER_ROOTS,
    PREAPPEARANCE_PRESENTATION_LIST_TEMPLATE_ROOT,
    PRETHEME_PRESENTATION_LIST_TEMPLATE_MEMBER_ROOTS,
    PRETHEME_PRESENTATION_LIST_TEMPLATE_ROOT,
    PRESENTATION_LIST_TEMPLATE_MEMBER_ROOTS,
    PRESENTATION_LIST_TEMPLATE_ROOT,
)
from nodelang.cell_canvas_toolbar_view import (
    CANVAS_TOOLBAR_PREFIX,
    CANVAS_TOOLBAR_TEMPLATE_ROOT,
)
from nodelang.cell_library_definition_view import (
    LIBRARY_DEFINITION_PREFIX,
    LIBRARY_DEFINITION_TEMPLATE_MEMBER_ROOTS,
    LIBRARY_DEFINITION_TEMPLATE_ROOT,
)
from nodelang.inspector_descriptor import _properties as legacy_field_list
from nodelang.cell_secret_keys import MemorySigningKeyProvider
from nodelang.map_import import resolve_map_path
from nodelang.universal_application import (
    build_universal_application,
    _ensure_properties_view_template_graph,
    _ensure_properties_presenter_graph,
    _GRAPH_PROPERTIES_PRESENTER_TEMPLATES,
    _PROPERTIES_COMPONENT_SPECS,
    _PROPERTIES_PRESENTER_CONTRACT,
    _PROPERTIES_PRESENTER_PARTS,
    _PROPERTIES_PRESENTER_PREFIX,
    _properties_presenter_primitive_roots,
    project_universal_canvas,
    restore_universal_application,
    set_universal_inspector_lens,
    set_universal_properties_panel,
    set_universal_scope,
)
from nodelang.universal_cell import NULL_CELL_ID, Cell, CellStore


def _provider() -> MemorySigningKeyProvider:
    provider = MemorySigningKeyProvider(
        "archhub.local.relationship-authority", b"p" * 32
    )
    provider.add_key("archhub.local.court-attestation", b"q" * 32)
    return provider


def test_view_template_protocol_evolves_old_stores_once_in_place():
    store = CellStore()
    batch = CellBatch(store)
    prefix = "app:view-template-protocol"
    vocabulary_role = prefix + ":role:vocabulary-member"
    legacy_operations = (
        "literal", "root", "item", "index", "path", "concat",
        "replace", "equals", "member-of", "and", "or", "not",
        "choose", "fallback", "string", "upper", "length",
    )
    legacy_roles = tuple(
        name for name in ROLE_NAMES if name != "transparent"
    )
    roots = []
    for namespace, names in (
        ("role", legacy_roles),
        ("operation", legacy_operations),
    ):
        for name in names:
            root = "%s:%s:%s" % (prefix, namespace, name)
            batch.add(Cell(
                root, NULL_CELL_ID, NULL_CELL_ID, name.encode("ascii")
            ))
            roots.append(root)
    batch.relation(
        ((vocabulary_role, root) for root in roots),
        relation_id=prefix + ":root",
    )
    batch.commit()
    legacy_revision = store.revision

    protocol = _ensure_properties_view_template_graph(store)
    migrated_revision = store.revision
    assert migrated_revision > legacy_revision
    assert {
        protocol.operation(name) for name in OPERATION_NAMES
    }.issubset(store.snapshot().cells)

    reopened = _ensure_properties_view_template_graph(store)
    assert reopened == protocol
    assert store.revision == migrated_revision


def test_released_canvas_toolbar_upgrade_is_additive_and_idempotent():
    store = CellStore()
    legacy_root = "app:canvas-toolbar-template:v1:surface"
    legacy_member = "app:canvas-toolbar-template:v1:scope"
    legacy_cells = (
        Cell(legacy_root, NULL_CELL_ID, NULL_CELL_ID, b"released-v1-surface"),
        Cell(legacy_member, NULL_CELL_ID, NULL_CELL_ID, b"released-v1-scope"),
    )
    store.commit(store.revision, create=legacy_cells)

    protocol = _ensure_properties_view_template_graph(store)
    migrated_revision = store.revision
    snapshot = store.snapshot()

    assert CANVAS_TOOLBAR_PREFIX == "app:canvas-toolbar-template:v2"
    assert CANVAS_TOOLBAR_TEMPLATE_ROOT in snapshot.cells
    assert snapshot.cells[legacy_root] == legacy_cells[0]
    assert snapshot.cells[legacy_member] == legacy_cells[1]

    reopened = _ensure_properties_view_template_graph(store)
    assert reopened == protocol
    assert store.revision == migrated_revision
    assert store.snapshot().cells[legacy_root] == legacy_cells[0]


def test_released_library_control_upgrade_is_additive_and_idempotent():
    store = CellStore()
    legacy_root = "app:library-definition-template:v2:entry"
    legacy_member = "app:library-definition-template:v2:place"
    legacy_cells = (
        Cell(legacy_root, NULL_CELL_ID, NULL_CELL_ID, b"released-v2-entry"),
        Cell(legacy_member, NULL_CELL_ID, NULL_CELL_ID, b"released-v2-place"),
    )
    store.commit(store.revision, create=legacy_cells)

    protocol = _ensure_properties_view_template_graph(store)
    migrated_revision = store.revision
    snapshot = store.snapshot()

    assert LIBRARY_DEFINITION_PREFIX == "app:library-definition-template:v3"
    assert LIBRARY_DEFINITION_TEMPLATE_ROOT in snapshot.cells
    assert snapshot.cells[legacy_root] == legacy_cells[0]
    assert snapshot.cells[legacy_member] == legacy_cells[1]

    reopened = _ensure_properties_view_template_graph(store)
    assert reopened == protocol
    assert store.revision == migrated_revision
    assert store.snapshot().cells[legacy_root] == legacy_cells[0]


def test_same_root_view_template_upgrade_replaces_released_marker_once():
    store = CellStore()
    batch = CellBatch(store)
    compose_view_template_protocol(batch, prefix=VIEW_TEMPLATE_PREFIX)
    batch.add(Cell(
        LIBRARY_DEFINITION_TEMPLATE_ROOT,
        NULL_CELL_ID,
        NULL_CELL_ID,
        b"released-v3-entry-marker",
    ))
    batch.commit()

    before = store.snapshot()
    assert before.cells[LIBRARY_DEFINITION_TEMPLATE_ROOT].link0 == NULL_CELL_ID
    assert any(
        root_id not in before.cells
        for root_id in LIBRARY_DEFINITION_TEMPLATE_MEMBER_ROOTS
    )

    protocol = _ensure_properties_view_template_graph(store)
    migrated_revision = store.revision
    snapshot = store.snapshot()

    assert migrated_revision > before.revision
    assert snapshot.cells[LIBRARY_DEFINITION_TEMPLATE_ROOT].link0 != NULL_CELL_ID
    assert all(
        root_id in snapshot.cells
        for root_id in LIBRARY_DEFINITION_TEMPLATE_MEMBER_ROOTS
    )

    reopened = _ensure_properties_view_template_graph(store)
    assert reopened == protocol
    assert store.revision == migrated_revision


def test_all_legacy_presenters_migrate_without_incidence_identity_loss():
    store = CellStore()
    view_protocol = _ensure_properties_view_template_graph(store)
    batch = CellBatch(store)
    presenter_protocol = compose_presenter_protocol(
        batch, prefix=_PROPERTIES_PRESENTER_PREFIX
    )
    primitive_roots = _properties_presenter_primitive_roots()
    batch.add(Cell(
        _PROPERTIES_PRESENTER_CONTRACT,
        NULL_CELL_ID,
        NULL_CELL_ID,
        b"safe keyed semantic DOM descriptor v1",
    ))
    for name, root in primitive_roots.items():
        batch.add(Cell(
            root, NULL_CELL_ID, NULL_CELL_ID, name.encode("ascii")
        ))
    for _component, label, presenter in _PROPERTIES_COMPONENT_SPECS:
        label_root = "app:properties-presenter-label:%s" % presenter
        projector_root = "app:properties-projector:%s" % presenter
        batch.add(Cell(
            label_root, NULL_CELL_ID, NULL_CELL_ID, label.encode("utf-8")
        ))
        batch.add(Cell(
            projector_root,
            NULL_CELL_ID,
            NULL_CELL_ID,
            presenter.encode("ascii"),
        ))
        compose_presenter(
            batch,
            presenter_protocol,
            root_id="app:properties-presenter:%s" % presenter,
            label_root=label_root,
            projector_root=projector_root,
            contract_root=_PROPERTIES_PRESENTER_CONTRACT,
            member_roots=(
                primitive_roots[name]
                for name in _PROPERTIES_PRESENTER_PARTS[presenter]
            ),
        )
    batch.commit()
    before = store.snapshot()
    incidence_ids = {
        presenter: tuple(
            member.incidence_id for member in read_relation(
                before,
                "app:properties-presenter:%s" % presenter,
                budget=128,
            )
        )
        for _component, _label, presenter in _PROPERTIES_COMPONENT_SPECS
    }

    migrated = _ensure_properties_presenter_graph(
        store, view_protocol
    )
    migrated_revision = store.revision
    snapshot = store.snapshot()
    assert migrated == presenter_protocol
    for _component, _label, presenter in _PROPERTIES_COMPONENT_SPECS:
        projected = read_presenter(
            snapshot,
            presenter_protocol,
            "app:properties-presenter:%s" % presenter,
        )
        template = _GRAPH_PROPERTIES_PRESENTER_TEMPLATES[presenter]
        assert projected.projector_root == template[1]
        assert projected.member_roots == template[2]
        migrated_incidences = tuple(
            member.incidence_id for member in read_relation(
                snapshot,
                projected.root_id,
                budget=128,
            )
        )
        assert migrated_incidences[:len(incidence_ids[presenter])] == (
            incidence_ids[presenter]
        )
        assert len(migrated_incidences) == len(incidence_ids[presenter]) + (
            len(template[2]) - len(_PROPERTIES_PRESENTER_PARTS[presenter])
        )

    reopened = _ensure_properties_presenter_graph(
        store, view_protocol
    )
    assert reopened == presenter_protocol
    assert store.revision == migrated_revision


def test_relation_list_v2_migrates_to_v3_without_incidence_identity_loss():
    store, registry = build_universal_application(resolve_map_path())
    snapshot = store.snapshot()
    cloned = []
    current_prefix = RELATION_LIST_PREFIX.encode("utf-8")
    legacy_prefix = LEGACY_RELATION_LIST_PREFIX.encode("utf-8")

    def legacy_id(root: str) -> str:
        return (
            LEGACY_RELATION_LIST_PREFIX
            + root.removeprefix(RELATION_LIST_PREFIX)
        )

    for cell in snapshot.cells.values():
        if not cell.id.startswith(RELATION_LIST_PREFIX):
            continue
        cloned.append(Cell(
            legacy_id(cell.id),
            legacy_id(cell.link0)
            if cell.link0.startswith(RELATION_LIST_PREFIX)
            else cell.link0,
            legacy_id(cell.link1)
            if cell.link1.startswith(RELATION_LIST_PREFIX)
            else cell.link1,
            cell.atom.replace(current_prefix, legacy_prefix),
        ))
    assert cloned
    store.commit(store.revision, create=tuple(cloned))

    presenter_root = "app:properties-presenter:relation-list"
    presenter_members = read_relation(
        store.snapshot(), presenter_root, budget=128
    )
    projector = next(
        member for member in presenter_members
        if member.role_id
        == registry.properties_presenter_protocol.role("projector")
    )
    members = [
        member for member in presenter_members
        if member.role_id
        == registry.properties_presenter_protocol.role("member")
    ]
    incidence_ids = tuple(
        member.incidence_id for member in presenter_members
    )
    rewire_incidence(
        store, projector.incidence_id, LEGACY_RELATION_LIST_TEMPLATE_ROOT
    )
    for member in members:
        rewire_incidence(
            store, member.incidence_id, legacy_id(member.participant_id)
        )

    downgraded = read_presenter(
        store.snapshot(),
        registry.properties_presenter_protocol,
        presenter_root,
    )
    assert downgraded.projector_root == LEGACY_RELATION_LIST_TEMPLATE_ROOT
    assert (
        downgraded.member_roots
        == LEGACY_RELATION_LIST_TEMPLATE_MEMBER_ROOTS
    )

    _ensure_properties_presenter_graph(
        store, registry.view_template_protocol
    )
    migrated_revision = store.revision
    migrated = read_presenter(
        store.snapshot(),
        registry.properties_presenter_protocol,
        presenter_root,
    )
    assert migrated.projector_root == RELATION_LIST_TEMPLATE_ROOT
    assert migrated.member_roots == RELATION_LIST_TEMPLATE_MEMBER_ROOTS
    assert tuple(
        member.incidence_id for member in read_relation(
            store.snapshot(), presenter_root, budget=128
        )
    ) == incidence_ids

    _ensure_properties_presenter_graph(
        store, registry.view_template_protocol
    )
    assert store.revision == migrated_revision


def test_graph_presentation_v1_migrates_to_v2_without_incidence_identity_loss():
    store = CellStore()
    view_protocol = _ensure_properties_view_template_graph(store)
    batch = CellBatch(store)
    presenter_protocol = compose_presenter_protocol(
        batch, prefix=_PROPERTIES_PRESENTER_PREFIX
    )
    builder = ViewTemplateBuilder(batch, view_protocol)
    builder.template(
        LEGACY_PRESENTATION_LIST_TEMPLATE_ROOT,
        tag=builder.literal(
            LEGACY_PRESENTATION_LIST_TEMPLATE_ROOT + ":migration-tag", "section"
        ),
        key=builder.literal(
            LEGACY_PRESENTATION_LIST_TEMPLATE_ROOT + ":migration-key",
            "legacy-presentation",
        ),
    )
    for root_id in dict.fromkeys(
        LEGACY_PRESENTATION_LIST_TEMPLATE_MEMBER_ROOTS[1:]
    ):
        batch.add(Cell(root_id, NULL_CELL_ID, NULL_CELL_ID, b"legacy member"))
    label_root = "app:properties-presenter-label:presentation-list"
    batch.add(Cell(
        label_root, NULL_CELL_ID, NULL_CELL_ID, b"Presentation"
    ))
    batch.add(Cell(
        _PROPERTIES_PRESENTER_CONTRACT,
        NULL_CELL_ID,
        NULL_CELL_ID,
        b"safe keyed semantic DOM descriptor v1",
    ))
    compose_presenter(
        batch,
        presenter_protocol,
        root_id="app:properties-presenter:presentation-list",
        label_root=label_root,
        projector_root=LEGACY_PRESENTATION_LIST_TEMPLATE_ROOT,
        contract_root=_PROPERTIES_PRESENTER_CONTRACT,
        member_roots=LEGACY_PRESENTATION_LIST_TEMPLATE_MEMBER_ROOTS,
    )
    batch.commit()
    before = tuple(
        member.incidence_id for member in read_relation(
            store.snapshot(),
            "app:properties-presenter:presentation-list",
            budget=128,
        )
    )

    migrated = _ensure_properties_presenter_graph(store, view_protocol)
    migrated_revision = store.revision
    projected = read_presenter(
        store.snapshot(),
        migrated,
        "app:properties-presenter:presentation-list",
    )
    after = tuple(
        member.incidence_id for member in read_relation(
            store.snapshot(), projected.root_id, budget=128
        )
    )
    assert projected.projector_root == PRESENTATION_LIST_TEMPLATE_ROOT
    assert projected.member_roots == PRESENTATION_LIST_TEMPLATE_MEMBER_ROOTS
    assert after[:len(before)] == before
    assert len(after) == len(before) + 3

    assert _ensure_properties_presenter_graph(store, view_protocol) == migrated
    assert store.revision == migrated_revision


def test_graph_presentation_v3_migrates_to_interaction_controls_once():
    store = CellStore()
    view_protocol = _ensure_properties_view_template_graph(store)
    batch = CellBatch(store)
    presenter_protocol = compose_presenter_protocol(
        batch, prefix=_PROPERTIES_PRESENTER_PREFIX
    )
    builder = ViewTemplateBuilder(batch, view_protocol)
    for index, root_id in enumerate(dict.fromkeys(
        PREAPPEARANCE_PRESENTATION_LIST_TEMPLATE_MEMBER_ROOTS
    )):
        builder.template(
            root_id,
            tag=builder.literal(root_id + ":migration-tag", "div"),
            key=builder.literal(
                root_id + ":migration-key", "appearance-v3:%s" % index
            ),
        )
    label_root = "app:properties-presenter-label:presentation-list"
    batch.add(Cell(label_root, NULL_CELL_ID, NULL_CELL_ID, b"Presentation"))
    batch.add(Cell(
        _PROPERTIES_PRESENTER_CONTRACT,
        NULL_CELL_ID,
        NULL_CELL_ID,
        b"safe keyed semantic DOM descriptor v1",
    ))
    presenter_root = "app:properties-presenter:presentation-list"
    compose_presenter(
        batch,
        presenter_protocol,
        root_id=presenter_root,
        label_root=label_root,
        projector_root=PREAPPEARANCE_PRESENTATION_LIST_TEMPLATE_ROOT,
        contract_root=_PROPERTIES_PRESENTER_CONTRACT,
        member_roots=PREAPPEARANCE_PRESENTATION_LIST_TEMPLATE_MEMBER_ROOTS,
    )
    batch.commit()
    before = tuple(
        member.incidence_id for member in read_relation(
            store.snapshot(), presenter_root, budget=128
        )
    )

    _ensure_properties_presenter_graph(store, view_protocol)
    migrated_revision = store.revision
    projected = read_presenter(
        store.snapshot(), presenter_protocol, presenter_root
    )
    after = tuple(
        member.incidence_id for member in read_relation(
            store.snapshot(), presenter_root, budget=128
        )
    )
    assert projected.projector_root == PRESENTATION_LIST_TEMPLATE_ROOT
    assert projected.member_roots == PRESENTATION_LIST_TEMPLATE_MEMBER_ROOTS
    assert after == before

    _ensure_properties_presenter_graph(store, view_protocol)
    assert store.revision == migrated_revision


def test_graph_presentation_v4_migrates_theme_controls_without_identity_loss():
    store = CellStore()
    view_protocol = _ensure_properties_view_template_graph(store)
    batch = CellBatch(store)
    presenter_protocol = compose_presenter_protocol(
        batch, prefix=_PROPERTIES_PRESENTER_PREFIX
    )
    builder = ViewTemplateBuilder(batch, view_protocol)
    for index, root_id in enumerate(dict.fromkeys(
        PRETHEME_PRESENTATION_LIST_TEMPLATE_MEMBER_ROOTS
    )):
        builder.template(
            root_id,
            tag=builder.literal(root_id + ":migration-tag", "div"),
            key=builder.literal(
                root_id + ":migration-key", "theme-v4:%s" % index
            ),
        )
    label_root = "app:properties-presenter-label:presentation-list"
    batch.add(Cell(label_root, NULL_CELL_ID, NULL_CELL_ID, b"Presentation"))
    batch.add(Cell(
        _PROPERTIES_PRESENTER_CONTRACT,
        NULL_CELL_ID,
        NULL_CELL_ID,
        b"safe keyed semantic DOM descriptor v1",
    ))
    presenter_root = "app:properties-presenter:presentation-list"
    compose_presenter(
        batch,
        presenter_protocol,
        root_id=presenter_root,
        label_root=label_root,
        projector_root=PRETHEME_PRESENTATION_LIST_TEMPLATE_ROOT,
        contract_root=_PROPERTIES_PRESENTER_CONTRACT,
        member_roots=PRETHEME_PRESENTATION_LIST_TEMPLATE_MEMBER_ROOTS,
    )
    batch.commit()
    before = tuple(
        member.incidence_id for member in read_relation(
            store.snapshot(), presenter_root, budget=128
        )
    )

    _ensure_properties_presenter_graph(store, view_protocol)
    migrated_revision = store.revision
    projected = read_presenter(
        store.snapshot(), presenter_protocol, presenter_root
    )
    after = tuple(
        member.incidence_id for member in read_relation(
            store.snapshot(), presenter_root, budget=128
        )
    )
    assert projected.projector_root == PRESENTATION_LIST_TEMPLATE_ROOT
    assert projected.member_roots == PRESENTATION_LIST_TEMPLATE_MEMBER_ROOTS
    assert after == before

    _ensure_properties_presenter_graph(store, view_protocol)
    assert store.revision == migrated_revision


def test_previous_graph_field_list_migrates_once_without_incidence_loss():
    store = CellStore()
    batch = CellBatch(store)
    view_protocol = compose_view_template_protocol(
        batch, prefix=VIEW_TEMPLATE_PREFIX
    )
    presenter_protocol = compose_presenter_protocol(
        batch, prefix=_PROPERTIES_PRESENTER_PREFIX
    )
    builder = ViewTemplateBuilder(batch, view_protocol)
    for index, root in enumerate(LEGACY_FIELD_LIST_TEMPLATE_MEMBER_ROOTS):
        builder.template(
            root,
            tag=builder.literal(root + ":migration-tag", "div"),
            key=builder.literal(
                root + ":migration-key", "legacy:%s" % index
            ),
        )
    contract = _PROPERTIES_PRESENTER_CONTRACT
    label_root = "app:properties-presenter-label:field-list"
    batch.add(Cell(
        contract,
        NULL_CELL_ID,
        NULL_CELL_ID,
        b"safe keyed semantic DOM descriptor v1",
    ))
    batch.add(Cell(
        label_root,
        NULL_CELL_ID,
        NULL_CELL_ID,
        b"Editable properties",
    ))
    compose_presenter(
        batch,
        presenter_protocol,
        root_id="app:properties-presenter:field-list",
        label_root=label_root,
        projector_root=LEGACY_FIELD_LIST_TEMPLATE_ROOT,
        contract_root=contract,
        member_roots=LEGACY_FIELD_LIST_TEMPLATE_MEMBER_ROOTS,
    )
    batch.commit()
    before = read_relation(
        store.snapshot(), "app:properties-presenter:field-list", budget=128
    )
    projector_incidence = next(
        member.incidence_id for member in before
        if member.role_id == presenter_protocol.role("projector")
    )
    member_incidences = tuple(
        member.incidence_id for member in before
        if member.role_id == presenter_protocol.role("member")
    )

    evolved_view = _ensure_properties_view_template_graph(store)
    _ensure_properties_presenter_graph(store, evolved_view)
    migrated_revision = store.revision
    projected = read_presenter(
        store.snapshot(),
        presenter_protocol,
        "app:properties-presenter:field-list",
    )
    after = read_relation(store.snapshot(), projected.root_id, budget=128)
    assert projected.projector_root != LEGACY_FIELD_LIST_TEMPLATE_ROOT
    assert projected.member_roots == FIELD_LIST_TEMPLATE_MEMBER_ROOTS
    assert next(
        member.incidence_id for member in after
        if member.role_id == presenter_protocol.role("projector")
    ) == projector_incidence
    migrated_members = tuple(
        member.incidence_id for member in after
        if member.role_id == presenter_protocol.role("member")
    )
    assert migrated_members[:len(member_incidences)] == member_incidences
    assert len(migrated_members) == len(FIELD_LIST_TEMPLATE_MEMBER_ROOTS)

    _ensure_properties_presenter_graph(store, evolved_view)
    assert store.revision == migrated_revision


def test_previous_graph_interface_list_migrates_once_without_incidence_loss():
    store = CellStore()
    batch = CellBatch(store)
    view_protocol = compose_view_template_protocol(
        batch, prefix=VIEW_TEMPLATE_PREFIX
    )
    presenter_protocol = compose_presenter_protocol(
        batch, prefix=_PROPERTIES_PRESENTER_PREFIX
    )
    builder = ViewTemplateBuilder(batch, view_protocol)
    for index, root in enumerate(dict.fromkeys(
        LEGACY_INTERFACE_LIST_TEMPLATE_MEMBER_ROOTS
    )):
        builder.template(
            root,
            tag=builder.literal(root + ":migration-tag", "div"),
            key=builder.literal(
                root + ":migration-key", "legacy-interface:%s" % index
            ),
        )
    contract = _PROPERTIES_PRESENTER_CONTRACT
    label_root = "app:properties-presenter-label:interface-list"
    batch.add(Cell(
        contract,
        NULL_CELL_ID,
        NULL_CELL_ID,
        b"safe keyed semantic DOM descriptor v1",
    ))
    batch.add(Cell(
        label_root,
        NULL_CELL_ID,
        NULL_CELL_ID,
        b"Public interfaces",
    ))
    compose_presenter(
        batch,
        presenter_protocol,
        root_id="app:properties-presenter:interface-list",
        label_root=label_root,
        projector_root=LEGACY_INTERFACE_LIST_TEMPLATE_ROOT,
        contract_root=contract,
        member_roots=LEGACY_INTERFACE_LIST_TEMPLATE_MEMBER_ROOTS,
    )
    batch.commit()
    before = read_relation(
        store.snapshot(),
        "app:properties-presenter:interface-list",
        budget=128,
    )
    projector_incidence = next(
        member.incidence_id for member in before
        if member.role_id == presenter_protocol.role("projector")
    )
    member_incidences = tuple(
        member.incidence_id for member in before
        if member.role_id == presenter_protocol.role("member")
    )

    evolved_view = _ensure_properties_view_template_graph(store)
    _ensure_properties_presenter_graph(store, evolved_view)
    migrated_revision = store.revision
    projected = read_presenter(
        store.snapshot(),
        presenter_protocol,
        "app:properties-presenter:interface-list",
    )
    after = read_relation(store.snapshot(), projected.root_id, budget=128)
    assert projected.projector_root != LEGACY_INTERFACE_LIST_TEMPLATE_ROOT
    assert projected.member_roots == INTERFACE_LIST_TEMPLATE_MEMBER_ROOTS
    assert next(
        member.incidence_id for member in after
        if member.role_id == presenter_protocol.role("projector")
    ) == projector_incidence
    migrated_members = tuple(
        member.incidence_id for member in after
        if member.role_id == presenter_protocol.role("member")
    )
    assert migrated_members[:len(member_incidences)] == member_incidences
    assert len(migrated_members) == len(
        INTERFACE_LIST_TEMPLATE_MEMBER_ROOTS
    )

    _ensure_properties_presenter_graph(store, evolved_view)
    assert store.revision == migrated_revision


def _assert_intermediate_presenter_migrates(
    presenter_name,
    presenter_label,
    previous_root,
    previous_members,
    expected_members,
):
    store = CellStore()
    batch = CellBatch(store)
    view_protocol = compose_view_template_protocol(
        batch, prefix=VIEW_TEMPLATE_PREFIX
    )
    presenter_protocol = compose_presenter_protocol(
        batch, prefix=_PROPERTIES_PRESENTER_PREFIX
    )
    builder = ViewTemplateBuilder(batch, view_protocol)
    for index, root in enumerate(dict.fromkeys(previous_members)):
        builder.template(
            root,
            tag=builder.literal(root + ":migration-tag", "div"),
            key=builder.literal(root + ":migration-key", str(index)),
        )
    contract = _PROPERTIES_PRESENTER_CONTRACT
    label_root = "app:properties-presenter-label:%s" % presenter_name
    batch.add(Cell(
        contract, NULL_CELL_ID, NULL_CELL_ID,
        b"safe keyed semantic DOM descriptor v1",
    ))
    batch.add(Cell(
        label_root, NULL_CELL_ID, NULL_CELL_ID, presenter_label.encode()
    ))
    presenter_root = "app:properties-presenter:%s" % presenter_name
    compose_presenter(
        batch,
        presenter_protocol,
        root_id=presenter_root,
        label_root=label_root,
        projector_root=previous_root,
        contract_root=contract,
        member_roots=previous_members,
    )
    batch.commit()
    before = read_relation(store.snapshot(), presenter_root, budget=128)
    projector_incidence = next(
        member.incidence_id for member in before
        if member.role_id == presenter_protocol.role("projector")
    )
    member_incidences = tuple(
        member.incidence_id for member in before
        if member.role_id == presenter_protocol.role("member")
    )

    evolved_view = _ensure_properties_view_template_graph(store)
    _ensure_properties_presenter_graph(store, evolved_view)
    migrated_revision = store.revision
    projected = read_presenter(
        store.snapshot(), presenter_protocol, presenter_root
    )
    after = read_relation(store.snapshot(), presenter_root, budget=128)
    assert projected.projector_root != previous_root
    assert projected.member_roots == expected_members
    assert next(
        member.incidence_id for member in after
        if member.role_id == presenter_protocol.role("projector")
    ) == projector_incidence
    migrated_members = tuple(
        member.incidence_id for member in after
        if member.role_id == presenter_protocol.role("member")
    )
    assert migrated_members[:len(member_incidences)] == member_incidences
    assert len(migrated_members) == len(expected_members)
    _ensure_properties_presenter_graph(store, evolved_view)
    assert store.revision == migrated_revision


def test_graph_form_field_list_migrates_additively_to_operation_bound_form():
    _assert_intermediate_presenter_migrates(
        "field-list",
        "Editable properties",
        GRAPH_FORM_FIELD_LIST_TEMPLATE_ROOT,
        GRAPH_FORM_FIELD_LIST_TEMPLATE_MEMBER_ROOTS,
        FIELD_LIST_TEMPLATE_MEMBER_ROOTS,
    )


def test_graph_form_interface_list_migrates_additively_to_operation_bound_form():
    _assert_intermediate_presenter_migrates(
        "interface-list",
        "Public interfaces",
        GRAPH_FORM_INTERFACE_LIST_TEMPLATE_ROOT,
        GRAPH_FORM_INTERFACE_LIST_TEMPLATE_MEMBER_ROOTS,
        INTERFACE_LIST_TEMPLATE_MEMBER_ROOTS,
    )


def test_properties_tabs_are_exact_graph_panels_with_exact_content_sources():
    store, registry = build_universal_application(resolve_map_path())
    snapshot = store.snapshot()
    presentation = read_relation(
        snapshot, registry.properties_presentation_root, budget=256
    )
    panel_roots = tuple(
        member.participant_id for member in presentation
        if member.role_id
        == registry.properties_presentation_protocol.role("panel")
    )
    assert panel_roots == tuple(registry.properties_panel_roots.values())

    projected = project_universal_canvas(store, registry)
    panels = projected["inspector"]["presentation"]["panels"]
    # History stands for every selected root: an append-only graph always
    # has history, and the empty timeline states itself honestly.
    assert [panel["label"] for panel in panels] == [
        "Properties", "Relations", "Presentation", "History"
    ]
    active_panels = [panel for panel in panels if panel["active"]]
    assert len(active_panels) == 1
    assert active_panels[0]["components"]
    assert all(
        panel["components"] == []
        for panel in panels if not panel["active"]
    )
    for panel in panels:
        for component in panel["components"]:
            assert component["id"] in snapshot.cells
            assert component["source"] in snapshot.cells
            assert component["presenter"] in snapshot.cells


def test_graph_field_list_is_exactly_equivalent_to_retired_python_reference():
    store, registry = build_universal_application(resolve_map_path())
    projection = project_universal_canvas(store, registry)
    component = next(
        component
        for panel in projection["inspector"]["presentation"]["panels"]
        for component in panel["components"]
        if component["id"] == registry.properties_component_roots["properties"]
    )
    assert component["projector_graph"] is True
    assert component["descriptor"] == legacy_field_list(projection)


def test_standard_presenters_are_open_relation_assemblies_not_opaque_atoms():
    store, registry = build_universal_application(resolve_map_path())
    snapshot = store.snapshot()
    assert snapshot.cells[registry.properties_presenter_protocol.root_id].link0
    for root in {
        "app:properties-presenter:%s" % presenter
        for _name, _label, presenter in (
            ("properties", "Editable properties", "field-list"),
            ("focus", "Current focus", "focus-list"),
            ("interfaces", "Public interfaces", "interface-list"),
            ("relations", "Attached relations", "relation-list"),
            ("logic", "Behavior and state", "control-list"),
            ("presentation", "Presentation", "presentation-list"),
            ("history", "Revision history", "timeline"),
            ("access", "Access and authority", "authority-list"),
            ("evidence", "Evidence", "evidence-list"),
            ("floor", "Physical Cell", "cell-floor"),
        )
    }:
        presenter = read_presenter(
            snapshot, registry.properties_presenter_protocol, root
        )
        assert snapshot.cells[root].link0 != NULL_CELL_ID
        assert presenter.member_roots
        assert all(member in snapshot.cells for member in presenter.member_roots)


def test_ui_domain_opens_into_the_live_design_system_and_executable_template():
    store, registry = build_universal_application(resolve_map_path())
    snapshot = store.snapshot()
    ui_root = registry.map.domains["ui"]
    design_memberships = tuple(
        member for member in read_relation(snapshot, ui_root, budget=10_000)
        if member.role_id == registry.roles["member"]
        and member.participant_id == registry.design_system_root
    )
    assert len(design_memberships) == 1

    set_universal_scope(store, registry, ui_root)
    ui_projection = project_universal_canvas(store, registry)
    design_card = next(
        node for node in ui_projection["nodes"]
        if node["id"] == registry.design_system_root
    )
    assert design_card["label"] == "Design System"
    assert design_card["openable"] is True
    assert design_card["composition"] is True

    set_universal_scope(store, registry, registry.design_system_root)
    design_projection = project_universal_canvas(store, registry)
    visible = {node["id"]: node for node in design_projection["nodes"]}
    presenter_roots = {
        "app:properties-presenter:%s" % name for name in (
            "field-list", "focus-list", "interface-list", "relation-list",
            "control-list", "presentation-list", "timeline",
            "authority-list", "evidence-list", "cell-floor",
        )
    }
    assert presenter_roots.issubset(visible)
    assert registry.theme_system_root in visible
    assert visible[registry.theme_system_root]["label"] == "Theme System"
    assert all(visible[root]["openable"] for root in presenter_roots)

    field_list_root = "app:properties-presenter:field-list"
    expected_primitives = read_presenter(
        store.snapshot(), registry.properties_presenter_protocol,
        field_list_root,
    ).member_roots
    assert expected_primitives == FIELD_LIST_TEMPLATE_MEMBER_ROOTS
    set_universal_scope(store, registry, field_list_root)
    primitive_projection = project_universal_canvas(store, registry)
    assert tuple(
        node["id"] for node in primitive_projection["nodes"]
    ) == expected_primitives
    assert [node["label"] for node in primitive_projection["nodes"]] == [
        "Section", "Heading", "Row", "Property label", "Editable input",
        "Read only value", "Property create", "New property label",
        "New property value", "Add property button",
    ]


def test_design_system_hierarchy_reopens_without_identity_or_revision_drift(
    tmp_path,
):
    path = tmp_path / "design-system.sqlite3"
    provider = _provider()
    store, registry = build_universal_application(
        resolve_map_path(), CellStore(path), key_provider=provider
    )
    snapshot = store.snapshot()
    expected_revision = snapshot.revision
    expected_design_members = tuple(
        (member.incidence_id, member.role_id, member.participant_id)
        for member in read_relation(
            snapshot, registry.design_system_root, budget=256
        )
    )
    expected_ui_membership = next(
        member.incidence_id for member in read_relation(
            snapshot, registry.map.domains["ui"], budget=10_000
        )
        if member.role_id == registry.roles["member"]
        and member.participant_id == registry.design_system_root
    )
    store.close()

    reopened = CellStore(path)
    reopened, restored = restore_universal_application(
        resolve_map_path(), reopened, key_provider=provider
    )
    snapshot = reopened.snapshot()
    assert snapshot.revision == expected_revision
    assert tuple(
        (member.incidence_id, member.role_id, member.participant_id)
        for member in read_relation(
            snapshot, restored.design_system_root, budget=256
        )
    ) == expected_design_members
    assert expected_ui_membership == next(
        member.incidence_id for member in read_relation(
            snapshot, restored.map.domains["ui"], budget=10_000
        )
        if member.role_id == restored.roles["member"]
        and member.participant_id == restored.design_system_root
    )
    reopened.close()


def test_rewiring_open_presenter_projector_changes_its_visible_composition():
    store, registry = build_universal_application(resolve_map_path())
    root = "app:properties-presenter:field-list"
    snapshot = store.snapshot()
    projector_member = next(
        member for member in read_relation(snapshot, root, budget=64)
        if member.role_id == registry.properties_presenter_protocol.role(
            "projector"
        )
    )
    rewire_incidence(
        store,
        projector_member.incidence_id,
        RELATION_LIST_TEMPLATE_ROOT,
    )
    projected = project_universal_canvas(store, registry)
    component = projected["inspector"]["presentation"]["panels"][0][
        "components"
    ][0]
    assert component["presenter"] == root
    assert component["presenter_name"] == "graph-template"
    assert component["descriptor"][0]["key"].startswith(
        "presenter:relation-list:"
    )


def test_rewiring_panel_component_changes_the_projected_ui_contract():
    store, registry = build_universal_application(resolve_map_path())
    before = project_universal_canvas(store, registry)
    properties = before["inspector"]["presentation"]["panels"][0]
    assert [item["id"] for item in properties["components"]] == [
        registry.properties_component_roots["properties"],
        registry.properties_component_roots["focus"],
    ]

    snapshot = store.snapshot()
    members = read_relation(
        snapshot,
        registry.properties_panel_roots["properties"],
        budget=64,
    )
    focus_member = next(
        member for member in members
        if member.role_id
        == registry.properties_presentation_protocol.role("component")
        and member.participant_id
        == registry.properties_component_roots["focus"]
    )
    rewire_incidence(
        store,
        focus_member.incidence_id,
        registry.properties_component_roots["relations"],
    )
    after = project_universal_canvas(store, registry)
    properties = after["inspector"]["presentation"]["panels"][0]
    assert [item["id"] for item in properties["components"]] == [
        registry.properties_component_roots["properties"],
        registry.properties_component_roots["relations"],
    ]


def test_rewiring_presenter_changes_visible_descriptor_without_browser_code():
    store, registry = build_universal_application(resolve_map_path())
    snapshot = store.snapshot()
    component_root = registry.properties_component_roots["properties"]
    presenter_member = next(
        member for member in read_relation(snapshot, component_root, budget=32)
        if member.role_id
        == registry.properties_presentation_protocol.role("presenter")
    )
    rewire_incidence(
        store,
        presenter_member.incidence_id,
        "app:properties-presenter:relation-list",
    )
    projection = project_universal_canvas(store, registry)
    component = projection["inspector"]["presentation"]["panels"][0][
        "components"
    ][0]
    assert component["presenter_name"] == "graph-template"
    assert component["descriptor"][0]["key"].startswith(
        "presenter:relation-list:"
    )


def test_active_properties_panel_is_a_durable_view_relation(tmp_path):
    path = tmp_path / "properties-presentation.sqlite3"
    provider = _provider()
    store, registry = build_universal_application(
        resolve_map_path(), CellStore(path), key_provider=provider
    )
    relation_panel = registry.properties_panel_roots["relations"]
    set_universal_properties_panel(store, registry, relation_panel)
    founder = registry.view_sessions[registry.authorization.subject_root]
    incidence_id = founder.properties_panel_incidence
    assert store.snapshot().cells[incidence_id].link1 == relation_panel
    store.close()

    reopened = CellStore(path)
    reopened, restored = restore_universal_application(
        resolve_map_path(), reopened, key_provider=provider
    )
    founder = restored.view_sessions[restored.authorization.subject_root]
    assert founder.properties_panel_incidence == incidence_id
    assert reopened.snapshot().cells[incidence_id].link1 == relation_panel
    assert (
        project_universal_canvas(reopened, restored)["inspector"]
        ["presentation"]["active"]
        == relation_panel
    )
    reopened.close()


def test_lens_and_properties_panel_focus_rewire_atomically():
    store, registry = build_universal_application(resolve_map_path())
    founder = registry.view_sessions[registry.authorization.subject_root]
    relations = registry.properties_panel_roots["relations"]
    floor = registry.properties_panel_roots["floor"]

    set_universal_properties_panel(store, registry, relations)
    before = store.snapshot().revision
    changed = set_universal_inspector_lens(
        store, registry, registry.inspector_lens_roots["floor"]
    )
    assert changed == before + 1
    snapshot = store.snapshot()
    assert (
        snapshot.cells[founder.inspector_lens_incidence].link1
        == registry.inspector_lens_roots["floor"]
    )
    assert snapshot.cells[founder.properties_panel_incidence].link1 == floor
    projection = project_universal_canvas(store, registry)
    assert projection["inspector"]["presentation"]["active"] == floor

    before = snapshot.revision
    changed = set_universal_inspector_lens(
        store, registry, registry.inspector_lens_roots["use"]
    )
    assert changed == before + 1
    snapshot = store.snapshot()
    assert (
        snapshot.cells[founder.inspector_lens_incidence].link1
        == registry.inspector_lens_roots["use"]
    )
    assert (
        snapshot.cells[founder.properties_panel_incidence].link1
        == registry.properties_panel_roots["properties"]
    )
