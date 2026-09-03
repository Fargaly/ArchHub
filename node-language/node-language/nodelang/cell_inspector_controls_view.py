"""Graph-authored inspector lens and Properties tab controls."""
from __future__ import annotations

from .cell_protocols import CellBatch
from .cell_view_template import ViewTemplateBuilder, ViewTemplateProtocol


INSPECTOR_CONTROLS_PREFIX = "app:inspector-controls-template:v1"
INSPECTOR_CONTROLS_TEMPLATE_ROOT = INSPECTOR_CONTROLS_PREFIX + ":root"
INSPECTOR_CONTROLS_TEMPLATE_MEMBER_ROOTS = (
    INSPECTOR_CONTROLS_TEMPLATE_ROOT,
    INSPECTOR_CONTROLS_PREFIX + ":lenses",
    INSPECTOR_CONTROLS_PREFIX + ":lens",
    INSPECTOR_CONTROLS_PREFIX + ":tabs",
    INSPECTOR_CONTROLS_PREFIX + ":tab",
)


def compose_inspector_controls_template(
    batch: CellBatch,
    protocol: ViewTemplateProtocol,
) -> str:
    """Compose progressive lenses and applicable Properties tabs as graph UI."""
    builder = ViewTemplateBuilder(batch, protocol)
    prefix = INSPECTOR_CONTROLS_PREFIX

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
    item = expression("item-context", "item")
    index = expression("item-index", "index")
    inspector = path("inspector", root, segment("inspector"))
    lenses = path("lenses", inspector, segment("lenses"))
    presentation = path(
        "presentation", inspector, segment("presentation")
    )
    panels = path("panels", presentation, segment("panels"))
    identity = path("item-id", item, segment("id"))
    label = path("item-label", item, segment("label"))
    active = path("item-active", item, segment("active"))

    lens_key = expression(
        "lens-key", "concat", literal("lens-key-prefix", "inspector-lens:"),
        identity,
    )
    tab_key = expression(
        "tab-key", "concat", literal("tab-key-prefix", "inspector-tab:"),
        identity,
    )
    tab_id = expression(
        "tab-id", "concat", literal("tab-id-prefix", "inspector-tab-"),
        index,
    )
    panel_id = expression(
        "panel-id", "concat",
        literal("panel-id-prefix", "inspector-panel-"), index,
    )
    tab_index = expression(
        "tab-index", "choose", active,
        literal("active-tab-index", 0), literal("inactive-tab-index", -1),
    )

    lens_attributes = (
        builder.attribute(
            prefix + ":attribute:lens-type", "type",
            literal("lens-type", "button"),
        ),
        builder.attribute(
            prefix + ":attribute:lens-root",
            "data-universal-inspector-lens", identity,
        ),
        builder.attribute(
            prefix + ":attribute:lens-active", "data-active", active,
        ),
        builder.attribute(
            prefix + ":attribute:lens-pressed", "aria-pressed", active,
        ),
    )
    tab_attributes = (
        builder.attribute(
            prefix + ":attribute:tab-type", "type",
            literal("tab-type", "button"),
        ),
        builder.attribute(
            prefix + ":attribute:tab-role", "role",
            literal("tab-role", "tab"),
        ),
        builder.attribute(
            prefix + ":attribute:tab-id", "id", tab_id,
        ),
        builder.attribute(
            prefix + ":attribute:tab-selected", "aria-selected", active,
        ),
        builder.attribute(
            prefix + ":attribute:tab-controls", "aria-controls", panel_id,
        ),
        builder.attribute(
            prefix + ":attribute:tab-index", "tabindex", tab_index,
        ),
        builder.attribute(
            prefix + ":attribute:tab-active", "data-active", active,
        ),
        builder.attribute(
            prefix + ":attribute:tab-root",
            "data-universal-properties-panel", identity,
        ),
    )

    builder.template(
        prefix + ":lens",
        tag=literal("lens-tag", "button"),
        key=lens_key,
        class_name=literal("lens-class", "inspector-lens-button"),
        text=label,
        attributes=lens_attributes,
        repeat=lenses,
    )
    builder.template(
        prefix + ":lenses",
        tag=literal("lenses-tag", "div"),
        key=literal("lenses-key", "inspector:lenses"),
        class_name=literal("lenses-class", "inspector-lenses"),
        attributes=(builder.attribute(
            prefix + ":attribute:lenses-label", "aria-label",
            literal("lenses-label", "Visibility level"),
        ),),
        children=(prefix + ":lens",),
    )
    builder.template(
        prefix + ":tab",
        tag=literal("tab-tag", "button"),
        key=tab_key,
        class_name=literal("tab-class", "inspector-tab"),
        text=label,
        attributes=tab_attributes,
        repeat=panels,
    )
    builder.template(
        prefix + ":tabs",
        tag=literal("tabs-tag", "div"),
        key=literal("tabs-key", "inspector:tabs"),
        class_name=literal("tabs-class", "inspector-tabs"),
        attributes=(
            builder.attribute(
                prefix + ":attribute:tabs-role", "role",
                literal("tabs-role", "tablist"),
            ),
            builder.attribute(
                prefix + ":attribute:tabs-label", "aria-label",
                literal("tabs-label", "Properties panels"),
            ),
        ),
        children=(prefix + ":tab",),
    )
    builder.template(
        INSPECTOR_CONTROLS_TEMPLATE_ROOT,
        tag=None,
        key=None,
        children=(prefix + ":lenses", prefix + ":tabs"),
        transparent=literal("transparent", True),
    )
    return INSPECTOR_CONTROLS_TEMPLATE_ROOT


__all__ = [
    "INSPECTOR_CONTROLS_PREFIX",
    "INSPECTOR_CONTROLS_TEMPLATE_MEMBER_ROOTS",
    "INSPECTOR_CONTROLS_TEMPLATE_ROOT",
    "compose_inspector_controls_template",
]
