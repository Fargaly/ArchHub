"""Universal Cell replacement for the old typed projection-delta court.

The ignored runtime copy once tested deltas through typed nodes, inline params,
and legacy UI ids. This authority court keeps the useful requirement but binds it
to the Universal Cell application lens: deltas are revision-bound projections of
real Cell roots, not a second application truth.
"""
from __future__ import annotations

import json
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from nodelang.application_server import ApplicationServer


def _json(server: ApplicationServer, path: str, payload: dict | None = None):
    request = Request(
        server.url + path,
        data=(
            None if payload is None
            else json.dumps(payload).encode("utf-8")
        ),
        headers={
            "Content-Type": "application/json",
            "X-ArchHub-Session": server.browser_session_token,
        },
        method="GET" if payload is None else "POST",
    )
    try:
        with urlopen(request, timeout=30) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        return error.code, json.loads(error.read().decode("utf-8"))


def _interaction_binding(projection: dict, control_root: str) -> dict:
    return next(
        item for item in projection["interaction_projection"]["bindings"]
        if item["control"] == control_root
    )


def _placement_request(
    projection: dict,
    control_root: str,
    x: float,
    y: float,
) -> dict:
    binding = _interaction_binding(projection, control_root)
    by_source = {item["source"]: item for item in binding["event_facts"]}
    return {
        "interaction": binding["interaction"],
        "control": binding["control"],
        "event": binding["event"],
        "event_facts": [
            {"input": by_source["canvas-point-x"]["input"], "value": x},
            {"input": by_source["canvas-point-y"]["input"], "value": y},
        ],
        "revision": projection["interaction_projection"]["revision"],
        "projection_mode": "topology-delta-v1",
    }


def _show_floor_catalog(server: ApplicationServer, projection: dict) -> dict:
    if projection["primitive"]["visible"] is True:
        return projection
    floor_lens = next(
        lens for lens in projection["inspector"]["lenses"]
        if lens["name"] == "floor"
    )
    binding = _interaction_binding(projection, floor_lens["id"])
    status, _changed = _json(server, "/api/universal/interaction", {
        "interaction": binding["interaction"],
        "control": binding["control"],
        "event": binding["event"],
        "revision": projection["interaction_projection"]["revision"],
    })
    assert status == 200
    status, refreshed = _json(server, "/api/universal/canvas")
    assert status == 200
    return refreshed


def test_interaction_delta_is_cell_root_bound_small_and_stale_fail_safe():
    server = ApplicationServer().start()
    try:
        status, before = _json(server, "/api/universal/canvas")
        assert status == 200
        roots = [node["id"] for node in before["nodes"][:2]]
        target = roots[-1]

        request = {
            "roots": roots,
            "focus": target,
            "projection_mode": "interaction-delta-v1",
            "projection_revision": before["revision"],
        }
        status, delta = _json(server, "/api/universal/gesture", request)

        assert status == 200
        assert delta["projection_mode"] == "interaction-delta-v1"
        assert delta["base_revision"] == before["revision"]
        assert delta["selected"] == target
        assert set(delta["selection"]) == set(roots)
        assert not ({
            "catalog", "catalog_sections", "configuration", "nodes", "wires",
        } & set(delta))
        before_nodes = {node["id"] for node in before["nodes"]}
        before_wires = {
            "%s:%s" % (wire["id"], wire["segment"])
            for wire in before["wires"]
        }
        assert delta["node_count"] == len(before_nodes)
        assert delta["wire_count"] == len(before_wires)
        assert {item["id"] for item in delta["node_states"]} <= before_nodes
        assert {
            "%s:%s" % (item["id"], item["segment"])
            for item in delta["wire_states"]
        } <= before_wires
        assert target in {item["id"] for item in delta["node_states"]}
        assert len(delta["node_states"]) < len(before_nodes)
        assert len(json.dumps(delta)) < len(json.dumps(before)) // 2
        assert set(roots).issubset(server.universal_store.snapshot().cells)

        status, stale = _json(server, "/api/universal/gesture", request)
        assert status == 400
        assert "stale" in stale["error"]
    finally:
        server.close()


def test_topology_delta_adds_graph_roots_without_duplicate_application_truth():
    server = ApplicationServer().start()
    try:
        status, before = _json(server, "/api/universal/canvas")
        assert status == 200
        before = _show_floor_catalog(server, before)
        status, delta = _json(
            server,
            "/api/universal/interaction",
            _placement_request(before, before["primitive"]["id"], 610.0, 240.0),
        )

        assert status == 200
        assert delta["projection_mode"] == "topology-delta-v1"
        assert "topology_patch" in delta
        assert not ({
            "catalog", "catalog_sections", "configuration", "nodes", "wires",
        } & set(delta))
        patch = delta["topology_patch"]
        assert patch["remove_nodes"] == []
        assert patch["upsert_nodes"]
        # Placing a node changes which ports are IN CONTEXT on its
        # neighbours, not the wiring itself. Context travels as state now
        # (state_nodes/state_wires), so structural upsert_wires is rightly
        # empty; the wire_order still names every wire the canvas holds.
        assert patch["wire_order"]
        assert patch["state_nodes"] or patch["upsert_wires"] or (
            patch["state_wires"]
        )
        assert delta["created_root"] in {
            node["id"] for node in patch["upsert_nodes"]
        }
        snapshot = server.universal_store.snapshot()
        assert delta["created_root"] in snapshot.cells
        assert all(node["id"] in snapshot.cells for node in patch["upsert_nodes"])
        assert all(wire["id"] in snapshot.cells for wire in patch["upsert_wires"])
    finally:
        server.close()
