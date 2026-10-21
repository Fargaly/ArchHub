"""Graph-authored operational control-list presenter over raw projections.

Runtime presentation is resolved only by ``cell_view_template`` from persisted
relations.  The assembly mapping is repeated directly so the state and
operational sections remain sibling descriptors without a presenter-specific
projection or disposable wrapper.
"""
from __future__ import annotations

from .cell_protocols import CellBatch
from .cell_view_template import ViewTemplateBuilder, ViewTemplateProtocol


VIEW_TEMPLATE_PREFIX = "app:view-template-protocol"
CONTROL_LIST_PREFIX = "app:properties-template:control-list:v1"
CONTROL_LIST_TEMPLATE_ROOT = CONTROL_LIST_PREFIX + ":section"

_STATE_SECTION_ROOT = CONTROL_LIST_PREFIX + ":state-section"
_STATE_HEADING_ROOT = CONTROL_LIST_PREFIX + ":state-heading"
_STATE_STATUS_ROW_ROOT = CONTROL_LIST_PREFIX + ":state-status-row"
_STATE_ERROR_ROW_ROOT = CONTROL_LIST_PREFIX + ":state-error-row"
_STATE_LABEL_ROOT = CONTROL_LIST_PREFIX + ":state-label"
_STATE_VALUE_ROOT = CONTROL_LIST_PREFIX + ":state-value"
_OPERATIONAL_SECTION_ROOT = CONTROL_LIST_PREFIX + ":operational-section"
_OPERATIONAL_HEADING_ROOT = CONTROL_LIST_PREFIX + ":operational-heading"
_CURRENT_ROW_ROOT = CONTROL_LIST_PREFIX + ":current-row"
_CURRENT_LABEL_ROOT = CONTROL_LIST_PREFIX + ":current-label"
_CURRENT_VALUE_ROOT = CONTROL_LIST_PREFIX + ":current-value"
_TRANSITION_ROW_ROOT = CONTROL_LIST_PREFIX + ":transition-row"
_TRANSITION_LABEL_ROOT = CONTROL_LIST_PREFIX + ":transition-label"
_TRANSITION_EVIDENCE_ROOT = CONTROL_LIST_PREFIX + ":transition-evidence"
_TRANSITION_ACTION_ROOT = CONTROL_LIST_PREFIX + ":transition-action"
_HISTORY_ROOT = CONTROL_LIST_PREFIX + ":history"
_HISTORY_SUMMARY_ROOT = CONTROL_LIST_PREFIX + ":history-summary"
_HISTORY_ROW_ROOT = CONTROL_LIST_PREFIX + ":history-row"
_HISTORY_LABEL_ROOT = CONTROL_LIST_PREFIX + ":history-label"
_HISTORY_VALUE_ROOT = CONTROL_LIST_PREFIX + ":history-value"

# Ordered replacement for section, heading, list, row, text, button, details,
# condition, and action-binding.  The action descriptor is both the visible
# button and its binding, so those two incidences intentionally share one root.
CONTROL_LIST_TEMPLATE_MEMBER_ROOTS = (
    CONTROL_LIST_TEMPLATE_ROOT,
    _OPERATIONAL_HEADING_ROOT,
    _STATE_STATUS_ROW_ROOT,
    _TRANSITION_ROW_ROOT,
    _TRANSITION_EVIDENCE_ROOT,
    _TRANSITION_ACTION_ROOT,
    _HISTORY_ROOT,
    _STATE_HEADING_ROOT,
    _TRANSITION_ACTION_ROOT,
)


def compose_control_list_template(
    batch: CellBatch,
    protocol: ViewTemplateProtocol,
) -> str:
    """Compose state and operational controls as rewritable graph relations."""
    builder = ViewTemplateBuilder(batch, protocol)
    prefix = CONTROL_LIST_PREFIX
    segments: dict[str, str] = {}

    def expression(
        name: str,
        operation: str,
        arguments: tuple[str, ...] = (),
    ) -> str:
        return builder.expression(
            "%s:expression:%s" % (prefix, name), operation, arguments
        )

    def literal(name: str, value: object) -> str:
        return builder.literal("%s:expression:%s" % (prefix, name), value)

    def segment(name: str) -> str:
        if name not in segments:
            segments[name] = builder.atom(
                "%s:segment:%s" % (prefix, name), name
            )
        return segments[name]

    def path(name: str, base: str, *names: str) -> str:
        return expression(
            name,
            "path",
            (base, *(segment(item) for item in names)),
        )

    def concat(name: str, *arguments: str) -> str:
        return expression(name, "concat", arguments)

    def attribute(name: str, attribute_name: str, value: str) -> str:
        return builder.attribute(
            "%s:attribute:%s" % (prefix, name), attribute_name, value
        )

    root_context = expression("root-context", "root")
    item_context = expression("item-context", "item")
    index_context = expression("index-context", "index")
    empty = literal("empty", "")
    false_value = expression(
        "false-value",
        "equals",
        (empty, literal("non-empty-false-comparator", "not-empty")),
    )
    absent = path(
        "absent-attribute", item_context, "attribute-not-present"
    )

    selected = path("selected", root_context, "selected")
    selected_text = expression("selected-text", "string", (selected,))
    assembly = path(
        "selected-assembly", root_context, "selected_assembly"
    )
    status_items = path("status-items", assembly, "status")
    error_items = path("error-items", assembly, "errors")
    operational_raw = path("operational-raw", assembly, "operational")
    operational = expression(
        "operational", "fallback", (operational_raw, empty)
    )
    operational_size = expression(
        "operational-size", "length", (operational,)
    )

    state_count = expression(
        "state-count",
        "add",
        (
            expression("status-count", "length", (status_items,)),
            expression("error-count", "length", (error_items,)),
        ),
    )
    show_state = expression("show-state", "and", (assembly, state_count))

    state_section_key = concat(
        "state-section-key",
        literal("state-section-key-prefix", "presenter:control-list:state:"),
        selected_text,
    )
    operational_section_key = concat(
        "operational-section-key",
        literal(
            "operational-section-key-prefix",
            "presenter:control-list:operational:",
        ),
        selected_text,
    )
    state_id = path("state-item-id", item_context, "id")
    state_label = path("state-item-label", item_context, "label")
    state_value = path("state-item-value", item_context, "value")
    normalized_state_value = expression(
        "normalized-state-value", "fallback", (state_value, false_value)
    )
    displayed_state_value = expression(
        "displayed-state-value",
        "choose",
        (
            normalized_state_value,
            expression(
                "state-value-text", "string", (normalized_state_value,)
            ),
            literal("empty-state-value", "empty"),
        ),
    )
    state_row_key = concat(
        "state-row-key",
        literal("state-row-key-prefix", "state:"),
        selected_text,
        literal("state-row-key-divider", ":"),
        state_id,
    )
    state_label_key = concat(
        "state-label-key", state_row_key, literal("state-label-suffix", ":label")
    )
    state_value_key = concat(
        "state-value-key",
        literal("state-value-key-prefix", "state-value:"),
        selected_text,
        literal("state-value-key-divider", ":"),
        state_id,
    )
    builder.template(
        _STATE_LABEL_ROOT,
        tag=literal("state-label-tag", "span"),
        key=state_label_key,
        class_name=literal("state-label-class", "property-label"),
        text=state_label,
    )
    builder.template(
        _STATE_VALUE_ROOT,
        tag=literal("state-value-tag", "div"),
        key=state_value_key,
        class_name=literal("state-value-class", "connection-box"),
        text=displayed_state_value,
    )
    state_row_tag = literal("state-row-tag", "div")
    state_row_class = literal("state-row-class", "property-row")
    for template_root, repeat_root in (
        (_STATE_STATUS_ROW_ROOT, status_items),
        (_STATE_ERROR_ROW_ROOT, error_items),
    ):
        builder.template(
            template_root,
            tag=state_row_tag,
            key=state_row_key,
            class_name=state_row_class,
            children=(_STATE_LABEL_ROOT, _STATE_VALUE_ROOT),
            repeat=repeat_root,
        )
    builder.template(
        _STATE_HEADING_ROOT,
        tag=literal("state-heading-tag", "div"),
        key=literal("state-heading-key", "state:heading"),
        class_name=literal("state-heading-class", "inspector-heading"),
        text=literal("state-heading-text", "STATE"),
    )

    current_state = path(
        "current-state", operational, "current_state"
    )
    current_state_text = expression(
        "current-state-text", "string", (current_state,)
    )
    current_state_label = path(
        "current-state-label", operational, "current_state_label"
    )
    current_row_key = concat(
        "current-row-key",
        literal("current-row-key-prefix", "operational-current:"),
        selected_text,
    )
    current_label_key = concat(
        "current-label-key",
        current_row_key,
        literal("current-label-key-suffix", ":label"),
    )
    current_value_key = concat(
        "current-value-key",
        literal("current-value-key-prefix", "operational-current-value:"),
        selected_text,
    )
    builder.template(
        _CURRENT_LABEL_ROOT,
        tag=literal("current-label-tag", "span"),
        key=current_label_key,
        class_name=literal("current-label-class", "property-label"),
        text=literal("current-label-text", "CURRENT"),
    )
    builder.template(
        _CURRENT_VALUE_ROOT,
        tag=literal("current-value-tag", "div"),
        key=current_value_key,
        class_name=literal(
            "current-value-class", "connection-box operational-current"
        ),
        text=current_state_label,
    )
    builder.template(
        _CURRENT_ROW_ROOT,
        tag=literal("current-row-tag", "div"),
        key=current_row_key,
        class_name=literal("current-row-class", "property-row"),
        children=(_CURRENT_LABEL_ROOT, _CURRENT_VALUE_ROOT),
    )
    builder.template(
        _OPERATIONAL_HEADING_ROOT,
        tag=literal("operational-heading-tag", "div"),
        key=literal("operational-heading-key", "operational:heading"),
        class_name=literal(
            "operational-heading-class", "inspector-heading"
        ),
        text=literal("operational-heading-text", "OPERATIONAL STATE"),
    )

    transitions = path(
        "admitted-transitions", operational, "admitted_transitions"
    )
    event = path("transition-event", item_context, "event")
    control = path("transition-control", item_context, "control")
    event_text = expression("transition-event-text", "string", (event,))
    event_label = path(
        "transition-event-label", item_context, "event_label"
    )
    to_state_label = path(
        "transition-to-state-label", item_context, "to_state_label"
    )
    evidence_types = path(
        "transition-evidence-types",
        item_context,
        "required_evidence_types",
    )
    evidence_label = path("evidence-label", item_context, "label")
    evidence_labels = expression(
        "transition-evidence-labels", "map", (evidence_types, evidence_label)
    )
    joined_evidence = expression(
        "joined-transition-evidence",
        "join",
        (evidence_labels, literal("evidence-separator", ", ")),
    )
    evidence_text = expression(
        "transition-evidence-text",
        "choose",
        (
            evidence_types,
            joined_evidence,
            literal("no-evidence-gate", "no evidence gate"),
        ),
    )
    user_decision_raw = path(
        "transition-user-decision", item_context, "user_decision"
    )
    user_decision = expression(
        "transition-user-decision-or-empty",
        "fallback",
        (user_decision_raw, false_value),
    )
    adapter_execute_raw = path(
        "transition-adapter-execute", item_context, "adapter_execute"
    )
    adapter_execute = expression(
        "transition-adapter-execute-or-empty",
        "fallback",
        (adapter_execute_raw, false_value),
    )
    event_upper = expression(
        "transition-event-upper", "upper", (event_label,)
    )
    action_text = expression(
        "transition-action-text",
        "choose",
        (
            user_decision,
            event_upper,
            expression(
                "adapter-or-gated-action-text",
                "choose",
                (
                    adapter_execute,
                    literal("execute-action-text", "EXECUTE"),
                    expression(
                        "gated-or-event-action-text",
                        "choose",
                        (
                            evidence_types,
                            literal(
                                "evidence-required-action-text",
                                "EVIDENCE REQUIRED",
                            ),
                            event_label,
                        ),
                    ),
                ),
            ),
        ),
    )
    transition_row_key = concat(
        "transition-row-key",
        literal(
            "transition-row-key-prefix", "operational-transition:"
        ),
        selected_text,
        literal("transition-row-key-divider", ":"),
        event_text,
    )
    transition_label_key = concat(
        "transition-label-key",
        literal(
            "transition-label-key-prefix", "operational-transition-label:"
        ),
        selected_text,
        literal("transition-label-key-divider", ":"),
        event_text,
    )
    transition_evidence_key = concat(
        "transition-evidence-key",
        literal(
            "transition-evidence-key-prefix",
            "operational-transition-evidence:",
        ),
        selected_text,
        literal("transition-evidence-key-divider", ":"),
        event_text,
    )
    transition_action_key = concat(
        "transition-action-key",
        literal(
            "transition-action-key-prefix", "operational-transition-action:"
        ),
        selected_text,
        literal("transition-action-key-divider", ":"),
        event_text,
    )
    transition_label_text = concat(
        "transition-label-text",
        event_label,
        literal("transition-label-arrow", " -> "),
        to_state_label,
    )
    adapter_title = literal(
        "adapter-action-title",
        "Execute through the graph allowlisted adapter",
    )
    decision_title = concat(
        "decision-action-title",
        literal("decision-title-prefix", "Record authenticated "),
        event_label,
        literal("decision-title-suffix", " decision"),
    )
    evidence_title = concat(
        "evidence-action-title",
        literal("evidence-title-prefix", "Requires "),
        evidence_text,
        literal(
            "evidence-title-suffix", " from an admitted adapter"
        ),
    )
    transition_title = concat(
        "transition-action-title",
        event_label,
        literal("transition-title-arrow", " -> "),
        to_state_label,
    )
    non_adapter_title = expression(
        "non-adapter-action-title",
        "choose",
        (
            user_decision,
            decision_title,
            expression(
                "evidence-or-transition-title",
                "choose",
                (evidence_types, evidence_title, transition_title),
            ),
        ),
    )
    action_title = expression(
        "action-title",
        "choose",
        (adapter_execute, adapter_title, non_adapter_title),
    )
    action_disabled = expression(
        "action-disabled",
        "and",
        (
            evidence_types,
            expression("not-user-decision", "not", (user_decision,)),
            expression("not-adapter-execute", "not", (adapter_execute,)),
        ),
    )
    adapter_attribute_value = expression(
        "adapter-attribute-value",
        "choose",
        (
            adapter_execute,
            literal("true-adapter-attribute", "true"),
            absent,
        ),
    )
    action_attributes = (
        attribute("action-type", "type", literal("button-type", "button")),
        attribute("action-disabled", "disabled", action_disabled),
        attribute("action-root", "data-root", selected_text),
        attribute("action-event", "data-event", event_text),
        attribute("action-expected", "data-expected", current_state_text),
        attribute(
            "action-adapter-execute",
            "data-universal-adapter-execute",
            adapter_attribute_value,
        ),
        attribute(
            "action-control",
            "data-universal-control",
            control,
        ),
        attribute("action-title", "title", action_title),
    )
    builder.template(
        _TRANSITION_LABEL_ROOT,
        tag=literal("transition-label-tag", "span"),
        key=transition_label_key,
        class_name=literal("transition-label-class", "property-label"),
        text=transition_label_text,
    )
    builder.template(
        _TRANSITION_EVIDENCE_ROOT,
        tag=literal("transition-evidence-tag", "div"),
        key=transition_evidence_key,
        class_name=literal(
            "transition-evidence-class", "connection-box"
        ),
        text=evidence_text,
    )
    builder.template(
        _TRANSITION_ACTION_ROOT,
        tag=literal("transition-action-tag", "button"),
        key=transition_action_key,
        class_name=literal("transition-action-class", "operational-action"),
        text=action_text,
        attributes=action_attributes,
    )
    builder.template(
        _TRANSITION_ROW_ROOT,
        tag=literal("transition-row-tag", "div"),
        key=transition_row_key,
        class_name=literal("transition-row-class", "property-row"),
        children=(
            _TRANSITION_LABEL_ROOT,
            _TRANSITION_EVIDENCE_ROOT,
            _TRANSITION_ACTION_ROOT,
        ),
        repeat=transitions,
    )

    history = path("operational-history", operational, "history")
    history_count = expression("history-count", "length", (history,))
    history_key = concat(
        "history-key",
        literal("history-key-prefix", "operational-history-list:"),
        selected_text,
    )
    history_summary_key = concat(
        "history-summary-key",
        literal(
            "history-summary-key-prefix", "operational-history-summary:"
        ),
        selected_text,
    )
    history_summary_text = concat(
        "history-summary-text",
        literal("history-summary-prefix", "OPERATION HISTORY / "),
        history_count,
    )
    history_event_label = path(
        "history-event-label", item_context, "event_label"
    )
    history_from_state = path(
        "history-from-state", item_context, "from_state_label"
    )
    history_to_state = path(
        "history-to-state", item_context, "to_state_label"
    )
    history_evidence = path(
        "history-evidence", item_context, "evidence"
    )
    history_evidence_count = expression(
        "history-evidence-count", "length", (history_evidence,)
    )
    history_row_key = concat(
        "history-row-key",
        literal("history-row-key-prefix", "operational-history:"),
        selected_text,
        literal("history-row-key-divider", ":"),
        index_context,
    )
    history_label_key = concat(
        "history-label-key",
        history_row_key,
        literal("history-label-key-suffix", ":label"),
    )
    history_value_key = concat(
        "history-value-key",
        literal(
            "history-value-key-prefix", "operational-history-value:"
        ),
        selected_text,
        literal("history-value-key-divider", ":"),
        index_context,
    )
    history_value_text = concat(
        "history-value-text",
        history_from_state,
        literal("history-state-arrow", " -> "),
        history_to_state,
        literal("history-evidence-divider", " / "),
        history_evidence_count,
        literal("history-evidence-suffix", " evidence"),
    )
    builder.template(
        _HISTORY_LABEL_ROOT,
        tag=literal("history-label-tag", "span"),
        key=history_label_key,
        class_name=literal("history-label-class", "property-label"),
        text=history_event_label,
    )
    builder.template(
        _HISTORY_VALUE_ROOT,
        tag=literal("history-value-tag", "div"),
        key=history_value_key,
        class_name=literal("history-value-class", "connection-box"),
        text=history_value_text,
    )
    builder.template(
        _HISTORY_ROW_ROOT,
        tag=literal("history-row-tag", "div"),
        key=history_row_key,
        class_name=literal("history-row-class", "property-row"),
        children=(_HISTORY_LABEL_ROOT, _HISTORY_VALUE_ROOT),
        repeat=history,
    )
    builder.template(
        _HISTORY_SUMMARY_ROOT,
        tag=literal("history-summary-tag", "summary"),
        key=history_summary_key,
        class_name=literal("history-summary-class", "inspector-heading"),
        text=history_summary_text,
    )
    builder.template(
        _HISTORY_ROOT,
        tag=literal("history-tag", "details"),
        key=history_key,
        class_name=literal("history-class", "inspector-section"),
        children=(_HISTORY_SUMMARY_ROOT, _HISTORY_ROW_ROOT),
    )

    builder.template(
        _STATE_SECTION_ROOT,
        tag=literal("section-tag", "section"),
        key=state_section_key,
        class_name=literal("section-class", "inspector-section"),
        children=(
            _STATE_HEADING_ROOT,
            _STATE_STATUS_ROW_ROOT,
            _STATE_ERROR_ROW_ROOT,
        ),
        condition=show_state,
    )
    builder.template(
        _OPERATIONAL_SECTION_ROOT,
        tag=literal("operational-section-tag", "section"),
        key=operational_section_key,
        class_name=literal(
            "operational-section-class", "inspector-section"
        ),
        children=(
            _OPERATIONAL_HEADING_ROOT,
            _CURRENT_ROW_ROOT,
            _TRANSITION_ROW_ROOT,
            _HISTORY_ROOT,
        ),
        condition=operational_size,
    )
    builder.template(
        CONTROL_LIST_TEMPLATE_ROOT,
        tag=None,
        key=None,
        children=(_STATE_SECTION_ROOT, _OPERATIONAL_SECTION_ROOT),
        transparent=literal("transparent-template", "true"),
    )
    return CONTROL_LIST_TEMPLATE_ROOT


__all__ = [
    "CONTROL_LIST_PREFIX",
    "CONTROL_LIST_TEMPLATE_MEMBER_ROOTS",
    "CONTROL_LIST_TEMPLATE_ROOT",
    "VIEW_TEMPLATE_PREFIX",
    "compose_control_list_template",
]
