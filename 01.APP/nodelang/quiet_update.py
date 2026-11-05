"""Bounded update staging. Owner supplies recovery admission and boot acknowledgment.

Published SHA-256 is byte integrity, not signed release proof or rollback.
"""
from __future__ import annotations
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
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
        if path.name not in APP_FOLDER_OWNERS and path.name != _CLEANUP_STAGE:
            if path.suffix.lower() == '.archhub':
                continue
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
                if file.suffix.lower() in ('.archhub', '.pem', '.key', '.dpapi') and path.suffix.lower() != '.archhub':
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
                if relative.parts[0] in APP_FOLDER_OWNERS and not (relative.parts[0] == 'sessions-files' and target.suffix.lower() == '.archhub'):
                    raise OSError('allowlisted entry retained')
                # Re-check locks/links: a process may have opened it since staging.
                if target.exists():
                    for file in _entry_files(target):
                        if file.suffix.lower() in ('.archhub', '.pem', '.key', '.dpapi'):
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


def installed_build_id(app_dir: Path) -> str:
    try:
        with (Path(app_dir) / "BUILD_ID").open(encoding="utf-8") as stream:
            value = stream.read(258).strip()
        return value if re.fullmatch(r"[A-Za-z0-9._-]{1,256}", value) else ""
    except (OSError, UnicodeError):
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


def read_latest_release(opener=urllib.request.urlopen, *, channel="stable") -> dict | None:
    """Return validated release identity and build time, or None.

    Missing chronology on an opaque old release is returned as built_at=None so
    callers can report unknown ordering without downloading its installer.
    A pre-release is not returned. ``saw_prerelease`` records that fact for the
    same response, so auto-update can ignore it without a second request.
    """
    read_latest_release.saw_prerelease = False
    try:
        if channel not in ("stable", "preview"):
            raise ValueError("update channel must be stable or preview")
        url = release_feed_url() if channel == "stable" else RELEASE_API.rsplit("/", 1)[0] + "?per_page=20"
        request = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "ArchHub"})
        with opener(request, timeout=15) as response:
            raw = response.read(_RELEASE_BYTES + 1)
        if len(raw) > _RELEASE_BYTES:
            return None
        data = json.loads(raw)
        if channel == "preview":
            if not isinstance(data, list):
                return None
            data = next((item for item in data if isinstance(item, dict) and not item.get("draft")), None)
        read_latest_release.saw_prerelease = (
            isinstance(data, dict) and data.get("prerelease") is True and not data.get("draft"))
        if not isinstance(data, dict) or data.get("draft") or (channel == "stable" and data.get("prerelease")):
            return None
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
    except (OSError, ValueError, TypeError):
        read_latest_release.saw_prerelease = False
        return None


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
                    and path.suffix.lower() not in (".pyc", ".pyo", ".sqlite3", ".db", ".key", ".pem")
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


def _status(updates, app_dir, *, verify_confirmed=False):
    marker = updates / "staged.json"
    _plain(marker)
    if not marker.exists():
        return {"staged": False, "build_id": "", "status": "none", "reason": "nothing staged"}
    with marker.open("rb") as stream:
        raw = stream.read(16385)
    if len(raw) > 16384:
        raise ValueError("staged marker exceeds size budget")
    data = json.loads(raw)
    if (not isinstance(data, dict) or not isinstance(data.get("build_id"), str)
            or not re.fullmatch(r"[A-Za-z0-9._-]{1,256}", data["build_id"])
            or not isinstance(data.get("sha256"), str)
            or not re.fullmatch(r"[0-9a-fA-F]{64}", data["sha256"])):
        raise ValueError("staged identity invalid")
    phase = data.get("phase", "staged")
    if phase not in ("staged", "applying", "awaiting_boot", "confirmed", "rolled_back"):
        raise ValueError("staged phase invalid")
    if phase == "rolled_back":
        reason = " ".join(str(data.get("rollback_reason") or "").split())[:512]
        return {**data, "staged": False, "retained": True, "status": phase,
                "reason": "Previous build restored after a failed update; "
                          + (reason + "; " if reason else "")
                          + "waiting for a newer release."}
    target = updates / ASSET_NAME
    current = installed_build_id(app_dir)
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
    if (verify_confirmed or not confirmed_current) and _digest(target) != data["sha256"].lower():
        raise ValueError("staged installer no longer matches published SHA-256")
    _plain(target)
    status = "awaiting_boot" if current == data["build_id"] and phase == "staged" else phase
    if status == "staged":
        json.loads(raw, object_pairs_hook=_unique_object)
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
    """Download bounded bytes under exclusive staging ownership; never install."""
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
            latest = read_latest_release(opener) if channel == "stable" else read_latest_release(opener, channel=channel)
            current = installed_build_id(app_dir)
            check_cancelled()
            # A staged installer older than GitHub Latest must not block it.
            if held["staged"] and held["status"] != "confirmed" and _keep_held_stage(held, latest):
                return held
            if latest is None:
                if channel == "stable" and _published_prerelease(opener):
                    return {"staged": False, "applied": False, "build_id": "", "status": "ignored",
                            "reason": "pre-release ignored"}
                return {"staged": False, "build_id": "", "reason": "no release information"}
            if channel != "stable" and _published_prerelease(opener, channel):
                # A preview may be staged for the Update button. Auto-install refuses it.
                latest = {**latest, "prerelease": True}
            if held.get("status") == "rolled_back" and latest["build_id"] == held["build_id"]:
                return {**held, "staged": False}
            if not current:
                return {"staged": False, "reason": "Installed build identity is missing; install a versioned ArchHub release first.", "build_id": ""}
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


def stop_runtime_processes(app_dir: Path, *, process_iter=None, wait_seconds: float = 5.0) -> list:
    """Stop every other process started from the install folder before the installer copies.

    A leftover executable under the install folder held a file, the silent replace failed
    with Windows error 32 (file in use), and the suppressed dialog answered Abort.
    The process running this update is left alive so it can start the installer.
    A supervisor outside the install folder, including agent connectors, is not stopped
    and is not a reason to refuse the update.
    """
    import psutil
    root = Path(app_dir).resolve()
    me = os.getpid()
    stopped = []
    for process in (process_iter or psutil.process_iter)(["pid", "exe"]):
        try:
            if process.info.get("pid") == me:
                continue
            exe = process.info.get("exe")
            if exe and Path(exe).resolve().is_relative_to(root):
                process.terminate()
                stopped.append(process)
        except (psutil.Error, OSError, ValueError):
            continue
    if stopped:
        _gone, alive = psutil.wait_procs(stopped, timeout=wait_seconds)
        refused = []
        for process in alive:
            try:
                process.kill()
            except psutil.NoSuchProcess:
                continue  # it exited between the wait and the kill
            except psutil.Error as error:
                refused.append("%d (%s)" % (process.pid, type(error).__name__))
        if refused:
            # Better to refuse the update than let the silent installer abort mid-replace.
            raise OSError("runtime processes could not be stopped: " + ", ".join(refused))
    return [process.pid for process in stopped]


def apply_staged(state_dir: Path, app_dir: Path, runner=subprocess.run, *, before_apply=None,
                 stop_runtime=stop_runtime_processes) -> dict:
    """Call before_apply() under staging ownership, then attempt once; retain package.

    The trusted callback raises to refuse recovery admission. It must not call
    staging APIs recursively; this operation holds their exclusive lock.
    """
    attempted_build = None
    try:
        with _locked(state_dir) as updates:
            data = _status(updates, app_dir, verify_confirmed=True)
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
            _discard_rollback_copy(updates)
            _marker(updates, {**data, "phase": "applying"})
            attempted_build = data["build_id"]
            # Setup may hash/copy several large closed journals. Wait for its
            # real exit rather than killing it on an arbitrary 600s deadline.
            options = {"timeout": None, "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}
            setup_log = updates / 'setup.log'
            setup_log.unlink(missing_ok=True)
            if stop_runtime is not None:
                stop_runtime(Path(app_dir))
            # /NOCLOSEAPPLICATIONS wins over the script default. /CLOSEAPPLICATIONS
            # and /FORCECLOSEAPPLICATIONS make Restart Manager ask every process
            # that holds a file under the install directory to quit. Revit holds
            # its bridge DLL there; that flag closed the founder's Revit.
            result = runner([data["installer"], "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
                             "/NOCLOSEAPPLICATIONS", "/NORESTARTAPPLICATIONS",
                             "/SP-", "/LOG=" + str(setup_log), "/DIR=" + str(app_dir)], **options)
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
                _marker(updates, {**data, "phase": "staged"})
                return {"staged": True, "applied": False, "rolled_back": False, "status": "failed",
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
            data = _status(updates, app_dir)
            # Setup wrote BUILD_ID after copying; the owner may have exited
            # before recording its result. Let the matching new app prove boot.
            # There is no product-sized rollback copy, so an unconfirmed boot
            # stays on the installed build instead of restoring one.
            if (data.get("status") == "applying" and data.get("bytes_verified")
                    and _installed_matches_target(app_dir, data)):
                _marker(updates, {**data, "phase": "awaiting_boot", "boot_started": True})
                return {**data, "status": "awaiting_boot", "boot_started": True}
            if data.get("status") == "awaiting_boot":
                _marker(updates, {**data, "phase": "awaiting_boot", "boot_started": True})
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
                matching = _installed_matches_target(app_dir, data)
            except (OSError, ValueError):
                matching = False
            if not matching:
                if rollback:
                    return _rollback(updates, app_dir, data, "installed build metadata does not match the staged release")
                return {**data, "confirmed": False,
                        "reason": "installed build metadata does not match the staged release; reconciliation required"}
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


def recover_failed_launch(state_dir: Path, app_dir: Path, *, socket_factory=None) -> dict:
    """Emergency entry uses stdlib only, before setup or application imports.

    It takes the same exclusive socket as the sole desktop launcher. A failed
    second launch must never restore files underneath an already running app.
    """
    import socket
    if not (Path(state_dir) / "updates" / "staged.json").is_file():
        return {"rolled_back": False, "reason": "no pending update"}
    lock = (socket_factory or socket.socket)()
    try:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            lock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        lock.bind(("127.0.0.1", int(os.environ.get("ARCHHUB_TEST_LOCK_PORT", "48611"))))
        return rollback_staged(state_dir, app_dir)
    except (OSError, ValueError) as exc:
        return _failure(exc, rolled_back=False)
    finally:
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
    if result.get("applied") is True:
        return result
    reason = str(result.get("reason") or "installer failed")
    if "fail" not in reason.lower():
        reason = "installer failed: " + reason
    return {**result, "applied": False, "status": "failed", "reason": reason}


def state_directory() -> Path:
    """The same folder launcher.py writes launcher.log into."""
    override = os.environ.get("ARCHHUB_TEST_STATE_DIR", "").strip()
    if override:
        return Path(override)
    return Path(os.environ["LOCALAPPDATA"]) / "ArchHub"


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
    if result.get("downloaded") and result.get("build_id"):
        append_update_log(state_dir, "update: staged %s" % result["build_id"])
    if result.get("status") in ("unavailable", "failed") or result.get("reason") == "no release information":
        append_update_log(state_dir, "update: error %s" % (result.get("reason") or result.get("status")))
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
    """True when launcher.py holds the single-instance port. It installs itself."""
    import socket
    sock = socket.socket()
    try:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        sock.bind(("127.0.0.1", int(os.environ.get("ARCHHUB_TEST_LOCK_PORT", "48611"))))
    except OSError:
        return True
    finally:
        sock.close()
    return False


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


def _relaunch(app_dir: Path) -> None:
    system = os.environ.get("SystemRoot", r"C:\Windows")
    subprocess.Popen([str(Path(system) / "System32" / "wscript.exe"), str(Path(app_dir) / "ArchHub.vbs")],
                     close_fds=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


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
                        try:
                            _relaunch(app_dir)
                        except OSError as error:
                            append_update_log(state, "update: error relaunch failed (%s)" % type(error).__name__)
                        return 0
                    if applied.get("status") in ("failed", "unavailable") or "fail" in str(applied.get("reason") or "").lower():
                        append_update_log(state, "update: error %s" % applied.get("reason"))
        except Exception as exc:
            append_update_log(state, "update: error %s" % exc)
        sleep(_check_policy()[0] * 60)
    return 0


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description="Recover a failed update or keep checking GitHub Latest.")
    parser.add_argument("--recover-failed-launch", type=Path)
    parser.add_argument("--maintain", type=Path, help="Application directory. Check now, then every N minutes.")
    parser.add_argument("--apply-staged", type=Path, help="Install a staged build when the desktop is not open, then exit.")
    parser.add_argument("--state-dir", type=Path)
    args = parser.parse_args(argv)
    if args.apply_staged is not None:
        if _desktop_running():
            append_update_log(state_directory(), "update: desktop is open; install waits until quit or the next start")
            return 0
        if args.state_dir is not None:
            os.environ["ARCHHUB_TEST_STATE_DIR"] = str(args.state_dir)
        applied = apply_staged(state_directory(), args.apply_staged, stop_runtime=stop_runtime_processes)
        if applied.get("applied"):
            append_update_log(state_directory(), "update: installed %s" % applied.get("build_id"))
        elif applied.get("reason"):
            append_update_log(state_directory(), "update: %s" % applied.get("reason"))
        return 0 if applied.get("applied") or applied.get("status") != "failed" else 1
    if args.maintain is not None:
        if args.state_dir is not None:
            os.environ["ARCHHUB_TEST_STATE_DIR"] = str(args.state_dir)
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
