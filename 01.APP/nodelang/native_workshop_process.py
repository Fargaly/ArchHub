"""Bounded physical Claude stream owned by an admitted application caller.

This module holds no graph, assignment, credential store or execution authority.
The caller supplies the complete launch profile and admits every turn. A returned
model result is stream completion, never proof that Work or effects succeeded.
Limits request cooperative interruption/EOF first. When a stop outlives its
cooperative budget, the owned tree (only processes this object observed, matched
by PID and creation time) is terminated, so a user's Stop really ends the run.
The caller must still reconcile the interrupted turn's unknown outcome.
"""
from collections import deque
from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import subprocess
import threading
import time
import uuid


def _text(value, maximum):
    return type(value) is str and bool(value) and '\0' not in value and len(value.encode('utf-8')) <= maximum


@dataclass(frozen=True, slots=True, repr=False)
class NativeWorkshopLaunch:
    argv: tuple[str, ...]
    env: tuple[tuple[str, str], ...]
    cwd: str
    runtime: str
    external_session_id: str
    max_input_bytes: int
    max_output_bytes: int
    max_event_bytes: int
    max_events: int
    max_process_bytes: int
    startup_timeout_seconds: float
    turn_timeout_seconds: float
    lifetime_seconds: float
    stop_timeout_seconds: float
    max_processes: int = 32

    def __post_init__(self):
        if (self.runtime != 'claude' or not _text(self.external_session_id, 128)
                or str(uuid.UUID(self.external_session_id)) != self.external_session_id):
            raise ValueError('native stream requires an explicit Claude session UUID')
        if (type(self.argv) is not tuple or not 1 <= len(self.argv) <= 128
                or not _text(self.argv[0], 8192)
                or any(type(item) is not str or '\0' in item or len(item.encode('utf-8')) > 8192
                       for item in self.argv[1:])
                or sum(len(item.encode('utf-8')) for item in self.argv) > 65536
                or not _text(self.cwd, 32768) or not Path(self.cwd).is_absolute()):
            raise ValueError('invalid native launch arguments or directory')
        if type(self.env) is not tuple or len(self.env) > 1024:
            raise ValueError('native environment must be an immutable explicit tuple')
        names, size = set(), 0
        for pair in self.env:
            if (type(pair) is not tuple or len(pair) != 2 or not _text(pair[0], 512)
                    or '=' in pair[0] or pair[0].casefold() in names
                    or type(pair[1]) is not str or '\0' in pair[1]):
                raise ValueError('invalid native environment')
            names.add(pair[0].casefold())
            size += len(pair[0].encode('utf-8')) + len(pair[1].encode('utf-8'))
        if size > 1024 * 1024:
            raise ValueError('native environment exceeds its bound')
        environment = {key.casefold():value for key, value in self.env}
        for name, expected in (('archhub_agent_runtime', self.runtime),
                ('archhub_external_session_id', self.external_session_id),
                ('claude_code_session_id', self.external_session_id),
                ('claude_session_id', self.external_session_id)):
            if name in environment and environment[name] != expected:
                raise ValueError('native launch identity conflicts with its environment')
        for value, minimum, maximum in (
                (self.max_input_bytes, 1024, 16 * 1024 * 1024),
                (self.max_output_bytes, 1024, 16 * 1024 * 1024),
                (self.max_event_bytes, 256, 1024 * 1024),
                (self.max_events, 1, 2048),
                (self.max_processes, 1, 64),
                (self.max_process_bytes, 1024 * 1024, 8 * 1024**3)):
            if type(value) is not int or not minimum <= value <= maximum:
                raise ValueError('invalid native resource budget')
        if self.max_event_bytes > self.max_output_bytes:
            raise ValueError('native event budget exceeds output budget')
        for value in (self.startup_timeout_seconds, self.turn_timeout_seconds,
                      self.lifetime_seconds, self.stop_timeout_seconds):
            if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value <= 3600:
                raise ValueError('invalid native time budget')
        if (max(self.startup_timeout_seconds, self.turn_timeout_seconds) > self.lifetime_seconds
                or self.stop_timeout_seconds > 60):
            raise ValueError('native time budgets are inconsistent')


class ObservedNativeProcessTree:
    """Bounded observations, not OS containment or proof of unseen children.

    Query direct children only beneath retained owned identities. A process seen
    once stays in this registry after its parent exits. The host must observe the
    expected MCP child before dispatch; absence of observations is not clearance.
    """
    def __init__(self, max_processes):
        self.max_processes = max_processes
        self._owned = {}
        self._root = None

    def __call__(self, process):
        import psutil
        if self._root is None:
            if process.poll() is not None:
                raise RuntimeError('native root exited before observation')
            native = psutil.Process(process.pid)
            created = native.create_time()
            if process.poll() is not None:
                raise RuntimeError('native root changed during observation')
            self._root = (native.pid, created)
            self._owned[self._root] = (native, None)
        elif process.pid != self._root[0]:
            raise RuntimeError('native root identity changed')
        observations, queue = {}, list(self._owned)
        while queue:
            identity = queue.pop(0)
            native, parent = self._owned[identity]
            try:
                # Fresh create_time defeats psutil's cached creation timestamp.
                current = psutil.Process(identity[0])
                if current.create_time() != identity[1]:
                    raise RuntimeError('observed native PID was reused')
                alive = current.is_running()
                rss = current.memory_info().rss if alive else 0
                children = current.children(recursive=False) if alive else ()
                if len(children) > self.max_processes:
                    raise RuntimeError('native descendants exceed observation budget')
                for child in children:
                    try:
                        child_created, parent_pid = child.create_time(), child.ppid()
                    except psutil.NoSuchProcess:
                        continue  # A transient unobserved child cannot mark its live parent exited.
                    if parent_pid != identity[0] or child_created < identity[1]:
                        raise RuntimeError('native descendant ancestry changed')
                    key = (child.pid, child_created)
                    if key not in self._owned:
                        if len(self._owned) >= self.max_processes:
                            raise RuntimeError('native descendant registry is full')
                        self._owned[key] = (child, identity)
                        queue.append(key)
                    elif self._owned[key][1] != identity:
                        raise RuntimeError('native descendant parent identity changed')
            except psutil.NoSuchProcess:
                alive, rss = False, 0
            observations[identity] = {'pid':identity[0], 'created_at':identity[1],
                'parent_pid':None if parent is None else parent[0],
                'parent_created_at':None if parent is None else parent[1], 'alive':alive, 'rss':rss}
        return tuple(observations.values())


def _terminate_owned_tree(observer, process):
    """Kill the observed owned tree, children first, then the root handle.

    Only identities the observer recorded (PID plus creation time) are killed,
    so a reused PID is never touched. Returns the number of kill requests.
    """
    killed = 0
    owned = getattr(observer, '_owned', None)
    if isinstance(owned, dict):
        try:
            import psutil
        except ImportError:
            psutil = None
        if psutil is not None:
            for (pid, created), _entry in reversed(list(owned.items())):
                try:
                    current = psutil.Process(pid)
                    if current.create_time() != created or not current.is_running():
                        continue
                    current.kill()
                    killed += 1
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
    kill = getattr(process, 'kill', None)
    if callable(kill) and process.poll() is None:
        try:
            kill()
            killed += 1
        except OSError:
            pass
    return killed


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate stream field')
        result[key] = value
    return result


def _reject_constant(_value):
    raise ValueError('nonfinite stream number')


def _finite_float(value):
    number = float(value)
    if not math.isfinite(number):
        raise ValueError('nonfinite stream number')
    return number


class NativeWorkshopProcess:
    """One child, one active turn, bounded queues, and no automatic replay.

    Only the two pipe owners run threads. The stdin owner checks time budgets
    while waiting; status/wait/stop observe the owned tree outside the pipe lock.
    The admitted host must service wait_event/status during an active operation.
    Pipe threads and the exact process handle remain retained until they exit.
    """
    def __init__(self, launch, *, launch_factory=subprocess.Popen,
                 clock=time.monotonic, tree_observer=None):
        if not isinstance(launch, NativeWorkshopLaunch):
            raise TypeError('native launch configuration is required')
        self.launch = launch
        self._launch_factory, self._clock = launch_factory, clock
        self._tree_observer = tree_observer if tree_observer is not None else ObservedNativeProcessTree(launch.max_processes)
        self._observation_lock = threading.Lock()
        self._tree = {}
        self._tree_observed = False
        self._tree_uncertain = False
        self._last_tree_sample = None
        self._condition = threading.Condition(threading.RLock())
        self._process = None
        self._threads = []
        self._commands, self._events = deque(), deque()
        self._pending = {}
        self._terminal_ids = set()
        self._started = self._turn_started = None
        self._initialized = self._initialize_sent = False
        self._closing = self._eof_sent = self._stdout_eof = False
        self._active_turn = None
        self._last_turn = None
        self._error = ''
        self._input_bytes = self._output_bytes = self._queued_bytes = 0
        self._memory_bytes = 0
        self._attempted = False

    def start(self):
        with self._condition:
            if self._attempted or self._closing:
                raise RuntimeError('native launch is single-attempt; inspect the retained status')
            self._attempted = True
            try:
                # Retain before pipe checks, thread construction or any other setup.
                self._process = self._launch_factory(self.launch.argv, env=dict(self.launch.env),
                    cwd=self.launch.cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL, shell=False, bufsize=0,
                    creationflags=(getattr(subprocess, 'CREATE_NO_WINDOW', 0)
                        | getattr(subprocess, 'BELOW_NORMAL_PRIORITY_CLASS', 0)))
                self._started = self._clock()
                if self._process.stdin is None or self._process.stdout is None:
                    raise ValueError('native pipes unavailable')
                for name, target in (('stdout', self._read), ('stdin', self._write)):
                    thread = threading.Thread(target=target, name='archhub-native-' + name, daemon=False)
                    self._threads.append(thread)
                    thread.start()
            except Exception:
                self._fail_locked('launch_setup_failed')
                # No command has been written if the stdin owner did not start.
                if len(self._threads) < 2 or self._threads[-1].ident is None:
                    self._close_unstarted_input()
            self._check_locked()
        return self.status(force_observation=True)

    def _close_unstarted_input(self):
        if self._process is not None and self._process.stdin is not None:
            try:
                self._process.stdin.close()
                self._eof_sent = True
            except Exception:
                pass

    def _enqueue_locked(self, value):
        payload = json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8') + b'\n'
        if (len(payload) > self.launch.max_event_bytes or len(self._commands) >= 16
                or self._input_bytes + len(payload) > self.launch.max_input_bytes):
            raise ValueError('native input budget exhausted')
        self._input_bytes += len(payload)
        kind = value['request']['subtype'] if value['type'] == 'control_request' else value['type']
        self._commands.append((payload, value.get('request_id'), kind))
        self._condition.notify_all()

    def _control_locked(self, subtype):
        request_id = uuid.uuid4().hex
        self._enqueue_locked({'type':'control_request', 'request_id':request_id,
                              'request':{'subtype':subtype}})
        self._pending[request_id] = subtype
        return request_id

    def _ready_locked(self, *, initialized=True):
        self._check_locked()
        if (self._process is None or self._process.poll() is not None or self._closing
                or self._error or initialized and not self._initialized):
            raise RuntimeError('native process is not ready; inspect status')

    def initialize(self):
        with self._condition:
            self._ready_locked(initialized=False)
            if self._initialize_sent:
                raise RuntimeError('native initialization has already been sent')
            request_id = self._control_locked('initialize')
            self._initialize_sent = True
            return request_id

    def mcp_status(self):
        with self._condition:
            self._ready_locked()
            if 'mcp_status' in self._pending.values():
                raise RuntimeError('native MCP status request is already pending')
            return self._control_locked('mcp_status')

    def turn(self, prompt):
        if not _text(prompt, self.launch.max_input_bytes):
            raise ValueError('native turn input is invalid or exceeds its bound')
        if not self._observe_tree(force=True):
            raise RuntimeError('native process observation is incomplete; inspect status')
        with self._condition:
            self._ready_locked()
            if self._active_turn is not None:
                raise RuntimeError('one native turn is already active')
            if len(self._terminal_ids) >= self.launch.max_events:
                raise RuntimeError('native process turn history budget exhausted')
            turn_id = uuid.uuid4().hex
            self._enqueue_locked({'type':'user', 'message':{'role':'user', 'content':prompt},
                'session_id':self.launch.external_session_id, 'parent_tool_use_id':None})
            self._active_turn = turn_id
            self._turn_started = self._clock()
            self._last_turn = {'turn_id':turn_id, 'outcome':'running'}
            return turn_id

    def interrupt(self):
        with self._condition:
            self._ready_locked()
            if self._active_turn is None:
                raise RuntimeError('there is no active native turn to interrupt')
            return self._fail_locked('turn_interrupted')

    def _begin_stop_locked(self, *, queue_interrupt=True):
        request_id = None
        if not self._closing:
            # Stop must not launch a queued turn or send a stale pending probe.
            while self._commands:
                _, pending_id, _ = self._commands.popleft()
                if pending_id is not None:
                    self._pending.pop(pending_id, None)
            if queue_interrupt and self._active_turn is not None and self._initialized:
                try:
                    request_id = self._control_locked('interrupt')
                except (ValueError, RuntimeError):
                    pass
            self._closing = True
            self._condition.notify_all()
        return request_id

    def _fail_locked(self, code, *, queue_interrupt=True):
        self._error = self._error or code
        if self._last_turn is not None and self._active_turn is not None:
            self._last_turn = {'turn_id':self._active_turn, 'outcome':'uncertain'}
        return self._begin_stop_locked(queue_interrupt=queue_interrupt)

    def _check_locked(self):
        process = self._process
        if process is None:
            return
        if process.poll() is not None:
            # A child may exit after writing its result but before our reader
            # drains it. EOF, not poll(), settles a missing final result.
            if self._stdout_eof and self._active_turn is not None:
                self._fail_locked('process_exited_before_result', queue_interrupt=False)
            return
        if self._started is None:
            self._fail_locked('launch_setup_failed')
            return
        now = self._clock()
        if self._started is not None and now - self._started >= self.launch.lifetime_seconds:
            self._fail_locked('lifetime_exceeded')
        elif not self._initialized and now - self._started >= self.launch.startup_timeout_seconds:
            self._fail_locked('startup_timeout')
        elif self._active_turn is not None and now - self._turn_started >= self.launch.turn_timeout_seconds:
            self._fail_locked('turn_timeout')

    def _observe_tree(self, *, force=False):
        if not self._observation_lock.acquire(blocking=False):
            return False
        try:
            with self._condition:
                process = self._process
                now = time.monotonic()
                if process is None:
                    return False
                root_exited = process.poll() is not None and any(
                    row['parent_pid'] is None and row['alive'] for row in self._tree.values())
                if not force and not root_exited and self._last_tree_sample is not None and now - self._last_tree_sample < 1.0:
                    return self._tree_observed and not self._tree_uncertain
                self._last_tree_sample = now
            try:
                # This may query process metadata, so never hold the pipe lock.
                observed = self._tree_observer(process)
                if not isinstance(observed, (tuple, list)) or not 1 <= len(observed) <= self.launch.max_processes:
                    raise ValueError('native tree observation is incomplete')
                rows = {}
                fields = {'pid','created_at','parent_pid','parent_created_at','alive','rss'}
                for row in observed:
                    if type(row) is not dict or set(row) != fields:
                        raise ValueError('invalid native process observation')
                    if (type(row['pid']) is not int or row['pid'] <= 0 or type(row['alive']) is not bool
                            or type(row['rss']) is not int or row['rss'] < 0
                            or not row['alive'] and row['rss'] != 0
                            or type(row['created_at']) not in (int, float)
                            or not math.isfinite(row['created_at']) or row['created_at'] < 0):
                        raise ValueError('invalid native process identity or memory')
                    if row['parent_pid'] is not None and (
                            type(row['parent_pid']) is not int or row['parent_pid'] <= 0
                            or type(row['parent_created_at']) not in (int, float)
                            or not math.isfinite(row['parent_created_at']) or row['parent_created_at'] < 0):
                        raise ValueError('invalid native parent identity')
                    key = (row['pid'], row['created_at'])
                    if any(prior[0] == key[0] for prior in rows) or any(
                            prior[0] == key[0] and prior != key for prior in self._tree):
                        raise ValueError('native process identity was repeated or reused')
                    rows[key] = dict(row)
                roots = [key for key, row in rows.items() if row['parent_pid'] is None]
                if len(roots) != 1 or roots[0][0] != process.pid or rows[roots[0]]['parent_created_at'] is not None:
                    raise ValueError('native process root is incomplete')
                for key, row in rows.items():
                    if key in self._tree and (row['parent_pid'], row['parent_created_at']) != (
                            self._tree[key]['parent_pid'], self._tree[key]['parent_created_at']):
                        raise ValueError('native process parent binding changed')
                    if row['parent_pid'] is not None:
                        parent = (row['parent_pid'], row['parent_created_at'])
                        if parent not in rows or parent == key or parent[1] > key[1]:
                            raise ValueError('native process ancestry is incomplete')
                        seen, ancestor = {key}, parent
                        while ancestor != roots[0]:
                            if ancestor in seen or ancestor not in rows:
                                raise ValueError('native process ancestry is cyclic')
                            seen.add(ancestor)
                            prior = rows[ancestor]
                            ancestor = (prior['parent_pid'], prior['parent_created_at'])
                if set(self._tree) - set(rows):
                    raise ValueError('observed native descendants disappeared without exit evidence')
                with self._condition:
                    self._tree = rows
                    self._tree_observed = True
                    self._memory_bytes = sum(row['rss'] for row in rows.values() if row['alive'])
                    if self._memory_bytes > self.launch.max_process_bytes:
                        self._fail_locked('memory_budget_exceeded')
                    return not self._tree_uncertain
            except Exception:
                with self._condition:
                    self._tree_uncertain = True
                    self._fail_locked('tree_observation_uncertain')
                    return False
        finally:
            self._observation_lock.release()

    def _write(self):
        stream = self._process.stdin
        try:
            while True:
                with self._condition:
                    self._check_locked()
                    while not self._commands and not self._closing:
                        self._condition.wait(0.25)
                        self._check_locked()
                    if not self._commands:
                        break
                    payload, _, kind = self._commands.popleft()
                remaining = memoryview(payload)
                while remaining:
                    with self._condition:
                        if self._closing and kind != 'interrupt':
                            if len(remaining) != len(payload):
                                # Do not append a control JSON object to a partial
                                # user frame. EOF retains its uncertain delivery.
                                raise OSError('native frame interrupted during delivery')
                            break
                    written = stream.write(remaining[:4096])
                    if type(written) is not int or written <= 0 or written > min(4096, len(remaining)):
                        raise OSError('native input write did not advance')
                    remaining = remaining[written:]
                stream.flush()
        except Exception:
            with self._condition:
                self._fail_locked('input_delivery_uncertain', queue_interrupt=False)
        finally:
            try:
                stream.close()
                with self._condition:
                    self._eof_sent = True
            except Exception:
                with self._condition:
                    self._error = self._error or 'input_close_failed'
            with self._condition:
                self._condition.notify_all()

    def _accept_locked(self, event, size):
        if type(event) is not dict or type(event.get('type')) is not str:
            raise ValueError('invalid stream event')
        kind = event['type']
        if kind not in ('control_response', 'system', 'assistant', 'user', 'result', 'stream_event'):
            raise ValueError('unsupported stream event')
        if ('session_id' in event and event['session_id'] != self.launch.external_session_id
                or kind in ('assistant', 'user', 'result', 'stream_event')
                and event.get('session_id') != self.launch.external_session_id):
            raise ValueError('native stream session mismatch')
        if len(self._events) >= self.launch.max_events or self._queued_bytes + size > self.launch.max_output_bytes:
            raise ValueError('native event queue exhausted')
        if kind == 'control_response':
            response = event.get('response')
            if type(response) is not dict or response.get('subtype') not in ('success', 'error'):
                raise ValueError('invalid control response')
            if response['subtype'] == 'success' and type(response.get('response')) is not dict:
                raise ValueError('invalid control success payload')
            request_id = response.get('request_id')
            if type(request_id) is not str or request_id not in self._pending:
                raise ValueError('unmatched control response')
            operation = self._pending.pop(request_id)
            if response['subtype'] == 'error':
                self._fail_locked('control_request_refused')
            elif operation == 'initialize':
                self._initialized = True
        if kind == 'result':
            if self._active_turn is None:
                raise ValueError('result has no active native turn')
            terminal_id = event.get('uuid')
            if (not _text(terminal_id, 128) or str(uuid.UUID(terminal_id)) != terminal_id
                    or terminal_id in self._terminal_ids):
                raise ValueError('invalid or repeated native terminal identity')
            subtype = event.get('subtype')
            if type(event.get('is_error')) is not bool:
                raise ValueError('invalid result status')
            if subtype == 'success':
                if event['is_error'] or type(event.get('result')) is not str:
                    raise ValueError('invalid successful terminal result')
            elif subtype in ('error_during_execution', 'error_max_turns',
                    'error_max_budget_usd', 'error_max_structured_output_retries'):
                if (not event['is_error'] or type(event.get('errors')) is not list
                        or len(event['errors']) > 64 or any(type(error) is not str for error in event['errors'])):
                    raise ValueError('invalid error terminal result')
            else:
                raise ValueError('unknown native terminal result')
            self._terminal_ids.add(terminal_id)
            self._last_turn = {'turn_id':self._active_turn, 'outcome':
                'uncertain' if self._error or self._closing else
                'provider-error' if event.get('is_error') else 'returned'}
            self._active_turn = None
            self._turn_started = None
        self._events.append((event, size))
        self._queued_bytes += size
        self._condition.notify_all()

    def _read(self):
        stream = self._process.stdout
        discard = False
        pending = bytearray()
        try:
            while True:
                chunk = stream.read(min(4096, self.launch.max_event_bytes + 1))
                if not chunk:
                    if pending and not discard:
                        with self._condition:
                            self._fail_locked('stream_protocol_refused')
                    break
                with self._condition:
                    self._output_bytes = min(self.launch.max_output_bytes + 1, self._output_bytes + len(chunk))
                    if type(chunk) is not bytes or self._output_bytes > self.launch.max_output_bytes:
                        self._fail_locked('output_budget_exceeded')
                        discard = True
                    if discard:
                        pending.clear()
                        continue
                    pending.extend(chunk)
                    while b'\n' in pending:
                        end = pending.index(b'\n') + 1
                        if end > self.launch.max_event_bytes:
                            self._fail_locked('output_budget_exceeded')
                            discard = True
                            break
                        raw = bytes(pending[:end])
                        del pending[:end]
                        try:
                            event = json.loads(raw.decode('utf-8'), object_pairs_hook=_object,
                                parse_constant=_reject_constant, parse_float=_finite_float)
                            self._accept_locked(event, len(raw))
                        except (ValueError, TypeError, UnicodeError, RecursionError):
                            self._fail_locked('stream_protocol_refused')
                            discard = True
                            break
                    if len(pending) > self.launch.max_event_bytes:
                        self._fail_locked('output_budget_exceeded')
                        discard = True
                    if discard:
                        pending.clear()
        except Exception:
            with self._condition:
                self._fail_locked('output_stream_failed')
        finally:
            try:
                stream.close()
            except Exception:
                pass
            with self._condition:
                self._stdout_eof = True
                if self._active_turn is not None:
                    self._fail_locked('stream_ended_before_result', queue_interrupt=False)
                elif not self._initialized:
                    self._fail_locked('stream_ended_before_initialize', queue_interrupt=False)
                else:
                    self._begin_stop_locked(queue_interrupt=False)
                self._condition.notify_all()

    def drain_events(self, limit=50):
        if type(limit) is not int or not 1 <= limit <= 2048:
            raise ValueError('invalid native event read limit')
        self._observe_tree()
        with self._condition:
            self._check_locked()
            result = []
            while self._events and len(result) < limit:
                event, size = self._events.popleft()
                self._queued_bytes -= size
                result.append(event)
            return result

    def wait_event(self, timeout_seconds):
        if type(timeout_seconds) not in (int, float) or not math.isfinite(timeout_seconds) or not 0 <= timeout_seconds <= 60:
            raise ValueError('invalid native event wait')
        deadline = time.monotonic() + timeout_seconds
        while True:
            self._observe_tree()
            with self._condition:
                if self._events:
                    break
                self._check_locked()
                remaining = deadline - time.monotonic()
                if remaining <= 0 or self._error or self._stdout_eof:
                    break
                self._condition.wait(min(remaining, 0.25))
        return self.drain_events(1)

    def close_input(self):
        with self._condition:
            if self._active_turn is not None:
                self._fail_locked('input_closed_during_turn')
            else:
                self._begin_stop_locked(queue_interrupt=False)

    def stop(self, timeout_seconds=None):
        timeout = self.launch.stop_timeout_seconds if timeout_seconds is None else timeout_seconds
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 <= timeout <= self.launch.stop_timeout_seconds:
            raise ValueError('invalid native stop timeout')
        self.close_input()
        deadline = time.monotonic() + timeout
        first_observation = True
        while True:
            self._observe_tree(force=first_observation)
            first_observation = False
            with self._condition:
                remaining_processes = any(row['alive'] for row in self._tree.values())
                if (self._process is None or self._process.poll() is not None) and not remaining_processes:
                    break
                self._check_locked()
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self._error = self._error or 'cooperative_stop_timeout'
                    break
                self._condition.wait(min(remaining, 0.25))
        with self._condition:
            outlived = self._error == 'cooperative_stop_timeout' or (
                self._process is not None and self._process.poll() is None)
        if outlived:
            # The child ignored interrupt and EOF within its budget: end it.
            _terminate_owned_tree(self._tree_observer, self._process)
            with self._condition:
                if self._error in ('', 'cooperative_stop_timeout'):
                    self._error = 'forced_stop'
                if self._active_turn is not None:
                    self._last_turn = {'turn_id':self._active_turn, 'outcome':'uncertain'}
            forced_deadline = time.monotonic() + 3.0
            while self._process is not None and self._process.poll() is None and time.monotonic() < forced_deadline:
                time.sleep(0.05)
            self._observe_tree(force=True)
            deadline = max(deadline, forced_deadline)
        for thread in self._threads:
            if thread.ident is not None:
                thread.join(max(0, deadline - time.monotonic()))
        return self.status(force_observation=True)

    def _status_locked(self):
        process = self._process
        code = None if process is None else process.poll()
        alive = process is not None and code is None
        remaining = [dict(row) for row in self._tree.values() if row['alive']]
        threads_alive = sum(thread.is_alive() for thread in self._threads)
        observation_pending = self._observation_lock.locked()
        return {'runtime':self.launch.runtime, 'external_session_id':self.launch.external_session_id,
            'pid':None if process is None else process.pid, 'started':process is not None,
            'process_alive':alive, 'returncode':code, 'initialized':self._initialized,
            'closing':self._closing, 'stdin_closed':self._eof_sent, 'stdout_eof':self._stdout_eof,
            'pipe_threads_alive':threads_alive, 'remaining_processes':remaining,
            'active_turn':self._active_turn, 'last_turn':None if self._last_turn is None else dict(self._last_turn),
            'error_code':self._error, 'input_bytes':self._input_bytes, 'output_bytes':self._output_bytes,
            'queued_events':len(self._events), 'memory_bytes':self._memory_bytes,
            'memory_scope':'observed-descendants', 'tree_observed':self._tree_observed,
            'tree_observation_uncertain':self._tree_uncertain,
            'tree_observation_pending':observation_pending,
            'drained':self._tree_observed and not self._tree_uncertain and not observation_pending and not alive and not remaining and not threads_alive,
            'requires_reconciliation':bool(self._error)}

    def status(self, *, force_observation=False):
        if type(force_observation) is not bool:
            raise ValueError('native observation selector must be boolean')
        self._observe_tree(force=force_observation)
        with self._condition:
            self._check_locked()
            return self._status_locked()


__all__ = ['NativeWorkshopLaunch', 'NativeWorkshopProcess', 'ObservedNativeProcessTree']
