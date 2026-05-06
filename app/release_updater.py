"""Release-based auto-update.

For users who installed via Setup-ArchHub-x.y.z.exe (Inno Setup), updates
arrive as new GitHub Releases attached to the public-or-private repo at
github.com/Fargaly/ArchHub. This module:

  - Reads the local version stamp (installer/version.json or VERSION)
  - Asks GitHub Releases API for the latest release
  - Compares versions
  - When newer, downloads the .exe asset
  - Runs it with `/SILENT /SUPPRESSMSGBOXES /CLOSEAPPLICATIONS` so it
    upgrades in place without UI interruption
  - Tells the launcher to relaunch ArchHub after the installer exits

For development users (running from a git clone), `updater.py` (git pull
based) remains the right path. The two coexist: in_git_checkout() picks
which one applies.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


REPO_OWNER = "Fargaly"
REPO_NAME = "ArchHub"
ASSET_PATTERN = re.compile(r"^ArchHub-Setup.*\.exe$", re.IGNORECASE)
DOWNLOAD_TIMEOUT_SECONDS = 600


@dataclass
class ReleaseInfo:
    tag: str = ""               # "v0.11.0"
    name: str = ""              # human title of the release
    body: str = ""              # markdown release notes
    asset_url: str = ""         # download URL for the installer
    asset_size: int = 0         # bytes
    published_at: str = ""      # ISO timestamp
    error: str = ""

    @property
    def version_tuple(self) -> tuple[int, ...]:
        """Numeric tuple parsed from the tag for comparison. Falls back to
        (0,) if the tag isn't semver-shaped."""
        return _version_tuple(self.tag)


# ---------------------------------------------------------------------------
def _version_tuple(version: str) -> tuple[int, ...]:
    """Convert 'v0.11.0' / '0.11.0' / '0.11' → (0, 11, 0). Unknown shapes → (0,)."""
    if not version:
        return (0,)
    cleaned = version.strip().lstrip("vV")
    parts = re.split(r"[^0-9]+", cleaned)
    nums = [int(p) for p in parts if p.isdigit()]
    return tuple(nums) if nums else (0,)


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def in_git_checkout() -> bool:
    return (repo_root() / ".git").exists()


def installed_version() -> str:
    """Local version, in priority order:

      1. installer/version.json written by Inno Setup at install time
      2. top-level VERSION file (always present in the source tree)
    """
    # Inno-generated stamp lives at the install root.
    stamp = repo_root() / "version.json"
    if stamp.exists():
        try:
            data = json.loads(stamp.read_text(encoding="utf-8"))
            v = data.get("version", "")
            if v:
                return v
        except Exception:
            pass
    version_file = repo_root() / "VERSION"
    if version_file.exists():
        try:
            return version_file.read_text(encoding="utf-8").strip()
        except Exception:
            pass
    return ""


def _gh_token() -> str:
    """Token from gh CLI if available, else from env. Empty string if neither."""
    try:
        from cloud_sync import auth_token
        tok = auth_token()
        if tok:
            return tok
    except Exception:
        pass
    return os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN") or ""


def fetch_latest_release() -> ReleaseInfo:
    """Hit the GitHub Releases API for the most recent published release."""
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/releases/latest"
    req = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": f"ArchHub/{installed_version() or 'dev'}",
    })
    token = _gh_token()
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    info = ReleaseInfo()
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as ex:
        info.error = f"Could not reach GitHub Releases: {ex}"
        return info

    info.tag = data.get("tag_name", "") or ""
    info.name = data.get("name", "") or info.tag
    info.body = data.get("body", "") or ""
    info.published_at = data.get("published_at", "") or ""

    for asset in data.get("assets", []) or []:
        name = asset.get("name", "") or ""
        if ASSET_PATTERN.match(name):
            info.asset_url = asset.get("browser_download_url", "") or ""
            info.asset_size = asset.get("size", 0) or 0
            break
    if not info.asset_url:
        info.error = (
            f"Latest release {info.tag} is missing a Setup-ArchHub-*.exe "
            f"asset. The CI build may have failed."
        )
    return info


def has_update_available() -> tuple[bool, ReleaseInfo, str]:
    """Return (newer_available, release_info, local_version)."""
    local = installed_version()
    info = fetch_latest_release()
    if info.error:
        return False, info, local
    return _version_tuple(info.tag) > _version_tuple(local), info, local


# ---------------------------------------------------------------------------
def download_asset(release: ReleaseInfo, dest_dir: Optional[Path] = None,
                   on_progress: Optional[callable] = None) -> Path:
    """Download the release's installer to a temp path. Returns the path."""
    if not release.asset_url:
        raise RuntimeError("Release has no installer asset to download.")
    target_dir = Path(dest_dir or tempfile.gettempdir())
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"ArchHub-Setup-{release.tag.lstrip('vV') or 'latest'}.exe"

    req = urllib.request.Request(release.asset_url, headers={
        "Accept": "application/octet-stream",
        "User-Agent": f"ArchHub/{installed_version() or 'dev'}",
    })
    token = _gh_token()
    if token:
        req.add_header("Authorization", f"Bearer {token}")

    with urllib.request.urlopen(req, timeout=DOWNLOAD_TIMEOUT_SECONDS) as resp, \
            target.open("wb") as out:
        total = release.asset_size or 0
        downloaded = 0
        while True:
            chunk = resp.read(64 * 1024)
            if not chunk:
                break
            out.write(chunk)
            downloaded += len(chunk)
            if on_progress is not None and total:
                try:
                    on_progress(downloaded, total)
                except Exception:
                    pass
    return target


def run_installer(installer_path: Path, *, silent: bool = True,
                  relaunch: bool = True) -> None:
    """Spawn the installer and exit the current process so the installer
    can replace running files. Inno Setup's silent flags upgrade in place
    and (because the .iss has CloseApplications=force) close any old
    ArchHub instances itself.

    Inno's `/RESTARTAPPLICATIONS` flag re-launches what it closed when the
    install finishes. We pass it when relaunch=True so the user lands back
    on a running, upgraded ArchHub without doing anything.
    """
    if not installer_path.exists():
        raise FileNotFoundError(f"Installer not found at {installer_path}")
    args = [str(installer_path)]
    if silent:
        args.extend(["/SILENT", "/SUPPRESSMSGBOXES", "/NOCANCEL", "/NORESTART"])
    if relaunch:
        args.append("/RESTARTAPPLICATIONS")

    creationflags = 0
    if sys.platform == "win32":
        creationflags = (
            getattr(subprocess, "DETACHED_PROCESS", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        )
    subprocess.Popen(args, creationflags=creationflags, close_fds=True)
    # Give the installer a beat before we exit so it has spawned its own
    # process and won't be killed when this one terminates.
    import time
    time.sleep(1.0)
    os._exit(0)
