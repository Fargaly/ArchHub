"""Graph-authored catalogue section in the Node Library."""
from __future__ import annotations

from .cell_protocols import CellBatch
from .cell_view_template import ViewTemplateBuilder, ViewTemplateProtocol


LIBRARY_SECTION_PREFIX = "app:library-section-template:v1"
LIBRARY_SECTION_TEMPLATE_ROOT = LIBRARY_SECTION_PREFIX + ":section"
LIBRARY_SECTION_TEMPLATE_MEMBER_ROOTS = (
    LIBRARY_SECTION_TEMPLATE_ROOT,
    LIBRARY_SECTION_PREFIX + ":label",
)


def compose_library_section_template(
    batch: CellBatch,
    protocol: ViewTemplateProtocol,
) -> str:
    """Compose one visible section from graph-held catalogue facts."""
    builder = ViewTemplateBuilder(batch, protocol)
    prefix = LIBRARY_SECTION_PREFIX

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
    identity = path("identity", root, segment("id"))
    label = path("label", root, segment("label"))

    def key(name: str) -> str:
        return expression(
            "%s-key" % name,
            "concat",
            literal("%s-key-prefix" % name, "library:%s:" % name),
            identity,
        )

    builder.template(
        prefix + ":label",
        tag=literal("label-tag", "div"),
        key=key("section-label"),
        class_name=literal("label-class", "universal-library-section"),
        text=label,
    )
    builder.template(
        LIBRARY_SECTION_TEMPLATE_ROOT,
        tag=literal("section-tag", "section"),
        key=key("section"),
        class_name=literal("section-class", "universal-library-group"),
        attributes=(builder.attribute(
            prefix + ":attribute:section-root",
            "data-universal-library-section",
            identity,
        ),),
        children=(prefix + ":label",),
    )
    return LIBRARY_SECTION_TEMPLATE_ROOT


__all__ = [
    "LIBRARY_SECTION_PREFIX",
    "LIBRARY_SECTION_TEMPLATE_MEMBER_ROOTS",
    "LIBRARY_SECTION_TEMPLATE_ROOT",
    "compose_library_section_template",
]
