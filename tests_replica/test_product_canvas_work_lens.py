"""Acceptance court: the product canvas lens draws Work only in the Workshop.

Registered Work and its <work>:data:<name> value nodes stay placed where
creation put them, because that placement is their Workshop access boundary.
The canvas lens does not draw them outside a Work home (the Governed Work
registry, the Workshop, its Workbench or a Work itself). The selection list
and count follow the lens, a selection on undrawn Work points to the Workshop,
and the Workshop still reads the Work the lens hides. Creation is unchanged;
these courts write every graph through create_universal_governed_work.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import nodelang.universal_application as application_module
from nodelang.application_server import (
    ApplicationServer,
    _interaction_canvas_delta,
    _topology_canvas_delta,
)
from nodelang.cell_protocols import read_relation
from nodelang.cell_secret_keys import MemorySigningKeyProvider
from nodelang.map_import import resolve_map_path
from nodelang.universal_application import (
    build_universal_application,
    create_universal_governed_work,
    group_universal_selection,
    instantiate_universal_definition,
    project_universal_canvas,
    project_universal_governed_work_index,
    restore_universal_application,
    set_universal_scope,
    set_universal_selection,
)
from nodelang.universal_cell import CellStore


# Titles as the founder canvas shows them, created by coding agents.
AGENT_WORK_TITLES = (
    "Claude717 landing: reviewed source patches for the design release",
    "Website lane: remove live prices, rebuild the canonical site, export "
    "and package it",
    "Startup backup: skip the doomed 2-second full copy for large graphs",
)
# A delta sends these two scalars only when they change; never the list.
LENS_DELTA_DEFAULTS = (("selection_hidden", False), ("hidden_work_count", 0))


def _provider():
    provider = MemorySigningKeyProvider(
        "archhub.local.relationship-authority", b"w" * 32
    )
    provider.add_key("archhub.local.court-attestation", b"c" * 32)
    return provider


def _members(snapshot, relation_root, role_id=None):
    return {
        member.participant_id
        for member in read_relation(snapshot, relation_root, budget=100_000)
        if role_id is None or member.role_id == role_id
    }


def _ids(projection):
    return [node["id"] for node in projection["nodes"]]


def _value_roots(work_root):
    return {"%s:data:requirements" % work_root}


def _composer_work(store, registry, title, index, **kwargs):
    """The composer and browser shape: structured, exposed and selected."""
    root, _wire, _revision = create_universal_governed_work(
        store,
        registry,
        title=title,
        description="Review the design release",
        x=600.0 + 40.0 * index,
        y=380.0 + 160.0 * index,
        structured_references={"requirements": {
            "acceptance_criteria": ["the release is reviewed"],
        }},
        **kwargs,
    )
    return root


def _agent_work(store, registry, title, **kwargs):
    """The Brain MCP shape: compact references and no selection."""
    root, _wire, _revision = create_universal_governed_work(
        store,
        registry,
        title=title,
        x=0.0,
        y=0.0,
        compact_references=True,
        select_created=False,
        **kwargs,
    )
    return root


def _scoped_ids(store, registry, trail, **kwargs):
    set_universal_scope(store, registry, registry.canvas_root, **kwargs)
    for scope_root in trail:
        set_universal_scope(store, registry, scope_root, **kwargs)
    ids = set(_ids(project_universal_canvas(store, registry, **kwargs)))
    set_universal_scope(store, registry, registry.canvas_root, **kwargs)
    return ids


def test_existing_graph_draws_work_only_in_the_workshop(tmp_path):
    path = tmp_path / "existing-founder-shape.sqlite3"
    store, registry = build_universal_application(
        resolve_map_path(), CellStore(path), key_provider=_provider()
    )
    try:
        product = _ids(project_universal_canvas(store, registry))
        user_root, _revision = instantiate_universal_definition(
            store,
            registry,
            registry.standard_library.definition_roots[0],
            x=420.0,
            y=120.0,
        )
        works = [
            _composer_work(store, registry, title, index)
            for index, title in enumerate(AGENT_WORK_TITLES[:2])
        ]
        works.append(_agent_work(store, registry, AGENT_WORK_TITLES[2]))
    finally:
        store.close()

    store, registry = restore_universal_application(
        resolve_map_path(), CellStore(path), key_provider=_provider()
    )
    try:
        view = registry.view_sessions[registry.authorization.subject_root]
        snapshot = store.snapshot()
        member_role = registry.roles["member"]
        # Creation placed every Work on the application canvas.
        assert set(works) <= _members(
            snapshot, registry.canvas_root, member_role
        )
        assert set(works) <= _members(
            snapshot, view.visibility_root, registry.roles["visible"]
        )
        first = project_universal_canvas(store, registry)
        drawn = _ids(first)
        values = set().union(*(_value_roots(root) for root in works[:2]))
        assert values <= set(snapshot.cells)
        assert not (set(works) | values) & set(drawn)
        assert set(product) | {user_root} <= set(drawn)
        assert not any(
            wire["source"] in works or wire["target"] in works
            for wire in first["wires"]
        )

        # The saved selection is the last selected Work. The canvas does not
        # draw it, so it does not count it and it points to the Workshop.
        assert first["selected"] == works[1]
        assert first["selection"] == []
        assert first["selection_hidden"] is True
        assert first["hidden_work_count"] == len(works)
        assert first["hidden_work"] == [
            {"id": root, "title": title}
            for root, title in zip(works, AGENT_WORK_TITLES)
        ]

        # The lens wrote nothing and deleted nothing.
        revision = store.revision
        assert _ids(project_universal_canvas(store, registry)) == drawn
        assert store.revision == revision
        assert set(works) <= _members(
            store.snapshot(), registry.governed_work_registry_root, member_role
        )
        assert project_universal_governed_work_index(store, registry)[
            "total"
        ] == len(works)


        # The served interaction projection agrees, and its retained scope
        # identity survives a round trip through a Work home.
        server = ApplicationServer(
            universal_store=store, universal_registry=registry
        )
        binding = server._resolve_browser_session(server.browser_session_token)
        served = server.project_interaction_canvas(binding)
        assert not set(works) & set(_ids(served))
        assert served["selection_hidden"] is True
        identity = server._browser_scope_canvas_identities[
            (binding.session_root, registry.canvas_root)
        ]
        # The retained identity keeps the hidden Work after the drawn order.
        drawn_count = len(served["nodes"])
        assert identity[0][:drawn_count] == tuple(_ids(served))
        assert set(identity[0][drawn_count:]) == set(works) | values
        entered = application_module._set_universal_scope_execution(
            store,
            registry,
            registry.governed_work_registry_root,
            expected_revision=served["revision"],
            projected_canvas=served,
            authentication_context=binding.context,
        )
        nested = application_module.project_universal_scope_transition(
            store,
            registry,
            authentication_context=binding.context,
            scope_materialization=entered.materialization,
            previous_projection=served,
            expected_base_revision=served["revision"],
        )
        assert set(works) <= set(_ids(nested))
        returned = application_module._set_universal_scope_execution(
            store,
            registry,
            registry.canvas_root,
            expected_revision=nested["revision"],
            projected_canvas=nested,
            reusable_scope_projection=served,
            reusable_scope_identity=identity,
            authentication_context=binding.context,
        )
        assert returned.materialization.visible_roots == identity[0]
        top = application_module.project_universal_scope_transition(
            store,
            registry,
            authentication_context=binding.context,
            scope_materialization=returned.materialization,
            previous_projection=nested,
            expected_base_revision=nested["revision"],
            reusable_scope_projection=served,
        )
        canonical = project_universal_canvas(
            store, registry, authentication_context=binding.context
        )
        assert _ids(top) == _ids(canonical)
        assert not set(works) & set(_ids(top))
        assert [row["id"] for row in top["hidden_work"]] == works

        # Brain is not a Work home; the registry and the Workbench are.
        brain = registry.map.domains["brain"]
        assert not set(works) & _scoped_ids(store, registry, (brain,))
        for trail in (
            (registry.governed_work_registry_root,),
            (brain, registry.workshop_workbench_root),
        ):
            assert set(works) <= _scoped_ids(store, registry, trail), trail
    finally:
        store.close()


def test_existing_folded_graph_with_agent_work_reads_back(tmp_path):
    path = tmp_path / "existing-folded-shape.sqlite3"
    store, registry = build_universal_application(
        resolve_map_path(), CellStore(path), key_provider=_provider()
    )
    try:
        top = project_universal_canvas(store, registry)
        selected = tuple(_ids(top)[:2])
        set_universal_selection(
            store, registry, selected, focus_root=selected[-1]
        )
        composition_root, _revision = group_universal_selection(
            store, registry, title="Founder group"
        )
        grouped = project_universal_canvas(store, registry)
        # An agent creates Work on the folded canvas with the unchanged path.
        work_root = _agent_work(store, registry, AGENT_WORK_TITLES[0])
    finally:
        store.close()

    store, registry = restore_universal_application(
        resolve_map_path(), CellStore(path), key_provider=_provider()
    )
    try:
        reread = project_universal_canvas(store, registry)
        assert _ids(reread) == _ids(grouped)
        assert reread["selected"] == grouped["selected"] == composition_root
        assert "selection_hidden" not in reread
        assert reread["hidden_work_count"] == 1
        assert reread["hidden_work"] == [
            {"id": work_root, "title": AGENT_WORK_TITLES[0]}
        ]
        assert set(selected) == _scoped_ids(
            store, registry, (composition_root,)
        )
        assert work_root in _scoped_ids(
            store,
            registry,
            (registry.map.domains["brain"], registry.workshop_workbench_root),
        )
    finally:
        store.close()


def _json(url, path, payload=None, *, token=None):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if token is not None:
        headers["X-ArchHub-Session"] = token
    request = Request(
        url + path, data=data, headers=headers,
        method="GET" if payload is None else "POST",
    )
    try:
        with urlopen(request, timeout=120) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        return error.code, json.loads(error.read().decode("utf-8"))


def _topology_request(projection, control_root):
    binding = next(
        item for item in projection["interaction_projection"]["bindings"]
        if item["control"] == control_root
    )
    return {
        "interaction": binding["interaction"],
        "control": binding["control"],
        "event": binding["event"],
        "revision": projection["interaction_projection"]["revision"],
        "projection_mode": "topology-delta-v1",
    }


def _assert_delta_carries_the_lens(projection):
    """The lens rides a delta as a boolean and a count, only on change."""
    unchanged = dict(projection)
    changed = {
        key: value for key, value in projection.items()
        if key not in {"selection_hidden", "hidden_work_count", "hidden_work"}
    }
    changed.update({
        "selection_hidden": not projection.get("selection_hidden", False),
        "hidden_work_count": projection.get("hidden_work_count", 0) + 1,
    })
    for build in (_interaction_canvas_delta, _topology_canvas_delta):
        for previous, sends in ((unchanged, False), (changed, True), (None, True)):
            delta = build(
                projection,
                base_revision=projection["revision"],
                previous_projection=previous,
            )
            assert "hidden_work" not in delta, build.__name__
            assert "selection_home" not in delta, build.__name__
            for field, default in LENS_DELTA_DEFAULTS:
                if sends:
                    assert delta[field] == projection.get(field, default), field
                else:
                    assert field not in delta, (build.__name__, field)


def test_client_delta_merge_holds_the_lens_scalars():
    source = (
        Path(__file__).resolve().parents[1] / "nodelang" / "ui_runtime.py"
    ).read_text(encoding="utf-8")
    listed = re.search(
        r"const interactionDeltaFields=\[(.*?)\];", source, re.S
    ).group(1)
    # The list never travels in a delta, and an absent scalar is held.
    assert "hidden_work" not in set(re.findall(r"'([a-z_]+)'", listed))
    assert (
        "['selection_hidden','hidden_work_count'].forEach(field => {\n"
        "      if (field in result) merged[field]=result[field];"
    ) in source


def test_composer_work_and_wire_at_canvas_root_points_to_the_workshop(
    tmp_path,
):
    from nodelang.agent_composer import (
        _apply_draft_actions,
        _validate_draft_references,
    )

    store, registry = build_universal_application(
        resolve_map_path(),
        CellStore(tmp_path / "composer.sqlite3"),
        key_provider=_provider(),
    )
    try:
        projection = project_universal_canvas(store, registry)
        assert projection["scope"]["current"] == registry.canvas_root
        target = _ids(projection)[0]
        actions = [
                {
                    "op": "work", "ref": "review",
                    "title": AGENT_WORK_TITLES[0],
                    "description": "Review the design release",
                    "criteria": [{
                        "criterion": "the release is reviewed",
                        "verification": "read the review",
                    }],
                    "x": 600, "y": 300,
                },
                {"op": "wire", "source": {"ref": "review"}, "target": target},
        ]
        _validate_draft_references(actions, projection)
        result = _apply_draft_actions(
            store, registry, projection, {"answer": ""}, actions,
            authentication_context=None,
        )
        work, wire = result["applied"]
        assert work["ok"] is True
        assert wire == {
            "op": "wire", "ok": False,
            "why": "Work is not on this canvas: open the Workshop to connect it",
        }
        assert result["draft_complete"] is False
        assert "open the Workshop" in result["answer"]
        # Creation is unchanged: the Work exists and is registered.
        assert work["root"] in _members(
            store.snapshot(),
            registry.governed_work_registry_root,
            registry.roles["member"],
        )
    finally:
        store.close()


def test_work_on_a_folded_canvas_reads_back_over_http():
    server = ApplicationServer().start()
    try:
        store, registry = server.universal_store, server.universal_registry
        token = server.browser_session_token
        binding = server._resolve_browser_session(token)
        status, before = _json(server.url, "/api/universal/canvas", token=token)
        assert status == 200
        product = _ids(before)

        # The browser Work route, unchanged: structured and selected.
        status, created = _json(server.url, "/api/universal/work", {
            "title": AGENT_WORK_TITLES[0],
            "description": "Review the design release",
            "structured_references": {"requirements": {
                "acceptance_criteria": ["the release is reviewed"],
            }},
            "x": 640.0,
            "y": 360.0,
            "projection": False,
        }, token=token)
        assert status == 200, created
        browser_work = created["created_root"]
        status, lensed = _json(server.url, "/api/universal/canvas", token=token)
        assert status == 200
        assert _ids(lensed) == product
        assert lensed["selected"] == browser_work
        assert lensed["selection"] == []
        assert lensed["selection_hidden"] is True
        assert lensed["hidden_work"] == [
            {"id": browser_work, "title": AGENT_WORK_TITLES[0]}
        ]
        with server.mutation_lock:
            _assert_delta_carries_the_lens(
                server.project_interaction_canvas(binding)
            )

        # Grouping on a canvas that holds hidden Work keeps the exposure a
        # lossless partition.
        status, selected = _json(
            server.url, "/api/universal/gesture",
            {"roots": product[:2], "focus": product[1]}, token=token,
        )
        assert status == 200
        assert "selection_hidden" not in selected
        with server.mutation_lock:
            _assert_delta_carries_the_lens(
                server.project_interaction_canvas(binding)
            )
        status, grouped = _json(
            server.url, "/api/universal/interaction",
            _topology_request(selected, "app:control:canvas:group"),
            token=token,
        )
        assert status == 200, grouped
        composition_root = grouped["created_root"]
        status, grouped = _json(server.url, "/api/universal/canvas", token=token)
        assert status == 200
        grouped_ids = _ids(grouped)
        assert composition_root in grouped_ids
        assert browser_work not in grouped_ids

        # An agent creates Work on the folded canvas with the unchanged path.
        with server.mutation_lock:
            top_work = _agent_work(
                store, registry, AGENT_WORK_TITLES[1],
                authentication_context=binding.context,
            )
        status, folded = _json(server.url, "/api/universal/canvas", token=token)
        assert status == 200, folded
        assert _ids(folded) == grouped_ids
        assert folded["selected"] == grouped["selected"]
        assert "selection_hidden" not in folded
        assert [row["id"] for row in folded["hidden_work"]] == [
            browser_work, top_work,
        ]

        # And from inside the composition, while the founder is there.
        status, entered = _json(
            server.url, "/api/universal/interaction",
            _topology_request(folded, composition_root), token=token,
        )
        assert status == 200, entered
        members_before = _members(store.snapshot(), composition_root)
        with server.mutation_lock:
            nested_work = _agent_work(
                store, registry, AGENT_WORK_TITLES[2],
                authentication_context=binding.context,
            )
        assert _members(store.snapshot(), composition_root) == members_before
        status, nested = _json(server.url, "/api/universal/canvas", token=token)
        assert status == 200, nested
        assert nested["scope"]["current"] == composition_root
        assert _ids(nested) == product[:2]

        works = {browser_work, top_work, nested_work}
        assert works <= _members(
            store.snapshot(),
            registry.governed_work_registry_root,
            registry.roles["member"],
        )
        with server.mutation_lock:
            for scope_root in (
                registry.canvas_root,
                registry.map.domains["brain"],
                registry.workshop_workbench_root,
            ):
                set_universal_scope(
                    store, registry, scope_root,
                    authentication_context=binding.context,
                )
        status, bench = _json(server.url, "/api/universal/canvas", token=token)
        assert status == 200, bench
        assert works <= set(_ids(bench))
    finally:
        server.close()