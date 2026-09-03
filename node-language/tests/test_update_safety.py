"""Behavioural safety tests for the dev-source update path (founder 2026-06-11).

These guard the class of bug the founder hit as *"WTF DID YOU DO / data not
persistent"* and *"the app updates itself"*: the installed AppData copy
quietly re-arming auto-sync, applying updates at quit without opt-in, reverting
itself to an OLDER commit, or fast-forwarding the source tree on a mere status
poll. Each test imports the REAL functions and asserts an OBSERVABLE contract.

Contracts (each FAILS on the old buggy code, PASSES on the fixed code):

1. sync_source_to_install MUST NOT flip enable_dev_source_sync True
   (re-arming auto-sync was the deploy doom-loop).
2. apply_staged_update is OPT-IN: returns False + touches nothing unless
   settings has auto_apply_updates_on_quit == True.
3. needs_sync is FORWARD-ONLY: it never reports a sync that would revert the
   install to an OLDER (non-descendant) commit.
4. bridge.py's update-status poll worker (_refresh_updates_work) no longer
   fast-forwards the source tree (no pull_source_to_main in its body).
5. delete_saved_skill tombstones a user-override delete when a shipped twin of
   the same slug remains, so the seed cannot resurface.

No network. No real git except a tiny throwaway repo built with subprocess for
contract 3 (skipped when git is unavailable). The autouse conftest fixtures
isolate secrets_store / the brain daemon for every test here too.
"""
from __future__ import annotations

import inspect
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

# Match the suite convention: import app/* modules by bare name.
_APP = Path(__file__).resolve().parent.parent / "app"
if str(_APP) not in sys.path:
    sys.path.insert(0, str(_APP))

import dev_source_sync as dss  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_fake_source(root: Path) -> Path:
    """Minimal source checkout that satisfies sync_source_to_install's reads.

    A .git marker is NOT required for sync_source_to_install (it only copies the
    CODE_PATHS + TOP_LEVEL_FILES and stamps a marker) — find_source_root is the
    only function that demands .git, and these tests call sync directly.
    """
    (root / "app").mkdir(parents=True, exist_ok=True)
    (root / "app" / "main.py").write_text("print('hello from source')\n",
                                           encoding="utf-8")
    (root / "VERSION").write_text("9.9.9\n", encoding="utf-8")
    return root


def _git(repo: Path, *args: str) -> str:
    out = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True, timeout=30,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
    )
    if out.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)} failed ({out.returncode}): {out.stderr.strip()}"
        )
    return out.stdout.strip()


# ===========================================================================
# 1. sync must never re-arm auto-sync
# ===========================================================================
def test_sync_does_not_rearm_auto_sync(tmp_path):
    """A real source->install copy MUST leave enable_dev_source_sync exactly as
    the user left it (False) and MUST NOT plant a dev_source_path. Re-writing
    those on every sync was the doom-loop that re-enabled auto-update after each
    deploy (founder 2026-06-11)."""
    source = _make_fake_source(tmp_path / "src")
    install = tmp_path / "install"
    install.mkdir(parents=True, exist_ok=True)

    settings_path = install / dss.SETTINGS_FILE
    settings_path.write_text(json.dumps({"enable_dev_source_sync": False}),
                             encoding="utf-8")

    stamp = dss.source_stamp(source)
    dss.sync_source_to_install(source, install, stamp)

    after = json.loads(settings_path.read_text(encoding="utf-8"))
    # The toggle the user set to False must STILL be False after a sync.
    assert after.get("enable_dev_source_sync") is False, (
        "sync_source_to_install re-armed enable_dev_source_sync — the deploy "
        f"doom-loop regressed. settings now: {after!r}"
    )
    # And sync must not plant a source path that would feed the next auto-sync.
    assert "dev_source_path" not in after, (
        f"sync_source_to_install planted dev_source_path={after.get('dev_source_path')!r}; "
        "the source path is owned solely by an explicit user action."
    )
    # Sanity: the sync really ran (marker + copied file landed).
    assert (install / dss.SYNC_MARKER).exists()
    assert (install / "app" / "main.py").exists()


# ===========================================================================
# 2. quit-apply is opt-in
# ===========================================================================
def test_quit_apply_is_opt_in(tmp_path, monkeypatch):
    """apply_staged_update must do NOTHING (return False, never sync) unless the
    user opted in with auto_apply_updates_on_quit. When opted in, the gate is
    passed and needs_sync IS consulted."""
    install = tmp_path / "install"
    install.mkdir(parents=True, exist_ok=True)
    fake_source = tmp_path / "src"
    fake_source.mkdir(parents=True, exist_ok=True)

    # Neutralise the install-detection + source-discovery guards so the test
    # exercises ONLY the opt-in gate, not the surrounding environment.
    monkeypatch.setattr(dss, "is_git_checkout", lambda root: False)
    monkeypatch.setattr(dss, "find_source_root", lambda install_root: fake_source)

    # Sentinel: any call to sync is a failure in the OFF case.
    sync_calls: list = []
    monkeypatch.setattr(
        dss, "sync_source_to_install",
        lambda *a, **k: sync_calls.append((a, k)),
    )
    # Record whether needs_sync is consulted, and stop the flow cleanly.
    needs_sync_calls: list = []

    def _needs_sync(source_root, install_root):
        needs_sync_calls.append((source_root, install_root))
        return False, {}

    monkeypatch.setattr(dss, "needs_sync", _needs_sync)

    # --- OFF (key absent) -> no-op, gate stops BEFORE needs_sync/sync ---
    settings_path = install / dss.SETTINGS_FILE
    settings_path.write_text(json.dumps({}), encoding="utf-8")
    assert dss.apply_staged_update(install) is False
    assert sync_calls == [], "quit-apply synced while opt-in was OFF (key absent)"
    assert needs_sync_calls == [], (
        "quit-apply consulted needs_sync before the opt-in gate — the gate must "
        "short-circuit first"
    )

    # --- OFF (explicit False) -> still a no-op ---
    settings_path.write_text(json.dumps({"auto_apply_updates_on_quit": False}),
                             encoding="utf-8")
    assert dss.apply_staged_update(install) is False
    assert sync_calls == [], "quit-apply synced while opt-in was explicitly False"
    assert needs_sync_calls == []

    # --- ON -> gate passes, needs_sync consulted; (False,{}) stops cleanly ---
    settings_path.write_text(json.dumps({"auto_apply_updates_on_quit": True}),
                             encoding="utf-8")
    result = dss.apply_staged_update(install)
    assert needs_sync_calls, (
        "opt-in was ON but apply_staged_update never consulted needs_sync — the "
        "gate did not pass"
    )
    # needs_sync returned (False, {}) so nothing was applied and no sync ran.
    assert result is False
    assert sync_calls == [], (
        "sync ran even though the stubbed needs_sync reported nothing to do"
    )


# ===========================================================================
# 3. forward-only: never revert the install to an older commit
# ===========================================================================
def test_forward_only_skips_older_source(tmp_path):
    """needs_sync must refuse to 'update' the install to a source commit that is
    BEHIND (not a descendant of) the installed commit — that would silently
    revert the user's app to older code."""
    if not shutil.which("git"):
        pytest.skip("git not available — forward-only contract needs a real repo")

    source = tmp_path / "src"
    source.mkdir(parents=True, exist_ok=True)
    _git(source, "init", "-q", "-b", "main")
    _git(source, "config", "user.email", "test@example.com")
    _git(source, "config", "user.name", "Test")
    # core.autocrlf off so file bytes (hence stamps) are deterministic here.
    _git(source, "config", "core.autocrlf", "false")

    (source / "app").mkdir(parents=True, exist_ok=True)
    (source / "VERSION").write_text("1.0.0\n", encoding="utf-8")

    (source / "app" / "main.py").write_text("print('c1')\n", encoding="utf-8")
    _git(source, "add", "-A")
    _git(source, "commit", "-qm", "c1")
    c1 = _git(source, "rev-parse", "--short", "HEAD")

    (source / "app" / "main.py").write_text("print('c2')\n", encoding="utf-8")
    _git(source, "add", "-A")
    _git(source, "commit", "-qm", "c2")
    c2 = _git(source, "rev-parse", "--short", "HEAD")
    assert c1 != c2

    install = tmp_path / "install"
    install.mkdir(parents=True, exist_ok=True)

    # Sync the install to C2 (source currently at C2). This writes a REAL marker
    # whose source_stamp.commit == short C2.
    stamp_c2 = dss.source_stamp(source)
    assert stamp_c2.get("commit") == c2
    dss.sync_source_to_install(source, install, stamp_c2)
    marker = dss._read_json(install / dss.SYNC_MARKER)
    assert (marker.get("source_stamp") or {}).get("commit") == c2

    # Now move the SOURCE checkout BACK to C1 (older). An "update" here would be
    # a revert — needs_sync must say no.
    _git(source, "checkout", "-q", c1)
    assert dss.source_commit(source) == c1
    should_sync, _stamp = dss.needs_sync(source, install)
    assert should_sync is False, (
        f"needs_sync wanted to revert the install from {c2} back to older {c1} "
        "— forward-only guard failed"
    )

    # Advance the source to a NEW descendant C3 (strictly forward of C2): now a
    # sync IS legitimate and needs_sync must say yes.
    _git(source, "checkout", "-q", "main")  # back to C2 (branch tip)
    (source / "app" / "main.py").write_text("print('c3')\n", encoding="utf-8")
    _git(source, "add", "-A")
    _git(source, "commit", "-qm", "c3")
    c3 = _git(source, "rev-parse", "--short", "HEAD")
    assert c3 not in (c1, c2)
    should_sync2, _stamp2 = dss.needs_sync(source, install)
    assert should_sync2 is True, (
        f"needs_sync refused a legitimate forward update {c2} -> descendant {c3}"
    )


# ===========================================================================
# 4. the status poll must not fast-forward the source tree
# ===========================================================================
def test_status_poll_does_not_ffmerge():
    """Source inspection guard: bridge.py's update-status worker
    (_refresh_updates_work) must NOT call dss.pull_source_to_main — advancing
    the source tree is user-initiated only. A silent ff on a mere status poll
    was a root cause of 'the app updates itself' (founder 2026-06-11).

    We scope strictly to the worker's own body (def _refresh_updates_work up to
    the next top-level `def`) so the legitimate call in the separate
    _apply_update_work (the user's Relaunch button) does not mask a regression
    here.
    """
    bridge_src = (Path(__file__).resolve().parent.parent
                  / "app" / "bridge.py").read_text(encoding="utf-8")

    lines = bridge_src.splitlines()
    start = None
    for i, line in enumerate(lines):
        if line.lstrip().startswith("def _refresh_updates_work"):
            start = i
            break
    assert start is not None, "could not find _refresh_updates_work in bridge.py"

    def_indent = len(lines[start]) - len(lines[start].lstrip())
    end = len(lines)
    for j in range(start + 1, len(lines)):
        stripped = lines[j].strip()
        if not stripped:
            continue
        indent = len(lines[j]) - len(lines[j].lstrip())
        # Next sibling/outer `def` (or class) at <= the worker's indent ends it.
        if indent <= def_indent and (stripped.startswith("def ")
                                     or stripped.startswith("@")
                                     or stripped.startswith("class ")):
            end = j
            break

    body = "\n".join(lines[start:end])
    assert "pull_source_to_main" not in body, (
        "_refresh_updates_work calls pull_source_to_main — the status poll is "
        "fast-forwarding the source tree again (silent self-update regression)"
    )
    # Belt-and-braces: the worker still detects updates via a read-only fetch.
    assert "fetch" in body, (
        "status worker no longer fetches refs — update detection would go stale"
    )


# ===========================================================================
# 5. deleting a user-override skill tombstones a remaining shipped twin
# ===========================================================================
def test_delete_user_skill_tombstones_shipped_twin(tmp_path, monkeypatch):
    """When the user deletes a skill whose slug ALSO exists as a shipped seed,
    a plain unlink of the user file would let the shipped twin resurface (the
    dedup-by-slug reveals it). The fix tombstones the slug so it stays hidden.

    This calls the REAL delete_saved_skill slot. The slot only touches `self`
    for a fire-and-forget `self.skills_changed.emit()` (wrapped in try/except),
    so a lightweight stand-in object exercises the real delete logic without
    constructing a full Qt Bridge. Everything load-bearing is module-level
    helpers (_scan_canvas_skills / _add_skill_tombstone / _user_skills_dir /
    _shipped_skills_dir), which we point at tmp_path dirs.
    """
    import bridge

    shipped_dir = tmp_path / "shipped"
    user_dir = tmp_path / "user"
    shipped_dir.mkdir(parents=True, exist_ok=True)
    user_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(bridge, "_shipped_skills_dir", lambda: shipped_dir)
    monkeypatch.setattr(bridge, "_user_skills_dir", lambda: user_dir)

    slug = "myskill"
    seed = {
        "slug": slug,
        "name": "My Skill",
        "graph": {"nodes": [], "wires": []},
        "meta": {"mode": "private"},
    }
    # Shipped seed + a user OVERRIDE of the same slug (distinct content).
    (shipped_dir / f"{slug}.archhub-skill.json").write_text(
        json.dumps(seed), encoding="utf-8")
    user_override = dict(seed, name="My Skill (mine)")
    (user_dir / f"{slug}.archhub-skill.json").write_text(
        json.dumps(user_override), encoding="utf-8")

    # Precondition: the slug is visible exactly once (deduped, user wins).
    pre = [s for s in bridge._scan_canvas_skills() if s.get("slug") == slug]
    assert len(pre) == 1
    assert pre[0]["name"] == "My Skill (mine)", "user override should win the dedup"
    assert bridge._load_skill_tombstones() == set()

    # Call the REAL slot with a minimal stand-in for `self`.
    fake_self = SimpleNamespace(
        skills_changed=SimpleNamespace(emit=lambda *a, **k: None)
    )
    raw = bridge.ArchHubBridge.delete_saved_skill(fake_self, slug)
    res = json.loads(raw)

    assert res.get("ok") is True, f"delete failed: {res!r}"
    # The user file is gone, but because a shipped twin remains the delete must
    # escalate to a tombstone (not a bare unlink) so it can't resurface.
    assert res.get("method") == "tombstoned", (
        "deleting a user override with a shipped twin must tombstone the slug "
        f"so the seed can't resurface, got method={res.get('method')!r}"
    )
    assert not (user_dir / f"{slug}.archhub-skill.json").exists(), (
        "the user-store override should have been unlinked"
    )
    # The two observable guards the contract names:
    assert slug in bridge._load_skill_tombstones(), (
        "slug missing from tombstones after deleting a shipped twin"
    )
    assert all(s.get("slug") != slug for s in bridge._scan_canvas_skills()), (
        "the shipped twin resurfaced after delete — tombstone not applied/filtered"
    )
