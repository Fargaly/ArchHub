"""Graph-authored standard Focus presenter.

This module only seeds a persisted template assembly. Runtime presentation is
interpreted through the generic ``cell_view_template`` protocol; no Focus or
presenter name selects host behavior.

The open-obligation heading is a visible ``count-where`` expression over the
projected collection. It is not a named host-side Focus behavior.
"""
from __future__ import annotations

from .cell_protocols import CellBatch
from .cell_view_template import ViewTemplateBuilder, ViewTemplateProtocol


VIEW_TEMPLATE_PREFIX = "app:view-template-protocol"
FOCUS_LIST_PREFIX = "app:focus-template:focus-list:v1"
FOCUS_LIST_TEMPLATE_ROOT = FOCUS_LIST_PREFIX + ":section"
# Ordered to replace the legacy section, heading, text, list, button, and
# details member incidences one-for-one.
FOCUS_LIST_TEMPLATE_MEMBER_ROOTS = (
    FOCUS_LIST_TEMPLATE_ROOT,
    FOCUS_LIST_PREFIX + ":heading",
    FOCUS_LIST_PREFIX + ":summary",
    FOCUS_LIST_PREFIX + ":reason-row",
    FOCUS_LIST_PREFIX + ":reason-button",
    FOCUS_LIST_PREFIX + ":obligations",
)


def compose_focus_list_template(
    batch: CellBatch,
    protocol: ViewTemplateProtocol,
) -> str:
    """Compose the Focus list as visible, rewritable graph relations."""
    builder = ViewTemplateBuilder(batch, protocol)
    prefix = FOCUS_LIST_PREFIX

    def literal(name: str, value: object) -> str:
        return builder.literal("%s:expression:%s" % (prefix, name), value)

    def segment(name: str) -> str:
        return builder.atom("%s:segment:%s" % (prefix, name), name)

    def path(name: str, base: str, *segments: str) -> str:
        return builder.expression(
            "%s:expression:%s" % (prefix, name),
            "path",
            (base, *segments),
        )

    def concat(name: str, *arguments: str) -> str:
        return builder.expression(
            "%s:expression:%s" % (prefix, name),
            "concat",
            arguments,
        )

    root_context = builder.expression(
        prefix + ":expression:root-context", "root"
    )
    item_context = builder.expression(
        prefix + ":expression:item-context", "item"
    )
    index_context = builder.expression(
        prefix + ":expression:index-context", "index"
    )

    focus_segment = segment("focus")
    root_segment = segment("root")
    origin_segment = segment("origin")
    state_segment = segment("state")
    created_at_segment = segment("created_at")
    reasons_segment = segment("reasons")
    previous_segment = segment("previous")
    obligations_segment = segment("obligations")
    label_segment = segment("label")
    priority_label_segment = segment("priority_label")

    focus = path("focus", root_context, focus_segment)
    focus_root = path("focus-root", focus, root_segment)
    focus_origin = path("focus-origin", focus, origin_segment)
    focus_state = path("focus-state", focus, state_segment)
    focus_created_at = path("focus-created-at", focus, created_at_segment)
    focus_reasons = path("focus-reasons", focus, reasons_segment)
    previous_focus = path("previous-focus", focus, previous_segment)
    obligations = path("obligations", root_context, obligations_segment)
    previous_present = builder.expression(
        prefix + ":expression:previous-present", "string", (previous_focus,)
    )

    item_root = path("item-root", item_context, root_segment)
    item_label = path("item-label", item_context, label_segment)
    item_state = path("item-state", item_context, state_segment)
    item_priority = path(
        "item-priority-label", item_context, priority_label_segment
    )

    upper_origin = builder.expression(
        prefix + ":expression:upper-origin", "upper", (focus_origin,)
    )
    upper_state = builder.expression(
        prefix + ":expression:upper-state", "upper", (focus_state,)
    )
    focus_summary = concat(
        "focus-summary", upper_origin, literal("summary-divider", " / "), upper_state
    )
    created_title = concat(
        "created-title", literal("created-prefix", "Created "), focus_created_at
    )

    section_key = concat(
        "section-key",
        literal("section-key-prefix", "presenter:focus-list:"),
        focus_root,
    )
    summary_key = concat(
        "summary-key", literal("summary-key-prefix", "focus:summary:"), focus_root
    )
    reason_row_key = concat(
        "reason-row-key",
        literal("reason-row-key-prefix", "focus:reason:"),
        index_context,
        literal("reason-row-key-divider", ":"),
        item_root,
    )
    reason_label_key = concat(
        "reason-label-key", reason_row_key, literal("reason-label-suffix", ":label")
    )
    reason_button_key = concat(
        "reason-button-key",
        literal("reason-button-key-prefix", "focus:reason-button:"),
        item_root,
    )
    previous_row_key = concat(
        "previous-row-key",
        literal("previous-row-key-prefix", "focus:previous:"),
        previous_focus,
    )
    previous_label_key = concat(
        "previous-label-key",
        previous_row_key,
        literal("previous-label-suffix", ":label"),
    )
    previous_button_key = concat(
        "previous-button-key",
        literal("previous-button-key-prefix", "focus:previous-button:"),
        previous_focus,
    )
    obligations_key = concat(
        "obligations-key",
        literal("obligations-key-prefix", "focus:obligations:"),
        focus_root,
    )
    obligations_summary_key = concat(
        "obligations-summary-key",
        literal(
            "obligations-summary-key-prefix", "focus:obligations-summary:"
        ),
        focus_root,
    )
    obligation_row_key = concat(
        "obligation-row-key",
        literal("obligation-row-key-prefix", "focus:obligation:"),
        item_root,
    )
    obligation_label_key = concat(
        "obligation-label-key",
        literal("obligation-label-key-prefix", "focus:obligation-label:"),
        item_root,
    )
    obligation_meta_key = concat(
        "obligation-meta-key",
        literal("obligation-meta-key-prefix", "focus:obligation-meta:"),
        item_root,
    )

    obligation_is_open = builder.expression(
        prefix + ":expression:obligation-is-open",
        "equals",
        (item_state, literal("obligation-open-state", "open")),
    )
    open_obligation_count = builder.expression(
        prefix + ":expression:open-obligation-count",
        "count-where",
        (obligations, obligation_is_open),
    )
    obligations_summary = concat(
        "obligations-summary",
        literal("obligations-summary-prefix", "OPEN OBLIGATIONS / "),
        open_obligation_count,
    )
    obligation_meta = concat(
        "obligation-meta",
        item_priority,
        literal("obligation-meta-divider", " / "),
        item_state,
    )

    reason_type = builder.attribute(
        prefix + ":attribute:reason-type", "type", literal("button-type", "button")
    )
    reason_title = builder.attribute(
        prefix + ":attribute:reason-title",
        "title",
        literal("reason-title", "Inspect this exact focus reason"),
    )
    reason_focus = builder.attribute(
        prefix + ":attribute:reason-focus", "data-universal-focus", item_root
    )
    previous_type = builder.attribute(
        prefix + ":attribute:previous-type",
        "type",
        literal("previous-button-type", "button"),
    )
    previous_title = builder.attribute(
        prefix + ":attribute:previous-title",
        "title",
        literal(
            "previous-title", "Inspect the previous persistent focus"
        ),
    )
    previous_focus_attribute = builder.attribute(
        prefix + ":attribute:previous-focus",
        "data-universal-focus",
        previous_focus,
    )
    obligation_type = builder.attribute(
        prefix + ":attribute:obligation-type",
        "type",
        literal("obligation-button-type", "button"),
    )
    obligation_title = builder.attribute(
        prefix + ":attribute:obligation-title",
        "title",
        literal(
            "obligation-title", "Inspect this exact persistent obligation"
        ),
    )
    obligation_focus = builder.attribute(
        prefix + ":attribute:obligation-focus",
        "data-universal-focus",
        item_root,
    )
    created_at = builder.attribute(
        prefix + ":attribute:created-at", "title", created_title
    )

    builder.template(
        FOCUS_LIST_PREFIX + ":heading",
        tag=literal("heading-tag", "div"),
        key=literal("heading-key", "focus:heading"),
        class_name=literal("heading-class", "inspector-heading"),
        text=literal("heading-text", "CURRENT FOCUS"),
    )
    builder.template(
        FOCUS_LIST_PREFIX + ":summary",
        tag=literal("summary-tag", "div"),
        key=summary_key,
        class_name=literal(
            "summary-class", "connection-box focus-summary"
        ),
        text=focus_summary,
        attributes=(created_at,),
    )
    builder.template(
        FOCUS_LIST_PREFIX + ":reason-label",
        tag=literal("reason-label-tag", "span"),
        key=reason_label_key,
        class_name=literal("reason-label-class", "property-label"),
        text=literal("reason-label-text", "WHY"),
    )
    builder.template(
        FOCUS_LIST_PREFIX + ":reason-button",
        tag=literal("reason-button-tag", "button"),
        key=reason_button_key,
        class_name=literal(
            "reason-button-class",
            "connection-box connection-link focus-reason-link",
        ),
        text=item_label,
        attributes=(reason_type, reason_title, reason_focus),
    )
    builder.template(
        FOCUS_LIST_PREFIX + ":reason-row",
        tag=literal("reason-row-tag", "div"),
        key=reason_row_key,
        class_name=literal("reason-row-class", "property-row"),
        children=(
            FOCUS_LIST_PREFIX + ":reason-label",
            FOCUS_LIST_PREFIX + ":reason-button",
        ),
        repeat=focus_reasons,
    )
    builder.template(
        FOCUS_LIST_PREFIX + ":previous-label",
        tag=literal("previous-label-tag", "span"),
        key=previous_label_key,
        class_name=literal("previous-label-class", "property-label"),
        text=literal("previous-label-text", "HISTORY"),
    )
    builder.template(
        FOCUS_LIST_PREFIX + ":previous-button",
        tag=literal("previous-button-tag", "button"),
        key=previous_button_key,
        class_name=literal(
            "previous-button-class", "connection-box connection-link"
        ),
        text=literal("previous-button-text", "Previous focus"),
        attributes=(
            previous_type,
            previous_title,
            previous_focus_attribute,
        ),
    )
    builder.template(
        FOCUS_LIST_PREFIX + ":previous-row",
        tag=literal("previous-row-tag", "div"),
        key=previous_row_key,
        class_name=literal("previous-row-class", "property-row"),
        children=(
            FOCUS_LIST_PREFIX + ":previous-label",
            FOCUS_LIST_PREFIX + ":previous-button",
        ),
        condition=previous_present,
    )
    builder.template(
        FOCUS_LIST_PREFIX + ":obligation-label",
        tag=literal("obligation-label-tag", "span"),
        key=obligation_label_key,
        class_name=literal("obligation-label-class", "property-label"),
        text=item_label,
    )
    builder.template(
        FOCUS_LIST_PREFIX + ":obligation-meta",
        tag=literal("obligation-meta-tag", "span"),
        key=obligation_meta_key,
        class_name=literal(
            "obligation-meta-class", "universal-library-meta"
        ),
        text=obligation_meta,
    )
    builder.template(
        FOCUS_LIST_PREFIX + ":obligation-row",
        tag=literal("obligation-row-tag", "button"),
        key=obligation_row_key,
        class_name=literal(
            "obligation-row-class", "library-row focus-obligation-row"
        ),
        attributes=(obligation_type, obligation_title, obligation_focus),
        children=(
            FOCUS_LIST_PREFIX + ":obligation-label",
            FOCUS_LIST_PREFIX + ":obligation-meta",
        ),
        repeat=obligations,
    )
    builder.template(
        FOCUS_LIST_PREFIX + ":obligations-summary",
        tag=literal("obligations-summary-tag", "summary"),
        key=obligations_summary_key,
        class_name=literal(
            "obligations-summary-class", "inspector-heading"
        ),
        text=obligations_summary,
    )
    builder.template(
        FOCUS_LIST_PREFIX + ":obligations",
        tag=literal("obligations-tag", "details"),
        key=obligations_key,
        class_name=literal("obligations-class", "focus-obligations"),
        children=(
            FOCUS_LIST_PREFIX + ":obligations-summary",
            FOCUS_LIST_PREFIX + ":obligation-row",
        ),
        condition=builder.expression(
            prefix + ":expression:obligation-count",
            "length",
            (obligations,),
        ),
    )
    builder.template(
        FOCUS_LIST_TEMPLATE_ROOT,
        tag=literal("section-tag", "section"),
        key=section_key,
        class_name=literal(
            "section-class", "inspector-section focus-section"
        ),
        children=(
            FOCUS_LIST_PREFIX + ":heading",
            FOCUS_LIST_PREFIX + ":summary",
            FOCUS_LIST_PREFIX + ":reason-row",
            FOCUS_LIST_PREFIX + ":previous-row",
            FOCUS_LIST_PREFIX + ":obligations",
        ),
    )
    return FOCUS_LIST_TEMPLATE_ROOT


__all__ = [
    "FOCUS_LIST_PREFIX",
    "FOCUS_LIST_TEMPLATE_MEMBER_ROOTS",
    "FOCUS_LIST_TEMPLATE_ROOT",
    "VIEW_TEMPLATE_PREFIX",
    "compose_focus_list_template",
]
