"""Graph-authored current-scope heading for the canvas."""
from __future__ import annotations

from .cell_protocols import CellBatch
from .cell_view_template import ViewTemplateBuilder, ViewTemplateProtocol


CANVAS_HEADING_PREFIX = "app:canvas-heading-template:v1"
CANVAS_HEADING_TEMPLATE_ROOT = CANVAS_HEADING_PREFIX + ":heading"
CANVAS_HEADING_TEMPLATE_MEMBER_ROOTS = (CANVAS_HEADING_TEMPLATE_ROOT,)


def compose_canvas_heading_template(
    batch: CellBatch,
    protocol: ViewTemplateProtocol,
) -> str:
    """Compose the visible heading from the exact active scope root."""
    builder = ViewTemplateBuilder(batch, protocol)
    prefix = CANVAS_HEADING_PREFIX

    def literal(name: str, value: object) -> str:
        return builder.literal("%s:expression:%s" % (prefix, name), value)

    def segment(name: str) -> str:
        return builder.atom("%s:segment:%s" % (prefix, name), name)

    def expression(name: str, operation: str, *arguments: str) -> str:
        return builder.expression(
            "%s:expression:%s" % (prefix, name), operation, arguments
        )

    root = expression("root-context", "root")
    scope_root = expression("scope-root", "path", root, segment("root"))
    scope_label = expression("scope-label", "path", root, segment("label"))

    builder.template(
        CANVAS_HEADING_TEMPLATE_ROOT,
        tag=literal("heading-tag", "div"),
        key=literal("heading-key", "canvas:heading"),
        class_name=literal("heading-class", "canvas-heading"),
        text=scope_label,
        attributes=(builder.attribute(
            prefix + ":attribute:scope-root",
            "data-universal-canvas-heading",
            scope_root,
        ),),
    )
    return CANVAS_HEADING_TEMPLATE_ROOT


__all__ = [
    "CANVAS_HEADING_PREFIX",
    "CANVAS_HEADING_TEMPLATE_MEMBER_ROOTS",
    "CANVAS_HEADING_TEMPLATE_ROOT",
    "compose_canvas_heading_template",
]
