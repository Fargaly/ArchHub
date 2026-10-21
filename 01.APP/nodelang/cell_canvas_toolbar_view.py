"""Graph-authored controls, scope, and status for the canvas toolbar."""
from __future__ import annotations

from .cell_control_bindings import (
    CAPABILITY_COMPOSITION,
    CAPABILITY_HISTORY,
    CAPABILITY_SCOPE,
    CAPABILITY_VIEWPORT,
)
from .cell_protocols import CellBatch
from .cell_view_template import ViewTemplateBuilder, ViewTemplateProtocol


CANVAS_TOOLBAR_PREFIX = "app:canvas-toolbar-template:v2"
CANVAS_TOOLBAR_TEMPLATE_ROOT = CANVAS_TOOLBAR_PREFIX + ":surface"
CANVAS_TOOLBAR_TEMPLATE_MEMBER_ROOTS = (
    CANVAS_TOOLBAR_TEMPLATE_ROOT,
    CANVAS_TOOLBAR_PREFIX + ":scope",
    CANVAS_TOOLBAR_PREFIX + ":scope-control",
    CANVAS_TOOLBAR_PREFIX + ":trail-item",
    CANVAS_TOOLBAR_PREFIX + ":divider",
    CANVAS_TOOLBAR_PREFIX + ":current",
    CANVAS_TOOLBAR_PREFIX + ":crumb",
    CANVAS_TOOLBAR_PREFIX + ":control-item",
    CANVAS_TOOLBAR_PREFIX + ":viewport-control",
    CANVAS_TOOLBAR_PREFIX + ":history-control",
    CANVAS_TOOLBAR_PREFIX + ":semantic-control",
    CANVAS_TOOLBAR_PREFIX + ":zoom",
    CANVAS_TOOLBAR_PREFIX + ":selection",
    CANVAS_TOOLBAR_PREFIX + ":selection-fallback",
)


def compose_canvas_toolbar_template(
    batch: CellBatch,
    protocol: ViewTemplateProtocol,
) -> str:
    """Compose the complete toolbar from graph-projected control facts."""
    builder = ViewTemplateBuilder(batch, protocol)
    prefix = CANVAS_TOOLBAR_PREFIX
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

    def path(name: str, base: str, *path_segments: str) -> str:
        return expression(name, "path", base, *path_segments)

    root = expression("root-context", "root")
    item = expression("item-context", "item")
    controls = path("controls", root, segment("controls"))
    trail = path("trail", root, segment("trail"))
    zoom_percent = path("zoom-percent", root, segment("zoom_percent"))
    selection_count = path(
        "selection-count", root, segment("selection_count")
    )
    owner = path("control-owner", item, segment("owner"))
    title = path("control-title", item, segment("title"))
    icon = path("control-icon", item, segment("icon"))
    activation_binding = path(
        "control-binding", item, segment("activation"), segment("binding")
    )
    activation_capability = path(
        "control-capability",
        item,
        segment("activation"),
        segment("capability"),
    )
    activation_operation = path(
        "control-operation",
        item,
        segment("activation"),
        segment("arguments"),
        segment("operation"),
    )
    activation_amount = path(
        "control-amount",
        item,
        segment("activation"),
        segment("arguments"),
        segment("amount"),
    )
    is_scope = expression(
        "is-scope",
        "equals",
        activation_capability,
        literal("scope-capability", CAPABILITY_SCOPE),
    )
    is_viewport = expression(
        "is-viewport",
        "equals",
        activation_capability,
        literal("viewport-capability", CAPABILITY_VIEWPORT),
    )
    is_history = expression(
        "is-history",
        "equals",
        activation_capability,
        literal("history-capability", CAPABILITY_HISTORY),
    )
    is_composition = expression(
        "is-composition",
        "equals",
        activation_capability,
        literal("composition-capability", CAPABILITY_COMPOSITION),
    )
    is_other_semantic = expression(
        "is-other-semantic",
        "and",
        expression("not-scope", "not", is_scope),
        expression("not-viewport", "not", is_viewport),
        expression("not-history", "not", is_history),
    )
    is_zoom_out = expression(
        "is-zoom-out",
        "and",
        is_viewport,
        expression(
            "is-delta",
            "equals",
            activation_operation,
            literal("delta-operation", "delta"),
        ),
        expression(
            "is-negative-delta",
            "equals",
            activation_amount,
            literal("negative-delta", "-0.1"),
        ),
    )
    has_composition = expression(
        "has-composition",
        "count-where",
        controls,
        is_composition,
    )
    no_composition = expression(
        "no-composition", "not", has_composition
    )
    trail_root = path("trail-root", item, segment("root"))
    trail_label = path("trail-label", item, segment("label"))
    trail_key = path("trail-key", item, segment("key"))
    current = path("trail-current", item, segment("current"))
    show_divider = path(
        "trail-show-divider", item, segment("show_divider")
    )

    def item_key(name: str) -> str:
        return expression(
            "%s-key" % name,
            "concat",
            trail_key,
            literal("%s-key-suffix" % name, ":%s" % name),
        )

    control_key = expression(
        "control-key",
        "concat",
        literal("control-key-prefix", "toolbar:control:"),
        owner,
    )

    def control_attributes(name: str, *extra: str) -> tuple[str, ...]:
        return (
            builder.attribute(
                "%s:attribute:%s:type" % (prefix, name),
                "type",
                literal("%s-type" % name, "button"),
            ),
            builder.attribute(
                "%s:attribute:%s:owner" % (prefix, name),
                "data-universal-control",
                owner,
            ),
            builder.attribute(
                "%s:attribute:%s:binding" % (prefix, name),
                "data-control-binding",
                activation_binding,
            ),
            builder.attribute(
                "%s:attribute:%s:capability" % (prefix, name),
                "data-control-capability",
                activation_capability,
            ),
            builder.attribute(
                "%s:attribute:%s:icon" % (prefix, name),
                "data-control-icon",
                icon,
            ),
            builder.attribute(
                "%s:attribute:%s:title" % (prefix, name), "title", title
            ),
            builder.attribute(
                "%s:attribute:%s:aria" % (prefix, name),
                "aria-label",
                title,
            ),
            *extra,
        )

    builder.template(
        prefix + ":divider",
        tag=literal("divider-tag", "span"),
        key=item_key("divider"),
        class_name=literal("divider-class", "canvas-scope-divider"),
        text=literal("divider-text", "/"),
        condition=show_divider,
    )
    builder.template(
        prefix + ":current",
        tag=literal("current-tag", "span"),
        key=item_key("current"),
        class_name=literal("current-class", "canvas-scope-current"),
        text=trail_label,
        condition=current,
    )
    builder.template(
        prefix + ":crumb",
        tag=literal("crumb-tag", "button"),
        key=item_key("crumb"),
        class_name=literal("crumb-class", "canvas-scope-button"),
        text=trail_label,
        attributes=(
            builder.attribute(
                prefix + ":attribute:crumb-type", "type",
                literal("crumb-type", "button"),
            ),
            builder.attribute(
                prefix + ":attribute:crumb-root",
                "data-universal-scope",
                trail_root,
            ),
        ),
        condition=expression("crumb-visible", "not", current),
    )
    builder.template(
        prefix + ":trail-item",
        tag=literal("trail-item-tag", "span"),
        key=trail_key,
        class_name=literal("trail-item-class", "canvas-scope-item"),
        children=(
            prefix + ":divider",
            prefix + ":current",
            prefix + ":crumb",
        ),
        repeat=trail,
    )
    builder.template(
        prefix + ":scope-control",
        tag=literal("scope-control-tag", "button"),
        key=control_key,
        class_name=literal(
            "scope-control-class", "header-action icon-only"
        ),
        attributes=control_attributes("scope-control"),
        condition=is_scope,
        repeat=controls,
    )
    builder.template(
        prefix + ":scope",
        tag=literal("scope-tag", "div"),
        key=literal("scope-key", "toolbar:scope"),
        class_name=literal("scope-class", "canvas-scope-trail"),
        attributes=(builder.attribute(
            prefix + ":attribute:scope-root",
            "data-universal-toolbar-scope",
            literal("scope-present", "True"),
        ),),
        children=(prefix + ":scope-control", prefix + ":trail-item"),
    )
    zoom_mode = expression(
        "zoom-mode",
        "choose",
        expression(
            "is-fit",
            "equals",
            activation_operation,
            literal("fit-operation", "fit"),
        ),
        literal("fit-mode", "fit"),
        expression(
            "zoom-direction",
            "choose",
            expression(
                "is-positive-delta",
                "equals",
                activation_amount,
                literal("positive-delta", "0.1"),
            ),
            literal("zoom-in-mode", "in"),
            literal("zoom-out-mode", "out"),
        ),
    )
    viewport_attribute = builder.attribute(
        prefix + ":attribute:viewport-control:zoom",
        "data-universal-zoom",
        zoom_mode,
    )
    builder.template(
        prefix + ":viewport-control",
        tag=literal("viewport-control-tag", "button"),
        key=control_key,
        class_name=literal(
            "viewport-control-class", "header-action icon-only"
        ),
        attributes=control_attributes(
            "viewport-control", viewport_attribute
        ),
        condition=is_viewport,
    )
    history_attribute = builder.attribute(
        prefix + ":attribute:history-control:history",
        "data-universal-history",
        activation_operation,
    )
    builder.template(
        prefix + ":history-control",
        tag=literal("history-control-tag", "button"),
        key=control_key,
        class_name=literal(
            "history-control-class", "header-action icon-only"
        ),
        attributes=control_attributes("history-control", history_attribute),
        condition=is_history,
    )
    builder.template(
        prefix + ":semantic-control",
        tag=literal("semantic-control-tag", "button"),
        key=control_key,
        class_name=literal(
            "semantic-control-class", "header-action icon-only"
        ),
        attributes=control_attributes("semantic-control"),
        condition=is_other_semantic,
    )
    builder.template(
        prefix + ":zoom",
        tag=literal("zoom-tag", "span"),
        key=literal("zoom-key", "toolbar:zoom:value"),
        class_name=literal("zoom-class", "universal-zoom-value"),
        text=expression(
            "zoom-text", "concat", zoom_percent,
            literal("zoom-suffix", "%"),
        ),
        attributes=(builder.attribute(
            prefix + ":attribute:zoom-value",
            "data-universal-toolbar-zoom-value",
            literal("zoom-present", "True"),
        ),),
        condition=is_zoom_out,
    )
    builder.template(
        prefix + ":selection",
        tag=literal("selection-tag", "span"),
        key=literal("selection-key", "toolbar:selection"),
        class_name=literal("selection-class", "canvas-selection-value"),
        text=expression(
            "selection-text", "concat", selection_count,
            literal("selection-suffix", " selected"),
        ),
        attributes=(builder.attribute(
            prefix + ":attribute:selection-value",
            "data-universal-toolbar-selection-value",
            literal("selection-present", "True"),
        ),),
        condition=is_composition,
    )
    builder.template(
        prefix + ":control-item",
        tag=None,
        key=None,
        transparent=literal("control-item-transparent", True),
        children=(
            prefix + ":selection",
            prefix + ":viewport-control",
            prefix + ":history-control",
            prefix + ":semantic-control",
            prefix + ":zoom",
        ),
        condition=expression("control-item-visible", "not", is_scope),
        repeat=controls,
    )
    builder.template(
        prefix + ":selection-fallback",
        tag=literal("selection-fallback-tag", "span"),
        key=literal("selection-fallback-key", "toolbar:selection"),
        class_name=literal(
            "selection-fallback-class", "canvas-selection-value"
        ),
        text=expression(
            "selection-fallback-text", "concat", selection_count,
            literal("selection-fallback-suffix", " selected"),
        ),
        attributes=(builder.attribute(
            prefix + ":attribute:selection-fallback-value",
            "data-universal-toolbar-selection-value",
            literal("selection-fallback-present", "True"),
        ),),
        condition=no_composition,
    )
    builder.template(
        CANVAS_TOOLBAR_TEMPLATE_ROOT,
        tag=literal("surface-tag", "div"),
        key=literal("surface-key", "toolbar:surface"),
        class_name=literal("surface-class", "canvas-toolbar-surface"),
        children=(
            prefix + ":scope",
            prefix + ":control-item",
            prefix + ":selection-fallback",
        ),
    )
    return CANVAS_TOOLBAR_TEMPLATE_ROOT


__all__ = [
    "CANVAS_TOOLBAR_PREFIX",
    "CANVAS_TOOLBAR_TEMPLATE_MEMBER_ROOTS",
    "CANVAS_TOOLBAR_TEMPLATE_ROOT",
    "compose_canvas_toolbar_template",
]
