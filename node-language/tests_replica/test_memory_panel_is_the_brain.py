"""Settings > Memory shows the brain, forget/edit reach it, the library creates real nodes."""
from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
Q = chr(39)


def test_memory_panel_no_longer_renders_a_fixture():
    jsx = (ROOT / "nodelang" / "studio" / "studio-lm.jsx").read_text(encoding="utf-8")
    assert "Habib Studio" not in jsx
    assert "window.ARCHHUB_LIVE.memory" in jsx
    assert "ARCHHUB_BRAIN_FORGET(m.id)" in jsx
    assert "ARCHHUB_BRAIN_EDIT(m.id" in jsx
    assert "ARCHHUB_REMEMBER(remember[1]" in jsx


def test_forget_edit_and_node_create_are_registered_and_wired():
    table = (ROOT / "nodelang" / "universal_application.py").read_text(encoding="utf-8")
    for route in ("brain-forget", "brain-edit", "node-create"):
        assert ("/api/universal/%s" % route) in table, route
    server = (ROOT / "nodelang" / "application_server.py").read_text(encoding="utf-8")
    assert "brain.delete_fact" in server and "fragment_id" in server
    assert "brain.edit_fact" in server
    assert "create_engine_node(" in server
    html = (ROOT / "nodelang" / "studio" / "studio.html").read_text(encoding="utf-8")
    assert "memory:(await" in html
    for bridge in ("ARCHHUB_BRAIN_FORGET", "ARCHHUB_BRAIN_EDIT", "ARCHHUB_NODE_CREATE"):
        assert bridge in html, bridge


def test_library_offers_only_hosts_an_engine_can_drive():
    jsx = (ROOT / "nodelang" / "studio" / "studio-lm.jsx").read_text(encoding="utf-8")
    for gone in ("h_rhino", "h_blender", "h_speckle", "h_dropbox", "h_outlook"):
        assert ("id:" + Q + gone) not in jsx, gone
    assert ("engine:" + Q + "revit.sessions") in jsx
    assert ("engine:" + Q + "cad.host_lines") in jsx
    assert jsx.count("engine:" + Q + "revit.read") == 8
    assert "window.ARCHHUB_NODE_CREATE({ title: libItem.title" in jsx


def test_create_engine_node_refuses_an_unknown_engine():
    from nodelang.universal_pipeline import create_engine_node
    with pytest.raises(ValueError):
        create_engine_node(None, None, title="x", engine="does.not.exist")
