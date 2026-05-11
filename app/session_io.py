"""Session persistence — save and load parametric sessions to/from disk.

Sessions are stored as .archhub-session.json files.
Default location: %LOCALAPPDATA%/ArchHub/sessions/
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from session import (
    Session, Parameter, ParamType, ChainStep, StepKind, StepStatus, StepOutput,
)

SESSIONS_DIR = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "ArchHub" / "sessions"
SESSION_EXT = ".archhub-session.json"


def save_session(session: Session, name: str = "", path: Optional[Path] = None,
                 messages: Optional[list] = None) -> Path:
    """Save session to disk. Returns the path written.

    `messages` — optional list of ChatMessage objects (or dicts already
    serialized via _msg_to_dict). When present, persists the entire
    chat conversation alongside the parametric session so reloading
    restores the full transcript, not just parameters + chain steps.
    """
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    if path is None:
        slug = _slugify(name or f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
        path = SESSIONS_DIR / f"{slug}{SESSION_EXT}"
    else:
        slug = path.stem.replace(SESSION_EXT.replace(".", ""), "")
    data = session.to_dict()
    data["_name"] = name or slug
    data["_saved_at"] = datetime.now().isoformat()
    if messages is not None:
        data["_messages"] = [_msg_to_dict(m) for m in messages]
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    return path


def load_session(path: Path) -> tuple[Session, str]:
    """Load session from disk. Returns (session, name).

    Use `load_session_with_messages` to also recover the chat history.
    Two entry points so callers that only want params (e.g. workflow
    runner) don't pay the deserialization cost.
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    session = _session_from_dict(data)
    name = data.get("_name", path.stem)
    return session, name


def load_session_with_messages(path: Path) -> tuple[Session, str, list[dict]]:
    """Load session + its chat message history. Messages come back as
    plain dicts; the chat layer reconstructs ChatMessage objects so we
    don't import the Qt module from this storage layer."""
    data = json.loads(path.read_text(encoding="utf-8"))
    session = _session_from_dict(data)
    name = data.get("_name", path.stem)
    messages = data.get("_messages") or []
    return session, name, list(messages)


def _msg_to_dict(msg) -> dict:
    """Serialise one ChatMessage to a JSON-safe dict.

    Tool invocations + image paths are preserved so a reload renders
    the bubble exactly as the user saw it last.
    """
    # Accept already-serialised dicts (autosave path may pre-build them).
    if isinstance(msg, dict):
        return msg
    role = getattr(msg, "role", "user")
    content = getattr(msg, "content", "") or ""
    model = getattr(msg, "model", "") or ""
    images = list(getattr(msg, "images", None) or [])
    invs_raw = getattr(msg, "tool_invocations", None) or []
    invs = []
    for inv in invs_raw:
        try:
            invs.append(inv.to_dict() if hasattr(inv, "to_dict") else dict(inv))
        except Exception:
            continue
    ts = getattr(msg, "timestamp", None)
    ts_iso = ""
    try:
        ts_iso = ts.isoformat() if ts is not None else ""
    except Exception:
        ts_iso = str(ts) if ts is not None else ""
    return {
        "role": role,
        "content": content,
        "model": model,
        "images": images,
        "tool_invocations": invs,
        "timestamp": ts_iso,
    }


def list_sessions() -> list[tuple[Path, str, str]]:
    """Return [(path, name, saved_at)] sorted newest first."""
    if not SESSIONS_DIR.exists():
        return []
    results = []
    for f in SESSIONS_DIR.glob(f"*{SESSION_EXT}"):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            name = data.get("_name", f.stem)
            saved_at = data.get("_saved_at", "")
        except Exception:
            name, saved_at = f.stem, ""
        results.append((f, name, saved_at))
    return sorted(results, key=lambda x: x[2], reverse=True)


def _session_from_dict(data: dict) -> Session:
    """Reconstruct a Session from a serialized dict."""
    session = Session()
    session.id = data.get("id", session.id)
    session.created_at = data.get("created_at", session.created_at)

    for p_dict in data.get("parameters") or []:
        try:
            param = Parameter.from_dict(p_dict)
            session.parameters[param.name] = param
        except Exception:
            pass

    for s_dict in data.get("chain") or []:
        try:
            kind = StepKind(s_dict.get("kind", "user.prompt"))
            status = StepStatus(s_dict.get("status", "ok"))
            output = None
            if s_dict.get("output"):
                o = s_dict["output"]
                output = StepOutput(
                    kind=o.get("kind", "text"),
                    value=o.get("value"),
                    preview=o.get("preview"),
                    metadata=o.get("metadata") or {},
                )
            step = ChainStep(
                id=s_dict.get("id", f"step_{uuid.uuid4().hex[:10]}"),
                kind=kind, label=s_dict.get("label", ""),
                parameters_used=s_dict.get("parameters_used") or [],
                parameters_introduced=s_dict.get("parameters_introduced") or [],
                config=s_dict.get("config") or {},
                status=StepStatus.OK,   # restore as OK — don't re-run on load
                output=output,
            )
            session.chain.append(step)
        except Exception:
            pass

    return session


def _slugify(s: str) -> str:
    import re
    s = s.lower().strip()
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"[\s_-]+", "_", s)
    return s[:60] or "session"
