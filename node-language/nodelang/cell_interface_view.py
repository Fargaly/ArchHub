"""Graph-authored interface-list Properties presenter over raw projections.

The functions here only seed persisted template relations. Runtime projection
is performed by the generic ``cell_view_template`` interpreter; interface and
lifecycle behavior is resolved from graph-held paths and expressions.
"""
from __future__ import annotations

from .cell_protocols import CellBatch
from .cell_view_template import ViewTemplateBuilder, ViewTemplateProtocol


VIEW_TEMPLATE_PREFIX = "app:view-template-protocol"
LEGACY_INTERFACE_LIST_PREFIX = "app:properties-template:interface-list:v1"
LEGACY_INTERFACE_LIST_TEMPLATE_ROOT = (
    LEGACY_INTERFACE_LIST_PREFIX + ":section"
)
GRAPH_FORM_INTERFACE_LIST_PREFIX = "app:properties-template:interface-list:v2"
PREINTERACTION_INTERFACE_LIST_PREFIX = (
    "app:properties-template:interface-list:v3"
)
PRECOLLECTION_INTERFACE_LIST_PREFIX = (
    "app:properties-template:interface-list:v4"
)
PRERELATION_MEMBER_INTERFACE_LIST_PREFIX = (
    "app:properties-template:interface-list:v5"
)
INTERFACE_LIST_PREFIX = "app:properties-template:interface-list:v6"
INTERFACE_LIST_TEMPLATE_ROOT = INTERFACE_LIST_PREFIX + ":section"

_HEADING_ROOT = INTERFACE_LIST_PREFIX + ":heading"
_INTERFACE_ROW_ROOT = INTERFACE_LIST_PREFIX + ":interface-row"
_INTERFACE_LABEL_ROOT = INTERFACE_LIST_PREFIX + ":interface-label"
_INTERFACE_VALUE_ROOT = INTERFACE_LIST_PREFIX + ":interface-value"
_INTERFACE_INPUT_ROOT = INTERFACE_LIST_PREFIX + ":interface-input"
_LIFECYCLE_CONTROLS_ROOT = INTERFACE_LIST_PREFIX + ":lifecycle-controls"
_LIFECYCLE_INPUT_ROOT = INTERFACE_LIST_PREFIX + ":lifecycle-input"
_LIFECYCLE_ACTION_ROOT = INTERFACE_LIST_PREFIX + ":lifecycle-action"
_RELATION_ROLE_ROOT = INTERFACE_LIST_PREFIX + ":relation-role"
_RELATION_ROLE_HEADER_ROOT = INTERFACE_LIST_PREFIX + ":relation-role-header"
_RELATION_ROLE_MEMBER_ROOT = INTERFACE_LIST_PREFIX + ":relation-role-member"
_RELATION_ROLE_SELECT_ROOT = INTERFACE_LIST_PREFIX + ":relation-role-select"
_RELATION_ROLE_OPTION_ROOT = INTERFACE_LIST_PREFIX + ":relation-role-option"
_RELATION_ROLE_REMOVE_ROOT = INTERFACE_LIST_PREFIX + ":relation-role-remove"
_RELATION_ROLE_ADD_ROOT = INTERFACE_LIST_PREFIX + ":relation-role-add"
_RELATION_ROLE_ADD_SELECT_ROOT = (
    INTERFACE_LIST_PREFIX + ":relation-role-add-select"
)
_RELATION_ROLE_ADD_OPTION_ROOT = (
    INTERFACE_LIST_PREFIX + ":relation-role-add-option"
)
_RELATION_ROLE_ADD_ACTION_ROOT = (
    INTERFACE_LIST_PREFIX + ":relation-role-add-action"
)
_COLLECTION_ROW_ROOT = INTERFACE_LIST_PREFIX + ":collection-row"
_COLLECTION_INPUT_ROOT = INTERFACE_LIST_PREFIX + ":collection-input"
_COLLECTION_UP_ROOT = INTERFACE_LIST_PREFIX + ":collection-up"
_COLLECTION_DOWN_ROOT = INTERFACE_LIST_PREFIX + ":collection-down"
_COLLECTION_REMOVE_ROOT = INTERFACE_LIST_PREFIX + ":collection-remove"
_COLLECTION_ADD_ROW_ROOT = INTERFACE_LIST_PREFIX + ":collection-add-row"
_COLLECTION_ADD_INPUT_ROOT = INTERFACE_LIST_PREFIX + ":collection-add-input"
_COLLECTION_ADD_ACTION_ROOT = INTERFACE_LIST_PREFIX + ":collection-add-action"
_INTERFACE_CREATE_ROOT = INTERFACE_LIST_PREFIX + ":interface-create"
_INTERFACE_CREATE_NAME_ROOT = (
    INTERFACE_LIST_PREFIX + ":interface-create-name"
)
_INTERFACE_CREATE_PRESENTATION_ROOT = (
    INTERFACE_LIST_PREFIX + ":interface-create-presentation"
)
_INTERFACE_CREATE_PRESENTATION_OPTION_ROOT = (
    INTERFACE_LIST_PREFIX + ":interface-create-presentation-option"
)
_INTERFACE_CREATE_CONTRACT_ROOT = (
    INTERFACE_LIST_PREFIX + ":interface-create-contract"
)
_INTERFACE_CREATE_CONTRACT_OPTION_ROOT = (
    INTERFACE_LIST_PREFIX + ":interface-create-contract-option"
)
_INTERFACE_CREATE_ACTION_ROOT = (
    INTERFACE_LIST_PREFIX + ":interface-create-action"
)

# The legacy slots are section, heading, list, row, control, input, button,
# condition, and action-binding. The lifecycle action is both the executable
# button and its graph-held action binding, preserving nine incidences with
# eight identities.
LEGACY_INTERFACE_LIST_TEMPLATE_MEMBER_ROOTS = tuple(
    root.replace(INTERFACE_LIST_PREFIX, LEGACY_INTERFACE_LIST_PREFIX)
    for root in (
        INTERFACE_LIST_TEMPLATE_ROOT,
        _HEADING_ROOT,
        _COLLECTION_ROW_ROOT,
        _INTERFACE_ROW_ROOT,
        _INTERFACE_VALUE_ROOT,
        _INTERFACE_INPUT_ROOT,
        _LIFECYCLE_ACTION_ROOT,
        _LIFECYCLE_CONTROLS_ROOT,
        _LIFECYCLE_ACTION_ROOT,
    )
)
INTERFACE_LIST_TEMPLATE_MEMBER_ROOTS = (
    INTERFACE_LIST_TEMPLATE_ROOT,
    _HEADING_ROOT,
    _COLLECTION_ROW_ROOT,
    _INTERFACE_ROW_ROOT,
    _INTERFACE_VALUE_ROOT,
    _INTERFACE_INPUT_ROOT,
    _LIFECYCLE_ACTION_ROOT,
    _LIFECYCLE_CONTROLS_ROOT,
    _LIFECYCLE_ACTION_ROOT,
    _INTERFACE_CREATE_ROOT,
    _INTERFACE_CREATE_NAME_ROOT,
    _INTERFACE_CREATE_PRESENTATION_ROOT,
    _INTERFACE_CREATE_PRESENTATION_OPTION_ROOT,
    _INTERFACE_CREATE_CONTRACT_ROOT,
    _INTERFACE_CREATE_CONTRACT_OPTION_ROOT,
    _INTERFACE_CREATE_ACTION_ROOT,
)
GRAPH_FORM_INTERFACE_LIST_TEMPLATE_ROOT = (
    GRAPH_FORM_INTERFACE_LIST_PREFIX + ":section"
)
GRAPH_FORM_INTERFACE_LIST_TEMPLATE_MEMBER_ROOTS = tuple(
    root.replace(INTERFACE_LIST_PREFIX, GRAPH_FORM_INTERFACE_LIST_PREFIX)
    for root in INTERFACE_LIST_TEMPLATE_MEMBER_ROOTS
)
PREINTERACTION_INTERFACE_LIST_TEMPLATE_ROOT = (
    PREINTERACTION_INTERFACE_LIST_PREFIX + ":section"
)
PREINTERACTION_INTERFACE_LIST_TEMPLATE_MEMBER_ROOTS = tuple(
    root.replace(
        INTERFACE_LIST_PREFIX, PREINTERACTION_INTERFACE_LIST_PREFIX
    )
    for root in INTERFACE_LIST_TEMPLATE_MEMBER_ROOTS
)
PRECOLLECTION_INTERFACE_LIST_TEMPLATE_ROOT = (
    PRECOLLECTION_INTERFACE_LIST_PREFIX + ":section"
)
PRECOLLECTION_INTERFACE_LIST_TEMPLATE_MEMBER_ROOTS = tuple(
    root.replace(
        INTERFACE_LIST_PREFIX, PRECOLLECTION_INTERFACE_LIST_PREFIX
    )
    for root in INTERFACE_LIST_TEMPLATE_MEMBER_ROOTS
)
PRERELATION_MEMBER_INTERFACE_LIST_TEMPLATE_ROOT = (
    PRERELATION_MEMBER_INTERFACE_LIST_PREFIX + ":section"
)
PRERELATION_MEMBER_INTERFACE_LIST_TEMPLATE_MEMBER_ROOTS = tuple(
    root.replace(
        INTERFACE_LIST_PREFIX, PRERELATION_MEMBER_INTERFACE_LIST_PREFIX
    )
    for root in INTERFACE_LIST_TEMPLATE_MEMBER_ROOTS
)


def compose_interface_list_template(
    batch: CellBatch,
    protocol: ViewTemplateProtocol,
) -> str:
    """Compose interface inspection and editing as persisted relations."""
    builder = ViewTemplateBuilder(batch, protocol)
    prefix = INTERFACE_LIST_PREFIX
    segments: dict[str, str] = {}

    def expression(name: str, operation: str, *arguments: str) -> str:
        return builder.expression(
            "%s:expression:%s" % (prefix, name), operation, arguments
        )

    def literal(name: str, value: object) -> str:
        return builder.literal(
            "%s:expression:%s" % (prefix, name), value
        )

    def segment(name: str) -> str:
        if name not in segments:
            segments[name] = builder.atom(
                "%s:segment:%s" % (prefix, name), name
            )
        return segments[name]

    def path(name: str, base: str, *names: str) -> str:
        return expression(
            name, "path", base, *(segment(item) for item in names)
        )

    def concat(name: str, *arguments: str) -> str:
        return expression(name, "concat", *arguments)

    def attribute(name: str, label: str, value: str) -> str:
        return builder.attribute(
            "%s:attribute:%s" % (prefix, name), label, value
        )

    root_context = expression("root-context", "root")
    item_context = expression("item-context", "item")
    index_context = expression("index-context", "index")
    parent_context = expression("parent-context", "parent")
    true_value = expression(
        "true-value",
        "equals",
        literal("true-left", "true"),
        literal("true-right", "true"),
    )
    false_value = expression("false-value", "not", true_value)
    empty = literal("empty", "")
    absent = path(
        "attribute-not-present",
        root_context,
        "__view_template_attribute_not_present__",
    )

    def truthy(name: str, value: str) -> str:
        return expression(name, "fallback", value, false_value)

    def value_or(name: str, value: str, default: str) -> str:
        return expression(
            name,
            "choose",
            truthy(name + "-present", value),
            value,
            default,
        )

    selected = path("selected", root_context, "selected")
    selected_text = expression("selected-text", "string", selected)
    assembly = path(
        "selected-assembly", root_context, "selected_assembly"
    )
    assembly_interfaces = path(
        "selected-assembly-interfaces", assembly, "interfaces"
    )
    projected_interfaces = path(
        "selected-interfaces", root_context, "selected_interfaces"
    )
    interfaces = expression(
        "selected-interface-source",
        "fallback",
        projected_interfaces,
        assembly_interfaces,
    )
    has_interfaces = truthy("has-selected-interfaces", interfaces)
    authoring = path("authoring", root_context, "authoring")
    can_add_interface = truthy(
        "can-add-interface",
        path("authoring-add-interface", authoring, "add_interface"),
    )
    show_interface_section = expression(
        "show-interface-section", "or", has_interfaces, can_add_interface
    )
    interface_form = path("interface-form", authoring, "interface_form")
    interface_form_root = path(
        "interface-form-root", interface_form, "root"
    )
    interface_form_inputs = path(
        "interface-form-inputs", interface_form, "inputs"
    )
    interface_name_input = path(
        "interface-name-input", interface_form_inputs, "name"
    )
    interface_presentation_input = path(
        "interface-presentation-input", interface_form_inputs, "presentation"
    )
    interface_contract_input = path(
        "interface-contract-input", interface_form_inputs, "contract"
    )
    interface_form_control = path(
        "interface-form-control", interface_form, "control"
    )
    interface_form_control_label = path(
        "interface-form-control-label", interface_form, "control_label"
    )
    interface_form_control_title = path(
        "interface-form-control-title", interface_form, "control_title"
    )
    interface_form_control_binding = path(
        "interface-form-control-binding", interface_form, "control_binding"
    )
    interface_form_control_capability = path(
        "interface-form-control-capability", interface_form,
        "control_capability",
    )
    interface_form_control_icon = path(
        "interface-form-control-icon", interface_form, "control_icon"
    )
    interface_form_operation = path(
        "interface-form-operation", interface_form, "operation"
    )
    interface_form_operation_path = path(
        "interface-form-operation-path", interface_form, "operation_path"
    )
    interface_presentations = path(
        "interface-presentations", authoring, "interface_presentations"
    )
    interface_contracts = path(
        "interface-contracts", authoring, "interface_contracts"
    )
    nodes = path("nodes", root_context, "nodes")
    lifecycle = path("lifecycle", assembly, "lifecycle")

    interface_id = path("interface-id", item_context, "id")
    interface_id_text = expression(
        "interface-id-text", "string", interface_id
    )
    interface_name = path("interface-name", item_context, "name")
    interface_mode = path("interface-mode", item_context, "mode")
    interface_value = path("interface-value", item_context, "value")
    interface_editable = path(
        "interface-editable", item_context, "editable"
    )
    interface_control = path(
        "interface-control", item_context, "control"
    )
    interface_event_fact_input = path(
        "interface-event-fact-input", item_context, "event_fact_input"
    )
    interface_items = path("interface-items", item_context, "items")

    release_scoped = path(
        "lifecycle-release-scoped", lifecycle, "release_scoped"
    )
    release_scoped_value = expression(
        "lifecycle-release-scoped-value",
        "fallback",
        release_scoped,
        false_value,
    )
    not_release_scoped = expression(
        "not-release-scoped", "not", release_scoped_value
    )
    content_interface = path(
        "lifecycle-content-interface", lifecycle, "content_interface"
    )
    content_interface_text = expression(
        "lifecycle-content-interface-text", "string", content_interface
    )
    lifecycle_content = expression(
        "is-lifecycle-content",
        "and",
        not_release_scoped,
        expression(
            "is-content-interface",
            "equals",
            interface_id_text,
            content_interface_text,
        ),
    )

    lifecycle_states = path("lifecycle-states", lifecycle, "states")
    state_name = path("state-name", item_context, "name")
    is_wip_state = expression(
        "is-wip-state", "equals", state_name, literal("wip-name", "WIP")
    )
    wip = expression(
        "wip-state", "find-where", lifecycle_states, is_wip_state
    )
    has_wip = truthy("has-wip-state", wip)
    wip_revision = path("wip-revision", wip, "revision")
    wip_revision_value = value_or(
        "wip-revision-value", wip_revision, empty
    )
    wip_head_count = path("wip-head-count", wip, "head_count")
    wip_head_count_text = expression(
        "wip-head-count-text", "string", wip_head_count
    )
    has_wip_heads = expression(
        "has-wip-heads",
        "and",
        has_wip,
        expression(
            "wip-head-count-not-zero",
            "not",
            expression(
                "wip-head-count-is-zero",
                "equals",
                wip_head_count_text,
                literal("zero-heads", "0"),
            ),
        ),
    )
    diverged = expression(
        "wip-diverged",
        "and",
        has_wip,
        expression(
            "wip-head-count-not-ordinary",
            "not",
            expression(
                "wip-head-count-ordinary",
                "member-of",
                wip_head_count_text,
                literal("ordinary-zero-heads", "0"),
                literal("ordinary-one-head", "1"),
            ),
        ),
    )
    action_disabled = expression(
        "lifecycle-action-disabled", "not", has_wip_heads
    )
    wip_heads = path("wip-heads", wip, "heads")
    head_revision = path("head-revision", item_context, "revision")
    wip_parent_roots = expression(
        "wip-parent-roots", "map", wip_heads, head_revision
    )
    wip_parents_json = expression(
        "wip-parents-json", "json", wip_parent_roots
    )

    interface_key = concat(
        "interface-row-key",
        literal("interface-row-key-prefix", "interface-row:"),
        selected_text,
        literal("interface-row-key-divider", ":"),
        interface_id_text,
    )
    interface_label_key = concat(
        "interface-label-key",
        interface_key,
        literal("interface-label-key-suffix", ":label"),
    )
    lifecycle_controls_key = concat(
        "lifecycle-controls-key",
        literal(
            "lifecycle-controls-key-prefix", "interface-content-controls:"
        ),
        selected_text,
        literal("lifecycle-controls-key-divider", ":"),
        interface_id_text,
    )
    lifecycle_input_key = concat(
        "lifecycle-input-key",
        literal("lifecycle-input-key-prefix", "interface-content:"),
        selected_text,
        literal("lifecycle-input-key-divider", ":"),
        interface_id_text,
    )
    lifecycle_action_key = concat(
        "lifecycle-action-key",
        literal(
            "lifecycle-action-key-prefix", "interface-content-action:"
        ),
        selected_text,
        literal("lifecycle-action-key-divider", ":"),
        interface_id_text,
    )
    editable_input_key = concat(
        "editable-input-key",
        literal("editable-input-key-prefix", "interface-input:"),
        selected_text,
        literal("editable-input-key-divider", ":"),
        interface_id_text,
    )
    interface_value_key = concat(
        "interface-value-key",
        literal("interface-value-key-prefix", "interface-value:"),
        selected_text,
        literal("interface-value-key-divider", ":"),
        interface_id_text,
    )

    value_or_empty = value_or(
        "interface-value-or-empty", interface_value, empty
    )
    connection_mode = expression(
        "is-connection-mode",
        "equals",
        interface_mode,
        literal("connection-mode", "connection"),
    )
    editable_connection = expression(
        "is-editable-connection",
        "and",
        connection_mode,
        truthy("interface-is-editable", interface_editable),
    )
    show_editable_input = expression(
        "show-editable-input",
        "and",
        expression("not-lifecycle-content", "not", lifecycle_content),
        editable_connection,
    )
    show_interface_value = expression(
        "show-interface-value",
        "not",
        expression(
            "has-special-interface-control",
            "or",
            lifecycle_content,
            editable_connection,
        ),
    )

    candidate_node_id = path("candidate-node-id", item_context, "id")
    parent_target = path("candidate-parent-target", parent_context, "target")
    node_matches_target = expression(
        "candidate-node-matches-target",
        "equals",
        candidate_node_id,
        parent_target,
    )
    target_node = expression(
        "target-node", "find-where", nodes, node_matches_target
    )
    has_target_node = truthy("has-target-node", target_node)
    target_label = path("target-node-label", target_node, "label")
    target_id = path("target-node-id", target_node, "id")
    target_display = expression(
        "target-node-display", "fallback", target_label, target_id
    )
    collection_mode = expression(
        "is-collection-mode",
        "equals",
        interface_mode,
        literal("collection-mode", "collection"),
    )
    relation_role_mode = expression(
        "is-relation-role-mode",
        "equals",
        interface_mode,
        literal("relation-role-mode", "relation-role"),
    )
    state_mode = expression(
        "is-state-mode",
        "equals",
        interface_mode,
        literal("state-mode", "state"),
    )
    collection_count = expression(
        "collection-count", "length", interface_items
    )
    collection_value = concat(
        "collection-value",
        collection_count,
        literal("collection-value-suffix", " items"),
    )
    relation_role_value = concat(
        "relation-role-value",
        collection_count,
        literal("relation-role-value-separator", " participants / "),
        path("relation-role-minimum-value", item_context, "minimum"),
        literal("relation-role-value-range", "-"),
        path("relation-role-maximum-value", item_context, "maximum"),
    )
    state_value = value_or(
        "state-value", interface_value, literal("empty-state", "empty")
    )
    unwired_value = value_or(
        "unwired-value",
        interface_value,
        literal("unwired-value-default", "unwired"),
    )
    ordinary_value = expression(
        "ordinary-interface-value",
        "choose",
        has_target_node,
        target_display,
        unwired_value,
    )
    displayed_value = expression(
        "displayed-interface-value",
        "choose",
        relation_role_mode,
        relation_role_value,
        expression(
            "collection-state-or-ordinary-value",
            "choose",
            collection_mode,
            collection_value,
            expression(
                "state-or-ordinary-value",
                "choose",
                state_mode,
                state_value,
                ordinary_value,
            ),
        ),
    )

    builder.template(
        _INTERFACE_LABEL_ROOT,
        tag=literal("interface-label-tag", "span"),
        key=interface_label_key,
        class_name=literal("interface-label-class", "property-label"),
        text=interface_name,
    )
    lifecycle_input_attributes = (
        attribute(
            "lifecycle-content-binding",
            "data-universal-lifecycle-content",
            literal("lifecycle-content-binding-value", "true"),
        ),
        attribute("lifecycle-input-root", "data-root", selected_text),
        attribute(
            "lifecycle-input-interface",
            "data-interface",
            interface_id_text,
        ),
        attribute("lifecycle-input-base", "data-base", wip_revision_value),
    )
    builder.template(
        _LIFECYCLE_INPUT_ROOT,
        tag=literal("lifecycle-input-tag", "textarea"),
        key=lifecycle_input_key,
        class_name=literal(
            "lifecycle-input-class",
            "property-input lifecycle-content-input",
        ),
        value=value_or_empty,
        attributes=lifecycle_input_attributes,
    )
    lifecycle_action_text = expression(
        "lifecycle-action-text",
        "choose",
        diverged,
        concat(
            "lifecycle-merge-action-text",
            literal("lifecycle-merge-action-prefix", "MERGE "),
            wip_head_count_text,
            literal("lifecycle-merge-action-suffix", " WIP HEADS"),
        ),
        literal("lifecycle-save-action-text", "SAVE NEW WIP"),
    )
    lifecycle_action_attributes = (
        attribute(
            "lifecycle-action-type",
            "type",
            literal("button-type", "button"),
        ),
        attribute(
            "lifecycle-action-disabled", "disabled", action_disabled
        ),
        attribute("lifecycle-action-root", "data-root", selected_text),
        attribute(
            "lifecycle-action-interface",
            "data-interface",
            interface_id_text,
        ),
        attribute(
            "lifecycle-merge-binding",
            "data-universal-lifecycle-merge",
            expression(
                "lifecycle-merge-binding-value",
                "choose",
                diverged,
                literal("lifecycle-merge-binding-true", "true"),
                absent,
            ),
        ),
        attribute(
            "lifecycle-merge-parents",
            "data-parents",
            expression(
                "lifecycle-merge-parents-value",
                "choose",
                diverged,
                wip_parents_json,
                absent,
            ),
        ),
        attribute(
            "lifecycle-save-binding",
            "data-universal-lifecycle-save",
            expression(
                "lifecycle-save-binding-value",
                "choose",
                diverged,
                absent,
                literal("lifecycle-save-binding-true", "true"),
            ),
        ),
        attribute(
            "lifecycle-action-base",
            "data-base",
            expression(
                "lifecycle-action-base-value",
                "choose",
                diverged,
                absent,
                wip_revision_value,
            ),
        ),
    )
    builder.template(
        _LIFECYCLE_ACTION_ROOT,
        tag=literal("lifecycle-action-tag", "button"),
        key=lifecycle_action_key,
        class_name=literal(
            "lifecycle-action-class", "operational-action"
        ),
        text=lifecycle_action_text,
        attributes=lifecycle_action_attributes,
    )
    builder.template(
        _LIFECYCLE_CONTROLS_ROOT,
        tag=literal("lifecycle-controls-tag", "div"),
        key=lifecycle_controls_key,
        class_name=literal(
            "lifecycle-controls-class",
            "universal-collection-row lifecycle-content-row",
        ),
        children=(_LIFECYCLE_INPUT_ROOT, _LIFECYCLE_ACTION_ROOT),
        condition=lifecycle_content,
    )
    editable_title = concat(
        "editable-interface-title",
        literal("editable-interface-title-prefix", "Edit "),
        interface_name,
        literal(
            "editable-interface-title-suffix",
            " through its declared interface",
        ),
    )
    editable_input_attributes = (
        attribute("editable-input-type", "type", literal("text-type", "text")),
        attribute("editable-input-title", "title", editable_title),
        attribute(
            "editable-input-binding",
            "data-universal-control",
            interface_control,
        ),
        attribute(
            "editable-input-event-fact",
            "data-universal-event-fact-input",
            interface_event_fact_input,
        ),
    )
    builder.template(
        _INTERFACE_INPUT_ROOT,
        tag=literal("editable-input-tag", "input"),
        key=editable_input_key,
        class_name=literal("editable-input-class", "property-input"),
        value=value_or_empty,
        attributes=editable_input_attributes,
        condition=show_editable_input,
    )
    builder.template(
        _INTERFACE_VALUE_ROOT,
        tag=literal("interface-value-tag", "div"),
        key=interface_value_key,
        class_name=literal("interface-value-class", "connection-box"),
        text=displayed_value,
        condition=show_interface_value,
    )
    builder.template(
        _INTERFACE_ROW_ROOT,
        tag=literal("interface-row-tag", "div"),
        key=interface_key,
        class_name=literal("interface-row-class", "property-row"),
        children=(
            _INTERFACE_LABEL_ROOT,
            _LIFECYCLE_CONTROLS_ROOT,
            _INTERFACE_INPUT_ROOT,
            _INTERFACE_VALUE_ROOT,
        ),
        repeat=interfaces,
    )

    # A relation-backed assembly exposes every contract role as a real
    # interface. These controls bind to that interface identity and submit
    # participant roots; the backend revalidates the complete relation before
    # one atomic commit.
    role_interface_id = path(
        "relation-role-interface-id", item_context, "id"
    )
    role_interface_id_text = expression(
        "relation-role-interface-id-text", "string", role_interface_id
    )
    role_name = path("relation-role-name", item_context, "name")
    role_items = path("relation-role-items", item_context, "items")
    role_choices = path("relation-role-choices", item_context, "choices")
    role_minimum = path("relation-role-minimum", item_context, "minimum")
    role_maximum = path("relation-role-maximum", item_context, "maximum")
    role_count = expression("relation-role-count", "length", role_items)
    role_key = concat(
        "relation-role-key",
        literal("relation-role-key-prefix", "relation-role:"),
        selected_text,
        literal("relation-role-key-divider", ":"),
        role_interface_id_text,
    )
    role_header_key = concat(
        "relation-role-header-key",
        role_key,
        literal("relation-role-header-key-suffix", ":header"),
    )
    role_header_text = concat(
        "relation-role-header-text",
        role_name,
        literal("relation-role-header-count-prefix", "  "),
        role_count,
        literal("relation-role-header-count-divider", "/"),
        role_minimum,
        literal("relation-role-header-range-divider", "-"),
        role_maximum,
    )
    builder.template(
        _RELATION_ROLE_HEADER_ROOT,
        tag=literal("relation-role-header-tag", "div"),
        key=role_header_key,
        class_name=literal(
            "relation-role-header-class", "property-label"
        ),
        text=role_header_text,
    )

    role_member_incidence = path(
        "relation-role-member-incidence", item_context, "incidence"
    )
    role_member_incidence_text = expression(
        "relation-role-member-incidence-text",
        "string",
        role_member_incidence,
    )
    role_member_participant = path(
        "relation-role-member-participant", item_context, "participant"
    )
    role_member_replace_control = path(
        "relation-role-member-replace-control",
        item_context,
        "replace_control",
    )
    role_member_replace_event_fact = path(
        "relation-role-member-replace-event-fact",
        item_context,
        "replace_event_fact_input",
    )
    role_member_remove_control = path(
        "relation-role-member-remove-control",
        item_context,
        "remove_control",
    )
    parent_role_id = path(
        "relation-role-parent-id", parent_context, "id"
    )
    parent_role_id_text = expression(
        "relation-role-parent-id-text", "string", parent_role_id
    )
    parent_role_choices = path(
        "relation-role-parent-choices", parent_context, "choices"
    )
    parent_role_items = path(
        "relation-role-parent-items", parent_context, "items"
    )
    parent_role_minimum = path(
        "relation-role-parent-minimum", parent_context, "minimum"
    )
    parent_role_editable = path(
        "relation-role-parent-editable", parent_context, "editable"
    )
    role_member_key = concat(
        "relation-role-member-key",
        literal("relation-role-member-key-prefix", "relation-role-member:"),
        role_member_incidence_text,
    )
    role_select_key = concat(
        "relation-role-select-key",
        role_member_key,
        literal("relation-role-select-key-suffix", ":select"),
    )
    role_select_attributes = (
        attribute(
            "relation-role-select-edit-binding",
            "data-universal-control",
            role_member_replace_control,
        ),
        attribute(
            "relation-role-select-event-fact",
            "data-universal-event-fact-input",
            role_member_replace_event_fact,
        ),
        attribute(
            "relation-role-select-disabled",
            "disabled",
            expression(
                "relation-role-select-is-disabled",
                "not",
                truthy(
                    "relation-role-parent-is-editable",
                    parent_role_editable,
                ),
            ),
        ),
    )

    role_choice_id = path("relation-role-choice-id", item_context, "id")
    role_choice_id_text = expression(
        "relation-role-choice-id-text", "string", role_choice_id
    )
    role_choice_label = path(
        "relation-role-choice-label", item_context, "label"
    )
    role_choice_parent_incidence_text = expression(
        "relation-role-choice-parent-incidence-text",
        "string",
        path(
            "relation-role-choice-parent-incidence",
            parent_context,
            "incidence",
        ),
    )
    role_option_key = concat(
        "relation-role-option-key",
        literal("relation-role-option-key-prefix", "relation-role-option:"),
        role_choice_parent_incidence_text,
        literal("relation-role-option-key-divider", ":"),
        role_choice_id_text,
    )
    builder.template(
        _RELATION_ROLE_OPTION_ROOT,
        tag=literal("relation-role-option-tag", "option"),
        key=role_option_key,
        text=role_choice_label,
        value=role_choice_id_text,
        repeat=parent_role_choices,
    )
    builder.template(
        _RELATION_ROLE_SELECT_ROOT,
        tag=literal("relation-role-select-tag", "select"),
        key=role_select_key,
        class_name=literal(
            "relation-role-select-class", "property-input"
        ),
        value=role_member_participant,
        attributes=role_select_attributes,
        children=(_RELATION_ROLE_OPTION_ROOT,),
    )
    at_role_minimum = expression(
        "relation-role-at-minimum",
        "equals",
        expression(
            "relation-role-parent-count", "length", parent_role_items
        ),
        parent_role_minimum,
    )
    role_remove_key = concat(
        "relation-role-remove-key",
        role_member_key,
        literal("relation-role-remove-key-suffix", ":remove"),
    )
    role_remove_attributes = (
        attribute(
            "relation-role-remove-type",
            "type",
            literal("relation-role-remove-type-value", "button"),
        ),
        attribute(
            "relation-role-remove-title",
            "title",
            literal("relation-role-remove-title-value", "Remove participant"),
        ),
        attribute(
            "relation-role-remove-binding",
            "data-universal-control",
            role_member_remove_control,
        ),
        attribute(
            "relation-role-remove-disabled",
            "disabled",
            expression(
                "relation-role-remove-is-disabled",
                "or",
                at_role_minimum,
                expression(
                    "relation-role-remove-not-editable",
                    "not",
                    truthy(
                        "relation-role-remove-parent-editable",
                        parent_role_editable,
                    ),
                ),
            ),
        ),
    )
    builder.template(
        _RELATION_ROLE_REMOVE_ROOT,
        tag=literal("relation-role-remove-tag", "button"),
        key=role_remove_key,
        class_name=literal(
            "relation-role-remove-class", "header-action"
        ),
        text=literal("relation-role-remove-label", "Remove"),
        attributes=role_remove_attributes,
    )
    builder.template(
        _RELATION_ROLE_MEMBER_ROOT,
        tag=literal("relation-role-member-tag", "div"),
        key=role_member_key,
        class_name=literal(
            "relation-role-member-class", "universal-collection-row"
        ),
        children=(
            _RELATION_ROLE_SELECT_ROOT,
            _RELATION_ROLE_REMOVE_ROOT,
        ),
        repeat=role_items,
    )

    add_role_interface_id = path(
        "relation-role-add-interface-id", item_context, "id"
    )
    add_role_interface_id_text = expression(
        "relation-role-add-interface-id-text",
        "string",
        add_role_interface_id,
    )
    add_role_choices = path(
        "relation-role-add-choices", item_context, "choices"
    )
    add_role_control = path(
        "relation-role-add-control", item_context, "append_control"
    )
    add_role_event_fact = path(
        "relation-role-add-event-fact",
        item_context,
        "append_event_fact_input",
    )
    add_role_count = expression(
        "relation-role-add-count",
        "length",
        path("relation-role-add-items", item_context, "items"),
    )
    add_role_maximum = path(
        "relation-role-add-maximum", item_context, "maximum"
    )
    add_role_editable = path(
        "relation-role-add-editable", item_context, "editable"
    )
    add_role_allowed = expression(
        "relation-role-add-is-allowed",
        "and",
        truthy("relation-role-add-is-editable", add_role_editable),
        expression(
            "relation-role-add-below-maximum",
            "not",
            expression(
                "relation-role-add-at-maximum",
                "equals",
                add_role_count,
                add_role_maximum,
            ),
        ),
    )
    add_role_key = concat(
        "relation-role-add-key",
        literal("relation-role-add-key-prefix", "relation-role-add:"),
        selected_text,
        literal("relation-role-add-key-divider", ":"),
        add_role_interface_id_text,
    )
    add_role_select_key = concat(
        "relation-role-add-select-key",
        add_role_key,
        literal("relation-role-add-select-key-suffix", ":select"),
    )
    add_role_select_attributes = (
        attribute(
            "relation-role-add-select-binding",
            "data-universal-event-fact-input",
            add_role_event_fact,
        ),
    )
    add_choice_id = path("relation-role-add-choice-id", item_context, "id")
    add_choice_id_text = expression(
        "relation-role-add-choice-id-text", "string", add_choice_id
    )
    add_choice_label = path(
        "relation-role-add-choice-label", item_context, "label"
    )
    add_choice_parent_interface_text = expression(
        "relation-role-add-choice-parent-interface-text",
        "string",
        path(
            "relation-role-add-choice-parent-interface",
            parent_context,
            "id",
        ),
    )
    add_option_key = concat(
        "relation-role-add-option-key",
        literal("relation-role-add-option-key-prefix", "relation-role-add-option:"),
        add_choice_parent_interface_text,
        literal("relation-role-add-option-key-divider", ":"),
        add_choice_id_text,
    )
    builder.template(
        _RELATION_ROLE_ADD_OPTION_ROOT,
        tag=literal("relation-role-add-option-tag", "option"),
        key=add_option_key,
        text=add_choice_label,
        value=add_choice_id_text,
        repeat=add_role_choices,
    )
    builder.template(
        _RELATION_ROLE_ADD_SELECT_ROOT,
        tag=literal("relation-role-add-select-tag", "select"),
        key=add_role_select_key,
        class_name=literal(
            "relation-role-add-select-class", "property-input"
        ),
        attributes=add_role_select_attributes,
        children=(_RELATION_ROLE_ADD_OPTION_ROOT,),
    )
    add_role_action_key = concat(
        "relation-role-add-action-key",
        add_role_key,
        literal("relation-role-add-action-key-suffix", ":action"),
    )
    add_role_action_attributes = (
        attribute(
            "relation-role-add-action-type",
            "type",
            literal("relation-role-add-action-type-value", "button"),
        ),
        attribute(
            "relation-role-add-action-title",
            "title",
            literal("relation-role-add-action-title-value", "Add participant"),
        ),
        attribute(
            "relation-role-add-action-binding",
            "data-universal-control",
            add_role_control,
        ),
        attribute(
            "relation-role-add-action-disabled",
            "disabled",
            expression(
                "relation-role-add-action-no-choices",
                "equals",
                expression(
                    "relation-role-add-choice-count",
                    "length",
                    add_role_choices,
                ),
                literal("relation-role-add-zero-choices", 0),
            ),
        ),
    )
    builder.template(
        _RELATION_ROLE_ADD_ACTION_ROOT,
        tag=literal("relation-role-add-action-tag", "button"),
        key=add_role_action_key,
        class_name=literal(
            "relation-role-add-action-class", "header-action"
        ),
        text=literal("relation-role-add-action-label", "Add"),
        attributes=add_role_action_attributes,
    )
    builder.template(
        _RELATION_ROLE_ADD_ROOT,
        tag=literal("relation-role-add-tag", "div"),
        key=add_role_key,
        class_name=literal(
            "relation-role-add-class", "universal-collection-row"
        ),
        attributes=(
            attribute(
                "relation-role-add-interaction-scope",
                "data-universal-interaction-scope",
                add_role_control,
            ),
        ),
        children=(
            _RELATION_ROLE_ADD_SELECT_ROOT,
            _RELATION_ROLE_ADD_ACTION_ROOT,
        ),
        condition=add_role_allowed,
    )
    builder.template(
        _RELATION_ROLE_ROOT,
        tag=literal("relation-role-tag", "section"),
        key=role_key,
        class_name=literal(
            "relation-role-class", "property-row relation-role-interface"
        ),
        children=(
            _RELATION_ROLE_HEADER_ROOT,
            _RELATION_ROLE_MEMBER_ROOT,
            _RELATION_ROLE_ADD_ROOT,
        ),
        condition=relation_role_mode,
        repeat=interfaces,
    )

    # Released assemblies expose at most one collection interface. Resolve it
    # from the raw interface list so member rows remain direct section children,
    # matching the legacy descriptor shape without a presenter-side projection.
    collection_interface = expression(
        "collection-interface", "find-where", interfaces, collection_mode
    )
    has_collection_interface = truthy(
        "has-collection-interface", collection_interface
    )
    collection_interface_id = path(
        "collection-interface-id", collection_interface, "id"
    )
    collection_interface_id_text = expression(
        "collection-interface-id-text", "string", collection_interface_id
    )
    collection_items = path(
        "collection-interface-items", collection_interface, "items"
    )
    member_incidence = path("member-incidence", item_context, "incidence")
    member_incidence_text = expression(
        "member-incidence-text", "string", member_incidence
    )
    member_value = path("member-value", item_context, "value")
    member_control = path("member-control", item_context, "control")
    member_event_fact_input = path(
        "member-event-fact-input", item_context, "event_fact_input"
    )
    member_up_control = path(
        "member-up-control", item_context, "up_control"
    )
    member_down_control = path(
        "member-down-control", item_context, "down_control"
    )
    member_remove_control = path(
        "member-remove-control", item_context, "remove_control"
    )
    collection_row_key = concat(
        "collection-row-key",
        literal("collection-row-key-prefix", "collection-row:"),
        member_incidence_text,
    )
    collection_input_key = concat(
        "collection-input-key",
        literal("collection-input-key-prefix", "collection-input:"),
        member_incidence_text,
    )
    collection_input_attributes = (
        attribute(
            "collection-input-type",
            "type",
            literal("collection-input-text-type", "text"),
        ),
        attribute(
            "collection-edit-binding",
            "data-universal-control",
            member_control,
        ),
        attribute(
            "collection-input-event-fact",
            "data-universal-event-fact-input",
            member_event_fact_input,
        ),
    )
    builder.template(
        _COLLECTION_INPUT_ROOT,
        tag=literal("collection-input-tag", "input"),
        key=collection_input_key,
        class_name=literal("collection-input-class", "property-input"),
        value=member_value,
        attributes=collection_input_attributes,
    )
    index_text = expression("collection-index-text", "string", index_context)
    first_member = expression(
        "collection-first-member",
        "equals",
        index_text,
        literal("collection-first-index", "0"),
    )
    last_index = expression(
        "collection-last-index",
        "add",
        expression("collection-item-count", "length", collection_items),
        literal("collection-index-minus-one", -1),
    )
    last_member = expression(
        "collection-last-member", "equals", index_context, last_index
    )

    def collection_action(
        root_id: str,
        name: str,
        label: str,
        disabled: str,
        control: str,
    ) -> None:
        key = concat(
            "collection-%s-key" % name,
            literal(
                "collection-%s-key-prefix" % name,
                "collection-action:",
            ),
            member_incidence_text,
            literal("collection-%s-key-divider" % name, ":"),
            literal("collection-%s-key-action" % name, name),
        )
        attributes = (
            attribute(
                "collection-%s-type" % name,
                "type",
                literal("collection-%s-button-type" % name, "button"),
            ),
            attribute(
                "collection-%s-title" % name,
                "title",
                literal("collection-%s-title-value" % name, name),
            ),
            attribute(
                "collection-%s-disabled" % name, "disabled", disabled
            ),
            attribute(
                "collection-%s-binding" % name,
                "data-universal-control",
                control,
            ),
        )
        builder.template(
            root_id,
            tag=literal("collection-%s-tag" % name, "button"),
            key=key,
            class_name=literal(
                "collection-%s-class" % name, "header-action"
            ),
            text=literal("collection-%s-label" % name, label),
            attributes=attributes,
        )

    collection_action(
        _COLLECTION_UP_ROOT,
        "up",
        "\u2191",
        first_member,
        member_up_control,
    )
    collection_action(
        _COLLECTION_DOWN_ROOT,
        "down",
        "\u2193",
        last_member,
        member_down_control,
    )
    collection_action(
        _COLLECTION_REMOVE_ROOT,
        "remove",
        "\u00d7",
        false_value,
        member_remove_control,
    )
    builder.template(
        _COLLECTION_ROW_ROOT,
        tag=literal("collection-row-tag", "div"),
        key=collection_row_key,
        class_name=literal(
            "collection-row-class", "universal-collection-row"
        ),
        children=(
            _COLLECTION_INPUT_ROOT,
            _COLLECTION_UP_ROOT,
            _COLLECTION_DOWN_ROOT,
            _COLLECTION_REMOVE_ROOT,
        ),
        repeat=collection_items,
    )

    collection_add_row_key = concat(
        "collection-add-row-key",
        literal("collection-add-row-key-prefix", "collection-add-row:"),
        selected_text,
        literal("collection-add-row-key-divider", ":"),
        collection_interface_id_text,
    )
    collection_add_input_key = concat(
        "collection-add-input-key",
        literal("collection-add-input-key-prefix", "collection-add-input:"),
        selected_text,
        literal("collection-add-input-key-divider", ":"),
        collection_interface_id_text,
    )
    collection_append_control = path(
        "collection-append-control",
        collection_interface,
        "append_control",
    )
    collection_append_event_fact_input = path(
        "collection-append-event-fact-input",
        collection_interface,
        "append_event_fact_input",
    )
    collection_add_input_attributes = (
        attribute(
            "collection-add-input-type",
            "type",
            literal("collection-add-input-text-type", "text"),
        ),
        attribute(
            "collection-add-input-placeholder",
            "placeholder",
            literal("collection-add-input-placeholder-value", "New item"),
        ),
        attribute(
            "collection-add-input-event-fact",
            "data-universal-event-fact-input",
            collection_append_event_fact_input,
        ),
    )
    builder.template(
        _COLLECTION_ADD_INPUT_ROOT,
        tag=literal("collection-add-input-tag", "input"),
        key=collection_add_input_key,
        class_name=literal(
            "collection-add-input-class", "property-input"
        ),
        attributes=collection_add_input_attributes,
    )
    collection_add_action_key = concat(
        "collection-add-action-key",
        literal("collection-add-action-key-prefix", "collection-add:"),
        selected_text,
        literal("collection-add-action-key-divider", ":"),
        collection_interface_id_text,
    )
    collection_add_action_attributes = (
        attribute(
            "collection-add-action-type",
            "type",
            literal("collection-add-action-button-type", "button"),
        ),
        attribute(
            "collection-add-action-title",
            "title",
            literal("collection-add-action-title-value", "Add item"),
        ),
        attribute(
            "collection-add-binding",
            "data-universal-control",
            collection_append_control,
        ),
    )
    builder.template(
        _COLLECTION_ADD_ACTION_ROOT,
        tag=literal("collection-add-action-tag", "button"),
        key=collection_add_action_key,
        class_name=literal(
            "collection-add-action-class", "header-action"
        ),
        text=literal("collection-add-action-label", "+"),
        attributes=collection_add_action_attributes,
    )
    builder.template(
        _COLLECTION_ADD_ROW_ROOT,
        tag=literal("collection-add-row-tag", "div"),
        key=collection_add_row_key,
        class_name=literal(
            "collection-add-row-class", "universal-collection-row"
        ),
        attributes=(
            attribute(
                "collection-add-interaction-scope",
                "data-universal-interaction-scope",
                collection_append_control,
            ),
        ),
        children=(_COLLECTION_ADD_INPUT_ROOT, _COLLECTION_ADD_ACTION_ROOT),
        condition=has_collection_interface,
    )

    interface_create_key = concat(
        "interface-create-key",
        literal("interface-create-key-prefix", "interface-create:"),
        selected_text,
    )
    interface_create_name_key = concat(
        "interface-create-name-key",
        interface_create_key,
        literal("interface-create-name-key-suffix", ":name"),
    )
    interface_create_name_attributes = (
        attribute(
            "interface-create-name-type",
            "type",
            literal("interface-create-name-type-value", "text"),
        ),
        attribute(
            "interface-create-name-placeholder",
            "placeholder",
            literal(
                "interface-create-name-placeholder-value",
                "Interface name",
            ),
        ),
        attribute(
            "interface-create-name-maximum",
            "maxlength",
            literal("interface-create-name-maximum-value", "512"),
        ),
        attribute(
            "interface-create-name-field",
            "data-universal-relation-form-field",
            literal("interface-create-name-field-value", "name"),
        ),
        attribute(
            "interface-create-name-input",
            "data-universal-relation-form-input",
            interface_name_input,
        ),
    )
    builder.template(
        _INTERFACE_CREATE_NAME_ROOT,
        tag=literal("interface-create-name-tag", "input"),
        key=interface_create_name_key,
        class_name=literal(
            "interface-create-name-class", "property-input"
        ),
        attributes=interface_create_name_attributes,
    )

    presentation_id = path(
        "interface-create-presentation-id", item_context, "id"
    )
    presentation_id_text = expression(
        "interface-create-presentation-id-text", "string", presentation_id
    )
    presentation_label = path(
        "interface-create-presentation-label", item_context, "label"
    )
    presentation_option_key = concat(
        "interface-create-presentation-option-key",
        literal(
            "interface-create-presentation-option-key-prefix",
            "interface-presentation-option:",
        ),
        presentation_id_text,
    )
    builder.template(
        _INTERFACE_CREATE_PRESENTATION_OPTION_ROOT,
        tag=literal("interface-create-presentation-option-tag", "option"),
        key=presentation_option_key,
        text=presentation_label,
        value=presentation_id_text,
        repeat=interface_presentations,
    )
    interface_create_presentation_key = concat(
        "interface-create-presentation-key",
        interface_create_key,
        literal("interface-create-presentation-key-suffix", ":presentation"),
    )
    builder.template(
        _INTERFACE_CREATE_PRESENTATION_ROOT,
        tag=literal("interface-create-presentation-tag", "select"),
        key=interface_create_presentation_key,
        class_name=literal(
            "interface-create-presentation-class", "property-input"
        ),
        attributes=(
            attribute(
                "interface-create-presentation-field",
                "data-universal-relation-form-field",
                literal(
                    "interface-create-presentation-field-value",
                    "presentation",
                ),
            ),
            attribute(
                "interface-create-presentation-input",
                "data-universal-relation-form-input",
                interface_presentation_input,
            ),
        ),
        children=(_INTERFACE_CREATE_PRESENTATION_OPTION_ROOT,),
    )

    contract_id = path("interface-create-contract-id", item_context, "id")
    contract_id_text = expression(
        "interface-create-contract-id-text", "string", contract_id
    )
    contract_label = path(
        "interface-create-contract-label", item_context, "label"
    )
    contract_option_key = concat(
        "interface-create-contract-option-key",
        literal(
            "interface-create-contract-option-key-prefix",
            "interface-contract-option:",
        ),
        contract_id_text,
    )
    builder.template(
        _INTERFACE_CREATE_CONTRACT_OPTION_ROOT,
        tag=literal("interface-create-contract-option-tag", "option"),
        key=contract_option_key,
        text=contract_label,
        value=contract_id_text,
        repeat=interface_contracts,
    )
    interface_create_contract_key = concat(
        "interface-create-contract-key",
        interface_create_key,
        literal("interface-create-contract-key-suffix", ":contract"),
    )
    builder.template(
        _INTERFACE_CREATE_CONTRACT_ROOT,
        tag=literal("interface-create-contract-tag", "select"),
        key=interface_create_contract_key,
        class_name=literal(
            "interface-create-contract-class", "property-input"
        ),
        attributes=(
            attribute(
                "interface-create-contract-field",
                "data-universal-relation-form-field",
                literal("interface-create-contract-field-value", "contract"),
            ),
            attribute(
                "interface-create-contract-input",
                "data-universal-relation-form-input",
                interface_contract_input,
            ),
        ),
        children=(_INTERFACE_CREATE_CONTRACT_OPTION_ROOT,),
    )

    interface_create_action_key = concat(
        "interface-create-action-key",
        interface_create_key,
        literal("interface-create-action-key-suffix", ":action"),
    )
    builder.template(
        _INTERFACE_CREATE_ACTION_ROOT,
        tag=literal("interface-create-action-tag", "button"),
        key=interface_create_action_key,
        class_name=literal(
            "interface-create-action-class", "header-action"
        ),
        text=interface_form_control_label,
        attributes=(
            attribute(
                "interface-create-action-type",
                "type",
                literal("interface-create-action-type-value", "button"),
            ),
            attribute(
                "interface-create-form-submit",
                "data-universal-relation-form-submit",
                interface_form_root,
            ),
            attribute(
                "interface-create-control",
                "data-universal-control",
                interface_form_control,
            ),
            attribute(
                "interface-create-control-binding",
                "data-control-binding",
                interface_form_control_binding,
            ),
            attribute(
                "interface-create-control-capability",
                "data-control-capability",
                interface_form_control_capability,
            ),
            attribute(
                "interface-create-control-icon",
                "data-control-icon",
                interface_form_control_icon,
            ),
            attribute(
                "interface-create-control-title",
                "title",
                interface_form_control_title,
            ),
            attribute(
                "interface-create-control-aria",
                "aria-label",
                interface_form_control_title,
            ),
        ),
    )
    builder.template(
        _INTERFACE_CREATE_ROOT,
        tag=literal("interface-create-tag", "div"),
        key=interface_create_key,
        class_name=literal(
            "interface-create-class", "interface-create"
        ),
        attributes=(
            attribute(
                "interface-create-form",
                "data-universal-relation-form",
                interface_form_root,
            ),
            attribute(
                "interface-create-operation",
                "data-universal-relation-form-operation",
                interface_form_operation,
            ),
            attribute(
                "interface-create-operation-path",
                "data-universal-relation-form-path",
                interface_form_operation_path,
            ),
        ),
        children=(
            _INTERFACE_CREATE_NAME_ROOT,
            _INTERFACE_CREATE_PRESENTATION_ROOT,
            _INTERFACE_CREATE_CONTRACT_ROOT,
            _INTERFACE_CREATE_ACTION_ROOT,
        ),
        condition=can_add_interface,
    )

    builder.template(
        _HEADING_ROOT,
        tag=literal("heading-tag", "div"),
        key=literal("heading-key", "interfaces:heading"),
        class_name=literal("heading-class", "inspector-heading"),
        text=literal("heading-text", "INTERFACES"),
    )
    section_key = concat(
        "section-key",
        literal("section-key-prefix", "presenter:interface-list:"),
        selected_text,
    )
    builder.template(
        INTERFACE_LIST_TEMPLATE_ROOT,
        tag=literal("section-tag", "section"),
        key=section_key,
        class_name=literal("section-class", "inspector-section"),
        children=(
            _HEADING_ROOT,
            _INTERFACE_ROW_ROOT,
            _RELATION_ROLE_ROOT,
            _COLLECTION_ROW_ROOT,
            _COLLECTION_ADD_ROW_ROOT,
            _INTERFACE_CREATE_ROOT,
        ),
        condition=show_interface_section,
    )
    return INTERFACE_LIST_TEMPLATE_ROOT


__all__ = [
    "INTERFACE_LIST_PREFIX",
    "INTERFACE_LIST_TEMPLATE_MEMBER_ROOTS",
    "INTERFACE_LIST_TEMPLATE_ROOT",
    "GRAPH_FORM_INTERFACE_LIST_PREFIX",
    "GRAPH_FORM_INTERFACE_LIST_TEMPLATE_MEMBER_ROOTS",
    "GRAPH_FORM_INTERFACE_LIST_TEMPLATE_ROOT",
    "LEGACY_INTERFACE_LIST_PREFIX",
    "LEGACY_INTERFACE_LIST_TEMPLATE_MEMBER_ROOTS",
    "LEGACY_INTERFACE_LIST_TEMPLATE_ROOT",
    "PREINTERACTION_INTERFACE_LIST_PREFIX",
    "PREINTERACTION_INTERFACE_LIST_TEMPLATE_MEMBER_ROOTS",
    "PREINTERACTION_INTERFACE_LIST_TEMPLATE_ROOT",
    "PRECOLLECTION_INTERFACE_LIST_PREFIX",
    "PRECOLLECTION_INTERFACE_LIST_TEMPLATE_MEMBER_ROOTS",
    "PRECOLLECTION_INTERFACE_LIST_TEMPLATE_ROOT",
    "PRERELATION_MEMBER_INTERFACE_LIST_PREFIX",
    "PRERELATION_MEMBER_INTERFACE_LIST_TEMPLATE_MEMBER_ROOTS",
    "PRERELATION_MEMBER_INTERFACE_LIST_TEMPLATE_ROOT",
    "VIEW_TEMPLATE_PREFIX",
    "compose_interface_list_template",
]
