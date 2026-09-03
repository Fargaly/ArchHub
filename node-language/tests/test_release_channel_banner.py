"""Behavioural tests for the PRODUCTION release-channel update path in the
QWebChannel bridge (founder 2026-06-11).

The bug these guard: the in-app "Update available -> Relaunch" banner did
NOTHING for installer users (people who ran the .exe — no git checkout, no
dev-source tree). Both halves of the banner used to fall to a dead 'none'/
blind-restart branch, so real multi-user installs (and the founder's own
install) NEVER saw an update. The fix routes installer users through the
EXISTING signed-GitHub-Releases path (`release_updater`).

Two observable contracts, each FAILS on the old code and PASSES on the fix:

1. DETECT — _refresh_updates_work, for an installer user (not a git checkout,
   no source root), populates `_update_status_cache` from
   `release_updater.has_update_available()` with kind=="release" (instead of
   the old {"available": False, "kind": "none"}). The latest tag is reported
   with its leading 'v' stripped.

2. APPLY — _apply_update_work, for an installer user, downloads the signed
   asset and runs the installer (which takes over + exits this process) and
   does NOT fall through to updater.restart() (which would restart the OLD,
   un-updated version).

No network: `release_updater`'s GitHub-hitting calls are monkeypatched, as are
the dev_source_sync install-detection helpers and updater.restart. The methods
import these modules LOCALLY by name, so patching the attribute on the module
object (resolved from sys.modules) is what the worker body sees.

Both workers only touch `self._update_status_cache` / `self._update_applying`
plus the module-level helpers, so an `object.__new__(ArchHubBridge)` instance
(skipping the heavy Qt __init__) is the smallest REAL call we can make — we set
only the attributes each method reads.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

# Match the suite convention: import app/* modules by bare name. (conftest also
# does this, but be self-sufficient if run in isolation.)
_APP = Path(__file__).resolve().parent.parent / "app"
if str(_APP) not in sys.path:
    sys.path.insert(0, str(_APP))

import bridge  # noqa: E402
import dev_source_sync  # noqa: E402
import release_updater  # noqa: E402
import updater  # noqa: E402


def _new_bridge():
    """A real ArchHubBridge with the heavy Qt __init__ skipped. The two update
    workers read no Qt state — only the two plain attributes set below.

    ArchHubBridge subclasses QObject (a C/Qt type), so `object.__new__(SubCls)`
    is refused ("not safe"); the type's own __new__ is the correct allocator for
    a no-__init__ instance."""
    inst = bridge.ArchHubBridge.__new__(bridge.ArchHubBridge)
    inst._update_status_cache = None
    inst._update_fetch_busy = True   # _refresh_updates_work clears this in finally
    inst._update_applying = True     # _apply_update_work toggles this off on no-op
    return inst


# ===========================================================================
# 1. DETECT — installer user's status poll uses the release channel
# ===========================================================================
def test_banner_detect_uses_release_for_installer_user(monkeypatch):
    """For an installer user (not a git checkout, no dev-source root),
    _refresh_updates_work must fill _update_status_cache from
    release_updater.has_update_available() with kind=='release' — the old code
    returned {"available": False, "kind": "none"} and the banner stayed dead."""
    # Installer user: neither a git checkout nor a discoverable source tree.
    monkeypatch.setattr(dev_source_sync, "is_git_checkout", lambda *_a, **_k: False)
    monkeypatch.setattr(dev_source_sync, "find_source_root", lambda *_a, **_k: None)

    # --- update IS available ---
    monkeypatch.setattr(
        release_updater, "has_update_available",
        lambda *_a, **_k: (True, SimpleNamespace(tag="v1.3.4", error=""), "1.3.3"),
    )

    inst = _new_bridge()
    bridge.ArchHubBridge._refresh_updates_work(inst)

    assert inst._update_status_cache == {
        "available": True,
        "current": "1.3.3",
        "latest": "1.3.4",   # leading 'v' stripped
        "kind": "release",
    }, inst._update_status_cache
    # The worker still clears its busy flag in finally.
    assert inst._update_fetch_busy is False

    # --- no update available: same channel, available False ---
    monkeypatch.setattr(
        release_updater, "has_update_available",
        lambda *_a, **_k: (False, SimpleNamespace(tag="v1.3.3", error=""), "1.3.3"),
    )

    inst2 = _new_bridge()
    bridge.ArchHubBridge._refresh_updates_work(inst2)

    assert inst2._update_status_cache.get("available") is False
    assert inst2._update_status_cache.get("kind") == "release"
    assert inst2._update_status_cache.get("latest") == "1.3.3"
    assert inst2._update_status_cache.get("current") == "1.3.3"


# ===========================================================================
# 2. APPLY — installer user downloads + runs the signed installer
# ===========================================================================
def test_banner_apply_runs_installer_for_installer_user(monkeypatch):
    """For an installer user, _apply_update_work must download the signed asset
    and run the installer (which exits this process) and must NOT fall through
    to updater.restart() — restarting would relaunch the OLD, un-updated
    version (founder 2026-06-11)."""
    # Installer user: not a git checkout, no dev-source root.
    monkeypatch.setattr(dev_source_sync, "is_git_checkout", lambda *_a, **_k: False)
    monkeypatch.setattr(dev_source_sync, "find_source_root", lambda *_a, **_k: None)

    info = SimpleNamespace(tag="v1.3.4", error="")
    monkeypatch.setattr(
        release_updater, "has_update_available",
        lambda *_a, **_k: (True, info, "1.3.3"),
    )

    calls: dict = {"download": [], "install": [], "restart": 0}

    fake_path = Path("C:/fake/ArchHub-Setup-1.3.4.exe")

    def _download_asset(release_info, *a, **k):
        calls["download"].append(release_info)
        return fake_path

    def _run_installer(path, *a, **k):
        # The real run_installer hands off to the installer and exits this
        # process. Record the call; do NOT actually exit (the worker `return`s
        # right after, which the production guard comment notes).
        calls["install"].append((path, a, k))

    def _restart():
        # If this ever fires for an installer user, the app would relaunch the
        # OLD version without applying the update — the exact bug.
        calls["restart"] += 1

    monkeypatch.setattr(release_updater, "download_asset", _download_asset)
    monkeypatch.setattr(release_updater, "run_installer", _run_installer)
    monkeypatch.setattr(updater, "restart", _restart)

    inst = _new_bridge()
    bridge.ArchHubBridge._apply_update_work(inst)

    # The signed-release apply path ran end to end.
    assert calls["download"] == [info], (
        "download_asset was not called with the release info — installer user "
        f"did not take the signed-release path. calls={calls!r}"
    )
    assert len(calls["install"]) == 1, (
        f"run_installer was not called exactly once. calls={calls!r}"
    )
    installed_path, _a, install_kwargs = calls["install"][0]
    assert installed_path == fake_path
    # The fix passes silent=True, relaunch=True so the installer takes over.
    assert install_kwargs.get("silent") is True
    assert install_kwargs.get("relaunch") is True

    # The crux: restart() must NOT run for an installer user (it would relaunch
    # the OLD version).
    assert calls["restart"] == 0, (
        "updater.restart() ran for an installer user — the banner would "
        "relaunch the OLD, un-updated version instead of applying the signed "
        "release"
    )
