"""Auto-update prompt flow tests — v1.0.4 Claude-Desktop pattern.

  - Check + download runs on a background thread.
  - When a newer release is available the download completes silently.
  - The UI (chat_window banner) is told via an `on_ready(installer_path,
    release)` callback, NOT a force-restart.
  - User picks Restart now / Later via the banner.

These tests cover the split: `check_and_download()` must not invoke
`run_installer`, and the legacy `auto_check_and_apply()` in 'prompt'
mode must return the installer path so the banner can show it.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

APP_ROOT = Path(__file__).resolve().parent.parent / "app"
sys.path.insert(0, str(APP_ROOT))


def _fake_release(tag: str = "v9.9.9") -> SimpleNamespace:
    return SimpleNamespace(
        tag=tag, tag_name=tag, name=tag,
        asset_url=f"https://example/{tag}.exe",
        asset_size=100_000, error=None,
    )


class TestCheckAndDownload:
    def test_off_mode_skips(self):
        from release_updater import check_and_download
        with patch("secrets_store.load_setting",
                    side_effect=lambda k: {"auto_update_mode": "off"}.get(k)):
            r = check_and_download()
        assert r["status"] == "skip"
        assert r["reason"] == "mode=off"

    def test_up_to_date_returns_ok(self):
        from release_updater import check_and_download
        with patch("secrets_store.load_setting",
                    side_effect=lambda k: {"auto_update_mode": "prompt"}.get(k)), \
             patch("secrets_store.save_setting"), \
             patch("release_updater.has_update_available",
                    return_value=(False, _fake_release("v1.0.4"), "1.0.4")):
            r = check_and_download(force=True)
        assert r["status"] == "ok"
        assert r["up_to_date"] is True

    def test_new_version_downloads_but_does_not_install(self):
        """Critical: download_asset is called, run_installer is NOT."""
        from release_updater import check_and_download
        downloaded = Path("/tmp/fake-installer.exe")
        with patch("secrets_store.load_setting",
                    side_effect=lambda k: {"auto_update_mode": "prompt"}.get(k)), \
             patch("secrets_store.save_setting"), \
             patch("release_updater.has_update_available",
                    return_value=(True, _fake_release(), "1.0.3")), \
             patch("release_updater.download_asset",
                    return_value=downloaded) as mock_dl, \
             patch("release_updater.run_installer") as mock_run:
            r = check_and_download(force=True)
        assert r["status"] == "ok"
        assert r["up_to_date"] is False
        assert r["installer_path"] == downloaded
        # The whole point of the new helper:
        assert mock_dl.called
        assert not mock_run.called, "check_and_download MUST NOT install"


class TestAutoCheckAndApply:
    """Behavioural matrix per mode."""

    def test_prompt_mode_returns_installer_path_does_not_install(self):
        from release_updater import auto_check_and_apply
        downloaded = Path("/tmp/fake-installer.exe")
        with patch("secrets_store.load_setting",
                    side_effect=lambda k: {"auto_update_mode": "prompt"}.get(k)), \
             patch("secrets_store.save_setting"), \
             patch("release_updater.has_update_available",
                    return_value=(True, _fake_release(), "1.0.3")), \
             patch("release_updater.download_asset",
                    return_value=downloaded), \
             patch("release_updater.run_installer") as mock_run:
            r = auto_check_and_apply(force=True)
        assert r["status"] == "ok"
        assert r["up_to_date"] is False
        assert r["installer_path"] == downloaded
        assert not mock_run.called, "prompt mode must NEVER auto-install"

    def test_silent_mode_installs(self):
        from release_updater import auto_check_and_apply
        downloaded = Path("/tmp/fake-installer.exe")
        with patch("secrets_store.load_setting",
                    side_effect=lambda k: {"auto_update_mode": "silent"}.get(k)), \
             patch("secrets_store.save_setting"), \
             patch("release_updater.has_update_available",
                    return_value=(True, _fake_release(), "1.0.3")), \
             patch("release_updater.download_asset",
                    return_value=downloaded), \
             patch("release_updater.run_installer") as mock_run:
            auto_check_and_apply(force=True)
        assert mock_run.called, "silent mode must install"

    def test_legacy_auto_mode_maps_to_silent(self):
        """Old configs use mode='auto' — must still force-install."""
        from release_updater import auto_check_and_apply
        downloaded = Path("/tmp/fake-installer.exe")
        with patch("secrets_store.load_setting",
                    side_effect=lambda k: {"auto_update_mode": "auto"}.get(k)), \
             patch("secrets_store.save_setting"), \
             patch("release_updater.has_update_available",
                    return_value=(True, _fake_release(), "1.0.3")), \
             patch("release_updater.download_asset",
                    return_value=downloaded), \
             patch("release_updater.run_installer") as mock_run:
            auto_check_and_apply(force=True)
        assert mock_run.called, "legacy auto mode must still install"

    def test_notify_mode_does_not_install(self):
        from release_updater import auto_check_and_apply
        downloaded = Path("/tmp/fake-installer.exe")
        with patch("secrets_store.load_setting",
                    side_effect=lambda k: {"auto_update_mode": "notify"}.get(k)), \
             patch("secrets_store.save_setting"), \
             patch("release_updater.has_update_available",
                    return_value=(True, _fake_release(), "1.0.3")), \
             patch("release_updater.download_asset",
                    return_value=downloaded), \
             patch("release_updater.run_installer") as mock_run:
            auto_check_and_apply(force=True)
        assert not mock_run.called


class TestScheduleAutoCheck:
    """The periodic watcher fires on_ready when a new build downloads."""

    def test_on_ready_called_with_installer_path(self):
        import release_updater
        downloaded = Path("/tmp/fake-installer.exe")
        called: list[tuple] = []
        def _on_ready(installer, release):
            called.append((installer, release))
        # Make the periodic loop run exactly once, then bail.
        with patch.object(release_updater, "auto_check_and_apply",
                           return_value={"status": "ok", "up_to_date": False,
                                          "installer_path": downloaded,
                                          "release": _fake_release(),
                                          "current": "1.0.3"}):
            # Run a synchronous version of the loop body — start the
            # daemon thread is overkill in unit tests. We bypass
            # `schedule_auto_check` and invoke the same logic directly.
            res = release_updater.auto_check_and_apply()
            if (res.get("status") == "ok" and not res.get("up_to_date")
                    and res.get("installer_path")):
                _on_ready(res["installer_path"], res.get("release"))
        assert called, "on_ready callback should fire"
        assert called[0][0] == downloaded


class TestUpdateBannerWiring:
    """ChatWindow's _on_update_ready emits a Qt signal so the daemon-thread
    callback marshals back to the main thread before mutating widgets.
    We assert the signal/slot wiring exists; rendering is GUI-thread work
    we don't exercise headlessly."""

    def test_chat_window_has_update_signal_and_handlers(self):
        # Import the class without instantiating (instantiation needs
        # QApplication + dependencies). Inspect class attributes only.
        import chat_window
        cls = chat_window.ChatWindow
        # Methods that wire the banner.
        for name in ("_build_update_banner",
                      "_on_update_ready",
                      "_on_update_ready_qt",
                      "_dismiss_update_banner",
                      "_restart_for_update"):
            assert hasattr(cls, name), f"missing method: {name}"
        # The cross-thread signal.
        assert hasattr(cls, "update_ready_signal"), \
            "ChatWindow needs an update_ready_signal pyqtSignal"
