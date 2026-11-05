"""BABOOM's role on the desk, read from Workshop rows and saved skills.

The companion window paints this. Nothing here opens a window, writes the
Workshop file, or keeps a second task store.
"""
from __future__ import annotations

import ctypes
import logging
import os
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Mapping


_STATE_MOTION = {
    "idle": "idle",
    "thinking": "think",
    "needs-you": "wave",
    "done": "talk",
    "error": "crouch",
}
_RANK = {"needs-you": 0, "error": 1, "thinking": 2, "done": 3}
_SKIP_WORDS = {"a", "an", "the", "of", "to", "for", "and", "in", "on"}
_LOG = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class BaboomWorkPresence:
    """What the sprite should be doing, from the Workshop rows it was shown."""

    state: str
    task_name: str
    motion: str
    badge: bool
    bubble: str
    task_id: str = ""
    report: str = ""


def windows_show_animations() -> bool:
    """Windows 'Show animations' (SPI_GETCLIENTAREAANIMATION). True when it is on."""
    if os.name != "nt":
        return True
    flag = ctypes.c_int(1)
    try:
        ok = ctypes.windll.user32.SystemParametersInfoW(0x1042, 0, ctypes.byref(flag), 0)
    except (AttributeError, OSError):
        return True
    if not ok:
        return True
    return bool(flag.value)


def baboom_reduced_motion(*, parameter: bool | None = None, show_animations: bool | None = None) -> bool:
    """Static pose when the caller asks, or when Windows animations are off."""
    if parameter is True:
        return True
    animations = windows_show_animations() if show_animations is None else bool(show_animations)
    return not animations


def baboom_shown_tick(tick: int, *, reduced_motion: bool) -> int:
    """The frame index to draw. Reduced motion stays on the first cell."""
    if type(tick) is not int or tick < 0 or type(reduced_motion) is not bool:
        raise ValueError("BABOOM animation tick is invalid")
    return 0 if reduced_motion else tick


def baboom_pose_motion(state: str, tick: int, *, reduced_motion: bool, transitioning: bool = False) -> str:
    """Which released sprite row this state shows. Transitions walk; thinking alternates think and cast."""
    if state not in _STATE_MOTION or type(transitioning) is not bool:
        raise ValueError("BABOOM work state is invalid")
    shown = baboom_shown_tick(tick, reduced_motion=reduced_motion)
    if reduced_motion:
        return _STATE_MOTION[state]
    if transitioning:
        return "walk"
    if state == "thinking" and shown % 2 == 1:
        return "cast"
    return _STATE_MOTION[state]


def _parsed_time(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if len(text) < 19 or text[4] != "-" or text[7] != "-" or text[10] not in "Tt ":
        return None
    text = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        _LOG.warning("BABOOM ignored an invalid Workshop timestamp; inspect the task's event time")
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _recent(row: Mapping[str, object], now: datetime, done_seconds: int) -> bool:
    parsed = _parsed_time(row.get("updated_at"))
    if parsed is None:
        return False
    # Allow only small clock skew, not a future timestamp that stays "done" for years.
    return -5 <= (now - parsed).total_seconds() <= done_seconds


def _failed(row: Mapping[str, object]) -> bool:
    result = row.get("result")
    if isinstance(result, Mapping):
        if result.get("ok") is False:
            return True
        status = str(result.get("status") or "").casefold()
        return status in {"error", "failed", "failure"}
    if not isinstance(result, str):
        return False
    text = result.strip().casefold()
    return text.startswith("fail") or text.startswith("error")


def _kind(row: Mapping[str, object], now: datetime, done_seconds: int) -> str | None:
    status = row.get("status")
    if not isinstance(status, str):
        return None
    if status in ("IN REVIEW", "blocked"):
        return "needs-you"
    if status == "WIP" or (status == "claimed" and not row.get("lease_expired")):
        return "thinking"
    if status in ("DONE", "done") and _recent(row, now, done_seconds):
        return "error" if _failed(row) else "done"
    return None


def _name(row: Mapping[str, object]) -> str:
    for key in ("title", "description"):
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "Task"


def _result_text(row: Mapping[str, object]) -> str:
    result = row.get("result")
    if isinstance(result, str):
        return result if result.strip() else ""
    if isinstance(result, Mapping):
        return "\n".join(dict.fromkeys(
            value.strip() for key in ("summary", "error", "message", "details")
            if isinstance(value := result.get(key), str) and value.strip()
        ))
    return ""


def _bubble(kind: str, name: str, row: Mapping[str, object]) -> str:
    text = _result_text(row).strip()
    if kind == "error":
        shown = text or name
    elif kind == "done":
        shown = text or ("Done: " + name)
    else:
        shown = name
    return shown if len(shown) <= 72 else shown[:71].rstrip() + "…"


def baboom_work_presence(rows: object, *, now: datetime | None = None, done_seconds: int = 120) -> BaboomWorkPresence:
    """Map real Workshop task rows to one companion state.

    ``rows`` is what ``workshop_tasks.rows`` or ``workshop_tasks.column`` returns.
    Open or planned work is not a running task. A finish or a failure only
    stays up for ``done_seconds``.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    if type(done_seconds) is not int or done_seconds < 0 or not isinstance(rows, (list, tuple)):
        raise ValueError("BABOOM workshop rows are invalid")
    ranked: list[tuple[int, float, str, str, Mapping[str, object]]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        kind = _kind(row, now, done_seconds)
        if kind is None:
            continue
        parsed = _parsed_time(row.get("updated_at"))
        stamp = parsed.timestamp() if parsed is not None else 0.0
        ranked.append((_RANK[kind], -stamp, _name(row), kind, row))
    if not ranked:
        return BaboomWorkPresence("idle", "", "idle", False, "")
    ranked.sort(key=lambda item: (item[0], item[1], item[2]))
    _rank, _stamp, name, kind, row = ranked[0]
    report = _result_text(row) or name
    task_id = row.get("id")
    return BaboomWorkPresence(
        kind, name, _STATE_MOTION[kind], kind == "needs-you", _bubble(kind, name, row),
        task_id if isinstance(task_id, str) else "", report,
    )


def read_workshop_task_rows() -> list[dict[str, object]]:
    """Read Workshop task rows. Never creates the database.

    Pytest stays off the founder's Workshop file unless a test points
    ARCHHUB_TEST_STATE_DIR at its own directory and opts in.
    """
    from .workshop_tasks import _declaration_for

    if os.environ.get("PYTEST_CURRENT_TEST") and not os.environ.get("ARCHHUB_BABOOM_READ_WORKSHOP"):
        return []
    root = os.environ.get("ARCHHUB_TEST_STATE_DIR")
    if not root:
        local = os.environ.get("LOCALAPPDATA")
        if not local:
            return []
        root = str(Path(local) / "ArchHub")
    database = Path(root) / "workshop" / "messages.sqlite3"
    if not database.is_file():
        return []
    try:
        connection = sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)
    except sqlite3.Error:
        return []
    try:
        if connection.execute("SELECT 1 FROM sqlite_master WHERE name='workshop_tasks'").fetchone() is None:
            return []
        from .workshop_mailbox import read_declarations
        from .workshop_tasks import rows
        from .baboom_nograph import own_session

        # The Workshop owns ordering, leases, archive filtering and native liveness.
        found = rows(SimpleNamespace(_db=connection), include_archived=False, settle=False)
        declarations = read_declarations(connection)
        own = own_session(root)
        shown = []
        for row in found:
            declaration = _declaration_for(row, declarations)
            if own and declaration and declaration.get("session") == own and declaration.get("request_id") == "BABOOM":
                continue
            declared = (declaration or {}).get("status")
            if row.get("status") == "done":
                row["status"] = "DONE"
            elif declared == "blocked":
                row["status"] = "IN REVIEW"
            elif declared == "working" or (row.get("status") == "claimed" and not row.get("lease_expired")):
                row["status"] = "WIP"
            elif row.get("status") == "open":
                row["status"] = "PLANNED"
            shown.append(row)
        return shown
    except sqlite3.Error:
        return []
    finally:
        connection.close()


def _words(text: str) -> set[str]:
    return {word for word in re.findall(r"[a-z0-9]+", text.casefold()) if word not in _SKIP_WORDS}


def load_saved_skills(directory: Path) -> list[dict[str, object]]:
    """Saved .archhub skills in one folder. A missing folder is an empty library."""
    from .session_files import read_document

    folder = Path(directory)
    if not folder.is_dir():
        return []
    found: list[dict[str, object]] = []
    for path in sorted(folder.glob("*.archhub")):
        try:
            document = read_document(path)
        except (OSError, ValueError):
            continue
        notes = [
            note["text"]
            for note in document.get("notes") or []
            if isinstance(note, dict) and isinstance(note.get("text"), str)
        ]
        found.append({
            "id": document.get("id") or path.stem,
            "title": document.get("title") or path.stem,
            "notes": notes,
            "path": path,
        })
    return found


def match_saved_skill(file_path: Path | str, skills: list[dict[str, object]]) -> dict[str, object] | None:
    """The saved skill whose title, id, or notes share the file name or extension."""
    path = Path(file_path)
    suffix = path.suffix.casefold().lstrip(".")
    wanted = _words(path.stem)
    if suffix:
        wanted.add(suffix)
    best: dict[str, object] | None = None
    best_score = 0
    for skill in skills:
        hay = _words(" ".join([
            str(skill.get("id") or ""),
            str(skill.get("title") or ""),
            " ".join(str(note) for note in skill.get("notes") or []),
        ]))
        score = len(wanted & hay)
        if suffix and suffix in hay:
            score += 2
        if score > best_score:
            best_score = score
            best = skill
    return best


def execute_saved_skill(skill_path: Path | str, file_path: Path | str) -> str:
    """Run one saved skill on the dropped file and return the reply-box text."""
    from .node_params import PARAM_ENGINE
    from .session_files import read_document, run_document

    document = read_document(skill_path)
    for node in document["nodes"]:
        if node.get("type") == PARAM_ENGINE and not node.get("bind"):
            node.setdefault("params", {})["value"] = str(file_path)
            break

    def invoke(engine, effect, params, feeds):
        return effect(params, feeds)

    result = run_document(document, invoke=invoke)
    if not result.get("succeeded"):
        errors = [str(row.get("error")) for row in result.get("results", {}).values() if row.get("error")]
        return "Skill failed: " + ("; ".join(errors) if errors else "the skill did not finish.")
    order = result.get("order") or []
    if not order:
        return "Skill ran."
    last = result["results"][order[-1]]
    shown = last.get("display")
    if shown in (None, "", {}):
        shown = last.get("output")
    if isinstance(shown, Mapping):
        shown = shown.get("value", shown)
    text = str(shown).strip() if shown not in (None, "") else ""
    return text or "Skill ran."
