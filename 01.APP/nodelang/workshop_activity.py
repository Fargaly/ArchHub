"""Read-only runtime evidence for existing Work rows; no transcript or status writes.

Incremental tail/discovery and event mapping adapted from AgentTrail (MIT),
Copyright (c) 2026 Kelly Sun. Full permission notice is retained in NOTICE.
"""
from datetime import datetime
from builtins import OverflowError
import fnmatch
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import threading
import time


_PRIVATE = frozenset(('20.clients', '60.personal'))
_SKIP = _PRIVATE | frozenset(('.git', '.venv', 'node_modules', '__pycache__', 'dist', 'build'))
_IDENTITY = re.compile(r'[A-Za-z0-9_-]{1,128}')
_TOOL = re.compile(r'[A-Za-z_][A-Za-z0-9_.:-]{0,79}')
_INIT_LOCK = threading.Lock()
_LIMIT = 2 * 1024 * 1024


def ownership(value):
    """Only bounded relative globs and ledger timestamps cross the row boundary."""
    if type(value) is not dict or set(value) - {'owns', 'installed_at', 'updated_at', 'installed_revision'}:
        raise ValueError('Activity requires owned relative paths and ledger timestamps')
    globs = value.get('owns', [])
    if type(globs) is not list or len(globs) > 128:
        raise ValueError('Activity ownership exceeds 128 globs')
    clean = []
    for pattern in globs:
        if (type(pattern) is not str or not pattern or len(pattern) > 512
                or any(ord(char) < 32 for char in pattern) or ':' in pattern):
            raise ValueError('Activity ownership requires relative file globs')
        pattern = pattern.replace('\\', '/')
        parts = pattern.casefold().split('/')
        if pattern.startswith('/') or any(part in ('', '.', '..') or part in _SKIP for part in parts):
            raise ValueError('Activity ownership is outside the observable workspace')
        clean.append(pattern)
    result = {'owns': sorted(set(clean))}
    for name in ('installed_at', 'updated_at'):
        stamp = value.get(name)
        if stamp is not None and (type(stamp) not in (int, float) or not math.isfinite(stamp) or stamp < 0):
            raise ValueError('Activity ledger timestamps must be finite Unix seconds')
        result[name] = stamp
    revision = value.get('installed_revision')
    if revision is not None and (type(revision) is not str or not re.fullmatch(r'[0-9a-f]{7,40}', revision)):
        raise ValueError('Activity install revision must be an exact Git revision')
    result['installed_revision'] = revision
    return result


def observer_for(owner):
    """One disposable reader on the existing application owner, never a daemon."""
    root = getattr(owner, 'universal_workspace_root', None)
    if root is None:
        return None
    resolved = Path(root).resolve()
    if any(part.casefold() in _PRIVATE for part in (*Path(root).parts, *resolved.parts)):
        return None
    with _INIT_LOCK:
        reader = getattr(owner, '_workshop_activity', None)
        if reader is None:
            reader = WorkshopActivity(root)
            owner._workshop_activity = reader
        return reader


class WorkshopActivity:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.homes = ((Path(os.environ.get('CODEX_HOME', Path.home() / '.codex')) / 'sessions', 'codex'),
                      (Path(os.environ.get('CLAUDE_CONFIG_DIR', Path.home() / '.claude')) / 'projects', 'claude'))
        self.streams = {}
        self.sessions = {}
        self.recent = []
        self.rows = {}
        self.last_discovery = -math.inf
        self.partial = False
        self.unavailable = False
        self.lock = threading.RLock()
        self.opencodes = {}
        self.opencode_worker = None
        self.ledger_stamp = None
        self.ledger = {}
        self.deadline = math.inf

    def relative(self, value, cwd=''):
        if type(value) is not str or not value or len(value) > 4096 or any(ord(char) < 32 for char in value):
            return None
        raw = Path(value.replace('\\', '/'))
        try:
            path = (raw if raw.is_absolute() else self.root / cwd / raw).resolve()
            # Test the resolved target AND spelling: a junction cannot bypass privacy.
            if any(part.casefold() in _SKIP for part in (*path.parts, *raw.parts)):
                return None
            if not path.is_relative_to(self.root):
                return None
            relative = path.relative_to(self.root).as_posix()
            return '' if relative == '.' else relative
        except (OSError, ValueError, RuntimeError):
            self.unavailable = True
            return None

    def _metadata(self, file, provider):
        try:
            with file.open('rb') as stream:
                head = stream.read(65536)
            consumed = 0
            for line in head.split(b'\n')[:-1]:
                consumed += len(line) + 1
                try:
                    row = json.loads(line)
                except (ValueError, UnicodeError):
                    continue
                if type(row) is not dict:
                    continue
                meta = row.get('payload') if provider == 'codex' and row.get('type') == 'session_meta' else row if provider == 'claude' else None
                if type(meta) is not dict:
                    continue
                session = meta.get('id') if provider == 'codex' else meta.get('sessionId')
                cwd = self.relative(meta.get('cwd'))
                if type(session) is str and _IDENTITY.fullmatch(session) and cwd is not None:
                    return {'provider':provider, 'session':session, 'cwd':cwd, 'offset':0, 'identity':None,
                            'header_size':consumed, 'header':hashlib.sha256(head[:consumed]).digest()}
        except OSError:
            self.unavailable = True
        return None

    def _discover(self, now):
        candidates = []
        count = 0
        for home, provider in self.homes:
            for directory, dirs, files in os.walk(home, followlinks=False):
                count += 1
                if count > 12000:
                    self.partial = True
                    break
                dirs[:] = sorted(name for name in dirs if name.casefold() not in _SKIP
                    and not (Path(directory) / name).is_symlink() and not (Path(directory) / name).is_junction())
                for name in files:
                    if not name.endswith('.jsonl'):
                        continue
                    count += 1
                    if count > 12000:
                        self.partial = True
                        break
                    file = Path(directory) / name
                    try:
                        stat = file.stat(follow_symlinks=False)
                        if not file.is_symlink() and now - stat.st_mtime < 86400:
                            candidates.append((stat.st_mtime, file, provider))
                    except OSError:
                        self.unavailable = True
                if count > 12000:
                    break
        found = {}
        for _stamp, file, provider in sorted(candidates, reverse=True)[:240]:
            state = self.streams.get(file) or self._metadata(file, provider)
            if state is not None:
                found[file] = state
            if len(found) == 120:
                break
        self.partial |= len(candidates) > 240
        self.streams = found
        self.last_discovery = now

    def _accept(self, state, row, now):
        if type(row) is not dict or row.get('isSidechain'):
            return
        try:
            at = datetime.fromisoformat(row['timestamp'].replace('Z', '+00:00')).timestamp()
        except (KeyError, ValueError, TypeError, AttributeError, OverflowError, OSError):
            return
        if not math.isfinite(at) or at > now + 5 or now - at > 86400:
            return
        provider, session = state['provider'], state['session']
        if provider == 'claude' and row.get('sessionId') != session:
            return
        if provider == 'claude':
            cwd = self.relative(row.get('cwd'))
            if cwd is None or cwd != state['cwd']:
                self.accept(provider, session, 'turn-start', '', None, None, at)
                return
        payload = row.get('payload', {})
        if type(payload) is not dict:
            return
        if provider == 'codex' and row.get('type') == 'turn_context':
            state['cwd'] = self.relative(payload.get('cwd'))
            if state['cwd'] is None:
                self.accept(provider, session, 'turn-start', '', None, None, at)
            return
        if state['cwd'] is None:
            return
        events = []
        if provider == 'codex':
            kind = payload.get('type')
            if row.get('type') == 'event_msg' and kind in ('task_started','task_complete','turn_aborted'):
                events.append(('turn-start' if kind == 'task_started' else 'turn-end', '', None, None))
            if row.get('type') == 'response_item' and kind in ('function_call','custom_tool_call'):
                try:
                    args = json.loads(payload.get('arguments', '{}'))
                except (ValueError, TypeError):
                    args = {}
                args = args if type(args) is dict else {}
                paths = [args.get('file_path') or args.get('path')]
                patch = payload.get('input') or args.get('patch') or args.get('input')
                if str(payload.get('name', '')).endswith('apply_patch') and type(patch) is str:
                    paths += re.findall(r'^\*\*\* (?:Update|Add|Delete) File: (.+)$', patch, re.M)[:32]
                for file in paths:
                    events.append(('tool-start', payload.get('name'), file, payload.get('call_id')))
            if row.get('type') == 'response_item' and kind in ('function_call_output','custom_tool_call_output'):
                events.append(('tool-end', '', None, payload.get('call_id')))
        else:
            message = row.get('message')
            message = message if type(message) is dict else {}
            content = message.get('content')
            for part in content[:256] if type(content) is list else []:
                if type(part) is not dict:
                    continue
                if part.get('type') == 'tool_use':
                    args = part.get('input')
                    args = args if type(args) is dict else {}
                    events.append(('tool-start', part.get('name'), args.get('file_path') or args.get('path'), part.get('id')))
                if part.get('type') == 'tool_result':
                    events.append(('tool-end', '', None, part.get('tool_use_id')))
            if (message.get('stop_reason') == 'end_turn' or row.get('type') == 'system' and row.get('subtype') == 'turn_duration'):
                events.append(('turn-end', '', None, None))
            if row.get('type') == 'user' and type(content) is str:
                events.append(('turn-start', '', None, None))
        for kind, tool, file, call in events:
            self.accept(provider, session, kind, tool, (self.relative(file, state['cwd']) or None) if file else None, call, at)

    def accept(self, provider, session, kind, tool, file, call, at):
        key = (provider, session)
        current = self.sessions.get(key)
        if current and at < current['at']:
            return
        if current is None and kind in ('turn-start', 'turn-end'):
            current = {'provider':provider, 'session':session, 'tool':'', 'file':None,
                'state':'turn_ended' if kind == 'turn-end' else 'unassociated',
                'at':at, 'call':None, 'associated':False}
            self.sessions[key] = current
        if kind == 'tool-start':
            if type(tool) is not str or not _TOOL.fullmatch(tool):
                return
            if file is None:
                if current:
                    current.update(tool=tool, state='unassociated', at=at, call=None, associated=False)
                else:
                    self.sessions[key] = {'provider':provider, 'session':session, 'tool':tool, 'file':None,
                        'state':'unassociated', 'at':at, 'call':None, 'associated':False}
                return
            current = {'provider':provider, 'session':session, 'tool':tool, 'file':file,
                       'state':'working', 'at':at, 'associated':True,
                       'call':call if type(call) is str and _IDENTITY.fullmatch(call) else None}
            self.sessions[key] = current
        elif current and at >= current['at']:
            if kind == 'turn-end':
                current.update(state='turn_ended', at=at)
            elif kind == 'turn-start':
                current.update(state='unassociated', at=at, call=None, associated=False)
            elif kind == 'tool-end' and call == current['call']:
                current.update(state='tool_ended', at=at)
        if current and current.get('associated') and kind in ('tool-start', 'turn-end'):
            self.recent.append({'provider':provider, 'session':session, 'kind':kind, 'file':current['file'], 'at':at})
            del self.recent[:-512]
        if len(self.sessions) > 240:
            self.sessions.pop(min(self.sessions, key=lambda item: self.sessions[item]['at']))

    def poll(self):
        with self.lock:
            now = time.time()
            self.deadline = time.monotonic() + 3
            self.partial = self.unavailable = False
            if now - self.last_discovery >= 5:
                self._discover(now)
            budget = 8 * 1024 * 1024
            for file, state in self.streams.items():
                try:
                    stat = file.stat()
                    identity = (stat.st_dev, stat.st_ino)
                    with file.open('rb') as stream:
                        header = hashlib.sha256(stream.read(state['header_size'])).digest()
                    if state['identity'] != identity or stat.st_size < state['offset'] or header != state['header']:
                        fresh = self._metadata(file, state['provider'])
                        if fresh is None:
                            self.sessions.pop((state['provider'], state['session']), None)
                            continue
                        self.sessions.pop((state['provider'], state['session']), None)
                        state.update(fresh, identity=identity)
                    if stat.st_size == state['offset']:
                        continue
                    if budget <= 0:
                        self.partial = True
                        break
                    start = max(state['offset'], stat.st_size - min(_LIMIT, budget))
                    with file.open('rb') as stream:
                        stream.seek(start)
                        raw = stream.read(min(_LIMIT, budget))
                    budget -= len(raw)
                    end = raw.rfind(b'\n')
                    if end < 0:
                        self.partial = True
                        continue
                    # Keep offsets, never raw partial lines containing prompt/reasoning.
                    begin = raw.find(b'\n') + 1 if start > state['offset'] else 0
                    self.partial |= start > state['offset']
                    for line in raw[begin:end].split(b'\n'):
                        try:
                            row = json.loads(line)
                        except (ValueError, UnicodeError):
                            continue
                        self._accept(state, row, now)
                    state['offset'] = start + end + 1
                except OSError:
                    self.unavailable = True

    def read_opencode(self, transport, sessions):
        """Use Workshop's bounded reader, then revalidate at this privacy boundary."""
        if transport is None or not hasattr(transport, 'activity'):
            return
        selected = sorted(set(sessions), key=lambda session: self.opencodes.get(session, -math.inf))
        if len(selected) > 4:
            self.partial = True
        for session in selected[:4]:
            if type(session) is not str:
                continue
            with self.lock:
                now = time.time()
                if not _IDENTITY.fullmatch(session) or now - self.opencodes.get(session, -math.inf) < 5:
                    continue
                self.opencodes[session] = now
            try:
                result = transport.activity(session, self.root)
            except (OSError, RuntimeError, ValueError):
                result = None
            with self.lock:
                if type(result) is not dict or result.get('status') != 'ok' or type(result.get('events')) is not list:
                    self.unavailable = True
                    continue
                for row in result['events'][:128]:
                    if (type(row) is not dict or row.get('session') != session or row.get('provider') != 'opencode'
                            or type(row.get('at')) not in (int, float) or not math.isfinite(row['at'])
                            or not 0 <= now - row['at'] < 86400):
                        continue
                    file = self.relative(row.get('file'))
                    if file is None:
                        continue
                    self.accept('opencode', session, 'tool-start', row.get('tool'), file, None, row['at'])
                    current = self.sessions.get(('opencode', session))
                    if current and row.get('state') in ('working', 'tool_ended', 'turn_ended'):
                        current['state'] = row['state']

    def poll_opencode(self, transport, sessions):
        """Observe on an owned channel so polling cannot hold native delivery's lock."""
        if transport is None or not sessions:
            return
        def observe():
            try:
                with transport.create_channel() as channel:
                    self.read_opencode(channel, sessions)
            except (OSError, RuntimeError, ValueError):
                with self.lock:
                    self.unavailable = True
        with self.lock:
            if len(set(sessions)) > 4:
                self.partial = True
            if self.opencode_worker is not None and self.opencode_worker.is_alive():
                return
            self.opencode_worker = threading.Thread(target=observe,
                name='Workshop OpenCode observation', daemon=True)
            self.opencode_worker.start()

    def _files(self, patterns):
        found = {}
        starts = set()
        for pattern in patterns:
            if not any(char in pattern for char in '*?['):
                path = self.root / pattern
                relative = self.relative(str(path))
                try:
                    if relative and path.is_file():
                        found[relative] = path.stat().st_mtime
                except OSError:
                    self.unavailable = True
                continue
            prefix = re.split(r'[*?\[]', pattern, maxsplit=1)[0]
            candidate = self.root / prefix
            start = candidate if not prefix or prefix.endswith('/') else candidate.parent
            if self.relative(str(start)) is None:
                self.unavailable = True
                continue
            starts.add(start)
        count = 0
        for start in starts:
            for directory, dirs, files in os.walk(start, followlinks=False):
                dirs[:] = [name for name in dirs if name.casefold() not in _SKIP
                    and not (Path(directory) / name).is_symlink() and not (Path(directory) / name).is_junction()]
                for name in files:
                    count += 1
                    if count > 20000 or time.monotonic() >= self.deadline:
                        self.partial = True
                        return found
                    path = Path(directory) / name
                    relative = self.relative(str(path))
                    if relative and any(fnmatch.fnmatchcase(relative.casefold(), pattern.casefold()) for pattern in patterns):
                        try:
                            found[relative] = path.stat().st_mtime
                        except OSError:
                            self.unavailable = True
        return found

    def ledger_config(self, key, config):
        """Read the existing delivery ledger's current cell, never its quoted history."""
        if type(key) is not str or not re.fullmatch(r'F\d{1,4}', key):
            return config
        ledger = self.root / '70.COMPANY/72.HANDOFFS/72.03-ARCHHUB-INTEGRATED-REPAIR/DELIVERY-STATUS.md'
        try:
            if self.relative(str(ledger)) is None:
                return config
            stat = ledger.stat()
            stamp = (stat.st_mtime_ns, stat.st_size)
            if stamp != self.ledger_stamp:
                if stat.st_size > _LIMIT:
                    self.partial = True
                    return config
                rows = {}
                for line in ledger.read_text(encoding='utf-8').splitlines():
                    cells = line.split('|')
                    if len(cells) < 7 or not re.fullmatch(r'F\d{1,4}', cells[1].strip()):
                        continue
                    # The current status is the last cell. "Was: INSTALLED" and
                    # "PARTLY INSTALLED" are explicitly not installed evidence.
                    match = re.match(r'INSTALLED\s+\d{8}-\d{4}-([0-9a-f]{7,40})(?:\b|\s)', cells[-2].strip())
                    rows[cells[1].strip()] = match[1] if match else None
                self.ledger, self.ledger_stamp = rows, stamp
            if key in self.ledger:
                return {**config, 'installed_at':None, 'installed_revision':self.ledger[key],
                        'updated_at':stat.st_mtime}
        except (OSError, UnicodeError):
            self.unavailable = True
        return config

    def _changed_since_revision(self, revision, patterns):
        product = self.root / '10.PRODUCT/11.ARCHHUB-APP'
        repo = product if (product / '.git').exists() else self.root
        if self.relative(str(repo)) is None or not (repo / '.git').exists():
            self.unavailable = True
            return False
        prefix = repo.relative_to(self.root).as_posix()
        prefix = '' if prefix == '.' else prefix + '/'
        paths = [pattern[len(prefix):] for pattern in patterns if pattern.startswith(prefix)]
        if not paths:
            self.unavailable = True
            return False
        paths += [':(exclude,icase)**/' + name + '/**' for name in _PRIVATE]
        paths += [':(exclude,icase)' + name + '/**' for name in _PRIVATE]
        flags = subprocess.CREATE_NO_WINDOW | subprocess.BELOW_NORMAL_PRIORITY_CLASS if os.name == 'nt' else 0
        try:
            budget = min(1.0, self.deadline - time.monotonic())
            if budget <= 0:
                self.partial = True
                return False
            changed = subprocess.run(['git', '-C', str(repo), 'diff', '--quiet', revision, '--', *paths],
                capture_output=True, timeout=budget, creationflags=flags)
            if changed.returncode not in (0, 1):
                self.unavailable = True
                return False
            untracked = subprocess.run(['git', '-C', str(repo), 'ls-files', '--others', '--exclude-standard', '--', *paths],
                capture_output=True, timeout=max(.01, min(1.0, self.deadline - time.monotonic())), creationflags=flags)
            if untracked.returncode:
                self.unavailable = True
            return changed.returncode == 1 or bool(untracked.stdout)
        except (OSError, subprocess.SubprocessError):
            self.unavailable = True
            return False

    def project(self, task, config, *, emit=None, declared_sessions=(), conflicting_sessions=()):
        config = ownership(config)
        with self.lock:
            patterns = config['owns']
            files = self._files(patterns)
            signature = (tuple(patterns), config['installed_at'], config['installed_revision'])
            prior = self.rows.get(task)
            if prior is None or prior['signature'] != signature:
                prior = {'signature':signature, 'files':set(), 'touched':False, 'handoffs':set(), 'checked':None}
                self.rows[task] = prior
            installed = config['installed_at']
            if installed is not None:
                prior['touched'] |= any(stamp > installed for stamp in files.values()) or (
                    not self.partial and not self.unavailable and bool(prior['files'] - files.keys()))
            fingerprint = tuple(sorted(files.items()))
            if config['installed_revision'] is not None and prior['checked'] != fingerprint:
                prior['touched'] |= self._changed_since_revision(config['installed_revision'], patterns)
                if not self.partial and not self.unavailable:
                    prior['checked'] = fingerprint
            prior['files'] = set(files) if not self.partial and not self.unavailable else prior['files'] | files.keys()
            sessions = [{key:value for key, value in row.items() if key != 'call'}
                for row in self.sessions.values() if time.time() - row['at'] < 900
                and (row['file'] is not None and any(fnmatch.fnmatchcase(row['file'].casefold(), pattern.casefold()) for pattern in patterns)
                     or row['file'] is None and (row['provider'], row['session']) in declared_sessions)]
            for row in sessions:
                if (row['provider'], row['session']) in conflicting_sessions:
                    row.update(state='unassociated', associated=False, association_conflict=True)
            events = [row for row in self.recent if time.time() - row['at'] < 900
                and (row['provider'], row['session']) not in conflicting_sessions
                and any(fnmatch.fnmatchcase(row['file'].casefold(), pattern.casefold()) for pattern in patterns)]
            for row in events:
                if row['kind'] == 'tool-start':
                    ended = [other for other in events if other['kind'] == 'turn-end'
                        and other['provider'] != row['provider'] and 0 < row['at'] - other['at'] <= 600]
                    for other in ended:
                        identity = hashlib.sha256(json.dumps([task, other['provider'], other['session'], other['at'],
                            row['provider'], row['session']]).encode()).hexdigest()
                        if emit is not None and identity not in prior['handoffs']:
                            emit(identity, other['provider'] + ' → ' + row['provider'] + ' on ' + task)
                            prior['handoffs'].add(identity)
            updated = config['updated_at']
            return {'sessions':sessions, 'ownership':'known' if patterns else 'unknown',
                'touched_after_install':prior['touched'],
                'installed_revision':config['installed_revision'],
                'stale':updated is not None and any(stamp > updated + 1200 and time.time() - stamp < 86400 for stamp in files.values()),
                'limited':self.partial, 'unavailable':self.unavailable}
