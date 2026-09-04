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
    "connector.param.promote",      # node-surface action from connector params
    "lm-param-promote",             # the gesture event
    "onParamPromote",               # the handler (socket add/remove + wire drop)
    "ConnectorParamsSurface",       # production right-rail surface
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
    assert not missing, (
        f"compiled bundle stale — missing: {missing} "
        f"(run `python tools/build_jsx.py`)")


def test_no_legacy_param_promote_widget_left():
    """The connector rail now promotes params through graph-authored surface
    actions. The old React-only dot must not remain as a parallel authority."""
    src = _read(_JSX)
    assert "const ParamPromoteDot" not in src
    assert "data-testid={'param-promote-'" not in src
    assert "const FullParam" not in src
    assert "const ParamField" not in src


def test_connector_param_surface_dispatches_promote_event():
    """A named socket on a non-connector cell would be a DEAD plug. The
    connector promote affordance now lives only inside ConnectorParamsSurface
    and dispatches the existing socket toggle event for the selected connector."""
    src = _read(_JSX)
    i = src.find("const ConnectorParamsSurface")
    assert i != -1
    body = src[i:src.find("const ConnectorDescriptionSurface", i)]
    assert "connector.param.promote" in body
    assert "lm-param-promote" in body
    assert "detail: {" in body
    assert "node_id: node.id" in body
    assert "key: d.args.key" in body


def test_unpromote_drops_feeding_wires():
    """Un-promoting must remove wires targeting the socket — a wire into a
    nonexistent port would dangle forever."""
    src = _read(_JSX)
    i = src.find("const onParamPromote")
    assert i != -1
    body = src[i:i + 1200]
    assert "wires" in body and "filter" in body, (
        "onParamPromote no longer drops wires on un-promote")


def test_promote_type_map_keeps_color_socket_string_typed():
    """A color value is a hex string. Promoting it should create a string
    socket, not a vague any socket or a dead color-only wire type."""
    src = _read(_JSX)
    i = src.find("const onParamPromote")
    assert i != -1
    body = src[i:i + 1800]
    assert "pt === 'color'" in body
    assert "? 'string'" in body


def test_engine_merges_inputs_by_param_key():
    """The contract the gesture rides on: the connector executor merges wired
    inputs by key over config. If this line goes, promoted sockets become
    decorative."""
    con = _read(os.path.join(os.path.dirname(_HERE), "app", "workflows",
                             "nodes", "connector.py"))
    assert "params.update(inputs)" in con, (
        "_connector_run_executor no longer merges inputs over config — "
        "promoted sockets would be dead plugs")
