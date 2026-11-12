"""Workshop tasks: one table in the Workshop mailbox SQLite, claimed atomically.

Prior art: Paperclip issues.ts checkout. A claim is one conditional UPDATE; the row
changes only when it is free, its lease expired, or the claimant already holds it.
A lease that lapses frees the task for the next agent; nothing runs on a timer.

Adapted from DeepSeek Harness 8bd07339 (MIT, (c) 2026 DeepSeek).
Every task write names the revision it read. A stale revision conflicts.
"""
import json
import re
import time
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from uuid import uuid4

SCHEMA = ("CREATE TABLE IF NOT EXISTS workshop_tasks(id TEXT PRIMARY KEY, title TEXT NOT NULL, "
          "status TEXT NOT NULL CHECK(status IN ('open','claimed','done')), owner TEXT, owner_label TEXT, "
          "lease_until REAL, result TEXT, created_by TEXT NOT NULL, created_at TEXT NOT NULL, "
          "updated_at TEXT NOT NULL, session_path TEXT, purpose TEXT, project TEXT, "
          "archived INTEGER NOT NULL DEFAULT 0, revision INTEGER NOT NULL DEFAULT 0, "
          "outcome TEXT, write_open INTEGER NOT NULL DEFAULT 0, capacity TEXT, members TEXT) STRICT")
TASKS_NODE = {'id': 'workshop.tasks', 'params': {'lease_seconds': 900, 'stale_hours': 24, 'max_runs': 2}}
UI_STATUS = {"open": "PLANNED", "claimed": "WIP", "done": "DONE"}


class TaskNotFound(ValueError):
    """The task id is not in the Workshop table."""
    code = "NOT_FOUND"

    def __init__(self, task):
        self.task = task
        super().__init__("No such Workshop task")


class TaskConflict(Exception):
    """The write named a revision that is no longer the row's revision."""
    code = "CONFLICT"

    def __init__(self, task, revision):
        self.task = task
        self.revision = revision
        super().__init__("Task write conflict")


class TaskLeaseLost(Exception):
    """The owner no longer holds the lease this write relies on."""
    code = "LEASE_LOST"

    def __init__(self, task):
        self.task = task
        super().__init__("Task lease lost")


class TaskLimitReached(Exception):
    """Another run would pass the capacity parameter."""
    code = "LIMIT_REACHED"

    def __init__(self, task):
        self.task = task
        super().__init__("LIMIT_REACHED")


def _now():
    return datetime.now(timezone.utc).isoformat()


def _add_column(history, column):
    """Two processes opening one old database together may both try the add; the second finds it done."""
    import sqlite3
    try:
        history._db.execute("ALTER TABLE workshop_tasks ADD COLUMN " + column)
    except sqlite3.OperationalError as error:
        if "duplicate column" not in str(error).lower():
            raise


def _ensure(history):
    """The task table is the association: session_path is that task's .archhub file."""
    history._db.execute(SCHEMA)
    names = {row[1] for row in history._db.execute("PRAGMA table_info(workshop_tasks)")}
    if "session_path" not in names:
        _add_column(history, "session_path TEXT")
    if "archived" not in names:
        _add_column(history, "archived INTEGER NOT NULL DEFAULT 0")
    if "purpose" not in names:
        _add_column(history, "purpose TEXT")
    if "project" not in names:
        _add_column(history, "project TEXT")
    if "revision" not in names:
        _add_column(history, "revision INTEGER NOT NULL DEFAULT 0")
    if "outcome" not in names:
        _add_column(history, "outcome TEXT")
    if "write_open" not in names:
        _add_column(history, "write_open INTEGER NOT NULL DEFAULT 0")
    if "capacity" not in names:
        _add_column(history, "capacity TEXT")
    if "members" not in names:
        _add_column(history, "members TEXT")
    history._db.execute("CREATE INDEX IF NOT EXISTS workshop_tasks_open_work "
                        "ON workshop_tasks(project, status, archived, updated_at)")


def _write(history, sql, values):
    with history._transaction(write=True):
        _ensure(history)
        return history._db.execute(sql, values).rowcount == 1


def _locked(history, task):
    _ensure(history)
    found = history._db.execute(
        "SELECT revision, status, owner, owner_label, lease_until, members FROM workshop_tasks WHERE id=?", (task,)).fetchone()
    if found is None:
        return None
    return {"revision": found[0], "status": found[1], "owner": found[2],
            "members": _member_list(found[5], found[2], found[3], found[4])}


def _member_list(text, owner=None, label=None, lease=None):
    """Every agent that joined the session, in join order. A row from before members holds its one owner."""
    try:
        held = json.loads(text) if text else []
    except ValueError:
        held = []
    held = [m for m in held if isinstance(m, dict) and isinstance(m.get("owner"), str)] if isinstance(held, list) else []
    if not held and owner:
        held = [{"owner": owner, "label": label or owner, "lease_until": lease}]
    return held


def _live(members, now=None):
    now = time.time() if now is None else now
    return [m for m in members if (m.get("lease_until") or 0) >= now]


def _holds(row, owner):
    return row["status"] == "claimed" and any(m["owner"] == owner for m in _live(row["members"]))


def _seat(members, now):
    """The row's owner columns name the latest live member; none live frees the session for the next agent."""
    live = _live(members, now)
    if not live:
        return "open", None, None, None
    latest = max(live, key=lambda m: m["lease_until"])
    return "claimed", latest["owner"], latest.get("label") or latest["owner"], max(m["lease_until"] for m in live)


def _update(history, task, revision, statement, *, holder=None):
    """Apply statement(revision) only when that revision is still current.

    statement returns (sql, values). The sql names the revision it read.
    A missing row is not-found. A moved revision is a conflict. A matching
    revision whose holder no longer has the lease is lease-lost.
    """
    with history._transaction(write=True):
        row = _locked(history, task)
        if row is None:
            if revision is None:
                return False
            raise TaskNotFound(task)
        if revision is not None and int(revision) != row["revision"]:
            raise TaskConflict(task, revision)
        if holder is not None and not _holds(row, holder):
            if revision is None:
                return False
            raise TaskLeaseLost(task)
        expected = row["revision"] if revision is None else int(revision)
        sql, values = statement(expected)
        if history._db.execute(sql, values).rowcount == 1:
            return True
        again = _locked(history, task)
        if again is None:
            raise TaskNotFound(task)
        if again["revision"] != expected:
            if revision is None:
                return False
            raise TaskConflict(task, revision)
        if holder is not None:
            if revision is None:
                return False
            raise TaskLeaseLost(task)
        if revision is None:
            return False
        raise TaskConflict(task, revision)


def _settle_lapsed(history):
    """A claimed row whose lease has passed is closed, then returned to the queue.

    Interrupted when the owner was between writes. Unknown when a write was still open.
    """
    now = time.time()
    _write(history, "UPDATE workshop_tasks SET outcome=CASE WHEN IFNULL(write_open,0)=1 THEN 'unknown' "
           "ELSE 'interrupted' END, status='open', owner=NULL, owner_label=NULL, lease_until=NULL, "
           # The session stays open for the next agent; every member's lease ends with it, the members stay listed.
           "members=CASE WHEN json_valid(members) THEN (SELECT json_group_array(json_set(value,'$.lease_until',NULL)) "
           "FROM json_each(workshop_tasks.members)) ELSE members END, "
           "write_open=0, revision=revision+1 WHERE status='claimed' AND lease_until IS NOT NULL "
           "AND lease_until<? AND NOT (id LIKE 'declared-%' AND " + _LIVE_ELSEWHERE + ")", (now, now))


# The row's owner is a live member of an open session (piece of work) today.
_LIVE_ELSEWHERE = ("EXISTS (SELECT 1 FROM workshop_tasks AS work, json_each(CASE WHEN json_valid(work.members) "
                   "THEN work.members ELSE '[]' END) AS member WHERE work.id NOT LIKE 'declared-%' "
                   "AND work.status!='done' AND IFNULL(work.archived,0)=0 "
                   "AND json_extract(member.value,'$.owner')=workshop_tasks.owner "
                   "AND json_extract(member.value,'$.lease_until')>=?)")


def mark_writing(history, task, owner, revision=None):
    """The holder has started a write. A lease that lapses before it finishes is outcome unknown."""
    def writing(expected):
        return ("UPDATE workshop_tasks SET write_open=1, updated_at=?, revision=revision+1 "
                "WHERE id=? AND revision=? AND status='claimed'",
                (_now(), task, expected))
    return _update(history, task, revision, writing, holder=owner)


def _text(value, label, maximum):
    if type(value) is not str or not value.strip() or "\0" in value or len(value.encode("utf-8")) > maximum:
        raise ValueError("Invalid task " + label)
    return value.strip()


def rename(history, task, title, revision=None):
    """The founder edits the task name. The row keeps the full text; the list shows the short name."""
    text = _text(title, "title", 2000)
    with history._transaction(write=True):
        row = get(history, task)
        if row is None:
            raise TaskNotFound(task)
        if revision is not None and int(revision) != row["revision"]:
            raise TaskConflict(task, revision)
        if text != row["title"]:
            def statement(expected):
                return ("UPDATE workshop_tasks SET title=?, updated_at=?, revision=revision+1 WHERE id=? AND revision=?",
                        (text, _now(), task, expected))
            if not _update(history, task, revision, statement):
                raise TaskConflict(task, revision if revision is not None else row["revision"])
        if row.get('session_path'):
            from . import canvas_documents
            def retitle(document):
                document['title'] = short_title(text)
                return []
            canvas_documents.edit(row['session_path'], 'You', 'rename task', retitle, solve_changed=False)
    return {"ok": True, "id": task, "title": short_title(text), "description": text}


def create(history, title, creator, *, agent='', workspace='', zoom=1):
    task = uuid4().hex
    title = _text(title, "title", 2000)
    path = _start_session(task, title, zoom, agent=agent, workspace=workspace)
    project = ''
    if workspace:
        from .workspace_roots_catalogue import read_registered_roots
        roots, _ = read_registered_roots()
        project = (roots.get(workspace) or {}).get('label') or workspace
    _write(history, "INSERT INTO workshop_tasks(id,title,status,created_by,created_at,updated_at,session_path,project) "
           "VALUES(?,?,'open',?,?,?,?,?)", (task, title, creator, _now(), _now(), path, project or None))
    return get(history, task)


def _members_now(history, task):
    return (_locked(history, task) or {"members": []})["members"]


def claim(history, task, owner, label, lease_seconds=None, revision=None):
    """Join the session as a member, or renew this member's lease. Any agent may join; done stays done."""
    lease_seconds = TASKS_NODE['params']['lease_seconds'] if lease_seconds is None else lease_seconds
    if type(lease_seconds) is not int or not 30 <= lease_seconds <= 86400:
        raise ValueError("Lease must be 30 to 86400 seconds")
    now = time.time()
    _settle_lapsed(history)

    def statement(expected):
        members = _members_now(history, task)
        mine = next((m for m in members if m["owner"] == owner), None)
        if mine is None:
            mine = {"owner": owner}
            members.append(mine)
        mine.update(label=label, lease_until=now + lease_seconds, seen=now)
        mine.pop("left", None)
        _, _, _, lease = _seat(members, now)
        return ("UPDATE workshop_tasks SET status='claimed', owner=?, owner_label=?, lease_until=?, members=?, "
                "outcome=NULL, write_open=0, updated_at=?, revision=revision+1 WHERE id=? AND revision=? "
                "AND status!='done'",
                (owner, label, lease, json.dumps(members), _now(), task, expected))
    return _update(history, task, revision, statement)


def _leave(history, task, owner, now):
    """This member's lease ends; it stays listed. The latest live member, if any, keeps the session."""
    members = _members_now(history, task)
    for member in members:
        if member["owner"] == owner:
            member["lease_until"] = None
            member["left"] = True
    return members, _seat(members, now)


def release(history, task, owner, revision=None):
    def statement(expected):
        members, (status, holder, label, lease) = _leave(history, task, owner, time.time())
        return ("UPDATE workshop_tasks SET status=?, owner=?, owner_label=?, lease_until=?, members=?, "
                "updated_at=?, revision=revision+1 WHERE id=? AND revision=? AND status='claimed'",
                (status, holder, label, lease, json.dumps(members), _now(), task, expected))
    return _update(history, task, revision, statement, holder=owner)


def complete(history, task, owner, result="", revision=None):
    """A member finishes. The session is done when no other member still holds a live lease; else it stays open."""
    _settle_lapsed(history)

    def statement(expected):
        members, (status, holder, label, lease) = _leave(history, task, owner, time.time())
        if status == "claimed":
            return ("UPDATE workshop_tasks SET owner=?, owner_label=?, lease_until=?, members=?, updated_at=?, "
                    "revision=revision+1 WHERE id=? AND revision=? AND status='claimed'",
                    (holder, label, lease, json.dumps(members), _now(), task, expected))
        return ("UPDATE workshop_tasks SET status='done', lease_until=NULL, write_open=0, result=?, members=?, updated_at=?, "
                "revision=revision+1 WHERE id=? AND revision=? AND status='claimed'",
                (result, json.dumps(members), _now(), task, expected))
    won = _update(history, task, revision, statement, holder=owner)
    row = get(history, task)
    reconciled = bool(row and row['status'] == 'done' and row['owner'] == owner and row['result'] == result)
    if won or reconciled:
        label = next((m.get('label') for m in row['members'] if m['owner'] == owner), None)
        record_step(history, task, owner, label or row['owner_label'] or owner, None, 'done', result)
    return won or reconciled


def begin_run(history, task, owner, label, revision=None, lease_seconds=None):
    """Start one agent run when a slot is free. The next one waits with LIMIT_REACHED."""
    lease_seconds = TASKS_NODE['params']['lease_seconds'] if lease_seconds is None else lease_seconds
    if type(lease_seconds) is not int or not 30 <= lease_seconds <= 86400:
        raise ValueError("Lease must be 30 to 86400 seconds")
    cap = TASKS_NODE['params']['max_runs']
    if type(cap) is not int or cap < 1:
        raise ValueError("Capacity must be a positive number of runs")
    _settle_lapsed(history)
    now = time.time()
    over_cap = False
    with history._transaction(write=True):
        row = _locked(history, task)
        if row is None:
            raise TaskNotFound(task)
        if revision is not None and int(revision) != row["revision"]:
            raise TaskConflict(task, revision)
        expected = row["revision"] if revision is None else int(revision)
        running = history._db.execute(
            "SELECT COUNT(*) FROM workshop_tasks WHERE status='claimed' AND lease_until IS NOT NULL "
            "AND lease_until>=? AND id!=?", (now, task)).fetchone()[0]
        holds = row["status"] == "claimed" and row["owner"] == owner
        if running >= cap and not holds:
            changed = history._db.execute(
                "UPDATE workshop_tasks SET capacity='LIMIT_REACHED', updated_at=?, revision=revision+1 "
                "WHERE id=? AND revision=? AND status!='done'",
                (_now(), task, expected)).rowcount == 1
            if not changed:
                raise TaskConflict(task, expected)
            over_cap = True
        else:
            changed = history._db.execute(
                "UPDATE workshop_tasks SET status='claimed', owner=?, owner_label=?, lease_until=?, "
                "outcome=NULL, write_open=0, capacity=NULL, updated_at=?, revision=revision+1 "
                "WHERE id=? AND revision=? AND status!='done' AND (owner IS NULL OR owner=?)",
                (owner, label, now + lease_seconds, _now(), task, expected, owner)).rowcount == 1
            if not changed:
                raise TaskConflict(task, expected)
    if over_cap:
        raise TaskLimitReached(task)
    return True


def archive(history, task, revision=None):
    """Close a task so it leaves the active list. Its .archhub file stays readable."""
    if get(history, task) is None:
        raise TaskNotFound(task)
    def statement(expected):
        return ("UPDATE workshop_tasks SET status='done', archived=1, lease_until=NULL, updated_at=?, "
                "revision=revision+1 WHERE id=? AND revision=?",
                (_now(), task, expected))
    return _update(history, task, revision, statement)


def _declared_id(owner):
    """The id older builds gave one agent's declared row. Kept to read those rows; new work never uses it."""
    return "declared-" + sha256(("agent\0" + owner).encode()).hexdigest()[:32]


SESSION_PREFIX = "session-"


def _open_session(history, task):
    row = get(history, task) if task else None
    return row if row and row["status"] != "done" and not row.get("archived") else None


_OPEN_WORK = "status!='done' AND IFNULL(archived,0)=0 AND id NOT LIKE 'declared-%'"
_MEMBER = ("EXISTS (SELECT 1 FROM json_each(CASE WHEN json_valid(members) THEN members ELSE '[]' END) "
           "WHERE json_extract(value,'$.owner')=?)")


_LIVE_MEMBER = ("EXISTS (SELECT 1 FROM json_each(CASE WHEN json_valid(members) THEN members ELSE '[]' END) "
                "WHERE json_extract(value,'$.owner')=? AND json_extract(value,'$.lease_until')>=?)")


def _own_membership(history, owner, project):
    """The open session this agent most recently worked in, in this project, unless it left it."""
    found = history._db.execute(
        "SELECT work.id FROM workshop_tasks AS work, json_each(CASE WHEN json_valid(work.members) THEN work.members "
        "ELSE '[]' END) AS member WHERE work.status!='done' AND IFNULL(work.archived,0)=0 AND work.id NOT LIKE 'declared-%' "
        "AND IFNULL(work.project,'')=? AND json_extract(member.value,'$.owner')=? "
        "AND IFNULL(json_extract(member.value,'$.left'),0)=0 "
        "ORDER BY IFNULL(json_extract(member.value,'$.seen'),0) DESC LIMIT 1", (project or "", owner)).fetchone()
    return found[0] if found else None


def _session_for(history, owner, project, request, inherited, hours, kind="refresh"):
    """The session a declare without a session id joins, or None. Never a guess. The caller states the kind.

    With a request: the agent's own session of that project and request, the starter's session when it is
    the same work, else in a registered project the one open session started for that request.
    Without a request, by kind: "refresh" (Stop, per-prompt, connector refresh) only renews the work the
    agent already has (live, else its most recent membership in this project); "start" (the session-start
    hook) may also take the starter's session or the single open session of the project active in the
    last `hours` that has no request; "alias" (the connector's startup alias) touches nothing.
    Rows from older builds (declared-*) are never joined.
    """
    now = time.time()
    if not request:
        if kind == "alias":
            return None
        mine = history._db.execute("SELECT id FROM workshop_tasks WHERE " + _OPEN_WORK + " AND " + _LIVE_MEMBER +
                                   " ORDER BY updated_at DESC LIMIT 1", (owner, now)).fetchone()
        if mine:
            return mine[0]
        mine = _own_membership(history, owner, project)
        if mine or kind != "start":
            return mine
    else:
        mine = history._db.execute("SELECT id FROM workshop_tasks WHERE " + _OPEN_WORK + " AND IFNULL(project,'')=? "
                                   "AND purpose=? AND " + _MEMBER + " ORDER BY updated_at DESC LIMIT 1",
                                   (project or "", request, owner)).fetchone()
        if mine:
            return mine[0]
    parent = _open_session(history, inherited)
    if parent and (parent.get("project") or "") == (project or "") and (
            not request or request in (parent.get("purpose"), parent["id"])):
        return inherited
    if not project:
        return None
    if request:
        found = history._db.execute("SELECT id FROM workshop_tasks WHERE " + _OPEN_WORK + " AND project=? "
                                    "AND purpose=? LIMIT 2", (project, request)).fetchall()
        return found[0][0] if len(found) == 1 else None
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    found = history._db.execute("SELECT id, purpose FROM workshop_tasks WHERE " + _OPEN_WORK + " AND project=? "
                                "AND updated_at>=? LIMIT 2", (project, cutoff)).fetchall()
    return found[0][0] if len(found) == 1 and not found[0][1] else None


def _leave_other_sessions(history, task, owner):
    """An agent that moves to another piece of work ends its lease in the one it left; it stays listed there."""
    held = history._db.execute("SELECT id FROM workshop_tasks WHERE " + _OPEN_WORK + " AND id!=? AND status='claimed' AND "
                               + _MEMBER, (task, owner)).fetchall()
    for (other,) in held:
        release(history, other, owner)


def handover(history, task):
    """What a joining agent needs to continue: the work, its file, the plan and the last handover note."""
    row = get(history, task)
    context = _session_context(row.get("session_path")) if row else {}
    return {"task": task, "title": short_title(row["title"]) if row else "", "path": (row or {}).get("session_path") or "",
            "plan": list(context.get("plan") or []), "handover": dict(context.get("handover") or {})}


_NO_REQUEST = {"", "unassigned", "none", "n/a", "-"}


def _request_of(request_id):
    """A placeholder request id (unassigned, none, n/a, -, empty) is no request."""
    return "" if str(request_id or "").strip().casefold() in _NO_REQUEST else request_id


def declared(history, root, request_id, title, status, owner, label, project="", inherited="", changed=True, kind="refresh"):
    """An agent's declare joins one session (a piece of work) and returns its task id, or False.

    A declare with a request (a task id, a founder or plan request id) is a real step: it joins that work
    or starts it and records the step. A declare without one (a start, Stop or refresh) only keeps or
    joins work that already exists; it never creates a row or file, never records a step, and a "done"
    without a request changes nothing. A re-declare that changes nothing only renews the lease.
    """
    title = _text(title, "title", 2000)
    request = _request_of(request_id)
    if not request and (status == "done" or kind == "alias"):
        return False
    task = request if request and get(history, request) else ""
    if not task:
        with history._transaction(write=True):
            _ensure(history)
            task = _session_for(history, owner, project, request, inherited, TASKS_NODE["params"]["stale_hours"], kind)
            if not task:
                if not request or status == "done":
                    return False
                task = SESSION_PREFIX + uuid4().hex
                history._db.execute("INSERT INTO workshop_tasks(id,title,status,created_by,created_at,updated_at,purpose,project) "
                                    "VALUES(?,?,'open',?,?,?,?,?)", (task, title, label, _now(), _now(), request, project or None))
    if status == 'done':
        row = get(history, task)
        won = complete(history, task, owner)
        if won:
            result = (row.get('result') or '') if row['owner'] == owner else ''
            record_step(history, task, owner, label, title, status, result, request=request_id)
        return task if won else False
    held = get(history, task)
    already = bool(held) and any(m["owner"] == owner for m in _live(held.get("members") or []))
    _leave_other_sessions(history, task, owner)
    won = claim(history, task, owner, label)
    if request and (changed or not already):
        record_step(history, task, owner, label, title, status, request=request_id)
    return task if won else False


def record_step(history, task, owner, label, title, status, result="", request=""):
    """Project the existing declaration/completion into its task file, without executing it."""
    from . import canvas_documents
    from .workshop_mailbox import latest_agent_message
    row = get(history, task)
    path = row.get('session_path')
    if not path:
        path = _start_session(task, row['title'], purpose=row.get('purpose') or '', generation=row['created_at'])
        for attempt in range(5):
            try:
                _bind_session(history, task, row['revision'], path)
                break
            except (ValueError, TaskConflict):
                # Another agent joined or bound the file at the same moment: use its file, or bind at the new revision.
                row = get(history, task)
                if row.get('session_path'):
                    path = row['session_path']
                    break
                if attempt == 4:
                    raise
    message = latest_agent_message(history, label + ' [' + owner + ']')
    declaration = None
    if history._db.execute("SELECT 1 FROM sqlite_master WHERE name='workshop_declarations'").fetchone():
        declaration = history._db.execute("SELECT json_extract(record,'$.runtime'),json_extract(record,'$.display_name'),record FROM workshop_declarations "
                                         "WHERE json_extract(record,'$.session')=? LIMIT 1", (owner,)).fetchone()
    identity = 'step-' + sha256(owner.encode()).hexdigest()[:24]
    def change(document):
        context = document.get('properties', {}).get('taskContext', {})
        if context.get('task') != task:
            raise ValueError('Session file belongs to another task')
        if row.get('project'):
            context['project'] = row['project']
            if not context.get('workspace'):
                from .workspace_roots_catalogue import read_registered_roots
                roots, _ = read_registered_roots()
                context['workspace'] = next((key for key, value in roots.items() if value.get('label') == row['project']), '')
        steps = [n for n in document['nodes'] if n.get('params', {}).get('workshop_step')]
        node = next((n for n in steps if n['id'] == identity), None)
        if node is None:
            previous = steps[-1] if steps else next((n for n in document['nodes'] if n['id'] == 'start'), None)
            node = {'id': identity, 'type': 'thing.agent', 'title': title or row['title'], 'params': {},
                    'position': {'x': (previous['position']['x'] + 384) if previous else 80, 'y': 80}}
            document['nodes'].append(node)
            if previous:
                document['wires'].append({'id': 'wire-' + identity,
                    'from': {'node': previous['id'], 'socket': 'result' if previous in steps else 'value'},
                    'to': {'node': identity, 'socket': 'task'}})
        if title is not None:
            node['title'] = title
        node['params'].update(workshop_step=True, agent=label, session=owner, status=status,
                              instructions=node['title'], result=result)
        if declaration:
            node['params']['vendor'] = declaration[0] or ''
            node['params']['display_name'] = declaration[1] or label
        if message:
            node['params'].update(message_id=message[0], last_message=message[1], message_at=message[2])
        from .agent_work import project, redact, _tool
        from .agent_status import read_transcript
        import json
        detail = json.loads(declaration[2]) if declaration else {}
        try:
            transcript = read_transcript(detail.get('runtime'), detail.get('native_session_id'))
        except (OSError, ValueError):
            transcript = {}
        calls = transcript.get('calls', [])
        selected, belongs = [], False
        for call in calls:
            if _tool(call) == 'declare':
                called = call.get('input', {}).get('request_id') if isinstance(call.get('input'), dict) else None
                if called:
                    # The agent's own purpose counts once it joined this session with it.
                    belongs = called in (task, row.get('purpose'), request or None) or (
                        detail.get('work') == task and called == detail.get('request_id'))
            if belongs:
                selected.append(call)
        transcript = {**transcript, 'calls': selected}
        detail['task_id'] = task
        # A session owns the real tool steps; old no-detail sessions keep their existing card.
        project(document, node, detail, transcript)
        foreign = {n['id'] for n in document['nodes'] if n.get('agentWork', {}).get('role') == 'step'
                   and n['agentWork'].get('owner') == node['id'] and n['agentWork'].get('task') != task}
        if foreign:
            from .session_files import checkpoint_document
            checkpoint_document(document, 'Before separating task steps')
            document['nodes'] = [n for n in document['nodes'] if n['id'] not in foreign]
            document['wires'] = [w for w in document['wires'] if w['from']['node'] not in foreign and w['to']['node'] not in foreign]
            for group in document['groups']:
                group['nodes'] = [identity for identity in group['nodes'] if identity not in foreign]
            for group in document['nodes']:
                if 'children' in group:
                    group['children'] = [identity for identity in group['children'] if identity not in foreign]
        node['params'] = redact(node['params'])
        node['title'] = redact(node['title'])
        return []
    canvas_documents.edit(path, label, 'agent step ' + status, change, solve_changed=False)


# A token that reads as an id, path, flag or measurement, not as words.
_JARGON = re.compile(r"[=/\\_<>{}`]|\d{3,}|[a-z][A-Z]|^[(\[]|^[A-Z][A-Z0-9]*-?\d|^[a-f0-9]{7,}$")
_TRAILING = {"in", "on", "at", "to", "for", "of", "and", "the", "a", "with", "from", "by"}


def short_title(text, limit=60):
    """A human task name: the first clause of the declared text without id/path tokens, at most `limit` chars."""
    text = re.sub(r"^\s*[A-Z0-9][A-Z0-9-]*:\s+", "", str(text or "").strip())  # a leading lane tag ("WSFIX: ")
    first = re.split(r"(?<=[.;:!?])\s|\n|\s[–—-]\s|\s\(", text, maxsplit=1)[0]
    words = [w for w in first.split() if not _JARGON.search(w)]
    while len(words) > 1 and words[-1].casefold() in _TRAILING:
        words.pop()
    title = " ".join(words).strip(" ,;:.-") or text[:limit]
    return title if len(title) <= limit else title[:limit - 1].rsplit(" ", 1)[0].rstrip(" ,;:.-") + "…"


def _thread_result(history, task):
    """The last Workshop message whose refs name this task. Empty when none was recorded."""
    if not history._db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='messages'").fetchone():
        return ""
    from .workshop_mailbox import ROOM
    found = history._db.execute(
        "SELECT content FROM messages WHERE conversation_id=? "
        "AND EXISTS (SELECT 1 FROM json_each(refs) WHERE value=?) ORDER BY sequence",
        (ROOM, task)).fetchall()
    return str(found[-1][0] or "").strip() if found else ""


def recorded_result(history, row):
    """The result the task stored, or the final reply that names it. Never a stand-in."""
    stored = row.get("result")
    if isinstance(stored, str) and stored.strip():
        return stored
    if row.get("status") != "done":
        return stored
    text = _thread_result(history, row["id"])
    return text if text else (stored if isinstance(stored, str) else "")


def _declaration_task_id(declaration):
    return "declared-" + sha256((declaration["root"] + "\0" + declaration["request_id"]).encode()).hexdigest()[:32]


def _session_context(path):
    """Task-session fields already stored in the task file. A missing file leaves them empty."""
    if not isinstance(path, str) or not path:
        return {}
    try:
        from .session_files import read_document
        document = read_document(path)
        context = _held_context(document)
    except (OSError, ValueError, KeyError, TypeError):
        return {}
    context["sessionTitle"] = document["title"]
    context["fileMessages"] = _file_messages(document)
    return context


def _bound_messages(history, task):
    """Messages whose refs name this task. Traffic addressed only to the owner stays out."""
    from .workshop_mailbox import DELIVERY_AUTHOR, DELIVERY_CATEGORY, ROOM
    if not history._db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='messages'").fetchone():
        return []
    return [{"id": row[0], "who": row[1], "text": row[2]} for row in history._db.execute(
        "SELECT id, author, content FROM messages WHERE conversation_id=? AND author!=? AND category!=? "
        "AND EXISTS (SELECT 1 FROM json_each(refs) WHERE value=?) ORDER BY sequence",
        (ROOM, DELIVERY_AUTHOR, DELIVERY_CATEGORY, task))]


def _is_stale(row, declarations, hours):
    """A declared task whose owner has not been live for `hours`, or a session with no live member and no
    activity for `hours` that is not waiting for the founder. Never deleted or archived; Continue still works."""
    if str(row["id"]).startswith(SESSION_PREFIX) and row["status"] != "done":
        if _live(row.get("members") or []):
            return False
        if any(item.get("work") == row["id"] and item.get("current") and item.get("status") == "blocked"
               for item in declarations):
            return False
        seen = datetime.fromisoformat(row.get("updated_at") or "1970-01-01T00:00:00+00:00")
        seen = seen if seen.tzinfo else seen.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) - seen >= timedelta(hours=hours)
    if not str(row["id"]).startswith("declared-") or row["status"] == "done":
        return False
    mine = [item for item in declarations if item.get("session") == row.get("owner")]
    if any(item.get("current") for item in mine):
        return False
    latest = max([row.get("updated_at") or ""] + [item.get("updated_at") or "" for item in mine])
    if not latest:
        return True
    seen = datetime.fromisoformat(latest)
    if seen.tzinfo is None:
        seen = seen.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - seen >= timedelta(hours=hours)


def _summary(title, status, result):
    """One plain line each: what it is, state, latest result, next step."""
    state = {"WIP": "In progress", "PLANNED": "Planned, not started", "DONE": "Done",
             "IN REVIEW": "Needs you", "stale": "Stale, not in progress"}.get(status, status)
    latest = (result or "").split("\n", 1)[0].strip() or "No result yet"
    nxt = {"stale": "Still searchable; nobody is working on it", "DONE": "Nothing further",
           "PLANNED": "Not started", "IN REVIEW": "Waiting for a decision"}.get(status, "Keep going")
    return "\n".join((short_title(title) or "Untitled task", state, latest[:200], nxt))


def _declaration_for(row, declarations):
    """The declaration this task row projects: the old root id, or this agent's current purpose."""
    matched = []
    for item in declarations:
        if item.get("work") == row["id"]:
            matched.append(item)
        elif item.get("root") and item.get("request_id") and _declaration_task_id(item) == row["id"]:
            matched.append(item)
        elif not item.get("work") and row["id"].startswith(SESSION_PREFIX) and item.get("session") == row.get("owner"):
            matched.append(item)
        elif item.get("session") and _declared_id(item["session"]) == row["id"]:
            if not row.get("purpose") or item.get("request_id") in (None, "", row.get("purpose")):
                matched.append(item)
    current = [item for item in matched if item.get("current")]
    return (current or matched or [None])[0]


def column(history, project=None, stale_hours=None, *, include_archived=False):
    """Studio Work rows. Declaration fields fill the view. A project shows only its own tasks.
    Stale declared work leaves in-progress."""
    from .workshop_mailbox import read_declarations
    hours = TASKS_NODE["params"]["stale_hours"] if stale_hours is None else stale_hours
    declarations = read_declarations(history._db, include_archived=True)
    fold_declarations(history, declarations)
    live = {}
    for item in declarations:
        if not item.get("current"):
            continue
        if item.get("session"):
            live[_declared_id(item["session"])] = item["status"]
        if item.get("root") and item.get("request_id"):
            live[_declaration_task_id(item)] = item["status"]
        if item.get("work"):
            live[item["work"]] = "blocked" if "blocked" in (item["status"], live.get(item["work"])) else item["status"]
    def state(row):
        if _is_stale(row, declarations, hours):
            return "stale"
        if row["status"] == "done":
            return "DONE"
        if live.get(row["id"]) == "blocked":
            return "IN REVIEW"
        if live.get(row["id"]) == "working" or (row["status"] == "claimed" and not row["lease_expired"]):
            return "WIP"
        return "PLANNED"
    current = _current_session()
    built = []
    listed = rows(history, include_archived=include_archived)
    working = {m["owner"] for row in listed if not row["id"].startswith("declared-") and row["status"] != "done"
               and not row.get("archived") for m in _live(row.get("members") or [])}
    for row in listed:
        if project and row.get("project") != project:
            continue
        if row["id"].startswith("declared-") and row.get("owner") in working:
            continue
        declaration = _declaration_for(row, declarations)
        session = _session_context(row.get("session_path"))
        paths = [item for item in ((declaration or {}).get("paths") or []) if isinstance(item, str)]
        shown = "ARCHIVED" if row.get("archived") else state(row)
        result = recorded_result(history, row)
        waiting = "limit reached" if row.get("capacity") == "LIMIT_REACHED" and shown == "PLANNED" else (
            row.get("outcome") if shown == "PLANNED" and row.get("outcome") in ("interrupted", "unknown") else "")
        bound = _bound_messages(history, row["id"])
        owner = row["owner_label"] if row["id"] in live or not row["lease_expired"] else None
        agents = [item for item in session.get("agents") or [] if isinstance(item, str) and item]
        label = owner or ((declaration or {}).get("agent") if declaration else None)
        if isinstance(label, str) and label and label not in agents:
            agents.insert(0, label)
        plan = list(session.get("plan") or [])
        if not plan and (declaration or owner or shown in ("WIP", "IN REVIEW", "DONE")):
            plan = [{"title": short_title(row["title"]), "status": {"WIP": "working", "IN REVIEW": "blocked", "DONE": "done"}.get(shown, "")}]
        activity = list(session.get("activity") or [])
        if not activity and (declaration or row.get("result") or owner):
            activity = [{"id": row["id"], "status": shown, "output": row.get("result") or ""}]
        built.append({'id': row['id'], 'title': short_title(row['title']), 'description': row['title'],
             'owner': owner, 'revision': row.get('revision') or 0,
             'status': shown, 'rowState': waiting, 'outcome': row.get('outcome') or '',
             'capacity': row.get('capacity') or '',
             'stale': shown == "stale", 'result': result, 'project': row.get('project') or '',
             'summary': _summary(row['title'], shown, result),
             'messages': [], 'fileMessages': list(session.get("fileMessages") or []), 'agentLog': bound, 'steps': [], 'reviews': [], 'queuedMessages': [],
             'declarations': [declaration] if declaration else [],
             'scope': session.get("scope") or (" · ".join(paths) if paths else ""),
             'rules': list(session.get("rules") or []),
             'pinnedMessages': list(session.get('pinnedMessages') or []),
             'homePinned': session.get('homePinned') is True, 'workspace': session.get('workspace') or '',
             'agents': agents, 'folders': list(session.get("folders") or []) or paths,
             # Every agent on this piece of work, lead (first to join) first; live while its lease runs.
             'members': [{'name': m.get('label') or m['owner'], 'live': (m.get('lease_until') or 0) >= time.time()}
                         for m in row.get('members') or []],
             'references': list(session.get("references") or []),
             'session': row.get("session_path") or ((declaration or {}).get("session") if declaration else "") or "",
             'plan': plan, 'planInferred': not bool(session.get('plan')), 'handover': session.get('handover') or {}, 'sessionTitle': session.get('sessionTitle') or short_title(row['title']), 'progress': session.get("progress") or {},
             'checkpoints': list(session.get("checkpoints") or []),
             'workflow': list(session.get("workflow") or []), 'activity': activity,
             'updated_at': row['updated_at'], 'sessionPath': row.get('session_path'),
             'sessionOpen': bool(row.get('session_path') and row['session_path'] == current),
             'inProgress': shown in ("WIP", "IN REVIEW")})
    return built


def fold_declarations(history, declarations):
    """Hide superseded declare rows using only the reversible archive flag."""
    held = rows(history, settle=False)
    for declaration in declarations:
        owner = declaration.get('session')
        if not owner:
            continue
        canonical = _declared_id(owner)
        legacy = {_declaration_task_id(d) for d in declarations if d.get('session') == owner and d.get('root') and d.get('request_id')}
        candidates = [r for r in held if r['id'] == canonical or r['id'] in legacy or
                      (r['id'].startswith('declared-') and r.get('owner') == owner)]
        if not candidates:
            continue
        keep = next((r['id'] for r in candidates if r['id'] == canonical),
                    max(candidates, key=lambda r: (not r['archived'], r['updated_at'], r['created_at'], r['id']))['id'])
        for row in candidates:
            if row['id'] != keep and not row['archived']:
                _write(history, 'UPDATE workshop_tasks SET archived=1, revision=revision+1 WHERE id=? AND archived=0', (row['id'],))


def refresh_steps(path):
    """The existing head/read poll reconciles native calls that arrive after declare()."""
    from .workshop_mailbox import application_history
    with application_history() as history:
        task = next((r for r in rows(history, settle=False) if r.get('session_path') == str(path)), None)
        if not task:
            return
        from .session_files import read_document
        document = read_document(path)
        for node in document['nodes']:
            if node.get('params', {}).get('workshop_step'):
                p = node['params']
                record_step(history, task['id'], p['session'], p['agent'], None, p['status'], p.get('result', ''))


def set_status(history, task, status, revision=None):
    """The founder's board move: PLANNED frees the task, DONE closes it, whoever holds it."""
    if status == "PLANNED":
        def planned(expected):
            return ("UPDATE workshop_tasks SET status='open', owner=NULL, owner_label=NULL, "
                    "lease_until=NULL, updated_at=?, revision=revision+1 WHERE id=? AND revision=?",
                    (_now(), task, expected))
        return _update(history, task, revision, planned)
    if status == "DONE":
        def finished(expected):
            return ("UPDATE workshop_tasks SET status='done', lease_until=NULL, updated_at=?, "
                    "revision=revision+1 WHERE id=? AND revision=?",
                    (_now(), task, expected))
        return _update(history, task, revision, finished)
    raise ValueError("An agent claims a task; the board sets PLANNED or DONE")


COLUMNS = ("id", "title", "status", "owner", "owner_label", "lease_until", "result",
           "created_by", "created_at", "updated_at", "session_path", "archived", "purpose", "project",
           "revision", "outcome", "write_open", "capacity", "members")


def rows(history, task=None, *, include_archived=True, settle=True):
    if not history._db.execute("SELECT 1 FROM sqlite_master WHERE name='workshop_tasks'").fetchone():
        return []
    if settle:
        _settle_lapsed(history)
    _ensure(history)
    now = time.time()
    # A lookup by id still finds an archived task. A list hides it unless asked.
    show = 1 if include_archived or task is not None else 0
    found = [dict(zip(COLUMNS, row)) for row in history._db.execute(
        "SELECT " + ",".join(COLUMNS) + " FROM workshop_tasks WHERE (? IS NULL OR id=?) "
        "AND (? OR IFNULL(archived,0)=0) ORDER BY created_at DESC LIMIT 500", (task, task, show))]
    for row in found:
        row["lease_expired"] = row["status"] == "claimed" and row["lease_until"] < now
        row["members"] = _member_list(row["members"], row["owner"], row["owner_label"], row["lease_until"])
    return found


def get(history, task):
    return next(iter(rows(history, task)), None)


def _current_session():
    """The file the founder has open. SessionFiles is the only owner of that choice."""
    from .session_files import SessionFiles
    try:
        return SessionFiles().current_path()
    except (OSError, ValueError, KeyError, TypeError):
        return ""


def _held_context(document):
    props = document.get("properties") if isinstance(document.get("properties"), dict) else {}
    held = props.get("taskContext") if isinstance(props.get("taskContext"), dict) else {}
    nodes = document.get("nodes") or []
    agents = list(held["agents"]) if isinstance(held.get("agents"), list) else []
    for node in nodes:
        if node.get("type") == "thing.agent":
            name = str((node.get("params") or {}).get("agent") or ('' if node.get('fixed') else node.get("title")) or "")
            if name and name not in agents:
                agents.append(name)
    return {
        "scope": "" if held.get("scope") == document["id"] else (held.get("scope") or ""),
        "rules": held["rules"] if isinstance(held.get("rules"), list) else [],
        "pinnedMessages": list(held.get('pinnedMessages') or []),
        "workspace": held.get('workspace') or '',
        "homePinned": held.get('homePinned') is True,
        "agents": agents,
        "plan": held["plan"] if isinstance(held.get("plan"), list) else [],
        "handover": held["handover"] if isinstance(held.get("handover"), dict) else {},
        "progress": held["progress"] if isinstance(held.get("progress"), dict) else {},
        "workflow": [{"id": node["id"], "type": node.get("type", ""), "title": node.get("title", "")} for node in nodes],
        "parameters": [{"id": node["id"], "params": node.get("params") or {}} for node in nodes],
        "activity": [{"id": node["id"], "status": node["result"].get("status", ""), "output": node["result"].get("output")}
                     for node in nodes if isinstance(node.get("result"), dict)],
        "folders": list(held["folders"]) if isinstance(held.get("folders"), list) else [],
        "references": list(held["references"]) if isinstance(held.get("references"), list) else [],
        "checkpoints": [{key: row[key] for key in ("id", "title", "at")} for row in props.get("checkpoints", [])],
    }


_TASK_ROLE = "task"


def _task_message(note):
    """A task chat line is a note marked role task. Canvas annotations are not."""
    return isinstance(note, dict) and note.get("role") == _TASK_ROLE


def _file_messages(document):
    found = []
    for index, note in enumerate(document.get("notes") or []):
        if not _task_message(note) or not isinstance(note.get("text"), str):
            continue
        found.append({"id": note["id"] if isinstance(note.get("id"), str) and note["id"] else "note-%d" % index,
                      "role": _TASK_ROLE,
                      "who": note["who"] if isinstance(note.get("who"), str) and note["who"] else "Agent",
                      "text": note["text"]})
    return found


def _view(task, path, document):
    return {"id": document["id"], "path": path, "taskId": task, "messages": _file_messages(document), **_held_context(document)}


def _stamp(path, task, document):
    """Record which task this file belongs to. Scope, rules, agents, plan and progress already in it stay."""
    from .session_files import write_document
    props = dict(document.get("properties") or {})
    held = dict(props.get("taskContext") or {})
    held["task"] = task
    held.setdefault("scope", "")
    props["taskContext"] = held
    document["properties"] = props
    write_document(path, document)
    return document


def _show(task, path, document, *, select=True):
    """Remember the file. Only an explicit open moves the canvas the founder has selected."""
    from .session_files import SessionFiles
    files = SessionFiles()
    files.remember(path, document)
    if select:
        files._current(document["id"], path)
    return _view(task, str(path), document)


def _bind_session(history, task, revision, target):
    def statement(expected, target=target):
        return ("UPDATE workshop_tasks SET session_path=?, updated_at=?, revision=revision+1 "
                "WHERE id=? AND revision=? AND session_path IS NULL",
                (target, _now(), task, expected))
    if not _update(history, task, revision, statement):
        raise ValueError("Task already has a session file")


def session_filename(task):
    """Legacy task ids may contain characters Windows cannot use in a filename."""
    safe = re.fullmatch(r'[A-Za-z0-9_-]{1,128}', task) and not re.fullmatch(r'CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9]', task, re.I)
    return (task if safe else 'task-' + sha256(task.encode()).hexdigest()) + '.archhub'


def _start_session(task, title, zoom=1, *, purpose='', generation='', agent='', workspace=''):
    from . import canvas_documents
    from .session_files import document_path, sessions_directory
    directory = sessions_directory()
    identity = 'task-' + sha256((task + ('\0' + purpose + '\0' + generation if purpose else '')).encode()).hexdigest()
    path = directory / session_filename(identity if purpose else task)
    if not path.exists():
        path = document_path(directory, {'id': identity, 'title': title})
    creating = not path.exists()
    def start(document):
        context = document.setdefault('properties', {}).setdefault('taskContext', {})
        if context.get('task', task) != task:
            raise ValueError('Session file belongs to another task')
        context['task'] = task
        if creating:
            document['id'] = identity
        if not document['nodes']:
            document['viewport']['zoom'] = zoom
            context.update(workspace=workspace, agents=[agent] if agent else [])
            fixed = [('start', 'thing.session', 'Session', {'value': title, 'workspace': workspace}, 80, 80),
                     ('fixed-agent', 'thing.agent', agent or 'No agent yet', {'agent': agent, 'reference': True}, -220, 40),
                     ('fixed-you', 'thing.you', 'You', {}, -220, 215),
                     ('fixed-workshop', 'thing.workshop', 'Workshop', {'thread': task}, -220, 395)]
            for node_id, kind, label, params, x, y in fixed:
                ports = {'source': [{'id': 'value' if node_id == 'start' else 'agent' if kind == 'thing.agent' else 'profile' if kind == 'thing.you' else 'rules',
                                     'type': 'string' if node_id in ('start', 'fixed-agent') else 'list' if kind == 'thing.workshop' else 'any'}],
                         'target': [{'id': 'value', 'type': 'any'}, {'id': 'agent', 'type': 'string'}, {'id': 'profile', 'type': 'any'}, {'id': 'rules', 'type': 'list'}] if node_id == 'start' else []}
                document['nodes'].append({'id': node_id, 'type': kind, 'title': label, 'fixed': True,
                                          'params': params, 'ports': ports, 'position': {'x': x, 'y': y}})
            for node_id, socket in [('fixed-agent', 'agent'), ('fixed-you', 'profile'), ('fixed-workshop', 'rules')]:
                document['wires'].append({'id': 'fixed-' + socket, 'from': {'node': node_id, 'socket': socket},
                                          'to': {'node': 'start', 'socket': socket}})
        return []
    canvas_documents.edit(path, 'Workshop', 'create task workflow', start,
                          create_title=title, solve_changed=False)
    return str(path)


def backfill_sessions(history):
    """Prepare files without a mailbox write lock, then bind all missing rows atomically."""
    _ensure(history)
    missing = history._db.execute(
        "SELECT id,title,purpose,created_at FROM workshop_tasks WHERE session_path IS NULL OR trim(session_path)=''"
    ).fetchall()
    prepared = [(task, _start_session(task, title, purpose=purpose or '', generation=created)) for task, title, purpose, created in missing]
    if not prepared:
        return 0
    changed = 0
    with history._transaction(write=True):
        for task, path in prepared:
            changed += history._db.execute(
                "UPDATE workshop_tasks SET session_path=?, revision=revision+1 WHERE id=? "
                "AND (session_path IS NULL OR trim(session_path)='')", (path, task)).rowcount
    return changed


def relocate_sessions(state_dir, moved):
    """Relocate bindings in one owner transaction, preserving task and document identity."""
    from pathlib import Path
    from .workshop_mailbox import application_history
    database = Path(state_dir) / 'workshop/messages.sqlite3'
    if not database.exists():
        return
    with application_history(database=database) as history, history._transaction(write=True):
        if not history._db.execute("SELECT 1 FROM sqlite_master WHERE name='workshop_tasks'").fetchone():
            return
        _ensure(history)
        for old, new in moved:
            history._db.execute("UPDATE workshop_tasks SET session_path=?, updated_at=?, revision=revision+1 "
                                "WHERE session_path=?", (str(new), _now(), str(old)))


def open_session(history, task, path=None, *, select=True, zoom=1):
    """Open this task's own .archhub file. A first path binds it; a later open reads that same file."""
    from .session_files import local_path, read_document, sessions_directory
    sessions_directory()
    row = get(history, task)
    if row is None:
        raise ValueError("No such Workshop task")
    bound = row.get("session_path")
    if bound:
        return _show(task, bound, read_document(bound), select=select)
    if path is not None:
        target = str(local_path(path))
        holder = history._db.execute("SELECT id FROM workshop_tasks WHERE session_path=? AND id!=?", (target, task)).fetchone()
        if holder:
            raise ValueError("Session file belongs to another task")
        document = read_document(target)
        document = _stamp(target, task, document)
        _bind_session(history, task, row.get("revision"), target)
        return _show(task, target, document, select=select)
    target = _start_session(task, row['title'], zoom, purpose=row.get('purpose') or '', generation=row['created_at'])
    document = read_document(target)
    _bind_session(history, task, row.get("revision"), target)
    return _show(task, target, document, select=select)


def checkpoint_session(history, task, identity=None, label=None):
    """Checkpoint the task's existing session through the document owner."""
    from .session_files import checkpoint, restore_checkpoint
    view = open_session(history, task, select=False)
    if identity is None:
        return checkpoint(view["path"], label)
    document = restore_checkpoint(view["path"], identity)
    return _show(task, view["path"], document, select=False)


def pin_message(history, task, message, pinned):
    """Pin a reference to an existing task message, without copying its content."""
    from . import canvas_documents
    from .session_files import read_document
    if type(pinned) is not bool or type(message) is not str:
        raise ValueError('Choose a task message and pin state.')
    row = get(history, task)
    if not row:
        raise ValueError('No such Workshop task')
    path = row['session_path']
    bound = {item['id'] for item in _bound_messages(history, task)}
    def change(document):
        if message not in bound | {item['id'] for item in _file_messages(document)}:
            raise ValueError('That message does not belong to this task.')
        context = document.setdefault('properties', {}).setdefault('taskContext', {})
        held = [identity for identity in context.get('pinnedMessages', []) if identity != message]
        if pinned:
            if len(held) >= 80:
                raise ValueError('Pin at most 80 task messages.')
            held.append(message)
        context['pinnedMessages'] = held
        return []
    canvas_documents.edit(path, 'You', 'pin task message' if pinned else 'unpin task message', change, solve_changed=False)
    return _show(task, path, read_document(path), select=False)


def create_session(history, title, creator="founder", *, select=True, zoom=1, agent='', workspace=''):
    """A new task and the .archhub file that holds its session."""
    if type(agent) is not str or len(agent) > 80 or '\0' in agent:
        raise ValueError('Choose a task agent.')
    if type(workspace) is not str or len(workspace) > 128:
        raise ValueError('Choose a registered task workspace.')
    if workspace:
        from .settings_owner import SettingsOwner
        SettingsOwner(None)._workspace(workspace)
    row = create(history, title, creator, agent=agent, workspace=workspace, zoom=zoom)
    return open_session(history, row["id"], select=select, zoom=zoom)


_SESSION_FIELDS = {"scope", "rules", "agents", "plan", "handover", "progress", "nodes", "parameters", "messages", "folders", "references", "homePinned"}
_HANDOVER = ("done", "next", "results")
# A drive-letter or UNC path; inner folders may hold spaces, the last part ends at a space.
_ABSOLUTE = re.compile(
    r"(?:\b[A-Za-z]:|\\\\[^\\/\s\"'<>|*?:]+)(?:\\[^\\/\n\"'<>|*?:]+)*\\(?:[^\\/\s\"'<>|*?:,](?:(?!\.[A-Za-z0-9]{1,8}\s|[.;)!?]\s)[^\\/\n\"'<>|*?:,])*(?=[.,;)!?](?:\s|$)|[/\\\n]|$)|[^\\/\s\"'<>|*?:]+)"   # C:\a b\c.txt, \\server\share, C:\John Smith
    r"|\b[A-Za-z]:(?:/(?:(?!\.[A-Za-z0-9]{1,8}\s|[.;)!?]\s)[^\\/\n\"'<>|*?:])+)*/(?:[^\\/\s\"'<>|*?:,](?:(?!\.[A-Za-z0-9]{1,8}\s|[.;)!?]\s)[^\\/\n\"'<>|*?:,])*(?=[.,;)!?](?:\s|$)|[/\\\n]|$)|[^\\/\s\"'<>|*?:]+)"      # C:/John Smith/b.txt
    r"|(?<![\w/.~-])/[A-Za-z](?:/(?:(?!\.[A-Za-z0-9]{1,8}\s|[.;)!?]\s)[^/\n\"'<>|*?:])+)*/(?:[^/\s\"'<>|*?:,](?:(?!\.[A-Za-z0-9]{1,8}\s|[.;)!?]\s)[^/\n\"'<>|*?:,])*(?=[.,;)!?](?:\s|$)|[/\n]|$)|[^/\s\"'<>|*?:]+)")   # /c/Users/John Smith/a.txt


def _clean_note(history, row, text):
    """A handover note is shared with any agent: every absolute path becomes relative to the project root
    or is dropped, and environment values and secret-shaped text are removed."""
    import os
    from pathlib import PureWindowsPath
    from .agent_work import redact
    roots = []
    if row.get("project"):
        from .workspace_roots_catalogue import read_registered_roots
        registered, _ = read_registered_roots()
        roots = [PureWindowsPath(item["path"]) for item in registered.values()
                 if (item.get("label") or item.get("root_id")) == row["project"] and item.get("path")]

    def place(match):
        whole = match.group(0)
        path = whole.rstrip(".,;:)")
        found = PureWindowsPath(path[1].upper() + ":" + path[2:]) if path.startswith("/") else PureWindowsPath(path)
        root = next((base for base in roots if found.is_relative_to(base)), None)
        return (found.relative_to(root).as_posix() if root else "[path removed]") + whole[len(path):]
    text = _ABSOLUTE.sub(place, text)
    for value in os.environ.values():
        if len(value) >= 12 and value in text:
            text = text.replace(value, "[removed]")
    return redact(text)


_NODE_TYPES = {"note", "thing.agent"}
_SECRET_NAME = re.compile(r"(^|_)(password|secret|token|api_key|private_key|credential)(_|$)", re.I)


def _short_text(value, label, limit):
    if type(value) is not str or not value.strip() or "\0" in value or len(value) > limit:
        raise ValueError("Invalid task " + label)
    return value.strip()


def _plain(value, depth=0):
    if depth > 4:
        raise ValueError("Task value is too deep")
    if value is None or type(value) is bool or type(value) is str:
        if type(value) is str and (len(value) > 4000 or "\0" in value):
            raise ValueError("Task text is too long")
        return value
    if type(value) is int:
        return value
    if type(value) is float:
        if value != value or abs(value) == float("inf"):
            raise ValueError("Task number must be finite")
        return value
    if type(value) is list:
        if len(value) > 40:
            raise ValueError("Task list is too long")
        return [_plain(item, depth + 1) for item in value]
    if type(value) is dict:
        if len(value) > 40 or any(type(key) is not str or not key or len(key) > 80 for key in value):
            raise ValueError("Task object is too large")
        return {key: _plain(item, depth + 1) for key, item in value.items()}
    raise ValueError("Task value must be text, a number, or a short list")


def _text_list(value, label):
    if type(value) is not list or len(value) > 40:
        raise ValueError("Task " + label + " must be a short list")
    return [_short_text(item, label, 500) for item in value]


def _session_list(value, label):
    if type(value) is not list or len(value) > 40:
        raise ValueError("Task " + label + " must be a short list")
    return [_plain(item) for item in value]


def _merge_params(node, params):
    if type(params) is not dict or len(params) > 40:
        raise ValueError("Node parameters must be a short object")
    cleaned = {}
    for key, value in params.items():
        if type(key) is not str or not key or len(key) > 80 or "\0" in key or _SECRET_NAME.search(key):
            raise ValueError("Parameter name is invalid")
        cleaned[key] = _plain(value)
    node["params"] = {**node.get("params", {}), **cleaned}


def _apply_nodes(document, specs):
    if type(specs) is not list or len(specs) > 40:
        raise ValueError("Task nodes must be a short list")
    nodes = {node["id"]: node for node in document["nodes"]}
    for index, spec in enumerate(specs):
        if type(spec) is not dict or type(spec.get("id")) is not str or not spec["id"] or len(spec["id"]) > 80 or "\0" in spec["id"]:
            raise ValueError("Each node needs an id")
        kind = spec.get("type") or (nodes[spec["id"]]["type"] if spec["id"] in nodes else "note")
        if kind not in _NODE_TYPES:
            raise ValueError("Task node type must be note or thing.agent")
        node = nodes.get(spec["id"])
        if node is None:
            node = {"id": spec["id"], "type": kind, "title": spec.get("title") or spec["id"], "params": {},
                    "position": {"x": 48, "y": 48 + index * 72}}
            if kind == "thing.agent":
                node["params"] = {"agent": spec.get("title") or spec["id"], "instructions": ""}
                node["ports"] = {"source": [{"id": "result", "type": "any"}], "target": [{"id": "task", "type": "any"}]}
            document["nodes"].append(node)
            nodes[spec["id"]] = node
        elif spec.get("type") and node.get("type") != kind:
            raise ValueError("Node type is already set")
        if spec.get("title"):
            node["title"] = _short_text(spec["title"], "node title", 200)
        if "params" in spec:
            _merge_params(node, spec["params"])
        if "result" in spec:
            result = spec["result"]
            if type(result) is not dict:
                raise ValueError("Node result must be an object")
            node["result"] = {"status": _short_text(str(result.get("status") or "Idle"), "result status", 80),
                              "output": _plain(result.get("output")), "error": result.get("error") or ""}
            if type(node["result"]["error"]) is not str or len(node["result"]["error"]) > 500:
                raise ValueError("Node result error must be short text")


def _apply_parameters(document, rows):
    if type(rows) is not list or len(rows) > 40:
        raise ValueError("Parameters must name nodes")
    nodes = {node["id"]: node for node in document["nodes"]}
    for row in rows:
        if type(row) is not dict or row.get("id") not in nodes:
            raise ValueError("Parameter names a node that is not in this task")
        _merge_params(nodes[row["id"]], row.get("params"))


def _apply_messages(document, rows):
    if type(rows) is not list or len(rows) > 80:
        raise ValueError("Task messages must be a short list")
    messages = []
    for index, row in enumerate(rows):
        if type(row) is not dict:
            raise ValueError("Each message needs text")
        text = _short_text(row.get("text"), "message", 4000)
        who = _short_text(row.get("who") or "Agent", "message author", 80)
        note_id = row.get("id") if type(row.get("id")) is str and row["id"] and len(row["id"]) <= 80 else "msg-%d" % index
        messages.append({"id": note_id, "role": _TASK_ROLE, "who": who, "text": text})
    kept = [note for note in (document.get("notes") or []) if not _task_message(note)]
    document["notes"] = kept + messages


def update_session(history, task, values):
    """Write this task's parameters, plan, agents and progress into its .archhub file."""
    from .session_files import read_document
    if type(values) is not dict or set(values) - _SESSION_FIELDS:
        raise ValueError("Unsupported task session fields")
    row = get(history, task)
    if row is None:
        raise ValueError("No such Workshop task")
    if not row.get("session_path"):
        open_session(history, task, select=False)
        row = get(history, task)
    path = row["session_path"]
    from . import canvas_documents
    def change(document):
        props = dict(document.get("properties") or {})
        held = dict(props.get("taskContext") or {})
        if 'homePinned' in values:
            if type(values['homePinned']) is not bool:
                raise ValueError('Choose whether to show this task at the top of Home.')
            held['homePinned'] = values['homePinned']
        if "scope" in values:
            held["scope"] = _short_text(values["scope"], "scope", 200)
        if "rules" in values:
            held["rules"] = _text_list(values["rules"], "rules")
        if "agents" in values:
            held["agents"] = _text_list(values["agents"], "agents")
        if "plan" in values:
            held["plan"] = _text_list(values["plan"], "plan")
        if "handover" in values:
            note = values["handover"]
            if type(note) is not dict or not note or set(note) - set(_HANDOVER):
                raise ValueError("A handover note says what is done, what is next and where the results are")
            held["handover"] = {key: _short_text(_clean_note(history, row, _short_text(note[key], "handover " + key, 8000)),
                                                 "handover " + key, 1000) for key in _HANDOVER if key in note}
        if "folders" in values:
            held["folders"] = _session_list(values["folders"], "folders")
        if "references" in values:
            held["references"] = _session_list(values["references"], "references")
        if "progress" in values:
            progress = values["progress"]
            if type(progress) is not dict:
                raise ValueError("Task progress must be an object")
            held["progress"] = _plain(progress)
        held["task"] = task
        props["taskContext"] = held
        document["properties"] = props
        if "nodes" in values:
            _apply_nodes(document, values["nodes"])
        if "parameters" in values:
            _apply_parameters(document, values["parameters"])
        if "messages" in values:
            _apply_messages(document, values["messages"])
        return []
    canvas_documents.edit(path, 'You', 'update task session', change, solve_changed=False)
    return _show(task, path, read_document(path), select=False)
