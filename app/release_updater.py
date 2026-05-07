"""Release-based auto-update.

For users who installed via Setup-ArchHub-x.y.z.exe (Inno Setup), updates
arrive as new GitHub Releases attached to a private repo at
github.com/Fargaly/ArchHub.

Why this is harder than it looks: the repo is **private**, so an
unauthenticated GET against api.github.com/.../releases/latest returns
404 (GitHub's anti-leaking behaviour). We cannot ship a long-lived
token in the app. So this module talks to the GitHub CLI (`gh`) when it
is installed, because the user already authenticated `gh` once during
onboarding and `gh` keeps the token in their Windows Credential Manager
for us.

Fallback chain for fetching the latest release:

  1. `gh release view --repo Fargaly/ArchHub --json ...`
     Authenticated automatically through the user's stored `gh` token.
  2. `gh api repos/Fargaly/ArchHub/releases/latest`
     Same token; raw API. Used if `gh release view` shape changes.
  3. urllib.request to api.github.com with an explicit Bearer token
     pulled from `gh auth token`. Last-ditch path; works even if `gh`
     isn't on PATH but the env has GH_TOKEN/GITHUB_TOKEN.

For development users running from a git clone (`updater.in_git_checkout()`
is True) the existing git-pull updater remains the right path. The two
coexist; UpdateDialog picks the correct one.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


REPO_OWNER = "Fargaly"
REPO_NAME = "ArchHub"
REPO_SLUG = f"{REPO_OWNER}/{REPO_NAME}"
ASSET_PATTERN = re.compile(r"^ArchHub-Setup.*\.exe$", re.IGNORECASE)
DOWNLOAD_TIMEOUT_SECONDS = 600
GH_TIMEOUT_SECONDS = 30


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


def _gh_on_path() -> bool:
    return shutil.which("gh") is not None


def _run_gh(*args: str) -> tuple[int, str, str]:
    """Invoke gh with a forced GH_TOKEN derived from `gh auth token`.

    On Windows, gh's keyring lookup can fail when launched from a non-
    interactive subprocess due to Credential Manager scoping (see
    cloud_sync for the same workaround). Fetching the token explicitly
    once and re-injecting it via env makes downstream gh calls reliable
    regardless of how ArchHub itself was launched.
    """
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    token = _gh_token()
    if token:
        env["GH_TOKEN"] = token
    try:
        result = subprocess.run(
            ["gh", *args], capture_output=True, text=True,
            timeout=GH_TIMEOUT_SECONDS, env=env,
        )
        return result.returncode, (result.stdout or "").strip(), (result.stderr or "").strip()
    except FileNotFoundError:
        return 127, "", "gh is not installed or not on PATH"
    except subprocess.TimeoutExpired:
        return 124, "", f"gh timed out after {GH_TIMEOUT_SECONDS}s"


def _populate_release_info(data: dict) -> ReleaseInfo:
    """Map a GitHub release JSON object to a ReleaseInfo."""
    info = ReleaseInfo()
    info.tag = data.get("tagName") or data.get("tag_name") or ""
    info.name = data.get("name") or info.tag
    info.body = data.get("body") or ""
    info.published_at = data.get("publishedAt") or data.get("published_at") or ""

    for asset in (data.get("assets") or []):
        name = asset.get("name") or ""
        if ASSET_PATTERN.match(name):
            # Newer gh versions expose "url" for the API asset URL and
            # "browser_download_url" / "browserDownloadUrl" for direct
            # download. We accept any of them.
            info.asset_url = (
                asset.get("browser_download_url")
                or asset.get("browserDownloadUrl")
                or asset.get("url")
                or ""
            )
            info.asset_size = asset.get("size") or 0
            break
    if not info.asset_url and not info.error:
        info.error = (
            f"Latest release {info.tag} is missing a Setup-ArchHub-*.exe "
            f"asset. The CI build may have failed."
        )
    return info


def fetch_latest_release() -> ReleaseInfo:
    """Get the most-recent release. Tries gh first (handles private repos
    cleanly), falls back to the raw API with a Bearer token."""

    # ── Path 1: gh release view ────────────────────────────────────────
    if _gh_on_path():
        rc, out, err = _run_gh(
            "release", "view", "--repo", REPO_SLUG,
            "--json", "tagName,name,body,publishedAt,assets",
        )
        if rc == 0 and out:
            try:
                return _populate_release_info(json.loads(out))
            except json.JSONDecodeError:
                pass     # fall through

        # ── Path 2: gh api raw ─────────────────────────────────────────
        rc, out, err = _run_gh(
            "api", f"repos/{REPO_SLUG}/releases/latest",
        )
        if rc == 0 and out:
            try:
                return _populate_release_info(json.loads(out))
            except json.JSONDecodeError:
                pass

    # ── Path 3: urllib + Bearer token ──────────────────────────────────
    info = ReleaseInfo()
    url = f"https://api.github.com/repos/{REPO_SLUG}/releases/latest"
    req = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": f"ArchHub/{installed_version() or 'dev'}",
    })
    token = _gh_token()
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as ex:
        # Most common cause for 404: private repo + missing/expired token.
        if ex.code == 404:
            info.error = (
                "Could not find releases. ArchHub's repo is private; "
                "ensure the GitHub CLI is signed in (`gh auth login`) "
                "and that this account has access."
            )
        elif ex.code == 401:
            info.error = "Authentication failed against GitHub. Re-run `gh auth login`."
        else:
            info.error = f"GitHub API error {ex.code}: {ex.reason}"
        return info
    except Exception as ex:
        info.error = f"Could not reach GitHub Releases: {ex}"
        return info
    return _populate_release_info(data)


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
    """Download the release's installer to a temp path. Returns the path.

    Uses `gh release download` when gh is on PATH because that path
    works for private repos out of the box. Falls back to a streaming
    urllib GET with a Bearer token (which also works, but only when the
    token is reachable from this process)."""
    target_dir = Path(dest_dir or tempfile.gettempdir())
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"ArchHub-Setup-{(release.tag or 'latest').lstrip('vV')}.exe"
    if target.exists():
        try:
            target.unlink()
        except Exception:
            pass

    # ── Path 1: gh release download ────────────────────────────────────
    if _gh_on_path() and release.tag:
        rc, out, err = _run_gh(
            "release", "download", release.tag,
            "--repo", REPO_SLUG,
            "--pattern", "ArchHub-Setup-*.exe",
            "--output", str(target),
            "--clobber",
        )
        if rc == 0 and target.exists():
            if on_progress is not None and target.stat().st_size:
                try:
                    on_progress(target.stat().st_size, target.stat().st_size)
                except Exception:
                    pass
            return target
        # else: fall through to direct download

    # ── Path 2: direct urllib stream w/ token ──────────────────────────
    if not release.asset_url:
        raise RuntimeError(
            "Release has no installer URL and gh download didn't produce "
            "the file. Check `gh auth status` and try again."
        )
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


# ---------------------------------------------------------------------------
def auto_check_and_apply(*, on_status=None, force: bool = False) -> dict:
    """Background-thread entry point. Called from main.py shortly after
    launch. Behaviour gated by the 'auto_update_mode' setting:

      'off'    — never check
      'notify' — check only; never install. Shows a Windows toast +
                 a status note in the chat that an update is available.
      'auto'   — check + silent install if the previous check is more
                 than 24h ago. Default for new installs.

    `force=True` overrides the 24h cooldown — used by the Settings
    'Check for updates now' button.
    """
    on_status = on_status or (lambda *_a, **_k: None)
    try:
        from secrets_store import load_setting, save_setting
    except Exception:
        return {"status": "skip", "reason": "secrets_store unavailable"}

    mode = (load_setting("auto_update_mode") or "auto").lower()
    if mode == "off":
        return {"status": "skip", "reason": "mode=off"}

    # 24h cooldown so we don't slam GitHub on every launch.
    if not force:
        import time as _t
        last = float(load_setting("auto_update_last_check") or 0)
        if _t.time() - last < 24 * 3600:
            return {"status": "skip", "reason": "24h cooldown"}
        save_setting("auto_update_last_check", _t.time())

    on_status("Checking for ArchHub updates…", 10, "")
    try:
        ok, release, current = has_update_available()
    except Exception as ex:
        return {"status": "error", "error": str(ex)[:300]}
    if not ok:
        on_status(f"ArchHub up to date (v{current})", 100, "")
        return {"status": "ok", "up_to_date": True, "current": current}

    on_status(f"Update available: {release.tag_name}", 30,
              f"installed {current} → {release.tag_name}")

    # Surface a Windows toast either way (notify + auto both ping).
    try:
        import sys
        from pathlib import Path as _P
        sys.path.insert(0, str(_P(__file__).resolve().parent.parent / "agents"))
        from notify import notify as _toast
        _toast(
            f"ArchHub {release.tag_name} available",
            f"{'Installing silently…' if mode == 'auto' else 'Open Settings to install.'}",
            html=None, toast=True,
        )
    except Exception:
        pass

    if mode == "notify":
        return {"status": "ok", "up_to_date": False,
                "current": current, "latest": release.tag_name}

    # mode == 'auto' → download + silent install
    try:
        on_status(f"Downloading {release.tag_name}", 50, "")
        installer = download_asset(release)
    except Exception as ex:
        return {"status": "error", "error": f"download failed: {ex}"}

    on_status(f"Installing {release.tag_name} silently", 90, "")
    try:
        run_installer(installer, silent=True, relaunch=True)
    except Exception as ex:
        return {"status": "error", "error": f"install failed: {ex}"}
    # run_installer calls os._exit(0); we never get here.
    return {"status": "ok", "installing": True}


def schedule_auto_check(delay_seconds: float = 6.0) -> None:
    """Spawn a daemon thread that runs auto_check_and_apply after a
    short delay. Call once from main.py post-window-shown. Failures
    are swallowed — never blocks the UI thread."""
    import threading
    def _runner():
        import time
        time.sleep(delay_seconds)
        try:
            auto_check_and_apply()
        except Exception:
            pass
    threading.Thread(target=_runner, daemon=True).start()
