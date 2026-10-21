"""A drag is one commit and no canvas projection, with every refusal kept.

The founder measured 29 s to save one drag on his own graph. 94% of that was
the canvas projected three times around a 0.38 s write: by the client before
the save, inside the save to read back where the moved nodes were, and by the
client again afterwards to confirm. The precondition compares two facts, the
points of the moved nodes and the scope, so the owner keeps those two,
revision-stamped, and the save reads them instead of the whole canvas.

That lease is trusted only while it still names the live Store revision, so
any other commit puts the full projection back in the path. These courts bind
both halves: the saving path costs no projection and one commit, and every
refusal the precondition owes -- a foreign scope, a root this canvas does not
hold, a node moved underneath, a position that is not finite, a revision ahead
of the graph -- still lands, and never advances the graph.
"""
from __future__ import annotations

import json
import math
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from nodelang.application_server import ApplicationServer
from nodelang.universal_cell import CellStore


def _json(server: ApplicationServer, path: str, payload: dict | None = None):
    request = Request(
        server.url + path,
        data=(None if payload is None
              else json.dumps(payload, allow_nan=True).encode("utf-8")),
        headers={
            "Content-Type": "application/json",
            "X-ArchHub-Session": server.browser_session_token,
            "X-ArchHub-CSRF": server.browser_csrf_token,
        },
        method="GET" if payload is None else "POST",
    )
    try:
        with urlopen(request, timeout=120) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        return error.code, json.loads(error.read().decode("utf-8"))


class _Counter:
    """Count the two acts a drag is allowed: no projection, one commit."""

    def __init__(self, monkeypatch):
        self.projections = 0
        self.commits = 0
        projected = ApplicationServer.project_interaction_canvas
        committed = CellStore.commit

        def count_projection(inner_self, *args, **kwargs):
            self.projections += 1
            return projected(inner_self, *args, **kwargs)

        def count_commit(inner_self, *args, **kwargs):
            revision = committed(inner_self, *args, **kwargs)
            self.commits += 1
            return revision

        monkeypatch.setattr(
            ApplicationServer, "project_interaction_canvas", count_projection)
        monkeypatch.setattr(CellStore, "commit", count_commit)

    def reset(self):
        self.projections = 0
        self.commits = 0


def _node(canvas, root):
    return next(node for node in canvas["nodes"] if node["id"] == root)


def _save(server, canvas, moved, *, scope=None, bases=None, revision=None):
    return _json(server, "/api/universal/gesture", {
        "expected_scope": (
            scope if scope is not None else canvas["scope"]["current"]),
        "positions": moved,
        "expected_positions": (
            bases if bases is not None
            else {root: {"x": _node(canvas, root)["x"],
                         "y": _node(canvas, root)["y"]} for root in moved}
        ),
        "projection_mode": "receipt-v1",
        "projection_revision": (
            canvas["revision"] if revision is None else revision),
    })


def _advanced(canvas, moved, receipt):
    """The canvas a client holds after a receipt: its points, its revision."""
    return {
        **canvas,
        "revision": receipt["committed_revision"],
        "nodes": [
            {**node, **moved[node["id"]]} if node["id"] in moved else node
            for node in canvas["nodes"]
        ],
    }


def test_a_layout_save_projects_the_canvas_never_and_commits_once(monkeypatch):
    server = ApplicationServer().start()
    counter = _Counter(monkeypatch)
    try:
        status, canvas = _json(server, "/api/universal/canvas")
        assert status == 200
        roots = [node["id"] for node in canvas["nodes"]]
        assert len(roots) >= 2

        counter.reset()
        moved = {root: {"x": _node(canvas, root)["x"] + 7,
                        "y": _node(canvas, root)["y"] + 5} for root in roots}
        status, receipt = _save(server, canvas, moved)
        assert status == 200, receipt
        assert receipt["projection_mode"] == "receipt-v1"
        assert receipt["base_revision"] == canvas["revision"]
        assert receipt["committed_revision"] > canvas["revision"]
        # The whole point: the save read the two facts it compares, not the canvas.
        assert counter.projections == 0
        # One drag of many nodes is one commit, whatever N is.
        assert counter.commits == 1

        # And the next drag needs no canvas read to run: the receipt named the
        # revision and the client already holds the points it just sent.
        held = _advanced(canvas, moved, receipt)
        counter.reset()
        again = {root: {"x": _node(held, root)["x"] - 3,
                        "y": _node(held, root)["y"]} for root in roots[:1]}
        status, second = _save(server, held, again)
        assert status == 200, second
        assert counter.projections == 0
        assert counter.commits == 1
        assert second["base_revision"] == held["revision"]

        status, fresh = _json(server, "/api/universal/canvas")
        assert status == 200
        assert _node(fresh, roots[0])["x"] == again[roots[0]]["x"]
        assert _node(fresh, roots[-1])["y"] == moved[roots[-1]]["y"]
    finally:
        server.close()


def test_one_node_and_many_nodes_are_each_exactly_one_commit(monkeypatch):
    server = ApplicationServer().start()
    counter = _Counter(monkeypatch)
    try:
        status, canvas = _json(server, "/api/universal/canvas")
        assert status == 200
        roots = [node["id"] for node in canvas["nodes"]]
        assert len(roots) >= 3
        for chosen in (roots[:1], roots):
            counter.reset()
            moved = {root: {"x": _node(canvas, root)["x"] + 1,
                            "y": _node(canvas, root)["y"] + 1} for root in chosen}
            status, receipt = _save(server, canvas, moved)
            assert status == 200, receipt
            assert counter.commits == 1, (len(chosen), counter.commits)
            canvas = _advanced(canvas, moved, receipt)
    finally:
        server.close()


def test_every_layout_refusal_still_lands_through_the_lease(monkeypatch):
    server = ApplicationServer().start()
    counter = _Counter(monkeypatch)
    try:
        status, canvas = _json(server, "/api/universal/canvas")
        assert status == 200
        roots = [node["id"] for node in canvas["nodes"]]
        root = roots[0]
        point = {"x": _node(canvas, root)["x"], "y": _node(canvas, root)["y"]}
        settled = server.universal_store.revision

        def refused(message, payload):
            before = server.universal_store.revision
            counter.reset()
            status, answer = _json(server, "/api/universal/gesture", payload)
            assert status == 400, (message, status, answer)
            assert message in answer["error"], (message, answer["error"])
            assert server.universal_store.revision == before, message

        # A scope this canvas is not in.
        refused("scope", {
            "expected_scope": roots[-1], "positions": {root: {"x": 1, "y": 2}},
            "expected_positions": {root: point},
            "projection_mode": "receipt-v1", "projection_revision": settled})
        # A root this canvas does not hold.
        refused("left this canvas", {
            "expected_scope": canvas["scope"]["current"],
            "positions": {"cell:not-on-this-canvas": {"x": 1, "y": 2}},
            "expected_positions": {"cell:not-on-this-canvas": {"x": 0, "y": 0}},
            "projection_mode": "receipt-v1", "projection_revision": settled})
        # A base that is not where the node is.
        refused("changed position", {
            "expected_scope": canvas["scope"]["current"],
            "positions": {root: {"x": 1, "y": 2}},
            "expected_positions": {root: {"x": point["x"] + 1000,
                                          "y": point["y"] - 1000}},
            "projection_mode": "receipt-v1", "projection_revision": settled})
        # A position that is not a finite number.
        refused("coordinates or preconditions are invalid", {
            "expected_scope": canvas["scope"]["current"],
            "positions": {root: {"x": math.inf, "y": 2}},
            "expected_positions": {root: point},
            "projection_mode": "receipt-v1", "projection_revision": settled})
        # A revision ahead of the graph.
        refused("layout preconditions are invalid", {
            "expected_scope": canvas["scope"]["current"],
            "positions": {root: {"x": 1, "y": 2}},
            "expected_positions": {root: point},
            "projection_mode": "receipt-v1", "projection_revision": settled + 50})
        # Layout preconditions belong to the canvas gesture and nothing else.
        status, answer = _json(server, "/api/universal/select", {
            "roots": [root], "focus": root,
            "positions": {root: {"x": 1, "y": 2}},
            "expected_positions": {root: point},
            "expected_scope": canvas["scope"]["current"],
            "projection_mode": "receipt-v1", "projection_revision": settled})
        assert status == 400 and "canvas gesture" in answer["error"], answer
        assert server.universal_store.revision == settled
    finally:
        server.close()


def test_the_lease_never_answers_for_a_canvas_another_commit_moved(monkeypatch):
    server = ApplicationServer().start()
    counter = _Counter(monkeypatch)
    try:
        status, canvas = _json(server, "/api/universal/canvas")
        assert status == 200
        roots = [node["id"] for node in canvas["nodes"]]
        root = roots[0]
        stale = {"x": _node(canvas, root)["x"], "y": _node(canvas, root)["y"]}

        # Somebody else moves the same node through the other owner route, and
        # takes no projection back, so nothing re-leases the canvas for anyone.
        status, elsewhere = _json(server, "/api/universal/move", {
            "root": root, "x": stale["x"] + 40, "y": stale["y"] + 40,
            "projection": False})
        assert status == 200, elsewhere
        assert server.universal_store.revision > canvas["revision"]

        # The drag that started before that move is refused, and the refusal is
        # decided by a real projection because the lease no longer names the
        # live revision. A lease trusted past its revision would admit it.
        counter.reset()
        status, answer = _json(server, "/api/universal/gesture", {
            "expected_scope": canvas["scope"]["current"],
            "positions": {root: {"x": 11, "y": 12}},
            "expected_positions": {root: stale},
            "projection_mode": "receipt-v1",
            "projection_revision": server.universal_store.revision})
        assert status == 400, answer
        assert "changed position" in answer["error"], answer
        assert counter.projections == 1, counter.projections

        # Reading the canvas again re-leases it, and the save is then admitted
        # with no projection at all. The refused points were never written.
        status, fresh = _json(server, "/api/universal/canvas")
        assert status == 200
        assert (_node(fresh, root)["x"], _node(fresh, root)["y"]) == (
            stale["x"] + 40, stale["y"] + 40)
        counter.reset()
        moved = {root: {"x": _node(fresh, root)["x"] + 1,
                        "y": _node(fresh, root)["y"] + 1}}
        status, receipt = _save(server, fresh, moved)
        assert status == 200, receipt
        assert counter.projections == 0
        assert counter.commits == 1
    finally:
        server.close()
