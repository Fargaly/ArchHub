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


def _git(source_root: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=str(source_root),
            capture_output=True,
            text=True,
            timeout=8,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        )
    except Exception:
        return ""
    return (result.stdout or "").strip() if result.returncode == 0 else ""


def source_commit(source_root: Path) -> str:
    return _git(source_root, "rev-parse", "--short", "HEAD")


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
    return marker.get("source_stamp") != stamp, stamp


def _copy_file(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


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

    settings = _read_json(_settings_path(install_root))
    settings["enable_dev_source_sync"] = True
    settings["dev_source_path"] = str(source_root)
    _write_json(_settings_path(install_root), settings)


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
    subprocess.Popen([sys.executable, *args], cwd=str(install_root), close_fds=True)


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

    should_sync, stamp = needs_sync(source_root, install_root)
    if not should_sync:
        return False

    _log(install_root, f"syncing from {source_root}")
    sync_source_to_install(source_root, install_root, stamp)
    _log(install_root, f"synced {stamp.get('file_count', 0)} files commit={stamp.get('commit', '')}")

    if relaunch:
        _relaunch(install_root, argv)
        os._exit(0)
    return True
