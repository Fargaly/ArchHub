"""Graph-authored standard Properties presenters.

These functions seed released assemblies. Runtime presentation comes only from
the persisted relations interpreted by ``cell_view_template``; the function
names and Python control flow below are not consulted during projection.
"""
from __future__ import annotations

from .cell_protocols import CellBatch
from .cell_view_template import ViewTemplateBuilder, ViewTemplateProtocol


VIEW_TEMPLATE_PREFIX = "app:view-template-protocol"
LEGACY_FIELD_LIST_PREFIX = "app:properties-template:field-list:v1"
LEGACY_FIELD_LIST_TEMPLATE_ROOT = LEGACY_FIELD_LIST_PREFIX + ":section"
LEGACY_FIELD_LIST_TEMPLATE_MEMBER_ROOTS = (
    LEGACY_FIELD_LIST_TEMPLATE_ROOT,
    LEGACY_FIELD_LIST_PREFIX + ":heading",
    LEGACY_FIELD_LIST_PREFIX + ":row",
    LEGACY_FIELD_LIST_PREFIX + ":property-label",
    LEGACY_FIELD_LIST_PREFIX + ":editable-input",
    LEGACY_FIELD_LIST_PREFIX + ":read-only-value",
)
INTERMEDIATE_FIELD_LIST_PREFIX = "app:properties-template:field-list:v2"
INTERMEDIATE_FIELD_LIST_TEMPLATE_ROOT = (
    INTERMEDIATE_FIELD_LIST_PREFIX + ":section"
)
INTERMEDIATE_FIELD_LIST_TEMPLATE_MEMBER_ROOTS = (
    INTERMEDIATE_FIELD_LIST_TEMPLATE_ROOT,
    INTERMEDIATE_FIELD_LIST_PREFIX + ":heading",
    INTERMEDIATE_FIELD_LIST_PREFIX + ":row",
    INTERMEDIATE_FIELD_LIST_PREFIX + ":property-label",
    INTERMEDIATE_FIELD_LIST_PREFIX + ":editable-input",
    INTERMEDIATE_FIELD_LIST_PREFIX + ":read-only-value",
    INTERMEDIATE_FIELD_LIST_PREFIX + ":property-create",
    INTERMEDIATE_FIELD_LIST_PREFIX + ":new-property-label",
    INTERMEDIATE_FIELD_LIST_PREFIX + ":new-property-value",
    INTERMEDIATE_FIELD_LIST_PREFIX + ":add-property-button",
)
GRAPH_FORM_FIELD_LIST_PREFIX = "app:properties-template:field-list:v3"
GRAPH_FORM_FIELD_LIST_TEMPLATE_ROOT = GRAPH_FORM_FIELD_LIST_PREFIX + ":section"
GRAPH_FORM_FIELD_LIST_TEMPLATE_MEMBER_ROOTS = (
    GRAPH_FORM_FIELD_LIST_TEMPLATE_ROOT,
    GRAPH_FORM_FIELD_LIST_PREFIX + ":heading",
    GRAPH_FORM_FIELD_LIST_PREFIX + ":row",
    GRAPH_FORM_FIELD_LIST_PREFIX + ":property-label",
    GRAPH_FORM_FIELD_LIST_PREFIX + ":editable-input",
    GRAPH_FORM_FIELD_LIST_PREFIX + ":read-only-value",
    GRAPH_FORM_FIELD_LIST_PREFIX + ":property-create",
    GRAPH_FORM_FIELD_LIST_PREFIX + ":new-property-label",
    GRAPH_FORM_FIELD_LIST_PREFIX + ":new-property-value",
    GRAPH_FORM_FIELD_LIST_PREFIX + ":add-property-button",
)
PREINTERACTION_FIELD_LIST_PREFIX = "app:properties-template:field-list:v4"
PREINTERACTION_FIELD_LIST_TEMPLATE_ROOT = (
    PREINTERACTION_FIELD_LIST_PREFIX + ":section"
)
PREINTERACTION_FIELD_LIST_TEMPLATE_MEMBER_ROOTS = (
    PREINTERACTION_FIELD_LIST_TEMPLATE_ROOT,
    PREINTERACTION_FIELD_LIST_PREFIX + ":heading",
    PREINTERACTION_FIELD_LIST_PREFIX + ":row",
    PREINTERACTION_FIELD_LIST_PREFIX + ":property-label",
    PREINTERACTION_FIELD_LIST_PREFIX + ":editable-input",
    PREINTERACTION_FIELD_LIST_PREFIX + ":read-only-value",
    PREINTERACTION_FIELD_LIST_PREFIX + ":property-create",
    PREINTERACTION_FIELD_LIST_PREFIX + ":new-property-label",
    PREINTERACTION_FIELD_LIST_PREFIX + ":new-property-value",
    PREINTERACTION_FIELD_LIST_PREFIX + ":add-property-button",
)
FIELD_LIST_PREFIX = "app:properties-template:field-list:v5"
FIELD_LIST_TEMPLATE_ROOT = FIELD_LIST_PREFIX + ":section"
FIELD_LIST_TEMPLATE_MEMBER_ROOTS = (
    FIELD_LIST_TEMPLATE_ROOT,
    FIELD_LIST_PREFIX + ":heading",
    FIELD_LIST_PREFIX + ":row",
    FIELD_LIST_PREFIX + ":property-label",
    FIELD_LIST_PREFIX + ":editable-input",
    FIELD_LIST_PREFIX + ":read-only-value",
    FIELD_LIST_PREFIX + ":property-create",
    FIELD_LIST_PREFIX + ":new-property-label",
    FIELD_LIST_PREFIX + ":new-property-value",
    FIELD_LIST_PREFIX + ":add-property-button",
)


def compose_field_list_template(
    batch: CellBatch,
    protocol: ViewTemplateProtocol,
) -> str:
    """Compose the editable property list as visible, rewritable relations."""
    builder = ViewTemplateBuilder(batch, protocol)
    prefix = FIELD_LIST_PREFIX

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

    root_context = builder.expression(
        prefix + ":expression:root-context", "root"
    )
    item_context = builder.expression(
        prefix + ":expression:item-context", "item"
    )
    selected_segment = segment("selected")
    properties_segment = segment("properties")
    relation_segment = segment("relation")
    label_segment = segment("label")
    value_segment = segment("value")
    mixed_segment = segment("mixed")
    editable_segment = segment("editable")
    control_segment = builder.atom(
        prefix + ":segment:item-control", "control"
    )
    event_fact_input_segment = segment("event_fact_input")
    authoring_segment = segment("authoring")
    add_property_segment = segment("add_property")
    property_form_segment = segment("property_form")
    form_root_segment = segment("root")
    form_inputs_segment = segment("inputs")
    form_control_segment = control_segment
    form_control_label_segment = segment("control_label")
    form_control_title_segment = segment("control_title")
    form_control_binding_segment = segment("control_binding")
    form_control_capability_segment = segment("control_capability")
    form_control_icon_segment = segment("control_icon")
    form_operation_segment = segment("operation")
    form_operation_path_segment = segment("operation_path")
    label_input_segment = label_segment
    value_input_segment = value_segment
    absent_segment = segment("attribute-not-present")

    selected = path("selected", root_context, selected_segment)
    properties = path("properties", root_context, properties_segment)
    relation = path("relation", item_context, relation_segment)
    label = path("label", item_context, label_segment)
    value = path("value", item_context, value_segment)
    mixed = path("mixed", item_context, mixed_segment)
    editable = path("editable", item_context, editable_segment)
    control = path("control", item_context, control_segment)
    event_fact_input = path(
        "event-fact-input", item_context, event_fact_input_segment
    )
    authoring = path("authoring", root_context, authoring_segment)
    add_property_path = path(
        "add-property", authoring, add_property_segment
    )
    property_form = path(
        "property-form", authoring, property_form_segment
    )
    property_form_root = path(
        "property-form-root", property_form, form_root_segment
    )
    property_form_inputs = path(
        "property-form-inputs", property_form, form_inputs_segment
    )
    property_label_input = path(
        "property-label-input", property_form_inputs, label_input_segment
    )
    property_value_input = path(
        "property-value-input", property_form_inputs, value_input_segment
    )
    property_form_control = path(
        "property-form-control", property_form, form_control_segment
    )
    property_form_control_label = path(
        "property-form-control-label",
        property_form,
        form_control_label_segment,
    )
    property_form_control_title = path(
        "property-form-control-title",
        property_form,
        form_control_title_segment,
    )
    property_form_control_binding = path(
        "property-form-control-binding",
        property_form,
        form_control_binding_segment,
    )
    property_form_control_capability = path(
        "property-form-control-capability",
        property_form,
        form_control_capability_segment,
    )
    property_form_control_icon = path(
        "property-form-control-icon",
        property_form,
        form_control_icon_segment,
    )
    property_form_operation = path(
        "property-form-operation", property_form, form_operation_segment
    )
    property_form_operation_path = path(
        "property-form-operation-path",
        property_form,
        form_operation_path_segment,
    )
    absent = path("attribute-not-present", item_context, absent_segment)
    not_editable = builder.expression(
        prefix + ":expression:not-editable", "not", (editable,)
    )

    empty = literal("empty", "")
    none = literal("none", "none")
    false = builder.expression(
        prefix + ":expression:false",
        "equals",
        (literal("false-left", "false"), literal("false-right", "true")),
    )
    add_property = builder.expression(
        prefix + ":expression:add-property-or-false",
        "fallback",
        (add_property_path, false),
    )
    selected_or_none = builder.expression(
        prefix + ":expression:selected-or-none",
        "fallback",
        (selected, none),
    )
    value_or_empty = builder.expression(
        prefix + ":expression:value-or-empty",
        "fallback",
        (value, empty),
    )
    label_or_empty = builder.expression(
        prefix + ":expression:label-or-empty",
        "fallback",
        (label, empty),
    )
    input_value = builder.expression(
        prefix + ":expression:input-value",
        "choose",
        (mixed, empty, value_or_empty),
    )

    section_key = builder.expression(
        prefix + ":expression:section-key",
        "concat",
        (literal("section-key-prefix", "presenter:field-list:"), selected_or_none),
    )
    row_key = builder.expression(
        prefix + ":expression:row-key",
        "concat",
        (literal("row-key-prefix", "property-row:"), relation),
    )
    label_key = builder.expression(
        prefix + ":expression:label-key",
        "concat",
        (row_key, literal("label-key-suffix", ":label")),
    )
    input_key = builder.expression(
        prefix + ":expression:input-key",
        "concat",
        (literal("input-key-prefix", "property-input:"), relation),
    )
    value_key = builder.expression(
        prefix + ":expression:value-key",
        "concat",
        (literal("value-key-prefix", "property-value:"), relation),
    )
    create_key = builder.expression(
        prefix + ":expression:create-key",
        "concat",
        (literal("create-key-prefix", "property-create:"), selected_or_none),
    )
    display_label = builder.expression(
        prefix + ":expression:display-label",
        "replace",
        (label_or_empty, literal("underscore", "_"), literal("space", " ")),
    )

    numeric = builder.expression(
        prefix + ":expression:is-numeric",
        "member-of",
        (
            label_or_empty,
            literal("position-x", "position_x"),
            literal("position-y", "position_y"),
            literal("width", "width"),
        ),
    )
    color = builder.expression(
        prefix + ":expression:is-color",
        "equals",
        (label_or_empty, literal("color", "color")),
    )
    number_or_text = builder.expression(
        prefix + ":expression:number-or-text",
        "choose",
        (numeric, literal("number", "number"), literal("text", "text")),
    )
    input_type = builder.expression(
        prefix + ":expression:input-type",
        "choose",
        (color, literal("color-input", "color"), number_or_text),
    )
    input_step = builder.expression(
        prefix + ":expression:input-step",
        "choose",
        (numeric, literal("any-step", "any"), absent),
    )

    type_attribute = builder.attribute(
        prefix + ":attribute:input-type", "type", input_type
    )
    control_attribute = builder.attribute(
        prefix + ":attribute:control-root",
        "data-universal-control",
        control,
    )
    event_fact_input_attribute = builder.attribute(
        prefix + ":attribute:event-fact-input",
        "data-universal-event-fact-input",
        event_fact_input,
    )
    step_attribute = builder.attribute(
        prefix + ":attribute:input-step", "step", input_step
    )
    mixed_placeholder = builder.expression(
        prefix + ":expression:mixed-placeholder",
        "choose",
        (mixed, literal("varies-placeholder", "Varies"), absent),
    )
    mixed_marker = builder.expression(
        prefix + ":expression:mixed-marker",
        "choose",
        (mixed, literal("mixed-marker-true", "true"), absent),
    )
    mixed_aria = builder.expression(
        prefix + ":expression:mixed-aria",
        "choose",
        (
            mixed,
            builder.expression(
                prefix + ":expression:mixed-aria-label",
                "concat",
                (
                    display_label,
                    literal(
                        "mixed-aria-suffix", "; values vary across selection"
                    ),
                ),
            ),
            absent,
        ),
    )
    mixed_placeholder_attribute = builder.attribute(
        prefix + ":attribute:mixed-placeholder",
        "placeholder",
        mixed_placeholder,
    )
    mixed_marker_attribute = builder.attribute(
        prefix + ":attribute:mixed-marker",
        "data-universal-mixed",
        mixed_marker,
    )
    mixed_aria_attribute = builder.attribute(
        prefix + ":attribute:mixed-aria",
        "aria-label",
        mixed_aria,
    )
    text_type_attribute = builder.attribute(
        prefix + ":attribute:new-property-type",
        "type",
        literal("new-property-type", "text"),
    )
    label_placeholder_attribute = builder.attribute(
        prefix + ":attribute:new-property-label-placeholder",
        "placeholder",
        literal("new-property-label-placeholder", "Parameter name"),
    )
    value_placeholder_attribute = builder.attribute(
        prefix + ":attribute:new-property-value-placeholder",
        "placeholder",
        literal("new-property-value-placeholder", "Initial value"),
    )
    label_aria_attribute = builder.attribute(
        prefix + ":attribute:new-property-label-aria",
        "aria-label",
        literal("new-property-label-aria", "Parameter name"),
    )
    value_aria_attribute = builder.attribute(
        prefix + ":attribute:new-property-value-aria",
        "aria-label",
        literal("new-property-value-aria", "Initial value"),
    )
    button_type_attribute = builder.attribute(
        prefix + ":attribute:add-property-button-type",
        "type",
        literal("add-property-button-type", "button"),
    )
    relation_form_attribute = builder.attribute(
        prefix + ":attribute:relation-form",
        "data-universal-relation-form",
        property_form_root,
    )
    relation_form_operation_attribute = builder.attribute(
        prefix + ":attribute:relation-form-operation",
        "data-universal-relation-form-operation",
        property_form_operation,
    )
    relation_form_path_attribute = builder.attribute(
        prefix + ":attribute:relation-form-path",
        "data-universal-relation-form-path",
        property_form_operation_path,
    )
    label_form_field_attribute = builder.attribute(
        prefix + ":attribute:label-form-field",
        "data-universal-relation-form-field",
        literal("label-form-field", "label"),
    )
    value_form_field_attribute = builder.attribute(
        prefix + ":attribute:value-form-field",
        "data-universal-relation-form-field",
        literal("value-form-field", "value"),
    )
    label_form_input_attribute = builder.attribute(
        prefix + ":attribute:label-form-input",
        "data-universal-relation-form-input",
        property_label_input,
    )
    value_form_input_attribute = builder.attribute(
        prefix + ":attribute:value-form-input",
        "data-universal-relation-form-input",
        property_value_input,
    )
    form_submit_attribute = builder.attribute(
        prefix + ":attribute:relation-form-submit",
        "data-universal-relation-form-submit",
        property_form_root,
    )
    form_control_attribute = builder.attribute(
        prefix + ":attribute:relation-form-control",
        "data-universal-control",
        property_form_control,
    )
    form_control_binding_attribute = builder.attribute(
        prefix + ":attribute:relation-form-control-binding",
        "data-control-binding",
        property_form_control_binding,
    )
    form_control_capability_attribute = builder.attribute(
        prefix + ":attribute:relation-form-control-capability",
        "data-control-capability",
        property_form_control_capability,
    )
    form_control_icon_attribute = builder.attribute(
        prefix + ":attribute:relation-form-control-icon",
        "data-control-icon",
        property_form_control_icon,
    )
    form_control_title_attribute = builder.attribute(
        prefix + ":attribute:relation-form-control-title",
        "title",
        property_form_control_title,
    )
    form_control_aria_attribute = builder.attribute(
        prefix + ":attribute:relation-form-control-aria",
        "aria-label",
        property_form_control_title,
    )

    builder.template(
        FIELD_LIST_PREFIX + ":property-label",
        tag=literal("span-tag", "span"),
        key=label_key,
        class_name=literal("property-label-class", "property-label"),
        text=display_label,
    )
    builder.template(
        FIELD_LIST_PREFIX + ":editable-input",
        tag=literal("input-tag", "input"),
        key=input_key,
        class_name=literal("property-input-class", "property-input"),
        value=input_value,
        attributes=(
            type_attribute,
            control_attribute,
            event_fact_input_attribute,
            step_attribute,
            mixed_placeholder_attribute,
            mixed_marker_attribute,
            mixed_aria_attribute,
        ),
        condition=editable,
    )
    builder.template(
        FIELD_LIST_PREFIX + ":read-only-value",
        tag=literal("div-tag", "div"),
        key=value_key,
        class_name=literal("connection-box-class", "connection-box"),
        text=value_or_empty,
        condition=not_editable,
    )
    builder.template(
        FIELD_LIST_PREFIX + ":row",
        tag=literal("label-tag", "label"),
        key=row_key,
        class_name=literal("property-row-class", "property-row"),
        children=(
            FIELD_LIST_PREFIX + ":property-label",
            FIELD_LIST_PREFIX + ":editable-input",
            FIELD_LIST_PREFIX + ":read-only-value",
        ),
        repeat=properties,
    )
    builder.template(
        FIELD_LIST_PREFIX + ":new-property-label",
        tag=literal("new-property-label-tag", "input"),
        key=literal("new-property-label-key", "property-create:label"),
        class_name=literal(
            "new-property-label-class", "property-input"
        ),
        value=empty,
        attributes=(
            text_type_attribute,
            label_placeholder_attribute,
            label_aria_attribute,
            label_form_field_attribute,
            label_form_input_attribute,
        ),
    )
    builder.template(
        FIELD_LIST_PREFIX + ":new-property-value",
        tag=literal("new-property-value-tag", "input"),
        key=literal("new-property-value-key", "property-create:value"),
        class_name=literal(
            "new-property-value-class", "property-input"
        ),
        value=empty,
        attributes=(
            text_type_attribute,
            value_placeholder_attribute,
            value_aria_attribute,
            value_form_field_attribute,
            value_form_input_attribute,
        ),
    )
    builder.template(
        FIELD_LIST_PREFIX + ":add-property-button",
        tag=literal("add-property-button-tag", "button"),
        key=literal("add-property-button-key", "property-create:add"),
        class_name=literal(
            "add-property-button-class", "header-action property-create-button"
        ),
        text=property_form_control_label,
        attributes=(
            button_type_attribute,
            form_submit_attribute,
            form_control_attribute,
            form_control_binding_attribute,
            form_control_capability_attribute,
            form_control_icon_attribute,
            form_control_title_attribute,
            form_control_aria_attribute,
        ),
    )
    builder.template(
        FIELD_LIST_PREFIX + ":property-create",
        tag=literal("property-create-tag", "div"),
        key=create_key,
        class_name=literal("property-create-class", "property-create"),
        attributes=(
            relation_form_attribute,
            relation_form_operation_attribute,
            relation_form_path_attribute,
        ),
        children=(
            FIELD_LIST_PREFIX + ":new-property-label",
            FIELD_LIST_PREFIX + ":new-property-value",
            FIELD_LIST_PREFIX + ":add-property-button",
        ),
        condition=add_property,
    )
    builder.template(
        FIELD_LIST_PREFIX + ":heading",
        tag=literal("heading-tag", "div"),
        key=literal("heading-key", "properties:heading"),
        class_name=literal("heading-class", "inspector-heading"),
        text=literal("heading-text", "PROPERTIES"),
    )
    builder.template(
        FIELD_LIST_TEMPLATE_ROOT,
        tag=literal("section-tag", "section"),
        key=section_key,
        class_name=literal("section-class", "inspector-section"),
        children=(
            FIELD_LIST_PREFIX + ":heading",
            FIELD_LIST_PREFIX + ":row",
            FIELD_LIST_PREFIX + ":property-create",
        ),
    )
    return FIELD_LIST_TEMPLATE_ROOT


__all__ = [
    "FIELD_LIST_PREFIX",
    "FIELD_LIST_TEMPLATE_MEMBER_ROOTS",
    "FIELD_LIST_TEMPLATE_ROOT",
    "GRAPH_FORM_FIELD_LIST_PREFIX",
    "GRAPH_FORM_FIELD_LIST_TEMPLATE_MEMBER_ROOTS",
    "GRAPH_FORM_FIELD_LIST_TEMPLATE_ROOT",
    "LEGACY_FIELD_LIST_PREFIX",
    "LEGACY_FIELD_LIST_TEMPLATE_MEMBER_ROOTS",
    "LEGACY_FIELD_LIST_TEMPLATE_ROOT",
    "INTERMEDIATE_FIELD_LIST_PREFIX",
    "INTERMEDIATE_FIELD_LIST_TEMPLATE_MEMBER_ROOTS",
    "INTERMEDIATE_FIELD_LIST_TEMPLATE_ROOT",
    "PREINTERACTION_FIELD_LIST_PREFIX",
    "PREINTERACTION_FIELD_LIST_TEMPLATE_MEMBER_ROOTS",
    "PREINTERACTION_FIELD_LIST_TEMPLATE_ROOT",
    "VIEW_TEMPLATE_PREFIX",
    "compose_field_list_template",
]
