"""Portable Canvas documents. No CellStore, enrollment or graph lock."""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile
from uuid import uuid4

from . import canvas_documents

MAX_BYTES = 8 * 1024 * 1024
_SECRET = re.compile(r'(^|_)(password|secret|token|api_key|private_key|credential)(_|$)', re.I)


def new_document(title='Untitled'):
    return {'format': 'archhub', 'version': 1, 'id': str(uuid4()), 'title': title,
            'nodes': [], 'wires': [], 'groups': [], 'notes': [],
            'viewport': {'x': 0, 'y': 0, 'zoom': 1}}


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
        nodes[node['id']] = node
    for node in nodes.values():
        if node.get('parent') and node['parent'] not in nodes or any(child not in nodes for child in node.get('children',[])):
            raise ValueError('Group members must exist')
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
    with target.open('rb') as stream:
        raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError('Session exceeds 8 MiB')
    return validate(json.loads(raw.decode('utf-8-sig')))


def write_document(path, document):
    target = local_path(str(path))
    validate(document)
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
        os.replace(temporary, target)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)
    return str(target)


def catalogue():
    from .library_engines import library_catalogue
    items = [item for group in library_catalogue() for item in group['items'] if not item.get('hidden')]
    items.append({'id':'data.convert','cat':'shape','title':'Convert','sub':'Convert a wired value','engine':'data.convert','params':{'target_type':'text'},'ports':{'source':[{'id':'out','type':'any'}],'target':[{'id':'in','type':'any'}]}})
    from .canvas_documents import thing_items
    from .node_params import CATALOGUE_ITEM
    from .node_datasets import CATALOGUE_ITEM as DATASET_ITEM, FIELD_ITEM
    items.extend(thing_items())
    items.extend(dict(item) for item in (CATALOGUE_ITEM, DATASET_ITEM, FIELD_ITEM))
    for path in sorted(skills_directory().glob('*.archhub')):
        try:
            skill = read_document(path)
        except (OSError, ValueError):
            continue
        items.append({'id':'skill:'+skill['id'],'cat':'skills','title':skill['title'],'sub':'Skill · %d nodes'%len(skill['nodes']),
                      'engine':'skill','params':{'skill':skill['id']},'ports':skill_ports(skill, items)})
    # C2 on every definition: pure (Unreal: re-solves on edit, else waits for Run), budget, loop.
    for item in items:
        item.update(canvas_documents.node_contract(item.get('engine')))
    return items


def skills_directory():
    # A skill is a saved workflow: one portable .archhub file, shown in the Library as one node.
    path = Path(os.environ['LOCALAPPDATA'])/'ArchHub'/'sessions-files'/'skills'
    path.mkdir(parents=True, exist_ok=True)
    return path


def skill_ports(skill, items=()):
    """A skill's sockets come from its inner workflow: each unbound Parameter node is a typed input
    ('in:<node>'), each output of a node nothing inside reads is a typed output ('out:<node>:<socket>').
    'out' (the last node's values) stays for skills placed before typed sockets existed."""
    from .node_params import PARAM_ENGINE, ports as node_ports, socket_type
    known = {item['id']: item for item in items}
    read = {w['from']['node'] for w in skill['wires']}
    target = [{'id': 'in:' + n['id'], 'type': socket_type(n['params'].get('type')), 'label': n.get('title') or 'Input'}
              for n in skill['nodes'] if n['type'] == PARAM_ENGINE and not n.get('bind')]
    source = [{'id': 'out', 'type': 'any', 'label': 'Result'}]
    for n in skill['nodes']:
        if n['id'] in read or n['type'] in (PARAM_ENGINE, 'note'):
            continue
        entry = known.get(n.get('item')) or next((i for i in known.values() if i['engine'] == n['type']), None) or {}
        for port in node_ports(n, entry.get('ports') or {})['source']:
            source.append({'id': 'out:%s:%s' % (n['id'], port['id']), 'type': port.get('type', 'any'),
                           'label': '%s · %s' % (n.get('title') or n['type'], port.get('label') or port['id'])})
    return {'source': source, 'target': target}


def run_skill(params, *, invoke, stopped, depth, feeds=None):
    if depth > 8:
        raise ValueError('Skills nest at most 8 deep')
    name = str(params.get('skill',''))
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', name):
        raise ValueError('Skill id is invalid')
    from .node_params import PARAM_ENGINE, coerce
    skill = read_document(skills_directory()/(name+'.archhub'))
    inputs = {n['id']: n for n in skill['nodes'] if n['type'] == PARAM_ENGINE and not n.get('bind')}
    for socket, value in (feeds or {}).items():
        held = inputs.get(str(socket)[3:]) if str(socket).startswith('in:') else None
        if held is None:
            raise ValueError('This skill has no input %s' % socket)
        held['params']['value'] = coerce(held['params'].get('type', 'json'), value)   # a wired value sets the inner Parameter
    inner = run_document(skill, invoke=invoke, stopped=stopped, depth=depth+1)
    if not inner['succeeded']:
        raise ValueError('Skill failed: '+'; '.join(r.get('error','') for r in inner['results'].values() if r.get('error')))
    last = inner['results'][inner['order'][-1]]['output'] if inner['order'] else {}
    produced = {'out': last}
    for key, result in inner['results'].items():
        for socket, value in (result.get('output') or {}).items():
            produced['out:%s:%s' % (key, socket)] = value
    return produced, 'Skill ran %d nodes' % len(inner['order'])


def run_document(document, *, invoke=None, roots=None, stopped=None, depth=0, plan_only=False, cached=(), only=None):
    """Validate the whole plan before invoking existing engines in wire order."""
    from collections import deque
    from .library_engines import canonical_engine_interface, canonical_engine_parameters, STEM_RUN_ENGINES
    from .pipeline_engines import PIPELINE_ENGINES
    from .stem_graph_evaluation import run_stem_operation, StemWire, _carry, _Refusal
    validate(document)
    nodes = {n['id']: n for n in document['nodes']}
    incoming = {key: [] for key in nodes}
    outgoing = {key: [] for key in nodes}
    known = {row['id']: row for row in catalogue()}
    for wire in document['wires']:
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
    from .canvas_documents import THING_ENGINES, run_thing
    from .node_params import PARAM_ENGINE, bound_value, coerce, ports as node_ports
    for key in order:
        node = nodes[key]
        engine = node['type']
        if engine not in PIPELINE_ENGINES and engine not in STEM_RUN_ENGINES and engine not in ('note', 'skill', PARAM_ENGINE, 'data.dataset', 'data.field') and engine not in THING_ENGINES:
            raise ValueError('Missing engine: '+engine)
        entry = known.get(node.get('item')) or next((r for r in known.values() if r['engine'] == engine), None)
        if entry and entry['engine'] != engine:
            raise ValueError('Library item and engine disagree')
        if entry:
            for side, wires, end in [('source', outgoing[key], 'from'), ('target', incoming[key], 'to')]:
                sockets = {p['id'] for p in node_ports(node, entry['ports'])[side]}
                if any(wire[end]['socket'] not in sockets for wire in wires):
                    raise ValueError('Unknown socket on '+node.get('title',key))
    outputs, results = {}, {}
    for key in order:
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
        feeds = {}
        engine = node['type']
        try:
            for wire in wired:
                source = nodes[wire['from']['node']]
                socket = canonical_engine_interface(source['type'], 'source', wire['from']['socket'])
                produced = outputs[source['id']]
                if socket not in produced:
                    raise ValueError('Source socket produced no value: '+str(socket))
                value = _carry(StemWire(source['id'], str(socket), key, wire['to']['socket'], condition=wire.get('rule','')), produced[socket])
                if isinstance(value, _Refusal):
                    raise ValueError(value.reason)
                feeds[canonical_engine_interface(engine, 'target', wire['to']['socket'])] = value
            # A user parameter's socket sets that parameter (a wired Parameter node is the same value).
            own = {k: v for k, v in node['params'].items() if k not in {d['id'] for d in node.get('paramDefs', [])}}
            extra = {k: v for k, v in node['params'].items() if k not in own}
            for socket in [s for s in list(feeds) if str(s).startswith('param:')]:
                extra[socket[6:]] = feeds.pop(socket)
            params = own if engine in ('skill', PARAM_ENGINE) or engine in THING_ENGINES else canonical_engine_parameters(engine, own)
            params = {**params, **extra}
            if engine == PARAM_ENGINE:
                value = bound_value(document, node)
                produced, display = {'value': coerce(node['params'].get('type', 'json'), value)}, str(value)
            elif engine in ('data.dataset', 'data.field'):
                from .node_datasets import outputs as dataset_outputs
                produced, display = dataset_outputs(node, feeds)
            elif engine in THING_ENGINES:
                produced, display = run_thing(engine, params, feeds)
            elif engine == 'skill':
                produced, display = run_skill(params, invoke=invoke, stopped=stopped, depth=depth, feeds=feeds)
            elif engine == 'note':
                produced, display = {}, node.get('title','Note')
            elif engine in STEM_RUN_ENGINES:
                produced, display = run_stem_operation(engine, params, feeds)
            else:
                effect = PIPELINE_ENGINES[engine]
                if invoke is None:
                    raise ValueError('This engine needs the application effect boundary')
                produced, display = invoke(engine, effect, params, feeds)
            json.dumps(produced, allow_nan=False)
            outputs[key] = produced
            results[key] = {'status':'Done', 'output':produced, 'display':display}
        except Exception as error:
            results[key] = {'status':'Error', 'output':{}, 'error':str(error)}
    return {'ok':True, 'succeeded':all(r['status'] in ('Done','Disabled','Skipped') for r in results.values()), 'results':results, 'order':order}


class SessionFiles:
    """Files are data; recent paths and crash recovery remain local to the profile."""
    def __init__(self, directory=None):
        self.directory = Path(directory) if directory else Path(os.environ['LOCALAPPDATA'])/'ArchHub'/'sessions-files'
        self.directory.mkdir(parents=True, exist_ok=True)

    def recent(self):
        path = self.directory/'recent.json'
        if not path.exists():
            return []
        rows = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(rows, list):
            raise ValueError('Recent session list is invalid')
        return rows

    def remember(self, path, document):
        rows = [{'id':str(path), 'path':str(path), 'name':document['title'], 'title':document['title']}] + [r for r in self.recent() if r['path'] != str(path)]
        target = self.directory/'recent.json'
        with tempfile.NamedTemporaryFile(dir=self.directory, suffix='.tmp', delete=False, mode='w', encoding='utf-8') as stream:
            temporary = stream.name
            json.dump(rows[:20],stream)
        try:
            os.replace(temporary,target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def _current(self, identity, path):
        current = self.directory/'current.json'
        with tempfile.NamedTemporaryFile(dir=self.directory, suffix='.tmp', delete=False, mode='w', encoding='utf-8') as stream:
            temporary = stream.name
            json.dump({'id':identity,'path':str(local_path(path)) if path else ''},stream)
        try:
            os.replace(temporary,current)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def open_files(self):
        """The file the app has open now (agents edit the same file), then recent files."""
        rows = []
        current = self.directory/'current.json'
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
        if kind == 'skill':
            target = skills_directory()/(imported['id']+'.archhub')
        else:
            imported['id'] = 'import-' + hashlib.sha1(str(source.resolve()).lower().encode()).hexdigest()[:16]
            target = self.directory/(imported['id']+'.archhub')
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
        if action == 'catalogue':
            return {'ok':True,'items':catalogue(),'recent':self.recent(),'directory':str(self.directory)}
        if action == 'initial':
            import sys
            launch = next((a for a in sys.argv[1:] if str(a).lower().endswith('.archhub')), None)
            current = self.directory/'current.json'
            held = json.loads(current.read_text(encoding='utf-8')) if current.exists() else {}
            recovery = Path(held['path']) if held.get('path') else self.directory/(held['id']+'.archhub') if held else self.directory/'autosave.archhub'
            document = read_document(launch) if launch else read_document(recovery) if recovery.exists() else new_document()
            return {'ok':True,'document':document,'path':str(launch or (json.loads(current.read_text(encoding='utf-8')).get('path','') if current.exists() else ''))}
        if action == 'starter':
            # A built-in starter becomes the founder's own new session file (the starter itself never changes).
            from .starters import document as starter_document
            document = starter_document(str(body.get('id') or ''))
            path = write_document(self.directory/(document['id']+'.archhub'), document)
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
            document = read_document(path)
            self.remember(local_path(path),document)
            return {'ok':True,'document':document,'path':str(local_path(path))}
        if action in ('save','autosave'):
            document = validate(body.get('document'))
            if not re.fullmatch(r'[A-Za-z0-9_-]{1,128}',document['id']):
                raise ValueError('Session id must be a portable filename identifier')
            if action == 'autosave':
                # Autosave is in place: the open file IS the document agents edit too.
                from .canvas_documents import commit_ui
                path = str(local_path(body['path'])) if body.get('path') else str(self.directory/(document['id']+'.archhub'))
                merged = commit_ui(path, document, int(body.get('base_revision') or 0))
                self._current(document['id'], body.get('path') or '')
                return {'ok':True,'path':path,'document':merged,'revision':merged.get('properties',{}).get('revision',0)}
            path = body.get('path')
            if not path and save_picker:
                path = save_picker('Save session','ArchHub session (*.archhub)')
            if not path:
                return {'ok':True,'cancelled':True}
            path = write_document(path,document)
            canvas_documents.remember(path, document)
            self.remember(path,document)
            self._current(document['id'], path)
            return {'ok':True,'path':path}
        if action == 'save-skill':
            document = validate(body.get('document'))
            if not re.fullmatch(r'[A-Za-z0-9_-]{1,128}',document['id']):
                raise ValueError('Skill id must be a portable filename identifier')
            return {'ok':True,'path':write_document(str(skills_directory()/(document['id']+'.archhub')),document),'id':'skill:'+document['id']}
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
            path = local_path(body.get('path')) if body.get('path') else self.directory/(str(body.get('id',''))+'.archhub')
            if not re.fullmatch(r'[A-Za-z0-9_-]{0,128}', str(body.get('id',''))) or not path.exists():
                return {'ok':True,'revision':-1}
            document = read_document(path)
            canvas_documents.remember(path, document)
            history = document.get('properties',{}).get('history',[])
            head = {'ok':True,'revision':canvas_documents.revision(document),'path':str(path),'by':history[-1]['by'] if history else ''}
            return {**head,'document':document} if action == 'read' else head
        if action == 'validate':
            return {'ok':True,'document':validate(body.get('document'))}
        if action == 'run':
            return run_document(body.get('document'),invoke=invoke,roots=body.get('roots'),stopped=stopped)
        raise ValueError('Unknown session file action')
