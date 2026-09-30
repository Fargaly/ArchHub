"""Court: opening a scope and coming back out reuses the design system it was sent.

31ccb255 added ``revision`` to the design-system projection, but the scope
transition still demanded the old exact key set, so every scope entry answered
400 "scope transition design system is invalid": no openable node could be
entered. This court enters and leaves a scope twice on a real server, and holds
the reuse check equal to what the projection actually carries.
"""
from __future__ import annotations

from nodelang import universal_application
from nodelang.application_server import ApplicationServer
from tests_replica.test_universal_interaction_server import _activate_scope_interaction, _json


def test_a_scope_is_entered_and_left_twice():
    server = ApplicationServer().start()
    try:
        status, before = _json(server, "/api/universal/canvas")
        assert status == 200
        openable = next(node for node in before["nodes"] if node["openable"])
        canvas = before
        for _ in range(2):
            status, canvas = _activate_scope_interaction(server, canvas, openable["id"])
            assert status == 200, canvas.get("error")
            assert canvas["scope"]["current"] == openable["id"]
            status, canvas = _activate_scope_interaction(server, canvas, "app:control:canvas:scope-up")
            assert status == 200, canvas.get("error")
            assert canvas["scope"]["current"] == before["scope"]["current"]
    finally:
        server.close()


def test_the_reuse_check_accepts_the_design_system_a_real_projection_carries():
    server = ApplicationServer()
    try:
        status, projection = _json(server.start(), "/api/universal/canvas")
        assert status == 200
        reused = universal_application._reusable_static_design_system(projection)
        carried = set(projection["configuration"]["design_system"])
        assert set(reused) == carried - {"control_catalog"}
    finally:
        server.close()
