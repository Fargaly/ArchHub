from __future__ import annotations

import ast
import inspect

import pytest

import nodelang.cell_view_template as cell_view_template
from nodelang.cell_protocols import CellBatch
from nodelang.cell_view_template import (
    ViewTemplateBuilder,
    compose_view_template_protocol,
    is_view_template,
    render_view_template,
)
from nodelang.universal_cell import (
    NULL_CELL_ID,
    Cell,
    CellStore,
    InvalidCell,
    MatchBudgetExceeded,
)


_PRODUCT_AND_PRESENTER_NAMES = frozenset({
    "archhub",
    "brain",
    "cockpit",
    "grand map",
    "grand-map",
    "grand_map",
    "properties",
    "watcher",
    "website",
    "field-list",
    "focus-list",
    "presentation-list",
    "evidence-list",
    "interface-list",
    "control-list",
    "timeline",
    "authority-list",
    "relation-list",
    "cell-floor",
})


def _new_builder(prefix: str = "court:protocol"):
    store = CellStore()
    batch = CellBatch(store)
    protocol = compose_view_template_protocol(batch, prefix=prefix)
    return store, batch, protocol, ViewTemplateBuilder(batch, protocol)


def _simple_template(
    *,
    tag: str = "div",
    attribute_name: str | None = None,
):
    store, batch, protocol, builder = _new_builder()
    tag_root = builder.literal("opaque:tag-expression", tag)
    key_root = builder.literal("opaque:key-expression", "opaque:key")
    attributes = ()
    if attribute_name is not None:
        value_root = builder.literal(
            "opaque:attribute-value-expression", "javascript:alert(1)"
        )
        attributes = (
            builder.attribute(
                "opaque:attribute", attribute_name, value_root
            ),
        )
    builder.template(
        "opaque:template-root",
        tag=tag_root,
        key=key_root,
        attributes=attributes,
    )
    batch.commit()
    return store, protocol


def _repeating_template(item_count: int):
    store, batch, protocol, builder = _new_builder("court:repeat-protocol")
    projection_root = builder.expression("opaque:projection", "root")
    items_segment = builder.atom("opaque:items-segment", "items")
    repeat_root = builder.expression(
        "opaque:repeat-expression",
        "path",
        (projection_root, items_segment),
    )
    tag_root = builder.literal("opaque:repeat-tag", "div")
    key_root = builder.expression("opaque:repeat-key", "index")
    builder.template(
        "opaque:repeat-template",
        tag=tag_root,
        key=key_root,
        repeat=repeat_root,
    )
    batch.commit()
    return store, protocol, {"items": list(range(item_count))}


def test_interpreter_source_has_no_product_dispatch_or_dynamic_code():
    source = inspect.getsource(cell_view_template)
    normalized_source = source.casefold()
    leaked_names = {
        name
        for name in _PRODUCT_AND_PRESENTER_NAMES
        if name in normalized_source
    }
    assert leaked_names == set()

    tree = ast.parse(source)
    forbidden_calls = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name):
            called_name = node.func.id
        elif isinstance(node.func, ast.Attribute):
            called_name = node.func.attr
        else:
            continue
        if called_name in {"eval", "exec", "compile"}:
            forbidden_calls.append((called_name, node.lineno))
    assert forbidden_calls == []


def test_template_recognition_depends_on_structure_not_root_names():
    store, batch, protocol, builder = _new_builder("opaque:protocol:9f4a")
    tag_root = builder.literal("opaque:expression:tag", "section")
    key_root = builder.literal("opaque:expression:key", "opaque-key")
    builder.template(
        "7f48d20a-93c8-48c2-a790-0cc5fd3aa9fb",
        tag=tag_root,
        key=key_root,
    )
    batch.add(Cell(
        "template:presenter:properties",
        NULL_CELL_ID,
        NULL_CELL_ID,
        b"looks like a template name",
    ))
    batch.commit()

    snapshot = store.snapshot()
    assert is_view_template(
        snapshot, protocol, "7f48d20a-93c8-48c2-a790-0cc5fd3aa9fb"
    )
    assert not is_view_template(
        snapshot, protocol, "template:presenter:properties"
    )


def test_expression_cycle_fails_closed():
    store, batch, protocol, builder = _new_builder()
    builder.expression(
        "opaque:cyclic-expression",
        "upper",
        ("opaque:cyclic-expression",),
    )
    key_root = builder.literal("opaque:cycle-key", "cycle-key")
    builder.template(
        "opaque:expression-cycle-template",
        tag="opaque:cyclic-expression",
        key=key_root,
    )
    batch.commit()

    with pytest.raises(InvalidCell, match="expression contains a cycle"):
        render_view_template(
            store.snapshot(),
            protocol,
            "opaque:expression-cycle-template",
            {},
        )


def test_child_cycle_fails_closed():
    store, batch, protocol, builder = _new_builder()
    tag_root = builder.literal("opaque:child-cycle-tag", "section")
    key_root = builder.literal("opaque:child-cycle-key", "cycle-key")
    builder.template(
        "opaque:child-cycle-template",
        tag=tag_root,
        key=key_root,
        children=("opaque:child-cycle-template",),
    )
    batch.commit()

    with pytest.raises(InvalidCell, match="child graph contains a cycle"):
        render_view_template(
            store.snapshot(),
            protocol,
            "opaque:child-cycle-template",
            {},
        )


def test_json_output_is_size_bounded():
    store, batch, protocol, builder = _new_builder(
        "court:json-protocol"
    )
    root = builder.expression("opaque:json-root", "root")
    payload_segment = builder.atom("opaque:json-payload-segment", "payload")
    payload = builder.expression(
        "opaque:json-payload", "path", (root, payload_segment)
    )
    encoded = builder.expression(
        "opaque:json-expression", "json", (payload,)
    )
    builder.template(
        "opaque:json-template",
        tag=builder.literal("opaque:json-tag", "div"),
        key=builder.literal("opaque:json-key", "json"),
        text=encoded,
    )
    batch.commit()

    with pytest.raises(MatchBudgetExceeded, match="65536"):
        render_view_template(
            store.snapshot(),
            protocol,
            "opaque:json-template",
            {"payload": "x" * 65_537},
        )


def test_transparent_fragment_cannot_hide_descriptor_authority():
    _store, _batch, _protocol, builder = _new_builder(
        "court:transparent-protocol"
    )
    marker = builder.atom("opaque:transparent-marker", "transparent")
    with pytest.raises(InvalidCell, match="cannot own descriptor fields"):
        builder.template(
            "opaque:invalid-transparent",
            tag=builder.literal("opaque:hidden-tag", "script"),
            key=None,
            transparent=marker,
        )


def test_noncontiguous_expression_order_fails_closed():
    store, protocol = _simple_template()
    order = store.read("opaque:tag-expression:argument:0:order")
    store.commit(store.revision, replace=(Cell(
        order.id, order.link0, order.link1, b"2"
    ),))

    with pytest.raises(InvalidCell, match="order is not contiguous and unique"):
        render_view_template(
            store.snapshot(), protocol, "opaque:template-root", {}
        )


def test_repeat_limit_fails_closed_before_projection():
    store, protocol, projection = _repeating_template(3)

    with pytest.raises(MatchBudgetExceeded, match="repeat limit exceeded"):
        render_view_template(
            store.snapshot(),
            protocol,
            "opaque:repeat-template",
            projection,
            repeat_limit=2,
        )


def test_global_budget_is_shared_across_repeated_projection_work():
    store, protocol, projection = _repeating_template(50)
    assert len(render_view_template(
        store.snapshot(),
        protocol,
        "opaque:repeat-template",
        projection,
    )) == 50

    with pytest.raises(MatchBudgetExceeded, match="exceeded"):
        render_view_template(
            store.snapshot(),
            protocol,
            "opaque:repeat-template",
            projection,
            budget=50,
        )


@pytest.mark.parametrize("tag", ("script", "iframe", "object"))
def test_executable_tags_remain_rejected(tag: str):
    store, protocol = _simple_template(tag=tag)

    with pytest.raises(InvalidCell, match="tag is outside the allowlist"):
        render_view_template(
            store.snapshot(), protocol, "opaque:template-root", {}
        )


@pytest.mark.parametrize("attribute", ("onclick", "style", "src", "srcdoc"))
def test_executable_attributes_remain_rejected(attribute: str):
    store, protocol = _simple_template(attribute_name=attribute)

    with pytest.raises(InvalidCell, match="attribute denied"):
        render_view_template(
            store.snapshot(), protocol, "opaque:template-root", {}
        )
