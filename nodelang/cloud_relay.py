"""The founder's application drains the cockpit.

The cockpit (api.archhub.io/founder) is the map, the map is the graph, and the
graph lives here, in the running application. When the founder types into the
cockpit's ask bar the cloud queues his instruction; this relay claims it, puts
it to BABOOM exactly as if he had typed it into the companion, and posts
BABOOM's answer back. A remote host read (kind host-read, from the cloud's
/mcp) is answered by this machine's own allowlisted read function instead,
never BABOOM. It also re-publishes the live map projection so the cockpit
keeps showing what the application actually holds.

Nothing runs without the founder's cloud session (cloud.json token) and his
recorded cloud-publish consent; without both the relay is inert.
"""
from __future__ import annotations

import hashlib
import json
import re
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable, Mapping, Optional

CLAIM_PATH = "/founder/api/agent-tasks/claim"
RESULT_PATH = "/founder/api/agent-tasks/%s/result"
MAP_PATH = "/founder/map-state"
DEFAULT_BASE = "https://api.archhub.io"
# The ONLY hosts a cloud session bearer is ever sent to. cloud.json is editable
# by anyone at the machine, so a base it names outside these is ignored and the
# one address is used. Every cloud reader goes through pinned_cloud_base().
PINNED_BASES = ("https://api.archhub.io", "https://archhub-cloud.fly.dev")
HOST_READ = "host-read"
# One Workshop step of an MCP client (Spark, Notion) as its own agent; see
# McpWorkshopAgents. Claimed only when this app can answer it.
WORKSHOP_CALL = "workshop-call"
SESSION_CALL = "session-call"
APP_KINDS = ("app", "app-execute", HOST_READ)
# What a remote host read may run: the SAME local read functions the host
# tools use, and nothing that executes, captures or sends. Anything else is
# refused before a host is touched.
HOST_READ_TOOLS = frozenset({
    "hosts.status", "revit.sessions", "connector.rows",
    "office.read", "outlook.inbox", "dropbox.list",
})
OFFICE_READS = frozenset({
    "excel.list_workbooks", "excel.list_worksheets", "word.list_documents",
    "word.list_paragraphs", "powerpoint.list_presentations", "powerpoint.list_slides",
})
# agent_tasks.result holds 8000 characters; a longer answer becomes a labelled
# head rather than JSON cut in half.
RESULT_LIMIT = 7900
OFFER_KEYS = ("revision", "sha256", "availability", "pricing_visible", "public_label")
SESSION_TAIL_LIMIT = 40
REMOTE_OWNER_LABEL = "remote cloud owner"


def _session_account(value: object) -> str:
    return str(value or "").strip().casefold()


class RemoteSessionCaller:
    """Account-scoped remote session tools over real app sessions and native peers."""

    def __init__(self, *, account: Callable[[], object], transport: object,
                 application_sessions: object = None):
        if not callable(account):
            raise ValueError("session account loader must be callable")
        if transport is None or not callable(getattr(transport, "discover", None)):
            raise ValueError("session transport must expose discover")
        if application_sessions is not None and not all(callable(getattr(application_sessions, name, None))
                for name in ("list", "open", "create", "send")):
            raise ValueError("application sessions must expose list/open/create/send")
        self._account = account
        self._transport = transport
        self._application_sessions = application_sessions

    def __call__(self, account: object, method: object, params: object,
                 request_id: object = None) -> object:
        requested = _session_account(account)
        current = _session_account(self._account())
        if not requested or requested != current:
            raise PermissionError("session request belongs to another signed-in account")
        if not isinstance(params, Mapping):
            params = {}
        request_identity = self._request_identity(request_id)
        name = str(method or "")
        if name == "list_sessions":
            return {"sessions": [self._public_session(row) for row in self._sessions(current)]}
        if name == "open_session":
            return self._public_session(self._session(current, params.get("id")))
        if name == "send_to_session":
            session = self._session(current, params.get("id"))
            text = str(params.get("text") or "")
            if not text.strip():
                raise ValueError("session message is empty")
            if str(params.get("mode") or "ask") != "ask":
                raise PermissionError("send_to_session is Ask-gated")
            if session.get("app") == "archhub":
                if self._application_sessions is None:
                    raise RuntimeError("ArchHub conversation route is unavailable")
                if request_identity is None:
                    raise ValueError("session send requires the relay task request identity")
                return self._application_sessions.send(
                    current, session["id"], text, request_identity=request_identity)
            request = getattr(self._transport, "request", None)
            if not callable(request):
                raise RuntimeError("session transport cannot send")
            return {"session_id": session["id"], "mode": "ask",
                    "delivery": request(session, text, permission_mode="prompting")}
        if name == "new_session":
            title = str(params.get("title") or "").strip()
            if not title:
                raise ValueError("session title is empty")
            if str(params.get("mode") or "ask") != "ask":
                raise PermissionError("new_session is Ask-gated")
            if self._application_sessions is None:
                raise RuntimeError("ArchHub conversation route is unavailable")
            if request_identity is None:
                raise ValueError("session creation requires the relay task request identity")
            created = self._application_sessions.create(
                current, title, request_identity=request_identity)
            if not isinstance(created, Mapping):
                raise RuntimeError("session creation did not return a session")
            created_account = created.get("account")
            if created_account is None or _session_account(created_account) != current:
                raise PermissionError("created session has no proven ArchHub account owner")
            session_id = created.get("id")
            if not isinstance(session_id, str) or not session_id:
                raise RuntimeError("created session has no id")
            return self._public_session(created)
        raise KeyError(name)

    @staticmethod
    def _request_identity(value: object) -> str | None:
        if value is None:
            return None
        identity = str(value or "").strip()
        if not identity or "\x00" in identity or len(identity.encode("utf-8")) > 512:
            raise ValueError("relay task request identity is invalid")
        return identity

    def _sessions(self, account: str) -> tuple[dict, ...]:
        rows = []
        if self._application_sessions is not None:
            rows.extend(self._application_sessions.list(account))
        found = self._transport.discover()
        if not isinstance(found, Mapping) or found.get("status") != "ok":
            reason = found.get("reason") if isinstance(found, Mapping) else None
            raise RuntimeError("session discovery failed: " + str(reason or "invalid response"))
        for row in found.get("recipients") or ():
            if not isinstance(row, Mapping):
                continue
            if row.get("app") == "archhub":
                continue
            row_account = row.get("account")
            if row_account is None or _session_account(row_account) != account:
                continue
            session_id = row.get("id")
            if isinstance(session_id, str) and session_id:
                rows.append(dict(row))
        return tuple(rows)

    def _session(self, account: str, session_id: object) -> dict:
        wanted = str(session_id or "").strip()
        if self._application_sessions is not None:
            opened = self._application_sessions.open(account, wanted, missing_ok=True)
            if opened is not None:
                return opened
        for row in self._sessions(account):
            if row.get("id") == wanted:
                return row
        raise PermissionError("session is not in this ArchHub account")

    @staticmethod
    def _public_session(row: Mapping[str, object]) -> dict:
        allowed = ("id", "app", "title", "name", "state", "cwd", "pid", "port", "runtimeId",
                   "tail", "history", "model_agent")
        return {key: row[key] for key in allowed if key in row}


class ArchHubApplicationSessions:
    """Remote session tools backed by the same application conversation route as Home."""

    def __init__(self, owner, *, cloud_account: Callable[[], object]):
        if not callable(cloud_account):
            raise ValueError("application sessions require authenticated cloud account")
        self._owner = owner
        self._cloud_account = cloud_account

    def list(self, account: str) -> list[dict]:
        from .workshop_conversation_catalog import list_workshop_conversations
        account, binding = self._account_binding(account)
        result = list_workshop_conversations(self._owner,
            authentication_context=binding.context,
            expected_revision=self._owner.universal_store.revision)
        rows = []
        for row in result.get("conversations", ()):
            if row.get("is_general"):
                continue
            root = row.get("root")
            if (isinstance(root, str) and root
                    and self._conversation_owner(root, binding) == account):
                rows.append({"account": account, "app": "archhub", "id": root,
                    "title": row.get("title", root), "state": "idle",
                    "runtimeId": "application-conversation"})
        return rows

    def open(self, account: str, session_id: object, *, missing_ok: bool = False) -> dict | None:
        wanted = str(session_id or "").strip()
        if not wanted:
            if missing_ok:
                return None
            raise PermissionError("session is not in this ArchHub account")
        account, binding = self._account_binding(account)
        titles = {row["id"]: row.get("title", row["id"]) for row in self.list(account)}
        if wanted not in titles:
            if missing_ok:
                return None
            raise PermissionError("session is not in this ArchHub account")
        page = self._read(wanted, binding)
        history = [{"id": row.get("message_id") or row.get("root"),
                    "sequence": row.get("sequence"),
                    "author": row.get("sender_root"),
                    "category": row.get("category"),
                    "text": row.get("body", ""),
                    "reply_to": row.get("reply_to_root")}
                   for row in page.get("messages", ())]
        history.extend({"id": row.get("root"),
                        "sequence": row.get("sequence"),
                        "author": row.get("sender_root"),
                        "category": "tool",
                        "text": row.get("body", ""),
                        "reply_to": None}
                       for row in page.get("activity", ()))
        history.sort(key=lambda row: row.get("sequence") or 0)
        return {"account": account, "app": "archhub", "id": wanted,
                "title": titles[wanted], "state": "idle",
                "runtimeId": "application-conversation",
                "tail": [row["text"] for row in history[-SESSION_TAIL_LIMIT:]],
                "history": history, "model_agent": page.get("model_agent")}

    def create(self, account: str, title: str, *, request_identity: str) -> dict:
        from .workshop_session_start import start_workshop_session
        from . import commit_intent
        account, binding = self._account_binding(account)
        prompt = str(title or "").strip()
        route = self._model_route()
        body = {"prompt": prompt, "model": route,
                "idempotency_key": self._relay_key("remote-session-create", request_identity)}
        with commit_intent.declare(commit_intent.USER_ACTION, actor=binding.subject_root,
                reason="remote ArchHub session creation"):
            with self._planning():
                result = start_workshop_session(self._owner, binding, body,
                    browser_guard=lambda: self._guard(binding, "/api/universal/workshop"))
            self._ensure_conversation_owner(result["root"], account, binding)
        opened = self.open(account, result["root"])
        return {**opened, "account": account}

    def send(self, account: str, session_id: str, text: str, *, request_identity: str) -> dict:
        from .workshop_session_start import send_workshop_model_message
        from . import commit_intent
        account, binding = self._account_binding(account)
        opened = self.open(account, session_id)
        agent = opened.get("model_agent")
        if not isinstance(agent, Mapping) or not isinstance(agent.get("root"), str):
            raise RuntimeError("ArchHub conversation has no admitted model agent")
        key = self._relay_key("remote-session-send", request_identity)
        body = {"root": session_id, "scope": self._owner.universal_registry.workshop_workbench_root,
                "node": agent["root"], "binding_digest": agent["binding_digest"],
                "prompt": text, "idempotency_key": key}
        with commit_intent.declare(commit_intent.USER_ACTION, actor=binding.subject_root,
                reason="remote ArchHub conversation send"):
            with self._planning():
                result = send_workshop_model_message(self._owner, binding, body,
                    browser_guard=lambda: self._guard(binding, "/api/universal/workshop"))
        return {"session_id": session_id, "mode": "ask", "delivery": result["delivery"],
                "message_id": result["message_id"], "reply_persisted": result["delivery"].get("state") == "replied"}

    def _read(self, root: str, binding) -> dict:
        from .existing_workshop_conversation import read_browser_workshop
        return read_browser_workshop(self._owner, binding, root=root,
            scope=self._owner.universal_registry.workshop_workbench_root,
            session_token=self._owner.browser_session_token, feed="messages")

    @staticmethod
    def _relay_key(prefix: str, request_identity: str) -> str:
        return prefix + ":" + hashlib.sha256(request_identity.encode("utf-8")).hexdigest()

    @staticmethod
    def _owner_roots(root: str) -> tuple[str, str, str]:
        digest = hashlib.sha256(root.encode("utf-8")).hexdigest()
        base = "app:remote-session-owner:" + digest
        return base, base + ":value", base + ":label"

    def _account_binding(self, account: object):
        requested = _session_account(account)
        authenticated = _session_account(self._cloud_account())
        if not requested or requested != authenticated:
            raise PermissionError("session request belongs to another signed-in account")
        binding = self._binding()
        if not isinstance(getattr(binding, "subject_root", None), str) or not binding.subject_root:
            raise PermissionError("remote sessions require an authenticated application subject")
        return authenticated, binding

    def _conversation_owner(self, root: str, binding) -> str | None:
        from .cell_protocols import read_relation
        relation_root, value_root, label_root = self._owner_roots(root)
        snapshot = self._owner.universal_store.snapshot()
        if relation_root not in snapshot.cells:
            return None
        try:
            members = read_relation(snapshot, relation_root, budget=8)
            roles = self._owner.universal_registry.roles
            if ({(row.role_id, row.participant_id) for row in members}
                    != {(roles["owner"], root), (roles["value"], value_root),
                        (roles["label"], label_root)}):
                return None
            label = snapshot.cells[label_root].atom.decode("utf-8")
            value = json.loads(snapshot.cells[value_root].atom.decode("utf-8"))
        except (KeyError, UnicodeDecodeError, ValueError, TypeError):
            return None
        account = _session_account(value.get("account") if isinstance(value, Mapping) else None)
        subject_root = value.get("subject_root") if isinstance(value, Mapping) else None
        if label != REMOTE_OWNER_LABEL or subject_root != binding.subject_root:
            return None
        return account or None

    def _ensure_conversation_owner(self, root: str, account: str, binding) -> None:
        from .cell_protocols import compose_relation_cells
        from .universal_cell import Cell, NULL_CELL_ID
        relation_root, value_root, label_root = self._owner_roots(root)
        with self._owner.mutation_lock:
            store, registry = self._owner.universal_store, self._owner.universal_registry
            with registry.authorization.broker.live_context(binding.context):
                snapshot = store.snapshot()
                current = self._conversation_owner(root, binding)
                if current == account:
                    return
                if current is not None:
                    raise PermissionError("ArchHub conversation belongs to another cloud account")
                if relation_root in snapshot.cells:
                    raise PermissionError("ArchHub conversation owner property is invalid")
                value = json.dumps({"account": account, "subject_root": binding.subject_root},
                                   sort_keys=True, separators=(",", ":")).encode("utf-8")
                relation = compose_relation_cells((
                    (registry.roles["owner"], root),
                    (registry.roles["value"], value_root),
                    (registry.roles["label"], label_root),
                ), relation_id=relation_root)
                registry.authorization.broker.commit_authenticated(binding.context, store,
                    snapshot.revision, create=(
                        Cell(value_root, NULL_CELL_ID, NULL_CELL_ID, value),
                        Cell(label_root, NULL_CELL_ID, NULL_CELL_ID,
                             REMOTE_OWNER_LABEL.encode("utf-8")),
                        *relation.cells))
        if self._conversation_owner(root, binding) != account:
            raise PermissionError("ArchHub conversation owner was not proven")

    def _binding(self):
        return self._owner._resolve_browser_session(
            self._owner.browser_session_token,
            csrf_token=self._owner.browser_csrf_token,
            require_csrf=True)

    def _guard(self, binding, path: str):
        current = self._binding()
        if current != binding:
            from .cell_authorization import AuthorizationDenied
            raise AuthorizationDenied("Remote session browser changed")
        if self._owner._runtime_handoff_exit.is_set():
            from .cell_authorization import AuthorizationDenied
            raise AuthorizationDenied("runtime generation was released during planning")
        if self._owner.universal_checkpoint_guard is not None:
            self._owner.universal_checkpoint_guard.require_healthy()
        self._owner.require_universal_http_route("POST", path,
            authentication_context=binding.context, revalidate=True)

    def _model_route(self) -> str:
        reader = getattr(self._owner, "_read_agent_model", None)
        route = ""
        if callable(reader):
            route = str(reader() or "").strip()
        if not route:
            default = getattr(self._owner, "_default_agent_model", None)
            if callable(default):
                route = str((default() or ("", ""))[0] or "").strip()
        if not route:
            raise RuntimeError("ArchHub session creation requires a configured composer model")
        return route

    def _planning(self):
        class _Planning:
            def __init__(self, slot):
                self._slot = slot

            def __enter__(self):
                if self._slot is not None and not self._slot.acquire(blocking=False):
                    from .universal_cell import InvalidCell
                    raise InvalidCell("Another draft is being prepared; wait for its result before trying again")

            def __exit__(self, exc_type, exc, tb):
                if self._slot is not None:
                    self._slot.release()
        return _Planning(getattr(self._owner, "_composer_planning_slot", None))


def pinned_cloud_base(value: object) -> str:
    """The cloud base a bearer may go to: a pinned host, else the one address."""
    base = str(value or "").strip().rstrip("/")
    return base if base in PINNED_BASES else DEFAULT_BASE


def load_cloud_session(appdata: Path | None = None) -> Optional[dict]:
    """The founder's cloud session as the brain recorded it, or None."""
    from .cloud_session import cloud_session_path
    cloud = cloud_session_path() if appdata is None else Path(appdata) / "ArchHub" / "brain" / "cloud.json"
    if not cloud.is_file():
        return None
    try:
        from .cloud_signin import read_cloud_session
        held = read_cloud_session(cloud)
    except (OSError, ValueError):
        return None
    token = held.get("token") if isinstance(held, Mapping) else None
    if not token:
        return None
    return {"token": str(token), "base_url": pinned_cloud_base(held.get("cloud_base_url"))}


def cockpit_url(appdata: Path | None = None) -> str:
    """The cockpit address for THIS machine, opened on the app's own session.

    One hand-off, written once in cloud_signin.cockpit_link: the app spends
    its session for a one-time claim link. With no usable session the plain
    address is returned; the cloud's page there says to open the cockpit
    from the app, and never offers a sign-in of its own.
    """
    from . import cloud_signin

    record = cloud_signin.cloud_session_path() if appdata is None else Path(appdata) / "ArchHub" / "brain" / "cloud.json"
    link = cloud_signin.cockpit_link(record)
    if link.get("ok"):
        return str(link["url"])
    return cloud_signin.pinned_base(cloud_signin.read_cloud_session(record)) + "/founder"


def published_offer_form(value: object) -> Optional[dict]:
    """The offer as its one published record, or None when nothing valid is declared.

    Only the five published keys travel; the rest of the record stays in the app.
    """
    if not isinstance(value, Mapping) or any(key not in value for key in OFFER_KEYS):
        return None
    digest = value["sha256"]
    if type(value["revision"]) is not int or not isinstance(digest, str) or len(digest) != 64:
        return None
    if not isinstance(value["availability"], str) or not isinstance(value["public_label"], str):
        return None
    if type(value["pricing_visible"]) is not bool:
        return None
    return {key: value[key] for key in OFFER_KEYS}


# What a person can actually do about a sign-in the cloud refuses or this
# machine never had. The model picker's cloud group says exactly this, so it
# is written once and read from here.
SIGN_IN_AGAIN = "Sign in again under Settings, Account."
MODEL_LIMIT = 40
# The cloud refuses an expired or revoked sign-in with 401 (API) or 403 (founder routes). The relay then
# asks again only this often, instead of every poll: on 2026-09-17 it had asked every ~5 s for four days.
REFUSED_BACKOFF = 300.0


def published_models_form(value: object) -> Optional[dict]:
    """The models and routing the app publishes for the cockpit, or None.

    This is the contract the router publishes into, through CloudRelay(models=...):

        {"models": [{"name": str, "provider": str, "available": bool}, ...],
         "routes": [{"task": str, "model": str}, ...]}      # routes may be omitted

    name is 1-80 characters and unique; provider is 1-40; task is 1-40 and unique; a
    route's model names a published model; at most 40 of each. Only those keys travel,
    so no key, endpoint or price leaves the app with them. Anything else makes the whole
    value invalid: the cockpit then says the list is not published, never half a list.
    """
    def text(item, key, limit):
        field = item.get(key) if isinstance(item, Mapping) else None
        return field if isinstance(field, str) and 0 < len(field.strip()) and len(field) <= limit else None

    if not isinstance(value, Mapping):
        return None
    models, routes = value.get("models"), value.get("routes", [])
    if not isinstance(models, list) or not isinstance(routes, list):
        return None
    if len(models) > MODEL_LIMIT or len(routes) > MODEL_LIMIT:
        return None
    published = []
    for item in models:
        name, provider = text(item, "name", 80), text(item, "provider", 40)
        if name is None or provider is None or type(item.get("available")) is not bool:
            return None
        published.append({"name": name, "provider": provider, "available": item["available"]})
    names = [m["name"] for m in published]
    if len(set(names)) != len(names):
        return None
    routing = []
    for item in routes:
        task, model = text(item, "task", 40), text(item, "model", 80)
        if task is None or model not in names:
            return None
        routing.append({"task": task, "model": model})
    if len({r["task"] for r in routing}) != len(routing):
        return None
    return {"models": published, "routes": routing}


def render_answer(result: Mapping[str, object]) -> str:
    """One founder-readable text from a BABOOM response or execution payload."""
    body = result.get("response") if isinstance(result.get("response"), Mapping) else result
    kind = str(body.get("kind") or result.get("kind") or "")
    summary = str(body.get("summary") or result.get("summary") or "").strip()
    data = body.get("data") if isinstance(body.get("data"), Mapping) else {}
    lines = [summary] if summary else []
    for key, value in list(data.items())[:12]:
        if key in ("requires", "command"):
            continue
        if isinstance(value, (str, int, float, bool)):
            lines.append("%s: %s" % (key, value))
        elif isinstance(value, (list, tuple)):
            items = []
            for item in list(value)[:10]:
                if isinstance(item, Mapping):
                    items.append(str(
                        item.get("title") or item.get("session")
                        or item.get("session_root") or item.get("provider")
                        or json.dumps(item, sort_keys=True)[:80]))
                else:
                    items.append(str(item))
            if items:
                lines.append("%s: %s" % (key, "; ".join(items)))
        elif isinstance(value, Mapping):
            lines.append("%s: %s" % (key, json.dumps(value, sort_keys=True)[:300]))
    if data.get("requires"):
        lines.append("Untick 'Confirm before any change' in the cockpit to make BABOOM act.")
    text = "\n".join(lines).strip()
    return text or (kind or "no answer")


def host_read(tool: object, arguments: object) -> object:
    """Answer one remote read with this machine's own read function.

    The cloud sends only {tool, args}. The tool must be on HOST_READ_TOOLS and
    only the arguments that tool reads are passed on; the rest are dropped.
    Never BABOOM, never an effect.
    """
    if tool not in HOST_READ_TOOLS:
        raise PermissionError("not a remote read: %r" % (tool,))
    args = arguments if isinstance(arguments, Mapping) else {}
    if tool == "hosts.status":
        from .connector_operation_evidence import host_projection
        return host_projection()
    if tool == "revit.sessions":
        from .clean_revit_adapter import live_sessions
        return {"ok": True, "sessions": live_sessions()}
    params: dict[str, object] = {}
    if tool == "office.read":
        operation = args.get("operation") or "excel.list_workbooks"
        if operation not in OFFICE_READS:
            raise PermissionError("not an office read: %r" % (operation,))
        params["operation"] = operation
        if isinstance(args.get("name"), str) and args["name"].strip():
            params["name"] = args["name"][:200]
    elif tool == "outlook.inbox":
        count = args.get("count")
        params.update(transport="classic",
                      count=max(1, min(count, 50)) if type(count) is int else 20)
    elif tool == "dropbox.list":
        path = args.get("path")
        params["path"] = path[:300] if isinstance(path, str) else ""
    from .host_brokers import ENGINES
    out, label = ENGINES[str(tool)](params, {})
    answer = dict(out) if isinstance(out, Mapping) else {"out": out}
    answer.setdefault("ok", True)
    answer["label"] = str(label)
    return answer


# What an MCP client's agent may do in the Workshop: the installed Workshop
# coordination methods Claude and Codex use (installed_workshop_coordination),
# nothing that executes, attaches another agent or runs a task.
WORKSHOP_METHODS = frozenset({
    "workshop_lens", "list_agents", "read_messages", "read_message",
    "send_message", "acknowledge_message", "claim_work",
})
MAX_MCP_AGENTS = 8
_RENEW_MARGIN_SECONDS = 120.0
_PRESENCE_EVERY_SECONDS = 60.0


def mcp_runtime(client_name: object) -> str:
    """The runtime an MCP client's agent is enrolled under: always mcp-<name>.

    The prefix keeps a client that names itself "Claude" or "Codex" out of those
    runtimes' Agent Bodies; the rest is the client's registered name.
    """
    slug = re.sub(r"[^a-z0-9]+", "-", str(client_name or "").lower()).strip("-")[:40].strip("-")
    return "mcp-" + (slug or "client")


def _compact(value: object, depth: int = 0) -> object:
    """A Workshop answer small enough for one task row: long texts cut, long lists cut."""
    if isinstance(value, str):
        return value if len(value) <= 600 else value[:600] + "..."
    if isinstance(value, Mapping):
        return {str(key): _compact(item, depth + 1) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_compact(item, depth + 1) for item in list(value)[:20]]
    return value


class McpWorkshopAgents:
    """Each MCP client (by OAuth client_id) is one Workshop agent of its own.

    It is enrolled like any runtime agent (UniversalRuntimeClient.bind_agent_session,
    runtime mcp-<name>, external session mcp:<client_id>) and every step goes
    through InstalledWorkshopCoordinationClient: the same allowlisted methods,
    identity checks and idempotency Claude and Codex use. One process-local
    capability per client, renewed before it expires; nothing else is kept.
    """

    def __init__(self, descriptor_path: Path, key_provider: object, *,
                 client_factory: Optional[Callable[[], object]] = None):
        self.descriptor_path = Path(descriptor_path)
        self.key_provider = key_provider
        self._factory = client_factory
        self._agents: dict[str, tuple[object, object, str]] = {}
        self._presence_at: dict[str, float] = {}
        self._presence: dict[str, str] = {}
        self._lock = threading.Lock()

    def _new_client(self) -> object:
        if self._factory is not None:
            return self._factory()
        from .application_machine_transport import UniversalRuntimeClient
        return UniversalRuntimeClient(self.descriptor_path, self.key_provider)

    def _bound(self, client_id: str, client_name: str):
        held = self._agents.get(client_id)
        runtime = mcp_runtime(client_name)
        if held is not None and held[2] == runtime:
            return held
        if held is None and len(self._agents) >= MAX_MCP_AGENTS:
            raise PermissionError("too many MCP agents on this app; restart ArchHub to reset them")
        from .installed_workshop_coordination import InstalledWorkshopCoordinationClient
        client = self._new_client()
        client.bind_agent_session(runtime=runtime, external_session_id="mcp:" + client_id)
        held = (client, InstalledWorkshopCoordinationClient(client), runtime)
        self._agents[client_id] = held
        self._presence_at.pop(client_id, None)
        return held

    def _keep_alive(self, client_id: str, client: object) -> None:
        if float(getattr(client, "_agent_session_expires_at", 0.0)) - time.time() < _RENEW_MARGIN_SECONDS:
            client.renew_agent_session()
        now = time.monotonic()
        if now - self._presence_at.get(client_id, -1e9) >= _PRESENCE_EVERY_SECONDS:
            # Presence is what the Workshop rail and Assign read as "verified".
            # A refusal is reported with the answer; messages still flow.
            try:
                client.renew_runtime_presence()
                self._presence[client_id] = "live"
            except Exception as refusal:
                self._presence[client_id] = "not renewed: %s" % (refusal,)
            self._presence_at[client_id] = now

    def call(self, agent: object, method: object, params: object) -> dict:
        if not isinstance(agent, Mapping):
            raise ValueError("a Workshop step names its agent")
        client_id = agent.get("client_id")
        if (type(client_id) is not str or not re.fullmatch(r"[A-Za-z0-9._~-]{1,200}", client_id)):
            raise ValueError("a Workshop step needs the MCP client's id")
        if method not in WORKSHOP_METHODS:
            raise PermissionError("not a Workshop step: %r" % (method,))
        if params is not None and not isinstance(params, Mapping):
            raise ValueError("Workshop parameters must be a mapping")
        client_name = str(agent.get("client_name") or "")[:200]
        with self._lock:
            for attempt in (0, 1):
                client, workshop, runtime = self._bound(client_id, client_name)
                try:
                    self._keep_alive(client_id, client)
                    result = workshop.call(str(method), dict(params or {}))
                    break
                except Exception as refusal:
                    # A capability the owner no longer honours (app restarted its
                    # runtime, session expired) is replaced once by a new binding.
                    text = str(refusal)
                    if attempt or not any(word in text for word in (
                            "binding changed", "owner changed", "Agent Session", "expired")):
                        raise
                    self._agents.pop(client_id, None)
        answer = _compact(result)
        extra = {"ok": True, "agent_runtime": runtime,
                 "agent_presence": self._presence.get(client_id, "unknown")}
        return {**answer, **extra} if isinstance(answer, dict) else {**extra, "answer": answer}


def bounded_json(value: object, limit: int = RESULT_LIMIT) -> str:
    """The answer as JSON that fits one task row, or a labelled head of it."""
    text = json.dumps(value, ensure_ascii=False, default=str, separators=(",", ":"))
    if len(text) <= limit:
        return text
    return json.dumps({"ok": True, "truncated": True, "chars": len(text),
                       "head": text[: limit // 2 - 200]}, ensure_ascii=False)


class CloudRelay:
    """Claim cockpit instructions, answer them through BABOOM, post the answer."""

    def __init__(
        self,
        *,
        base_url: str,
        token: str,
        respond: Callable[[str], Mapping[str, object]],
        execute: Callable[[str], Mapping[str, object]],
        claimed_by: str = "archhub-app",
        opener: Optional[Callable[..., object]] = None,
        timeout: float = 20.0,
        map_script: Optional[Callable[[], str]] = None,
        hosts: Optional[Callable[[], object]] = None,
        offer: Optional[Callable[[], object]] = None,
        offer_command: Optional[Callable[[str, bool], object]] = None,
        models: Optional[Callable[[], object]] = None,
        session_loader: Optional[Callable[[], Optional[Mapping[str, str]]]] = None,
        workshop_caller: Optional[Callable[[object, object, object], object]] = None,
        session_caller: Optional[Callable[[object, object, object, object], object]] = None,
        session_path: Optional[Path] = None,
        consent: Optional[Callable[[], bool]] = None,
        host_reader: Optional[Callable[[object, object], object]] = None,
        app_kinds: tuple[str, ...] = APP_KINDS,
    ) -> None:
        self.base_url = str(base_url).rstrip("/")
        # A remote read runs this: host_read, unless a caller supplies its own.
        self.host_reader = host_reader or host_read
        self.token = str(token)
        self.respond = respond
        self.execute = execute
        self.claimed_by = claimed_by
        self.opener = opener or urllib.request.urlopen
        self.timeout = float(timeout)
        self.map_script = map_script
        self.hosts = hosts
        self.offer = offer
        self.offer_command = offer_command
        self.models = models
        self.session_loader = session_loader
        self.workshop_caller = workshop_caller
        self.session_caller = session_caller
        self.app_kinds = tuple(k for k in app_kinds if k in APP_KINDS)
        self.session_path = session_path
        # Settings > Account withdraws cloud publish consent by deleting its
        # record; the relay reads it before every claim and stops for good.
        self.consent = consent
        self.last_error: str = ""
        self.answered = 0
        self._map_digest = ""
        self._map_pushed_at = 0.0
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lifecycle_lock = threading.Lock()

    def start(self) -> "CloudRelay":
        """Start the one worker whose lifetime this relay owns."""
        with self._lifecycle_lock:
            if self._stop.is_set() or self._thread is not None:
                raise RuntimeError("cloud relay cannot be started again")
            self._thread = threading.Thread(
                target=self.run_forever, name="archhub-cloud-relay", daemon=True,
            )
            self._thread.start()
        return self

    def request_stop(self) -> None:
        self._stop.set()

    def close(self, *, timeout_seconds: float = 6.0) -> None:
        """Return only once the owned worker can no longer touch its graph."""
        timeout = float(timeout_seconds)
        if not 0 <= timeout <= 30:
            raise ValueError("cloud relay shutdown timeout must be within 30 seconds")
        self.request_stop()
        with self._lifecycle_lock:
            worker = self._thread
        if worker is None:
            return
        if worker is threading.current_thread():
            raise RuntimeError("cloud relay cannot join its own worker")
        worker.join(timeout=timeout)
        if worker.is_alive():
            raise TimeoutError("cloud relay worker is still active; graph close is unsafe")

    def _request(self, path: str, body: Optional[bytes], *, method: str = "POST") -> dict:
        request = urllib.request.Request(
            self.base_url + path, data=body, method=method,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Authorization": "Bearer " + self.token,
            },
        )
        with self.opener(request, timeout=self.timeout) as answer:
            payload = json.loads(answer.read().decode("utf-8"))
        return payload if isinstance(payload, dict) else {"raw": payload}

    def _call(self, path: str, body: Mapping[str, object]) -> dict:
        return self._request(path, json.dumps(body).encode("utf-8"))

    def poll_once(self) -> Optional[dict]:
        """Claim one instruction, answer it, post the answer. None when idle."""
        if self._stop.is_set():
            return None  # stopping: claim nothing new
        if callable(self.consent):
            allowed = self.consent()
            if allowed is None:
                return None  # identity proof pending/unreachable: claim nothing, retain worker
            if not allowed:
                self._stop.set()
                self.last_error = "cloud publish consent withdrawn; relay stopped"
                return None
        kinds = (list(self.app_kinds) +
                 ([WORKSHOP_CALL] if callable(self.workshop_caller) else []) +
                 ([SESSION_CALL] if callable(self.session_caller) else []))
        claimed = self._call(CLAIM_PATH, {"claimed_by": self.claimed_by, "kinds": kinds})
        task = claimed.get("task")
        if not isinstance(task, Mapping) or not task.get("id"):
            return None
        if task.get("kind") == HOST_READ:
            return self._answer_host_read(task)
        if task.get("kind") == WORKSHOP_CALL:
            return self._answer_workshop_call(task)
        if task.get("kind") == SESSION_CALL:
            return self._answer_session_call(task)
        utterance = str(task.get("directive") or "").strip()
        execute = task.get("kind") == "app-execute"
        handled = None
        try:
            # The offer is one record in this application, so its command is
            # answered from that record here and never handed to BABOOM.
            if callable(self.offer_command):
                handled = self.offer_command(utterance, execute)
            if handled is not None:
                result = handled
            elif execute:
                result = self.execute(utterance)
            else:
                result = self.respond(utterance)
            ok, text = True, render_answer(result)
        except Exception as exc:  # the refusal IS the answer; never a silent drop
            ok, text = False, "%s: %s" % (type(exc).__name__, exc)
        self._call(RESULT_PATH % str(task["id"]), {"ok": ok, "result": text[:8000]})
        self.answered += 1
        if ok and isinstance(handled, Mapping) and handled.get("kind") == "offer-updated":
            # Republish at once, so the cockpit states the changed offer.
            try:
                self.push_map(force=True)
            except Exception as exc:
                self.last_error = "%s: %s" % (type(exc).__name__, exc)
        return {"task": str(task["id"]), "ok": ok, "result": text}

    def _answer_host_read(self, task: Mapping[str, object]) -> dict:
        """A remote read: this machine's allowlisted read function, never BABOOM."""
        try:
            request = json.loads(str(task.get("directive") or ""))
            if not isinstance(request, Mapping):
                raise ValueError("a host read is {tool, args}")
            ok, text = True, bounded_json(self.host_reader(request.get("tool"), request.get("args")))
        except Exception as exc:  # the refusal IS the answer; never a silent drop
            ok, text = False, "%s: %s" % (type(exc).__name__, exc)
        self._call(RESULT_PATH % str(task["id"]), {"ok": ok, "result": text[:8000]})
        self.answered += 1
        return {"task": str(task["id"]), "ok": ok, "result": text}

    def _answer_workshop_call(self, task: Mapping[str, object]) -> dict:
        """One Workshop step of an MCP client's own agent; never BABOOM, never a host."""
        try:
            if not callable(self.workshop_caller):
                raise PermissionError("this app does not answer Workshop steps")
            request = json.loads(str(task.get("directive") or ""))
            if not isinstance(request, Mapping):
                raise ValueError("a Workshop step is {agent, method, params}")
            ok, text = True, bounded_json(self.workshop_caller(
                request.get("agent"), request.get("method"), request.get("params")))
        except Exception as exc:  # the refusal IS the answer; never a silent drop
            ok, text = False, "%s: %s" % (type(exc).__name__, exc)
        self._call(RESULT_PATH % str(task["id"]), {"ok": ok, "result": text[:8000]})
        self.answered += 1
        return {"task": str(task["id"]), "ok": ok, "result": text}

    def _answer_session_call(self, task: Mapping[str, object]) -> dict:
        """One remote session operation; never BABOOM, never a host."""
        try:
            if not callable(self.session_caller):
                raise PermissionError("this app does not answer remote session calls")
            request = json.loads(str(task.get("directive") or ""))
            if not isinstance(request, Mapping):
                raise ValueError("a session call is {account, method, params}")
            account = _session_account(request.get("account"))
            if not account:
                raise ValueError("a session call requires an account")
            request_id = request.get("request_id") or task["id"]
            ok, text = True, bounded_json(self.session_caller(
                account, request.get("method"), request.get("params"), request_id))
        except Exception as exc:
            ok, text = False, "%s: %s" % (type(exc).__name__, exc)
        self._call(RESULT_PATH % str(task["id"]), {"ok": ok, "result": text[:8000]})
        self.answered += 1
        return {"task": str(task["id"]), "ok": ok, "result": text}

    def push_map(self, *, force: bool = False, min_interval: float = 60.0) -> Optional[dict]:
        """Re-publish the live projection when it changed (or on demand)."""
        if self._stop.is_set() or self.map_script is None:
            return None
        if callable(self.consent) and self.consent() is not True:
            return None
        now = time.monotonic()
        if not force and now - self._map_pushed_at < min_interval:
            return None
        script = self.map_script()
        if self._stop.is_set():
            return None
        body = script.split("window.ATLAS_MAP = ", 1)[1].rsplit("; window.ATLAS_LIVE", 1)[0]
        body = self._with_control(body)
        if self._stop.is_set():
            return None
        digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
        self._map_pushed_at = now
        if not force and digest == self._map_digest:
            return None
        answer = self._request(MAP_PATH, body.encode("utf-8"))
        self._map_digest = digest
        return answer

    def _with_control(self, body: str) -> str:
        """Add the CONTROL block the cockpit's domain panel drives from.

        The cockpit is the map and the map is the graph -- and the founder
        controls the graph through BABOOM. So the control block IS BABOOM's
        own answers, read the same way he would: the agents on this machine,
        the governed work, the hosts and their states. Best effort: a silent
        brain or coordination host leaves the field empty, never breaks the push.
        The declared offer travels beside it; an undeclared offer sends no key.
        """
        try:
            model = json.loads(body)
        except ValueError:
            return body
        control: dict[str, object] = {"agents": [], "work_summary": "", "work_items": [], "hosts": []}
        if self._stop.is_set():
            return body
        try:
            agents = self.respond("agents")
            answer = agents.get("response") if isinstance(agents.get("response"), Mapping) else agents
            control["agents"] = list(((answer.get("data") or {}).get("agents") or []))[:24]
        except Exception:
            pass
        if self._stop.is_set():
            return body
        try:
            work = self.respond("show governed work")
            answer = work.get("response") if isinstance(work.get("response"), Mapping) else work
            control["work_summary"] = str(answer.get("summary") or "")[:400]
            data = answer.get("data") if isinstance(answer.get("data"), Mapping) else {}
            items = data.get("items") or data.get("work") or []
            if isinstance(items, list):
                control["work_items"] = [
                    {
                        "title": str((it.get("title") if isinstance(it, Mapping) else it) or "")[:80],
                        "state": str((it.get("state") or it.get("status")) if isinstance(it, Mapping) else "")[:24],
                        "agent": str(it.get("agent") or "")[:40] if isinstance(it, Mapping) else "",
                    }
                    for it in items[:12]
                ]
        except Exception:
            pass
        if self._stop.is_set():
            return body
        try:
            rows = self.hosts() if callable(self.hosts) else []
            control["hosts"] = [
                {"id": str(r.get("id") or ""), "name": str(r.get("name") or ""), "state": str(r.get("state") or ""), "detail": str(r.get("detail") or "")[:120]}
                for r in (rows or []) if isinstance(r, Mapping)
            ][:40]
        except Exception:
            pass
        if callable(self.models) and not self._stop.is_set():
            # No key when the app publishes nothing valid: the cockpit tells "not published"
            # apart from a published empty list.
            try:
                published = published_models_form(self.models())
            except Exception:
                published = None
            if published is not None:
                control["models"] = published["models"]
                control["routes"] = published["routes"]
        offer = None
        if callable(self.offer) and not self._stop.is_set():
            try:
                offer = published_offer_form(self.offer())
            except Exception:
                offer = None
        if isinstance(model, dict):
            model["control"] = control
            if offer is not None:
                model["offer"] = offer
            # The cockpit's Wire panel draws the engine's one list; the cloud keeps no copy.
            try:
                from .universal_pipeline import wire_parameter_specs
                model["wire_params"] = wire_parameter_specs()
            except Exception:
                pass
            return json.dumps(model, separators=(",", ":"))
        return body

    def run_forever(self, *, interval: float = 4.0, stop: Optional[threading.Event] = None) -> None:
        stop = stop or self._stop
        while not self._stop.is_set() and not stop.is_set():
            try:
                worked = self.poll_once()
                self.last_error = ""
                if self._stop.is_set() or stop.is_set():
                    break
                if worked is not None:
                    continue  # drain the queue before sleeping
                self.push_map()
            except urllib.error.HTTPError as exc:
                if exc.code in (401, 403):
                    stop.wait(self._after_session_refused(exc))
                    continue
                self.last_error = "%s: %s" % (type(exc).__name__, exc)
            except Exception as exc:
                self.last_error = "%s: %s" % (type(exc).__name__, exc)
            stop.wait(interval)

    def _after_session_refused(self, exc: urllib.error.HTTPError) -> float:
        """The cloud refused this machine's sign-in; return how long to wait before asking again.

        A token lives 90 days on the cloud and cannot be revived. When the founder has signed in
        again, the record on this machine carries a new token: take it and ask at once. Otherwise
        say what to do, never the token, and slow down.
        """
        fresh = None
        if callable(self.session_loader):
            try:
                fresh = self.session_loader()
            except Exception:
                fresh = None
        token = fresh.get("token") if isinstance(fresh, Mapping) else None
        if token and str(token) != self.token:
            self.token = str(token)
            self.base_url = str(fresh.get("base_url") or self.base_url).rstrip("/")
            self.last_error = "cloud sign-in renewed from this machine"
            return 0.0
        self.last_error = (
            "the cloud refused this machine's sign-in (HTTP %d): it expired or was revoked. "
            % exc.code) + SIGN_IN_AGAIN
        if self.session_path is not None:
            # Settings > Account reads this record. A 401 is a refused session;
            # a founder route's 403 may only mean another account, so /v1/me
            # decides before the record says "sign-in expired".
            from .cloud_signin import confirm_with_cloud, record_refusal
            try:
                if exc.code == 401:
                    record_refusal(self.session_path, self.token)
                else:
                    confirm_with_cloud(self.session_path)
            except OSError:
                pass
        return REFUSED_BACKOFF


def start_cloud_relay(
    *,
    appdata: Path | None = None,
    state_dir: Path,
    respond: Callable[[str], Mapping[str, object]],
    execute: Callable[[str], Mapping[str, object]],
    map_script: Optional[Callable[[], str]] = None,
    hosts: Optional[Callable[[], object]] = None,
    offer: Optional[Callable[[], object]] = None,
    offer_command: Optional[Callable[[str, bool], object]] = None,
    models: Optional[Callable[[], object]] = None,
    workshop_caller: Optional[Callable[[object, object, object], object]] = None,
    session_caller: Optional[Callable[[object, object, object, object], object]] = None,
    session_transport: object = None,
    application_session_owner: object = None,
    app_kinds: tuple[str, ...] = APP_KINDS,
) -> Optional[CloudRelay]:
    """Start the relay thread when the founder's session and consent exist.

    Consent is the signed-in account's own (cloud_publish_consent): after a
    sign-out or an account switch the relay does not start, and a running one
    stops at its next poll.
    """
    from .cloud_publish_consent import cloud_publish_allowed
    from .cloud_session import cloud_session_path, signed_in_cloud_account

    session_path = cloud_session_path() if appdata is None else Path(appdata) / "ArchHub" / "brain" / "cloud.json"

    pending = object()

    def consented() -> bool | None:
        account = signed_in_cloud_account(session_path, pending=pending)
        return None if account is pending else cloud_publish_allowed(state_dir, account)

    if consented() is False:
        return None
    session = load_cloud_session(appdata)
    if session is None:
        return None
    if session_caller is None and session_transport is not None:
        can_open_application = (application_session_owner is not None and all(
            hasattr(application_session_owner, name) for name in (
                "browser_session_token", "browser_csrf_token", "universal_store",
                "universal_registry", "conversation_content")))
        cloud_account = lambda: signed_in_cloud_account(session_path)
        application_sessions = (ArchHubApplicationSessions(
            application_session_owner, cloud_account=cloud_account)
                                if can_open_application else None)
        session_caller = RemoteSessionCaller(
            account=cloud_account,
            transport=session_transport,
            application_sessions=application_sessions,
        )
    relay = CloudRelay(
        base_url=session["base_url"], token=session["token"],
        respond=respond, execute=execute, map_script=map_script, hosts=hosts,
        offer=offer,
        offer_command=offer_command,
        models=models,
        session_loader=lambda: load_cloud_session(appdata),
        session_path=session_path,
        consent=consented,
        workshop_caller=workshop_caller,
        session_caller=session_caller,
        app_kinds=app_kinds,
    )
    return relay.start()


__all__ = [
    "CloudRelay", "PINNED_BASES", "load_cloud_session", "pinned_cloud_base",
    "published_models_form", "published_offer_form",
    "render_answer", "host_read", "bounded_json", "HOST_READ_TOOLS",
    "McpWorkshopAgents", "WORKSHOP_CALL", "SESSION_CALL", "WORKSHOP_METHODS", "mcp_runtime",
    "RemoteSessionCaller", "ArchHubApplicationSessions", "start_cloud_relay",
    "CLAIM_PATH", "RESULT_PATH", "MAP_PATH",
]
