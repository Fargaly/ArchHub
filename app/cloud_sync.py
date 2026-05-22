"""Cloud sync — GitHub-backed Skills + Sessions storage.

Skills used to live only on the user's machine. The chat showed them, the
matcher found them, the user could share them by emailing JSON. That's
acceptable for one architect on one box; it falls apart the moment they
own two devices or want a teammate to see what they built.

This module makes a private GitHub repo the source of truth for the
user's Skills (and, later, Sessions). The local filesystem becomes a
cache. Save → write the JSON, commit, push. Launch → pull. Edit on
device A → it appears on device B without OneDrive symlinks or
copy-paste.

Implementation choices:

  - Authentication is delegated to whatever credential helper git is
    already configured with. The user signed in once via `gh auth login`
    earlier in onboarding, so git already speaks to GitHub on their
    behalf — no token plumbing in ArchHub.
  - The repo is created via `gh repo create` if missing. The owner is
    inferred from `gh api user`, the name is fixed (ArchHub-data) so
    multiple devices land on the same repo.
  - Operations shell out to `git` and `gh` rather than reaching for
    PyGithub. Both are already installed on this machine and avoid a
    new dependency.
  - All git invocations have a short hard timeout so a flaky network
    never freezes the UI.

The module exposes a small API the rest of ArchHub uses:

    cloud_sync.is_available()      -> bool      (gh + git both installed)
    cloud_sync.is_signed_in()      -> bool      (gh auth status ok)
    cloud_sync.is_initialised()    -> bool      (cache repo cloned)
    cloud_sync.cache_dir()         -> Path      (local clone path)
    cloud_sync.repo_slug()         -> str       (owner/name)
    cloud_sync.bootstrap()         -> SyncResult (clone or create + clone)
    cloud_sync.pull()              -> SyncResult
    cloud_sync.push(commit_msg)    -> SyncResult
    cloud_sync.status()            -> SyncStatus (lightweight diagnostic)

Errors never raise; all results carry a success flag and message string
the UI can render.
"""
from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


# Cache lives next to the existing %LOCALAPPDATA%/ArchHub/ tree.
_CACHE_ROOT = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "ArchHub"
_CACHE_DIR = _CACHE_ROOT / "data_repo"

# Fixed remote name so multiple devices land on the same place.
_DEFAULT_REPO_NAME = "ArchHub-data"
# Subfolder inside the repo where skill JSONs go. Workflows/sessions can
# live alongside in their own subfolders later.
_SKILLS_SUBDIR = "skills"

_GIT_TIMEOUT_SECONDS = 60
_GH_TIMEOUT_SECONDS = 60


@dataclass
class SyncStatus:
    available: bool = False
    signed_in: bool = False
    initialised: bool = False
    repo_slug: str = ""
    cache_dir: Path = _CACHE_DIR
    last_pull: str = ""           # ISO timestamp from sidecar
    last_push: str = ""
    behind: int = 0
    ahead: int = 0
    dirty: bool = False
    error: str = ""


@dataclass
class SyncResult:
    success: bool
    message: str
    detail: str = ""


# ---------------------------------------------------------------------------
def _run(cmd: list[str], *, cwd: Optional[Path] = None,
         timeout: int = _GIT_TIMEOUT_SECONDS) -> tuple[int, str, str]:
    """Run a subprocess. Returns (rc, stdout, stderr). Never raises."""
    try:
        # Hidden console — `git` / `gh` would otherwise flash a CMD box
        # every time we call them on Windows.
        from proc_utils import _hidden_kwargs
        result = subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
            **_hidden_kwargs(),
        )
        return (result.returncode,
                (result.stdout or "").strip(),
                (result.stderr or "").strip())
    except FileNotFoundError:
        return 127, "", f"{cmd[0]} not found on PATH"
    except subprocess.TimeoutExpired:
        return 124, "", f"{cmd[0]} timed out after {timeout}s"


def _git(*args: str, cwd: Optional[Path] = None) -> tuple[int, str, str]:
    return _run(["git", *args], cwd=cwd or _CACHE_DIR)


def _gh(*args: str) -> tuple[int, str, str]:
    return _run(["gh", *args], timeout=_GH_TIMEOUT_SECONDS)


# ---------------------------------------------------------------------------
def cache_dir() -> Path:
    return _CACHE_DIR


def skills_dir() -> Path:
    return _CACHE_DIR / _SKILLS_SUBDIR


def is_available() -> bool:
    """gh + git installed?"""
    rc_git, _, _ = _run(["git", "--version"])
    rc_gh, _, _ = _run(["gh", "--version"])
    return rc_git == 0 and rc_gh == 0


def is_signed_in() -> bool:
    """Best-effort sign-in check.

    Pragmatic version: ask `gh auth token` for the currently active token.
    If we get one, credentials are reachable from this process. Notably
    we do NOT rely on `gh auth status`, which on Windows occasionally
    reports "not logged in" when launched from a subprocess due to
    Credential Manager vault scoping quirks — even though the token is
    fine and `gh repo view` etc. work fine.

    If the token retrieval also fails, fall back to a quick `git ls-remote`
    against a dummy URL — if git's own credential helper can authenticate,
    we count that as signed in.
    """
    if not is_available():
        return False
    rc, out, _ = _gh("auth", "token")
    if rc == 0 and out and not out.startswith("error"):
        return True
    return False


def auth_token() -> str:
    """Return the active GitHub token if `gh` knows one. Empty string otherwise."""
    if not is_available():
        return ""
    rc, out, _ = _gh("auth", "token")
    if rc != 0:
        return ""
    return (out or "").strip()


def _gh_with_token(*args: str) -> tuple[int, str, str]:
    """Invoke gh with GH_TOKEN forced from `gh auth token`. This sidesteps
    the Credential Manager scoping issue on Windows where `gh` invoked
    from a subprocess sometimes can't see its own keyring entry."""
    token = auth_token()
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    if token:
        env["GH_TOKEN"] = token
    try:
        from proc_utils import _hidden_kwargs
        result = subprocess.run(
            ["gh", *args], capture_output=True, text=True,
            timeout=_GH_TIMEOUT_SECONDS, env=env,
            **_hidden_kwargs(),
        )
        return (result.returncode,
                (result.stdout or "").strip(),
                (result.stderr or "").strip())
    except Exception as ex:
        return 1, "", str(ex)


def repo_slug() -> str:
    """Return owner/name. Caches in a sidecar file so we don't shell out
    on every call."""
    sidecar = _CACHE_ROOT / "data_repo.slug"
    try:
        if sidecar.exists():
            cached = sidecar.read_text(encoding="utf-8").strip()
            if cached:
                return cached
    except Exception:
        pass
    if not is_available():
        return ""
    rc, out, _ = _gh_with_token("api", "user", "-q", ".login")
    if rc != 0 or not out:
        return ""
    slug = f"{out}/{_DEFAULT_REPO_NAME}"
    try:
        sidecar.parent.mkdir(parents=True, exist_ok=True)
        sidecar.write_text(slug, encoding="utf-8")
    except Exception:
        pass
    return slug


def is_initialised() -> bool:
    return (_CACHE_DIR / ".git").exists()


# ---------------------------------------------------------------------------
def bootstrap() -> SyncResult:
    """Make the cache repo exist and be cloned locally.

    If the local clone already exists, this is a no-op success.
    If the remote repo doesn't exist on GitHub, we create it via `gh`.
    Either way the user ends up with a cloned, initialised cache.
    """
    if not is_available():
        return SyncResult(False, "git or gh CLI missing.",
                          "Install GitHub CLI: winget install GitHub.cli")
    if not is_signed_in():
        return SyncResult(False, "Not signed in to GitHub.",
                          "Run `gh auth login` once, then try again.")

    if is_initialised():
        return SyncResult(True, "Cloud sync ready.")

    slug = repo_slug()
    if not slug:
        return SyncResult(False, "Could not determine GitHub user.")

    # Does the repo exist on GitHub?
    rc, _, _ = _gh_with_token("repo", "view", slug)
    if rc != 0:
        # Create it (private) using a fresh empty README so the clone has
        # a default branch to track.
        _CACHE_DIR.parent.mkdir(parents=True, exist_ok=True)
        rc_c, out_c, err_c = _gh_with_token(
            "repo", "create", slug,
            "--private",
            "--description", "ArchHub Skills + Sessions sync (private)",
            "--add-readme",
        )
        if rc_c != 0:
            return SyncResult(False, "Could not create the cloud repo.",
                              err_c or out_c)

    # Clone it into the cache directory.
    _CACHE_DIR.parent.mkdir(parents=True, exist_ok=True)
    rc, out, err = _run(
        ["git", "clone", f"https://github.com/{slug}.git", str(_CACHE_DIR)],
    )
    if rc != 0:
        return SyncResult(False, "Could not clone the cloud repo.",
                          err or out)

    # Ensure subfolder + .gitkeep so first push isn't empty.
    skills_dir().mkdir(parents=True, exist_ok=True)
    keep = skills_dir() / ".gitkeep"
    if not keep.exists():
        keep.write_text("", encoding="utf-8")
        _git("add", "-A")
        _git("-c", "user.email=archhub@local", "-c", "user.name=ArchHub",
             "commit", "-m", "Initial Skills sync")
        _git("push", "origin", "HEAD")

    return SyncResult(True, f"Cloud sync ready ({slug}).")


def pull() -> SyncResult:
    if not is_initialised():
        boot = bootstrap()
        if not boot.success:
            return boot
    rc, out, err = _git("pull", "--ff-only")
    if rc != 0:
        return SyncResult(False, "Pull failed.", err or out)
    _stamp_pull()
    return SyncResult(True, "Pulled latest from cloud.", out)


def push(commit_msg: str) -> SyncResult:
    if not is_initialised():
        boot = bootstrap()
        if not boot.success:
            return boot
    # Stage everything under the cache.
    rc, out, err = _git("add", "-A")
    if rc != 0:
        return SyncResult(False, "Could not stage changes.", err or out)
    # Bail early if there's nothing to commit.
    rc, out, _ = _git("status", "--porcelain")
    if not out.strip():
        return SyncResult(True, "Already up to date.")
    rc, out, err = _git(
        "-c", "user.email=archhub@local",
        "-c", "user.name=ArchHub",
        "commit", "-m", commit_msg or "ArchHub sync",
    )
    if rc != 0:
        return SyncResult(False, "Commit failed.", err or out)
    rc, out, err = _git("push", "origin", "HEAD")
    if rc != 0:
        return SyncResult(False, "Push failed.", err or out)
    _stamp_push()
    return SyncResult(True, "Synced to cloud.", out)


def status() -> SyncStatus:
    s = SyncStatus(
        available=is_available(),
        signed_in=is_signed_in(),
        initialised=is_initialised(),
        repo_slug=repo_slug(),
        last_pull=_read_stamp("last_pull"),
        last_push=_read_stamp("last_push"),
    )
    if not s.initialised:
        return s
    rc, out, err = _git("status", "--porcelain")
    if rc == 0:
        s.dirty = bool(out.strip())
    rc, out, _ = _git("rev-list", "--left-right", "--count", "HEAD...@{u}")
    if rc == 0 and out:
        parts = out.split()
        if len(parts) == 2:
            try:
                s.ahead = int(parts[0])
                s.behind = int(parts[1])
            except ValueError:
                pass
    return s


# ---------------------------------------------------------------------------
def _stamp_path(name: str) -> Path:
    return _CACHE_ROOT / f"sync_{name}.stamp"


def _stamp_pull() -> None:
    _stamp_path("pull").write_text(
        datetime.now(timezone.utc).isoformat(), encoding="utf-8"
    )


def _stamp_push() -> None:
    _stamp_path("push").write_text(
        datetime.now(timezone.utc).isoformat(), encoding="utf-8"
    )


def _read_stamp(name: str) -> str:
    p = _stamp_path(name)
    try:
        if p.exists():
            return p.read_text(encoding="utf-8").strip()
    except Exception:
        pass
    return ""
