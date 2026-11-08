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

from .user_paths import state_directory

import copy
import hashlib
import json
import re
import threading
import time
from contextlib import contextmanager
from pathlib import Path

# The .archhub document owner node: its typed parameters.
DOCUMENT_NODE = {'id': 'canvas.document', 'params': {'history_limit': 200, 'lock_poll_seconds': 0.02,
                                                     'budget': {'seconds': 60, 'calls': 1, 'cost_usd': 0.0},
                                                     'loop': {'trigger': 'Run', 'stop': 'list exhausted', 'evaluator': '', 'cap': 1000}}}
_READ = re.compile(r'\.(read|info|list|search|inbox|get|query|ping|status|preview|probe)(_|$)')


# --------------------------------------------------------------- purity --
def is_pure(engine, params=None):
    """Pure nodes solve on edit; anything that writes waits for Run."""
    from .library_engines import STEM_RUN_ENGINES
    from .pipeline_engines import PIPELINE_ENGINES
    if engine == 'thing.agent' and (params or {}).get('reference') is True:
        return True
    if engine in STEM_RUN_ENGINES or engine in ('note', 'data.convert', 'param.value', 'data.dataset', 'data.field'):
        return True
    if engine in THING_ENGINES:
        return THING_ENGINES[engine]['pure']
    effect = PIPELINE_ENGINES.get(engine)
    return bool(effect is not None and not getattr(effect, 'enforce_pending', False) and _READ.search(engine))


# ------------------------------------------------------------ node contract --
# C2: every node has typed sockets, a pure/side-effect flag and a budget; a loop node also
# declares its trigger, stop condition, evaluator and cap. These are the catalogue defaults;
# a THING_ENGINES row may override 'budget'. Purity is engine-owned and never read from a file.
BUDGET_DEFAULT = DOCUMENT_NODE['params']['budget']
BUDGET_KEYS = frozenset(BUDGET_DEFAULT)
LOOP_ENGINES = frozenset({'library.loop', 'control.foreach'})
LOOP_DEFAULT = DOCUMENT_NODE['params']['loop']


def node_contract(engine):
    """The catalogue's contract for one engine: pure, budget and (loop nodes only) loop."""
    spec = THING_ENGINES.get(engine) or {}
    return {'pure': is_pure(engine), 'budget': dict(spec.get('budget', BUDGET_DEFAULT)),
            'loop': dict(LOOP_DEFAULT) if engine in LOOP_ENGINES else None}


def check_contract(node):
    """Refuse a malformed budget/loop in a file, and set pure from the engine."""
    budget = node.get('budget')
    if budget is not None and (not isinstance(budget, dict) or set(budget) - BUDGET_KEYS or any(
            type(v) not in (int, float) or v < 0 for v in budget.values())):
        raise ValueError('Node budget must hold non-negative seconds, calls and cost_usd')
    loop = node.get('loop')
    if loop is not None and (not isinstance(loop, dict) or set(loop) != set(LOOP_DEFAULT)
                             or any(not isinstance(loop[k], str) for k in ('trigger', 'stop', 'evaluator'))
                             or type(loop['cap']) is not int or loop['cap'] < 1):
        raise ValueError('Node loop must declare trigger, stop, evaluator and a positive cap')
    if 'pure' in node:  # a file may carry the flag for readers; the value is always the engine's (unknown = side effect)
        node['pure'] = is_pure(node.get('type'), node.get('params'))


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
    system = str(feeds.get('system') or params.get('system') or '').strip()
    if system:
        prompt = system + '\n\n' + prompt
    body = {'prompt': prompt, 'agent': 'BABOOM', 'model': str(params.get('route') or _router()['default_model'])}
    if feeds.get('temperature') not in (None, ''):
        body['temperature'] = float(feeds['temperature'])
    result = composer_chat(body)
    return {'text': result['answer'], 'model': result['model']}, result['model']


def _run_agent(params, feeds):
    if params.get('reference') is True:
        return {'agent': params.get('agent', '')}, params.get('agent') or 'No agent yet'
    from .workshop_mailbox import call
    instructions = str(params.get('instructions') or '').strip()
    task = str(feeds.get('task') or '').strip()
    # A wired task runs under the node's instructions (an imported skill is both).
    task = instructions + '\n\nTask: ' + task if instructions and task else task or instructions
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


def _write_file(params, feeds):
    from .hook_decision import _RELEASING
    import os
    import tempfile
    if not _RELEASING.get(False):
        raise PermissionError('File writes require the Approve card.')
    path = Path(str(params['path']))
    if not path.is_absolute() or str(path).startswith(('\\\\', '//')):
        raise ValueError('Choose an absolute local output file.')
    content = str(params.get('content', ''))
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', newline='', dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
    if path.read_bytes() != content.encode('utf-8'):
        raise OSError('File write readback did not match.')
    return {'path': str(path)}, 'File written and re-read'


def _run_workshop(params, feeds):
    limit = int(params.get('limit') or 20)
    if params.get('thread') and params['thread'] != 'app:workshop':
        from .workshop_mailbox import application_history
        from .workshop_tasks import rows, _held_context, _file_messages, _bound_messages
        from .session_files import read_document
        with application_history() as history:
            task = next(iter(rows(history, params['thread'], settle=False)), None)
            if not task:
                raise ValueError('No such Workshop task')
            document = read_document(task['session_path'])
            messages = (_file_messages(document) + _bound_messages(history, params['thread']))[-limit:]
        return {'messages': messages, 'rules': _held_context(document)['rules']}, '%d messages' % len(messages)
    from .nograph_server import _list_messages
    page = _list_messages()
    messages = [{'who': m.get('who'), 'text': m.get('text')} for m in page['messages'][-limit:]]
    return {'messages': messages}, '%d messages' % len(messages)


def _run_session(params, feeds):
    return {'value': feeds.get('value', params.get('value', '')), 'agent': feeds.get('agent', ''),
            'profile': feeds.get('profile'), 'rules': feeds.get('rules', [])}, 'Session parameters'


def _run_you(params, feeds):
    # The portable document carries a binding, never a copy of account identity.
    return {'profile': {'owner': 'account', 'scope': 'current'}}, 'Current profile in Settings'


def _run_setting(params, feeds):
    if params.get('setting'):
        from .settings_owner import appearance_setting
        value = appearance_setting(params['setting'])['value']
    else:
        value = feeds.get('value', params.get('value'))
    return {'value': value}, str(value)


def _run_foreign(params, feeds):
    # An imported node ArchHub has no engine for: untrusted foreign code never runs (flow_import.py).
    raise ValueError('Not run: imported %s %s node. %s. Replace it with a Library node.'
                     % (params.get('format', ''), params.get('kind', ''), params.get('reason', 'No ArchHub engine')))


# engine -> sockets, purity, executor, and which parameter writes through to which owner.
THING_ENGINES = {
    'thing.agent': {'pure': False, 'run': _run_agent, 'in': [_port('task'), _port('files', 'list')],
                    'out': [_port('result'), _port('messages', 'list'), _port('agent', 'string')]},
    'thing.session': {'pure': True, 'run': _run_session,
                      'in': [_port('value'), _port('agent', 'string'), _port('profile'), _port('rules', 'list')],
                      'out': [_port('value', 'string'), _port('agent', 'string'), _port('profile'), _port('rules', 'list')]},
    'thing.you': {'pure': True, 'run': _run_you, 'in': [], 'out': [_port('profile')]},
    'thing.model': {'pure': False, 'run': _run_model, 'in': [_port('prompt', 'string'), _port('temperature', 'number'), _port('system', 'string')],
                    'out': [_port('text', 'string'), _port('model', 'string')]},
    'thing.host': {'pure': True, 'run': _run_host, 'in': [], 'out': [_port('sessions', 'list'), _port('elements', 'list')]},
    'thing.workspace': {'pure': True, 'run': _run_workspace, 'in': [], 'out': [_port('path', 'string'), _port('files', 'list')]},
    'thing.file': {'pure': True, 'run': _run_file, 'in': [], 'out': [_port('path', 'file'), _port('text', 'string')]},
    'thing.file.write': {'pure': False, 'run': _write_file, 'in': [], 'out': [_port('path', 'file')]},
    'thing.workshop': {'pure': True, 'run': _run_workshop, 'in': [], 'out': [_port('messages', 'list'), _port('rules', 'list')],
                       'engine': 'thing.workshop', 'params': {'thread': 'app:workshop', 'limit': 20}},
    'thing.setting': {'pure': True, 'run': _run_setting, 'in': [_port('value')], 'out': [_port('value')]},
    # Not a Library card: only importers place it; its sockets live on the node.
    'import.foreign': {'pure': False, 'run': _run_foreign, 'in': [], 'out': []},
}
from .daily_work_nodes import DAILY_ENGINES, daily_items  # noqa: E402 - the daily-work pack shares this one contract
THING_ENGINES.update(DAILY_ENGINES)
# (engine, param) -> function(new value) writing the owner file the Settings screen reads.
WRITE_THROUGH = {
    ('thing.model', 'default_model'): lambda value: _set_router({'default_model': str(value)}),
    ('thing.model', 'temperature'): lambda value: _set_router({'generation': {**_router()['generation'], 'temperature': float(value)}}),
    ('thing.model', 'max_tokens'): lambda value: _set_router({'generation': {**_router()['generation'], 'max_tokens': int(value)}}),
    ('thing.model', 'top_p'): lambda value: _set_router({'generation': {**_router()['generation'], 'top_p': float(value)}}),
}


def thing_items():
    """Library cards for every app thing, built on demand from their live owners."""
    def card(item, cat, title, sub, engine, params, kind=None):
        spec = THING_ENGINES[engine]
        typed = lambda ports: [dict(p, type=kind) if kind and p['type'] == 'any' else p for p in ports]
        # Parameters that are router.json settings show as From Settings: one authority.
        settings = sorted(key for (owner, key) in WRITE_THROUGH if owner == engine and key in params)
        return {'id': item, 'cat': cat, 'title': title, 'sub': sub, 'engine': engine, 'params': params,
                'settingsKeys': settings, 'ports': {'source': typed(spec['out']), 'target': typed(spec['in'])}}
    items = []
    try:
        router = _router()
        items.append(card('thing:model:default', 'models', 'Model', 'Default model from router.json', 'thing.model',
                          {'route': router['default_model'], 'default_model': router['default_model'], 'prompt': '',
                           'temperature': router['generation']['temperature'], 'top_p': router['generation']['top_p'],
                           'max_tokens': router['generation']['max_tokens']}))
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
    held_path = state_directory() / 'settings' / 'workspaces.json'
    try:
        held = json.loads(held_path.read_text(encoding='utf-8')) if held_path.exists() else {'roots': []}
        for root in held.get('roots', []):
            items.append(card('thing:workspace:' + root['root_id'], 'workspaces', root.get('label') or root['path'],
                              'Workspace folder', 'thing.workspace', {'path': root['path']}))
    except (OSError, ValueError, KeyError) as error:
        items.append(card('thing:workspace:unreadable', 'workspaces', 'Workspaces', 'workspaces.json unreadable: %s' % error,
                          'thing.workspace', {'path': ''}))
    items.append(card('thing:file', 'files', 'File or folder', 'A local file or folder reference', 'thing.file', {'path': ''}))
    items.append(card('thing:file:write', 'files', 'Write file', 'Writes after Approve, then re-reads', 'thing.file.write', {'path': '', 'content': ''}))
    items.append(card('thing:session', 'workshop', 'Session', 'Task parameters', 'thing.session', {'value': '', 'workspace': ''}))
    items.append(card('thing:you', 'settings', 'You', 'Current profile in Settings', 'thing.you', {}))
    items.append(card('thing:workshop', 'workshop', 'Workshop thread', 'Messages in the Workshop room', 'thing.workshop',
                      dict(THING_ENGINES['thing.workshop']['params'])))
    # The value is router.json's own; a profile whose router.json sets no temperature shows "unset", never a default.
    try:
        from .settings_owner import router_settings_path
        _router()
        held = json.loads(router_settings_path().read_text(encoding='utf-8'))
        temperature = held.get('generation', {}).get('temperature') if isinstance(held, dict) else None
    except Exception:  # noqa: BLE001 - a missing or unreadable router file leaves the parameter unset
        temperature = None
    items.append(card('thing:setting:temperature', 'settings', 'Temperature', 'Number parameter · router generation',
                      'thing.setting', {'value': temperature}, kind='number'))
    from .settings_owner import appearance_settings
    from .node_params import socket_type
    for row in appearance_settings()['appearanceSettings']:
        kind = {'boolean': 'bool'}.get(row['type'], row['type'])
        item = card('thing:setting:' + row['id'], 'settings', row['label'], 'From Settings · ' + row['page'],
                    'thing.setting', {'setting': row['id']}, kind=socket_type(kind))
        item['setting'] = row
        item['settingsKeys'] = ['value']
        items.append(item)
    items.extend(daily_items())
    return items


def run_thing(engine, params, feeds):
    return THING_ENGINES[engine]['run'](params, feeds)


def write_through(node, key, value):
    """A parameter of an app-thing node is the owner's setting; write it there."""
    if node.get('type') == 'thing.setting' and node.get('params', {}).get('setting') and key == 'value':
        from .settings_owner import appearance_setting, appearance_settings
        from .node_params import coerce
        row = appearance_setting(node['params']['setting'])
        kind = 'bool' if type(row['default']) is bool else 'integer' if type(row['default']) is int else row['type']
        appearance_settings('setAppearance', [row['id'], coerce(kind, value, row)])
        return True
    writer = WRITE_THROUGH.get((node.get('type'), key))
    if writer is not None:
        writer(value)
        return True
    return False


def _member_id(member):
    if isinstance(member, str) and member:
        return member
    if isinstance(member, dict) and isinstance(member.get('id'), str) and member['id']:
        return member['id']
    return ''


def _group_node(document, group_id):
    found = [node for node in document.get('nodes') or [] if node.get('id') == group_id]
    if len(found) != 1:
        raise ValueError('Group node is absent')
    return found[0]


def _finite_point(value):
    number = float(value)
    if number != number or number in (float('inf'), float('-inf')):
        raise ValueError('Position must be finite')
    return number


def _source_socket(group):
    ports = group.get('ports') if isinstance(group.get('ports'), dict) else {}
    source = ports.get('source') if isinstance(ports.get('source'), list) else []
    for port in source:
        if isinstance(port, dict) and isinstance(port.get('id'), str) and port['id']:
            return port['id']
    if group.get('type') == 'thing.workshop':
        return 'messages'
    return ''


def detach_member(document, group_id, member, x=0, y=0):
    """Pull one agent member out of a group into one thing.agent node on the same document.

    The node keeps the member's id and agent identity. Its sockets are task in and result out.
    A wire from the group's output into task keeps it on the same graph. Dropping it back is attach_member.
    """
    group = _group_node(document, group_id)
    wanted = member.get('id') if isinstance(member, dict) else member
    if not isinstance(wanted, str) or not wanted or wanted == group_id:
        raise ValueError('Member id is required')
    held = list(group.get('members') or [])
    index = next((i for i, item in enumerate(held) if _member_id(item) == wanted), None)
    if index is None:
        if group.get('type') != 'thing.workshop' or not isinstance(member, dict):
            raise ValueError('Member is not in this group')
        record = {'id': wanted, 'title': str(member.get('title') or wanted), 'agent': str(member.get('agent') or wanted)}
    else:
        item = held.pop(index)
        group['members'] = held
        if isinstance(item, dict):
            record = {'id': wanted, 'title': str(item.get('title') or item.get('name') or wanted),
                      'agent': str(item.get('agent') or wanted)}
        else:
            record = {'id': wanted, 'title': wanted, 'agent': wanted}
        if isinstance(member, dict):
            if isinstance(member.get('title'), str) and member['title'].strip():
                record['title'] = member['title'].strip()
            if isinstance(member.get('agent'), str) and member['agent'].strip():
                record['agent'] = member['agent'].strip()
    if any(node.get('id') == wanted for node in document['nodes']):
        raise ValueError('Agent node already exists')
    created = {
        'id': wanted,
        'type': 'thing.agent',
        'title': record['title'],
        'params': {'agent': record['agent'], 'instructions': ''},
        'position': {'x': _finite_point(x), 'y': _finite_point(y)},
        'ports': {'source': [_port('result')], 'target': [_port('task')]},
    }
    document['nodes'].append(created)
    socket = _source_socket(group)
    if socket:
        document.setdefault('wires', []).append({
            'id': 'wire-' + group_id + '-' + wanted,
            'from': {'node': group_id, 'socket': socket},
            'to': {'node': wanted, 'socket': 'task'},
        })
    return [wanted]


def attach_member(document, group_id, node_id):
    """Put a detached agent node back in the group and remove that node from the document."""
    group = _group_node(document, group_id)
    if node_id == group_id:
        raise ValueError('A group cannot contain itself')
    node = next((item for item in document.get('nodes') or [] if item.get('id') == node_id), None)
    if node is None:
        raise ValueError('Agent node is absent')
    if node.get('type') != 'thing.agent':
        raise ValueError('Only an agent node returns to the group')
    document['nodes'] = [item for item in document['nodes'] if item.get('id') != node_id]
    document['wires'] = [wire for wire in document.get('wires') or []
                         if wire.get('from', {}).get('node') != node_id and wire.get('to', {}).get('node') != node_id]
    for item in document['nodes']:
        if isinstance(item.get('children'), list):
            item['children'] = [child for child in item['children'] if child != node_id]
        if item.get('parent') == node_id:
            item.pop('parent', None)
    members = [item for item in list(group.get('members') or []) if _member_id(item) != node_id]
    members.append({'id': node_id, 'title': str(node.get('title') or node_id),
                    'agent': str((node.get('params') or {}).get('agent') or node_id)})
    group['members'] = members
    for listing in document.get('groups') or []:
        if isinstance(listing, dict) and isinstance(listing.get('nodes'), list):
            listing['nodes'] = [item for item in listing['nodes'] if item != node_id]
    return [group_id]


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
    unsolved = {k for k in plan if is_pure(nodes[k]['type'], nodes[k]['params']) and not nodes[k].get('frozen')
                and (nodes[k].get('result') or {}).get('status') not in ('Done',)}
    if unsolved - affected:
        affected = downstream(document, affected | unsolved)
        plan = run_document(document, roots=sorted(affected), plan_only=True)['order']
    for key in plan:
        node = nodes[key]
        if key in affected and (not is_pure(node['type'], node['params']) or node.get('frozen')
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
    from .session_files import profile_directory
    root = profile_directory() / 'data' / 'sessions' / 'locks'
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
            'title': (before or {}).get('title'),
            **{key: copy.deepcopy(before[key]) for key in ('groups', 'notes') if before is not None and before.get(key) != document.get(key)}}
    history = [row for row in (before or {}).get('properties', {}).get('history', [])][-(DOCUMENT_NODE['params']['history_limit'] - 1):]
    history.append({'revision': props['revision'], 'by': str(by)[:120], 'op': str(op)[:200],
                    'at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'undo': undo})
    props['history'] = history
    return document


def read(path):
    from .session_files import read_document
    return read_document(path)


def edit(path, by, op, change, *, create_title=None, solve_changed=True, always_record=False):
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
        fixed = {node['id'] for node in (before or {}).get('nodes', []) if node.get('fixed')}
        if fixed - {node['id'] for node in document['nodes'] if node.get('fixed')}:
            raise ValueError('The four fixed nodes stay on every task canvas.')
        mutated = document != before
        validate(document)
        solved = None
        if solve_changed and touched:
            solved = solve(document, touched, invoke=guard_effect)
        if not mutated and not always_record:
            return document, solved
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
        for key in ('groups', 'notes'):
            if key in entry['undo']:
                document[key] = copy.deepcopy(entry['undo'][key])
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
                                                                          if k not in ('revision', 'history', 'checkpoints')}}
        _stamp(document, current, by, 'edit in ArchHub')
        write_document(path, document)
        remember(path, document)
        return document
