"""Portable Canvas documents. No CellStore, enrollment or graph lock."""
from __future__ import annotations

from .user_paths import state_directory, test_writer, stamp_test_write, strip_test_write

import copy
import hashlib
import json
import logging
import math
import os
from pathlib import Path
import re
import tempfile
import threading
import time
from uuid import uuid4

from . import canvas_documents

MAX_BYTES = 8 * 1024 * 1024
# Windows readers must close metadata handles before another request replaces the file.
_METADATA_LOCK = threading.RLock()

def _metadata_io(operation, *args, **kwargs):
    for attempt in range(7):
        try:
            return operation(*args, **kwargs)
        except OSError as error:
            if getattr(error, 'winerror', None) not in (5, 32, 33):
                raise
            time.sleep(.025 * (attempt + 1))
    return operation(*args, **kwargs)


_SECRET = re.compile(r'(^|_)(password|secret|token|api_key|private_key|credential)(_|$)', re.I)
# Connection-node choices on the wire record itself. The first choice is what a
# missing field means, so an old .archhub file still loads. Mirrored in studio/api.js.
_WIRE_MENUS = (
    ('matching', ('By index', 'Longest', 'Shortest', 'Cross')),
    ('order', ('Source order', 'Reverse')),
    ('missing', ('Preserve', 'Drop', 'Blank')),
    ('units', ('From source', 'From target')),
    ('conversion', ('None', 'Number', 'Text')),
    ('route', ('Bezier', 'Straight', 'Step')),
)


def wire_choice(wire, name):
    """Saved choice, or the first choice when the file omits the field."""
    choices = next(items for key, items in _WIRE_MENUS if key == name)
    held = wire.get(name) if isinstance(wire, dict) else None
    if held in (None, ''):
        return choices[0]
    if not isinstance(held, str) or held not in choices:
        raise ValueError('Wire %s must be one of: %s' % (name, ', '.join(choices)))
    return held


def _blank_missing(value):
    if value is None:
        return ''
    if isinstance(value, list):
        return ['' if item is None else item for item in value]
    return value


def _convert_carried(kind, value):
    if kind == 'None':
        return value
    if isinstance(value, list):
        return [_convert_carried(kind, item) for item in value]
    if kind == 'Text':
        return '' if value is None else str(value)
    if kind == 'Number':
        if isinstance(value, bool) or value is None:
            raise ValueError('Wire conversion Number cannot read %r' % (value,))
        if isinstance(value, (int, float)):
            return value
        try:
            number = float(str(value).strip())
        except ValueError:
            raise ValueError('Wire conversion Number cannot read %r' % (value,)) from None
        if not math.isfinite(number):
            raise ValueError('Wire conversion Number cannot read %r' % (value,))
        return int(number) if number == int(number) else number
    raise ValueError('Wire conversion %r is not one this version applies' % (kind,))


def _shape_carried(wire, value):
    """Order, then missing values, then conversion, on the one value this wire carries.

    Units stay on the record and are not converted here. Route is the drawn path.
    From, To, Data, Access, Direction and State are read from the sockets and the run.
    """
    if wire_choice(wire, 'order') == 'Reverse' and isinstance(value, list):
        value = list(reversed(value))
    missing = wire_choice(wire, 'missing')
    if missing == 'Drop' and isinstance(value, list):
        value = [item for item in value if item is not None]
    elif missing == 'Blank':
        value = _blank_missing(value)
    return _convert_carried(wire_choice(wire, 'conversion'), value)


def _match_feeds(rows):
    """Align list feeds into one node. A single list is already indexed."""
    lists = [row for row in rows if isinstance(row[2], list)]
    if len(lists) < 2:
        return
    lengths = [len(row[2]) for row in lists]
    shortest = min(lengths)
    longest = max(lengths)
    product = 1
    for length in lengths:
        product *= length
    originals = [list(row[2]) for row in lists]
    for row, original, length in zip(lists, originals, lengths):
        mode = wire_choice(row[0], 'matching')
        if mode == 'Shortest':
            row[2] = original[:shortest]
        elif mode == 'Longest' and length and length < longest:
            row[2] = original + [original[-1]] * (longest - length)
        elif mode == 'Cross' and length:
            span = product // length
            row[2] = [item for item in original for _count in range(span)]


def _split_each_wires(wired, nodes, outputs, engine, target_id):
    """Separate foreach.each streams from inputs that stay constant."""
    from .library_engines import canonical_engine_interface
    from .stem_graph_evaluation import StemWire, _carry, _Refusal, foreach_each_items
    shaped = []
    streams = {}
    for wire in wired:
        source = nodes[wire['from']['node']]
        socket = canonical_engine_interface(source['type'], 'source', wire['from']['socket'])
        produced = outputs[source['id']]
        if socket not in produced:
            raise ValueError('Source socket produced no value: ' + str(socket))
        target = canonical_engine_interface(engine, 'target', wire['to']['socket'])
        gate = StemWire(source['id'], str(socket), target_id, wire['to']['socket'], condition=wire.get('rule', ''))
        items = foreach_each_items(source['type'], socket, produced)
        if items is None:
            value = _carry(gate, _shape_carried(wire, produced[socket]))
            if isinstance(value, _Refusal):
                raise ValueError(value.reason)
            shaped.append([wire, target, value])
            continue
        ordered = _shape_carried(wire, items)
        if not isinstance(ordered, list):
            ordered = [ordered]
        carried = []
        for item in ordered:
            value = _carry(gate, item)
            if isinstance(value, _Refusal):
                raise ValueError(value.reason)
            carried.append(value)
        streams[target] = carried
    return shaped, streams


def _params_and_feeds(node, engine, feeds):
    """Base sockets and param:<id> set the same value; param:<id> takes precedence."""
    from .canvas_documents import THING_ENGINES
    from .library_engines import canonical_engine_parameters
    from .node_params import PARAM_ENGINE
    own = {k: v for k, v in node['params'].items() if k not in {d['id'] for d in node.get('paramDefs', [])}}
    extra = {k: v for k, v in node['params'].items() if k not in own}
    for definition in node.get('paramDefs', []):
        if definition['id'] in feeds:
            extra[definition['id']] = feeds[definition['id']]
    for socket in [s for s in list(feeds) if str(s).startswith('param:')]:
        extra[socket[6:]] = feeds.pop(socket)
    params = own if engine in ('skill', PARAM_ENGINE) or engine in THING_ENGINES else canonical_engine_parameters(engine, own)
    return {**params, **extra}, feeds


def _dispatch_node(document, node, engine, params, feeds, *, invoke, stopped, depth, continuation=None):
    """One engine call. Effect engines receive the application invoke boundary."""
    from .canvas_documents import THING_ENGINES, run_thing
    from .library_engines import STEM_RUN_ENGINES
    from .node_params import PARAM_ENGINE, bound_value, coerce
    from .pipeline_engines import PIPELINE_ENGINES
    from .stem_graph_evaluation import run_stem_operation
    from .hook_decision import _RELEASING
    work = node.get('agentWork', {})
    if work.get('runnable') is False:
        raise ValueError('Shell and edit steps require the escape hatch; replay is unavailable.')
    if not _RELEASING.get(False) and (engine == 'approval.gate' or not canvas_documents.is_pure(engine, params) and (work.get('role') == 'step' or node.get('approvalRequired') or engine in ('thing.file.write', 'script.python'))):
        from .agent_work import request_approval
        card = request_approval(node, params, feeds, continuation=continuation)
        return {'approvalId': card['id']}, 'Waiting for approval'
    if engine == 'approval.gate' and _RELEASING.get(False):
        from hashlib import sha256
        from .nodeslib_v2_engines import approval_gate
        digest = sha256(json.dumps({'node': node, 'feeds': feeds}, sort_keys=True).encode()).hexdigest()
        granted = {**params, 'grant': {'digest': digest, 'operations': [params.get('operation', '*')], 'scope': params.get('scope', 'revit.write')}}
        produced, _display = approval_gate(granted, feeds)
        return produced, 'Approved'
    if engine == PARAM_ENGINE:
        value = bound_value(document, node) if node.get('bind') else feeds.get('value', params.get('value'))
        owner = next((n for n in document['nodes'] if n['id'] == (node.get('bind') or {}).get('node')), node)
        key = (node.get('bind') or {}).get('param', 'value')
        entry = next((d for d in owner.get('paramDefs', []) if d['id'] == key), {})
        return {'value': coerce(node['params'].get('type', 'json'), value, entry)}, str(value)
    if engine in ('data.dataset', 'data.field'):
        from .node_datasets import outputs as dataset_outputs
        return dataset_outputs(node, feeds)
    if engine in THING_ENGINES:
        return run_thing(engine, params, feeds)
    if engine == 'skill':
        return run_skill({**params, 'called_by': document['title']}, invoke=invoke, stopped=stopped, depth=depth, feeds=feeds,
                         parent={**continuation, 'node': node} if continuation else None)
    if engine == 'note':
        return {}, node.get('title', 'Note')
    if engine == 'script.python':
        from .host_exec import script_python
        produced, display = script_python(params, {**{p['id']: params.get(p['id'], '') for p in node.get('ports', {'target': [{'id': 'a'}]}).get('target', [])}, **feeds})
        if any(p['id'] not in produced for p in node.get('ports', {}).get('source', [])):
            raise ValueError('Return a value for every declared output.')
        return produced, display
    if engine in STEM_RUN_ENGINES:
        return run_stem_operation(engine, params, feeds)
    effect = PIPELINE_ENGINES[engine]
    if invoke is None:
        raise ValueError('This engine needs the application effect boundary')
    return invoke(engine, effect, params, feeds)


def new_document(title='Untitled'):
    return {'format': 'archhub', 'version': 1, 'id': str(uuid4()), 'title': title,
            'nodes': [], 'wires': [], 'groups': [], 'notes': [],
            'viewport': {'x': 0, 'y': 0, 'zoom': 1}}


def wire_rule(document, identity, rule):
    from .stem_graph_evaluation import rule_holds
    wire = next((w for w in document['wires'] if w['id'] == identity), None)
    if wire is None:
        raise ValueError('Choose a wire.')
    if not isinstance(rule, str) or len(rule) > 4096 or rule.strip() and rule_holds(rule, None) is None:
        raise ValueError('Use a wire comparison such as value > 0 or count >= 1.')
    return rule


def validate(document):
    """Reject corrupt/secret-bearing files before changing the open document."""
    if not isinstance(document, dict) or document.get('format') != 'archhub' or (type(document.get('version')) is not int or document.get('version') != 1):
        raise ValueError('Unsupported .archhub format or version')
    if not isinstance(document.get('id'), str) or not document['id'] or not isinstance(document.get('title'), str):
        raise ValueError('Session id and title are required')
    if set(document) - {'format','version','id','title','nodes','wires','groups','notes','viewport','properties'}:
        raise ValueError('Unknown session fields')
    for key in ('nodes','wires','groups','notes'):
        if not isinstance(document.get(key), list):
            raise ValueError(key + ' must be an array')
    if len(document['nodes']) > 10000 or len(document['wires']) > 50000:
        raise ValueError('Session exceeds 10000 nodes or 50000 wires')
    def safe(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if _SECRET.search(key) and child not in ('', None):
                    raise ValueError('Credentials belong in Connections, never session files')
                safe(child)
        elif isinstance(value, list):
            for child in value:
                safe(child)
        elif isinstance(value, float) and not math.isfinite(value):
            raise ValueError('Session numbers must be finite')
    safe(document)
    nodes = {}
    for node in document['nodes']:
        if not isinstance(node, dict) or not isinstance(node.get('id'), str) or not node['id'] or node['id'] in nodes:
            raise ValueError('Node ids must be unique nonempty strings')
        if not isinstance(node.get('type'), str) or not isinstance(node.get('params'), dict):
            raise ValueError('Each node needs a type and params')
        position = node.get('position')
        if not isinstance(position, dict) or set(position) != {'x','y'} or any(type(v) not in (int,float) or not math.isfinite(v) for v in position.values()):
            raise ValueError('Each node needs a finite x/y position')
        for field in ('title','item','parent'):
            if field in node and not isinstance(node[field],str):
                raise ValueError('Node '+field+' must be text')
        if 'children' in node and (not isinstance(node['children'],list) or any(not isinstance(child,str) for child in node['children'])):
            raise ValueError('Group children must be node ids')
        canvas_documents.check_contract(node)
        for field in ('portVisibility','parameterPresentation','ports','result'):
            if field in node and not isinstance(node[field],dict):
                raise ValueError('Node '+field+' must be an object')
        if 'result' in node:
            if not isinstance(node['result'].get('status',''),str) or not isinstance(node['result'].get('error',''),str):
                raise ValueError('Node result status and error must be text')
        if 'ports' in node:
            for side in ('source','target'):
                if not isinstance(node['ports'].get(side),list) or any(not isinstance(port,dict) or not isinstance(port.get('id'),str) for port in node['ports'][side]):
                    raise ValueError('Node ports must declare source and target sockets')
        if node['type'] == 'script.python':
            if not isinstance(node['params'].get('code', ''), str) or len(node['params'].get('code', '')) > 65536:
                raise ValueError('Script code must be text, up to 64 KiB.')
            if node['params'].get('kind', 'pure') not in ('pure', 'effect'):
                raise ValueError('Script kind must be Pure or Effect.')
            for side, ports in node.get('ports', {}).items():
                if len({p['id'] for p in ports}) != len(ports) or any(not re.fullmatch(r'[a-zA-Z][a-zA-Z0-9_]*', p['id']) or p.get('type') not in ('text','number','file','elements','color','event','any') for p in ports):
                    raise ValueError('Use unique Script socket names and a supported type.')
            if node.get('ports') and not node['ports']['source']:
                raise ValueError('Keep at least one Script output.')
        nodes[node['id']] = node
    for node in nodes.values():
        if node.get('parent') and node['parent'] not in nodes or any(child not in nodes for child in node.get('children',[])):
            raise ValueError('Group members must exist')
        if 'frameMembers' in node and (not isinstance(node['frameMembers'], list) or len(set(node['frameMembers'])) != len(node['frameMembers']) or any(not isinstance(child, str) or child not in nodes or child == node['id'] for child in node['frameMembers'])):
            raise ValueError('Frame members must name existing nodes once.')
        for flag in ('collapsed', 'bypassed'):
            if flag in node and type(node[flag]) is not bool:
                raise ValueError('Node ' + flag + ' must be Boolean')
    for group in document['groups']:
        if not isinstance(group,dict) or not isinstance(group.get('id'),str) or not isinstance(group.get('nodes'),list) or any(key not in nodes for key in group['nodes']):
            raise ValueError('Groups must name existing nodes')
    for note in document['notes']:
        if not isinstance(note,dict) or not isinstance(note.get('text'),str):
            raise ValueError('Notes must contain text')
    ids, inputs = set(), set()
    for wire in document['wires']:
        if not isinstance(wire, dict) or not isinstance(wire.get('id'), str) or wire['id'] in ids:
            raise ValueError('Wire ids must be unique strings')
        ids.add(wire['id'])
        for side in ('from','to'):
            end = wire.get(side)
            if not isinstance(end, dict) or set(end) != {'node','socket'} or end['node'] not in nodes or not isinstance(end['socket'], str) or not end['socket']:
                raise ValueError('Wire endpoints must name existing nodes and sockets')
        target = (wire['to']['node'], wire['to']['socket'])
        if target in inputs:
            raise ValueError('An input socket accepts one wire')
        inputs.add(target)
        if 'rule' in wire and not isinstance(wire.get('rule'), str):
            raise ValueError('Wire rule must be text')
        if 'enabled' in wire and type(wire['enabled']) is not bool:
            raise ValueError('Wire enabled state must be Boolean')
        for name, _choices in _WIRE_MENUS:
            if name in wire:
                wire_choice(wire, name)
    viewport = document.get('viewport', {'x':0,'y':0,'zoom':1})
    if not isinstance(viewport, dict) or any(type(viewport.get(k)) not in (int,float) or not math.isfinite(viewport[k]) for k in ('x','y','zoom')) or not 0 < viewport['zoom'] <= 10:
        raise ValueError('Invalid session viewport')
    raw = json.dumps(document, ensure_ascii=False, allow_nan=False).encode('utf-8')
    if len(raw) > MAX_BYTES:
        raise ValueError('Session exceeds 8 MiB')
    return document


def local_path(path):
    if not isinstance(path, str) or path.startswith(('\\\\','//')) or path.upper().startswith(('FILE:','SMB:','\\\\?')):
        raise ValueError('Choose a local .archhub file')
    result = Path(path)
    if not result.is_absolute() or result.suffix.lower() != '.archhub':
        raise ValueError('Choose an absolute local .archhub path')
    resolved = result.resolve()
    if resolved.suffix.lower() != '.archhub' or str(resolved).startswith(('\\\\','//')):
        raise ValueError('Choose a local .archhub target, not a link to another file type')
    return resolved


def read_document(path):
    target = local_path(str(path))
    with _metadata_io(target.open, 'rb') as stream:
        raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError('Session exceeds 8 MiB')
    document = validate(json.loads(raw.decode('utf-8-sig')))
    properties = document.get('properties', {}) if isinstance(document, dict) else {}
    writer = properties.get('_test_writer') if isinstance(properties, dict) else None
    if isinstance(writer, dict) and writer.get('test_run_id'):
        properties.pop('_test_writer')
        if not properties and not writer.get('had_properties', False):
            document.pop('properties')
    return document


def write_document(path, document):
    target = local_path(str(path))
    validate(document)
    if writer := test_writer():
        document = {**document, 'properties': {**document.get('properties', {}),
                    '_test_writer': {**writer, 'had_properties': 'properties' in document}}}
    raw = json.dumps(document, ensure_ascii=False, indent=2, allow_nan=False).encode('utf-8')
    if len(raw) > MAX_BYTES:
        raise ValueError('Session exceeds 8 MiB')
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent, prefix='.'+target.name, suffix='.tmp', delete=False) as stream:
            temporary = stream.name
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        _metadata_io(os.replace, temporary, target)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)
    return str(target)


def checkpoint_document(document, label=None):
    """Append a non-recursive checkpoint while the caller holds this document's edit lock."""
    import copy
    from datetime import datetime, timezone
    snapshot = copy.deepcopy(document)
    props = snapshot.setdefault('properties', {})
    for key in ('checkpoints', 'history', 'revision'):
        props.pop(key, None)
    at = datetime.now(timezone.utc).isoformat()
    title = label if label is not None else 'Checkpoint ' + at
    if not isinstance(title, str) or not title.strip() or len(title) > 200:
        raise ValueError('Checkpoint label must be 1 to 200 characters')
    saved = {'id': str(uuid4()), 'title': title.strip(), 'at': at}
    document.setdefault('properties', {}).setdefault('checkpoints', []).append({**saved, 'document': snapshot})
    return saved


def checkpoint(path, label=None):
    """Keep a non-recursive document snapshot in its own portable file."""
    saved = None
    def change(document):
        nonlocal saved
        saved = checkpoint_document(document, label)

    canvas_documents.edit(path, 'You', 'save checkpoint', change, solve_changed=False)
    return saved


def restore_checkpoint(path, identity):
    """Restore content as a new revision; keep checkpoints and attributed history."""
    import copy

    def change(document):
        props = document.get('properties') or {}
        saved = next((row for row in props.get('checkpoints', []) if row.get('id') == identity), None)
        if saved is None:
            raise ValueError('No such checkpoint')
        snapshot = copy.deepcopy(validate(saved['document']))
        if snapshot['id'] != document['id']:
            raise ValueError('Checkpoint belongs to another document')
        snapshot.setdefault('properties', {}).update({key: props[key] for key in ('checkpoints', 'history', 'revision') if key in props})
        document.clear()
        document.update(snapshot)

    document, _ = canvas_documents.edit(path, 'You', 'restore checkpoint', change, solve_changed=False)
    return document


def catalogue():
    """The one library, flat: the same cards r_node_library serves, hidden compatibility rows aside."""
    from .library_engines import library_catalogue
    return [item for group in library_catalogue() for item in group['items']
            if not item.get('hidden') or item.get('id') == 'data.field']


def load_skills():
    """Saved Canvas sessions, read by the Library and reusable-node engine."""
    found = []
    for path in sorted(sessions_directory().glob('*.archhub')):
        try:
            skill = read_document(path)
        except (OSError, ValueError):
            continue
        found.append({'path': path, 'skill': skill})
    return found


def skill_template_rows():
    """Each saved skill as the Library template row. id is skill:<document id>."""
    return [{'id': 'skill:' + row['skill']['id'], 'title': row['skill']['title'], 'path': str(row['path'])}
            for row in load_skills()]


def profile_directory():
    return state_directory()


def sessions_directory():
    recover_session_move()
    owner = _folder_move_owner()
    with canvas_documents.locked(owner.path):
        _restore_folder_move(owner)
        return _selected_sessions_directory()


def _default_sessions_directory():
    from .user_paths import sessions_directory as default_sessions
    path = default_sessions()
    if os.environ.get('ARCHHUB_TEST_STATE_DIR'):
        return path
    home = path.parent.parent
    if os.name == 'nt':
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r'Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders') as key:
                documents = Path(os.path.expandvars(winreg.QueryValueEx(key, 'Personal')[0]))
            # A redirected folder may be an offline network share; compare registry paths without probing it.
            if documents != home / 'Documents':
                logging.getLogger(__name__).info('Documents is redirected; default sessions stay under the user profile')
        except OSError as error:
            logging.getLogger(__name__).debug('Documents redirection lookup unavailable: %s', error)
    return path


def _selected_sessions_directory():
    from .nograph_server import JsonFile
    settings = JsonFile(profile_directory() / 'settings' / 'settings.json', {}).read()
    path = Path(settings.get('sessionsFolder') or _default_sessions_directory())
    if not path.is_absolute() or str(path).startswith(('\\\\', '//')):
        raise ValueError('Choose an absolute local sessions folder')
    path.mkdir(parents=True, exist_ok=True)
    return path


def document_path(directory, document):
    """Readable Windows filename, without overwriting another session of the same title."""
    title = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '-', document['title']).strip(' .')[:160] or 'Untitled'
    if title.split('.')[0].upper() in {'CON', 'PRN', 'AUX', 'NUL', *('COM%d' % n for n in range(1, 10)), *('LPT%d' % n for n in range(1, 10))}:
        title = '_' + title
    path, index = Path(directory) / (title + '.archhub'), 2
    while path.exists():
        try:
            if read_document(path)['id'] == document['id']:
                return path
        except (OSError, ValueError) as error:
            logging.getLogger(__name__).debug('Existing session filename retained: %s', error)
        path = Path(directory) / ('%s (%d).archhub' % (title, index))
        index += 1
    return path


def _folder_move_owner():
    from .nograph_server import JsonFile
    return JsonFile(profile_directory() / 'data/sessions/folder-move.json', {})


def _restore_folder_move(owner):
    """An interrupted folder change rolls back before any reader selects a folder."""
    if not owner.path.exists():
        return
    from .nograph_server import JsonFile
    from .quiet_update import _cleanup_plain
    import shutil
    pending = owner.read()
    for row in reversed(pending['moves']):
        old, new = local_path(row['old']), local_path(row['new'])
        if old == new or not _cleanup_plain(old) or not _cleanup_plain(new):
            raise ValueError('Folder recovery requires distinct plain session paths')
        with canvas_documents.locked(old), canvas_documents.locked(new):
            if new.exists():
                if old.exists():
                    if old.read_bytes() != new.read_bytes():
                        raise OSError('Folder recovery conflict; both sessions retained')
                    if not row['duplicate']:
                        new.unlink()
                elif row['duplicate']:
                    with new.open('rb') as source, old.open('xb') as target:
                        shutil.copyfileobj(source, target)
                else:
                    try:
                        new.rename(old)
                    except OSError as error:
                        import errno
                        if error.errno != errno.EXDEV and getattr(error, 'winerror', None) != 17:
                            raise
                        _copy_session_across_volumes(new, old)
    with _METADATA_LOCK:
        for snapshot in pending['metadata']:
            path = profile_directory() / snapshot['path']
            if snapshot['path'] not in ('settings/settings.json', 'data/sessions/current.json', 'data/sessions/recent.json'):
                raise ValueError('Invalid folder recovery metadata')
            if snapshot['existed']:
                JsonFile(path, {}).write(snapshot['value'])
            else:
                path.unlink(missing_ok=True)
    from .workshop_tasks import relocate_sessions
    relocate_sessions(profile_directory(), [(row['new'], row['old']) for row in pending['moves']])
    owner.path.unlink()


def set_sessions_directory(target):
    """One recoverable folder change, including local current/recent pointers."""
    from .nograph_server import JsonFile
    from .quiet_update import _cleanup_plain
    import sqlite3
    target = Path(target)
    if not target.is_absolute() or str(target).startswith(('\\\\', '//')) or not _cleanup_plain(target):
        raise ValueError('Choose an absolute local sessions folder without links')
    target.mkdir(parents=True, exist_ok=True)
    owner = _folder_move_owner()
    with canvas_documents.locked(owner.path):
        _restore_folder_move(owner)
        previous = _selected_sessions_directory()
        if previous.resolve() == target.resolve():
            return []
        metadata = []
        with _METADATA_LOCK:
            for name, default in (('settings/settings.json', {}), ('data/sessions/current.json', {}), ('data/sessions/recent.json', [])):
                path = profile_directory() / name
                metadata.append({'path': name, 'existed': path.exists(), 'value': JsonFile(path, default).read()})
        pending = {'moves': [], 'metadata': metadata}
        owner.write(pending)
        def before_move(old, new):
            pending['moves'].append({'old': str(old), 'new': str(new), 'duplicate': new.exists()})
            owner.write(pending)
        try:
            moved = [(str(path), move_session(path, target, before_move=before_move)) for path in list(previous.glob('*.archhub'))]
            _relocate_pointers(profile_directory(), moved)
            settings = JsonFile(profile_directory() / 'settings/settings.json', {})
            settings.write({**settings.read(), 'sessionsFolder': str(target)})
            owner.path.unlink()
            return moved
        except (OSError, ValueError, sqlite3.Error):
            _restore_folder_move(owner)
            raise


def _relocate_pointers(state_dir, moved):
    with _METADATA_LOCK:
        from .nograph_server import JsonFile
        replacements = dict(moved)
        for name in ('recent.json', 'current.json'):
            owner = JsonFile(Path(state_dir) / 'data/sessions' / name, [] if name == 'recent.json' else {})
            value = owner.read()
            for row in value if isinstance(value, list) else [value]:
                if isinstance(row, dict) and row.get('path') in replacements:
                    row['path'] = replacements[row['path']]
            if owner.path.exists():
                owner.write(value)


def recover_session_move():
    from .nograph_server import JsonFile
    owner = JsonFile(profile_directory() / 'data/sessions/file-move.json', {})
    with canvas_documents.locked(owner.path):
        _recover_session_move(owner)


def _recover_session_move(owner):
    from .workshop_tasks import relocate_sessions
    if not owner.path.exists():
        return
    pending = owner.read()
    old, new = pending['old'], pending['new']
    from .quiet_update import _cleanup_plain
    if not _cleanup_plain(local_path(old)) or not _cleanup_plain(local_path(new)):
        raise ValueError('Session recovery requires plain local document paths')
    with canvas_documents.locked(old), canvas_documents.locked(new):
        for current, other in ((old, new), (new, old)):
            try:
                if read_document(current)['id'] == pending['id']:
                    moved = [(other, current)]
                    break
            except (OSError, ValueError):
                continue
        else:
            raise OSError('Session move recovery cannot find the original document')
        relocate_sessions(profile_directory(), moved)
        _relocate_pointers(profile_directory(), moved)
        owner.path.unlink()


def move_session(path, destination, *, before_move=None):
    """Journal the file move before publication; replay bindings before any reopen."""
    from .nograph_server import JsonFile
    import sqlite3
    owner = JsonFile(profile_directory() / 'data/sessions/file-move.json', {})
    with canvas_documents.locked(owner.path):
        _recover_session_move(owner)
        def prepare(old, new):
            if before_move:
                before_move(old, new)
            owner.write({'old': str(old), 'new': str(new), 'id': read_document(old)['id'],
                         'duplicate': new.exists()})
        try:
            result = _move_session(path, destination, before_move=prepare)
            _recover_session_move(owner)
            return result
        except (OSError, ValueError, sqlite3.Error):
            if owner.path.exists():
                pending = owner.read()
                old, new = Path(pending['old']), Path(pending['new'])
                with canvas_documents.locked(old), canvas_documents.locked(new):
                    if not old.exists() and new.exists():
                        if pending['duplicate']:
                            import shutil
                            with new.open('rb') as source, old.open('xb') as target:
                                shutil.copyfileobj(source, target)
                        else:
                            try:
                                new.rename(old)
                            except OSError as error:
                                import errno
                                if error.errno != errno.EXDEV and getattr(error, 'winerror', None) != 17:
                                    raise
                                _copy_session_across_volumes(new, old)
                _recover_session_move(owner)
            raise


def _move_session(path, destination, *, before_move=None):
    """Move one document under the same exclusion used by Canvas and agent editors."""
    from .quiet_update import _cleanup_plain, _unlocked
    path, destination = Path(path), Path(destination)
    if not _cleanup_plain(path) or not _cleanup_plain(destination):
        raise OSError('Linked session paths are retained')
    with canvas_documents.locked(path):
        document = read_document(path)
        target = document_path(destination, document)
        if path.resolve() == target.resolve():
            return str(target)
        _unlocked(path)
        with canvas_documents.locked(target):
            if target.exists():
                if target.read_bytes() == path.read_bytes():
                    if before_move:
                        before_move(path, target)
                    path.unlink()
                    return str(target)
                target = document_path(destination, {**document, 'id': str(uuid4())})
            if before_move:
                before_move(path, target)
            try:
                # Same-volume rename is atomic and does not copy a concurrently
                # edited file. Cross-volume publication uses a complete temp file.
                path.rename(target)
            except OSError as error:
                import errno
                if error.errno != errno.EXDEV and getattr(error, 'winerror', None) != 17:
                    raise
                _copy_session_across_volumes(path, target)
        return str(target)


def _copy_session_across_volumes(path, target):
    """Hold Windows write exclusion until the verified source is deleted."""
    import ctypes
    import msvcrt
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateFileW.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                  ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE)
    kernel.CreateFileW.restype = wintypes.HANDLE
    # Readers and deletion may share this handle; writers may not.
    handle = kernel.CreateFileW(str(path), 0x80000000, 5, None, 3, 0x80, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    with os.fdopen(msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY), 'rb') as original:
        raw = original.read(MAX_BYTES + 1)
        validate(json.loads(raw.decode('utf-8-sig')))
        if len(raw) > MAX_BYTES:
            raise ValueError('Session exceeds 8 MiB')
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=target.parent, suffix='.tmp', delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            temporary.rename(target)
            path.unlink()
        finally:
            if temporary:
                temporary.unlink(missing_ok=True)


def migrate_sessions(state_dir):
    """Move legacy documents byte-for-byte; unknown files and invalid documents stay put."""
    from .quiet_update import _cleanup_plain
    source = Path(state_dir) / 'sessions-files'
    if not source.is_dir() or not _cleanup_plain(source):
        return []
    destination, moved = sessions_directory(), []
    for path in [*source.glob('*.archhub'), *(source / 'skills').glob('*.archhub')]:
        try:
            if not _cleanup_plain(path) or verification_document(read_document(path)):
                continue
            target = move_session(path, destination)
            if path.resolve() != Path(target).resolve():
                moved.append((str(path), target))
        except (OSError, ValueError):
            continue
    with _METADATA_LOCK:
        for name in ('recent.json', 'current.json'):
            old = source / name
            if not old.is_file() or not _cleanup_plain(old):
                continue
            try:
                value = json.loads(old.read_text(encoding='utf-8'))
                replacements = dict(moved)
                def update(row):
                    if isinstance(row, dict) and row.get('path') in replacements:
                        row['path'] = replacements[row['path']]
                    return row
                if isinstance(value, list):
                    value = [update(row) for row in value]
                else:
                    if not value.get('path') and value.get('id'):
                        value['path'] = str(source / (value['id'] + '.archhub'))
                    update(value)
                from .nograph_server import JsonFile
                target = Path(state_dir) / 'data' / 'sessions' / name
                if not target.exists():
                    JsonFile(target, {}).write(value)
                if JsonFile(target, {}).read() == strip_test_write(value):
                    old.unlink()
            except (OSError, ValueError, AttributeError):
                continue
    try:
        (source / 'skills').rmdir()
    except OSError as error:
        logging.getLogger(__name__).debug('Legacy session directory retained: %s', error)
    try:
        source.rmdir()
    except OSError as error:
        logging.getLogger(__name__).debug('Legacy session directory retained: %s', error)
    return moved


def verification_document(document):
    return document.get('title', '').strip().casefold() in {
        'archhub interface verification a', 'archhub interface verification b', 'ui verification'}


def skill_ports(skill, items=()):
    """A skill's sockets come from its inner workflow: each unbound Parameter node is a typed input
    ('in:<node>'), each output of a node nothing inside reads is a typed output ('out:<node>:<socket>').
    'out' (the last node's values) stays for skills placed before typed sockets existed."""
    from .node_params import PARAM_ENGINE, ports as node_ports, socket_type
    known = {item['id']: item for item in items}
    read = {w['from']['node'] for w in skill['wires']}
    target = [{'id': 'in:' + n['id'], 'type': socket_type(n['params'].get('type')), 'label': n.get('title') or 'Input'}
              for n in skill['nodes'] if n['type'] in (PARAM_ENGINE, 'thing.session') and not n.get('bind')]
    source = [{'id': 'out', 'type': 'any', 'label': 'Result'}]
    for n in skill['nodes']:
        if n['id'] in read or n['type'] in (PARAM_ENGINE, 'note'):
            continue
        entry = known.get(n.get('item')) or next((i for i in known.values() if i['engine'] == n['type']), None) or {}
        for port in node_ports(n, entry.get('ports') or {})['source']:
            source.append({'id': 'out:%s:%s' % (n['id'], port['id']), 'type': port.get('type', 'any'),
                           'label': '%s · %s' % (n.get('title') or n['type'], port.get('label') or port['id'])})
    for side, ports in (('source', source), ('target', target)):
        for port in skill.get('properties', {}).get('sessionPorts', {}).get(side, []):
            if not any(p['id'] == port['id'] for p in ports):
                ports.append(dict(port))
    return {'source': source, 'target': target}


def node_type_document(document, ids, name, category='Scripts', public=(), kind=None):
    """Extract one reusable file; the source task and its private metadata stay put."""
    from .agent_work import redact
    document = validate(copy.deepcopy(document))
    if not isinstance(ids, list) or not ids or not isinstance(name, str) or not name.strip():
        raise ValueError('Choose nodes and name the node type.')
    selected = set(ids)
    by_id = {n['id']: n for n in document['nodes']}
    if any(key not in by_id or by_id[key].get('fixed') for key in selected):
        raise ValueError('Choose editable nodes for the node type.')
    pending = list(selected)
    while pending:
        node = by_id[pending.pop()]
        for child in [*node.get('children', []), *node.get('frameMembers', [])]:
            if child not in selected:
                selected.add(child)
                pending.append(child)
    saved = new_document(name.strip())
    saved['nodes'] = [n for n in document['nodes'] if n['id'] in selected]
    saved['wires'] = [w for w in document['wires'] if w['from']['node'] in selected and w['to']['node'] in selected]
    saved['groups'] = [g for g in document['groups'] if g['id'] in selected]
    for node in saved['nodes']:
        node.pop('result', None)
        node.pop('agentWork', None)
        if node.get('parent') not in selected:
            node.pop('parent', None)
    if redact(saved) != saved:
        raise ValueError('Remove credentials before saving. Nothing was saved.')
    ports = skill_ports(saved, catalogue())
    public_parameters = []
    for item in public:
        if not isinstance(item, dict) or item.get('node') not in selected:
            raise ValueError('Public parameter must belong to the selected nodes.')
        node, key = by_id[item['node']], item.get('key')
        definition = next((p for p in node.get('paramDefs', []) if p['id'] == key), None)
        if definition is None or key not in node['params']:
            raise ValueError('Choose a declared public parameter.')
        socket = 'in:' + node['id'] + ':param:' + key
        ports['target'].append({'id': socket, 'label': definition.get('name', key), 'type': definition['type']})
        public_parameters.append({'node': node['id'], 'key': key, 'socket': socket, 'definition': definition, 'value': node['params'][key]})
    for wire in document['wires']:
        if wire['from']['node'] not in selected and wire['to']['node'] in selected:
            target = wire['to']
            socket = 'in:' + target['node'] + ':' + target['socket']
            if not any(p['id'] == socket for p in ports['target']):
                ports['target'].append({'id': socket, 'label': target['socket'], 'type': 'any'})
        if wire['from']['node'] in selected and wire['to']['node'] not in selected:
            source = wire['from']
            socket = 'out:' + source['node'] + ':' + source['socket']
            if not any(p['id'] == socket for p in ports['source']):
                ports['source'].append({'id': socket, 'label': source['socket'], 'type': 'any'})
    pure = all(canvas_documents.is_pure(n['type'], n['params']) for n in saved['nodes'])
    if kind not in (None, 'pure', 'effect') or kind == 'pure' and not pure:
        raise ValueError('This definition contains effects and cannot be saved as Pure.')
    saved['properties'] = {'nodeType': {'category': str(category)[:80], 'public': public_parameters, 'kind': kind or ('pure' if pure else 'effect')}, 'sessionPorts': ports}
    validate(saved)
    return saved


def run_skill(params, *, invoke, stopped, depth, feeds=None, parent=None):
    if depth > 8:
        raise ValueError('Skills nest at most 8 deep')
    name = str(params.get('skill',''))
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', name):
        raise ValueError('Skill id is invalid')
    from .node_params import PARAM_ENGINE, coerce
    path = params.get('session_file')
    if path:
        path, skill = linked_session(params)
    else:
        saved = next((row for row in load_skills() if row['skill']['id'] == name), None)
        path, skill = (str(saved['path']), saved['skill']) if saved else (None, None)
    if skill is None:
        raise ValueError('Saved session is unavailable')
    source = copy.deepcopy(skill)
    original = {n['id']: dict(n['params']) for n in skill['nodes']}
    inputs = {n['id']: n for n in skill['nodes'] if n['type'] in (PARAM_ENGINE, 'thing.session') and not n.get('bind')}
    feeds = dict(feeds or {})
    for index, entry in enumerate(skill.get('properties', {}).get('nodeType', {}).get('public', [])):
        key = 'public_' + str(index)
        feeds[entry['socket']] = feeds.pop(key, params.get(key, entry['value']))
    for socket, value in feeds.items():
        held = inputs.get(str(socket)[3:]) if str(socket).startswith('in:') else None
        if held is None:
            endpoint = []
            for node in skill['nodes']:
                prefix = 'in:' + node['id'] + ':'
                if str(socket).startswith(prefix):
                    endpoint = [node['id'], str(socket)[len(prefix):]]
                    break
            if len(endpoint) != 2 or not any(n['id'] == endpoint[0] for n in skill['nodes']):
                raise ValueError('This skill has no input %s' % socket)
            identity = 'input-' + hashlib.sha256(str(socket).encode()).hexdigest()[:24]
            skill['nodes'].append({'id': identity, 'type': PARAM_ENGINE, 'params': {'type': 'json', 'value': value}, 'position': {'x': 0, 'y': 0}})
            skill['wires'] = [w for w in skill['wires'] if w['to'] != {'node': endpoint[0], 'socket': endpoint[1]}]
            skill['wires'].append({'id': identity, 'from': {'node': identity, 'socket': 'value'}, 'to': {'node': endpoint[0], 'socket': endpoint[1]}})
            continue
        held['params']['value'] = coerce(held['params'].get('type', 'json'), value)   # a wired value sets the inner Parameter
    inner = run_document(skill, invoke=invoke, stopped=stopped, depth=depth+1, path=path,
                         _source=source, _parent=parent)
    if path and source.get('properties', {}).get('nodeType', {}).get('kind') != 'pure':
        def record(document):
            for node in document['nodes']:
                if node['id'] in inner['results'] and node['params'] == original.get(node['id']):
                    node['result'] = inner['results'][node['id']]
            return []
        canvas_documents.edit(path, 'Session', 'called by ' + str(params.get('called_by') or 'canvas'), record, solve_changed=False, always_record=True)
    if inner.get('approvalId'):
        return {'approvalId': inner['approvalId']}, 'Waiting for approval'
    if not inner['succeeded']:
        raise ValueError('Skill failed: '+'; '.join(r.get('error','') for r in inner['results'].values() if r.get('error')))
    return skill_result(inner)


def skill_result(inner):
    last = inner['results'][inner['order'][-1]]['output'] if inner['order'] else {}
    produced = {'out': last}
    for key, result in inner['results'].items():
        for socket, value in (result.get('output') or {}).items():
            produced['out:%s:%s' % (key, socket)] = value
    return produced, 'Skill ran %d nodes' % len(inner['order'])


def linked_session(params):
    """Follow identity across APPTIDY renames; never execute a replacement at an old path."""
    path = local_path(params.get('session_file'))
    try:
        document = read_document(path)
    except FileNotFoundError:
        matches = [row for row in load_skills() if row['skill']['id'] == params.get('skill')]
        if len(matches) != 1:
            raise ValueError('Linked session is missing or ambiguous')
        path, document = matches[0]['path'], matches[0]['skill']
    if document['id'] != params.get('skill'):
        raise ValueError('Linked session identity changed')
    return str(path), document


def check_session_links(document, ancestors=frozenset(), visited=None):
    """Refuse linked recursion before any effect, including files changed since placement."""
    visited = set() if visited is None else visited
    if document['id'] in ancestors:
        raise ValueError('Cycle detected in linked sessions')
    if len(ancestors) > 8 or len(visited) > 128:
        raise ValueError('Linked sessions exceed 8 levels or 128 files')
    if document['id'] in visited:
        return
    for node in document['nodes']:
        if node['type'] == 'skill' and node['params'].get('session_file'):
            check_session_links(linked_session(node['params'])[1], ancestors | {document['id']}, visited)
    visited.add(document['id'])


def insert_session(document, path, x=80, y=100):
    """One linked group; the referenced document remains the owner of its graph."""
    from uuid import uuid4
    document = validate(document)
    path = local_path(path)
    child = read_document(path)
    check_session_links(child, {document['id']})
    node = {'id': str(uuid4()), 'type': 'skill', 'title': child['title'], 'children': [],
            'params': {'skill': child['id'], 'session_file': str(path)},
            'ports': skill_ports(child, catalogue()), 'position': {'x': x, 'y': y}}
    item = next((row for row in catalogue() if row['id'] == 'skill:' + child['id']), None)
    if item:
        node.update(item=item['id'], params=copy.deepcopy(item['params']), ports=copy.deepcopy(item['ports']),
                    paramDefs=copy.deepcopy(item.get('paramDefs', [])))
        node.update(canvas_documents.node_contract('skill'))
        node['pure'] = canvas_documents.is_pure('skill', item['params'])
        node['approvalRequired'] = child.get('properties', {}).get('nodeType', {}).get('kind') == 'effect'
    document['nodes'].append(node)
    return node


def split_sessions(path):
    """Replace legacy session islands with references, retaining the source in Undo."""
    import copy
    path = local_path(path)
    saved = []
    source = read_document(path)
    if source.get('properties', {}).get('taskContext') or source.get('properties', {}).get('sessionMigration') == 1 or sum(
            n.get('agentWork', {}).get('role') == 'session' or n['type'] == 'thing.agent' and bool(n['params'].get('session'))
            for n in source['nodes']) < 2:
        return saved
    recovery = checkpoint(path, 'Before splitting task sessions')
    def split(document):
        document.setdefault('properties', {})['sessionMigration'] = 1
        snapshot = next(row['document'] for row in document['properties']['checkpoints'] if row['id'] == recovery['id'])
        snapshot.setdefault('properties', {})['sessionMigration'] = 1
        sessions = [n for n in document['nodes'] if n.get('agentWork', {}).get('role') == 'session'
                    or n['type'] == 'thing.agent' and n['params'].get('session')]
        if len(sessions) < 2:
            return []
        ownership = {}
        for session in sessions:
            ownership[session['id']] = session['id']
        changed = True
        while changed:
            changed = False
            for node in document['nodes']:
                owner = ownership.get(node.get('agentWork', {}).get('owner') or node.get('parent'))
                if owner and node['id'] not in ownership:
                    ownership[node['id']] = owner
                    changed = True
        replacements, crossings = {}, []
        for session in sessions:
            ids = {key for key, owner in ownership.items() if owner == session['id']}
            child = new_document(session.get('title') or 'Session')
            child['id'] = 'session-' + hashlib.sha256((document['id'] + '\0' + session['id']).encode()).hexdigest()[:32]
            child['nodes'] = copy.deepcopy([n for n in document['nodes'] if n['id'] in ids])
            for node in child['nodes']:
                if node.get('parent') not in ids:
                    node.pop('parent', None)
            child['wires'] = copy.deepcopy([w for w in document['wires'] if w['from']['node'] in ids and w['to']['node'] in ids])
            child['groups'] = [copy.deepcopy(g) for g in document['groups'] if g['id'] in ids and set(g['nodes']) <= ids]
            ports = skill_ports(child, catalogue())
            for wire in document['wires']:
                for side, other, direction in (('from', 'to', 'source'), ('to', 'from', 'target')):
                    if wire[side]['node'] in ids and wire[other]['node'] not in ids:
                        endpoint = wire[side]
                        socket = ('out:' if side == 'from' else 'in:') + endpoint['node'] + ':' + endpoint['socket']
                        if not any(p['id'] == socket for p in ports[direction]):
                            ports[direction].append({'id': socket, 'type': 'any', 'label': endpoint['socket']})
            child.setdefault('properties', {})['sessionPorts'] = ports
            target = document_path(path.parent, child)
            if target.exists():
                existing = read_document(target)
                if existing['nodes'] != child['nodes'] or existing['wires'] != child['wires']:
                    raise ValueError('Migration destination contains different work')
            else:
                write_document(target, child)
            group = {'id': session['id'], 'type': 'skill', 'title': child['title'], 'children': [],
                     'params': {'skill': child['id'], 'session_file': str(target)},
                     'position': dict(session['position']), 'ports': ports}
            replacements[session['id']] = group
            saved.append(str(target))
        for wire in document['wires']:
            a, b = ownership.get(wire['from']['node']), ownership.get(wire['to']['node'])
            if a and a == b:
                continue
            wire = copy.deepcopy(wire)
            for side, owner in (('from', a), ('to', b)):
                if owner:
                    endpoint = wire[side]
                    socket = ('out:' if side == 'from' else 'in:') + endpoint['node'] + ':' + endpoint['socket']
                    ports = replacements[owner]['ports']['source' if side == 'from' else 'target']
                    if not any(p['id'] == socket for p in ports):
                        ports.append({'id': socket, 'type': 'any', 'label': endpoint['socket']})
                    wire[side] = {'node': owner, 'socket': socket}
            crossings.append(wire)
        document['nodes'] = [replacements[n['id']] if n['id'] in replacements else n for n in document['nodes']
                             if n['id'] not in ownership or n['id'] in replacements]
        document['wires'] = crossings
        document['groups'] = [{**g, 'nodes': list(dict.fromkeys(ownership.get(n, n) for n in g['nodes']))}
                              for g in document['groups'] if g['id'] not in ownership]
        for node in document['nodes']:
            if node.get('children'):
                node['children'] = list(dict.fromkeys(ownership.get(n, n) for n in node['children']))
        return []
    canvas_documents.edit(path, 'Migration', 'split task sessions (Undo restores shared canvas)', split, solve_changed=False)
    return saved


def run_document(document, *, invoke=None, roots=None, stopped=None, depth=0, plan_only=False, cached=(), only=None, path=None, _resume=None, _each=None, _source=None, _parent=None):
    """Validate the whole plan before invoking existing engines in wire order."""
    from collections import deque
    from .library_engines import STEM_RUN_ENGINES
    from .pipeline_engines import PIPELINE_ENGINES
    from .stem_graph_evaluation import longest_each_plans, collect_each_runs, each_fault
    validate(document)
    if not plan_only and only is None:
        check_session_links(document)
    nodes = {n['id']: n for n in document['nodes']}
    incoming = {key: [] for key in nodes}
    outgoing = {key: [] for key in nodes}
    known = {row['id']: row for row in catalogue()}
    for wire in document['wires']:
        if wire.get('inferred') or wire.get('enabled') is False:
            continue
        incoming[wire['to']['node']].append(wire)
        outgoing[wire['from']['node']].append(wire)
    selected = set(nodes)
    if roots:
        if any(root not in nodes for root in roots):
            raise ValueError('Run target is absent')
        selected = set(roots)
        pending = list(roots)
        while pending:
            for wire in incoming[pending.pop()]:
                source = wire['from']['node']
                if source not in selected:
                    selected.add(source)
                    pending.append(source)
    degrees = {key: len(incoming[key]) for key in selected}
    queue = deque(key for key in nodes if key in selected and degrees[key] == 0)
    order = []
    while queue:
        key = queue.popleft()
        order.append(key)
        for wire in outgoing[key]:
            target = wire['to']['node']
            if target in degrees:
                degrees[target] -= 1
                if degrees[target] == 0:
                    queue.append(target)
    if len(order) != len(selected):
        raise ValueError('Cycle detected: disconnect a feedback wire before Run')
    if plan_only:
        return {'ok': True, 'order': order}
    from .canvas_documents import THING_ENGINES
    from .node_params import PARAM_ENGINE, ports as node_ports
    for key in order:
        node = nodes[key]
        if node.get('agentWork', {}).get('role') == 'session':
            continue
        engine = node['type']
        if engine not in PIPELINE_ENGINES and engine not in STEM_RUN_ENGINES and engine not in ('note', 'skill', PARAM_ENGINE, 'data.dataset', 'data.field') and engine not in THING_ENGINES:
            raise ValueError('Missing engine: '+engine)
        entry = known.get(node.get('item')) or next((r for r in known.values() if r['engine'] == engine), None)
        if entry and entry['engine'] != engine:
            raise ValueError('Library item and engine disagree')
        if entry:
            for side, wires, end in [('source', outgoing[key], 'from'), ('target', incoming[key], 'to')]:
                base = node.get('ports') if engine in ('skill', 'script.python') else None
                sockets = {p['id'] for p in node_ports(node, base or entry['ports'])[side]}
                if any(wire[end]['socket'] not in sockets for wire in wires):
                    raise ValueError('Unknown socket on '+node.get('title',key))
    results = copy.deepcopy(_resume or {})
    outputs = {key: value.get('output', {}) for key, value in results.items() if value.get('status') in ('Done', 'Solved', 'Skipped')}
    for key in order:
        if key in results:
            continue
        if stopped is not None and stopped():
            for pending_key in order:
                if pending_key not in results:
                    results[pending_key] = {'status':'Stopped','output':{},'error':'Stopped by you.'}
            break
        node = nodes[key]
        if only is not None and key not in only:
            # A solve reuses the outputs upstream nodes already show; it never re-runs them.
            held = node.get('result') or {}
            if held.get('status') in ('Done', 'Solved') and key not in cached:
                outputs[key] = held.get('output', {})
            continue
        if node.get('frozen'):
            results[key] = {'status':'Disabled', 'output':{}}
            continue
        # A branch If/Switch did not take, and everything only it feeds, is Skipped, not an error.
        untaken = [w for w in incoming[key] if results.get(w['from']['node'], {}).get('status') == 'Skipped' or (
            nodes[w['from']['node']]['type'] in ('control.if', 'control.switch') and w['from']['node'] in outputs
            and w['from']['socket'] not in outputs[w['from']['node']])]
        # A Merge takes whichever branch arrived; it is Skipped only when none did.
        if untaken and (node['type'] != 'control.merge' or len(untaken) == len(incoming[key])):
            results[key] = {'status': 'Skipped', 'output': {}}
            continue
        wired = [w for w in incoming[key] if w not in untaken]
        blocked = next((w['from']['node'] for w in wired if w['from']['node'] not in outputs), None)
        if blocked:
            results[key] = {'status':'Blocked', 'output':{}, 'error':'Upstream node did not produce output'}
            continue
        if node.get('bypassed'):
            values = [outputs[w['from']['node']][w['from']['socket']] for w in wired]
            ports = node_ports(node, (known.get(node.get('item')) or {}).get('ports', {}))['source']
            if len(values) != 1 or not ports or len({p.get('type', 'any') for p in ports}) != 1:
                results[key] = {'status': 'Error', 'output': {}, 'error': 'Bypass needs one connected input and outputs of one type.'}
                continue
            outputs[key] = {p['id']: values[0] for p in ports}
            results[key] = {'status': 'Skipped', 'output': outputs[key]}
            continue
        engine = node['type']
        started = time.perf_counter()
        try:
            if node.get('agentWork', {}).get('role') == 'session':
                outputs[key] = {'result': node['params'].get('result', '')}
                results[key] = {'status': 'Skipped', 'output': outputs[key]}
                continue
            shaped, streams = _split_each_wires(wired, nodes, outputs, engine, key)
            _match_feeds(shaped)
            constants = {}
            for _wire, socket_name, value in shaped:
                constants[socket_name] = value
            plans = longest_each_plans(streams, constants)

            each_state = None
            def run_once(plan):
                params, bound = _params_and_feeds(node, engine, dict(plan))
                return _dispatch_node(
                    document, node, engine, params, bound,
                    invoke=invoke, stopped=stopped, depth=depth,
                    continuation={'document': document, 'source': _source or document, 'roots': roots, 'completed': results,
                                  'path': str(path), 'each': each_state, 'parent': _parent, 'depth': depth} if path else None)

            if plans is None:
                produced, display = run_once(constants)
                if node.get('agentWork') or node.get('approvalRequired'):
                    from .agent_work import redact
                    produced, display = redact(produced), redact(display)
                json.dumps(produced, allow_nan=False)
                outputs[key] = produced
                results[key] = {'status':'Done', 'output':produced, 'display':display, 'elapsed_ms': round((time.perf_counter() - started) * 1000, 2)}
                if isinstance(produced, dict) and produced.get('approvalId'):
                    results[key]['status'] = 'Waiting for approval'
                    for pending_key in order:
                        if pending_key not in results:
                            results[pending_key] = {'status': 'Waiting', 'output': {}, 'error': 'Waiting for approval before continuing.'}
                    return {'ok': True, 'succeeded': False, 'results': results, 'order': order, 'approvalId': produced['approvalId']}
            else:
                # foreach.each: one run per item. decide() stays inside the effect.
                held_each = (_each or {}).get(key)
                rows = copy.deepcopy(held_each['rows']) if held_each else []
                plans = held_each['remaining'] if held_each else list(plans)
                for index, plan in enumerate(plans):
                    if stopped is not None and stopped():
                        rows.append((None, None, 'Stopped by you.'))
                        continue
                    try:
                        each_state = {'rows': rows, 'remaining': plans[index+1:]}
                        produced, display = run_once(plan)
                        if isinstance(produced, dict) and produced.get('approvalId'):
                            results[key] = {'status': 'Waiting for approval', 'output': produced, 'display': display}
                            for pending_key in order:
                                if pending_key not in results:
                                    results[pending_key] = {'status': 'Waiting', 'output': {}, 'error': 'Waiting for approval before continuing.'}
                            return {'ok': True, 'succeeded': False, 'results': results, 'order': order, 'approvalId': produced['approvalId']}
                        json.dumps(produced, allow_nan=False)
                        rows.append((produced, display, each_fault(produced, display)))
                    except Exception as error:
                        rows.append((None, None, str(error)))
                entry = known.get(node.get('item')) or next(
                    (r for r in known.values() if r.get('engine') == engine), None)
                names = [
                    p['id'] for p in node_ports(node, (entry or {}).get('ports') or {}).get('source') or []
                    if isinstance(p, dict) and p.get('id')]
                output, shown, error = collect_each_runs(rows, names)
                outputs[key] = output
                held_result = {'status': 'Error' if error else 'Done', 'output': output, 'display': shown}
                if error:
                    held_result['error'] = error
                results[key] = held_result
        except Exception as error:
            results[key] = {'status':'Error', 'output':{}, 'error':str(error), 'elapsed_ms': round((time.perf_counter() - started) * 1000, 2)}
    return {'ok':True, 'succeeded':all(r['status'] in ('Done','Disabled','Skipped') for r in results.values()), 'results':results, 'order':order}


class SessionFiles:
    """Files are data; recent paths and crash recovery remain local to the profile."""
    def __init__(self, directory=None):
        self.directory = Path(directory) if directory else sessions_directory()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.metadata = Path(directory) if directory else profile_directory() / 'data' / 'sessions'
        self.metadata.mkdir(parents=True, exist_ok=True)

    def _recent(self):
        path = self.metadata/'recent.json'
        try:
            rows = strip_test_write(json.loads(_metadata_io(path.read_text, encoding='utf-8')))
        except FileNotFoundError:
            return []
        if not isinstance(rows, list):
            raise ValueError('Recent session list is invalid')
        return rows

    def recent(self):
        with _METADATA_LOCK, canvas_documents.locked(self.metadata/'recent.json'):
            return self._recent()

    def remember(self, path, document):
        with _METADATA_LOCK, canvas_documents.locked(self.metadata/'recent.json'):
            rows = [{'id':str(path), 'path':str(path), 'name':document['title'], 'title':document['title']}] + [r for r in self._recent() if r['path'] != str(path)]
            target = self.metadata/'recent.json'
            with tempfile.NamedTemporaryFile(dir=self.metadata, suffix='.tmp', delete=False, mode='w', encoding='utf-8') as stream:
                temporary = stream.name
                json.dump(stamp_test_write(rows[:20]),stream)
            try:
                _metadata_io(os.replace, temporary, target)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)

    def _current(self, identity, path):
        with _METADATA_LOCK:
            current = self.metadata/'current.json'
            with tempfile.NamedTemporaryFile(dir=self.metadata, suffix='.tmp', delete=False, mode='w', encoding='utf-8') as stream:
                temporary = stream.name
                json.dump(stamp_test_write({'id':identity,'path':str(local_path(path)) if path else ''}),stream)
            try:
                _metadata_io(os.replace, temporary, current)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)

    def current_path(self):
        """The file the founder has open. Every reader asks here; none of them writes this choice."""
        for row in self.open_files():
            if row.get('open_in_app') and isinstance(row.get('path'), str):
                return row['path']
        return ''

    def open_files(self):
        """The file the app has open now (agents edit the same file), then recent files."""
        with _METADATA_LOCK:
            rows = []
            current = self.metadata/'current.json'
            if current.exists():
                held = json.loads(current.read_text(encoding='utf-8'))
                path = held.get('path') or str(self.directory/(held['id']+'.archhub'))
                rows.append({'path':path,'open_in_app':True})
            rows += [{'path':r['path'],'open_in_app':False,'title':r.get('title','')} for r in self.recent() if r['path'] not in {x['path'] for x in rows}]
            return rows

    def import_file(self, path):
        """A Node-RED/Langflow .json flow opens as a new .archhub beside the session files; a SKILL.md
        becomes a Library skill. Re-importing the same source updates its nodes in place."""
        from .flow_import import import_text, reimport
        source = Path(str(path))
        if not source.is_absolute() or not source.is_file() or source.suffix.lower() not in ('.json', '.md'):
            raise ValueError('Choose a local Node-RED or Langflow .json flow, or a SKILL.md file')
        with source.open('rb') as stream:
            raw = stream.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ValueError('Imported file exceeds 8 MiB')
        kind, imported = import_text(raw.decode('utf-8-sig'), source.name)
        if kind != 'skill':
            imported['id'] = 'import-' + hashlib.sha1(str(source.resolve()).lower().encode()).hexdigest()[:16]
        target = document_path(self.directory, imported)
        with canvas_documents.locked(target):
            existing = read_document(target) if target.exists() else None
            document = reimport(existing, imported)
            canvas_documents._stamp(document, existing, 'Import', 'import ' + source.name)
            write_document(target, document)
        self.remember(target, document)
        return {'ok':True,'document':document,'path':str(target),'kind':kind}

    def dispatch(self, body, *, invoke=None, picker=None, save_picker=None, stopped=None):
        if not isinstance(body,dict) or not isinstance(body.get('action'),str):
            raise ValueError('Session file action is required')
        action = body['action']
        if action == 'resolve-session':
            path, document = linked_session(body.get('params') or {})
            return {'ok': True, 'path': path, 'document': document}
        if action == 'detach-session':
            document = validate(body.get('document'))
            node = next((n for n in document['nodes'] if n['id'] == body.get('node')), None)
            if not node or node['type'] != 'skill' or not node['params'].get('session_file'):
                raise ValueError('Choose a linked session group')
            _, child = linked_session(node['params'])
            child['id'], child['title'] = str(uuid4()), child['title'] + ' copy'
            for key in ('taskContext', 'history', 'revision', 'checkpoints'):
                child.get('properties', {}).pop(key, None)
            check_session_links(child, {document['id']})
            path = write_document(document_path(self.directory, child), child)
            node['params'] = {'skill': child['id'], 'session_file': path}
            node['title'], node['ports'] = child['title'], skill_ports(child, catalogue())
            return {'ok': True, 'document': document, 'path': path}
        if action == 'insert-session':
            document = validate(body.get('document'))
            node = insert_session(document, body.get('session'), body.get('x', 80), body.get('y', 100))
            return {'ok': True, 'document': validate(document), 'node': node['id']}
        if action == 'split-sessions':
            return {'ok': True, 'sessions': split_sessions(body.get('path'))}
        if action == 'add-automation':
            identity = str(uuid4())
            trigger = body.get('trigger', 'manual')
            if trigger not in ('manual', 'schedule', 'file-change', 'host-event'):
                raise ValueError('Choose a supported trigger')
            item_id = {'manual': 'tr_manual', 'schedule': 'tr_schedule', 'file-change': 'tr_file', 'host-event': 'tr_host'}[trigger]
            item = next(i for i in catalogue() if i['id'] == item_id)
            def automate(document):
                target = next((n for n in document['nodes'] if n['id'] == 'start'), None)
                if target is None:
                    raise ValueError('Choose a task session with a Start input')
                document['nodes'].append({'id': identity, 'type': item['engine'], 'item': item['id'], 'title': item['title'],
                    'params': dict(item['params']), 'position': {'x': target['position']['x'] - 300, 'y': target['position']['y']}})
                document['wires'] = [w for w in document['wires'] if w['to'] != {'node': target['id'], 'socket': 'value'}]
                document['wires'].append({'id': 'trigger-' + identity, 'from': {'node': identity, 'socket': 'fire'},
                                          'to': {'node': target['id'], 'socket': 'value'}})
                return [identity]
            document, _ = canvas_documents.edit(local_path(body.get('path')), 'You', 'add automation trigger', automate)
            return {'ok': True, 'document': document, 'node': identity}
        if action in ('open', 'initial'):
            from .enforce import guard_effect
            invoke = invoke or guard_effect
        if action == 'catalogue':
            return {'ok':True,'items':catalogue(),'recent':self.recent(),'directory':str(self.directory),
                    'sessions':[{'id':row['skill']['id'], 'title':row['skill']['title'], 'path':str(row['path'])} for row in load_skills()]}
        if action == 'initial':
            import sys
            launch = next((a for a in sys.argv[1:] if str(a).lower().endswith('.archhub')), None)
            current = self.metadata/'current.json'
            with _METADATA_LOCK:
                held = json.loads(current.read_text(encoding='utf-8')) if current.exists() else {}
            recovery = Path(held['path']) if held.get('path') else self.directory/(held['id']+'.archhub') if held else self.directory/'autosave.archhub'
            selected_path = Path(launch) if launch else recovery
            before_migration = read_document(selected_path) if selected_path.exists() else None
            migrated = split_sessions(str(selected_path)) if before_migration else []
            if migrated:
                before_migration.setdefault('properties', {})['sessionMigration'] = 1
            document = read_document(selected_path) if before_migration else new_document()
            return {'ok':True,'document':document,'path':str(launch or held.get('path', '')),
                    **({'migrationDocument': before_migration} if migrated else {})}
        if action == 'starter':
            # A built-in starter becomes the founder's own new session file (the starter itself never changes).
            from .starters import document as starter_document
            document = starter_document(str(body.get('id') or ''))
            path = write_document(document_path(self.directory, document), document)
            canvas_documents.remember(path, document)
            self.remember(path, document)
            self._current(document['id'], path)
            return {'ok':True,'document':document,'path':str(path)}
        if action == 'open':
            path = body.get('path')
            if not path and picker:
                path = picker('Open session','ArchHub session, Node-RED or Langflow flow, skills.sh skill (*.archhub *.json SKILL.md)')
            if not path:
                return {'ok':True,'cancelled':True}
            if not str(path).lower().endswith('.archhub'):
                return self.import_file(path)
            before_migration = read_document(path)
            migrated = split_sessions(path)
            if migrated:
                before_migration.setdefault('properties', {})['sessionMigration'] = 1
            document = read_document(path)
            self.remember(local_path(path),document)
            self._current(document['id'], path)
            return {'ok':True,'document':document,'path':str(local_path(path)),
                    **({'migrationDocument': before_migration} if migrated else {})}
        if action in ('save','autosave'):
            document = validate(body.get('document'))
            if not re.fullmatch(r'[A-Za-z0-9_-]{1,128}',document['id']):
                raise ValueError('Session id must be a portable filename identifier')
            if action == 'autosave':
                # Autosave is in place: the open file IS the document agents edit too.
                from .canvas_documents import commit_ui
                path = str(local_path(body['path'])) if body.get('path') else str(document_path(self.directory, document))
                merged = commit_ui(path, document, int(body.get('base_revision') or 0))
                # APPTIDY owns names only in Sessions; external filenames belong to the user.
                renamed = move_session(path, Path(path).parent) if Path(path).parent == self.directory.resolve() else path
                if renamed != path:
                    _relocate_pointers(profile_directory(), [(path, renamed)])
                    path = renamed
                    canvas_documents.remember(path, merged)
                self._current(document['id'], path)
                return {'ok':True,'path':path,'document':merged,'revision':merged.get('properties',{}).get('revision',0)}
            path = body.get('path')
            if not path and body.get('save_as') and save_picker:
                path = save_picker('Save session','ArchHub session (*.archhub)',str(document_path(self.directory, document)))
                if not path:
                    return {'ok':True,'cancelled':True}
            elif not path:
                path = str(document_path(self.directory, document))
            if not path:
                return {'ok':True,'cancelled':True}
            if body.get('save_as'):
                document = {**document, 'title': Path(path).stem}
            path = write_document(path,document)
            canvas_documents.remember(path, document)
            self.remember(path,document)
            self._current(document['id'], path)
            return {'ok':True,'path':path,'document':document}
        if action == 'save-skill':
            document = validate(body.get('document'))
            if not re.fullmatch(r'[A-Za-z0-9_-]{1,128}',document['id']):
                raise ValueError('Skill id must be a portable filename identifier')
            return self.dispatch({'action':'save', 'document':document, **({'path': body['path']} if body.get('path') else {})})
        if action in ('scan-node-type', 'save-node-type'):
            document = node_type_document(body.get('document'), body.get('ids'), body.get('name'),
                                          body.get('category', 'Scripts'), body.get('public', []), body.get('kind'))
            if action == 'scan-node-type':
                return {'ok': True, 'pure': all(canvas_documents.is_pure(n['type'], n['params']) for n in document['nodes']),
                        'paths': bool(re.search(r'(?:[A-Za-z]:[\\/]|/Users/|/home/)', json.dumps(document)))}
            return self.dispatch({'action': 'save-skill', 'document': document})
        if action == 'param-op':
            # One implementation of typed parameters for the window and the agents (node_params.py).
            from . import node_params
            document = validate(body.get('document'))
            operations = {'add': node_params.add_param, 'promote': node_params.promote,
                          'demote': node_params.demote, 'set': node_params.set_value}
            operation = operations.get(body.get('op'))
            if operation is None or not isinstance(body.get('args'), list):
                raise ValueError('Parameter operation must be add, promote, demote or set')
            args = body['args']
            if body['op'] == 'add':
                options = dict(args[4]) if len(args) > 4 and isinstance(args[4], dict) else {}
                show = options.pop('show_as_node', False)
                changed = operation(document, *args[:4], **options)
                if show:  # "Show as node" in the add form: expose at once
                    owner = next(n for n in document['nodes'] if n['id'] == changed[0])
                    changed = node_params.promote(document, owner['id'], owner['paramDefs'][-1]['id'])
            else:
                changed = operation(document, *args)
            return {'ok': True, 'document': validate(document), 'changed': changed}
        if action == 'wire-rule':
            document = validate(body.get('document'))
            return {'ok': True, 'rule': wire_rule(document, body.get('id'), body.get('rule'))}
        if action == 'dataset-op':
            # One implementation of fields, records and cells for the window and the agents (node_datasets.py).
            from . import node_datasets
            document = validate(body.get('document'))
            operations = {'new': node_datasets.new_dataset, 'add-field': node_datasets.add_field,
                          'add-record': node_datasets.add_record, 'set-cell': node_datasets.set_cell,
                          'expose-field': node_datasets.expose_field}
            operation = operations.get(body.get('op'))
            if operation is None or not isinstance(body.get('args'), list):
                raise ValueError('Dataset operation must be new, add-field, add-record, set-cell or expose-field')
            args, options = body['args'], body.get('options') if isinstance(body.get('options'), dict) else {}
            changed = operation(document, *args, **options)
            return {'ok': True, 'document': validate(document), 'changed': changed}
        if action == 'solve':
            from .canvas_documents import solve, write_through
            document = validate(body.get('document'))
            written = []
            for change in body.get('params') or []:
                node = next((n for n in document['nodes'] if n['id'] == change.get('node')), None)
                if node is not None and write_through(node, change.get('key'), change.get('value')):
                    written.append(change.get('key'))
            return {**solve(document, list(body.get('changed') or []), invoke=invoke, stopped=stopped), 'written': written}
        if action in ('head', 'read'):
            path = local_path(body.get('path')) if body.get('path') else next((row['path'] for row in load_skills() if row['skill']['id'] == body.get('id')), self.directory/'missing.archhub')
            if not re.fullmatch(r'[A-Za-z0-9_-]{0,128}', str(body.get('id',''))) or not path.exists():
                return {'ok':True,'revision':-1}
            from .workshop_tasks import refresh_steps
            refresh_steps(path)
            document = read_document(path)
            canvas_documents.remember(path, document)
            history = document.get('properties',{}).get('history',[])
            head = {'ok':True,'revision':canvas_documents.revision(document),'path':str(path),'by':history[-1]['by'] if history else ''}
            return {**head,'document':document} if action == 'read' else head
        if action == 'member-op':
            # One implementation of pulling an agent out of a group and dropping it back (canvas_documents.py).
            document = validate(body.get('document'))
            operation = {'detach': canvas_documents.detach_member, 'attach': canvas_documents.attach_member}.get(body.get('op'))
            args = body.get('args')
            if operation is None or not isinstance(args, list) or len(args) < 2:
                raise ValueError('Member operation must be detach or attach')
            changed = operation(document, *args)
            return {'ok': True, 'document': validate(document), 'changed': changed}
        if action == 'validate':
            return {'ok':True,'document':validate(body.get('document'))}
        if action == 'run':
            return run_document(body.get('document'),invoke=invoke,roots=body.get('roots'),stopped=stopped,path=body.get('path'))
        if action in ('agent-history', 'fork-node'):
            document = validate(body.get('document'))
            node = next(n for n in document['nodes'] if n['id'] == body.get('node'))
            if action == 'agent-history':
                from .agent_work import history
                return {'ok': True, **history(node)}
            from .agent_work import fork
            ids = fork(document, node['id'])
            return {'ok': True, 'document': validate(document), 'ids': ids}
        raise ValueError('Unknown session file action')


_SAMPLE_REF_PREFIX = "samples/"
_SAMPLES = Path(__file__).resolve().parent / "samples"

def resolve_sample_input(value: object) -> str | None:
    """Resolve a graph-held sample reference to its shipped local file."""
    text = str(value or "").strip().replace("\\", "/")
    if not text.startswith(_SAMPLE_REF_PREFIX):
        return None
    name = text[len(_SAMPLE_REF_PREFIX):]
    # Only a file the app actually ships under samples/ is a sample reference;
    # any other "samples/..." value is the user's own relative path, unchanged.
    if not name or "/" in name or name in (".", ".."):
        return None
    shipped = _SAMPLES / name
    try:
        if shipped.resolve().parent != _SAMPLES.resolve() or not shipped.is_file():
            return None
    except OSError as error:
        raise ValueError("Shipped sample could not be inspected.") from error
    return str(shipped)
