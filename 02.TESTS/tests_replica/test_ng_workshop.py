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
            'ARCHHUB_COORDINATION_ENDPOINT': 'http://127.0.0.1:1/coordination'})
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
                capture_output=True, text=True, timeout=90)
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
            reply = mailbox.call('send', {'to':'founder','text':'Answer', 'reply_to':first['message_id']}, recipient)
            # Founder 2026-10-28: no pending state. Delivery is one live row, made at send time.
            from nodelang.workshop_live import deliveries
            with mailbox.application_history(None) as history:
                rows = deliveries(history, [first['message_id']])[first['message_id']]
                linked = history.get(mailbox.ROOM, reply['message_id'], principal=mailbox.DELIVERY_AUTHOR)
            self.assertEqual([row['state'] for row in rows], ['delivered'])
            self.assertEqual(first['delivery'][0]['state'], 'delivered')
            self.assertEqual(linked['reply_to'], first['message_id'])

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

    def test_broadcast_reaches_each_recipient_without_app_worker(self):
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
            mailbox.call('send', {'to':'*','text':'No reply needed.'}, self.context)
        self.assertEqual({row[0]['id'] for row in transport.sent}, {'recipient-one', 'recipient-two'})

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
            mailbox.call('send', {'to':'external-session','text':'No reply needed.'}, self.context)
        self.assertEqual(transport.sent, [{'app':'claude','id':'external-session'}])

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

    def test_retention_is_bounded_to_128_rows_per_open(self):
        from datetime import datetime, timedelta, timezone
        old = (datetime.now(timezone.utc) - timedelta(days=21)).isoformat()
        with mailbox.application_history(None) as history:
            for index in range(129):
                history.append(mailbox.ROOM, author='test', content='expired',
                    category=mailbox.CATEGORY, idempotency_key=str(index), created_at=old)
        with mailbox.application_history(None) as history:
            self.assertEqual(history._db.execute('SELECT count(*) FROM messages').fetchone()[0], 1)
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
            mailbox._send(history, {'to':'*','text':'No reply needed.'}, identity)
        transport = Transport()
        worker = mailbox.WorkshopInjection(None, transport)
        worker.tick()
        self.assertEqual(len(transport.sent), 1)
        worker.tick()
        self.assertEqual(set(transport.sent), {'recipient-one', 'recipient-two'})


if __name__ == '__main__':
    unittest.main()
