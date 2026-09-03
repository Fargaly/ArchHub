"""Every route the server answers must be reachable from the product.

The application server answers thirty-seven paths. The canvas the founder
opens can call ten of them -- those are the ones its own served source
names -- and the shell adds the stylesheet, health, and boot. A route no
product module can reach is surface the server must still admit, guard,
and keep correct, for a caller that does not exist.

This court reads both sides from source: the paths the server dispatches
on, and the paths every product module (the served client included) names.
It fails when the server grows a route nothing reaches, which is the shape
this file exists to stop.
"""
from __future__ import annotations

import pathlib
import re


NODELANG = pathlib.Path(__file__).resolve().parents[1] / "nodelang"
SERVER = NODELANG / "application_server.py"

_DISPATCH = re.compile(
    r"(?:self|parsed)\.path\s*(?:==|\.startswith\()\s*['\"](/api/universal/[a-z0-9/_-]+)"
)
_NAMED = re.compile(r"['\"](/api/universal/[a-z0-9/_-]+)['\"]")

# A route whose only caller is the server's own table. Recorded so the
# court states what is known rather than pretending the tree is clean:
# nothing in the product reaches it, and removing it is a decision, not a
# cleanup this file may make on its own.
UNREACHED = frozenset({"/api/universal/focus"})


def _served() -> frozenset[str]:
    return frozenset(_DISPATCH.findall(SERVER.read_text(encoding="utf-8")))


def _reached() -> frozenset[str]:
    reached: set[str] = set()
    for path in NODELANG.glob("*.py"):
        if path.name == "application_server.py":
            continue
        reached |= set(_NAMED.findall(path.read_text(encoding="utf-8")))
    return frozenset(reached)


def test_the_server_dispatches_on_paths_this_court_can_read() -> None:
    served = _served()
    # A floor that says "the parser found the dispatcher", not a count.
    # Counting served routes here would make this court fail every time
    # the surface is cut, which is the opposite of what it is for.
    assert len(served) >= 10, sorted(served)
    assert "/api/universal/canvas" in served
    assert "/api/universal/interaction" in served


def test_every_served_route_is_reached_by_some_product_module() -> None:
    unreached = _served() - _reached() - UNREACHED
    assert not unreached, (
        "the server answers a route no product module can reach: %s"
        % sorted(unreached)
    )


def test_the_recorded_unreached_routes_are_still_unreached() -> None:
    """A recorded exception that quietly gains a caller is no longer an
    exception, and the record must shrink rather than rot."""
    still = UNREACHED - _reached()
    assert still == UNREACHED, (
        "these recorded routes now have a caller and must leave the "
        "exception list: %s" % sorted(UNREACHED - still)
    )


def test_the_served_canvas_names_the_routes_it_calls() -> None:
    """The client is source the server ships, so what the canvas can reach
    is readable, not guessed."""
    client = frozenset(
        _NAMED.findall((NODELANG / "ui_runtime.py").read_text(encoding="utf-8"))
    )
    assert "/api/universal/canvas" in client
    assert "/api/universal/gesture" in client
    assert "/api/universal/interaction" in client
    assert client <= _served(), sorted(client - _served())
    # The canvas reaches a minority of what the server answers. That gap is
    # the second authority's surface, and it is the number a cut is judged
    # against.
    assert len(client) < len(_served())
