"""User parameters on any node, and Parameter nodes that share their value (Grasshopper / ComfyUI).

Founder 2026-10-28: the whole app is parametric; a user adds a parameter to a node, picks its
data type and value, and any parameter can itself be a node.

Stored in the .archhub node:
  node.paramDefs = [{id, name, type, min?, max?, options?, promoted?}]   value lives in node.params[id]
  node 'param:<id>' input socket, typed from the parameter type
A promoted parameter is a 'param.value' node with bind {node, param} and one typed 'value' output,
wired into the owner's 'param:<id>' socket. It holds NO value of its own: it reads and writes
node.params[id] of its owner, so the inline control and the Parameter node are one value.
An unbound Parameter node (from the Library) keeps its own value in params.value.
"""
from __future__ import annotations

import json
import math
import re
from uuid import uuid4

# Ping's Penpot rev1028: Boolean / Integer / Number (with units) / Text / Choice / Date / File-Folder / Object / List.
TYPES = ('bool', 'integer', 'number', 'text', 'choice', 'date', 'file', 'folder', 'object', 'list',
         'path', 'color', 'enum', 'json')  # the last four: earlier spellings, kept readable
SOCKET = {'number': 'number', 'integer': 'number', 'text': 'string', 'bool': 'boolean', 'list': 'list',
          'file': 'file', 'folder': 'file', 'path': 'file', 'color': 'string', 'choice': 'string', 'enum': 'string',
          'date': 'string', 'object': 'any', 'json': 'any'}
PARAM_ENGINE = 'param.value'


def socket_type(kind):
    return SOCKET.get(kind, 'any')


def coerce(kind, value, definition=None):
    """The one value check, shared by the UI, agents and Run."""
    definition = definition or {}
    if kind not in TYPES:
        raise ValueError('Choose a parameter type: ' + ', '.join(TYPES))
    if kind in ('number', 'integer'):
        # Blank min/max (and any parameter marked optional) means unbounded / unset.
        if value in ('', None) and definition.get('optional'):
            return None
        try:
            number = float(value)
        except (TypeError, ValueError):
            raise ValueError('Enter a number, not %r.' % value) from None
        if not math.isfinite(number) or (kind == 'integer' and number != int(number)):
            raise ValueError('Enter a %s.' % ('whole number' if kind == 'integer' else 'finite number'))
        for bound, test in (('min', lambda b: number < b), ('max', lambda b: number > b)):
            if definition.get(bound) not in (None, '') and test(float(definition[bound])):
                raise ValueError('Value is outside %s %s.' % (bound, definition[bound]))
        return int(number) if kind == 'integer' else number
    if kind == 'bool':
        if isinstance(value, bool):
            return value
        if str(value).casefold() in ('true', 'false', '1', '0', 'yes', 'no'):
            return str(value).casefold() in ('true', '1', 'yes')
        raise ValueError('Choose true or false.')
    if kind == 'list':
        parsed = json.loads(value) if isinstance(value, str) else value
        if not isinstance(parsed, list):
            raise ValueError('Enter a list, e.g. [1, 2, 3].')
        return parsed
    if kind in ('json', 'object'):
        parsed = json.loads(value) if isinstance(value, str) else value
        if kind == 'object' and not isinstance(parsed, dict):
            raise ValueError('Enter an object, e.g. {"key": 1}.')
        return parsed
    if kind == 'date':
        import datetime
        return datetime.date.fromisoformat(str(value)).isoformat()
    if kind == 'color':
        if not re.fullmatch(r'#[0-9a-fA-F]{6}', str(value)):
            raise ValueError('Choose a colour like #d97757.')
        return str(value)
    if kind in ('enum', 'choice'):
        options = definition.get('options') or []
        if str(value) not in options:
            raise ValueError('Choose one of: ' + ', '.join(options))
        return str(value)
    return str(value)


def infer(value):
    if isinstance(value, bool) or str(value).casefold() in ('true', 'false'):
        return 'bool'
    for kind, cast in (('integer', int), ('number', float)):
        try:
            cast(value)
            return kind
        except (TypeError, ValueError):
            continue
    return 'list' if isinstance(value, list) else 'json' if isinstance(value, dict) else 'text'


def _node(document, ref):
    found = [n for n in document['nodes'] if n['id'] == ref or n.get('title') == ref]
    if len(found) != 1:
        raise ValueError('Name exactly one node: %s' % ref)
    return found[0]


def definition(node, param):
    found = [d for d in node.get('paramDefs', []) if d['id'] == param]
    if not found:
        raise ValueError('Parameter is absent: %s' % param)
    return found[0]


def default(entry):
    """The empty value of a parameter (or dataset field) of this type."""
    import datetime
    first = (entry.get('options') or [''])[0]
    value = {'number': 0, 'integer': 0, 'bool': False, 'list': [], 'json': {}, 'object': {}, 'color': '#d97757',
             'date': datetime.date.today().isoformat(), 'enum': first, 'choice': first}.get(entry['type'], '')
    if entry['type'] in ('number', 'integer') and entry.get('min') not in (None, ''):
        value = max(value, float(entry['min']))
    return coerce(entry['type'], value, entry)


def add_param(document, node_ref, name, kind, value=None, **limits):
    """Add a typed user parameter (with its input socket) to a node. Returns the node id."""
    node = _node(document, node_ref)
    identity = re.sub(r'[^a-z0-9_]+', '_', str(name).strip().casefold()).strip('_')[:60]
    if not identity or identity in node['params']:
        raise ValueError('Choose a new parameter name for this node.')
    entry = {'id': identity, 'name': str(name).strip()[:80], 'type': kind,
             **{k: v for k, v in limits.items() if k in ('min', 'max', 'step', 'unit', 'options') and v not in (None, '', [])}}
    node['params'][identity] = coerce(kind, default(entry) if value in (None, '') else value, entry)
    node.setdefault('paramDefs', []).append(entry)
    return [node['id']]


def bound_value(document, node):
    bind = node.get('bind') or {}
    owner = next((n for n in document['nodes'] if n['id'] == bind.get('node')), None)
    if owner is None:
        return node['params'].get('value')
    return owner['params'].get(bind.get('param'))


def set_value(document, node_ref, key, value):
    """Set a parameter; a bound Parameter node writes its owner's value (one identity). Returns changed ids."""
    node = _node(document, node_ref)
    if node['type'] == PARAM_ENGINE and node.get('bind') and key == 'value':
        owner = _node(document, node['bind']['node'])
        param = node['bind']['param']
        owner['params'][param] = coerce(definition(owner, param)['type'], value, definition(owner, param))
        return [owner['id'], node['id']]
    if key not in node['params']:
        raise ValueError('Parameter is absent. Parameters: %s' % list(node['params']))
    user = [d for d in node.get('paramDefs', []) if d['id'] == key]
    node['params'][key] = coerce(user[0]['type'], value, user[0]) if user else value
    promoted = user[0].get('promoted') if user else None
    return [node['id']] + ([promoted] if promoted else [])


def promote(document, node_ref, param):
    """Expose a parameter as a Parameter node wired into the owner's typed socket."""
    owner = _node(document, node_ref)
    if param in owner['params'] and not any(d['id'] == param for d in owner.get('paramDefs', [])):
        # A built-in parameter becomes typed (from its value) the first time it is exposed.
        owner.setdefault('paramDefs', []).append({'id': param, 'name': param.replace('_', ' ').capitalize(),
                                                   'type': infer(owner['params'][param]), 'builtin': True})
    entry = definition(owner, param)
    if entry.get('promoted'):
        raise ValueError('This parameter is already a node.')
    node = {'id': str(uuid4()), 'type': PARAM_ENGINE, 'item': PARAM_ENGINE, 'title': entry['name'],
            'params': {'type': entry['type']}, 'bind': {'node': owner['id'], 'param': param},
            'position': {'x': owner['position']['x'], 'y': owner['position']['y'] + 300 + 40 * len(owner.get('paramDefs', []))}}
    document['nodes'].append(node)
    document['wires'].append({'id': str(uuid4()), 'from': {'node': node['id'], 'socket': 'value'},
                              'to': {'node': owner['id'], 'socket': 'param:' + param}})
    entry['promoted'] = node['id']
    return [node['id'], owner['id']]


def demote(document, node_ref, param):
    owner = _node(document, node_ref)
    entry = definition(owner, param)
    gone = entry.pop('promoted', None)
    if not gone:
        raise ValueError('This parameter is not a node.')
    downstream = [w['to']['node'] for w in document['wires'] if w['from']['node'] == gone and w['to']['node'] != owner['id']]
    document['nodes'] = [n for n in document['nodes'] if n['id'] != gone]
    document['wires'] = [w for w in document['wires'] if gone not in (w['from']['node'], w['to']['node'])]
    return [owner['id']] + downstream


def ports(node, base):
    """Library ports plus the typed sockets of the node's own parameters (and a Parameter node's output)."""
    source, target = list(base.get('source', [])), list(base.get('target', []))
    if node['type'] in ('data.dataset', 'data.field'):
        from .node_datasets import ports as dataset_ports
        source, target = dataset_ports(node)['source'], dataset_ports(node)['target']
    if node['type'] == PARAM_ENGINE:
        source = [{'id': 'value', 'type': socket_type(node['params'].get('type'))}]
    if node['type'] != 'data.dataset':  # a dataset's fields are its columns, not inputs
        target += [{'id': 'param:' + d['id'], 'type': socket_type(d['type'])} for d in node.get('paramDefs', [])]
    return {'source': source, 'target': target}


def compatible(out_type, in_type):
    return 'any' in (out_type, in_type) or 'unknown' in (out_type, in_type) or out_type == in_type


CATALOGUE_ITEM = {'id': PARAM_ENGINE, 'cat': 'input', 'title': 'Parameter', 'sub': 'A typed value you can wire anywhere',
                  'engine': PARAM_ENGINE, 'params': {'type': 'number', 'value': 0},
                  'ports': {'source': [{'id': 'value', 'type': 'any'}], 'target': []}}


if __name__ == '__main__':  # self-check: one identity, typed sockets, rejection
    doc = {'nodes': [{'id': 'a', 'type': 'shape.slice', 'title': 'Slice', 'params': {}, 'position': {'x': 400, 'y': 0}}], 'wires': []}
    add_param(doc, 'a', 'Count', 'integer', 3, min=0, max=10)
    pid = promote(doc, 'a', 'count')[0]
    assert set_value(doc, pid, 'value', 7) == ['a', pid] and doc['nodes'][0]['params']['count'] == 7
    assert set_value(doc, 'a', 'count', 2) == ['a', pid] and bound_value(doc, doc['nodes'][1]) == 2
    assert ports(doc['nodes'][1], {})['source'][0]['type'] == 'number' and not compatible('number', 'string')
    try:
        set_value(doc, 'a', 'count', 2.5)
        refused = False
    except ValueError:
        refused = True
    assert refused, 'integer accepted a fraction'
    demote(doc, 'a', 'count')
    assert len(doc['nodes']) == 1 and not doc['wires']
    add_param(doc, 'a', 'Due', 'date', '2026-10-30')
    add_param(doc, 'a', 'Height', 'number', '3.2', unit='m', step=0.1)
    add_param(doc, 'a', 'Level', 'choice', 'L2', options=['L1', 'L2'])
    assert doc['nodes'][0]['paramDefs'][-2]['unit'] == 'm' and ports(doc['nodes'][0], {})['target'][-3]['type'] == 'string'
    print('node_params ok')
