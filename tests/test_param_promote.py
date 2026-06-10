"""Param->socket promote pins (stem-surface #4, the final gap — the Houdini
gesture: a connector-op knob toggles into a typed input socket).

Live-CDP-verified 2026-06-10 (isolated instance): dispatching the real
`lm-param-promote` event on a connector node ADDED the typed socket
(ins: in + path), and a second dispatch REMOVED it and dropped the wire
feeding it (no dangling wires). The engine needs zero change —
`_connector_run_executor` merges wired inputs by param key over config
(`params.update(inputs)`), so a wire into the named socket overrides that
param for real.
"""
from __future__ import annotations

import os

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_WEB = os.path.join(os.path.dirname(_HERE), "app", "web_ui")
_JSX = os.path.join(_WEB, "studio-lm.jsx")
_COMPILED = os.path.join(_WEB, "studio-lm.compiled.js")

_MARKERS = (
    "ParamPromoteDot",          # the per-knob toggle (connector tiles only)
    "param-promote-",           # its data-testid prefix (the live hook)
    "lm-param-promote",         # the gesture event
    "onParamPromote",           # the handler (socket add/remove + wire drop)
)


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def test_jsx_source_carries_param_promote():
    src = _read(_JSX)
    missing = [m for m in _MARKERS if m not in src]
    assert not missing, f"param promote regressed — missing from .jsx: {missing}"


def test_compiled_artifact_carries_param_promote():
    if not os.path.exists(_COMPILED):
        pytest.skip("precompiled artifact not present (built at launch)")
    out = _read(_COMPILED)
    missing = [m for m in _MARKERS if m not in out]
    assert not missing, f"compiled bundle stale — missing: {missing} (run tools/build_jsx)"


def test_dot_is_scoped_to_connector_tiles():
    """A named socket on a non-connector cell would be a DEAD plug (their
    executors don't merge inputs by param key) — the dot must bail without
    node.op_id."""
    src = _read(_JSX)
    i = src.find("const ParamPromoteDot")
    assert i != -1
    head = src[i:i + 400]
    assert "op_id" in head and "return null" in head, (
        "ParamPromoteDot lost its connector-only guard — dead plugs incoming")


def test_unpromote_drops_feeding_wires():
    """Un-promoting must remove wires targeting the socket — a wire into a
    nonexistent port would dangle forever."""
    src = _read(_JSX)
    i = src.find("const onParamPromote")
    assert i != -1
    body = src[i:i + 1200]
    assert "wires" in body and "filter" in body, (
        "onParamPromote no longer drops wires on un-promote")


def test_engine_merges_inputs_by_param_key():
    """The contract the gesture rides on: the connector executor merges wired
    inputs by key over config. If this line goes, promoted sockets become
    decorative."""
    con = _read(os.path.join(os.path.dirname(_HERE), "app", "workflows",
                             "nodes", "connector.py"))
    assert "params.update(inputs)" in con, (
        "_connector_run_executor no longer merges inputs over config — "
        "promoted sockets would be dead plugs")
