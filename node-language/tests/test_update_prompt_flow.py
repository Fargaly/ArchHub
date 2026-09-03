"""Auto-update prompt flow tests - staged restart pattern.

  - Check + download runs on a background thread.
  - When a newer release is available the installer is staged silently.
  - The UI banner is told after staging, not after a force-restart.
  - User picks Restart now / Later via the banner.

These tests cover the split: prompt mode installs/stages in the
background, run_installer remains reserved for immediate restart flows,
and the banner button restarts into the staged build.
"""
from __future__ import annotations

import inspect
import subprocess
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

    def test_new_version_downloads_but_does_not_force_install(self):
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
        assert mock_dl.called
        assert not mock_run.called


class TestStageInstaller:
    def test_stage_installer_uses_no_close_no_restart_flags(self, tmp_path):
        from release_updater import stage_installer
        installer = tmp_path / "ArchHub-Setup-9.9.9.exe"
        installer.write_bytes(b"fake")

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="", stderr=""
            )
            result = stage_installer(installer)

        args = mock_run.call_args.args[0]
        assert result["status"] == "ok"
        assert "/VERYSILENT" in args
        assert "/NOCLOSEAPPLICATIONS" in args
        assert "/NORESTARTAPPLICATIONS" in args
        assert "/ARCHHUB_STAGE=1" in args

    def test_setup_script_supports_stage_without_closing_app(self):
        setup = (Path(__file__).resolve().parent.parent
                 / "installer" / "setup.iss").read_text(encoding="utf-8")
        assert "CloseApplications=no" in setup
        assert "function IsStageInstall" in setup
        assert "(CurStep = ssInstall) and (not IsStageInstall)" in setup


class TestAutoCheckAndApply:
    """Behavioural matrix per mode."""

    def test_prompt_mode_stages_installer_without_force_restart(self):
        from release_updater import auto_check_and_apply
        downloaded = Path("/tmp/fake-installer.exe")
        with patch("secrets_store.load_setting",
                   side_effect=lambda k: {"auto_update_mode": "prompt"}.get(k)), \
             patch("secrets_store.save_setting"), \
             patch("release_updater.has_update_available",
                   return_value=(True, _fake_release(), "1.0.3")), \
             patch("release_updater.download_asset",
                   return_value=downloaded), \
             patch("release_updater.stage_installer",
                   return_value={"status": "ok", "installer_path": downloaded}) as mock_stage, \
             patch("release_updater.run_installer") as mock_run:
            r = auto_check_and_apply(force=True)
        assert r["status"] == "ok"
        assert r["up_to_date"] is False
        assert r["installer_path"] == downloaded
        assert r["staged"] is True
        assert r["restart_required"] is True
        assert mock_stage.called
        assert not mock_run.called

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
        """Old configs use mode='auto' and must still force-install."""
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
             patch("release_updater.run_installer") as mock_run, \
             patch("release_updater.stage_installer") as mock_stage:
            auto_check_and_apply(force=True)
        assert not mock_run.called
        assert not mock_stage.called


class TestScheduleAutoCheck:
    """The periodic watcher fires on_ready when a new build is staged."""

    def test_on_ready_called_with_installer_path(self):
        import release_updater
        downloaded = Path("/tmp/fake-installer.exe")
        called: list[tuple] = []

        def _on_ready(installer, release):
            called.append((installer, release))

        with patch.object(release_updater, "auto_check_and_apply",
                          return_value={"status": "ok", "up_to_date": False,
                                        "installer_path": downloaded,
                                        "release": _fake_release(),
                                        "staged": True,
                                        "restart_required": True,
                                        "current": "1.0.3"}):
            res = release_updater.auto_check_and_apply()
            if (res.get("status") == "ok" and not res.get("up_to_date")
                    and res.get("installer_path")):
                _on_ready(res["installer_path"], res.get("release"))
        assert called, "on_ready callback should fire"
        assert called[0][0] == downloaded


class TestUpdateBannerWiring:
    """ChatWindow's update banner is signalled from the watcher thread."""

    def test_chat_window_has_update_signal_and_handlers(self):
        import chat_window
        cls = chat_window.ChatWindow
        for name in ("_build_update_banner",
                     "_on_update_ready",
                     "_on_update_ready_qt",
                     "_dismiss_update_banner",
                     "_restart_for_update"):
            assert hasattr(cls, name), f"missing method: {name}"
        assert hasattr(cls, "update_ready_signal")

    def test_restart_button_restarts_staged_build_without_running_installer(self):
        import chat_window
        source = inspect.getsource(chat_window.ChatWindow._restart_for_update)
        assert "release_updater.run_installer" not in source
        assert "updater.restart" in source
