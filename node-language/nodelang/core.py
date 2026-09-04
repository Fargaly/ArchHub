"""nodelang.core -- THE ONE TABLE (SPEC.md sections 1, 2, 19 forcing).

Ground-up build. No imports from any legacy application or runtime. Optional
host capabilities terminate at explicit floor adapters.

The law (SPEC section 2 / section 19):
    There is ONE node table: ``Store.nodes`` = {node_id -> node}.
    EVERY thing -- value, op, wire, group, param, session, ui element,
    ai proposal, secret reference, history entry -- is an instance of the
    ONE node shape stored in that ONE table. ``kind`` is a STRING FIELD on
    the shape, never a subclass with its own storage. No second container,
    no special-cased edge list, no meta-layer.

The ONE shape (a plain dict, validated by ``validate_node``):
    {
      'id':        str            # key in the one table
      'kind':      str            # one of KINDS -- data, not a class
      'title':     str
      'params':    {name: param_node_id}
      'body':      {'floor': {...}} OR {'inner': [node_id, ...]}
      'relations': [wire_node_id, ...]   # wires ARE nodes; this lists their ids
      'meta':      {'seq': int, 'created_at': float, 'frozen': bool, ...}
    }

DECISION (documented as required): ``params`` is a dict {name -> param-node
id}. A parameter is NEVER an inline value -- it is itself a node of kind
'param' living in the same one table (its value is its floor body). This is
what makes "pull any param out, see its logic, edit it" (SPEC section 2) hold.

Openability (SPEC section 1): ``Store.open(node_id)`` answers for EVERY kind --
either the list of inner node ids (body has 'inner': group-ish kinds) or the
floor primitive spec (body has 'floor').

The floor (SPEC section 6, minimal but real):
    {'op': 'value',     'value': X}                      literal
    {'op': 'math',      'fn': '+'|'-'|'*'|'/'|'min'|'max'|'avg'}   over wired inputs
    {'op': 'reduce',    'mode': 'sum'|'collect'}          list -> one
    {'op': 'foreach',   'sub': node_id}                   map sub-node over input list
    {'op': 'item'}                                        reads the foreach binding
    {'op': 'copy'}                                        Frobenius comult: 1 input -> N identical fan-outs
    {'op': 'merge',     'fn': 'sum'|'concat'|'first'}     Frobenius mult: N inputs -> 1
    {'op': 'reference', 'target': node_id}                reads another node by id
    {'op': 'compare',   'cmp': '>'|'>='|'<'|'<='|'=='|'!='}  boolean over 2 wired inputs
    {'op': 'secret_ref','ref': 'op://...'}                NEVER resolves; value never in graph
    {'op': 'history',   'entry': {the op dict}}           append-only audit
    (there is NO 'topsis' op: a decision ALGORITHM is an OPENABLE GROUP of these
     generic ops -- nodelang.laws_decision.build_topsis_group -- never hidden code)

Run (SPEC section 4): pull() is lazy + memoized; edits dirty-propagate through
wires, groups, references, foreach subs and params; a group's value = the
inner nodes whose wires cross OUT of it (computed ports, SPEC section 3);
deterministic (inputs ordered by wire creation id).

Every edit goes through ONE function: ``Store.apply_op``. Each applied op
appends a HISTORY node (kind='history', body = the op) into the same one
table. History is append-only: apply_op refuses to target a history node
(raises HistoryImmutable) and there is deliberately NO delete op.

SLICE 2 extensions (SPEC sections 3, 7, 1 / section 19 forcing), still ONE table:
  * RELATION-AS-NODE with a GATE (section 7): a relation opens into ordered
    endpoint parameter nodes and ordinary stage nodes. A gate is a stage node.
    Gate false -> the wire conducts its LAST held value, or NO_VALUE if it
    never conducted (downstream input lists simply omit NO_VALUE). Gate true
    -> conducts live. Inputs are pulled THROUGH the wire node (the wire is a
    real computing node, not a bypassed edge).
  * PARAM MARKER (section 2 table row 1): any floor field may be promoted to a
    param -- the field becomes {'$param': name} and node['params'][name] points
    at a param NODE in the same table; computing the field pulls that node.
  * 'dissolve_group' op: the inverse of grouping (collapse-then-expand =
    identity, section 3). NOT a general delete: refuses non-group-ish nodes,
    frozen nodes and wired groups; splices children back into any parent
    group's inner list. History stays append-only.

SLICE 4 extensions (SPEC sections 12, 4, 5b -- one graph, two drivers), still ONE table:
  * ops may carry an 'actor' ('user' | 'ai' | 'import' | ...); the actor is
    recorded verbatim in the op's history node -- the audit says WHO drove.
    The convenience constructors (add/wire/edit) thread it through.
  * 'freeze' / 'unfreeze' ops: toggling meta.frozen is an EXPLICIT, audited
    op -- never a side effect of 'set' (which still refuses frozen targets).
    Unfreezing is the deliberate two-step gate for editing frozen nodes.
  * floor {'op': 'effect', 'payload': X}: the effectful primitive. While
    meta.frozen it REFUSES to fire on pull -- returns a dry-run marker
    {'fired': False, 'dry_run': True, ...}; unfrozen it returns
    {'fired': True, ...}. Firing is never a silent side effect of pull.

Whitelisted non-table state on Store (holds VALUES/counters, never nodes):
    _memo      {node_id -> computed VALUE}   the memo cache
    _computes  {node_id -> int}              compute counters (observability)
    _held      {wire_id -> last conducted VALUE}  gate hold-last (values only)
    _seq       int                           id counter
"""
from __future__ import annotations

import base64
import copy
import json as _json
import math as _math
import os
import subprocess
import sys
import time
import urllib.request

def _run_probe(kind, spec):
    """Run ONE real check on the real machine. Read-only. Returns
    {ok: bool, kind, detail} -- reality, not a typed label. This is the court's
    artifact lens (SPEC section 16) expressed as a node primitive: a node value
    that is TRUE only when the thing is actually built/live right now."""
    try:
        if kind == 'file_exists':
            p = spec.get('path', '')
            ok = bool(p) and os.path.exists(p)
            det = 'exists' if ok else 'missing'
            if ok and spec.get('contains'):
                try:
                    with open(p, 'r', encoding='utf-8', errors='replace') as fh:
                        ok = spec['contains'] in fh.read()
                    det = 'contains' if ok else 'present-but-missing-marker'
                except OSError as ex:
                    ok, det = False, repr(ex)
            return {'ok': ok, 'kind': kind, 'detail': '%s: %s' % (p, det)}
        if kind == 'http_ok':
            url = spec.get('url', '')
            want = int(spec.get('status', 200))
            try:
                req = urllib.request.Request(url, method=spec.get('method', 'GET'))
                with urllib.request.urlopen(req, timeout=float(spec.get('timeout', 8))) as r:
                    code = r.getcode()
                ok = (code == want)
                return {'ok': ok, 'kind': kind, 'detail': '%s -> %s (want %s)' % (url, code, want)}
            except urllib.error.HTTPError as ex:
                return {'ok': ex.code == want, 'kind': kind,
                        'detail': '%s -> %s (want %s)' % (url, ex.code, want)}
            except Exception as ex:
                return {'ok': False, 'kind': kind, 'detail': '%s -> %r' % (url, ex)}
        if kind == 'governance':
            from .governance_probe import run_governance_probe
            return run_governance_probe(spec)
        if kind == 'resource':
            from .resource_probe import run_resource_probe
            return run_resource_probe(spec)
        if kind == 'py_compile':
            p = spec.get('path', '')
            proc = subprocess.run([sys.executable, '-m', 'py_compile', p],
                                  capture_output=True, text=True, timeout=60, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            ok = proc.returncode == 0
            return {'ok': ok, 'kind': kind,
                    'detail': 'compiles' if ok else proc.stderr.strip()[:200]}
        if kind == 'pytest':
            sel = spec.get('selector', '')
            cwd = spec.get('cwd') or None
            proc = subprocess.run([sys.executable, '-m', 'pytest', sel, '-q',
                                   '-p', 'no:cacheprovider'],
                                  capture_output=True, text=True, timeout=600, cwd=cwd, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            ok = proc.returncode == 0
            tail = (proc.stdout or proc.stderr).strip().splitlines()
            return {'ok': ok, 'kind': kind, 'detail': tail[-1] if tail else 'no output'}
        return {'ok': False, 'kind': kind, 'detail': 'unknown probe kind %r' % kind}
    except Exception as ex:                       # a probe never crashes a cook
        return {'ok': False, 'kind': kind, 'detail': repr(ex)}


def _run_host(port, code):
    """Drive a REAL running host broker (revit-mcp /exec) over HTTP and return
    the real result. READ-ONLY by contract: the caller sends a query against the
    live document. A node value that is real work on a real model NOW."""
    import json as _json
    try:
        body = _json.dumps({'code': code}).encode('utf-8')
        req = urllib.request.Request('http://localhost:%s/exec' % port,
                                     data=body, method='POST',
                                     headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=45) as r:
            out = _json.loads(r.read().decode('utf-8'))
        if out.get('status') == 'ok':
            return out.get('result')
        return {'host_error': out.get('error') or out}
    except Exception as ex:
        return {'host_unreachable': '%s:%r' % (port, ex)}


KINDS = frozenset({
    'value', 'op', 'wire', 'group', 'param', 'session',
    'ui', 'proposal', 'secret_ref', 'history',
})
GROUPISH = frozenset({'group', 'session'})
NODE_KEYS = frozenset({'id', 'kind', 'title', 'params', 'body', 'relations', 'meta'})
META_REQUIRED = frozenset({'seq', 'created_at', 'frozen'})


class OneTableViolation(ValueError):
    """A node-shaped thing lives outside the one table, or a node breaks the one shape."""


class HistoryImmutable(ValueError):
    """History nodes are append-only; the past cannot be rewritten."""


class FrozenNode(ValueError):
    """Frozen (effectful/proposal) nodes refuse edits until unfrozen deliberately."""


class _NoValue:
    """Sentinel: a gate-closed wire that never conducted carries NO value
    (SPEC section 7). Downstream input lists omit it. Falsy on purpose."""
    __slots__ = ()

    def __repr__(self):
        return '<NO_VALUE>'

    def __bool__(self):
        return False


NO_VALUE = _NoValue()


# ---------------------------------------------------------------- validation

def relation_endpoints(nodes, relation):
    """Return the ordered endpoint values owned by a relation-role node.

    Endpoint incidence terminates at parameter nodes.  The endpoint value is
    the atomic reference allowed by SPEC section 7; there is no edge table and
    no recursive relation needed to attach a relation to its participants.
    """
    if relation.get('kind') != 'wire':
        return []
    endpoints = []
    for name, pid in relation.get('params', {}).items():
        if not str(name).startswith('endpoint:'):
            continue
        param = nodes.get(pid)
        floor = param and param.get('body', {}).get('floor')
        value = floor.get('value') if isinstance(floor, dict) and floor.get('op') == 'value' else None
        if isinstance(value, dict):
            endpoints.append((str(name), pid, value))
    endpoints.sort(key=lambda item: item[0])
    return [
        dict(copy.deepcopy(value), endpoint_param=pid, endpoint_name=name)
        for name, pid, value in endpoints
    ]


def relation_sources(nodes, relation):
    return [endpoint for endpoint in relation_endpoints(nodes, relation)
            if endpoint.get('role') == 'source'
            or endpoint.get('direction') in ('out', 'read', 'source')]


def relation_targets(nodes, relation):
    return [endpoint for endpoint in relation_endpoints(nodes, relation)
            if endpoint.get('role') == 'target'
            or endpoint.get('direction') in ('in', 'write', 'target')]


def relation_stages(nodes, relation):
    """Return ordered executable stage assignments owned by a relation.

    A stage assignment is a parameter node, not metadata. Its value names an
    ordinary behavior node plus a generic execution mode: guard, map, or tap.
    """
    if relation.get('kind') != 'wire':
        return []
    stages = []
    for name, pid in relation.get('params', {}).items():
        if not str(name).startswith('stage:'):
            continue
        param = nodes.get(pid)
        floor = param and param.get('body', {}).get('floor')
        value = floor.get('value') if isinstance(floor, dict) and floor.get('op') == 'value' else None
        if isinstance(value, dict):
            stages.append((str(name), pid, value))
    stages.sort(key=lambda item: item[0])
    return [
        dict(copy.deepcopy(value), assignment_param=pid, assignment_name=name)
        for name, pid, value in stages
    ]

def validate_node(nodes, node):
    """Assert ``node`` is the ONE shape and internally consistent with the
    ONE table ``nodes``. Raises OneTableViolation. Same code path for every
    kind -- kind is data."""
    if not isinstance(node, dict):
        raise OneTableViolation('node is not a dict: %r' % (node,))
    if set(node.keys()) != set(NODE_KEYS):
        raise OneTableViolation('node %r keys %r != the one shape %r'
                                % (node.get('id'), sorted(node.keys()), sorted(NODE_KEYS)))
    nid = node['id']
    if not isinstance(nid, str) or nodes.get(nid) is not node:
        raise OneTableViolation('node %r is not stored in the one table under its id' % (nid,))
    if node['kind'] not in KINDS:
        raise OneTableViolation('node %s has unknown kind %r' % (nid, node['kind']))
    if not isinstance(node['title'], str):
        raise OneTableViolation('node %s title not a string' % nid)

    # params: every parameter IS a param node in the same table
    if not isinstance(node['params'], dict):
        raise OneTableViolation('node %s params not a dict' % nid)
    for name, pid in node['params'].items():
        if pid not in nodes:
            raise OneTableViolation('node %s param %r -> %r not in the one table' % (nid, name, pid))
        if nodes[pid]['kind'] != 'param':
            raise OneTableViolation('node %s param %r -> %r is kind %r, not param'
                                    % (nid, name, pid, nodes[pid]['kind']))

    # body: every role may terminate in a primitive OR open into more nodes.
    body = node['body']
    if not isinstance(body, dict) or len(body) != 1 or next(iter(body)) not in ('floor', 'inner'):
        raise OneTableViolation('node %s body must be exactly {floor:...} or {inner:[...]}' % nid)
    if 'inner' in body:
        if not isinstance(body['inner'], list):
            raise OneTableViolation('node %s inner is not a list' % nid)
        for cid in body['inner']:
            if cid not in nodes:
                raise OneTableViolation('node %s inner child %r not in the one table' % (nid, cid))
    else:
        floor = body['floor']
        if not isinstance(floor, dict) or not isinstance(floor.get('op'), str):
            raise OneTableViolation('node %s floor must be a dict with an op string' % nid)
        if node['kind'] == 'secret_ref':
            if floor['op'] != 'secret_ref' or not str(floor.get('ref', '')).startswith('op://'):
                raise OneTableViolation('secret_ref %s must hold an op:// reference' % nid)
            if 'value' in floor:
                raise OneTableViolation('secret_ref %s stores a resolved value -- forbidden' % nid)
        if node['kind'] == 'history' and floor['op'] != 'history':
            raise OneTableViolation('history node %s floor op is %r' % (nid, floor['op']))

    if node['kind'] in ('secret_ref', 'history') and 'floor' not in body:
        raise OneTableViolation('%s node %s must terminate in its protected floor'
                                % (node['kind'], nid))

    if node['kind'] == 'wire':
        if 'inner' not in body:
            raise OneTableViolation('relation node %s must open into endpoint/stage nodes' % nid)
        endpoints = relation_endpoints(nodes, node)
        if len(endpoints) < 2 or not relation_sources(nodes, node) or not relation_targets(nodes, node):
            raise OneTableViolation('relation node %s needs ordered source and target endpoint parameters' % nid)
        for endpoint in endpoints:
            participant = endpoint.get('node_id')
            if participant not in nodes:
                raise OneTableViolation('relation %s endpoint participant %r not in the one table'
                                        % (nid, participant))
            if not isinstance(endpoint.get('port_id'), str) or not endpoint.get('port_id'):
                raise OneTableViolation('relation %s endpoint has no open port id' % nid)
            if endpoint['endpoint_param'] not in body['inner']:
                raise OneTableViolation('relation %s endpoint %s is not inside the relation'
                                        % (nid, endpoint['endpoint_param']))
        for stage in relation_stages(nodes, node):
            stage_id = stage.get('node_id')
            if stage.get('mode') not in ('guard', 'map', 'tap'):
                raise OneTableViolation('relation %s stage %r has invalid mode %r'
                                        % (nid, stage.get('role'), stage.get('mode')))
            if stage_id not in nodes or stage_id not in body['inner']:
                raise OneTableViolation('relation %s stage %r -> %r is not an inner node'
                                        % (nid, stage.get('role'), stage_id))
            if stage['assignment_param'] not in body['inner']:
                raise OneTableViolation('relation %s stage assignment %r is not inside the relation'
                                        % (nid, stage['assignment_param']))

    # relations: a list of WIRE-node ids living in the same one table
    if not isinstance(node['relations'], list):
        raise OneTableViolation('node %s relations not a list' % nid)
    for wid in node['relations']:
        if wid not in nodes:
            raise OneTableViolation('node %s relation %r not in the one table '
                                    '(a wire stored elsewhere = the banned second container)'
                                    % (nid, wid))
        if nodes[wid]['kind'] != 'wire':
            raise OneTableViolation('node %s relation %r is kind %r, not wire'
                                    % (nid, wid, nodes[wid]['kind']))

    meta = node['meta']
    if not isinstance(meta, dict) or not META_REQUIRED <= set(meta.keys()):
        raise OneTableViolation('node %s meta missing %r' % (nid, sorted(META_REQUIRED)))
    return True


def validate_store(store):
    """Every entry in the one table passes the one-shape validator."""
    nodes = store.nodes
    if not isinstance(nodes, dict):
        raise OneTableViolation('the one table is not a dict')
    for nid, node in nodes.items():
        if node.get('id') != nid:
            raise OneTableViolation('table key %r != node id %r' % (nid, node.get('id')))
        validate_node(nodes, node)
    return True


# ---------------------------------------------------------------- the store

class Store:
    """THE one table + the run engine. See module docstring for the law."""

    def __init__(self, secret_resolver=None):
        self.nodes = {}       # THE ONE TABLE: {node_id -> node}. Nothing node-like lives anywhere else.
        self._memo = {}       # {node_id -> computed VALUE} -- values, never nodes
        self._computes = {}   # {node_id -> int} compute counters (proves memo/dirty behavior)
        self._held = {}       # {wire_id -> last conducted VALUE} gate hold-last (values, never nodes)
        self._secret_resolver = secret_resolver  # external capability; secrets never enter the table
        self._dependency_out = None  # disposable id-only index; rebuilt from the table
        self._invalidation_out = None  # disposable reverse-dependency index
        self._seq = 0

    # -- ids ------------------------------------------------------------
    def _next_id(self):
        # never mint an id already present in the one table -- a collision
        # would silently OVERWRITE a node (e.g. a sync-lagged history entry
        # replacing a synced node), which breaks the append-only law
        nid = 'n%06d' % self._seq
        self._seq += 1
        while nid in self.nodes:
            nid = 'n%06d' % self._seq
            self._seq += 1
        return nid

    def _blank(self, kind, title, params, body, frozen):
        return {
            'id': self._next_id(),
            'kind': kind,
            'title': title,
            'params': dict(params or {}),
            'body': body,
            'relations': [],
            'meta': {'seq': self._seq - 1, 'created_at': time.time(), 'frozen': bool(frozen)},
        }

    def _relation_owner_for_endpoint(self, endpoint_id):
        for relation_id, node in self.nodes.items():
            if node.get('kind') == 'wire' and endpoint_id in node.get('params', {}).values():
                return relation_id
        return None

    def _sync_relation_incidence(self, relation_id):
        relation = self.nodes[relation_id]
        for node in self.nodes.values():
            if relation_id in node.get('relations', []):
                node['relations'] = [wid for wid in node['relations'] if wid != relation_id]
        for endpoint in relation_endpoints(self.nodes, relation):
            participant = self.nodes.get(endpoint.get('node_id'))
            if participant is not None and relation_id not in participant['relations']:
                participant['relations'].append(relation_id)

    def _attach_relation_incidence(self, relation_id):
        """Attach a new relation without scanning unrelated nodes."""
        relation = self.nodes[relation_id]
        for endpoint in relation_endpoints(self.nodes, relation):
            participant = self.nodes.get(endpoint.get('node_id'))
            if participant is not None and relation_id not in participant['relations']:
                participant['relations'].append(relation_id)

    # -- THE one edit function -------------------------------------------
    def apply_op(self, op):
        """Every edit goes through here. Applies the op, dirty-propagates,
        and appends a HISTORY node (kind='history', body=the op) to the same
        one table. Returns the id of the node the op produced/touched."""
        what = op['op']
        topology_changed = False
        if what == 'add_node':
            node = op['node']
            if node['kind'] == 'history':
                raise HistoryImmutable('history nodes are engine-appended only')
            self.nodes[node['id']] = node
            validate_node(self.nodes, node)
            out = node['id']
            topology_changed = True
        elif what == 'add_wire':
            endpoint_specs = copy.deepcopy(op.get('endpoints') or [
                {'role': 'source', 'direction': 'out', 'node_id': op['from'],
                 'port_id': op.get('from_port', 'value'), 'cardinality': 'one'},
                {'role': 'target', 'direction': 'in', 'node_id': op['to'],
                 'port_id': op.get('to_port', 'value'), 'cardinality': 'one'},
            ])
            if len(endpoint_specs) < 2:
                raise ValueError('a relation needs at least two endpoint parameters')
            endpoint_ids = []
            endpoint_params = {}
            for index, spec in enumerate(endpoint_specs):
                participant = spec.get('node_id')
                if participant not in self.nodes:
                    raise KeyError('relation endpoint participant %r not in the one table'
                                   % participant)
                endpoint = self._blank(
                    'param', 'endpoint:%03d' % index, None,
                    {'floor': {'op': 'value', 'value': spec}}, False)
                endpoint['meta'].update({
                    'role': 'relation_endpoint',
                    'endpoint_index': index,
                })
                self.nodes[endpoint['id']] = endpoint
                validate_node(self.nodes, endpoint)
                endpoint_ids.append(endpoint['id'])
                endpoint_params['endpoint:%03d' % index] = endpoint['id']
            stage_specs = []
            for raw in op.get('stages', []):
                spec = copy.deepcopy(raw) if isinstance(raw, dict) else {
                    'role': 'transform', 'mode': 'map', 'node_id': str(raw)}
                stage_specs.append(spec)
            for role, stage_id in (op.get('stage_nodes') or {}).items():
                stage_specs.append({'role': role,
                                    'mode': 'guard' if role == 'gate' else 'map',
                                    'node_id': stage_id})
            stage_ids = []
            for index, spec in enumerate(stage_specs):
                stage_id = spec.get('node_id')
                if stage_id not in self.nodes:
                    raise KeyError('relation stage %r not in the one table' % stage_id)
                assignment = self._blank(
                    'param', 'stage:%03d' % index, None,
                    {'floor': {'op': 'value', 'value': spec}}, False)
                assignment['meta'].update({'role': 'relation_stage', 'stage_index': index})
                self.nodes[assignment['id']] = assignment
                validate_node(self.nodes, assignment)
                endpoint_params['stage:%03d' % index] = assignment['id']
                stage_ids.extend([assignment['id'], stage_id])
            wire = self._blank('wire', op.get('title', ''), endpoint_params,
                               {'inner': endpoint_ids + stage_ids}, False)
            wire['meta'].update({'capabilities': ['relation']})
            self.nodes[wire['id']] = wire
            self._attach_relation_incidence(wire['id'])
            validate_node(self.nodes, wire)
            # A new relation changes dependency topology. Cached values are
            # disposable, so a constant-time cache clear is both correct and
            # avoids repeatedly scanning a large graph during graph assembly.
            self._memo.clear()
            out = wire['id']
            topology_changed = True
        elif what in ('set', 'unset'):
            target = self.nodes[op['id']]
            if target['kind'] == 'history':
                raise HistoryImmutable('cannot rewrite the past: %s is a history node' % op['id'])
            if target['meta'].get('frozen'):
                raise FrozenNode('node %s is frozen' % op['id'])
            old_endpoint_participant = None
            if target['meta'].get('role') == 'relation_endpoint':
                old_value = target['body'].get('floor', {}).get('value')
                if isinstance(old_value, dict):
                    old_endpoint_participant = old_value.get('node_id')
            obj = target
            for key in op['path'][:-1]:
                obj = obj[key]
            leaf = op['path'][-1]
            if 'before' not in op and not op.get('before_missing'):
                if leaf in obj:
                    op['before'] = copy.deepcopy(obj[leaf])
                else:
                    op['before_missing'] = True
            if what == 'set':
                obj[leaf] = op['value']
            else:
                if leaf not in obj:
                    raise KeyError('cannot unset missing path leaf %r' % leaf)
                if 'before' not in op:
                    op['before'] = copy.deepcopy(obj[leaf])
                del obj[leaf]
            if target['meta'].get('role') == 'relation_endpoint':
                owner = self._relation_owner_for_endpoint(target['id'])
                if owner:
                    relation = self.nodes[owner]
                    new_value = target['body'].get('floor', {}).get('value')
                    new_participant = new_value.get('node_id') if isinstance(new_value, dict) else None
                    if old_endpoint_participant != new_participant:
                        old_node = self.nodes.get(old_endpoint_participant)
                        if old_node and not any(
                                endpoint.get('node_id') == old_endpoint_participant
                                for endpoint in relation_endpoints(self.nodes, relation)):
                            old_node['relations'] = [rid for rid in old_node['relations']
                                                     if rid != owner]
                        new_node = self.nodes.get(new_participant)
                        if new_node is not None and owner not in new_node['relations']:
                            new_node['relations'].append(owner)
                    self._invalidate([owner])
            floor_reference = (op['path'][:2] == ['body', 'floor'] and
                               (len(op['path']) == 2 or
                                op['path'][2] in ('from', 'target', 'sub', 'gate')))
            structural = (op['path'][:1] == ['params']
                          or op['path'][:2] == ['body', 'inner'])
            topology_changed = (structural or floor_reference or
                                target['meta'].get('role') == 'relation_endpoint')
            if structural:
                self._memo.clear()
            else:
                self._invalidate([op['id']])
            out = op['id']
        elif what == 'dissolve_group':
            # Inverse of grouping (SPEC section 3: collapse-then-expand = identity).
            # NOT a general delete: only group-ish, unfrozen, unwired nodes dissolve.
            gid = op['id']
            target = self.nodes[gid]
            if 'inner' not in target['body']:
                raise ValueError('dissolve_group: %s is not group-ish' % gid)
            if target['meta'].get('frozen'):
                raise FrozenNode('node %s is frozen' % gid)
            if target['relations']:
                raise ValueError('dissolve_group: %s still has wires; rewire first' % gid)
            children = list(target['body']['inner'])
            for other in self.nodes.values():
                if other is not target and 'inner' in other['body'] \
                        and gid in other['body']['inner']:
                    idx = other['body']['inner'].index(gid)
                    other['body']['inner'][idx:idx + 1] = children
            del self.nodes[gid]
            self._memo.pop(gid, None)
            self._held.pop(gid, None)
            self._invalidate(children)
            out = gid
            topology_changed = True
        elif what in ('freeze', 'unfreeze'):
            # SLICE 4 (SPEC section 5b): frozen is toggled ONLY by these
            # explicit, audited ops. 'unfreeze' deliberately bypasses the
            # FrozenNode guard -- it IS the deliberate escape hatch, and the
            # history node records who pulled it.
            target = self.nodes[op['id']]
            if target['kind'] == 'history':
                raise HistoryImmutable('cannot %s the past: %s is a history node'
                                       % (what, op['id']))
            target['meta']['frozen'] = (what == 'freeze')
            self._invalidate([op['id']])  # effect nodes compute differently when frozen
            out = op['id']
        elif what in ('effect_apply', 'effect_revert'):
            # SLICE (SPEC section 4/5b): a real effect fired against the
            # caller's EXTERNAL sink. The sink is not a node and never enters
            # the one table; this op touches nothing in self.nodes -- it exists
            # ONLY so the mutation is recorded as an append-only history node
            # (the revert token). The actual sink read/write is done by
            # laws_effect BEFORE calling apply_op; here we only audit.
            eff = self.nodes.get(op.get('effect'))
            if eff is None:
                raise ValueError('%s: effect %r not in the one table' % (what, op.get('effect')))
            out = op['effect']
        elif what == 'sample':
            source = self.nodes.get(op.get('source'))
            target = self.nodes.get(op.get('target'))
            if source is None or target is None:
                raise ValueError('sample requires source and target nodes')
            floor = target['body'].get('floor')
            if target['kind'] != 'param' or not floor or floor.get('op') != 'value':
                raise ValueError('sample target must be a value parameter node')
            if target['meta'].get('frozen'):
                raise FrozenNode('node %s is frozen' % target['id'])
            # A court sample is explicitly live. Derived relation/op nodes may
            # otherwise hold memoized values above volatile probe/host leaves.
            self._memo.clear()
            floor['value'] = copy.deepcopy(self.pull(source['id']))
            self._invalidate([target['id']])
            out = target['id']
        elif what == 'command':
            capability = op.get('capability')
            args = op.get('args', {})
            if not isinstance(capability, str) or not capability:
                raise ValueError('command requires a capability name')
            if not isinstance(args, dict):
                raise ValueError('command args must be a mapping')
            # External execution belongs to the injected application host.
            # The one table records the requested capability and arguments.
            out = capability
        else:
            raise ValueError('unknown op %r' % (what,))
        if topology_changed:
            self._dependency_out = None
            self._invalidation_out = None
        self._record(op)
        return out

    def _record(self, op):
        """Append the op as a history NODE in the same one table (append-only)."""
        entry = self._blank('history', 'op:%s' % op['op'], None,
                            {'floor': {'op': 'history', 'entry': copy.deepcopy(op)}}, False)
        self.nodes[entry['id']] = entry

    # -- convenience constructors (all route through apply_op) -----------
    def add(self, kind, title='', floor=None, inner=None, params=None, frozen=False,
            actor=None):
        if (floor is None) == (inner is None):
            raise ValueError('exactly one of floor/inner')
        body = {'floor': floor} if floor is not None else {'inner': list(inner)}
        node = self._blank(kind, title, params, body, frozen)
        op = {'op': 'add_node', 'node': node}
        if actor is not None:
            op['actor'] = actor
        return self.apply_op(op)

    def wire(self, src, dst, title='', actor=None):
        return self.relation([
            {'role': 'source', 'direction': 'out', 'node_id': src,
             'port_id': 'value', 'cardinality': 'one'},
            {'role': 'target', 'direction': 'in', 'node_id': dst,
             'port_id': 'value', 'cardinality': 'one'},
        ], title=title, actor=actor)

    def relation(self, endpoints, title='', stages=None, stage_nodes=None, actor=None):
        op = {'op': 'add_wire', 'endpoints': copy.deepcopy(list(endpoints)),
              'title': title, 'stages': list(stages or []),
              'stage_nodes': copy.deepcopy(stage_nodes or {})}
        if actor is not None:
            op['actor'] = actor
        return self.apply_op(op)

    def endpoints(self, relation_id):
        return relation_endpoints(self.nodes, self.nodes[relation_id])

    def edit(self, nid, path, value, actor=None, transaction=None):
        op = {'op': 'set', 'id': nid, 'path': list(path), 'value': value}
        if actor is not None:
            op['actor'] = actor
        if transaction is not None:
            op['transaction'] = transaction
        return self.apply_op(op)

    # -- openability ------------------------------------------------------
    def open(self, nid):
        """EVERY kind answers: inner node ids (group-ish) or the floor primitive."""
        body = self.nodes[nid]['body']
        return list(body['inner']) if 'inner' in body else body['floor']

    # -- run: lazy pull + memo + dirty propagation ------------------------
    def pull(self, nid, env=None):
        node = self.nodes[nid]
        # A 'probe' reads the LIVE world (a real file / endpoint / test on the
        # real machine, SPEC section 16 -- done = an independent check on the
        # real artifact). Its value is reality, which changes independent of any
        # graph edit, so it is VOLATILE: never memoized, always re-checked.
        volatile = ('floor' in node['body']
                    and node['body']['floor'].get('op') in ('probe', 'probe_ok', 'host', 'mcp'))
        if env is None and not volatile and nid in self._memo:
            return self._memo[nid]
        value = self._compute(node, env)
        if env is None and not volatile:
            self._memo[nid] = value
        return value

    def _incoming_wire_ids(self, node):
        ids = []
        for wid in node['relations']:
            w = self.nodes.get(wid)
            if (w and w['kind'] == 'wire'
                    and any(endpoint.get('node_id') == node['id']
                            for endpoint in relation_targets(self.nodes, w))):
                ids.append(wid)
        return sorted(ids)  # deterministic: creation order (ids are zero-padded)

    def _inputs(self, node, env):
        """Inputs are pulled THROUGH the wire nodes (the wire is a computing
        node -- gates live on it, SPEC section 7). A gate-closed wire that never
        conducted yields NO_VALUE and is omitted: downstream sees no value."""
        vals = [self.pull(wid, env) for wid in self._incoming_wire_ids(node)]
        return [v for v in vals if v is not NO_VALUE]

    def _floor_val(self, node, raw, env):
        """A floor field may be promoted to a param (SPEC section 2 row 1):
        {'$param': name} reads the param NODE named in node['params']."""
        if isinstance(raw, dict) and set(raw) == {'$param'}:
            return self.pull(node['params'][raw['$param']], env)
        return raw

    def _compute_relation(self, node, env):
        sources = relation_sources(self.nodes, node)
        values = [self.pull(endpoint['node_id'], env) for endpoint in sources]
        if not values:
            raise RuntimeError('relation node %s has no source endpoints' % node['id'])
        value = values[0] if len(values) == 1 else values
        for stage in relation_stages(self.nodes, node):
            stage_env = dict(env or {}, item=value)
            stage_value = self.pull(stage['node_id'], stage_env)
            if stage['mode'] == 'guard':
                if not stage_value:
                    return self._held.get(node['id'], NO_VALUE)
            elif stage['mode'] == 'map':
                value = stage_value
            elif stage['mode'] == 'tap':
                pass
        self._held[node['id']] = value
        return value

    def _compute(self, node, env):
        self._computes[node['id']] = self._computes.get(node['id'], 0) + 1
        if node['kind'] == 'wire':
            return self._compute_relation(node, env)
        body = node['body']
        if 'inner' in body:
            return self._compute_group(node, env)
        floor = body['floor']
        op = floor['op']
        if op == 'value':
            return self._floor_val(node, floor['value'], env)
        if op == 'item':
            if not env or 'item' not in env:
                raise RuntimeError('item is unbound outside a foreach (node %s)' % node['id'])
            return env['item']
        if op == 'math':
            xs = self._inputs(node, env)
            if not xs:
                raise RuntimeError('math node %s has no inputs' % node['id'])
            fn = self._floor_val(node, floor['fn'], env)
            if fn == '+':
                return sum(xs)
            if fn == '-':
                return xs[0] - sum(xs[1:])
            if fn == '*':
                out = 1
                for x in xs:
                    out *= x
                return out
            if fn == '/':
                out = xs[0]
                for x in xs[1:]:
                    out /= x
                return out
            if fn == 'min':
                return min(xs)
            if fn == 'max':
                return max(xs)
            if fn == 'avg':
                return sum(xs) / len(xs)
            if fn == 'sqrt':                     # irreducible scalar primitive
                return _math.sqrt(xs[0])
            raise ValueError('unknown math fn %r' % fn)
        if op == 'compare':
            xs = self._inputs(node, env)
            if len(xs) != 2:
                raise RuntimeError('compare node %s needs exactly 2 inputs, got %d'
                                   % (node['id'], len(xs)))
            a, b = xs
            cmp = self._floor_val(node, floor['cmp'], env)
            if cmp == '>':
                return a > b
            if cmp == '>=':
                return a >= b
            if cmp == '<':
                return a < b
            if cmp == '<=':
                return a <= b
            if cmp == '==':
                return a == b
            if cmp == '!=':
                return a != b
            if cmp == 'contains':
                try:
                    return b in a
                except TypeError:
                    return str(b) in str(a)
            if cmp == 'icontains':
                return str(b).casefold() in str(a).casefold()
            raise ValueError('unknown compare cmp %r' % cmp)
        if op == 'reduce':
            xs = self._inputs(node, env)
            items = xs[0] if xs else []
            if not isinstance(items, (list, tuple)):
                items = [items]
            mode = self._floor_val(node, floor['mode'], env)
            if mode == 'sum':
                return sum(items)
            if mode == 'collect':
                return list(items)
            if mode == 'count':
                return len(items)
            if mode == 'argmax':
                key_path = self._floor_val(node, floor.get('key_path'), env)
                where_path = self._floor_val(node, floor.get('where_path'), env)
                default = copy.deepcopy(self._floor_val(node, floor.get('default'), env))

                def read_path(value, path):
                    if path in (None, '', []):
                        return value
                    path = path if isinstance(path, list) else [path]
                    for key in path:
                        if not isinstance(value, dict) or key not in value:
                            return None
                        value = value[key]
                    return value

                candidates = [item for item in items
                              if where_path in (None, '', [])
                              or bool(read_path(item, where_path))]
                if not candidates:
                    return default
                values = [read_path(item, key_path) for item in candidates]
                if any(not isinstance(value, (int, float))
                       or not _math.isfinite(float(value)) for value in values):
                    raise ValueError('reduce/argmax needs finite numeric key values')
                winner = max(range(len(candidates)), key=lambda index: float(values[index]))
                return copy.deepcopy(candidates[winner])
            raise ValueError('unknown reduce mode %r' % mode)
        if op == 'foreach':
            xs = self._inputs(node, env)
            items = xs[0] if xs else []
            sub = floor['sub']
            return [self.pull(sub, dict(env or {}, item=it)) for it in items]
        if op == 'copy':
            # Frobenius COMULTIPLICATION (SPEC section 7 / section 19 spider
            # structure): a node that fan-outs its ONE input to N identical
            # outputs. In this value-per-node engine the "N outputs" ARE the N
            # consumers wired FROM this copy node -- each reads the SAME value
            # (that is fan-out, section 7). So copy's own value = its single
            # input, conducted unchanged. Zero inputs is unbound, not a silent
            # default (matches math's contract).
            xs = self._inputs(node, env)
            if len(xs) != 1:
                raise RuntimeError('copy node %s needs exactly 1 input, got %d'
                                   % (node['id'], len(xs)))
            return xs[0]
        if op == 'merge':
            # Frobenius MULTIPLICATION (section 19 spider): merges N inputs into
            # ONE. fn=first is the counit-side partner of copy (copy then
            # merge-first = identity); sum/concat are the associative merges.
            xs = self._inputs(node, env)
            fn = self._floor_val(node, floor['fn'], env)
            if fn == 'first':
                if not xs:
                    raise RuntimeError('merge/first node %s has no inputs' % node['id'])
                return xs[0]
            if fn == 'sum':
                return sum(xs)
            if fn == 'concat':
                out = []
                for x in xs:
                    out.extend(x)
                return out
            if fn == 'list':                     # assemble N inputs into an ordered list
                return list(xs)
            if fn == 'record':                   # assemble named inputs into an open record
                keys = self._floor_val(node, floor.get('keys'), env)
                if not isinstance(keys, list) or len(keys) != len(xs):
                    raise RuntimeError('merge/record node %s needs one key per input'
                                       % node['id'])
                return dict(zip(keys, xs))
            raise ValueError('unknown merge fn %r' % fn)
        if op == 'format':
            template = str(self._floor_val(node, floor.get('template', ''), env))
            return template.format(*self._inputs(node, env))
        if op == 'reference':
            return self.pull(floor['target'], env)
        if op == 'field':
            xs = self._inputs(node, env)
            if len(xs) != 1:
                raise RuntimeError('field node %s needs exactly one input' % node['id'])
            path = self._floor_val(node, floor.get('path'), env)
            path = path if isinstance(path, list) else [path]
            value = xs[0]
            for key in path:
                if isinstance(value, dict) and key in value:
                    value = value[key]
                else:
                    return copy.deepcopy(self._floor_val(node, floor.get('default'), env))
            return value
        if op == 'mcp':
            effectful = bool(self._floor_val(node, floor.get('effectful', False), env))
            tool = self._floor_val(node, floor.get('tool'), env)
            args = self._floor_val(node, floor.get('args', {}), env) or {}
            url = self._floor_val(node, floor.get('url'), env)
            timeout = float(self._floor_val(node, floor.get('timeout', 8.0), env))
            if effectful and node['meta'].get('frozen'):
                return {'fired': False, 'dry_run': True, 'tool': tool}
            from .governance_probe import DEFAULT_MCP_URL, _mcp_tool
            result = _mcp_tool(str(tool), dict(args), url=str(url or DEFAULT_MCP_URL),
                               timeout=timeout)
            return {'fired': True, 'result': result} if effectful else result
        if op == 'codec':
            xs = self._inputs(node, env)
            if len(xs) != 1:
                raise RuntimeError('codec node %s needs exactly one input' % node['id'])
            action = self._floor_val(node, floor.get('action'), env)
            if action == 'json_encode':
                return _json.dumps(xs[0], sort_keys=True, separators=(',', ':')).encode('utf-8')
            if action == 'json_decode':
                raw = xs[0].decode('utf-8') if isinstance(xs[0], (bytes, bytearray)) else xs[0]
                return _json.loads(raw)
            raise ValueError('unknown codec action %r' % action)
        if op == 'aead':
            xs = self._inputs(node, env)
            if len(xs) != 1:
                raise RuntimeError('aead node %s needs exactly one input' % node['id'])
            if self._secret_resolver is None:
                raise RuntimeError('aead node %s has no external secret resolver' % node['id'])
            action = self._floor_val(node, floor.get('action'), env)
            key_ref = self._floor_val(node, floor.get('key_ref'), env)
            key = self._secret_resolver(key_ref)
            if not isinstance(key, (bytes, bytearray)) or len(key) not in (16, 24, 32):
                raise ValueError('secret resolver must return a 16/24/32-byte AES key')
            aad_raw = self._floor_val(node, floor.get('aad', b''), env)
            aad = aad_raw.encode('utf-8') if isinstance(aad_raw, str) else bytes(aad_raw)
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
            cipher = AESGCM(bytes(key))
            if action == 'encrypt':
                raw = xs[0] if isinstance(xs[0], (bytes, bytearray)) else bytes(xs[0])
                nonce = os.urandom(12)
                encrypted = cipher.encrypt(nonce, bytes(raw), aad)
                return {
                    'algorithm': 'AES-GCM',
                    'nonce': base64.b64encode(nonce).decode('ascii'),
                    'ciphertext': base64.b64encode(encrypted).decode('ascii'),
                }
            if action == 'decrypt':
                envelope = xs[0]
                if not isinstance(envelope, dict) or envelope.get('algorithm') != 'AES-GCM':
                    raise ValueError('aead decrypt input is not an AES-GCM envelope')
                nonce = base64.b64decode(envelope['nonce'], validate=True)
                encrypted = base64.b64decode(envelope['ciphertext'], validate=True)
                return cipher.decrypt(nonce, encrypted, aad)
            raise ValueError('unknown aead action %r' % action)
        if op == 'host':
            # SPEC section 0 / section 6: connectors/hosts are the LIVE effectful
            # primitives. This node DRIVES a real running host (Revit/AutoCAD/Max
            # broker over HTTP) and its value = the REAL result from the real
            # model NOW -- an architect wiring a node makes real work run. READ
            # ONLY here (a query against the live doc); a write is an effect node
            # (frozen, gated, section 5b). Volatile: the live model can change.
            port = self._floor_val(node, floor.get('port'), env)
            code = self._floor_val(node, floor.get('code'), env)
            return _run_host(port, code)
        if op == 'probe':
            # SPEC section 16 made a node: the value is an INDEPENDENT CHECK ON
            # THE REAL ARTIFACT, run on the real machine at pull time -- not a
            # typed label, not stored, not averaged guesswork. Read-only (never
            # mutates the world); volatile in pull() so it always reflects
            # reality NOW. Returns the real boolean + evidence.
            kind = self._floor_val(node, floor.get('kind'), env)
            spec = self._floor_val(node, floor.get('spec'), env) or {}
            return _run_probe(kind, spec)
        if op == 'probe_ok':
            # 1.0 when the referenced probe is live-true NOW, else 0.0 -- a
            # numeric score you can average. Volatile (re-reads the probe).
            r = self.pull(floor['probe'], env)
            return 1.0 if (isinstance(r, dict) and r.get('ok')) else 0.0
        if op == 'secret_ref':
            return floor['ref']  # the reference, NEVER the resolved secret
        if op == 'effect':
            # SPEC sections 4 / 5b: a frozen effectful node REFUSES pull-side
            # effects -- pulling it yields a dry-run PLAN, never a firing, and
            # NEVER touches the external sink. pull() is pure by construction:
            # the sink is not even reachable from _compute, so no mutation can
            # leak here. Real mutation lives only in laws_effect.apply_effect,
            # gated behind an explicit unfreeze.
            #
            # Two floor shapes, ONE op (kind is data, so is the payload shape):
            #   {op:'effect', target: <key>, change: <value>}  -- plan a set
            #   {op:'effect', payload: X}                       -- opaque plan
            # 'target'/'change' may themselves be promoted to params or wired.
            if 'target' in floor or 'change' in floor:
                target = self._floor_val(node, floor.get('target'), env)
                change = self._floor_val(node, floor.get('change'), env)
                plan = {'target': copy.deepcopy(target), 'change': copy.deepcopy(change)}
                if node['meta'].get('frozen'):
                    return {'fired': False, 'dry_run': True, 'plan': plan}
                return {'fired': True, 'plan': plan}
            payload = self._floor_val(node, floor.get('payload'), env)
            if node['meta'].get('frozen'):
                return {'fired': False, 'dry_run': True, 'payload': copy.deepcopy(payload)}
            return {'fired': True, 'payload': copy.deepcopy(payload)}
        # NOTE: there is deliberately NO 'topsis' floor op. TOPSIS is a decision
        # ALGORITHM, not an irreducible primitive -- it lives as an OPENABLE GROUP
        # of generic nodes (nodelang.laws_decision.build_topsis_group). A product
        # algorithm must be a visible composition, never hidden engine code.
        if op == 'history':
            return copy.deepcopy(floor['entry'])
        raise ValueError('unknown floor op %r' % op)

    def _deep_members(self, nid, _seen=None):
        """The TRANSITIVE member closure of a node: itself plus, for group-ish
        bodies, every descendant at any depth. This is a group's true boundary
        (SPEC section 3): 'crossing OUT' means out of the whole group, not out
        of one nesting level. Cycle-safe."""
        seen = set() if _seen is None else _seen
        if nid in seen:
            return seen
        seen.add(nid)
        body = self.nodes[nid]['body']
        if 'inner' in body:
            for cid in body['inner']:
                self._deep_members(cid, seen)
        return seen

    def _wires_from(self, member_ids):
        """Dependency pairs leaving members: relations plus visible node refs."""
        if self._dependency_out is None:
            index = {}
            for nid, node in self.nodes.items():
                for pid in node['params'].values():
                    index.setdefault(pid, set()).add(nid)
                floor = node['body'].get('floor')
                if floor:
                    for key in ('target', 'sub'):
                        dep = floor.get(key)
                        if isinstance(dep, str) and dep in self.nodes:
                            index.setdefault(dep, set()).add(nid)
            self._dependency_out = index
        for m in member_ids:
            for wid in self.nodes[m]['relations']:
                w = self.nodes.get(wid)
                if w and w['kind'] == 'wire':
                    sources = relation_sources(self.nodes, w)
                    targets = relation_targets(self.nodes, w)
                    if any(endpoint.get('node_id') == m for endpoint in sources):
                        for target in targets:
                            yield m, target['node_id']
            for nid in self._dependency_out.get(m, ()):
                yield m, nid

    def _compute_group(self, node, env):
        """A group's value = its inner subgraph run; outputs = direct inner
        nodes whose wires (their own, or -- for nested groups -- any deep
        member's) cross OUT of the group's TRANSITIVE boundary (computed
        ports, SPEC section 3). The transitive boundary is what makes
        regrouping the same nodes different ways yield the same composite
        (SPEC section 19 regroup-invariance forcing -- the direct-inner-only
        check violated it as soon as wired nodes were folded one level down).
        Fallback when nothing crosses out: the inner sinks (direct inner whose
        deep members feed nothing else inside the boundary). Single output ->
        the value; else list in inner order (deterministic)."""
        inner = list(node['body']['inner'])
        scans = {cid: self._deep_members(cid) for cid in inner}
        boundary = {node['id']}
        for s in scans.values():
            boundary |= s
        outputs = []
        for cid in inner:
            if any(dst not in boundary for _, dst in self._wires_from(scans[cid])):
                outputs.append(cid)
        if not outputs:
            for cid in inner:
                feeds_inside = any(
                    dst in boundary and dst not in scans[cid]
                    for _, dst in self._wires_from(scans[cid]))
                if not feeds_inside:
                    outputs.append(cid)
        outputs = list(dict.fromkeys(outputs))  # dedupe, PRESERVE inner order (deterministic)
        values = [self.pull(o, env) for o in outputs]
        return values[0] if len(values) == 1 else values

    # -- dirty propagation -------------------------------------------------
    def prepare_runtime_indexes(self):
        """Build disposable acceleration indexes before serving interaction."""
        self._ensure_invalidation_index()
        return self

    def _ensure_invalidation_index(self):
        if self._invalidation_out is not None:
            return self._invalidation_out
        index = {}

        def depend(source, target):
            if source in self.nodes and target in self.nodes and source != target:
                index.setdefault(source, set()).add(target)

        for nid, node in self.nodes.items():
            body = node['body']
            for pid in node['params'].values():
                depend(pid, nid)
            if 'inner' in body:
                for child in body['inner']:
                    depend(child, nid)
            else:
                floor = body['floor']
                for key in ('from', 'target', 'sub', 'gate'):
                    reference = floor.get(key)
                    if isinstance(reference, str):
                        depend(reference, nid)
            if node['kind'] == 'wire':
                for endpoint in relation_sources(self.nodes, node):
                    depend(endpoint.get('node_id'), nid)
                for endpoint in relation_targets(self.nodes, node):
                    depend(nid, endpoint.get('node_id'))
        self._invalidation_out = index
        return index

    def _invalidate(self, seed_ids):
        if not self._memo:
            return  # nothing memoized -> nothing to pop (bulk-import fast path)
        index = self._ensure_invalidation_index()
        dirty = set(seed_ids)
        pending = list(dirty)
        while pending:
            source = pending.pop()
            for dependent in index.get(source, ()):
                if dependent not in dirty:
                    dirty.add(dependent)
                    pending.append(dependent)
        for nid in dirty:
            self._memo.pop(nid, None)

    def _depends_on(self, node, dirty):
        body = node['body']
        if node['kind'] == 'wire' and any(
                endpoint.get('node_id') in dirty
                for endpoint in relation_endpoints(self.nodes, node)):
            return True
        if 'inner' in body:
            if any(cid in dirty for cid in body['inner']):
                return True
        else:
            floor = body['floor']
            for key in ('from', 'target', 'sub', 'gate'):
                reference = floor.get(key)
                # Promoted floor properties use {'$param': name}. They depend
                # through node.params below; only literal node-id references
                # participate in this direct-reference check.
                if isinstance(reference, str) and reference in dirty:
                    return True
        if any(pid in dirty for pid in node['params'].values()):
            return True
        for wid in node['relations']:
            w = self.nodes.get(wid)
            if (w and w['kind'] == 'wire' and wid in dirty
                    and any(endpoint.get('node_id') == node['id']
                            for endpoint in relation_targets(self.nodes, w))):
                return True
        return False

    # -- serialize: the whole graph IS one flat list of one-shape nodes ----
    def dump(self):
        return [copy.deepcopy(self.nodes[nid]) for nid in sorted(self.nodes)]

    @classmethod
    def load(cls, flat, secret_resolver=None):
        store = cls(secret_resolver=secret_resolver)
        for node in flat:
            store.nodes[node['id']] = copy.deepcopy(node)
        if store.nodes:
            store._seq = max(n['meta']['seq'] for n in store.nodes.values()) + 1
        return store
