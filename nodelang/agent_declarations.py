"""Workshop declaration nodes; the mailbox remains the only coordination channel."""
from datetime import datetime, timezone
from hashlib import sha256
import json
import ntpath
from pathlib import Path

from .cell_protocols import compose_relation_cells, prepare_append_relation_members, read_relation
from .universal_cell import Cell, NULL_CELL_ID

FIELDS = ("agent", "session", "task", "request_id", "paths", "status", "updated_at",
          "runtime", "app", "native_session_id", "pid", "created_at", "version", "process_lineage")
ROLE = "workshop:agent-declaration:"
SESSION_KEYS = {"threadId": "codex", "ai.opencode/sessionID": "opencode",
                "claude/sessionID": "claude", "gemini/sessionID": "gemini",
                "goose/sessionID": "goose", "archhub/sessionID": "archhub"}
SESSION_KEYS.update({"antigravity/sessionID": "antigravity", "antigravity-ide/sessionID": "antigravity-ide"})


def _terminal(root, value):
    return Cell(root, NULL_CELL_ID, NULL_CELL_ID, json.dumps(value, ensure_ascii=False).encode())


def _index(registry):
    return registry.workshop_root + ":agent-declarations"


def _rows(snapshot, registry):
    index = _index(registry)
    if index not in snapshot.cells:
        return []
    result = []
    for member in read_relation(snapshot, index):
        if member.role_id != ROLE + "member":
            continue
        values = {item.role_id.removeprefix(ROLE): json.loads(snapshot.cells[item.participant_id].atom)
                  for item in read_relation(snapshot, member.participant_id)}
        result.append({"root": member.participant_id, **values})
    return result


def _alive(row):
    import psutil
    try:
        return abs(psutil.Process(row["pid"]).create_time() - row["created_at"]) < 0.00001
    except (psutil.Error, OSError):
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
    """No idle writes: process exit or done archives the node in this same lens."""
    registry = owner.universal_registry
    rows = _rows(owner.universal_store.snapshot(), registry)
    for row in rows:
        row["process_alive"] = _alive(row)
        row["current"] = row["status"] != "done" and row["process_alive"]
        row["sockets"] = {field: row["root"] + ":" + field for field in FIELDS}
    return [row for row in rows if include_archived or row["current"]]


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


def publish(owner, peer, identity, context, body, *, append):
    """Caller holds the app mutation lock and existing mailbox authority guard."""
    from .agent_runtime_registry import mailbox_label
    task, request, status, paths = (body[key] for key in ("task", "request_id", "status", "paths"))
    for value, maximum in ((task, 1024), (request, 256)):
        if (type(value) is not str or not value.strip() or "\0" in value or "\n" in value
                or "\r" in value or len(value.encode()) > maximum):
            raise ValueError("declare one plain task line and its founder request id")
    if type(status) is not str or status not in ("working", "blocked", "done"):
        raise ValueError("declaration status must be working, blocked or done")
    if type(paths) is not list or not 1 <= len(paths) <= 128:
        raise ValueError("declare between 1 and 128 exact paths")
    paths = sorted({canonical_path(path, peer.cwd) for path in paths})
    if sum(len(path.encode()) for path in paths) > 16384:
        raise ValueError("declaration paths exceed the 16 KiB node budget")
    registry, store = owner.universal_registry, owner.universal_store
    root = _index(registry) + ":" + sha256(identity["sender_key"].encode()).hexdigest()
    snapshot = store.snapshot()
    old = next((row for row in _rows(snapshot, registry) if row["root"] == root), None)
    runtime = SESSION_KEYS.get(next(iter(context), ""), mailbox_label(peer, context)[1])
    if identity["sender_label"] == "BABOOM":
        runtime = "baboom"
    row = dict(agent=identity["sender_label"], session=identity["sender_key"], task=task.strip(),
               request_id=request.strip(), paths=paths, status=status, runtime=runtime, app=runtime,
               native_session_id=next(iter(context.values()), None), pid=peer.pid, created_at=peer.created_at,
               process_lineage=_lineage(peer))
    changed = old is None or any(row[key] != old[key] for key in row)
    row.update(updated_at=datetime.now(timezone.utc).isoformat(),
               version=(old["version"] if old else 0) + int(changed))
    create, replace = [], []
    if old is None:
        for field in (*FIELDS, "member"):
            if ROLE + field not in snapshot.cells:
                create.append(_terminal(ROLE + field, field))
        create.extend(_terminal(root + ":" + field, row[field]) for field in FIELDS)
        create.extend(compose_relation_cells(((ROLE + field, root + ":" + field) for field in FIELDS),
                                            relation_id=root).cells)
        index = _index(registry)
        if index not in snapshot.cells:
            create.extend(compose_relation_cells(((ROLE + "member", root),), relation_id=index).cells)
            patch = prepare_append_relation_members(snapshot, registry.application_root,
                ((registry.roles["member"], index),))
        else:
            patch = prepare_append_relation_members(snapshot, index, ((ROLE + "member", root),))
        create.extend(patch.create)
        replace.extend(patch.replace)
    else:
        replace.extend(_terminal(root + ":" + field, row[field]) for field in FIELDS if row[field] != old[field])
    store.commit(snapshot.revision, create=tuple(create), replace=tuple(replace))
    row = {"root": root, **row, "current": status != "done"}
    notices = []
    if row["current"] and row["request_id"] != "unassigned":
        for other in declarations(owner):
            shared = overlaps(paths, other["paths"]) if other["root"] != root and other["request_id"] != "unassigned" else []
            if not shared:
                continue
            pair = sorted(((root, row["version"]), (other["root"], other["version"])))
            key = "declaration-overlap:" + sha256(json.dumps(pair).encode()).hexdigest()
            ordered = sorted((row, other), key=lambda item: item["root"])
            attached = [{field: item[field] for field in
                ("root", "agent", "session", "task", "request_id", "paths", "status", "version")}
                for item in ordered]
            content = ("To " + ordered[0]["agent"] + ", " + ordered[1]["agent"] + ":\n"
                "Your work overlaps at " + ", ".join(shared) + ". Coordinate here: one yields or split the paths. "
                "This is a notice, never a lock.\n" + json.dumps({"declarations": attached}, ensure_ascii=False))
            notice = append(content, key, tuple(item["root"] for item in ordered))
            notices.append(notice["id"])
    return {"declaration": row, "coordination_messages": notices}


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
            context = _default_context()
            if not context:
                return ""  # A human commit is not an undeclared agent session.
            page = _mailbox_call("read", {"since": 0}, context)
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
