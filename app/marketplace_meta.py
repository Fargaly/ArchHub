"""Marketplace install metadata — track which version of each item is
installed locally, who signed it, and when, so the UI can surface
'update available' badges without re-walking the catalog payload by
payload.

Storage: %LOCALAPPDATA%/ArchHub/marketplace_installed.json — a single
flat dict keyed by item id:

    {
      "official.dimension_walls": {
        "version":     "0.1.0",
        "signed_by":   "official",
        "installed_at": "2026-05-09T12:34:00Z",
        "kind":        "skill"
      },
      ...
    }

Public API
----------
    record_install(item: dict) -> None
    record_uninstall(item_id: str) -> None
    installed_version(item_id: str) -> str | None
    update_available(catalog_item: dict) -> bool
    install_state(catalog_item: dict) -> str   # 'installed'|'update'|'not_installed'
    semver_cmp(a: str, b: str) -> int          # -1/0/1
    list_installed() -> dict[str, dict]
"""
from __future__ import annotations

import json
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


# Single-process lock — JSON read+write is small but the marketplace
# UI install button can be clicked twice in fast succession.
_LOCK = threading.Lock()


def _store_path() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "ArchHub"
    base.mkdir(parents=True, exist_ok=True)
    return base / "marketplace_installed.json"


def _read() -> dict[str, dict]:
    p = _store_path()
    if not p.exists():
        return {}
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _write(d: dict[str, dict]) -> None:
    p = _store_path()
    try:
        p.write_text(json.dumps(d, indent=2, sort_keys=True),
                      encoding="utf-8")
    except Exception:
        pass


def list_installed() -> dict[str, dict]:
    """Snapshot of every recorded install. Caller owns the dict."""
    with _LOCK:
        return dict(_read())


def installed_version(item_id: str) -> Optional[str]:
    rec = _read().get(item_id)
    if not rec:
        return None
    return rec.get("version")


def record_install(item: dict) -> None:
    """Persist that this catalog item has been installed locally.
    Overwrites any prior record (used on update too)."""
    item_id = item.get("id")
    if not item_id:
        return
    record = {
        "version":      str(item.get("version") or "0.0.0"),
        "signed_by":    item.get("signed_by") or "",
        "installed_at": datetime.now(timezone.utc).isoformat(),
        "kind":         item.get("kind") or "",
    }
    with _LOCK:
        d = _read()
        d[item_id] = record
        _write(d)


def record_uninstall(item_id: str) -> None:
    if not item_id:
        return
    with _LOCK:
        d = _read()
        if item_id in d:
            d.pop(item_id, None)
            _write(d)


# ---------------------------------------------------------------------------
# Semver comparison — strict major.minor.patch ints, with optional
# pre-release suffix that we treat as "lower than the same version
# without the suffix" (matches semver.org §11). Pre-release segments
# are compared lexically because we don't ship numeric-vs-string mixing
# in our catalog today; if that changes, swap to packaging.version.

_VER_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.\-]+))?$")


def _parse(v: str) -> tuple[int, int, int, str]:
    m = _VER_RE.match(str(v).strip())
    if not m:
        return (0, 0, 0, "")
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)),
            m.group(4) or "")


def semver_cmp(a: str, b: str) -> int:
    """Return -1/0/1 for a<b / a==b / a>b. Invalid strings sort as
    0.0.0 so a malformed version never silently 'beats' a valid one."""
    pa = _parse(a)
    pb = _parse(b)
    # Compare major/minor/patch first.
    for x, y in zip(pa[:3], pb[:3]):
        if x < y:
            return -1
        if x > y:
            return 1
    # Pre-release rules: empty > any pre-release (e.g. 1.0.0 > 1.0.0-rc1)
    pre_a, pre_b = pa[3], pb[3]
    if pre_a == pre_b:
        return 0
    if not pre_a:
        return 1
    if not pre_b:
        return -1
    return -1 if pre_a < pre_b else 1


def update_available(catalog_item: dict) -> bool:
    """True iff catalog version is strictly newer than the installed
    version. False when not installed (use install_state for that)."""
    iid = catalog_item.get("id")
    if not iid:
        return False
    have = installed_version(iid)
    if have is None:
        return False
    cat_ver = str(catalog_item.get("version") or "0.0.0")
    return semver_cmp(cat_ver, have) > 0


def install_state(catalog_item: dict) -> str:
    """One of 'not_installed' | 'installed' | 'update'."""
    iid = catalog_item.get("id")
    if not iid:
        return "not_installed"
    have = installed_version(iid)
    if have is None:
        return "not_installed"
    cat_ver = str(catalog_item.get("version") or "0.0.0")
    if semver_cmp(cat_ver, have) > 0:
        return "update"
    return "installed"
