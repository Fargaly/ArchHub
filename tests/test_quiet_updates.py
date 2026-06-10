"""QUIET-UPDATE MODEL pins (founder 2026-06-10 — "UI BUGS & INITIATION PROCESS
REPEATS WITH EVERY LAUNCH... THAT'S NOT ACCEPTABLE").

Root cause of the repeat: the launch path auto-sync-RELAUNCHED whenever main
had moved, so with an active merge cadence every launch was a double-boot
("the app re-initiates every time"). Root cause of the UI bugs: QtWebEngine's
persistent cache could serve a stale-but-CONSISTENT .jsx/.compiled.js pair
after a sync swapped them on disk — the previous UI painting against the new
Python bridge.

The model now (Chrome/VS-Code): a normal launch boots INSTANTLY on the code on
disk — no sync, no self-relaunch, no supersede-quit of a running instance.
Updates land quietly via (a) the in-app banner when the USER clicks "Relaunch
to update", and (b) `apply_staged_update` in the shutdown tail — files sync at
exit so the NEXT launch is already current. The loader cache-busts its fetches
so a fresh boot can never paint a stale bundle.

These tests pin both halves: the functional quit-apply, and the wiring (the
interrupting paths must stay retired).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent.parent / "app"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


# ── functional: apply_staged_update ──────────────────────────────────────

def _fixture(tmp_path: Path) -> tuple[Path, Path]:
    source = tmp_path / "source"
    install = tmp_path / "install"
    (source / ".git").mkdir(parents=True)
    _write(source / "VERSION", "9.9.9")
    _write(source / "app" / "main.py", "print('new main')\n")
    _write(source / "app" / "studio_shell.py", "NEW_UI = True\n")
    _write(source / "payload" / "bridge" / "server.py", "BRIDGE = True\n")
    _write(install / "settings.json", json.dumps({
        "enable_dev_source_sync": True,
        "dev_source_path": str(source),
    }))
    _write(install / "app" / "studio_shell.py", "OLD_UI = True\n")
    return source, install


def test_apply_staged_update_syncs_files_quietly(tmp_path):
    import dev_source_sync

    source, install = _fixture(tmp_path)
    applied = dev_source_sync.apply_staged_update(install)
    assert applied is True
    assert (install / "app" / "studio_shell.py").read_text(
        encoding="utf-8") == "NEW_UI = True\n"
    # marker written → a second quit-apply is a no-op (idempotent)
    assert dev_source_sync.apply_staged_update(install) is False


def test_apply_staged_update_never_touches_a_git_checkout(tmp_path):
    import dev_source_sync

    source, install = _fixture(tmp_path)
    (install / ".git").mkdir()   # dev checkout — must never self-sync
    assert dev_source_sync.apply_staged_update(install) is False
    assert (install / "app" / "studio_shell.py").read_text(
        encoding="utf-8") == "OLD_UI = True\n"


def test_apply_staged_update_no_configured_source(tmp_path):
    import dev_source_sync

    install = tmp_path / "install"
    _write(install / "settings.json", json.dumps({}))
    assert dev_source_sync.apply_staged_update(install) is False


# ── wiring pins: the interrupting paths stay retired ─────────────────────

def _main_src() -> str:
    return (APP_ROOT / "main.py").read_text(encoding="utf-8")


def test_launch_path_never_sync_relaunches():
    """A normal launch must not call maybe_sync_and_relaunch — that call was
    the every-launch double-boot. (The library function itself remains for the
    banner's apply path + tests.)"""
    src = _main_src()
    assert "maybe_sync_and_relaunch" not in src, (
        "launch-time sync+relaunch is back — the every-launch 'initiation' "
        "double-boot returns with it")


def test_shutdown_tail_applies_staged_update():
    src = _main_src()
    assert "apply_staged_update" in src, (
        "quit-apply missing — updates would only land via the banner")


def test_supersede_gate_is_closed():
    """A second launch must summon the running window, never quit it to load
    new code (the interrupting supersede is retired with the launch sync)."""
    src = _main_src()
    i = src.find("def _should_supersede")
    assert i != -1
    body = src[i:i + 700]
    assert "return False" in body and "has_new_source" not in body, (
        "_should_supersede re-opened — a second launch can kill the running "
        "instance again")


def test_jsx_boot_cache_busts_its_fetches():
    """The loader must cache-bust .jsx/.compiled.js fetches — a stale-but-
    consistent cached pair passes sha pairing and paints the previous UI
    against the new bridge (the founder's 'UI bugs')."""
    boot = (APP_ROOT / "web_ui" / "jsx-boot.js").read_text(encoding="utf-8")
    assert "Date.now()" in boot and "bust" in boot, (
        "jsx-boot no longer cache-busts — stale-bundle first paint returns")
