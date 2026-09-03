"""Graph-authored relation-composer form for the Build catalogue."""
from __future__ import annotations

from .cell_protocols import CellBatch
from .cell_view_template import ViewTemplateBuilder, ViewTemplateProtocol


RELATION_COMPOSER_VIEW_PREFIX = "app:relation-composer-template:v3"
RELATION_COMPOSER_VIEW_TEMPLATE_ROOT = (
    RELATION_COMPOSER_VIEW_PREFIX + ":form"
)
RELATION_COMPOSER_VIEW_TEMPLATE_MEMBER_ROOTS = (
    RELATION_COMPOSER_VIEW_TEMPLATE_ROOT,
    RELATION_COMPOSER_VIEW_PREFIX + ":heading",
    RELATION_COMPOSER_VIEW_PREFIX + ":help",
    RELATION_COMPOSER_VIEW_PREFIX + ":role",
    RELATION_COMPOSER_VIEW_PREFIX + ":role-label",
    RELATION_COMPOSER_VIEW_PREFIX + ":fixed",
    RELATION_COMPOSER_VIEW_PREFIX + ":entry",
    RELATION_COMPOSER_VIEW_PREFIX + ":select",
    RELATION_COMPOSER_VIEW_PREFIX + ":placeholder",
    RELATION_COMPOSER_VIEW_PREFIX + ":option",
    RELATION_COMPOSER_VIEW_PREFIX + ":remove",
    RELATION_COMPOSER_VIEW_PREFIX + ":add",
    RELATION_COMPOSER_VIEW_PREFIX + ":unavailable",
    RELATION_COMPOSER_VIEW_PREFIX + ":create",
)


def compose_relation_composer_view_template(
    batch: CellBatch,
    protocol: ViewTemplateProtocol,
) -> str:
    """Compose a bounded relation form entirely from graph projection facts."""
    builder = ViewTemplateBuilder(batch, protocol)
    prefix = RELATION_COMPOSER_VIEW_PREFIX
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

    def path(name: str, base: str, *segments: str) -> str:
        return expression(name, "path", base, *segments)

    root = expression("root-context", "root")
    item = expression("item-context", "item")
    definition = path("definition", root, segment("definition"))
    name = path("name", root, segment("name"))
    roles = path("roles", root, segment("roles"))
    complete = path("complete", root, segment("complete"))

    role_id = path("role-id", item, segment("role"))
    role_key = path("role-key", item, segment("key"))
    role_label = path("role-label", item, segment("requirement"))
    fixed = path("role-fixed", item, segment("fixed"))
    fixed_label = path("role-fixed-label", item, segment("fixed_label"))
    entries = path("role-entries", item, segment("entries"))
    can_add = path("role-can-add", item, segment("can_add"))
    unavailable = path("role-unavailable", item, segment("unavailable"))

    entry_id = path("entry-id", item, segment("id"))
    entry_key = path("entry-key", item, segment("key"))
    entry_definition = path(
        "entry-definition", item, segment("definition")
    )
    entry_role = path("entry-role", item, segment("role"))
    entry_value = path("entry-value", item, segment("value"))
    entry_label = path("entry-label", item, segment("label"))
    entry_choices = path("entry-choices", item, segment("choices"))
    placeholder_selected = path(
        "placeholder-selected", item, segment("placeholder_selected")
    )
    remove_disabled = path(
        "remove-disabled", item, segment("remove_disabled")
    )
    remove_control = path(
        "remove-control", item, segment("remove_control")
    )
    select_control = path(
        "select-control", item, segment("select_control")
    )

    choice_id = path("choice-id", item, segment("id"))
    choice_key = path("choice-key", item, segment("key"))
    choice_label = path("choice-label", item, segment("label"))
    choice_selected = path("choice-selected", item, segment("selected"))
    add_control = path("add-control", item, segment("add_control"))
    create_control = path("create-control", root, segment("create_control"))

    builder.template(
        prefix + ":heading",
        tag=literal("heading-tag", "div"),
        key=expression(
            "heading-key", "concat",
            literal("heading-prefix", "relation-composer:heading:"),
            definition,
        ),
        class_name=literal("heading-class", "inspector-heading"),
        text=name,
    )
    builder.template(
        prefix + ":help",
        tag=literal("help-tag", "div"),
        key=expression(
            "help-key", "concat",
            literal("help-prefix", "relation-composer:help:"), definition,
        ),
        class_name=literal("help-class", "universal-library-meta"),
        text=literal(
            "help-text",
            "Choose the visible nodes that participate in this relation.",
        ),
    )
    builder.template(
        prefix + ":role-label",
        tag=literal("role-label-tag", "div"),
        key=expression(
            "role-label-key", "concat",
            literal("role-label-prefix", "relation-composer:role-label:"),
            role_key,
        ),
        class_name=literal("role-label-class", "property-label"),
        text=role_label,
    )
    builder.template(
        prefix + ":fixed",
        tag=literal("fixed-tag", "div"),
        key=expression(
            "fixed-key", "concat",
            literal("fixed-prefix", "relation-composer:fixed:"), role_key,
        ),
        class_name=literal("fixed-class", "connection-box"),
        text=fixed_label,
        condition=fixed,
    )
    builder.template(
        prefix + ":placeholder",
        tag=literal("placeholder-tag", "option"),
        key=expression(
            "placeholder-key", "concat",
            literal("placeholder-prefix", "relation-composer:placeholder:"),
            entry_key,
        ),
        text=literal("placeholder-text", "Select a visible node"),
        value=literal("placeholder-value", ""),
        attributes=(builder.attribute(
            prefix + ":attribute:placeholder-selected",
            "data-selected",
            placeholder_selected,
        ),),
    )
    builder.template(
        prefix + ":option",
        tag=literal("option-tag", "option"),
        key=choice_key,
        text=choice_label,
        value=choice_id,
        attributes=(builder.attribute(
            prefix + ":attribute:option-selected",
            "data-selected",
            choice_selected,
        ),),
        repeat=entry_choices,
    )
    builder.template(
        prefix + ":select",
        tag=literal("select-tag", "select"),
        key=expression(
            "select-key", "concat",
            literal("select-prefix", "relation-composer:select:"), entry_key,
        ),
        class_name=literal("select-class", "property-input"),
        value=entry_value,
        attributes=(
            builder.attribute(
                prefix + ":attribute:select-label", "aria-label", entry_label
            ),
            builder.attribute(
                prefix + ":attribute:select-definition",
                "data-universal-contract-definition", entry_definition,
            ),
            builder.attribute(
                prefix + ":attribute:select-role",
                "data-universal-contract-role", entry_role,
            ),
            builder.attribute(
                prefix + ":attribute:select-entry",
                "data-universal-contract-entry", entry_id,
            ),
            builder.attribute(
                prefix + ":attribute:select-control",
                "data-universal-relation-control", select_control,
            ),
        ),
        children=(prefix + ":placeholder", prefix + ":option"),
    )
    builder.template(
        prefix + ":remove",
        tag=literal("remove-tag", "button"),
        key=expression(
            "remove-key", "concat",
            literal("remove-prefix", "relation-composer:remove:"), entry_key,
        ),
        class_name=literal("remove-class", "header-action"),
        text=literal("remove-text", "Remove"),
        attributes=(
            builder.attribute(
                prefix + ":attribute:remove-type", "type",
                literal("remove-type", "button"),
            ),
            builder.attribute(
                prefix + ":attribute:remove-disabled", "disabled",
                remove_disabled,
            ),
            builder.attribute(
                prefix + ":attribute:remove-definition",
                "data-universal-contract-remove", entry_definition,
            ),
            builder.attribute(
                prefix + ":attribute:remove-role",
                "data-universal-contract-role", entry_role,
            ),
            builder.attribute(
                prefix + ":attribute:remove-entry",
                "data-universal-contract-entry", entry_id,
            ),
            builder.attribute(
                prefix + ":attribute:remove-control",
                "data-universal-relation-control", remove_control,
            ),
        ),
    )
    builder.template(
        prefix + ":entry",
        tag=literal("entry-tag", "div"),
        key=entry_key,
        class_name=literal("entry-class", "universal-collection-row"),
        children=(prefix + ":select", prefix + ":remove"),
        repeat=entries,
    )
    builder.template(
        prefix + ":add",
        tag=literal("add-tag", "button"),
        key=expression(
            "add-key", "concat",
            literal("add-prefix", "relation-composer:add:"), role_key,
        ),
        class_name=literal("add-class", "header-action"),
        text=literal("add-text", "Add participant"),
        attributes=(
            builder.attribute(
                prefix + ":attribute:add-type", "type",
                literal("add-type", "button"),
            ),
            builder.attribute(
                prefix + ":attribute:add-definition",
                "data-universal-contract-add", definition,
            ),
            builder.attribute(
                prefix + ":attribute:add-role",
                "data-universal-contract-role", role_id,
            ),
            builder.attribute(
                prefix + ":attribute:add-control",
                "data-universal-relation-control", add_control,
            ),
        ),
        condition=can_add,
    )
    builder.template(
        prefix + ":unavailable",
        tag=literal("unavailable-tag", "div"),
        key=expression(
            "unavailable-key", "concat",
            literal("unavailable-prefix", "relation-composer:unavailable:"),
            role_key,
        ),
        class_name=literal("unavailable-class", "universal-library-meta"),
        text=literal(
            "unavailable-text",
            "No compatible visible node is available in this scope.",
        ),
        condition=unavailable,
    )
    builder.template(
        prefix + ":role",
        tag=literal("role-tag", "div"),
        key=role_key,
        class_name=literal(
            "role-class", "property-row universal-contract-role"
        ),
        children=(
            prefix + ":role-label",
            prefix + ":fixed",
            prefix + ":entry",
            prefix + ":add",
            prefix + ":unavailable",
        ),
        repeat=roles,
    )
    builder.template(
        prefix + ":create",
        tag=literal("create-tag", "button"),
        key=expression(
            "create-key", "concat",
            literal("create-prefix", "relation-composer:create:"), definition,
        ),
        class_name=literal(
            "create-class", "header-action header-primary"
        ),
        text=literal("create-text", "Create relation"),
        attributes=(
            builder.attribute(
                prefix + ":attribute:create-type", "type",
                literal("create-type", "button"),
            ),
            builder.attribute(
                prefix + ":attribute:create-disabled", "disabled",
                expression("create-disabled", "not", complete),
            ),
            builder.attribute(
                prefix + ":attribute:create-definition",
                "data-universal-contract-create", definition,
            ),
            builder.attribute(
                prefix + ":attribute:create-control",
                "data-universal-relation-control", create_control,
            ),
        ),
    )
    builder.template(
        RELATION_COMPOSER_VIEW_TEMPLATE_ROOT,
        tag=literal("form-tag", "section"),
        key=expression(
            "form-key", "concat",
            literal("form-prefix", "library:relation-composer:"), definition,
        ),
        class_name=literal(
            "form-class", "inspector-section universal-relation-composer"
        ),
        attributes=(builder.attribute(
            prefix + ":attribute:form-definition",
            "data-universal-relation-composer", definition,
        ),),
        children=(
            prefix + ":heading",
            prefix + ":help",
            prefix + ":role",
            prefix + ":create",
        ),
    )
    return RELATION_COMPOSER_VIEW_TEMPLATE_ROOT


__all__ = [
    "RELATION_COMPOSER_VIEW_PREFIX",
    "RELATION_COMPOSER_VIEW_TEMPLATE_MEMBER_ROOTS",
    "RELATION_COMPOSER_VIEW_TEMPLATE_ROOT",
    "compose_relation_composer_view_template",
]
