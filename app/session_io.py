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


def save_session(session: Session, name: str = "", path: Optional[Path] = None) -> Path:
    """Save session to disk. Returns the path written."""
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    if path is None:
        slug = _slugify(name or f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
        path = SESSIONS_DIR / f"{slug}{SESSION_EXT}"
    data = session.to_dict()
    data["_name"] = name or slug
    data["_saved_at"] = datetime.now().isoformat()
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    return path


def load_session(path: Path) -> tuple[Session, str]:
    """Load session from disk. Returns (session, name)."""
    data = json.loads(path.read_text(encoding="utf-8"))
    session = _session_from_dict(data)
    name = data.get("_name", path.stem)
    return session, name


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
