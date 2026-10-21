"""Graph-authored evidence and physical-floor Properties presenters.

These composers seed visible, rewritable template relations. Runtime projection
is performed only by ``cell_view_template`` from those persisted relations; no
presenter name or product label selects host behavior here.
"""
from __future__ import annotations

from .cell_properties_view import VIEW_TEMPLATE_PREFIX
from .cell_protocols import CellBatch
from .cell_view_template import ViewTemplateBuilder, ViewTemplateProtocol


EVIDENCE_LIST_PREFIX = "app:properties-template:evidence-list:v1"
EVIDENCE_LIST_TEMPLATE_ROOT = EVIDENCE_LIST_PREFIX + ":section"
EVIDENCE_LIST_TEMPLATE_MEMBER_ROOTS = (
    EVIDENCE_LIST_TEMPLATE_ROOT,
    EVIDENCE_LIST_PREFIX + ":heading",
    EVIDENCE_LIST_PREFIX + ":list",
    EVIDENCE_LIST_PREFIX + ":row",
    EVIDENCE_LIST_PREFIX + ":text",
    EVIDENCE_LIST_PREFIX + ":details",
)

PRECELL_INTERACTION_FLOOR_PREFIX = "app:properties-template:cell-floor:v1"
PRECELL_INTERACTION_FLOOR_TEMPLATE_ROOT = (
    PRECELL_INTERACTION_FLOOR_PREFIX + ":section"
)
PRECELL_INTERACTION_FLOOR_TEMPLATE_MEMBER_ROOTS = tuple(
    PRECELL_INTERACTION_FLOOR_PREFIX + ":" + name
    for name in ("section", "heading", "row", "text", "control", "input")
)

CELL_FLOOR_PREFIX = "app:properties-template:cell-floor:v2"
CELL_FLOOR_TEMPLATE_ROOT = CELL_FLOOR_PREFIX + ":section"
CELL_FLOOR_TEMPLATE_MEMBER_ROOTS = (
    CELL_FLOOR_TEMPLATE_ROOT,
    CELL_FLOOR_PREFIX + ":heading",
    CELL_FLOOR_PREFIX + ":row",
    CELL_FLOOR_PREFIX + ":text",
    CELL_FLOOR_PREFIX + ":control",
    CELL_FLOOR_PREFIX + ":input",
)


def compose_evidence_list_template(
    batch: CellBatch,
    protocol: ViewTemplateProtocol,
) -> str:
    """Compose the release-evidence presenter as graph-held relations."""
    builder = ViewTemplateBuilder(batch, protocol)
    prefix = EVIDENCE_LIST_PREFIX

    def literal(name: str, value: object) -> str:
        return builder.literal("%s:expression:%s" % (prefix, name), value)

    def segment(root_name: str, value: str) -> str:
        return builder.atom("%s:segment:%s" % (prefix, root_name), value)

    def path(name: str, base: str, *segments: str) -> str:
        return builder.expression(
            "%s:expression:%s" % (prefix, name),
            "path",
            (base, *segments),
        )

    root_context = builder.expression(
        prefix + ":expression:root-context", "root"
    )
    item_context = builder.expression(
        prefix + ":expression:item-context", "item"
    )
    selected = path(
        "selected", root_context, segment("selected", "selected")
    )
    definition = path(
        "selected-definition",
        root_context,
        segment("selected-definition", "selected_definition"),
    )
    item_key = path(
        "item-key", item_context, segment("item-key", "key")
    )
    item_value = path(
        "item-value", item_context, segment("item-value", "value")
    )
    selected_or_none = builder.expression(
        prefix + ":expression:selected-or-none",
        "fallback",
        (selected, literal("none", "none")),
    )

    is_version = builder.expression(
        prefix + ":expression:is-version",
        "equals",
        (item_key, literal("version-field", "version")),
    )
    is_interfaces = builder.expression(
        prefix + ":expression:is-interfaces",
        "equals",
        (item_key, literal("interfaces-field", "interfaces")),
    )
    is_parts = builder.expression(
        prefix + ":expression:is-parts",
        "equals",
        (item_key, literal("parts-field", "parts")),
    )
    is_evidence_field = builder.expression(
        prefix + ":expression:is-evidence-field",
        "or",
        (is_version, is_interfaces, is_parts),
    )
    slug = builder.expression(
        prefix + ":expression:slug",
        "choose",
        (
            is_version,
            literal("version-slug", "version"),
            builder.expression(
                prefix + ":expression:non-version-slug",
                "choose",
                (
                    is_interfaces,
                    literal("interface-count-slug", "interface-count"),
                    literal("cell-count-slug", "cell-count"),
                ),
            ),
        ),
    )
    label = builder.expression(
        prefix + ":expression:label",
        "choose",
        (
            is_version,
            literal("version-label", "version"),
            builder.expression(
                prefix + ":expression:non-version-label",
                "choose",
                (
                    is_interfaces,
                    literal("interface-count-label", "interface count"),
                    literal("cell-count-label", "cell count"),
                ),
            ),
        ),
    )
    section_key = builder.expression(
        prefix + ":expression:section-key",
        "concat",
        (
            literal("section-key-prefix", "presenter:evidence-list:"),
            selected_or_none,
        ),
    )
    row_key = builder.expression(
        prefix + ":expression:row-key",
        "concat",
        (
            literal("row-key-prefix", "release:"),
            selected_or_none,
            literal("row-key-separator", ":"),
            slug,
        ),
    )
    label_key = builder.expression(
        prefix + ":expression:label-key",
        "concat",
        (row_key, literal("label-key-suffix", ":label")),
    )
    value_key = builder.expression(
        prefix + ":expression:value-key",
        "concat",
        (
            literal("value-key-prefix", "release-value:"),
            selected_or_none,
            literal("value-key-separator", ":"),
            slug,
        ),
    )
    dormant_list = builder.expression(
        prefix + ":expression:dormant-list",
        "equals",
        (literal("dormant-list-left", "0"), literal("dormant-list-right", "1")),
    )

    builder.template(
        prefix + ":heading",
        tag=literal("heading-tag", "div"),
        key=literal("heading-key", "release:heading"),
        class_name=literal("heading-class", "inspector-heading"),
        text=literal("heading-text", "RELEASE"),
    )
    builder.template(
        prefix + ":list",
        tag=literal("list-tag", "div"),
        key=builder.expression(
            prefix + ":expression:list-key",
            "concat",
            (literal("list-key-prefix", "release-list:"), selected_or_none),
        ),
        condition=dormant_list,
    )
    builder.template(
        prefix + ":text",
        tag=literal("text-tag", "span"),
        key=label_key,
        class_name=literal("text-class", "property-label"),
        text=label,
    )
    builder.template(
        prefix + ":details",
        tag=literal("details-tag", "div"),
        key=value_key,
        class_name=literal("details-class", "connection-box"),
        text=item_value,
    )
    builder.template(
        prefix + ":row",
        tag=literal("row-tag", "div"),
        key=row_key,
        class_name=literal("row-class", "property-row"),
        children=(prefix + ":text", prefix + ":details"),
        repeat=definition,
        condition=is_evidence_field,
    )
    builder.template(
        EVIDENCE_LIST_TEMPLATE_ROOT,
        tag=literal("section-tag", "section"),
        key=section_key,
        class_name=literal("section-class", "inspector-section"),
        children=(prefix + ":heading", prefix + ":list", prefix + ":row"),
        condition=definition,
    )
    return EVIDENCE_LIST_TEMPLATE_ROOT


def compose_cell_floor_template(
    batch: CellBatch,
    protocol: ViewTemplateProtocol,
) -> str:
    """Compose the physical Cell presenter as graph-held relations."""
    builder = ViewTemplateBuilder(batch, protocol)
    prefix = CELL_FLOOR_PREFIX

    def literal(name: str, value: object) -> str:
        return builder.literal("%s:expression:%s" % (prefix, name), value)

    def segment(root_name: str, value: str) -> str:
        return builder.atom("%s:segment:%s" % (prefix, root_name), value)

    def path(name: str, base: str, *segments: str) -> str:
        return builder.expression(
            "%s:expression:%s" % (prefix, name),
            "path",
            (base, *segments),
        )

    root_context = builder.expression(
        prefix + ":expression:root-context", "root"
    )
    item_context = builder.expression(
        prefix + ":expression:item-context", "item"
    )
    physical = path(
        "physical", root_context, segment("physical", "physical")
    )
    identity = path(
        "identity", physical, segment("identity", "identity")
    )
    editable = path(
        "editable", physical, segment("editable", "editable")
    )
    control = path(
        "control", physical, segment("control", "control")
    )
    event_fact_input = path(
        "event-fact-input",
        physical,
        segment("event-fact-input", "event_fact_input"),
    )
    item_key = path(
        "item-key", item_context, segment("item-key", "key")
    )
    item_value = path(
        "item-value", item_context, segment("item-value", "value")
    )

    def equals(name: str, value: str) -> str:
        return builder.expression(
            "%s:expression:is-%s" % (prefix, name),
            "equals",
            (item_key, literal("%s-field" % name, value)),
        )

    is_identity = equals("identity", "identity")
    is_link0 = equals("link0", "link0")
    is_link1 = equals("link1", "link1")
    is_atom = equals("atom", "atom")
    is_floor_field = builder.expression(
        prefix + ":expression:is-floor-field",
        "or",
        (is_identity, is_link0, is_link1, is_atom),
    )
    not_atom = builder.expression(
        prefix + ":expression:not-atom", "not", (is_atom,)
    )
    not_editable = builder.expression(
        prefix + ":expression:not-editable", "not", (editable,)
    )
    show_control = builder.expression(
        prefix + ":expression:show-control",
        "or",
        (
            not_atom,
            builder.expression(
                prefix + ":expression:read-only-atom",
                "and",
                (is_atom, not_editable),
            ),
        ),
    )
    show_input = builder.expression(
        prefix + ":expression:show-input",
        "and",
        (is_atom, editable),
    )
    slug = builder.expression(
        prefix + ":expression:slug",
        "choose",
        (
            is_link0,
            literal("link0-slug", "link-0"),
            builder.expression(
                prefix + ":expression:non-link0-slug",
                "choose",
                (is_link1, literal("link1-slug", "link-1"), item_key),
            ),
        ),
    )
    label = builder.expression(
        prefix + ":expression:label",
        "replace",
        (item_key, literal("link-label", "link"), literal("link-space", "link ")),
    )
    normal_row_key = builder.expression(
        prefix + ":expression:normal-row-key",
        "concat",
        (
            literal("normal-row-key-prefix", "floor:"),
            identity,
            literal("normal-row-key-separator", ":"),
            slug,
        ),
    )
    atom_row_key = builder.expression(
        prefix + ":expression:atom-row-key",
        "concat",
        (literal("atom-row-key-prefix", "floor-atom:"), identity),
    )
    row_key = builder.expression(
        prefix + ":expression:row-key",
        "choose",
        (is_atom, atom_row_key, normal_row_key),
    )
    row_tag = builder.expression(
        prefix + ":expression:row-tag",
        "choose",
        (is_atom, literal("label-tag", "label"), literal("div-tag", "div")),
    )
    label_key = builder.expression(
        prefix + ":expression:label-key",
        "concat",
        (row_key, literal("label-key-suffix", ":label")),
    )
    normal_value_key = builder.expression(
        prefix + ":expression:normal-value-key",
        "concat",
        (
            literal("normal-value-key-prefix", "floor-value:"),
            identity,
            literal("normal-value-key-separator", ":"),
            slug,
        ),
    )
    atom_value_key = builder.expression(
        prefix + ":expression:atom-value-key",
        "concat",
        (literal("atom-value-key-prefix", "floor-atom-value:"), identity),
    )
    value_key = builder.expression(
        prefix + ":expression:value-key",
        "choose",
        (is_atom, atom_value_key, normal_value_key),
    )
    atom_falsy = builder.expression(
        prefix + ":expression:atom-falsy", "not", (item_value,)
    )
    atom_truthy = builder.expression(
        prefix + ":expression:atom-truthy", "not", (atom_falsy,)
    )
    atom_or_empty = builder.expression(
        prefix + ":expression:atom-or-empty",
        "choose",
        (atom_truthy, item_value, literal("empty-atom", "empty")),
    )
    value_text = builder.expression(
        prefix + ":expression:value-text",
        "choose",
        (is_atom, atom_or_empty, item_value),
    )
    input_key = builder.expression(
        prefix + ":expression:input-key",
        "concat",
        (literal("input-key-prefix", "floor-atom-input:"), identity),
    )
    section_key = builder.expression(
        prefix + ":expression:section-key",
        "concat",
        (literal("section-key-prefix", "presenter:cell-floor:"), identity),
    )
    summary_key = builder.expression(
        prefix + ":expression:summary-key",
        "concat",
        (literal("summary-key-prefix", "floor-summary:"), identity),
    )

    builder.template(
        prefix + ":heading",
        tag=literal("heading-tag", "summary"),
        key=summary_key,
        class_name=literal("heading-class", "inspector-heading"),
        text=literal("heading-text", "PHYSICAL FLOOR"),
    )
    builder.template(
        prefix + ":text",
        tag=literal("text-tag", "span"),
        key=label_key,
        class_name=literal("text-class", "property-label"),
        text=label,
    )
    builder.template(
        prefix + ":control",
        tag=literal("control-tag", "div"),
        key=value_key,
        class_name=literal("control-class", "connection-box"),
        text=value_text,
        condition=show_control,
    )
    input_type = builder.attribute(
        prefix + ":attribute:input-type",
        "type",
        literal("input-type", "text"),
    )
    control_binding = builder.attribute(
        prefix + ":attribute:control-binding",
        "data-universal-control",
        control,
    )
    event_fact_binding = builder.attribute(
        prefix + ":attribute:event-fact-binding",
        "data-universal-event-fact-input",
        event_fact_input,
    )
    builder.template(
        prefix + ":input",
        tag=literal("input-tag", "input"),
        key=input_key,
        class_name=literal("input-class", "property-input"),
        value=item_value,
        attributes=(input_type, control_binding, event_fact_binding),
        condition=show_input,
    )
    builder.template(
        prefix + ":row",
        tag=row_tag,
        key=row_key,
        class_name=literal("row-class", "property-row"),
        children=(prefix + ":text", prefix + ":control", prefix + ":input"),
        repeat=physical,
        condition=is_floor_field,
    )
    builder.template(
        CELL_FLOOR_TEMPLATE_ROOT,
        tag=literal("section-tag", "details"),
        key=section_key,
        class_name=literal("section-class", "inspector-section"),
        children=(prefix + ":heading", prefix + ":row"),
    )
    return CELL_FLOOR_TEMPLATE_ROOT


__all__ = [
    "CELL_FLOOR_PREFIX",
    "CELL_FLOOR_TEMPLATE_MEMBER_ROOTS",
    "CELL_FLOOR_TEMPLATE_ROOT",
    "PRECELL_INTERACTION_FLOOR_PREFIX",
    "PRECELL_INTERACTION_FLOOR_TEMPLATE_MEMBER_ROOTS",
    "PRECELL_INTERACTION_FLOOR_TEMPLATE_ROOT",
    "EVIDENCE_LIST_PREFIX",
    "EVIDENCE_LIST_TEMPLATE_MEMBER_ROOTS",
    "EVIDENCE_LIST_TEMPLATE_ROOT",
    "VIEW_TEMPLATE_PREFIX",
    "compose_cell_floor_template",
    "compose_evidence_list_template",
]
