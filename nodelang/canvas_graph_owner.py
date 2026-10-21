"""Canvas graph operations over the ONE graph store (the universal CellStore).

Every operation composes an existing owner call; nothing here persists
anything itself. A flag, a wire rule, a schedule or a fork is a node or a
property Cell written through create_engine_node, create_universal_property,
edit_universal_property, connect_universal_roots or retract_universal_node.
The caller supplies the admitted store, registry and authentication context.
"""
from __future__ import annotations

import inspect
import json
import re

from . import universal_application as app
from .universal_cell import InvalidCell
from .universal_graphs import create_graph, open_graph
from .universal_pipeline import create_engine_node, retract_universal_node

SCHEDULE_ENGINE = "trigger.schedule"
CONVERTER_ENGINE = "data.convert"
MAX_IMPORT_NODES = 100
_HHMM = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")
_NOT_COPIED = {"title", "status", "definition", "version", "color", "position_x", "position_y",
               "placed", "last_run", "frozen", "pinned"}
_BOOL = {True: "true", False: "false"}


class CanvasRefused(InvalidCell):
    pass


class CanvasOwner:
    PUBLIC = ("add_graph", "update_graph", "remove_graph", "set_node_flags", "fork_node",
              "run_to_here", "trace_node", "add_schedule",
              "set_schedule_enabled", "set_schedule_time", "remove_schedule", "import_recipe",
              "export_recipe", "project_schedules", "save_skill", "list_skills", "open_skill",
              "read_company", "set_account_seats", "transfer_ownership", "sign_out_everywhere",
              "project_state", "add_interface_element", "save_graph_version", "restore_graph_version",
              "review_model", "update_review_issue", "mcp_servers", "discover_mcp_tools",
              "reconnect_mcp", "import_mcp_tool", "dismiss_suggestion",
              "community_state", "subscribe_community", "review_community_pattern", "import_mod_node",
              "set_port_visibility", "set_promoted_parameter", "add_file", "project_files",
              "library_ports", "add_compatible_node", "insert_convert")

    def __init__(self, store, registry, context):
        self.store, self.registry, self.context = store, registry, context

    def dispatch(self, name, args):
        if type(name) is not str or name not in self.PUBLIC or type(args) is not list:
            raise CanvasRefused("invalid canvas operation")
        function = getattr(self, name)
        try:
            inspect.signature(function).bind(*args)
        except TypeError:
            raise CanvasRefused("invalid canvas operation arguments") from None
        return function(*args)

    def canvas(self):
        return app.project_universal_canvas(
            self.store, self.registry, authentication_context=self.context)

    def project_state(self):
        root = self._project_owner()
        rows = self._rows(None, root) if root else {}
        return json.loads(rows.get('studio.projects', {}).get('value') or
                          '{"versions":[],"modelReview":{"operation":"","results":[],"issues":[]},"dismissed":[]}')

    def _save_projects(self, state):
        encoded = json.dumps(state, ensure_ascii=False)
        if len(encoded.encode('utf-8')) > 65536:
            raise CanvasRefused('Project history exceeds 64 KiB. Export versions before saving more.')
        root = self._project_owner()
        if root:
            self.set_property(root, 'studio.projects', encoded)
        else:
            create_engine_node(self.store, self.registry, title='Project history', engine='note',
                properties={'studio.projects': encoded}, authentication_context=self.context)
        return state

    def _project_owner(self):
        canvas = self.canvas()
        matches = [n['id'] for n in canvas['nodes'] if 'studio.projects' in self._rows(canvas, n['id'])]
        if len(matches) > 1:
            raise CanvasRefused('More than one node owns project history. Reconcile their versions before saving.')
        return matches[0] if matches else None

    def add_interface_element(self, kind):
        if kind not in ('Button', 'Card', 'Text'):
            raise CanvasRefused('Choose Button, Card or Text.')
        made = create_engine_node(self.store, self.registry, title=kind, engine='data.constant',
            properties={'element': kind, 'label': kind, 'value': kind, 'width': '160',
                        'height': '48', 'colour': '#3b82f6', 'enabled': 'true', 'action': 'Canvas'}, authentication_context=self.context)
        return {'id': made['root']}

    def project_files(self):
        from pathlib import Path
        canvas = self.canvas()
        result = []
        for node in canvas['nodes']:
            rows = self._rows(canvas, node['id'])
            if 'file_path' in rows:
                path = rows['file_path']['value']
                result.append({'id': node['id'], 'name': Path(path).name, 'path': path,
                               'kind': rows.get('record_kind', {}).get('value', 'Project file')})
        return result

    def add_file(self, path, kind='Project file'):
        from pathlib import Path
        from .pipeline_engines import _local_input_path
        path = str(Path(_local_input_path(path, label='project file')).resolve())
        if Path(path).suffix.lower() in {'.key', '.pem', '.env'} or Path(path).name.lower() == 'cloud.json':
            raise CanvasRefused('Credentials belong in Connections, not project file nodes.')
        if type(kind) is not str or not kind.strip() or len(kind) > 128:
            raise CanvasRefused('Choose a short project file kind.')
        existing = next((r for r in self.project_files() if r['path'] == path), None)
        if existing:
            return existing
        create_engine_node(self.store, self.registry, title=Path(path).name, engine='input.parameter',
            properties={'value': path, 'file_path': path, 'record_kind': kind}, authentication_context=self.context)
        return next(r for r in self.project_files() if r['path'] == path)

    def library_ports(self):
        from .universal_pipeline import read_engine_library
        self.canvas()
        result = [item for group in read_engine_library(self.store.snapshot()) or []
                  for item in group['items'] if not item.get('noEngine') and not item.get('children')]
        # Pipeline sockets use the assembly interface contract; logical hints can be absent.
        for item in result:
            item['ports'] = {side: [{**p, 'logical_type': p['type'],
                'type': p['type'] if p['type'] != 'unknown' else 'any',
                'contract': self.registry.assembly_protocol.root_id} for p in ports]
                for side, ports in item['ports'].items()}
        return result

    def add_compatible_node(self, endpoint, item, position):
        if type(endpoint) is not dict or set(endpoint) != {'id', 'side', 'port'} or endpoint['side'] not in ('in', 'out'):
            raise CanvasRefused('Choose an existing input or output socket.')
        canvas = self.canvas()
        original = self._node(canvas, endpoint['id'])
        side = 'source' if endpoint['side'] == 'out' else 'target'
        port = next((p for p in original['ports'] if p['id'] == endpoint['port'] and p['side'] == side), None)
        entry = next((r for r in self.library_ports() if r['id'] == item), None)
        if port is None or entry is None:
            raise CanvasRefused('The socket or Library entry changed. Refresh Canvas and retry.')
        other_side = 'target' if side == 'source' else 'source'
        value_type = port.get('value_type') or 'any'
        candidates = [p for p in entry['ports'][other_side] if p['type'] != 'unknown'
                      and (p['type'] == value_type or 'any' in (p['type'], value_type))]
        if not candidates:
            raise CanvasRefused('This Library node has no compatible declared socket.')
        if type(position) is not dict or set(position) != {'x', 'y'}:
            raise CanvasRefused('Choose a Canvas position for the new node.')
        made = create_engine_node(self.store, self.registry, title=entry['title'], engine=entry['engine'],
                                  item=entry['id'], properties={k: v for k, v in entry['params'].items() if k not in _NOT_COPIED}, x=position['x'], y=position['y'],
                                  authentication_context=self.context)['root']
        try:
            original_name = port.get('name') or port.get('label') or port['id']
            source, target = (endpoint['id'], made) if side == 'source' else (made, endpoint['id'])
            names = [original_name, candidates[0]['id']] if side == 'source' else [candidates[0]['id'], original_name]
            wire = self._connect(source, target, names)
        except Exception:
            retract_universal_node(self.store, self.registry, made, authentication_context=self.context)
            raise
        return {'id': made, 'wire': wire}

    def import_mod_node(self, identity, item):
        from .domains.selfext import mods_rows
        package = next((r for r in mods_rows(self.store)['rows'] if r['id'] == identity and r['enabled']), None)
        node = next((n for n in package['nodes'] if n['id'] == item), None) if package else None
        if node is None:
            raise CanvasRefused('Enable this installed package and choose one of its nodes.')
        made = create_engine_node(self.store, self.registry, title=node['title'], engine=node['behavior']['engine'],
                                  properties=node['params'], authentication_context=self.context)
        return {'id': made['root']}

    def set_port_visibility(self, root, port, value):
        canvas = self.canvas()
        node = self._node(canvas, root)
        if value not in ('Visible', 'Faint', 'Hidden') or port not in {p['id'] for p in node['ports']}:
            raise CanvasRefused('Select an existing socket and a listed visibility.')
        held = json.loads(self._rows(canvas, root).get('port_visibility', {}).get('value') or '{}')
        held[port] = value
        self.set_property(root, 'port_visibility', json.dumps(held))
        return held

    def set_promoted_parameter(self, root, key, values):
        canvas = self.canvas()
        self._node(canvas, root)
        if key not in self._rows(canvas, root) or type(values) is not dict or not values or set(values) - {'hidden', 'order', 'label'}:
            raise CanvasRefused('Select an existing parameter and its presentation fields.')
        if ('hidden' in values and type(values['hidden']) is not bool
                or 'order' in values and (type(values['order']) is not int or not 0 <= values['order'] <= 10000)
                or 'label' in values and (type(values['label']) is not str or len(values['label']) > 128)):
            raise CanvasRefused('Use a boolean visibility, a nonnegative order and a short label.')
        held = json.loads(self._rows(canvas, root).get('parameter_presentation', {}).get('value') or '{}')
        held[key] = {**held.get(key, {}), **values}
        self.set_property(root, 'parameter_presentation', json.dumps(held))
        return held

    def save_graph_version(self):
        from uuid import uuid4
        canvas, state = self.canvas(), self.project_state()
        recipe = self.export_recipe()
        nodes = [n for n in canvas['nodes'] if n['id'] != self._project_owner()]
        if len(recipe['nodes']) != len(nodes):
            raise CanvasRefused('This graph contains non-recipe nodes. Export Graph to preserve their full structure.')
        for item, node in zip(recipe['nodes'], nodes, strict=True):
            rows = self._rows(canvas, node['id'])
            item['params'].update({k: rows[k]['value'] for k in ('frozen', 'pinned') if k in rows})
        def socket_name(root, port):
            return next(p.get('name') or p.get('label') or p['id'] for p in self._node(canvas, root)['ports'] if p['id'] == port)
        node_ids = {n['id'] for n in nodes}
        recipe['wire_ports'] = [[socket_name(w['source'], w['source_interface']), socket_name(w['target'], w['target_interface'])]
                                for w in canvas['wires'] if w['source'] in node_ids and w['target'] in node_ids]
        row = {'id': uuid4().hex, 'name': 'Revision ' + str(self.store.revision),
               'revision': self.store.revision, **recipe,
               'positions': [[n['x'], n['y']] for n in nodes],
               'colors': [self._rows(canvas, n['id']).get('color', {}).get('value') for n in nodes]}
        state['versions'].append(row)
        self._save_projects(state)
        return row

    def restore_graph_version(self, identity):
        state = self.project_state()
        version = next((v for v in state['versions'] if v['id'] == identity), None)
        if version is None:
            raise CanvasRefused('Version no longer exists in this graph. Refresh history.')
        canvas = self.canvas()
        # Create first: a refused import must not discard the current graph.
        made = self.import_recipe({'nodes': version['nodes'], 'wires': version['wires'],
                                   'wire_ports': version.get('wire_ports')}, positions=version['positions'])
        for root, color in zip(made['nodes'], version.get('colors', [None] * len(made['nodes'])), strict=True):
            if color is not None:
                self.set_property(root, 'color', color)
        if canvas['nodes']:
            history_owner = self._project_owner()
            for node in canvas['nodes']:
                if node['id'] != history_owner:
                    retract_universal_node(self.store, self.registry, node['id'], authentication_context=self.context)
        return {'id': identity, **made}

    def review_model(self, operation):
        allowed = ('Startup Check', 'Naming Check', 'Model QA', 'Parameter Dictionary',
                   'Clash & Issues', 'Delivery Plan', 'IFC Export & Check', 'Library Admission')
        if operation not in allowed:
            raise CanvasRefused('Choose a listed model check.')
        canvas = self.canvas()
        # Host-specific checks must execute their configured node, never infer a host verdict.
        matches = [n for n in canvas['nodes'] if n['label'] == operation
                   and self._rows(canvas, n['id']).get('engine')]
        if len(matches) != 1:
            raise CanvasRefused('Add and configure one ' + operation +
                                ' check node on this canvas, then retry. No model check has run.')
        root = matches[0]['id']
        rows = self._rows(canvas, root)
        if 'timeout_seconds' not in rows:
            self.set_property(root, 'timeout_seconds', '180')
        seconds = float(self._rows(canvas, root)['timeout_seconds']['value'])
        if not 0 < seconds <= 3600:
            raise CanvasRefused('Set the check node timeout_seconds between 0 and 3600 seconds.')
        return {**self.run_to_here(root), 'wait_seconds': seconds}

    def update_review_issue(self, identity, values):
        state = self.project_state()
        issues = state['modelReview']['issues']
        issue = next((r for r in issues if r['id'] == identity), None)
        if issue is None or type(values) is not dict or not values or set(values) - {'type', 'owner', 'severity', 'status'}:
            raise CanvasRefused('Refresh the model check and choose an existing issue.')
        for key, choices in (('type', ('Discrepancy', 'Error', 'Clash', 'Missing')),
                             ('severity', ('Low', 'Normal', 'High')), ('status', ('Open', 'In review', 'Closed'))):
            if key in values and values[key] not in choices:
                raise CanvasRefused('Choose a listed issue ' + key + '.')
        if any(type(v) is not str or len(v) > 256 for v in values.values()):
            raise CanvasRefused('Issue fields must be text within 256 characters.')
        issue.update(values)
        self._save_projects(state)
        return issue

    def record_model_review(self, operation, result):
        state = self.project_state()
        issues = []
        for root, output in result.get('outputs', {}).items():
            output = output if isinstance(output, dict) else {}
            for index, issue in enumerate(output.get('issues', [])):
                if not isinstance(issue, dict) or not isinstance(issue.get('title'), str):
                    raise CanvasRefused('The check returned malformed issues. Inspect its raw run result.')
                issues.append({**issue, 'id': root + ':' + str(index), 'source': root})
        state['modelReview'] = {'operation': operation, 'revision': result['revision'],
            'results': [{'check': operation, 'status': 'Needs review' if result.get('pending') else 'Run returned',
                         'detail': json.dumps({'outputs': result.get('outputs', {}), 'results': result.get('results', {})}), 'revision': result['revision']}],
            'issues': issues}
        self._save_projects(state)
        return {'run': result, 'modelReview': state['modelReview']}

    def mcp_servers(self):
        from .cell_mcp_broker import list_mcp_servers, list_mcp_tools, list_mcp_negotiations
        snapshot = self.store.snapshot()
        self.canvas()
        protocol = self.registry.mcp_broker_protocol
        tools = list_mcp_tools(snapshot, protocol)
        negotiations = {n.root_id: n for n in list_mcp_negotiations(snapshot, protocol)}
        import time
        result = []
        for server in list_mcp_servers(snapshot, protocol):
            admitted = [t for t in tools if negotiations[t.negotiation_root].server_root == server.root_id
                        and negotiations[t.negotiation_root].expires_at > time.time()]
            result.append({'id': server.root_id, 'name': server.transport,
                           'status': 'Negotiated' if admitted else 'Connection failed',
                           'tools': [{'id': t.root_id, 'name': t.root_id,
                                      'schemaDigest': t.schema_digest} for t in admitted]})
        return result

    def discover_mcp_tools(self, identity, kind='Tools'):
        if kind != 'Tools':
            raise CanvasRefused('This broker admits tools. Open the server resource or prompt node for other content.')
        server = next((s for s in self.mcp_servers() if s['id'] == identity), None)
        if server is None:
            raise CanvasRefused('Connect the MCP server in Connections, then refresh Library.')
        return server

    def reconnect_mcp(self, identity):
        server = self.discover_mcp_tools(identity)
        if server['status'] == 'Connection failed':
            raise CanvasRefused('The MCP negotiation expired. Reconnect its existing agent in Connections to negotiate fresh tools, then retry.')
        return server

    def import_mcp_tool(self, identity, tool):
        server = self.discover_mcp_tools(identity)
        if tool not in {t['id'] for t in server['tools']}:
            raise CanvasRefused('Tool negotiation changed. Discover tools again before importing.')
        raise CanvasRefused('Open this admitted tool in its Workshop work and request execution there; this build has no executable canvas tool adapter.')

    def dismiss_suggestion(self, identity):
        canvas, state = self.canvas(), self.project_state()
        self._node(canvas, identity)
        if identity not in state['dismissed']:
            state['dismissed'].append(identity)
            self._save_projects(state)
        return {'id': identity, 'status': 'Dismissed'}

    def community_state(self):
        from . import cell_brain_community as community
        self.canvas()
        snapshot = self.store.snapshot()
        incoming = (*community.quarantine(snapshot), *community.admitted(snapshot), *community.rejected(snapshot))
        peers = set(community.peers(snapshot)) | {r.peer_root for r in incoming}
        return {'peers': [{'id': p, 'name': p, 'subscribed': p in community.subscriptions(snapshot)} for p in sorted(peers)],
                'patterns': [{'id': r.root_id, 'title': r.claim[:80], 'description': r.claim,
                              'source': r.peer_root, 'status': {community.QUARANTINED: 'Quarantine',
                              community.ADMITTED: 'Accepted', community.REJECTED: 'Rejected'}[r.verdict]}
                             for r in incoming]}

    def subscribe_community(self, identity):
        from . import cell_brain_community as community
        self.canvas()
        if identity not in {p['id'] for p in self.community_state()['peers']}:
            raise CanvasRefused('Choose an existing community peer, then retry.')
        function = community.unsubscribe if identity in community.subscriptions(self.store.snapshot()) else community.subscribe
        function(self.store, identity)
        return self.community_state()

    def review_community_pattern(self, identity, decision):
        from . import cell_brain_community as community
        state = self.community_state()
        row = next((r for r in state['patterns'] if r['id'] == identity), None)
        if row is None or decision not in ('Accept', 'Quarantine', 'Reject', 'Recheck'):
            raise CanvasRefused('Choose an existing pattern and a listed review decision.')
        if decision == 'Recheck':
            raise CanvasRefused('Request a fresh evidence check from this pattern in Workshop before judging again.')
        if decision in ('Accept', 'Reject'):
            community.judge(self.store, identity, admit=decision == 'Accept')
        elif row['status'] != 'Quarantine':
            raise CanvasRefused('This pattern already has a final judgement. Review a fresh incoming claim.')
        return self.community_state()

    def _node(self, canvas, root):
        for node in canvas["nodes"]:
            if node["id"] == root:
                return node
        raise CanvasRefused("that node is not on this canvas")

    def _rows(self, canvas, owner):
        from .universal_pipeline import _owner_properties
        held = _owner_properties(self.store.snapshot(), self.registry).get(owner) or {}
        return {label: {"relation": relation, "value": value}
                for label, (relation, value) in held.items()}

    def set_property(self, owner, label, value, canvas=None):
        row = self._rows(canvas or self.canvas(), owner).get(label)
        if row is None:
            app.create_universal_property(
                self.store, self.registry, owner, label, value,
                authentication_context=self.context)
        elif row["value"] != value:
            app.edit_universal_property(
                self.store, self.registry, row["relation"], value,
                authentication_context=self.context)
        return value

    def _flag(self, owner, label, value, canvas=None):
        if type(value) is not bool:
            raise CanvasRefused("%s must be true or false" % label)
        return self.set_property(owner, label, _BOOL[value], canvas)

    # ---- graphs -------------------------------------------------------
    def add_graph(self, title):
        return create_graph(self.store, self.registry, title,
                            authentication_context=self.context)["graph"]

    def _at_top(self):
        return open_graph(self.store, self.registry, self.registry.canvas_root,
                          authentication_context=self.context)

    def update_graph(self, root, name=None, pinned=None):
        self._at_top()
        canvas = self.canvas()
        self._node(canvas, root)
        app.select_universal_root(self.store, self.registry, root,
                                  authentication_context=self.context)
        if name is not None:
            if type(name) is not str or not name.strip():
                raise CanvasRefused("graph name is empty")
            self.set_property(root, "title", name.strip())
        if pinned is not None:
            self._flag(root, "pinned", pinned)
        rows = self._rows(self.canvas(), root)
        return {"id": root, "name": rows["title"]["value"],
                "pinned": rows.get("pinned", {}).get("value") == "true"}

    def remove_graph(self, root):
        if root == self.registry.canvas_root:
            raise CanvasRefused("the application canvas cannot be removed")
        self._at_top()
        return retract_universal_node(self.store, self.registry, root,
                                      authentication_context=self.context)

    # ---- nodes --------------------------------------------------------
    def set_node_flags(self, root, frozen=None, pinned=None):
        canvas = self.canvas()
        self._node(canvas, root)
        for label, value in (("frozen", frozen), ("pinned", pinned)):
            if value is not None:
                self._flag(root, label, value, canvas)
                canvas = self.canvas()
        rows = self._rows(canvas, root)
        return {"id": root, **{k: rows.get(k, {}).get("value") == "true"
                               for k in ("frozen", "pinned")}}

    def fork_node(self, root):
        canvas = self.canvas()
        node = self._node(canvas, root)
        rows = self._rows(canvas, root)
        engine = (rows.get("engine") or {}).get("value", "").strip()
        if not engine:
            raise CanvasRefused("only an engine node can be forked")
        params = {label: row["value"] for label, row in rows.items()
                  if label not in _NOT_COPIED and label != "engine"}
        created = create_engine_node(
            self.store, self.registry,
            title=(rows["title"]["value"] + " copy")[:80], engine=engine,
            x=node["x"] + 40.0, y=node["y"] + 40.0, properties=params,
            authentication_context=self.context)
        return {"id": created["root"], "forked_from": root, "engine": engine}

    def _connect(self, source, target, names=None):
        canvas = self.canvas()

        def port(root, side, name):
            return next(p["id"] for n in canvas["nodes"] if n["id"] == root
                        for p in n["ports"] if p["side"] == side and (p.get("mode") == "connection" or name is not None and p.get('connectable') is True)
                        and (name is None or name == (p.get('name') or p.get('label') or p['id'])))
        try:
            out, into = port(source, "source", names[0] if names else None), port(target, "target", names[1] if names else None)
        except StopIteration:
            raise CanvasRefused("a node has no free socket to connect") from None
        return app.connect_universal_roots(
            self.store, self.registry, source, target,
            source_interface=out, target_interface=into,
            authentication_context=self.context)[0]

    def insert_convert(self, wire):
        canvas = self.canvas()
        found = next((w for w in canvas['wires'] if w['id'] == wire), None) if isinstance(wire, str) else None
        if found is None and isinstance(wire, dict) and {'from', 'to', 'fromPort', 'toPort'} <= set(wire):
            found = {'source': wire['from'], 'target': wire['to'], 'source_interface': wire['fromPort'], 'target_interface': wire['toPort']}
        if found is None:
            raise CanvasRefused('The wire changed. Select its current sockets and retry.')
        source, target = self._node(canvas, found['source']), self._node(canvas, found['target'])
        source_port = next((p for p in source['ports'] if p['id'] == found['source_interface']), None)
        target_port = next((p for p in target['ports'] if p['id'] == found['target_interface']), None)
        if source_port is None or target_port is None:
            raise CanvasRefused('The wire sockets changed. Refresh Canvas before inserting Convert.')
        target_type = target_port.get('value_type') or 'any'
        if target_type not in ('any', 'text', 'number', 'boolean', 'list', 'object'):
            raise CanvasRefused('This target type needs its domain converter: ' + str(target_type))
        converter = create_engine_node(self.store, self.registry, title='Convert', engine=CONVERTER_ENGINE,
            x=(source['x'] + target['x']) / 2, y=(source['y'] + target['y']) / 2,
            properties={'target_type': target_type}, authentication_context=self.context)['root']
        removed = False
        try:
            first = self._connect(source['id'], converter, [source_port['name'], 'in'])
            if found.get('id'):
                app.disconnect_universal_connection(self.store, self.registry, found['id'], authentication_context=self.context)
                removed = True
            second = self._connect(converter, target['id'], ['out', target_port['name']])
        except Exception:
            retract_universal_node(self.store, self.registry, converter, authentication_context=self.context)
            if removed:
                self._connect(source['id'], target['id'], [source_port['name'], target_port['name']])
            raise
        return {'converter': converter, 'wires': [first, second], 'replaced': found.get('id')}

    # ---- run / trace --------------------------------------------------
    def _upstream(self, canvas, root):
        incoming = {}
        for wire in canvas["wires"]:
            incoming.setdefault(wire["target"], []).append(wire["source"])
        order, seen = [], set()

        def visit(current):
            if current in seen:
                return
            seen.add(current)
            for source in incoming.get(current, ()):
                visit(source)
            order.append(current)

        visit(root)
        return order

    def run_to_here(self, root):
        canvas = self.canvas()
        self._node(canvas, root)
        order = self._upstream(canvas, root)
        frozen = [r for r in order if self._rows(canvas, r).get("frozen", {}).get("value") == "true"]
        return {"roots": [r for r in order if r not in frozen], "frozen_kept": frozen}

    def trace_node(self, root, direction):
        if direction not in ("back", "forward"):
            raise CanvasRefused("direction must be back or forward")
        canvas = self.canvas()
        self._node(canvas, root)
        near, far = ("target", "source") if direction == "back" else ("source", "target")
        seen, queue = [], [root]
        while queue:
            current = queue.pop(0)
            for wire in canvas["wires"]:
                if wire[near] == current and wire[far] not in seen and wire[far] != root:
                    seen.append(wire[far])
                    queue.append(wire[far])
        titles = {n["id"]: n["label"] for n in canvas["nodes"]}
        return [{"id": r, "title": titles.get(r, r)} for r in seen]

    # ---- recurring schedule: a trigger.schedule node wired to its target
    def add_schedule(self, target, time="08:00"):
        if not _HHMM.match(str(time)):
            raise CanvasRefused("schedule time must be HH:MM")
        canvas = self.canvas()
        scope = canvas.get('scope', {}).get('current') or canvas.get('root') or self.registry.canvas_root
        if target == scope:
            runnable = {n['id'] for n in canvas['nodes']
                        if self._rows(canvas, n['id']).get('engine', {}).get('value') not in (None, SCHEDULE_ENGINE)}
            outgoing = {w['source'] for w in canvas['wires'] if w['target'] in runnable}
            targets = sorted(runnable - outgoing)
        else:
            targets = target if type(target) is list else [target]
        if not targets or len(targets) > MAX_IMPORT_NODES:
            raise CanvasRefused('choose at least one runnable target before adding a schedule')
        nodes = [self._node(canvas, root) for root in targets]
        node = nodes[0]
        created = create_engine_node(
            self.store, self.registry, title="Daily " + time, engine=SCHEDULE_ENGINE,
            x=node["x"] - 220.0, y=node["y"],
            properties={"time": time, "enabled": "true", "recurrence": "daily"},
            authentication_context=self.context)["root"]
        for root in targets:
            self._connect(created, root)
        return {"id": created, "target": target, "time": time, "enabled": True}

    def _schedule(self, canvas, schedule):
        rows = self._rows(canvas, schedule)
        if (rows.get("engine") or {}).get("value") != SCHEDULE_ENGINE:
            raise CanvasRefused("that is not a schedule node")
        return rows

    def set_schedule_enabled(self, schedule, enabled):
        canvas = self.canvas()
        self._schedule(canvas, schedule)
        self._flag(schedule, "enabled", enabled, canvas)
        if enabled:
            self.set_property(schedule, 'last_attempt', '')
        return {"id": schedule, "enabled": enabled}

    def set_schedule_time(self, schedule, time):
        if not _HHMM.match(str(time)):
            raise CanvasRefused("schedule time must be HH:MM")
        canvas = self.canvas()
        self._schedule(canvas, schedule)
        self.set_property(schedule, "time", time, canvas)
        self.set_property(schedule, 'last_attempt', '')
        return {"id": schedule, "time": time}

    def remove_schedule(self, schedule):
        self._schedule(self.canvas(), schedule)
        return retract_universal_node(self.store, self.registry, schedule,
                                      authentication_context=self.context)

    def due_schedules(self, now):
        """Enabled schedules whose time has passed today and have not run today."""
        canvas, today, hhmm = self.canvas(), now.strftime("%Y-%m-%d"), now.strftime("%H:%M")
        due = []
        for node in canvas["nodes"]:
            rows = self._rows(canvas, node["id"])
            if (rows.get("engine") or {}).get("value") != SCHEDULE_ENGINE:
                continue
            if (rows.get("enabled") or {}).get("value") == "true" \
                    and (rows.get("time") or {}).get("value", "99:99") <= hhmm \
                    and (rows.get("last_run") or {}).get("value") != today:
                if (rows.get('last_attempt') or {}).get('value') != today:
                    due.append(node["id"])
        return due

    def mark_schedule_ran(self, schedule, now):
        return self.set_property(schedule, "last_run", now.strftime("%Y-%m-%d"))

    # ---- graph import (recipe: nodes with engine/title/params, wires as index pairs)
    def import_recipe(self, recipe, positions=None):
        if isinstance(recipe, str):
            if len(recipe.encode('utf-8')) > 262144:
                raise CanvasRefused('recipe exceeds 256 KiB; split it before importing')
            import yaml
            try:
                recipe = yaml.safe_load(recipe)
            except yaml.YAMLError as error:
                raise CanvasRefused('invalid recipe YAML: %s' % error) from None
        nodes = recipe.get("nodes") if isinstance(recipe, dict) else None
        wires = recipe.get("wires", []) if isinstance(recipe, dict) else None
        if type(nodes) is not list or not nodes or type(wires) is not list:
            raise CanvasRefused("recipe needs a nodes list and a wires list")
        if len(nodes) > MAX_IMPORT_NODES:
            raise CanvasRefused("a recipe holds at most %d nodes" % MAX_IMPORT_NODES)
        import math
        if positions is not None and (type(positions) is not list or len(positions) != len(nodes) or any(
                type(p) is not list or len(p) != 2 or any(type(v) not in (int, float) or not math.isfinite(v) for v in p)
                for p in positions)):
            raise CanvasRefused('Saved positions are invalid. Choose another graph version.')
        wire_ports = recipe.get('wire_ports')
        if wire_ports is not None and (type(wire_ports) is not list or len(wire_ports) != len(wires) or any(
                type(p) is not list or len(p) != 2 or any(type(v) is not str or not v for v in p) for p in wire_ports)):
            raise CanvasRefused('Saved wire sockets are invalid. Choose another graph version.')
        for pair in wires:
            if (type(pair) is not list or len(pair) != 2
                    or not all(type(i) is int and 0 <= i < len(nodes) for i in pair)):
                raise CanvasRefused("a wire must name two node positions in the recipe")
        from .library_engines import engine_runs
        from .pipeline_engines import PIPELINE_ENGINES
        for item in nodes:
            if not isinstance(item, dict) or not engine_runs(str(item.get("engine", "")), PIPELINE_ENGINES):
                raise CanvasRefused("recipe names an engine this app does not run: %r"
                                    % (item.get("engine") if isinstance(item, dict) else item))
            if (set(item) - {'engine', 'title', 'params'}
                    or type(item.get('params', {})) is not dict
                    or any(type(k) is not str or not k.strip() or type(v) not in (str, int, float, bool)
                           for k, v in item.get('params', {}).items())):
                raise CanvasRefused('recipe parameters must be named scalar values')
        roots = []
        try:
            for index, item in enumerate(nodes):
                roots.append(create_engine_node(
                    self.store, self.registry, title=str(item.get("title") or item["engine"]),
                    engine=item["engine"], x=positions[index][0] if positions is not None else 240.0 + 260.0 * (index % 4),
                    y=positions[index][1] if positions is not None else 200.0 + 160.0 * (index // 4),
                    properties=item.get("params") or {}, authentication_context=self.context)["root"])
            made = [self._connect(roots[a], roots[b], wire_ports[i] if wire_ports is not None else None)
                    for i, (a, b) in enumerate(wires)]
        except Exception:
            for root in reversed(roots):
                retract_universal_node(self.store, self.registry, root, authentication_context=self.context)
            raise
        return {"nodes": roots, "wires": made}

    def export_recipe(self):
        canvas = self.canvas()
        nodes, indexes = [], {}
        for node in canvas['nodes']:
            rows = self._rows(canvas, node['id'])
            if 'studio.projects' in rows:
                continue
            engine = rows.get('engine', {}).get('value')
            if not engine:
                continue
            indexes[node['id']] = len(nodes)
            nodes.append({'engine': engine, 'title': node['label'], 'params': {
                k: row['value'] for k, row in rows.items()
                if k not in _NOT_COPIED and k != 'engine'}})
        wires = [[indexes[w['source']], indexes[w['target']]] for w in canvas['wires']
                 if w['source'] in indexes and w['target'] in indexes]
        return {'nodes': nodes, 'wires': wires}

    def project_schedules(self):
        canvas, result = self.canvas(), []
        for node in canvas['nodes']:
            rows = self._rows(canvas, node['id'])
            if rows.get('engine', {}).get('value') == SCHEDULE_ENGINE:
                result.append({'id': node['id'], 'title': node['label'],
                               'time': rows.get('time', {}).get('value', ''),
                               'enabled': rows.get('enabled', {}).get('value') == 'true'})
        return result

    def tick_schedules(self, now, run, lock=None):
        """Run through the caller's admitted pipeline; never mark pending work done."""
        from contextlib import nullcontext
        lock = lock or nullcontext()
        results = []
        with lock:
            due = self.due_schedules(now)
        for schedule in due:
            with lock:
                if schedule not in self.due_schedules(now):
                    continue
                canvas = self.canvas()
                targets = [w['target'] for w in canvas['wires'] if w['source'] == schedule]
                if not targets:
                    raise CanvasRefused('schedule has no target; connect it to a runnable node')
                downstream = [row['id'] for row in self.trace_node(schedule, 'forward')]
                targets = list(dict.fromkeys(root for target in downstream
                    for root in self._upstream(canvas, target)))
                # Persist before effects: a timeout or restart must never replay uncertain work.
                self.set_property(schedule, 'last_attempt', now.strftime('%Y-%m-%d'))
            result = run(targets)
            if result.get('pending') or result.get('ok') is False or not result.get('ran'):
                raise CanvasRefused('scheduled run needs attention; review its result, then re-enable the schedule: %s' % json.dumps(result))
            with lock:
                self.mark_schedule_ran(schedule, now)
            results.append({'id': schedule, 'result': result})
        return results

    def save_skill(self, name):
        from uuid import uuid4
        from .cell_brain_skills import mint_skill
        if type(name) is not str or not name.strip() or len(name) > 128:
            raise CanvasRefused('name the skill using 1 to 128 characters')
        recipe = self.export_recipe()
        if not recipe['nodes']:
            raise CanvasRefused('add runnable nodes before saving a skill')
        scope = self.canvas().get('scope', {}).get('current') or self.registry.canvas_root
        root = mint_skill(self.store, self.registry.assembly_protocol,
                          skill_id='app:skill:' + uuid4().hex, name=name.strip(),
                          purpose=json.dumps({'name': name.strip(), 'recipe': recipe}),
                          learned_from=(scope,))
        return next(row for row in self.list_skills() if row['id'] == root)

    def list_skills(self):
        from .cell_brain_skills import recall_skills
        self.canvas()  # Validate the current caller before reading its library.
        result = []
        for skill in recall_skills(self.store.snapshot(), self.registry.assembly_protocol, '',
                                   released_only=False):
            try:
                purpose = json.loads(skill.purpose)
            except (ValueError, TypeError):
                continue
            if not isinstance(purpose, dict) or not isinstance(purpose.get('recipe'), dict):
                continue
            result.append({'id': skill.root_id, 'title': skill.name, 'runs': None,
                           'chain': [n['title'] for n in purpose['recipe']['nodes']],
                           'recipe': purpose['recipe'], 'status': 'Draft'})
        return result

    def open_skill(self, root):
        skill = next((row for row in self.list_skills() if row['id'] == root), None)
        if skill is None:
            raise CanvasRefused('skill no longer exists; refresh the Library')
        return self.import_recipe(skill['recipe'])

    def _company_request(self, method, path, body=None):
        from . import cloud_signin
        self.canvas()
        session = cloud_signin.read_cloud_session(cloud_signin.cloud_session_path())
        token = session.get('token')
        if not token:
            raise CanvasRefused('Sign in from Account, then retry this office action.')
        status, answer = cloud_signin.http_json(method, cloud_signin.pinned_base(session) + path,
            body=body, headers={'Authorization': 'Bearer ' + token})
        if status < 200 or status >= 300:
            detail = answer.get('detail') or answer.get('error') or 'office request refused'
            raise CanvasRefused('Office action refused (%s): %s. Refresh Account and retry.' % (status, detail))
        return answer

    def read_company(self):
        from urllib.parse import quote
        listing = self._company_request('GET', '/v1/companies/mine')
        current = next((c for c in listing.get('companies', ()) if c.get('is_current')), None)
        if current is None:
            raise CanvasRefused('Select an office in Account before changing its seats or ownership.')
        return self._company_request('GET', '/v1/companies/' + quote(current['id'], safe=''))

    def set_account_seats(self, seats, company_id):
        from urllib.parse import quote
        if type(seats) is not int or not 1 <= seats <= 100000:
            raise CanvasRefused('Office seats must be a whole number between 1 and 100000.')
        company = self.read_company()
        if company['id'] != company_id:
            raise CanvasRefused('The selected office changed. Refresh its account and confirm the seat change again.')
        self._company_request('POST', '/v1/companies/' + quote(company['id'], safe='') + '/seats', {'seats': seats})
        return self.read_company()

    def transfer_ownership(self, user, company_id):
        from urllib.parse import quote
        company = self.read_company()
        if company['id'] != company_id:
            raise CanvasRefused('The selected office changed. Refresh its account and review the new owner again.')
        if type(user) is not str or user not in {m['user_id'] for m in company['members']}:
            raise CanvasRefused('Choose an existing member of this office as the new owner.')
        self._company_request('POST', '/v1/companies/' + quote(company['id'], safe='') + '/transfer-ownership',
                              {'new_owner_user_id': user})
        return self.read_company()

    def sign_out_everywhere(self):
        from . import cloud_signin
        answer = self._company_request('POST', '/v1/auth/logout', {'all_sessions': True})
        cloud_signin.sign_out()
        return answer
