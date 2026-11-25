"""Bounded update staging. Owner supplies recovery admission and boot acknowledgment.

Published SHA-256 is byte integrity, not signed release proof or rollback.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
from importlib import import_module
import json
import logging
import os
from pathlib import Path
import sys
import re
import subprocess
import tempfile
import threading
import time
import urllib.parse
import urllib.request
import zipfile

RELEASE_API = "https://api.github.com/repos/Fargaly/ArchHub/releases/latest"
# Kept current by release propagation; redirects to the latest release's own release.json asset.
OFFER_URL = "https://archhub.io/download.json"
RELEASE_RECORD = "https://github.com/Fargaly/ArchHub/releases/download/%s/release.json"
UPDATE_FEED_NODE = {'id': 'update.feed', 'params': {'request_seconds': 15, 'gh_seconds': 5}}
ASSET_NAME = "ArchHub-Setup-0.exe"
_BUILD_RE = re.compile(r"(?m)^BUILD_ID:[ \t]*([A-Za-z0-9._-]{1,128})[ \t]*\r?$")
_SHA_RE = re.compile(r"(?m)^SHA256 " + re.escape(ASSET_NAME)
                     + r":[ \t]*([0-9a-fA-F]{64})(?: \([1-9][0-9]{0,9} bytes\))?[ \t]*\r?$")
_UTC_BUILD_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")
# Historical public CI identity only: UTC stamp, GitHub run id/attempt, SHA12.
# A candidate or arbitrary opaque identifier never supplies chronology.
_LEGACY_PUBLIC_RE = re.compile(r"([0-9]{8})-([0-9]{6})-[1-9][0-9]*-[1-9][0-9]*-[0-9a-f]{12}")
_RELEASE_BYTES = 2 * 1024 * 1024
_INSTALLER_BYTES = 1024 * 1024 * 1024
_THREAD_LOCK = threading.Lock()
_PAYLOAD_DIRS = ("nodelang", "app", "runtime", "tools", "bridges", "licenses", "wheelhouse")
_PAYLOAD_FILES = ("BUILD_ID", "BUILD_METADATA.json", "colleague_setup.py",
                  "requirements.txt", "ArchHub.vbs", "ArchHub.bat", "archhub.ico", "NOTICE", "HOST_ARTIFACTS.json")
_ROLLBACK_BYTES = 2 * 1024 * 1024 * 1024

# The installed payload and the current plain-file owners. User documents are
# protected independently of this list, including unrecognised sessions-files data.
APP_FOLDER_OWNERS = {
    **{name: 'installer payload' for name in (*_PAYLOAD_DIRS, *_PAYLOAD_FILES, 'packed', 'docs', '.venv',
                                             'unins000.exe', 'unins000.dat', '.archhub-ready')},
    'settings': 'nograph_server.JsonFile / settings_owner',
    'workshop': 'workshop_mailbox / Workshop Session Link',
    'sessions': 'host_brokers / pipeline_engines',
    'sessions-files': 'legacy Canvas migration; unknown user files retained',
    'workflows': 'user Canvas documents', 'skills': 'user supplied workflows',
    'data': 'session_files recent/current metadata',
    'logs': 'log_rotation / cleanup removal manifest',
    'runtime': 'installer runtimes / runtime_credentials browser session',
    'bin': 'colleague_setup._setup_compiler_candidates host compiler discovery',
    'updates': 'quiet_update release handoff',
    'web-profile': 'nograph_launcher Qt browser profile',
    'agents': 'installed agent work files',
    'BABOOM': 'user companion assets', 'goose': 'goose_runtime work files',
    'library': 'user imported host connectors',
    'custom_nodes': 'selfext runtime user mods',
    'payload': 'host_exec compiled connector payloads',
    'Revit': 'host_brokers session records', 'AutoCAD': 'host_brokers session records',
    'bridge': 'host_brokers runtime', 'bridges': 'installer host adapters',
    'session-link': 'existing Workshop connection records',
    'native-launch-configs': 'native_agent_session configuration',
    'native-workshop': 'native_workshop_profile isolated assistant configuration',
    'runtimes': 'daily_work_nodes installed tools', 'daily-work': 'daily_work_nodes results',
    'nograph-http-port': 'nograph_server discovery',
    'baboom-position.json': 'baboom_native_runtime window position',
    'tray-notice-shown': 'window_commands close-to-tray preference',
    'browser-session-v1.dpapi': 'browser_admission protected session',
    'assistant-hooks.json': 'assistant_registration consent',
    'assistant-integration.json': 'assistant_registration consent',
    'settings.json': 'existing user preferences', 'profile.json': 'user profile',
    'theme.json': 'existing user theme',
    'deployment-evidence.json': 'deployment_evidence installed build provenance',
    'use_software_render': 'desktop renderer compatibility',
    'rhino.active': 'host_brokers', 'speckle.active': 'host_brokers',
    'keys': 'existing credential custody; never cleanup input',
    'runtime-context': 'hook_decision / native_stop_hook',
    'relay-descriptor.json': 'nograph_server cloud relay',
    'terminal': 'terminal_sessions working directory',
    'projects': 'user project files', 'exports': 'user exported files',
    'renders': 'user render outputs', 'personal_brain': 'user knowledge',
    'memory': 'user knowledge', 'private-client-backups': 'user client data',
}
_CLEANUP_STAGE = '_cleanup-staging'
_CLEANUP_JOURNAL = 'cleanup-pending.json'
_OBSOLETE_ROOT_ENTRIES = frozenset({
    'candidate-20.log', 'candidate-locked.log', 'live-20.stdout.log',
    'settings.json.bak_old', 'version.json.bak_old', 'node-native-wip.next-25.json.gz',
    'authority-bridge-headless.json.gz.universal.sqlite3', 'node-native-wip.json.gz.universal.sqlite3',
    '_syncrung_backup', '_deploy_backup', '.retired-v1-docs', 'preflight', 'packages', 'cache',
})


def _protected_file(path):
    file_type = path.suffix.casefold().lstrip('.').partition('-')[0]
    return (path.suffix.lower() in ('.pem', '.key', '.dpapi', '.pfx', '.p12', '.kdbx',
                                   '.pdf', '.xlsx', '.xls', '.json', '.docx', '.csv')
            or file_type in ('sqlite', 'sqlite3', 'db')
            or path.name.lower().startswith('.env')
            or any(re.search(r'credential|secret|token|password|^keys$|^auth[.-]', part, re.I)
                   for part in path.parts)
            or path.name.lower() == 'cloud.json')


# Historical data cannot become cleanup input just because an older build listed it.
for _entry in tuple(_OBSOLETE_ROOT_ENTRIES):
    if _protected_file(Path(_entry)):
        _OBSOLETE_ROOT_ENTRIES -= {_entry}
        APP_FOLDER_OWNERS[_entry] = 'founder-owned data; never cleanup'


def _cleanup_plain(path):
    return all(not item.is_symlink() and not getattr(item.lstat(), 'st_file_attributes', 0) & 0x400
               for item in (path, *path.parents) if item.exists() or item.is_symlink())


def _entry_files(path):
    """Never traverse junctions, even in retired folders."""
    if not _cleanup_plain(path):
        raise OSError('linked entry retained')
    if path.is_dir():
        for child in path.iterdir():
            yield from _entry_files(child)
    else:
        yield path


def _unlocked(path):
    if os.name != 'nt':
        return
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateFileW.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                  ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE)
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    handle = kernel.CreateFileW(str(path), 0x80000000, 0, None, 3, 0x80, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    kernel.CloseHandle(handle)


def _cleanup_paths(state):
    for path in state.iterdir():
        if path.name in _OBSOLETE_ROOT_ENTRIES:
            yield path
    # Only these exact founder-identified test titles are removable user-format files.
    from .session_files import read_document, verification_document
    legacy = state / 'sessions-files'
    for path in [*legacy.glob('*.archhub'), *(legacy / 'skills').glob('*.archhub')]:
        try:
            if _cleanup_plain(path) and verification_document(read_document(path)):
                yield path
        except (OSError, ValueError):
            continue


def restore_app_folder(state_dir):
    """Recover an interrupted/failed boot without overwriting any new user file."""
    from .nograph_server import JsonFile
    state = Path(state_dir)
    if not _cleanup_plain(state / _CLEANUP_STAGE) or not _cleanup_plain(state / 'logs'):
        raise ValueError('Cleanup paths must not contain links or reparse points')
    journal = state / 'logs' / _CLEANUP_JOURNAL
    if not journal.exists():
        return {'restored': [], 'pending': False}
    rows = json.loads(journal.read_text(encoding='utf-8'))
    restored, pending = [], []
    for row in reversed(rows):
        relative = Path(row['path'])
        if not relative.parts or relative.is_absolute() or relative.drive or '..' in relative.parts or relative.parts[0] == _CLEANUP_STAGE:
            raise ValueError('Invalid cleanup journal path')
        source, target = state / _CLEANUP_STAGE / relative, state / relative
        if source.exists():
            try:
                if target.exists():
                    raise OSError('restoration target exists; both retained')
                target.parent.mkdir(parents=True, exist_ok=True)
                source.rename(target)
                restored.append(row['path'])
            except OSError:
                pending.append(row)
    if pending:
        JsonFile(journal, []).write(pending)
    else:
        journal.unlink()
        _remove_empty_stage(state / _CLEANUP_STAGE)
    return {'restored': restored, 'pending': bool(pending)}


def _remove_empty_stage(stage):
    if not stage.is_dir():
        return
    for child in stage.iterdir():
        if child.is_dir() and _cleanup_plain(child):
            _remove_empty_stage(child)
    try:
        stage.rmdir()
    except OSError as error:
        logging.getLogger(__name__).debug('Cleanup staging retained: %s', error)


def stage_app_folder(state_dir):
    """First-run owner: stage unused entries before boot; never run by a maintenance tool."""
    from .nograph_server import JsonFile
    state = Path(state_dir).absolute()
    if not _cleanup_plain(state) or not _cleanup_plain(state / _CLEANUP_STAGE) or not _cleanup_plain(state / 'logs'):
        raise ValueError('Cleanup requires a plain application folder')
    if restore_app_folder(state)['pending']:
        return {'staged': [], 'skipped': ['unfinished restoration']}
    journal = state / 'logs' / _CLEANUP_JOURNAL
    staged, skipped = [], []
    for path in list(_cleanup_paths(state)):
        relative = path.relative_to(state)
        try:
            size = 0
            for file in _entry_files(path):
                # Unrecognised Canvas documents are user data, even in an old directory.
                if _protected_file(file.relative_to(state)) or (file.suffix.lower() == '.archhub' and path.suffix.lower() != '.archhub'):
                    raise OSError('user Canvas document retained')
                _unlocked(file)
                size += file.stat().st_size
            target = state / _CLEANUP_STAGE / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            row = {'path': relative.as_posix(), 'size': size}
            # Journal before rename: either side remains recoverable after a crash.
            JsonFile(journal, []).write([*staged, row])
            path.rename(target)
            staged.append(row)
        except OSError as error:
            skipped.append({'path': relative.as_posix(), 'reason': str(error)})
    if staged:
        JsonFile(journal, []).write(staged)
    elif journal.exists():
        journal.unlink()
    _remove_empty_stage(state / _CLEANUP_STAGE)
    return {'staged': staged, 'skipped': skipped}


def finish_app_folder(state_dir, *, healthy):
    """Delete only after the app's health check; failure restores the exact staged entries."""
    if not healthy:
        return restore_app_folder(state_dir)
    import shutil
    from .nograph_server import JsonFile
    from .log_rotation import RotatingLog
    state = Path(state_dir)
    if not _cleanup_plain(state / _CLEANUP_STAGE) or not _cleanup_plain(state / 'logs'):
        raise ValueError('Cleanup paths must not contain links or reparse points')
    journal = state / 'logs' / _CLEANUP_JOURNAL
    if not journal.exists():
        return {'removed': [], 'pending': False}
    if not _cleanup_plain(journal) or not _cleanup_plain(state / 'logs/removals.jsonl'):
        raise ValueError('Cleanup journal and manifest must be plain files')
    rows = json.loads(journal.read_text(encoding='utf-8'))
    removed, pending = [], []
    from contextlib import closing
    with closing(RotatingLog(state / 'logs' / 'removals.jsonl')) as manifest:
        for row in rows:
            relative = Path(row['path'])
            if not relative.parts or relative.is_absolute() or relative.drive or '..' in relative.parts or relative.parts[0] == _CLEANUP_STAGE:
                raise ValueError('Invalid cleanup journal path')
            target = state / _CLEANUP_STAGE / relative
            try:
                if relative.parts[0] not in _OBSOLETE_ROOT_ENTRIES and not (relative.parts[0] == 'sessions-files' and target.suffix.lower() == '.archhub'):
                    raise OSError('unidentified entry retained')
                # Re-check locks/links: a process may have opened it since staging.
                if target.exists():
                    for file in _entry_files(target):
                        if _protected_file(file.relative_to(state)) or file.suffix.lower() == '.archhub':
                            from .session_files import read_document, verification_document
                            if file.suffix.lower() != '.archhub' or not verification_document(read_document(file)):
                                raise OSError('new user data in staged entry retained')
                        _unlocked(file)
                    manifest.write(json.dumps({**row, 'status': 'removing'}) + '\n')
                    manifest.flush()
                    if target.is_dir():
                        shutil.rmtree(target)
                    else:
                        target.unlink()
                manifest.write(json.dumps({**row, 'status': 'removed'}) + '\n')
                manifest.flush()
                removed.append(row)
            except (OSError, ValueError):
                pending.append(row)
    if pending:
        JsonFile(journal, []).write(pending)
    else:
        journal.unlink()
        _remove_empty_stage(state / _CLEANUP_STAGE)
    return {'removed': removed, 'pending': bool(pending)}


# One recorded pre-installer Studio build, accepted only as the local origin.
_LIGHT_ORIGIN = "20261119-0904-665c785+light-f10-b598855b"
_LIGHT_METADATA_SHA256 = "cb5e86dcea424ecf57d57785749f7933f50a76542c55cac5154839c69c0adac8"


def installed_build_id(app_dir: Path) -> str:
    try:
        with (Path(app_dir) / "BUILD_ID").open(encoding="utf-8") as stream:
            value = stream.read(258).strip()
        if value == _LIGHT_ORIGIN:
            return value if _installed_build_time(app_dir, value) is not None else ""
        return value if re.fullmatch(r"[A-Za-z0-9._-]{1,256}", value) else ""
    except (OSError, ValueError):
        return ""


def _utc_build_time(value):
    if type(value) is not str or _UTC_BUILD_RE.fullmatch(value) is None:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _legacy_built_at(build_id):
    match = _LEGACY_PUBLIC_RE.fullmatch(build_id)
    if match is None:
        return None
    try:
        value = datetime.strptime("".join(match.groups()), "%Y%m%d%H%M%S")
    except ValueError:
        return None
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate update metadata field")
        result[key] = value
    return result


def _installed_build_time(app_dir, build_id):
    path = Path(app_dir) / "BUILD_METADATA.json"
    _plain(path)
    if not path.exists():
        return _utc_build_time(_legacy_built_at(build_id))
    with path.open("rb") as stream:
        raw = stream.read(4097)
    if len(raw) > 4096:
        raise ValueError("installed build metadata exceeds size budget")
    if build_id == _LIGHT_ORIGIN:
        if hashlib.sha256(raw).hexdigest() != _LIGHT_METADATA_SHA256:
            raise ValueError("Unrecognized local light build metadata")
        return _utc_build_time(json.loads(raw)["built_at"])
    try:
        data = json.loads(raw, object_pairs_hook=_unique_object)
    except (ValueError, UnicodeError):
        raise ValueError("installed build metadata is invalid") from None
    if (type(data) is not dict or set(data) != {"format", "build_id", "built_at"}
            or type(data["format"]) is not int or data["format"] != 1
            or data["build_id"] != build_id or _utc_build_time(data["built_at"]) is None):
        raise ValueError("installed build metadata does not match BUILD_ID or its ordering contract")
    return _utc_build_time(data["built_at"])


def _target_build_time(data):
    if "built_at" in data:
        return _utc_build_time(data["built_at"])
    return _utc_build_time(_legacy_built_at(data["build_id"]))


def _installed_matches_target(app_dir, data):
    current = installed_build_id(app_dir)
    if current != data["build_id"]:
        return False
    target = _target_build_time(data)
    return target is not None and _installed_build_time(app_dir, current) == target


def _installed_inventory_matches(app_dir):
    """The same manifest Setup verified against its embedded digest before publishing BUILD_ID."""
    # ArchHub.vbs also starts this module by file path.
    inventory = import_module(".host_addin_retarget", __package__) if __package__ else import_module("host_addin_retarget")

    app_dir = Path(app_dir)
    manifest, receipt = app_dir / "source-manifest.tsv", app_dir / inventory.RECEIPT
    for path in (manifest, receipt, app_dir / "BUILD_ID"):
        _plain(path)
    with manifest.open("rb") as stream:
        raw = stream.read(_RELEASE_BYTES + 1)
    with receipt.open("rb") as stream:
        installed = stream.read(_RELEASE_BYTES + 1)
    if len(raw) > _RELEASE_BYTES or len(installed) > _RELEASE_BYTES:
        return False
    evidence = json.loads(installed, object_pairs_hook=_unique_object)
    if (type(evidence) is not dict or evidence.get("manifest") != raw.decode("utf-8")
            or type(evidence.get("installed_at_ns")) is not int
            or not 0 < evidence["installed_at_ns"] <= (app_dir / "BUILD_ID").stat().st_mtime_ns):
        return False
    for relative, digest in inventory.manifest_rows(raw).items():
        path = app_dir / relative
        _plain(path)
        with path.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != digest:
                return False
    return True


def _ordering_refusal(app_dir, data, current):
    if not current:
        return "Installed build identity is missing; update ordering is unavailable."
    try:
        installed = _installed_build_time(app_dir, current)
    except (OSError, ValueError) as exc:
        return str(exc)
    target = _target_build_time(data)
    if installed is None or target is None:
        return "Build ordering is unknown; a dated installer/release is required before updating."
    if target <= installed:
        return "The offered build is not newer than the installed build; no update staged."
    return None


def release_feed_url() -> str:
    """GitHub Latest. A loopback ARCHHUB_UPDATE_FEED is the test feed and nothing else."""
    override = os.environ.get("ARCHHUB_UPDATE_FEED", "").strip()
    if not override:
        return RELEASE_API
    parts = urllib.parse.urlsplit(override)
    host = (parts.hostname or "").lower()
    if (parts.scheme == "http" and host in ("127.0.0.1", "localhost") and parts.port
            and not parts.username and not parts.password):
        return override
    return RELEASE_API


def _asset_url_allowed(url, tag, *, stable_feed) -> bool:
    if type(url) is not str or type(tag) is not str:
        return False
    if stable_feed == RELEASE_API:
        expected = ("https://github.com/Fargaly/ArchHub/releases/download/"
                    + urllib.parse.quote(tag, safe="") + "/" + ASSET_NAME)
        return url == expected
    feed, asset = urllib.parse.urlsplit(stable_feed), urllib.parse.urlsplit(url)
    return (asset.scheme == "http" and (asset.hostname or "").lower() in ("127.0.0.1", "localhost")
            and asset.hostname == feed.hostname and asset.port == feed.port
            and asset.path.endswith("/" + ASSET_NAME) and not asset.username and not asset.query)


_RELEASE_RETRY_WAITS = (2, 8)


def _read_cause(exc):
    """Name why the feed read failed, for the update log. Never includes a URL or header value."""
    code = getattr(exc, "code", None)
    if type(code) is int:
        headers = getattr(exc, "headers", None)
        limited = code in (403, 429) and headers is not None and headers.get("X-RateLimit-Remaining") == "0"
        return "HTTP %d%s" % (code, " rate limited" if limited else "")
    reason = getattr(exc, "reason", None)
    return type(reason if isinstance(reason, BaseException) else exc).__name__


def _transient(exc):
    code = getattr(exc, "code", None)
    return type(code) is not int or code in (403, 408, 429) or code >= 500


def read_latest_release_retrying(opener, waits, wait, **options):
    """The feed read, retried quietly on network faults, rate limits and server errors."""
    latest = read_latest_release(opener, **options)
    for pause in waits:
        if latest is not None or not read_latest_release.transient:
            break
        if wait(pause) is True:  # Event.wait: the desktop is closing; no further feed request
            break
        latest = read_latest_release(opener, **options)
    return latest


def read_latest_release(opener=urllib.request.urlopen, *, channel="stable") -> dict | None:
    """Return validated release identity and build time, or None.

    Missing chronology on an opaque old release is returned as built_at=None so
    callers can report unknown ordering without downloading its installer.
    A pre-release is not returned. ``saw_prerelease`` records that fact for the
    same response, so auto-update can ignore it without a second request.
    """
    read_latest_release.saw_prerelease = False
    read_latest_release.cause, read_latest_release.transient = "release unreadable", False
    try:
        if channel not in ("stable", "preview"):
            raise ValueError("update channel must be stable or preview")
        url = release_feed_url() if channel == "stable" else RELEASE_API.rsplit("/", 1)[0] + "?per_page=20"
        request = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "ArchHub"})
        token = _github_token() if url.startswith("https://api.github.com/") else ""
        if token:
            request.add_unredirected_header("Authorization", "Bearer " + token)
        with opener(request, timeout=15) as response:
            raw = response.read(_RELEASE_BYTES + 1)
        if len(raw) > _RELEASE_BYTES:
            return None
        data = json.loads(raw)
        if channel == "preview":
            if not isinstance(data, list):
                return None
            # GitHub's list order is not build order (an older stable was listed before a newer pre-release):
            # the newest validated build wins; a release without a valid identity or date is never chosen.
            dated = [(_utc_build_time(found["built_at"]), index, item, found) for index, item in enumerate(data)
                     if isinstance(item, dict) and not item.get("draft")
                     for found in [_release_identity(item, channel)] if found is not None
                     and _utc_build_time(found["built_at"]) is not None]
            if not dated:
                return None
            _when, _index, item, found = max(dated, key=lambda row: (row[0], -row[1]))
            read_latest_release.saw_prerelease = item.get("prerelease") is True
            read_latest_release.cause = ""
            return found
        read_latest_release.saw_prerelease = (
            isinstance(data, dict) and data.get("prerelease") is True and not data.get("draft"))
        if not isinstance(data, dict) or data.get("draft") or data.get("prerelease"):
            return None
        found = _release_identity(data, channel)
        if found is not None:
            read_latest_release.cause = ""
        return found
    except OSError as exc:
        read_latest_release.saw_prerelease = False
        read_latest_release.cause, read_latest_release.transient = _read_cause(exc), _transient(exc)
        return None
    except (ValueError, TypeError):
        read_latest_release.saw_prerelease = False
        return None


def _github_token() -> str:
    """GH_TOKEN, GITHUB_TOKEN or the signed-in gh CLI; "" when none. The anonymous API quota is shared per IP."""
    token = (os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN") or "").strip()
    if token:
        return token
    import shutil
    gh = shutil.which("gh")
    if not gh:
        return ""
    try:
        run = subprocess.run([gh, "auth", "token"], capture_output=True, text=True, timeout=UPDATE_FEED_NODE["params"]["gh_seconds"],
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError):
        return ""
    return run.stdout.strip() if run.returncode == 0 else ""


def _release_record(opener, url):
    request = urllib.request.Request(url, headers={"User-Agent": "ArchHub"})
    with opener(request, timeout=UPDATE_FEED_NODE["params"]["request_seconds"]) as response:
        raw = response.read(65537)
    if len(raw) > 65536:
        raise ValueError("release record exceeds size budget")
    data = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=_unique_object)
    if type(data) is not dict:
        raise ValueError("release record is not an object")
    return data


def read_offer_release(opener=urllib.request.urlopen) -> dict | None:
    """The website offer, used when the GitHub API is rate limited or unreachable.

    Accepted only when the GitHub release of the offered build serves the same
    release.json (build, date, installer name, size, SHA-256). The installer URL
    is the fixed GitHub release URL for that build. ``cause`` says why it was refused.
    """
    read_offer_release.cause = ""
    try:
        offer = _release_record(opener, OFFER_URL)
        build = offer.get("build_id")
        if type(build) is not str or not re.fullmatch(r"[A-Za-z0-9._-]{1,128}", build):
            raise ValueError("offer has no valid build id")
        tag = "build-" + build
        record = _release_record(opener, RELEASE_RECORD % urllib.parse.quote(tag, safe=""))
        fields = ("build_id", "built_at", "asset_name", "asset_sha256", "asset_bytes")
        if any(offer.get(key) != record.get(key) for key in fields):
            raise ValueError("offer does not match the GitHub release record of " + tag)
        sha, size = record.get("asset_sha256"), record.get("asset_bytes")
        if (record.get("asset_name") != ASSET_NAME or type(sha) is not str
                or not re.fullmatch(r"[0-9a-fA-F]{64}", sha)
                or type(size) is not int or not 0 < size <= _INSTALLER_BYTES
                or _utc_build_time(record.get("built_at")) is None):
            raise ValueError("GitHub release record of " + tag + " is incomplete")
        url = ("https://github.com/Fargaly/ArchHub/releases/download/"
               + urllib.parse.quote(tag, safe="") + "/" + ASSET_NAME)
        return {"build_id": build, "built_at": record["built_at"], "sha256": sha.lower(), "url": url, "tag": tag}
    except OSError as exc:
        read_offer_release.cause = _read_cause(exc)
    except (ValueError, TypeError, UnicodeError) as exc:
        read_offer_release.cause = str(exc) or type(exc).__name__
    return None


def _release_identity(data, channel):
    """One release's validated identity (build id, built_at, installer digest, asset URL, tag), or None."""
    body, assets, tag = data.get("body"), data.get("assets"), data.get("tag_name")
    if (not isinstance(body, str) or not isinstance(assets, list)
            or not isinstance(tag, str) or not 0 < len(tag) <= 256):
        return None
    builds, hashes = _BUILD_RE.findall(body), _SHA_RE.findall(body)
    build_fields = re.findall(r"(?m)^[ \t]*BUILD_ID\b[^\r\n]*", body)
    hash_fields = re.findall(r"(?m)^[ \t]*SHA256 " + re.escape(ASSET_NAME) + r"\b[^\r\n]*", body)
    assets = [a for a in assets if isinstance(a, dict) and a.get("name") == ASSET_NAME]
    if (len(builds) != 1 or len(hashes) != 1 or len(assets) != 1
            or len(build_fields) != 1 or len(hash_fields) != 1):
        return None
    dates = re.findall(r"(?m)^[ \t]*BUILT_AT\b[^\r\n]*", body)
    if dates:
        if len(dates) != 1 or not dates[0].startswith("BUILT_AT: "):
            return None
        built_at = dates[0][len("BUILT_AT: "):]
        if _utc_build_time(built_at) is None:
            return None
    else:
        built_at = _legacy_built_at(builds[0])
    asset = assets[0]
    url = asset.get("browser_download_url")
    stable_feed = release_feed_url() if channel == "stable" else RELEASE_API
    size = asset.get("size")
    if (not _asset_url_allowed(url, tag, stable_feed=stable_feed)
            or (size is not None and (type(size) is not int or not 0 < size <= _INSTALLER_BYTES))):
        return None
    return {"build_id": builds[0], "built_at": built_at,
            "sha256": hashes[0].lower(), "url": url, "tag": tag}


def _published_prerelease(opener, channel="stable") -> bool:
    """True when the release just read was a pre-release. Stable auto-update ignores it."""
    return read_latest_release.saw_prerelease is True


def _plain(path):
    for item in (path, *path.parents):
        if item.exists() or item.is_symlink():
            stat = item.lstat()
            if item.is_symlink() or getattr(stat, "st_file_attributes", 0) & 0x400:
                raise ValueError("update paths must not contain links or reparse points")


@contextmanager
def _locked(state_dir):
    if not _THREAD_LOCK.acquire(blocking=False):
        raise ValueError("update operation busy")
    stream, acquired = None, False
    try:
        state = Path(state_dir)
        if not state.is_absolute():
            raise ValueError("explicit absolute update state directory required")
        updates = state / "updates"
        _plain(updates)
        updates.mkdir(parents=True, exist_ok=True)
        lock_path = updates / "operation.lock"
        _plain(lock_path)
        stream = lock_path.open("a+b")
        if stream.seek(0, 2) == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        acquired = True
        yield updates
    finally:
        try:
            if acquired:
                stream.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        finally:
            try:
                if stream is not None:
                    stream.close()
            finally:
                _THREAD_LOCK.release()


def _marker(updates, data):
    # Runtime projections must not leave a stale "awaiting_boot" beside phase.
    data = {key: value for key, value in data.items() if key not in
            ("staged", "status", "installed_build_id", "installer", "reason", "bytes_verified")}
    fd, name = tempfile.mkstemp(prefix=".marker-", suffix=".tmp", dir=updates)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(data, stream, separators=(",", ":"))
            stream.flush()
            os.fsync(stream.fileno())
        _plain(updates / "staged.json")
        os.replace(temporary, updates / "staged.json")
    finally:
        temporary.unlink(missing_ok=True)


def _digest(path):
    _plain(path)
    if not path.is_file() or not 0 < path.stat().st_size <= _INSTALLER_BYTES:
        raise ValueError("staged installer size invalid")
    digest, count = hashlib.sha256(), 0
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(65536), b""):
            count += len(chunk)
            if count > _INSTALLER_BYTES:
                raise ValueError("installer exceeds size budget")
            digest.update(chunk)
    return digest.hexdigest()


def _payload_files(app):
    """Only installer-owned product bytes; never the graph, profile or environment."""
    app = Path(app)
    for name in _PAYLOAD_FILES:
        path = app / name
        _plain(path)
        if path.is_file():
            yield path
    for name in _PAYLOAD_DIRS:
        root = app / name
        _plain(root)
        for path in sorted(root.rglob("*")) if root.exists() else ():
            _plain(path)
            if (path.is_file() and "__pycache__" not in path.parts
                    and not path.name.startswith(('cell_', 'universal_'))
                    and not (name == 'nodelang' and path.stem in ('application_server', 'application_machine_transport',
                                          'postgres_cell_journal', 'persistence', 'app_brain', 'canvas_graph_owner',
                                          'core', 'laws_structure', 'laws_effect', 'laws_relation', 'laws_surface',
                                          'laws_decision', 'serve_canvas', 'graph_api'))
                    and path.suffix.lower() not in (".pyc", ".pyo", ".sqlite3", ".db", ".key", ".pem")
                    and path.suffix.casefold().lstrip('.').partition('-')[0] not in ('sqlite', 'sqlite3', 'db')
                    and not path.name.startswith(".env")):
                yield path


def _discard_rollback_copy(updates):
    """Do not keep a product-sized rollback archive on this machine."""
    target = Path(updates) / "previous-build.zip"
    _plain(target)
    target.unlink(missing_ok=True)


def _rollback(updates, app, data, reason):
    """Report the failure and drop any rollback archive. Product bytes are not rewritten."""
    del app
    _discard_rollback_copy(updates)
    return {**data, "confirmed": False, "rolled_back": False, "reason": reason}


def _read_stage_marker(updates):
    marker = updates / "staged.json"
    _plain(marker)
    with marker.open("rb") as stream:
        raw = stream.read(16385)
    if len(raw) > 16384:
        raise ValueError("staged marker exceeds size budget")
    data = json.loads(raw, object_pairs_hook=_unique_object)
    if (not isinstance(data, dict) or not isinstance(data.get("build_id"), str)
            or not re.fullmatch(r"[A-Za-z0-9._-]{1,256}", data["build_id"])
            or not isinstance(data.get("sha256"), str)
            or not re.fullmatch(r"[0-9a-fA-F]{64}", data["sha256"])):
        raise ValueError("staged identity invalid")
    return data


def _status(updates, app_dir, *, verify_confirmed=False, reconcile=False):
    try:
        data = _read_stage_marker(updates)
    except FileNotFoundError:
        return {"staged": False, "build_id": "", "status": "none", "reason": "nothing staged"}
    phase = data.get("phase", "staged")
    if phase not in ("staged", "applying", "awaiting_boot", "confirmed", "rolled_back"):
        raise ValueError("staged phase invalid")
    target = updates / ASSET_NAME
    current = installed_build_id(app_dir)
    resume_direct_install = phase == "rolled_back" and reconcile and current == data["build_id"]
    if phase == "rolled_back" and not resume_direct_install:
        recorded_reason = " ".join(str(data.get("rollback_reason") or "").split())[:512]
        reason = ("Matching build needs verification at boot." if current == data["build_id"]
                  else "Previous build restored after a failed update; "
                  + (recorded_reason + "; " if recorded_reason else "") + "waiting for a newer release.")
        return {**data, "staged": False, "retained": True, "status": phase, "reason": reason}
    if phase == "applying":
        # The attempt reservation survives loss or alteration of its package.
        # Returning 'unavailable' here would let a launcher boot partial code.
        try:
            verified = _digest(target) == data["sha256"].lower()
            reason = "installation requires reconciliation"
            if not verified:
                reason += "; installer bytes changed"
        except (OSError, ValueError) as exc:
            verified = False
            reason = "installation requires reconciliation; " + str(exc)
        return {**data, "staged": True, "status": "applying", "bytes_verified": verified,
                "installed_build_id": current, "installer": str(target), "reason": reason}
    # A confirmed package is retained evidence, not an executable candidate.
    # Avoid reading up to 1 GiB on each normal startup. Effect paths opt in.
    confirmed_current = phase == "confirmed" and current == data["build_id"]
    if verify_confirmed or not confirmed_current:
        if _digest(target) != data["sha256"].lower():
            raise ValueError("staged installer no longer matches published SHA-256")
    _plain(target)
    status = "awaiting_boot" if resume_direct_install or (current == data["build_id"] and phase == "staged") else phase
    if status == "staged":
        refusal = _ordering_refusal(app_dir, data, current)
        if refusal:
            # This exact owned package remains evidence; it is not a ready
            # installation and does not block a later, strictly newer release.
            return {**data, "staged": False, "retained": True, "status": "not_ready",
                    "installed_build_id": current, "installer": str(target),
                    "bytes_verified": True, "reason": refusal}
    return {**data, "staged": True, "status": status, "installed_build_id": current,
            "installer": str(target), "reason": status,
            "bytes_verified": verify_confirmed or not confirmed_current}


def _failure(exc, **extra):
    return {"staged": False, "build_id": "", "status": "unavailable", "reason": str(exc), **extra}


def auto_install_held(state_dir: Path) -> str:
    """Why the staged build may not be installed automatically again; "" when it may.

    Set when an apply was refused before Setup. Without it the desktop saw the same
    staged build as ready again, closed, was refused, reopened, and repeated every minute.
    Metadata only: the installer is not hashed here, so the desktop may ask on every tick.
    """
    try:
        data = _read_stage_marker(Path(state_dir) / "updates")
    except FileNotFoundError:
        return ""
    except (OSError, ValueError) as exc:
        return "update marker unreadable (%s)" % type(exc).__name__
    held = data.get("auto_held")
    return held if data.get("phase", "staged") == "staged" and isinstance(held, str) and held else ""


def staged_update(state_dir: Path, app_dir: Path) -> dict:
    """Verify candidates; confirmed current builds use metadata only, never apply."""
    try:
        with _locked(state_dir) as updates:
            return _status(updates, app_dir)
    except (OSError, ValueError) as exc:
        return _failure(exc)


def _keep_held_stage(held, latest) -> bool:
    """Keep a staged installer while it is still the newest release we can see.

    A package older than GitHub Latest must not block that release. An install
    already in progress is left untouched. No release information keeps the
    package that is already verified.
    """
    if held.get("status") == "applying":
        return True
    if not isinstance(latest, dict):
        return True
    if held.get("build_id") == latest.get("build_id"):
        return True
    held_time, latest_time = _target_build_time(held), _target_build_time(latest)
    if held_time is not None and latest_time is not None and latest_time <= held_time:
        return True
    return False


def stage_if_newer(state_dir: Path, app_dir: Path, opener=urllib.request.urlopen, *, cancellation_event=None, channel="stable") -> dict:
    """Download bounded bytes under exclusive staging ownership; never install.

    ``source`` names where the release identity came from; ``fallback`` why the website offer was refused.
    """
    seen = {}
    result = _stage_if_newer(state_dir, app_dir, opener, cancellation_event, channel, seen)
    return {**result, **seen}


def _stage_if_newer(state_dir, app_dir, opener, cancellation_event, channel, seen):
    partial = None
    def check_cancelled():
        if cancellation_event is not None and cancellation_event.is_set():
            raise ValueError("update download cancelled for application shutdown")
    try:
        check_cancelled()
        with _locked(state_dir) as updates:
            check_cancelled()
            held = _status(updates, app_dir)
            # A build waiting to prove boot, or an install in progress, is not
            # replaced and is not a reason to call the release feed.
            if held["staged"] and held["status"] in ("applying", "awaiting_boot"):
                return held
            wait = cancellation_event.wait if cancellation_event is not None else time.sleep
            options = {} if channel == "stable" else {"channel": channel}
            latest = read_latest_release_retrying(opener, _RELEASE_RETRY_WAITS, wait, **options)
            if latest is not None:
                seen["source"] = "api.github.com"
            elif (channel == "stable" and release_feed_url() == RELEASE_API
                  and (read_latest_release.transient or read_latest_release.cause == "HTTP 401")):
                check_cancelled()
                latest = read_offer_release(opener)
                if latest is not None:
                    seen["source"] = OFFER_URL + " (verified against GitHub release " + latest["tag"] + ")"
                else:
                    seen["fallback"] = read_offer_release.cause
            current = installed_build_id(app_dir)
            check_cancelled()
            # A staged installer older than GitHub Latest must not block it.
            if held["staged"] and held["status"] != "confirmed" and _keep_held_stage(held, latest):
                return held
            if latest is None:
                if channel == "stable" and _published_prerelease(opener):
                    return {"staged": False, "applied": False, "build_id": "", "status": "ignored",
                            "reason": "pre-release ignored"}
                return {"staged": False, "build_id": "", "reason": "no release information",
                        "cause": read_latest_release.cause}
            if channel != "stable" and _published_prerelease(opener, channel):
                # A preview may be staged for the Update button. Auto-install refuses it.
                latest = {**latest, "prerelease": True}
            if not current:
                return {"staged": False, "reason": "Installed build identity is missing; install a versioned ArchHub release first.", "build_id": ""}
            if held.get("status") == "rolled_back" and latest["build_id"] == held["build_id"]:
                return {**held, "staged": False}
            if latest["build_id"] == current:
                return {"staged": False, "reason": "up to date", "build_id": current}
            refusal = _ordering_refusal(app_dir, latest, current)
            if refusal:
                return {"staged": False, "status": "not_ready", "reason": refusal,
                        "build_id": latest["build_id"]}
            target = updates / ASSET_NAME
            _plain(target)
            if target.exists() and not held["staged"] and not held.get("retained"):
                raise ValueError("unowned installer already exists")
            fd, name = tempfile.mkstemp(prefix=".download-", suffix=".part", dir=updates)
            partial = Path(name)
            deadline, count = time.monotonic() + 300, 0
            with os.fdopen(fd, "wb") as out:
                request = urllib.request.Request(latest["url"], headers={"User-Agent": "ArchHub"})
                with opener(request, timeout=30) as response:
                    while True:
                        check_cancelled()
                        chunk = response.read(65536)
                        check_cancelled()
                        if time.monotonic() > deadline:
                            raise ValueError("download deadline exceeded")
                        if not chunk:
                            break
                        count += len(chunk)
                        if count > _INSTALLER_BYTES:
                            raise ValueError("download exceeds size budget")
                        out.write(chunk)
                out.flush()
                os.fsync(out.fileno())
            if _digest(partial) != latest["sha256"]:
                raise ValueError("download did not match published SHA-256")
            check_cancelled()
            refusal = _ordering_refusal(app_dir, latest, installed_build_id(app_dir))
            if refusal:
                return {"staged": False, "status": "not_ready", "reason": refusal,
                        "build_id": latest["build_id"]}
            check_cancelled()
            os.replace(partial, target)
            partial = None
            _marker(updates, {**latest, "phase": "staged"})
            return {**_status(updates, app_dir), "downloaded": True}
    except (OSError, ValueError) as exc:
        return _failure(exc)
    finally:
        if partial is not None:
            partial.unlink(missing_ok=True)


_LAUNCHER_HOLDS_INSTALL = "An in-folder launcher must release the install before Setup"


def _owned_executable(exe, root):
    """The process image when it is an absolute path inside the install folder, else None.

    psutil reports some system processes by bare name ("Registry", "System",
    "Memory Compression"). Resolving a bare name joins it to the current folder,
    which is the install folder under ArchHub.vbs, so "Registry" looked like an
    installed program and the update refused on it at every launch.
    """
    if type(exe) is not str or not os.path.isabs(exe):
        return None
    path = Path(exe).resolve()
    return path if path.is_relative_to(root) else None


def _session_zero(pid):
    """True for services and kernel processes (Windows session 0). ArchHub never runs there."""
    if os.name != "nt":
        return False
    import ctypes
    from ctypes import wintypes
    session = wintypes.DWORD()
    if not ctypes.windll.kernel32.ProcessIdToSessionId(wintypes.DWORD(pid), ctypes.byref(session)):
        return True  # unreadable session: never ours to stop
    return session.value == 0


_CONNECTOR_DEFERRED = "deferred: "
_SETUP_AGENT_BUSY = "installer failed: An agent is still using ArchHub ("
_AGENT_BUSY_NOTICE = "Agents were busy, so the update waits. It stays downloaded and installs when they finish."
_UNSUPERVISED_TRANSPORT = (_CONNECTOR_DEFERRED + "an agent's ArchHub connector runs without its supervisor; "
                           "Setup would cut that agent's connection, so the update waits for it to end")
# Programs that host agent connectors. A process below one of them is that agent's work, never ArchHub's to stop.
_AGENT_HOSTS = frozenset(("cursor.exe", "claude.exe", "codex.exe", "opencode.exe", "node.exe", "code.exe",
                          "gemini.exe", "goose.exe", "windsurf.exe", "antigravity.exe"))


def _process_chain(process):
    """[(exe, command line)] for the process and each ancestor, as far as they can be read."""
    chain = []
    try:
        for item in [process, *process.parents()]:
            command = item.cmdline()
            chain.append((str(item.exe() or ""), " ".join(command) if isinstance(command, list) else ""))
    except Exception as error:  # noqa: BLE001 - a process that ends or hides its details mid-walk keeps what was read
        chain.append(("", "ancestry unreadable (%s)" % type(error).__name__))
    return chain


def _agent_transport(chain, root=None):
    """None for ArchHub's own processes; "supervised" or "unsupervised" for an agent-hosted connector.

    Agents start ArchHub's connector through mcp_supervisor (ArchHub-Runtime, outside the install).
    It pauses its child while Setup's .archhub-installing marker exists and reconnects after, so the
    agent keeps its connection. An agent-hosted process without that supervisor would just be cut.
    """
    commands = " ".join(command for _exe, command in chain)
    # Hosts outside the install only: BABOOM's own goose.exe ships inside it and is ArchHub's.
    hosted = any(Path(exe).name.lower() in _AGENT_HOSTS and _owned_executable(exe, root) is None
                 for exe, _command in chain[1:]) if root is not None else False
    if not (hosted or "native_agent_mcp" in commands or "mcp_supervisor" in commands):
        return None
    return "supervised" if any("mcp_supervisor" in command for _exe, command in chain[1:]) else "unsupervised"


def _install_processes(root, process_iter=None, session_zero=None):
    """(process, pid, executable) for each process the install-folder stop would consider.

    Only an absolute image path inside the install counts; session_zero, when given, also skips services.
    """
    import psutil
    for process in (process_iter or psutil.process_iter)(["pid", "exe"]):
        try:
            pid = process.info.get("pid")
            executable = _owned_executable(process.info.get("exe"), root)
        except (psutil.Error, OSError, ValueError):
            continue
        if executable is not None and pid not in (0, 4) and not (session_zero and session_zero(pid)):
            yield process, pid, executable


def _can_terminate(pid) -> bool:
    """Ask Windows for the right to end the process without ending it (OpenProcess, PROCESS_TERMINATE)."""
    if os.name != "nt":
        return True
    import ctypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.restype = ctypes.c_void_p
    handle = kernel.OpenProcess(0x0001, False, int(pid))
    if not handle:
        return False
    kernel.CloseHandle(ctypes.c_void_p(handle))
    return True


def preflight_refusal(app_dir: Path, *, desktop_pids, process_iter=None, can_terminate=None, chain_of=None) -> str:
    """Why an install started now would be refused before Setup; "" when nothing is known to refuse it.

    Asked by the desktop before it closes for an automatic install, so a refusal keeps the Studio open.
    The desktop's own processes are left out: they end when it closes. Nothing is stopped or signalled.
    """
    root = Path(app_dir).resolve()
    can_terminate = can_terminate or _can_terminate
    chain_of = chain_of or _process_chain
    for process, pid, _executable in _install_processes(root, process_iter):
        if pid in desktop_pids:
            continue
        transport = _agent_transport(chain_of(process), root)
        if transport == "unsupervised":
            return _UNSUPERVISED_TRANSPORT
        if transport is None and not can_terminate(pid):
            return "runtime process %d refused termination" % pid
    return ""


def connector_install_deferred(reason: str) -> bool:
    """These refusals clear with the connector, so keep the build eligible for a retry."""
    return reason.startswith(_CONNECTOR_DEFERRED)


def hold_auto_install(state_dir: Path, reason: str) -> bool:
    """Record that the staged build is not installed automatically again. True when recorded."""
    try:
        with _locked(state_dir) as updates:
            data = _read_stage_marker(updates)
            if data.get("phase", "staged") != "staged":
                return False
            _marker(updates, {**data, "auto_held": str(reason)[:512]})
            return True
    except (OSError, ValueError) as exc:
        append_update_log(state_dir, "update: error hold not recorded (%s)" % exc)
        return False


def stop_runtime_processes(app_dir: Path, *, process_iter=None, wait_seconds: float = 5.0,
                           session_zero=None, chain_of=None) -> list:
    """Stop every other process started from the install folder before the installer copies.

    A leftover executable under the install folder held a file, the silent replace failed
    with Windows error 32 (file in use), and the suppressed dialog answered Abort.
    The out-of-folder updater and its Windows venv redirector must survive Setup.
    A supervisor outside the install folder, including agent connectors, is not stopped
    and is not a reason to refuse the update. An agent-hosted connector is never stopped:
    a supervised one is paused by its own supervisor during Setup; an unsupervised one
    defers the whole update, before anything is stopped.
    """
    import psutil
    session_zero = session_zero or _session_zero
    chain_of = chain_of or _process_chain
    root = Path(app_dir).resolve()
    updater = psutil.Process()
    ancestors = [ancestor.pid for ancestor in updater.parents()]
    candidates = []
    for process, pid, executable in _install_processes(root, process_iter, session_zero):
        if pid == updater.pid:
            continue
        if pid in ancestors:
            if (os.name == "nt" and pid == ancestors[0] and executable.parent == root / ".venv" / "Scripts"
                    and executable.name in ("python.exe", "pythonw.exe")
                    and executable == Path(sys.executable).resolve()
                    and not Path(updater.exe()).resolve().is_relative_to(root)):
                continue
            raise ValueError(_LAUNCHER_HOLDS_INSTALL)
        transport = _agent_transport(chain_of(process), root)
        if transport == "unsupervised":
            raise ValueError(_UNSUPERVISED_TRANSPORT)  # nothing has been stopped yet
        if transport is None:
            candidates.append(process)
    stopped = []
    for process in candidates:
        try:
            process.terminate()
            stopped.append(process)
        except psutil.NoSuchProcess:
            continue
        except psutil.AccessDenied as error:
            raise OSError("runtime process %d refused termination" % process.pid) from error
    if stopped:
        _gone, alive = psutil.wait_procs(stopped, timeout=wait_seconds)
        for process in alive:
            try:
                process.kill()
            except psutil.NoSuchProcess:
                continue  # it exited between the wait and the kill
            except psutil.Error as error:
                raise OSError("runtime process %d could not be stopped" % process.pid) from error
        if alive:
            _, remaining = psutil.wait_procs(alive, timeout=wait_seconds)
            if remaining:
                raise OSError("runtime processes still running: " + ", ".join(str(p.pid) for p in remaining))
    return [process.pid for process in stopped]


DRAIN_REQUEST = "drain-request.json"  # ArchHub-Runtime\\connectors: while it names an attempt, no new call starts


def _runtime_connectors(app_dir) -> Path:
    return Path(app_dir).parent / "ArchHub-Runtime" / "connectors"


def connector_acknowledgements(app_dir: Path, attempt: str | None, *, process_iter=None) -> list:
    """For each live supervisor of this install, why it has NOT confirmed `attempt` idle ([] = all confirmed).

    Confirmed means its connectors\\<pid>.json is valid JSON naming this attempt, with admission closed and
    exactly zero pending calls. Anything else holds: no report (an older supervisor), unreadable or invalid
    JSON, a missing or non-integer count, admission still open, another attempt, or a call in flight.
    With no attempt, preflight predicts readiness from open, idle reports without closing admission.
    """
    import psutil
    script = str(Path(app_dir).parent / "ArchHub-Runtime" / "mcp_supervisor.py").casefold()
    folder = _runtime_connectors(app_dir)
    reasons = []
    for process in (process_iter or psutil.process_iter)(["pid", "cmdline"]):
        try:
            command = process.info.get("cmdline") or []
            pid = process.info["pid"]
        except (psutil.Error, OSError, KeyError, TypeError, AttributeError):
            continue
        if not any(str(part).casefold() == script for part in command):
            continue
        try:
            report = json.loads((folder / ("%d.json" % pid)).read_text(encoding="utf-8"))
        except FileNotFoundError:
            reasons.append("pid %d: no report (older supervisor)" % pid)
            continue
        except (OSError, ValueError) as error:
            reasons.append("pid %d: report unreadable (%s)" % (pid, type(error).__name__))
            continue
        pending = report.get("pending") if isinstance(report, dict) else None
        if type(pending) is not int or isinstance(pending, bool):
            reasons.append("pid %d: report has no call count" % pid)
        elif report.get("attempt") != attempt:
            reasons.append("pid %d: has not acknowledged this attempt" % pid)
        elif attempt is None and report.get("admission") != "open":
            reasons.append("pid %d: admission is not open" % pid)
        elif attempt is not None and report.get("admission") != "closed":
            reasons.append("pid %d: admission still open" % pid)
        elif pending != 0:
            reasons.append("pid %d: %d call(s) in flight" % (pid, pending))
    return reasons


def reopen_connectors(app_dir: Path, attempt: str, *, sleep=time.sleep, tries: int = 40, pause: float = 0.05) -> None:
    """Remove this attempt's drain request so supervisors admit calls again (a newer attempt's is left alone).

    A supervisor polling the file holds it open for a moment; Windows then refuses the delete (error 32).
    One such moment (2026-11-25) left a finished install unresolved, so retry briefly.
    """
    request = _runtime_connectors(app_dir) / DRAIN_REQUEST
    for left in range(tries, 0, -1):
        try:
            if json.loads(request.read_text(encoding="utf-8")).get("attempt") == attempt:
                request.unlink()
            return
        except FileNotFoundError:
            return
        except PermissionError as error:  # sharing violation while a supervisor reads it
            if left == 1:
                raise OSError("connector drain request could not be removed: %s" % error) from error
            sleep(pause)
        except (OSError, ValueError, AttributeError) as error:
            raise OSError("connector drain request could not be removed: %s" % error) from error


def drain_connectors(app_dir: Path, attempt: str, *, acknowledgements=connector_acknowledgements,
                     sleep=time.sleep, bound: float = 10.0) -> None:
    """Close admission for `attempt`, then wait until every live supervisor confirms it idle; raise to defer.

    Order matters: admission is closed first, so no call can start after the all-clear. A deferral
    reopens admission before it is reported, and nothing has been stopped or signalled to Setup yet.
    """
    from nodelang.canvas_triggers import TRIGGER_NODE

    folder = _runtime_connectors(app_dir)
    folder.mkdir(parents=True, exist_ok=True)
    temporary = folder / (DRAIN_REQUEST + ".tmp")
    temporary.write_text(json.dumps({"attempt": attempt}), encoding="utf-8")
    os.replace(temporary, folder / DRAIN_REQUEST)
    poll = TRIGGER_NODE["params"]["file_poll_floor_seconds"]
    waited = 0
    while True:
        reasons = acknowledgements(app_dir, attempt)
        if not reasons:
            return
        if waited >= bound:
            # Founder 2026-11-25 "بيقفل كل حاجة ويعمل ريستارت عادي": Update closes busy agent connections and
            # goes ahead. Admission stays closed; Setup's install marker makes each supervisor end its connector.
            print("update: closing busy agent connections: " + "; ".join(reasons)[:400], file=sys.stderr, flush=True)
            return
        sleep(poll)
        waited += poll


def _setup_ancestors(depth=4):
    """The pids above this process: Setup, then the updater that launched it."""
    import psutil
    pids, process = [], psutil.Process()
    for _ in range(depth):
        try:
            process = process.parent()
        except psutil.Error:
            break
        if process is None:
            break
        pids.append(process.pid)
    return pids


def setup_admission(app_dir: Path, build_id: str, *, expected: str | None = None,
                    acknowledgements=connector_acknowledgements, drain=drain_connectors, clock=time.time_ns,
                    ancestors=_setup_ancestors) -> tuple:
    """Setup's own entry into the same drain, before its marker or any program file: ("existing"|"owned", attempt).

    Setup inherits a drain request only from the updater invocation that launched it: the attempt it was handed
    (/ARCHHUBDRAIN), or, for an older updater that passes none, an attempt named for this build and a live
    ancestor pid ("<build>-<pid>-<ns>", apply_staged's form), and only when every supervisor confirms it idle.
    Any other request (malformed, empty, foreign, a stale earlier Setup's) holds Setup and is left as it is. With
    no request, a Setup run by hand closes admission under its own attempt and waits for every supervisor to
    confirm idle; a supervisor that cannot report (an older script, an unreadable report) holds it first. Holding
    raises ValueError with nothing touched. The caller reopens an owned attempt when Setup ends.
    """
    request = _runtime_connectors(app_dir) / DRAIN_REQUEST
    try:
        data = json.loads(request.read_text(encoding="utf-8"))
    except FileNotFoundError:
        data = None
    except (OSError, ValueError) as error:
        raise ValueError(_CONNECTOR_DEFERRED + "the connector drain request is unreadable (%s); it was left as it is"
                         % type(error).__name__) from None
    if data is not None:
        held = data.get("attempt") if isinstance(data, dict) and set(data) == {"attempt"} else None
        if not isinstance(held, str) or not held.strip():
            raise ValueError(_CONNECTOR_DEFERRED + "the connector drain request names no install attempt; it was left as it is")
        ours = (held == expected) if expected else any(held.startswith("%s-%d-" % (build_id, pid)) for pid in ancestors())
        if not ours:
            raise ValueError(_CONNECTOR_DEFERRED + "a connector drain request from another install attempt (%s) is in place; "
                             "it was left as it is" % held[:80])
        # A busy agent connection does not hold Setup: the install marker makes its supervisor close it.
        return "existing", held
    if expected:
        raise ValueError(_CONNECTOR_DEFERRED + "the updater's connector drain request is missing; nothing touched")
    attempt = "setup-%s-%d-%d" % (build_id, os.getpid(), clock())
    drain(Path(app_dir), attempt)  # waits briefly for calls in flight, then goes ahead
    return "owned", attempt


def apply_staged(state_dir: Path, app_dir: Path, runner=subprocess.run, *, before_apply=None,
                 stop_runtime=stop_runtime_processes, drain=drain_connectors, expect=None) -> dict:
    """Call before_apply() under staging ownership, then attempt once; retain package.

    The trusted callback raises to refuse recovery admission. It must not call
    staging APIs recursively; this operation holds their exclusive lock.
    """
    attempted_build = None
    try:
        with _locked(state_dir) as updates:
            data = _status(updates, app_dir, verify_confirmed=True)
            if expect is not None and (data.get("build_id"), str(data.get("sha256", "")).lower()) != (
                    expect[0], str(expect[1]).lower()):
                # The staged package is not the one the caller selected (replaced at the handoff): touch nothing.
                return {**data, "applied": False, "status": "not_ready",
                        "reason": "staged build changed since it was selected; nothing done"}
            if not data["staged"]:
                return {**data, "applied": False}
            if data["installed_build_id"] == data["build_id"]:
                return {**data, "applied": False, "reason": "already installed; " + data["status"]}
            if data["status"] != "staged":
                return {**data, "applied": False, "reason": "prior attempt requires reconciliation"}
            refusal = _ordering_refusal(app_dir, data, installed_build_id(app_dir))
            if refusal:
                return {**data, "staged": False, "applied": False, "status": "not_ready", "reason": refusal}
            if not Path(app_dir).is_absolute():
                raise ValueError("absolute application directory required")
            _plain(Path(app_dir))
            if before_apply is not None:
                before_apply()
            refusal = _ordering_refusal(app_dir, data, installed_build_id(app_dir))
            if refusal:
                return {**data, "staged": False, "applied": False, "status": "not_ready", "reason": refusal}
            attempt = "%s-%d-%d" % (data["build_id"], os.getpid(), time.time_ns())
            if drain is not None:
                try:
                    drain(Path(app_dir), attempt)  # admission closed and confirmed idle before anything is stopped
                except (OSError, ValueError) as exc:
                    return {**data, "applied": False, "status": "failed", "reason": str(exc)}
            if stop_runtime is not None:
                try:
                    stop_runtime(Path(app_dir))
                except (OSError, ValueError) as exc:
                    if drain is not None:
                        reopen_connectors(Path(app_dir), attempt)  # refused: agents' calls flow again
                    if str(exc) != _LAUNCHER_HOLDS_INSTALL and not connector_install_deferred(str(exc)):
                        # Refused before Setup: this candidate is not installed automatically again.
                        # A new build or the user's own Retry re-arms it (hold_auto_install).
                        _marker(updates, {**data, "phase": "staged", "auto_held": str(exc)[:512]})
                    return {**data, "applied": False, "status": "failed", "reason": str(exc)}
            data.pop("auto_held", None)
            _discard_rollback_copy(updates)
            _marker(updates, {**data, "phase": "applying"})
            attempted_build = data["build_id"]
            # Setup may hash/copy several large closed journals. Wait for its
            # real exit rather than killing it on an arbitrary 600s deadline.
            options = {"timeout": None, "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}
            setup_log = updates / 'setup.log'
            setup_log.unlink(missing_ok=True)
            # /NOCLOSEAPPLICATIONS wins over the script default. /CLOSEAPPLICATIONS
            # and /FORCECLOSEAPPLICATIONS make Restart Manager ask every process
            # that holds a file under the install directory to quit. Revit holds
            # its bridge DLL there; that flag closed the founder's Revit.
            result = runner([data["installer"], "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
                             "/NOCLOSEAPPLICATIONS", "/NORESTARTAPPLICATIONS",
                             "/SP-", "/LOG=" + str(setup_log), "/DIR=" + str(app_dir),
                             *(["/ARCHHUBDRAIN=" + attempt] if drain is not None else [])], **options)
            if drain is not None:
                reopen_connectors(Path(app_dir), attempt)  # Setup has ended; its own marker is gone too
            exit_code = getattr(result, "returncode", 1)
            if exit_code != 0 or not _installed_matches_target(app_dir, data):
                reason = ("installer failed (exit %s)" % exit_code) if exit_code != 0 else "installer did not confirm its outcome"
                if setup_log.is_file() and not setup_log.is_symlink():
                    with setup_log.open('rb') as stream:
                        stream.seek(max(0, setup_log.stat().st_size - 1024 * 1024))
                        raw = stream.read()
                    encoding = 'utf-16-le' if b'\x00' in raw[:64] else 'utf-8-sig'
                    for line in raw.decode(encoding, errors='replace').splitlines():
                        if 'ArchHub Setup refused: ' in line:
                            reason = "installer failed: " + line.split('ArchHub Setup refused: ', 1)[1]
                if reason.startswith(_SETUP_AGENT_BUSY):
                    # Setup's own connector check found an agent busy: nothing was installed and the
                    # same build stays eligible, so the next idle moment or Update retries it.
                    append_update_log(state_dir, "update: waiting for agent connectors (%s)" % reason[:600])
                    _marker(updates, {**data, "phase": "staged"})
                    return {"staged": True, "applied": False, "status": "waiting", "build_id": data["build_id"],
                            "reason": _AGENT_BUSY_NOTICE}
                # Recorded as failed for this build: the next start opens the installed build
                # instead of running the same installer again; a newer release replaces it.
                _marker(updates, {**data, "phase": "rolled_back", "rollback_reason": reason})
                return {"staged": False, "applied": False, "rolled_back": False, "status": "failed",
                        "build_id": data["build_id"], "reason": reason}
            _marker(updates, {**data, "phase": "awaiting_boot"})
            return {"applied": True, "build_id": data["build_id"], "status": "awaiting_boot",
                    "reason": "installer completed; successful new boot acknowledgment required"}
    except Exception as exc:
        if attempted_build is not None:
            return {"staged": True, "applied": False, "build_id": attempted_build,
                    "status": "applying", "reason": "installer outcome requires reconciliation: " + str(exc)}
        return _failure(exc, applied=False)


def rollback_staged(state_dir: Path, app_dir: Path) -> dict:
    """Caller has closed the runtime and still holds its instance lock."""
    try:
        with _locked(state_dir) as updates:
            data = json.loads((updates / "staged.json").read_text(encoding="utf-8"), object_pairs_hook=_unique_object)
            if data.get("phase") not in ("applying", "awaiting_boot"):
                return {"rolled_back": False, "reason": "no failed installation to roll back"}
            return _rollback(updates, app_dir, data, "new build did not confirm a successful boot")
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        return _failure(exc, rolled_back=False)


def begin_update_boot(state_dir: Path, app_dir: Path) -> dict:
    """Reserve one boot attempt. An unconfirmed boot stays on the installed build."""
    try:
        with _locked(state_dir) as updates:
            _discard_rollback_copy(updates)
            data = _status(updates, app_dir, reconcile=True)
            # Setup wrote BUILD_ID after copying; the owner may have exited
            # before recording its result. Let the matching new app prove boot.
            # There is no product-sized rollback copy, so an unconfirmed boot
            # stays on the installed build instead of restoring one.
            if data.get("status") in ("applying", "awaiting_boot"):
                if not (data.get("bytes_verified") and _installed_matches_target(app_dir, data)
                        and _installed_inventory_matches(app_dir)):
                    return {**data, "status": "applying", "reason": "installed payload requires reconciliation"}
                _marker(updates, {**data, "phase": "awaiting_boot", "boot_started": True})
                return {**data, "status": "awaiting_boot", "boot_started": True}
            return data
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        # A pending install must never degrade into a normal startup on error.
        return {**_failure(exc), "status": "applying"}


def boot_acknowledgment(page_ready, studio_mounted, checks, *, limit=150) -> str:
    """The new build's fate after boot: "confirm", "wait" or "rollback".

    The booted Studio confirms at once; graph hydration is not install health.
    Only a build that never reached the Studio by ``limit`` polls rolls back.
    """
    if page_ready or studio_mounted:
        return "confirm"
    if checks < limit:
        return "wait"
    return "confirm" if studio_mounted else "rollback"


def confirm_applied(state_dir: Path, app_dir: Path, *, rollback=True) -> dict:
    """Call only after successful boot. Confirmed package remains as evidence."""
    try:
        with _locked(state_dir) as updates:
            data = _status(updates, app_dir, verify_confirmed=True)
            if (not data["staged"] or data["installed_build_id"] != data["build_id"]
                    or not data.get("bytes_verified")
                    or data["status"] not in ("applying", "awaiting_boot", "confirmed")):
                if rollback and data.get("status") == "awaiting_boot":
                    return _rollback(updates, app_dir, data, "installed BUILD_ID does not match staged build")
                return {**data, "confirmed": False, "reason": "installed BUILD_ID does not match staged build"}
            try:
                matching = (_installed_matches_target(app_dir, data)
                            and (data["status"] == "confirmed" or _installed_inventory_matches(app_dir)))
            except (OSError, ValueError):
                matching = False
            if not matching:
                if rollback:
                    return _rollback(updates, app_dir, data, "installed build metadata or source inventory does not match the staged release")
                return {**data, "confirmed": False,
                        "reason": "installed build metadata or source inventory does not match the staged release; reconciliation required"}
            _discard_rollback_copy(updates)
            _marker(updates, {**data, "phase": "confirmed"})
            return {**data, "confirmed": True, "status": "confirmed", "reason": "successful boot acknowledged"}
    except (OSError, ValueError) as exc:
        if rollback:
            restored = rollback_staged(state_dir, app_dir)
            if restored.get("rolled_back"):
                return restored
        return _failure(exc, confirmed=False)


def confirm_when_free(state_dir: Path, app_dir: Path, *, attempts: int = 30, wait_seconds: float = 1.0,
                      sleep=time.sleep) -> dict:
    """Confirm a booted build; a busy update lock (the boot-time update check) is waited out, never a failure.

    Build 20261023-0221 quit itself at every boot: its confirmation met the background
    update check holding the same lock, read "update operation busy" as a failed boot and
    rolled back.
    """
    result = {}
    for _ in range(attempts):
        result = confirm_applied(state_dir, app_dir, rollback=False)
        if result.get("confirmed") or "update operation busy" not in str(result.get("reason", "")):
            return result
        sleep(wait_seconds)
    return result


def _profile_instance(state_dir=None):
    # Emergency bootstrap must work even if nodelang/__init__.py is damaged.
    import importlib.util
    spec = importlib.util.spec_from_file_location("archhub_profile_instance", Path(__file__).with_name("profile_instance.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    environment = dict(os.environ)
    if state_dir is not None:
        environment["ARCHHUB_TEST_STATE_DIR"] = str(state_dir)
    return module.ProfileInstance(environment)


def recover_failed_launch(state_dir: Path, app_dir: Path, *, lock_factory=None) -> dict:
    """Recover only while holding the same profile mutex as the desktop."""
    if not (Path(state_dir) / "updates" / "staged.json").is_file():
        return {"rolled_back": False, "reason": "no pending update"}
    lock = None
    try:
        lock = lock_factory() if lock_factory is not None else _profile_instance(state_dir)
        if lock.handle is None:
            return {"rolled_back": False, "reason": "existing desktop owns the profile"}
        return rollback_staged(state_dir, app_dir)
    except (OSError, ValueError) as exc:
        return _failure(exc, rolled_back=False)
    finally:
        if lock is not None:
            lock.close()


def apply_unattended(state_dir: Path, app_dir: Path, opener=urllib.request.urlopen, runner=subprocess.run, *,
                      safe: bool, channel: str = "stable", stop_runtime=stop_runtime_processes) -> dict:
    """Stage GitHub Latest and run the silent installer only at a safe moment.

    ``safe`` is true when no canvas job is running and the user is idle, or ArchHub
    is closing to the tray or quitting. A pre-release is ignored and never installed.
    A failed installer is reported as failed. No product-sized rollback copy is kept.
    """
    staged = stage_if_newer(state_dir, app_dir, opener, channel=channel)
    if staged.get("status") == "ignored" or staged.get("prerelease") is True:
        return {**staged, "staged": False, "applied": False, "status": "ignored",
                "reason": "pre-release ignored"}
    if not staged.get("staged"):
        return {**staged, "applied": False}
    if not safe:
        return {**staged, "applied": False, "status": "waiting",
                "reason": "waiting for a safe moment"}
    result = apply_staged(state_dir, app_dir, runner=runner, stop_runtime=stop_runtime)
    if result.get("applied") is True or result.get("status") == "waiting":
        return result
    reason = str(result.get("reason") or "installer failed")
    if "fail" not in reason.lower():
        reason = "installer failed: " + reason
    return {**result, "applied": False, "status": "failed", "reason": reason}


def state_directory() -> Path:
    """The same folder launcher.py writes launcher.log into."""
    if __package__ in (None, ""):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from nodelang.user_paths import state_directory as user_state_directory
    return user_state_directory()


def append_update_log(state_dir: Path, line: str) -> None:
    """One update line in launcher.log. A log failure must not hide the check."""
    try:
        directory = Path(state_dir) / 'logs'
        directory.mkdir(parents=True, exist_ok=True)
        from contextlib import closing
        from nodelang.log_rotation import RotatingLog
        with closing(RotatingLog(directory / 'updates.log')) as stream:
            stream.write(str(line).rstrip("\r\n") + "\n")
            stream.flush()
    except OSError:
        return


def note_check(state_dir: Path, app_dir: Path, result: dict) -> dict:
    """Write the update lines for one finished check. The result is unchanged."""
    installed = installed_build_id(Path(app_dir)) or "none"
    latest = str(result.get("build_id") or "") or "none"
    if result.get("reason") == "up to date":
        latest = installed
    append_update_log(state_dir, "update: checked latest=%s installed=%s" % (latest, installed))
    if result.get("source"):
        append_update_log(state_dir, "update: source %s" % result["source"])
    if result.get("fallback"):
        append_update_log(state_dir, "update: %s not used (%s); nothing staged from it" % (OFFER_URL, result["fallback"]))
    if result.get("downloaded") and result.get("build_id"):
        append_update_log(state_dir, "update: staged %s" % result["build_id"])
    if result.get("status") in ("unavailable", "failed") or result.get("reason") == "no release information":
        cause = " (%s)" % result["cause"] if result.get("cause") else ""
        append_update_log(state_dir, "update: error %s%s" % (result.get("reason") or result.get("status"), cause))
    return result


def check_for_update(state_dir: Path, app_dir: Path, opener=urllib.request.urlopen, *,
                     cancellation_event=None, channel="stable") -> dict:
    """Check GitHub Latest, stage a newer installer, and write the update lines.

    This is the check the start-path maintainer runs. The desktop calls
    stage_if_newer itself so a test can substitute that one function.
    """
    state_dir, app_dir = Path(state_dir), Path(app_dir)
    try:
        result = stage_if_newer(state_dir, app_dir, opener, cancellation_event=cancellation_event, channel=channel)
    except Exception as exc:
        append_update_log(state_dir, "update: error %s" % exc)
        raise
    return note_check(state_dir, app_dir, result)


def _check_policy():
    """The catalogue interval (default 30 minutes) and the idle wait."""
    try:
        root = str(Path(__file__).resolve().parents[1])
        if root not in sys.path:
            sys.path.insert(0, root)
        from nodelang.application_update import default_update_policy
        policy = default_update_policy()
        interval, idle = int(policy["check_interval_minutes"]), int(policy["idle_minutes"])
    except (OSError, ValueError, TypeError, ImportError, KeyError):
        interval, idle = 30, 15
    if type(interval) is not int or not 1 <= interval <= 1440:
        interval = 30
    if type(idle) is not int or not 1 <= idle <= 1440:
        idle = 15
    return interval, idle


def _machine_is_idle(minutes: int) -> bool:
    try:
        root = str(Path(__file__).resolve().parents[1])
        if root not in sys.path:
            sys.path.insert(0, root)
        import math
        from nodelang.baboom_native_companion import desktop_input_idle_seconds
        age = desktop_input_idle_seconds()
    except (ImportError, OSError, AttributeError, TypeError, ValueError):
        return False
    return math.isfinite(age) and age >= minutes * 60


def _desktop_running() -> bool:
    """The same profile mutex guards desktop launch and update recovery."""
    lock = _profile_instance()
    try:
        return lock.handle is None
    finally:
        lock.close()


_MAINTAINER_MUTEX = None


def _claim_maintainer(app_dir: Path) -> bool:
    """One maintainer per install. A second start leaves the first running.

    A failed claim does not start another copy. The handle stays open for
    the life of this process so the mutex is not abandoned while it runs.
    """
    global _MAINTAINER_MUTEX
    if os.name != "nt":
        return True
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.SetLastError.argtypes = [wintypes.DWORD]
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, ctypes.c_wchar_p]
    kernel.CreateMutexW.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    name = "Local\\ArchHub.UpdateMaintain." + hashlib.sha256(
        os.path.normcase(str(Path(app_dir).resolve())).encode("utf-8")).hexdigest()[:16]
    kernel.SetLastError(0)
    handle = kernel.CreateMutexW(None, True, name)
    if not handle:
        return False
    if ctypes.get_last_error() == 183:
        waited = kernel.WaitForSingleObject(handle, 0)
        if waited not in (0, 0x80):
            kernel.CloseHandle(handle)
            return False
    _MAINTAINER_MUTEX = handle
    return True


def spawn_detached(argv):
    """Start a hidden process outside the caller's job object.

    The venv redirector holds its child in a kill-on-close job. A helper left in it
    dies with the desktop it outlives. Breakaway is refused when the job forbids it;
    the plain hidden start is then the fallback.
    """
    hidden = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    breakaway = getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0)
    try:
        return subprocess.Popen(argv, close_fds=True, creationflags=hidden | breakaway)
    except OSError:
        return subprocess.Popen(argv, close_fds=True, creationflags=hidden)


def _relaunch(app_dir: Path, tray: bool = False):
    system = os.environ.get("SystemRoot", r"C:\Windows")
    return spawn_detached([str(Path(system) / "System32" / "wscript.exe"), str(Path(app_dir) / "ArchHub.vbs")]
                          + (["--tray"] if tray else []))


def _reopen_after_update(state: Path, app_dir: Path, build_id: str, *, sleep, tray: bool = False) -> bool:
    """Use the desktop's existing boot acknowledgment to settle the update."""
    from nodelang.canvas_triggers import TRIGGER_NODE

    file_interval = TRIGGER_NODE["params"]["file_poll_floor_seconds"]
    for _ in range(2):
        launcher = None
        if not _desktop_running():
            try:
                launcher = _relaunch(app_dir, tray) if tray else _relaunch(app_dir)
            except OSError as error:
                append_update_log(state, "update: error relaunch failed (%s)" % type(error).__name__)
                continue
        checks = 0
        while boot_acknowledgment(False, False, checks) == "wait":
            try:
                marker = _read_stage_marker(state / "updates")
            except (OSError, ValueError):
                marker = {}
            if marker.get("build_id") == build_id and marker.get("phase") == "confirmed":
                return True
            if launcher is not None and launcher.poll() is not None and not _desktop_running():
                append_update_log(state, "update: desktop launcher exited before confirming Studio boot")
                break
            sleep(file_interval)
            checks += 1
        else:
            break
    return False


def maintain(app_dir: Path, opener=urllib.request.urlopen, *, sleep=time.sleep) -> int:
    """Check on start and every N minutes. Install when the desktop is not open.

    A founder who keeps ArchHub open is not installed over: the next start,
    before the window, and Quit from the tray apply the staged build. Machine
    idle is not required once the desktop lock is free. A second start exits.
    """
    app_dir = Path(app_dir)
    if not _claim_maintainer(app_dir):
        return 0
    state = state_directory()
    while True:
        try:
            result = check_for_update(state, app_dir, opener)
            ready = result.get("staged") and result.get("status") == "staged" and result.get("prerelease") is not True
            if ready and not _desktop_running():
                try:
                    import psutil
                    psutil.Process(os.getpid())
                except ImportError as missing:
                    append_update_log(state, "update: error installer runtime is not ready (%s)" % type(missing).__name__)
                else:
                    applied = apply_staged(state, app_dir, stop_runtime=stop_runtime_processes)
                    if applied.get("applied"):
                        append_update_log(state, "update: installed %s" % applied.get("build_id"))
                        if _reopen_after_update(state, app_dir, applied["build_id"], sleep=sleep):
                            return 0
                        append_update_log(state, "update: error installed build did not confirm Studio boot; installer retained")
                        return 1
                    if applied.get("status") in ("failed", "unavailable") or "fail" in str(applied.get("reason") or "").lower():
                        append_update_log(state, "update: error %s" % applied.get("reason"))
        except Exception as exc:
            append_update_log(state, "update: error %s" % exc)
        sleep(_check_policy()[0] * 60)
    return 0


def hand_off(app_dir: Path, *, relaunch: bool, tray: bool = False, expect=None, sleep=time.sleep,
             wait_seconds: float = 120.0) -> int:
    """Install the staged build once the desktop that asked for it has fully exited.

    The desktop starts this hidden helper and then quits. Its profile mutex and its
    in-folder launcher outlive the request by seconds; installing or relaunching
    before they are gone lost the update and left ArchHub closed. Setup runs hidden
    with /NOCLOSEAPPLICATIONS; Revit and AutoCAD are never stopped.
    """
    app_dir, state = Path(app_dir), state_directory()  # also puts the app root on sys.path for a file-path start
    from nodelang.canvas_triggers import TRIGGER_NODE

    poll = TRIGGER_NODE["params"]["file_poll_floor_seconds"]
    waited, applied = 0.0, {}
    while True:
        if not _desktop_running():
            applied = apply_staged(state, app_dir, stop_runtime=stop_runtime_processes, expect=expect)
            if applied.get("reason") != _LAUNCHER_HOLDS_INSTALL:
                break
        if waited >= wait_seconds:
            append_update_log(state, "update: desktop still open after %ds; install waits for the next start"
                              % wait_seconds)
            return 0
        sleep(poll)
        waited += poll
    if applied.get("applied"):
        append_update_log(state, "update: installed %s" % applied.get("build_id"))
        if not relaunch:
            return 0
        if _reopen_after_update(state, app_dir, applied["build_id"], sleep=sleep, tray=tray):
            append_update_log(state, "update: confirmed %s" % applied["build_id"])
            return 0
        append_update_log(state, "update: error installed build did not confirm Studio boot; installer retained")
        return 1
    if applied.get("reason"):
        append_update_log(state, "update: error %s" % applied["reason"])
    if relaunch:
        # A restart was asked for: ArchHub comes back on the build it had, where it was (window or tray).
        try:
            _relaunch(app_dir, tray) if tray else _relaunch(app_dir)
        except OSError as error:
            append_update_log(state, "update: error relaunch failed (%s)" % type(error).__name__)
    return 0 if applied.get("status") != "failed" else 1


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description="Recover a failed update or keep checking GitHub Latest.")
    parser.add_argument("--recover-failed-launch", type=Path)
    parser.add_argument("--maintain", type=Path, help="Application directory. Check now, then every N minutes.")
    parser.add_argument("--apply-staged", type=Path, help="Install a staged build when the desktop is not open, then exit.")
    parser.add_argument("--relaunch", action="store_true", help="With --apply-staged: reopen ArchHub afterwards.")
    parser.add_argument("--tray", action="store_true", help="With --relaunch: reopen in the tray, no window.")
    parser.add_argument("--expect-build", help="With --apply-staged: install only this staged build id.")
    parser.add_argument("--expect-sha256", help="With --expect-build: and only with this installer SHA-256.")
    parser.add_argument("--state-dir", type=Path)
    parser.add_argument("--setup-admission", type=Path, help="Setup: drain agent connectors of this application directory.")
    parser.add_argument("--build-id", help="With --setup-admission: the build Setup installs.")
    parser.add_argument("--expect-attempt", help="With --setup-admission: the updater's drain attempt (/ARCHHUBDRAIN).")
    args = parser.parse_args(argv)
    if args.state_dir is not None:
        os.environ["ARCHHUB_TEST_STATE_DIR"] = str(args.state_dir)
    if args.setup_admission is not None:
        if not args.build_id:
            parser.error("--setup-admission needs --build-id")
        try:
            mode, attempt = setup_admission(args.setup_admission, args.build_id, expected=args.expect_attempt or None)
        except (OSError, ValueError) as held:
            print("ArchHub connector admission held: %s" % held, flush=True)
            return 3
        print("ARCHHUB-ADMISSION %s %s" % (mode, attempt), flush=True)
        return 0
    if args.apply_staged is not None:
        expect = None
        if args.expect_build or args.expect_sha256:
            if not (args.expect_build and args.expect_sha256):
                parser.error("--expect-build and --expect-sha256 go together")
            expect = (args.expect_build, args.expect_sha256.lower())
        return hand_off(args.apply_staged, relaunch=args.relaunch, tray=args.tray, expect=expect)
    if args.maintain is not None:
        return maintain(args.maintain)
    if args.recover_failed_launch is None or args.state_dir is None:
        parser.error("--recover-failed-launch and --state-dir are required unless --maintain is set")
    result = recover_failed_launch(args.state_dir, args.recover_failed_launch)
    if not result.get("rolled_back"):
        return 1
    subprocess.Popen([str(Path(os.environ["SystemRoot"]) / "System32" / "wscript.exe"),
                      str(args.recover_failed_launch / "ArchHub.vbs")], close_fds=True,
                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return 0


__all__ = ["apply_staged", "apply_unattended", "boot_acknowledgment", "installed_build_id", "read_latest_release", "stage_if_newer",
           "staged_update", "confirm_applied", "begin_update_boot", "rollback_staged", "recover_failed_launch", "ASSET_NAME"]


if __name__ == "__main__":
    raise SystemExit(main())
