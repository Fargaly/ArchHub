"""AgDR-0032 — delete_saved_skill must hit the canvas-skill store
that get_saved_skills lists from, not the engine-skill library.

Founder bug 2026-05-21: "attempted deletion... but nothing happened."
Root cause: v1 called skills.library.delete_skill which scans a
DIFFERENT store than _scan_canvas_skills.  Skills listed in the
panel never deleted because the id ('canvas', 'ping_outlook')
didn't match any engine-skill Workflow id.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))


# ─── 1. bridge slot source-level pins (no Qt boot) ───────────────────


def _bridge_src() -> str:
    return (APP / "bridge.py").read_text(encoding="utf-8")


def test_delete_saved_skill_uses_scan_canvas_skills():
    """The fix MUST resolve via the same _scan_canvas_skills() table
    that get_saved_skills lists from — otherwise the id never matches."""
    src = _bridge_src()
    # Locate the slot body.
    m = re.search(r"def delete_saved_skill\(self, skill_id: str\)[\s\S]+?"
                  r"def clear_all_custom_nodes\b", src)
    assert m, "delete_saved_skill function not found"
    body = m.group(0)
    assert "_scan_canvas_skills" in body, (
        "delete_saved_skill must scan the canvas-skill store")
    # And explicitly NOT the engine-skill library delete_skill.
    assert "skills.library import delete_skill" not in body
    assert "from skills.library import delete_skill" not in body


def test_delete_saved_skill_tombstones_shipped_seeds():
    """AgDR-0033 — shipped seeds are tombstoned, not rejected."""
    src = _bridge_src()
    m = re.search(r"def delete_saved_skill\(self, skill_id: str\)[\s\S]+?"
                  r"def delete_custom_node\b", src)
    body = m.group(0)
    assert "_user_skills_dir" in body
    # AgDR-0033 — shipped seed → tombstone, not read_only reject.
    assert "_add_skill_tombstone" in body
    assert "read_only" not in body, (
        "AgDR-0033 retired the read_only rejection — shipped seeds "
        "must tombstone, not reject")


def test_delete_saved_skill_returns_typed_errors():
    src = _bridge_src()
    m = re.search(r"def delete_saved_skill\(self, skill_id: str\)[\s\S]+?"
                  r"def delete_custom_node\b", src)
    body = m.group(0)
    # Typed errors for the genuine failure paths (read_only removed).
    for code in ("not_found", "unlink_failed", "bad_args"):
        assert f'"{code}"' in body, f"missing typed error: {code}"


def test_clear_all_saved_skills_uses_canvas_store_too():
    src = _bridge_src()
    m = re.search(r"def clear_all_saved_skills\(self\)[\s\S]+?"
                  r"def ai_create_node\b", src)
    assert m, "clear_all_saved_skills function not found"
    body = m.group(0)
    assert "_scan_canvas_skills" in body
    assert "_user_skills_dir" in body
    # And must NOT call the wrong-store delete_skill.
    assert "from skills.library import delete_skill" not in body


# ─── 2. functional round-trip via the same helpers ──────────────────


def test_user_dir_skill_deletes(monkeypatch, tmp_path):
    """Drop a fake canvas-skill into the user dir, scan it, delete it,
    verify the file is gone."""
    import bridge
    # Stub _user_skills_dir + _shipped_skills_dir to point at tmp_path.
    user_dir = tmp_path / "user_skills"
    shipped_dir = tmp_path / "shipped_skills"
    user_dir.mkdir(); shipped_dir.mkdir()
    monkeypatch.setattr(bridge, "_user_skills_dir", lambda: user_dir)
    monkeypatch.setattr(bridge, "_shipped_skills_dir", lambda: shipped_dir)
    # Write a canvas skill.
    skill_file = user_dir / "delete_me.archhub-skill.json"
    skill_file.write_text(json.dumps({
        "name": "delete me",
        "slug": "delete_me",
        "graph": {"nodes": [], "wires": []},
        "meta": {"mode": "private"},
    }), encoding="utf-8")
    # Build a bridge instance.  Only need _scan_canvas_skills + the
    # static fields the delete slot touches — instantiate without args.
    inst = bridge.ArchHubBridge.__new__(bridge.ArchHubBridge)
    raw = inst.delete_saved_skill("delete_me")
    result = json.loads(raw)
    assert result.get("ok") is True, result
    assert not skill_file.exists()


def test_shipped_skill_tombstoned_not_rejected(monkeypatch, tmp_path):
    """AgDR-0033 — deleting a shipped seed tombstones its slug; the
    seed file stays on disk but disappears from the listing."""
    import bridge
    user_dir = tmp_path / "user_skills"
    shipped_dir = tmp_path / "shipped_skills"
    user_dir.mkdir(); shipped_dir.mkdir()
    monkeypatch.setattr(bridge, "_user_skills_dir", lambda: user_dir)
    monkeypatch.setattr(bridge, "_shipped_skills_dir", lambda: shipped_dir)
    seed = shipped_dir / "starter.archhub-skill.json"
    seed.write_text(json.dumps({
        "name": "starter", "slug": "starter",
        "graph": {"nodes": [], "wires": []},
    }), encoding="utf-8")
    inst = bridge.ArchHubBridge.__new__(bridge.ArchHubBridge)
    raw = inst.delete_saved_skill("starter")
    result = json.loads(raw)
    assert result.get("ok") is True
    assert result.get("method") == "tombstoned"
    # File untouched (app update would otherwise restore it anyway)…
    assert seed.exists()
    # …but it's filtered out of the listing.
    listed = [s["slug"] for s in bridge._scan_canvas_skills()]
    assert "starter" not in listed


def test_resaving_clears_tombstone(monkeypatch, tmp_path):
    """AgDR-0033 — a fresh save of a tombstoned slug un-hides it."""
    import bridge
    user_dir = tmp_path / "user_skills"
    shipped_dir = tmp_path / "shipped_skills"
    user_dir.mkdir(); shipped_dir.mkdir()
    monkeypatch.setattr(bridge, "_user_skills_dir", lambda: user_dir)
    monkeypatch.setattr(bridge, "_shipped_skills_dir", lambda: shipped_dir)
    bridge._add_skill_tombstone("revivme")
    assert "revivme" in bridge._load_skill_tombstones()
    bridge._clear_skill_tombstone("revivme")
    assert "revivme" not in bridge._load_skill_tombstones()


def test_missing_skill_returns_not_found(monkeypatch, tmp_path):
    import bridge
    monkeypatch.setattr(bridge, "_user_skills_dir", lambda: tmp_path / "u")
    monkeypatch.setattr(bridge, "_shipped_skills_dir", lambda: tmp_path / "s")
    (tmp_path / "u").mkdir(); (tmp_path / "s").mkdir()
    inst = bridge.ArchHubBridge.__new__(bridge.ArchHubBridge)
    raw = inst.delete_saved_skill("nonexistent")
    result = json.loads(raw)
    assert result.get("ok") is False
    assert result.get("error_code") == "not_found"


def test_empty_skill_id_returns_bad_args(monkeypatch, tmp_path):
    import bridge
    monkeypatch.setattr(bridge, "_user_skills_dir", lambda: tmp_path)
    inst = bridge.ArchHubBridge.__new__(bridge.ArchHubBridge)
    for sid in ("", "   ", None):
        raw = inst.delete_saved_skill(sid or "")
        result = json.loads(raw)
        assert result.get("ok") is False
        assert result.get("error_code") == "bad_args"


def test_clear_all_unlinks_user_tombstones_shipped(monkeypatch, tmp_path):
    """AgDR-0033 — clear-all empties the panel: user files unlinked,
    shipped seeds tombstoned.  The panel ends up empty."""
    import bridge
    user_dir = tmp_path / "u"; shipped_dir = tmp_path / "s"
    user_dir.mkdir(); shipped_dir.mkdir()
    monkeypatch.setattr(bridge, "_user_skills_dir", lambda: user_dir)
    monkeypatch.setattr(bridge, "_shipped_skills_dir", lambda: shipped_dir)
    (user_dir / "u1.archhub-skill.json").write_text(json.dumps({
        "name": "u1", "slug": "u1", "graph": {"nodes": [], "wires": []}}))
    (user_dir / "u2.archhub-skill.json").write_text(json.dumps({
        "name": "u2", "slug": "u2", "graph": {"nodes": [], "wires": []}}))
    (shipped_dir / "seed.archhub-skill.json").write_text(json.dumps({
        "name": "seed", "slug": "seed", "graph": {"nodes": [], "wires": []}}))
    inst = bridge.ArchHubBridge.__new__(bridge.ArchHubBridge)
    raw = inst.clear_all_saved_skills()
    result = json.loads(raw)
    assert result.get("ok") is True
    assert result.get("removed") == 3   # 2 user + 1 shipped
    # User files unlinked.
    assert not (user_dir / "u1.archhub-skill.json").exists()
    assert not (user_dir / "u2.archhub-skill.json").exists()
    # Shipped seed file survives on disk but is tombstoned.
    assert (shipped_dir / "seed.archhub-skill.json").exists()
    assert "seed" in bridge._load_skill_tombstones()
    # Panel list ends up empty.
    assert bridge._scan_canvas_skills() == []


# ─── 3. AgDR-0032 doc ────────────────────────────────────────────────


def test_agdr_0032_exists_and_approved():
    p = (Path(__file__).resolve().parents[1] / "docs" / "agdr"
         / "AgDR-0032-composer-stream-coalesce-and-delete-skill-fix.md")
    assert p.exists()
    text = p.read_text(encoding="utf-8")
    assert "status: approved" in text
    assert "_scan_canvas_skills" in text
    assert "bumpGraphRaf" in text
