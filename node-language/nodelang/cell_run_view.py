"""Graph-authored presentation for running the selected node.

Every other inspector tab in this build lists something the graph already
holds. This one offers an action, and it is the reason the Run tab stood
empty: there was no template that put a control in front of a person, so
the tab existed, declared itself, and rendered nothing.

The control names the node it belongs to and nothing else. Which
operation that node runs is read from the graph when the button is
pressed -- naming a node is not naming an operation -- so this template
cannot widen what a caller is able to run.
"""
from __future__ import annotations

from .cell_protocols import CellBatch
from .cell_view_template import ViewTemplateBuilder, ViewTemplateProtocol


RUN_PREFIX = "app:run-template:v1"
RUN_TEMPLATE_ROOT = RUN_PREFIX + ":root"
RUN_TEMPLATE_MEMBER_ROOTS = (
    RUN_TEMPLATE_ROOT,
    RUN_PREFIX + ":heading",
    RUN_PREFIX + ":operation",
    RUN_PREFIX + ":button",
)


def compose_run_template(
    batch: CellBatch,
    protocol: ViewTemplateProtocol,
) -> str:
    """Compose the run control as visible graph expressions."""
    builder = ViewTemplateBuilder(batch, protocol)
    prefix = RUN_PREFIX

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

    def attribute(name: str, attribute_name: str, value: str) -> str:
        return builder.attribute(
            "%s:attribute:%s" % (prefix, name), attribute_name, value
        )

    root = expression("root-context", "root")
    selected = path("selected", root, segment("selected"))
    operation = path("operation", root, segment("operation"))
    # A node that declares no operation has nothing to run, and the label
    # says so rather than offering a button that would be refused.
    operation_text = expression(
        "operation-text",
        "fallback",
        operation,
        literal("no-operation", "This node declares no operation."),
    )

    builder.template(
        prefix + ":heading",
        tag=literal("heading-tag", "div"),
        key=literal("heading-key", "run:heading"),
        class_name=literal("heading-class", "inspector-heading"),
        text=literal("heading-text", "RUN"),
    )
    builder.template(
        prefix + ":operation",
        tag=literal("operation-tag", "div"),
        key=literal("operation-key", "run:operation"),
        class_name=literal("operation-class", "run-operation"),
        text=operation_text,
    )
    builder.template(
        prefix + ":button",
        tag=literal("button-tag", "button"),
        key=literal("button-key", "run:button"),
        class_name=literal("button-class", "run-button"),
        attributes=(
            attribute("button-type", "type", literal("type-button", "button")),
            # The client finds a run control by this attribute and sends
            # the node under it. Both carry the same identity so the
            # request can name nothing the projection did not show.
            attribute(
                "adapter-execute", "data-universal-adapter-execute", selected
            ),
            attribute("adapter-root", "data-root", selected),
        ),
        text=literal("button-text", "Run"),
    )
    builder.template(
        RUN_TEMPLATE_ROOT,
        tag=literal("root-tag", "section"),
        key=literal("root-key", "run:section"),
        class_name=literal("root-class", "inspector-section"),
        children=(
            prefix + ":heading",
            prefix + ":operation",
            prefix + ":button",
        ),
    )
    return RUN_TEMPLATE_ROOT


__all__ = [
    "RUN_PREFIX",
    "RUN_TEMPLATE_MEMBER_ROOTS",
    "RUN_TEMPLATE_ROOT",
    "compose_run_template",
]