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


class EmptySessionError(ValueError):
    """Raised when save_session is called with a payload that would
    produce a stub file (no messages, no parameters, no chain steps).

    Pre-v1.0 autosave silently wrote stub files because save_session
    accepted any Session object without verifying it had content. The
    chat surface stored conversation in self.history, not
    self.session, so the saved payload was always empty — files
    appeared in the THREADS rail but loaded blank chats.

    This error is the load-bearing piece preventing recurrence. Every
    caller MUST pass either messages=, or a populated Session with
    parameters/chain, or both. Empty saves are no longer silent —
    they raise loud and the file is never written."""


class SessionRoundtripError(RuntimeError):
    """Raised when save_session writes a payload but the verification
    re-read returns different counts. Means the on-disk JSON is
    corrupted or the serializer dropped content silently. The
    half-written file is unlinked before raising."""


def _payload_is_empty(session: Session, messages: Optional[list]) -> bool:
    """Return True iff this save would produce a stub file."""
    if messages:
        return False
    try:
        params = getattr(session, "parameters", None) or {}
        chain = getattr(session, "chain", None) or []
        if len(params) > 0 or len(chain) > 0:
            return False
    except Exception:
        return False
    return True


def save_session(session: Session, name: str = "", path: Optional[Path] = None,
                 messages: Optional[list] = None) -> Path:
    """Save session to disk. Returns the path written.

    `messages` — list of ChatMessage objects (or dicts already
    serialized via _msg_to_dict). When present, persists the entire
    chat conversation alongside the parametric session so reloading
    restores the full transcript, not just parameters + chain steps.

    Contract (enforced at runtime):
      1. Refuses to write if messages + parameters + chain are ALL
         empty — raises EmptySessionError instead of silently producing
         a stub. This is the load-bearing rule that prevents recurrence
         of the "sessions are empty after restart" bug class.
      2. After writing, re-reads the file and verifies the message /
         parameter / chain counts match what was passed in. Mismatch
         raises SessionRoundtripError and unlinks the half-written
         file. Future serializer regressions blow up loudly instead
         of silently corrupting saves.
    """
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    if path is None:
        slug = _slugify(name or f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
        path = SESSIONS_DIR / f"{slug}{SESSION_EXT}"
    else:
        slug = path.stem.replace(SESSION_EXT.replace(".", ""), "")

    # Contract gate #1 — refuse empty payloads.
    if _payload_is_empty(session, messages):
        raise EmptySessionError(
            f"Refusing to save empty session '{name or slug}': no "
            "messages, no parameters, no chain steps. Pass "
            "messages=self.history (chat surface) or populate "
            "session.parameters / session.chain (skills surface) "
            "before saving."
        )

    # ADR-003 Phase 2: dual-write the graph projection. If the session
    # already has a `graph` (canvas authored it), keep it but refresh
    # its conversation node body with the latest messages. Otherwise
    # auto-wrap the legacy session into a single-`conversation.chat`-
    # node graph. Pure additive — legacy `_messages` continues to be
    # written so v1.3.x loaders keep working.
    from session_graph_migrator import (
        wrap_legacy_as_graph, update_graph_messages,
    )
    if session.graph is None:
        session.graph = wrap_legacy_as_graph(
            session, messages, name=name or slug,
        )
    else:
        update_graph_messages(session.graph, messages or [])

    data = session.to_dict()
    data["_name"] = name or slug
    data["_saved_at"] = datetime.now().isoformat()
    msg_list: list[dict] = []
    if messages is not None:
        msg_list = [_msg_to_dict(m) for m in messages]
        data["_messages"] = msg_list
    expected_msgs = len(msg_list)
    expected_params = len(data.get("parameters") or [])
    expected_chain = len(data.get("chain") or [])
    expected_graph_nodes = len((data.get("graph") or {}).get("nodes") or [])

    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")

    # Contract gate #2 — round-trip verify. If the re-read drops any
    # of the three populations, the file is corrupt; remove it +
    # raise so the caller can react.
    try:
        verify = json.loads(path.read_text(encoding="utf-8"))
        got_msgs = len(verify.get("_messages") or [])
        got_params = len(verify.get("parameters") or [])
        got_chain = len(verify.get("chain") or [])
        got_graph_nodes = len((verify.get("graph") or {}).get("nodes") or [])
        if (got_msgs != expected_msgs
                or got_params != expected_params
                or got_chain != expected_chain
                or got_graph_nodes != expected_graph_nodes):
            try:
                path.unlink(missing_ok=True)
            except Exception:
                pass
            raise SessionRoundtripError(
                f"Save verification failed for '{name or slug}': "
                f"wrote msgs={expected_msgs}/params={expected_params}/"
                f"chain={expected_chain}/graph_nodes={expected_graph_nodes}"
                f" but read back msgs={got_msgs}/params={got_params}/"
                f"chain={got_chain}/graph_nodes={got_graph_nodes}."
                f" File removed."
            )
    except SessionRoundtripError:
        raise
    except Exception as ex:
        # Verification itself blew up — better to delete the file than
        # leave a possibly-corrupt one on disk that re-loads as a stub.
        try:
            path.unlink(missing_ok=True)
        except Exception:
            pass
        raise SessionRoundtripError(
            f"Couldn't verify saved session '{name or slug}': "
            f"{type(ex).__name__}: {ex}"
        )

    return path


def load_session(path: Path) -> tuple[Session, str]:
    """Load session from disk. Returns (session, name).

    Use `load_session_with_messages` to also recover the chat history.
    Two entry points so callers that only want params (e.g. workflow
    runner) don't pay the deserialization cost.
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    session = _session_from_dict(data)
    # v1.4 graph-first schema stores `name` at top level; legacy chat
    # schema stores `_name`. Try both, fall back to file stem.
    name = data.get("name") or data.get("_name") or path.stem
    return session, name


def load_session_with_messages(path: Path) -> tuple[Session, str, list[dict]]:
    """Load session + its chat message history. Messages come back as
    plain dicts; the chat layer reconstructs ChatMessage objects so we
    don't import the Qt module from this storage layer."""
    data = json.loads(path.read_text(encoding="utf-8"))
    session = _session_from_dict(data)
    name = data.get("name") or data.get("_name") or path.stem
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


def _node_host_family(node: dict) -> str:
    """Host family key for a `cat == "host"` graph node. Node ids look
    like `h_<family>_<rand>` (e.g. `h_outlook_ma8p`); fall back to the
    first word of the title. Lower-cased so it matches the JSX
    `LM_HOST_META` keys."""
    nid = str(node.get("id") or "")
    if nid.startswith("h_"):
        parts = nid.split("_")
        if len(parts) >= 3 and parts[1]:
            return parts[1].lower()
    title = str(node.get("title") or "").strip().lower()
    return title.split()[0] if title else ""


def _summarize(data: dict) -> dict:
    """Pull the card-facing summary out of a parsed session blob:
    distinct host families, last-message preview, message + node
    counts. Graph-first sessions keep messages inside `cat == "ai"`
    conversation nodes; legacy sessions keep them in top-level
    `_messages`. Both are folded in."""
    graph = data.get("graph") or {}
    nodes = graph.get("nodes") or []
    hosts: list[str] = []
    msgs: list[dict] = []
    for n in nodes:
        if not isinstance(n, dict):
            continue
        if n.get("cat") == "host":
            fam = _node_host_family(n)
            if fam and fam not in hosts:
                hosts.append(fam)
        nm = n.get("messages")
        if isinstance(nm, list):
            msgs.extend(m for m in nm if isinstance(m, dict))
    legacy = data.get("_messages")
    if isinstance(legacy, list):
        msgs.extend(m for m in legacy if isinstance(m, dict))
    last = ""
    if msgs:
        raw = msgs[-1].get("text") or msgs[-1].get("content") or ""
        last = " ".join(str(raw).split())[:120]
    return {
        "host": hosts,
        "last": last,
        "messages": len(msgs),
        "node_count": len(nodes),
    }


def _scan_sessions(*, include_empty: bool = False) -> list[dict]:
    """Single scanner — glob + parse every session file ONCE, apply the
    stub filter, return a rich dict per surviving session. Both
    `list_sessions` (legacy tuple shape) and `list_sessions_rich` are
    thin views over this so the parse happens exactly once and the two
    can never drift."""
    if not SESSIONS_DIR.exists():
        return []
    out: list[dict] = []
    for f in SESSIONS_DIR.glob(f"*{SESSION_EXT}"):
        summary = {"host": [], "last": "", "messages": 0, "node_count": 0}
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            # v1.4 graph-first schema uses `name` + `saved_at` at top level;
            # legacy chat schema uses `_name` + `_saved_at`. Prefer v1.4 first.
            name = data.get("name") or data.get("_name") or f.stem
            saved_at = data.get("saved_at") or data.get("_saved_at") or ""
            if not include_empty:
                # Real-content signals. Any one is enough:
                #   • At least one assistant message with non-empty
                #     content (a real chat — empty assistant content
                #     means the LLM never responded, so it's a stub)
                #   • At least one parameter (Skills-style save)
                #   • At least one chain step
                #   • v1.4 graph-first: at least one graph node OR a
                #     fresh v1.4 schema (id + name + saved_at present
                #     means user explicitly minted this session via the
                #     composer — keep it even if empty)
                msgs = data.get("_messages") or []
                params = data.get("parameters") or []
                chain = data.get("chain") or []
                graph_nodes = ((data.get("graph") or {}).get("nodes") or [])
                v14_minted = (
                    bool(data.get("id"))
                    and bool(data.get("name"))
                    and bool(data.get("saved_at"))
                )
                has_real_chat = any(
                    m.get("role") == "assistant"
                    and (m.get("content") or "").strip()
                    for m in msgs if isinstance(m, dict)
                )
                if (not has_real_chat and not params and not chain
                        and not graph_nodes and not v14_minted):
                    continue
            summary = _summarize(data)
        except Exception:
            if not include_empty:
                continue
            name, saved_at = f.stem, ""
        out.append({"path": f, "name": name, "saved_at": saved_at,
                    **summary})
    return sorted(out, key=lambda r: r["saved_at"], reverse=True)


def list_sessions(*, include_empty: bool = False
                   ) -> list[tuple[Path, str, str]]:
    """Return [(path, name, saved_at)] sorted newest first.

    Legacy tuple shape — kept stable for existing callers. For the
    host / last-message / counts the session cards render, use
    `list_sessions_rich`.

    Pre-v1.0 autosave bug wrote stub files containing zero messages,
    zero parameters, zero chain steps — sessions that look saved in
    the THREADS rail but load an empty chat. By default we filter
    those out so the rail only surfaces sessions with actual content.
    Pass include_empty=True to see everything (cleanup utility / test).
    """
    return [(r["path"], r["name"], r["saved_at"])
            for r in _scan_sessions(include_empty=include_empty)]


def list_sessions_rich(*, include_empty: bool = False) -> list[dict]:
    """Like `list_sessions`, but each entry is a dict carrying the
    fields the Home session cards render:

        {path, name, saved_at, host: [str], last: str,
         messages: int, node_count: int}

    Same single scan + stub filter as `list_sessions`."""
    return _scan_sessions(include_empty=include_empty)


def cleanup_empty_sessions() -> int:
    """Delete stub files from the sessions directory. Returns count
    removed.

    A file is a stub when it has no assistant message with non-empty
    content AND no parameters AND no chain steps. Captures both the
    original empty-stub bug (pre-fix autosave wrote Session.to_dict
    only) AND the failure-mode stubs (LLM call returned empty text
    so the assistant message was saved as ''). Used by the
    'Clean up empty sessions' settings action + once at app startup
    to keep the rail tidy across crashes."""
    if not SESSIONS_DIR.exists():
        return 0
    removed = 0
    for f in SESSIONS_DIR.glob(f"*{SESSION_EXT}"):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        msgs = data.get("_messages") or []
        params = data.get("parameters") or []
        chain = data.get("chain") or []
        has_real_chat = any(
            m.get("role") == "assistant"
            and (m.get("content") or "").strip()
            for m in msgs if isinstance(m, dict)
        )
        if not has_real_chat and not params and not chain:
            try:
                f.unlink()
                removed += 1
            except Exception:
                continue
    return removed


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

    # ADR-003 Phase 2: restore the graph projection if present. Older
    # session files without `graph` leave it at None — chat surface
    # continues to read `_messages` as before. v1.4: preserve even an
    # empty graph dict so save_graph round-trips correctly.
    graph_dict = data.get("graph")
    if isinstance(graph_dict, dict):
        session.graph = graph_dict

    return session


def _slugify(s: str) -> str:
    import re
    s = s.lower().strip()
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"[\s_-]+", "_", s)
    return s[:60] or "session"
