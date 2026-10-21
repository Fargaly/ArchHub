from __future__ import annotations

import pytest

import nodelang.cell_view_template as cell_view_template
from nodelang.cell_protocols import CellBatch, read_relation, rewire_incidence
from nodelang.cell_view_template import (
    ViewTemplateBuilder,
    compose_view_template_protocol,
    is_view_template,
    open_view_template_protocol,
    render_view_template,
    view_template_projection_scope,
)
from nodelang.universal_cell import (
    NULL_CELL_ID,
    Cell,
    CellStore,
    InvalidCell,
    MatchBudgetExceeded,
)


def _template_store():
    store = CellStore()
    batch = CellBatch(store)
    protocol = compose_view_template_protocol(
        batch, prefix="test:view-template"
    )
    builder = ViewTemplateBuilder(batch, protocol)

    root_context = builder.expression("expr:root", "root")
    item_context = builder.expression("expr:item", "item")
    items_segment = builder.atom("segment:items", "items")
    id_segment = builder.atom("segment:id", "id")
    label_segment = builder.atom("segment:label", "label")
    visible_segment = builder.atom("segment:visible", "visible")
    enabled_segment = builder.atom("segment:enabled", "enabled")
    items = builder.expression(
        "expr:items", "path", (root_context, items_segment)
    )
    item_id = builder.expression(
        "expr:item-id", "path", (item_context, id_segment)
    )
    item_label = builder.expression(
        "expr:item-label", "path", (item_context, label_segment)
    )
    item_visible = builder.expression(
        "expr:item-visible", "path", (item_context, visible_segment)
    )
    prefix = builder.literal("expr:key-prefix", "row:")
    key = builder.expression(
        "expr:row-key", "concat", (prefix, item_id)
    )
    label_prefix = builder.literal("expr:label-prefix", "Label: ")
    text = builder.expression(
        "expr:row-text", "concat", (label_prefix, item_label)
    )
    row_tag = builder.literal("expr:row-tag", "button")
    row_class = builder.literal("expr:row-class", "library-row")
    row_type = builder.literal("expr:row-type", "button")
    type_attribute = builder.attribute(
        "attribute:row-type", "type", row_type
    )
    root_attribute = builder.attribute(
        "attribute:row-root", "data-universal-focus", item_id
    )
    row = builder.template(
        "template:row",
        tag=row_tag,
        key=key,
        class_name=row_class,
        text=text,
        attributes=(type_attribute, root_attribute),
        repeat=items,
        condition=item_visible,
    )
    section_tag = builder.literal("expr:section-tag", "section")
    section_key = builder.literal("expr:section-key", "section:items")
    section_class = builder.literal(
        "expr:section-class", "inspector-section"
    )
    builder.template(
        "template:root",
        tag=section_tag,
        key=section_key,
        class_name=section_class,
        children=(row,),
    )
    batch.commit()
    return store, protocol, enabled_segment


def test_graph_template_drives_paths_repetition_conditions_keys_and_actions():
    store, protocol, _enabled_segment = _template_store()
    projection = {
        "items": [
            {"id": "a", "label": "Alpha", "visible": True},
            {"id": "b", "label": "Beta", "visible": False},
            {"id": "c", "label": "Gamma", "visible": True},
        ]
    }
    rendered = render_view_template(
        store.snapshot(), protocol, "template:root", projection
    )
    assert len(rendered) == 1
    assert [child["key"] for child in rendered[0]["children"]] == [
        "row:a", "row:c"
    ]
    assert [child["text"] for child in rendered[0]["children"]] == [
        "Label: Alpha", "Label: Gamma"
    ]
    assert rendered[0]["children"][0]["attributes"] == {
        "type": "button", "data-universal-focus": "a"
    }


def test_shared_pure_expressions_are_memoized_within_one_render_context():
    store, protocol, _enabled_segment = _template_store()
    rendered = render_view_template(
        store.snapshot(),
        protocol,
        "template:root",
        {
            "items": [
                {"id": "item-%s" % index, "label": "Item", "visible": True}
                for index in range(20)
            ]
        },
        budget=800,
    )
    assert len(rendered[0]["children"]) == 20


def test_template_plans_survive_unrelated_commits_and_invalidate_on_dependency(
    monkeypatch,
):
    store, protocol, _enabled_segment = _template_store()
    projection = {
        "items": [{
            "id": "a", "label": "Alpha", "visible": True,
        }]
    }
    original_read_relation = cell_view_template.read_relation
    calls = 0

    def counted_read_relation(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original_read_relation(*args, **kwargs)

    monkeypatch.setattr(
        cell_view_template, "read_relation", counted_read_relation
    )
    with view_template_projection_scope(store):
        first = render_view_template(
            store.snapshot(), protocol, "template:root", projection
        )
    assert calls > 0

    store.commit(store.revision, create=(Cell(
        "unrelated:atom", NULL_CELL_ID, NULL_CELL_ID, b"unrelated"
    ),))
    calls = 0
    with view_template_projection_scope(store):
        second = render_view_template(
            store.snapshot(), protocol, "template:root", projection
        )
    assert second == first
    assert calls == 0

    literal = store.read("expr:label-prefix:value")
    store.commit(store.revision, replace=(Cell(
        literal.id, literal.link0, literal.link1, b"Name: "
    ),))
    calls = 0
    with view_template_projection_scope(store):
        changed = render_view_template(
            store.snapshot(), protocol, "template:root", projection
        )
    assert changed[0]["children"][0]["text"] == "Name: Alpha"
    assert calls > 0


def test_stable_template_plan_invalidates_when_expression_relation_is_rewired():
    store, protocol, enabled_segment = _template_store()
    projection = {
        "items": [{
            "id": "a",
            "label": "Alpha",
            "visible": True,
            "enabled": False,
        }]
    }
    with view_template_projection_scope(store):
        before = render_view_template(
            store.snapshot(), protocol, "template:root", projection
        )
    assert len(before[0]["children"]) == 1

    expression_members = read_relation(
        store.snapshot(), "expr:item-visible", budget=32
    )
    wrappers = [
        member.participant_id for member in expression_members
        if member.role_id == protocol.role("argument")
    ]
    segment_wrapper = read_relation(store.snapshot(), wrappers[1], budget=8)
    segment_incidence = next(
        member.incidence_id for member in segment_wrapper
        if member.role_id == protocol.role("item")
    )
    rewire_incidence(store, segment_incidence, enabled_segment)

    with view_template_projection_scope(store):
        after = render_view_template(
            store.snapshot(), protocol, "template:root", projection
        )
    assert after[0]["children"] == []


def test_rewiring_a_path_cell_changes_the_interpreted_result():
    store, protocol, enabled_segment = _template_store()
    before = render_view_template(
        store.snapshot(),
        protocol,
        "template:root",
        {"items": [{
            "id": "a", "label": "Alpha", "visible": True,
            "enabled": False,
        }]},
    )
    assert len(before[0]["children"]) == 1

    expression_members = read_relation(
        store.snapshot(), "expr:item-visible", budget=32
    )
    argument_wrappers = [
        member.participant_id for member in expression_members
        if member.role_id == protocol.role("argument")
    ]
    segment_wrapper = read_relation(
        store.snapshot(), argument_wrappers[1], budget=8
    )
    segment_incidence = next(
        member.incidence_id for member in segment_wrapper
        if member.role_id == protocol.role("item")
    )
    rewire_incidence(store, segment_incidence, enabled_segment)

    after = render_view_template(
        store.snapshot(),
        protocol,
        "template:root",
        {"items": [{
            "id": "a", "label": "Alpha", "visible": True,
            "enabled": False,
        }]},
    )
    assert after[0]["children"] == []


def test_template_protocol_reopens_and_unsafe_dom_still_fails_closed():
    store, protocol, _enabled_segment = _template_store()
    reopened = open_view_template_protocol(
        store.snapshot(), prefix="test:view-template"
    )
    assert reopened == protocol

    tag_value = store.read("expr:row-tag:value")
    store.commit(store.revision, replace=(Cell(
        tag_value.id, tag_value.link0, tag_value.link1, b"script"
    ),))
    with pytest.raises(InvalidCell, match="tag"):
        render_view_template(
            store.snapshot(),
            protocol,
            "template:root",
            {"items": [{
                "id": "a", "label": "Alpha", "visible": True,
            }]},
        )


def test_generic_count_where_and_slice_are_graph_authored_and_bounded():
    store = CellStore()
    batch = CellBatch(store)
    protocol = compose_view_template_protocol(
        batch, prefix="test:view-template:collection"
    )
    builder = ViewTemplateBuilder(batch, protocol)
    root = builder.expression("collection:root", "root")
    item = builder.expression("collection:item", "item")
    rows_segment = builder.atom("collection:segment:rows", "rows")
    open_segment = builder.atom("collection:segment:open", "open")
    digest_segment = builder.atom("collection:segment:digest", "digest")
    rows = builder.expression(
        "collection:rows", "path", (root, rows_segment)
    )
    is_open = builder.expression(
        "collection:is-open", "path", (item, open_segment)
    )
    count = builder.expression(
        "collection:open-count", "count-where", (rows, is_open)
    )
    digest = builder.expression(
        "collection:digest", "path", (root, digest_segment)
    )
    start = builder.literal("collection:start", 0)
    stop = builder.literal("collection:stop", 12)
    digest_preview = builder.expression(
        "collection:digest-preview", "slice", (digest, start, stop)
    )
    text = builder.expression(
        "collection:text",
        "concat",
        (
            count,
            builder.literal("collection:divider", " / "),
            digest_preview,
        ),
    )
    builder.template(
        "collection:template",
        tag=builder.literal("collection:tag", "div"),
        key=builder.literal("collection:key", "collection:result"),
        text=text,
    )
    batch.commit()

    rendered = render_view_template(
        store.snapshot(),
        protocol,
        "collection:template",
        {
            "rows": [
                {"open": True},
                {"open": False},
                {"open": True},
            ],
            "digest": "0123456789abcdef",
        },
    )
    assert rendered[0]["text"] == "2 / 0123456789ab"

    with pytest.raises(MatchBudgetExceeded):
        render_view_template(
            store.snapshot(),
            protocol,
            "collection:template",
            {"rows": [{"open": True}] * 100, "digest": "abc"},
            budget=40,
        )


def test_parent_find_where_and_add_support_nested_generic_assemblies():
    store = CellStore()
    batch = CellBatch(store)
    protocol = compose_view_template_protocol(
        batch, prefix="test:view-template:nested"
    )
    builder = ViewTemplateBuilder(batch, protocol)

    def atom(name: str, value: object) -> str:
        return builder.atom("nested:segment:%s" % name, value)

    root = builder.expression("nested:root", "root")
    item = builder.expression("nested:item", "item")
    parent = builder.expression("nested:parent", "parent")
    index = builder.expression("nested:index", "index")
    rows = builder.expression(
        "nested:rows", "path", (root, atom("rows", "rows"))
    )
    options = builder.expression(
        "nested:options", "path", (root, atom("options", "options"))
    )
    item_id = builder.expression(
        "nested:item-id", "path", (item, atom("id", "id"))
    )
    item_label = builder.expression(
        "nested:item-label", "path", (item, atom("label", "label"))
    )
    parent_incidence = builder.expression(
        "nested:parent-incidence",
        "path",
        (parent, atom("incidence", "incidence")),
    )
    parent_selected = builder.expression(
        "nested:parent-selected",
        "path",
        (parent, atom("selected", "selected")),
    )
    selected = builder.expression(
        "nested:selected", "equals", (item_id, parent_selected)
    )
    option_key = builder.expression(
        "nested:option-key",
        "concat",
        (
            builder.literal("nested:option-prefix", "option:"),
            parent_incidence,
            builder.literal("nested:option-divider", ":"),
            item_id,
        ),
    )
    position = builder.expression(
        "nested:position",
        "add",
        (index, builder.literal("nested:one", 1)),
    )
    option_text = builder.expression(
        "nested:option-text",
        "concat",
        (position, builder.literal("nested:text-divider", ". "), item_label),
    )
    selected_attribute = builder.attribute(
        "nested:selected-attribute", "data-selected", selected
    )
    builder.template(
        "nested:option-template",
        tag=builder.literal("nested:option-tag", "option"),
        key=option_key,
        text=option_text,
        value=item_id,
        attributes=(selected_attribute,),
        repeat=options,
    )

    row_selected = builder.expression(
        "nested:row-selected",
        "path",
        (item, atom("row-selected", "selected")),
    )
    candidate_parent = builder.expression(
        "nested:candidate-parent", "parent"
    )
    outer_selected = builder.expression(
        "nested:outer-selected",
        "path",
        (candidate_parent, atom("outer-selected", "selected")),
    )
    candidate_matches = builder.expression(
        "nested:candidate-matches",
        "equals",
        (item_id, outer_selected),
    )
    selected_option = builder.expression(
        "nested:selected-option",
        "find-where",
        (options, candidate_matches),
    )
    selected_label = builder.expression(
        "nested:selected-label",
        "path",
        (selected_option, atom("selected-label", "label")),
    )
    option_ids = builder.expression(
        "nested:option-ids", "map", (options, item_id)
    )
    option_ids_json = builder.expression(
        "nested:option-ids-json", "json", (option_ids,)
    )
    option_ids_joined = builder.expression(
        "nested:option-ids-joined",
        "join",
        (option_ids, builder.literal("nested:join-separator", ", ")),
    )
    option_ids_attribute = builder.attribute(
        "nested:option-ids-attribute", "data-parents", option_ids_json
    )
    option_ids_title = builder.attribute(
        "nested:option-ids-title", "title", option_ids_joined
    )
    row_key = builder.expression(
        "nested:row-key",
        "concat",
        (builder.literal("nested:row-prefix", "row:"), row_selected),
    )
    builder.template(
        "nested:row-template",
        tag=builder.literal("nested:row-tag", "select"),
        key=row_key,
        text=selected_label,
        attributes=(option_ids_attribute, option_ids_title),
        children=("nested:option-template",),
        repeat=rows,
    )
    builder.template(
        "nested:root-template",
        tag=builder.literal("nested:root-tag", "section"),
        key=builder.literal("nested:root-key", "nested"),
        children=("nested:row-template",),
    )
    batch.commit()

    rendered = render_view_template(
        store.snapshot(),
        protocol,
        "nested:root-template",
        {
            "rows": [{"incidence": "i1", "selected": "b"}],
            "options": [
                {"id": "a", "label": "Alpha"},
                {"id": "b", "label": "Beta"},
            ],
        },
    )
    row = rendered[0]["children"][0]
    assert row["text"] == "Beta"
    assert row["attributes"]["data-parents"] == '["a", "b"]'
    assert row["attributes"]["title"] == "a, b"
    assert [child["key"] for child in row["children"]] == [
        "option:i1:a", "option:i1:b"
    ]
    assert [child["text"] for child in row["children"]] == [
        "1. Alpha", "2. Beta"
    ]
    assert [child["attributes"]["data-selected"] for child in row["children"]] == [
        False, True
    ]


def test_transparent_fragment_splices_repeated_children_in_order():
    store = CellStore()
    batch = CellBatch(store)
    protocol = compose_view_template_protocol(
        batch, prefix="test:view-template:fragment"
    )
    builder = ViewTemplateBuilder(batch, protocol)
    root = builder.expression("fragment:root", "root")
    item = builder.expression("fragment:item", "item")
    items_segment = builder.atom("fragment:items-segment", "items")
    label_segment = builder.atom("fragment:label-segment", "label")
    items = builder.expression(
        "fragment:items", "path", (root, items_segment)
    )
    label = builder.expression(
        "fragment:label", "path", (item, label_segment)
    )
    key = builder.expression(
        "fragment:row-key",
        "concat",
        (builder.literal("fragment:key-prefix", "row:"), label),
    )
    builder.template(
        "fragment:row",
        tag=builder.literal("fragment:row-tag", "div"),
        key=key,
        text=label,
    )
    builder.template(
        "fragment:splice",
        tag=None,
        key=None,
        children=("fragment:row",),
        repeat=items,
        transparent=builder.atom("fragment:marker", "transparent"),
    )
    builder.template(
        "fragment:section",
        tag=builder.literal("fragment:section-tag", "section"),
        key=builder.literal("fragment:section-key", "section"),
        children=("fragment:splice",),
    )
    batch.commit()

    snapshot = store.snapshot()
    assert is_view_template(snapshot, protocol, "fragment:splice")
    rendered = render_view_template(
        snapshot,
        protocol,
        "fragment:section",
        {"items": [{"label": "A"}, {"label": "B"}]},
    )
    assert [child["key"] for child in rendered[0]["children"]] == [
        "row:A", "row:B"
    ]
