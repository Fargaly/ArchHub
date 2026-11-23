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
# Installed app: nodelang sits beside packaging/. Repository (REPOCLEAN3): it sits in 01.APP/.
for candidate in (ROOT, Path(__file__).resolve().parents[3] / "01.APP"):
    if (candidate / "nodelang").is_dir() and str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from nodelang import quiet_update as qu  # noqa: E402
from nodelang.host_addin_retarget import manifest_rows  # noqa: E402

REPOSITORY = "Fargaly/ArchHub"
RELEASE_CHECK_NODE = {"id": "release.check_update_offer", "params": {"request_seconds": 20}}
INSTALLED_MANIFEST = "installed-source-manifest.tsv"
FILES = ("ArchHub-Setup-0.exe", "release.json", "release-notes.md",
         "source-manifest.tsv", "studio-build.json", "BUILD_METADATA.json", INSTALLED_MANIFEST)
# Native support carried by the last complete baseline, 20261119-0904-665c785.
# A stable release must keep these years even if the build runner lacks their SDKs.
STABLE_HOST_YEARS = {"revit": (2020, 2023, 2024, 2025, 2027), "autocad": (2026,)}
# Count the same source inventory the build compiler consumes, not an old
# hand-maintained count that rejects every newly compiled installer.
_compiler = (ROOT / "packaging/compile_studio.cjs").read_text(encoding="utf-8")
STUDIO_FILES = len(re.findall(r"""["'][^"']+\.jsx?["']""", _compiler.split("const names = [", 1)[1].split("];", 1)[0]))
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


def _valid_build_notes(notes: str, build_id: str, built_at: str, asset_sha: str) -> bool:
    if "\r" in notes:
        return False
    heading = re.search(r"(?m)^## Build[ \t]*\n", notes)
    if heading is None:
        return False
    tail = notes[heading.end():]
    return (qu._BUILD_RE.findall(notes) == [build_id]
            and qu._BUILD_RE.findall(tail) == [build_id]
            and len(re.findall(r"(?m)^[ \t]*BUILD_ID\b[^\r\n]*", notes)) == 1
            and qu._SHA_RE.findall(notes) == [asset_sha]
            and qu._SHA_RE.findall(tail) == [asset_sha]
            and len(re.findall(r"(?m)^[ \t]*SHA256 " + re.escape(qu.ASSET_NAME) + r"\b[^\r\n]*", notes)) == 1
            and ("BUILD_ID: %s\n" % build_id) in tail
            and ("BUILT_AT: %s\n" % built_at) in tail
            and ("SHA256 %s: %s\n" % (qu.ASSET_NAME, asset_sha)) in tail)


# The API assemblies build_host_bridges.ps1 compiles each stable year against.
HOST_SDK_FILES = {"revit": ("Revit", ("RevitAPI.dll", "RevitAPIUI.dll")),
                  "autocad": ("AutoCAD", ("acmgd.dll", "acdbmgd.dll", "accoremgd.dll"))}


def missing_host_sdks(program_files) -> list:
    """Each stable host year whose SDK this machine lacks, checked before any long compile."""
    missing = []
    for host, years in STABLE_HOST_YEARS.items():
        product, names = HOST_SDK_FILES[host]
        for year in years:
            folder = Path(program_files) / "Autodesk" / f"{product} {year}"
            absent = [name for name in names if not (folder / name).is_file()]
            if absent:
                missing.append(f"{host} {year} ({', '.join(absent)})")
    return missing


def check_host_payloads(manifest: Path, build_id: str) -> None:
    """Apply the stable coverage floor to the same file inventory Setup prunes against."""
    # The install manifest inventories program files. The broker review checks host JSON.
    paths = manifest_rows(manifest.read_bytes())
    missing = []
    for host, years in STABLE_HOST_YEARS.items():
        for year in years:
            folder = f"bridges/{host}/{year}/{build_id.casefold()}"
            if host == "revit":
                required = (f"{folder}/revitmcp.dll", f"{folder}/revitmcpcore.dll")
            else:
                required = (f"{folder}/acadmcp.dll",)
            if any(path not in paths for path in required):
                missing.append(f"{host} {year}")
    if missing:
        raise Refused("stable release would drop supported native host payloads: " + ", ".join(missing))


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
        "installed_manifest": manifest.get("installed_source_manifest_sha256") == _sha(release_dir / INSTALLED_MANIFEST),
        "studio_manifest": manifest.get("studio_manifest") == "studio-build.json"
        and manifest.get("studio_manifest_sha256") == _sha(release_dir / "studio-build.json"),
        "studio_files": type(manifest.get("studio_files")) is int and manifest["studio_files"] == STUDIO_FILES,
        "build_metadata": manifest.get("build_metadata_sha256") == _sha(release_dir / "BUILD_METADATA.json")
        and metadata == {"format": 1, "build_id": build_id, "built_at": built_at},
        "source_revision": type(manifest.get("source_revision")) is str
        and re.fullmatch(r"[0-9a-f]{40}", manifest["source_revision"]) is not None
        and (not expected_revision or manifest["source_revision"] == expected_revision),
        "notes": _valid_build_notes(notes, build_id, built_at, asset_sha),
    }
    failed = sorted(name for name, ok in checks.items() if not ok)
    if failed:
        raise Refused("release output does not reconcile: " + ", ".join(failed))
    check_host_payloads(release_dir / INSTALLED_MANIFEST, build_id)
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


def updater_reads(github_release: dict, *, channel="stable") -> dict | None:
    """Run the installed updater's own parser over the release it would see."""
    def opener(request, timeout=0):
        if getattr(request, "full_url", request) != (qu.RELEASE_API if channel == "stable" else qu.RELEASE_API.rsplit("/", 1)[0] + "?per_page=20"):
            raise OSError("offline check reads only the release API")
        return _Body(json.dumps(github_release if channel == "stable" else [github_release]).encode("utf-8"))
    return qu.read_latest_release(opener, channel=channel)


def _headers() -> dict:
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "ArchHub-release"}
    credential = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if credential:
        headers["Authorization"] = "Bearer " + credential
    return headers


def _status(url: str) -> int:
    request = urllib.request.Request(url, method="GET", headers=_headers())
    try:
        with urllib.request.urlopen(request, timeout=RELEASE_CHECK_NODE["params"]["request_seconds"]) as response:
            return response.status
    except urllib.error.HTTPError as exc:
        return exc.code


def _live_manifest(repository: str = REPOSITORY) -> dict | None:
    """The live latest release's own release.json, for releases whose body the
    updater cannot read (a hand-written prose body carries no BUILD_ID)."""
    request = urllib.request.Request(
        "https://api.github.com/repos/%s/releases/latest" % repository, headers=_headers())
    try:
        with urllib.request.urlopen(request, timeout=RELEASE_CHECK_NODE["params"]["request_seconds"]) as response:
            data = json.loads(response.read(qu._RELEASE_BYTES))
        url = next(a["browser_download_url"] for a in data.get("assets", [])
                   if isinstance(a, dict) and a.get("name") == "release.json")
        # Public download URL: no credential is sent to the asset host.
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "ArchHub-release"}),
                                    timeout=RELEASE_CHECK_NODE["params"]["request_seconds"]) as response:
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


def generated_build_block(directory, manifest, expected_revision):
    fields = {"BUILD_ID": manifest["build_id"], "BUILT_AT": manifest["built_at"],
              "SHA256 " + qu.ASSET_NAME: manifest["asset_sha256"], "SOURCE_REVISION": manifest["source_revision"],
              "REQUIREMENTS_SHA256": manifest["requirements_sha256"]}
    if not re.fullmatch(r"[0-9a-f]{40}", fields["SOURCE_REVISION"]) or not re.fullmatch(
            r"[0-9a-f]{64}", fields["REQUIREMENTS_SHA256"]):
        raise Refused("invalid generated preview provenance")
    if expected_revision and expected_revision != fields["SOURCE_REVISION"]:
        raise Refused("unexpected preview source revision")
    block = "## Build\n" + "".join(f"{key}: {value}\n" for key, value in fields.items())
    reserved = re.compile(r"^\s*(?:##\s+Build\s*$|(?:" + "|".join(map(re.escape, fields)) + r")\b)", re.I)
    def machine_lines(text):
        return [line for line in text.splitlines() if reserved.match(line)]
    if machine_lines((directory / "release-notes.md").read_text(encoding="utf-8-sig")) != block.splitlines():
        raise Refused("generated Build metadata differs from release.json")
    return block, machine_lines


def preview_notes(directory, tag, prose_path, expected_revision, snapshot, phase):
    """Validate public snapshots from the publisher; only the outer publisher can edit a release."""
    manifest = _json(directory / "release.json")
    if tag != "build-" + manifest["build_id"]:
        raise Refused("preview tag does not match the verified build ID")
    block, machine_lines = generated_build_block(directory, manifest, expected_revision)
    prose = prose_path.read_text(encoding="utf-8-sig").strip()
    if machine_lines(prose):
        raise Refused("human notes must not contain Build metadata")
    body = (prose + "\n\n" if prose else "") + block
    def identity(release):
        return (release["id"], release["tag_name"], release["draft"], release["prerelease"],
                sorted((a["id"], a["name"], a["size"], a["digest"]) for a in release["assets"]))
    original_stable = _json(snapshot / "before-stable.json")
    stable = identity(original_stable)
    preview = _json(snapshot / "before-preview.json")
    before = identity(preview)
    if preview["tag_name"] != tag or preview["draft"] or not preview["prerelease"] or stable[0] == preview["id"]:
        raise Refused("target is not a separate published preview")
    if (snapshot / (phase + "-revision")).read_text(encoding="ascii") != manifest["source_revision"]:
        raise Refused("preview tag targets a different source revision")
    prior = machine_lines(preview["body"] or "")
    # Older previews carried only the three updater fields. Every field present
    # must match the generated value, exactly once and in its original order.
    lines = block.splitlines()
    required = lines[:4]
    if prior and prior != required + [line for line in lines[4:] if line in prior]:
        raise Refused("published Build metadata conflicts with generated metadata")
    assets = {a["name"]: a for a in preview["assets"]}
    if len(assets) != len(preview["assets"]) or len({a["id"] for a in assets.values()}) != len(assets):
        raise Refused("duplicate preview asset identity")
    if (assets.get("release.json", {}).get("digest") != "sha256:" + _sha(directory / "release.json")
            or assets.get(qu.ASSET_NAME, {}).get("digest") != "sha256:" + manifest["asset_sha256"]
            or assets[qu.ASSET_NAME]["size"] != manifest["asset_bytes"]):
        raise Refused("preview assets differ from generated release")
    expected = {"build_id": manifest["build_id"], "built_at": manifest["built_at"], "tag": tag,
                "url": assets[qu.ASSET_NAME]["browser_download_url"], "sha256": manifest["asset_sha256"]}
    if updater_reads({**preview, "body": body}, channel="preview") != expected:
        raise Refused("updater refused proposed preview")
    changed = (preview["body"] or "").replace("\r\n", "\n") != body
    if phase == "before":
        (snapshot / "body.md").write_bytes(body.encode("utf-8"))
    else:
        published = _json(snapshot / (phase + "-preview.json"))
        observed_stable = _json(snapshot / (phase + "-stable.json"))
        expected_body = preview["body"] if phase == "recheck" else body
        if (identity(published) != before or identity(observed_stable) != stable
                or observed_stable["body"] != original_stable["body"]
                or (published["body"] or "").replace("\r\n", "\n") != (expected_body or "").replace("\r\n", "\n")
                or (phase == "after" and updater_reads(published, channel="preview") != expected)):
            raise Refused("preview readback or stable release identity changed; inspect before retrying")
    return {"ok": True, "id": preview["id"], "changed": phase == "before" and changed, "stable_tag": stable[1]}


def _remote_json(repository, suffix):
    request = urllib.request.Request("https://api.github.com/repos/" + repository + "/" + suffix,
                                     headers=_headers())
    with urllib.request.urlopen(request, timeout=RELEASE_CHECK_NODE["params"]["request_seconds"]) as response:
        return json.load(response, object_pairs_hook=qu._unique_object)


def _release_binding(record):
    assets = sorted((a["id"], a["name"], a["size"], a["digest"]) for a in record["assets"])
    identity = [record[k] for k in ("id", "tag_name", "target_commitish", "body")]
    return hashlib.sha256(json.dumps(identity + [assets], separators=(",", ":")).encode()).hexdigest()


def preview_publication(directory, report, mode, phase, stable_id, preview_id, previous_stable,
                        previous_preview, repository, remote=_remote_json, feed=qu.read_latest_release,
                        read_manifest=_live_manifest, draft_snapshot=None):
    offer = report["offer"]
    tag = offer["tag"]
    if repository != REPOSITORY:
        raise Refused("installed updater uses " + REPOSITORY)
    manifest = _json(directory / "release.json")
    block, machine_lines = generated_build_block(directory, manifest, offer["source_revision"])
    if (phase != "before" and not previous_stable) or (
            (phase == "after" or (mode == "promote" and phase == "ready")) and not previous_preview):
        raise Refused("missing prior release binding")
    if (mode == "promote" or phase != "before") and (preview_id is None or preview_id <= 0):
        raise Refused("missing preview release ID")
    stable = remote(repository, "releases/latest")
    published = phase == "after"
    promoted = published and mode == "promote"
    if (stable["draft"] is not False or stable["prerelease"] is not False
            or type(stable["id"]) is not int or stable["id"] != (preview_id if promoted else stable_id)):
        raise Refused("unexpected stable release identity")
    stable_binding = _release_binding(stable)
    if not promoted:
        if stable["tag_name"] == tag or (previous_stable and previous_stable != stable_binding):
            raise Refused("stable changed during publication")
        latest = updater_reads(stable) or read_manifest(repository)
        when = qu._utc_build_time(latest.get("built_at")) if latest and latest.get("tag") == stable["tag_name"] else None
        if when is None or when >= qu._utc_build_time(offer["built_at"]):
            raise Refused("cannot verify candidate is newer than stable")
    proof = {"stable_binding": stable_binding, "preview_binding": "", "id": 0}
    if mode == "create" and phase == "before":
        # The normal live check has already established a free tag and pushed revision.
        return proof
    preview = _json(draft_snapshot) if draft_snapshot else remote(repository, "releases/" + str(preview_id))
    draft = mode == "create" and not published
    if (preview["id"] != preview_id or preview_id <= 0 or preview_id == stable_id
            or preview["tag_name"] != tag or preview["draft"] is not draft
            or preview["prerelease"] is not (not promoted)):
        raise Refused("unexpected preview release identity or channel")
    if draft:
        if preview["target_commitish"] != offer["source_revision"]:
            raise Refused("draft targets a different revision")
    elif remote(repository, "commits/tags/" + tag)["sha"] != offer["source_revision"]:
        raise Refused("published tag targets a different revision")
    if machine_lines(preview["body"]) != block.splitlines():
        raise Refused("preview Build block is incomplete or conflicting; repair preview notes first")
    assets = preview["assets"]
    names = set(FILES) - {"release-notes.md", INSTALLED_MANIFEST}
    if ({a["name"] for a in assets} != names or len(assets) != len(names)
            or len({a["id"] for a in assets}) != len(assets)):
        raise Refused("preview asset inventory differs from publisher")
    for asset in assets:
        path = directory / asset["name"]
        digest = offer["asset_sha256"] if asset["name"] == qu.ASSET_NAME else _sha(path)
        if (type(asset["id"]) is not int or asset["id"] <= 0 or asset["size"] != path.stat().st_size
                or asset["digest"] != "sha256:" + digest):
            raise Refused("preview bytes differ for " + asset["name"])
    binding = _release_binding(preview)
    if previous_preview and previous_preview != binding:
        raise Refused("preview changed during publication")
    if promoted and _release_binding(remote(repository, "releases/" + str(stable_id))) != previous_stable:
        raise Refused("former stable release changed during promotion")
    if promoted and stable_binding != binding:
        raise Refused("latest differs from the approved preview")
    if not draft:
        channel = "stable" if promoted else "preview"
        if updater_reads(preview, channel=channel) != report["updater_reads"] or feed(channel=channel) != report["updater_reads"]:
            raise Refused("installed updater channel does not select the exact approved release")
    return dict(proof, preview_binding=binding, id=preview_id)


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["--missing-host-sdks"] and len(argv) == 2:
        # Build preflight: a plain argument, so every Windows shell passes it unchanged.
        missing = missing_host_sdks(argv[1])
        print("; ".join(missing))
        return 1 if missing else 0
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("release_dir", type=Path)
    parser.add_argument("--expected-revision", default="")
    parser.add_argument("--repository", default=REPOSITORY)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--installed-app-dir", type=Path)
    parser.add_argument("--preview-tag")
    parser.add_argument("--preview-notes", type=Path)
    parser.add_argument("--snapshot", type=Path)
    parser.add_argument("--phase", choices=("before", "recheck", "after"))
    parser.add_argument("--draft-snapshot", type=Path)
    parser.add_argument("--publication", choices=("create", "promote"))
    parser.add_argument("--publication-phase", choices=("before", "ready", "after"), default="before")
    parser.add_argument("--stable-id", type=int)
    parser.add_argument("--preview-id", type=int)
    parser.add_argument("--stable-binding")
    parser.add_argument("--preview-binding")
    args = parser.parse_args(argv)
    try:
        if any((args.preview_tag, args.preview_notes, args.snapshot, args.phase)):
            if not all((args.preview_tag, args.preview_notes, args.snapshot, args.phase)) or args.live or args.installed_app_dir:
                parser.error("preview edit requires the tag, prose, snapshot directory and phase")
            print(json.dumps(preview_notes(args.release_dir, args.preview_tag, args.preview_notes,
                                           args.expected_revision, args.snapshot, args.phase)))
            return 0
        result = check(args.release_dir, expected_revision=args.expected_revision,
                       live=args.live or (args.publication == "create" and args.publication_phase != "after"),
                       installed_app_dir=args.installed_app_dir,
                       repository=args.repository)
        if args.publication:
            if not args.expected_revision or not args.stable_id:
                raise Refused("explicit revision and stable ID required")
            result["publication"] = preview_publication(
                args.release_dir, result, args.publication, args.publication_phase, args.stable_id,
                args.preview_id, args.stable_binding, args.preview_binding, args.repository, draft_snapshot=args.draft_snapshot)
    except (KeyError, TypeError, OSError, ValueError) as exc:
        print(json.dumps({"ok": False, "refused": str(exc)}, indent=2))
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
