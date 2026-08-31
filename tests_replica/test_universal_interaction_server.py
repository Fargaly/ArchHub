"""HTTP court for the single generic Universal Cell interaction endpoint."""
import json
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from nodelang.application_server import (
    ApplicationServer,
    _interaction_canvas_delta,
    _topology_canvas_delta,
)


def _json(server, path, payload=None):
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


def _merge_projection_delta(previous, result):
    if result.get("projection_mode") not in {
        "interaction-delta-v1", "topology-delta-v1",
    }:
        return result
    merged = {**previous, **result}
    configuration = {
        **previous["configuration"],
        **result["configuration_state"],
    }
    configuration["design_system"] = {
        **previous["configuration"]["design_system"],
        "control_catalog": result["control_state"],
    }
    merged["configuration"] = configuration
    patch = result.get("topology_patch")
    if patch is not None:
        nodes = {node["id"]: node for node in previous["nodes"]}
        wires = {
            f"{wire['id']}:{wire['segment']}": wire
            for wire in previous["wires"]
        }
        for root in patch["remove_nodes"]:
            nodes.pop(root, None)
        for root in patch["remove_wires"]:
            wires.pop(root, None)
        nodes.update({node["id"]: node for node in patch["upsert_nodes"]})
        wires.update({
            f"{wire['id']}:{wire['segment']}": wire
            for wire in patch["upsert_wires"]
        })
        # Selection, position and port context ride the light channel, exactly
        # as the browser client applies them.
        for state in patch.get("node_context", ()):
            node = nodes.get(state["id"])
            if node is None:
                continue
            updated = dict(node)
            updated.update({
                "selected": state["selected"],
                "x": state["x"],
                "y": state["y"],
            })
            flags = state.get("ports")
            if isinstance(flags, list) and isinstance(node.get("ports"), list):
                ports = []
                for index, port in enumerate(node["ports"]):
                    flag = flags[index] if index < len(flags) else None
                    descriptor = port.get("descriptor") if isinstance(port, dict) else None
                    if flag is None or not isinstance(descriptor, list):
                        ports.append(port)
                        continue
                    rendered = []
                    for item in descriptor:
                        attributes = item.get("attributes") if isinstance(item, dict) else None
                        if isinstance(attributes, dict) and "data-context" in attributes:
                            item = dict(item)
                            item["attributes"] = {**attributes, "data-context": flag}
                        rendered.append(item)
                    ports.append({**port, "descriptor": rendered})
                updated["ports"] = ports
            nodes[state["id"]] = updated
        for state in patch.get("wire_context", ()):
            key = "%s:%s" % (state["id"], state["segment"])
            wire = wires.get(key)
            if wire is None:
                continue
            wires[key] = {
                **wire,
                "selected": state["selected"],
                "context": state["context"],
            }
        merged["nodes"] = [nodes[root] for root in patch["node_order"]]
        merged["wires"] = [wires[root] for root in patch["wire_order"]]
    elif result.get("topology_recovery") is not True:
        node_states = {node["id"]: node for node in result["node_states"]}
        wire_states = {
            f"{wire['id']}:{wire['segment']}": wire
            for wire in result["wire_states"]
        }
        node_patches = {
            node["id"]: node for node in result.get("node_patches", ())
        }
        wire_patches = {
            f"{wire['id']}:{wire['segment']}": wire
            for wire in result.get("wire_patches", ())
        }
        assert result["node_count"] == len(previous["nodes"])
        assert result["wire_count"] == len(previous["wires"])
        assert set(node_states) <= {node["id"] for node in previous["nodes"]}
        assert set(wire_states) <= {
            f"{wire['id']}:{wire['segment']}" for wire in previous["wires"]
        }
        merged["nodes"] = [
            {
                **node,
                **node_patches.get(node["id"], {}),
                **node_states.get(node["id"], {}),
            }
            for node in previous["nodes"]
        ]
        merged["wires"] = [
            {
                **wire,
                **wire_patches.get(f"{wire['id']}:{wire['segment']}", {}),
                **wire_states.get(f"{wire['id']}:{wire['segment']}", {})
            }
            for wire in previous["wires"]
        ]
    return merged


def _descriptor_nodes(items):
    for item in items:
        yield item
        yield from _descriptor_nodes(item.get("children", ()))


def _interaction_binding(projection, control_root):
    return next(
        item for item in projection["interaction_projection"]["bindings"]
        if item["control"] == control_root
    )


def _event_facts(form, values):
    return [
        {"input": form["inputs"][key], "value": value}
        for key, value in values.items()
    ]


def _placement_request(projection, control_root, x, y):
    binding = _interaction_binding(projection, control_root)
    by_source = {item["source"]: item for item in binding["event_facts"]}
    return {
        "interaction": binding["interaction"],
        "control": binding["control"],
        "event": binding["event"],
        "event_facts": [
            {
                "input": by_source["canvas-point-x"]["input"],
                "value": x,
            },
            {
                "input": by_source["canvas-point-y"]["input"],
                "value": y,
            },
        ],
        "revision": projection["interaction_projection"]["revision"],
        "projection_mode": "topology-delta-v1",
    }


def _create_primitive(server, *, x=420, y=180):
    status, projection = _json(server, "/api/universal/canvas")
    assert status == 200
    if projection["primitive"]["visible"] is not True:
        floor_lens = next(
            lens for lens in projection["inspector"]["lenses"]
            if lens["name"] == "floor"
        )
        binding = _interaction_binding(projection, floor_lens["id"])
        status, _delta = _json(server, "/api/universal/interaction", {
            "interaction": binding["interaction"],
            "control": binding["control"],
            "event": binding["event"],
            "revision": projection["interaction_projection"]["revision"],
        })
        assert status == 200
        status, projection = _json(server, "/api/universal/canvas")
        assert status == 200
    status, created = _json(
        server,
        "/api/universal/interaction",
        _placement_request(
            projection, projection["primitive"]["id"], x, y
        ),
    )
    assert status == 200
    return _merge_projection_delta(projection, created)


def test_properties_tab_uses_one_revision_bound_interaction_endpoint():
    server = ApplicationServer().start()
    try:
        status, before = _json(server, "/api/universal/canvas")
        assert status == 200
        authority = before["interaction_projection"]
        assert authority["lifecycle"] == "wip"
        assert authority["revision"] == server.universal_store.revision
        bindings = {
            item["control"]: item
            for item in authority["bindings"]
        }
        active = before["inspector"]["presentation"]["active"]
        desired = next(control for control in bindings if control != active)
        request = {
            "interaction": bindings[desired]["interaction"],
            "control": desired,
            "event": bindings[desired]["event"],
            "revision": authority["revision"],
        }

        status, changed = _json(
            server, "/api/universal/interaction", request
        )
        assert status == 200
        assert changed["inspector"]["presentation"]["active"] == desired
        assert changed["interaction_projection"]["revision"] == (
            server.universal_store.revision
        )

        status, stale = _json(
            server, "/api/universal/interaction", request
        )
        assert status == 400
        assert "revision" in stale["error"]
        assert server.universal_store.read(
            server.universal_registry.view_sessions[
                server.universal_registry.authorization.subject_root
            ].properties_panel_incidence
        ).link1 == desired

        forged = dict(request)
        forged.update({
            "revision": changed["interaction_projection"]["revision"],
            "control": "app:forged-control",
        })
        status, denied = _json(
            server, "/api/universal/interaction", forged
        )
        assert status == 400
        assert "admitted" in denied["error"]

        broadened = dict(forged)
        broadened["pointer"] = {"x": 1, "y": 2}
        status, denied = _json(
            server, "/api/universal/interaction", broadened
        )
        assert status == 400
        assert "undeclared facts" in denied["error"]
    finally:
        server.close()


def test_property_form_uses_the_same_revision_bound_interaction_endpoint():
    server = ApplicationServer().start()
    try:
        created = _create_primitive(server)
        form = created["authoring"]["property_form"]
        binding = _interaction_binding(created, form["control"])
        facts = _event_facts(form, {
            "label": "Acoustic rating",
            "value": "Rw 50",
        })
        assert {item["input"] for item in binding["event_facts"]} == {
            item["input"] for item in facts
        }
        request = {
            "interaction": binding["interaction"],
            "control": binding["control"],
            "event": binding["event"],
            "event_facts": facts,
            "revision": created["interaction_projection"]["revision"],
            "projection_mode": "interaction-delta-v1",
        }

        status, authored = _json(server, "/api/universal/interaction", request)
        assert status == 200
        relation_root = authored["created_root"]
        row = next(
            item for item in authored["properties"]
            if item["relation"] == relation_root
        )
        assert row["label"] == "Acoustic rating"
        assert row["value"] == "Rw 50"

        before = server.universal_store.revision
        forged = dict(request)
        forged["revision"] = authored["interaction_projection"]["revision"]
        forged["event_facts"] = [
            *facts,
            {"input": "forged:owner", "value": "forged:root"},
        ]
        status, denied = _json(server, "/api/universal/interaction", forged)
        assert status == 400
        assert "event facts" in denied["error"]
        assert server.universal_store.revision == before

        status, retired = _json(
            server, "/api/universal/property-create", {"submitted": {}}
        )
        assert status == 404
        assert retired["error"] == "not found"
    finally:
        server.close()


def test_property_value_edit_uses_graph_issued_control_and_submitted_fact():
    server = ApplicationServer().start()
    try:
        created = _create_primitive(server)
        row = next(
            item for item in created["properties"]
            if item["editable"] is True
        )
        assert row["control"] == row["relation"]
        binding = _interaction_binding(created, row["control"])
        assert binding["inputs"][:2] == [
            row["relation"], row["value_root"],
        ]
        assert binding["event_facts"] == [{
            "input": row["event_fact_input"],
            "source": "submitted",
            "value_kind": "text",
            "required": False,
            "maximum_bytes": 65_536,
        }]
        request = {
            "interaction": binding["interaction"],
            "control": binding["control"],
            "event": binding["event"],
            "event_facts": [{
                "input": row["event_fact_input"],
                "value": "Editable through one Interaction",
            }],
            "revision": created["interaction_projection"]["revision"],
            "projection_mode": "interaction-delta-v1",
        }

        status, edited = _json(server, "/api/universal/interaction", request)
        assert status == 200
        changed = next(
            item for item in edited["properties"]
            if item["relation"] == row["relation"]
        )
        assert changed["value"] == "Editable through one Interaction"

        before = server.universal_store.revision
        forged = dict(request)
        forged.update({
            "revision": edited["interaction_projection"]["revision"],
            "relation": row["relation"],
        })
        status, denied = _json(server, "/api/universal/interaction", forged)
        assert status == 400
        assert "undeclared facts" in denied["error"]
        assert server.universal_store.revision == before

        status, retired = _json(server, "/api/universal/property", {
            "relation": row["relation"],
            "value": "direct bypass",
        })
        assert status == 404
        assert retired["error"] == "not found"
    finally:
        server.close()


def test_interface_form_uses_graph_declared_root_facts_on_the_same_endpoint():
    server = ApplicationServer().start()
    try:
        created = _create_primitive(server)
        form = created["authoring"]["interface_form"]
        binding = _interaction_binding(created, form["control"])
        presentation = next(
            item for item in created["authoring"]["interface_presentations"]
            if item["side"] == "source"
        )
        contract = created["authoring"]["interface_contracts"][0]
        request = {
            "interaction": binding["interaction"],
            "control": binding["control"],
            "event": binding["event"],
            "event_facts": _event_facts(form, {
                "name": "Acoustic source",
                "presentation": presentation["id"],
                "contract": contract["id"],
            }),
            "revision": created["interaction_projection"]["revision"],
            "projection_mode": "interaction-delta-v1",
        }

        status, authored = _json(server, "/api/universal/interaction", request)
        assert status == 200
        interface_root = authored["created_root"]
        socket = next(
            item for item in authored["selected_interfaces"]
            if item["id"] == interface_root
        )
        assert socket["name"] == "Acoustic source"
        assert socket["side"] == "source"
        assert socket["contract_root"] == contract["id"]

        status, retired = _json(
            server, "/api/universal/interface-create", {"submitted": {}}
        )
        assert status == 404
        assert retired["error"] == "not found"
    finally:
        server.close()


def test_catalogue_placement_uses_graph_target_and_bounded_event_facts():
    server = ApplicationServer().start()
    try:
        status, before = _json(server, "/api/universal/canvas")
        assert status == 200
        definition = next(
            item for item in before["catalog"]
            if item.get("composition_contract") is None
        )
        binding = _interaction_binding(before, definition["id"])
        facts_by_source = {
            item["source"]: item for item in binding["event_facts"]
        }
        assert set(facts_by_source) == {
            "canvas-point-x",
            "canvas-point-y",
            "canvas-viewport-pan-x",
            "canvas-viewport-pan-y",
            "canvas-viewport-zoom",
        }
        request = {
            "interaction": binding["interaction"],
            "control": binding["control"],
            "event": binding["event"],
            "event_facts": [
                {
                    "input": facts_by_source["canvas-point-x"]["input"],
                    "value": 460,
                },
                {
                    "input": facts_by_source["canvas-point-y"]["input"],
                    "value": 240,
                },
            ],
            "revision": before["interaction_projection"]["revision"],
            "projection_mode": "topology-delta-v1",
        }
        status, placed_delta = _json(
            server, "/api/universal/interaction", request
        )
        assert status == 200
        assert "topology_patch" in placed_delta
        assert "nodes" not in placed_delta
        assert "wires" not in placed_delta
        assert len(json.dumps(placed_delta)) < len(json.dumps(before)) // 2
        placed = _merge_projection_delta(before, placed_delta)
        created_root = placed["created_root"]
        created = next(
            item for item in placed["nodes"]
            if item["id"] == created_root
        )
        assert created["x"] == 460
        assert created["y"] == 240

        direct_revision = server.universal_store.revision
        status, bypass = _json(server, "/api/universal/instantiate", {
            "definition": definition["id"],
            "x": 600,
            "y": 300,
        })
        assert status == 400
        assert "Interaction lease" in bypass["error"]
        assert server.universal_store.revision == direct_revision

        before_revision = server.universal_store.revision
        status, rejected = _json(server, "/api/universal/interaction", {
            **request,
            "revision": placed["interaction_projection"]["revision"],
            "event_facts": [
                {
                    "input": facts_by_source["canvas-point-x"]["input"],
                    "value": -1,
                },
                {
                    "input": facts_by_source["canvas-point-y"]["input"],
                    "value": 240,
                },
            ],
        })
        assert status == 400
        assert "bounds" in rejected["error"]
        assert server.universal_store.revision == before_revision
    finally:
        server.close()


def test_openable_canvas_node_uses_graph_declared_scope_interaction():
    server = ApplicationServer().start()
    try:
        status, before = _json(server, "/api/universal/canvas")
        assert status == 200
        openable = next(node for node in before["nodes"] if node["openable"])
        binding = _interaction_binding(before, openable["id"])
        assert binding["inputs"] == [
            before["scope"]["current"], openable["id"],
        ]
        request = {
            "interaction": binding["interaction"],
            "control": binding["control"],
            "event": binding["event"],
            "revision": before["interaction_projection"]["revision"],
            "projection_mode": "topology-delta-v1",
        }

        revision = server.universal_store.revision
        status, denied = _json(server, "/api/universal/interaction", {
            **request,
            "event_facts": [],
        })
        assert status == 400
        assert "undeclared event facts" in denied["error"]
        assert server.universal_store.revision == revision

        status, entered = _json(server, "/api/universal/interaction", request)
        assert status == 200
        assert entered["scope"]["current"] == openable["id"]

        revision = server.universal_store.revision
        forged = {
            **request,
            "revision": entered["interaction_projection"]["revision"],
            "control": entered["scope"]["current"],
        }
        status, denied = _json(server, "/api/universal/interaction", forged)
        assert status == 400
        assert "admitted" in denied["error"]
        assert server.universal_store.revision == revision

        status, retired = _json(server, "/api/universal/scope", {
            "target": openable["id"],
        })
        assert status == 404
        assert retired["error"] == "not found"
    finally:
        server.close()


def test_inspector_lens_uses_graph_declared_view_section_interaction():
    server = ApplicationServer().start()
    try:
        status, before = _json(server, "/api/universal/canvas")
        assert status == 200
        active = before["inspector"]["active"]
        desired = next(
            lens["id"] for lens in before["inspector"]["lenses"]
            if lens["id"] != active
        )
        binding = _interaction_binding(before, desired)
        assert binding["inputs"] == [active, desired]
        status, changed = _json(server, "/api/universal/interaction", {
            "interaction": binding["interaction"],
            "control": binding["control"],
            "event": binding["event"],
            "revision": before["interaction_projection"]["revision"],
            "projection_mode": "interaction-delta-v1",
        })
        assert status == 200
        assert changed["inspector"]["active"] == desired

        status, retired = _json(server, "/api/universal/inspector-lens", {
            "lens": active,
        })
        assert status == 404
        assert retired["error"] == "not found"
    finally:
        server.close()


def test_single_property_value_and_canvas_presentation_share_one_delta():
    server = ApplicationServer().start()
    try:
        status, before = _json(server, "/api/universal/canvas")
        assert status == 200
        title = next(
            item for item in before["properties"]
            if item["label"] == "title"
        )
        title_inputs = [
            item
            for panel in before["inspector"]["presentation"]["panels"]
            for component in panel["components"]
            for item in _descriptor_nodes(component.get("descriptor", ()))
            if item.get("key") == "property-input:%s" % title["relation"]
        ]
        assert len(title_inputs) == 1
        assert title_inputs[0]["value"] == title["value"]
        assert "data-universal-mixed" not in title_inputs[0]["attributes"]

        binding = _interaction_binding(before, title["control"])
        edited_title = "%s Court" % title["value"]
        status, delta = _json(server, "/api/universal/interaction", {
            "interaction": binding["interaction"],
            "control": binding["control"],
            "event": binding["event"],
            "event_facts": [{
                "input": title["event_fact_input"],
                "value": edited_title,
            }],
            "revision": before["interaction_projection"]["revision"],
            "projection_mode": "interaction-delta-v1",
        })
        assert status == 200
        assert [node["id"] for node in delta["node_patches"]] == [
            title["owner"]
        ]
        assert delta["wire_patches"] == []
        after = _merge_projection_delta(before, delta)
        assert next(
            node for node in after["nodes"]
            if node["id"] == title["owner"]
        )["label"] == edited_title
        assert next(
            item for item in after["properties"]
            if item["label"] == "title"
        )["value"] == edited_title
    finally:
        server.close()


def test_canvas_interaction_delta_is_revision_bound_and_omits_static_graph():
    server = ApplicationServer().start()
    try:
        status, before = _json(server, "/api/universal/canvas")
        assert status == 200
        targets = [node["id"] for node in before["nodes"][:2]]
        target = targets[-1]
        status, changed = _json(server, "/api/universal/gesture", {
            "roots": targets,
            "focus": target,
            "projection_mode": "interaction-delta-v1",
            "projection_revision": before["revision"],
        })
        assert status == 200
        assert changed["projection_mode"] == "interaction-delta-v1"
        assert changed["base_revision"] == before["revision"]
        assert changed["selected"] == target
        controls = {
            control["owner"]: control
            for control in changed["control_state"]["controls"]
        }
        assert controls["app:control:canvas:group"]["applicable"] is True
        assert controls["app:control:canvas:ungroup"]["applicable"] is False
        selection_status = [
            item for item in _descriptor_nodes(changed["toolbar_descriptor"])
            if item.get("attributes", {}).get(
                "data-universal-toolbar-selection-value"
            ) == "True"
        ]
        assert len(selection_status) == 1
        assert selection_status[0]["text"] == "2 selected"
        assert changed["canvas_heading_descriptor"] == (
            before["canvas_heading_descriptor"]
        )
        assert changed["canvas_signature"] != before["canvas_signature"]
        before_node_roots = {node["id"] for node in before["nodes"]}
        before_wire_roots = {
            "%s:%s" % (wire["id"], wire["segment"])
            for wire in before["wires"]
        }
        assert changed["node_count"] == len(before_node_roots)
        assert changed["wire_count"] == len(before_wire_roots)
        assert {
            item["id"] for item in changed["node_states"]
        } <= before_node_roots
        assert {
            "%s:%s" % (item["id"], item["segment"])
            for item in changed["wire_states"]
        } <= before_wire_roots
        assert target in {item["id"] for item in changed["node_states"]}
        assert len(changed["node_states"]) < len(before["nodes"])
        assert changed["node_patches"] == []
        assert changed["wire_patches"] == []
        assert all(
            set(item) == {"id", "segment", "selected", "context"}
            for item in changed["wire_states"]
        )
        assert not ({
            "catalog", "configuration", "authorization", "nodes", "wires",
        } & set(changed))
        assert len(json.dumps(changed)) < len(json.dumps(before)) // 2

        status, stale = _json(server, "/api/universal/gesture", {
            "roots": targets,
            "focus": target,
            "projection_mode": "interaction-delta-v1",
            "projection_revision": before["revision"],
        })
        assert status == 400
        assert "stale" in stale["error"]
    finally:
        server.close()


def test_interaction_delta_patches_changed_socket_authority():
    base_port = {
        "id": "interface:source",
        "name": "Result",
        "side": "source",
        "mode": "connection",
        "connectable": True,
        "connect_control": "control:connect",
        "connect_choices": [],
    }
    previous = {
        "revision": 8,
        "connections": [],
        "nodes": [{
            "id": "node:source",
            "selected": False,
            "x": 10,
            "y": 20,
            "ports": [base_port],
        }],
        "wires": [],
        "configuration": {
            "design_system": {"control_catalog": {"controls": []}},
        },
    }
    projection = {
        **previous,
        "revision": 9,
        "nodes": [{
            **previous["nodes"][0],
            "ports": [{
                **base_port,
                "connect_choices": [{
                    "id": "interface:target",
                    "owner": "node:target",
                    "label": "Target / Input",
                }],
            }],
        }],
    }

    delta = _interaction_canvas_delta(
        projection,
        base_revision=previous["revision"],
        previous_projection=previous,
    )

    assert [node["id"] for node in delta["node_patches"]] == [
        "node:source"
    ]
    assert delta["node_patches"][0]["ports"][0]["connect_choices"] == [{
        "id": "interface:target",
        "owner": "node:target",
        "label": "Target / Input",
    }]


def test_topology_delta_carries_graph_replacement_without_stable_app_data():
    projection = {
        "revision": 9,
        "connections": [{"id": "relation:a"}],
        "nodes": [{
            "id": "node:a", "selected": True, "x": 10, "y": 20,
        }],
        "wires": [{
            "id": "relation:a", "segment": "relation:a:0",
            "selected": False, "context": True,
        }],
        "configuration": {
            "design_system": {"control_catalog": {"controls": [{}]}},
        },
    }
    delta = _topology_canvas_delta(projection, base_revision=7)
    assert delta["projection_mode"] == "topology-delta-v1"
    assert delta["base_revision"] == 7
    assert delta["topology_recovery"] is True
    assert delta["nodes"] == projection["nodes"]
    assert delta["wires"] == projection["wires"]
    assert delta["connection_count"] == 1
    assert "node_states" not in delta
    assert "wire_states" not in delta
    assert not ({"catalog", "catalog_sections", "composer"} & set(delta))


def test_topology_delta_sends_only_revision_bound_changed_graph_items():
    before = {
        "revision": 7,
        "connections": [{"id": "relation:a"}],
        "nodes": [
            {"id": "node:a", "selected": True, "x": 10, "y": 20},
        ],
        "wires": [
            {
                "id": "relation:a", "segment": "relation:a:0",
                "selected": False, "context": True,
            },
        ],
        "configuration": {
            "design_system": {"control_catalog": {"controls": [{}]}},
        },
    }
    after = {
        **before,
        "revision": 9,
        "nodes": [
            {"id": "node:a", "selected": False, "x": 10, "y": 20},
            {"id": "node:b", "selected": True, "x": 30, "y": 40},
        ],
        "wires": [
            *before["wires"],
            {
                "id": "relation:b", "segment": "relation:b:0",
                "selected": False, "context": False,
            },
        ],
    }

    delta = _topology_canvas_delta(
        after,
        base_revision=before["revision"],
        previous_projection=before,
    )

    patch = delta["topology_patch"]
    assert "topology_recovery" not in delta
    assert "nodes" not in delta
    assert "wires" not in delta
    assert patch["node_order"] == ["node:a", "node:b"]
    assert patch["wire_order"] == ["relation:a:relation:a:0", "relation:b:relation:b:0"]
    assert [node["id"] for node in patch["upsert_nodes"]] == ["node:a", "node:b"]
    assert [wire["id"] for wire in patch["upsert_wires"]] == ["relation:b"]
    assert patch["remove_nodes"] == []
    assert patch["remove_wires"] == []


def test_semantic_toolbar_control_rechecks_graph_binding_revision_and_shape():
    server = ApplicationServer().start()
    try:
        status, original = _json(server, "/api/universal/canvas")
        assert status == 200
        root = original["nodes"][0]["id"]
        original_node = next(node for node in original["nodes"] if node["id"] == root)
        moved_x = float(original_node["x"]) + 180.0
        moved_y = float(original_node["y"]) + 120.0
        status, _ = _json(server, "/api/universal/move", {
            "root": root,
            "x": moved_x,
            "y": moved_y,
        })
        assert status == 200
        status, moved = _json(server, "/api/universal/canvas")
        assert status == 200
        undo = next(
            control for control in moved["configuration"]["design_system"]
            ["control_catalog"]["controls"]
            if control["owner"] == "app:control:canvas:undo"
        )
        assert undo["applicable"] is True
        binding = _interaction_binding(moved, undo["owner"])
        assert binding["inputs"] == [undo["activation"]["binding"]]
        request = {
            "interaction": binding["interaction"],
            "control": binding["control"],
            "event": binding["event"],
            "revision": moved["interaction_projection"]["revision"],
            "projection_mode": "topology-delta-v1",
        }

        status, undone_delta = _json(
            server, "/api/universal/interaction", request
        )
        assert status == 200
        undone = _merge_projection_delta(moved, undone_delta)
        restored = next(node for node in undone["nodes"] if node["id"] == root)
        assert restored["x"] == original_node["x"]
        assert restored["y"] == original_node["y"]
        assert "created_root" not in undone

        status, stale = _json(server, "/api/universal/interaction", request)
        assert status == 400
        assert "revision" in stale["error"]

        forged = {
            **request,
            "revision": undone["interaction_projection"]["revision"],
            "control": "app:control:forged",
        }
        status, denied = _json(server, "/api/universal/interaction", forged)
        assert status == 400
        assert "control" in denied["error"].lower()

        broadened = {**forged, "operation": "redo"}
        status, denied = _json(server, "/api/universal/interaction", broadened)
        assert status == 400
        assert "undeclared facts" in denied["error"]

        status, retired = _json(server, "/api/universal/control", {})
        assert status == 404
        assert retired["error"] == "not found"
    finally:
        server.close()


def _toolbar_control(projection, owner):
    catalog = (
        projection["configuration"]["design_system"]["control_catalog"]
        if "configuration" in projection
        else projection["control_state"]
    )
    return next(
        control for control in catalog["controls"]
        if control["owner"] == owner
    )


def _activate_control(server, projection, owner):
    control = _toolbar_control(projection, owner)
    assert control["applicable"] is True
    binding = _interaction_binding(projection, owner)
    assert binding["inputs"] == [control["activation"]["binding"]]
    status, result = _json(server, "/api/universal/interaction", {
        "interaction": binding["interaction"],
        "control": binding["control"],
        "event": binding["event"],
        "revision": projection["interaction_projection"]["revision"],
        "projection_mode": "topology-delta-v1",
    })
    return status, (
        _merge_projection_delta(projection, result)
        if status == 200 else result
    )


def _activate_scope_interaction(server, projection, control_root):
    binding = _interaction_binding(projection, control_root)
    status, result = _json(server, "/api/universal/interaction", {
        "interaction": binding["interaction"],
        "control": binding["control"],
        "event": binding["event"],
        "revision": projection["interaction_projection"]["revision"],
        "projection_mode": "topology-delta-v1",
    })
    return status, (
        _merge_projection_delta(projection, result)
        if status == 200 else result
    )


def test_group_and_ungroup_toolbar_bindings_preserve_selected_root_identities():
    server = ApplicationServer().start()
    try:
        status, before = _json(server, "/api/universal/canvas")
        assert status == 200
        roots = [node["id"] for node in before["nodes"][:2]]
        status, selected = _json(server, "/api/universal/gesture", {
            "roots": roots,
            "focus": roots[-1],
        })
        assert status == 200

        status, grouped = _activate_control(
            server, selected, "app:control:canvas:group"
        )
        assert status == 200
        composition_root = grouped["created_root"]
        assert composition_root
        assert grouped["selected"] == composition_root
        assert composition_root in {node["id"] for node in grouped["nodes"]}

        status, ungrouped = _activate_control(
            server, grouped, "app:control:canvas:ungroup"
        )
        assert status == 200
        visible = {node["id"] for node in ungrouped["nodes"]}
        assert set(roots).issubset(visible)
        assert composition_root not in visible
        assert set(roots).issubset(server.universal_store.snapshot().cells)

        for path, body in (
            ("/api/universal/group", {"title": "retired"}),
            ("/api/universal/ungroup", {"root": composition_root}),
        ):
            status, retired = _json(server, path, body)
            assert status == 404
            assert retired["error"] == "not found"
    finally:
        server.close()


def test_scope_up_toolbar_binding_returns_to_the_exact_graph_parent():
    server = ApplicationServer().start()
    try:
        status, before = _json(server, "/api/universal/canvas")
        assert status == 200
        openable = next(node for node in before["nodes"] if node["openable"])
        status, entered = _activate_scope_interaction(
            server, before, openable["id"]
        )
        assert status == 200
        assert entered["scope"]["current"] == openable["id"]

        status, returned = _activate_scope_interaction(
            server, entered, "app:control:canvas:scope-up"
        )
        assert status == 200
        assert returned["scope"]["current"] == before["scope"]["current"]
        assert returned["scope"]["trail"] == before["scope"]["trail"]
    finally:
        server.close()
