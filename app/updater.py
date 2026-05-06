"""In-app updater — check for and apply updates without leaving ArchHub.

The user should never need a terminal to update. This module:

  - reports the local commit + branch
  - checks the configured Git remote for newer commits
  - pulls the latest changes (fast-forward only, never rewrites history)
  - exposes a single restart() helper so the chat window can relaunch
    the app after applying the update

The architect clicks "Update" in the header. ArchHub does the rest.

Implementation notes:
  - We shell out to `git` because every dev box already has it (the repo
    was cloned with it). Using libgit2 / pygit2 would add a heavyweight
    binary dependency for a one-call use case.
  - Authentication is delegated to whatever credential helper git is
    already configured with (e.g. the GitHub CLI's helper installed when
    the user ran `gh auth login`). This means private repos work without
    asking for a password again.
  - All git invocations have a short timeout so a network hang never
    freezes the UI thread that called us.
"""
from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


# Repo root = the ArchHub directory containing .git, app/, payload/, etc.
# We resolve from this file: app/updater.py → app/ → repo root.
REPO_ROOT = Path(__file__).resolve().parent.parent

GIT_TIMEOUT_SECONDS = 60


@dataclass
class UpdateStatus:
    """Snapshot of where the local checkout sits relative to its remote."""
    repo_root: Path
    local_commit: str = ""           # short sha of HEAD
    local_subject: str = ""          # commit subject of HEAD
    branch: str = ""                 # current branch name
    remote_url: str = ""             # configured upstream URL (origin)
    behind: int = 0                  # commits HEAD is behind upstream
    ahead: int = 0                   # commits HEAD is ahead of upstream
    has_uncommitted: bool = False    # working tree dirty? affects safety
    error: str = ""                  # populated if any check failed

    @property
    def is_git_checkout(self) -> bool:
        return (self.repo_root / ".git").exists()

    @property
    def has_updates(self) -> bool:
        return self.behind > 0

    @property
    def can_safely_apply(self) -> bool:
        """Fast-forward is safe iff local has no commits the remote doesn't,
        and the working tree is clean."""
        return self.has_updates and self.ahead == 0 and not self.has_uncommitted


# ---------------------------------------------------------------------------
def _git(*args: str, cwd: Optional[Path] = None) -> tuple[int, str, str]:
    """Run a git command. Returns (returncode, stdout, stderr)."""
    cwd = cwd or REPO_ROOT
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT_SECONDS,
            # Don't let git pop a credential prompt that would hang forever.
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        )
        return result.returncode, (result.stdout or "").strip(), (result.stderr or "").strip()
    except FileNotFoundError:
        return 127, "", "git is not installed or not on PATH."
    except subprocess.TimeoutExpired:
        return 124, "", f"git {' '.join(args)} timed out after {GIT_TIMEOUT_SECONDS}s."


def check_for_updates() -> UpdateStatus:
    """Inspect local + remote state. Cheap network call (a `git fetch`).

    Returns an UpdateStatus the UI can render directly. On any failure the
    `error` field carries a one-line explanation; the rest is best-effort.
    """
    status = UpdateStatus(repo_root=REPO_ROOT)
    if not status.is_git_checkout:
        status.error = (
            "ArchHub doesn't appear to be installed from Git. "
            "Updates require a Git checkout."
        )
        return status

    # Local commit + branch
    rc, out, err = _git("rev-parse", "--short", "HEAD")
    status.local_commit = out if rc == 0 else ""
    rc, out, err = _git("log", "-1", "--pretty=%s")
    status.local_subject = out if rc == 0 else ""
    rc, out, err = _git("rev-parse", "--abbrev-ref", "HEAD")
    status.branch = out if rc == 0 else ""

    # Remote URL
    rc, out, err = _git("remote", "get-url", "origin")
    if rc != 0:
        status.error = "No 'origin' remote configured. Cannot check for updates."
        return status
    status.remote_url = out

    # Working tree dirty?
    rc, out, err = _git("status", "--porcelain")
    if rc == 0:
        status.has_uncommitted = bool(out.strip())

    # Fetch — refresh remote-tracking refs without touching the working tree.
    rc, out, err = _git("fetch", "--quiet", "origin", status.branch or "HEAD")
    if rc != 0:
        status.error = f"Could not contact remote: {err or 'unknown error'}"
        return status

    # ahead / behind counts
    upstream = f"origin/{status.branch}" if status.branch else "origin/HEAD"
    rc, out, err = _git("rev-list", "--left-right", "--count", f"HEAD...{upstream}")
    if rc == 0 and out:
        parts = out.split()
        if len(parts) == 2:
            try:
                status.ahead = int(parts[0])
                status.behind = int(parts[1])
            except ValueError:
                pass
    return status


def apply_update() -> tuple[bool, str]:
    """Fast-forward the local branch to the remote tip.

    Returns (success, message). The caller should then call restart().
    The message contains git's actual stderr/stdout on failure so the
    user can see exactly why an update was refused.
    """
    status = check_for_updates()
    if status.error:
        return False, status.error
    if not status.has_updates:
        return True, "Already up to date."
    if status.ahead > 0:
        return False, (
            f"Cannot fast-forward: this checkout has {status.ahead} local "
            f"commit(s) the remote doesn't.\n"
            f"Open a terminal and run `git push` or `git reset --hard origin/{status.branch}` "
            f"if you want to discard them."
        )
    if status.has_uncommitted:
        return False, (
            "Cannot update: the working tree has uncommitted changes. "
            "Commit or discard them first.\n\n"
            "If those changes are just line-ending warnings, run:\n"
            "    git checkout -- .\n"
            "Then try Update again."
        )

    # Use a verbose pull so any git error message reaches the user.
    rc, out, err = _git("pull", "--ff-only", "origin", status.branch or "HEAD")
    if rc != 0:
        return False, (
            f"git pull failed (exit {rc}).\n\n"
            f"git output:\n{out or '(empty)'}\n\n"
            f"git error:\n{err or '(empty)'}"
        )

    # Re-read to confirm we actually moved forward.
    after = check_for_updates()
    if after.local_commit == status.local_commit:
        return False, (
            "git pull reported success but the local commit didn't change. "
            "Run Update.bat from the repo folder to diagnose."
        )
    return True, (
        f"Updated {status.local_commit} → {after.local_commit}\n"
        f"{after.local_subject}"
    )


def restart() -> None:
    """Relaunch ArchHub with the same Python interpreter and exit current
    process. Caller is responsible for closing windows / saving state first.

    On Windows we use pythonw.exe (no console window) when available so the
    relaunched app behaves like a normal desktop app, with DETACHED_PROCESS
    + CREATE_NEW_PROCESS_GROUP flags so the new instance survives this
    process exiting and isn't tied to its console (if any).
    """
    python = _preferred_python_for_relaunch()
    main_py = REPO_ROOT / "app" / "main.py"

    creationflags = 0
    if sys.platform == "win32":
        creationflags = (
            getattr(subprocess, "DETACHED_PROCESS", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        )

    subprocess.Popen(
        [str(python), str(main_py), *sys.argv[1:]],
        cwd=str(REPO_ROOT),
        creationflags=creationflags,
        close_fds=True,
    )
    # Give the OS a beat to schedule the child before we vanish.
    os._exit(0)


def _preferred_python_for_relaunch() -> Path:
    """Prefer pythonw.exe on Windows so the relaunched app has no console
    window. Falls back to whatever started the current process."""
    current = Path(sys.executable)
    if sys.platform != "win32":
        return current
    # python.exe → pythonw.exe lives next to it.
    if current.name.lower() == "python.exe":
        candidate = current.with_name("pythonw.exe")
        if candidate.exists():
            return candidate
    return current


def explain_state() -> str:
    """Human-readable diagnostic for support requests. Safe to display."""
    s = check_for_updates()
    lines = [
        f"Repo:    {s.repo_root}",
        f"Branch:  {s.branch or '(none)'}",
        f"Commit:  {s.local_commit or '(unknown)'}  {s.local_subject}",
        f"Remote:  {s.remote_url or '(none)'}",
        f"Ahead:   {s.ahead}",
        f"Behind:  {s.behind}",
        f"Dirty:   {s.has_uncommitted}",
        f"Error:   {s.error or '(none)'}",
    ]
    return "\n".join(lines)
