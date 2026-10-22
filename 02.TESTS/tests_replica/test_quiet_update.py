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


def test_the_launcher_keeps_the_one_brain_owner_and_no_retired_daemon():
    source = (Path(__file__).resolve().parents[2] / "01.APP/nodelang/launcher.py").read_text(encoding='utf-8')
    tree = ast.parse(source)
    names = {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
    assert '_watch_brain' not in names and '_ensure_brain' not in names
    assert '_stage_update_quietly' in names
    assert any(isinstance(node, ast.ImportFrom) and node.module == 'nodelang.application_server'
               for node in ast.walk(tree)), 'the single application server owns the Brain'
