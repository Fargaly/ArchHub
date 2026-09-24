"""Publish -> update, end to end, against a LOCAL release in a temp folder.

The release is written exactly as installer/build_release.ps1 writes one; the
GitHub release it would become is produced by packaging/windows/
check_update_offer.py (the one publish path); the installed updater
(nodelang.quiet_update) then reads, downloads, verifies, applies and confirms
it. Nothing reaches the network, the real installer or the founder's graph:
the graph is a throwaway sqlite fixture and the "installer" is a stand-in that
writes only into the application directory, as ArchHub.iss does.
"""
from __future__ import annotations

import hashlib
import importlib.util
import io
import json
from pathlib import Path
import re
import sqlite3

import pytest

from nodelang import quiet_update as qu

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "check_update_offer", ROOT / "packaging" / "windows" / "check_update_offer.py")
offer_check = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(offer_check)

REVISION = "72bcaaecc5c3c69d83a3155c9b691c9b8cf5d8d1"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _installer_bytes(build_id: str, built_at: str) -> bytes:
    """Stand-in installer: the files it lays into {app}, nothing else."""
    metadata = json.dumps({"format": 1, "build_id": build_id, "built_at": built_at},
                          separators=(",", ":")) + "\n"
    return json.dumps({"BUILD_ID": build_id, "BUILD_METADATA.json": metadata,
                       "nodelang/__release_marker__.py": "BUILD = %r\n" % build_id}).encode("utf-8")


def _build_output(folder: Path, build_id: str, built_at: str) -> Path:
    """The six files build_release.ps1 writes for a release-mode build."""
    folder.mkdir(parents=True)
    asset = _installer_bytes(build_id, built_at)
    (folder / qu.ASSET_NAME).write_bytes(asset)
    metadata = json.dumps({"format": 1, "build_id": build_id, "built_at": built_at},
                          separators=(",", ":")) + "\n"
    (folder / "BUILD_METADATA.json").write_bytes(metadata.encode("utf-8"))
    (folder / "source-manifest.tsv").write_bytes(b"ARCHHUB_RELEASE_SOURCE_MANIFEST_V2\n")
    (folder / "studio-build.json").write_bytes(b'{"format":1}\n')
    manifest = {
        "format": 1, "build_id": build_id, "built_at": built_at,
        "build_metadata_sha256": _sha(metadata.encode("utf-8")),
        "source_revision": REVISION,
        "payload_manifest": "source-manifest.tsv",
        "payload_manifest_sha256": _sha((folder / "source-manifest.tsv").read_bytes()),
        "studio_manifest": "studio-build.json",
        "studio_manifest_sha256": _sha((folder / "studio-build.json").read_bytes()),
        "studio_files": 10,
        "asset_name": qu.ASSET_NAME, "asset_sha256": _sha(asset), "asset_bytes": len(asset),
    }
    (folder / "release.json").write_text(json.dumps(manifest, indent=4) + "\n", encoding="utf-8")
    notes = "BUILD_ID: %s\nBUILT_AT: %s\nSHA256 %s: %s\nSOURCE_REVISION: %s\n" % (
        build_id, built_at, qu.ASSET_NAME, _sha(asset), REVISION)
    (folder / "release-notes.md").write_bytes(notes.encode("utf-8"))
    return folder


class _Body(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


def _local_github(release_dir: Path, served_asset: bytes | None = None, downloads=None):
    """Serve the release exactly as GitHub would once publish_release.ps1 ran."""
    offer = offer_check.reconcile(release_dir)
    download_url = offer["github_release"]["assets"][0]["browser_download_url"]

    def opener(request, timeout=0):
        url = getattr(request, "full_url", request)
        if url == qu.RELEASE_API:
            return _Body(json.dumps(offer["github_release"]).encode("utf-8"))
        if url == download_url:
            if downloads is not None:
                downloads.append(url)
            data = served_asset if served_asset is not None else (release_dir / qu.ASSET_NAME).read_bytes()
            return _Body(data)
        raise AssertionError("unexpected network request: %s" % url)
    return opener


def _installed_app(folder: Path, build_id: str, built_at: str) -> Path:
    folder.mkdir(parents=True)
    (folder / "BUILD_ID").write_text(build_id, encoding="utf-8")
    (folder / "BUILD_METADATA.json").write_text(json.dumps(
        {"format": 1, "build_id": build_id, "built_at": built_at}) + "\n", encoding="utf-8")
    return folder


def _fixture_state(folder: Path) -> Path:
    """A throwaway graph (the persisted Cell shape, in WAL) plus user config."""
    folder.mkdir(parents=True)
    connection = sqlite3.connect(folder / "archhub-test.universal.sqlite3")
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("CREATE TABLE cells (id TEXT PRIMARY KEY, link0 TEXT, link1 TEXT, atom BLOB)")
    connection.executemany("INSERT INTO cells VALUES (?, ?, ?, ?)",
                           [("c%03d" % i, "c%03d" % (i - 1), "", ("atom-%d" % i).encode()) for i in range(200)])
    connection.commit()
    connection.close()
    (folder / "settings.json").write_text(json.dumps({"default_model": "fixture", "theme": "dark"}), encoding="utf-8")
    (folder / "window-layout.json").write_text('{"panels":["Properties"]}', encoding="utf-8")
    return folder


def _state_fingerprint(state: Path) -> dict:
    return {str(p.relative_to(state)): _sha(p.read_bytes())
            for p in sorted(state.rglob("*")) if p.is_file() and "updates" not in p.relative_to(state).parts}


def _fake_installer(calls):
    """Inno stand-in: lays its files into /DIR= only, as ArchHub.iss does."""
    class _Done:
        returncode = 0

    def runner(argv, **_options):
        calls.append(argv)
        target = Path(next(a for a in argv if a.startswith("/DIR="))[len("/DIR="):])
        for relative, text in json.loads(Path(argv[0]).read_bytes()).items():
            destination = target / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(text, encoding="utf-8")
        return _Done()
    return runner


def test_newer_local_release_is_verified_applied_confirmed_and_keeps_graph_and_config(tmp_path):
    release = _build_output(tmp_path / "release", "20260924-0900-abc1234", "2026-09-24T05:00:00Z")
    app = _installed_app(tmp_path / "ArchHub", "20260923-1945-72bcaae", "2026-09-23T15:57:49Z")
    state = _fixture_state(tmp_path / "ArchHub-Test")
    before = _state_fingerprint(state)
    downloads = []

    staged = qu.stage_if_newer(state, app, opener=_local_github(release, downloads=downloads))
    assert staged["staged"] is True and staged["status"] == "staged", staged
    assert staged["build_id"] == "20260924-0900-abc1234" and staged["bytes_verified"] is True
    assert staged["sha256"] == _sha((release / qu.ASSET_NAME).read_bytes())
    assert _sha((state / "updates" / qu.ASSET_NAME).read_bytes()) == staged["sha256"]
    assert len(downloads) == 1
    assert qu.installed_build_id(app) == "20260923-1945-72bcaae", "staging never installs"

    calls = []
    applied = qu.apply_staged(state, app, runner=_fake_installer(calls))
    assert applied["applied"] is True and applied["status"] == "awaiting_boot", applied
    assert calls and "/VERYSILENT" in calls[0] and "/DIR=" + str(app) in calls[0]
    confirmed = qu.confirm_applied(state, app)
    assert confirmed["confirmed"] is True and confirmed["status"] == "confirmed", confirmed
    assert qu.installed_build_id(app) == "20260924-0900-abc1234"

    assert _state_fingerprint(state) == before, "update changed the graph or user config"
    connection = sqlite3.connect("file:%s?mode=ro" % (state / "archhub-test.universal.sqlite3").as_posix(), uri=True)
    try:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute("SELECT COUNT(*) FROM cells").fetchone()[0] == 200
    finally:
        connection.close()

    again = qu.stage_if_newer(state, app, opener=_local_github(release, downloads=downloads))
    assert again == {"staged": False, "reason": "up to date", "build_id": "20260924-0900-abc1234"}
    assert len(downloads) == 1, "an installed build is never downloaded again"


@pytest.mark.parametrize("offered_id,offered_at,reason", [
    ("20260923-1945-72bcaae", "2026-09-23T15:57:49Z", "up to date"),
    ("20260923-1946-rebuilt", "2026-09-23T15:57:49Z", "not newer"),
    ("20260918-1700-b63fdf3", "2026-09-18T12:43:29Z", "not newer"),
])
def test_equal_or_older_release_is_refused_without_download(tmp_path, offered_id, offered_at, reason):
    release = _build_output(tmp_path / "release", offered_id, offered_at)
    app = _installed_app(tmp_path / "ArchHub", "20260923-1945-72bcaae", "2026-09-23T15:57:49Z")
    state = _fixture_state(tmp_path / "ArchHub-Test")
    downloads = []
    out = qu.stage_if_newer(state, app, opener=_local_github(release, downloads=downloads))
    assert out["staged"] is False and reason in out["reason"], out
    assert downloads == []
    assert not (state / "updates" / qu.ASSET_NAME).exists()
    assert qu.installed_build_id(app) == "20260923-1945-72bcaae"


def test_corrupt_download_is_refused_and_nothing_is_staged_or_installed(tmp_path):
    release = _build_output(tmp_path / "release", "20260924-0900-abc1234", "2026-09-24T05:00:00Z")
    app = _installed_app(tmp_path / "ArchHub", "20260923-1945-72bcaae", "2026-09-23T15:57:49Z")
    state = _fixture_state(tmp_path / "ArchHub-Test")
    good = (release / qu.ASSET_NAME).read_bytes()
    corrupt = good[:-1] + bytes([good[-1] ^ 0xFF])
    out = qu.stage_if_newer(state, app, opener=_local_github(release, served_asset=corrupt))
    assert out["staged"] is False and "did not match published SHA-256" in out["reason"], out
    assert not (state / "updates" / qu.ASSET_NAME).exists()
    assert not (state / "updates" / "staged.json").exists()
    assert not list((state / "updates").glob(".download-*")), "partial download retained"
    refused = qu.apply_staged(state, app, runner=_fake_installer([]))
    assert refused["applied"] is False
    assert qu.installed_build_id(app) == "20260923-1945-72bcaae"


def test_staged_installer_altered_on_disk_is_never_run(tmp_path):
    release = _build_output(tmp_path / "release", "20260924-0900-abc1234", "2026-09-24T05:00:00Z")
    app = _installed_app(tmp_path / "ArchHub", "20260923-1945-72bcaae", "2026-09-23T15:57:49Z")
    state = _fixture_state(tmp_path / "ArchHub-Test")
    assert qu.stage_if_newer(state, app, opener=_local_github(release))["staged"] is True
    (state / "updates" / qu.ASSET_NAME).write_bytes(b"swapped after verification")
    calls = []
    out = qu.apply_staged(state, app, runner=_fake_installer(calls))
    assert out["applied"] is False and "SHA-256" in out["reason"], out
    assert calls == [] and qu.installed_build_id(app) == "20260923-1945-72bcaae"


def test_publish_check_refuses_build_output_whose_bytes_do_not_reconcile(tmp_path):
    release = _build_output(tmp_path / "release", "20260924-0900-abc1234", "2026-09-24T05:00:00Z")
    with (release / qu.ASSET_NAME).open("ab") as stream:
        stream.write(b"!")
    with pytest.raises(offer_check.Refused, match="asset_bytes.*asset_sha256|asset_sha256"):
        offer_check.reconcile(release)
    release2 = _build_output(tmp_path / "release2", "20260924-0900-abc1234", "2026-09-24T05:00:00Z")
    with pytest.raises(offer_check.Refused, match="source_revision"):
        offer_check.reconcile(release2, expected_revision="0" * 40)


def test_a_prose_release_body_is_unreadable_to_installed_users(tmp_path):
    """build-20260918-1700-b63fdf3 was uploaded by hand with a prose body:
    every installed updater reads it as 'no release information'."""
    release = _build_output(tmp_path / "release", "20260924-0900-abc1234", "2026-09-24T05:00:00Z")
    offer = offer_check.reconcile(release)
    assert offer_check.updater_reads(offer["github_release"])["build_id"] == "20260924-0900-abc1234"
    prose = dict(offer["github_release"], body="Studio built from the founder's design.")
    assert offer_check.updater_reads(prose) is None
    (release / "release-notes.md").write_bytes(b"Studio built from the founder's design.\n")
    with pytest.raises(offer_check.Refused, match="notes"):
        offer_check.reconcile(release)


OLDER_LIVE = lambda *_repository: {"build_id": "20260918-1700-b63fdf3", "built_at": "2026-09-18T12:43:29Z"}
FREE_AND_PUSHED = lambda url: 404 if "/git/ref/tags/" in url else 200


def test_publish_check_orders_against_live_latest_even_when_its_body_is_unreadable(tmp_path):
    release = _build_output(tmp_path / "release", "20260924-0900-abc1234", "2026-09-24T05:00:00Z")
    ok = offer_check.check(release, live=True, latest_reader=lambda: None, status=FREE_AND_PUSHED,
                           live_manifest=OLDER_LIVE)
    assert ok["ok"] and ok["remote"] == {"tag_free": True, "source_revision_pushed": True}
    with pytest.raises(offer_check.Refused, match="not newer than the live latest"):
        offer_check.check(release, live=True, latest_reader=lambda: None, status=FREE_AND_PUSHED,
                          live_manifest=lambda *_r: {"build_id": "later", "built_at": "2026-09-25T00:00:00Z"})
    with pytest.raises(offer_check.Refused, match="cannot verify the live latest"):
        offer_check.check(release, live=True, latest_reader=lambda: None, status=FREE_AND_PUSHED,
                          live_manifest=lambda *_r: None)
    with pytest.raises(offer_check.Refused, match="already exists"):
        offer_check.check(release, live=True, latest_reader=lambda: None, status=lambda url: 200,
                          live_manifest=OLDER_LIVE)
    with pytest.raises(offer_check.Refused, match="push it first"):
        offer_check.check(release, live=True, latest_reader=lambda: None, live_manifest=OLDER_LIVE,
                          status=lambda url: 404)


def test_studio_file_count_must_match_the_reviewed_build(tmp_path):
    release = _build_output(tmp_path / "release", "20260924-0900-abc1234", "2026-09-24T05:00:00Z")
    assert offer_check.reconcile(release)["build_id"] == "20260924-0900-abc1234"
    manifest = json.loads((release / "release.json").read_text(encoding="utf-8"))
    for wrong in (13, 9, "10", None):
        manifest["studio_files"] = wrong
        (release / "release.json").write_text(json.dumps(manifest), encoding="utf-8")
        with pytest.raises(offer_check.Refused, match="studio_files"):
            offer_check.reconcile(release)


def test_repository_is_passed_through_and_only_the_updaters_repository_is_readable(tmp_path):
    release = _build_output(tmp_path / "release", "20260924-0900-abc1234", "2026-09-24T05:00:00Z")
    offer = offer_check.reconcile(release, repository="someone/fork")
    assert offer["github_release"]["assets"][0]["browser_download_url"].startswith(
        "https://github.com/someone/fork/releases/download/")
    seen, manifests = [], []
    def status(url):
        seen.append(url)
        return FREE_AND_PUSHED(url)
    with pytest.raises(offer_check.Refused, match="would not read"):
        offer_check.check(release, repository="someone/fork", live=True, status=status,
                          latest_reader=lambda: None, live_manifest=lambda r: manifests.append(r))
    assert seen == [], "a release the updater cannot read is refused before any live read"
    offer_check.check(release, repository="Fargaly/ArchHub", live=True, status=status,
                      latest_reader=lambda: None, live_manifest=lambda r: manifests.append(r) or OLDER_LIVE())
    assert manifests == ["Fargaly/ArchHub"]
    assert seen and all(u.startswith("https://api.github.com/repos/Fargaly/ArchHub/") for u in seen)
    publish = (ROOT / "packaging" / "windows" / "publish_release.ps1").read_text(encoding="utf-8")
    assert "'--repository', $Repository" in publish
    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert "-Repository $env:GH_REPO" in workflow


@pytest.mark.parametrize("code", [403, 429, 500])
def test_rate_limited_or_forbidden_github_reads_refuse_and_never_read_as_tag_exists(tmp_path, code):
    release = _build_output(tmp_path / "release", "20260924-0900-abc1234", "2026-09-24T05:00:00Z")
    with pytest.raises(offer_check.Refused) as refused:
        offer_check.check(release, live=True, latest_reader=lambda: None, live_manifest=OLDER_LIVE,
                          status=lambda url: code if "/git/ref/tags/" in url else 200)
    assert "cannot verify the tag" in str(refused.value) and "already exists" not in str(refused.value)
    with pytest.raises(offer_check.Refused, match="cannot verify the source revision"):
        offer_check.check(release, live=True, latest_reader=lambda: None, live_manifest=OLDER_LIVE,
                          status=lambda url: 404 if "/git/ref/tags/" in url else code)


def test_live_reads_use_gh_token_when_present_and_are_anonymous_otherwise(monkeypatch):
    sent = []
    class _Answer:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *_exc): return False
    def urlopen(request, timeout=0):
        sent.append(request.get_header("Authorization"))
        return _Answer()
    monkeypatch.setattr(offer_check.urllib.request, "urlopen", urlopen)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    assert offer_check._status("https://api.github.com/repos/Fargaly/ArchHub/commits/x") == 200
    monkeypatch.setenv("GH_TOKEN", "fixture-credential-not-real")
    assert offer_check._status("https://api.github.com/repos/Fargaly/ArchHub/commits/x") == 200
    assert sent == [None, "Bearer fixture-credential-not-real"]


def test_real_installer_deletes_only_named_application_files_never_user_state():
    iss = (ROOT / "installer" / "ArchHub.iss").read_text(encoding="utf-8")
    assert re.search(r"(?m)^DefaultDirName=\{localappdata\}\\ArchHub\s*$", iss)
    assert "[UninstallDelete]" not in iss and "filesandordirs" not in iss.lower()
    section = iss.split("[InstallDelete]", 1)[1].split("\n[", 1)[0]
    entries = re.findall(r'(?m)^Type:\s*(\w+);\s*Name:\s*"([^"]+)"', section)
    assert entries, "InstallDelete section not parsed"
    for kind, name in entries:
        assert kind == "files" and name.startswith("{app}\\"), (kind, name)
        assert not re.search(r"(?i)sqlite|graph|settings|credential|ArchHub-Test", name), name
    launcher = (ROOT / "launch_archhub_test.py").read_text(encoding="utf-8")
    assert '"ArchHub-Test"' in launcher, "user state must live outside the {app} folder the installer owns"
