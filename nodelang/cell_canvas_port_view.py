"""Graph-authored canvas interface control presentation."""
from __future__ import annotations

from .cell_protocols import CellBatch
from .cell_view_template import ViewTemplateBuilder, ViewTemplateProtocol


CANVAS_PORT_PREFIX = "app:canvas-port-template:v1"
CANVAS_PORT_TEMPLATE_ROOT = CANVAS_PORT_PREFIX + ":port"
CANVAS_PORT_TEMPLATE_MEMBER_ROOTS = (CANVAS_PORT_TEMPLATE_ROOT,)


def compose_canvas_port_template(
    batch: CellBatch,
    protocol: ViewTemplateProtocol,
) -> str:
    """Compose one exact interface control from graph-projected interface facts."""
    builder = ViewTemplateBuilder(batch, protocol)
    prefix = CANVAS_PORT_PREFIX

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
    missing = path("missing", root, segment("__missing__"))
    identity = path("identity", root, segment("id"))
    name = path("name", root, segment("name"))
    side = path("side", root, segment("side"))
    mode = path("mode", root, segment("mode"))
    node_id = path("node-id", root, segment("node_id"))
    connectable = path("connectable", root, segment("connectable"))
    editable = path("editable", root, segment("editable"))
    selected = path("selected", root, segment("selected"))
    context = path("context", root, segment("context"))
    relation_target = path("relation-target", root, segment("target"))
    incidence = path("incidence", root, segment("incidence"))
    incidence_owner = path("incidence-owner", root, segment("owner"))
    incidence_relation = path(
        "incidence-relation", root, segment("relation")
    )
    incidence_interface = path(
        "incidence-interface", root, segment("interface")
    )
    member_role = path("member-role", root, segment("member_role"))

    is_target = expression(
        "is-target", "equals", side, literal("target-side", "target")
    )
    is_role = expression(
        "is-role", "equals", mode,
        literal("relation-role-mode", "relation-role"),
    )
    is_incidence = expression(
        "is-incidence", "equals", mode,
        literal("relation-incidence-mode", "relation-incidence"),
    )
    is_input = expression(
        "is-input", "and", is_target,
        expression("not-role", "not", is_role),
    )
    is_output = expression(
        "is-output", "and", expression("not-target", "not", is_target),
        expression("not-incidence", "not", is_incidence),
    )
    role_owner = expression(
        "role-owner", "choose", is_role, node_id,
        expression(
            "incidence-owner-choice", "choose", is_incidence,
            incidence_owner, missing,
        ),
    )
    role_relation = expression(
        "role-relation", "choose", is_role, relation_target,
        expression(
            "incidence-relation-choice", "choose", is_incidence,
            incidence_relation, missing,
        ),
    )
    inaccessible_role = expression(
        "inaccessible-role", "and", is_role,
        expression("not-editable", "not", editable),
    )
    inaccessible_output = expression(
        "inaccessible-output", "and",
        expression("source-side", "not", is_target),
        expression("not-connectable", "not", connectable),
    )
    existing_only = expression(
        "existing-only", "choose",
        expression(
            "existing-only-condition", "or",
            inaccessible_role, inaccessible_output,
        ),
        literal("existing-only-true", "true"), missing,
    )
    aria_prefix = expression(
        "aria-prefix", "choose", is_role,
        literal("role-prefix", "Relation role: "),
        expression(
            "non-role-prefix", "choose", is_incidence,
            literal("incidence-prefix", "Relation incidence: "),
            expression(
                "direction-prefix", "choose", is_target,
                literal("input-prefix", "Input: "),
                literal("output-prefix", "Output: "),
            ),
        ),
    )
    aria_label = expression("aria-label", "concat", aria_prefix, name)
    class_name = expression(
        "class-name", "choose", is_target,
        literal("input-class", "node-port node-port-in"),
        literal("output-class", "node-port node-port-out"),
    )

    def attribute(name_root: str, name_value: str, value_root: str) -> str:
        return builder.attribute(
            "%s:attribute:%s" % (prefix, name_root), name_value, value_root
        )

    builder.template(
        CANVAS_PORT_TEMPLATE_ROOT,
        tag=literal("tag", "button"),
        key=expression(
            "key", "concat", literal("key-prefix", "canvas:interface:"),
            identity,
        ),
        class_name=class_name,
        text=name,
        attributes=(
            attribute("type", "type", literal("type", "button")),
            attribute("title", "title", name),
            attribute("aria-label", "aria-label", aria_label),
            attribute("aria-pressed", "aria-pressed", selected),
            attribute("interface", "data-universal-interface", identity),
            attribute("interface-label", "data-interface-label", name),
            attribute("interface-mode", "data-interface-mode", mode),
            attribute(
                "port-index", "data-port-index",
                path("port-index", root, segment("port_index")),
            ),
            attribute("context", "data-context", context),
            attribute("selected", "data-selected", selected),
            attribute(
                "relation-role", "data-universal-relation-role",
                expression(
                    "relation-role-value", "choose", is_role,
                    identity, missing,
                ),
            ),
            attribute("role-owner", "data-universal-role-owner", role_owner),
            attribute(
                "role-relation", "data-universal-role-relation", role_relation
            ),
            attribute(
                "role-member", "data-universal-role-member",
                expression(
                    "role-member-value", "choose",
                    expression("role-or-incidence", "or", is_role, is_incidence),
                    member_role, missing,
                ),
            ),
            attribute("existing-only", "data-existing-only", existing_only),
            attribute(
                "input-owner", "data-universal-input",
                expression("input-owner-value", "choose", is_input, node_id, missing),
            ),
            attribute(
                "output-owner", "data-universal-output",
                expression(
                    "output-owner-value", "choose", is_output, node_id, missing
                ),
            ),
            attribute(
                "relation-incidence", "data-universal-relation-incidence",
                expression(
                    "relation-incidence-value", "choose", is_incidence,
                    incidence, missing,
                ),
            ),
            attribute(
                "role-interface", "data-universal-role-interface",
                expression(
                    "role-interface-value", "choose", is_incidence,
                    incidence_interface, missing,
                ),
            ),
        ),
    )
    return CANVAS_PORT_TEMPLATE_ROOT


__all__ = [
    "CANVAS_PORT_PREFIX",
    "CANVAS_PORT_TEMPLATE_MEMBER_ROOTS",
    "CANVAS_PORT_TEMPLATE_ROOT",
    "compose_canvas_port_template",
]
