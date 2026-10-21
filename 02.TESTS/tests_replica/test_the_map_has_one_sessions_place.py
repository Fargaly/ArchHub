"""The cockpit map holds ONE Runtime Sessions place, not one per session.

The founder's canvas held 60 app:agent-session roots against 15 authored
domains, and every one of them became a top-level cockpit domain: his map
drew 95 domains, seventeen of them identical cards reading "baboom Agent
Ses...". He was explicit that the runtime belongs ON the map -- what must
not happen is sixty broken copies of it (2026-09-07).

So: sessions are members of one place that says what each session IS, pure
wiring is not drawn at all, and everything he authored is untouched.
"""
from __future__ import annotations

import json
import types

import pytest

from nodelang import universal_pipeline as pipeline


def _projection():
    nodes = [
        {"id": "gm:domain:ui", "label": "UI", "openable": True},
        {"id": "gm:domain:brain", "label": "Brain & Memory", "openable": True},
        {"id": "app:workshop", "label": "Workshop", "openable": True},
    ]
    for spot in range(60):
        nodes.append({
            "id": "app:agent-session:runtime:%02d" % spot,
            "label": "baboom Agent Session", "openable": True,
        })
    for spot in range(9):
        nodes.append({
            "id": "app:canvas-relation:%d" % spot,
            "label": "relation", "openable": True,
        })
        nodes.append({
            "id": "relation-candidate:%d" % spot,
            "label": "candidate", "openable": True,
        })
        nodes.append({
            "id": "app:dynamic:property:%d" % spot,
            "label": "property", "openable": True,
        })
        nodes.append({
            "id": "assembly-instance:%d" % spot,
            "label": "instance", "openable": True,
        })
    return {"nodes": nodes, "wires": ()}


@pytest.fixture
def drawn(monkeypatch):
    monkeypatch.setattr(
        pipeline, "project_universal_canvas",
        lambda store, registry, authentication_context=None: _projection(),
    )
    monkeypatch.setattr(pipeline, "_owner_properties", lambda snapshot, registry: {
        "app:agent-session:runtime:00": {
            "runtime": ("rel:a", "baboom"), "state": ("rel:b", "active"),
        },
        "app:agent-session:runtime:01": {
            "runtime": ("rel:c", "codex"), "state": ("rel:d", "closed"),
        },
    })
    from nodelang import universal_application as app_module
    monkeypatch.setattr(
        app_module, "_nested_canvas_scope",
        lambda snapshot, registry, key: ((), (), ()),
    )
    store = types.SimpleNamespace(
        snapshot=lambda: types.SimpleNamespace(revision=1, cells={})
    )
    registry = types.SimpleNamespace(
        roles={name: "role:" + name for name in (
            "wire", "source", "target", "why", "property", "owner",
            "label", "value",
        )},
    )
    script = pipeline.project_atlas_map(store, registry)
    body = script.split("window.ATLAS_MAP = ", 1)[1].rsplit("; window.ATLAS_LIVE", 1)[0]
    return json.loads(body)


def test_sixty_sessions_make_one_place(drawn):
    keys = [d["key"] for d in drawn["domains"]]
    assert keys.count(pipeline._ATLAS_SESSION_DOMAIN) == 1
    assert not any(k.startswith("app:agent-session:") for k in keys), (
        "a session must never be a place of its own: %s" % keys
    )


def test_the_sessions_place_says_what_each_session_is(drawn):
    seats = [n for n in drawn["nodes"] if n["dom"] == pipeline._ATLAS_SESSION_DOMAIN]
    assert seats, "the place must hold the sessions, not just count them"
    titles = {n["title"] for n in seats}
    assert "baboom" in titles and "codex" in titles, (
        "each session must say which runtime attached: %s" % sorted(titles)
    )
    live = {n["title"]: n["status"] for n in seats}
    assert live["baboom"] == "live" and live["codex"] != "live", (
        "a finished session must not read as live: %s" % live
    )


def test_pure_wiring_is_not_drawn_as_a_place(drawn):
    keys = [d["key"] for d in drawn["domains"]]
    for wiring in pipeline._ATLAS_WIRING_ROOTS:
        assert not any(k.startswith(wiring) for k in keys), (
            "%s is an incidence, not a place: %s" % (wiring, keys)
        )


def test_every_authored_domain_survives(drawn):
    keys = set(d["key"] for d in drawn["domains"])
    assert {"ui", "brain", "app:workshop"} <= keys, (
        "the founder's own domains must never be filtered: %s" % sorted(keys)
    )


def test_the_map_is_a_readable_size(drawn):
    assert len(drawn["domains"]) == 4, (
        "3 authored + 1 Runtime Sessions, not 95: %s"
        % [d["key"] for d in drawn["domains"]]
    )
