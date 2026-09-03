"""Graph-authored Floor primitive entry in the node catalogue."""
from __future__ import annotations

from .cell_protocols import CellBatch
from .cell_view_template import ViewTemplateBuilder, ViewTemplateProtocol


LIBRARY_PRIMITIVE_PREFIX = "app:library-primitive-template:v1"
LIBRARY_PRIMITIVE_TEMPLATE_ROOT = LIBRARY_PRIMITIVE_PREFIX + ":primitive"
LIBRARY_PRIMITIVE_TEMPLATE_MEMBER_ROOTS = (
    LIBRARY_PRIMITIVE_TEMPLATE_ROOT,
    LIBRARY_PRIMITIVE_PREFIX + ":kicker",
    LIBRARY_PRIMITIVE_PREFIX + ":name",
    LIBRARY_PRIMITIVE_PREFIX + ":fields",
)


def compose_library_primitive_template(
    batch: CellBatch,
    protocol: ViewTemplateProtocol,
) -> str:
    """Compose the Floor-only primitive catalogue control from graph facts."""
    builder = ViewTemplateBuilder(batch, protocol)
    prefix = LIBRARY_PRIMITIVE_PREFIX

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
    label = path("label", root, segment("label"))
    kicker = path("kicker", root, segment("kicker"))
    fields = path("fields", root, segment("fields"))
    selected = path("selected", root, segment("selected"))
    field_text = expression(
        "field-text", "join", fields, literal("field-separator", "  /  ")
    )

    def keyed_value(name_root: str) -> str:
        return expression(
            "%s-key" % name_root,
            "concat",
            literal(
                "%s-key-prefix" % name_root,
                "library:primitive:%s:" % name_root,
            ),
            identity,
        )

    builder.template(
        prefix + ":kicker",
        tag=literal("kicker-tag", "div"),
        key=keyed_value("kicker"),
        class_name=literal("kicker-class", "universal-library-kicker"),
        text=kicker,
    )
    builder.template(
        prefix + ":name",
        tag=literal("name-tag", "div"),
        key=keyed_value("name"),
        class_name=literal("name-class", "universal-library-name"),
        text=label,
    )
    builder.template(
        prefix + ":fields",
        tag=literal("fields-tag", "div"),
        key=keyed_value("fields"),
        class_name=literal("fields-class", "universal-library-fields"),
        text=field_text,
    )
    builder.template(
        LIBRARY_PRIMITIVE_TEMPLATE_ROOT,
        tag=literal("primitive-tag", "button"),
        key=expression(
            "primitive-key", "concat",
            literal("primitive-key-prefix", "library:primitive:"), identity,
        ),
        class_name=literal(
            "primitive-class", "universal-library-primitive"
        ),
        attributes=(
            builder.attribute(
                prefix + ":attribute:type", "type",
                literal("type", "button"),
            ),
            builder.attribute(
                prefix + ":attribute:primitive-root",
                "data-universal-primitive", identity,
            ),
            builder.attribute(
                prefix + ":attribute:active", "data-active",
                expression(
                    "active-value", "choose", selected,
                    literal("active-true", "true"), missing,
                ),
            ),
        ),
        children=(
            prefix + ":kicker", prefix + ":name", prefix + ":fields"
        ),
    )
    return LIBRARY_PRIMITIVE_TEMPLATE_ROOT


__all__ = [
    "LIBRARY_PRIMITIVE_PREFIX",
    "LIBRARY_PRIMITIVE_TEMPLATE_MEMBER_ROOTS",
    "LIBRARY_PRIMITIVE_TEMPLATE_ROOT",
    "compose_library_primitive_template",
]
