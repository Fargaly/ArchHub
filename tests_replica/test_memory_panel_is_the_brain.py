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
    # 326b657: the Memory tab reads the brain when it opens, not at page load.
    load = html[html.index("window.ARCHHUB_LOAD_MEMORY = async"):html.index("window.ARCHHUB_LOAD_SKILLS")]
    assert "jpost('/api/universal/brain-export'" in load
    assert "if (fact.archived) continue;" in load, "forgotten facts never come back"
    for bridge in ("ARCHHUB_BRAIN_FORGET", "ARCHHUB_BRAIN_EDIT", "ARCHHUB_NODE_CREATE"):
        assert bridge in html, bridge


def test_library_offers_only_hosts_an_engine_can_drive():
    """Since 0705c9d the graph serves the one node library (library_engines) and
    Studio keeps no copy. Every card it offers is placed with an engine the
    catalogue runs, and Studio refuses to place a card that has none."""
    from nodelang.connector_operation_evidence import EVIDENCE
    from nodelang.library_engines import LIBRARY_ITEM_ENGINES
    from nodelang.pipeline_engines import PIPELINE_ENGINES

    for item, row in LIBRARY_ITEM_ENGINES.items():
        assert row["engine"] in PIPELINE_ENGINES, (item, row["engine"])
        assert row["engine"] in EVIDENCE, (item, row["engine"])
    engines = {row["engine"] for row in LIBRARY_ITEM_ENGINES.values()}
    assert {"revit.sessions", "cad.host_lines", "revit.read"} <= engines
    jsx = (ROOT / "nodelang" / "studio" / "studio-lm.jsx").read_text(encoding="utf-8")
    for gone in ("h_rhino", "h_blender", "h_speckle", "h_dropbox", "h_outlook"):
        assert ("id:" + Q + gone) not in jsx, "Studio must not type its own library card: " + gone
    place = jsx[jsx.index("const addNodeFromLibrary"):]
    place = place[:place.index("window.ARCHHUB_NODE_CREATE({ item: libItem.id")]
    assert "if (libItem.noEngine || !libItem.engine || !window.ARCHHUB_NODE_CREATE)" in place
    assert "has no engine in this build, so it cannot run yet" in place
    assert "window.ARCHHUB_NODE_CREATE({ item: libItem.id, title: libItem.title, engine: libItem.engine" in jsx


def test_create_engine_node_refuses_an_unknown_engine():
    from nodelang.universal_pipeline import create_engine_node
    with pytest.raises(ValueError):
        create_engine_node(None, None, title="x", engine="does.not.exist")
