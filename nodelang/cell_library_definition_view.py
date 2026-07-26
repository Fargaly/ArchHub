"""Graph-authored released-assembly row in the node catalogue."""
from __future__ import annotations

from .cell_protocols import CellBatch
from .cell_view_template import ViewTemplateBuilder, ViewTemplateProtocol


LIBRARY_DEFINITION_PREFIX = "app:library-definition-template:v3"
LIBRARY_DEFINITION_TEMPLATE_ROOT = LIBRARY_DEFINITION_PREFIX + ":entry"
LIBRARY_DEFINITION_TEMPLATE_MEMBER_ROOTS = (
    LIBRARY_DEFINITION_TEMPLATE_ROOT,
    LIBRARY_DEFINITION_PREFIX + ":row",
    LIBRARY_DEFINITION_PREFIX + ":place",
    LIBRARY_DEFINITION_PREFIX + ":name",
    LIBRARY_DEFINITION_PREFIX + ":description",
    LIBRARY_DEFINITION_PREFIX + ":meta",
)


def compose_library_definition_template(
    batch: CellBatch,
    protocol: ViewTemplateProtocol,
) -> str:
    """Compose one released assembly entry from catalogue projection facts."""
    builder = ViewTemplateBuilder(batch, protocol)
    prefix = LIBRARY_DEFINITION_PREFIX

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
    version = path("version", root, segment("version"))
    interfaces = path("interfaces", root, segment("interfaces"))
    category = path("category", root, segment("category"))
    description = path("description", root, segment("description"))
    search_text = path("search-text", root, segment("search_text"))
    selected = path("selected", root, segment("selected"))
    control = path("control", root, segment("control"))
    control_owner = path("control-owner", control, segment("owner"))
    control_title = path("control-title", control, segment("title"))
    control_icon = path("control-icon", control, segment("icon"))
    control_activation = path(
        "control-activation", control, segment("activation")
    )
    control_binding = path(
        "control-binding", control_activation, segment("binding")
    )
    control_capability = path(
        "control-capability", control_activation, segment("capability")
    )
    place_title = expression(
        "place-title", "concat", control_title,
        literal("place-title-divider", ": "), name,
    )
    meta = expression(
        "meta", "concat", category,
        literal("interface-prefix", "  /  "), interfaces,
        literal("interfaces-suffix", " interface(s)  /  v"), version,
    )

    def keyed_value(name_root: str) -> str:
        return expression(
            "%s-key" % name_root,
            "concat",
            literal("%s-key-prefix" % name_root, "library:%s:" % name_root),
            identity,
        )

    builder.template(
        prefix + ":name",
        tag=literal("name-tag", "span"),
        key=keyed_value("name"),
        class_name=literal("name-class", "universal-library-name"),
        text=name,
    )
    builder.template(
        prefix + ":description",
        tag=literal("description-tag", "span"),
        key=keyed_value("description"),
        class_name=literal(
            "description-class", "universal-library-description"
        ),
        text=description,
    )
    builder.template(
        prefix + ":meta",
        tag=literal("meta-tag", "span"),
        key=keyed_value("meta"),
        class_name=literal("meta-class", "universal-library-meta"),
        text=meta,
    )
    builder.template(
        prefix + ":row",
        tag=literal("row-tag", "button"),
        key=keyed_value("definition"),
        class_name=literal(
            "row-class", "library-row universal-library-definition"
        ),
        attributes=(
            builder.attribute(
                prefix + ":attribute:row-type", "type",
                literal("row-type", "button"),
            ),
            builder.attribute(
                prefix + ":attribute:definition-root",
                "data-universal-definition", identity,
            ),
            builder.attribute(
                prefix + ":attribute:definition-title",
                "title", description,
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
            prefix + ":name",
            prefix + ":description",
            prefix + ":meta",
        ),
    )
    builder.template(
        prefix + ":place",
        tag=literal("place-tag", "button"),
        key=keyed_value("place"),
        class_name=literal("place-class", "library-definition-place"),
        attributes=(
            builder.attribute(
                prefix + ":attribute:place-type", "type",
                literal("place-type", "button"),
            ),
            builder.attribute(
                prefix + ":attribute:place-definition",
                "data-universal-definition-place", identity,
            ),
            builder.attribute(
                prefix + ":attribute:place-control",
                "data-universal-control",
                control_owner,
            ),
            builder.attribute(
                prefix + ":attribute:place-binding",
                "data-control-binding",
                control_binding,
            ),
            builder.attribute(
                prefix + ":attribute:place-capability",
                "data-control-capability",
                control_capability,
            ),
            builder.attribute(
                prefix + ":attribute:place-icon",
                "data-control-icon",
                control_icon,
            ),
            builder.attribute(
                prefix + ":attribute:place-title", "title", place_title,
            ),
            builder.attribute(
                prefix + ":attribute:place-aria", "aria-label", place_title,
            ),
        ),
    )
    builder.template(
        LIBRARY_DEFINITION_TEMPLATE_ROOT,
        tag=literal("entry-tag", "div"),
        key=keyed_value("entry"),
        class_name=literal("entry-class", "universal-library-entry"),
        attributes=(
            builder.attribute(
                prefix + ":attribute:entry-root",
                "data-universal-library-entry", identity,
            ),
            builder.attribute(
                prefix + ":attribute:search-text",
                "data-universal-search-text", search_text,
            ),
        ),
        children=(prefix + ":row", prefix + ":place"),
    )
    return LIBRARY_DEFINITION_TEMPLATE_ROOT


__all__ = [
    "LIBRARY_DEFINITION_PREFIX",
    "LIBRARY_DEFINITION_TEMPLATE_MEMBER_ROOTS",
    "LIBRARY_DEFINITION_TEMPLATE_ROOT",
    "compose_library_definition_template",
]
