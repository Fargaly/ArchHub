"""Quiet self-update, the way Chrome and Claude Desktop do it.

While the app runs, the newest release is checked once in the background; a
newer build is downloaded to the state folder and verified by SHA-256. Nothing
is applied while the founder works. The NEXT launch applies the staged
installer silently before booting (in-place upgrade, the graph untouched) and
re-launches itself. A build is identified by BUILD_ID, written by the installer
and published in the release notes, because the beta ships under one label (0).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

RELEASE_API = "https://api.github.com/repos/Fargaly/ArchHub/releases/latest"
ASSET_NAME = "ArchHub-Setup-0.exe"
_BUILD_RE = re.compile(r"BUILD_ID:\s*([A-Za-z0-9._-]+)")
_SHA_RE = re.compile(r"SHA256 " + re.escape(ASSET_NAME) + r":\s*([0-9a-fA-F]{64})")


def installed_build_id(app_dir: Path) -> str:
    try:
        return (app_dir / "BUILD_ID").read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def read_latest_release(opener=urllib.request.urlopen) -> dict | None:
    """{build_id, sha256, url, tag} from the latest release, or None."""
    request = urllib.request.Request(RELEASE_API, headers={"Accept": "application/vnd.github+json", "User-Agent": "ArchHub"})
    try:
        with opener(request, timeout=15) as response:
            data = json.loads(response.read().decode("utf-8"))
    except Exception:
        return None
    body = str(data.get("body") or "")
    build = _BUILD_RE.search(body)
    sha = _SHA_RE.search(body)
    asset = next((a for a in data.get("assets") or [] if a.get("name") == ASSET_NAME), None)
    if not (build and sha and asset):
        return None
    return {"build_id": build.group(1), "sha256": sha.group(1).lower(), "url": asset["browser_download_url"], "tag": data.get("tag_name")}


def stage_if_newer(state_dir: Path, app_dir: Path, opener=urllib.request.urlopen) -> dict:
    """Download + verify a newer build into state_dir/updates; never apply."""
    current = installed_build_id(app_dir)
    latest = read_latest_release(opener)
    if latest is None:
        return {"staged": False, "reason": "no release information"}
    if not current or latest["build_id"] == current:
        return {"staged": False, "reason": "up to date", "build_id": current}
    updates = state_dir / "updates"
    updates.mkdir(parents=True, exist_ok=True)
    target = updates / ASSET_NAME
    marker = updates / "staged.json"
    if marker.exists():
        try:
            staged = json.loads(marker.read_text(encoding="utf-8"))
            if staged.get("build_id") == latest["build_id"] and target.exists():
                return {"staged": True, "reason": "already staged", "build_id": latest["build_id"]}
        except Exception:
            pass
    partial = updates / (ASSET_NAME + ".part")
    digest = hashlib.sha256()
    with opener(urllib.request.Request(latest["url"], headers={"User-Agent": "ArchHub"}), timeout=120) as response, open(partial, "wb") as out:
        while True:
            chunk = response.read(1 << 16)
            if not chunk:
                break
            digest.update(chunk)
            out.write(chunk)
    if digest.hexdigest() != latest["sha256"]:
        partial.unlink(missing_ok=True)
        return {"staged": False, "reason": "download did not match the published SHA-256"}
    os.replace(partial, target)
    marker.write_text(json.dumps({"build_id": latest["build_id"], "sha256": latest["sha256"], "tag": latest["tag"]}), encoding="utf-8")
    return {"staged": True, "reason": "downloaded and verified", "build_id": latest["build_id"]}


def apply_staged(state_dir: Path, app_dir: Path, runner=subprocess.run) -> dict:
    """At launch, before boot: install the staged build silently if it verifies."""
    updates = state_dir / "updates"
    target = updates / ASSET_NAME
    marker = updates / "staged.json"
    if not (target.exists() and marker.exists()):
        return {"applied": False, "reason": "nothing staged"}
    try:
        staged = json.loads(marker.read_text(encoding="utf-8"))
    except Exception:
        return {"applied": False, "reason": "staged marker unreadable"}
    if staged.get("build_id") == installed_build_id(app_dir):
        target.unlink(missing_ok=True); marker.unlink(missing_ok=True)
        return {"applied": False, "reason": "staged build already installed"}
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    if digest != str(staged.get("sha256", "")).lower():
        target.unlink(missing_ok=True); marker.unlink(missing_ok=True)
        return {"applied": False, "reason": "staged file no longer matches its SHA-256"}
    result = runner([str(target), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/DIR=" + str(app_dir)], timeout=600)
    code = getattr(result, "returncode", 1)
    target.unlink(missing_ok=True); marker.unlink(missing_ok=True)
    return {"applied": code == 0, "reason": "installer exit %s" % code, "build_id": staged.get("build_id")}


__all__ = ["apply_staged", "installed_build_id", "read_latest_release", "stage_if_newer", "ASSET_NAME"]
