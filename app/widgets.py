"""Agent-authored UI WIDGET registry — the persistence organ for the
self-extension UI rung (founder steer: "ALLOW AGENT FREE-FORM UI CODE BUT PUT
GUARDRAILS AGAINST BAD EDITS").

The agent NEVER edits the 21k-line studio-lm.jsx monolith directly. Instead the
`create_ui_widget` build tool authors a REAL, free-form widget — component code
(a function body that returns React elements) + the bridge slots/data it binds
to — and this module persists it as JSON under LOCALAPPDATA (NOT the repo tree),
exactly like workflows.custom_nodes.write_spec persists a minted node type.

The persisted widget is then rendered by ONE generic sandboxed host in the JSX
(AgentWidgetHost) inside its OWN React error boundary + isolated container, so a
crashing/blanking widget is caught and shows a fallback — it can NEVER unmount
the app shell. THAT containment + the COURT (gate_kind 'ui_renders') +
AUTO-REVERT are the guardrails the founder asked for.

ONE-SYSTEM (ONE-SYSTEM-PLAN-BEFORE-BUILD): this mirrors workflows.custom_nodes
1:1 (LOCALAPPDATA dir, sanitized-id filename, write/list/get/delete, load_all on
boot). It is the widget twin of custom_nodes, not a parallel engine.

SECURITY:
  * The widget id is SANITIZED to ``[a-z0-9_]`` and the file path is
    ``<widgets_dir>/<sanitized_id>.json`` — a crafted id can never escape the
    jail (the same confinement self_extend.undo_artifact enforces on delete).
  * The widget code is stored as data; it is executed ONLY inside the JSX
    sandboxed error-boundaried host (a contained render), never in the Python
    process and never against the app shell DOM directly.
  * No secret/credential is stored — a widget that needs data binds a bridge
    slot name (resolved at render time by the host), it does not embed values.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Optional


# A widget id is the filename stem + the React testid the court asserts on, so it
# must be a safe, collision-free token. Sanitize hard (mirrors
# connectors.scaffold._safe_host_id + the self_extend undo jail).
_ID_RE = re.compile(r"[^a-z0-9_]")


def widgets_dir() -> Path:
    """Return ``%LOCALAPPDATA%/ArchHub/ui_widgets`` on Windows, else
    ``~/.archhub/ui_widgets``. Always ensures the dir exists. This is the JAIL:
    every widget file lives directly under here, keyed by a sanitized id, so a
    read/delete can never touch a file outside it."""
    base = os.environ.get("LOCALAPPDATA")
    if base:
        root = Path(base) / "ArchHub" / "ui_widgets"
    else:
        root = Path.home() / ".archhub" / "ui_widgets"
    root.mkdir(parents=True, exist_ok=True)
    return root


def safe_widget_id(raw: str) -> str:
    """Sanitize an arbitrary widget id to ``[a-z0-9_]`` (no path separators, no
    ``..``). Empty / all-junk input falls back to ``widget``."""
    s = _ID_RE.sub("_", (raw or "").strip().lower())
    s = re.sub(r"_+", "_", s).strip("_")
    return s or "widget"


def widget_path(widget_id: str) -> Path:
    """The jailed JSON path for a widget id (sanitized)."""
    return widgets_dir() / f"{safe_widget_id(widget_id)}.json"


def _normalize_spec(spec: dict) -> dict:
    """Validate + normalize a widget spec into the stored shape.

    Stored shape (all but id/code optional):
      {
        "id":          "co2_panel",      # sanitized; the file stem + testid
        "title":       "CO2 panel",      # human label in the host chrome
        "description": "shows ...",
        "code":        "<JS function body that returns a React element>",
        "slots":       ["get_co2"],      # bridge slot names the widget may read
        "placement":   "panel",          # where the host mounts it (panel|float)
      }

    The ``code`` is a FREE-FORM function body the host wraps as
    ``new Function('React','bridge','api', code)`` and renders inside its error
    boundary — real component logic, not a fixed declarative schema (honoring
    the founder steer), but contained by the sandboxed host.
    """
    if not isinstance(spec, dict):
        raise ValueError("widget spec must be a JSON object")
    raw_id = (spec.get("id") or spec.get("widget_id")
              or spec.get("name") or "").strip()
    if not raw_id:
        raise ValueError("widget spec requires an 'id'")
    wid = safe_widget_id(raw_id)
    code = spec.get("code")
    if not isinstance(code, str) or not code.strip():
        raise ValueError("widget spec requires non-empty 'code' "
                         "(a JS function body returning a React element)")
    slots = spec.get("slots") or []
    if not isinstance(slots, list):
        slots = []
    slots = [str(s) for s in slots if isinstance(s, (str,)) and s.strip()]
    placement = str(spec.get("placement") or "panel").strip().lower()
    if placement not in ("panel", "float"):
        placement = "panel"
    return {
        "id": wid,
        "title": str(spec.get("title") or spec.get("display_name") or wid),
        "description": str(spec.get("description") or ""),
        "code": code,
        "slots": slots,
        "placement": placement,
    }


def write_widget(spec: dict) -> Path:
    """Persist a normalized widget spec to the jailed dir. Returns the abs path.
    Idempotent per id (re-authoring overwrites the same file)."""
    norm = _normalize_spec(spec)
    path = widget_path(norm["id"])
    path.write_text(json.dumps(norm, indent=2, ensure_ascii=False),
                    encoding="utf-8")
    return path


def get_widget(widget_id: str) -> Optional[dict]:
    """Return one persisted widget spec by id, or None."""
    path = widget_path(widget_id)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def list_widgets() -> list[dict]:
    """Every persisted widget spec (raw, for the JSX host registry read). Bad
    files are skipped — one corrupt widget never blocks the rest."""
    out: list[dict] = []
    for path in sorted(widgets_dir().glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("id"):
                out.append(data)
        except Exception:
            continue
    return out


def delete_widget(widget_id: str) -> dict:
    """Remove a widget by id (the AUTO-REVERT + manual-undo primitive).

    Path-jailed: the id is sanitized and joined under widgets_dir(), then the
    candidate is asserted to be INSIDE the jail (commonpath) before unlink — a
    crafted id can never delete a file outside the widgets dir. Idempotent:
    an already-absent widget reports ok with removed=False."""
    wid = safe_widget_id(widget_id)
    jail = widgets_dir().resolve()
    cand = (jail / f"{wid}.json").resolve()
    try:
        inside = os.path.commonpath([str(jail), str(cand)]) == str(jail)
    except ValueError:
        inside = False
    if not inside or cand == jail:
        return {"ok": False, "error": "refused: path outside widgets jail"}
    if not cand.exists():
        return {"ok": True, "removed": False, "id": wid, "note": "already absent"}
    try:
        cand.unlink()
    except Exception:
        return {"ok": False, "error": "remove failed", "id": wid}
    return {"ok": True, "removed": True, "id": wid, "path": str(cand)}
