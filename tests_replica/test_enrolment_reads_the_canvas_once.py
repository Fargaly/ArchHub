"""Enrolling one Agent Session reads the canvas once, not once per session.

Every abandoned attach leaves another active session behind, and the
enrolment walked the whole canvas relation for EACH of them: the cost grew
with every failure until BABOOM could not attach at all, and the retries
made it worse (2026-09-07, py-spy on the founder's app caught the pipe
thread inside _machine_session_surface_values with the GIL).
"""
from __future__ import annotations

import types
from pathlib import Path

import pytest

from nodelang import application_server as server_module

ROOT = Path(__file__).resolve().parents[1]


class _Snapshot:
    def __init__(self, revision):
        self.revision = revision
        self.cells = {}


def _fake_server(monkeypatch, walks):
    roles = {"property": "role:property", "owner": "role:owner",
             "label": "role:label", "value": "role:value"}
    registry = types.SimpleNamespace(roles=roles, canvas_root="canvas")

    def read_relation(snapshot, root, budget=None):
        if root == "canvas":
            walks.append(root)
            return [types.SimpleNamespace(role_id=roles["property"], participant_id="p1")]
        return [
            types.SimpleNamespace(role_id=roles["owner"], participant_id="app:agent-session:runtime:a"),
            types.SimpleNamespace(role_id=roles["label"], participant_id="l"),
            types.SimpleNamespace(role_id=roles["value"], participant_id="v"),
        ]

    monkeypatch.setattr(server_module, "read_relation", read_relation)
    fake = types.SimpleNamespace(universal_registry=registry, _surface_index_cache=None)
    fake._machine_session_surface_index = types.MethodType(
        server_module.ApplicationServer._machine_session_surface_index, fake)
    fake._machine_session_surface_values = types.MethodType(
        server_module.ApplicationServer._machine_session_surface_values, fake)
    return fake


def test_many_sessions_cost_one_walk_of_the_canvas(monkeypatch):
    walks = []
    fake = _fake_server(monkeypatch, walks)
    snap = _Snapshot(7)
    snap.cells = {"l": types.SimpleNamespace(atom=b"runtime"),
                  "v": types.SimpleNamespace(atom=b"claude-code")}
    for _candidate in range(25):
        fake._machine_session_surface_values(snap, "app:agent-session:runtime:a")
    assert len(walks) == 1, "the canvas was walked %d times for one snapshot" % len(walks)


def test_a_new_revision_is_read_again(monkeypatch):
    walks = []
    fake = _fake_server(monkeypatch, walks)
    first, second = _Snapshot(7), _Snapshot(8)
    for snap in (first, first, second, second):
        snap.cells = {"l": types.SimpleNamespace(atom=b"runtime"),
                      "v": types.SimpleNamespace(atom=b"claude-code")}
        fake._machine_session_surface_values(snap, "app:agent-session:runtime:a")
    assert len(walks) == 2, walks


def test_the_values_are_still_the_two_released_properties(monkeypatch):
    walks = []
    fake = _fake_server(monkeypatch, walks)
    snap = _Snapshot(1)
    snap.cells = {"l": types.SimpleNamespace(atom=b"runtime"),
                  "v": types.SimpleNamespace(atom=b"claude-code")}
    assert fake._machine_session_surface_values(snap, "app:agent-session:runtime:a") == {"runtime": "claude-code"}
    assert fake._machine_session_surface_values(snap, "app:agent-session:runtime:other") == {}
