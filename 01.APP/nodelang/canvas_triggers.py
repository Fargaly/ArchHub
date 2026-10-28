"""Trigger nodes fire while the app is open: Schedule and File change, event-driven, per workflow file.

Founder 2026-10-28: nothing lost, and no always-on graph. A workflow (.archhub) that holds a
trigger.schedule or trigger.file node gets one timer for that node while the app runs. When it
fires, the nodes downstream of the trigger run once through the existing engines (Run's
approval rules unchanged) and the outputs are saved into the same file, attributed
"trigger:<kind>", so the open window shows them. Timers are rebuilt when a workflow is saved.
Host-event triggers (trigger.host) need a host event feed; they are listed as not armed.
"""
from __future__ import annotations

import datetime
import fnmatch
import os
import threading
import time
from pathlib import Path

TRIGGER_NODE = {'id': 'canvas.triggers', 'params': {'min_every_seconds': 10, 'file_poll_floor_seconds': 1}}


class TriggerService:
    def __init__(self, files=None):
        from .session_files import SessionFiles
        self.files = files or SessionFiles()
        self.lock = threading.Lock()
        self.timers = {}
        self.armed = []
        self.fired = []
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
                    wanted[(path, node['id'])] = (node['type'], dict(node['params']), node.get('title', ''))
        with self.lock:
            for key in [k for k in self.timers if k not in wanted]:
                self.timers.pop(key).cancel()
            self.armed = [{'path': p, 'node': n, 'kind': kind, 'title': title, 'params': params}
                          for (p, n), (kind, params, title) in wanted.items()]
            for key, (kind, params, _title) in wanted.items():
                if key not in self.timers:
                    self._arm(key, kind, params, state=None)
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
        if changed:
            self.fire(key, kind)
        with self.lock:
            if key in self.timers:
                self._arm(key, kind, params, state)

    def fire(self, key, kind):
        """Run the trigger's downstream nodes once and save their outputs into the workflow."""
        from . import canvas_documents as docs
        from .enforce import guard_effect
        from .session_files import run_document
        path, node_id = key
        started = time.time()

        def change(document):
            downstream = sorted(docs.downstream(document, [node_id]))
            ran = run_document(document, invoke=guard_effect, roots=downstream)
            for node in document['nodes']:
                if node['id'] in ran['results']:
                    node['result'] = {k: v for k, v in ran['results'][node['id']].items()
                                      if k in ('status', 'output', 'error', 'display')}
            return []
        try:
            docs.edit(path, 'trigger:' + kind.split('.')[1], 'fired %s' % node_id, change, solve_changed=False)
            outcome = 'ran'
        except Exception as refused:  # noqa: BLE001 - a failed run is recorded, the timer stays armed
            outcome = 'failed: %s' % refused
        self.fired.append({'path': path, 'node': node_id, 'kind': kind, 'at': started, 'outcome': outcome})
        del self.fired[:-50]


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

