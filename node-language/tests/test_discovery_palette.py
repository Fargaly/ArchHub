"""Discovery palette pins (stem-surface #2 — founder "mostly visual user").

Live-CDP-verified 2026-06-10 on an isolated instance: 101 library items show
typed plug rows in browse; typing "read files" produced a flat BEST MATCHES
section ranked by intent with Read File + List Files on top; the synonym net
surfaced the fs family for "folder"; clearing the query restored category
browse (USER-AGENCY: the library stays browsable).

These pins keep the discovery layer from regressing in BOTH the source .jsx
and the precompiled artifact the app actually loads.
"""
from __future__ import annotations

import os

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_WEB = os.path.join(os.path.dirname(_HERE), "app", "web_ui")
_JSX = os.path.join(_WEB, "studio-lm.jsx")
_COMPILED = os.path.join(_WEB, "studio-lm.compiled.js")

_MARKERS = (
    "LibPlugRow",                 # visible-plugs row component
    "lib-plugs",                  # its testid (the CDP/live hook)
    "_libTypeCol",                # plug dots share the canvas type colors
    "BEST MATCHES",               # the flat intent-ranked section
    "RANKED BY INTENT",           # header state when a query is active
    "_SYN",                       # the AEC synonym net
)


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def test_jsx_source_carries_discovery_layer():
    src = _read(_JSX)
    missing = [m for m in _MARKERS if m not in src]
    assert not missing, f"discovery palette regressed — missing from .jsx: {missing}"


def test_compiled_artifact_carries_discovery_layer():
    if not os.path.exists(_COMPILED):
        pytest.skip("precompiled artifact not present (built at launch)")
    out = _read(_COMPILED)
    missing = [m for m in _MARKERS if m not in out]
    assert not missing, f"compiled bundle stale — missing: {missing} (run tools/build_jsx)"


def test_browse_mode_is_preserved():
    """USER-AGENCY: ranked discovery replaces the category groups ONLY while a
    query is typed — the empty-query path must keep rendering the grouped
    browse (renderGroups falls back to `groups`)."""
    src = _read(_JSX)
    assert "renderGroups = _ranked" in src and ": groups;" in src, (
        "ranked view no longer falls back to category browse on empty query")
