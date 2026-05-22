"""Skill library — cloud-first, with local cache as the on-disk surface.

Source of truth, in priority order:

  1. Cloud cache (a private GitHub repo cloned to
     %LOCALAPPDATA%/ArchHub/data_repo/skills/) — managed by cloud_sync.
  2. Legacy user library (%LOCALAPPDATA%/ArchHub/workflows/) — kept readable
     so Skills saved before cloud sync was wired up still appear.
  3. Shared library (%PROGRAMDATA%/ArchHub/skills/) — for the
     pre-cloud-sync OneDrive-symlink path; same fallback rationale.

When cloud sync is available + initialised, save_skill writes into the
cloud cache and immediately pushes to GitHub in the background. Save
on device A → device B sees the change after its next pull (which we
trigger silently on launch).

When cloud sync is unavailable (no gh, not signed in, or offline), saves
fall back to the legacy user library. Existing Skills keep working;
they just don't sync until the user signs in.
"""
from __future__ import annotations

import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from workflows.graph import Workflow
from workflows.library import WORKFLOWS_DIR as USER_LIBRARY, _FILE_SUFFIX, _slug

from .metadata import SkillMeta, attach_meta, get_meta, is_skill, SCOPE_USER, SCOPE_FIRM, SCOPE_TEAM


SHARED_LIBRARY = Path(
    os.environ.get("PROGRAMDATA", os.environ.get("LOCALAPPDATA", str(Path.home())))
) / "ArchHub" / "skills"


def _marketplace_skills_dir() -> Optional[Path]:
    """Where marketplace_client.install_pack drops downloaded packs.

    Honors ARCHHUB_MARKETPLACE_DIR so tests + advanced users can redirect.
    Returns None when the directory hasn't been created yet — the loader
    treats that as 'nothing installed' rather than walking an empty tree."""
    override = os.environ.get("ARCHHUB_MARKETPLACE_DIR")
    if override:
        base = Path(override)
    else:
        appdata = os.environ.get("APPDATA")
        if appdata:
            base = Path(appdata) / "ArchHub" / "marketplace_skills"
        else:
            base = Path.home() / ".archhub" / "marketplace_skills"
    return base if base.exists() else None


def _cloud_skills_dir() -> Optional[Path]:
    """Return the cloud-cache skills directory if cloud sync is initialised,
    otherwise None. Imported lazily so the cloud_sync module is optional."""
    try:
        import cloud_sync
        if cloud_sync.is_initialised():
            d = cloud_sync.skills_dir()
            d.mkdir(parents=True, exist_ok=True)
            return d
    except Exception:
        pass
    return None


def library_paths() -> list[Path]:
    """All library roots searched for Skills, in priority order. Cloud
    cache wins on id collision so a synced Skill overrides a stale local
    copy with the same id. The marketplace tree is appended last so a
    user-edited copy of a marketplace Skill takes precedence over the
    pristine installed version."""
    paths: list[Path] = []
    cloud = _cloud_skills_dir()
    if cloud is not None:
        paths.append(cloud)
    paths.extend([USER_LIBRARY, SHARED_LIBRARY])
    mkt = _marketplace_skills_dir()
    if mkt is not None:
        paths.append(mkt)
    return paths


def _read_pack_marker(pack_dir: Path) -> dict:
    """Return the .archhub_pack.json marker that marketplace_client
    drops into each install dir, or {} when missing/corrupt."""
    marker = pack_dir / ".archhub_pack.json"
    if not marker.exists():
        return {}
    try:
        import json as _json
        return _json.loads(marker.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _ensure(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def _path_for(workflow: Workflow, root: Path) -> Path:
    return _ensure(root) / f"{_slug(workflow.name)}__{workflow.id}{_FILE_SUFFIX}"


# Lightweight in-memory cache. The chat hits list_skills() on every
# matcher pass (every keystroke that triggers autocomplete) and on
# every welcome-card render, so a fresh filesystem scan + JSON parse
# per call adds 200-500 ms of UI lag with even a modest library.
# The cache is invalidated explicitly by save_skill / delete_skill
# below so changes propagate immediately, and on a 30-second
# wall-clock TTL so any out-of-band edits (cloud-sync pull, manual
# JSON edit) are picked up without a restart.
import time as _time

_LIST_CACHE: tuple[float, list[dict]] | None = None
_LIST_TTL_SECONDS = 30.0


def _invalidate_list_cache() -> None:
    global _LIST_CACHE
    _LIST_CACHE = None


def list_skills() -> list[dict]:
    """Index every Skill across libraries. Lightweight: name + meta + path."""
    global _LIST_CACHE
    now = _time.time()
    if _LIST_CACHE is not None:
        ts, cached = _LIST_CACHE
        if (now - ts) < _LIST_TTL_SECONDS:
            return cached

    seen_ids: set[str] = set()
    out: list[dict] = []
    cloud = _cloud_skills_dir()
    mkt = _marketplace_skills_dir()
    for root in library_paths():
        if not root.exists():
            continue
        # Marketplace packs land in subdirs (one per pack_id) so we walk
        # recursively for that root only. Other libraries are flat — a
        # shallow glob is faster and avoids surprising recursion.
        if mkt is not None and root == mkt:
            files_iter = root.rglob(f"*{_FILE_SUFFIX}")
        else:
            files_iter = root.glob(f"*{_FILE_SUFFIX}")
        for f in sorted(files_iter,
                        key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                wf = Workflow.from_json(f.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not is_skill(wf):
                continue
            if wf.id in seen_ids:
                continue
            seen_ids.add(wf.id)
            meta = get_meta(wf)
            pack_id = ""
            pack_marker: dict = {}
            if mkt is not None and root == mkt:
                source = "marketplace"
                # The first path segment under the marketplace root is
                # the pack_id (the dir marketplace_client created).
                try:
                    rel = f.relative_to(mkt)
                    pack_id = rel.parts[0] if rel.parts else ""
                except Exception:
                    pack_id = ""
                if pack_id:
                    pack_marker = _read_pack_marker(mkt / pack_id)
            elif cloud is not None and root == cloud:
                source = "cloud"
            elif root == SHARED_LIBRARY:
                source = "shared"
            else:
                source = "user"
            entry = {
                "id": wf.id,
                "name": wf.name,
                "intent": meta.intent if meta else "",
                "keywords": meta.keywords if meta else [],
                "when_to_use": meta.when_to_use if meta else "",
                "examples": meta.examples if meta else [],
                "tags": meta.tags if meta else [],
                "requires": meta.requires if meta else [],
                "scope": meta.scope if meta else SCOPE_USER,
                "author": meta.author if meta else "",
                "path": str(f),
                "library": source,
                "source": source,
                "node_count": len(wf.nodes),
                "updated_at": wf.updated_at,
            }
            if source == "marketplace":
                entry["pack_id"] = pack_id
                if pack_marker:
                    entry["pack_version"] = pack_marker.get("version", "")
                    entry["pack_title"] = pack_marker.get("title", "")
            out.append(entry)
    out = _filter_by_feature_flags(out)
    _LIST_CACHE = (now, out)
    return out


def _filter_by_feature_flags(skills: list[dict]) -> list[dict]:
    """Drop any Skill whose `kill_switch_flag` is OFF in PostHog.

    Convention: a Skill that wants to be killable in production sets
    `meta.tags = [..., "flag:skill_<id>_enabled"]`. The flag defaults
    to TRUE if telemetry is off / unreachable, so killing happens
    only on an explicit OFF in PostHog. Lets us disable a
    misbehaving Skill across all users in 30s without a release.
    """
    try:
        from telemetry import is_feature_enabled, is_enabled
    except Exception:
        return skills
    if not is_enabled():
        return skills
    out: list[dict] = []
    for s in skills:
        tags = s.get("tags") or []
        flag = next(
            (t.split(":", 1)[1] for t in tags if isinstance(t, str) and t.startswith("flag:")),
            None,
        )
        if flag and not is_feature_enabled(flag, default=True):
            continue
        out.append(s)
    return out


def load_skill(skill_id: str) -> Optional[Workflow]:
    for item in list_skills():
        if item["id"] == skill_id:
            return Workflow.load(Path(item["path"]))
    return None


def save_skill(workflow: Workflow, meta: Optional[SkillMeta] = None) -> Path:
    """Save a workflow as a Skill. Cloud cache wins when available; falls
    back to the legacy user library when cloud sync is offline so the
    save never silently disappears."""
    if meta is not None:
        attach_meta(workflow, meta)
    workflow.updated_at = datetime.now(timezone.utc).isoformat()

    cloud = _cloud_skills_dir()
    cur_meta = get_meta(workflow)
    scope = cur_meta.scope if cur_meta else SCOPE_USER

    if cloud is not None:
        root = cloud
    elif scope in (SCOPE_TEAM, SCOPE_FIRM):
        root = SHARED_LIBRARY
    else:
        root = USER_LIBRARY

    path = _path_for(workflow, root)
    path.write_text(workflow.to_json(), encoding="utf-8")

    # If we wrote into the cloud cache, push in the background so the UI
    # doesn't block on the network. Failures are silent here; the user
    # can see the sync status in Settings.
    if cloud is not None and root == cloud:
        threading.Thread(
            target=_background_push,
            args=(f"Save Skill: {workflow.name}",),
            daemon=True,
        ).start()
    _invalidate_list_cache()
    return path


def delete_skill(skill_id: str) -> bool:
    for item in list_skills():
        if item["id"] == skill_id:
            target = Path(item["path"])
            target.unlink(missing_ok=True)
            cloud = _cloud_skills_dir()
            if cloud is not None and cloud in target.parents:
                threading.Thread(
                    target=_background_push,
                    args=(f"Delete Skill: {item['name']}",),
                    daemon=True,
                ).start()
            _invalidate_list_cache()
            return True
    return False


def _background_push(message: str) -> None:
    """Push the cloud cache without blocking the caller."""
    try:
        import cloud_sync
        cloud_sync.push(message)
    except Exception:
        pass
