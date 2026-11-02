"""Quiet update: stage only a newer, SHA-verified build; apply only at launch; never guess."""
from __future__ import annotations

import ast
import runpy
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
    return {"tag_name": "v0", "body": "Open beta.\nBUILD_ID: %s\nBUILT_AT: 2026-09-04T12:00:00Z\nSHA256 %s: %s (%d bytes)" % (build_id, qu.ASSET_NAME, sha, len(asset)),
            "assets": [{"name": qu.ASSET_NAME, "browser_download_url": "https://github.com/Fargaly/ArchHub/releases/download/v0/" + qu.ASSET_NAME}]}


def _metadata(app, build, built_at="2026-09-04T10:00:00Z"):
    (app / 'BUILD_METADATA.json').write_text(json.dumps(dict(format=1, build_id=build, built_at=built_at)), encoding='utf-8')



def test_same_build_is_not_staged(tmp_path):
    app = tmp_path / "app"; app.mkdir(); (app / "BUILD_ID").write_text("20260904-1000", encoding="utf-8")
    _metadata(app, '20260904-1000')
    out = qu.stage_if_newer(tmp_path / "state", app, opener=_opener(_release("20260904-1000", b"setup"), b"setup"))
    assert out == {"staged": False, "reason": "up to date", "build_id": "20260904-1000"}
    assert not (tmp_path / "state" / "updates" / qu.ASSET_NAME).exists()


def test_newer_build_is_downloaded_verified_and_staged_not_applied(tmp_path):
    app = tmp_path / "app"; app.mkdir(); (app / "BUILD_ID").write_text("20260904-1000", encoding="utf-8")
    _metadata(app, '20260904-1000')
    asset = b"new-setup-bytes"
    out = qu.stage_if_newer(tmp_path / "state", app, opener=_opener(_release("20260904-1200", asset), asset))
    assert out["staged"] and out["build_id"] == "20260904-1200"
    staged = tmp_path / "state" / "updates" / qu.ASSET_NAME
    assert staged.read_bytes() == asset
    assert (app / "BUILD_ID").read_text(encoding="utf-8") == "20260904-1000", "staging never installs"


def test_a_download_that_does_not_match_the_published_sha_is_refused(tmp_path):
    app = tmp_path / "app"; app.mkdir(); (app / "BUILD_ID").write_text("a", encoding="utf-8")
    _metadata(app, 'a')
    out = qu.stage_if_newer(tmp_path / "state", app, opener=_opener(_release("b", b"good", sha="0" * 64), b"tampered"))
    assert out["staged"] is False and "SHA-256" in out["reason"]
    assert not (tmp_path / "state" / "updates" / qu.ASSET_NAME).exists()


def test_apply_runs_the_staged_installer_silently_and_retains_its_receipt(tmp_path):
    app = tmp_path / "app"; app.mkdir(); (app / "BUILD_ID").write_text("old", encoding="utf-8")
    _metadata(app, 'old')
    updates = tmp_path / "state" / "updates"; updates.mkdir(parents=True)
    asset = b"setup"; (updates / qu.ASSET_NAME).write_bytes(asset)
    (updates / "staged.json").write_text(json.dumps({"build_id": "new", "built_at": "2026-09-04T12:00:00Z", "sha256": hashlib.sha256(asset).hexdigest()}), encoding="utf-8")
    calls = []
    class _Done:
        returncode = 0
    def runner(argv, timeout=0, **options):
        calls.append(argv)
        (app / "BUILD_ID").write_text("new", encoding="utf-8")
        _metadata(app, 'new', '2026-09-04T12:00:00Z')
        return _Done()
    out = qu.apply_staged(tmp_path / "state", app, runner=runner)
    assert out["applied"] and out["build_id"] == "new"
    assert calls and calls[0][1:] == ["/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/NOCLOSEAPPLICATIONS", "/NORESTARTAPPLICATIONS", "/SP-", "/LOG=" + str(updates / "setup.log"), "/DIR=" + str(app)]
    assert "/CLOSEAPPLICATIONS" not in calls[0] and "/FORCECLOSEAPPLICATIONS" not in calls[0]
    assert (updates / qu.ASSET_NAME).is_file() and qu.staged_update(tmp_path / "state", app)["status"] == "awaiting_boot"


def test_apply_refuses_a_staged_file_that_changed_on_disk(tmp_path):
    app = tmp_path / "app"; app.mkdir(); (app / "BUILD_ID").write_text("old", encoding="utf-8")
    _metadata(app, 'old')
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
    # The route reads the RESPONSE, not the envelope: respond returns
    # {"command": ..., "response": ...}, so the old result["kind"] check never
    # matched and Restart-now could not fire (2026-09-04).
    assert '_answer.get("kind") == "update-ready"' in src
    assert '_answer = result.get("response")' in src


def test_the_app_has_one_close_owner_and_optional_tray(monkeypatch):
    # The accepted STAGE2B owner replaced always-hide with an explicit setting.
    court = Path(__file__).with_name('test_launcher_close_quits.py')
    runpy.run_path(str(court))['test_window_close_requests_quit_and_arms_a_bounded_watchdog'](monkeypatch)


_SILENT = ["/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/NOCLOSEAPPLICATIONS", "/NORESTARTAPPLICATIONS", "/SP-"]


def _watch(release, asset):
    seen = []
    def opener(request, timeout=0):
        url = request.full_url if hasattr(request, "full_url") else str(request)
        seen.append(url)
        if url != qu.RELEASE_API:
            return _Resp(asset)
        return _Resp(json.dumps(release).encode("utf-8"))
    return opener, seen


def test_unattended_newer_release_is_verified_and_installed_only_when_safe(tmp_path):
    app = tmp_path / "app"
    app.mkdir()
    (app / "BUILD_ID").write_text("20260904-1000", encoding="utf-8")
    _metadata(app, "20260904-1000", "2026-09-04T10:00:00Z")
    asset = b"new-setup-bytes"
    release = _release("20260904-1200", asset)
    opener, seen = _watch(release, asset)
    calls = []
    class _Done:
        returncode = 0
    def runner(argv, timeout=0, **options):
        calls.append(argv)
        (app / "BUILD_ID").write_text("20260904-1200", encoding="utf-8")
        _metadata(app, "20260904-1200", "2026-09-04T12:00:00Z")
        return _Done()
    state = tmp_path / "state"
    waiting = qu.apply_unattended(state, app, opener=opener, runner=runner, safe=False, stop_runtime=lambda *_: [])
    staged = state / "updates" / qu.ASSET_NAME
    marker = json.loads((state / "updates" / "staged.json").read_text(encoding="utf-8"))
    assert waiting["applied"] is False and waiting["status"] == "waiting" and waiting["reason"] == "waiting for a safe moment"
    assert staged.read_bytes() == asset and marker["sha256"] == hashlib.sha256(asset).hexdigest()
    assert any(url != qu.RELEASE_API for url in seen) and not calls
    installed = qu.apply_unattended(state, app, opener=opener, runner=runner, safe=True, stop_runtime=lambda *_: [])
    assert installed["applied"] is True and installed["build_id"] == "20260904-1200"
    assert calls and calls[0][1:7] == _SILENT
    assert "/CLOSEAPPLICATIONS" not in calls[0] and "/FORCECLOSEAPPLICATIONS" not in calls[0]


def test_unattended_same_version_does_nothing(tmp_path):
    app = tmp_path / "app"
    app.mkdir()
    (app / "BUILD_ID").write_text("20260904-1000", encoding="utf-8")
    _metadata(app, "20260904-1000")
    asset = b"setup"
    opener, seen = _watch(_release("20260904-1000", asset), asset)
    calls = []
    out = qu.apply_unattended(tmp_path / "state", app, opener=opener, runner=lambda *args, **kwargs: calls.append(args),
                              safe=True, stop_runtime=lambda *_: [])
    assert out == {"staged": False, "reason": "up to date", "build_id": "20260904-1000", "applied": False}
    assert seen == [qu.RELEASE_API] and not calls
    assert not (tmp_path / "state" / "updates" / qu.ASSET_NAME).exists()


def test_unattended_prerelease_is_ignored_and_not_downloaded(tmp_path):
    app = tmp_path / "app"
    app.mkdir()
    (app / "BUILD_ID").write_text("20260904-1000", encoding="utf-8")
    _metadata(app, "20260904-1000")
    release = dict(_release("20260904-1200", b"preview"), prerelease=True)
    opener, seen = _watch(release, b"preview")
    out = qu.apply_unattended(tmp_path / "state", app, opener=opener, runner=lambda *a, **k: (_ for _ in ()).throw(AssertionError("installer ran")),
                              safe=True, stop_runtime=lambda *_: [])
    assert out["applied"] is False and out["status"] == "ignored" and out["reason"] == "pre-release ignored"
    assert seen == [qu.RELEASE_API]
    assert not (tmp_path / "state" / "updates" / qu.ASSET_NAME).exists()


def test_unattended_hash_mismatch_is_refused_with_a_reason(tmp_path):
    app = tmp_path / "app"
    app.mkdir()
    (app / "BUILD_ID").write_text("20260904-1000", encoding="utf-8")
    _metadata(app, "20260904-1000", "2026-09-04T10:00:00Z")
    opener, _seen = _watch(_release("20260904-1200", b"good", sha="0" * 64), b"tampered")
    calls = []
    out = qu.apply_unattended(tmp_path / "state", app, opener=opener, runner=lambda *args, **kwargs: calls.append(args),
                              safe=True, stop_runtime=lambda *_: [])
    assert out["staged"] is False and out["applied"] is False and "SHA-256" in out["reason"]
    assert not calls and not (tmp_path / "state" / "updates" / qu.ASSET_NAME).exists()


def test_unattended_installer_failure_is_reported_as_failed(tmp_path):
    app = tmp_path / "app"
    app.mkdir()
    (app / "BUILD_ID").write_text("20260904-1000", encoding="utf-8")
    _metadata(app, "20260904-1000", "2026-09-04T10:00:00Z")
    asset = b"new-setup-bytes"
    opener, _seen = _watch(_release("20260904-1200", asset), asset)
    class _Fail:
        returncode = 7
    out = qu.apply_unattended(tmp_path / "state", app, opener=opener, runner=lambda argv, timeout=0, **options: _Fail(),
                              safe=True, stop_runtime=lambda *_: [])
    assert out["applied"] is False and out["status"] == "failed" and "installer failed (exit 7)" in out["reason"]
    from nodelang.application_update import update_decision
    decision = update_decision(out, "20260904-1000")
    assert decision["state"] == "failed" and decision["available_build"] == "" and "installer failed (exit 7)" in decision["detail"]


def test_header_update_button_keeps_install_now_and_shows_a_failed_reason():
    source = (Path(__file__).resolve().parents[2] / "01.APP/nodelang/studio/app.jsx").read_text(encoding="utf-8")
    assert "s.update.available || s.update.state==='failed'" in source
    assert "s.update.detail || 'Update failed'" in source
    assert "s.update.available ? act(api.installUpdate)" in source
    launcher = (Path(__file__).resolve().parents[2] / "01.APP/nodelang/nograph_launcher.py").read_text(encoding="utf-8")
    assert "check_if_due" in launcher and "install_if_safe" in launcher


def test_the_launcher_keeps_the_one_brain_owner_and_no_retired_daemon():
    source = (Path(__file__).resolve().parents[2] / "01.APP/nodelang/launcher.py").read_text(encoding='utf-8')
    tree = ast.parse(source)
    names = {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
    assert '_watch_brain' not in names and '_ensure_brain' not in names
    assert '_stage_update_quietly' in names
    assert any(isinstance(node, ast.ImportFrom) and node.module == 'nodelang.application_server'
               for node in ast.walk(tree)), 'the single application server owns the Brain'
