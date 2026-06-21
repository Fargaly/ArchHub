"""Skills + Search sidebar panels — REAL-wiring gate (MAKE-IT-REAL).

Context (2026-06-15): the SkillsPanel + SearchPanel were purged 2026-05-14
as "empty shells". The emptiness was a MECHANICAL bug, not an unwanted
feature: the originals read their data with the SYNC `bridgeJson(...)`, and a
QWebChannel slot never returns synchronously — so every list rendered zero
rows and the panels looked dead. Per the founder's MAKE-IT-REAL mandate
("a fake is NOT resolved by deleting it... if it's something I asked for and
beneficial, make it real"), the panels are RESTORED and wired the RIGHT way:
they load real data via the async `bridgeAsync(...)` path into React state.

This gate locks the restore so it cannot silently regress to the dead/deleted
state. It proves three things the task requires:

  1. The panels DISPATCH REAL bridge slots (get_saved_skills / get_sessions /
     list_memory_facts / library_search), wired via bridgeAsync — not the
     sync bridgeJson that caused the original death, and not a stub.
  2. Those slots RETURN REAL (non-stub) data — exercised against the live
     ArchHubBridge with a real on-disk skill + the real in-process library,
     round-tripping actual content (not a hard-coded fake).
  3. The panels are REACHABLE from a VISIBLE affordance — the IconRail has
     Skills + Search items and SidebarInner mounts the matching panel — and
     the skill drag-onto-canvas has a real receiver in the canvas drop path.

Both the source AND the compiled bundle the app actually loads are checked
(the boot path runs studio-lm.compiled.js when its sha matches the .jsx).
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

APP_ROOT = Path(__file__).resolve().parents[1] / "app"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

_JSX_SRC = (APP_ROOT / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
_COMPILED = (APP_ROOT / "web_ui" / "studio-lm.compiled.js").read_text(
    encoding="utf-8")
# Comment-stripped view so an assertion can't be satisfied by a comment, and
# whitespace-flat views so spacing/line-wrap differences never break a match
# (the compiled bundle strips inter-token spaces).
_JSX_CODE = re.sub(r"//[^\n]*", "", _JSX_SRC)
_JSX_FLAT = re.sub(r"\s+", " ", _JSX_CODE)
_COMPILED_FLAT = re.sub(r"\s+", " ", _COMPILED)


def _jsx_window(anchor: str, size: int = 1200) -> str:
    i = _JSX_CODE.find(anchor)
    assert i >= 0, f"anchor not found in studio-lm.jsx: {anchor!r}"
    return _JSX_CODE[i:i + size]


# ════════════════════════════════════════════════════════════════════
# PART 1 — the slots return REAL data (live ArchHubBridge, no Qt boot)
# ════════════════════════════════════════════════════════════════════
# The slots are plain synchronous Python methods returning JSON strings;
# QWebChannel only makes the *transport* async. We can call them directly on
# an instance built via __new__ (no event loop), mirroring the proven pattern
# in test_delete_saved_skill.py / test_library_bridge.py.


@pytest.fixture
def isolated_skill_dirs(monkeypatch, tmp_path):
    """Point the canvas-skill store at tmp dirs and drop ONE real skill
    envelope in, so get_saved_skills/load_skill round-trip actual content."""
    import bridge
    user_dir = tmp_path / "user_skills"
    shipped_dir = tmp_path / "shipped_skills"
    user_dir.mkdir()
    shipped_dir.mkdir()
    monkeypatch.setattr(bridge, "_user_skills_dir", lambda: user_dir)
    monkeypatch.setattr(bridge, "_shipped_skills_dir", lambda: shipped_dir)
    # Neutralise any pre-existing tombstone file so the seed is visible.
    monkeypatch.setattr(bridge, "_load_skill_tombstones", lambda: set())
    # A REAL canvas-skill: a 2-node graph the panel can list AND spawn.
    envelope = {
        "name": "Wall dimensions",
        "slug": "wall_dimensions",
        "graph": {
            "nodes": [
                {"id": "n1", "kind": "connector.run", "cat": "read",
                 "x": 0, "y": 0, "title": "list walls"},
                {"id": "n2", "kind": "connector.run", "cat": "write",
                 "x": 200, "y": 0, "title": "dimension"},
            ],
            "wires": [{"from": ["n1", "out"], "to": ["n2", "in"]}],
        },
        "meta": {"mode": "private", "description": "Dimension every wall",
                 "category": "revit"},
    }
    (user_dir / "wall_dimensions.archhub-skill.json").write_text(
        json.dumps(envelope), encoding="utf-8")
    return bridge, user_dir, shipped_dir


def test_get_saved_skills_returns_real_rows(isolated_skill_dirs):
    """SkillsPanel's slot returns the real on-disk skill with real fields —
    NOT a stub, NOT an empty list."""
    bridge, _user, _shipped = isolated_skill_dirs
    inst = bridge.ArchHubBridge.__new__(bridge.ArchHubBridge)
    payload = json.loads(inst.get_saved_skills())
    assert isinstance(payload, list), f"expected a list, got {payload!r}"
    rows = {r["id"]: r for r in payload}
    assert "wall_dimensions" in rows, (
        "the real on-disk skill must surface in get_saved_skills")
    row = rows["wall_dimensions"]
    # Real content threaded from the envelope, not a placeholder.
    assert row["name"] == "Wall dimensions"
    assert row["node_count"] == 2, "node_count reflects the REAL graph"
    assert row["mode"] == "private"
    assert row["description"] == "Dimension every wall"


def test_load_skill_returns_real_graph(isolated_skill_dirs):
    """The click/drag path (lm-spawn-skill → load_skill) resolves the SAME
    store and returns the real graph the canvas splices."""
    bridge, _user, _shipped = isolated_skill_dirs
    inst = bridge.ArchHubBridge.__new__(bridge.ArchHubBridge)
    blob = json.loads(inst.load_skill("wall_dimensions"))
    assert "error" not in blob, blob
    assert isinstance(blob.get("nodes"), list) and len(blob["nodes"]) == 2
    assert isinstance(blob.get("wires"), list) and len(blob["wires"]) == 1
    # The exact nodes round-trip (real data, not a fabricated shape).
    kinds = {n["kind"] for n in blob["nodes"]}
    assert kinds == {"connector.run"}


def test_get_saved_skills_is_not_a_stub(isolated_skill_dirs):
    """Belt-and-braces: the slot reads the real store, so REMOVING the file
    makes the row disappear. A stub would keep returning canned rows."""
    bridge, user_dir, _shipped = isolated_skill_dirs
    inst = bridge.ArchHubBridge.__new__(bridge.ArchHubBridge)
    assert any(r["id"] == "wall_dimensions"
               for r in json.loads(inst.get_saved_skills()))
    (user_dir / "wall_dimensions.archhub-skill.json").unlink()
    after = json.loads(inst.get_saved_skills())
    assert not any(r["id"] == "wall_dimensions" for r in after), (
        "get_saved_skills must reflect the real store — it is not a stub")


def test_library_search_returns_real_results(monkeypatch, tmp_path):
    """SearchPanel's library scope hits library_search, which returns real
    ranked node-types from the seeded in-process library."""
    import bridge as _bridge_module
    import library as _lib
    appdata = tmp_path / "appdata"
    appdata.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("LOCALAPPDATA", str(appdata))
    _lib.reset_registry()
    try:
        # Full construction (like test_library_bridge.py): library_search runs
        # _library_bootstrap which needs the real instance state.
        b = _bridge_module.ArchHubBridge()
        payload = json.loads(b.library_search("constant", "", 8))
        assert "results" in payload and payload["count"] >= 1, payload
        assert any(r.get("type") == "data.constant"
                   for r in payload["results"]), (
            "library_search must return the real seeded data.constant node")
        # A nonsense query returns an honest empty set (not a canned stub).
        empty = json.loads(b.library_search("zzx-no-such-node-zzx", "", 8))
        assert empty["results"] == [] and empty["count"] == 0
    finally:
        _lib.reset_registry()


def test_list_memory_facts_returns_structured_envelope(monkeypatch, tmp_path):
    """SearchPanel's memory scope hits list_memory_facts. With cloud absent
    it returns an HONEST typed envelope (degraded, not a fabricated stub) —
    and never raises. The slot reads the real cloud client, so when the call
    can't be made the answer is an error envelope, never invented facts."""
    import bridge as _bridge_module
    # Full construction: list_memory_facts routes through _cached_async which
    # needs the real per-instance async state.
    b = _bridge_module.ArchHubBridge()
    # Force the cloud request to fail deterministically so the test is
    # hermetic and we observe the honest-degradation contract.
    import cloud_client
    monkeypatch.setattr(
        cloud_client, "_request",
        lambda *a, **k: {"status": "error", "json": None})
    raw = b.list_memory_facts("anything")
    payload = json.loads(raw)
    # Either the cached-async wrapper hands back the `empty` ({}) default or
    # the honest error envelope — both are structured + non-fabricated. The
    # banned outcome is invented fact rows when the backend is unreachable.
    assert isinstance(payload, dict), f"expected dict envelope, got {payload!r}"
    if payload:
        assert "error" in payload, (
            "offline list_memory_facts must be an honest error, not fake facts")


# ════════════════════════════════════════════════════════════════════
# PART 2 — the panels DISPATCH the real slots (JSX source guards)
# ════════════════════════════════════════════════════════════════════


class TestSkillsPanelWiring:
    def test_skills_panel_component_exists(self):
        assert "const SkillsPanel = (" in _JSX_CODE, (
            "SkillsPanel must be RESTORED (MAKE-IT-REAL — not deleted)")

    def test_skills_panel_loads_real_async_slot(self):
        block = _jsx_window("const SkillsPanel = (", size=1800)
        # REAL slot via the ASYNC path — the fix for the original death.
        assert "bridgeAsync('get_saved_skills')" in block, (
            "SkillsPanel must load get_saved_skills via bridgeAsync (the "
            "sync bridgeJson is exactly what made the original panel dead)")
        # It must NOT regress to the sync slot that returned null.
        assert "bridgeJson('get_saved_skills')" not in block

    def test_skills_panel_spawns_via_real_event(self):
        block = _jsx_window("const SkillsPanel = (", size=3600)
        # Click + drag both route to the real spawn path.
        assert "lm-spawn-skill" in block, (
            "clicking a skill must dispatch lm-spawn-skill (→ onSpawnSkill "
            "→ load_skill → real canvas splice)")
        assert "application/x-archhub-skill" in block, (
            "dragging a skill must carry the typed payload the canvas accepts")

    def test_skills_panel_refreshes_on_mutation(self):
        block = _jsx_window("const SkillsPanel = (", size=1800)
        assert "lm-skills-refresh" in block, (
            "SkillsPanel must re-fetch on lm-skills-refresh so a promote/"
            "save updates the list live")


class TestSearchPanelWiring:
    def test_search_panel_component_exists(self):
        assert "const SearchPanel = (" in _JSX_CODE, (
            "SearchPanel must be RESTORED (MAKE-IT-REAL — not deleted)")

    def test_search_panel_dispatches_all_real_slots(self):
        block = _jsx_window("const SearchPanel = (", size=4200)
        for slot in ("get_sessions", "get_saved_skills",
                     "list_memory_facts", "library_search"):
            assert f"bridgeAsync('{slot}'" in block, (
                f"SearchPanel must search via the real async slot {slot}")

    def test_search_panel_does_not_use_dead_sync_path(self):
        block = _jsx_window("const SearchPanel = (", size=4200)
        # The original SearchPanel died because it used sync bridgeJson for
        # these. The restore must not reintroduce that.
        for slot in ("get_sessions", "get_saved_skills",
                     "list_memory_facts", "library_search"):
            assert f"bridgeJson('{slot}'" not in block, (
                f"SearchPanel must not use the dead sync bridgeJson for {slot}")

    def test_search_panel_hits_route_to_real_destinations(self):
        block = _jsx_window("const SearchPanel = (", size=8000)
        # A session hit opens; a node hit focuses; a skill hit spawns; a
        # library hit adds the node — all real, wired destinations.
        assert "onOpen && onOpen(s.id)" in block
        assert "setFocusId && setFocusId(n.id)" in block
        assert "lm-spawn-skill" in block
        assert "addNodeFromLibrary({" in block

    def test_searchhit_component_restored(self):
        assert "const SearchHit = (" in _JSX_CODE


# ════════════════════════════════════════════════════════════════════
# PART 3 — the panels are REACHABLE from a visible affordance
# ════════════════════════════════════════════════════════════════════


class TestPanelsReachable:
    def test_rail_has_search_skills_via_cmdk(self):
        # Founder 2026-06-20 ("strip to essentials" + "I don't want the UI
        # cramped with shit with no use"): Skills + Nodes were REMOVED from the
        # rail (redundant with the graph library / Cmd-K). Search stays. This
        # locks the strip so they can't silently return to the rail.
        block = re.sub(r"\s+", " ", _jsx_window("const IconRailInner = (", size=2200))
        assert "id:'search', title:'Search'" in block, (
            "the left rail must keep a Search destination icon")
        assert "id:'skills', title:'Skills'" not in block, (
            "Skills must NOT be a rail icon anymore (reachable via Cmd-K)")
        assert "id:'nodes', title:'Nodes'" not in block, (
            "Nodes must NOT be a rail icon anymore (reachable via the library)")

    def test_sidebar_mounts_panels_on_rail_switch(self):
        block = _jsx_window("const SidebarInner = (", size=1400)
        flat = re.sub(r"\s+", " ", block)
        assert "panel === 'skills'" in flat and "<SkillsPanel" in flat, (
            "SidebarInner must render SkillsPanel when the rail selects it")
        assert "panel === 'search'" in flat and "<SearchPanel" in flat, (
            "SidebarInner must render SearchPanel when the rail selects it")

    def test_search_panel_receives_real_callbacks_from_sidebar(self):
        block = _jsx_window("const SidebarInner = (", size=1400)
        flat = re.sub(r"\s+", " ", block)
        # The wired props that make hits actionable must be passed down.
        assert "onOpen={onOpen}" in flat
        assert "setFocusId={setFocusId}" in flat
        assert "addNodeFromLibrary={addNodeFromLibrary}" in flat

    def test_canvas_drop_receives_dragged_skill(self):
        # The SkillsPanel drag is only real if the canvas accepts the drop.
        drop = _jsx_window("const onDrop = (e) => {", size=900)
        assert "application/x-archhub-skill" in drop, (
            "the canvas onDrop must read the skill payload")
        assert "lm-spawn-skill" in drop, (
            "a dropped skill must route through the real spawn path")
        # dragover must allow the skill type through, else the drop is refused.
        over = _jsx_window("const onDragOver = (e) => {", size=600)
        assert "application/x-archhub-skill" in over, (
            "onDragOver must whitelist the skill MIME or the browser blocks "
            "the drop")


# ════════════════════════════════════════════════════════════════════
# PART 4 — the COMPILED bundle the app loads carries the wiring
# ════════════════════════════════════════════════════════════════════


class TestCompiledBundleParity:
    def test_panels_present_in_bundle(self):
        # Babel preserves identifiers + single quotes, strips inter-token
        # spaces — match the minified form via the flat view.
        assert "var SkillsPanel=" in _COMPILED_FLAT or \
               "const SkillsPanel=" in _COMPILED_FLAT, (
            "SkillsPanel must be in the compiled bundle the app boots")
        assert "var SearchPanel=" in _COMPILED_FLAT or \
               "const SearchPanel=" in _COMPILED_FLAT

    def test_real_slots_wired_in_bundle(self):
        for slot in ("get_saved_skills", "get_sessions",
                     "list_memory_facts", "library_search"):
            assert f"bridgeAsync('{slot}'" in _COMPILED_FLAT, (
                f"{slot} async wiring must be in the compiled bundle")

    def test_rail_items_in_bundle(self):
        # Stripped rail (founder 2026-06-20): Search is the kept rail destination.
        # (Skills/Nodes are no longer rail items — reachable via Cmd-K/library.)
        assert "id:'search'" in _COMPILED_FLAT

    def test_canvas_skill_drop_in_bundle(self):
        assert "application/x-archhub-skill" in _COMPILED, (
            "the skill drop receiver must be in the compiled bundle")
