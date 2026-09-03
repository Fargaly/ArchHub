"""Graph-authored presentation-list Properties presenter.

The composer below only persists paths, expressions, templates, and action
attributes. Runtime projection is performed by the generic
``cell_view_template`` interpreter over the raw application projection.
"""
from __future__ import annotations

from .cell_protocols import CellBatch
from .cell_view_template import ViewTemplateBuilder, ViewTemplateProtocol


VIEW_TEMPLATE_PREFIX = "app:view-template-protocol"
LEGACY_PRESENTATION_LIST_PREFIX = (
    "app:properties-template:presentation-list:v1"
)
LEGACY_PRESENTATION_LIST_TEMPLATE_ROOT = (
    LEGACY_PRESENTATION_LIST_PREFIX + ":section"
)
LEGACY_PRESENTATION_LIST_TEMPLATE_MEMBER_ROOTS = (
    LEGACY_PRESENTATION_LIST_TEMPLATE_ROOT,
    LEGACY_PRESENTATION_LIST_PREFIX + ":heading",
    LEGACY_PRESENTATION_LIST_PREFIX + ":history",
    LEGACY_PRESENTATION_LIST_PREFIX + ":property-row",
    LEGACY_PRESENTATION_LIST_PREFIX + ":theme-input",
    LEGACY_PRESENTATION_LIST_PREFIX + ":property-input",
    LEGACY_PRESENTATION_LIST_PREFIX + ":court-action",
    LEGACY_PRESENTATION_LIST_PREFIX + ":evidence",
    LEGACY_PRESENTATION_LIST_PREFIX + ":property-value",
    LEGACY_PRESENTATION_LIST_PREFIX + ":court-action",
)
PREINTERACTION_PRESENTATION_LIST_PREFIX = (
    "app:properties-template:presentation-list:v2"
)
PREINTERACTION_PRESENTATION_LIST_TEMPLATE_ROOT = (
    PREINTERACTION_PRESENTATION_LIST_PREFIX + ":section"
)
PREINTERACTION_PRESENTATION_LIST_TEMPLATE_MEMBER_ROOTS = (
    PREINTERACTION_PRESENTATION_LIST_TEMPLATE_ROOT,
    PREINTERACTION_PRESENTATION_LIST_PREFIX + ":heading",
    PREINTERACTION_PRESENTATION_LIST_PREFIX + ":history",
    PREINTERACTION_PRESENTATION_LIST_PREFIX + ":property-row",
    PREINTERACTION_PRESENTATION_LIST_PREFIX + ":theme-input",
    PREINTERACTION_PRESENTATION_LIST_PREFIX + ":property-input",
    PREINTERACTION_PRESENTATION_LIST_PREFIX + ":court-action",
    PREINTERACTION_PRESENTATION_LIST_PREFIX + ":evidence",
    PREINTERACTION_PRESENTATION_LIST_PREFIX + ":property-value",
    PREINTERACTION_PRESENTATION_LIST_PREFIX + ":court-action",
    PREINTERACTION_PRESENTATION_LIST_PREFIX + ":color-input",
    PREINTERACTION_PRESENTATION_LIST_PREFIX + ":color-source",
    PREINTERACTION_PRESENTATION_LIST_PREFIX + ":color-reset",
)
PREAPPEARANCE_PRESENTATION_LIST_PREFIX = (
    "app:properties-template:presentation-list:v3"
)
PREAPPEARANCE_PRESENTATION_LIST_TEMPLATE_ROOT = (
    PREAPPEARANCE_PRESENTATION_LIST_PREFIX + ":section"
)
PREAPPEARANCE_PRESENTATION_LIST_TEMPLATE_MEMBER_ROOTS = (
    PREAPPEARANCE_PRESENTATION_LIST_TEMPLATE_ROOT,
    PREAPPEARANCE_PRESENTATION_LIST_PREFIX + ":heading",
    PREAPPEARANCE_PRESENTATION_LIST_PREFIX + ":history",
    PREAPPEARANCE_PRESENTATION_LIST_PREFIX + ":property-row",
    PREAPPEARANCE_PRESENTATION_LIST_PREFIX + ":theme-input",
    PREAPPEARANCE_PRESENTATION_LIST_PREFIX + ":property-input",
    PREAPPEARANCE_PRESENTATION_LIST_PREFIX + ":court-action",
    PREAPPEARANCE_PRESENTATION_LIST_PREFIX + ":evidence",
    PREAPPEARANCE_PRESENTATION_LIST_PREFIX + ":property-value",
    PREAPPEARANCE_PRESENTATION_LIST_PREFIX + ":court-action",
    PREAPPEARANCE_PRESENTATION_LIST_PREFIX + ":color-input",
    PREAPPEARANCE_PRESENTATION_LIST_PREFIX + ":color-source",
    PREAPPEARANCE_PRESENTATION_LIST_PREFIX + ":color-reset",
)
PRETHEME_PRESENTATION_LIST_PREFIX = (
    "app:properties-template:presentation-list:v4"
)
PRETHEME_PRESENTATION_LIST_TEMPLATE_ROOT = (
    PRETHEME_PRESENTATION_LIST_PREFIX + ":section"
)
PRETHEME_PRESENTATION_LIST_TEMPLATE_MEMBER_ROOTS = (
    PRETHEME_PRESENTATION_LIST_TEMPLATE_ROOT,
    PRETHEME_PRESENTATION_LIST_PREFIX + ":heading",
    PRETHEME_PRESENTATION_LIST_PREFIX + ":history",
    PRETHEME_PRESENTATION_LIST_PREFIX + ":property-row",
    PRETHEME_PRESENTATION_LIST_PREFIX + ":theme-input",
    PRETHEME_PRESENTATION_LIST_PREFIX + ":property-input",
    PRETHEME_PRESENTATION_LIST_PREFIX + ":court-action",
    PRETHEME_PRESENTATION_LIST_PREFIX + ":evidence",
    PRETHEME_PRESENTATION_LIST_PREFIX + ":property-value",
    PRETHEME_PRESENTATION_LIST_PREFIX + ":court-action",
    PRETHEME_PRESENTATION_LIST_PREFIX + ":color-input",
    PRETHEME_PRESENTATION_LIST_PREFIX + ":color-source",
    PRETHEME_PRESENTATION_LIST_PREFIX + ":color-reset",
)
PRESENTATION_LIST_PREFIX = "app:properties-template:presentation-list:v5"
PRESENTATION_LIST_TEMPLATE_ROOT = PRESENTATION_LIST_PREFIX + ":section"

_HEADING_ROOT = PRESENTATION_LIST_PREFIX + ":heading"
_PROPERTY_ROW_ROOT = PRESENTATION_LIST_PREFIX + ":property-row"
_PROPERTY_INPUT_ROOT = PRESENTATION_LIST_PREFIX + ":property-input"
_PROPERTY_VALUE_ROOT = PRESENTATION_LIST_PREFIX + ":property-value"
_COLOR_INPUT_ROOT = PRESENTATION_LIST_PREFIX + ":color-input"
_COLOR_SOURCE_ROOT = PRESENTATION_LIST_PREFIX + ":color-source"
_COLOR_RESET_ROOT = PRESENTATION_LIST_PREFIX + ":color-reset"
_THEME_INPUT_ROOT = PRESENTATION_LIST_PREFIX + ":theme-input"
_HISTORY_ROOT = PRESENTATION_LIST_PREFIX + ":history"
_EVIDENCE_ROOT = PRESENTATION_LIST_PREFIX + ":evidence"
_ACTION_ROOT = PRESENTATION_LIST_PREFIX + ":court-action"

# Ordered to replace section, heading, list, row, control, input, button,
# details, condition, and action-binding incidences. The court action is both
# the visible button and its graph action binding, so those two slots honestly
# share one executable relation.
PRESENTATION_LIST_TEMPLATE_MEMBER_ROOTS = (
    PRESENTATION_LIST_TEMPLATE_ROOT,
    _HEADING_ROOT,
    _HISTORY_ROOT,
    _PROPERTY_ROW_ROOT,
    _THEME_INPUT_ROOT,
    _PROPERTY_INPUT_ROOT,
    _ACTION_ROOT,
    _EVIDENCE_ROOT,
    _PROPERTY_VALUE_ROOT,
    _ACTION_ROOT,
    _COLOR_INPUT_ROOT,
    _COLOR_SOURCE_ROOT,
    _COLOR_RESET_ROOT,
)


def compose_presentation_list_template(
    batch: CellBatch,
    protocol: ViewTemplateProtocol,
) -> str:
    """Persist the complete Presentation view as rewritable graph relations."""
    builder = ViewTemplateBuilder(batch, protocol)
    prefix = PRESENTATION_LIST_PREFIX

    def expression(
        name: str,
        operation: str,
        *arguments: str,
    ) -> str:
        return builder.expression(
            "%s:expression:%s" % (prefix, name), operation, arguments
        )

    def literal(name: str, value: object) -> str:
        return builder.literal("%s:expression:%s" % (prefix, name), value)

    def segment(name: str, value: str | None = None) -> str:
        return builder.atom(
            "%s:segment:%s" % (prefix, name),
            name if value is None else value,
        )

    def path(name: str, base: str, *segments: str) -> str:
        return expression(name, "path", base, *segments)

    def truthy(name: str, source: str) -> str:
        candidate = expression(name + "-candidate", "fallback", source)
        present = expression(name + "-present", "string", candidate)
        return expression(name, "and", source, present)

    root_context = expression("root-context", "root")
    item_context = expression("item-context", "item")
    index_context = expression("index-context", "index")
    parent_context = expression("parent-context", "parent")

    segments = {
        name: segment(name)
        for name in (
            "selected",
            "configuration",
            "personal_asset",
            "properties",
            "label",
            "relation",
            "value",
            "editable",
            "control",
            "event_fact_input",
            "state",
            "binding_mode",
            "preview_revision",
            "binding",
            "court",
            "theme_fields",
            "history",
            "revision",
            "reason",
            "digest",
            "evidence",
            "current",
            "restore_control",
            "root",
            "checks",
            "result",
            "builder",
            "duration_ms",
            "key",
            "presentation_editable",
            "presentation_control",
            "presentation_event_fact_input",
            "presentation_reset",
            "presentation_reset_control",
            "presentation_source",
            "presentation_source_mode",
        )
    }
    zero_item_segment = segment("zero-item", "0")
    absent_segment = segment("attribute-not-present")

    empty = literal("empty", "")
    none = literal("none", "none")
    zero = literal("zero", "0")
    one = literal("one", "1")
    seven = literal("seven", "7")
    minus = literal("minus", "-")
    slash = literal("slash", " / ")
    colon = literal("colon", ":")
    hash_character = literal("hash-character", "#")
    text_type = literal("text-input-type", "text")
    color_type = literal("color-input-type", "color")
    button_type = literal("button-type", "button")

    selected = path("selected", root_context, segments["selected"])
    configuration = path(
        "configuration", root_context, segments["configuration"]
    )
    personal_asset = path(
        "personal-asset", configuration, segments["personal_asset"]
    )
    properties = path("properties", root_context, segments["properties"])
    config_state = path(
        "configuration-state", configuration, segments["state"]
    )
    binding_mode = path(
        "binding-mode", configuration, segments["binding_mode"]
    )
    preview_revision = path(
        "preview-revision", configuration, segments["preview_revision"]
    )
    binding = path("binding", configuration, segments["binding"])
    court_state = path(
        "court-state", configuration, segments["court"], segments["state"]
    )
    theme = path("theme-fields", configuration, segments["theme_fields"])
    history = path("history", configuration, segments["history"])

    item_label = path("item-label", item_context, segments["label"])
    item_relation = path(
        "item-relation", item_context, segments["relation"]
    )
    item_value = path("item-value", item_context, segments["value"])
    item_editable = path(
        "item-editable", item_context, segments["editable"]
    )
    item_control = path(
        "item-control", item_context, segments["control"]
    )
    item_event_fact_input = path(
        "item-event-fact-input",
        item_context,
        segments["event_fact_input"],
    )
    item_presentation_editable = path(
        "item-presentation-editable",
        item_context,
        segments["presentation_editable"],
    )
    item_presentation_control = path(
        "item-presentation-control",
        item_context,
        segments["presentation_control"],
    )
    item_presentation_event_fact_input = path(
        "item-presentation-event-fact-input",
        item_context,
        segments["presentation_event_fact_input"],
    )
    item_presentation_reset = path(
        "item-presentation-reset",
        item_context,
        segments["presentation_reset"],
    )
    item_presentation_reset_control = path(
        "item-presentation-reset-control",
        item_context,
        segments["presentation_reset_control"],
    )
    item_presentation_source = path(
        "item-presentation-source",
        item_context,
        segments["presentation_source"],
    )
    item_presentation_source_mode = path(
        "item-presentation-source-mode",
        item_context,
        segments["presentation_source_mode"],
    )
    item_key = path("item-key", item_context, segments["key"])
    item_value_string = expression(
        "item-value-string", "string", item_value
    )

    selected_truthy = truthy("selected-truthy", selected)
    selected_or_none = expression(
        "selected-or-none",
        "choose",
        selected_truthy,
        expression("selected-string", "string", selected),
        none,
    )
    personal_root = expression(
        "personal-root-string", "string", personal_asset
    )
    is_personal = expression(
        "is-personal", "equals", selected, personal_asset
    )
    is_not_personal = expression(
        "is-not-personal", "not", is_personal
    )

    presentation_label = literal("presentation-label", "presentation")
    icon_label = literal("icon-label", "icon")
    color_label = literal("color-label", "color")
    is_presentation_property = expression(
        "is-presentation-property",
        "member-of",
        item_label,
        color_label,
        icon_label,
        presentation_label,
    )
    presentation_property_count = expression(
        "presentation-property-count",
        "count-where",
        properties,
        is_presentation_property,
    )
    has_nonpersonal_rows = expression(
        "has-nonpersonal-rows",
        "and",
        is_not_personal,
        presentation_property_count,
    )
    section_visible = expression(
        "section-visible", "or", is_personal, has_nonpersonal_rows
    )

    section_subject = expression(
        "section-subject",
        "choose",
        is_personal,
        personal_root,
        selected_or_none,
    )
    section_key = expression(
        "section-key",
        "concat",
        literal("section-key-prefix", "presenter:presentation-list:"),
        section_subject,
    )
    heading_text = expression(
        "heading-text",
        "choose",
        is_personal,
        literal("versioned-theme-heading", "VERSIONED THEME"),
        literal("presentation-heading", "PRESENTATION"),
    )

    relation_text = expression(
        "relation-string", "string", item_relation
    )
    property_row_key = expression(
        "property-row-key",
        "concat",
        literal("property-row-key-prefix", "presentation-row:"),
        relation_text,
    )
    property_label_key = expression(
        "property-label-key",
        "concat",
        property_row_key,
        literal("label-key-suffix", ":label"),
    )
    property_input_key = expression(
        "property-input-key",
        "concat",
        literal("property-input-key-prefix", "presentation-input:"),
        relation_text,
    )
    property_value_key = expression(
        "property-value-key",
        "concat",
        literal("property-value-key-prefix", "presentation-value:"),
        relation_text,
    )
    property_label_text = expression(
        "property-label-text",
        "replace",
        expression("property-label-string", "string", item_label),
        literal("underscore", "_"),
        literal("space", " "),
    )
    property_value_truthy = truthy("property-value-truthy", item_value)
    property_value_text = expression(
        "property-value-text",
        "choose",
        property_value_truthy,
        item_value_string,
        empty,
    )
    editable = truthy("editable-truthy", item_editable)
    not_editable = expression("not-editable", "not", editable)
    presentation_editable = truthy(
        "presentation-editable-truthy", item_presentation_editable
    )
    presentation_reset = truthy(
        "presentation-reset-truthy", item_presentation_reset
    )
    editable_property = expression(
        "editable-presentation-property",
        "and",
        is_not_personal,
        is_presentation_property,
        editable,
    )
    readonly_property = expression(
        "readonly-presentation-property",
        "and",
        is_not_personal,
        is_presentation_property,
        not_editable,
        expression(
            "not-presentation-editable", "not", presentation_editable
        ),
    )
    editable_color = expression(
        "editable-personal-color",
        "and",
        is_not_personal,
        expression("is-color-property", "equals", item_label, color_label),
        presentation_editable,
    )
    resettable_color = expression(
        "resettable-personal-color",
        "and",
        editable_color,
        presentation_reset,
    )
    visible_property_row = expression(
        "visible-property-row",
        "and",
        is_not_personal,
        is_presentation_property,
    )

    item_value_length = expression(
        "item-value-length", "length", item_value_string
    )
    seven_character_value = expression(
        "seven-character-value",
        "equals",
        expression(
            "item-value-length-string", "string", item_value_length
        ),
        seven,
    )
    hash_prefix = expression(
        "hash-prefix",
        "equals",
        expression(
            "item-value-hash-slice",
            "slice",
            item_value_string,
            zero,
            one,
        ),
        hash_character,
    )
    hex_candidates = tuple(
        literal("hex-%s" % value, value)
        for value in (*map(str, range(10)), "A", "B", "C", "D", "E", "F")
    )
    hex_positions = []
    for offset in range(1, 7):
        character = expression(
            "hex-character-%s" % offset,
            "slice",
            item_value_string,
            literal("hex-start-%s" % offset, offset),
            literal("hex-stop-%s" % offset, offset + 1),
        )
        hex_positions.append(expression(
            "hex-character-%s-valid" % offset,
            "member-of",
            expression("hex-character-%s-upper" % offset, "upper", character),
            *hex_candidates,
        ))
    is_hex_color = expression(
        "is-hex-color",
        "and",
        seven_character_value,
        hash_prefix,
        *hex_positions,
    )
    item_input_type = expression(
        "item-input-type",
        "choose",
        is_hex_color,
        color_type,
        text_type,
    )

    property_type_attribute = builder.attribute(
        prefix + ":attribute:property-type", "type", item_input_type
    )
    property_control_attribute = builder.attribute(
        prefix + ":attribute:property-control",
        "data-universal-control",
        item_control,
    )
    property_event_fact_attribute = builder.attribute(
        prefix + ":attribute:property-event-fact",
        "data-universal-event-fact-input",
        item_event_fact_input,
    )
    color_control_attribute = builder.attribute(
        prefix + ":attribute:color-control",
        "data-universal-control",
        item_presentation_control,
    )
    color_event_fact_attribute = builder.attribute(
        prefix + ":attribute:color-event-fact",
        "data-universal-event-fact-input",
        item_presentation_event_fact_input,
    )
    reset_control_attribute = builder.attribute(
        prefix + ":attribute:color-reset-control",
        "data-universal-control",
        item_presentation_reset_control,
    )
    color_source_text = expression(
        "color-source-text",
        "concat",
        expression(
            "color-source-mode-upper",
            "upper",
            item_presentation_source_mode,
        ),
        literal("color-source-separator", " / "),
        expression(
            "color-source-root-string",
            "string",
            item_presentation_source,
        ),
    )
    color_source_key = expression(
        "color-source-key",
        "concat",
        property_row_key,
        literal("color-source-key-suffix", ":source"),
    )
    color_reset_key = expression(
        "color-reset-key",
        "concat",
        property_row_key,
        literal("color-reset-key-suffix", ":reset"),
    )

    theme_name = expression("theme-name", "string", item_key)
    theme_value = item_value_string
    theme_row_key = expression(
        "theme-row-key",
        "concat",
        literal("theme-row-key-prefix", "theme-row:"),
        personal_root,
        colon,
        theme_name,
    )
    theme_label_key = expression(
        "theme-label-key",
        "concat",
        theme_row_key,
        literal("theme-label-key-suffix", ":label"),
    )
    theme_input_key = expression(
        "theme-input-key",
        "concat",
        literal("theme-input-key-prefix", "theme-input:"),
        personal_root,
        colon,
        theme_name,
    )
    theme_label_text = expression(
        "theme-label-text",
        "replace",
        theme_name,
        literal("theme-underscore", "_"),
        literal("theme-space", " "),
    )
    theme_type_attribute = builder.attribute(
        prefix + ":attribute:theme-type", "type", item_input_type
    )
    theme_control_attribute = builder.attribute(
        prefix + ":attribute:theme-control",
        "data-universal-control",
        item_control,
    )
    theme_event_fact_attribute = builder.attribute(
        prefix + ":attribute:theme-event-fact",
        "data-universal-event-fact-input",
        item_event_fact_input,
    )

    state_key = expression(
        "state-key",
        "concat",
        literal("state-key-prefix", "presentation:state:"),
        personal_root,
    )
    state_text = expression(
        "state-text",
        "concat",
        config_state,
        slash,
        expression(
            "display-binding-mode",
            "replace",
            binding_mode,
            minus,
            literal("binding-mode-space", " "),
        ),
        slash,
        preview_revision,
    )
    binding_key = expression(
        "binding-key",
        "concat",
        literal("binding-key-prefix", "presentation:binding:"),
        personal_root,
    )
    binding_text = expression(
        "binding-text",
        "concat",
        literal("active-wire-prefix", "ACTIVE WIRE "),
        binding,
        literal("court-prefix", " / COURT "),
        expression("court-state-upper", "upper", court_state),
    )

    history_length = expression("history-length", "length", history)
    index_string = expression("history-index-string", "string", index_context)
    index_plus_one = expression(
        "history-index-plus-one", "add", index_context, one
    )
    reverse_start = expression(
        "history-reverse-start",
        "concat",
        minus,
        expression(
            "history-index-plus-one-string", "string", index_plus_one
        ),
    )
    reverse_stop = expression(
        "history-reverse-stop",
        "choose",
        expression("history-index-is-zero", "equals", index_string, zero),
        history_length,
        expression(
            "history-negative-index", "concat", minus, index_string
        ),
    )
    reversed_history_slice = expression(
        "reversed-history-slice",
        "slice",
        history,
        reverse_start,
        reverse_stop,
    )
    history_item = path(
        "reversed-history-item", reversed_history_slice, zero_item_segment
    )
    history_revision = path(
        "history-revision", history_item, segments["revision"]
    )
    history_revision_text = expression(
        "history-revision-string", "string", history_revision
    )
    history_state = path(
        "history-state", history_item, segments["state"]
    )
    history_reason = path(
        "history-reason", history_item, segments["reason"]
    )
    history_digest = path(
        "history-digest", history_item, segments["digest"]
    )
    history_digest_text = expression(
        "history-digest-string", "string", history_digest
    )
    history_evidence = path(
        "history-evidence", history_item, segments["evidence"]
    )
    history_current = path(
        "history-current", history_item, segments["current"]
    )
    history_restore_control = path(
        "history-restore-control", history_item, segments["restore_control"]
    )
    current_truthy = truthy("history-current-truthy", history_current)
    history_reason_truthy = truthy(
        "history-reason-truthy", history_reason
    )
    history_reason_text = expression(
        "history-reason-text",
        "choose",
        history_reason_truthy,
        expression("history-reason-string", "string", history_reason),
        literal("initial-reason", "initial"),
    )
    history_row_key = expression(
        "history-row-key",
        "concat",
        literal("history-row-key-prefix", "theme-history-row:"),
        history_revision_text,
    )
    history_label_key = expression(
        "history-label-key",
        "concat",
        literal("history-label-key-prefix", "theme-history-label:"),
        history_revision_text,
    )
    history_label_text = expression(
        "history-label-text",
        "concat",
        history_state,
        slash,
        history_reason_text,
        slash,
        expression(
            "history-digest-prefix",
            "slice",
            history_digest_text,
            zero,
            literal("history-digest-stop", "10"),
        ),
        literal("evidence-count-prefix", " / "),
        expression(
            "history-evidence-length-string",
            "string",
            expression(
                "history-evidence-length", "length", history_evidence
            ),
        ),
        literal("evidence-count-suffix", " evidence"),
    )
    restore_key = expression(
        "restore-key",
        "concat",
        literal("restore-key-prefix", "theme-restore:"),
        history_revision_text,
    )
    restore_text = expression(
        "restore-text",
        "choose",
        current_truthy,
        literal("current-wip", "CURRENT WIP"),
        literal("restore-as-wip", "RESTORE AS NEW WIP"),
    )
    restore_type_attribute = builder.attribute(
        prefix + ":attribute:restore-type", "type", button_type
    )
    restore_disabled_attribute = builder.attribute(
        prefix + ":attribute:restore-disabled", "disabled", current_truthy
    )
    restore_control_attribute = builder.attribute(
        prefix + ":attribute:restore-control",
        "data-universal-control",
        history_restore_control,
    )

    evidence_root_value = path(
        "evidence-root-value", item_context, segments["root"]
    )
    evidence_digest = path(
        "evidence-digest", item_context, segments["digest"]
    )
    evidence_root_truthy = truthy(
        "evidence-root-truthy", evidence_root_value
    )
    evidence_root = expression(
        "evidence-root",
        "choose",
        evidence_root_truthy,
        expression("evidence-root-string", "string", evidence_root_value),
        expression("evidence-digest-string", "string", evidence_digest),
    )
    evidence_checks = path(
        "evidence-checks", item_context, segments["checks"]
    )
    check_value = path("check-value", item_context, segments["value"])
    check_truthy = truthy("check-truthy", check_value)
    passed_checks = expression(
        "passed-checks", "count-where", evidence_checks, check_truthy
    )
    evidence_result = path(
        "evidence-result", item_context, segments["result"]
    )
    evidence_builder = path(
        "evidence-builder", item_context, segments["builder"]
    )
    evidence_duration = path(
        "evidence-duration", item_context, segments["duration_ms"]
    )
    evidence_key = expression(
        "evidence-key",
        "concat",
        literal("evidence-key-prefix", "theme-evidence:"),
        evidence_root,
    )
    evidence_summary_key = expression(
        "evidence-summary-key",
        "concat",
        literal("evidence-summary-key-prefix", "theme-evidence-summary:"),
        evidence_root,
    )
    evidence_summary_text = expression(
        "evidence-summary-text",
        "concat",
        expression("evidence-result-upper", "upper", evidence_result),
        literal("court-checks-prefix", " COURT / "),
        passed_checks,
        literal("court-checks-middle", " OF "),
        expression("evidence-check-count", "length", evidence_checks),
        literal("court-checks-suffix", " CHECKS"),
    )
    evidence_meta_key = expression(
        "evidence-meta-key",
        "concat",
        literal("evidence-meta-key-prefix", "theme-evidence-meta:"),
        evidence_root,
    )
    evidence_meta_text = expression(
        "evidence-meta-text",
        "concat",
        evidence_builder,
        slash,
        evidence_duration,
        literal("milliseconds-suffix", " ms / "),
        expression(
            "evidence-digest-prefix",
            "slice",
            expression(
                "evidence-digest-text", "string", evidence_digest
            ),
            zero,
            literal("evidence-digest-stop", "12"),
        ),
    )

    parent_evidence_root_value = path(
        "parent-evidence-root-value", parent_context, segments["root"]
    )
    parent_evidence_digest = path(
        "parent-evidence-digest", parent_context, segments["digest"]
    )
    parent_evidence_root_truthy = truthy(
        "parent-evidence-root-truthy", parent_evidence_root_value
    )
    parent_evidence_root = expression(
        "parent-evidence-root",
        "choose",
        parent_evidence_root_truthy,
        expression(
            "parent-evidence-root-string",
            "string",
            parent_evidence_root_value,
        ),
        expression(
            "parent-evidence-digest-string",
            "string",
            parent_evidence_digest,
        ),
    )
    check_name = expression("check-name", "string", item_key)
    check_key = expression(
        "check-key",
        "concat",
        literal("check-key-prefix", "theme-check:"),
        parent_evidence_root,
        colon,
        check_name,
    )
    check_text = expression(
        "check-text",
        "concat",
        expression(
            "check-result-text",
            "choose",
            check_truthy,
            literal("check-pass", "PASS"),
            literal("check-fail", "FAIL"),
        ),
        literal("check-label-space", " "),
        expression(
            "check-display-name",
            "replace",
            check_name,
            literal("check-hyphen", "-"),
            literal("check-space", " "),
        ),
    )

    history_key = expression(
        "history-key",
        "concat",
        literal("history-key-prefix", "theme-history:"),
        personal_root,
    )
    history_summary_key = expression(
        "history-summary-key",
        "concat",
        literal("history-summary-key-prefix", "theme-history-summary:"),
        personal_root,
    )
    history_summary_text = expression(
        "history-summary-text",
        "concat",
        literal("history-summary-prefix", "PREVIEW HISTORY / "),
        history_length,
    )

    published_revision = path(
        "published-revision", configuration, segment("published_revision")
    )
    shared_revision = path(
        "shared-revision", configuration, segment("shared_revision")
    )
    can_publish_value = path(
        "can-publish", configuration, segment("can_publish")
    )
    can_promote_value = path(
        "can-promote", configuration, segment("can_promote")
    )
    published_truthy = truthy("published-truthy", published_revision)
    shared_truthy = truthy("shared-truthy", shared_revision)
    can_publish = truthy("can-publish-truthy", can_publish_value)
    can_promote = truthy("can-promote-truthy", can_promote_value)
    action_text = expression(
        "action-text",
        "choose",
        published_truthy,
        literal("published-action", "PUBLISHED / BROWSER COURT PASSED"),
        expression(
            "unpublished-action-text",
            "choose",
            can_publish,
            literal(
                "publish-action", "RUN BROWSER COURT + PUBLISH"
            ),
            expression(
                "unpublishable-action-text",
                "choose",
                can_promote,
                literal("promote-action", "RUN COURT + SHARE"),
                expression(
                    "unpromotable-action-text",
                    "choose",
                    shared_truthy,
                    literal(
                        "shared-action",
                        "SHARED / PUBLISH COURT UNAVAILABLE",
                    ),
                    literal(
                        "authority-action",
                        "SHARE REQUIRES FOUNDER AUTHORITY",
                    ),
                ),
            ),
        ),
    )
    action_key = expression(
        "action-key",
        "concat",
        literal("action-key-prefix", "theme-court-action:"),
        personal_root,
    )
    action_enabled = expression(
        "action-enabled", "or", can_promote, can_publish
    )
    action_disabled = expression(
        "action-disabled", "not", action_enabled
    )
    missing_attribute = path(
        "missing-attribute", item_context, absent_segment
    )
    publish_attribute_value = expression(
        "publish-attribute-value",
        "choose",
        can_publish,
        expression("shared-revision-string", "string", shared_revision),
        missing_attribute,
    )
    share_attribute_value = expression(
        "share-attribute-value",
        "choose",
        can_publish,
        missing_attribute,
        expression("preview-revision-string", "string", preview_revision),
    )
    action_type_attribute = builder.attribute(
        prefix + ":attribute:action-type", "type", button_type
    )
    action_disabled_attribute = builder.attribute(
        prefix + ":attribute:action-disabled", "disabled", action_disabled
    )
    action_publish_attribute = builder.attribute(
        prefix + ":attribute:action-publish",
        "data-universal-theme-publish",
        publish_attribute_value,
    )
    action_share_attribute = builder.attribute(
        prefix + ":attribute:action-share",
        "data-universal-theme-share",
        share_attribute_value,
    )

    builder.template(
        _HEADING_ROOT,
        tag=literal("heading-tag", "div"),
        key=literal("heading-key", "presentation:heading"),
        class_name=literal("heading-class", "inspector-heading"),
        text=heading_text,
    )
    builder.template(
        PRESENTATION_LIST_PREFIX + ":property-label",
        tag=literal("property-label-tag", "span"),
        key=property_label_key,
        class_name=literal("property-label-class", "property-label"),
        text=property_label_text,
    )
    builder.template(
        _PROPERTY_INPUT_ROOT,
        tag=literal("property-input-tag", "input"),
        key=property_input_key,
        class_name=literal("property-input-class", "property-input"),
        value=property_value_text,
        attributes=(
            property_type_attribute,
            property_control_attribute,
            property_event_fact_attribute,
        ),
        condition=editable_property,
    )
    builder.template(
        _PROPERTY_VALUE_ROOT,
        tag=literal("property-value-tag", "div"),
        key=property_value_key,
        class_name=literal("property-value-class", "connection-box"),
        text=property_value_text,
        condition=readonly_property,
    )
    builder.template(
        _COLOR_INPUT_ROOT,
        tag=literal("color-input-tag", "input"),
        key=expression(
            "color-input-key",
            "concat",
            property_input_key,
            literal("color-input-key-suffix", ":personal"),
        ),
        class_name=literal("color-input-class", "property-input"),
        value=property_value_text,
        attributes=(
            property_type_attribute,
            color_control_attribute,
            color_event_fact_attribute,
        ),
        condition=editable_color,
    )
    builder.template(
        _COLOR_SOURCE_ROOT,
        tag=literal("color-source-tag", "div"),
        key=color_source_key,
        class_name=literal("color-source-class", "presentation-source"),
        text=color_source_text,
        condition=editable_color,
    )
    builder.template(
        _COLOR_RESET_ROOT,
        tag=literal("color-reset-tag", "button"),
        key=color_reset_key,
        class_name=literal("color-reset-class", "presentation-reset"),
        text=literal("color-reset-text", "RESET"),
        attributes=(
            builder.attribute(
                prefix + ":attribute:color-reset-type",
                "type",
                button_type,
            ),
            reset_control_attribute,
        ),
        condition=resettable_color,
    )
    builder.template(
        _PROPERTY_ROW_ROOT,
        tag=literal("property-row-tag", "label"),
        key=property_row_key,
        class_name=literal("property-row-class", "property-row"),
        children=(
            PRESENTATION_LIST_PREFIX + ":property-label",
            _PROPERTY_INPUT_ROOT,
            _COLOR_INPUT_ROOT,
            _PROPERTY_VALUE_ROOT,
            _COLOR_SOURCE_ROOT,
            _COLOR_RESET_ROOT,
        ),
        repeat=properties,
        condition=visible_property_row,
    )

    builder.template(
        PRESENTATION_LIST_PREFIX + ":state",
        tag=literal("state-tag", "div"),
        key=state_key,
        class_name=literal("state-class", "connection-box"),
        text=state_text,
        condition=is_personal,
    )
    builder.template(
        PRESENTATION_LIST_PREFIX + ":binding",
        tag=literal("binding-tag", "div"),
        key=binding_key,
        class_name=literal("binding-class", "connection-box"),
        text=binding_text,
        condition=is_personal,
    )
    builder.template(
        PRESENTATION_LIST_PREFIX + ":theme-label",
        tag=literal("theme-label-tag", "span"),
        key=theme_label_key,
        class_name=literal("theme-label-class", "property-label"),
        text=theme_label_text,
    )
    builder.template(
        _THEME_INPUT_ROOT,
        tag=literal("theme-input-tag", "input"),
        key=theme_input_key,
        class_name=literal("theme-input-class", "property-input"),
        value=theme_value,
        attributes=(
            theme_type_attribute,
            theme_control_attribute,
            theme_event_fact_attribute,
        ),
    )
    builder.template(
        PRESENTATION_LIST_PREFIX + ":theme-row",
        tag=literal("theme-row-tag", "label"),
        key=theme_row_key,
        class_name=literal("theme-row-class", "property-row"),
        children=(
            PRESENTATION_LIST_PREFIX + ":theme-label",
            _THEME_INPUT_ROOT,
        ),
        repeat=theme,
        condition=is_personal,
    )

    builder.template(
        PRESENTATION_LIST_PREFIX + ":history-label",
        tag=literal("history-label-tag", "span"),
        key=history_label_key,
        class_name=literal("history-label-class", "property-label"),
        text=history_label_text,
    )
    builder.template(
        PRESENTATION_LIST_PREFIX + ":restore",
        tag=literal("restore-tag", "button"),
        key=restore_key,
        class_name=literal("restore-class", "operational-action"),
        text=restore_text,
        attributes=(
            restore_type_attribute,
            restore_disabled_attribute,
            restore_control_attribute,
        ),
    )
    builder.template(
        PRESENTATION_LIST_PREFIX + ":evidence-summary",
        tag=literal("evidence-summary-tag", "summary"),
        key=evidence_summary_key,
        class_name=literal(
            "evidence-summary-class", "property-label"
        ),
        text=evidence_summary_text,
    )
    builder.template(
        PRESENTATION_LIST_PREFIX + ":evidence-meta",
        tag=literal("evidence-meta-tag", "div"),
        key=evidence_meta_key,
        class_name=literal("evidence-meta-class", "connection-box"),
        text=evidence_meta_text,
    )
    builder.template(
        PRESENTATION_LIST_PREFIX + ":check",
        tag=literal("check-tag", "div"),
        key=check_key,
        class_name=literal("check-class", "court-check"),
        text=check_text,
        repeat=evidence_checks,
    )
    builder.template(
        _EVIDENCE_ROOT,
        tag=literal("evidence-tag", "details"),
        key=evidence_key,
        class_name=literal("evidence-class", "court-evidence"),
        children=(
            PRESENTATION_LIST_PREFIX + ":evidence-summary",
            PRESENTATION_LIST_PREFIX + ":evidence-meta",
            PRESENTATION_LIST_PREFIX + ":check",
        ),
        repeat=history_evidence,
    )
    builder.template(
        PRESENTATION_LIST_PREFIX + ":history-row",
        tag=literal("history-row-tag", "div"),
        key=history_row_key,
        class_name=literal("history-row-class", "property-row"),
        children=(
            PRESENTATION_LIST_PREFIX + ":history-label",
            PRESENTATION_LIST_PREFIX + ":restore",
            _EVIDENCE_ROOT,
        ),
        repeat=history,
    )
    builder.template(
        PRESENTATION_LIST_PREFIX + ":history-summary",
        tag=literal("history-summary-tag", "summary"),
        key=history_summary_key,
        class_name=literal(
            "history-summary-class", "inspector-heading"
        ),
        text=history_summary_text,
    )
    builder.template(
        _HISTORY_ROOT,
        tag=literal("history-tag", "details"),
        key=history_key,
        class_name=literal("history-class", "inspector-section"),
        children=(
            PRESENTATION_LIST_PREFIX + ":history-summary",
            PRESENTATION_LIST_PREFIX + ":history-row",
        ),
        condition=is_personal,
    )
    builder.template(
        _ACTION_ROOT,
        tag=literal("action-tag", "button"),
        key=action_key,
        class_name=literal("action-class", "operational-action"),
        text=action_text,
        attributes=(
            action_type_attribute,
            action_disabled_attribute,
            action_publish_attribute,
            action_share_attribute,
        ),
        condition=is_personal,
    )
    builder.template(
        PRESENTATION_LIST_TEMPLATE_ROOT,
        tag=literal("section-tag", "section"),
        key=section_key,
        class_name=literal("section-class", "inspector-section"),
        children=(
            _HEADING_ROOT,
            _PROPERTY_ROW_ROOT,
            PRESENTATION_LIST_PREFIX + ":state",
            PRESENTATION_LIST_PREFIX + ":binding",
            PRESENTATION_LIST_PREFIX + ":theme-row",
            _HISTORY_ROOT,
            _ACTION_ROOT,
        ),
        condition=section_visible,
    )
    return PRESENTATION_LIST_TEMPLATE_ROOT


__all__ = [
    "LEGACY_PRESENTATION_LIST_PREFIX",
    "LEGACY_PRESENTATION_LIST_TEMPLATE_MEMBER_ROOTS",
    "LEGACY_PRESENTATION_LIST_TEMPLATE_ROOT",
    "PREINTERACTION_PRESENTATION_LIST_PREFIX",
    "PREINTERACTION_PRESENTATION_LIST_TEMPLATE_MEMBER_ROOTS",
    "PREINTERACTION_PRESENTATION_LIST_TEMPLATE_ROOT",
    "PREAPPEARANCE_PRESENTATION_LIST_PREFIX",
    "PREAPPEARANCE_PRESENTATION_LIST_TEMPLATE_MEMBER_ROOTS",
    "PREAPPEARANCE_PRESENTATION_LIST_TEMPLATE_ROOT",
    "PRETHEME_PRESENTATION_LIST_PREFIX",
    "PRETHEME_PRESENTATION_LIST_TEMPLATE_MEMBER_ROOTS",
    "PRETHEME_PRESENTATION_LIST_TEMPLATE_ROOT",
    "PRESENTATION_LIST_PREFIX",
    "PRESENTATION_LIST_TEMPLATE_MEMBER_ROOTS",
    "PRESENTATION_LIST_TEMPLATE_ROOT",
    "VIEW_TEMPLATE_PREFIX",
    "compose_presentation_list_template",
]
