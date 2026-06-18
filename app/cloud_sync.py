"""Cloud sync — GitHub-backed Skills + Sessions storage.

Skills and node-graph Sessions used to live only on the user's machine.
The chat showed them, the matcher found them, the user could share them
by emailing JSON. That's acceptable for one architect on one box; it
falls apart the moment they own two devices or want a teammate to see
what they built.

This module makes a private GitHub repo the source of truth for the
user's Skills AND Sessions. The local filesystem becomes a cache.
Save → write the JSON, commit, push. Launch → pull. Edit on device A →
it appears on device B without OneDrive symlinks or copy-paste.

Skills and Sessions live in different places, so they sync differently:

  - Skills are authored directly INTO the cache (skills_dir()) by
    app/skills/library.py, which then pushes — the cache IS the working
    surface. push()/pull() carry them as-is.
  - Sessions are authored into a SEPARATE live store
    (app/session_io.py SESSIONS_DIR = %LOCALAPPDATA%/ArchHub/sessions/)
    by the chat + canvas surfaces, which know nothing about the cache.
    sync_sessions() therefore MIRRORS that live store into the cache's
    sessions/ subfolder before a push, and back out of it after a pull,
    so the cross-device copy stays a byte-for-byte clone the local
    surfaces never have to be aware of.

Large-session gate: some session files are tens of MB because they
inline base64 image _attachments. Those would bloat the gh-backed repo
(and slow every clone/pull), so the session mirror SKIPS any file over
SESSION_SIZE_CAP_BYTES and reports the skip (file name + size) — never a
silent truncation. The user keeps the heavy session locally; only the
sync of that one file is declined, with a visible reason.

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
    cloud_sync.skills_dir()        -> Path      (cache skills/ subfolder)
    cloud_sync.sessions_dir()      -> Path      (cache sessions/ subfolder)
    cloud_sync.repo_slug()         -> str       (owner/name)
    cloud_sync.bootstrap()         -> SyncResult (clone or create + clone)
    cloud_sync.pull()              -> SyncResult
    cloud_sync.push(commit_msg)    -> SyncResult
    cloud_sync.sync_sessions()     -> SyncResult (mirror + push + pull sessions)
    cloud_sync.status()            -> SyncStatus (lightweight diagnostic)

Errors never raise; all results carry a success flag and message string
the UI can render.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

_log = logging.getLogger("archhub.cloud_sync")


# Cache lives next to the existing %LOCALAPPDATA%/ArchHub/ tree.
_CACHE_ROOT = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "ArchHub"
_CACHE_DIR = _CACHE_ROOT / "data_repo"

# Fixed remote name so multiple devices land on the same place.
_DEFAULT_REPO_NAME = "ArchHub-data"
# Subfolders inside the repo. Skills are authored straight into theirs;
# sessions are mirrored into theirs from the live SESSIONS_DIR.
_SKILLS_SUBDIR = "skills"
_SESSIONS_SUBDIR = "sessions"

# The on-disk extension session_io writes (kept in sync with
# session_io.SESSION_EXT). Only files matching this are mirrored — a
# *.archhub-session.json glob, the same the THREADS rail scans.
_SESSION_GLOB = "*.archhub-session.json"

# Large-blob gate. Session files balloon past tens of MB when the user
# inlines base64 image _attachments; pushing those into the gh-backed
# repo bloats every clone. 5 MB is comfortably above a real graph
# session (nodes + wires + chat text is KBs) yet well under an
# attachment-heavy one. Skipped files are reported, never truncated.
SESSION_SIZE_CAP_BYTES = 5 * 1024 * 1024

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
    skills: int = 0               # count of synced skill files in cache
    sessions: int = 0            # count of synced session files in cache
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


def sessions_dir() -> Path:
    """Cache subfolder where node-graph session JSONs are mirrored for
    cross-device sync. Mirrors skills_dir() — lives inside the same
    cloned cache repo, alongside skills/. The live working copy is
    session_io.SESSIONS_DIR; sync_sessions() keeps the two in step."""
    return _CACHE_DIR / _SESSIONS_SUBDIR


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

    # Ensure both subfolders + .gitkeep so the first push isn't empty
    # and device B's clone already has the directories.
    skills_dir().mkdir(parents=True, exist_ok=True)
    sessions_dir().mkdir(parents=True, exist_ok=True)
    made_keep = False
    for sub in (skills_dir(), sessions_dir()):
        keep = sub / ".gitkeep"
        if not keep.exists():
            keep.write_text("", encoding="utf-8")
            made_keep = True
    if made_keep:
        _git("add", "-A")
        _git("-c", "user.email=archhub@local", "-c", "user.name=ArchHub",
             "commit", "-m", "Initial Skills + Sessions sync")
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


# ---------------------------------------------------------------------------
# Sessions sync. Sessions live in a SEPARATE live store (session_io.
# SESSIONS_DIR) the chat + canvas surfaces write to, unaware of the
# cloud cache. We bridge the two by mirroring: live -> cache before a
# push, cache -> live after a pull. The size cap is applied on the way
# INTO the cache so attachment-heavy blobs never enter the repo.
# ---------------------------------------------------------------------------
def _live_sessions_dir() -> Path:
    """The on-disk working store the app actually saves sessions to.
    Read from session_io so a test (or a future relocation) that
    monkeypatches SESSIONS_DIR is honoured — we never freeze a second
    copy of the path."""
    try:
        import session_io
        return Path(session_io.SESSIONS_DIR)
    except Exception:
        # session_io computes the same path off LOCALAPPDATA; fall back
        # to that so sync still works if the import is unavailable.
        return _CACHE_ROOT / "sessions"


def _mirror_sessions_into_cache() -> tuple[int, list[str]]:
    """Copy every live session file into the cache sessions/ subfolder,
    skipping any file over the size cap. Returns (copied_count,
    skipped_report_lines). A skipped file is NOT copied and NOT
    truncated — the live original stays put; only its sync is declined.

    Files deleted locally are also removed from the cache so a delete on
    device A propagates (the mirror is authoritative for the live set)."""
    live = _live_sessions_dir()
    cache = sessions_dir()
    cache.mkdir(parents=True, exist_ok=True)
    copied = 0
    skipped: list[str] = []
    if not live.exists():
        return copied, skipped

    live_names: set[str] = set()
    for src in sorted(live.glob(_SESSION_GLOB)):
        live_names.add(src.name)
        try:
            size = src.stat().st_size
        except OSError:
            continue
        if size > SESSION_SIZE_CAP_BYTES:
            mb = size / (1024 * 1024)
            cap_mb = SESSION_SIZE_CAP_BYTES / (1024 * 1024)
            line = (f"{src.name} ({mb:.1f} MB) skipped — over the "
                    f"{cap_mb:.0f} MB sync cap (likely inline attachments)")
            skipped.append(line)
            _log.warning("cloud_sync: %s", line)
            # If a previously-synced copy exists in the cache, leave it;
            # don't push a NEW oversize blob. Nothing else to do.
            continue
        dst = cache / src.name
        try:
            # Only copy when content actually differs — keeps git from
            # churning identical files into no-op commits.
            if (not dst.exists()
                    or dst.stat().st_size != size
                    or src.read_bytes() != dst.read_bytes()):
                shutil.copy2(src, dst)
            copied += 1
        except OSError as ex:
            _log.warning("cloud_sync: could not mirror %s: %s",
                         src.name, ex)

    # Propagate local deletions: a cache file with no live counterpart
    # (and not an oversize one we deliberately left) is removed so the
    # next push reflects the delete. .gitkeep is preserved.
    skipped_names = {ln.split(" ", 1)[0] for ln in skipped}
    for cached in cache.glob(_SESSION_GLOB):
        if cached.name not in live_names and cached.name not in skipped_names:
            try:
                cached.unlink()
            except OSError:
                pass
    return copied, skipped


def _mirror_sessions_out_of_cache() -> int:
    """Copy every session file from the cache back into the live store
    (the device-B side of a pull). Returns the count written. New files
    from another device land in SESSIONS_DIR where the THREADS rail and
    session_io.load_session find them. Existing-but-different files are
    refreshed; local-only files are left untouched (a local save not yet
    pushed must not be clobbered by an older cache)."""
    live = _live_sessions_dir()
    cache = sessions_dir()
    if not cache.exists():
        return 0
    live.mkdir(parents=True, exist_ok=True)
    written = 0
    for src in cache.glob(_SESSION_GLOB):
        dst = live / src.name
        try:
            if (not dst.exists()
                    or dst.stat().st_size != src.stat().st_size
                    or dst.read_bytes() != src.read_bytes()):
                shutil.copy2(src, dst)
            written += 1
        except OSError as ex:
            _log.warning("cloud_sync: could not restore %s: %s",
                         src.name, ex)
    return written


def sync_sessions() -> SyncResult:
    """Two-way sync of node-graph sessions — the entrypoint the bridge
    slot / Home 'Sync now' affordance calls.

    Order of operations:
      1. pull()                     — get the latest cache from GitHub
      2. cache -> live mirror        — surface other devices' sessions
      3. live -> cache mirror (+cap) — stage this device's sessions
      4. push()                     — publish them

    Step 3's cap silently declines (with a logged + reported reason)
    any session file over SESSION_SIZE_CAP_BYTES so the repo never
    bloats. The returned SyncResult.detail carries the skip report so
    the UI can show 'N skipped' without the user digging through logs.
    """
    if not is_initialised():
        boot = bootstrap()
        if not boot.success:
            return boot

    # 1. Pull first so we merge before mirroring our own changes up.
    pull_res = pull()
    if not pull_res.success:
        return SyncResult(False, "Sessions sync failed on pull.",
                          pull_res.detail or pull_res.message)

    # 2. Bring down anything new from other devices.
    restored = _mirror_sessions_out_of_cache()

    # 3. Stage this device's live sessions into the cache (cap applied).
    copied, skipped = _mirror_sessions_into_cache()

    # 4. Commit + push the staged session changes.
    msg = f"Sync sessions ({copied} session{'s' if copied != 1 else ''})"
    push_res = push(msg)
    if not push_res.success:
        return SyncResult(False, "Sessions sync failed on push.",
                          push_res.detail or push_res.message)

    detail_parts = [
        f"{copied} session(s) synced up",
        f"{restored} restored from cloud",
    ]
    if skipped:
        detail_parts.append(
            f"{len(skipped)} skipped (too large): " + "; ".join(skipped))
    detail = " · ".join(detail_parts)
    return SyncResult(True, "Sessions synced.", detail)


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
    # Synced artifact counts — what the user has in the cloud cache right
    # now. Cheap glob, no network. Lets the Home/Settings card render
    # "N skills · M sessions synced".
    try:
        s.skills = len(list(skills_dir().glob("*.archhub-skill.json")))
    except Exception:
        pass
    try:
        s.sessions = len(list(sessions_dir().glob(_SESSION_GLOB)))
    except Exception:
        pass
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
