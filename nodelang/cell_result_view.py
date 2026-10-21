"""Graph-authored presentation for what a node last returned.

A run reaches a host, comes back with rows, and the graph keeps them in
the receipt it signed. Until this template existed there was nowhere to
put them: the canvas could run an operation against a live model and the
person who pressed the button saw a revision number.

The rows are whatever the host answered, so this presents them as they
are -- one line per row, each naming the fields it carries. Nothing here
knows what a workset or a sheet is, and it should not: the shape of the
answer belongs to the host that gave it.
"""
from __future__ import annotations

from .cell_protocols import CellBatch
from .cell_view_template import ViewTemplateBuilder, ViewTemplateProtocol


RESULT_PREFIX = "app:result-template:v1"
RESULT_TEMPLATE_ROOT = RESULT_PREFIX + ":root"
RESULT_TEMPLATE_MEMBER_ROOTS = (
    RESULT_TEMPLATE_ROOT,
    RESULT_PREFIX + ":heading",
    RESULT_PREFIX + ":summary",
    RESULT_PREFIX + ":row",
)


def compose_result_template(
    batch: CellBatch,
    protocol: ViewTemplateProtocol,
) -> str:
    """Compose the last-run presenter as visible graph expressions."""
    builder = ViewTemplateBuilder(batch, protocol)
    prefix = RESULT_PREFIX

    def literal(name: str, value: object) -> str:
        return builder.literal("%s:expression:%s" % (prefix, name), value)

    def segment(name: str) -> str:
        return builder.atom("%s:segment:%s" % (prefix, name), name)

    def expression(name: str, operation: str, *arguments: str) -> str:
        return builder.expression(
            "%s:expression:%s" % (prefix, name), operation, arguments
        )

    def path(name: str, base: str, *segments: str) -> str:
        return expression(name, "path", base, *segments)

    root = expression("root-context", "root")
    item = expression("item-context", "item")
    index = expression("index-context", "index")
    rows = path("rows", root, segment("rows"))
    operation = path("operation", root, segment("operation"))
    row_text = expression("row-text", "string", item)
    row_key = expression(
        "row-key",
        "concat",
        literal("row-key-prefix", "result:row:"),
        expression("index-text", "string", index),
    )
    # A run that returned nothing and a node that has never run are
    # different facts, and the summary is where the difference shows.
    summary = expression(
        "summary",
        "fallback",
        operation,
        literal("never-run", "This node has not run yet."),
    )

    builder.template(
        prefix + ":heading",
        tag=literal("heading-tag", "div"),
        key=literal("heading-key", "result:heading"),
        class_name=literal("heading-class", "inspector-heading"),
        text=literal("heading-text", "LAST RUN"),
    )
    builder.template(
        prefix + ":summary",
        tag=literal("summary-tag", "div"),
        key=literal("summary-key", "result:summary"),
        class_name=literal("summary-class", "result-summary"),
        text=summary,
    )
    builder.template(
        prefix + ":row",
        tag=literal("row-tag", "div"),
        key=row_key,
        class_name=literal("row-class", "result-row"),
        text=row_text,
        repeat=rows,
    )
    builder.template(
        RESULT_TEMPLATE_ROOT,
        tag=literal("root-tag", "section"),
        key=literal("root-key", "result:section"),
        class_name=literal("root-class", "inspector-section"),
        children=(
            prefix + ":heading",
            prefix + ":summary",
            prefix + ":row",
        ),
    )
    return RESULT_TEMPLATE_ROOT


__all__ = [
    "RESULT_PREFIX",
    "RESULT_TEMPLATE_MEMBER_ROOTS",
    "RESULT_TEMPLATE_ROOT",
    "compose_result_template",
]