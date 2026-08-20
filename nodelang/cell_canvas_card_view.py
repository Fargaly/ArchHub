"""Graph-authored canvas card presentation.

The persisted template decides how a visible root is named and summarized.
The browser only interprets the resulting keyed descriptors and owns no
product category dispatch.
"""
from __future__ import annotations

from .cell_protocols import CellBatch
from .cell_view_template import ViewTemplateBuilder, ViewTemplateProtocol


LEGACY_CANVAS_CARD_PREFIX = "app:canvas-card-template:v1"
CANVAS_CARD_PREFIX = "app:canvas-card-template:v2"
CANVAS_CARD_TEMPLATE_ROOT = CANVAS_CARD_PREFIX + ":card"
CANVAS_CARD_TEMPLATE_MEMBER_ROOTS = (
    CANVAS_CARD_TEMPLATE_ROOT,
    CANVAS_CARD_PREFIX + ":accent",
    CANVAS_CARD_PREFIX + ":head",
    CANVAS_CARD_PREFIX + ":title",
    CANVAS_CARD_PREFIX + ":summary",
    CANVAS_CARD_PREFIX + ":value",
    CANVAS_CARD_PREFIX + ":ports",
)


def compose_canvas_card_template(
    batch: CellBatch,
    protocol: ViewTemplateProtocol,
) -> str:
    """Compose the standard canvas card as visible graph expressions."""
    builder = ViewTemplateBuilder(batch, protocol)
    prefix = CANVAS_CARD_PREFIX

    def literal(name: str, value: object) -> str:
        return builder.literal("%s:expression:%s" % (prefix, name), value)

    def segment(name: str) -> str:
        return builder.atom("%s:segment:%s" % (prefix, name), name)

    def expression(name: str, operation: str, *arguments: str) -> str:
        return builder.expression(
            "%s:expression:%s" % (prefix, name),
            operation,
            arguments,
        )

    def path(name: str, base: str, *segments: str) -> str:
        return expression(name, "path", base, *segments)

    root = expression("root-context", "root")
    identity = path("identity", root, segment("id"))
    label = path("label", root, segment("label"))
    assembly = path("assembly", root, segment("assembly"))
    composition = path("composition", root, segment("composition"))
    openable = path("openable", root, segment("openable"))
    member_count = path("member-count", root, segment("member_count"))
    connection_count = path(
        "connection-count", root, segment("connection_count")
    )
    false_value = literal("false", False)
    assembly_present = expression(
        "assembly-present", "fallback", assembly, false_value
    )
    # What the graph says this node IS, what state it is in, and what it
    # says about itself. Read from the projection, which reads them from
    # the definition name and the node's own properties. Absent -> False,
    # so the chooser below can fall through to the structural words.
    # Presence is length(): a literal False is an atom, and an atom's text
    # is never empty, so fallback(x, False) is always truthy here. length
    # of "" is 0, which is the only false the engine's choose respects.
    kind = path("kind", root, segment("kind"))
    category = path("category", root, segment("category"))
    kind_present = expression("kind-present", "length", kind)
    status = path("status", root, segment("status"))
    status_present = expression("status-present", "length", status)
    summary = path("summary", root, segment("summary"))
    summary_present = expression("summary-present", "length", summary)
    assembly_version = path(
        "assembly-version", assembly, segment("version")
    )
    assembly_interfaces = path(
        "assembly-interfaces", assembly, segment("interfaces")
    )
    assembly_interface_count = expression(
        "assembly-interface-count", "length", assembly_interfaces
    )

    # The head names the kind of thing: the definition's own name when the
    # node was made from one ("Domain composition", "Requirement"), else
    # the structural word. "ASSEMBLY / v" told the founder nothing.
    category_present = expression("category-present", "length", category)
    head = expression(
        "head",
        "choose",
        category_present,
        category,
        expression(
        "head-kind",
        "choose",
        kind_present,
        kind,
        expression(
            "non-assembly-head",
            "choose",
            composition,
            literal("composition-label", "Composition"),
            expression(
                "non-composition-head",
                "choose",
                openable,
                literal("relation-label", "Relation"),
                literal("cell-label", "Cell"),
            ),
        ),
        ),
    )
    assembly_value = expression(
        "assembly-value",
        "concat",
        member_count,
        literal("assembly-cells", " cells  /  "),
        assembly_interface_count,
        literal("assembly-interface", " interface"),
    )
    cell_value = expression(
        "cell-value",
        "concat",
        member_count,
        literal("cell-nodes", " nodes  /  "),
        connection_count,
        literal("cell-relations", " relations"),
    )
    # The value line is the node's state when it declares one; a scope
    # that opens says so; everything else keeps its structural count.
    value = expression(
        "value",
        "choose",
        status_present,
        status,
        expression(
            "value-without-status",
            "choose",
            openable,
            literal("open-hint", "Double-click to open"),
            expression(
                "value-structural", "choose",
                assembly_present, assembly_value, cell_value,
            ),
        ),
    )
    accessibility_label = expression(
        "accessibility-label",
        "concat",
        label,
        literal("accessibility-separator", ". "),
        connection_count,
        literal("accessibility-relations", " relations"),
    )

    def keyed_value(name: str) -> str:
        return expression(
            "%s-key" % name,
            "concat",
            literal("%s-key-prefix" % name, "canvas:node:"),
            identity,
            literal("%s-key-suffix" % name, ":%s" % name),
        )

    builder.template(
        prefix + ":accent",
        tag=literal("accent-tag", "div"),
        key=keyed_value("accent"),
        class_name=literal("accent-class", "node-accent"),
    )

    builder.template(
        prefix + ":head",
        tag=literal("head-tag", "div"),
        key=keyed_value("head"),
        class_name=literal("head-class", "node-head"),
        text=head,
    )
    builder.template(
        prefix + ":title",
        tag=literal("title-tag", "div"),
        key=keyed_value("title"),
        class_name=literal("title-class", "node-title"),
        text=label,
    )
    builder.template(
        prefix + ":summary",
        tag=literal("summary-tag", "div"),
        key=keyed_value("summary"),
        class_name=literal("summary-class", "node-summary"),
        text=summary,
        condition=summary_present,
    )
    builder.template(
        prefix + ":value",
        tag=literal("value-tag", "div"),
        key=keyed_value("value"),
        class_name=literal("value-class", "node-value"),
        text=value,
    )
    builder.template(
        prefix + ":ports",
        tag=literal("ports-tag", "div"),
        key=keyed_value("ports"),
        class_name=literal("ports-class", "node-ports"),
    )
    builder.template(
        CANVAS_CARD_TEMPLATE_ROOT,
        tag=literal("card-tag", "div"),
        key=expression(
            "card-key", "concat",
            literal("card-key-prefix", "canvas:node:"), identity,
        ),
        class_name=literal(
            "card-class", "graph-node universal-graph-node"
        ),
        attributes=(
            builder.attribute(
                prefix + ":attribute:card-role", "role",
                literal("card-role", "button"),
            ),
            builder.attribute(
                prefix + ":attribute:card-tabindex", "tabindex",
                literal("card-tabindex", 0),
            ),
            builder.attribute(
                prefix + ":attribute:card-label", "aria-label",
                accessibility_label,
            ),
            builder.attribute(
                prefix + ":attribute:card-category", "data-node-category",
                category,
            ),
        ),
        children=(
            prefix + ":accent",
            prefix + ":head",
            prefix + ":title",
            prefix + ":summary",
            prefix + ":value",
            prefix + ":ports",
        ),
    )
    return CANVAS_CARD_TEMPLATE_ROOT


__all__ = [
    "CANVAS_CARD_PREFIX",
    "CANVAS_CARD_TEMPLATE_MEMBER_ROOTS",
    "CANVAS_CARD_TEMPLATE_ROOT",
    "LEGACY_CANVAS_CARD_PREFIX",
    "compose_canvas_card_template",
]
