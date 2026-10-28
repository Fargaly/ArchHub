"""Canvas tools for every agent (any provider) on the archhub-agent MCP connector.

The canvas is the workspace where agents build the deliverable. Each tool reads or
edits one .archhub file through canvas_documents.edit(): the same lock, the same
attributed history and the same parametric solve the founder's window uses. When
the app has that file open, the window picks the edit up on its next file check.
"""
from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from mcp.server.fastmcp import Context


def _who(ctx):
    try:
        info = ctx.session.client_params.clientInfo
        return 'agent:' + info.name
    except Exception:  # noqa: BLE001 - a client that sends no name is still attributed
        return 'agent'


def _path(path):
    from .session_files import local_path
    return str(local_path(path))


def _summary(document, solved=None):
    nodes = [{'id': n['id'], 'type': n['type'], 'title': n.get('title', ''), 'params': n['params'],
              'position': n['position'], 'status': (n.get('result') or {}).get('status', 'Idle'),
              'stale': (n.get('result') or {}).get('status') == 'Out of date',
              'output': (n.get('result') or {}).get('output', {}), 'error': (n.get('result') or {}).get('error', '')}
             for n in document['nodes']]
    from .session_files import catalogue
    ports = {item['id']: item['ports'] for item in catalogue()}
    from .node_params import bound_value, ports as node_ports, PARAM_ENGINE
    for node, source in zip(nodes, document['nodes']):
        held = node_ports(source, ports.get(source.get('item')) or {})
        node['sockets'] = {'in': [p['id'] + ':' + p.get('type', 'any') for p in held['target']],
                           'out': [p['id'] + ':' + p.get('type', 'any') for p in held['source']]}
        if source.get('paramDefs'):
            node['param_types'] = {d['id']: d['type'] for d in source['paramDefs']}
        if source['type'] == 'data.dataset':
            node['fields'] = source.get('paramDefs', [])
            node['records'] = source.get('records', [])
        if source['type'] == PARAM_ENGINE and source.get('bind'):
            node['params'] = {**node['params'], 'value': bound_value(document, source)}
            node['bound_to'] = source['bind']
    history = document.get('properties', {}).get('history', [])
    return {'title': document['title'], 'revision': document.get('properties', {}).get('revision', 0), 'nodes': nodes,
            'wires': [{'id': w['id'], 'from': w['from']['node'] + '.' + w['from']['socket'],
                       'to': w['to']['node'] + '.' + w['to']['socket']} for w in document['wires']],
            'last_edits': [{k: h[k] for k in ('revision', 'by', 'op')} for h in history[-5:]],
            **({'solve_ms': solved['ms']} if solved else {})}


def _item(kind):
    from .session_files import catalogue
    items = catalogue()
    found = [i for i in items if i['id'] == kind] or [i for i in items if i['engine'] == kind and not i.get('hidden')] \
        or [i for i in items if i['title'].casefold() == str(kind).casefold()]
    if not found or found[0].get('noEngine'):
        raise ValueError('Unknown or non-executable node type: %s. Use library.search.' % kind)
    return found[0]


def _end(document, ref):
    node, _, socket = str(ref).partition('.')
    match = [n for n in document['nodes'] if n['id'] == node or n['id'].startswith(node) or n.get('title') == node]
    if len(match) != 1 or not socket:
        raise ValueError('Name an end as <node id or title>.<socket>: %s' % ref)
    return match[0], socket


def register_canvas_tools(server):
    from . import canvas_documents as docs

    @server.tool(name='canvas.list_open')
    def canvas_list_open() -> dict:
        """The .archhub file open in the ArchHub window now, then recent files."""
        from .session_files import SessionFiles
        return {'files': SessionFiles().open_files()}

    @server.tool(name='canvas.new')
    def canvas_new(path: str, ctx: Context, title: str = '') -> dict:
        """Create a new empty .archhub workflow at an absolute path."""
        if Path(path).exists():
            raise ValueError('A file already exists there; use canvas.open.')
        document, _ = docs.edit(_path(path), _who(ctx), 'new', lambda d: [], create_title=title or Path(path).stem)
        return _summary(document)

    @server.tool(name='canvas.open')
    def canvas_open(path: str) -> dict:
        """Open an .archhub file and return its nodes, sockets, wires, params and outputs."""
        return _summary(docs.read(_path(path)))

    @server.tool(name='canvas.read')
    def canvas_read(path: str) -> dict:
        """Read an .archhub file: nodes (sockets, params, outputs, stale flags), wires and last edits."""
        return _summary(docs.read(_path(path)))

    @server.tool(name='canvas.add_node')
    def canvas_add_node(path: str, type: str, ctx: Context, params: dict | None = None, x: float = 0, y: float = 0,
                        title: str = '') -> dict:
        """Add a Library node (id, engine or title from library.search) with optional params and position."""
        item = _item(type)
        node = {'id': str(uuid4()), 'type': item['engine'], 'item': item['id'], 'title': title or item['title'],
                'params': {**item['params'], **{k: v for k, v in (params or {}).items() if k in item['params']}},
                'position': {'x': float(x), 'y': float(y)}}
        def change(document):
            document['nodes'].append(node)
            return [node['id']]
        document, solved = docs.edit(_path(path), _who(ctx), 'add %s' % item['title'], change)
        return {'node': node['id'], **_summary(document, solved)}

    @server.tool(name='canvas.wire')
    def canvas_wire(path: str, source: str, target: str, ctx: Context) -> dict:
        """Wire <node>.<output socket> to <node>.<input socket>. One wire per input; cycles are refused."""
        def change(document):
            (a, out), (b, inp) = _end(document, source), _end(document, target)
            from .node_params import compatible, ports as node_ports
            ports_a = node_ports(a, _item(a.get('item') or a['type'])['ports'])
            ports_b = node_ports(b, _item(b.get('item') or b['type'])['ports'])
            outs = {p['id']: p.get('type', 'any') for p in ports_a['source']}
            ins = {p['id']: p.get('type', 'any') for p in ports_b['target']}
            if out not in outs or inp not in ins:
                raise ValueError('Unknown socket. Outputs: %s; inputs: %s' % (list(outs), list(ins)))
            if a['id'] in docs.downstream(document, [b['id']]):
                raise ValueError('Cycle detected: this wire would feed a node back into itself.')
            if not compatible(outs[out], ins[inp]):
                raise ValueError('Wrong type: a %s output cannot feed a %s input. Insert Convert.' % (outs[out], ins[inp]))
            document['wires'] = [w for w in document['wires'] if (w['to']['node'], w['to']['socket']) != (b['id'], inp)]
            document['wires'].append({'id': str(uuid4()), 'from': {'node': a['id'], 'socket': out}, 'to': {'node': b['id'], 'socket': inp}})
            return [b['id']]
        document, solved = docs.edit(_path(path), _who(ctx), 'wire %s -> %s' % (source, target), change)
        return _summary(document, solved)

    @server.tool(name='canvas.set_param')
    def canvas_set_param(path: str, node: str, key: str, value: str, ctx: Context) -> dict:
        """Set one parameter; downstream pure nodes re-solve at once, effect nodes become out of date."""
        def change(document):
            from .node_params import set_value
            held, _ = _end(document, node + '.x')
            changed = set_value(document, held['id'], key, value)
            docs.write_through(held, key, value)
            return changed
        document, solved = docs.edit(_path(path), _who(ctx), 'set %s.%s' % (node, key), change)
        return _summary(document, solved)

    @server.tool(name='canvas.add_param')
    def canvas_add_param(path: str, node: str, name: str, type: str, ctx: Context, value: str = '',
                         min: float | None = None, max: float | None = None, options: list[str] | None = None) -> dict:
        """Add a typed parameter to a node (number, integer, text, bool, list, file, path, color, enum, json)."""
        from .node_params import add_param
        document, solved = docs.edit(_path(path), _who(ctx), 'add parameter %s.%s' % (node, name),
            lambda d: add_param(d, _end(d, node + '.x')[0]['id'], name, type, value, min=min, max=max, options=options))
        return _summary(document, solved)

    @server.tool(name='canvas.promote_param')
    def canvas_promote_param(path: str, node: str, param: str, ctx: Context, demote: bool = False) -> dict:
        """Expose a parameter as a Parameter node (one shared value, typed output socket), or demote it back."""
        from .node_params import promote, demote as demote_param
        action = demote_param if demote else promote
        document, solved = docs.edit(_path(path), _who(ctx), '%s %s.%s' % ('demote' if demote else 'promote', node, param),
                                     lambda d: action(d, _end(d, node + '.x')[0]['id'], param))
        return _summary(document, solved)

    @server.tool(name='canvas.add_field')
    def canvas_add_field(path: str, dataset: str, name: str, type: str, ctx: Context, value: str = '',
                         unit: str = '', options: list[str] | None = None, show_as_node: bool = False) -> dict:
        """+Field: add a typed column to a dataset (creates the dataset when absent); show_as_node exposes it as a typed list node."""
        from . import node_datasets as ds
        def change(document):
            if not any(n['type'] == ds.DATASET_ENGINE and dataset in (n['id'], n.get('title')) for n in document['nodes']):
                ds.new_dataset(document, dataset)
            changed = ds.add_field(document, dataset, name, type, value, unit=unit, options=options)
            if show_as_node:
                field = ds._dataset(document, dataset)['paramDefs'][-1]['id']
                changed += ds.expose_field(document, dataset, field)
            return changed
        document, solved = docs.edit(_path(path), _who(ctx), 'add field %s.%s' % (dataset, name), change)
        return _summary(document, solved)

    @server.tool(name='canvas.add_record')
    def canvas_add_record(path: str, dataset: str, ctx: Context, cells: dict | None = None) -> dict:
        """+Record: add one row; cells are {field: value}, typed by their field, others take the default."""
        from .node_datasets import add_record
        document, solved = docs.edit(_path(path), _who(ctx), 'add record to %s' % dataset,
                                     lambda d: add_record(d, dataset, cells))
        return _summary(document, solved)

    @server.tool(name='canvas.set_cell')
    def canvas_set_cell(path: str, dataset: str, record: str, field: str, value: str, ctx: Context) -> dict:
        """Edit one cell (record = index or id); its field nodes and everything downstream re-solve at once."""
        from .node_datasets import set_cell
        document, solved = docs.edit(_path(path), _who(ctx), 'set %s[%s].%s' % (dataset, record, field),
                                     lambda d: set_cell(d, dataset, record, field, value))
        return _summary(document, solved)

    @server.tool(name='canvas.remove')
    def canvas_remove(path: str, item: str, ctx: Context) -> dict:
        """Remove a node (and its wires) or a wire by id."""
        def change(document):
            if any(w['id'] == item for w in document['wires']):
                target = next(w for w in document['wires'] if w['id'] == item)['to']['node']
                document['wires'] = [w for w in document['wires'] if w['id'] != item]
                return [target]
            held, _ = _end(document, item + '.x')
            after = [w['to']['node'] for w in document['wires'] if w['from']['node'] == held['id']]
            document['nodes'] = [n for n in document['nodes'] if n['id'] != held['id']]
            document['wires'] = [w for w in document['wires'] if held['id'] not in (w['from']['node'], w['to']['node'])]
            return after
        document, solved = docs.edit(_path(path), _who(ctx), 'remove %s' % item, change)
        return _summary(document, solved)

    @server.tool(name='canvas.run')
    def canvas_run(path: str, ctx: Context, node: str = '') -> dict:
        """Run the workflow (or up to one node), effects included, with their existing approvals."""
        from .enforce import guard_effect
        from .session_files import run_document
        def change(document):
            roots = [_end(document, node + '.x')[0]['id']] if node else None
            ran = run_document(document, invoke=guard_effect, roots=roots)
            for n in document['nodes']:
                if n['id'] in ran['results']:
                    n['result'] = {k: v for k, v in ran['results'][n['id']].items() if k in ('status', 'output', 'error', 'display')}
            return []
        document, _ = docs.edit(_path(path), _who(ctx), 'run' + (' to ' + node if node else ''), change, solve_changed=False)
        return _summary(document)

    @server.tool(name='canvas.save')
    def canvas_save(path: str, ctx: Context, save_as: str = '') -> dict:
        """Save (the file is already current) or save a copy to another absolute .archhub path."""
        from .session_files import write_document
        document = docs.read(_path(path))
        if save_as:
            write_document(_path(save_as), document)
        return {'saved': _path(save_as or path), 'revision': document.get('properties', {}).get('revision', 0)}

    @server.tool(name='canvas.undo')
    def canvas_undo(path: str, ctx: Context) -> dict:
        """Undo the newest edit in this file (by anyone); the undo is itself in the history."""
        document, solved = docs.undo_last(_path(path), _who(ctx))
        return _summary(document, solved)

    @server.tool(name='library.search')
    def library_search(query: str = '') -> dict:
        """Search node types: tools, data, shape, text, math, skills and app things (agents, models, connectors...)."""
        from .session_files import catalogue
        words = str(query).casefold().split()
        rows = [{'type': i['id'], 'title': i['title'], 'category': i['cat'], 'about': i.get('sub', ''),
                 'params': i['params'], 'inputs': [p['id'] for p in i['ports']['target']],
                 'outputs': [p['id'] for p in i['ports']['source']]}
                for i in catalogue() if not i.get('noEngine') and not i.get('hidden')
                and all(w in (i['id'] + ' ' + i['title'] + ' ' + i['cat'] + ' ' + i.get('sub', '')).casefold() for w in words)]
        return {'count': len(rows), 'items': rows[:40]}
