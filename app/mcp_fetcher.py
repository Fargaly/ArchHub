"""Cloud-first fetch of prebuilt MCP connector DLLs.

CI builds RevitMCP / AcadMCP / etc. on every release tag and uploads
`ArchHub-MCP-Binaries.zip` as a release asset. When the user toggles
a connector ON and the local payload/<family>/<year>/ directory is
empty, this module pulls the zip from GitHub Releases and extracts
only the slice the connector needs.

Why cloud-first: building C# locally requires a .NET SDK (and for
older Revit years, the .NET Framework 4.8 Developer Pack) that the
average architect doesn't have. CI does it once, every install
re-uses the result.

Falls back to `auto_build.py` (the local-build path) if every
mirror is unreachable — useful for air-gapped sites.
"""
from __future__ import annotations

import io
import json
import os
import shutil
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

# Where built binaries land — same root the connector activator reads.
APP_ROOT = Path(__file__).resolve().parent
PAYLOAD_DIR = APP_ROOT.parent / "payload"

# Public asset name written by .github/workflows/release.yml.
MCP_ASSET_NAME = "ArchHub-MCP-Binaries.zip"

# Repo for the public Release feed.
GH_OWNER = "Fargaly"
GH_REPO = "ArchHub"

# How long to keep a downloaded zip cached locally.
CACHE_DIR = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "ArchHub" / "_mcp_cache"

ProgressFn = Callable[[str, int, str], None]


@dataclass
class FetchResult:
    success: bool
    detail: str
    files_written: list[Path]


# ---------------------------------------------------------------------------
def _read_token() -> Optional[str]:
    """Try gh CLI's stored token (works for private-repo releases too)."""
    try:
        import subprocess
        out = subprocess.run(
            ["gh", "auth", "token"], capture_output=True, text=True, timeout=5,
        )
        if out.returncode == 0:
            tok = (out.stdout or "").strip()
            if tok:
                return tok
    except Exception:
        pass
    return os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN") or None


def _gh_get(url: str, accept: str = "application/json") -> bytes:
    """GET against GitHub with optional bearer token. Raises on non-2xx."""
    req = urllib.request.Request(
        url,
        headers={
            "Accept": accept,
            "User-Agent": "ArchHub-MCP-Fetcher",
            **({"Authorization": f"Bearer {_read_token()}"} if _read_token() else {}),
        },
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


# ---------------------------------------------------------------------------
def latest_release_tag() -> Optional[str]:
    """Return the most recent release tag (`v0.20.1`) or None on failure."""
    try:
        data = json.loads(_gh_get(
            f"https://api.github.com/repos/{GH_OWNER}/{GH_REPO}/releases/latest"
        ))
        return data.get("tag_name")
    except Exception:
        return None


def find_asset_url(tag: str) -> Optional[str]:
    """Return the browser-download URL for the MCP zip in a release."""
    try:
        data = json.loads(_gh_get(
            f"https://api.github.com/repos/{GH_OWNER}/{GH_REPO}/releases/tags/{tag}"
        ))
        for a in data.get("assets") or []:
            if a.get("name") == MCP_ASSET_NAME:
                return a.get("url") or a.get("browser_download_url")
    except Exception:
        return None
    return None


# ---------------------------------------------------------------------------
def _cached_zip_for(tag: str) -> Path:
    return CACHE_DIR / f"mcp-{tag}.zip"


def _download_zip(asset_url: str, dest: Path,
                  on_progress: Optional[ProgressFn] = None) -> None:
    """Download the zip to dest. Honours both the API asset URL (octet-stream
    redirect) and a direct browser_download_url."""
    on_progress = on_progress or (lambda *_a, **_k: None)
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(
        asset_url,
        headers={
            "Accept": "application/octet-stream",
            "User-Agent": "ArchHub-MCP-Fetcher",
            **({"Authorization": f"Bearer {_read_token()}"} if _read_token() else {}),
        },
    )
    on_progress("Downloading MCP binaries", 30, asset_url)
    with urllib.request.urlopen(req, timeout=120) as r:
        total = int(r.headers.get("Content-Length") or 0)
        chunk = 64 * 1024
        with dest.open("wb") as fh:
            read = 0
            while True:
                buf = r.read(chunk)
                if not buf:
                    break
                fh.write(buf)
                read += len(buf)
                if total:
                    pct = 30 + int(60 * read / total)
                    on_progress("Downloading MCP binaries", pct,
                                f"{read//1024} / {total//1024} KB")


def _extract_slice(zip_path: Path, family: str, year: int,
                   on_progress: Optional[ProgressFn] = None) -> list[Path]:
    """Extract just `payload/<family>/<year>/` out of the release zip into
    the repo's payload/. Returns the list of files written."""
    on_progress = on_progress or (lambda *_a, **_k: None)
    prefix = f"payload/{family}/{year}/"
    out_dir = PAYLOAD_DIR / family / str(year)
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    with zipfile.ZipFile(zip_path) as z:
        members = [m for m in z.namelist() if m.startswith(prefix) and not m.endswith("/")]
        if not members:
            # Older zips may not include the family/year. Try the bare top
            # form `<family>/<year>/...` too.
            alt_prefix = f"{family}/{year}/"
            members = [m for m in z.namelist() if m.startswith(alt_prefix) and not m.endswith("/")]
            prefix = alt_prefix
        for m in members:
            rel = m[len(prefix):]
            target = out_dir / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            with z.open(m) as src, target.open("wb") as dst:
                shutil.copyfileobj(src, dst)
            written.append(target)
            on_progress("Extracting", 95, str(target.name))
    return written


# ---------------------------------------------------------------------------
def fetch_connector(family: str, year: int,
                    on_progress: Optional[ProgressFn] = None,
                    tag: Optional[str] = None) -> FetchResult:
    """Pull the MCP binaries for `family/year` from the latest release.

    `tag` lets the caller pin a specific release (useful for tests or
    when an older client must talk to an older Revit). Default is the
    latest published release.
    """
    on_progress = on_progress or (lambda *_a, **_k: None)
    on_progress("Looking up latest release", 5, "")
    tag = tag or latest_release_tag()
    if not tag:
        return FetchResult(False, "Could not reach GitHub Releases.", [])

    cached = _cached_zip_for(tag)
    if not cached.exists():
        url = find_asset_url(tag)
        if not url:
            return FetchResult(False, f"No {MCP_ASSET_NAME} on release {tag}.", [])
        try:
            _download_zip(url, cached, on_progress=on_progress)
        except Exception as ex:
            try:
                cached.unlink(missing_ok=True)
            except Exception:
                pass
            return FetchResult(False, f"Download failed: {ex}", [])

    on_progress("Extracting", 90, f"{family}/{year}")
    try:
        written = _extract_slice(cached, family, year, on_progress=on_progress)
    except Exception as ex:
        return FetchResult(False, f"Extract failed: {ex}", [])

    if not written:
        return FetchResult(
            False,
            f"Release {tag} doesn't ship MCP binaries for {family} {year}. "
            "Falling back to local build.",
            [],
        )

    on_progress("Done", 100, f"{len(written)} files")
    return FetchResult(True, f"Fetched {len(written)} files from {tag}.", written)
