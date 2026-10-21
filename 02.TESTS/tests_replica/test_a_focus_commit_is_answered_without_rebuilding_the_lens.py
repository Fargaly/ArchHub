"""A select click is answered from the lens the view already holds.

Every select commits attention cells and then rebuilt the whole
projection. The lens phase alone re-read the scope level, every instance
definition, the relations and the ports -- measured 0.081-0.115 s on the
founder graph, 0.27-0.39 s per click on a five-node graph -- to change
exactly two lens fields, selected_root and selected_roots
(unified_application_lens.project_unified_scope). SPEC 11.14 owes the
founder the whole click in 0.150 s.

The rule courted here, on the clean server the desktop window uses:

* the answer to POST /api/universal/focus equals a full rebuild at the
  same revision, byte for byte -- the selection is read back from the
  focus the graph recorded, never from the request;
* the answer runs the lens phase ZERO times (bound on call count, not
  on the clock, so a slow machine cannot make it flap);
* it holds for an openable card (selection-count moves, and
  focus-is-composition when the scope shows a composition), for a wire
  (a relation root is a selection too), for two cards after a pan (the
  lens carried through the view-only commit), and for a select sent
  through the gesture route.
"""
from __future__ import annotations

import json
import uuid as _uuid

import nodelang.application_server as application_server_module
from tests_replica.test_clean_server_visual_projection import (
    _issue_clean_session,
    _json,
    _provision_clean_runtime,
    _start_clean_server,
)

# What the route adds on top of the projection it serves.
_ROUTE_ONLY = frozenset({
    "ok", "accepted_revision", "receipt", "replayed", "focus_root", "moved",
})


def _count_lens_builds(monkeypatch):
    """Every lens the owner builds, as the server module calls it."""
    calls = []
    real = application_server_module.project_unified_scope

    def counted(*args, **kwargs):
        calls.append(kwargs.get("at_revision"))
        return real(*args, **kwargs)

    monkeypatch.setattr(
        application_server_module, "project_unified_scope", counted
    )
    return calls


def _focus(server, scope, roots, primary, revision, *, token, csrf):
    return _json(
        server.url,
        "/api/universal/focus",
        {
            "expected_scope": scope,
            "scope_root": scope,
            "selected_roots": roots,
            "primary_root": primary,
            "revision": revision,
            "command_id": str(_uuid.uuid4()),
        },
        token=token,
        csrf=csrf,
    )


def _rebuilt(server, token):
    """What the owner would have built from nothing at this revision."""
    server._clean_projection_cache.clear()
    return server._canvas(server._resolve_binding(token))


def _assert_served_is_rebuilt(answer, rebuilt, what):
    served = {k: v for k, v in answer.items() if k not in _ROUTE_ONLY}
    assert served["revision"] == rebuilt["revision"]
    assert json.dumps(served, sort_keys=True) == json.dumps(
        rebuilt, sort_keys=True
    ), "%s: the served projection drifted from a full rebuild" % what


def test_a_focus_commit_is_answered_without_rebuilding_the_lens(
    tmp_path, monkeypatch
):
    built, provider = _provision_clean_runtime(tmp_path)
    server = _start_clean_server(built, provider)
    token, csrf = "focus-reuse-token", "focus-reuse-csrf"
    try:
        _issue_clean_session(built, token=token, csrf=csrf)
        status, canvas = _json(server.url, "/api/universal/canvas", token=token)
        assert status == 200 and canvas["selected"] is None
        scope = canvas["root"]
        # An openable card when the scope shows one (focus-is-composition
        # and selection-count both move), else the first card.
        composition = next(
            (node["id"] for node in canvas["nodes"] if node["openable"]),
            canvas["nodes"][0]["id"],
        )
        other = next(
            node["id"] for node in canvas["nodes"] if node["id"] != composition
        )
        assert canvas["wires"], "this court needs a wire to select"
        wire = canvas["wires"][0]["id"]
        lens_builds = _count_lens_builds(monkeypatch)

        # A composition: focus-is-composition and selection-count flip.
        status, first = _focus(
            server, scope, [composition], composition, canvas["revision"],
            token=token, csrf=csrf,
        )
        assert status == 200, first
        assert first["selected"] == composition
        assert first["selection"] == [composition]
        assert next(
            node for node in first["nodes"] if node["id"] == composition
        )["focused"] is True
        assert lens_builds == [], (
            "the focus answer rebuilt the lens %d time(s): %r"
            % (len(lens_builds), lens_builds)
        )
        _assert_served_is_rebuilt(first, _rebuilt(server, token), "composition")

        # A wire: a relation root is as selectable as a card.
        lens_builds.clear()
        status, second = _focus(
            server, scope, [wire], wire, first["accepted_revision"],
            token=token, csrf=csrf,
        )
        assert status == 200, second
        assert second["selection"] == [wire]
        assert next(
            row for row in second["wires"] if row["id"] == wire
        )["selected"] is True
        assert lens_builds == [], (
            "the wire focus rebuilt the lens %d time(s)" % len(lens_builds)
        )
        _assert_served_is_rebuilt(second, _rebuilt(server, token), "wire")

        # A pan, then two cards: the lens carried through the view-only
        # commit answers the click that follows it.
        status, panned = _json(
            server.url,
            "/api/universal/gesture",
            {"viewport": {"panX": -21.0, "panY": 5.0, "zoom": 1.3}},
            token=token,
            csrf=csrf,
        )
        assert status == 200, panned
        lens_builds.clear()
        status, third = _focus(
            server, scope, [composition, other], other, panned["revision"],
            token=token, csrf=csrf,
        )
        assert status == 200, third
        assert third["selection"] == [composition, other]
        assert third["selected"] == other
        assert third["viewport"]["zoom"] == 1.3
        assert lens_builds == [], (
            "the focus after a pan rebuilt the lens %d time(s)"
            % len(lens_builds)
        )
        _assert_served_is_rebuilt(third, _rebuilt(server, token), "after a pan")

        # The same select through the gesture route.
        lens_builds.clear()
        status, fourth = _json(
            server.url,
            "/api/universal/gesture",
            {"expected_scope": scope, "roots": [other], "focus": other},
            token=token,
            csrf=csrf,
        )
        assert status == 200, fourth
        assert fourth["selection"] == [other]
        assert lens_builds == [], (
            "the gesture select rebuilt the lens %d time(s)" % len(lens_builds)
        )
        _assert_served_is_rebuilt(fourth, _rebuilt(server, token), "gesture")
    finally:
        server.close()
        built.location.authority.store.close()
