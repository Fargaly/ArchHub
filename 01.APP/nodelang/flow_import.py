"""Importers: Node-RED flows, Langflow flows and skills.sh SKILL.md files become .archhub documents.

Founder doctrine (S8 Library): importers bring ecosystems in as nodes, fitted, never a black box.
Each foreign node becomes an ArchHub engine node (typed sockets, params, pure flag from the one
is_pure(), a budget) or, when ArchHub has no engine for it, an 'import.foreign' node: side-effect,
untrusted, and it never runs (safety rules 1-2). node['source'] keeps the original id so a re-import
updates nodes in place (rule 4). Imported files are data: nothing in them is executed or evaluated.
"""
from __future__ import annotations

import hashlib
import json
import re

FOREIGN = 'import.foreign'
# The importer's owner node: its typed parameters. Every imported node carries a budget (rule 3);
# catalogue cards declare none, so these are the default. A repeating trigger stops after loop_cap runs.
IMPORT_NODE = {'id': 'canvas.import', 'params': {'budget_seconds': 60, 'budget_runs': 1, 'loop_cap': 100}}
DEFAULT_BUDGET = {'seconds': IMPORT_NODE['params']['budget_seconds'], 'runs': IMPORT_NODE['params']['budget_runs']}
LOOP_CAP = IMPORT_NODE['params']['loop_cap']
_COMPARE = {'lt': '<', 'lte': '<=', 'gt': '>', 'gte': '>=', 'eq': '==', 'neq': '!='}


def _sid(prefix, value):
    """A stable ArchHub node id from the source id: the same source node maps to the same node."""
    return prefix + re.sub(r'[^A-Za-z0-9_-]+', '_', str(value))[:100]


def _node(nid, engine, title, params, position, source, *, sources=(), targets=(), budget=None):
    from .canvas_documents import is_pure
    return {'id': nid, 'type': engine, 'title': str(title)[:200], 'params': params,
            'position': {'x': float(position[0]), 'y': float(position[1])},
            'ports': {'source': [{'id': s, 'type': 'any'} for s in sources],
                      'target': [{'id': t, 'type': 'any'} for t in targets]},
            'pure': is_pure(engine), 'budget': dict(budget or DEFAULT_BUDGET), 'source': source}


def _foreign(nid, fmt, kind, title, position, source, sources, targets, why):
    return _node(nid, FOREIGN, title or kind, {'format': fmt, 'kind': kind, 'reason': why}, position, source,
                 sources=sources, targets=targets)


def _escape(text):
    return str(text).replace('{', '{{').replace('}', '}}')


class _Builder:
    """Collects nodes and wires; fan-in to one input becomes a Merge chain (an input takes one wire)."""

    def __init__(self, fmt):
        self.fmt, self.nodes, self.wires, self.dropped = fmt, {}, [], []

    def add(self, node):
        self.nodes[node['id']] = node
        return node

    def connect(self, wires):
        by_target = {}
        for wire in wires:
            by_target.setdefault((wire[2], wire[3]), []).append(wire)
        for (target, socket), group in by_target.items():
            node = self.nodes[target]
            if len(group) == 1:
                self._wire(group[0])
            elif node['type'] == FOREIGN:   # a foreign node keeps each wire on its own numbered socket
                for index, (src, out, _, _) in enumerate(group):
                    name = socket if index == 0 else '%s#%d' % (socket, index + 1)
                    if name not in [p['id'] for p in node['ports']['target']]:
                        node['ports']['target'].append({'id': name, 'type': 'any'})
                    self._wire((src, out, target, name))
            else:
                held = group[0][:2]
                for index, (src, out, _, _) in enumerate(group[1:], start=1):
                    x, y = node['position']['x'] - 120, node['position']['y'] + 40 * index
                    merge = self.add(_node('%s-merge%d-%s' % (target, index, re.sub(r'\W', '', socket)), 'control.merge',
                                           'Merge (first value wins)', {}, (x, y),
                                           {'format': self.fmt, 'type': 'fan-in', 'id': '%s:%s:%d' % (target, socket, index)},
                                           sources=['value'], targets=['a', 'b']))
                    self._wire((held[0], held[1], merge['id'], 'a'))
                    self._wire((src, out, merge['id'], 'b'))
                    held = (merge['id'], 'value')
                self._wire((held[0], held[1], target, socket))

    def _wire(self, wire):
        src, out, target, socket = wire
        self.wires.append({'id': 'w-%s-%s-%s-%s' % (src, out, target, socket), 'from': {'node': src, 'socket': out},
                           'to': {'node': target, 'socket': socket}})

    def document(self, title, identity, report):
        from .session_files import new_document, validate
        document = new_document(title)
        document['id'] = identity
        document['nodes'], document['wires'] = list(self.nodes.values()), self.wires
        document['properties'] = {'import': {**report, 'format': self.fmt, 'dropped': self.dropped,
                                             'foreign': sum(n['type'] == FOREIGN for n in document['nodes'])}}
        return validate(document)


# ------------------------------------------------------------------ Node-RED --
def _nr_value(kind, value):
    if kind == 'num':
        return float(value) if str(value).strip() not in ('', None) else 0
    if kind == 'json':
        return json.loads(value) if str(value).strip() else None
    if kind == 'bool':
        return str(value).lower() == 'true'
    return str(value)


def _nr_node(item, nid, pos, source, outputs):
    """(engine node, input socket, output sockets in Node-RED port order) for one Node-RED node."""
    kind, name = item.get('type', ''), item.get('name') or ''
    outs = ['out%d' % i for i in range(outputs)]
    foreign = lambda why: (_foreign(nid, 'node-red', kind, name, pos, source, outs, ['in'], why), 'in', outs)
    if kind == 'comment':
        return _node(nid, 'note', name or 'Comment', {'text': str(item.get('info') or name)}, pos, source), None, []
    if kind == 'inject':
        budget = dict(DEFAULT_BUDGET)
        if str(item.get('repeat') or '').strip() or str(item.get('crontab') or '').strip():
            budget = {**budget, 'runs': LOOP_CAP, 'repeat_seconds': float(item['repeat']) if str(item.get('repeat') or '').strip() else None,
                      'crontab': str(item.get('crontab') or ''), 'stop': 'Stop, or after %d runs' % LOOP_CAP}
        ptype = item.get('payloadType', 'date')
        if ptype in ('num', 'str', 'json', 'bool'):
            try:
                value = _nr_value(ptype, item.get('payload', ''))
            except ValueError:
                return foreign('payload is not valid %s' % ptype)
            return _node(nid, 'data.constant', name or 'Inject', {'value': value}, pos, source, sources=['value'],
                         budget=budget), None, ['value']
        return _node(nid, 'trigger.emit', name or 'Inject', {}, pos, source, sources=['out'], budget=budget), None, ['out']
    if kind == 'debug':
        return _node(nid, 'watch.preview', name or 'Debug', {'as': 'table'}, pos, source, sources=['out'], targets=['in']), 'in', []
    if kind == 'change':
        rules = item.get('rules') or []
        if len(rules) == 1 and rules[0].get('t') == 'set' and rules[0].get('p') == 'payload' and rules[0].get('pt') == 'msg':
            rule = rules[0]
            if rule.get('tot') == 'str':
                return _node(nid, 'text.ops', name or 'Change', {'operation': 'format', 'template': _escape(rule.get('to', ''))},
                             pos, source, sources=['text'], targets=['text']), 'text', ['text']
            if rule.get('tot') == 'num':
                return _node(nid, 'math.expression', name or 'Change', {'expression': str(float(rule.get('to') or 0))},
                             pos, source, sources=['value'], targets=['x']), 'x', ['value']
        return foreign('change rules other than "set payload to text or number" have no ArchHub engine yet')
    if kind == 'range' and item.get('property', 'payload') == 'payload' and item.get('action') in ('scale', 'clamp'):
        try:
            a, b, c, d = (float(item[k]) for k in ('minin', 'maxin', 'minout', 'maxout'))
        except (KeyError, ValueError):
            return foreign('range limits are not numbers')
        if a == b:
            return foreign('range input limits are equal')
        expr = '(x - %r) * %r + %r' % (a, (d - c) / (b - a), c)
        if item['action'] == 'clamp':
            expr = 'min(max(%s, %r), %r)' % (expr, min(c, d), max(c, d))
        if item.get('round'):
            expr = 'round(%s)' % expr
        return _node(nid, 'math.expression', name or 'Range', {'expression': expr}, pos, source,
                     sources=['value'], targets=['x']), 'x', ['value']
    if kind == 'json' and item.get('property', 'payload') == 'payload':
        target = {'str': 'text', 'obj': 'object'}.get(item.get('action') or 'obj', 'object')
        return _node(nid, 'data.convert', name or 'JSON', {'target_type': target}, pos, source,
                     sources=['out'], targets=['in']), 'in', ['out']
    if kind == 'template' and item.get('field', 'payload') == 'payload' and item.get('syntax') == 'plain':
        return _node(nid, 'text.ops', name or 'Template', {'operation': 'format', 'template': _escape(item.get('template', ''))},
                     pos, source, sources=['text'], targets=['text']), 'text', ['text']
    template = re.sub(r'\{\{\s*payload\s*\}\}', '\0', str(item.get('template', '')))
    if kind == 'template' and item.get('field', 'payload') == 'payload' and '{{' not in template:
        # Mustache whose only tag is {{payload}}; sections and other tags have no engine yet.
        return _node(nid, 'text.ops', name or 'Template', {'operation': 'format', 'template': _escape(template).replace('\0', '{value}')},
                     pos, source, sources=['text'], targets=['text']), 'text', ['text']
    code = kind in ('function', 'exec') or 'func' in item
    return foreign('Node-RED %s nodes have no ArchHub engine yet%s' % (kind, '; their code is untrusted and never runs' if code else ''))


def _nr_switch(builder, item, nid, pos, source):
    """A Node-RED switch on msg.payload with comparison rules -> a chain of If nodes, one per rule."""
    rules = item.get('rules') or []
    if item.get('property', 'payload') != 'payload' or item.get('propertyType', 'msg') != 'msg' or not rules or \
            any(r.get('t') not in _COMPARE or r.get('vt') not in ('num', 'str') for r in rules):
        return None
    outs, first = [], None
    previous = None
    for index, rule in enumerate(rules):
        value = rule.get('v', '')
        literal = repr(float(value)) if rule.get('vt') == 'num' else '"%s"' % str(value).replace('"', '')
        node = builder.add(_node('%s-r%d' % (nid, index), 'control.if', '%s rule %d' % (item.get('name') or 'Switch', index + 1),
                                 {'condition': 'value %s %s' % (_COMPARE[rule['t']], literal)},
                                 (pos[0] + 40 * index, pos[1] + 30 * index),
                                 {**source, 'rule': index}, sources=['true', 'false'], targets=['value']))
        if previous is None:
            first = node['id']
        else:
            builder._wire((previous, 'false', node['id'], 'value'))
        outs.append((node['id'], 'true'))
        previous = node['id']
    return first, outs


def import_node_red(flow, title='Node-RED flow', identity=None):
    """A Node-RED flow export (a JSON array of nodes) -> a validated .archhub document."""
    items = flow.get('flows') if isinstance(flow, dict) else flow
    if not isinstance(items, list) or not all(isinstance(i, dict) and isinstance(i.get('id'), str) for i in items):
        raise ValueError('Not a Node-RED flow: expected a JSON array of nodes with ids')
    builder = _Builder('node-red')
    tabs = [i for i in items if i.get('type') == 'tab']
    title = (tabs[0].get('label') if len(tabs) == 1 and tabs[0].get('label') else title)
    skipped = []
    outs, inputs = {}, {}
    for item in items:
        if item.get('type') in ('tab', 'subflow', 'group') or 'x' not in item:
            skipped.append(item.get('type'))   # tabs, groups and config nodes carry no flow step
            continue
        nid = _sid('nr-', item['id'])
        pos = (item.get('x', 0), item.get('y', 0))
        source = {'format': 'node-red', 'type': item.get('type'), 'id': item['id']}
        if item.get('type') == 'switch':
            chained = _nr_switch(builder, item, nid, pos, source)
            if chained:
                inputs[item['id']] = (chained[0], 'value')
                outs[item['id']] = chained[1]
                continue
        node, socket, sockets = _nr_node(item, nid, pos, source, len(item.get('wires') or []))
        builder.add(node)
        if socket:
            inputs[item['id']] = (nid, socket)
        outs[item['id']] = [(nid, s) for s in sockets]
    wires = []
    for item in items:
        for index, targets in enumerate(item.get('wires') or []):
            for target in targets or []:
                port = outs.get(item['id'], [])
                if index >= len(port) or target not in inputs:
                    builder.dropped.append({'from': item['id'], 'port': index, 'to': target})
                    continue
                wires.append((*port[index], *inputs[target]))
    builder.connect(wires)
    digest = hashlib.sha1(json.dumps(items, sort_keys=True).encode()).hexdigest()[:16]
    return builder.document(title, identity or 'nodered-' + digest, {'skipped': skipped})


# ------------------------------------------------------------------ Langflow --
_LF_INPUT = ('ChatInput', 'TextInput')
_LF_OUTPUT = ('ChatOutput', 'TextOutput')


def _field(template, key, default=''):
    held = template.get(key)
    return held.get('value', default) if isinstance(held, dict) else default


def import_langflow(flow, identity=None):
    """A Langflow flow export ({data: {nodes, edges}}) -> a validated .archhub document."""
    graph = flow.get('data') if isinstance(flow, dict) else None
    if not isinstance(graph, dict) or not isinstance(graph.get('nodes'), list) or not isinstance(graph.get('edges'), list):
        raise ValueError('Not a Langflow flow: expected {"data": {"nodes": [...], "edges": [...]}}')
    builder = _Builder('langflow')
    edges = [e for e in graph['edges'] if isinstance(e, dict)]
    handle = lambda e, side, key: ((e.get('data') or {}).get(side + 'Handle') or {}).get(key)
    tool_targets = {e.get('target') for e in edges if handle(e, 'target', 'fieldName') == 'tools'}
    mapped = {}   # langflow id -> (node id, {langflow field: socket}, {langflow output: socket})
    for item in graph['nodes']:
        if not isinstance(item, dict) or not isinstance(item.get('id'), str):
            continue
        data = item.get('data') or {}
        spec = data.get('node') or {}
        kind = data.get('type') or item.get('type') or 'unknown'
        template = spec.get('template') or {}
        nid, pos = _sid('lf-', item['id']), ((item.get('position') or {}).get('x', 0), (item.get('position') or {}).get('y', 0))
        source = {'format': 'langflow', 'type': kind, 'id': item['id']}
        name = spec.get('display_name') or kind
        if item.get('type') == 'noteNode':
            builder.add(_node(nid, 'note', 'Note', {'text': str((spec.get('description') or ''))[:20000]}, pos, source))
            continue
        if kind in _LF_INPUT:
            builder.add(_node(nid, 'param.value', name, {'type': 'text', 'value': str(_field(template, 'input_value'))}, pos, source,
                              sources=['value']))
            mapped[item['id']] = (nid, {}, {o: 'value' for o in ('message', 'text')})
            continue
        if kind in _LF_OUTPUT:
            builder.add(_node(nid, 'watch.preview', name, {'as': 'table'}, pos, source, sources=['out'], targets=['in']))
            mapped[item['id']] = (nid, {'input_value': 'in'}, {'message': 'out'})
            continue
        if kind == 'Prompt' and not _field(template, 'use_double_brackets', False):
            from .node_params import add_param
            text = str(_field(template, 'template'))
            names = [n for n in dict.fromkeys(re.findall(r'\{([A-Za-z_][A-Za-z0-9_]*)\}', text))]
            pattern = re.compile(r'\{(%s)\}' % '|'.join(map(re.escape, names))) if names else None
            parts, last = [], 0
            for match in (pattern.finditer(text) if pattern else []):
                parts.append(_escape(text[last:match.start()]) + '{' + match.group(1).casefold() + '}')
                last = match.end()
            parts.append(_escape(text[last:]))
            node = builder.add(_node(nid, 'text.ops', name, {'operation': 'format', 'template': ''.join(parts)}, pos, source,
                                     sources=['text'], targets=['text']))
            holder = {'nodes': [node]}
            for variable in names:
                add_param(holder, nid, variable, 'text', '')
            node['ports']['target'] += [{'id': 'param:' + v.casefold(), 'type': 'string'} for v in names]
            mapped[item['id']] = (nid, {v: 'param:' + v.casefold() for v in names}, {'prompt': 'text'})
            continue
        is_model = kind == 'LanguageModelComponent' or kind.endswith('Model') or (kind == 'Agent' and item['id'] not in tool_targets)
        if is_model:
            system = str(_field(template, 'system_prompt') or _field(template, 'system_message') or '')
            builder.add(_node(nid, 'thing.model', name, {'prompt': '', 'system': system}, pos,
                              {**source, 'model': str(_field(template, 'model_name') or _field(template, 'model') or '')[:200]},
                              sources=['text', 'model'], targets=['prompt', 'system']))
            mapped[item['id']] = (nid, {'input_value': 'prompt', 'system_message': 'system'},
                                  {o: 'text' for o in ('text_output', 'response', 'model_output')})
            continue
        sources = [o.get('name') for o in spec.get('outputs') or [] if isinstance(o, dict) and o.get('name')]
        why = ('Langflow %s has no ArchHub engine yet; its component code is untrusted and never runs'
               if 'code' in template else 'Langflow %s has no ArchHub engine yet') % kind
        builder.add(_foreign(nid, 'langflow', kind, name, pos, source, sources, [], why))
        mapped[item['id']] = (nid, None, None)
    wires = []
    for edge in edges:
        src, dst = mapped.get(edge.get('source')), mapped.get(edge.get('target'))
        out, field = handle(edge, 'source', 'name'), handle(edge, 'target', 'fieldName')
        if not src or not dst or not out or not field:
            builder.dropped.append({'from': edge.get('source'), 'to': edge.get('target'), 'field': field})
            continue
        socket_out = out if src[2] is None else src[2].get(out)
        socket_in = field if dst[1] is None else dst[1].get(field)
        if socket_out is None or socket_in is None:
            builder.dropped.append({'from': edge.get('source'), 'output': out, 'to': edge.get('target'), 'field': field})
            continue
        if dst[1] is None and socket_in not in [p['id'] for p in builder.nodes[dst[0]]['ports']['target']]:
            builder.nodes[dst[0]]['ports']['target'].append({'id': socket_in, 'type': 'any'})
        wires.append((src[0], socket_out, dst[0], socket_in))
    builder.connect(wires)
    digest = hashlib.sha1(json.dumps(graph, sort_keys=True).encode()).hexdigest()[:16]
    return builder.document(str(flow.get('name') or 'Langflow flow')[:200], identity or 'langflow-' + digest, {})


# ------------------------------------------------------------------ skills.sh --
def import_skill_md(text, identity=None, origin=''):
    """A skills.sh SKILL.md -> an ArchHub skill: Task input -> Agent carrying the instructions."""
    match = re.match(r'\A---\r?\n(.*?)\r?\n---(?:\r?\n|$)(.*)\Z', str(text), re.S)
    if not match or not match[2].strip():
        raise ValueError('SKILL.md needs YAML name and description frontmatter and instructions')
    # Top-level "key: value" lines only; nested metadata stays in the text, nothing is evaluated.
    manifest = {}
    for line in match[1].splitlines():
        held = re.match(r'^([A-Za-z][\w-]*):\s*(.*)$', line)
        if held and held[2].strip():
            manifest[held[1]] = held[2].strip().strip('"\'')
    if not manifest.get('name') or not manifest.get('description'):
        raise ValueError('SKILL.md frontmatter needs name and description')
    from .agent_runtime_registry import RUNTIMES
    agent = next((row.get('label', key) for key, row in RUNTIMES.items()), 'Claude Code')
    skill = re.sub(r'[^A-Za-z0-9_-]+', '-', manifest['name']).strip('-')[:100] or 'skill'
    source = {'format': 'skills.sh', 'type': 'SKILL.md', 'id': manifest['name'], 'origin': str(origin)[:500]}
    builder = _Builder('skills.sh')
    builder.add(_node('sk-task', 'param.value', 'Task', {'type': 'text', 'value': ''}, (0, 0), {**source, 'part': 'task'},
                      sources=['value']))
    builder.add(_node('sk-agent', 'thing.agent', manifest['name'], {'agent': agent, 'instructions': str(text)}, (320, 0),
                      {**source, 'part': 'agent'}, sources=['result', 'messages'], targets=['task', 'files']))
    builder.add(_node('sk-about', 'note', 'About this skill', {'text': '%s\n\nLicence: %s\nSource: %s' % (
        manifest['description'], manifest.get('license', 'not stated'), origin or 'skills.sh')}, (0, -160), {**source, 'part': 'note'}))
    builder.connect([('sk-task', 'value', 'sk-agent', 'task')])
    return builder.document(manifest['name'], identity or 'skill-' + skill, {'description': manifest['description']})


# ------------------------------------------------------------------ one door --
def import_text(text, name=''):
    """Detect the format from the content: (kind, document). kind is 'flow' or 'skill'."""
    if str(name).lower().endswith('.md') or str(text).lstrip().startswith('---'):
        return 'skill', import_skill_md(text, origin=name)
    try:
        value = json.loads(text)
    except ValueError as error:
        raise ValueError('Choose a Node-RED or Langflow .json flow, or a SKILL.md file') from error
    if isinstance(value, dict) and isinstance(value.get('data'), dict) and 'edges' in value['data']:
        return 'flow', import_langflow(value)
    return 'flow', import_node_red(value)


def reimport(existing, imported):
    """Re-import updates nodes in place (same source id -> same node id, position kept); the
    founder's own nodes and wires stay; imported nodes gone from the source are removed."""
    if not existing:
        return imported
    held = {n['id']: n for n in existing['nodes']}
    nodes = [n for n in existing['nodes'] if not n.get('source')]
    for node in imported['nodes']:
        if node['id'] in held:
            node['position'] = held[node['id']]['position']
        nodes.append(node)
    ids = {n['id'] for n in nodes}
    taken = {(w['to']['node'], w['to']['socket']) for w in imported['wires']}
    own = [w for w in existing['wires'] if not w['id'].startswith('w-') and w['from']['node'] in ids
           and w['to']['node'] in ids and (w['to']['node'], w['to']['socket']) not in taken]
    return {**existing, 'title': imported['title'], 'nodes': nodes, 'wires': imported['wires'] + own,
            'properties': {**existing.get('properties', {}), 'import': imported['properties']['import']}}
