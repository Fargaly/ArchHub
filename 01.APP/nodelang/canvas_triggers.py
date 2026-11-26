"""Trigger nodes fire while the app is open: Schedule and File change, event-driven, per workflow file.

Founder 2026-10-28: nothing lost, and no always-on graph. A workflow (.archhub) that holds a
trigger.schedule or trigger.file node gets one timer for that node while the app runs. When it
fires, the nodes downstream of the trigger run once through the existing engines (Run's
approval rules unchanged) and the outputs are saved into the same file, attributed
"trigger:<kind>", so the open window shows them. Timers are rebuilt when a workflow is saved.
Host-event triggers (trigger.host) need a host event feed; they are listed as not armed.

Routines (Paperclip routines / Open Duet, research note 2026-10-30 gap 6): each fire also posts one
Workshop message: param 'to' (agent handles) pushes it live through the composer's send_as_founder;
the default (the founder) records it for his screen. Optional node params:
'concurrency' = skip | queue (a fire while the last run is still going), 'catch_up' = skip | run_once
(a schedule missed while the app was closed runs once at start). The last fire time is kept in the
trigger node's result ('fired_at') inside the same file.
"""
from __future__ import annotations

import datetime
import fnmatch
import hashlib
import os
import re
import threading
import time
import uuid
from collections import deque
from contextlib import nullcontext
from pathlib import Path

TRIGGER_NODE = {'id': 'canvas.triggers', 'params': {'min_every_seconds': 10, 'file_poll_floor_seconds': 1,
                                                    'queue_cap': 25, 'workshop_to': 'Ahmed'}}


class TriggerService:
    def __init__(self, files=None, *, pause_settings=None, require_access=None):
        from .session_files import SessionFiles
        self.files = files or SessionFiles()
        self.pause_settings = pause_settings
        self.require_access = require_access
        self.paused = pause_settings is not None and pause_settings.read().get('automationsPaused') is True
        self.lock = threading.Lock()
        self.pause_epoch = object()
        self.pause_skips = {}
        self.file_snapshots = {}
        self.timers = {}
        self.generations = {}
        self.refresh_revision = 0
        self.startup_refresh = True
        self.armed = []
        self.fired = []
        self.running = set()
        self.queued = {}
        self.stopped = threading.Event()

    def set_paused(self, paused):
        if type(paused) is not bool or self.pause_settings is None:
            raise ValueError('Choose Pause all or Resume all in the app.')
        with self.lock:
            if paused == self.paused:
                return paused
            if paused:
                self.pause_settings.update({'automationsPaused': True})
                self.paused = True
                self.pause_epoch = object()
                self.startup_refresh = False
                return True
            epoch = self.pause_epoch
            watchers = {(row['path'], row['node']): row['params'] for row in self.armed
                        if row['kind'] == 'trigger.file'}
        # Take a fresh baseline before resuming so a change between ticks cannot start a run.
        snapshots = {}
        for key, params in watchers.items():
            try:
                snapshots[key] = folder_snapshot(params)
            except OSError:
                snapshots[key] = None
        with self.lock:
            if not self.paused or epoch is not self.pause_epoch or self.stopped.is_set():
                return self.paused
            self.pause_settings.update({'automationsPaused': False})
            for row in self.armed:
                key = (row['path'], row['node'])
                if row['kind'] != 'trigger.file' or key not in self.timers:
                    continue
                snapshot = snapshots.get(key) if watchers.get(key) == row['params'] else None
                previous = self.file_snapshots.get(key)
                if snapshot is not None and previous is not None and snapshot != previous:
                    self._skip_paused(key, row['kind'])
                self.timers[key].cancel()
                self._arm(key, row['kind'], row['params'], state=snapshot)
            self.paused = False
            skips, self.pause_skips = self.pause_skips, {}
        self._save_pause_history(skips)
        return paused

    def _skip_paused(self, key, kind):
        if self.paused:
            event = (key, kind)
            self.pause_skips[event] = self.pause_skips.get(event, 0) + 1
        return self.paused

    def _save_pause_history(self, skips):
        for (key, kind), count in skips.items():
            self._history(key, {'id': uuid.uuid4().hex, 'trigger': key[1], 'kind': kind,
                                'state': 'skipped', 'reason': 'skipped while paused: %d' % count,
                                'count': count, 'end': time.time()})

    def close(self):
        self.stopped.set()
        with self.lock:
            for timer in self.timers.values():
                timer.cancel()
            self.timers.clear()
            self.generations.clear()
            self.file_snapshots.clear()
            skips, self.pause_skips = self.pause_skips, {}
        self._save_pause_history(skips)

    def workflows(self):
        paths = []
        for row in self.files.open_files():
            path = Path(row['path'])
            if path.suffix.lower() == '.archhub' and path.exists() and str(path) not in paths:
                paths.append(str(path))
        return paths

    def refresh(self):
        """Re-arm every trigger node in the known workflows (called at start and after a save)."""
        from .session_files import read_document
        with self.lock:
            self.refresh_revision += 1
            revision = self.refresh_revision
        wanted = {}
        for path in self.workflows():
            try:
                document = read_document(path)
            except (OSError, ValueError) as refused:
                print('  triggers   : %s not read (%s)' % (path, refused), flush=True)
                continue
            for node in document['nodes']:
                # Armed is the stored switch (default on); it times only while the app is open.
                if node['type'] in ('trigger.schedule', 'trigger.file') and not node.get('frozen') and not _off(node['params'].get('armed', True)):
                    params = _effective_params(node, path)
                    wanted[(path, node['id'])] = (node['type'], params, node.get('title', ''),
                                                  (node.get('result') or {}).get('fired_at'))
        missed = []
        with self.lock:
            if revision != self.refresh_revision or self.stopped.is_set():
                return self.armed
            startup, self.startup_refresh = self.startup_refresh, False
            previous = {(row['path'], row['node']): (row['kind'], row['params']) for row in self.armed}
            for key, timer in list(self.timers.items()):
                if key not in wanted or previous.get(key) != wanted[key][:2]:
                    timer.cancel()
                    self.generations.pop(key, None)
                    self.file_snapshots.pop(key, None)
                    del self.timers[key]
            self.armed = [{'path': p, 'node': n, 'kind': kind, 'title': title, 'params': params}
                          for (p, n), (kind, params, title, _last) in wanted.items()]
            for key, (kind, params, _title, last) in wanted.items():
                if key not in self.timers:
                    self._arm(key, kind, params, state=None)
                    if startup and not self.paused and kind == 'trigger.schedule' and missed_while_closed(params, last):
                        missed.append((key, kind, params, self.timers[key], self.pause_epoch))
        for key, kind, params, timer, epoch in missed:
            threading.Thread(target=self.dispatch, args=(key, kind, params, 'catch-up'), kwargs={'timer': timer, 'epoch': epoch},
                             name='archhub-trigger-catchup', daemon=True).start()
        return self.armed

    def change_schedule(self, op, args):
        from .canvas_documents import edit
        from .library_engines import library_item_ports
        from .node_params import compatible, ports
        from .session_files import catalogue, local_path

        if not args:
            raise ValueError('Choose a schedule.')
        addition = op == 'add_schedule'
        identity = None
        if addition:
            path = self.files.current_path()
            if not path:
                raise ValueError('Open a workflow before adding a schedule.')
            if len(args) > 2 and local_path(args[2]) != local_path(path):
                raise ValueError('The open workflow changed. Reopen it before adding a schedule.')
        else:
            path, separator, identity = str(args[0]).rpartition('#')
            if not separator or path not in self.workflows() or not identity:
                raise ValueError('Choose a schedule in a known workflow.')

        value = args[1] if len(args) > 1 else None
        if op in ('add_schedule', 'set_schedule_time'):
            if not isinstance(value, str) or not re.fullmatch(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]', value):
                raise ValueError('Choose a time in HH:MM.')
        if op == 'set_schedule_enabled' and type(value) is not bool:
            raise ValueError('Choose whether the schedule is enabled.')
        item = next(row for row in catalogue() if row['id'] == 'tr_schedule') if addition else None
        result = {}

        def change(document):
            nodes = {node['id']: node for node in document['nodes']}
            if addition:
                selection = args[0]
                if selection == document['id']:
                    runnable = {key for key, node in nodes.items() if not node['type'].startswith('trigger.')}
                    upstream = {wire['from']['node'] for wire in document['wires']
                                if wire['to']['node'] in runnable and wire.get('enabled') is not False}
                    targets = sorted(runnable - upstream)
                else:
                    targets = selection if isinstance(selection, list) else [selection]
                if not targets or any(not isinstance(key, str) or key not in nodes for key in targets):
                    raise ValueError('Choose at least one runnable node on this workflow.')
                occupied = {(wire['to']['node'], wire['to']['socket']) for wire in document['wires']}
                key = str(uuid.uuid4())
                links = []
                for target in dict.fromkeys(targets):
                    node = nodes[target]
                    base = node.get('ports') or library_item_ports(node.get('item', ''), node['type'])
                    target_ports = ports(node, base)['target']
                    connection = next(((out['id'], inp['id'])
                                       for out in item['ports']['source'] for inp in target_ports
                                       if not inp['id'].startswith('param:')
                                       and compatible(out['type'], inp['type'], inp['id'])
                                       and (target, inp['id']) not in occupied), None)
                    if connection:
                        out, into = connection
                        links.append({'id': str(uuid.uuid4()), 'from': {'node': key, 'socket': out},
                                      'to': {'node': target, 'socket': into}})
                    else:
                        raise ValueError('The selected node has no free schedule input.')
                if not links:
                    raise ValueError('Choose a node with a free schedule input.')
                position = nodes[links[0]['to']['node']]['position']
                document['nodes'].append({
                    'id': key, 'type': item['engine'], 'item': item['id'], 'title': 'Daily ' + value,
                    'params': {**item['params'], 'every_seconds': None, 'daily_at': value,
                               'armed': True, 'ask_before_running': True},
                    'paramDefs': item['paramDefs'],
                    'position': {'x': position['x'] - 220, 'y': position['y']},
                })
                document['wires'].extend(links)
                result.update(id=path + '#' + key, time=value, enabled=True)
                return [key]

            node = nodes.get(identity)
            if node is None or node['type'] not in ('trigger.schedule', 'trigger.file'):
                raise ValueError('That is not a schedule node.')
            result['id'] = args[0]
            if op == 'set_schedule_time':
                if node['type'] != 'trigger.schedule':
                    raise ValueError('File change triggers do not have a daily time.')
                node['params'].update(daily_at=value, every_seconds=None)
                result['time'] = value
            elif op == 'set_schedule_enabled':
                node['params']['armed'] = value
                result['enabled'] = value
            else:
                document['nodes'].remove(node)
                document['wires'] = [wire for wire in document['wires']
                                     if identity not in (wire['from']['node'], wire['to']['node'])]
            return [identity]

        edit(path, 'Studio', op.replace('_', ' '), change, solve_changed=False)
        self.refresh()
        return result

    def _arm(self, key, kind, params, state):
        if self.stopped.is_set():
            return
        if kind == 'trigger.schedule':
            delay = next_delay(params)
        else:
            delay = max(TRIGGER_NODE['params']['file_poll_floor_seconds'], float(params.get('debounce_seconds') or 5))
            self.file_snapshots[key] = state
        timer = threading.Timer(delay, lambda: self._tick(key, kind, params, state, timer), args=())
        timer.daemon = True
        self.generations.setdefault(key, object())
        self.timers[key] = timer
        timer.start()

    def _tick(self, key, kind, params, state, timer):
        if kind == 'trigger.file':
            snapshot = folder_snapshot(params)
            changed = state is not None and snapshot != state
            state = snapshot
        else:
            changed = True
        with self.lock:
            if self.timers.get(key) is not timer or self.stopped.is_set():
                return
            self._arm(key, kind, params, state)
            next_timer = self.timers[key]
            if not changed or self._skip_paused(key, kind):
                return
            epoch = self.pause_epoch
        self.dispatch(key, kind, params, timer=next_timer, epoch=epoch)

    def dispatch(self, key, kind, params, reason='scheduled', *, timer=None, epoch=None):
        """Concurrency policy: a fire while this node's last run is going is skipped, or queued (capped).

        Ask before running (the trigger's switch, default on) keeps the fire as an "asking" run in the
        session's run history; nothing runs until approve()."""
        from .canvas_documents import locked
        from .session_files import read_document
        from .cloud_session import DesktopAccessRefused
        automatic = reason not in ('approved', 'manual')
        if self.require_access is not None:
            try:
                self.require_access()
            except DesktopAccessRefused:
                if automatic:
                    return 'desktop_access_required'
                raise
        with self.lock:
            if self.stopped.is_set():
                return 'superseded'
            if automatic and self._skip_paused(key, kind):
                return 'paused'
            if epoch is None:
                epoch = self.pause_epoch
        asking = automatic and timer is None and self._asks(key)
        with locked(key[0]) if timer is not None else nullcontext(), self.lock:
            if self.stopped.is_set() or (automatic and epoch is not self.pause_epoch):
                return 'superseded'
            if timer is not None:
                try:
                    if not _schedule_matches(read_document(key[0]), key, kind, params):
                        return 'superseded'
                except (OSError, ValueError):
                    return 'superseded'
                asking = not _off(params.get('ask_before_running', True))
            if timer is not None and (self.timers.get(key) is not timer or self.stopped.is_set()):
                return 'superseded'
            if asking:
                self._history(key, {'id': uuid.uuid4().hex, 'trigger': key[1], 'kind': kind, 'reason': reason,
                                    'state': 'asking', 'start': time.time()})
                self._record(key, kind, time.time(), 'asking')
                return 'asking'
            expected = {'epoch': epoch} if automatic else None
            if timer is not None and expected is not None:
                expected.update(params=dict(params), generation=self.generations[key])
            if key in self.running:
                queue = str(params.get('concurrency') or _default('trigConcurrency')) == 'queue'
                pending = self.queued.get(key)
                if queue and (pending is None or len(pending) < TRIGGER_NODE['params']['queue_cap']):
                    self.queued.setdefault(key, deque()).append((kind, expected,
                                                                 'queued' if automatic else reason))
                    outcome = 'queued'
                else:
                    outcome = 'skipped'
                self._record(key, kind, time.time(), outcome)
                self._history(key, {'id': uuid.uuid4().hex, 'trigger': key[1], 'kind': kind, 'reason': reason,
                                    'state': outcome, 'start': time.time(), 'end': time.time()})
                return outcome
            self.running.add(key)
        completed = False
        try:
            while True:
                self.fire(key, kind, reason=reason, **({'expected': expected} if expected is not None else {}))
                with self.lock:
                    queue = self.queued.get(key)
                    if not queue:
                        self.running.discard(key)
                        self.queued.pop(key, None)
                        completed = True
                        break
                    kind, expected, reason = queue.popleft()
        finally:
            if not completed:
                with self.lock:
                    self.running.discard(key)
                    self.queued.pop(key, None)
        return 'ran'

    def fire(self, key, kind, reason='scheduled', *, expected=None):
        """Run the trigger's downstream nodes once, save their outputs into the workflow, post it to the Workshop."""
        if expected is None and reason not in ('approved', 'manual'):
            with self.lock:
                if self.stopped.is_set():
                    return {'outcome': 'superseded'}
                if self._skip_paused(key, kind):
                    return {'outcome': 'paused'}
                expected = {'epoch': self.pause_epoch}
            if self._asks(key):
                return self.dispatch(key, kind, {}, reason, epoch=expected['epoch'])
        from . import canvas_documents as docs
        from .cloud_session import DesktopAccessRefused
        from .enforce import guard_effect
        from .session_files import TriggerWaitingForApproval, run_document, run_outcome

        try:
            admission = self.require_access() if self.require_access is not None else None
        except DesktopAccessRefused:
            return {'outcome': 'desktop_access_required'}

        def require_current_access():
            if admission is not None and self.require_access()["subject"] != admission["subject"]:
                raise DesktopAccessRefused("session_invalid")

        def invoke(*args, **kwargs):
            require_current_access()
            return guard_effect(*args, **kwargs)
        path, node_id = key
        started = time.time()
        trigger = {}
        run = {'id': uuid.uuid4().hex, 'trigger': node_id, 'kind': kind, 'reason': reason, 'state': 'running', 'start': started}
        started_node = False

        def is_superseded():
            return (self.stopped.is_set() or expected['epoch'] is not self.pause_epoch
                    or ('generation' in expected and self.generations.get(key) is not expected['generation']))

        def admit_trigger():
            with self.lock:
                if expected is not None and is_superseded():
                    raise _Superseded()

        def stopped():
            nonlocal started_node
            with self.lock:
                superseded = is_superseded()
                if superseded and not started_node:
                    raise _Superseded()
                started_node = True
                return superseded

        def change(document):
            if expected is not None and 'params' in expected:
                if not _schedule_matches(document, key, kind, expected['params']):
                    raise _Superseded()
            downstream = sorted(docs.downstream(document, [node_id]))
            ran = run_document(document, invoke=invoke if admission is not None else guard_effect,
                               roots=downstream, path=path, again=True,
                               stopped=stopped if expected is not None else None, trigger_admission=admit_trigger)
            run['id'] = ran['run']['id']
            run.update(run_outcome(ran))
            for node in document['nodes']:
                if node['id'] in ran['results']:
                    node['result'] = {k: v for k, v in ran['results'][node['id']].items()
                                      if k in ('status', 'output', 'error', 'display')}
                if node['id'] == node_id:
                    node['result'] = {**(node.get('result') or {}), 'fired_at': started}
                    trigger.update(node)
            # Commit the trigger identity before an approval can resume the same run.
            self._history(key, {**run, 'end': time.time()})
            return []
        try:
            docs.edit(path, 'trigger:' + kind.split('.')[1], 'fired %s' % node_id, change, solve_changed=False)
            outcome = 'ran'
        except _Superseded:
            return {'outcome': 'superseded'}
        except TriggerWaitingForApproval as held:
            self._history(key, {**run, 'state': 'skipped', 'reason': str(held), 'end': time.time()})
            return {'outcome': 'skipped', 'reason': str(held)}
        except Exception as refused:  # noqa: BLE001 - a failed run is recorded, the timer stays armed
            outcome = 'failed: %s' % refused
            run.update(state='failed', failedNode='', error=str(refused)[:500])
            self._history(key, {**run, 'end': time.time()})
        entry = self._record(key, kind, started, outcome)
        try:
            require_current_access()
        except DesktopAccessRefused as refused:
            entry['workshop_error'] = str(refused)
            return entry
        entry.update(self._post(key, trigger, reason, outcome, started))
        return entry

    def _post(self, key, trigger, reason, outcome, started):
        """One Workshop message per fire. Addressed to agents ('to' = handles), it is pushed live into their
        sessions through the composer's @mention path; to the founder (default) it is recorded for his screen."""
        from .workshop_live import send_as_founder
        from .workshop_mailbox import call
        path, node_id = key
        from .settings_owner import agent_setting  # Settings › Agents › Automation messages go to
        to = str((trigger.get('params') or {}).get('to') or {'Coordinator': 'coordinator', 'BABOOM': 'baboom'}.get(
            agent_setting('autoTo'), TRIGGER_NODE['params']['workshop_to']))
        text = 'Routine %s (%s) fired, %s: %s' % (trigger.get('title') or node_id, Path(path).stem, reason, outcome)
        handles = [part.strip().lstrip('@').casefold() for part in to.split(',') if part.strip()]
        pushed = None
        if not set(handles) <= {'ahmed', 'founder', 'you'}:
            try:
                sent = send_as_founder(text, handles)
                return {'workshop': sent['message_id'], 'deliveries': sent['deliveries']}
            except Exception as refused:  # noqa: BLE001 - no live agent: still recorded below, with the reason
                pushed = str(refused)[:200]
        retry = hashlib.sha256(('%s#%s@%r' % (path, node_id, started)).encode('utf-8')).hexdigest()
        try:
            sent = call('send', {'to': to, 'text': text, 'idempotency_key': 'routine:' + retry}, {})
            return {'workshop': sent['message_id'], **({'push_error': pushed} if pushed else {})}
        except Exception as refused:  # noqa: BLE001 - the run already happened; the post failure is recorded
            return {'workshop_error': str(refused)[:200]}

    def _record(self, key, kind, at, outcome):
        entry = {'path': key[0], 'node': key[1], 'kind': kind, 'at': at, 'outcome': outcome}
        self.fired.append(entry)
        del self.fired[:-50]
        return entry

    # --------------------------------------------- session model (ONE BUILD 1) --
    def _asks(self, key):
        """The trigger's stored Ask before running switch, read from the file now (default on)."""
        from .session_files import read_document
        try:
            node = next(n for n in read_document(key[0])['nodes'] if n['id'] == key[1])
        except (OSError, ValueError, StopIteration):
            return False  # nothing readable to ask about: the fire fails and is recorded as failed
        return not _off(node['params'].get('ask_before_running', True))

    def _history(self, key, entry):
        """Persist one run line beside the session; a history write failure never stops the timer."""
        from .session_files import append_run
        try:
            append_run(key[0], entry)
        except (OSError, ValueError) as refused:
            print('  triggers   : run history for %s not written (%s)' % (key[0], refused), flush=True)

    def approve(self, path, run_id):
        """Claim the asking run before dispatch so repeated approvals cannot run it twice."""
        from .session_files import claim_run_approval
        if self.require_access is not None:
            self.require_access()
        node = claim_run_approval(path, run_id)
        return self.dispatch((str(path), node['id']), node['type'], dict(node['params']), reason='approved')


class _Superseded(Exception):
    pass


def _effective_params(node, path):
    from .session_files import file_parameters, resolve_file_parameter
    result = dict(node['params'])
    for name in file_parameters(node):
        if name in result:
            result[name] = resolve_file_parameter(result[name], path)
    return result


def _schedule_matches(document, key, kind, params):
    node = next((row for row in document['nodes'] if row['id'] == key[1]), None)
    return bool(node and node['type'] == kind and not node.get('frozen')
                and not _off(node['params'].get('armed', True))
                and _effective_params(node, key[0]) == params)


def _off(value):
    from .session_files import _off as switched_off
    return switched_off(value)


def _default(key):
    """Settings › Agents › Automations: the policy a trigger node follows when it sets none ('skip' / 'queue' / 'run_once')."""
    from .settings_owner import agent_setting
    return agent_setting(key).lower().replace(' ', '_')


def missed_while_closed(params, last, now=None):
    """Catch-up policy run_once: a schedule whose next fire after the last one has already passed."""
    if str(params.get('catch_up') or _default('trigCatchUp')) != 'run_once' or type(last) not in (int, float):
        return False
    from .settings_owner import settings_zone
    due = last + next_delay(params, datetime.datetime.fromtimestamp(last, settings_zone()))
    return due <= (now or time.time())


def next_delay(params, now=None):
    """Seconds until a schedule fires: every N seconds, or daily at HH:MM in Settings › Account › Time zone."""
    if now is None:
        from .settings_owner import settings_zone
        now = datetime.datetime.now(settings_zone())
    every = params.get('every_seconds')
    if every not in (None, '', '0', 0):
        return max(TRIGGER_NODE['params']['min_every_seconds'], float(every))
    hour, minute = (int(part) for part in str(params.get('daily_at') or '08:00').split(':')[:2])
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += datetime.timedelta(days=1)
    return target.timestamp() - now.timestamp()  # real seconds, also across a daylight-saving change


def folder_snapshot(params):
    folder = Path(str(params.get('folder') or ''))
    if not folder.is_dir():
        return ()
    pattern = str(params.get('pattern') or '*.*')
    return tuple(sorted((entry.name, entry.stat().st_mtime_ns) for entry in os.scandir(folder)
                        if entry.is_file() and fnmatch.fnmatch(entry.name, pattern)))

