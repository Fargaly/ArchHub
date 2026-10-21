"""Lean browser document projected from the universal application graph."""
from __future__ import annotations

import re

from .cell_ui import render_ui
from .ui_runtime import UNIVERSAL_CANVAS_SCRIPT
from .universal_application import UniversalApplicationRegistry, read_universal_theme
from .universal_cell import CellStore, InvalidCell


THEME_NAME = re.compile(r"^[a-z][a-z0-9_]*$")
CSRF_TOKEN = re.compile(r"^[A-Za-z0-9_-]{32,128}$")
UNSAFE_CSS = ("</style", "@import", "url(", "expression(")


def project_universal_document(
    store: CellStore,
    registry: UniversalApplicationRegistry,
    *,
    csrf_token: str | None = None,
    authentication_context: object | None = None,
) -> str:
    snapshot = store.snapshot()
    shell = render_ui(
        snapshot, registry.ui_protocol, registry.presentation.ui_root
    )
    theme, _ = read_universal_theme(
        store, registry, authentication_context=authentication_context
    )
    for name, value in theme.items():
        if not THEME_NAME.fullmatch(name):
            raise InvalidCell("theme token name is invalid")
        if any(character in value for character in ";{}<>"):
            raise InvalidCell("theme token value is unsafe")
    stylesheet = snapshot.cells[
        registry.presentation.stylesheet_root
    ].atom.decode("utf-8")
    if any(token in stylesheet.casefold() for token in UNSAFE_CSS):
        raise InvalidCell("stylesheet contains a forbidden external-code path")
    variables = "".join(
        "--%s:%s;" % (name.replace("_", "-"), value)
        for name, value in theme.items()
    )
    script = UNIVERSAL_CANVAS_SCRIPT
    if "</script" in script.casefold():
        raise InvalidCell("client interpreter contains a script terminator")
    if csrf_token is not None and not CSRF_TOKEN.fullmatch(csrf_token):
        raise InvalidCell("browser CSRF token is invalid")
    csrf_meta = (
        '<meta name="archhub-csrf" content="%s">' % csrf_token
        if csrf_token is not None else ""
    )
    return (
        "<!doctype html><html><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        "%s<title>ArchHub</title><style>:root{%s}%s</style></head><body>%s"
        "<script>%s</script></body></html>"
        % (csrf_meta, variables, stylesheet, shell, script)
    )


__all__ = ["project_universal_document"]
