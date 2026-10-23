"""Bounded update staging. Owner supplies recovery admission and boot acknowledgment.

Published SHA-256 is byte integrity, not signed release proof or rollback.
"""
from __future__ import annotations
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
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
_PAYLOAD_FILES = ("BUILD_ID", "BUILD_METADATA.json", "launch_archhub_test.py", "colleague_setup.py",
                  "requirements.txt", "ArchHub.vbs", "ArchHub.bat", "archhub.ico", "NOTICE", "HOST_ARTIFACTS.json")
_ROLLBACK_BYTES = 2 * 1024 * 1024 * 1024


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


def read_latest_release(opener=urllib.request.urlopen, *, channel="stable") -> dict | None:
    """Return validated release identity and build time, or None.

    Missing chronology on an opaque old release is returned as built_at=None so
    callers can report unknown ordering without downloading its installer.
    """
    try:
        if channel not in ("stable", "preview"):
            raise ValueError("update channel must be stable or preview")
        url = RELEASE_API if channel == "stable" else RELEASE_API.rsplit("/", 1)[0] + "?per_page=20"
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
        expected = "https://github.com/Fargaly/ArchHub/releases/download/" + urllib.parse.quote(tag, safe="") + "/" + ASSET_NAME
        size = asset.get("size")
        if url != expected or (size is not None and (type(size) is not int or not 0 < size <= _INSTALLER_BYTES)):
            return None
        return {"build_id": builds[0], "built_at": built_at,
                "sha256": hashes[0].lower(), "url": url, "tag": tag}
    except (OSError, ValueError, TypeError):
        return None


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


def _retain_previous(updates, app):
    files = list(_payload_files(app))
    size = sum(path.stat().st_size for path in files)
    if size > _ROLLBACK_BYTES or shutil.disk_usage(updates).free < size + 256 * 1024 * 1024:
        raise ValueError("previous build cannot be retained within the update disk budget")
    target = updates / "previous-build.zip"
    _plain(target)
    descriptor, name = tempfile.mkstemp(prefix=".previous-build-", suffix=".tmp", dir=updates)
    os.close(descriptor)
    temporary = Path(name)
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_STORED) as archive:
            for path in files:
                archive.write(path, path.relative_to(app).as_posix())
        os.replace(temporary, target)
        digest = _archive_digest(target)
        return {"build_id": installed_build_id(app), "sha256": digest}
    finally:
        temporary.unlink(missing_ok=True)


def _archive_digest(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _rollback(updates, app, data, reason):
    """Restore the retained product, leaving all user data and recovery intact."""
    previous = data.get("previous")
    if not isinstance(previous, dict):
        return {**data, "confirmed": False, "rolled_back": False, "reason": reason}
    archive_path = updates / "previous-build.zip"
    _plain(archive_path)
    if _archive_digest(archive_path) != previous.get("sha256"):
        raise ValueError("previous build digest changed; rollback refused")
    app = Path(app)
    with zipfile.ZipFile(archive_path) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)) or sum(entry.file_size for entry in archive.infolist()) > _ROLLBACK_BYTES:
            raise ValueError("previous build inventory is invalid")
        for name in names:
            parts = name.split("/")
            if (any(part in ("", ".", "..") or ":" in part or "\\" in part for part in parts)
                    or not (name in _PAYLOAD_FILES or parts[0] in _PAYLOAD_DIRS)):
                raise ValueError("previous build path is outside the product")
            _plain(app / name)
        # Validate the whole archive before the first write.
        if archive.testzip() is not None or archive.read("BUILD_ID").decode("utf-8").strip() != previous["build_id"]:
            raise ValueError("previous build identity is invalid")
        extras = [path for path in _payload_files(app) if path.relative_to(app).as_posix() not in names]
        for name in names:
            target = app / name
            target.parent.mkdir(parents=True, exist_ok=True)
            fd, temporary = tempfile.mkstemp(prefix=".rollback-", dir=target.parent)
            try:
                with os.fdopen(fd, "wb") as out, archive.open(name) as source:
                    shutil.copyfileobj(source, out, 65536)
                    out.flush()
                    os.fsync(out.fileno())
                os.replace(temporary, target)
            finally:
                Path(temporary).unlink(missing_ok=True)
        for path in extras:
            path.unlink()
        # Do not reuse bytecode compiled from the failed release.
        for root in _PAYLOAD_DIRS:
            for path in (app / root).rglob("*.pyc"):
                _plain(path)
                path.unlink()
    _marker(updates, {**data, "phase": "rolled_back", "rollback_reason": reason})
    return {"staged": False, "confirmed": False, "rolled_back": True, "status": "rolled_back",
            "build_id": previous["build_id"], "reason": reason + "; previous build restored"}


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
            if held["staged"] and held["status"] != "confirmed":
                return held
            latest = read_latest_release(opener) if channel == "stable" else read_latest_release(opener, channel=channel)
            current = installed_build_id(app_dir)
            check_cancelled()
            if latest is None:
                return {"staged": False, "build_id": "", "reason": "no release information"}
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
            _marker(updates, {**latest, "phase": "staged"})
            return _status(updates, app_dir)
    except (OSError, ValueError) as exc:
        return _failure(exc)
    finally:
        if partial is not None:
            partial.unlink(missing_ok=True)


def stop_runtime_processes(app_dir: Path, *, process_iter=None, wait_seconds: float = 5.0) -> list:
    """Stop processes whose executable lives under <app>/runtime before the installer replaces it.

    Build 20261023-0423 rolled back: a leftover BABOOM goose.exe held runtime/goose/goose.exe,
    the silent installer's replace failed (code 5), and /SUPPRESSMSGBOXES answered Abort.
    """
    import psutil
    root = (Path(app_dir) / "runtime").resolve()
    stopped = []
    for process in (process_iter or psutil.process_iter)(["pid", "exe"]):
        try:
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
            data = {**data, "previous": _retain_previous(updates, Path(app_dir))}
            _marker(updates, {**data, "phase": "applying"})
            attempted_build = data["build_id"]
            # Setup may hash/copy several large closed journals. Wait for its
            # real exit rather than killing it on an arbitrary 600s deadline.
            options = {"timeout": None, "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}
            setup_log = updates / 'setup.log'
            setup_log.unlink(missing_ok=True)
            if stop_runtime is not None:
                stop_runtime(Path(app_dir))
            result = runner([data["installer"], "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
                             "/NOCLOSEAPPLICATIONS", "/NORESTARTAPPLICATIONS",
                             "/SP-", "/LOG=" + str(setup_log), "/DIR=" + str(app_dir)], **options)
            if getattr(result, "returncode", 1) != 0 or not _installed_matches_target(app_dir, data):
                reason = "installer did not confirm its outcome"
                if setup_log.is_file() and not setup_log.is_symlink():
                    with setup_log.open('rb') as stream:
                        stream.seek(max(0, setup_log.stat().st_size - 1024 * 1024))
                        raw = stream.read()
                    encoding = 'utf-16-le' if b'\x00' in raw[:64] else 'utf-8-sig'
                    for line in raw.decode(encoding, errors='replace').splitlines():
                        if 'ArchHub Setup refused: ' in line:
                            reason = line.split('ArchHub Setup refused: ', 1)[1]
                return {**_rollback(updates, app_dir, data, reason), "applied": False, "reason": reason}
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
    """Reserve one boot attempt; the next unconfirmed boot restores the old code."""
    try:
        with _locked(state_dir) as updates:
            data = _status(updates, app_dir)
            # Setup wrote BUILD_ID after copying; the owner may have exited
            # before recording its result. Let the matching new app prove boot.
            if (data.get("status") == "applying" and data.get("bytes_verified")
                    and _installed_matches_target(app_dir, data)):
                _marker(updates, {**data, "phase": "awaiting_boot", "boot_started": True})
                return {**data, "status": "awaiting_boot", "boot_started": True}
            if data.get("previous") and (data.get("status") == "applying" or (
                    data.get("status") == "awaiting_boot" and data.get("boot_started"))):
                return _rollback(updates, app_dir, data, "previous update boot did not confirm")
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


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description="Recover a failed update with the existing update owner.")
    parser.add_argument("--recover-failed-launch", type=Path, required=True)
    parser.add_argument("--state-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    result = recover_failed_launch(args.state_dir, args.recover_failed_launch)
    if not result.get("rolled_back"):
        return 1
    subprocess.Popen([str(Path(os.environ["SystemRoot"]) / "System32" / "wscript.exe"),
                      str(args.recover_failed_launch / "ArchHub.vbs")], close_fds=True,
                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return 0


__all__ = ["apply_staged", "boot_acknowledgment", "installed_build_id", "read_latest_release", "stage_if_newer",
           "staged_update", "confirm_applied", "begin_update_boot", "rollback_staged", "recover_failed_launch", "ASSET_NAME"]


if __name__ == "__main__":
    raise SystemExit(main())
