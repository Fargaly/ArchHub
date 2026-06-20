"""Realify left-rail + Share panel + Brain folder tree — REAL-wiring gate.

Founder audit (2026-06-18, verified live via CDP): clicking DECK/NODES/SKILLS/
SEARCH/SHARE on Home did NOTHING (the main view never changed), and the Brain
view was cards-only with ZERO folder/tree. Both are the banned "shell" failure
(MAKE-IT-REAL: "nothing for show only"). This gate locks the fix so it cannot
silently regress:

  PART 1  — every left-rail item opens its REAL surface from ANY view (Home AND
            in-session): the rail dispatches a real open-handler, never a no-op.
  PART 1b — the Share rail item opens a REAL SharePanel listing the user's
            shareable skills + sessions with real actions, backed by a real
            bridge slot (share_export) that writes a re-loadable artifact.
  PART 2  — the Brain view has a real collapsible folder/tree (scope → project
            → fact) sourced from the SAME brain.browse payload, drilling to a
            fact's detail.

Both the source AND the compiled bundle the app actually boots are checked.

RED→GREEN: on origin/main (before this change) the rail's panel items were
`disabled` on Home (setPanel===_NOOP → a dead clickable), there was NO
SharePanel / share_export, and NO BrainFolderTree — so every assertion below
fails. `git stash` proves it.
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
# Comment-stripped + whitespace-flat views (a match can't be satisfied by a
# comment, and spacing/line-wrap differences never break it).
_JSX_CODE = re.sub(r"//[^\n]*", "", _JSX_SRC)
_JSX_FLAT = re.sub(r"\s+", " ", _JSX_CODE)
_COMPILED_FLAT = re.sub(r"\s+", " ", _COMPILED)


def _jsx_window(anchor: str, size: int = 1600) -> str:
    i = _JSX_CODE.find(anchor)
    assert i >= 0, f"anchor not found in studio-lm.jsx: {anchor!r}"
    return _JSX_CODE[i:i + size]


def _flat(anchor: str, size: int = 1600) -> str:
    return re.sub(r"\s+", " ", _jsx_window(anchor, size))


# ════════════════════════════════════════════════════════════════════
# PART 1 — the LEFT RAIL opens REAL surfaces (no no-op, works from Home)
# ════════════════════════════════════════════════════════════════════


class TestRailWiring:
    def test_rail_items_dispatch_real_open_handler_not_noop(self):
        """The NODES/SKILLS/SEARCH items must dispatch a REAL open event
        (lm-rail-open) on click — NOT the old `disabled-on-Home` dead path.
        The whole point of the founder audit: these were no-ops on Home."""
        block = _flat("const IconRailInner = (", size=3200)
        # Each panel item opens the real drawer from any view.
        assert "lm-rail-open" in block, (
            "rail panel items must dispatch lm-rail-open (open the REAL panel "
            "from Home AND in-session) — not a no-op")
        # The regressed dead path (disable the item when setPanel is the NOOP)
        # must be GONE: items are real from Home now.
        assert "disabled={dead}" not in block, (
            "rail panel items must NOT be disabled on Home anymore — they open "
            "the real surface from any view")

    def test_rail_items_still_sync_sidebar_in_session(self):
        """In-session the rail must ALSO switch the docked sidebar panel
        (existing behaviour preserved), so the rail and sidebar stay in sync."""
        block = _flat("const IconRailInner = (", size=6000)
        assert "setPanel(it.id)" in block, (
            "in a session the rail must still drive the sidebar panel switch")

    def test_rail_stripped_to_essentials(self):
        """Founder 2026-06-19 ('strip to essentials'): the rail drops the Command
        Deck and the NODES/SKILLS buttons (redundant with the graph library).
        Only the search drawer-item remains; skills move to the Cmd-K palette."""
        block = _flat("const IconRailInner = (", size=6000)
        assert "rail-deck" not in block, "Command Deck must be removed from the rail"
        assert "lm-command-deck-open" not in block, "the DECK rail trigger must be gone"
        assert "it.id === 'search'" in block, (
            "the rail items map must be filtered to the search drawer only "
            "(nodes/skills removed)")
        # Skills left the rail — they MUST stay reachable via the Cmd-K palette.
        pal = _flat("'open-plan-history'", size=600)
        assert "open-skills" in pal, (
            "skills left the rail — add a Cmd-K 'Open skills' action so they are "
            "not orphaned")

    def test_rail_share_opens_real_share_panel(self):
        """SHARE must open the REAL Share panel drawer (lm-rail-open share),
        NOT the old silent save_as_skill shell with no visible surface."""
        block = _flat("const IconRailInner = (", size=6000)
        assert "panel:'share'" in block, (
            "the SHARE item must open the real SharePanel drawer "
            "(lm-rail-open {panel:'share'})")

    def test_rail_testids_present(self):
        block = _flat("const IconRailInner = (", size=6000)
        # The panel items build their testid dynamically ('rail-' + it.id), so
        # rail-nodes / rail-skills / rail-search render at runtime; the static
        # items carry literal testids.
        for tid in ("rail-home", "rail-share-icon"):
            assert tid in block, f"rail item must carry data-testid {tid!r}"
        assert "'rail-' + it.id" in block, (
            "panel items must carry a per-id testid (rail-nodes/-skills/-search)")
        # And the drawer host stamps the resolved testids the CDP checks use.
        host = _flat("const RAIL_DRAWER_META = {", size=400)
        for tid in ("rail-nodes", "rail-skills", "rail-search"):
            assert tid in host, f"the opened drawer must carry data-testid {tid!r}"

    def test_rail_drawer_host_mounts_real_panels(self):
        """The drawer host renders the REAL panels — not stubs — so opening
        from Home shows populated content."""
        block = _flat("const RailDrawerHostInner = (", size=2600)
        assert "<NodesPanelMemo" in block
        assert "<SkillsPanel" in block
        assert "<SearchPanel" in block
        assert "<SharePanel" in block

    def test_rail_drawer_host_is_mounted_in_app(self):
        assert "<RailDrawerHost" in _JSX_FLAT, (
            "RailDrawerHost must be mounted so lm-rail-open has a receiver")

    def test_rail_drawer_open_listener_wired(self):
        block = _flat("const RailDrawerHostInner = (", size=2600)
        assert "addEventListener('lm-rail-open'" in block, (
            "the drawer host must listen for lm-rail-open")

    def test_rail_drawer_place_node_starts_canvas_from_home(self):
        """Placing a node from a Home drawer must START a working canvas (never
        a no-op): ensureCanvas dispatches lm-new-session when none is open."""
        block = _flat("const RailDrawerHostInner = (", size=3200)
        assert "__archhub_session_id" in block and "lm-new-session" in block, (
            "a place/spawn from Home must start/focus a working canvas")


# ════════════════════════════════════════════════════════════════════
# PART 1b — the SHARE panel + the share_export bridge slot are REAL
# ════════════════════════════════════════════════════════════════════


class TestSharePanelJsx:
    def test_share_panel_component_exists(self):
        assert "const SharePanel = (" in _JSX_CODE, (
            "SharePanel must exist (PART 1b — the rail's Share surface)")

    def test_share_panel_loads_real_shareables(self):
        block = _jsx_window("const SharePanel = (", size=3000)
        assert "bridgeAsync('get_saved_skills')" in block, (
            "SharePanel must list real saved skills")
        assert "bridgeAsync('get_sessions')" in block, (
            "SharePanel must list real sessions")

    def test_share_panel_actions_call_real_slots(self):
        block = _jsx_window("const SharePanel = (", size=6000)
        # Copy-link / Export-JSON route through the real share_export slot.
        assert "share_export" in block, (
            "SharePanel actions must call the real share_export slot")
        # Publish routes through the real promote slot.
        assert "promote_skill_to_shared" in block, (
            "SharePanel Publish must call the real promote_skill_to_shared slot")

    def test_share_panel_has_honest_empty_states(self):
        block = _jsx_window("const SharePanel = (", size=10000)
        assert "rail-share-skills-empty" in block
        assert "rail-share-sessions-empty" in block

    def test_share_panel_rows_have_testids(self):
        block = _jsx_window("const SharePanel = (", size=10000)
        assert "rail-share-skill-row" in block
        assert "rail-share-session-row" in block


@pytest.fixture
def isolated_share_stores(monkeypatch, tmp_path):
    """Point the skill + session + share stores at tmp dirs, seed one real
    skill + one real session, so share_export round-trips actual content."""
    import bridge
    from importlib import import_module
    session_io = import_module("session_io")

    user_dir = tmp_path / "user_skills"
    shipped_dir = tmp_path / "shipped_skills"
    share_dir = tmp_path / "shared"
    sess_dir = tmp_path / "sessions"
    for d in (user_dir, shipped_dir, share_dir, sess_dir):
        d.mkdir()
    monkeypatch.setattr(bridge, "_user_skills_dir", lambda: user_dir)
    monkeypatch.setattr(bridge, "_shipped_skills_dir", lambda: shipped_dir)
    monkeypatch.setattr(bridge, "_share_dir", lambda: share_dir)
    monkeypatch.setattr(bridge, "_load_skill_tombstones", lambda: set())
    # Redirect the sessions store too (share_export(session) reads it).
    monkeypatch.setattr(session_io, "SESSIONS_DIR", sess_dir)

    skill_env = {
        "kind": "archhub.skill", "name": "Wall QC", "slug": "wall_qc",
        "meta": {"mode": "private", "description": "QC every wall",
                 "category": "revit"},
        "graph": {"nodes": [{"id": "n1", "kind": "connector.run"}],
                  "wires": []},
    }
    (user_dir / "wall_qc.archhub-skill.json").write_text(
        json.dumps(skill_env), encoding="utf-8")
    (sess_dir / f"demo{session_io.SESSION_EXT}").write_text(
        json.dumps({"name": "Demo session", "nodes": []}), encoding="utf-8")
    return bridge, share_dir


class TestShareExportSlot:
    def test_share_export_skill_writes_real_artifact(self, isolated_share_stores):
        bridge, share_dir = isolated_share_stores
        inst = bridge.ArchHubBridge.__new__(bridge.ArchHubBridge)
        r = json.loads(inst.share_export("skill", "wall_qc"))
        assert r.get("ok") is True, r
        assert r["kind"] == "skill"
        # Real file on disk + real JSON content (not a fabricated row).
        assert Path(r["path"]).exists(), "share_export must write a real file"
        assert Path(r["path"]).parent == share_dir
        blob = json.loads(r["json"])
        assert blob["name"] == "Wall QC"
        assert blob["graph"]["nodes"], "the artifact carries the real graph"

    def test_share_export_session_writes_real_artifact(self, isolated_share_stores):
        bridge, share_dir = isolated_share_stores
        inst = bridge.ArchHubBridge.__new__(bridge.ArchHubBridge)
        r = json.loads(inst.share_export("session", "demo"))
        assert r.get("ok") is True, r
        assert r["kind"] == "session"
        assert Path(r["path"]).exists()
        blob = json.loads(r["json"])
        assert blob["name"] == "Demo session"

    def test_share_export_honest_on_missing_and_bad_kind(self, isolated_share_stores):
        bridge, _ = isolated_share_stores
        inst = bridge.ArchHubBridge.__new__(bridge.ArchHubBridge)
        # Missing item → honest error, never a fabricated artifact (ANTI-LIE).
        miss = json.loads(inst.share_export("skill", "does-not-exist"))
        assert "error" in miss and "ok" not in miss
        bad = json.loads(inst.share_export("bogus", "x"))
        assert "error" in bad


# ════════════════════════════════════════════════════════════════════
# PART 2 — the BRAIN FOLDER TREE renders folders + drills to a fact
# ════════════════════════════════════════════════════════════════════


class TestBrainFolderTreeJsx:
    def test_folder_tree_component_exists(self):
        assert "const BrainFolderTree = (" in _JSX_CODE, (
            "BrainFolderTree must exist (PART 2 — the founder wants folders)")

    def test_folder_tree_sourced_from_browse_payload(self):
        block = _jsx_window("const BrainFolderTree = (", size=6500)
        # The tree reads the SAME brain.browse payload fields the cards use —
        # totals (scope folder counts) + projects (sub-folder census).
        assert "view.totals" in block
        assert "view.projects" in block

    def test_folder_tree_three_levels_scope_project_leaf(self):
        block = _jsx_window("const BrainFolderTree = (", size=8000)
        assert 'data-folder-kind="scope"' in block
        assert 'data-folder-kind="project"' in block
        assert 'data-folder-kind="leaf"' in block

    def test_folder_tree_leaf_opens_fact_detail(self):
        block = _jsx_window("const BrainFolderTree = (", size=8000)
        # Clicking a leaf opens the SAME BrainCard the cards view uses.
        assert "brain-folder-leaf" in block
        assert "brain-folder-leaf-detail" in block
        assert "<BrainCard" in block, (
            "a leaf must drill to the fact's real card detail")

    def test_folder_tree_testids(self):
        block = _jsx_window("const BrainFolderTree = (", size=8000)
        assert "brain-folder-tree" in block
        assert 'data-testid="brain-folder"' in block

    def test_browser_has_cards_folders_toggle(self):
        block = _jsx_window("const BrainBrowser = (", size=20000)
        assert "brain-view-mode-folders" in re.sub(r"\s+", " ", block) or \
               "brain-view-mode-" in re.sub(r"\s+", " ", block), (
            "the brain browser must offer a Cards↔Folders toggle")
        assert "<BrainFolderTree" in block, (
            "the browser must render the folder tree in folders mode")

    def test_cards_view_preserved(self):
        """Keep ALL existing behaviour: the cards view (top-of-mind + lanes)
        must still be present (founder: 'Keep ALL existing behavior')."""
        block = _jsx_window("const BrainBrowser = (", size=20000)
        assert "brain-top-of-mind" in block
        assert "brain-facet-lanes" in block


def test_brain_all_cards_helper_aggregates_payload():
    """The tree's leaf source is the real cards in the payload (top_of_mind +
    every lane cluster). The helper exists + the wiring references it."""
    assert "const _brainAllCards = (" in _JSX_CODE
    block = _jsx_window("const _brainAllCards = (", size=900)
    assert "top_of_mind" in block and "clusters" in block, (
        "leaves must come from the real top_of_mind + lane clusters")


# ════════════════════════════════════════════════════════════════════
# PART 3 — the COMPILED bundle the app BOOTS carries every surface
# ════════════════════════════════════════════════════════════════════


class TestCompiledBundleParity:
    def test_components_in_bundle(self):
        for ident in ("SharePanel", "RailDrawerHost", "BrainFolderTree"):
            assert (f"var {ident}=" in _COMPILED_FLAT
                    or f"const {ident}=" in _COMPILED_FLAT
                    or f"{ident}=React.memo" in _COMPILED_FLAT
                    or f"{ident} =" in _COMPILED_FLAT), (
                f"{ident} must be in the compiled bundle the app boots")

    def test_rail_open_event_in_bundle(self):
        assert "lm-rail-open" in _COMPILED, (
            "the rail→drawer wiring must be in the compiled bundle")

    def test_share_export_wired_in_bundle(self):
        assert "share_export" in _COMPILED, (
            "the SharePanel→share_export wiring must be in the compiled bundle")

    def test_folder_tree_testids_in_bundle(self):
        assert "brain-folder-tree" in _COMPILED
        assert "rail-share" in _COMPILED
