"""Would installed ArchHub accept this build output as its next update?

One reconciliation for every publish path (local and GitHub Actions). It reads
a build_release.ps1 output directory, checks every byte the release claims,
then feeds the exact GitHub release shape the publish would create through
nodelang.quiet_update.read_latest_release -- the parser installed users run.
A release the updater cannot read, or one that is not newer than the release
it would replace, is refused before anything is uploaded.

Usage: python check_update_offer.py RELEASE_DIR [--expected-revision SHA]
           [--repository OWNER/NAME] [--live] [--installed-app-dir DIR]
GH_TOKEN (or GITHUB_TOKEN), when set, authenticates the live reads; it is
never printed. A rate-limited or forbidden read refuses; it never reads as
"tag exists" or "not pushed".
Prints one JSON object; exit 0 only when every requested check passes.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from nodelang import quiet_update as qu  # noqa: E402

REPOSITORY = "Fargaly/ArchHub"
FILES = ("ArchHub-Setup-0.exe", "release.json", "release-notes.md",
         "source-manifest.tsv", "studio-build.json", "BUILD_METADATA.json")
# build_release.ps1 Read-StudioBuild records this reviewed count; the former
# CI publish step refused any other value.
STUDIO_FILES = 10
_UTC = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")


class Refused(ValueError):
    pass


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8-sig"), object_pairs_hook=qu._unique_object)
    if type(data) is not dict:
        raise Refused("%s is not a JSON object" % path.name)
    return data


def reconcile(release_dir: Path, expected_revision: str = "", repository: str = REPOSITORY) -> dict:
    """Return the release offer; raise Refused when any claimed byte differs."""
    release_dir = Path(release_dir)
    missing = [name for name in FILES if not (release_dir / name).is_file()]
    if missing:
        raise Refused("release output is missing: " + ", ".join(missing))
    manifest = _json(release_dir / "release.json")
    metadata = _json(release_dir / "BUILD_METADATA.json")
    asset = release_dir / qu.ASSET_NAME
    asset_sha, asset_bytes = _sha(asset), asset.stat().st_size
    notes = (release_dir / "release-notes.md").read_bytes().decode("utf-8")
    build_id, built_at = manifest.get("build_id"), manifest.get("built_at")
    checks = {
        "format": manifest.get("format") == 1,
        "build_id": type(build_id) is str and re.fullmatch(r"[A-Za-z0-9._-]{1,128}", build_id) is not None,
        "built_at": type(built_at) is str and _UTC.fullmatch(built_at) is not None,
        "asset_name": manifest.get("asset_name") == qu.ASSET_NAME,
        "asset_sha256": manifest.get("asset_sha256") == asset_sha,
        "asset_bytes": manifest.get("asset_bytes") == asset_bytes and 0 < asset_bytes <= qu._INSTALLER_BYTES,
        "payload_manifest": manifest.get("payload_manifest") == "source-manifest.tsv"
        and manifest.get("payload_manifest_sha256") == _sha(release_dir / "source-manifest.tsv"),
        "studio_manifest": manifest.get("studio_manifest") == "studio-build.json"
        and manifest.get("studio_manifest_sha256") == _sha(release_dir / "studio-build.json"),
        "studio_files": type(manifest.get("studio_files")) is int and manifest["studio_files"] == STUDIO_FILES,
        "build_metadata": manifest.get("build_metadata_sha256") == _sha(release_dir / "BUILD_METADATA.json")
        and metadata == {"format": 1, "build_id": build_id, "built_at": built_at},
        "source_revision": type(manifest.get("source_revision")) is str
        and re.fullmatch(r"[0-9a-f]{40}", manifest["source_revision"]) is not None
        and (not expected_revision or manifest["source_revision"] == expected_revision),
        "notes": "\r" not in notes
        and ("BUILD_ID: %s\n" % build_id) in notes
        and ("BUILT_AT: %s\n" % built_at) in notes
        and ("SHA256 %s: %s\n" % (qu.ASSET_NAME, asset_sha)) in notes,
    }
    failed = sorted(name for name, ok in checks.items() if not ok)
    if failed:
        raise Refused("release output does not reconcile: " + ", ".join(failed))
    tag = "build-" + build_id
    return {
        "tag": tag,
        "build_id": build_id,
        "built_at": built_at,
        "source_revision": manifest["source_revision"],
        "asset_sha256": asset_sha,
        "asset_bytes": asset_bytes,
        # Exactly what GitHub's releases/latest returns once published.
        "github_release": {
            "tag_name": tag, "draft": False, "prerelease": False, "body": notes,
            "assets": [{
                "name": qu.ASSET_NAME, "size": asset_bytes,
                "browser_download_url": "https://github.com/%s/releases/download/%s/%s"
                % (repository, urllib.parse.quote(tag, safe=""), qu.ASSET_NAME),
            }],
        },
    }


class _Body(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


def updater_reads(github_release: dict) -> dict | None:
    """Run the installed updater's own parser over the release it would see."""
    def opener(request, timeout=0):
        if getattr(request, "full_url", request) != qu.RELEASE_API:
            raise OSError("offline check reads only the release API")
        return _Body(json.dumps(github_release).encode("utf-8"))
    return qu.read_latest_release(opener)


def _headers() -> dict:
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "ArchHub-release"}
    credential = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if credential:
        headers["Authorization"] = "Bearer " + credential
    return headers


def _status(url: str) -> int:
    request = urllib.request.Request(url, method="GET", headers=_headers())
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.status
    except urllib.error.HTTPError as exc:
        return exc.code


def _live_manifest(repository: str = REPOSITORY) -> dict | None:
    """The live latest release's own release.json, for releases whose body the
    updater cannot read (a hand-written prose body carries no BUILD_ID)."""
    request = urllib.request.Request(
        "https://api.github.com/repos/%s/releases/latest" % repository, headers=_headers())
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            data = json.loads(response.read(qu._RELEASE_BYTES))
        url = next(a["browser_download_url"] for a in data.get("assets", [])
                   if isinstance(a, dict) and a.get("name") == "release.json")
        # Public download URL: no credential is sent to the asset host.
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "ArchHub-release"}),
                                    timeout=20) as response:
            manifest = json.loads(response.read(65536).decode("utf-8-sig"))
        return {"tag": data.get("tag_name"), "build_id": manifest.get("build_id"),
                "built_at": manifest.get("built_at")}
    except (OSError, ValueError, StopIteration, KeyError, TypeError):
        return None


def check(release_dir: Path, *, expected_revision: str = "", live: bool = False,
          installed_app_dir: Path | None = None, latest_reader=qu.read_latest_release,
          status=_status, live_manifest=_live_manifest, repository: str = REPOSITORY) -> dict:
    offer = reconcile(release_dir, expected_revision, repository)
    parsed = updater_reads(offer["github_release"])
    wanted = {"build_id": offer["build_id"], "built_at": offer["built_at"],
              "sha256": offer["asset_sha256"], "tag": offer["tag"],
              "url": offer["github_release"]["assets"][0]["browser_download_url"]}
    if parsed != wanted:
        raise Refused("the installed updater would not read this release: %r" % (parsed,))
    result = {"ok": True, "offer": {k: v for k, v in offer.items() if k != "github_release"},
              "updater_reads": parsed}
    if installed_app_dir is not None:
        current = qu.installed_build_id(installed_app_dir)
        refusal = None if current == offer["build_id"] else qu._ordering_refusal(installed_app_dir, parsed, current)
        result["installed"] = {"build_id": current,
                               "decision": "up to date" if current == offer["build_id"]
                               else (refusal or "would stage this update")}
    if live:
        latest = latest_reader()
        result["live_latest"] = latest
        if latest is None:
            # Installed users currently get "no release information". Order
            # against the release's own manifest so an older build never
            # replaces a newer, unreadable one.
            latest = live_manifest(repository)
            result["live_latest_unreadable_by_updater"] = latest
            if latest is None:
                raise Refused("cannot verify the live latest release's build time; refusing rather than "
                              "risk replacing a newer release (set GH_TOKEN if rate-limited)")
        if latest is not None and qu._utc_build_time(latest.get("built_at")) is not None:
            if qu._utc_build_time(offer["built_at"]) <= qu._utc_build_time(latest["built_at"]):
                raise Refused("not newer than the live latest release %s (%s); installed users would refuse it"
                              % (latest["build_id"], latest["built_at"]))
        base = "https://api.github.com/repos/" + repository
        tag_status = status(base + "/git/ref/tags/" + urllib.parse.quote(offer["tag"], safe=""))
        commit_status = status(base + "/commits/" + offer["source_revision"])
        for what, code in (("tag", tag_status), ("source revision", commit_status)):
            if code not in (200, 404):
                raise Refused("cannot verify the %s on %s (HTTP %d: rate-limited, forbidden or unavailable); "
                              "refusing -- set GH_TOKEN and retry" % (what, repository, code))
        result["remote"] = {"tag_free": tag_status == 404, "source_revision_pushed": commit_status == 200}
        if tag_status != 404:
            raise Refused("tag %s already exists on %s" % (offer["tag"], repository))
        if commit_status != 200:
            raise Refused("source revision %s is not on %s (HTTP %d); push it first"
                          % (offer["source_revision"], repository, commit_status))
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("release_dir", type=Path)
    parser.add_argument("--expected-revision", default="")
    parser.add_argument("--repository", default=REPOSITORY)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--installed-app-dir", type=Path)
    args = parser.parse_args(argv)
    try:
        result = check(args.release_dir, expected_revision=args.expected_revision,
                       live=args.live, installed_app_dir=args.installed_app_dir,
                       repository=args.repository)
    except (Refused, OSError, ValueError) as exc:
        print(json.dumps({"ok": False, "refused": str(exc)}, indent=2))
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
