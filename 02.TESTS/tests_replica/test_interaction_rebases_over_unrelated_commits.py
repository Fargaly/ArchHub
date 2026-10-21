"""A click is refused for a conflict, not for the graph having moved.

Measured on the live owner 2026-08-19: double-clicking a domain returned
``400 expected revision 909, current revision is 914``. The five revisions
between were the viewport auto-commit -- a pan. Nothing the click read had
changed, yet the click died. That is a global lock wearing a conflict
detector's name (SPEC 8: conflicts are about WHAT changed; Layer 42: read
set, write set, conflict surface).

The rule courted here, on the clean server that the desktop window uses:

* a scope-open interaction whose revision is behind the head is ACCEPTED
  when nothing in its read set (scope tree, catalogue) moved -- a viewport
  commit in between must not refuse it;
* the same interaction is REFUSED with the client's existing retry code
  when what it read (here: the published catalogue) did move.
"""
from __future__ import annotations

import json
import os
import uuid as _uuid
from pathlib import Path

from tests_replica.test_clean_server_visual_projection import (
    _issue_clean_session,
    _json,
    _provision_clean_runtime,
    _start_clean_server,
)


def _publish_definition(built, name):
    """Grow the published catalogue by one card -- part of every click's read set."""
    from nodelang.unified_authority import declare_definition, promote_definition

    authority, caller = built.location.authority, built.caller
    declared = declare_definition(
        authority, name, {}, caller=caller,
        command_id=str(_uuid.uuid4()), version="1",
        presentation={"label": name, "icon": "play"},
    )
    shared = promote_definition(
        authority, declared.root_id, target_lifecycle="shared",
        version="1-shared", evidence_roots=(declared.receipt_root,),
        caller=caller, command_id=str(_uuid.uuid4()),
    )
    promote_definition(
        authority, declared.root_id, target_lifecycle="published",
        version="1-published", evidence_roots=(shared.receipt_root,),
        caller=caller, command_id=str(_uuid.uuid4()),
    )
    return declared.root_id


def _open_binding(canvas):
    target = next(node for node in canvas["nodes"] if node["openable"])
    binding = next(
        item
        for item in canvas["interaction_projection"]["bindings"]
        if item["control"] == target["id"]
    )
    return target, binding


def _enter(server, binding, revision, *, token, csrf):
    return _json(
        server.url,
        "/api/universal/interaction",
        {
            "interaction": binding["interaction"],
            "control": binding["control"],
            "event": binding["event"],
            "revision": revision,
            "projection_mode": "topology-delta-v1",
        },
        token=token,
        csrf=csrf,
    )


def test_a_viewport_commit_between_projection_and_click_does_not_refuse_the_click(
    tmp_path,
):
    built, provider = _provision_clean_runtime(tmp_path)
    server = _start_clean_server(built, provider)
    token, csrf = "rebase-token", "rebase-csrf"
    try:
        _issue_clean_session(built, token=token, csrf=csrf)
        status, canvas = _json(server.url, "/api/universal/canvas", token=token)
        assert status == 200
        seen = canvas["interaction_projection"]["revision"]
        target, binding = _open_binding(canvas)

        # The pan the client auto-commits after opening: moves the head.
        status, panned = _json(
            server.url,
            "/api/universal/gesture",
            {
                "viewport": {"panX": -40.0, "panY": 12.5, "zoom": 1.1},
                "projection_revision": seen,
            },
            token=token,
            csrf=csrf,
        )
        assert status == 200, panned
        assert panned["revision"] > seen, "the pan must actually move the head"

        # The click still carries the revision it SAW.
        status, entered = _enter(server, binding, seen, token=token, csrf=csrf)
        assert status == 200, entered
        assert entered["scope"]["current"] == target["id"], (
            "a click whose read set did not change enters the scope"
        )
    finally:
        server.close()
        built.location.authority.store.close()


def test_a_read_set_change_between_projection_and_click_still_refuses_with_the_retry_code(
    tmp_path,
):
    built, provider = _provision_clean_runtime(tmp_path)
    server = _start_clean_server(built, provider)
    token, csrf = "conflict-token", "conflict-csrf"
    try:
        _issue_clean_session(built, token=token, csrf=csrf)
        status, canvas = _json(server.url, "/api/universal/canvas", token=token)
        assert status == 200
        seen = canvas["interaction_projection"]["revision"]
        target, binding = _open_binding(canvas)

        # Something the click READS moves: the published catalogue grows,
        # so the interaction set the click was projected from is stale.
        _publish_definition(built, "Published under the click")
        assert built.location.authority.store.revision > seen

        status, refused = _enter(server, binding, seen, token=token, csrf=csrf)
        assert status == 409, refused
        assert refused["ok"] is False
        assert "revision" in refused["error"]
        assert refused["code"] == "projection_lease_expired", (
            "the refusal must ride the client's existing refresh-and-retry code"
        )
        # The graph did not take the click.
        status, after = _json(server.url, "/api/universal/canvas", token=token)
        assert status == 200
        assert after["scope"]["current"] != target["id"]
    finally:
        server.close()
        built.location.authority.store.close()


def test_a_scope_click_enters_when_the_interaction_table_is_retired(tmp_path):
    """The live graph serves interactions from the derivation, not a table.

    Fresh fixtures install the table and never take the derived path, so
    every scope-entry court was green while no domain on the live graph
    would open: the read overlay stamped a CANDIDATE revision (base + 1)
    and the lease check refused every click with "expected 919, projected
    920". This court walks the live path -- table unreachable, derived
    cells overlaid for reads -- and clicks.
    """
    from nodelang import application_server as module

    built, provider = _provision_clean_runtime(tmp_path)
    real_open = module.open_clean_scope_interactions

    def table_is_retired(*args, **kwargs):
        raise RuntimeError("the interaction table was retired")

    module.open_clean_scope_interactions = table_is_retired
    try:
        server = _start_clean_server(built, provider)
    finally:
        module.open_clean_scope_interactions = real_open
    token, csrf = "retired-table-token", "retired-table-csrf"
    try:
        assert server._derived_interaction_cells, (
            "the court must run on the derived path the live graph uses"
        )
        _issue_clean_session(built, token=token, csrf=csrf)
        status, canvas = _json(server.url, "/api/universal/canvas", token=token)
        assert status == 200
        seen = canvas["interaction_projection"]["revision"]
        target, binding = _open_binding(canvas)
        status, entered = _enter(server, binding, seen, token=token, csrf=csrf)
        assert status == 200, entered
        assert entered["scope"]["current"] == target["id"]
    finally:
        server.close()
        built.location.authority.store.close()


def test_an_entered_scope_shows_the_door_in_its_trail_and_can_go_back(tmp_path):
    """Entering a domain must not be a one-way door.

    THE court measured it on the live graph: the trail held only the scope
    the founder stood in, and no interaction opened the map again. The
    projection of a scope below the door now carries the door as a
    non-current trail entry, and the graph declares the interaction from
    that scope back to the door; pressing it projects the map.
    """
    built, provider = _provision_clean_runtime(tmp_path)
    server = _start_clean_server(built, provider)
    token, csrf = "way-back-token", "way-back-csrf"
    try:
        _issue_clean_session(built, token=token, csrf=csrf)
        status, canvas = _json(server.url, "/api/universal/canvas", token=token)
        assert status == 200
        door = canvas["scope"]["current"]
        assert [entry["root"] for entry in canvas["scope"]["trail"]] == [door]
        target, binding = _open_binding(canvas)
        status, entered = _enter(
            server, binding, canvas["interaction_projection"]["revision"],
            token=token, csrf=csrf,
        )
        assert status == 200, entered
        assert entered["scope"]["current"] == target["id"]
        trail = entered["scope"]["trail"]
        assert [entry["root"] for entry in trail] == [door, target["id"]]
        assert trail[0]["current"] is False and trail[1]["current"] is True
        assert trail[0]["label"], "the door entry must be named"
        toolbar_trail = entered["toolbar_descriptor"]
        assert door in json.dumps(toolbar_trail), (
            "the toolbar descriptor must draw the door as a crumb"
        )
        # The graph declares the way back: an interaction bound to the door
        # from inside the entered scope.
        back = next(
            item
            for item in entered["interaction_projection"]["bindings"]
            if item["control"] == door
        )
        status, returned = _json(
            server.url,
            "/api/universal/interaction",
            {
                "interaction": back["interaction"],
                "control": back["control"],
                "event": back["event"],
                "revision": entered["interaction_projection"]["revision"],
                "projection_mode": "topology-delta-v1",
            },
            token=token,
            csrf=csrf,
        )
        assert status == 200, returned
        assert returned["scope"]["current"] == door
        assert [entry["root"] for entry in returned["scope"]["trail"]] == [door]
    finally:
        server.close()
        built.location.authority.store.close()


def test_a_pan_is_answered_as_a_delta_against_what_the_view_holds(tmp_path):
    """Every pan answered with the whole canvas -- 841 KB on the live graph,
    re-rendered per wheel notch. When the client names the revision it
    holds and asks for a delta, the answer is the delta; merged onto what
    it holds it equals the full projection the server would have sent."""
    from tests_replica.test_universal_interaction_server import (
        _merge_projection_delta,
    )

    built, provider = _provision_clean_runtime(tmp_path)
    server = _start_clean_server(built, provider)
    token, csrf = "delta-token", "delta-csrf"
    try:
        _issue_clean_session(built, token=token, csrf=csrf)
        status, canvas = _json(server.url, "/api/universal/canvas", token=token)
        assert status == 200
        full_bytes = len(json.dumps(canvas))
        status, answer = _json(
            server.url,
            "/api/universal/gesture",
            {
                "viewport": {"panX": -12.0, "panY": 7.0, "zoom": 1.2},
                "projection_revision": canvas["revision"],
                "projection_mode": "interaction-delta-v1",
            },
            token=token,
            csrf=csrf,
        )
        assert status == 200, answer
        assert answer["projection_mode"] == "interaction-delta-v1", (
            "a pan that names its base must be answered as a delta"
        )
        assert answer["base_revision"] == canvas["revision"]
        assert len(json.dumps(answer)) < full_bytes // 2
        merged = _merge_projection_delta(canvas, answer)
        status, truth = _json(server.url, "/api/universal/canvas", token=token)
        assert status == 200
        assert merged["revision"] == truth["revision"]
        assert merged["viewport"] == truth["viewport"]
        assert [n["id"] for n in merged["nodes"]] == [n["id"] for n in truth["nodes"]]
        assert merged["interaction_projection"] == truth["interaction_projection"]
        # Without a base in hand the answer is the full projection.
        status, whole = _json(
            server.url,
            "/api/universal/gesture",
            {"viewport": {"panX": -13.0, "panY": 7.0, "zoom": 1.2}},
            token=token,
            csrf=csrf,
        )
        assert status == 200 and whole.get("projection_mode") is None
        assert "nodes" in whole
    finally:
        server.close()
        built.location.authority.store.close()


def test_a_view_only_commit_reuses_the_held_projection_exactly(tmp_path):
    """After a viewport commit the projection the view gets back must equal
    a full rebuild -- the reuse patches four facts from the graph and must
    never drift from what the projector would have built."""
    built, provider = _provision_clean_runtime(tmp_path)
    server = _start_clean_server(built, provider)
    token, csrf = "reuse-token", "reuse-csrf"
    try:
        _issue_clean_session(built, token=token, csrf=csrf)
        status, canvas = _json(server.url, "/api/universal/canvas", token=token)
        assert status == 200
        status, answer = _json(
            server.url,
            "/api/universal/gesture",
            {"viewport": {"panX": -21.0, "panY": 5.0, "zoom": 1.3}},
            token=token,
            csrf=csrf,
        )
        assert status == 200 and answer.get("projection_mode") is None
        assert answer["viewport"]["zoom"] == 1.3
        # What the server served is what it would have built.
        served = {k: v for k, v in answer.items() if k not in ("ok", "moved")}
        log = (server._clean_projection_cache.clear(), None)
        binding = server._resolve_binding(token)
        rebuilt = server._canvas(binding)
        assert json.dumps(served, sort_keys=True) == json.dumps(rebuilt, sort_keys=True), (
            "the reused projection drifted from a full rebuild"
        )
        # And it was a reuse, not a rebuild (the owner logs it as such).
        timing = (Path(os.environ.get("LOCALAPPDATA", "")) / "ArchHub"
                  / "unified-authority" / "gesture-timing.log")
        if timing.exists():
            tail = timing.read_text(encoding="utf-8", errors="ignore")[-4000:]
            assert "view-only reuse rev=%s" % answer["revision"] in tail
    finally:
        server.close()
        built.location.authority.store.close()


def test_group_then_ungroup_round_trips_the_selection(tmp_path):
    """Group folds the graph-held selection into one openable composition;
    ungroup dissolves it back. Both are signed commands acting on the
    focus the founder sees -- never a list the client invents."""
    from nodelang.base_universal_catalogue import install_base_universal_catalogue
    from nodelang.clean_browser_authority import revise_clean_browser_focus
    from nodelang.unified_authority import published_definition_named, instantiate_definition

    built, provider = _provision_clean_runtime(tmp_path)
    install_base_universal_catalogue(built.location.authority, caller=built.caller)
    server = _start_clean_server(built, provider)
    token, csrf = "group-token", "group-csrf"
    try:
        _issue_clean_session(built, token=token, csrf=csrf)
        auth, caller = built.location.authority, built.caller
        door = built.grand_map.root_id
        number = published_definition_named(auth, "Number", caller=caller)
        a = instantiate_definition(auth, number, {}, scope_root=door, caller=caller, command_id=str(_uuid.uuid4())).root_id
        b = instantiate_definition(auth, number, {}, scope_root=door, caller=caller, command_id=str(_uuid.uuid4())).root_id
        st, canvas = _json(server.url, "/api/universal/canvas", token=token)
        assert st == 200
        binding = server._resolve_binding(token)
        revise_clean_browser_focus(
            auth, server.clean_browser_authority, binding.session_root,
            scope_root=door, selected_roots=[a, b], primary_root=b,
            caller=caller, command_id=str(_uuid.uuid4()),
        )
        st, canvas = _json(server.url, "/api/universal/canvas", token=token)
        group_binding = next(
            item for item in canvas["interaction_projection"]["bindings"]
            if item["control"] == "app:control:canvas:group"
        )
        st, grouped = _json(
            server.url, "/api/universal/interaction",
            {"interaction": group_binding["interaction"],
             "control": group_binding["control"],
             "event": group_binding["event"],
             "revision": canvas["interaction_projection"]["revision"],
             "projection_mode": "topology-delta-v1"},
            token=token, csrf=csrf,
        )
        assert st == 200, grouped
        st, after = _json(server.url, "/api/universal/canvas", token=token)
        ids = {n["id"] for n in after["nodes"]}
        assert a not in ids and b not in ids, "grouped members left the scope"
        group_node = next(
            n for n in after["nodes"]
            if n["label"].startswith("Group of") and n["openable"]
        )
        # Entering the group shows both members.
        enter = next(
            item for item in after["interaction_projection"]["bindings"]
            if item["control"] == group_node["id"]
        )
        st, inside = _json(
            server.url, "/api/universal/interaction",
            {"interaction": enter["interaction"], "control": enter["control"],
             "event": enter["event"],
             "revision": after["interaction_projection"]["revision"],
             "projection_mode": "topology-delta-v1"},
            token=token, csrf=csrf,
        )
        assert st == 200, inside
        inside_ids = {n["id"] for n in (inside.get("nodes") or (inside.get("topology_patch") or {}).get("upsert_nodes", []))}
        assert {a, b} <= inside_ids, "the group must hold its members"
        # Ungroup from the door: select the group, press ungroup.
        revise_clean_browser_focus(
            auth, server.clean_browser_authority, binding.session_root,
            scope_root=door, selected_roots=[group_node["id"]],
            primary_root=group_node["id"],
            caller=caller, command_id=str(_uuid.uuid4()),
        )
        st, canvas3 = _json(server.url, "/api/universal/canvas", token=token)
        ungroup_binding = next(
            item for item in canvas3["interaction_projection"]["bindings"]
            if item["control"] == "app:control:canvas:ungroup"
        )
        st, ungrouped = _json(
            server.url, "/api/universal/interaction",
            {"interaction": ungroup_binding["interaction"],
             "control": ungroup_binding["control"],
             "event": ungroup_binding["event"],
             "revision": canvas3["interaction_projection"]["revision"],
             "projection_mode": "topology-delta-v1"},
            token=token, csrf=csrf,
        )
        assert st == 200, ungrouped
        st, final = _json(server.url, "/api/universal/canvas", token=token)
        final_ids = {n["id"] for n in final["nodes"]}
        assert {a, b} <= final_ids, "ungrouped members must return to the scope"
        assert group_node["id"] not in final_ids
    finally:
        server.close()
        built.location.authority.store.close()
def test_run_flows_a_number_through_the_wire_into_the_result(tmp_path):
    """Run on a stem graph evaluates it: the Number's value crosses the
    wire and lands on the Result card as its status -- a signed write,
    visible without opening anything."""
    from nodelang.base_universal_catalogue import install_base_universal_catalogue
    from nodelang.clean_browser_authority import revise_clean_browser_focus
    from nodelang.unified_authority import (
        instantiate_definition,
        published_definition_named,
    )

    built, provider = _provision_clean_runtime(tmp_path)
    install_base_universal_catalogue(built.location.authority, caller=built.caller)
    server = _start_clean_server(built, provider)
    token, csrf = "run-token", "run-csrf"
    try:
        _issue_clean_session(built, token=token, csrf=csrf)
        auth, caller = built.location.authority, built.caller
        door = built.grand_map.root_id
        number = published_definition_named(auth, "Number", caller=caller)
        result = published_definition_named(auth, "Result", caller=caller)
        num = instantiate_definition(
            auth, number, {"value": "42"}, scope_root=door,
            caller=caller, command_id=str(_uuid.uuid4()),
        ).root_id
        res = instantiate_definition(
            auth, result, {}, scope_root=door,
            caller=caller, command_id=str(_uuid.uuid4()),
        ).root_id
        st, wired = _json(
            server.url, "/api/universal/connect",
            {"source": num, "source_interface": "value",
             "target": res, "target_interface": "value"},
            token=token, csrf=csrf,
        )
        assert st == 200, wired
        binding = server._resolve_binding(token)
        revise_clean_browser_focus(
            auth, server.clean_browser_authority, binding.session_root,
            scope_root=door, selected_roots=[num], primary_root=num,
            caller=caller, command_id=str(_uuid.uuid4()),
        )
        st, canvas = _json(server.url, "/api/universal/canvas", token=token)
        assert st == 200
        run_binding = next(
            item for item in canvas["interaction_projection"]["bindings"]
            if item["control"] == "app:control:canvas:run"
        )
        st, ran = _json(
            server.url, "/api/universal/interaction",
            {"interaction": run_binding["interaction"],
             "control": run_binding["control"],
             "event": run_binding["event"],
             "revision": canvas["interaction_projection"]["revision"]},
            token=token, csrf=csrf,
        )
        assert st == 200, ran
        assert ran["ran"] == "stem-graph"
        assert ran["results"] == {"result": 42}
        assert ran["pending"] == {}
        st, after = _json(server.url, "/api/universal/canvas", token=token)
        by_id = {n["id"]: n for n in after["nodes"]}
        res_rows = {
            row["label"]: row["value"]
            for row in by_id[res]["properties"]
        }
        assert res_rows.get("status") == "42", res_rows
        assert by_id[res]["status"] == "42"
        # Running again writes nothing new: same values, same statuses.
        st, again = _json(
            server.url, "/api/universal/interaction",
            {"interaction": run_binding["interaction"],
             "control": run_binding["control"],
             "event": run_binding["event"],
             "revision": after["interaction_projection"]["revision"]},
            token=token, csrf=csrf,
        )
        assert st == 200, again
        assert again["written"] == 0, again["written"]
    finally:
        server.close()
        built.location.authority.store.close()
def test_a_rail_edit_reaches_the_graph_and_the_next_run_uses_it(tmp_path):
    """Typing a value in the rail is a signed sparse override: the gesture
    names the held node and its declared parameter, the graph records it,
    and the next Run flows the typed value -- no offline step anywhere."""
    from nodelang.base_universal_catalogue import install_base_universal_catalogue
    from nodelang.clean_browser_authority import revise_clean_browser_focus
    from nodelang.unified_authority import (
        instantiate_definition,
        published_definition_named,
    )

    built, provider = _provision_clean_runtime(tmp_path)
    install_base_universal_catalogue(built.location.authority, caller=built.caller)
    server = _start_clean_server(built, provider)
    token, csrf = "edit-token", "edit-csrf"
    try:
        _issue_clean_session(built, token=token, csrf=csrf)
        auth, caller = built.location.authority, built.caller
        door = built.grand_map.root_id
        number = published_definition_named(auth, "Number", caller=caller)
        result = published_definition_named(auth, "Result", caller=caller)
        num = instantiate_definition(
            auth, number, {}, scope_root=door,
            caller=caller, command_id=str(_uuid.uuid4()),
        ).root_id
        res = instantiate_definition(
            auth, result, {}, scope_root=door,
            caller=caller, command_id=str(_uuid.uuid4()),
        ).root_id
        st, wired = _json(
            server.url, "/api/universal/connect",
            {"source": num, "source_interface": "value",
             "target": res, "target_interface": "value"},
            token=token, csrf=csrf,
        )
        assert st == 200, wired
        st, edited = _json(
            server.url, "/api/universal/gesture",
            {"property": {"owner": num, "label": "value", "value": "42"}},
            token=token, csrf=csrf,
        )
        assert st == 200, edited
        by_id = {n["id"]: n for n in edited["nodes"]}
        num_rows = {
            row["label"]: row["value"] for row in by_id[num]["properties"]
        }
        assert num_rows.get("value") == "42", num_rows
        # An edit outside the scope's held nodes is refused, not applied.
        st, refused = _json(
            server.url, "/api/universal/gesture",
            {"property": {"owner": str(_uuid.uuid4()), "label": "value",
                          "value": "1"}},
            token=token, csrf=csrf,
        )
        assert st in (400, 403), refused
        # The next Run flows the typed value.
        binding = server._resolve_binding(token)
        revise_clean_browser_focus(
            auth, server.clean_browser_authority, binding.session_root,
            scope_root=door, selected_roots=[num], primary_root=num,
            caller=caller, command_id=str(_uuid.uuid4()),
        )
        st, canvas = _json(server.url, "/api/universal/canvas", token=token)
        run_binding = next(
            item for item in canvas["interaction_projection"]["bindings"]
            if item["control"] == "app:control:canvas:run"
        )
        st, ran = _json(
            server.url, "/api/universal/interaction",
            {"interaction": run_binding["interaction"],
             "control": run_binding["control"],
             "event": run_binding["event"],
             "revision": canvas["interaction_projection"]["revision"]},
            token=token, csrf=csrf,
        )
        assert st == 200, ran
        assert ran["results"] == {"result": 42}
    finally:
        server.close()
        built.location.authority.store.close()
