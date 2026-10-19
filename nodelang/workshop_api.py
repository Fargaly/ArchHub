"""Design-named data functions over the existing Workshop Work and content owners.

No UI, provider simulation, task database or execution authority is introduced.
Task status is projected from committed Work state and live declarations.
"""
import hashlib
import json

from .cell_authorization import AuthorizationDenied
from .cell_protocols import prepare_append_relation_members
from .universal_cell import Cell, InvalidCell


FUNCTIONS = frozenset({"listAgentsWorking", "listTasks", "sendToBaboom", "setTaskStatus",
    "reassignTask", "setTaskDelegate", "queueTaskMessage", "settleQueuedMessage",
    "steerTask", "addTaskReview", "resolveTaskReview"})
LABELS = {"claude":"Claude", "codex":"Codex", "antigravity":"Antigravity",
          "antigravity-ide":"Antigravity", "gemini":"Gemini", "opencode":"OpenCode",
          "goose":"Goose", "baboom":"BABOOM"}
STATES = {"open":"PLANNED", "claimed":"WIP", "blocked":"PLANNED",
          "review":"IN REVIEW", "complete":"DONE", "cancelled":"ARCHIVED"}


class WorkshopAPI:
    def __init__(self, owner, binding, root, scope, *, guard, request_id, route, message_limit=1000):
        self.owner, self.binding, self.root, self.scope = owner, binding, root, scope
        self.guard, self.request_id = guard, request_id
        self.message_limit = message_limit
        self.route = route

    def admit(self):
        from .existing_workshop_conversation import _admit
        self.guard()
        snapshot, _ = _admit(self.owner, self.binding, self.root, self.scope)
        authority = self.owner.universal_registry.authorization
        if self.binding.subject_root != authority.subject_root:
            raise AuthorizationDenied("Workshop task data belongs to this account")
        return snapshot

    def history(self):
        self.admit()
        service, registry = self.owner.conversation_content, self.owner.universal_registry
        binding = service._authorize_content_read(self.owner.universal_store.snapshot(), registry,
            space_root=self.root, authentication_context=self.binding.context,
            principal=self.binding.subject_root, machine=False)
        return service._history_for(binding)

    def _options(self, task):
        snapshot = self.admit()
        cell = snapshot.cells.get(task + ":workshop-options")
        return json.loads(cell.atom) if cell else {"reviews":[], "queuedMessages":[]}

    def _save(self, task, values):
        from .universal_application import _view_session_for_context, _commit_universal_user_change
        self._work(task)
        store, registry = self.owner.universal_store, self.owner.universal_registry
        snapshot = self.admit()
        view, context = _view_session_for_context(registry, self.binding.context)
        cell = Cell(task + ":workshop-options", task, self.binding.subject_root,
                    json.dumps(values, ensure_ascii=False, separators=(",", ":")).encode())
        if len(cell.atom) > 65536:
            raise InvalidCell("Task options exceed the existing bounded property budget")
        exists = cell.id in snapshot.cells
        if exists and snapshot.cells[cell.id] == cell:
            return
        patch = prepare_append_relation_members(snapshot, task,
            () if exists else ((registry.roles["member"], cell.id),))
        self.guard()
        _commit_universal_user_change(store, registry, view, context, snapshot,
            route=self.route, command_name="catalog.configure",
            authorization_scope_root=self.root, create=(*patch.create, *((cell,) if not exists else ())),
            replace=(*patch.replace, *((cell,) if exists else ())))

    def _works(self):
        from .universal_application import project_universal_governed_work
        from .workshop_work_creation import _work_scope
        self.admit()
        rows = project_universal_governed_work(self.owner.universal_store,
            self.owner.universal_registry, authentication_context=self.binding.context)
        snapshot = self.admit()
        return [row for row in rows if _work_scope(snapshot, self.owner.universal_registry,
                                                   row["root"]) == self.root]

    def _work(self, task):
        if type(task) is not str:
            raise InvalidCell("Task id must be an existing Work root")
        rows = [row for row in self._works() if row["root"] == task]
        if len(rows) != 1:
            raise InvalidCell("Task is outside this Workshop")
        return rows[0]

    def _messages(self, task):
        history = self.history()
        category = self.owner.universal_registry.workshop_category_roots["note"]
        roots = history.messages_referencing(self.root,task,categories=(category,),limit=self.message_limit)
        truncated = len(roots) == self.message_limit
        selected = {}
        for row in roots:
            visible = history.get(self.root,row["id"],principal=self.binding.subject_root)
            if visible:
                selected[row["id"]] = visible
        frontier = list(selected)
        while frontier and len(selected) < self.message_limit:
            batch, frontier = frontier[:200], frontier[200:]
            page = history.replies_to(self.root,batch,principal=self.binding.subject_root,
                                      limit=min(500,self.message_limit-len(selected)))
            truncated = truncated or page['truncated']
            for row in page["messages"]:
                if row["id"] not in selected and row["category"] == category:
                    selected[row["id"]] = row
                    frontier.append(row["id"])
        truncated = truncated or bool(frontier)
        return [{"id":row["id"],"who":row["author"],"text":row["content"],
            "reply_to":row["reply_to"],"sequence":row["sequence"],
            "created_at":row["created_at"],"state":"stored"}
            for row in sorted(selected.values(),key=lambda item:item["sequence"])], truncated

    def listAgentsWorking(self):
        from .agent_declarations import declarations
        self.admit()
        grouped = {}
        for row in declarations(self.owner):
            if row["status"] != "working" or row["request_id"] == "unassigned":
                continue
            app = row["app"]
            provider = grouped.setdefault(app, {"id":app, "name":LABELS.get(app, app),
                "enabled":True, "signedIn":None, "presence":"working", "model":"Unavailable",
                "sessions":[]})
            provider["sessions"].append(row)
        return list(grouped.values())

    def _task(self, row):
        from .agent_declarations import declarations
        task = row["root"]
        options = self._options(task)
        state = str(row["operational"]["current_state_label"]).casefold()
        status = STATES[state]
        active = [item for item in declarations(self.owner) if item["request_id"] == task]
        if state == "open" and any(item["status"] == "working" for item in active):
            status = "WIP"
        owners = {item["app"] for item in active}
        owner = next(iter(owners)) if len(owners) == 1 else options.get("delegate")
        interfaces = row["interfaces"]
        messages, messages_truncated = self._messages(task)
        delivery = options.get("delivery", {"state":"unassigned"})
        if messages:
            from .workshop_delivery_state import project_delivery, work_pending_digests
            history = self.history()
            raw = [history.get(self.root,item["id"],principal=self.binding.subject_root) for item in messages[-200:]]
            replies = history.replies_to(self.root,[item["id"] for item in raw],principal=self.binding.subject_root)
            registry = self.owner.universal_registry
            states,_ = project_delivery(raw,replies["messages"],relay_pending=work_pending_digests(self.owner),
                note_category=registry.workshop_category_roots["note"],
                tool_category=registry.workshop_category_roots["tool"],relay_author=registry.authorization.subject_root)
            latest = next((states[item["id"]] for item in reversed(messages)
                if item["id"] in states and states[item["id"]]["state"] != "stored"), None)
            if latest:
                delivery = latest
        return {"id":task, "title":interfaces["title"]["value"], "owner":owner,
            "status":status, "messages":messages, "messagesTruncated":messages_truncated,
            "messagesContinuation":({"tool":"read","arguments":{"since":0},"work_root":task}
                if messages_truncated else None), "steps":[],
            "sources":[], "usage":None, "reviews":options.get("reviews", []),
            "queuedMessages":[item for item in options.get("queuedMessages", []) if item["state"] == "queued"], "delegate":options.get("delegate"),
            "blocked":state == "blocked" or any(item["status"] == "blocked" for item in active),
            "declarations":active, "delivery":delivery,
            "revision":self.owner.universal_store.revision}

    def listTasks(self):
        return [self._task(row) for row in self._works()]

    def _append(self, task, text, *, key, reply_to=None):
        self._work(task)
        registry = self.owner.universal_registry
        options = self._options(task)
        delegate = options.get("delegate") or "BABOOM"
        self.guard()
        return self.owner.conversation_content.append_authenticated(space_root=self.root,
            actor_root=self.binding.subject_root, category_root=registry.workshop_category_roots["note"],
            content="To " + delegate + ":\n" + _text(text), idempotency_key=key,
            recipient_roots=(), reference_roots=(task,), reply_to_root=reply_to,
            authentication_context=self.binding.context,
            expected_revision=self.owner.universal_store.revision)["message"]

    def _route(self, task, message):
        """Use the existing native contact effect; never launch a second router."""
        from .native_contact import _discover, bind_native_contact, read_contact
        options = self._options(task)
        previous = options.get("delivery", {})
        if options.get("dispatch_message") == message["id"]:
            # The durable relay outcome supersedes the initially saved
            # 'started' projection; a definitive non-dispatch may be retried.
            previous = self._task(self._work(task))["delivery"]
        if options.get("dispatch_message") == message["id"] and (
                not isinstance(previous,dict) or previous.get("state") not in {"not_sent","unavailable"}):
            return
        provider = options.get("delegate")
        if provider and provider not in {"claude","codex","opencode","antigravity","antigravity-ide"}:
            options.update(delivery={"state":"not_sent","reason":"selected_provider_requires_its_existing_builtin_workflow"},
                dispatch_message=message["id"])
            self._save(task,options)
            return
        delivery = {"state":"not_sent", "reason":"no_available_native_agent"}
        found = _discover(self.owner, [provider] if provider in {"claude","codex","opencode","antigravity","antigravity-ide"}
                          else ["claude","codex","opencode","antigravity","antigravity-ide"])
        candidates = found.get("recipients", []) if type(found) is dict and found.get("status") == "ok" else []
        if len(candidates) == 1:
            target = candidates[0]
            try:
                contact_scope = self.owner.universal_registry.workshop_workbench_root
                def guard():
                    self.guard()
                    self.owner.require_universal_http_route("POST", "/api/universal/native-contact",
                        authentication_context=self.binding.context, revalidate=True)
                contact = bind_native_contact(self.owner, self.binding,
                    {"root":self.root,"scope":contact_scope,"app":target["app"],
                     "session_id":target["id"],"revision":self.owner.universal_store.revision}, browser_guard=guard)
                def revalidate():
                    guard()
                    return read_contact(self.owner,self.binding,contact["contact"],contact["binding_digest"],
                                        self.root,self.scope)
                delivery = self.owner.native_work_delivery.request_contact(space_root=self.root,
                    message_id=message["id"],sender_root=self.binding.subject_root,
                    contact_root=contact["contact"],endpoint=revalidate(),revalidate=revalidate,
                    text="Workshop task " + task)
                options["delegate"] = target["app"]
            except (AuthorizationDenied, InvalidCell, ValueError):
                delivery = {"state":"not_sent", "reason":"native_contact_admission_unavailable"}
        elif candidates:
            delivery = {"state":"not_sent", "reason":"recipient_not_exactly_one_live_session"}
        options.update(delivery=delivery, dispatch_message=message["id"])
        self._save(task, options)

    def sendToBaboom(self, text, options=None):
        from .workshop_work_creation import create_browser_workshop_work
        options = {} if options is None else options
        if type(options) is not dict or set(options) - {"provider", "taskId"}:
            raise InvalidCell("Task options accept provider and taskId")
        text = _text(text)
        task = options.get("taskId")
        if task is None:
            result = create_browser_workshop_work(self.owner, self.binding,
                {"workshop_root":self.root, "workshop_scope":self.scope,
                 "revision":self.admit().revision, "title":text[:90], "description":text,
                 "external_key":"workshop-api:" + self.request_id, "projection":False},
                browser_guard=self.guard)
            task = result["created_root"]
        self._work(task)
        if "provider" in options:
            self.setTaskDelegate(task, options["provider"])
        message = self._append(task, text, key="workshop-api:" + self.request_id + ":message")
        self._route(task, message)
        return self._task(self._work(task))

    def setTaskStatus(self, id, status):
        if type(status) is not str or status not in set(STATES.values()):
            raise InvalidCell("Choose PLANNED, WIP, IN REVIEW, DONE or ARCHIVED")
        task = self._task(self._work(id))
        if task["status"] != status and (status == "ARCHIVED" or
                task["status"] == "ARCHIVED" and status == "PLANNED"):
            from .universal_application import _founder_governed_work_evidence_transition
            _founder_governed_work_evidence_transition(self.owner.universal_store,
                self.owner.universal_registry, id, "cancel" if status == "ARCHIVED" else "restore",
                {"request_id":self.request_id, "reason":"User moved the existing Workshop task"},
                authentication_context=self.binding.context, commit_guard=lambda _snapshot:self.guard())
            return self._task(self._work(id))
        if task["status"] != status:
            raise InvalidCell("Task state follows its live owner and verified Work transitions; "
                              "a display status cannot claim execution or completion")
        return task

    def setTaskDelegate(self, id, providerId):
        if type(providerId) is not str or providerId not in LABELS:
            raise InvalidCell("Unknown provider")
        task = self._task(self._work(id))
        if task["declarations"] and any(row["app"] != providerId for row in task["declarations"]):
            raise InvalidCell("The current owner must report its result or yield before handoff")
        options = self._options(id)
        if options.get("delegate") == providerId:
            return self._task(self._work(id))
        options.update(delegate=providerId, delivery={"state":"stored"})
        self._save(id, options)
        return self._task(self._work(id))

    def reassignTask(self, id):
        from .agent_declarations import declarations
        task = self._task(self._work(id))
        candidates = {row["app"] for row in declarations(self.owner)
            if row["app"] != task["owner"] and row["request_id"] == "unassigned"
            and any(path.startswith(root + "/") or path == root
                    for path in row["paths"] for root in [str(self.owner.universal_workspace_root).replace("\\", "/").casefold()])}
        if len(candidates) != 1:
            raise InvalidCell("No unique available capable replacement; keep the existing task and owner")
        self.setTaskDelegate(id, next(iter(candidates)))
        message=self._append(id,"Continue the existing task after the previous owner yielded.",
            key="workshop-reassign:"+self.request_id)
        self._route(id,message)
        return self._task(self._work(id))

    def queueTaskMessage(self, id, text):
        self._work(id)
        options = self._options(id)
        key = "queued:" + self.request_id
        old = next((row for row in options["queuedMessages"] if row["id"] == key), None)
        message = {"id":key, "text":_text(text), "state":"queued"}
        if old and old != message:
            raise InvalidCell("Queued message request id already names another message")
        if not old:
            options["queuedMessages"].append(message)
            self._save(id, options)
        return message

    def settleQueuedMessage(self, taskId, messageId, send):
        if type(send) is not bool:
            raise InvalidCell("Queue settlement requires a boolean")
        self._work(taskId)
        options = self._options(taskId)
        row = next((row for row in options["queuedMessages"] if row["id"] == messageId), None)
        if row is None:
            raise InvalidCell("Queued message is unavailable")
        if row["state"] != "queued":
            if (row["state"] == "sent") != send:
                raise InvalidCell("Queued message was already settled differently")
            return row
        message = self._append(taskId, row["text"], key=messageId) if send else None
        row.update(state="sent" if send else "withdrawn", messageId=message["id"] if message else None)
        self._save(taskId, options)
        if message:
            self._route(taskId,message)
        return row

    def steerTask(self, id, instruction):
        message=self._append(id, instruction, key="workshop-steer:" + self.request_id)
        self._route(id,message)
        return self._task(self._work(id))

    def addTaskReview(self, id, scope, comment):
        self._work(id)
        options = self._options(id)
        review = {"id":"review:" + self.request_id, "scope":_text(scope),
                  "comment":_text(comment), "resolved":False, "author":self.binding.subject_root}
        old = next((row for row in options["reviews"] if row["id"] == review["id"]), None)
        if old and any(old[key] != review[key] for key in ("scope", "comment", "author")):
            raise InvalidCell("Review request id already names another review")
        if not old:
            options["reviews"].append(review)
            self._save(id, options)
        return self._task(self._work(id))

    def resolveTaskReview(self, taskId, index, resolved):
        self._work(taskId)
        options = self._options(taskId)
        if type(index) is not int or not 0 <= index < len(options["reviews"]) or type(resolved) is not bool:
            raise InvalidCell("Review settlement is invalid")
        options["reviews"][index]["resolved"] = resolved
        self._save(taskId, options)
        return options["reviews"][index]


def _text(value):
    if type(value) is not str or not value.strip() or len(value.encode()) > 32000 or "\0" in value:
        raise InvalidCell("Task text must contain 1–32000 UTF-8 bytes")
    return value.strip()


def dispatch(owner, binding, body, *, guard, route):
    fields = {"action", "function", "args", "root", "scope", "request_id"}
    if (type(body) is not dict or set(body) != fields or body["action"] != "data-api"
            or type(body["function"]) is not str or body["function"] not in FUNCTIONS
            or type(body["args"]) is not list or len(body["args"]) > 3
            or type(body["request_id"]) is not str or not 1 <= len(body["request_id"]) <= 128):
        raise InvalidCell("Workshop data function request is invalid")
    api = WorkshopAPI(owner, binding, body["root"], body["scope"], guard=guard,
                      request_id=hashlib.sha256(body["request_id"].encode()).hexdigest(), route=route)
    with owner.mutation_lock, owner.universal_registry.authorization.broker.live_context(binding.context):
        api.admit()
        try:
            result = getattr(api, body["function"])(*body["args"])
        except TypeError as exc:
            raise InvalidCell("Workshop data function arguments are invalid") from exc
        return {"ok":True, "result":result, "revision":owner.universal_store.revision}
