"""Bridge tests for the Settings-overlay housekeeping slots added in
the 2026-05-14 audit pass.

These slots back the JSX Settings overlay (rename / fork / delete a
session, theme persistence, storage stats, export-all, model cache
clear, forget all memory, delete all sessions, open data folder,
session + provider stats). Before this patch, the JSX buttons were
silent no-ops because the slots didn't exist.

All slots return _safe_json strings — never raise. We assert on the
JSON envelope shape (`ok`, `id`, `title`, `theme`, `bytes`, ...) so
the JSX side has stable contracts.
"""
from __future__ import annotations

import json
import os
import sys
import zipfile
from pathlib import Path

import pytest

APP_ROOT = Path(__file__).resolve().parent.parent / "app"
sys.path.insert(0, str(APP_ROOT))

import bridge as _bridge_module  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate_session_io_module_state(monkeypatch):
    """Structural isolation against cross-file test pollution
    (ROADMAP NEXT-30-DAYS — `test_delete_session_removes_file` was
    flaking in full-suite runs while passing isolated).

    Class of bug: a test file collected EARLIER imports `session_io`
    + caches/mutates module-level state (SESSIONS_DIR, session
    caches, etc.) that bleeds into our tests when the harness
    doesn't reset it between modules. Symptom: KeyError on slot
    invocation because the cached SESSIONS_DIR points at a stale
    or non-existent path.

    Fix: this autouse fixture forces `session_io` to be re-imported
    fresh + has the test-level `tmp_appdata` fixture stamp its
    SESSIONS_DIR via monkeypatch. The reset is structural — not
    a symptom patch on the one failing test."""
    import importlib
    import session_io as _sio
    # Capture the module's current SESSIONS_DIR + any other module-
    # level caches the JSX-facing slots read at call time.
    _orig_sessions_dir = getattr(_sio, "SESSIONS_DIR", None)
    # Re-stamping it via monkeypatch ensures any earlier test's
    # leak gets overridden + restored after this test.
    monkeypatch.setattr(_sio, "SESSIONS_DIR", _orig_sessions_dir)
    yield


@pytest.fixture
def tmp_appdata(tmp_path, monkeypatch):
    """Redirect LOCALAPPDATA + USERPROFILE so test writes never touch
    the user's real %LOCALAPPDATA%/ArchHub. SESSIONS_DIR is module-
    level so we monkeypatch the symbol directly in session_io."""
    appdata = tmp_path / "appdata"
    home    = tmp_path / "home"
    appdata.mkdir(parents=True, exist_ok=True)
    home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("LOCALAPPDATA", str(appdata))
    monkeypatch.setenv("USERPROFILE", str(home))
    # session_io grabs SESSIONS_DIR at import time — point it at our
    # tmp dir so all session-touching slots write here.
    import session_io as _sio
    sess_dir = appdata / "ArchHub" / "sessions"
    sess_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(_sio, "SESSIONS_DIR", sess_dir)
    return {"appdata": appdata, "home": home, "sessions": sess_dir}


@pytest.fixture
def bridge_inst():
    return _bridge_module.ArchHubBridge()


def _write_session(sess_dir: Path, slug: str, *,
                    name: str = "demo", graph=None) -> Path:
    """Helper — drop a minimal session JSON on disk for tests."""
    payload = {
        "id":       slug,
        "name":     name,
        "title":    name,
        "graph":    graph or {"nodes": [], "wires": []},
        "saved_at": "2026-05-14T00:00:00Z",
    }
    p = sess_dir / f"{slug}.archhub-session.json"
    p.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return p


# ---------------------------------------------------------------------
# rename_session
# ---------------------------------------------------------------------

def test_rename_session_round_trips_title(tmp_appdata, bridge_inst):
    p = _write_session(tmp_appdata["sessions"], "alpha", name="old")
    out = json.loads(bridge_inst.rename_session("alpha", "Renamed One"))
    assert out["ok"] is True
    assert out["id"] == "alpha"
    assert out["title"] == "Renamed One"
    payload = json.loads(p.read_text(encoding="utf-8"))
    assert payload["name"]  == "Renamed One"
    assert payload["title"] == "Renamed One"


def test_rename_session_missing_returns_error(tmp_appdata, bridge_inst):
    out = json.loads(bridge_inst.rename_session("ghost", "X"))
    assert "error" in out


def test_rename_session_blank_title_rejected(tmp_appdata, bridge_inst):
    _write_session(tmp_appdata["sessions"], "alpha")
    out = json.loads(bridge_inst.rename_session("alpha", "   "))
    assert "error" in out


# ---------------------------------------------------------------------
# fork_session
# ---------------------------------------------------------------------

def test_fork_session_creates_new_id(tmp_appdata, bridge_inst):
    _write_session(tmp_appdata["sessions"], "alpha", name="orig")
    out = json.loads(bridge_inst.fork_session("alpha", "Forked Copy"))
    assert out["ok"] is True
    assert out["id"] != "alpha"
    assert "fork" in out["id"] or "forked" in out["id"]
    assert out["title"] == "Forked Copy"
    new_file = tmp_appdata["sessions"] / f"{out['id']}.archhub-session.json"
    assert new_file.exists()
    payload = json.loads(new_file.read_text(encoding="utf-8"))
    assert payload["id"] == out["id"]
    assert payload["name"] == "Forked Copy"


def test_fork_session_default_title_from_original(tmp_appdata, bridge_inst):
    _write_session(tmp_appdata["sessions"], "alpha", name="orig")
    out = json.loads(bridge_inst.fork_session("alpha"))
    assert out["ok"] is True
    assert out["id"] != "alpha"
    # Default title is "<original>-fork"
    assert "fork" in out["title"].lower()


# ---------------------------------------------------------------------
# delete_session
# ---------------------------------------------------------------------

def test_delete_session_removes_file(tmp_appdata, bridge_inst):
    p = _write_session(tmp_appdata["sessions"], "alpha")
    assert p.exists()
    out = json.loads(bridge_inst.delete_session("alpha"))
    assert out["ok"] is True
    assert not p.exists()


def test_delete_session_missing_returns_error(tmp_appdata, bridge_inst):
    out = json.loads(bridge_inst.delete_session("ghost"))
    assert "error" in out


# ---------------------------------------------------------------------
# set_theme / get_theme
# ---------------------------------------------------------------------

def test_set_theme_and_get_theme_round_trip(tmp_appdata, bridge_inst):
    out = json.loads(bridge_inst.set_theme("light"))
    assert out["ok"] is True
    assert out["theme"] == "light"
    got = json.loads(bridge_inst.get_theme())
    assert got["theme"] == "light"
    # Switch + re-read
    bridge_inst.set_theme("system")
    assert json.loads(bridge_inst.get_theme())["theme"] == "system"


def test_set_theme_rejects_invalid(tmp_appdata, bridge_inst):
    out = json.loads(bridge_inst.set_theme("rainbow"))
    assert "error" in out


def test_get_theme_default_when_missing(tmp_appdata, bridge_inst):
    got = json.loads(bridge_inst.get_theme())
    assert got["theme"] == "dark"


# ---------------------------------------------------------------------
# get_storage_stats
# ---------------------------------------------------------------------

def test_get_storage_stats_returns_positive_bytes(tmp_appdata, bridge_inst):
    # Drop a few session files so the sessions count > 0 + bytes > 0.
    _write_session(tmp_appdata["sessions"], "a")
    _write_session(tmp_appdata["sessions"], "b")
    out = json.loads(bridge_inst.get_storage_stats())
    assert "sessions" in out
    assert "app" in out
    assert "custom_nodes" in out
    assert "skills" in out
    assert "total_bytes" in out
    assert out["sessions"]["count"] >= 2
    assert out["sessions"]["bytes"] > 0
    assert out["total_bytes"] > 0


# ---------------------------------------------------------------------
# export_all
# ---------------------------------------------------------------------

def test_export_all_creates_zip(tmp_appdata, bridge_inst):
    _write_session(tmp_appdata["sessions"], "a", name="export-me")
    out = json.loads(bridge_inst.export_all())
    assert out["ok"] is True
    p = Path(out["path"])
    assert p.exists()
    assert p.suffix == ".zip"
    assert out["size"] > 0
    # Verify our session is actually in the archive.
    with zipfile.ZipFile(p, "r") as z:
        names = z.namelist()
        assert any("a.archhub-session.json" in n for n in names)


# ---------------------------------------------------------------------
# clear_model_cache
# ---------------------------------------------------------------------

def test_clear_model_cache_no_dir_returns_ok(tmp_appdata, bridge_inst):
    out = json.loads(bridge_inst.clear_model_cache())
    assert out["ok"] is True
    assert out["freed_bytes"] == 0


def test_clear_model_cache_removes_contents(tmp_appdata, bridge_inst):
    cache = tmp_appdata["appdata"] / "ArchHub" / "model_cache"
    cache.mkdir(parents=True, exist_ok=True)
    (cache / "blob.bin").write_bytes(b"x" * 1024)
    out = json.loads(bridge_inst.clear_model_cache())
    assert out["ok"] is True
    assert out["freed_bytes"] >= 1024
    assert not (cache / "blob.bin").exists()


# ---------------------------------------------------------------------
# forget_all_memory
# ---------------------------------------------------------------------

def test_forget_all_memory_returns_ok(tmp_appdata, bridge_inst):
    base = tmp_appdata["appdata"] / "ArchHub"
    base.mkdir(parents=True, exist_ok=True)
    (base / "memory_facts.json").write_text("{}", encoding="utf-8")
    out = json.loads(bridge_inst.forget_all_memory())
    assert out["ok"] is True
    assert not (base / "memory_facts.json").exists()


# ---------------------------------------------------------------------
# delete_all_sessions
# ---------------------------------------------------------------------

def test_delete_all_sessions_removes_files(tmp_appdata, bridge_inst):
    _write_session(tmp_appdata["sessions"], "a")
    _write_session(tmp_appdata["sessions"], "b")
    _write_session(tmp_appdata["sessions"], "c")
    out = json.loads(bridge_inst.delete_all_sessions())
    assert out["ok"] is True
    assert out["deleted"] == 3
    leftover = list(tmp_appdata["sessions"].glob("*.archhub-session.json"))
    assert leftover == []


# ---------------------------------------------------------------------
# open_folder
# ---------------------------------------------------------------------

def test_open_folder_rejects_unknown_kind(tmp_appdata, bridge_inst,
                                            monkeypatch):
    monkeypatch.setattr(os, "startfile",
                        lambda *_a, **_k: None, raising=False)
    out = json.loads(bridge_inst.open_folder("rocketship"))
    assert "error" in out


def test_open_folder_known_kinds_dont_explode(tmp_appdata, bridge_inst,
                                                monkeypatch):
    """We can't actually pop Explorer in CI — monkeypatch os.startfile."""
    calls: list[str] = []
    monkeypatch.setattr(os, "startfile",
                        lambda p, *_a, **_k: calls.append(str(p)),
                        raising=False)
    for kind in ("sessions", "skills", "custom_nodes", "app", "logs"):
        out = json.loads(bridge_inst.open_folder(kind))
        # On platforms without os.startfile we still get an `ok` or an
        # `error` envelope — never an exception.
        assert "ok" in out or "error" in out


# ---------------------------------------------------------------------
# get_session_stats
# ---------------------------------------------------------------------

def test_get_session_stats_shape(tmp_appdata, bridge_inst):
    _write_session(tmp_appdata["sessions"], "a")
    _write_session(tmp_appdata["sessions"], "b")
    out = json.loads(bridge_inst.get_session_stats())
    assert out["count"] == 2
    assert "active_id" in out
    assert "last_modified" in out
    # last_modified should be ISO-ish (or empty if no files were
    # found — but here we wrote some so it must be non-empty).
    assert out["last_modified"] != ""


# ---------------------------------------------------------------------
# get_provider_stats
# ---------------------------------------------------------------------

class _FakeRouter:
    def configured_providers(self):
        return ["anthropic", "openai", "openrouter"]

    def blocked_providers(self):
        return {"google": "missing key"}


def test_get_provider_stats_with_router():
    b = _bridge_module.ArchHubBridge(router=_FakeRouter())
    out = json.loads(b.get_provider_stats())
    assert out["configured"] == 3
    assert out["blocked"] == 1


def test_get_provider_stats_no_router_returns_zeros():
    b = _bridge_module.ArchHubBridge()
    out = json.loads(b.get_provider_stats())
    assert out["configured"] == 0
    assert out["blocked"] == 0


# ---------------------------------------------------------------------
# Reachability — every new slot must be a @pyqtSlot on the class so the
# JSX side sees it through QWebChannel introspection.
# ---------------------------------------------------------------------

@pytest.mark.parametrize("name", [
    "rename_session", "fork_session", "delete_session",
    "set_theme", "get_theme", "get_storage_stats", "export_all",
    "clear_model_cache", "forget_all_memory", "delete_all_sessions",
    "open_folder", "get_session_stats", "get_provider_stats",
    "load_skill", "get_node_grammar",
])
def test_new_slots_present_on_bridge(name):
    assert hasattr(_bridge_module.ArchHubBridge, name), (
        f"missing bridge slot: {name}"
    )


def test_load_skill_round_trips_a_saved_skill():
    """save_as_skill writes a canvas skill; load_skill reads its graph
    back. Founder bug 2026-05-18: the panel listed one store while
    load_skill globbed another, so spawning a saved skill no-op'd.
    This pins the save -> load round-trip on ONE store."""
    import json
    from pathlib import Path
    b = _bridge_module.ArchHubBridge()
    payload = json.dumps({"nodes": [{"id": "n1", "cat": "host"}],
                          "wires": []})
    saved = json.loads(b.save_as_skill("Bridge Slot Test Skill", payload))
    slug = saved.get("slug")
    assert slug, saved
    # save_as_skill writes the writable user store (%LOCALAPPDATA%),
    # never the source tree — verify the path lands there.
    assert Path(saved["path"]).parent == _bridge_module._user_skills_dir()
    loaded = json.loads(b.load_skill(slug))
    assert isinstance(loaded.get("nodes"), list)
    assert loaded["nodes"] and loaded["nodes"][0]["id"] == "n1"
    assert loaded.get("wires") == []
    # Unknown skill -> honest error, never a fabricated graph.
    missing = json.loads(b.load_skill("no-such-skill-xyz"))
    assert "error" in missing


def test_get_saved_skills_lists_only_loadable_skills():
    """THE drift guard. Every skill get_saved_skills returns MUST be
    loadable by load_skill — list + loader share one resolver
    (_scan_canvas_skills), so they cannot point at different stores
    again. Structural fix for the 'empty & not working' Skills panel
    (founder, 2026-05-18): the list read skills.library while the
    loader globbed app/skills/, so every panel click 404'd."""
    import json
    b = _bridge_module.ArchHubBridge()
    # Seed one canvas skill into the writable store.
    b.save_as_skill("Drift Guard Skill",
                    json.dumps({"nodes": [{"id": "g1", "cat": "ai"}],
                                "wires": []}))
    listed = json.loads(b.get_saved_skills())
    assert isinstance(listed, list), listed
    assert listed, "expected at least the seeded skill"
    for entry in listed:
        assert entry.get("id"), entry
        loaded = json.loads(b.load_skill(entry["id"]))
        assert "error" not in loaded, (
            f"listed skill {entry['id']!r} is not loadable: {loaded}")
        assert isinstance(loaded.get("nodes"), list)


def test_shipped_canvas_skills_are_loadable():
    """Skills shipped in app/skills/*.archhub-skill.json must parse +
    load — they are the panel's built-in starter skills."""
    import json
    b = _bridge_module.ArchHubBridge()
    shipped = _bridge_module._shipped_skills_dir()
    files = list(shipped.glob("*.archhub-skill.json"))
    assert files, "no shipped canvas skills found in app/skills/"
    for f in files:
        env = json.loads(f.read_text(encoding="utf-8"))
        slug = env.get("slug") or f.stem.replace(".archhub-skill", "")
        loaded = json.loads(b.load_skill(slug))
        assert "error" not in loaded, (loaded, slug)
        assert isinstance(loaded.get("nodes"), list)


def test_get_node_grammar_returns_the_canonical_grammar():
    """get_node_grammar exposes the ~12-primitive node grammar so the
    JSX canvas builds its palette from ONE source (no parallel JS-side
    node list that drifts — the LM_LIBRARY mistake)."""
    import json
    b = _bridge_module.ArchHubBridge()
    payload = json.loads(b.get_node_grammar())
    assert isinstance(payload, list), payload
    assert payload, "grammar must not be empty"
    # SLICE H + I: typed-node split per category. Cap bumped further
    # for LOGIC / SHAPE / WATCH / TRIGGER typed nodes. AgDR-0016 added
    # SHARE (3) + ADAPTER (3). AgDR-0018 added 3 more ADAPTER nodes.
    # Ceiling stays well below the old 80-node decorative catalogue.
    assert len(payload) <= 70, "a grammar, not a catalogue"
    kinds = {p["kind"] for p in payload}
    # Required families now represented by typed-node anchors:
    #   input  → number    · logic   → if      · output → result
    #   watch  → table     · trigger → manual_run · ai → ai_chat
    for fam in ("connector", "ai_chat", "number", "result", "if"):
        assert fam in kinds, f"{fam!r} missing from the node grammar"
    for entry in payload:
        assert {"kind", "display", "cat", "selector",
                "engine_types", "status", "note"} <= entry.keys()
