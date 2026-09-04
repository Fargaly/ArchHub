"""Quiet update: stage only a newer, SHA-verified build; apply only at launch; never guess."""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path

from nodelang import quiet_update as qu


class _Resp(io.BytesIO):
    def __enter__(self): return self
    def __exit__(self, *exc): return False


def _opener(release: dict, asset: bytes):
    def opener(request, timeout=0):
        url = request.full_url if hasattr(request, "full_url") else str(request)
        if url == qu.RELEASE_API:
            return _Resp(json.dumps(release).encode("utf-8"))
        return _Resp(asset)
    return opener


def _release(build_id: str, asset: bytes, sha: str | None = None):
    sha = sha or hashlib.sha256(asset).hexdigest()
    return {"tag_name": "v0", "body": "Open beta.\nBUILD_ID: %s\nSHA256 %s: %s (%d bytes)" % (build_id, qu.ASSET_NAME, sha, len(asset)),
            "assets": [{"name": qu.ASSET_NAME, "browser_download_url": "https://example.invalid/setup.exe"}]}


def test_same_build_is_not_staged(tmp_path):
    app = tmp_path / "app"; app.mkdir(); (app / "BUILD_ID").write_text("20260904-1000", encoding="utf-8")
    out = qu.stage_if_newer(tmp_path / "state", app, opener=_opener(_release("20260904-1000", b"setup"), b"setup"))
    assert out == {"staged": False, "reason": "up to date", "build_id": "20260904-1000"}
    assert not (tmp_path / "state" / "updates").exists()


def test_newer_build_is_downloaded_verified_and_staged_not_applied(tmp_path):
    app = tmp_path / "app"; app.mkdir(); (app / "BUILD_ID").write_text("20260904-1000", encoding="utf-8")
    asset = b"new-setup-bytes"
    out = qu.stage_if_newer(tmp_path / "state", app, opener=_opener(_release("20260904-1200", asset), asset))
    assert out["staged"] and out["build_id"] == "20260904-1200"
    staged = tmp_path / "state" / "updates" / qu.ASSET_NAME
    assert staged.read_bytes() == asset
    assert (app / "BUILD_ID").read_text(encoding="utf-8") == "20260904-1000", "staging never installs"


def test_a_download_that_does_not_match_the_published_sha_is_refused(tmp_path):
    app = tmp_path / "app"; app.mkdir(); (app / "BUILD_ID").write_text("a", encoding="utf-8")
    out = qu.stage_if_newer(tmp_path / "state", app, opener=_opener(_release("b", b"good", sha="0" * 64), b"tampered"))
    assert out["staged"] is False and "SHA-256" in out["reason"]
    assert not (tmp_path / "state" / "updates" / qu.ASSET_NAME).exists()


def test_apply_runs_the_staged_installer_silently_and_clears_it(tmp_path):
    app = tmp_path / "app"; app.mkdir(); (app / "BUILD_ID").write_text("old", encoding="utf-8")
    updates = tmp_path / "state" / "updates"; updates.mkdir(parents=True)
    asset = b"setup"; (updates / qu.ASSET_NAME).write_bytes(asset)
    (updates / "staged.json").write_text(json.dumps({"build_id": "new", "sha256": hashlib.sha256(asset).hexdigest()}), encoding="utf-8")
    calls = []
    class _Done:
        returncode = 0
    def runner(argv, timeout=0):
        calls.append(argv); (app / "BUILD_ID").write_text("new", encoding="utf-8"); return _Done()
    out = qu.apply_staged(tmp_path / "state", app, runner=runner)
    assert out["applied"] and out["build_id"] == "new"
    assert calls and calls[0][1:] == ["/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/DIR=" + str(app)]
    assert not (updates / qu.ASSET_NAME).exists() and not (updates / "staged.json").exists()


def test_apply_refuses_a_staged_file_that_changed_on_disk(tmp_path):
    app = tmp_path / "app"; app.mkdir(); (app / "BUILD_ID").write_text("old", encoding="utf-8")
    updates = tmp_path / "state" / "updates"; updates.mkdir(parents=True)
    (updates / qu.ASSET_NAME).write_bytes(b"changed"); (updates / "staged.json").write_text(json.dumps({"build_id": "new", "sha256": "0" * 64}), encoding="utf-8")
    out = qu.apply_staged(tmp_path / "state", app, runner=lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not run")))
    assert out["applied"] is False and "SHA-256" in out["reason"]


def test_baboom_offers_restart_when_a_build_is_staged():
    import inspect
    import nodelang.universal_application as ua
    src = inspect.getsource(ua.project_universal_baboom_companion_directive)
    assert '"update-ready"' in src and '"restart-to-update"' in src and '"Restart now"' in src
    # The directive must FORWARD the staged build into the lens, or the branch is dead code.
    assert "staged_update=staged_update," in src
    lens = inspect.getsource(ua.project_universal_baboom_context)
    assert '"update":' in lens and "staged_update" in lens
    responder = inspect.getsource(ua.respond_universal_baboom_utterance)
    assert 'intent == "restart-to-update"' in responder and '"update-none"' in responder
    assert any(spec[0] == "restart-to-update" for spec in ua._BABOOM_COMMAND_SPECS)


def test_the_server_hands_over_to_a_fresh_launcher_on_restart():
    import inspect
    import nodelang.application_server as srv
    src = inspect.getsource(srv)
    assert "def _staged_update(self)" in src and "def _restart_to_update(self)" in src
    assert src.count("staged_update=self._staged_update()") >= 5
    assert 'result.get("kind") == "update-ready"' in src


def test_the_app_lives_in_the_tray_and_closing_hides_it():
    """The founder asked where the app is: a tray icon says it is running in the
    background; close hides; Quit and Restart-to-update live in the tray menu."""
    src = (Path(__file__).resolve().parents[1] / "launch_archhub_test.py").read_text(encoding="utf-8")
    assert "QSystemTrayIcon" in src and "class _ArchHubWindow(QMainWindow)" in src
    assert "event.ignore()" in src and "self.hide()" in src
    for label in ("Open ArchHub", "Check for updates now", "Restart to install the update", "Quit ArchHub"):
        assert label in src, label
    assert 'window.setWindowTitle("ArchHub")' in src
    assert "app.setQuitOnLastWindowClosed(False)" in src
