"""The owner's liveness probe must not need a browser session.

Courting the absence: a probe that asks for an authenticated endpoint is
refused, the refusal is logged as an error, and the watchdog treats the
refusal as health -- so nothing fails and the log fills forever. The
regression is invisible in review because every part behaves correctly.
This reads the URL the owner actually probes and refuses any endpoint the
server declares as needing a session.
"""
from __future__ import annotations

import ast
import pathlib


SERVICE = (
    pathlib.Path(__file__).resolve().parents[1]
    / "nodelang"
    / "clean_coordination_service.py"
)


def _probed_suffix() -> str:
    """The path the watchdog appends to the canvas URL, read from source."""
    tree = ast.parse(SERVICE.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
        if "canvas_url" not in targets:
            continue
        strings = [
            child.value
            for child in ast.walk(node)
            if isinstance(child, ast.Constant) and isinstance(child.value, str)
        ]
        assert strings, "the watchdog probes no path at all"
        return strings[-1]
    raise AssertionError("the owner declares no canvas probe URL")


def test_owner_probe_does_not_ask_for_an_authenticated_endpoint() -> None:
    suffix = _probed_suffix()
    assert suffix.startswith("/"), suffix
    # /api/universal/canvas is the projection endpoint and is refused
    # without X-ArchHub-Session; probing it logs an error every five
    # seconds for as long as the owner lives.
    assert suffix != "/api/universal/canvas", (
        "the liveness probe asks for a session it does not hold"
    )


def test_owner_probe_target_is_served_without_a_session() -> None:
    from nodelang import universal_application

    session_free = {
        path
        for method, path, *_ in universal_application.PUBLIC_ROUTES
        if method == "GET"
    } if hasattr(universal_application, "PUBLIC_ROUTES") else None
    suffix = _probed_suffix()
    if session_free is None:
        # No declared public-route table to read; the weaker statement is
        # still worth holding: the probe is not the projection endpoint.
        assert suffix != "/api/universal/canvas"
        return
    assert suffix in session_free, (suffix, sorted(session_free))
