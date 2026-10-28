"""Parametric .archhub documents: solve on edit, app things as nodes, attributed edits.

Founder 2026-10-28: the canvas is the workspace where agents work; the whole app
is parametric (Grasshopper); everything in the app can be dropped in as a node
with sockets, parameters and wires -- inside one .archhub file, never a global graph.

* solve(): an edit marks downstream nodes stale. Pure nodes re-solve at once;
  effect nodes become "Out of date" and run only on Run. Solve ends when done.
* THINGS: agents, models, connectors, workspaces, skills, settings, files and the
  Workshop as Library nodes. Setting-like parameters write through to the same
  owner file the Settings screen uses (router.json): one source, no copy.
* edit(): the one read-modify-write for a file, shared by the app and every
  agent's MCP tools: cross-process lock, attributed history, atomic replace.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import threading
import time
from contextlib import contextmanager
from pathlib import Path

# The .archhub document owner node: its typed parameters.
DOCUMENT_NODE = {'id': 'canvas.document', 'params': {'history_limit': 200, 'lock_poll_seconds': 0.02}}
_READ = re.compile(r'\.(read|info|list|search|inbox|get|query|ping|status|preview|probe)(_|$)')


# --------------------------------------------------------------- purity --
def is_pure(engine):
    """Pure nodes solve on edit; anything that writes waits for Run."""
    from .library_engines import STEM_RUN_ENGINES
    from .pipeline_engines import PIPELINE_ENGINES
    if engine in STEM_RUN_ENGINES or engine in ('note', 'data.convert', 'param.value', 'data.dataset', 'data.field'):
        return True
    if engine in THING_ENGINES:
        return THING_ENGINES[engine]['pure']
    effect = PIPELINE_ENGINES.get(engine)
    return bool(effect is not None and not getattr(effect, 'enforce_pending', False) and _READ.search(engine))


# ------------------------------------------------------- app things as nodes --
def _port(name, kind='any'):
    return {'id': name, 'type': kind}


def _router():
    from .settings_owner import read_router_settings
    return read_router_settings()


def _set_router(changes):
    from .settings_owner import SettingsOwner
    return SettingsOwner(None, dependencies=object()).setRouterSettings(changes)


def _run_model(params, feeds):
    from .model_router import composer_chat
    prompt = str(feeds.get('prompt') or params.get('prompt') or '').strip()
    if not prompt:
        raise ValueError('Wire a prompt or set the prompt parameter.')
    result = composer_chat({'prompt': prompt, 'agent': 'BABOOM', 'model': str(params.get('route') or _router()['default_model'])})
    return {'text': result['answer'], 'model': result['model']}, result['model']


def _run_agent(params, feeds):
    from .workshop_mailbox import call
    task = str(feeds.get('task') or params.get('instructions') or '').strip()
    if not task:
        raise ValueError('Wire a task or write instructions.')
    files = feeds.get('files')
    text = task + ('\nFiles: ' + json.dumps(files) if files else '')
    sent = call('send', {'to': str(params['agent']), 'text': text}, {})
    return {'result': {'message_id': sent['message_id'], 'to': params['agent']}, 'messages': [sent['message_id']]}, 'Sent to ' + str(params['agent'])


def _run_host(params, feeds):
    host = str(params['host'])
    if host in ('revit', 'acad'):
        from .host_brokers import broker_sessions
        sessions = broker_sessions(host)
        if params.get('document'):
            sessions = [s for s in sessions if params['document'].lower() in json.dumps(s).lower()]
        return {'sessions': sessions, 'elements': []}, '%d session(s)' % len(sessions)
    from .pipeline_engines import probe_connectors
    row = next((r for r in probe_connectors() if r.get('id') == host), {'state': 'absent'})
    return {'sessions': [row], 'elements': []}, str(row.get('state'))


def _run_workspace(params, feeds):
    root = Path(str(params['path']))
    if not root.is_dir():
        raise ValueError('Workspace folder is not available: ' + str(root))
    files = sorted(str(p) for p in root.iterdir())[:200]
    return {'path': str(root), 'files': files}, '%d entries' % len(files)


def _run_file(params, feeds):
    path = Path(str(params['path']))
    if not path.is_absolute():
        raise ValueError('Choose an absolute local file or folder.')
    if path.is_dir():
        return {'path': str(path), 'text': '\n'.join(sorted(p.name for p in path.iterdir())[:500])}, 'folder'
    with path.open('rb') as stream:
        raw = stream.read(65536)
    return {'path': str(path), 'text': raw.decode('utf-8', 'replace')}, '%d bytes read' % len(raw)


def _run_workshop(params, feeds):
    from .nograph_server import _list_messages
    page = _list_messages()
    limit = int(params.get('limit') or 20)
    messages = [{'who': m.get('who'), 'text': m.get('text')} for m in page['messages'][-limit:]]
    return {'messages': messages}, '%d messages' % len(messages)


def _run_setting(params, feeds):
    value = feeds.get('value', params.get('value'))
    return {'value': value}, str(value)


# engine -> sockets, purity, executor, and which parameter writes through to which owner.
THING_ENGINES = {
    'thing.agent': {'pure': False, 'run': _run_agent, 'in': [_port('task'), _port('files', 'list')],
                    'out': [_port('result'), _port('messages', 'list')]},
    'thing.model': {'pure': False, 'run': _run_model, 'in': [_port('prompt', 'string')], 'out': [_port('text', 'string'), _port('model', 'string')]},
    'thing.host': {'pure': True, 'run': _run_host, 'in': [], 'out': [_port('sessions', 'list'), _port('elements', 'list')]},
    'thing.workspace': {'pure': True, 'run': _run_workspace, 'in': [], 'out': [_port('path', 'string'), _port('files', 'list')]},
    'thing.file': {'pure': True, 'run': _run_file, 'in': [], 'out': [_port('path', 'string'), _port('text', 'string')]},
    'thing.workshop': {'pure': True, 'run': _run_workshop, 'in': [], 'out': [_port('messages', 'list')],
                       'engine': 'thing.workshop', 'params': {'thread': 'app:workshop', 'limit': 20}},
    'thing.setting': {'pure': True, 'run': _run_setting, 'in': [_port('value')], 'out': [_port('value')]},
}
# (engine, param) -> function(new value) writing the owner file the Settings screen reads.
WRITE_THROUGH = {
    ('thing.model', 'default_model'): lambda value: _set_router({'default_model': str(value)}),
    ('thing.model', 'temperature'): lambda value: _set_router({'generation': {**_router()['generation'], 'temperature': float(value)}}),
    ('thing.model', 'max_tokens'): lambda value: _set_router({'generation': {**_router()['generation'], 'max_tokens': int(value)}}),
}


def thing_items():
    """Library cards for every app thing, built on demand from their live owners."""
    def card(item, cat, title, sub, engine, params):
        spec = THING_ENGINES[engine]
        return {'id': item, 'cat': cat, 'title': title, 'sub': sub, 'engine': engine, 'params': params,
                'ports': {'source': list(spec['out']), 'target': list(spec['in'])}}
    items = []
    try:
        router = _router()
        items.append(card('thing:model:default', 'models', 'Model', 'Default model from router.json', 'thing.model',
                          {'route': router['default_model'], 'default_model': router['default_model'], 'prompt': '',
                           'temperature': router['generation']['temperature'], 'max_tokens': router['generation']['max_tokens']}))
        for route in router['fallback_models'][:8]:
            items.append(card('thing:model:' + route, 'models', route.split('/')[-1], 'Free model', 'thing.model',
                              {'route': route, 'prompt': ''}))
    except Exception as error:  # noqa: BLE001 - an unreadable router file leaves the Model cards out, never the Library
        items.append(card('thing:model:unavailable', 'models', 'Model', 'router.json unreadable: %s' % error, 'thing.model',
                          {'prompt': ''}))
    from .agent_runtime_registry import RUNTIMES
    for runtime, row in RUNTIMES.items():
        items.append(card('thing:agent:' + runtime, 'agents', row.get('label', runtime), 'Agent · any open session',
                          'thing.agent', {'agent': row.get('label', runtime), 'instructions': ''}))
    for host, name in (('revit', 'Revit'), ('acad', 'AutoCAD'), ('excel', 'Excel'), ('word', 'Word'), ('outlook', 'Outlook'),
                       ('notion', 'Notion'), ('rhino', 'Rhino'), ('blender', 'Blender'), ('max', '3ds Max'), ('dropbox', 'Dropbox')):
        items.append(card('thing:host:' + host, 'connectors', name, 'Connector · read sessions', 'thing.host',
                          {'host': host, 'document': '', 'view': ''}))
    held_path = Path(os.environ['LOCALAPPDATA']) / 'ArchHub' / 'settings' / 'workspaces.json'
    try:
        held = json.loads(held_path.read_text(encoding='utf-8')) if held_path.exists() else {'roots': []}
        for root in held.get('roots', []):
            items.append(card('thing:workspace:' + root['root_id'], 'workspaces', root.get('label') or root['path'],
                              'Workspace folder', 'thing.workspace', {'path': root['path']}))
    except (OSError, ValueError, KeyError) as error:
        items.append(card('thing:workspace:unreadable', 'workspaces', 'Workspaces', 'workspaces.json unreadable: %s' % error,
                          'thing.workspace', {'path': ''}))
    items.append(card('thing:file', 'files', 'File or folder', 'A local file or folder reference', 'thing.file', {'path': ''}))
    items.append(card('thing:workshop', 'workshop', 'Workshop thread', 'Messages in the Workshop room', 'thing.workshop',
                      dict(THING_ENGINES['thing.workshop']['params'])))
    items.append(card('thing:setting:temperature', 'settings', 'Setting · temperature', 'Router generation setting',
                      'thing.setting', {'value': ''}))
    return items


def run_thing(engine, params, feeds):
    return THING_ENGINES[engine]['run'](params, feeds)


def write_through(node, key, value):
    """A parameter of an app-thing node is the owner's setting; write it there."""
    writer = WRITE_THROUGH.get((node.get('type'), key))
    if writer is not None:
        writer(value)
        return True
    return False


# ----------------------------------------------------------------- solve --
def downstream(document, changed):
    out = {}
    for wire in document['wires']:
        out.setdefault(wire['from']['node'], []).append(wire['to']['node'])
    seen, pending = set(changed), list(changed)
    while pending:
        for target in out.get(pending.pop(), []):
            if target not in seen:
                seen.add(target)
                pending.append(target)
    return seen


def solve(document, changed, *, invoke=None, stopped=None):
    """Re-solve the pure nodes downstream of an edit; mark effects Out of date. Mutates and returns results."""
    from .session_files import run_document, validate
    started = time.perf_counter()
    validate(document)
    nodes = {n['id']: n for n in document['nodes']}
    affected = downstream(document, [c for c in changed if c in nodes])
    incoming = {}
    for wire in document['wires']:
        incoming.setdefault(wire['to']['node'], []).append(wire['from']['node'])
    stale = set()
    # A node waits for Run if it writes, is disabled, or is fed by a node that waits.
    plan = run_document(document, roots=sorted(affected), plan_only=True)['order'] if affected else []
    # Like Grasshopper, an upstream pure node that never solved solves now too.
    unsolved = {k for k in plan if is_pure(nodes[k]['type']) and not nodes[k].get('frozen')
                and (nodes[k].get('result') or {}).get('status') not in ('Done',)}
    if unsolved - affected:
        affected = downstream(document, affected | unsolved)
        plan = run_document(document, roots=sorted(affected), plan_only=True)['order']
    for key in plan:
        node = nodes[key]
        if key in affected and (not is_pure(node['type']) or node.get('frozen')
                                or any(source in stale for source in incoming.get(key, []))):
            stale.add(key)
    pure = [key for key in plan if key in affected and key not in stale]
    results = {}
    if pure:
        ran = run_document(document, roots=pure, invoke=invoke, stopped=stopped, cached=affected - set(pure),
                           only=set(pure))
        for key in pure:
            results[key] = ran['results'].get(key, {'status': 'Idle', 'output': {}})
    for key in stale:
        held = nodes[key].get('result') or {}
        results[key] = {'status': 'Disabled' if nodes[key].get('frozen') else 'Out of date',
                        'output': held.get('output', {}), 'error': ''}
    for key, result in results.items():
        nodes[key]['result'] = {k: v for k, v in result.items() if k in ('status', 'output', 'error', 'display')}
        nodes[key]['result']['error'] = str(nodes[key]['result'].get('error', ''))
    ms = round((time.perf_counter() - started) * 1000, 1)
    return {'ok': True, 'results': results, 'solved': pure, 'stale': sorted(stale), 'ms': ms}


# ----------------------------------------------------- shared file edits --
def _lock_path(path):
    root = Path(os.environ['LOCALAPPDATA']) / 'ArchHub' / 'sessions-files' / 'locks'
    root.mkdir(parents=True, exist_ok=True)
    return root / (hashlib.sha1(str(Path(path).resolve()).lower().encode()).hexdigest() + '.lock')


_THREAD_LOCKS = {}
_THREAD_GUARD = threading.Lock()


@contextmanager
def locked(path, timeout=10.0):
    """One writer per file across the app and every agent process."""
    import msvcrt
    key = str(_lock_path(path))
    with _THREAD_GUARD:
        local = _THREAD_LOCKS.setdefault(key, threading.Lock())
    with local:
        with open(key, 'a+b') as handle:
            deadline = time.monotonic() + timeout
            while True:
                try:
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    if time.monotonic() > deadline:
                        raise TimeoutError('Another editor holds this file; retry.')
                    time.sleep(DOCUMENT_NODE['params']['lock_poll_seconds'])
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


def revision(document):
    return int((document.get('properties') or {}).get('revision', 0))


def _stamp(document, before, by, op):
    """Bump the revision and record who changed which nodes/wires, with the values to undo it."""
    props = document.setdefault('properties', {})
    props['revision'] = revision(before) + 1 if before else revision(document) + 1
    old_nodes = {n['id']: n for n in (before or {}).get('nodes', [])}
    old_wires = {w['id']: w for w in (before or {}).get('wires', [])}
    new_nodes = {n['id']: n for n in document['nodes']}
    new_wires = {w['id']: w for w in document['wires']}
    strip = lambda n: {k: v for k, v in n.items() if k != 'result'} if n else None
    undo = {'nodes': {i: old_nodes.get(i) for i in set(old_nodes) | set(new_nodes) if strip(old_nodes.get(i)) != strip(new_nodes.get(i))},
            'wires': {i: old_wires.get(i) for i in set(old_wires) | set(new_wires) if old_wires.get(i) != new_wires.get(i)},
            'title': (before or {}).get('title')}
    history = [row for row in (before or {}).get('properties', {}).get('history', [])][-(DOCUMENT_NODE['params']['history_limit'] - 1):]
    history.append({'revision': props['revision'], 'by': str(by)[:120], 'op': str(op)[:200],
                    'at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'undo': undo})
    props['history'] = history
    return document


def read(path):
    from .session_files import read_document
    return read_document(path)


def edit(path, by, op, change, *, create_title=None, solve_changed=True):
    """Read-modify-write one .archhub file atomically; change(doc) returns the ids it touched."""
    from .session_files import new_document, read_document, write_document, validate
    from .enforce import guard_effect
    with locked(path):
        if Path(path).exists():
            before = read_document(path)
        elif create_title is not None:
            before = None
        else:
            raise FileNotFoundError('No .archhub file at ' + str(path))
        document = copy.deepcopy(before) if before else new_document(create_title or Path(path).stem)
        touched = change(document) or []
        validate(document)
        solved = None
        if solve_changed and touched:
            solved = solve(document, touched, invoke=guard_effect)
        _stamp(document, before, by, op)
        write_document(path, document)
    return document, solved


def undo_last(path, by):
    """Undo the newest history entry (any author), itself recorded as an attributed edit."""
    def change(document):
        history = document.get('properties', {}).get('history', [])
        entry = next((h for h in reversed(history) if not h['op'].startswith('undo')), None)
        if entry is None:
            raise ValueError('Nothing to undo.')
        nodes = {n['id']: n for n in document['nodes']}
        wires = {w['id']: w for w in document['wires']}
        for key, old in entry['undo']['nodes'].items():
            nodes.pop(key, None) if old is None else nodes.__setitem__(key, old)
        for key, old in entry['undo']['wires'].items():
            wires.pop(key, None) if old is None else wires.__setitem__(key, old)
        document['nodes'], document['wires'] = list(nodes.values()), list(wires.values())
        entry['op'] = 'undo:' + entry['op']
        return [k for k in entry['undo']['nodes'] if k in nodes]
    return edit(path, by, 'undo', change)


def merge(base, ours, theirs):
    """Three-way merge at node/wire id granularity: the other editor's changes survive ours."""
    result = copy.deepcopy(theirs)
    for field in ('nodes', 'wires'):
        b = {x['id']: x for x in (base or {}).get(field, [])}
        o = {x['id']: x for x in ours.get(field, [])}
        t = {x['id']: x for x in result[field]}
        for key in set(b) | set(o):
            if b.get(key) == o.get(key):
                continue  # we did not touch it: theirs stands
            if key in o:
                t[key] = o[key]
            else:
                t.pop(key, None)
        result[field] = list(t.values())
    node_ids = {n['id'] for n in result['nodes']}
    result['wires'] = [w for w in result['wires'] if w['from']['node'] in node_ids and w['to']['node'] in node_ids]
    seen = set()
    result['wires'] = [w for w in result['wires'] if not ((w['to']['node'], w['to']['socket']) in seen or seen.add((w['to']['node'], w['to']['socket'])))]
    for key in ('title', 'viewport', 'groups', 'notes'):
        if (base or {}).get(key) != ours.get(key):
            result[key] = copy.deepcopy(ours[key])
    return result


# The app's in-memory copies of revisions it served, so a UI save can merge against its base.
_SNAPSHOTS = {}


def remember(path, document):
    held = _SNAPSHOTS.setdefault(str(path).lower(), {})
    held[revision(document)] = copy.deepcopy(document)
    for old in sorted(held)[:-20]:
        held.pop(old)


def commit_ui(path, document, base_revision, by='You'):
    """The founder's window saves: merge with any agent edit made since its base."""
    from .session_files import read_document, write_document, validate
    validate(document)
    with locked(path):
        current = read_document(path) if Path(path).exists() else None
        if current is not None and revision(current) != base_revision:
            base = _SNAPSHOTS.get(str(path).lower(), {}).get(base_revision)
            document = merge(base, document, current)
            validate(document)
        if current is not None and json.dumps({k: v for k, v in document.items() if k != 'properties'}, sort_keys=True) == \
                json.dumps({k: v for k, v in current.items() if k != 'properties'}, sort_keys=True):
            remember(path, current)
            return current
        document['properties'] = {**(current or {}).get('properties', {}), **{k: v for k, v in (document.get('properties') or {}).items()
                                                                          if k not in ('revision', 'history')}}
        _stamp(document, current, by, 'edit in ArchHub')
        write_document(path, document)
        remember(path, document)
        return document
