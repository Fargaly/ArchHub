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
import threading
import time
from pathlib import Path

TRIGGER_NODE = {'id': 'canvas.triggers', 'params': {'min_every_seconds': 10, 'file_poll_floor_seconds': 1,
                                                    'queue_cap': 25, 'workshop_to': 'Ahmed'}}


class TriggerService:
    def __init__(self, files=None):
        from .session_files import SessionFiles
        self.files = files or SessionFiles()
        self.lock = threading.Lock()
        self.timers = {}
        self.armed = []
        self.fired = []
        self.running = set()
        self.queued = {}
        self.stopped = threading.Event()

    def close(self):
        self.stopped.set()
        with self.lock:
            for timer in self.timers.values():
                timer.cancel()
            self.timers.clear()

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
        wanted = {}
        for path in self.workflows():
            try:
                document = read_document(path)
            except (OSError, ValueError) as refused:
                print('  triggers   : %s not read (%s)' % (path, refused), flush=True)
                continue
            for node in document['nodes']:
                if node['type'] in ('trigger.schedule', 'trigger.file') and not node.get('frozen'):
                    wanted[(path, node['id'])] = (node['type'], dict(node['params']), node.get('title', ''),
                                                  (node.get('result') or {}).get('fired_at'))
        missed = []
        with self.lock:
            for key in [k for k in self.timers if k not in wanted]:
                self.timers.pop(key).cancel()
            self.armed = [{'path': p, 'node': n, 'kind': kind, 'title': title, 'params': params}
                          for (p, n), (kind, params, title, _last) in wanted.items()]
            for key, (kind, params, _title, last) in wanted.items():
                if key not in self.timers:
                    self._arm(key, kind, params, state=None)
                    if kind == 'trigger.schedule' and missed_while_closed(params, last):
                        missed.append((key, kind, params))
        for key, kind, params in missed:
            threading.Thread(target=self.dispatch, args=(key, kind, params, 'catch-up'),
                             name='archhub-trigger-catchup', daemon=True).start()
        return self.armed

    def _arm(self, key, kind, params, state):
        if self.stopped.is_set():
            return
        if kind == 'trigger.schedule':
            delay = next_delay(params)
        else:
            delay = max(TRIGGER_NODE['params']['file_poll_floor_seconds'], float(params.get('debounce_seconds') or 5))
        timer = threading.Timer(delay, self._tick, args=(key, kind, params, state))
        timer.daemon = True
        self.timers[key] = timer
        timer.start()

    def _tick(self, key, kind, params, state):
        if kind == 'trigger.file':
            snapshot = folder_snapshot(params)
            changed = state is not None and snapshot != state
            state = snapshot
        else:
            changed = True
        with self.lock:
            if key in self.timers:  # the next fire stays on the clock while this run goes
                self._arm(key, kind, params, state)
        if changed:
            self.dispatch(key, kind, params)

    def dispatch(self, key, kind, params, reason='scheduled'):
        """Concurrency policy: a fire while this node's last run is going is skipped, or queued (capped)."""
        with self.lock:
            if key in self.running:
                queue = str(params.get('concurrency') or 'skip') == 'queue'
                if queue and self.queued.get(key, 0) < TRIGGER_NODE['params']['queue_cap']:
                    self.queued[key] = self.queued.get(key, 0) + 1
                    outcome = 'queued'
                else:
                    outcome = 'skipped'
                self._record(key, kind, time.time(), outcome)
                return outcome
            self.running.add(key)
        more = True
        try:
            while more:
                self.fire(key, kind, reason=reason)
                with self.lock:
                    more = bool(self.queued.get(key))
                    if more:
                        self.queued[key] -= 1
                reason = 'queued'
        finally:
            with self.lock:
                self.running.discard(key)
                self.queued.pop(key, None)
        return 'ran'

    def fire(self, key, kind, reason='scheduled'):
        """Run the trigger's downstream nodes once, save their outputs into the workflow, post it to the Workshop."""
        from . import canvas_documents as docs
        from .enforce import guard_effect
        from .session_files import run_document
        path, node_id = key
        started = time.time()
        trigger = {}

        def change(document):
            downstream = sorted(docs.downstream(document, [node_id]))
            ran = run_document(document, invoke=guard_effect, roots=downstream)
            for node in document['nodes']:
                if node['id'] in ran['results']:
                    node['result'] = {k: v for k, v in ran['results'][node['id']].items()
                                      if k in ('status', 'output', 'error', 'display')}
                if node['id'] == node_id:
                    node['result'] = {**(node.get('result') or {}), 'fired_at': started}
                    trigger.update(node)
            return []
        try:
            docs.edit(path, 'trigger:' + kind.split('.')[1], 'fired %s' % node_id, change, solve_changed=False)
            outcome = 'ran'
        except Exception as refused:  # noqa: BLE001 - a failed run is recorded, the timer stays armed
            outcome = 'failed: %s' % refused
        entry = self._record(key, kind, started, outcome)
        entry.update(self._post(key, trigger, reason, outcome, started))
        return entry

    def _post(self, key, trigger, reason, outcome, started):
        """One Workshop message per fire. Addressed to agents ('to' = handles), it is pushed live into their
        sessions through the composer's @mention path; to the founder (default) it is recorded for his screen."""
        from .workshop_live import send_as_founder
        from .workshop_mailbox import call
        path, node_id = key
        to = str((trigger.get('params') or {}).get('to') or TRIGGER_NODE['params']['workshop_to'])
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


def missed_while_closed(params, last, now=None):
    """Catch-up policy run_once: a schedule whose next fire after the last one has already passed."""
    if str(params.get('catch_up') or 'skip') != 'run_once' or type(last) not in (int, float):
        return False
    due = last + next_delay(params, datetime.datetime.fromtimestamp(last))
    return due <= (now or time.time())


def next_delay(params, now=None):
    """Seconds until a schedule fires: every N seconds, or daily at HH:MM."""
    now = now or datetime.datetime.now()
    every = params.get('every_seconds')
    if every not in (None, '', '0', 0):
        return max(TRIGGER_NODE['params']['min_every_seconds'], float(every))
    hour, minute = (int(part) for part in str(params.get('daily_at') or '08:00').split(':')[:2])
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += datetime.timedelta(days=1)
    return (target - now).total_seconds()


def folder_snapshot(params):
    folder = Path(str(params.get('folder') or ''))
    if not folder.is_dir():
        return ()
    pattern = str(params.get('pattern') or '*.*')
    return tuple(sorted((entry.name, entry.stat().st_mtime_ns) for entry in os.scandir(folder)
                        if entry.is_file() and fnmatch.fnmatch(entry.name, pattern)))

