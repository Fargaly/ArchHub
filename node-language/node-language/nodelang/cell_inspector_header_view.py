"""Graph-authored inspector header presentation.

The browser interprets this persisted template through cell_view_template.
Selection semantics therefore remain graph data instead of a JavaScript
category dispatch.
"""
from __future__ import annotations

from .cell_protocols import CellBatch
from .cell_view_template import ViewTemplateBuilder, ViewTemplateProtocol


INSPECTOR_HEADER_PREFIX = "app:inspector-header-template:v1"
INSPECTOR_HEADER_TEMPLATE_ROOT = INSPECTOR_HEADER_PREFIX + ":root"
INSPECTOR_HEADER_TEMPLATE_MEMBER_ROOTS = (
    INSPECTOR_HEADER_TEMPLATE_ROOT,
    INSPECTOR_HEADER_PREFIX + ":kicker",
    INSPECTOR_HEADER_PREFIX + ":title",
)


def compose_inspector_header_template(
    batch: CellBatch,
    protocol: ViewTemplateProtocol,
) -> str:
    """Compose the selected-subject header as visible graph expressions."""
    builder = ViewTemplateBuilder(batch, protocol)
    prefix = INSPECTOR_HEADER_PREFIX

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
    selected_relation = path(
        "selected-relation", root, segment("selected_relation")
    )
    selected_definition = path(
        "selected-definition", root, segment("selected_definition")
    )
    selected_assembly = path(
        "selected-assembly", root, segment("selected_assembly")
    )
    physical = path("physical", root, segment("physical"))
    physical_editable = path(
        "physical-editable", physical, segment("editable")
    )
    connection_count = path(
        "connection-count", root, segment("connection_count")
    )
    selected_title = path(
        "selected-title", root, segment("selected_title")
    )
    false_value = literal("false", False)

    def present(name: str, value: str) -> str:
        return expression(name, "fallback", value, false_value)

    kicker = expression(
        "kicker",
        "choose",
        present("relation-present", selected_relation),
        literal("relation-label", "RELATION NODE"),
        expression(
            "non-relation-kicker",
            "choose",
            present("physical-editable-present", physical_editable),
            literal("stem-label", "STEM CELL"),
            expression(
                "non-physical-kicker",
                "choose",
                present("definition-present", selected_definition),
                literal("definition-label", "LIBRARY DEFINITION"),
                expression(
                    "non-definition-kicker",
                    "choose",
                    present("assembly-present", selected_assembly),
                    literal("assembly-label", "ASSEMBLY INSTANCE"),
                    expression(
                        "cell-kicker",
                        "choose",
                        present("connections-present", connection_count),
                        literal("connected-cell-label", "RELATION CELL"),
                        literal("cell-label", "UNIVERSAL CELL"),
                    ),
                ),
            ),
        ),
    )

    builder.template(
        prefix + ":kicker",
        tag=literal("kicker-tag", "div"),
        key=literal("kicker-key", "inspector:kicker"),
        class_name=literal("kicker-class", "inspector-kicker"),
        text=kicker,
    )
    builder.template(
        prefix + ":title",
        tag=literal("title-tag", "div"),
        key=literal("title-key", "inspector:title"),
        class_name=literal("title-class", "inspector-title"),
        text=selected_title,
    )
    builder.template(
        INSPECTOR_HEADER_TEMPLATE_ROOT,
        tag=literal("root-tag", "div"),
        key=literal("root-key", "inspector:header"),
        class_name=literal("root-class", "inspector-header"),
        children=(
            prefix + ":kicker",
            prefix + ":title",
        ),
    )
    return INSPECTOR_HEADER_TEMPLATE_ROOT


__all__ = [
    "INSPECTOR_HEADER_PREFIX",
    "INSPECTOR_HEADER_TEMPLATE_MEMBER_ROOTS",
    "INSPECTOR_HEADER_TEMPLATE_ROOT",
    "compose_inspector_header_template",
]
