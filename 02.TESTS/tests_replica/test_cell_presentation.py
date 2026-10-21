from __future__ import annotations

from nodelang.cell_presentation import (
    compose_component,
    compose_panel,
    compose_panel_focus,
    compose_presentation,
    compose_presentation_protocol,
    project_presentation,
)
from nodelang.cell_protocols import CellBatch, read_relation
from nodelang.universal_cell import NULL_CELL_ID, Cell, CellStore


def _fixture():
    store = CellStore()
    batch = CellBatch(store)
    protocol = compose_presentation_protocol(batch, prefix="court:present")
    atoms = {
        name: "court:%s" % name
        for name in (
            "use", "build", "founder", "properties-label",
            "relations-label", "floor-label", "properties-source",
            "relations-source", "floor-source", "fields-presenter",
            "relations-presenter", "floor-presenter",
        )
    }
    for name, root in atoms.items():
        batch.add(Cell(root, NULL_CELL_ID, NULL_CELL_ID, name.encode("ascii")))
    for key in ("properties", "relations", "floor"):
        compose_component(
            batch,
            protocol,
            root_id="court:component:%s" % key,
            label_root=atoms["%s-label" % key],
            source_root=atoms["%s-source" % key],
            presenter_root=atoms[
                "%s-presenter" % ("fields" if key == "properties" else key)
            ],
        )
    compose_panel(
        batch,
        protocol,
        root_id="court:panel:properties",
        label_root=atoms["properties-label"],
        lens_roots=(atoms["use"], atoms["build"]),
        component_roots=("court:component:properties",),
    )
    compose_panel(
        batch,
        protocol,
        root_id="court:panel:relations",
        label_root=atoms["relations-label"],
        lens_roots=(atoms["use"], atoms["build"]),
        component_roots=("court:component:relations",),
    )
    compose_panel(
        batch,
        protocol,
        root_id="court:panel:floor",
        label_root=atoms["floor-label"],
        lens_roots=(atoms["build"],),
        component_roots=("court:component:floor",),
        authority_roots=(atoms["founder"],),
    )
    compose_presentation(
        batch,
        protocol,
        root_id="court:presentation",
        panel_roots=(
            "court:panel:properties",
            "court:panel:relations",
            "court:panel:floor",
        ),
    )
    compose_panel_focus(
        batch,
        protocol,
        root_id="court:focus",
        panel_root="court:panel:properties",
    )
    batch.commit()
    return store, protocol, atoms


def test_panels_are_ordered_relations_and_empty_or_unauthorised_tabs_do_not_exist():
    store, protocol, atoms = _fixture()
    projected = project_presentation(
        store.snapshot(),
        protocol,
        "court:presentation",
        active_lens_root=atoms["use"],
        focus_binding_root="court:focus",
        available_component_roots=("court:component:properties",),
        principal_roots=(),
    )
    assert [panel.root_id for panel in projected.panels] == [
        "court:panel:properties"
    ]
    assert projected.active_panel_root == "court:panel:properties"
    assert set(projected.components) == {"court:component:properties"}


def test_rewiring_graph_focus_changes_the_active_panel_without_renderer_state():
    store, protocol, atoms = _fixture()
    snapshot = store.snapshot()
    focus = read_relation(snapshot, "court:focus", budget=16)[0]
    incidence = snapshot.cells[focus.incidence_id]
    store.commit(snapshot.revision, replace=(Cell(
        incidence.id,
        incidence.link0,
        "court:panel:relations",
        incidence.atom,
    ),))
    projected = project_presentation(
        store.snapshot(),
        protocol,
        "court:presentation",
        active_lens_root=atoms["use"],
        focus_binding_root="court:focus",
        available_component_roots=(
            "court:component:properties",
            "court:component:relations",
        ),
        principal_roots=(),
    )
    assert projected.active_panel_root == "court:panel:relations"


def test_rewiring_panel_content_changes_what_can_render():
    store, protocol, atoms = _fixture()
    snapshot = store.snapshot()
    panel_members = read_relation(
        snapshot, "court:panel:properties", budget=32
    )
    component = next(
        member for member in panel_members
        if member.role_id == protocol.role("component")
    )
    incidence = snapshot.cells[component.incidence_id]
    store.commit(snapshot.revision, replace=(Cell(
        incidence.id,
        incidence.link0,
        "court:component:relations",
        incidence.atom,
    ),))
    projected = project_presentation(
        store.snapshot(),
        protocol,
        "court:presentation",
        active_lens_root=atoms["use"],
        focus_binding_root="court:focus",
        available_component_roots=("court:component:properties",),
        principal_roots=(),
    )
    assert all(
        panel.root_id != "court:panel:properties"
        for panel in projected.panels
    )


def test_floor_requires_both_lens_and_authority():
    store, protocol, atoms = _fixture()
    unauthorised = project_presentation(
        store.snapshot(),
        protocol,
        "court:presentation",
        active_lens_root=atoms["build"],
        focus_binding_root="court:focus",
        available_component_roots=("court:component:floor",),
        principal_roots=(),
    )
    assert not unauthorised.panels
    authorised = project_presentation(
        store.snapshot(),
        protocol,
        "court:presentation",
        active_lens_root=atoms["build"],
        focus_binding_root="court:focus",
        available_component_roots=("court:component:floor",),
        principal_roots=(atoms["founder"],),
    )
    assert [panel.root_id for panel in authorised.panels] == [
        "court:panel:floor"
    ]
