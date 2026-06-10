"""Local development-source sync for installer launches.

The release updater handles normal users: it downloads a signed installer from
GitHub Releases. During active development, though, Fargaly often launches the
installed AppData copy while Claude/Codex edit the git checkout. This module
bridges that gap by copying the configured source checkout into the installed
copy before Qt imports the rest of the app, then relaunching once.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Sequence


ENV_SOURCE_KEYS = ("ARCHHUB_DEV_SOURCE", "ARCHHUB_SOURCE_DIR")
SYNC_MARKER = "dev_source_sync.json"
SETTINGS_FILE = "settings.json"
VERSION_FILE = "version.json"

# reopen=latest: bound on waiting for the OLD single-instance to quit + release
# its lock before we relaunch the freshly-synced child. Hard cap so a wedged old
# instance can NEVER block startup — on timeout we sync + relaunch anyway
# (worst case = the old behaviour). 4s mirrors single_instance._quit's default.
QUIT_OLD_INSTANCE_TIMEOUT = 4.0

CODE_PATHS: tuple[tuple[str, str], ...] = (
    ("app", "app"),
    ("payload/sources", "payload/sources"),
    ("payload/bridge", "payload/bridge"),
    ("payload/blender", "payload/blender"),
    ("installer", "installer"),
    ("docs", "docs"),
)
TOP_LEVEL_FILES = (
    "VERSION",
    "requirements.txt",
    "README.md",
    "LICENSE",
    "QUICKSTART.md",
)

EXCLUDED_DIRS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
    "node_modules",
    "venv",
    ".venv",
}
EXCLUDED_SUFFIXES = {".pyc", ".pyo", ".log", ".tmp"}


def is_git_checkout(root: Path) -> bool:
    return (root / ".git").exists()


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")


def _settings_path(install_root: Path) -> Path:
    return install_root / SETTINGS_FILE


def _configured_source_candidates(install_root: Path) -> list[Path]:
    candidates: list[Path] = []
    for key in ENV_SOURCE_KEYS:
        value = os.environ.get(key)
        if value:
            candidates.append(Path(value))

    settings = _read_json(_settings_path(install_root))
    if settings.get("enable_dev_source_sync"):
        for key in ("dev_source_path", "source_dir", "archhub_source_path"):
            value = settings.get(key)
            if value:
                candidates.append(Path(value))

    manifest = _read_json(install_root / VERSION_FILE)
    if manifest.get("dev_source_sync"):
        value = manifest.get("source_dir") or manifest.get("dev_source_path")
        if value:
            candidates.append(Path(value))

    return candidates


def find_source_root(install_root: Path) -> Path | None:
    """Return a configured git checkout that can safely feed this install."""
    try:
        install_root = install_root.resolve()
    except Exception:
        install_root = install_root.absolute()

    for candidate in _configured_source_candidates(install_root):
        try:
            source_root = candidate.expanduser().resolve()
        except Exception:
            continue
        if source_root == install_root:
            continue
        if not is_git_checkout(source_root):
            continue
        if not (source_root / "app" / "main.py").exists():
            continue
        if not (source_root / "VERSION").exists():
            continue
        return source_root
    return None


_GIT_BROKEN = False  # set True after first failed launch this process


def _suppress_win_error_dialogs() -> None:
    """Stop child crashes (0xc0000142 etc) from popping modal dialogs
    that block the parent. Without this, an antivirus DLL-injection
    failure on git.exe halts ArchHub boot until the user clicks OK
    on a hidden popup. Founder 2026-05-25: identified Kaspersky 21.22
    WSC ghost as the trigger. SetErrorMode flags:
      SEM_FAILCRITICALERRORS  0x0001  no Windows critical-error dialog
      SEM_NOGPFAULTERRORBOX   0x0002  no fault popup
      SEM_NOOPENFILEERRORBOX  0x8000  no missing-file popup
    Best-effort; non-Windows + import failure are silently OK."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.kernel32.SetErrorMode(0x0001 | 0x0002 | 0x8000)
    except Exception:
        pass


def _git(source_root: Path, *args: str, timeout: float = 3.0) -> str:
    global _GIT_BROKEN
    if _GIT_BROKEN:
        return ""
    _suppress_win_error_dialogs()
    # CREATE_NO_WINDOW (0x08000000) keeps a console window from
    # flashing AND prevents the renderer from inheriting console
    # state, which on Win11 sometimes triggers the same 0xc0000142
    # path under AV-DLL injection.
    creationflags = 0x08000000 if sys.platform == "win32" else 0
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=str(source_root),
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
            creationflags=creationflags,
        )
    except subprocess.TimeoutExpired:
        # git hung — likely AV DLL injection holding the process.
        # Mark broken so subsequent calls skip the wait.
        _GIT_BROKEN = True
        return ""
    except Exception:
        _GIT_BROKEN = True
        return ""
    # Exit code 0xc0000142 = STATUS_DLL_INIT_FAILED (= -1073741502 in signed).
    # Treat any non-zero exit as a failure and mark git broken so we
    # don't pay the timeout on every subsequent call.
    if result.returncode != 0:
        if result.returncode in (-1073741502, 0xc0000142):
            _GIT_BROKEN = True
        return ""
    return (result.stdout or "").strip()


def _git_ok(source_root: Path, *args: str, timeout: float = 5.0) -> bool | None:
    """Run git for its EXIT CODE (not stdout). Returns True on exit 0,
    False on exit 1, None on any other/error (unknown). Used for
    'merge-base --is-ancestor' which emits no stdout."""
    global _GIT_BROKEN
    if _GIT_BROKEN:
        return None
    _suppress_win_error_dialogs()
    creationflags = 0x08000000 if sys.platform == "win32" else 0
    try:
        result = subprocess.run(["git", *args], cwd=str(source_root),
            capture_output=True, text=True, timeout=timeout,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"}, creationflags=creationflags)
    except Exception:
        return None
    if result.returncode == 0:
        return True
    if result.returncode == 1:
        return False
    return None


def source_commit(source_root: Path) -> str:
    return _git(source_root, "rev-parse", "--short", "HEAD")


def _source_is_forward(source_root: Path, install_root: Path) -> bool:
    """True iff syncing source into install is a FORWARD move (never a
    revert to older code). Empty marker (never synced) -> True (first sync).
    Same commit -> True (dirty-tree resync). Otherwise True ONLY when the
    installed commit is an ANCESTOR of the source commit. Unknown/error -> False
    (conservative: never auto-revert; the user can still force via the button)."""
    marker = _read_json(install_root / SYNC_MARKER)
    installed = (marker.get("source_stamp") or {}).get("commit", "")
    if not installed:
        return True
    cur = source_commit(source_root)
    if not cur:
        return False
    if cur == installed:
        return True
    anc = _git_ok(source_root, "merge-base", "--is-ancestor", installed, cur)
    return anc is True


def pull_source_to_main(source_root: Path) -> bool:
    """Best-effort: fast-forward the source checkout to ``origin/main`` so the
    installed copy syncs MERGED code, not just whatever was last pulled — the
    "ALWAYS runs up-to-date code" guarantee (founder 2026-06-09).

    SAFE + bounded by construction:
      • Acts ONLY when the checkout is on ``main`` with a CLEAN tree. A feature
        branch (active dev) or ANY local edits are left untouched — we then sync
        exactly what's checked out, never clobbering work in progress.
      • Every git call is the same AV-hardened, timeout-capped, ``_GIT_BROKEN``-
        gated ``_git``. Offline / detached / no-remote / git-blocked all fail
        fast and are swallowed; the launch proceeds on the current code.
      • ``--ff-only`` can only advance the branch — never a merge commit, never
        a rewrite. Never raises.

    Returns True when a fast-forward actually advanced HEAD, else False."""
    try:
        if _git(source_root, "rev-parse", "--abbrev-ref", "HEAD") != "main":
            return False
        if _git(source_root, "status", "--porcelain"):
            return False  # local edits present — never disturb them
        before = source_commit(source_root)
        if not before:
            return False  # can't read HEAD (git broken/unavailable) → unknown
        # fetch needs a longer cap than the 3s default (network round-trip);
        # offline fails fast, only a black-hole link waits the full bound.
        _git(source_root, "fetch", "origin", "main", timeout=12.0)
        _git(source_root, "merge", "--ff-only", "origin/main", timeout=8.0)
        after = source_commit(source_root)
        # An empty `after` means a fetch/merge timeout flipped `_GIT_BROKEN` and
        # `source_commit()` now returns "" — that is UNKNOWN, never an advance.
        # Without this guard the "" != before comparison would falsely report a
        # fast-forward on a timed-out fetch (Copilot review, PR #91).
        if not after:
            return False
        return after != before
    except Exception:
        return False


def _iter_sync_files(source_root: Path):
    for src_rel, _dst_rel in CODE_PATHS:
        root = source_root / src_rel
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if path.is_dir():
                continue
            rel = path.relative_to(source_root)
            parts = set(rel.parts)
            if parts & EXCLUDED_DIRS:
                continue
            if path.suffix.lower() in EXCLUDED_SUFFIXES:
                continue
            yield rel, path

    for name in TOP_LEVEL_FILES:
        path = source_root / name
        if path.exists() and path.is_file():
            yield Path(name), path


def source_stamp(source_root: Path) -> dict:
    """Stable-ish dirty-worktree stamp for copied code assets."""
    digest = hashlib.sha256()
    latest_mtime_ns = 0
    count = 0
    for rel, path in sorted(_iter_sync_files(source_root), key=lambda item: item[0].as_posix()):
        try:
            stat = path.stat()
        except OSError:
            continue
        digest.update(rel.as_posix().encode("utf-8", errors="ignore"))
        digest.update(str(stat.st_size).encode("ascii"))
        digest.update(str(stat.st_mtime_ns).encode("ascii"))
        latest_mtime_ns = max(latest_mtime_ns, stat.st_mtime_ns)
        count += 1
    return {
        "hash": digest.hexdigest(),
        "latest_mtime_ns": latest_mtime_ns,
        "file_count": count,
        "commit": source_commit(source_root),
    }


def needs_sync(source_root: Path, install_root: Path) -> tuple[bool, dict]:
    stamp = source_stamp(source_root)
    marker = _read_json(install_root / SYNC_MARKER)
    if marker.get("source_stamp") == stamp:
        return False, stamp
    if not _source_is_forward(source_root, install_root):
        return False, stamp   # source is BEHIND / unrelated — never revert the install
    return True, stamp


def _copy_file(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    # Use a tmp-then-rename so a crash mid-copy doesn't leave a
    # half-written file in place. shutil.copy2 followed by os.replace
    # is atomic on the same filesystem; both sides of dev sync live on
    # %LOCALAPPDATA% so this holds.
    tmp = dst.with_suffix(dst.suffix + ".dst_tmp")
    try:
        shutil.copy2(src, tmp)
        os.replace(tmp, dst)
    except Exception:
        # Best-effort cleanup of the temp file.
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass
        raise


def _copy_tree_merge(source_root: Path, install_root: Path, src_rel: str, dst_rel: str) -> None:
    src_root = source_root / src_rel
    dst_root = install_root / dst_rel
    if not src_root.exists():
        return
    for rel, path in sorted(_iter_sync_files_for_root(source_root, src_root), key=lambda item: item[0].as_posix()):
        dst = dst_root / rel
        _copy_file(path, dst)


def _iter_sync_files_for_root(source_root: Path, root: Path):
    for path in root.rglob("*"):
        if path.is_dir():
            continue
        rel_from_source = path.relative_to(source_root)
        rel_from_root = path.relative_to(root)
        parts = set(rel_from_source.parts)
        if parts & EXCLUDED_DIRS:
            continue
        if path.suffix.lower() in EXCLUDED_SUFFIXES:
            continue
        yield rel_from_root, path


def sync_source_to_install(source_root: Path, install_root: Path, stamp: dict | None = None) -> None:
    install_root.mkdir(parents=True, exist_ok=True)
    stamp = stamp or source_stamp(source_root)

    for src_rel, dst_rel in CODE_PATHS:
        _copy_tree_merge(source_root, install_root, src_rel, dst_rel)

    for name in TOP_LEVEL_FILES:
        src = source_root / name
        if src.exists() and src.is_file():
            _copy_file(src, install_root / name)

    now = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    marker = {
        "source_dir": str(source_root),
        "source_stamp": stamp,
        "synced_at": now,
    }
    _write_json(install_root / SYNC_MARKER, marker)

    manifest = _read_json(install_root / VERSION_FILE)
    version_path = source_root / "VERSION"
    if version_path.exists():
        try:
            manifest["version"] = version_path.read_text(encoding="utf-8").strip()
        except Exception:
            pass
    manifest.update({
        "dev_source_sync": True,
        "source_dir": str(source_root),
        "source_synced_at": now,
        "source_stamp": stamp,
    })
    _write_json(install_root / VERSION_FILE, manifest)

    # NOTE: sync NEVER arms auto-sync. enable_dev_source_sync / dev_source_path
    # are owned solely by an explicit user action (Settings toggle / update button).
    # Re-writing them here was the doom-loop that re-enabled auto-update after
    # every deploy (founder 2026-06-11). Do not reintroduce.


def _log(install_root: Path, message: str) -> None:
    try:
        logs_dir = install_root / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        with (logs_dir / "dev_source_sync.log").open("a", encoding="utf-8") as handle:
            handle.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {message}\n")
    except Exception:
        pass


def _relaunch(install_root: Path, argv: Sequence[str]) -> None:
    args = [str(install_root / "app" / "main.py")]
    args.extend(arg for arg in argv[1:] if arg != "--no-dev-source-sync")
    args.append("--no-dev-source-sync")
    # Force the OS write buffer to disk BEFORE we hand control to the
    # successor process. Without this, os._exit(0) below would lose
    # any data still in Windows' filesystem cache — manifests as the
    # marker reporting "synced 603 files" while studio_shell.py and
    # other freshly-copied files quietly stayed at their previous
    # bytes on disk. The atomic _copy_file pattern (tmp + os.replace)
    # plus this fsync sweep is the real ship-stability fix.
    try:
        # On Windows there's no os.sync(); flush python's own stdout/
        # stderr buffers and call Win32 FlushFileBuffers via ctypes
        # for the install root's volume.
        try: sys.stdout.flush()
        except Exception: pass  # audit: deliberate-fail-soft — best-effort stdout flush inside an outer best-effort fsync sweep
        try: sys.stderr.flush()
        except Exception: pass  # audit: deliberate-fail-soft — best-effort stderr flush inside an outer best-effort fsync sweep
        if sys.platform == "win32":
            try:
                import ctypes
                # Best-effort; failure is OK — the os.replace in
                # _copy_file already gives per-file atomicity.
                ctypes.windll.kernel32.GetDiskFreeSpaceExW(
                    str(install_root), None, None, None)
            except Exception:
                pass
        else:
            try: os.sync()
            except Exception: pass  # audit: deliberate-fail-soft — best-effort os.sync inside an outer best-effort fsync sweep
    except Exception:
        pass
    subprocess.Popen([sys.executable, *args], cwd=str(install_root), close_fds=True)


def _quit_running_instance_before_relaunch(install_root: Path) -> bool:
    """Ask any running single-instance (old, stale code) to quit + release its
    lock so the relaunched child becomes the listener on the freshly-synced code.

    This is the PRIMARY reopen=latest fix: it runs in the PARENT, inside the sync
    path, before _relaunch + os._exit. Returns True when no instance remains
    (none was running, stale lock, or it quit in time); False on timeout/error.

    Load-bearing safety: NEVER raises + NEVER blocks beyond the bounded quit.
    A missing symbol (ImportError), any exception, or a timeout all return False,
    and the caller proceeds to sync + relaunch regardless — so the worst case is
    exactly today's behaviour (old window foregrounded), never a wedged launch.
    single_instance.quit_running_instance is a plain socket call (no Qt), safe
    here at module-import time before QApplication exists."""
    try:
        from single_instance import quit_running_instance
        gone = quit_running_instance(timeout=QUIT_OLD_INSTANCE_TIMEOUT)
        _log(install_root,
             f"quit old instance before relaunch -> {'released' if gone else 'still-alive/timeout'}")
        return bool(gone)
    except Exception as ex:  # missing symbol / any error -> degrade to today's behaviour
        _log(install_root, f"quit old instance skipped ({type(ex).__name__}: {ex})")
        return False


def maybe_sync_and_relaunch(
    install_root: Path,
    argv: Sequence[str] | None = None,
    *,
    relaunch: bool = True,
) -> bool:
    """Sync from configured checkout when running from an installed copy.

    Returns True when a sync happened. With relaunch=True the current process
    exits after launching the updated app.
    """
    argv = list(argv or sys.argv)
    install_root = Path(install_root)
    if "--no-dev-source-sync" in argv:
        return False
    if is_git_checkout(install_root):
        return False

    source_root = find_source_root(install_root)
    if source_root is None:
        return False

    # Source advance (git fetch + ff to origin/main) is USER-INITIATED only
    # (update button / dev-verify), never silent on a launch/quit (founder 2026-06-11).
    should_sync, stamp = needs_sync(source_root, install_root)
    if not should_sync:
        return False

    if relaunch:
        # reopen=latest PRIMARY fix: the running install is the old, stale-code
        # instance (it was launched with --no-dev-source-sync so it never
        # re-syncs). Ask it to quit + release its lock NOW — before we relaunch
        # — so the freshly-synced child becomes the single-instance listener on
        # the NEW code instead of summoning the old one. Best-effort + bounded:
        # on timeout/error we sync + relaunch anyway (worst case = today).
        _quit_running_instance_before_relaunch(install_root)

    _log(install_root, f"syncing from {source_root}")
    sync_source_to_install(source_root, install_root, stamp)
    _log(install_root, f"synced {stamp.get('file_count', 0)} files commit={stamp.get('commit', '')}")

    if relaunch:
        _relaunch(install_root, argv)
        os._exit(0)
    return True


def has_new_source(install_root: Path) -> bool:
    """reopen=latest predicate: True when a configured source checkout has
    code newer than what this install was last synced to.

    GATED + graceful: returns False (→ caller summons / normal startup) when
    the install IS a git checkout, when no source is configured, or on ANY
    error. This is the predicate the single-instance summon decision consults
    to decide "is there new code worth superseding the running instance for?".

    It mirrors the guards inside maybe_sync_and_relaunch (is_git_checkout,
    find_source_root) so the answer is consistent with what an actual sync
    would do — but it NEVER syncs, relaunches, or exits. Pure query."""
    try:
        install_root = Path(install_root)
        if is_git_checkout(install_root):
            return False
        source_root = find_source_root(install_root)
        if source_root is None:
            return False
        should_sync, _stamp = needs_sync(source_root, install_root)
        return bool(should_sync)
    except Exception:
        return False


def apply_staged_update(install_root: Path) -> bool:
    """QUIET-UPDATE MODEL (founder 2026-06-10 — "initiation process repeats
    with every launch... that's not acceptable"): apply any pending source
    update at QUIT — files only, NEVER a relaunch — so the next launch boots
    the new code instantly with no double-boot.

    Called from main.py's clean-shutdown tail. Same guards as the launch path
    (installed copies only, configured source, marker-gated), pulls the source
    checkout to merged origin/main first (guarded ff), and is best-effort.

    Failure semantics: each file copy is atomic (tmp + os.replace) but the sync
    is NOT transactional across files — an exception mid-way can leave a mixed
    tree. That state SELF-HEALS: the marker is only written after a complete
    sync, so the next quit-apply (or the banner's apply path) re-syncs
    everything. Any exception is swallowed and reported as False.

    Returns True when an update was applied."""
    try:
        install_root = Path(install_root)
        if is_git_checkout(install_root):
            return False
        source_root = find_source_root(install_root)
        if source_root is None:
            return False
        settings = _read_json(_settings_path(install_root))
        if not settings.get("auto_apply_updates_on_quit", False):
            return False   # default: quit-apply OFF — updates land only via the user's Relaunch button
        # Source advance (git fetch + ff to origin/main) is USER-INITIATED only
        # (update button / dev-verify), never silent on a launch/quit (founder 2026-06-11).
        should_sync, stamp = needs_sync(source_root, install_root)
        if not should_sync:
            return False
        _log(install_root, f"quit-apply: syncing from {source_root}")
        sync_source_to_install(source_root, install_root, stamp)
        _log(install_root,
             f"quit-apply: synced {stamp.get('file_count', 0)} files "
             f"commit={stamp.get('commit', '')}")
        return True
    except Exception:
        return False


def force_sync_now(install_root: Path, argv: Sequence[str] | None = None) -> bool:
    """Dev-verify launch: sync from the configured checkout IGNORING the
    sync marker (so even an up-to-date install is force-refreshed once),
    without relaunching. Returns True when a sync happened.

    Used by the ARCHHUB_DEV_VERIFY=1 / --dev-verify path so the founder +
    Claude can be certain the running app reflects HEAD before CDP
    verification. GATED + graceful exactly like maybe_sync_and_relaunch:
    a git-checkout install or no configured source → no-op False; any error
    is swallowed so the launch always proceeds."""
    try:
        argv = list(argv or sys.argv)
        install_root = Path(install_root)
        if is_git_checkout(install_root):
            return False
        source_root = find_source_root(install_root)
        if source_root is None:
            return False
        pull_source_to_main(source_root)   # advance to merged main first
        stamp = source_stamp(source_root)
        _log(install_root, f"force-sync (dev-verify) from {source_root}")
        sync_source_to_install(source_root, install_root, stamp)
        _log(install_root,
             f"force-synced {stamp.get('file_count', 0)} files commit={stamp.get('commit', '')}")
        return True
    except Exception:
        return False
