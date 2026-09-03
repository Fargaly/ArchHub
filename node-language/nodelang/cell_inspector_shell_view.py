"""Graph-authored shell and tab panels for the Properties inspector."""
from __future__ import annotations

from .cell_protocols import CellBatch
from .cell_view_template import ViewTemplateBuilder, ViewTemplateProtocol


INSPECTOR_SHELL_PREFIX = "app:inspector-shell-template:v1"
INSPECTOR_SHELL_TEMPLATE_ROOT = INSPECTOR_SHELL_PREFIX + ":shell"
INSPECTOR_SHELL_TEMPLATE_MEMBER_ROOTS = (
    INSPECTOR_SHELL_TEMPLATE_ROOT,
    INSPECTOR_SHELL_PREFIX + ":tabpanel",
)


def compose_inspector_shell_template(
    batch: CellBatch,
    protocol: ViewTemplateProtocol,
) -> str:
    """Compose the inspector frame and its accessible panels from graph facts."""
    builder = ViewTemplateBuilder(batch, protocol)
    prefix = INSPECTOR_SHELL_PREFIX
    segments: dict[str, str] = {}

    def literal(name: str, value: object) -> str:
        return builder.literal("%s:expression:%s" % (prefix, name), value)

    def segment(name: str) -> str:
        cached = segments.get(name)
        if cached is None:
            cached = builder.atom("%s:segment:%s" % (prefix, name), name)
            segments[name] = cached
        return cached

    def expression(name: str, operation: str, *arguments: str) -> str:
        return builder.expression(
            "%s:expression:%s" % (prefix, name), operation, arguments
        )

    def path(name: str, base: str, *segments: str) -> str:
        return expression(name, "path", base, *segments)

    root = expression("root-context", "root")
    item = expression("item-context", "item")
    selected = path("selected", root, segment("selected"))
    panels = path("panels", root, segment("panels"))
    panel_root = path("panel-root", item, segment("id"))
    panel_key = path("panel-key", item, segment("key"))
    panel_id = path("panel-id", item, segment("panel_id"))
    tab_id = path("tab-id", item, segment("tab_id"))
    active = path("active", item, segment("active"))

    builder.template(
        prefix + ":tabpanel",
        tag=literal("tabpanel-tag", "div"),
        key=panel_key,
        class_name=literal("tabpanel-class", "inspector-tabpanel"),
        attributes=(
            builder.attribute(
                prefix + ":attribute:tabpanel-root",
                "data-inspector-tabpanel",
                panel_root,
            ),
            builder.attribute(
                prefix + ":attribute:tabpanel-id", "id", panel_id
            ),
            builder.attribute(
                prefix + ":attribute:tabpanel-role", "role",
                literal("tabpanel-role", "tabpanel"),
            ),
            builder.attribute(
                prefix + ":attribute:tabpanel-labelledby",
                "aria-labelledby",
                tab_id,
            ),
            builder.attribute(
                prefix + ":attribute:tabpanel-tabindex", "tabindex",
                literal("tabpanel-tabindex", 0),
            ),
            builder.attribute(
                prefix + ":attribute:tabpanel-hidden", "hidden",
                expression("tabpanel-hidden", "not", active),
            ),
        ),
        repeat=panels,
    )
    builder.template(
        INSPECTOR_SHELL_TEMPLATE_ROOT,
        tag=literal("shell-tag", "section"),
        key=literal("shell-key", "inspector:root"),
        class_name=literal("shell-class", "inspector-panel"),
        attributes=(
            builder.attribute(
                prefix + ":attribute:shell-visible",
                "data-visible",
                literal("shell-visible", "True"),
            ),
            builder.attribute(
                prefix + ":attribute:shell-selection",
                "data-inspected-node",
                selected,
            ),
        ),
        children=(prefix + ":tabpanel",),
    )
    return INSPECTOR_SHELL_TEMPLATE_ROOT


__all__ = [
    "INSPECTOR_SHELL_PREFIX",
    "INSPECTOR_SHELL_TEMPLATE_MEMBER_ROOTS",
    "INSPECTOR_SHELL_TEMPLATE_ROOT",
    "compose_inspector_shell_template",
]
