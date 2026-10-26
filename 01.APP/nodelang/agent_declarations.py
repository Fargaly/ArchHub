"""Workshop declaration nodes; the mailbox remains the only coordination channel."""
from hashlib import sha256
import ntpath
from pathlib import Path


SESSION_KEYS = {"threadId": "codex", "ai.opencode/sessionID": "opencode",
                "claude/sessionID": "claude", "gemini/sessionID": "gemini",
                "goose/sessionID": "goose", "archhub/sessionID": "archhub"}
SESSION_KEYS.update({"antigravity/sessionID": "antigravity", "antigravity-ide/sessionID": "antigravity-ide"})


def _alive(row, *, strict=False):
    import psutil
    try:
        return abs(psutil.Process(row["pid"]).create_time() - row["created_at"]) < 0.00001
    except (psutil.Error, OSError) as exc:
        if strict and not isinstance(exc, psutil.NoSuchProcess):
            raise
        return False


def _lineage(peer):
    """OS-observed task-control provenance, never sender-selected process data."""
    import psutil
    result = [{"pid":peer.pid, "created_at":peer.created_at}]
    try:
        process = psutil.Process(peer.pid)
        if abs(process.create_time()-peer.created_at) >= 0.00001:
            return result
        for _ in range(7):
            process = process.parent()
            if process is None:
                break
            result.append({"pid":process.pid, "created_at":process.create_time()})
    except (psutil.Error, OSError):
        return result
    return result


def declarations(owner, *, include_archived=False):
    """Read the same typed declaration rows used with the UI closed."""
    from .workshop_mailbox import read_declarations
    from .conversation_content import read_content_binding
    with owner.mutation_lock:
        owner.conversation_content._require_live_owner()
        registry = owner.universal_registry
        binding = read_content_binding(owner.universal_store.snapshot(), registry.deliberation_protocol,
            application_root=registry.application_root, space_root=registry.workshop_root)
        history = owner.conversation_content._history_for(binding)
    with history._transaction():
        return read_declarations(history._db, include_archived=include_archived)


def canonical_path(value, cwd):
    if type(value) is not str or not value.strip() or "\0" in value or len(value.encode()) > 4096:
        raise ValueError("declare exact bounded file, folder or host paths")
    value = value.strip()
    if "://" in value:
        return value.replace("\\", "/").rstrip("/").casefold()
    # Resolve junctions/symlinks as well as dot segments; retain the actual host
    # name/drive so two unrelated workspaces never claim the same relative path.
    path = value if ntpath.isabs(value) else ntpath.join(cwd, value)
    return ntpath.normcase(ntpath.normpath(str(Path(path).resolve()))).replace("\\", "/").rstrip("/")


def overlaps(first, second):
    return sorted({a if len(a) >= len(b) else b for a in first for b in second
                   if a == b or a.startswith(b + "/") or b.startswith(a + "/")})


def founder_inbox(history, space):
    """A filtered lens of addressed notes, never a separate inbox/store."""
    rows = history._db.execute("SELECT * FROM messages WHERE conversation_id=? AND public=1 "
        "AND content LIKE 'To founder:%' ORDER BY sequence DESC LIMIT 100", (space,))
    result = []
    for row in rows:
        message = history._message(row)
        content = message["content"]
        result.append({"id":message["id"], "sequence":message["sequence"], "author":message["author"],
                       "content":content[:500], "truncated":len(content)>500, "created_at":message["created_at"]})
    return result


def reminder(*, mailbox=None):
    """Advisory Stop/commit context; never refuses or grants an operation."""
    notice = "Workshop: declare(task, paths, status, request_id); keep it current. Send findings to founder in the same mailbox."
    try:
        if mailbox is None:
            from .native_agent_mcp import _mailbox_call, _default_context
            from .library_engines import LIBRARY_ITEM_ENGINES
            budget = min(0.75, LIBRARY_ITEM_ENGINES['tool_workshop']['params']['preflight_database_ms'] / 1000)
            context = _default_context()
            if not context:
                return ""  # A human commit is not an undeclared agent session.
            page = _mailbox_call("read", {"since": 0}, context, timeout_seconds=budget)
            native = next(iter(context.values()), None)
        else:
            page, native = mailbox(), None
        if any(row.get("request_id") != "unassigned" and
               (row["session"] == page["sender_key"] or
                native is not None and row.get("native_session_id") == native)
               for row in page.get("declarations", [])):
            return ""
    except (OSError, RuntimeError, ValueError, KeyError):
        # App off or an older version is not a reason to stop routine work.
        return notice
    return notice


def declared_baboom(function):
    """Built-in turns declare through the same application-owned MCP sink."""
    from functools import wraps

    @wraps(function)
    def run(*args, **kwargs):
        owner = getattr(kwargs.get("agent_mail"), "__self__", None)
        if owner is None:
            return function(*args, **kwargs)
        utterance = kwargs.get("utterance", "")
        request = "baboom:" + sha256(utterance.encode()).hexdigest()[:24]
        with declaration_scope(owner, task="Respond to a founder BABOOM request", request_id=request):
            result = function(*args, **kwargs)
            report = result.get("response", result) if type(result) is dict else {}
            if type(report) is dict and report.get("kind") in {"finding", "proposal", "needs-approval", "decision-needed"}:
                notify_founder(owner, "BABOOM has a new " + report["kind"] + " for your review (request " + request + ").")
            return result
    return run


def declaration_scope(owner, *, task, request_id, session=None, paths=None):
    from contextlib import contextmanager
    from .model_router import redact_user_visible
    import logging

    def publish_status(body):
        try:
            owner.shared_agent_mail("declare", body)
        except Exception:
            logging.getLogger(__name__).warning("Workshop declaration unavailable; task continues. Call declare to reconcile.")

    @contextmanager
    def scope():
        line = " ".join(redact_user_visible(task).split()).encode()[:1000].decode(errors="ignore")
        body = {"task": line or "Working on a founder request",
                "paths": paths or [str(owner.universal_workspace_root)], "request_id":request_id,
                "status":"working"}
        if session:
            body["context"] = {"archhub/sessionID":session}
        publish_status(body)
        try:
            yield
        except BaseException:
            publish_status({**body, "status":"blocked"})
            raise
        else:
            publish_status({**body, "status":"done"})
    return scope()


def notify_founder(owner, text, *, context=None):
    """A metadata-only notice never copies private conversation/host content."""
    import logging
    try:
        return owner.shared_agent_mail("send", {"to":"founder", "text":text,
            **({"context":context} if context else {})})
    except Exception:
        logging.getLogger(__name__).warning("Founder notice unavailable; result remains in its source conversation.")
        return None
