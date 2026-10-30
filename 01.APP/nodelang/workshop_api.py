"""Design-named data functions over the existing Workshop Work and content owners.

No UI, provider simulation, task database or execution authority is introduced.
Task status is projected from committed Work state and live declarations.
"""
import hashlib
import json
from contextlib import nullcontext

from .cell_authorization import AuthorizationDenied
from .cell_protocols import prepare_append_relation_members
from .universal_cell import Cell, InvalidCell


FUNCTIONS = frozenset({"listAgentsWorking", "listTasks", "listWorkshopMessages", "sendToBaboom", "setTaskStatus",
    "reassignTask", "setTaskDelegate", "queueTaskMessage", "settleQueuedMessage",
    "steerTask", "addTaskReview", "resolveTaskReview", "setTaskActivity"})
LABELS = {"claude":"Claude", "codex":"Codex", "antigravity":"Antigravity",
          "antigravity-ide":"Antigravity", "gemini":"Gemini", "opencode":"OpenCode",
          "goose":"Goose", "baboom":"BABOOM"}
STATES = {"open":"PLANNED", "claimed":"WIP", "blocked":"PLANNED",
          "review":"IN REVIEW", "complete":"DONE", "cancelled":"ARCHIVED"}


def _message_identity(author, declared, subject_root):
    row = next((item for item in declared
                if author.endswith(" [" + item["session"] + "]")), None)
    if row is None:
        return {"who": "You" if author == subject_root else author, "author": author,
                "sender_key": author, "viewer_key": subject_root}
    return {"who": row.get("display_name") or LABELS.get(row["app"], row["agent"].split(" / ", 1)[0]),
            "model": row.get("model"), "provider": row["app"], "author": author,
            "sender_key": row["session"], "viewer_key": subject_root}


class WorkshopAPI:
    def __init__(self, owner, binding, root, scope, *, guard, request_id, route, message_limit=1000):
        self.owner, self.binding, self.root, self.scope = owner, binding, root, scope
        self.guard, self.request_id = guard, request_id
        self.message_limit = message_limit
        self.route = route

    def readDesktop(self):
        from .desktop_owner import DesktopOwner
        return DesktopOwner(self).read()

    def readResearchState(self):
        from .research_owner import ResearchOwner
        return ResearchOwner(self).read()

    def runValuation(self, id):
        from .research_owner import ResearchOwner
        return ResearchOwner(self).run(id,valuation=True)

    def runResearchNode(self, id):
        from .research_owner import ResearchOwner
        return ResearchOwner(self).run(id)

    def setResearchReview(self, id, values):
        from .research_owner import ResearchOwner
        return ResearchOwner(self).review(id,values)

    def correctAnswerSource(self, message, index, values):
        from .research_owner import ResearchOwner
        return ResearchOwner(self).correct(message,index,values)

    def setDesktopProgram(self, program):
        from .desktop_owner import DesktopOwner
        return DesktopOwner(self).set_program(program)

    def offerDesktopAction(self):
        from .desktop_owner import DesktopOwner
        return DesktopOwner(self).offer()

    def prepareDesktopAction(self):
        from .desktop_owner import DesktopOwner
        return DesktopOwner(self).prepare()

    def setScheduleResponsibility(self, root, values):
        from .desktop_owner import DesktopOwner
        return DesktopOwner(self).responsibility(root, values)

    def reviewScheduledWork(self, root):
        from .desktop_owner import DesktopOwner
        return DesktopOwner(self).review_schedule(root)

    def readHostSkills(self):
        from .host_skill_owner import HostSkillOwner
        return HostSkillOwner(self).read()

    def importHostSkill(self, value):
        from .host_skill_owner import HostSkillOwner
        return HostSkillOwner(self).import_skill(value)

    def inspectConnectorBundle(self, value):
        from .host_skill_owner import HostSkillOwner
        return HostSkillOwner(self).inspect(value)

    def configureConnectorBundle(self, root, key, value):
        from .host_skill_owner import HostSkillOwner
        return HostSkillOwner(self).configure(root, key, value)

    def installConnectorBundle(self, root):
        from .host_skill_owner import HostSkillOwner
        return HostSkillOwner(self).request(root, "install")

    def setHostSkillEnabled(self, root, enabled):
        from .host_skill_owner import HostSkillOwner
        return HostSkillOwner(self).set_enabled(root, enabled)

    def auditHostSkill(self, root):
        from .host_skill_owner import HostSkillOwner
        return HostSkillOwner(self).audit(root)

    def readWatcher(self):
        from .watcher_owner import WatcherOwner
        return WatcherOwner(self).read()

    def setWatcherHost(self, host):
        from .watcher_owner import WatcherOwner
        return WatcherOwner(self).set_host(host)

    def setWatcherView(self, view):
        from .watcher_owner import WatcherOwner
        return WatcherOwner(self).set_view(view)

    def editWall(self, y):
        from .watcher_owner import WatcherOwner
        return WatcherOwner(self).edit(y)

    def addDimension(self, values):
        from .watcher_owner import WatcherOwner
        return WatcherOwner(self).annotate("dimension", values)

    def addMark(self, values):
        from .watcher_owner import WatcherOwner
        return WatcherOwner(self).annotate("mark", values)

    def addComment(self, values):
        from .watcher_owner import WatcherOwner
        return WatcherOwner(self).annotate("comment", values)

    def proposeWatcherEdit(self):
        from .watcher_owner import WatcherOwner
        return WatcherOwner(self).propose()

    def discardWatcherChanges(self):
        from .watcher_owner import WatcherOwner
        return WatcherOwner(self).discard()

    def answerApproval(self, kind, root, digest, decision):
        """Every Approve/Deny card (desktop, schedule, hostskills, watcher): the one decision."""
        from .hook_decision import decide
        from .host_skill_owner import HostSkillOwner
        return decide({"approval": kind, "owner": HostSkillOwner(self) if kind == "hostskills" else self,
                       "id": root, "digest": digest, "decision": decision})

    def listApprovals(self):
        from .social_approval import list_reviews
        return list_reviews(self)

    def postponeApproval(self, id):
        from .social_approval import change_review
        return change_review(self, id, "postponeApproval")

    def resumeApproval(self, id):
        from .social_approval import change_review
        return change_review(self, id, "resumeApproval")

    def contestDecision(self, id, reason):
        from .social_approval import change_review
        return change_review(self, id, "contestDecision", reason)

    def refreshApproval(self, id):
        from .social_approval import change_review
        return change_review(self, id, "refreshApproval")

    def reviewProofRow(self, id, index, decision):
        from .social_approval import change_review
        return change_review(self, id, "reviewProofRow", index, decision)

    def setApprovalRubric(self, id, item, checked):
        from .social_approval import change_review
        return change_review(self, id, "setApprovalRubric", item, checked)

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
            self.owner.universal_registry, authentication_context=self.binding.context,
            workshop_root=self.root)
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
        from .research_owner import ResearchOwner
        research = ResearchOwner(self)
        from .workshop_mailbox import delivery_events
        from .workshop_delivery_state import project_injection_delivery
        from .agent_declarations import declarations
        declared = declarations(self.owner, include_archived=True)
        with history._transaction():
            events = {row["id"]: delivery_events(history, row) for row in selected.values()}
        return [{"id":row["id"], **_message_identity(row["author"], declared, self.binding.subject_root), "text":row["content"],
            **research.sources(row['id'],row.get('evidence',[]),row.get('refs',[task])),
            "reply_to":row["reply_to"],"sequence":row["sequence"],
            "created_at":row["created_at"], **project_injection_delivery(events[row["id"]])}
            for row in sorted(selected.values(),key=lambda item:item["sequence"])], truncated

    def _notification_root(self, id):
        return self.root + ':notification:' + hashlib.sha256(
            (self.binding.subject_root + ':' + id).encode()).hexdigest()

    def listNotifications(self):
        snapshot = self.admit()
        notifications = []
        seen = set()
        for work in sorted(self._works(), key=lambda row: row['root']):
            messages, _truncated = self._messages(work['root'])
            for message in messages:
                if message['who'] == self.binding.subject_root or message['id'] in seen:
                    continue
                seen.add(message['id'])
                root = self._notification_root(message['id'])
                receipt = snapshot.cells.get(root)
                notifications.append({'id': message['id'], 'text': message['text'], 'taskId': work['root'],
                    'read': bool(receipt and receipt.link0 == work['root'] and
                                 receipt.link1 == self.binding.subject_root and json.loads(receipt.atom).get('read'))})
        return {'notifications': notifications}

    def readNotification(self, id):
        from .universal_application import _view_session_for_context, _commit_universal_user_change
        if type(id) is not str:
            raise InvalidCell('Choose an existing notification.')
        matches = [row for row in self.listNotifications()['notifications'] if row['id'] == id]
        if len(matches) != 1:
            raise InvalidCell('Notification is outside this account or no longer available.')
        row = matches[0]
        store, registry = self.owner.universal_store, self.owner.universal_registry
        snapshot = self.admit()
        root = self._notification_root(id)
        cell = Cell(root, row['taskId'], self.binding.subject_root,
                    json.dumps({'message': id, 'read': True}).encode())
        if snapshot.cells.get(root) != cell:
            exists = root in snapshot.cells
            patch = prepare_append_relation_members(snapshot, row['taskId'],
                () if exists else ((registry.roles['member'], root),))
            view, context = _view_session_for_context(registry, self.binding.context)
            self.guard()
            _commit_universal_user_change(store, registry, view, context, snapshot,
                route=self.route, command_name='catalog.configure', authorization_scope_root=self.root,
                create=(*patch.create, *((cell,) if not exists else ())),
                replace=(*patch.replace, *((cell,) if exists else ())))
        return {**self.listNotifications(), 'receipt': root}

    def listAgentsWorking(self):
        from datetime import datetime
        from .agent_declarations import declarations, _alive
        from .agent_runtime_registry import RUNTIMES, discover_runtime_processes, observed_runtime_process
        from .workshop_activity import observer_for
        from .model_router import redact_user_visible
        import psutil
        self.admit()
        aliases = {'claude-code':'claude', 'gemini-cli':'gemini', 'opencode-cli':'opencode'}
        complete = True
        unavailable = False
        try:
            observed = discover_runtime_processes()
        except (OSError, RuntimeError, ValueError, ImportError, psutil.Error):
            observed = {'processes':[], 'complete':False, 'observed_at':None}
            unavailable = True
        complete &= observed['complete']
        try:
            declared = declarations(self.owner, include_archived=True)
            reader = observer_for(self.owner)
            if reader is not None:
                reader.poll()
                with reader.lock:
                    lifecycle = {key:dict(value) for key, value in reader.sessions.items()}
                    complete &= not (reader.partial or reader.unavailable)
                    unavailable |= reader.unavailable
            else:
                lifecycle = {}
        except (OSError, RuntimeError, ValueError):
            declared, lifecycle, complete = [], {}, False
            unavailable = True
        titles = {}
        for work in self._works():
            title = work['interfaces'].get('title', {}).get('value')
            if title:
                titles[work['root']] = title
                titles[work['interfaces'].get('external-key', {}).get('value')] = title
        grouped, claimed = {}, set()
        def updated(declaration):
            stamp = declaration.get('updated_at', 0)
            if isinstance(stamp, str):
                try:
                    return datetime.fromisoformat(stamp.replace('Z', '+00:00')).timestamp()
                except ValueError:
                    return float('inf')
            return stamp
        for declaration in sorted(declared, key=updated):
            runtime = aliases.get(declaration.get('runtime') or declaration['app'], declaration.get('runtime') or declaration['app'])
            native = declaration.get('native_process') or declaration
            try:
                live = _alive(native, strict=True)
            except (psutil.Error, OSError):
                live, complete = None, False
            generation = (runtime, native['pid'], native['created_at'])
            if live:
                claimed.add(generation)
                if declaration.get('native_process'):
                    from types import SimpleNamespace
                    try:
                        current = observed_runtime_process(SimpleNamespace(**native), strict=True)
                        if current and current['runtime'] == runtime:
                            claimed.add((runtime, current['pid'], current['created_at']))
                    except (psutil.Error, OSError):
                        live, complete = None, False
            session = declaration.get('native_session_id') or declaration['session']
            key = (runtime, session)
            row = grouped.setdefault(key, {'id':runtime + ':' + session if declaration.get('native_session_id') else declaration['session'], 'runtime':runtime,
                'name':declaration.get('display_name') or RUNTIMES.get(runtime, {}).get('label') or LABELS.get(runtime, runtime),
                'session':session, 'title':declaration['agent'], 'sessions':[],
                'presence':'not-running', 'model':'Model not reported', 'task':'Task not reported',
                'evidence':'declaration', 'observed_at':observed['observed_at']})
            row['sessions'].append(declaration)
            row['name'] = declaration.get('display_name') or RUNTIMES.get(runtime, {}).get('label') or LABELS.get(runtime, runtime)
            row['title'] = declaration['agent']
            if declaration.get('model'):
                row['model'] = declaration['model']
            task = titles.get(declaration.get('request_id')) or declaration.get('task')
            if task:
                row['task'] = task
            if not live:
                row['presence'] = 'unknown' if live is None else 'not-running'
                continue
            status = {'working':'working', 'done':'idle', 'blocked':'needs-attention'}.get(declaration['status'], 'unknown')
            event = lifecycle.get((runtime, session))
            stamp = updated(declaration)
            if stamp == float('inf'):
                status = 'unknown'
            if event and event['at'] >= max(stamp, native['created_at']):
                status = 'idle' if event['state'] == 'turn_ended' else 'working'
            row['presence'] = status
        for process in observed['processes']:
            runtime = process['runtime']
            generation = (runtime, process['pid'], process['created_at'])
            if generation in claimed:
                continue
            identity = '%s:%s:%s' % generation
            grouped[(runtime, identity)] = {'id':identity, 'runtime':runtime,
                'name':RUNTIMES.get(runtime, {}).get('label') or LABELS.get(runtime, runtime),
                'session':identity, 'title':'Session identity not confirmed', 'sessions':[],
                'presence':'working', 'task':'Task not reported', 'model':'Model not reported',
                'evidence':'native-process', 'observed_at':observed['observed_at']}
        result = list(grouped.values())
        if not complete and not result:
            result.append({'id':'agent-observation', 'kind':'observation', 'name':'Agent status',
                'presence':'unknown', 'sessions':[]})
        for row in result:
            row['observation_complete'] = complete
            if unavailable:
                row['presence'] = 'unknown'
            row['status_text'] = {'working':'Working', 'idle':'Idle', 'not-running':'Not running',
                'needs-attention':'Needs attention', 'unknown':'Status unknown'}[row['presence']]
            row['detail'] = {'working':'Runtime is running; task details are not available.' if row.get('task') == 'Task not reported' else '',
                'idle':'Waiting for work.', 'not-running':'', 'needs-attention':'This agent could not continue its task.',
                'unknown':'ArchHub could not check this agent.'}[row['presence']]
            for field in ('task', 'title', 'model', 'name'):
                if row.get(field):
                    row[field] = redact_user_visible(row[field])
        return result

    def _task(self, row):
        from .agent_declarations import declarations
        task = row["root"]
        options = self._options(task)
        state = str(row["operational"]["current_state_label"]).casefold()
        status = STATES[state]
        external_key = row['interfaces'].get('external-key', {}).get('value')
        known = [item for item in declarations(self.owner, include_archived=True) if item["request_id"] in (task, external_key)]
        active = [item for item in known if item.get("current")]
        if state == "open" and any(item["status"] == "working" for item in active):
            status = "WIP"
        owners = {item["app"] for item in active}
        previous = {item["app"] for item in known}
        owner = next(iter(owners)) if len(owners) == 1 else options.get("delegate")
        if owner is None:
            from .cell_agent_body import read_agent_session
            from .universal_application import _agent_body_catalog_entry_for_session
            claim = next((event for event in reversed(row["operational"].get("history", []))
                          if event["event_label"].casefold() == "claim"), None)
            recorded = set()
            if claim:
                snapshot, registry = self.admit(), self.owner.universal_registry
                for root in claim["context"]:
                    if not root.startswith("app:agent-session:runtime:"):
                        continue
                    try:
                        session = read_agent_session(snapshot, registry.agent_body.protocol,
                                                     registry.authorization.protocol, root)
                        recorded.add(_agent_body_catalog_entry_for_session(snapshot, registry, session).runtime)
                    except (InvalidCell, AuthorizationDenied):
                        continue  # An unavailable old session must not hide the task.
            owner = (next(iter(recorded)) if len(recorded) == 1 else
                     next(iter(previous)) if not recorded and len(previous) == 1 else None)
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
        from .workshop_activity import observer_for
        reader = observer_for(self.owner)
        activity = None
        if reader is not None:
            config = options.get('activity')
            if config is None:
                paths = {reader.relative(path) for item in known for path in item.get('paths', [])}
                config = {'owns':[('**' if not path else path + '/**') if (reader.root / path).is_dir() else path
                                  for path in paths if path is not None]}
            def emit(identity, text):
                self.history().append(self.root, author='Workshop observation', content=text,
                    category=self.owner.universal_registry.workshop_category_roots['note'],
                    refs=(task,), idempotency_key='activity-handoff:' + identity)
            activity = reader.project(task, reader.ledger_config(external_key, config), emit=emit,
                declared_sessions={(item.get('app'), item.get('native_session_id')) for item in active},
                conflicting_sessions={(item.get('app'), item.get('native_session_id'))
                    for item in declarations(self.owner) if item.get('request_id') not in (task, external_key)})
            if activity['stale']:
                for item in active:
                    if not item.get('agent') or not item.get('native_session_id'):
                        continue
                    identity = hashlib.sha256(json.dumps([task, reader.ledger_stamp,
                        config.get('updated_at'), item['native_session_id']]).encode()).hexdigest()
                    self.history().append(self.root, author='Workshop observation',
                        content='To ' + item['agent'] + ':\nRe-verify row status on ' + task + '; owned files changed after its ledger update.',
                        category=self.owner.universal_registry.workshop_category_roots['note'],
                        refs=(task,), idempotency_key='activity-stale:' + identity)
            unobserved = any(item.get('app') not in ('codex','claude','opencode') for item in active)
            if activity['ownership'] == 'known' and not unobserved and state in ('open', 'claimed'):
                status = 'WIP' if any(item['state'] in ('working', 'tool_ended') for item in activity['sessions']) else 'PLANNED'
        return {"id":task, "title":interfaces["title"]["value"], "owner":owner,
            "status":status, "messages":messages, "messagesTruncated":messages_truncated,
            "messagesContinuation":({"tool":"read","arguments":{"since":0},"work_root":task}
                if messages_truncated else None), "steps":[],
            "sources":[], "usage":None, "reviews":options.get("reviews", []),
            "queuedMessages":[item for item in options.get("queuedMessages", []) if item["state"] == "queued"], "delegate":options.get("delegate"),
            "blocked":state == "blocked" or any(item["status"] == "blocked" for item in active),
            "declarations":active, "delivery":delivery, "activity":activity,
            # WIRE-agents: restore only saved task parameters; never claim Work completion.
            "planMode":options.get("planMode"), "checkpoints":options.get("checkpoints",[]),
            "revision":self.owner.universal_store.revision}

    def listTasks(self):
        from .workshop_activity import observer_for
        reader = observer_for(self.owner)
        if reader is not None:
            reader.poll()
            from .agent_declarations import declarations
            reader.poll_opencode(getattr(self.owner, '_cloud_relay_transport', None),
                [row['native_session_id'] for row in declarations(self.owner)
                 if row.get('app') == 'opencode' and type(row.get('native_session_id')) is str])
        return [self._task(row) for row in self._works()]

    def setTaskActivity(self, task, values):
        """Keep ledger ownership/install facts in this Work's existing parameters."""
        from .workshop_activity import ownership
        try:
            activity = ownership(values)
        except ValueError as exc:
            raise InvalidCell(str(exc)) from exc
        options = self._options(task)
        self._save(task, {**options, 'activity':activity})
        return self._task(self._work(task))

    def listWorkshopMessages(self, before=None):
        """The existing public room, including notes that have no Work reference."""
        from .workshop_mailbox import CATEGORY, agent_addressed, delivery_events
        from .workshop_delivery_state import project_injection_delivery
        if before is not None and (type(before) is not int or before < 1):
            raise InvalidCell("Workshop message cursor is invalid")
        from .workshop_mailbox import application_history, read_declarations
        with application_history() as history:
            declared = read_declarations(history._db, include_archived=True)
            with history._transaction():
                rows, more = history._collect(history._db.execute("SELECT * FROM messages WHERE conversation_id=? "
                    "AND category=? AND public=1 AND (? IS NULL OR sequence<?) ORDER BY sequence DESC LIMIT 101",
                    ("app:workshop", CATEGORY, before, before)), 100, 180000)
                events = {row["id"]: delivery_events(history, row) for row in rows}
        messages = [{"id":row["id"], **_message_identity(row["author"], declared, self.binding.subject_root), "text":row["content"],
            "reply_to":row["reply_to"], "sequence":row["sequence"], "created_at":row["created_at"],
            **project_injection_delivery(events[row["id"]], addressed=agent_addressed(row))}
            for row in reversed(rows)]
        return {"messages":messages, "more":more, "next_before":rows[-1]["sequence"] if rows else None}

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
        # Re-read Settings at dispatch; a saved choice is never execution authority.
        from .settings_owner import SettingsOwner
        settings = SettingsOwner(self.owner.universal_store, runtime=self.owner,
            authentication_context=self.binding.context).executionContext(self.scope)
        if settings['workspaces']:
            text += '\n\nWorkspace policy from the Settings owner (apply only within existing access):\n' + json.dumps(
                settings['workspaces'], ensure_ascii=False)
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


    # WIRE-agents: parameters extend the current admitted graph and task owner.
    def _surface_rows(self):
        from .canvas_graph_owner import CanvasOwner
        self.admit()
        return CanvasOwner(self.owner.universal_store, self.owner.universal_registry,
                           self.binding.context)

    def _surface_node(self, create=False):
        ops=self._surface_rows()
        canvas=ops.canvas()
        found=[n['id'] for n in canvas['nodes'] if
            ops._rows(None,n['id']).get('wire_agents_owner',{}).get('value')==self.root]
        if len(found)>1:raise InvalidCell('More than one Agent settings node; merge its parameters before editing')
        if found:return ops,found[0]
        if not create:return ops,None
        from .universal_pipeline import create_engine_node
        node=create_engine_node(self.owner.universal_store,self.owner.universal_registry,
            title='Agent settings',engine='data.constant',properties={'wire_agents_owner':self.root},
            authentication_context=self.binding.context)
        return ops,node['root']

    def _parameter(self, name, default=None):
        ops,root=self._surface_node()
        held=ops._rows(None,root).get(name) if root else None
        return json.loads(held['value']) if held else default

    def _put_parameter(self, name, value):
        encoded=json.dumps(value,ensure_ascii=False,allow_nan=False)
        if len(encoded.encode('utf-8'))>65536:
            raise InvalidCell('Parameter exceeds 64 KiB; reduce the selected content')
        self.guard()
        ops,root=self._surface_node(create=True)
        ops.set_property(root,name,encoded)
        return value

    def getAgentSurface(self):
        return {name:self._parameter("studio:" + name, default) for name,default in
            (("intakeRules",[]),("uncertainLinks",[]),("onboarding",{}),
             ("provenance",[]),("learning",{}),("hostSkills",[]))}

    def setTaskPlanMode(self, id, mode):
        if mode not in {"Run on its own","Confirm each step","Keep planning"}:
            raise InvalidCell("Choose a task plan mode")
        self._work(id)
        options=self._options(id); options["planMode"]=mode; self._save(id,options)
        return self._task(self._work(id))

    def checkpointTask(self, id):
        self._work(id)
        options=self._options(id)
        checkpoints=options.setdefault("checkpoints",[])
        key="checkpoint:"+self.request_id
        if not any(row["id"]==key for row in checkpoints):
            checkpoints.append({"id":key,"title":"Checkpoint " + str(len(checkpoints)+1),
                "steps":options.get("steps",[]),"planMode":options.get("planMode")})
            self._save(id,options)
        return next(row for row in checkpoints if row["id"]==key)

    def restoreTaskCheckpoint(self, id, checkpoint):
        self._work(id); options=self._options(id)
        saved=next((row for row in options.get("checkpoints",[]) if row["id"]==checkpoint),None)
        if saved is None: raise InvalidCell("Checkpoint no longer exists; refresh the task")
        options.update(steps=saved["steps"],planMode=saved["planMode"])
        self._save(id,options)
        return self._task(self._work(id))

    def openTaskGraph(self, id):
        self._work(id)
        ops=self._surface_rows(); canvas=ops.canvas()
        ops._node(canvas,id)
        return {"id":canvas.get('scope',{}).get('current',canvas['root']),"taskId":id}

    def setIntakeRule(self, id, values):
        if type(values) is not dict or set(values)-{"synonym","canonical","unit","shorthand"} or any(type(v) is not str for v in values.values()):
            raise InvalidCell("Dictionary fields must be text")
        rows=self._parameter("studio:intakeRules",[])
        if id is None:
            id="intake:"+self.request_id
            if not any(r["id"]==id for r in rows):
                rows.append({"id":id,"synonym":"","canonical":"","unit":"","shorthand":""})
        row=next((row for row in rows if row["id"]==id),None)
        if row is None: raise InvalidCell("Dictionary row disappeared; refresh before editing")
        row.update(values); self._put_parameter("studio:intakeRules",rows); return row

    def setOnboarding(self, values):
        if type(values) is not dict or set(values)-{"role","assessment"} or any(type(v) is not str for v in values.values()):
            raise InvalidCell("Onboarding accepts a role and assessment")
        return self._put_parameter("studio:onboarding",{**self._parameter("studio:onboarding",{}),**values})

    def reviewBrainLink(self, id, decision):
        if decision not in {"Accepted","Rejected"}: raise InvalidCell("Choose Accept or Reject")
        rows=self._parameter("studio:uncertainLinks",[])
        row=next((row for row in rows if row["id"]==id),None)
        if row is None: raise InvalidCell("Link disappeared; reload Brain before reviewing it")
        row["status"]=decision; self._put_parameter("studio:uncertainLinks",rows); return row

    def setSourceEvidence(self, id, values):
        if type(values) is not dict or set(values)-{"cited","trust","source","excluded"}:
            raise InvalidCell("Unsupported source evidence fields")
        rows=self._parameter("studio:provenance",[])
        row=next((row for row in rows if row["id"]==id),None)
        if row is None: raise InvalidCell("Source disappeared; refresh the evidence list")
        row.update(values); self._put_parameter("studio:provenance",rows); return row

    def setLearningLayer(self, layer, values=None):
        keys={"Host":{"program","operation","preserveRelationships"},
            "Habit":{"pattern","minimumRepeats","learn"},"Intent":{"baseline","deviation","why"},
            "Self":{"metric","threshold","rebaseline"},"Agent":{"provider","checkResults","maxIterations"},
            "Session":{"graph","shareContext","retainCheckpoints"}}
        values={} if values is None else values
        if layer not in keys or type(values) is not dict or set(values)-keys[layer]:
            raise InvalidCell("Choose a learning layer and its displayed parameters")
        held=self._parameter("studio:learning",{"layers":{}})
        held["layer"]=layer; held["layers"][layer]={**held["layers"].get(layer,{}),**values}
        return self._put_parameter("studio:learning",held)

    def setGraphMetadata(self, id, values):
        if id != self.scope or type(values) is not dict or set(values)-{"documentation","customProperties","courtStatus","thumbnail"}:
            raise InvalidCell("Only metadata for the currently selected graph may be edited")
        if values.get("courtStatus") == "Pass":
            raise InvalidCell("Pass requires a court receipt; open Run history and run its court")
        return self._put_parameter('graph-metadata:'+id,{**self.getGraphMetadata(),**values})

    def getGraphMetadata(self):
        return self._parameter('graph-metadata:'+self.scope,{})

    def setPinnedOutput(self, id, text):
        rows=json.loads(_text(text))
        if not isinstance(rows,(list,dict)): raise InvalidCell("Output JSON must be an array or object")
        ops=self._surface_rows(); ops._node(ops.canvas(),id)
        ops.set_property(id,"pinned_output",json.dumps(rows,ensure_ascii=False))
        ops.set_node_flags(id,pinned=True)
        return rows

    def setNodeRunPolicy(self, id, values):
        if type(values) is not dict or set(values)-{"onError","retries","previewOff","hostHighlighted"}:
            raise InvalidCell("Unsupported node run policy")
        if "retries" in values and (type(values["retries"]) is not int or not 0<=values["retries"]<=10):
            raise InvalidCell("Retries must be an integer from 0 to 10")
        if values.get("hostHighlighted"):
            raise InvalidCell("Choose this target in the connected program's Watcher, then retry highlighting")
        ops=self._surface_rows(); ops._node(ops.canvas(),id)
        for key,value in values.items(): ops.set_property(id,key,json.dumps(value))
        return values

    def verifyOutputStamp(self, id):
        ops=self._surface_rows(); node=ops._node(ops.canvas(),id)
        output=node.get("output",node.get("result"))
        if output is None: raise InvalidCell("Run this node to produce an output before verifying its hash")
        expected=ops._rows(None,id).get("output_hash",{}).get("value")
        actual=hashlib.sha256(json.dumps(output,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()
        if not expected: raise InvalidCell("Output has no provenance stamp; run its Provenance stamp node first")
        if expected != actual: raise InvalidCell("Content hash differs from its recorded stamp; inspect the output before rerunning")
        return {"verified":True,"sha256":actual}

    def refreshOfficeAwareness(self):
        tasks=self.listTasks()
        return [{"id":t["id"],"title":t["title"],"when":t["status"],"owner":t["owner"] or "Unassigned"}
                for t in tasks if t["status"] not in {"DONE","ARCHIVED"}]
    # WIRE-agents end.


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
    if body["function"] == "listWorkshopMessages":
        guard()
        try:
            return {"ok":True, "result":api.listWorkshopMessages(*body["args"]), "revision":0}
        except TypeError as exc:
            raise InvalidCell("Workshop data function arguments are invalid") from exc
    # Browser and route scans must not hold the graph writer lock.
    revision = api.admit().revision
    read = body["function"] in {"listAgentsWorking", "listTasks", "listWorkshopMessages"}
    with (nullcontext() if read else owner.mutation_lock), (
        nullcontext() if read else owner.universal_registry.authorization.broker.live_context(binding.context)
    ):
        if not read:
            api.admit()
        try:
            result = getattr(api, body["function"])(*body["args"])
        except TypeError as exc:
            raise InvalidCell("Workshop data function arguments are invalid") from exc
        if read and api.admit().revision != revision:
            raise InvalidCell("Workshop changed while reading; refresh the data")
        return {"ok":True, "result":result, "revision":revision if read else owner.universal_store.revision}

# WIRE-agents: extend the same authenticated dispatch allowlist.
FUNCTIONS = FUNCTIONS | frozenset({"getAgentSurface","setTaskPlanMode",
    "checkpointTask","restoreTaskCheckpoint","openTaskGraph","setIntakeRule","setOnboarding",
    "reviewBrainLink","setSourceEvidence","setLearningLayer","setGraphMetadata","getGraphMetadata",
    "setPinnedOutput","setNodeRunPolicy","verifyOutputStamp","refreshOfficeAwareness"})
FUNCTIONS = FUNCTIONS | frozenset({"listApprovals", "postponeApproval", "resumeApproval", "contestDecision",
    "refreshApproval", "reviewProofRow", "setApprovalRubric"})
# WIRE-agents end.

FUNCTIONS = FUNCTIONS | frozenset({"readWatcher", "setWatcherHost", "setWatcherView", "editWall",
    "addDimension", "addMark", "addComment", "proposeWatcherEdit", "discardWatcherChanges", "answerApproval"})
FUNCTIONS = FUNCTIONS | frozenset({"readHostSkills", "importHostSkill", "inspectConnectorBundle",
    "configureConnectorBundle", "installConnectorBundle", "setHostSkillEnabled", "auditHostSkill"})

FUNCTIONS = FUNCTIONS | frozenset({"readDesktop", "setDesktopProgram", "offerDesktopAction", "prepareDesktopAction",
    "setScheduleResponsibility", "reviewScheduledWork"})

FUNCTIONS = FUNCTIONS | frozenset({"listNotifications", "readNotification"})
FUNCTIONS = FUNCTIONS | frozenset({'readResearchState','runValuation','runResearchNode','setResearchReview','correctAnswerSource'})
