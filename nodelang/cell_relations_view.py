"""Graph-authored relation-list Properties presenter.

The functions in this module seed a released executable assembly. Runtime
projection is performed only by ``cell_view_template`` from persisted paths,
conditions, values, and action attributes; no relation-list name selects host
behavior after composition.
"""
from __future__ import annotations

from .cell_protocols import CellBatch
from .cell_view_template import ViewTemplateBuilder, ViewTemplateProtocol


VIEW_TEMPLATE_PREFIX = "app:view-template-protocol"
LEGACY_RELATION_LIST_V1_PREFIX = "app:properties-template:relation-list:v1"
LEGACY_RELATION_LIST_V1_TEMPLATE_ROOT = (
    LEGACY_RELATION_LIST_V1_PREFIX + ":section"
)
LEGACY_RELATION_LIST_V1_TEMPLATE_MEMBER_ROOTS = (
    LEGACY_RELATION_LIST_V1_TEMPLATE_ROOT,
    LEGACY_RELATION_LIST_V1_PREFIX + ":heading",
    LEGACY_RELATION_LIST_V1_PREFIX + ":relation-authority",
    LEGACY_RELATION_LIST_V1_PREFIX + ":relation-row",
    LEGACY_RELATION_LIST_V1_PREFIX + ":relation-select",
    LEGACY_RELATION_LIST_V1_PREFIX + ":relation-target",
    LEGACY_RELATION_LIST_V1_PREFIX + ":relation-value",
    LEGACY_RELATION_LIST_V1_PREFIX + ":relation-link",
    LEGACY_RELATION_LIST_V1_PREFIX + ":empty",
)

LEGACY_RELATION_LIST_PREFIX = "app:properties-template:relation-list:v2"
LEGACY_RELATION_LIST_TEMPLATE_ROOT = (
    LEGACY_RELATION_LIST_PREFIX + ":section"
)
LEGACY_RELATION_LIST_TEMPLATE_MEMBER_ROOTS = (
    LEGACY_RELATION_LIST_TEMPLATE_ROOT,
    LEGACY_RELATION_LIST_PREFIX + ":heading",
    LEGACY_RELATION_LIST_PREFIX + ":relation-authority",
    LEGACY_RELATION_LIST_PREFIX + ":relation-row",
    LEGACY_RELATION_LIST_PREFIX + ":relation-select",
    LEGACY_RELATION_LIST_PREFIX + ":relation-target",
    LEGACY_RELATION_LIST_PREFIX + ":relation-value",
    LEGACY_RELATION_LIST_PREFIX + ":relation-link",
    LEGACY_RELATION_LIST_PREFIX + ":empty",
)

LEGACY_RELATION_LIST_TEMPLATE_VARIANTS = (
    (
        LEGACY_RELATION_LIST_V1_TEMPLATE_ROOT,
        LEGACY_RELATION_LIST_V1_TEMPLATE_MEMBER_ROOTS,
    ),
    (
        LEGACY_RELATION_LIST_TEMPLATE_ROOT,
        LEGACY_RELATION_LIST_TEMPLATE_MEMBER_ROOTS,
    ),
)

RELATION_LIST_PREFIX = "app:properties-template:relation-list:v3"
RELATION_LIST_TEMPLATE_ROOT = RELATION_LIST_PREFIX + ":section"

# These nine executable roots preserve the presenter's incidence shape while
# The current graph adds progressive-disclosure groups as auxiliary templates.
RELATION_LIST_TEMPLATE_MEMBER_ROOTS = (
    RELATION_LIST_TEMPLATE_ROOT,
    RELATION_LIST_PREFIX + ":heading",
    RELATION_LIST_PREFIX + ":relation-authority",
    RELATION_LIST_PREFIX + ":relation-row",
    RELATION_LIST_PREFIX + ":relation-select",
    RELATION_LIST_PREFIX + ":relation-target",
    RELATION_LIST_PREFIX + ":relation-value",
    RELATION_LIST_PREFIX + ":relation-link",
    RELATION_LIST_PREFIX + ":empty",
)


def compose_relation_list_template(
    batch: CellBatch,
    protocol: ViewTemplateProtocol,
) -> str:
    """Compose relation inspection and actions as rewritable graph relations."""
    builder = ViewTemplateBuilder(batch, protocol)
    prefix = RELATION_LIST_PREFIX

    def literal(name: str, value: object) -> str:
        return builder.literal("%s:expression:%s" % (prefix, name), value)

    def segment(name: str, value: str | None = None) -> str:
        return builder.atom(
            "%s:segment:%s" % (prefix, name), value if value is not None else name
        )

    def expression(name: str, operation: str, *arguments: str) -> str:
        return builder.expression(
            "%s:expression:%s" % (prefix, name), operation, arguments
        )

    def path(name: str, base: str, *segments: str) -> str:
        return expression(name, "path", base, *segments)

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

    segments = {
        name: segment(name)
        for name in (
            "selected",
            "selected_relation",
            "connections",
            "wires",
            "nodes",
            "id",
            "segment",
            "source",
            "target",
            "gates",
            "nary",
            "participants",
            "participant_count",
            "observed_revision",
            "incidence",
            "role",
            "direction",
            "participant",
            "participant_label",
            "participant_owner",
            "participant_interface",
            "rewire_choices",
            "editable",
            "navigable",
            "label",
        )
    }
    absent_segment = segment(
        "attribute-not-present", "__view_template_attribute_not_present__"
    )
    absent = path("attribute-not-present", root_context, absent_segment)

    selected = path("selected", root_context, segments["selected"])
    selected_relation = path(
        "selected-relation", root_context, segments["selected_relation"]
    )
    relation_present = expression(
        "relation-present", "fallback", selected_relation, false_value
    )
    connections = path("connections", root_context, segments["connections"])
    wires = path("wires", root_context, segments["wires"])
    nodes = path("nodes", root_context, segments["nodes"])
    selected_or_none = expression(
        "selected-or-none", "fallback", selected, literal("none", "none")
    )
    relation_absent = expression("relation-absent", "not", relation_present)
    relation_nary = expression(
        "relation-is-nary",
        "fallback",
        path(
            "selected-relation-nary",
            selected_relation,
            segments["nary"],
        ),
        false_value,
    )
    connection_count = expression(
        "connection-count", "length", connections
    )
    no_connections = expression(
        "no-connections", "not", connection_count
    )

    section_key = expression(
        "section-key",
        "concat",
        literal("section-key-prefix", "presenter:relation-list:"),
        selected_or_none,
    )
    heading_text = expression(
        "heading-text",
        "choose",
        relation_present,
        expression(
            "relation-heading",
            "choose",
            relation_nary,
            literal("nary-relation-heading", "RELATION"),
            literal("data-flow-heading", "DATA FLOW"),
        ),
        literal("connections-heading", "CONNECTIONS"),
    )

    relation_id = path(
        "selected-relation-id", selected_relation, segments["id"]
    )
    relation_gates = path(
        "selected-relation-gates", selected_relation, segments["gates"]
    )
    relation_source = path(
        "selected-relation-source", selected_relation, segments["source"]
    )
    relation_target = path(
        "selected-relation-target", selected_relation, segments["target"]
    )
    relation_revision = path(
        "selected-relation-revision",
        selected_relation,
        segments["observed_revision"],
    )
    relation_participant_count = path(
        "selected-relation-participant-count",
        selected_relation,
        segments["participant_count"],
    )
    source_label = expression(
        "selected-source-label",
        "fallback",
        path(
            "selected-source-participant-label",
            relation_source,
            segments["participant_label"],
        ),
        literal("unresolved-source", "Unresolved source"),
    )
    target_label = expression(
        "selected-target-label",
        "fallback",
        path(
            "selected-target-participant-label",
            relation_target,
            segments["participant_label"],
        ),
        literal("unresolved-target", "Unresolved target"),
    )
    gate_count = expression("gate-count", "length", relation_gates)
    authority_heading_text = expression(
        "authority-heading-text",
        "choose",
        relation_nary,
        expression(
            "nary-authority-heading-text",
            "concat",
            literal("nary-authority-heading-prefix", "THIS RELATION / "),
            relation_participant_count,
            literal("nary-authority-heading-suffix", " PARTICIPANTS"),
        ),
        expression(
            "binary-authority-heading-text",
            "concat",
            literal("authority-heading-prefix", "THIS RELATION / "),
            gate_count,
            literal("authority-heading-suffix", " GATE"),
        ),
    )
    authority_key = expression(
        "authority-key",
        "concat",
        literal("authority-key-prefix", "relation-authority:"),
        relation_id,
    )
    relation_flow_key = expression(
        "relation-flow-key",
        "concat",
        literal("relation-flow-key-prefix", "relation-flow:"),
        relation_id,
    )
    relation_flow_text = expression(
        "relation-flow-text",
        "choose",
        relation_nary,
        expression(
            "nary-relation-flow-text",
            "concat",
            relation_participant_count,
            literal(
                "nary-relation-flow-suffix",
                " participants connected through explicit roles",
            ),
        ),
        expression(
            "binary-relation-flow-text",
            "concat",
            source_label,
            literal("relation-flow-arrow", " -> "),
            target_label,
        ),
    )
    relation_flow_title = expression(
        "relation-flow-title",
        "concat",
        literal("relation-node-title", "relation node: "),
        relation_id,
        literal("relation-revision-title", "\nobserved revision: "),
        relation_revision,
    )
    relation_flow_title_attribute = builder.attribute(
        prefix + ":attribute:relation-flow-title",
        "title",
        relation_flow_title,
    )

    gate_participant = path(
        "gate-participant", item_context, segments["participant"]
    )
    gate_label = expression(
        "gate-participant-label",
        "fallback",
        path("gate-label", item_context, segments["participant_label"]),
        gate_participant,
    )
    gate_role = expression(
        "gate-role",
        "fallback",
        path("gate-role-value", item_context, segments["role"]),
        literal("gate-role-default", "gate"),
    )
    gate_navigable = expression(
        "gate-navigable",
        "fallback",
        path("gate-navigable-value", item_context, segments["navigable"]),
        false_value,
    )
    gate_position = expression(
        "gate-position",
        "add",
        index_context,
        literal("gate-position-one", 1),
    )
    gate_key_tail = expression(
        "gate-key-tail",
        "concat",
        index_context,
        literal("gate-key-separator", ":"),
        gate_participant,
    )
    gate_row_key = expression(
        "gate-row-key",
        "concat",
        literal("gate-row-key-prefix", "relation-gate:"),
        gate_key_tail,
    )
    gate_label_key = expression(
        "gate-label-key",
        "concat",
        gate_row_key,
        literal("gate-label-key-suffix", ":label"),
    )
    gate_display_label = expression(
        "gate-display-label",
        "concat",
        gate_role,
        literal("gate-label-space", " "),
        gate_position,
        literal("gate-label-suffix", " / protected"),
    )
    gate_button_key = expression(
        "gate-button-key",
        "concat",
        literal("gate-button-key-prefix", "relation-gate-button:"),
        gate_key_tail,
    )
    gate_value_key = expression(
        "gate-value-key",
        "concat",
        literal("gate-value-key-prefix", "relation-gate-value:"),
        gate_key_tail,
    )
    gate_content_key = expression(
        "gate-content-key",
        "choose",
        gate_navigable,
        gate_button_key,
        gate_value_key,
    )
    gate_content_tag = expression(
        "gate-content-tag",
        "choose",
        gate_navigable,
        literal("button-tag", "button"),
        literal("div-tag", "div"),
    )
    gate_content_class = expression(
        "gate-content-class",
        "choose",
        gate_navigable,
        literal(
            "gate-button-class", "connection-box connection-link"
        ),
        literal("connection-box-class", "connection-box"),
    )
    gate_type = expression(
        "gate-button-type",
        "choose",
        gate_navigable,
        literal("button-type", "button"),
        absent,
    )
    gate_focus = expression(
        "gate-focus",
        "choose",
        gate_navigable,
        gate_participant,
        absent,
    )
    gate_type_attribute = builder.attribute(
        prefix + ":attribute:gate-button-type", "type", gate_type
    )
    gate_title_attribute = builder.attribute(
        prefix + ":attribute:gate-title", "title", gate_participant
    )
    gate_focus_attribute = builder.attribute(
        prefix + ":attribute:gate-focus",
        "data-universal-focus",
        gate_focus,
    )

    connection_incidence = path(
        "connection-incidence", item_context, segments["incidence"]
    )
    connection_role = path(
        "connection-role", item_context, segments["role"]
    )
    connection_direction = expression(
        "connection-direction",
        "fallback",
        path(
            "connection-direction-value", item_context, segments["direction"]
        ),
        literal("connection-direction-default", "outbound"),
    )
    overview_role = expression(
        "connection-is-overview",
        "member-of",
        connection_role,
        literal("interface-target-role", "interface-target"),
        literal("name-role", "name"),
        literal("interface-contract-role", "interface-contract"),
        literal("interface-presentation-role", "interface-presentation"),
    )
    flow_role = expression(
        "connection-is-flow",
        "member-of",
        connection_role,
        literal("seed-role", "seed"),
        literal("source-role-for-group", "source"),
        literal("target-role-for-group", "target"),
    )
    governance_role = expression(
        "connection-is-governance",
        "member-of",
        connection_role,
        literal("authority-role", "authority"),
        literal("policy-role", "policy"),
        literal("governance-gate-role", "gate"),
        literal("court-role", "court"),
        literal("steward-role", "steward"),
    )
    history_role = expression(
        "connection-is-history",
        "member-of",
        connection_role,
        literal("previous-role", "previous"),
        literal("predecessor-role", "predecessor"),
        literal("revision-role", "revision"),
    )
    structure_role = expression(
        "connection-is-structure",
        "member-of",
        connection_role,
        literal("member-role", "member"),
        literal("part-role", "part"),
        literal("catalog-role", "catalog"),
        literal("scope-role", "scope"),
        literal("visible-role", "visible"),
        literal("relation-role", "relation"),
        literal("property-role", "property"),
    )
    known_role = expression(
        "connection-is-known",
        "or",
        overview_role,
        flow_role,
        governance_role,
        history_role,
        structure_role,
    )
    other_role = expression("connection-is-other", "not", known_role)
    endpoint_role = expression(
        "connection-is-endpoint",
        "member-of",
        connection_role,
        literal("source-role", "source"),
        literal("target-role", "target"),
    )
    connection_visible = expression(
        "connection-visible",
        "or",
        relation_absent,
        endpoint_role,
        relation_nary,
    )
    overview_visible = expression(
        "overview-connection-visible", "and", connection_visible, overview_role
    )
    flow_visible = expression(
        "flow-connection-visible", "and", connection_visible, flow_role
    )
    governance_visible = expression(
        "governance-connection-visible",
        "and",
        connection_visible,
        governance_role,
    )
    history_visible = expression(
        "history-connection-visible", "and", connection_visible, history_role
    )
    structure_visible = expression(
        "structure-connection-visible", "and", connection_visible, structure_role
    )
    inbound_structure = expression(
        "inbound-structure-connection",
        "and",
        structure_visible,
        expression(
            "connection-structure-direction-is-inbound",
            "equals",
            connection_direction,
            literal("structure-inbound-direction", "inbound"),
        ),
    )
    outbound_structure = expression(
        "outbound-structure-connection",
        "and",
        structure_visible,
        expression(
            "connection-structure-direction-is-outbound",
            "equals",
            connection_direction,
            literal("structure-outbound-direction", "outbound"),
        ),
    )
    other_visible = expression(
        "other-connection-visible", "and", connection_visible, other_role
    )
    overview_count = expression(
        "overview-connection-count", "count-where", connections, overview_visible
    )
    flow_count = expression(
        "flow-connection-count", "count-where", connections, flow_visible
    )
    governance_count = expression(
        "governance-connection-count",
        "count-where",
        connections,
        governance_visible,
    )
    history_count = expression(
        "history-connection-count", "count-where", connections, history_visible
    )
    parent_count = expression(
        "parent-connection-count", "count-where", connections,
        inbound_structure,
    )
    contents_count = expression(
        "contents-connection-count", "count-where", connections,
        outbound_structure,
    )
    other_count = expression(
        "other-connection-count", "count-where", connections, other_visible
    )
    connection_editable = expression(
        "connection-editable",
        "fallback",
        path("connection-editable-value", item_context, segments["editable"]),
        true_value,
    )
    editable_endpoint = expression(
        "editable-endpoint", "and", connection_editable, endpoint_role
    )
    fixed_endpoint = expression(
        "fixed-endpoint", "not", editable_endpoint
    )
    connection_navigable = expression(
        "connection-navigable",
        "fallback",
        path(
            "connection-navigable-value",
            item_context,
            segments["navigable"],
        ),
        false_value,
    )
    navigable_endpoint = expression(
        "navigable-endpoint", "and", fixed_endpoint, connection_navigable
    )
    static_endpoint = expression(
        "static-endpoint",
        "and",
        fixed_endpoint,
        expression("connection-not-navigable", "not", connection_navigable),
    )
    connection_participant = path(
        "connection-participant", item_context, segments["participant"]
    )
    connection_participant_label = expression(
        "connection-participant-label",
        "fallback",
        path(
            "connection-participant-label-value",
            item_context,
            segments["participant_label"],
        ),
        connection_participant,
    )
    presentation_direction = expression(
        "connection-presentation-direction",
        "choose",
        expression(
            "connection-presentation-is-target",
            "equals",
            connection_participant_label,
            literal("target-presentation-value", "target"),
        ),
        literal("input-presentation-label", "Input"),
        expression(
            "connection-presentation-direction-fallback",
            "choose",
            expression(
                "connection-presentation-is-source",
                "equals",
                connection_participant_label,
                literal("source-presentation-value", "source"),
            ),
            literal("output-presentation-label", "Output"),
            connection_participant_label,
        ),
    )
    connection_display_value = expression(
        "connection-display-value",
        "choose",
        expression(
            "connection-role-is-presentation",
            "equals",
            connection_role,
            literal(
                "interface-presentation-role-for-value",
                "interface-presentation",
            ),
        ),
        presentation_direction,
        connection_participant_label,
    )
    generic_connection_display_role = expression(
        "connection-display-role",
        "choose",
        expression(
            "connection-role-is-interface-target",
            "equals",
            connection_role,
            literal("display-interface-target-role", "interface-target"),
        ),
        literal("display-owner-label", "Owner"),
        expression(
            "connection-display-role-name",
            "choose",
            expression(
                "connection-role-is-name",
                "equals",
                connection_role,
                literal("display-name-role", "name"),
            ),
            literal("display-name-label", "Name"),
            expression(
                "connection-display-role-contract",
                "choose",
                expression(
                    "connection-role-is-contract",
                    "equals",
                    connection_role,
                    literal(
                        "display-interface-contract-role",
                        "interface-contract",
                    ),
                ),
                literal("display-contract-label", "Contract"),
                expression(
                    "connection-display-role-presentation",
                    "choose",
                    expression(
                        "connection-role-is-presentation-label",
                        "equals",
                        connection_role,
                        literal(
                            "display-interface-presentation-role",
                            "interface-presentation",
                        ),
                    ),
                    literal("display-direction-label", "Direction"),
                    expression(
                        "connection-display-role-seed",
                        "choose",
                        expression(
                            "connection-role-is-seed",
                            "equals",
                            connection_role,
                            literal("display-seed-role", "seed"),
                        ),
                        literal("display-connection-label", "Connection"),
                        expression(
                            "connection-display-role-authority",
                            "choose",
                            expression(
                                "connection-role-is-authority",
                                "equals",
                                connection_role,
                                literal(
                                    "display-authority-role", "authority"
                                ),
                            ),
                            literal(
                                "display-authority-label", "Authority"
                            ),
                            expression(
                                "connection-display-role-previous",
                                "choose",
                                expression(
                                    "connection-role-is-previous",
                                    "equals",
                                    connection_role,
                                    literal(
                                        "display-previous-role", "previous"
                                    ),
                                ),
                                literal(
                                    "display-previous-label", "Previous"
                                ),
                                expression(
                                    "connection-display-role-source",
                                    "choose",
                                    expression(
                                        "connection-role-is-source",
                                        "equals",
                                        connection_role,
                                        literal(
                                            "display-source-role", "source"
                                        ),
                                    ),
                                    literal(
                                        "display-source-label", "Source"
                                    ),
                                    expression(
                                        "connection-display-role-target",
                                        "choose",
                                        expression(
                                            "connection-role-is-target",
                                            "equals",
                                            connection_role,
                                            literal(
                                                "display-target-role", "target"
                                            ),
                                        ),
                                        literal(
                                            "display-target-label", "Target"
                                        ),
                                        connection_role,
                                    ),
                                ),
                            ),
                        ),
                    ),
                ),
            ),
        ),
    )
    connection_display_role = expression(
        "connection-display-role-with-structure",
        "choose",
        structure_role,
        expression(
            "connection-structure-display-role",
            "choose",
            expression(
                "connection-structure-is-inbound",
                "equals",
                connection_direction,
                literal("inbound-direction", "inbound"),
            ),
            literal("contained-in-label", "Contained in"),
            literal("contains-label", "Contains"),
        ),
        generic_connection_display_role,
    )
    selected_endpoint = expression(
        "selected-endpoint",
        "fallback",
        path(
            "connection-participant-interface",
            item_context,
            segments["participant_interface"],
        ),
        path(
            "connection-participant-owner",
            item_context,
            segments["participant_owner"],
        ),
        connection_participant,
    )
    relation_row_key = expression(
        "relation-row-key",
        "concat",
        literal("relation-row-key-prefix", "relation-row:"),
        connection_incidence,
    )
    relation_label_key = expression(
        "relation-label-key",
        "concat",
        relation_row_key,
        literal("relation-label-key-suffix", ":label"),
    )
    relation_select_key = expression(
        "relation-select-key",
        "concat",
        literal("relation-select-key-prefix", "relation-select:"),
        connection_incidence,
    )
    relation_target_key = expression(
        "relation-target-key",
        "concat",
        literal("relation-target-key-prefix", "relation-target:"),
        connection_incidence,
    )
    relation_value_key = expression(
        "relation-value-key",
        "concat",
        literal("relation-value-key-prefix", "relation-value:"),
        connection_incidence,
    )
    incidence_attribute = builder.attribute(
        prefix + ":attribute:connection-incidence",
        "data-universal-incidence",
        connection_incidence,
    )
    target_type_attribute = builder.attribute(
        prefix + ":attribute:target-button-type",
        "type",
        literal("target-button-type", "button"),
    )
    target_title_attribute = builder.attribute(
        prefix + ":attribute:target-title",
        "title",
        connection_participant,
    )
    target_focus_attribute = builder.attribute(
        prefix + ":attribute:target-focus",
        "data-universal-focus",
        connection_participant,
    )
    value_title_attribute = builder.attribute(
        prefix + ":attribute:value-title",
        "title",
        connection_participant,
    )

    node_id = path("option-node-id", item_context, segments["id"])
    node_label = path(
        "option-node-label", item_context, segments["label"]
    )
    option_rewire_choices = path(
        "option-rewire-choices",
        item_context,
        segments["rewire_choices"],
    )
    relation_option_source = expression(
        "relation-option-source",
        "fallback",
        option_rewire_choices,
        nodes,
    )
    parent_incidence = path(
        "option-parent-incidence", parent_context, segments["incidence"]
    )
    parent_participant = path(
        "option-parent-participant", parent_context, segments["participant"]
    )
    parent_selected_endpoint = expression(
        "option-parent-selected-endpoint",
        "fallback",
        path(
            "option-parent-participant-interface",
            parent_context,
            segments["participant_interface"],
        ),
        path(
            "option-parent-participant-owner",
            parent_context,
            segments["participant_owner"],
        ),
        parent_participant,
    )
    option_key = expression(
        "relation-option-key",
        "concat",
        literal("relation-option-key-prefix", "relation-option:"),
        parent_incidence,
        literal("relation-option-key-separator", ":"),
        node_id,
    )
    option_selected = expression(
        "relation-option-selected",
        "equals",
        node_id,
        parent_selected_endpoint,
    )
    option_selected_attribute = builder.attribute(
        prefix + ":attribute:relation-option-selected",
        "data-selected",
        option_selected,
    )

    wire_id = path("wire-id", item_context, segments["id"])
    wire_segment = expression(
        "wire-segment",
        "fallback",
        path("wire-segment-value", item_context, segments["segment"]),
        wire_id,
    )
    wire_source = path("wire-source", item_context, segments["source"])
    wire_target = path("wire-target", item_context, segments["target"])
    parent_wire_source = path(
        "parent-wire-source", parent_context, segments["source"]
    )
    parent_wire_target = path(
        "parent-wire-target", parent_context, segments["target"]
    )
    source_node_matches = expression(
        "source-node-matches", "equals", node_id, parent_wire_source
    )
    target_node_matches = expression(
        "target-node-matches", "equals", node_id, parent_wire_target
    )
    wire_source_node = expression(
        "wire-source-node", "find-where", nodes, source_node_matches
    )
    wire_target_node = expression(
        "wire-target-node", "find-where", nodes, target_node_matches
    )
    wire_source_label = expression(
        "wire-source-label",
        "fallback",
        path("wire-source-node-label", wire_source_node, segments["label"]),
        wire_source,
    )
    wire_target_label = expression(
        "wire-target-label",
        "fallback",
        path("wire-target-node-label", wire_target_node, segments["label"]),
        wire_target,
    )
    wire_is_attached = expression(
        "wire-is-attached",
        "or",
        expression(
            "wire-source-is-selected", "equals", wire_source, selected
        ),
        expression(
            "wire-target-is-selected", "equals", wire_target, selected
        ),
    )
    attached_wire = wire_is_attached
    attached_wire_count = expression(
        "attached-wire-count", "count-where", wires, wire_is_attached
    )
    empty_relations = expression(
        "empty-relations",
        "and",
        no_connections,
        expression("no-attached-wires", "not", attached_wire_count),
    )
    wire_key = expression(
        "wire-key",
        "concat",
        literal("wire-key-prefix", "relation-link:"),
        wire_segment,
    )
    wire_text = expression(
        "wire-text",
        "concat",
        wire_source_label,
        literal("wire-arrow", " -> "),
        wire_target_label,
    )
    wire_type_attribute = builder.attribute(
        prefix + ":attribute:wire-button-type",
        "type",
        literal("wire-button-type", "button"),
    )
    wire_title_attribute = builder.attribute(
        prefix + ":attribute:wire-title", "title", wire_id
    )
    wire_action_attribute = builder.attribute(
        prefix + ":attribute:wire-action",
        "data-universal-relation",
        wire_id,
    )
    empty_key = expression(
        "empty-key",
        "concat",
        literal("empty-key-prefix", "relations:empty:"),
        selected_or_none,
    )

    # Auxiliary templates reachable from the nine presenter members.
    builder.template(
        prefix + ":relation-authority-heading",
        tag=literal("authority-heading-tag", "div"),
        key=literal("authority-heading-key", "relation-authority:heading"),
        class_name=literal("inspector-heading-class", "inspector-heading"),
        text=authority_heading_text,
    )
    builder.template(
        prefix + ":relation-flow",
        tag=literal("relation-flow-tag", "div"),
        key=relation_flow_key,
        class_name=literal(
            "relation-flow-class", "connection-box relation-flow-summary"
        ),
        text=relation_flow_text,
        attributes=(relation_flow_title_attribute,),
    )
    builder.template(
        prefix + ":relation-gate-label",
        tag=literal("gate-label-tag", "span"),
        key=gate_label_key,
        class_name=literal("property-label-class", "property-label"),
        text=gate_display_label,
    )
    builder.template(
        prefix + ":relation-gate-content",
        tag=gate_content_tag,
        key=gate_content_key,
        class_name=gate_content_class,
        text=gate_label,
        attributes=(
            gate_type_attribute,
            gate_title_attribute,
            gate_focus_attribute,
        ),
    )
    builder.template(
        prefix + ":relation-gate",
        tag=literal("gate-row-tag", "div"),
        key=gate_row_key,
        class_name=literal("property-row-class", "property-row"),
        children=(
            prefix + ":relation-gate-label",
            prefix + ":relation-gate-content",
        ),
        repeat=relation_gates,
    )
    builder.template(
        prefix + ":relation-label",
        tag=literal("relation-label-tag", "span"),
        key=relation_label_key,
        class_name=literal("relation-label-class", "property-label"),
        text=connection_display_role,
    )
    builder.template(
        prefix + ":relation-option",
        tag=literal("option-tag", "option"),
        key=option_key,
        text=node_label,
        value=node_id,
        attributes=(option_selected_attribute,),
        repeat=relation_option_source,
    )

    # Exactly nine executable presenter member roots.
    builder.template(
        RELATION_LIST_PREFIX + ":relation-select",
        tag=literal("select-tag", "select"),
        key=relation_select_key,
        class_name=literal("property-input-class", "property-input"),
        value=selected_endpoint,
        attributes=(incidence_attribute,),
        children=(prefix + ":relation-option",),
        condition=editable_endpoint,
    )
    builder.template(
        RELATION_LIST_PREFIX + ":relation-target",
        tag=literal("target-button-tag", "button"),
        key=relation_target_key,
        class_name=literal(
            "target-button-class", "connection-box connection-link"
        ),
        text=connection_display_value,
        attributes=(
            target_type_attribute,
            target_title_attribute,
            target_focus_attribute,
        ),
        condition=navigable_endpoint,
    )
    builder.template(
        RELATION_LIST_PREFIX + ":relation-value",
        tag=literal("relation-value-tag", "div"),
        key=relation_value_key,
        class_name=literal("relation-value-class", "connection-box"),
        text=connection_display_value,
        attributes=(value_title_attribute,),
        condition=static_endpoint,
    )
    builder.template(
        RELATION_LIST_PREFIX + ":relation-row",
        tag=literal("relation-row-tag", "label"),
        key=relation_row_key,
        class_name=literal(
            "relation-row-class", "property-row relation-connection-row"
        ),
        children=(
            prefix + ":relation-label",
            RELATION_LIST_PREFIX + ":relation-select",
            RELATION_LIST_PREFIX + ":relation-target",
            RELATION_LIST_PREFIX + ":relation-value",
        ),
        repeat=connections,
        condition=flow_visible,
    )

    group_specs = (
        ("overview", "Overview", overview_count, overview_visible, True),
        ("connections", "Connections", flow_count, flow_visible, False),
        (
            "governance",
            "Governance",
            governance_count,
            governance_visible,
            False,
        ),
        ("parent", "Parent", parent_count, inbound_structure, True),
        ("contents", "Contents", contents_count, outbound_structure, False),
        ("history", "History", history_count, history_visible, False),
        ("other", "Other", other_count, other_visible, False),
    )
    relation_group_roots = []
    for slug, label, count, row_condition, opened in group_specs:
        summary_root = prefix + ":group:%s:summary" % slug
        row_root = (
            RELATION_LIST_PREFIX + ":relation-row"
            if slug == "connections"
            else prefix + ":group:%s:row" % slug
        )
        details_root = prefix + ":group:%s" % slug
        if slug != "connections":
            builder.template(
                row_root,
                tag=literal("%s-row-tag" % slug, "label"),
                key=relation_row_key,
                class_name=literal(
                    "%s-row-class" % slug,
                    "property-row relation-%s-row" % slug,
                ),
                children=(
                    prefix + ":relation-label",
                    RELATION_LIST_PREFIX + ":relation-select",
                    RELATION_LIST_PREFIX + ":relation-target",
                    RELATION_LIST_PREFIX + ":relation-value",
                ),
                repeat=connections,
                condition=row_condition,
            )
        builder.template(
            summary_root,
            tag=literal("%s-summary-tag" % slug, "summary"),
            key=expression(
                "%s-summary-key" % slug,
                "concat",
                literal(
                    "%s-summary-key-prefix" % slug,
                    "relation-group:%s:summary:" % slug,
                ),
                selected_or_none,
            ),
            class_name=literal(
                "%s-summary-class" % slug, "relation-group-summary"
            ),
            text=expression(
                "%s-summary-text" % slug,
                "concat",
                literal("%s-summary-label" % slug, label + " / "),
                count,
            ),
        )
        open_attributes = ()
        if opened:
            open_attributes = (
                builder.attribute(
                    prefix + ":attribute:%s-open" % slug,
                    "open",
                    true_value,
                ),
            )
        builder.template(
            details_root,
            tag=literal("%s-details-tag" % slug, "details"),
            key=expression(
                "%s-details-key" % slug,
                "concat",
                literal(
                    "%s-details-key-prefix" % slug,
                    "relation-group:%s:" % slug,
                ),
                selected_or_none,
            ),
            class_name=literal(
                "%s-details-class" % slug,
                "relation-group relation-group-%s" % slug,
            ),
            attributes=open_attributes,
            children=(summary_root, row_root),
            condition=count,
        )
        relation_group_roots.append(details_root)
    builder.template(
        RELATION_LIST_PREFIX + ":relation-authority",
        tag=literal("authority-tag", "section"),
        key=authority_key,
        class_name=literal(
            "authority-class", "relation-authority-summary"
        ),
        children=(
            prefix + ":relation-authority-heading",
            prefix + ":relation-flow",
            prefix + ":relation-gate",
        ),
        condition=relation_present,
    )
    builder.template(
        RELATION_LIST_PREFIX + ":relation-link",
        tag=literal("wire-button-tag", "button"),
        key=wire_key,
        class_name=literal("wire-button-class", "library-row"),
        text=wire_text,
        attributes=(
            wire_type_attribute,
            wire_title_attribute,
            wire_action_attribute,
        ),
        repeat=wires,
        condition=attached_wire,
    )
    builder.template(
        RELATION_LIST_PREFIX + ":empty",
        tag=literal("empty-tag", "div"),
        key=empty_key,
        class_name=literal("empty-class", "connection-box"),
        text=literal("empty-text", "0 relation cells attached"),
        condition=empty_relations,
    )
    builder.template(
        RELATION_LIST_PREFIX + ":heading",
        tag=literal("heading-tag", "div"),
        key=literal("heading-key", "relations:heading"),
        class_name=literal("heading-class", "inspector-heading"),
        text=heading_text,
    )
    builder.template(
        RELATION_LIST_TEMPLATE_ROOT,
        tag=literal("section-tag", "section"),
        key=section_key,
        class_name=literal("section-class", "inspector-section"),
        children=(
            RELATION_LIST_PREFIX + ":heading",
            RELATION_LIST_PREFIX + ":relation-authority",
            RELATION_LIST_PREFIX + ":empty",
            RELATION_LIST_PREFIX + ":relation-link",
            *relation_group_roots,
        ),
    )
    return RELATION_LIST_TEMPLATE_ROOT


__all__ = [
    "LEGACY_RELATION_LIST_PREFIX",
    "LEGACY_RELATION_LIST_TEMPLATE_VARIANTS",
    "LEGACY_RELATION_LIST_TEMPLATE_MEMBER_ROOTS",
    "LEGACY_RELATION_LIST_TEMPLATE_ROOT",
    "LEGACY_RELATION_LIST_V1_PREFIX",
    "LEGACY_RELATION_LIST_V1_TEMPLATE_MEMBER_ROOTS",
    "LEGACY_RELATION_LIST_V1_TEMPLATE_ROOT",
    "RELATION_LIST_PREFIX",
    "RELATION_LIST_TEMPLATE_MEMBER_ROOTS",
    "RELATION_LIST_TEMPLATE_ROOT",
    "VIEW_TEMPLATE_PREFIX",
    "compose_relation_list_template",
]
