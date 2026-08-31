from __future__ import annotations

from pathlib import Path

import pytest

import nodelang.inspector_descriptor as inspector_descriptor
from nodelang.inspector_descriptor import _floor, descriptor
from nodelang.cell_properties_view import FIELD_LIST_TEMPLATE_ROOT
from nodelang.cell_focus_view import FOCUS_LIST_TEMPLATE_ROOT
from nodelang.cell_evidence_floor_view import (
    CELL_FLOOR_TEMPLATE_ROOT,
    EVIDENCE_LIST_TEMPLATE_ROOT,
)
from nodelang.cell_relations_view import RELATION_LIST_TEMPLATE_ROOT
from nodelang.cell_timeline_view import TIMELINE_TEMPLATE_ROOT
from nodelang.cell_interface_view import INTERFACE_LIST_TEMPLATE_ROOT
from nodelang.cell_control_view import CONTROL_LIST_TEMPLATE_ROOT
from nodelang.cell_presentation_view import PRESENTATION_LIST_TEMPLATE_ROOT
from nodelang.cell_authority_view import AUTHORITY_LIST_TEMPLATE_ROOT
from nodelang.cell_inspector_header_view import (
    INSPECTOR_HEADER_TEMPLATE_ROOT,
)
from nodelang.cell_canvas_card_view import CANVAS_CARD_TEMPLATE_ROOT
from nodelang.cell_inspector_controls_view import (
    INSPECTOR_CONTROLS_TEMPLATE_ROOT,
)
from nodelang.cell_inspector_shell_view import INSPECTOR_SHELL_TEMPLATE_ROOT
from nodelang.cell_canvas_port_view import CANVAS_PORT_TEMPLATE_ROOT
from nodelang.cell_canvas_toolbar_view import CANVAS_TOOLBAR_TEMPLATE_ROOT
from nodelang.cell_canvas_heading_view import CANVAS_HEADING_TEMPLATE_ROOT
from nodelang.cell_library_definition_view import (
    LIBRARY_DEFINITION_TEMPLATE_ROOT,
)
from nodelang.cell_library_primitive_view import (
    LIBRARY_PRIMITIVE_TEMPLATE_ROOT,
)
from nodelang.cell_library_section_view import LIBRARY_SECTION_TEMPLATE_ROOT
from nodelang.cell_library_shell_view import LIBRARY_SHELL_TEMPLATE_ROOT
from nodelang.cell_relation_composer_view import (
    RELATION_COMPOSER_VIEW_TEMPLATE_ROOT,
)
from nodelang.cell_view_template import is_view_template
from nodelang.map_import import resolve_map_path
from nodelang.universal_application import (
    build_universal_application,
    edit_universal_property,
    instantiate_universal_definition,
    instantiate_universal_primitive,
    project_universal_canvas,
    select_universal_root,
    set_universal_inspector_lens,
    set_universal_properties_panel,
    set_universal_selection,
)
from nodelang.universal_cell import InvalidCell


def _walk(items):
    for item in items:
        yield item
        yield from _walk(item.get("children", ()))


def test_legacy_named_presenter_dispatch_is_a_shrink_only_migration_list():
    assert set(inspector_descriptor._PROJECTORS) == set()


def test_descriptor_floor_rejects_executable_or_unbounded_dom_authority():
    with pytest.raises(InvalidCell, match="tag"):
        descriptor("bad", "script")
    with pytest.raises(InvalidCell, match="executable"):
        descriptor("bad", attributes={"onclick": "steal()"})
    with pytest.raises(InvalidCell, match="executable"):
        descriptor("bad", attributes={"style": "display:none"})


def test_descriptor_floor_admits_bounded_search_input_attributes_only():
    search = descriptor(
        "library:search",
        "input",
        attributes={
            "autocomplete": "off",
            "spellcheck": "false",
            "type": "search",
        },
    )
    assert search["attributes"] == {
        "autocomplete": "off",
        "spellcheck": "false",
        "type": "search",
    }
    with pytest.raises(InvalidCell, match="outside the allowlist"):
        descriptor("bad-search", "input", attributes={"autofocus": True})


def test_properties_and_relations_project_stable_graph_identity_bindings():
    store, registry = build_universal_application(resolve_map_path())
    projection = project_universal_canvas(store, registry)

    fields = next(
        component["descriptor"]
        for panel in projection["inspector"]["presentation"]["panels"]
        for component in panel["components"]
        if component["id"] == registry.properties_component_roots["properties"]
    )
    field_nodes = list(_walk(fields))
    editable = [
        item for item in field_nodes
        if "data-universal-event-fact-input" in item["attributes"]
    ]
    assert {
        item["attributes"]["data-universal-control"] for item in editable
    } == {
        item["relation"] for item in projection["properties"]
        if item["editable"]
    }
    assert {
        item["attributes"]["data-universal-event-fact-input"]
        for item in editable
    } == {
        item["event_fact_input"] for item in projection["properties"]
        if item["editable"]
    }
    assert all(item["key"].startswith("property-input:") for item in editable)

    set_universal_properties_panel(
        store, registry, registry.properties_panel_roots["relations"]
    )
    relation_projection = project_universal_canvas(store, registry)
    relations = next(
        component["descriptor"]
        for panel in relation_projection["inspector"]["presentation"]["panels"]
        for component in panel["components"]
        if component["id"] == registry.properties_component_roots["relations"]
    )
    relation_nodes = list(_walk(relations))
    assert {
        item["attributes"]["data-universal-relation"]
        for item in relation_nodes
        if "data-universal-relation" in item["attributes"]
    } == {
        wire["id"] for wire in relation_projection["wires"]
        if wire["source"] == relation_projection["selected"]
        or wire["target"] == relation_projection["selected"]
    }


def test_multi_selection_field_uses_varies_without_faking_a_scalar_value():
    store, registry = build_universal_application(resolve_map_path())
    first, _ = instantiate_universal_primitive(
        store, registry, x=420, y=180, title="First Cell", atom="first"
    )
    second, _ = instantiate_universal_primitive(
        store, registry, x=760, y=360, title="Second Cell", atom="second"
    )
    set_universal_selection(store, registry, (first, second), focus_root=second)
    projection = project_universal_canvas(store, registry)
    title = next(row for row in projection["properties"] if row["label"] == "title")
    fields = next(
        component["descriptor"]
        for panel in projection["inspector"]["presentation"]["panels"]
        for component in panel["components"]
        if component["id"] == registry.properties_component_roots["properties"]
    )
    title_input = next(
        item for item in _walk(fields)
        if item["key"] == "property-input:%s" % title["relation"]
    )
    assert title_input["value"] == ""
    assert title_input["attributes"]["placeholder"] == "Varies"
    assert title_input["attributes"]["data-universal-mixed"] == "true"
    assert title_input["attributes"]["data-universal-control"] == title["control"]


def test_floor_presenter_exposes_no_edit_control_for_a_noneditable_cell():
    store, registry = build_universal_application(resolve_map_path())
    projection = project_universal_canvas(store, registry)
    floor = _floor(projection)
    nodes = list(_walk(floor))
    assert not any(
        "data-universal-atom" in item["attributes"] for item in nodes
    )
    assert any(item.get("text") == "PHYSICAL FLOOR" for item in nodes)


def test_use_lens_does_not_expose_the_raw_physical_floor():
    store, registry = build_universal_application(resolve_map_path())
    projection = project_universal_canvas(store, registry)

    assert [
        lens["name"] for lens in projection["inspector"]["lenses"]
        if lens["active"]
    ] == ["use"]
    panels = projection["inspector"]["presentation"]["panels"]
    # History stands for every selected root now: an append-only graph
    # always has history, and an empty timeline is an honest answer.
    assert {panel["label"] for panel in panels} == {
        "Properties", "Relations", "Presentation", "History",
    }
    assert all(
        component["id"] != registry.properties_component_roots["floor"]
        for panel in panels
        for component in panel["components"]
    )

    projected_nodes = [
        node
        for panel in panels
        for component in panel["components"]
        for node in _walk(component.get("descriptor") or ())
    ]
    visible_text = {node.get("text") for node in projected_nodes}
    visible_keys = {node.get("key") for node in projected_nodes}
    assert "PHYSICAL FLOOR" not in visible_text
    assert not any(str(key).startswith("floor:") for key in visible_keys)
    assert not any(str(key).startswith("floor-atom:") for key in visible_keys)

    set_universal_inspector_lens(
        store, registry, registry.inspector_lens_roots["floor"]
    )
    floor_projection = project_universal_canvas(store, registry)
    floor_panel = floor_projection["inspector"]["presentation"]["panels"]
    assert [(panel["label"], panel["active"]) for panel in floor_panel] == [
        ("Floor", True),
    ]
    assert [
        component["id"]
        for panel in floor_panel
        for component in panel["components"]
    ] == [registry.properties_component_roots["floor"]]


def test_inspector_header_is_an_executable_graph_template():
    store, registry = build_universal_application(resolve_map_path())
    projection = project_universal_canvas(store, registry)
    header = projection["inspector"]["header_descriptor"]
    nodes = list(_walk(header))
    assert is_view_template(
        store.snapshot(),
        registry.view_template_protocol,
        INSPECTOR_HEADER_TEMPLATE_ROOT,
    )
    assert [item["text"] for item in nodes if item["key"] == "inspector:kicker"]
    assert [
        item["text"] for item in nodes if item["key"] == "inspector:title"
    ] == [projection["selected_title"]]


def test_canvas_cards_are_rendered_by_one_executable_graph_template():
    store, registry = build_universal_application(resolve_map_path())
    projection = project_universal_canvas(store, registry)
    assert is_view_template(
        store.snapshot(),
        registry.view_template_protocol,
        CANVAS_CARD_TEMPLATE_ROOT,
    )
    for node in projection["nodes"]:
        descriptors = node["card_descriptor"]
        assert len(descriptors) == 1
        assert descriptors[0]["key"] == "canvas:node:%s" % node["id"]
        card_nodes = list(_walk(descriptors))
        by_key = {descriptor["key"]: descriptor for descriptor in card_nodes}
        assert by_key["canvas:node:%s:title" % node["id"]]["text"] == (
            node["label"]
        )
        assert descriptors[0]["attributes"]["aria-label"] == (
            "%s. %s relations" % (node["label"], node["connection_count"])
        )
        assert "canvas:node:%s:ports" % node["id"] in by_key


def test_inspector_lenses_and_tabs_are_one_executable_graph_template():
    store, registry = build_universal_application(resolve_map_path())
    projection = project_universal_canvas(store, registry)
    assert is_view_template(
        store.snapshot(),
        registry.view_template_protocol,
        INSPECTOR_CONTROLS_TEMPLATE_ROOT,
    )
    controls = {
        item["key"]: item
        for item in projection["inspector"]["controls_descriptor"]
    }
    assert len(controls["inspector:lenses"]["children"]) == len(
        projection["inspector"]["lenses"]
    )
    assert len(controls["inspector:tabs"]["children"]) == len(
        projection["inspector"]["presentation"]["panels"]
    )


def test_canvas_interfaces_are_rendered_by_one_executable_graph_template():
    store, registry = build_universal_application(resolve_map_path())
    projection = project_universal_canvas(store, registry)
    assert is_view_template(
        store.snapshot(),
        registry.view_template_protocol,
        CANVAS_PORT_TEMPLATE_ROOT,
    )
    ports = [port for node in projection["nodes"] for port in node["ports"]]
    assert ports
    for port in ports:
        assert len(port["descriptor"]) == 1
        descriptor = port["descriptor"][0]
        assert descriptor["key"] == "canvas:interface:%s" % port["id"]
        assert descriptor["attributes"]["data-universal-interface"] == (
            port["id"]
        )
        assert descriptor["text"] == port["name"]


def test_catalogue_rows_are_rendered_by_one_executable_graph_template():
    store, registry = build_universal_application(resolve_map_path())
    projection = project_universal_canvas(store, registry)
    assert is_view_template(
        store.snapshot(),
        registry.view_template_protocol,
        LIBRARY_DEFINITION_TEMPLATE_ROOT,
    )
    for definition in projection["catalog"]:
        assert len(definition["descriptor"]) == 1
        descriptor = definition["descriptor"][0]
        assert descriptor["key"] == "library:entry:%s" % definition["id"]
        rows = [
            item for item in _walk((descriptor,))
            if item["attributes"].get("data-universal-definition")
        ]
        assert len(rows) == 1
        assert rows[0]["attributes"]["data-universal-definition"] == (
            definition["id"]
        )
        place_controls = [
            item for item in _walk((descriptor,))
            if item["attributes"].get("data-universal-definition-place")
        ]
        assert len(place_controls) == 1
        place_control = next(
            control
            for control in projection["configuration"]["design_system"]
            ["control_catalog"]["controls"]
            if control["owner"] == "app:control:library:place"
        )
        assert place_controls[0]["attributes"] == {
            "aria-label": "%s: %s" % (
                place_control["title"], definition["name"]
            ),
            "data-control-binding": place_control["activation"]["binding"],
            "data-control-capability": place_control["activation"][
                "capability"
            ],
            "data-control-icon": place_control["icon"],
            "data-universal-control": place_control["owner"],
            "data-universal-definition-place": definition["id"],
            "title": "%s: %s" % (
                place_control["title"], definition["name"]
            ),
            "type": "button",
        }


def test_floor_primitive_is_rendered_by_one_executable_graph_template():
    store, registry = build_universal_application(resolve_map_path())
    projection = project_universal_canvas(store, registry)
    assert is_view_template(
        store.snapshot(),
        registry.view_template_protocol,
        LIBRARY_PRIMITIVE_TEMPLATE_ROOT,
    )
    descriptor = projection["primitive"]["descriptor"]
    assert len(descriptor) == 1
    assert descriptor[0]["attributes"]["data-universal-primitive"] == (
        projection["primitive"]["id"]
    )


def test_catalogue_sections_are_rendered_by_one_executable_graph_template():
    store, registry = build_universal_application(resolve_map_path())
    projection = project_universal_canvas(store, registry)
    assert is_view_template(
        store.snapshot(),
        registry.view_template_protocol,
        LIBRARY_SECTION_TEMPLATE_ROOT,
    )
    for section in projection["catalog_sections"]:
        assert len(section["descriptor"]) == 1
        descriptor = section["descriptor"][0]
        assert descriptor["key"] == "library:section:%s" % section["id"]
        assert descriptor["attributes"] == {
            "data-universal-library-section": section["id"],
        }
        assert descriptor["children"][0]["text"] == section["label"]


def test_node_library_shell_is_one_executable_graph_template():
    store, registry = build_universal_application(resolve_map_path())
    projection = project_universal_canvas(store, registry)
    assert is_view_template(
        store.snapshot(),
        registry.view_template_protocol,
        LIBRARY_SHELL_TEMPLATE_ROOT,
    )
    descriptor = projection["library"]["descriptor"]
    assert len(descriptor) == 1
    assert descriptor[0]["key"] == "library:surface"
    assert descriptor[0]["children"][0]["text"] == (
        projection["library"]["title"]
    )
    search = descriptor[0]["children"][1]
    assert search["attributes"] == {
        "aria-label": "Search Node Library",
        "autocomplete": "off",
        "data-universal-library-search": "True",
        "placeholder": "Search nodes",
        "spellcheck": "false",
        "type": "search",
    }
    assert descriptor[0]["children"][2]["attributes"] == {
        "data-universal-library-result-count": "True",
    }
    assert descriptor[0]["children"][2]["text"] == (
        projection["library"]["count_text"]
    )
    assert descriptor[0]["children"][3]["attributes"] == {
        "data-universal-library-list": "True",
    }


def test_properties_shell_and_tabpanels_are_one_executable_graph_template():
    store, registry = build_universal_application(resolve_map_path())
    projection = project_universal_canvas(store, registry)
    assert is_view_template(
        store.snapshot(),
        registry.view_template_protocol,
        INSPECTOR_SHELL_TEMPLATE_ROOT,
    )
    descriptor = projection["inspector"]["shell_descriptor"]
    assert len(descriptor) == 1
    shell = descriptor[0]
    assert shell["key"] == "inspector:root"
    assert shell["attributes"] == {
        "data-inspected-node": projection["selected"],
        "data-visible": "True",
    }
    panels = projection["inspector"]["presentation"]["panels"]
    assert len(shell["children"]) == len(panels)
    for index, (panel, rendered) in enumerate(zip(panels, shell["children"])):
        assert rendered["key"] == "inspector-tabpanel:%s" % panel["id"]
        assert rendered["attributes"] == {
            "aria-labelledby": "inspector-tab-%s" % index,
            "data-inspector-tabpanel": panel["id"],
            "hidden": not panel["active"],
            "id": "inspector-panel-%s" % index,
            "role": "tabpanel",
            "tabindex": "0",
        }


def test_complete_canvas_toolbar_is_one_executable_graph_template():
    store, registry = build_universal_application(resolve_map_path())
    projection = project_universal_canvas(store, registry)
    assert is_view_template(
        store.snapshot(),
        registry.view_template_protocol,
        CANVAS_TOOLBAR_TEMPLATE_ROOT,
    )
    descriptor = projection["toolbar_descriptor"]
    assert len(descriptor) == 1
    surface = descriptor[0]
    assert surface["key"] == "toolbar:surface"
    descriptors = list(_walk(descriptor))
    scope = next(
        item for item in descriptors if item["key"] == "toolbar:scope"
    )
    zoom = next(
        item for item in descriptors
        if item["attributes"].get("data-universal-toolbar-zoom-value")
    )
    selection = next(
        item for item in descriptors
        if item["attributes"].get("data-universal-toolbar-selection-value")
    )
    assert scope["key"] == "toolbar:scope"
    assert scope["attributes"] == {
        "data-universal-toolbar-scope": "True",
    }
    assert zoom["text"] == "%s%%" % round(
        float(projection["viewport"]["zoom"]) * 100
    )
    assert selection["text"] == "%s selected" % len(
        projection["selection"]
    )
    controls = sorted(
        (
            control for control in projection["configuration"]["design_system"]
            ["control_catalog"]["controls"]
            if control["zone"] == "canvas-toolbar" and control["applicable"]
        ),
        key=lambda control: control["order"],
    )
    rendered_controls = [
        item for item in descriptors
        if item["attributes"].get("data-universal-control")
    ]
    assert [
        item["attributes"]["data-universal-control"]
        for item in rendered_controls
    ] == [control["owner"] for control in controls]
    for control, rendered in zip(controls, rendered_controls):
        assert rendered["tag"] == "button"
        assert rendered["attributes"]["data-control-binding"] == (
            control["activation"]["binding"]
        )
        assert rendered["attributes"]["data-control-capability"] == (
            control["activation"]["capability"]
        )
        assert rendered["attributes"]["data-control-icon"] == control["icon"]
        assert rendered["attributes"]["aria-label"] == control["title"]

    trail = projection["scope"]["trail"]
    rendered_trail = [
        item for item in scope["children"]
        if item["key"].startswith("toolbar:scope:item:")
    ]
    assert len(rendered_trail) == len(trail)
    for index, (item, rendered) in enumerate(zip(trail, rendered_trail)):
        assert rendered["key"] == "toolbar:scope:item:%s" % item["root"]
        children = rendered["children"]
        assert any(child["text"] == item["label"] for child in children)
        assert any(child["text"] == "/" for child in children) is bool(index)


def test_canvas_heading_is_one_graph_template_bound_to_the_active_scope():
    store, registry = build_universal_application(resolve_map_path())
    projection = project_universal_canvas(store, registry)
    assert is_view_template(
        store.snapshot(),
        registry.view_template_protocol,
        CANVAS_HEADING_TEMPLATE_ROOT,
    )
    descriptor = projection["canvas_heading_descriptor"]
    assert len(descriptor) == 1
    heading = descriptor[0]
    assert heading["key"] == "canvas:heading"
    assert heading["text"] == projection["scope"]["current_label"]
    assert heading["attributes"] == {
        "data-universal-canvas-heading": projection["scope"]["current"],
    }


def test_canvas_signature_changes_when_visible_graph_presentation_changes():
    store, registry = build_universal_application(resolve_map_path())
    before = project_universal_canvas(store, registry)
    selected = before["selected"]
    title = next(
        row for row in before["properties"] if row["label"] == "title"
    )
    edit_universal_property(
        store, registry, title["relation"], "Signature court title"
    )
    after = project_universal_canvas(store, registry)
    assert next(
        node for node in after["nodes"] if node["id"] == selected
    )["label"] == "Signature court title"
    assert after["canvas_signature"] != before["canvas_signature"]


def test_relation_composer_is_rendered_by_one_executable_graph_template():
    store, registry = build_universal_application(resolve_map_path())
    definition = next(
        item for item in project_universal_canvas(store, registry)["catalog"]
        if item["composition_contract"]
    )
    set_universal_selection(store, registry, (), focus_root=definition["id"])
    projection = project_universal_canvas(store, registry)
    composer = projection["selected_definition"]["composer"]
    assert is_view_template(
        store.snapshot(),
        registry.view_template_protocol,
        RELATION_COMPOSER_VIEW_TEMPLATE_ROOT,
    )
    assert len(composer["descriptor"]) == 1
    descriptors = list(_walk(composer["descriptor"]))
    assert composer["descriptor"][0]["attributes"][
        "data-universal-relation-composer"
    ] == definition["id"]
    assert len([
        item for item in descriptors
        if item["attributes"].get("data-universal-contract-role")
        and item["tag"] == "select"
    ]) == sum(
        role["minimum"]
        for role in definition["composition_contract"]["roles"]
        if not role["fixed"]
    )


def test_every_admitted_standard_presenter_has_nonempty_generic_descriptors():
    store, registry = build_universal_application(resolve_map_path())
    seen = set()

    def inspect():
        projection = project_universal_canvas(store, registry)
        panel_roots = [
            panel["id"]
            for panel in projection["inspector"]["presentation"]["panels"]
        ]
        assert panel_roots
        for panel_root in panel_roots:
            set_universal_properties_panel(store, registry, panel_root)
            active_projection = project_universal_canvas(store, registry)
            active = [
                panel
                for panel in active_projection["inspector"]["presentation"][
                    "panels"
                ]
                if panel["active"]
            ]
            assert len(active) == 1
            assert active[0]["id"] == panel_root
            for component in active[0]["components"]:
                assert component.get("descriptor"), component["presenter_name"]
                seen.add(component["projector"])

    for lens in ("use", "build", "govern", "floor"):
        set_universal_inspector_lens(
            store, registry, registry.inspector_lens_roots[lens]
        )
        inspect()

    instantiate_universal_definition(
        store,
        registry,
        registry.standard_library.definition_roots[1],
        x=400,
        y=160,
    )
    set_universal_inspector_lens(
        store, registry, registry.inspector_lens_roots["build"]
    )
    inspect()

    instantiate_universal_definition(
        store,
        registry,
        registry.standard_library.definition_roots[2],
        x=640,
        y=160,
    )
    set_universal_inspector_lens(
        store, registry, registry.inspector_lens_roots["use"]
    )
    inspect()

    select_universal_root(
        store, registry, registry.standard_library.definition_roots[0]
    )
    set_universal_inspector_lens(
        store, registry, registry.inspector_lens_roots["govern"]
    )
    inspect()

    assert seen == {
        FIELD_LIST_TEMPLATE_ROOT,
        FOCUS_LIST_TEMPLATE_ROOT,
        INTERFACE_LIST_TEMPLATE_ROOT,
        RELATION_LIST_TEMPLATE_ROOT,
        CONTROL_LIST_TEMPLATE_ROOT,
        PRESENTATION_LIST_TEMPLATE_ROOT,
        TIMELINE_TEMPLATE_ROOT,
        AUTHORITY_LIST_TEMPLATE_ROOT,
        EVIDENCE_LIST_TEMPLATE_ROOT,
        CELL_FLOOR_TEMPLATE_ROOT,
    }


def test_browser_contains_only_the_generic_descriptor_interpreter():
    source = (
        Path(__file__).resolve().parents[1] / "nodelang" / "ui_runtime.py"
    ).read_text(encoding="utf-8")
    for legacy_dispatch in (
        "presenterBySection", "markSection", "appendSection",
        "VERSIONED THEME", "CONTROLLED REVISION HEADS",
        "AUTHORITY AND POLICY", "PHYSICAL FLOOR", "RELATION NODE",
        "STEM CELL", "LIBRARY DEFINITION", "ASSEMBLY INSTANCE",
        "RELATION CELL", "UNIVERSAL CELL", "NODE LIBRARY",
        "RELEASED ASSEMBLIES", "ADAPTERS / DENY DEFAULT",
        "ASSEMBLY  /  v", "'COMPOSITION'", "'RELATION'", "'CELL'",
        "Visibility level", "Properties panels",
        "Relation role: ", "Relation incidence: ", "Input: ", "Output: ",
        "item.version", "item.parts", "item.interfaces",
        "primitive.kicker", "primitive.label", "primitive.fields",
        "function relationDraft(", "function relationDraftBindings(",
        "function relationDraftComplete(",
        "Choose the visible nodes that participate in this relation.",
        "Select a visible node", "Add participant", "Create relation",
        "element('button','library-definition-place')",
        "element('section','universal-library-group')",
        "element('div','universal-library-section',section.label)",
        "element('div','panel-title',projection.library.title)",
        "element('div','library-list universal-library')",
        "element('section','inspector-panel')",
        "element('div','inspector-tabpanel')",
        "element('div','canvas-scope-trail')",
        "element('span','canvas-scope-divider','/')",
        "element('span','canvas-scope-current',item.label)",
        "element('button','canvas-scope-button',item.label)",
        "element('span','universal-zoom-value'",
        "element('span','canvas-selection-value'",
        "element('div','canvas-heading',projection.scope.current_label)",
    ):
        assert legacy_dispatch not in source
    assert "data-universal-transition" not in source
    assert "'/api/universal/transition'" not in source
    assert "function renderDescriptor(spec)" in source
