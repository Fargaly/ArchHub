"""Graph-authored Node Library shell."""
from __future__ import annotations

from .cell_protocols import CellBatch
from .cell_view_template import ViewTemplateBuilder, ViewTemplateProtocol


LIBRARY_SHELL_PREFIX = "app:library-shell-template:v1"
LIBRARY_SHELL_TEMPLATE_ROOT = LIBRARY_SHELL_PREFIX + ":surface"
LIBRARY_SHELL_TEMPLATE_MEMBER_ROOTS = (
    LIBRARY_SHELL_TEMPLATE_ROOT,
    LIBRARY_SHELL_PREFIX + ":title",
    LIBRARY_SHELL_PREFIX + ":search",
    LIBRARY_SHELL_PREFIX + ":result-count",
    LIBRARY_SHELL_PREFIX + ":list",
)


def compose_library_shell_template(
    batch: CellBatch,
    protocol: ViewTemplateProtocol,
) -> str:
    """Compose the stable library frame from graph-held title data."""
    builder = ViewTemplateBuilder(batch, protocol)
    prefix = LIBRARY_SHELL_PREFIX

    def literal(name: str, value: object) -> str:
        return builder.literal("%s:expression:%s" % (prefix, name), value)

    def segment(name: str) -> str:
        return builder.atom("%s:segment:%s" % (prefix, name), name)

    def expression(name: str, operation: str, *arguments: str) -> str:
        return builder.expression(
            "%s:expression:%s" % (prefix, name), operation, arguments
        )

    root = expression("root-context", "root")
    title = expression("title", "path", root, segment("title"))
    count_text = expression(
        "count-text", "path", root, segment("count_text")
    )

    builder.template(
        prefix + ":title",
        tag=literal("title-tag", "div"),
        key=literal("title-key", "library:title"),
        class_name=literal("title-class", "panel-title"),
        text=title,
    )
    builder.template(
        prefix + ":search",
        tag=literal("search-tag", "input"),
        key=literal("search-key", "library:search"),
        class_name=literal("search-class", "universal-library-search"),
        attributes=(
            builder.attribute(
                prefix + ":attribute:search-type", "type",
                literal("search-type", "search"),
            ),
            builder.attribute(
                prefix + ":attribute:search-placeholder", "placeholder",
                literal("search-placeholder", "Search nodes"),
            ),
            builder.attribute(
                prefix + ":attribute:search-label", "aria-label",
                literal("search-label", "Search Node Library"),
            ),
            builder.attribute(
                prefix + ":attribute:search-autocomplete", "autocomplete",
                literal("search-autocomplete", "off"),
            ),
            builder.attribute(
                prefix + ":attribute:search-spellcheck", "spellcheck",
                literal("search-spellcheck", "false"),
            ),
            builder.attribute(
                prefix + ":attribute:search-root",
                "data-universal-library-search",
                literal("search-present", True),
            ),
        ),
    )
    builder.template(
        prefix + ":result-count",
        tag=literal("result-count-tag", "div"),
        key=literal("result-count-key", "library:result-count"),
        class_name=literal(
            "result-count-class", "universal-library-result-count"
        ),
        text=count_text,
        attributes=(builder.attribute(
            prefix + ":attribute:result-count-root",
            "data-universal-library-result-count",
            literal("result-count-present", True),
        ),),
    )
    builder.template(
        prefix + ":list",
        tag=literal("list-tag", "div"),
        key=literal("list-key", "library:list"),
        class_name=literal("list-class", "library-list universal-library"),
        attributes=(builder.attribute(
            prefix + ":attribute:list-root",
            "data-universal-library-list",
            literal("list-present", True),
        ),),
    )
    builder.template(
        LIBRARY_SHELL_TEMPLATE_ROOT,
        tag=literal("surface-tag", "div"),
        key=literal("surface-key", "library:surface"),
        class_name=literal("surface-class", "universal-library-surface"),
        children=(
            prefix + ":title",
            prefix + ":search",
            prefix + ":result-count",
            prefix + ":list",
        ),
    )
    return LIBRARY_SHELL_TEMPLATE_ROOT


__all__ = [
    "LIBRARY_SHELL_PREFIX",
    "LIBRARY_SHELL_TEMPLATE_MEMBER_ROOTS",
    "LIBRARY_SHELL_TEMPLATE_ROOT",
    "compose_library_shell_template",
]
