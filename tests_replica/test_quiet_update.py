"""Quiet update: stage only a newer, SHA-verified build; apply only at launch; never guess."""
from __future__ import annotations

import hashlib
import io
import json

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
