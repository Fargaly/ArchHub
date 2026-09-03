from __future__ import annotations

import pytest

from nodelang.cell_protocols import (
    CellBatch,
    append_relation_member,
    read_relation,
    rewire_incidence,
)
from nodelang.cell_view_template import (
    ViewTemplateBuilder,
    compose_view_template_protocol,
    is_view_template,
    render_view_template,
)
from nodelang.universal_cell import (
    Cell,
    CellStore,
    InvalidCell,
    MatchBudgetExceeded,
)


def _new_builder(prefix: str):
    store = CellStore()
    batch = CellBatch(store)
    protocol = compose_view_template_protocol(
        batch, prefix=prefix + ":protocol"
    )
    return store, batch, protocol, ViewTemplateBuilder(batch, protocol)


def _projection_path(
    builder: ViewTemplateBuilder,
    prefix: str,
    segment: str,
) -> str:
    root = builder.expression(prefix + ":root", "root")
    segment_root = builder.atom(prefix + ":segment", segment)
    return builder.expression(
        prefix + ":path", "path", (root, segment_root)
    )


def _output_template(
    builder: ViewTemplateBuilder,
    prefix: str,
    *,
    text: str | None = None,
    repeat: str | None = None,
) -> str:
    return builder.template(
        prefix + ":template",
        tag=builder.literal(prefix + ":tag", "div"),
        key=builder.literal(prefix + ":key", "opaque-key"),
        text=text,
        repeat=repeat,
    )


def _collection_template(operation: str):
    prefix = "opaque:collection:" + operation
    store, batch, protocol, builder = _new_builder(prefix)
    collection = _projection_path(builder, prefix + ":source", "values")

    if operation == "repeat":
        template_root = _output_template(
            builder, prefix, repeat=collection
        )
    else:
        item = builder.expression(prefix + ":item", "item")
        if operation == "map":
            expression_root = builder.expression(
                prefix + ":map", "map", (collection, item)
            )
            expression_root = builder.expression(
                prefix + ":json", "json", (expression_root,)
            )
        elif operation == "join":
            separator = builder.literal(prefix + ":separator", ",")
            expression_root = builder.expression(
                prefix + ":join", "join", (collection, separator)
            )
        elif operation in ("find-where", "count-where"):
            predicate = builder.literal(prefix + ":predicate", True)
            expression_root = builder.expression(
                prefix + ":result",
                operation,
                (collection, predicate),
            )
        else:
            raise AssertionError("unsupported test operation")
        template_root = _output_template(
            builder, prefix, text=expression_root
        )

    batch.commit()
    return store, protocol, template_root


def _json_template():
    prefix = "opaque:json"
    store, batch, protocol, builder = _new_builder(prefix)
    payload = _projection_path(builder, prefix + ":payload", "payload")
    encoded = builder.expression(prefix + ":encode", "json", (payload,))
    template_root = _output_template(builder, prefix, text=encoded)
    batch.commit()
    return store, protocol, template_root


def _transparent_fragment():
    prefix = "opaque:fragment"
    store, batch, protocol, builder = _new_builder(prefix)
    child = _output_template(builder, prefix + ":child")
    condition = builder.literal(prefix + ":condition", True)
    marker = builder.atom(prefix + ":marker", "fragment")
    second_marker = builder.atom(prefix + ":second-marker", "fragment")
    fragment = builder.template(
        prefix + ":root",
        tag=None,
        key=None,
        children=(child,),
        condition=condition,
        transparent=marker,
    )
    batch.commit()
    return store, protocol, fragment, second_marker


@pytest.mark.parametrize(
    "outer_operation", ("map", "find-where", "count-where")
)
def test_nested_higher_order_predicate_self_cycles_fail_closed(
    outer_operation: str,
):
    prefix = "opaque:nested-cycle:" + outer_operation
    store, batch, protocol, builder = _new_builder(prefix)
    collection = _projection_path(builder, prefix + ":source", "values")
    current_item = builder.expression(prefix + ":item", "item")
    outer_root = prefix + ":outer"
    nested_mapper = builder.expression(
        prefix + ":nested-map", "map", (current_item, outer_root)
    )
    builder.expression(
        outer_root,
        outer_operation,
        (collection, nested_mapper),
    )
    template_root = _output_template(builder, prefix, text=outer_root)
    batch.commit()

    with pytest.raises(InvalidCell, match="cycle"):
        render_view_template(
            store.snapshot(),
            protocol,
            template_root,
            {"values": [[1]]},
        )


def test_parent_at_root_cannot_escape_into_projection_context():
    prefix = "opaque:parent-scope"
    store, batch, protocol, builder = _new_builder(prefix)
    parent = builder.expression(prefix + ":parent", "parent")
    field = builder.atom(prefix + ":field", "hidden")
    attempted_escape = builder.expression(
        prefix + ":attempt", "path", (parent, field)
    )
    fallback = builder.literal(prefix + ":fallback", "sealed")
    text = builder.expression(
        prefix + ":text", "fallback", (attempted_escape, fallback)
    )
    template_root = _output_template(builder, prefix, text=text)
    batch.commit()

    rendered = render_view_template(
        store.snapshot(),
        protocol,
        template_root,
        {"hidden": "must-not-escape"},
    )

    assert rendered[0]["text"] == "sealed"
    assert "must-not-escape" not in repr(rendered)


@pytest.mark.parametrize(
    "operation",
    ("map", "find-where", "count-where", "join", "repeat"),
)
def test_non_iterable_collection_inputs_fail_closed(operation: str):
    store, protocol, template_root = _collection_template(operation)

    with pytest.raises(InvalidCell, match="not .*iterable"):
        render_view_template(
            store.snapshot(),
            protocol,
            template_root,
            {"values": 17},
        )


@pytest.mark.parametrize("operation", ("map", "join", "repeat"))
def test_collection_limits_fail_before_unbounded_output(operation: str):
    store, protocol, template_root = _collection_template(operation)

    with pytest.raises(MatchBudgetExceeded):
        render_view_template(
            store.snapshot(),
            protocol,
            template_root,
            {"values": ["a", "b", "c"]},
            repeat_limit=2,
        )


@pytest.mark.parametrize(
    ("operation", "expected"),
    (
        ("map", '["a", "b"]'),
        ("join", "a,b"),
        ("repeat", 2),
    ),
)
def test_collection_limits_admit_the_exact_boundary(
    operation: str,
    expected: str | int,
):
    store, protocol, template_root = _collection_template(operation)

    rendered = render_view_template(
        store.snapshot(),
        protocol,
        template_root,
        {"values": ["a", "b"]},
        repeat_limit=2,
    )

    if operation == "repeat":
        assert len(rendered) == expected
    else:
        assert rendered[0]["text"] == expected


@pytest.mark.parametrize(
    "payload",
    (
        pytest.param({"unsupported"}, id="unsupported-set"),
        pytest.param(float("nan"), id="nan"),
    ),
)
def test_json_rejects_unsupported_and_non_finite_values(payload: object):
    store, protocol, template_root = _json_template()

    with pytest.raises(InvalidCell, match="not serializable"):
        render_view_template(
            store.snapshot(),
            protocol,
            template_root,
            {"payload": payload},
        )


def test_json_size_limit_has_an_exact_utf8_boundary():
    store, protocol, template_root = _json_template()
    snapshot = store.snapshot()

    admitted = render_view_template(
        snapshot,
        protocol,
        template_root,
        {"payload": "x" * 65_534},
    )
    assert len(admitted[0]["text"].encode("utf-8")) == 65_536

    with pytest.raises(MatchBudgetExceeded, match="65536"):
        render_view_template(
            snapshot,
            protocol,
            template_root,
            {"payload": "x" * 65_535},
        )


def test_json_is_deterministic_across_mapping_insertion_order():
    store, protocol, template_root = _json_template()
    snapshot = store.snapshot()
    first = {
        "z": 3,
        "label": "caf\u00e9",
        "a": {"y": 2, "x": 1},
    }
    second = {
        "a": {"x": 1, "y": 2},
        "label": "caf\u00e9",
        "z": 3,
    }

    first_text = render_view_template(
        snapshot, protocol, template_root, {"payload": first}
    )[0]["text"]
    second_text = render_view_template(
        snapshot, protocol, template_root, {"payload": second}
    )[0]["text"]

    assert first_text == second_text
    assert first_text == (
        '{"a": {"x": 1, "y": 2}, '
        '"label": "caf\\u00e9", "z": 3}'
    )


def test_transparent_fragment_role_rewiring_cannot_add_descriptor_fields():
    store, protocol, fragment, _second_marker = _transparent_fragment()
    condition_member = next(
        member
        for member in read_relation(store.snapshot(), fragment, budget=32)
        if member.role_id == protocol.role("condition")
    )
    incidence = store.read(condition_member.incidence_id)
    store.commit(
        store.revision,
        replace=(Cell(
            incidence.id,
            protocol.role("tag"),
            incidence.link1,
            incidence.atom,
        ),),
    )

    assert not is_view_template(store.snapshot(), protocol, fragment)
    with pytest.raises(InvalidCell, match="owns descriptor fields"):
        render_view_template(store.snapshot(), protocol, fragment, {})


def test_transparent_fragment_child_rewiring_cannot_create_recursion():
    store, protocol, fragment, _second_marker = _transparent_fragment()
    child_member = next(
        member
        for member in read_relation(store.snapshot(), fragment, budget=32)
        if member.role_id == protocol.role("child")
    )
    child_wrapper = read_relation(
        store.snapshot(), child_member.participant_id, budget=8
    )
    item_incidence = next(
        member.incidence_id
        for member in child_wrapper
        if member.role_id == protocol.role("item")
    )
    rewire_incidence(store, item_incidence, fragment)

    with pytest.raises(InvalidCell, match="child graph contains a cycle"):
        render_view_template(store.snapshot(), protocol, fragment, {})


def test_malformed_transparent_cardinality_fails_closed():
    store, protocol, fragment, second_marker = _transparent_fragment()
    append_relation_member(
        store,
        fragment,
        protocol.role("transparent"),
        second_marker,
    )

    assert not is_view_template(store.snapshot(), protocol, fragment)
    with pytest.raises(InvalidCell, match="invalid transparent cardinality"):
        render_view_template(store.snapshot(), protocol, fragment, {})
