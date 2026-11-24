"""No app/graph is present: exercise the real mailbox and SQLite across processes."""
import concurrent.futures
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from nodelang import workshop_mailbox as mailbox


class WorkshopCourt(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.fixture = tempfile.TemporaryDirectory(dir=os.environ['TEMP'])
        self.addCleanup(self.fixture.cleanup)
        self.env = patch.dict(os.environ, {'LOCALAPPDATA': self.fixture.name,
            'ARCHHUB_TEST_STATE_DIR': self.fixture.name,
            'ARCHHUB_COORDINATION_ENDPOINT': 'http://127.0.0.1:1/coordination', 'APPDATA': self.fixture.name, 'TEMP': self.fixture.name, 'TMP': self.fixture.name})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.context = {'threadId': 'ng-codex'}

    def test_app_absent_send_read_declare_idempotency(self):
        result = mailbox.call('declare', {'task': 'NG court', 'paths': [str(Path.cwd())],
            'status': 'working', 'request_id': 'NG-WORKSHOP'}, self.context, timeout_seconds=.1)
        body = {'to': 'founder', 'text': 'NG app absent', 'idempotency_key': 'stable'}
        started = time.perf_counter()
        first = mailbox.call('send', body, self.context, timeout_seconds=.1)
        first_seconds = time.perf_counter() - started
        started = time.perf_counter()
        second = mailbox.call('send', body, self.context, timeout_seconds=.1)
        retry_seconds = time.perf_counter() - started
        self.assertEqual(first['message_id'], second['message_id'])
        started = time.perf_counter()
        rows = mailbox.call('read', {'since': 0}, self.context)['messages']
        read_seconds = time.perf_counter() - started
        self.assertEqual([r['content'] for r in rows], ['To founder:\nNG app absent'])
        self.assertEqual(result['declaration']['request_id'], 'NG-WORKSHOP')
        timings = {'send_seconds':first_seconds, 'resend_seconds':retry_seconds,
            'read_seconds':read_seconds}
        for operation, seconds in timings.items():
            self.assertLess(seconds, 2, operation)
        print(json.dumps({'local_mailbox_timing':timings, 'native_arrival_verified':False}))
        with self.assertRaisesRegex(ValueError, 'idempotency conflict'):
            mailbox.call('send', {**body, 'text': 'changed'}, self.context)

    def test_concurrent_10_processes_100_messages(self):
        # Unique OS peers, 100 unique keys each. No app or mocked SQLite.
        program = """from nodelang.workshop_mailbox import call
import sys
for i in range(100):
 call('send', {'to':'founder','text':sys.argv[1]+':'+str(i),'idempotency_key':str(i)}, {})
"""
        def run(i):
            result = subprocess.run([sys.executable, '-B', '-c', program, str(i)],
                capture_output=True, text=True, timeout=90,
                env={**os.environ, 'PYTHONPATH':str(Path(__file__).resolve().parents[2] / '01.APP')}, **({"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}))
            self.assertEqual(result.returncode, 0, result.stderr)
        started = time.perf_counter()
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
            list(pool.map(run, range(10)))
        with mailbox.application_history(None) as history:
            rows = history._db.execute('SELECT sequence,content FROM messages WHERE category=?',
                (mailbox.CATEGORY,)).fetchall()
            self.assertEqual(history._db.execute('PRAGMA journal_mode').fetchone()[0], 'wal')
        self.assertEqual(len(rows), 1000)
        self.assertEqual(len({r['content'] for r in rows}), 1000)
        self.assertEqual(sorted(r['sequence'] for r in rows), list(range(1, 1001)))
        print(json.dumps({'concurrent_messages': len(rows), 'lost': 0,
            'seconds': round(time.perf_counter() - started, 3)}))

    def test_four_senders_200_messages_with_concurrent_readers(self):
        # Real independent SQLite connections, including cold-start schema contention.
        program = """from nodelang.workshop_mailbox import call
import json, sys, time
while time.time() < float(sys.argv[2]):
 time.sleep(.01)
if sys.argv[1].startswith('writer'):
 for i in range(50):
  call('send', {'to':'founder', 'text':sys.argv[1]+':'+str(i), 'idempotency_key':str(i)}, {})
else:
 for i in range(100):
  call('read', {'since':8050 if i % 2 else 0}, {})
print(json.dumps({'lock_errors':0}))
"""
        start = str(time.time() + 3)
        def run(name):
            result = subprocess.run([sys.executable, '-B', '-c', program, name, start],
                capture_output=True, text=True, timeout=90,
                env={**os.environ, 'PYTHONPATH':str(Path(__file__).resolve().parents[2] / '01.APP')},
                **({'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), {'lock_errors':0})
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            list(pool.map(run, ['writer0', 'writer1', 'writer2', 'writer3', 'reader0', 'reader1']))
        with mailbox.application_history(None) as history:
            rows = history._db.execute('SELECT content FROM messages WHERE category=?',
                (mailbox.CATEGORY,)).fetchall()
        self.assertEqual({row['content'] for row in rows},
            {'To founder:\nwriter%d:%d' % (writer, i) for writer in range(4) for i in range(50)})
        self.assertEqual(len(rows), 200)
        print(json.dumps({'concurrent_senders':4, 'concurrent_readers':2,
            'messages':len(rows), 'lost':0, 'lock_errors':0}))

    def test_injection_once_and_reply_settles(self):
        class Transport:
            sent = []
            def inject(self, recipient, text, **kwargs):
                self.sent.append((recipient, text))
                return {'status': 'injected', 'dispatch_attempted': True}
        transport = Transport()
        peer = SimpleNamespace(pid=os.getpid(), created_at=__import__('psutil').Process().create_time(), cwd=str(Path.cwd()))
        recipient = {'claude/sessionID': 'ng-claude'}
        mailbox.call('declare', {'task':'recipient', 'paths':[str(Path.cwd())], 'status':'working',
            'request_id':'unassigned'}, recipient, peer=peer)
        with patch.object(mailbox, '_local_transport', return_value=transport):
            first = mailbox.call('send', {'to':'ng-claude','text':'Please reply.', 'idempotency_key':'one'}, self.context)
            mailbox.call('send', {'to':'ng-claude','text':'Please reply.', 'idempotency_key':'one'}, self.context)
            self.assertEqual(len(transport.sent), 1)
            self.assertEqual(transport.sent[0][0], {'app':'claude','id':'ng-claude'})
            from nodelang.workshop_api import WorkshopAPI
            api = WorkshopAPI(None, SimpleNamespace(subject_root='viewer'), 'unused', 'unused',
                              guard=lambda: None, request_id='court', route='court')
            def check(expected):
                for messages in (mailbox.call('read', {'since': 0}, self.context)['messages'],
                                 api.listWorkshopMessages()['messages']):
                    self.assertEqual(next(m['state'] for m in messages if m['id'] == first['message_id']), expected)
            check('delivered')
            mailbox.call('send', {'to':'founder','text':'My follow-up','reply_to':first['message_id']}, self.context)
            check('delivered')
            reply = mailbox.call('send', {'to':'founder','text':'Answer', 'reply_to':first['message_id']}, recipient)
            check('answered')
            # Founder 2026-10-28: no pending state. Delivery is one live row, made at send time.
            from nodelang.workshop_live import deliveries
            with mailbox.application_history(None) as history:
                rows = deliveries(history, [first['message_id']])[first['message_id']]
                linked = history.get(mailbox.ROOM, reply['message_id'], principal=mailbox.DELIVERY_AUTHOR)
            self.assertEqual([row['state'] for row in rows], ['delivered'])
            self.assertEqual(first['delivery'][0]['state'], 'delivered')
            self.assertEqual(linked['reply_to'], first['message_id'])

    def test_recipient_delivery_evidence_stays_separate(self):
        from nodelang.workshop_api import WorkshopAPI
        from nodelang.workshop_live import SCHEMA
        api = WorkshopAPI(None, SimpleNamespace(subject_root='viewer'), 'unused', 'unused',
                          guard=lambda: None, request_id='court', route='court')
        targets = [{"session": key, "agent": key, "runtime": "codex", "native_session_id": key}
                   for key in ("one", "two")]
        with mailbox.application_history() as history:
            parent = history.append(mailbox.ROOM, author="Sender", category=mailbox.CATEGORY,
                content="To one,two:\nQuestion", evidence=[mailbox.ROUTING_EVIDENCE,
                json.dumps({"recipients":targets})], idempotency_key="multi-test")
            history._db.execute(SCHEMA)
            for key, status in (("one", "delivered"), ("two", "uncertain")):
                history._db.execute("INSERT INTO workshop_live_deliveries VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (parent["id"],key,key,"codex",key,"workshop",status,"","2026-01-01",0))
            for label, private, project in (("private", True, ""), ("other-project", False, "unrelated")):
                author = {"session":"one", "native_session_id":"one", "runtime":"codex"}
                reply = history.append(mailbox.ROOM, author="Agent [one]", category=mailbox.CATEGORY,
                    content="This reply must stay scoped", recipients=("one",) if private else (),
                    reply_to=parent["id"], evidence=[mailbox.ROUTING_EVIDENCE,
                    json.dumps({"sender":author, "project":project})], idempotency_key=label)
                if private:
                    mailbox._delivery_receipt(history, parent, targets[0], "answered", reply_message_id=reply["id"])
        def check(second):
            message = next(m for m in api.listWorkshopMessages()["messages"] if m["id"] == parent["id"])
            self.assertEqual({r["recipient"]:r["state"] for r in message["delivery"]}, {"one":"delivered","two":second})
            self.assertFalse(any("reply_message_id" in r for r in message["delivery"]))
            self.assertEqual(message["state"],second)
            notes = mailbox.call("read", {"since":0}, self.context)["messages"]
            self.assertEqual(next(m["state"] for m in notes if m["id"] == parent["id"]), second)
        check("uncertain")
        with mailbox.application_history() as history:
            history._db.execute("UPDATE workshop_live_deliveries SET state='refused' WHERE message_id=? AND recipient='two'",
                                (parent["id"],))
        check("refused")
        # Earlier profiles may lack the optional reply index. Reading still respects scope.
        with mailbox.application_history() as history:
            history._db.execute("DROP INDEX IF EXISTS workshop_reply_to")
            viewed = mailbox.message_delivery(history, parent)
            self.assertEqual(viewed["state"], "refused")
            self.assertFalse(any("reply_message_id" in r for r in viewed["delivery"]))
            self.assertIsNone(history._db.execute("SELECT 1 FROM sqlite_master WHERE name='workshop_reply_to'").fetchone())

    def test_cross_project_answer_only_reaches_addressed_parent_author(self):
        self._check_reply_address(cross_project=True)

    def test_same_project_note_to_third_peer_is_visible_without_answering(self):
        self._check_reply_address(cross_project=False)

    def _check_reply_address(self, cross_project):
        from nodelang.workshop_api import WorkshopAPI
        import psutil
        class Transport:
            def inject(self, recipient, text, **kwargs):
                return {"status":"injected", "dispatch_attempted": True}
        contexts = [self.context, {"claude/sessionID":"other-project"}, {"threadId":"third-viewer"}]
        declarations = []
        with patch.object(mailbox, 'project_of', side_effect=lambda cwd, paths: Path(cwd).name), patch.object(mailbox, '_local_transport', return_value=Transport()):
            for ctx, project in zip(contexts, ("Alpha", "Beta" if cross_project else "Alpha", "Alpha")):
                cwd = Path(self.fixture.name) / project
                cwd.mkdir(exist_ok=True)
                peer = SimpleNamespace(pid=os.getpid(), created_at=psutil.Process().create_time(), cwd=str(cwd))
                declarations.append(mailbox.call("declare", {"task":"court", "paths":[str(cwd)],
                    "status":"working", "request_id":"unassigned"}, ctx, peer=peer)["declaration"])
            a, b, other = declarations
            parent = mailbox.call("send", {"to":b["agent"], "text":"Please answer"}, contexts[0])["message_id"]
            wrong = mailbox.call("send", {"to":other["agent"], "text":"For someone else", "reply_to":parent}, contexts[1])["message_id"]
            author_view = WorkshopAPI(None, SimpleNamespace(subject_root=a["session"]), "", "",
                                      guard=lambda:None, request_id="court", route="court")
            for page in (mailbox.call("read", {"since":0}, contexts[0]), author_view.listWorkshopMessages()):
                notes = {n["id"]:n for n in page["messages"]}
                self.assertEqual(wrong in notes, not cross_project)
                self.assertEqual(notes[parent]["state"], "delivered")
                self.assertTrue(all("reply_message_id" not in row for row in notes[parent].get("delivery", [])))
            child = mailbox.call("send", {"to":a["agent"], "text":"Answer", "reply_to":parent}, contexts[1])["message_id"]
            for viewer, ctx, admitted in ((a, contexts[0], True), (other, contexts[2], not cross_project)):
                studio = WorkshopAPI(None, SimpleNamespace(subject_root=viewer["session"]), "", "",
                                     guard=lambda:None, request_id="court", route="court")
                for page in (mailbox.call("read", {"since":0}, ctx), studio.listWorkshopMessages()):
                    notes = {note["id"]:note for note in page["messages"]}
                    self.assertEqual(child in notes, admitted)
                    self.assertEqual(notes[parent]["state"], "answered" if admitted else "delivered")
                    if "delivery" in notes[parent]:
                        self.assertEqual(notes[parent]["delivery"][0].get("reply_message_id"), child if admitted else None)

    def test_ui_thread_uses_same_file_without_owner_graph(self):
        from nodelang.workshop_api import WorkshopAPI
        first = mailbox.call('send', {'to':'founder','text':'thread'}, self.context)
        mailbox.call('send', {'to':'founder','text':'reply','reply_to':first['message_id']}, self.context)
        api = WorkshopAPI(None, SimpleNamespace(subject_root='viewer'), 'unused', 'unused',
            guard=lambda:None, request_id='court', route='court')
        rows = api.listWorkshopMessages()['messages']
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1]['reply_to'], rows[0]['id'])

    def test_existing_application_caller_cannot_select_graph_database(self):
        forbidden = Path(self.fixture.name) / 'GRAPH-SENTINEL'
        forbidden.write_bytes(b'not a Workshop database; must stay untouched')
        with mailbox.application_history(None) as history:
            result = mailbox.call('send', {'to':'founder','text':'application caller'}, self.context,
                database=forbidden, history=history)
            self.assertEqual(history.get(mailbox.ROOM, result['message_id'],
                principal=mailbox.DELIVERY_AUTHOR)['content'], 'To founder:\napplication caller')
        self.assertEqual(forbidden.read_bytes(), b'not a Workshop database; must stay untouched')

    def test_room_notes_inject_nobody_and_named_target_injects_once(self):
        class Transport:
            def __init__(self):
                self.sent = []
            def inject(self, recipient, text, **kwargs):
                self.sent.append((recipient, text))
                return {'status':'injected', 'dispatch_attempted':True}
        transport = Transport()
        for native in ('recipient-one', 'recipient-two'):
            mailbox.call('declare', {'task':'recipient','paths':[str(Path.cwd())],
                'status':'working','request_id':'unassigned'}, {'claude/sessionID':native})
        with patch.object(mailbox, '_local_transport', return_value=transport):
            for target in ('*', 'room', 'founder'):
                mailbox.call('send', {'to':target,'text':'No reply needed.'}, self.context)
            self.assertEqual(transport.sent, [])
            mailbox.call('send', {'to':'recipient-one','text':'No reply needed.'}, self.context)
        self.assertEqual([row[0]['id'] for row in transport.sent], ['recipient-one'])

    def test_exact_live_session_needs_no_graph_enrollment_or_declaration(self):
        class Transport:
            def __init__(self):
                self.sent = []
            def discover(self, **kwargs):
                return {'status':'ok', 'recipients':[
                    {'app':'claude','id':'external-session','title':'External existing session'}]}
            def inject(self, recipient, text, **kwargs):
                self.sent.append(recipient)
                return {'status':'injected', 'dispatch_attempted':True}
        transport = Transport()
        with patch.object(mailbox, '_local_transport', return_value=transport):
            result = mailbox.call('send', {'to':'external-session','text':'No reply needed.'}, self.context)
        self.assertEqual(transport.sent, [{'app':'claude','id':'external-session'}])
        self.assertEqual(result['status'], 'recorded')
        self.assertEqual([row['state'] for row in result['delivery']], ['delivered'])
        with mailbox.application_history(None) as history:
            self.assertIsNone(history._db.execute(
                "SELECT 1 FROM messages WHERE idempotency_key LIKE 'workshop-unresolved:%'").fetchone())

    def test_retention_expires_parent_preserves_recent_reply_and_indexes(self):
        from datetime import datetime, timedelta, timezone
        old = (datetime.now(timezone.utc) - timedelta(days=21)).isoformat()
        recent = (datetime.now(timezone.utc) - timedelta(days=19)).isoformat()
        with mailbox.application_history(None) as history:
            parent = history.append(mailbox.ROOM, author='test', content='expiredparent',
                category=mailbox.CATEGORY, idempotency_key='old', created_at=old)
            child = history.append(mailbox.ROOM, author='test', content='recentreply',
                category=mailbox.CATEGORY, idempotency_key='child', created_at=recent,
                reply_to=parent['id'])
        with mailbox.application_history(None) as history:
            mailbox._retain_messages(history)  # explicit archive only: no open deletes (founder rule)
            self.assertIsNone(history.get(mailbox.ROOM, parent['id'], principal='test'))
            kept = history.get(mailbox.ROOM, child['id'], principal='test')
            self.assertEqual(kept['content'], 'recentreply')
            self.assertIsNone(kept['reply_to'])
            self.assertEqual(history._db.execute('PRAGMA foreign_key_check').fetchall(), [])
            self.assertEqual(history.search(mailbox.ROOM, 'expiredparent', principal='test'), [])
            self.assertEqual([row['id'] for row in history.search(mailbox.ROOM, 'recentreply',
                principal='test')], [child['id']])
            counts = history._db.execute('SELECT audience_kind,amount FROM category_counts '
                'WHERE conversation_id=? AND category=?', (mailbox.ROOM, mailbox.CATEGORY)).fetchall()
            self.assertEqual({row[0]:row[1] for row in counts}, {'all':1, 'public':1})

    def test_opening_never_deletes_and_the_explicit_archive_drains_in_small_batches(self):
        # Founder rule: never delete his data without his word. 2026-11-16 "database is locked": the delete ran on every open.
        from datetime import datetime, timedelta, timezone
        old = (datetime.now(timezone.utc) - timedelta(days=21)).isoformat()
        with mailbox.application_history(None) as history:
            for index in range(129):
                history.append(mailbox.ROOM, author='test', content='expired',
                    category=mailbox.CATEGORY, idempotency_key=str(index), created_at=old)
        with mailbox.application_history(None) as history:
            self.assertEqual(history._db.execute('SELECT count(*) FROM messages').fetchone()[0], 129)
            mailbox._retain_messages(history)
        with mailbox.application_history(None) as history:
            self.assertEqual(history._db.execute('SELECT count(*) FROM messages').fetchone()[0], 0)

    def test_nearest_codex_runtime_overrides_inherited_claude_environment(self):
        from nodelang.native_agent_mcp import _default_context
        environment = {'CODEX_THREAD_ID':'actual-codex', 'CLAUDE_SESSION_ID':'inherited-claude'}
        with patch.dict(os.environ, environment, clear=True), patch(
                'nodelang.agent_runtime_registry.observed_runtime_process',
                return_value={'runtime':'codex', 'pid':os.getpid(), 'created_at':0}):
            self.assertEqual(_default_context(), {'threadId':'actual-codex'})

    def test_app_worker_yields_after_one_effect_but_finishes_next_tick(self):
        class Transport:
            def __init__(self):
                self.sent = []
            def inject(self, recipient, text, **kwargs):
                self.sent.append(recipient['id'])
                return {'status':'injected', 'dispatch_attempted':True}
        for native in ('recipient-one', 'recipient-two'):
            mailbox.call('declare', {'task':'recipient','paths':[str(Path.cwd())],
                'status':'working','request_id':'unassigned'}, {'claude/sessionID':native})
        with mailbox.application_history(None) as history:
            identity, _runtime, _peer = mailbox._identity(self.context, None)
            mailbox._send(history, {'to':'recipient-one, recipient-two','text':'No reply needed.'}, identity)
        transport = Transport()
        worker = mailbox.WorkshopInjection(None, transport)
        worker.tick()
        self.assertEqual(len(transport.sent), 1)
        worker.tick()
        self.assertEqual(set(transport.sent), {'recipient-one', 'recipient-two'})

    def test_the_injection_tick_never_probes_processes_while_holding_the_writer(self):
        """0ea5038: claim_delivery re-read declarations (psutil liveness for every agent) inside the tick's write
        transaction, holding the Workshop's only writer and refusing every sender."""
        class Transport:
            def inject(self, recipient, text, **kwargs):
                return {'status': 'injected', 'dispatch_attempted': True}
        mailbox.call('declare', {'task': 'recipient', 'paths': [str(Path.cwd())], 'status': 'working',
                                 'request_id': 'unassigned'}, {'claude/sessionID': 'recipient-one'})
        with mailbox.application_history(None) as history:
            identity, _runtime, _peer = mailbox._identity(self.context, None)
            mailbox._send(history, {'to': 'recipient-one', 'text': 'No reply needed.'}, identity)
        real, probes = mailbox.read_declarations, []

        def counted(connection, **kwargs):
            probes.append(connection.in_transaction)
            return real(connection, **kwargs)
        sent = []
        transport = Transport()
        transport.inject = lambda recipient, text, **kwargs: sent.append(recipient['id']) or {
            'status': 'injected', 'dispatch_attempted': True}
        with patch.object(mailbox, 'read_declarations', side_effect=counted):
            mailbox.WorkshopInjection(None, transport).tick()
        self.assertEqual(sent, ['recipient-one'])
        self.assertTrue(probes)
        self.assertNotIn(True, probes)  # every liveness read happened outside a transaction

    def test_an_idle_tick_does_not_scan_the_roster_and_new_work_still_delivers(self):
        sent = []

        class Transport:
            def inject(self, recipient, text, **kwargs):
                sent.append(recipient['id'])
                return {'status': 'injected', 'dispatch_attempted': True}
        mailbox.call('declare', {'task': 'recipient', 'paths': [str(Path.cwd())], 'status': 'working',
                                 'request_id': 'unassigned'}, {'claude/sessionID': 'recipient-one'})
        worker = mailbox.WorkshopInjection(None, Transport())
        real, scans = mailbox.read_declarations, []
        with patch.object(mailbox, 'read_declarations', side_effect=lambda *a, **k: scans.append(1) or real(*a, **k)):
            worker.tick(now=1000.0)   # the first pass is a watcher pass
            scans.clear()
            worker.tick(now=1001.0)
            worker.tick(now=1002.0)
            self.assertEqual(scans, [])   # idle: no roster scan
            with mailbox.application_history(None) as history:
                identity, _runtime, _peer = mailbox._identity(self.context, None)
                mailbox._send(history, {'to': 'recipient-one', 'text': 'No reply needed.'}, identity)
            worker.tick(now=time.time())
        self.assertTrue(scans)
        self.assertEqual(sent, ['recipient-one'])

    def test_seen_reads_the_roster_before_taking_the_writer(self):
        mailbox.call('declare', {'task': 'recipient', 'paths': [str(Path.cwd())], 'status': 'working',
                                 'request_id': 'unassigned'}, self.context)
        sent = mailbox.call('send', {'to': 'founder', 'text': 'seen check'}, self.context)
        real, probes = mailbox.read_declarations, []
        with patch.object(mailbox, 'read_declarations',
                          side_effect=lambda connection, **k: probes.append(connection.in_transaction) or real(connection, **k)):
            mailbox.call('seen', {'message_ids': [sent['message_id']], 'channel': 'connector tool result'}, self.context)
        self.assertTrue(probes)
        self.assertNotIn(True, probes)

    def test_a_confirmed_background_claim_acknowledges_the_message_for_its_recipient(self):
        with mailbox.application_history(None) as history:
            identity, _runtime, _peer = mailbox._identity(self.context, None)
            message = history.get(mailbox.ROOM, mailbox._send(history, {'to': 'founder', 'text': 'claimed'}, identity)
                                  ["message_id"], principal=mailbox.DELIVERY_AUTHOR)
            seat = {'session': 'agent:session:x', 'agent': 'X', 'runtime': 'claude', 'native_session_id': 'native-x'}
            other = {'session': 'agent:session:y', 'agent': 'Y', 'runtime': 'claude', 'native_session_id': 'native-y'}
            recipient = {'sender_key': 'agent:session:x', 'sender': 'X [agent:session:x]'}
            self.assertFalse(mailbox._acknowledged(history, message, recipient, seat))
            self.assertTrue(mailbox.claim_delivery(history, message, seat, 'initial', 'background')[0])
            mailbox.record_claim_outcome(history, message['id'], seat, 'initial', 'uncertain')
            self.assertFalse(mailbox._acknowledged(history, message, recipient, seat))  # uncertain stays pending
            self.assertTrue(mailbox.claim_delivery(history, message, other, 'initial', 'background')[0])
            mailbox.record_claim_outcome(history, message['id'], other, 'initial', 'delivered')
            self.assertFalse(mailbox._acknowledged(history, message, recipient, seat))  # per recipient
            self.assertTrue(mailbox._acknowledged(history, message, {'sender_key': 'agent:session:y',
                                                                      'sender': 'Y [agent:session:y]'}, other))

    def test_an_unchanged_waiting_backlog_is_not_rescanned_every_tick(self):
        worker = mailbox.WorkshopInjection(None, None)
        with mailbox.application_history(None) as history:
            identity, _runtime, _peer = mailbox._identity(self.context, None)
            sent = mailbox._send(history, {'to': 'offline-role-nobody', 'text': 'No reply needed.'}, identity)
            history._db.execute("CREATE TABLE IF NOT EXISTS workshop_waiting(message_id TEXT PRIMARY KEY, target TEXT NOT NULL)")
            history._db.execute("INSERT OR IGNORE INTO workshop_waiting VALUES (?,?)", (sent['message_id'], 'offline-role-nobody'))
        mailbox.call('declare', {'task': 'someone', 'paths': [str(Path.cwd())], 'status': 'working',
                                 'request_id': 'unassigned'}, self.context)
        real, scans = mailbox.read_declarations, []
        with patch.object(mailbox, 'read_declarations', side_effect=lambda *a, **k: scans.append(1) or real(*a, **k)):
            worker.tick(now=time.time())
            first = len(scans)
            worker.tick(now=time.time() + 1)
            worker.tick(now=time.time() + 2)
            self.assertEqual(len(scans), first)   # same roster, same backlog: no rescan
            mailbox.call('declare', {'task': 'newcomer', 'paths': [str(Path.cwd())], 'status': 'working',
                                     'request_id': 'unassigned'}, {'claude/sessionID': 'newcomer'})
            scans.clear()
            worker.tick(now=time.time() + 3)
            self.assertTrue(scans)   # a new declaration is picked up promptly

    def test_a_busy_activity_line_never_turns_a_committed_send_into_an_error(self):
        import sqlite3
        busy = sqlite3.OperationalError('database is locked')
        busy.sqlite_errorcode = sqlite3.SQLITE_BUSY
        with patch.object(mailbox, 'record_activity', side_effect=busy):
            sent = mailbox.call('send', {'to': 'founder', 'text': 'saved before its activity line'}, self.context)
        rows = mailbox.call('read', {'since': 0}, self.context)['messages']
        self.assertEqual([row['id'] for row in rows if 'saved before its activity line' in json.dumps(row)],
                         [sent['message_id']])  # one message, and the caller has its id
        broken = sqlite3.OperationalError('disk I/O error')
        with patch.object(mailbox, 'record_activity', side_effect=broken):
            with self.assertRaises(sqlite3.OperationalError):
                mailbox.call('declare', {'task': 'x', 'paths': [str(Path.cwd())], 'status': 'working',
                                         'request_id': 'X'}, self.context)

    def test_a_busy_receipt_never_turns_a_committed_send_into_an_error(self):
        import sqlite3
        sent = mailbox.call('send', {'to': 'founder', 'text': 'committed before the receipt'}, self.context)
        database = mailbox.profile_database()
        holder = sqlite3.connect(database, isolation_level=None, timeout=1)
        self.addCleanup(holder.close)
        holder.execute('BEGIN IMMEDIATE')  # another process holds the only writer
        started = time.perf_counter()
        rows = mailbox._receipt(None, sent, {'to': 'recipient'}, 'uncertain', 'push did not finish')
        self.assertLess(time.perf_counter() - started, 10)
        self.assertEqual(rows[0]['state'], 'pending')
        self.assertIn('do not send it again', rows[0]['reason'])
        holder.execute('ROLLBACK')
        self.assertEqual(mailbox._receipt(None, sent, {'to': 'recipient'}, 'uncertain', 'later')[0]['state'], 'uncertain')
        with mailbox.application_history(None) as history:
            saved = [tuple(row) for row in history._db.execute(
                'SELECT state FROM workshop_live_deliveries WHERE message_id=?', (sent['message_id'],))]
        self.assertEqual(saved, [('uncertain',)])  # exactly one receipt once the writer is gone
        # A failure that is not a busy store still fails.
        with patch.object(mailbox, 'application_history', side_effect=sqlite3.OperationalError('disk I/O error')):
            with self.assertRaises(sqlite3.OperationalError):
                mailbox._receipt(None, sent, {'to': 'recipient'}, 'failed', 'x')


if __name__ == '__main__':
    unittest.main()


# WSROLES exercises real mailbox functions against a disposable database.

from nodelang import workshop_mailbox as mb
import pytest
def peer(pid=None):
    import psutil
    process = psutil.Process(pid or os.getpid())
    return SimpleNamespace(pid=process.pid, created_at=process.create_time(), cwd=os.getcwd())


@pytest.fixture
def database(tmp_path):
    path = tmp_path / 'messages.sqlite3'
    with mb.application_history(database=path):
        pass
    return path


def application_call(method, body, context, *, database, peer):
    return mb.call(method, body, context, database=database, peer=peer)


def declare(database, session, role, **extra):
    return application_call('declare', {'task': 'Role test', 'paths': [os.getcwd()], 'status': 'working',
        'request_id': 'unassigned', 'role': role, **extra}, {'threadId': session}, database=database, peer=peer())


def ident(row):
    return {key: row[key] for key in ('sender_key', 'sender_label', 'sender')}


def test_display_name_role_title_and_once(database, monkeypatch):
    holder = declare(database, 'holder', 'coordinator', display_name='717', title='Desktop coordinator')
    sender = {'sender_key': 'writer', 'sender_label': 'Writer', 'sender': 'Writer [writer]'}
    with mb.application_history(database=database) as history:
        sent = [mb._send(history, {'to': name, 'text': 'hello', 'idempotency_key': name}, sender)
                for name in ('717', 'coordinator', 'Desktop coordinator')]
        ids = [row['message_id'] for row in sent]
        pending = mb._pending(history, ident(holder), 'codex')['pending']
        assert {m['id'] for m in pending} == set(ids)
        mb._seen(history, {'message_ids': ids, 'channel': 'hook'}, ident(holder), 'codex')
        assert mb._pending(history, ident(holder), 'codex')['pending'] == []
    from nodelang import workshop_live
    pushes = []
    monkeypatch.setattr(workshop_live, 'push', lambda *a, **k: pushes.append(a) or ('delivered', 'test', ''))
    body = {'to': '717', 'text': 'unread live delivery'}
    with mb.application_history(database=database) as history:
        unread = mb._send(history, body, sender)
    assert mb._deliver_now(database, unread, body, sender)[0]['state'] == 'delivered'
    mb._deliver_now(database, unread, body, sender)
    assert len(pushes) == 1


def test_queue_and_handover_100_messages(database):
    old = declare(database, 'old-design', 'design', display_name='retired designer')
    sender = {'sender_key': 'writer', 'sender_label': 'Writer', 'sender': 'Writer [writer]'}
    with mb.application_history(database=database) as history:
        record = dict(old['declaration'], status='done')
        history._db.execute('UPDATE workshop_declarations SET record=? WHERE root=?',
                            (json.dumps(record), record['root']))
        sent = [mb._send(history, {'to': ('design', '717', 'retired designer', old['sender_key'])[i % 4],
                                 'text': 'replay ' + str(i)}, sender) for i in range(100)]
        ids = [row['message_id'] for row in sent if row['status'] != 'returned']
        returned = [row for row in sent if row['status'] == 'returned']
        assert len(returned) == 25
        assert all(row['unresolved'] == [old['sender_key']] for row in returned)
    design = declare(database, 'next-design', 'design')
    coordinator = declare(database, 'next-717', '717')
    delivered = []
    with mb.application_history(database=database) as history:
        for holder in (design, coordinator):
            while True:
                pending = mb._pending(history, ident(holder), 'codex')['pending']
                if not pending:
                    break
                batch = [m['id'] for m in pending]
                delivered.extend(batch)
                mb._seen(history, {'message_ids': batch, 'channel': 'hook'}, ident(holder), 'codex')
        assert len(delivered) == len(set(delivered)) == 75
        assert set(delivered) == set(ids)
        assert history._db.execute("SELECT count(*) FROM messages WHERE idempotency_key LIKE 'workshop-unresolved:%'").fetchone()[0] == 25


def test_session_start_declares_role(tmp_path, monkeypatch, database):
    from nodelang.native_agent_hooks import declare_session
    monkeypatch.setenv('ARCHHUB_WORKSHOP_ROLE', 'research')
    value = declare_session({'session_id': 'auto', 'cwd': str(tmp_path)}, 'codex', database=database, kind='start')
    assert value['declaration']['role'] == 'research'
    monkeypatch.delenv('ARCHHUB_WORKSHOP_ROLE')
    again = declare_session({'session_id': 'auto', 'cwd': str(tmp_path)}, 'codex', database=database, kind='start')
    assert again['declaration']['role'] == 'research'


def test_two_live_role_holders_keep_exact_session_addresses(database):
    older = declare(database, 'older-design', 'design', display_name='First designer')
    newer = declare(database, 'newer-design', 'design', display_name='Second designer')
    sender = {'sender_key':'writer', 'sender_label':'Writer', 'sender':'Writer [writer]'}
    with mb.application_history(database=database) as history:
        exact = mb._send(history, {'to':'older-design', 'text':'exact native'}, sender)
        session = mb._send(history, {'to':older['sender_key'], 'text':'exact session'}, sender)
        role = mb._send(history, {'to':'design', 'text':'current role'}, sender)
        rows = mb.read_declarations(history._db)
        assert {row['session'] for row in rows} == {older['sender_key'], newer['sender_key']}
        assert {m['id'] for m in mb._pending(history, ident(older), 'codex')['pending']} == {
            exact['message_id'], session['message_id']}
        assert {m['id'] for m in mb._pending(history, ident(newer), 'codex')['pending']} == {role['message_id']}


class LegacyAnswerCourt(unittest.TestCase):
    def test_a_second_reply_to_a_legacy_native_note_never_conflicts_on_every_tick(self):
        """e988 cc31c6f0: a legacy note grouped its native addressee as ('session', 'native:codex:<id>') while the reply
        resolved to ('native', 'codex', <id>); the tick missed the first answer and the second reply hit its key."""
        import json
        from nodelang.conversation_history import ConversationHistoryStore
        seat = {'session': 'native:codex:test-uuid', 'agent': 'Reviewer', 'runtime': 'codex', 'native_session_id': 'test-uuid'}
        registered = {**seat, 'session': 'reviewer-registration', 'current': True}

        def routing(**fields):
            return [mailbox.ROUTING_EVIDENCE, json.dumps(fields)]
        with ConversationHistoryStore(':memory:', instance_id=mailbox.ROOM) as history:
            history.ensure_conversation(mailbox.ROOM)

            def note(key, author, **fields):
                return history.append(mailbox.ROOM, author=author, content='Example', category=mailbox.CATEGORY,
                                      idempotency_key=key, **fields)
            parent = note('p', 'Coordinator [q]', evidence=routing(recipients=[seat]))
            replies = [note(key, 'Reviewer [reviewer-registration]', reply_to=parent['id'],
                            evidence=routing(sender=registered, recipients=[])) for key in ('r1', 'r2')]
            with patch.object(mailbox, 'read_declarations', return_value=[registered]):
                worker = mailbox.WorkshopInjection(None, None)
                for _ in range(2):
                    worker._tick(history, time.time())   # raised ValueError('idempotency conflict') on every tick
            answer = mailbox.delivery_events(history, parent)[seat['session']]['answered']
            self.assertEqual(answer['reply_message_id'], replies[0]['id'])        # the first answer stands
            self.assertEqual([history.get(mailbox.ROOM, r['id'], principal=mailbox.DELIVERY_AUTHOR)['id'] for r in replies],
                             [r['id'] for r in replies])                          # both reply notes kept
