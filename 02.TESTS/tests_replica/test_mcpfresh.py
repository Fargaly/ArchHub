import types
"""MCPFRESH: real stdio pipes, real process replacement, no live application data."""
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import threading
import time

import psutil
import pytest

pytest_plugins = ('tests_replica.test_nokey',)


def test_startup_and_explicit_connector_mail_have_bounded_budgets(monkeypatch):
    import asyncio
    from nodelang import native_agent_mcp as native, workshop_mailbox
    from nodelang.library_engines import LIBRARY_ITEM_ENGINES
    monkeypatch.setitem(LIBRARY_ITEM_ENGINES['tool_workshop']['params'], 'preflight_database_ms', 750)
    monkeypatch.setitem(LIBRARY_ITEM_ENGINES['tool_workshop']['params'], 'recovery_timeout_seconds', 4)
    calls = []

    def unavailable(method, body, context, *, timeout_seconds=30.0):
        calls.append((method, timeout_seconds))
        raise TimeoutError("fixture mailbox is unavailable")

    monkeypatch.setattr(workshop_mailbox, "call", unavailable)
    server = native.build_server()

    async def initialize():
        async with server.settings.lifespan(server):
            import anyio
            with anyio.fail_after(3):
                while not calls:
                    await anyio.sleep(.01)

    asyncio.run(initialize())
    assert calls[0] == ("declare", 0.75)
    assert all(timeout == .75 for _, timeout in calls)
    with pytest.raises(TimeoutError):
        native._mailbox_call("read", {"since": 0}, {})
    assert calls[-1] == ("read", 4.0)  # an agent's own tool call waits out other writers

ENTRY = '''import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from nodelang import native_agent_mcp as native
from probe_build import BUILD
import asyncio, json, os, time
root = Path(__file__).parent
import subprocess
launch = subprocess.Popen
def restart(*args, **kwargs):
    if (root / 'FAIL_RESTART').exists():
        raise OSError('fixture restart refused')
    return launch(*args, **kwargs)
subprocess.Popen = restart
if os.environ.get('ARCHHUB_MCP_CONTINUATION'):
    (root / 'CONTINUATION_SIZE').write_text(str(sum(len(value) for key, value in os.environ.items()
        if key.startswith('ARCHHUB_MCP_CONTINUATION_'))), encoding='utf-8')
original = native.build_server
def mailbox(method, body, context):
    if method == 'send':
        with (root / 'EFFECTS').open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(body['text']) + '\\n')
        if body['text'] == 'slow':
            (root / 'ENTERED').touch()
            while not (root / 'RELEASE').exists():
                time.sleep(.02)
        return {'build':BUILD, 'pid':os.getpid(), 'parent':os.getppid(), 'text':body['text']}
    return {'pending':[]} if method == 'pending' else {}
def build(**kwargs):
    server = (original(**kwargs) if os.environ.get('MCPFRESH_REAL_MAILBOX')
              else original(mailbox_call=mailbox, **kwargs))
    async def slow() -> dict[str, object]:
        (root / 'ENTERED').touch()
        with (root / 'EFFECTS').open('a', encoding='utf-8') as stream:
            stream.write(json.dumps('async slow') + '\\n')
        try:
            while not (root / 'RELEASE').exists():
                await asyncio.sleep(.02)
        finally:
            (root / 'FINISHED').touch()
        return {'build':BUILD, 'pid':os.getpid()}
    server.add_tool(slow, name='slow')
    def custody(state: str) -> dict[str, object]:
        from types import SimpleNamespace
        import threading
        server.work_control.owner = None if state == 'clear' else SimpleNamespace(
            _lock=threading.RLock(), _state=state, _session_root=None,
            _active_calls=0, _rebind_candidate=None, _retired_release=None)
        return {'build':BUILD, 'pid':os.getpid()}
    server.add_tool(custody, name='custody')
    return server
native.build_server = build
native.main()
'''


def _pump(stream, output):
    for line in iter(stream.readline, b''):
        output.put(line)
    output.put(None)


class Connector:
    def __init__(self, root, *, parent=False, loader=False, endpoint=None):
        self.root = root
        package = root / 'nodelang'
        package.mkdir()
        source = Path(__file__).resolve().parents[2] / '01.APP/nodelang'
        (package / '__init__.py').write_text('__path__.append(' + repr(str(source)) + ')', encoding='utf-8')
        shutil.copyfile(source / 'native_agent_mcp.py', package / 'native_agent_mcp.py')
        (root / 'probe_build.py').write_text("BUILD = 'A'\n", encoding='utf-8')
        (root / 'BUILD_ID').write_text('A', encoding='utf-8')
        (root / '.archhub-ready').write_text('venv-v1:A:fixture', encoding='ascii')
        (root / 'ENTRY.py').write_text(ENTRY, encoding='utf-8')
        argv = [sys.executable, '-B', str(root / 'ENTRY.py')]
        if loader:
            # The installed -I/-B/-c/runpy launcher mutates sys.argv, not orig_argv.
            code = "import runpy,sys;root=sys.argv.pop(1);sys.path.insert(0,root);runpy.run_path(root+'/ENTRY.py',run_name='__main__')"
            argv = [sys.executable, '-I', '-B', '-c', code, str(root)]
        if parent:
            (root / 'PARENT.py').write_text(
                'import subprocess,time,os\nfrom pathlib import Path\n'
                'Path(__file__).with_name("PARENT_PID").write_text(str(os.getpid()))\n'
                'p=subprocess.Popen(' + repr(argv) + ')\ntime.sleep(120)\n', encoding='utf-8')
            argv = [sys.executable, '-B', str(root / 'PARENT.py')]
        self.err = (root / 'STDERR').open('wb')
        env = {**os.environ, 'ARCHHUB_TEST_STATE_DIR':str(root),
               'ARCHHUB_COORDINATION_VENDOR':'codex', 'CODEX_THREAD_ID':'mcpfresh-fixture'}
        if endpoint:
            env['ARCHHUB_COORDINATION_ENDPOINT'] = endpoint
            env['MCPFRESH_REAL_MAILBOX'] = '1'
            env['CODEX_THREAD_ID'] += '-' + root.name
        self.process = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=self.err, env=env)
        self.lines = queue.Queue()
        self.reader = threading.Thread(target=_pump, args=(self.process.stdout, self.lines), daemon=True)
        self.reader.start()
        self.pids = {self.process.pid}
        self.send({'jsonrpc':'2.0', 'id':1, 'method':'initialize', 'params':{
            'protocolVersion':'2025-11-25', 'capabilities':{},
            'clientInfo':{'name':'MCPFRESH', 'version':'1'}}})
        assert 'result' in self.response(1)
        self.send({'jsonrpc':'2.0', 'method':'notifications/initialized'})

    def send(self, body):
        self.process.stdin.write(json.dumps(body).encode('utf-8') + b'\n')
        self.process.stdin.flush()

    def call(self, identity, text):
        self.send({'jsonrpc':'2.0', 'id':identity, 'method':'tools/call',
                   'params':{'name':'send', 'arguments':{'to':'fixture', 'text':text}}})

    def response(self, identity, timeout=15):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            line = self.lines.get(timeout=max(.01, deadline-time.monotonic()))
            assert line is not None, (self.root / 'STDERR').read_text(encoding='utf-8')
            message = json.loads(line)
            if message.get('id') == identity:
                result = message.get('result', {}).get('structuredContent', {})
                if 'pid' in result:
                    self.pids.add(result['pid'])
                return message
        raise AssertionError('No response: ' + str(identity))

    def update(self, value='B', *, ready=True):
        (self.root / 'probe_build.py').write_text('BUILD = ' + repr(value) + '\n', encoding='utf-8')
        (self.root / 'BUILD_ID').write_text(value, encoding='utf-8')
        if ready:
            (self.root / '.archhub-ready').write_text('venv-v1:' + value + ':fixture', encoding='ascii')

    def close(self):
        if self.process.stdin.closed:
            return
        try:
            self.process.stdin.close()
        except OSError:
            pass  # A failed child must still have all fixture processes reaped.
        self.reader.join(timeout=5)
        for pid in self.pids:
            try:
                process = psutil.Process(pid)
                process.terminate()
                process.wait(timeout=5)
            except psutil.NoSuchProcess:
                pass
        self.process.wait(timeout=5)
        self.process.stdout.close()
        self.err.close()


@pytest.fixture
def connector(tmp_path):
    running = []
    def start(**kwargs):
        instance = Connector(tmp_path, **kwargs)
        running.append(instance)
        return instance
    yield start
    for instance in running:
        instance.close()


@pytest.mark.parametrize('loader', [False, True])
def test_build_switch_uses_same_pipes_and_never_replays(connector, loader):
    client = connector(loader=loader)
    client.call(2, 'before')
    first = client.response(2)['result']['structuredContent']
    client.update()
    client.call(3, 'after')
    second = client.response(3)['result']['structuredContent']
    assert (first['build'], second['build']) == ('A', 'B')
    assert first['pid'] != second['pid'] if os.name == 'nt' else first['pid'] == second['pid']
    # The process the client started stays alive: a client that watches it (Claude Code) never sees
    # "server closed" on an install and never respawns into a half-updated app.
    assert client.process.poll() is None
    assert (client.root / 'EFFECTS').read_text(encoding='utf-8').splitlines() == ['"before"', '"after"']
    # Keep using the original pipe objects through another replacement.
    client.update('C')
    client.call(4, 'again')
    assert client.response(4)['result']['structuredContent']['build'] == 'C'
    assert client.process.poll() is None


def test_change_during_call_drains_response_before_reexec(connector):
    client = connector()
    client.call(2, 'slow')
    deadline = time.monotonic() + 10
    while not (client.root / 'ENTERED').exists() and time.monotonic() < deadline:
        time.sleep(.02)
    assert (client.root / 'ENTERED').exists()
    client.update()
    client.call(3, 'queued')
    (client.root / 'RELEASE').touch()
    assert client.response(2)['result']['structuredContent']['build'] == 'A'
    assert client.response(3)['result']['structuredContent']['build'] == 'B'
    assert sorted((client.root / 'EFFECTS').read_text(encoding='utf-8').splitlines()) == ['"queued"', '"slow"']


def test_dead_original_parent_exits_even_after_reexec(connector):
    client = connector(parent=True)
    client.call(2, 'before')
    client.response(2)
    client.update()
    client.call(3, 'after')
    pid = client.response(3)['result']['structuredContent']['pid']
    psutil.Process(int((client.root / 'PARENT_PID').read_text())).terminate()
    client.process.wait(timeout=5)
    deadline = time.monotonic() + 5
    while psutil.pid_exists(pid) and time.monotonic() < deadline:
        time.sleep(.05)
    assert not psutil.pid_exists(pid), 'orphan connector survived its original parent'


def test_dead_parent_without_update_exits_with_open_pipe(connector):
    client = connector(parent=True)
    client.call(2, 'before')
    pid = client.response(2)['result']['structuredContent']['pid']
    psutil.Process(int((client.root / 'PARENT_PID').read_text())).terminate()
    client.process.wait(timeout=5)
    deadline = time.monotonic() + 5
    while psutil.pid_exists(pid) and time.monotonic() < deadline:
        time.sleep(.05)
    assert not psutil.pid_exists(pid), 'orphan connector survived with inherited pipe still open'


def test_cancel_queued_request_does_not_execute_after_refresh(connector):
    client = connector()
    client.send({'jsonrpc':'2.0', 'id':2, 'method':'tools/call',
                 'params':{'name':'slow', 'arguments':{}}})
    deadline = time.monotonic() + 10
    while not (client.root / 'ENTERED').exists() and time.monotonic() < deadline:
        time.sleep(.02)
    assert (client.root / 'ENTERED').exists()
    client.update()
    client.call(3, 'cancelled queued effect')
    client.send({'jsonrpc':'2.0', 'method':'notifications/cancelled', 'params':{'requestId':3}})
    assert 'error' in client.response(3)
    (client.root / 'RELEASE').touch()
    client.response(2)
    client.call(4, 'after')
    assert client.response(4)['result']['structuredContent']['build'] == 'B'
    assert (client.root / 'EFFECTS').read_text(encoding='utf-8').splitlines() == ['"async slow"', '"after"']


def test_large_queued_frame_and_invalid_frame_keep_sdk_behavior(connector):
    client = connector()
    client.call(2, 'before')
    client.response(2)
    client.send({'jsonrpc':'2.0', 'id':[], 'method':'tools/call', 'params':{}})
    client.update()
    client.call(3, 'x' * 100000)
    result = client.response(3)['result']['structuredContent']
    assert result['build'] == 'B' and len(result['text']) == 100000


def test_large_undispatched_request_survives_continuation_environment(connector):
    client = connector()
    client.send({'jsonrpc':'2.0', 'id':2, 'method':'tools/call',
                 'params':{'name':'slow', 'arguments':{}}})
    deadline = time.monotonic() + 10
    while not (client.root / 'ENTERED').exists() and time.monotonic() < deadline:
        time.sleep(.02)
    assert (client.root / 'ENTERED').exists()
    client.update()
    client.call(3, 'x' * 100000)
    time.sleep(1)
    (client.root / 'RELEASE').touch()
    assert client.response(2)['result']['structuredContent']['build'] == 'A'
    assert client.response(3)['result']['structuredContent']['build'] == 'B'
    assert int((client.root / 'CONTINUATION_SIZE').read_text()) > 100000
    assert len((client.root / 'EFFECTS').read_text(encoding='utf-8').splitlines()) == 2


def test_partial_frame_is_not_lost_when_build_changes(connector):
    client = connector()
    client.call(2, 'before')
    client.response(2)
    message = json.dumps({'jsonrpc':'2.0', 'id':3, 'method':'tools/call',
        'params':{'name':'send', 'arguments':{'to':'fixture', 'text':'partial'}}}).encode() + b'\n'
    client.process.stdin.write(message[:40])
    client.process.stdin.flush()
    time.sleep(1)
    client.update()
    client.process.stdin.write(message[40:])
    client.process.stdin.flush()
    assert client.response(3)['result']['structuredContent']['build'] == 'B'
    assert (client.root / 'EFFECTS').read_text(encoding='utf-8').splitlines() == ['"before"', '"partial"']


@pytest.mark.parametrize('state', ['uncertain', 'released'])
def test_unsettled_owner_is_retained_until_existing_recovery_clears_it(connector, state):
    client = connector()
    client.send({'jsonrpc':'2.0', 'id':2, 'method':'tools/call',
        'params':{'name':'custody', 'arguments':{'state':state}}})
    original = client.response(2)['result']['structuredContent']
    client.update()
    client.call(3, 'retained')
    retained = client.response(3)['result']['structuredContent']
    assert retained['build'] == 'A' and retained['pid'] == original['pid']
    client.send({'jsonrpc':'2.0', 'id':4, 'method':'tools/call',
        'params':{'name':'custody', 'arguments':{'state':'clear'}}})
    assert client.response(4)['result']['structuredContent']['build'] == 'A'
    client.call(5, 'after recovery')
    assert client.response(5)['result']['structuredContent']['build'] == 'B'


def test_real_sdk_client_keeps_connection_after_windows_replacement(connector):
    from datetime import timedelta
    import anyio
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    client = connector()
    client.close()
    pids = []
    async def run():
        params = StdioServerParameters(command=sys.executable, args=['-B', str(client.root / 'ENTRY.py')],
            env={'ARCHHUB_TEST_STATE_DIR':str(client.root), 'ARCHHUB_COORDINATION_VENDOR':'codex',
                 'CODEX_THREAD_ID':'mcpfresh-sdk-fixture'})
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write, read_timeout_seconds=timedelta(seconds=15)) as session:
                await session.initialize()
                first = await session.call_tool('send', {'to':'fixture', 'text':'before'})
                pids.append(first.structuredContent['pid'])
                client.update()
                second = await session.call_tool('send', {'to':'fixture', 'text':'after'})
                pids.append(second.structuredContent['pid'])
                assert (first.structuredContent['build'], second.structuredContent['build']) == ('A', 'B')
    try:
        anyio.run(run)
    finally:
        for pid in pids:
            try:
                process = psutil.Process(pid)
                process.wait(timeout=5)
            except psutil.NoSuchProcess:
                pass


def test_metadata_actor_and_dynamic_unresolved_receipt_survive_repeated_refresh():
    from nodelang import native_agent_mcp as native
    from nodelang.native_workshop_tools import build_workshop_task_server
    server = native.build_server(mailbox_call=lambda *args: {})
    actor = 'app:agent-session:runtime:' + 'a' * 32
    server.work_control.continuations[('codex', 'not-reused-on-B')] = actor
    task = build_workshop_task_server(server.work_control, 'assembly-instance:fixture-work')
    held = task.selected_work
    held.pending = ('configure', 42, {'proposal':'x' * 100000})
    held.court_response_received = True
    server._mcpfresh_attached.update(held=held, names=[], server=server)
    server._mcpfresh_level = 'error'
    for _ in range(2):
        state = json.loads(json.dumps(native._work_continuation(server)))
        server = native.build_server(mailbox_call=lambda *args: {})
        native._restore_work_continuation(server, state)
        assert server.work_control.continuations[('codex', 'not-reused-on-B')] == actor
        restored = server._mcpfresh_attached['held']
        assert restored.pending == held.pending and restored.court_response_received
        assert server._mcpfresh_level == 'error'
        assert server._tool_manager.get_tool('native.work_reconcile') is not None


@pytest.mark.parametrize('state,candidate,retired,active,expected', [
    ('unbound', None, None, 0, True), ('bound', None, None, 0, True),
    ('uncertain', None, None, 0, False), ('released', None, None, 0, False),
    ('bound', object(), None, 0, False), ('bound', None, object(), 0, False),
    ('bound', None, None, 1, None),
])
def test_unresolved_native_custody_never_turns_into_new_enrollment(state, candidate, retired, active, expected):
    from types import SimpleNamespace
    from nodelang import native_agent_mcp as native
    server = native.build_server(mailbox_call=lambda *args: {})
    server.work_control.owner = SimpleNamespace(_lock=threading.RLock(), _state=state,
        _rebind_candidate=candidate, _retired_release=retired, _active_calls=active,
        _client=SimpleNamespace(_continuation_request={'already':'accepted'}))
    transport = object.__new__(native._FreshStdio)
    transport.server = server
    assert transport._settled() is expected


def test_final_recheck_holds_stop_then_owner_locks_through_replacement(monkeypatch):
    from types import SimpleNamespace
    from nodelang import native_agent_mcp as native
    from nodelang.native_stop_hook import StopHostSupervisor
    server = native.build_server(mailbox_call=lambda *args: {})
    owner = SimpleNamespace(_lock=threading.RLock(), _state='bound',
        _active_calls=0, _rebind_candidate=None, _retired_release=None)
    supervisor = StopHostSupervisor(owner)
    server.work_control.owner, server.work_control.supervisor = owner, supervisor
    transport = object.__new__(native._FreshStdio)
    transport.server = server
    replaced = []
    def replace(build):
        acquired = []
        def background():
            for lock in (supervisor._lock, owner._lock):
                held = lock.acquire(blocking=False)
                acquired.append(held)
                if held:
                    lock.release()
        thread = threading.Thread(target=background)
        thread.start()
        thread.join(timeout=2)
        assert acquired == [False, False]
        replaced.append(build)
    transport._replace = replace
    assert transport._settled() is True
    owner._state, owner._rebind_candidate = 'uncertain', object()
    transport._exec('B')
    assert not replaced, 'custody changed after the first check; it must remain retained'
    owner._state, owner._rebind_candidate = 'bound', None
    transport._exec('B')
    assert replaced == ['B']
    # Nonblocking acquisition cannot invert a Stop thread holding its supervisor.
    ready, release = threading.Event(), threading.Event()
    def reconcile():
        with supervisor._lock:
            ready.set()
            release.wait(timeout=2)
    thread = threading.Thread(target=reconcile)
    thread.start()
    assert ready.wait(timeout=2)
    try:
        transport._exec('C')
        assert replaced == ['B']
    finally:
        release.set()
        thread.join(timeout=2)
    # Exercise the real Stop shutdown segment with its actual nonreentrant lock.
    del transport._replace
    closed = []
    supervisor._host = SimpleNamespace(close=lambda: closed.append(True) or True)
    transport.parent = {'pid':os.getpid(), 'created_at':psutil.Process().create_time()}
    transport.initialize = '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}'
    transport.waiting, transport.buffer, transport.build = [], bytearray(), 'A'
    transport.output = SimpleNamespace(flush=lambda: None)
    class Replaced(BaseException):
        pass
    def finish(*args, **kwargs):
        raise Replaced
    monkeypatch.setattr(subprocess, 'Popen', lambda *args, **kwargs: types.SimpleNamespace(wait=lambda: 0))  # the shim waits on its successor
    monkeypatch.setattr(native.os, '_exit', finish)
    monkeypatch.setattr(native.os, 'execve', finish)
    with pytest.raises(Replaced):
        transport._exec('B')
    assert closed == [True] and supervisor._closed.is_set() and supervisor._host is None


def test_response_is_not_marked_flushed_before_its_write_finishes(monkeypatch):
    import anyio
    from types import SimpleNamespace
    from nodelang import native_agent_mcp as native
    async def run():
        started, release = anyio.Event(), anyio.Event()
        writes = []
        output = SimpleNamespace(write=lambda value: writes.append(value), flush=lambda: None)
        transport = object.__new__(native._FreshStdio)
        transport.output, transport.inflight, transport.flushed = output, {2}, set()
        transport.suppress_initialize = False
        async def delayed(function, *args):
            if function is output.write:
                started.set()
                await release.wait()
            return function(*args)
        monkeypatch.setattr(anyio.to_thread, 'run_sync', delayed)
        async with anyio.create_task_group() as group:
            group.start_soon(transport.write, '{"jsonrpc":"2.0","id":2,"result":{}}\n')
            await started.wait()
            await transport.flush()
            assert transport.inflight == {2} and not writes
            release.set()
        assert transport.inflight == {2} and transport.flushed == {2}
        await transport.flush()
        assert not transport.inflight and len(writes) == 1
    anyio.run(run)


def test_eight_sequential_calls_have_under_60ms_median(connector):
    from statistics import median
    client = connector()
    elapsed = []
    for identity in range(2, 10):
        started = time.monotonic()
        client.call(identity, str(identity))
        assert client.response(identity)['result']['structuredContent']['build'] == 'A'
        elapsed.append((time.monotonic() - started) * 1000)
    print('Sequential call milliseconds:', elapsed, 'median:', median(elapsed))
    assert median(elapsed) < 60


def test_build_waits_for_matching_ready_marker(connector):
    client = connector()
    client.call(2, 'before')
    first = client.response(2)['result']['structuredContent']
    client.update(ready=False)
    client.call(3, 'not ready')
    assert client.response(3)['result']['structuredContent'] == {**first, 'text':'not ready'}
    (client.root / '.archhub-ready').write_text('venv-v1:B:fixture', encoding='ascii')
    client.call(4, 'ready')
    assert client.response(4)['result']['structuredContent']['build'] == 'B'


def test_failed_popen_keeps_answering_without_retry_storm(connector):
    client = connector()
    client.call(2, 'before')
    first = client.response(2)['result']['structuredContent']
    (client.root / 'FAIL_RESTART').touch()
    client.update()
    for identity in (3, 4):
        client.call(identity, 'still answering')
        assert client.response(identity)['result']['structuredContent']['pid'] == first['pid']
    time.sleep(.6)
    client.call(5, 'after another tick')
    assert client.response(5)['result']['structuredContent']['pid'] == first['pid']
    assert (client.root / 'STDERR').read_text(encoding='utf-8').count('fixture restart refused') == 1
    (client.root / 'FAIL_RESTART').unlink()
    client.update('C')
    client.call(6, 'later build')
    assert client.response(6)['result']['structuredContent']['build'] == 'C'


@pytest.mark.parametrize('denied', ['exe', 'cmdline'])
def test_denied_parent_metadata_falls_back_to_direct_parent(monkeypatch, denied):
    from types import SimpleNamespace
    from nodelang import native_agent_mcp as native
    direct = SimpleNamespace(pid=os.getpid(), create_time=lambda: 42,
        exe=lambda: sys.executable, cmdline=lambda: ['python', 'fixture'])
    def refuse():
        raise psutil.AccessDenied(direct.pid)
    setattr(direct, denied, refuse)
    process = SimpleNamespace(parent=lambda: direct, cmdline=lambda: ['python', 'fixture'])
    monkeypatch.setattr(psutil, 'Process', lambda: process)
    read, write = os.pipe()
    monkeypatch.setattr(sys, 'stdin', SimpleNamespace(fileno=lambda: read))
    try:
        transport = native._FreshStdio(native.build_server(mailbox_call=lambda *args: {}))
        assert transport.parent == {'pid':direct.pid, 'created_at':42}
    finally:
        os.close(read)
        os.close(write)


def test_failed_launch_leaves_stop_supervisor_open(monkeypatch):
    from types import SimpleNamespace
    from nodelang import native_agent_mcp as native
    from nodelang.native_stop_hook import StopHostSupervisor
    server = native.build_server(mailbox_call=lambda *args: {})
    owner = SimpleNamespace(_lock=threading.RLock(), _state='bound',
        _active_calls=0, _rebind_candidate=None, _retired_release=None)
    supervisor = StopHostSupervisor(owner)
    closed = []
    supervisor._host = SimpleNamespace(close=lambda: closed.append(True) or True)
    server.work_control.owner, server.work_control.supervisor = owner, supervisor
    transport = object.__new__(native._FreshStdio)
    transport.server, transport.parent, transport.initialize = server, None, None
    transport.waiting, transport.buffer, transport.build = [], bytearray(), 'A'
    transport.output = SimpleNamespace(flush=lambda: None)
    def refuse(*args, **kwargs):
        raise OSError('fixture restart refused')
    monkeypatch.setattr(subprocess, 'Popen', refuse)
    transport._exec('B')
    assert transport.build == 'B'
    assert not supervisor._closed.is_set() and not closed and supervisor._host is not None


def test_two_connectors_commit_while_peer_is_mid_call(owner, tmp_path, monkeypatch):
    from nodelang import desktop
    from nodelang import workshop_mailbox as mail
    server, root = owner
    surface = desktop.bind_coordination_surface(server, root)
    endpoint = 'http://127.0.0.1:%d/coordination' % surface.server_address[1]
    entered, release = threading.Event(), threading.Event()
    class NativeWait:
        def inject(self, *args, **kwargs):
            entered.set()
            assert release.wait(timeout=15), 'fixture injection was not released'
            return {'status':'injected'}
    original_call = mail.call
    def measured_call(*args, **kwargs):
        history = kwargs['history']
        result = original_call(*args, **kwargs)
        result['busy_timeout_ms'] = history._db.execute('PRAGMA busy_timeout').fetchone()[0]
        return result
    monkeypatch.setattr(mail, 'call', measured_call)
    clients = []
    try:
        for name in ('FIRST', 'SECOND'):
            root = tmp_path / name
            root.mkdir()
            clients.append(Connector(root, endpoint=endpoint))
        first, second = clients
        injection = mail.WorkshopInjection(server, NativeWait())
        # Run the real injection tick in the send handler to hold that request mid-call.
        wake = injection.wake
        injection.wake = lambda: wake() if entered.is_set() else injection.tick()
        server.workshop_injection = injection
        first.send({'jsonrpc':'2.0', 'id':2, 'method':'tools/call', 'params':{
            'name':'send', 'arguments':{'to':'codex', 'text':'slow'}}})
        assert entered.wait(timeout=10)
        assert not first.lines.qsize(), 'the first request must still be awaiting injection'
        started = time.monotonic()
        second.call(2, 'peer commits')
        result = second.response(2)['result']['structuredContent']
        elapsed = time.monotonic() - started
        assert elapsed < result['busy_timeout_ms'] / 1000 and result['message_id']
        print('Production HTTP peer commit seconds:', elapsed, 'busy timeout ms:', result['busy_timeout_ms'])
        release.set()
        assert first.response(2)['result']['structuredContent']['message_id']
        second.call(3, 'after both responses')
        assert second.response(3)['result']['structuredContent']['message_id']
    finally:
        release.set()
        for client in clients:
            client.close()
