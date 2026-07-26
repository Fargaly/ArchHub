"""nodelang.laws_surface -- SLICE 3 laws on top of the one table (core.py).

SPEC coverage:
  section 2/9  SESSION-AS-NODE: a session node's body['inner'] = its graph's
               root ids. It is the SAME primitive (kind='session' is data on
               the one shape) -- no session class, no session table.
               - import_session: pull one session INTO another (grand session,
                 SPEC section 9 federation). It is just an inner-list edit
                 through apply_op; the imported session then behaves as a
                 group (its value = live result of its nodes, core group law).
               - stage: sessions carry a 'stage' PARAM ('wip'/'central') --
                 the param is itself a param NODE in the one table.
               - make_wip: WIP = a SEPARATE Store (local copy, SAME node ids;
                 node-id = element-id, SPEC section 9) so local edits cannot
                 touch central by construction.
               - sync: the ONLY way WIP reaches central -- deliberate,
                 by-node-id copy, every change routed through
                 central.apply_op (so central's history records the sync).
                 NEVER automatic. Stage params are governance metadata and
                 are excluded from sync (else syncing would flip central's
                 stage to 'wip').

  section 10   UI-FROM-NODES: ui-element nodes (kind='ui') carry params
               tag / text / bind / children -- each param IS a param node
               (text is a value floor; bind is a REFERENCE floor to the bound
               node, so the binding is graph logic, not an annotation).
               render(store, ui_root) is a PURE function that walks the one
               table and returns HTML. There is no template and no second
               source: the page IS the nodes.

  section 5b   SECRET-REF: a secret_ref node holds only the 'op://...'
               string (core validate_node FORBIDS a stored value).
               resolve_secret resolves at pull-time through an INJECTED
               resolver and never writes the result anywhere in the table
               or the memo -- serializing the graph can never leak it.

Stdlib only. Nothing here adds a second container: every helper reads and
writes THE one table through Store.apply_op / Store.pull.
"""
from __future__ import annotations

import copy
import html as _html

from .core import Store, OneTableViolation


class SyncError(ValueError):
    """WIP->central sync refused: wrong direction, wrong stage, or unsyncable."""


# --------------------------------------------------------------- sessions

def make_session(store, title, inner, stage='wip'):
    """A session IS a node: kind='session', body inner = the graph's root ids,
    plus a 'stage' PARAM that is itself a param node in the one table."""
    pid = store.add('param', 'stage', floor={'op': 'value', 'value': stage})
    return store.add('session', title, inner=list(inner), params={'stage': pid})


def stage(store, session_id):
    """Read the session's stage by PULLING its stage param node (live value)."""
    return store.pull(store.nodes[session_id]['params']['stage'])


def import_session(store, target_session_id, session_node_id):
    """Grand session (SPEC section 9): pull a session INTO another session.
    The imported session becomes an inner member of the target -- from then on
    it behaves exactly as a group (core group law: value = live inner result).
    Routed through apply_op, so it lands in history."""
    target = store.nodes[target_session_id]
    imported = store.nodes[session_node_id]
    if target['kind'] != 'session' or imported['kind'] != 'session':
        raise ValueError('import_session needs two session nodes, got %r into %r'
                         % (imported['kind'], target['kind']))
    if session_node_id == target_session_id:
        raise ValueError('a session cannot import itself')
    inner = list(target['body']['inner'])
    if session_node_id in inner:
        raise ValueError('session %s already imported into %s'
                         % (session_node_id, target_session_id))
    store.edit(target_session_id, ['body', 'inner'], inner + [session_node_id])
    return target_session_id


def closure(store, root_id):
    """Every node id reachable from root through the one shape's reference
    fields: inner children, params, relations (wire ids), and floor
    from/to/target/sub. This IS the session subtree (by node-id)."""
    seen, order, stack = set(), [], [root_id]
    while stack:
        nid = stack.pop()
        if nid in seen:
            continue
        seen.add(nid)
        order.append(nid)
        node = store.nodes[nid]
        refs = list(node['params'].values()) + list(node['relations'])
        body = node['body']
        if 'inner' in body:
            refs += list(body['inner'])
        else:
            floor = body['floor']
            for key in ('from', 'to', 'target', 'sub'):
                dependency = floor.get(key)
                if isinstance(dependency, str) and dependency in store.nodes:
                    refs.append(dependency)
        stack.extend(r for r in refs if r not in seen)
    return order


def make_wip(central, session_id):
    """WIP (SPEC section 9): a SEPARATE local Store holding a copy of the
    central session's subtree under the SAME node ids (node-id = element-id).
    Edits in the WIP physically cannot touch central -- different table.
    The WIP session's stage param is flipped to 'wip' (in the WIP only)."""
    if central.nodes[session_id]['kind'] != 'session':
        raise ValueError('%s is not a session node' % session_id)
    wip = Store.load([copy.deepcopy(central.nodes[nid])
                      for nid in closure(central, session_id)])
    # node-id = element-id: NEW nodes minted in the WIP must not collide with
    # ids central has already issued (e.g. its history nodes), so the WIP id
    # counter continues from central's counter, not from the copied subset.
    wip._seq = max(wip._seq, central._seq)
    wip.apply_op({'op': 'set',
                  'id': wip.nodes[session_id]['params']['stage'],
                  'path': ['body', 'floor', 'value'], 'value': 'wip'})
    return wip


def _refs_present(central, node):
    """True when everything the node references (EXCEPT relations -- wires
    and their endpoint nodes reference each other, so relations are filtered
    at insert time and patched by the field-sync pass) exists in central."""
    ok = all(pid in central.nodes for pid in node['params'].values())
    body = node['body']
    if 'inner' in body:
        ok = ok and all(cid in central.nodes for cid in body['inner'])
    else:
        floor = body['floor']
        for key in ('from', 'to'):
            if key in floor:
                ok = ok and floor[key] in central.nodes
    return ok


def sync(wip, central, session_id):
    """The DELIBERATE WIP -> central copy, by node-id (SPEC section 9).
    Refuses to run unless wip's session is staged 'wip' and central's is
    staged 'central' (direction lock). Every change goes through
    central.apply_op, so central's history records the sync. Stage params
    (governance metadata) are never synced. Returns the synced node ids."""
    if stage(wip, session_id) != 'wip':
        raise SyncError('source session %s is staged %r, not wip -- refusing'
                        % (session_id, stage(wip, session_id)))
    if stage(central, session_id) != 'central':
        raise SyncError('target session %s is staged %r, not central -- refusing'
                        % (session_id, stage(central, session_id)))
    skip = {wip.nodes[session_id]['params']['stage'],
            central.nodes[session_id]['params']['stage']}
    ids = [nid for nid in closure(wip, session_id) if nid not in skip]
    for nid in ids:                      # id-collision guard (node-id = element-id)
        if nid in central.nodes and central.nodes[nid]['kind'] != wip.nodes[nid]['kind']:
            raise SyncError('id collision: %s is kind %r in wip but %r in central'
                            % (nid, wip.nodes[nid]['kind'], central.nodes[nid]['kind']))
    synced = []

    # 1. add nodes central does not have yet (dependency-tolerant passes;
    #    add_node validates, so a node only goes in once its refs exist).
    #    Relations are inserted FILTERED to wires already present -- a node
    #    and its wire reference each other, so the full relation list is
    #    patched by pass 2 once every wire exists.
    pending = [nid for nid in ids if nid not in central.nodes]
    while pending:
        progressed = []
        for nid in pending:
            if _refs_present(central, wip.nodes[nid]):
                candidate = copy.deepcopy(wip.nodes[nid])
                candidate['relations'] = [w for w in candidate['relations']
                                          if w in central.nodes]
                central.apply_op({'op': 'add_node', 'node': candidate})
                synced.append(nid)
                progressed.append(nid)
        if not progressed:
            raise SyncError('unsyncable subgraph: %r reference nodes outside '
                            'the session closure' % (pending,))
        pending = [nid for nid in pending if nid not in progressed]

    # 2. update every node that differs, field by field, through apply_op
    #    (this also completes the relation lists of freshly added nodes)
    for nid in ids:
        wn, cn = wip.nodes[nid], central.nodes[nid]
        # the session node itself: sync its BODY (content roots) only --
        # its params carry governance (stage) which never syncs
        fields = ('body',) if nid == session_id else ('title', 'params', 'body', 'relations')
        changed = False
        for field in fields:
            if wn[field] != cn[field]:
                central.apply_op({'op': 'set', 'id': nid, 'path': [field],
                                  'value': copy.deepcopy(wn[field])})
                changed = True
        if changed and nid not in synced:
            synced.append(nid)
    return synced


# --------------------------------------------------------------- ui-from-nodes

def ui_element(store, tag, text=None, bind=None, children=None, title='',
               cls=None, attrs=None, style=None):
    """Create a ui-element NODE (kind='ui') in the one table. Its params are
    param NODES: tag (value floor), text (value floor), bind (REFERENCE floor
    to the bound node -- the binding is live graph logic), children (value
    floor holding the child ui node ids), cls (value floor: the CSS class -- so
    the app's LOOK is itself node data, section 10). The ui node's own body is
    a reference to its tag param, so opening it hits a real floor primitive."""
    params = {'tag': store.add('param', 'tag', floor={'op': 'value', 'value': tag})}
    if cls is not None:
        params['cls'] = store.add('param', 'cls', floor={'op': 'value', 'value': cls})
    if text is not None:
        params['text'] = store.add('param', 'text', floor={'op': 'value', 'value': text})
    if bind is not None:
        if bind not in store.nodes:
            raise ValueError('bind target %r not in the one table' % (bind,))
        params['bind'] = store.add('param', 'bind',
                                   floor={'op': 'reference', 'target': bind})
    if children is not None:
        for cid in children:
            if store.nodes[cid]['kind'] != 'ui':
                raise ValueError('child %r is kind %r, not ui'
                                 % (cid, store.nodes[cid]['kind']))
        params['children'] = store.add('param', 'children',
                                       floor={'op': 'value', 'value': list(children)})
    if attrs is not None:
        params['attrs'] = store.add('param', 'attrs',
                                    floor={'op': 'value', 'value': dict(attrs)})
    if style is not None:
        params['style'] = store.add('param', 'style',
                                    floor={'op': 'value', 'value': dict(style)})
    return store.add('ui', title or tag,
                     floor={'op': 'reference', 'target': params['tag']},
                     params=params)


def render(store, ui_root):
    """PURE render: walk the one table from a ui node and return HTML.
    No template, no second source -- text comes from pulling the text param
    node, bound values from pulling the bind param node (a live reference),
    the class from the cls param, children from the children param node. The
    page IS the nodes."""
    node = store.nodes[ui_root]
    if node['kind'] != 'ui':
        raise ValueError('render root %s is kind %r, not ui' % (ui_root, node['kind']))
    params = node['params']
    tag = str(store.pull(params['tag']))
    cls = ''
    if 'cls' in params:
        cls = ' class="%s"' % _html.escape(str(store.pull(params['cls'])), quote=True)
    attrs = ''
    if 'attrs' in params:
        raw_attrs = store.pull(params['attrs'])
        if isinstance(raw_attrs, dict):
            bits = []
            for name, value in raw_attrs.items():
                safe_name = ''.join(ch for ch in str(name)
                                    if ch.isalnum() or ch in ('-', '_', ':'))
                if safe_name and safe_name != 'class':
                    if isinstance(value, dict) and value.get('$bind') in store.nodes:
                        value = store.pull(value['$bind'])
                    bits.append('%s="%s"' % (
                        safe_name, _html.escape(str(value), quote=True)))
            if bits:
                attrs = ' ' + ' '.join(bits)
    parts = []
    if 'text' in params:
        parts.append(_html.escape(str(store.pull(params['text']))))
    if 'bind' in params:
        parts.append(_html.escape(str(store.pull(params['bind']))))
    if 'children' in params:
        parts.extend(render(store, cid) for cid in store.pull(params['children']))
    return '<%s data-node="%s"%s%s>%s</%s>' % (
        tag, ui_root, cls, attrs, ''.join(parts), tag)


# --------------------------------------------------------------- secret-ref

def resolve_secret(store, node_id, resolver):
    """Resolve a secret_ref node at PULL-TIME through the injected resolver.
    The resolved value is returned to the caller and written NOWHERE: not
    into the node, not into the memo, not into history. The graph only ever
    contains the op:// reference (core validate_node enforces that shape)."""
    node = store.nodes[node_id]
    if node['kind'] != 'secret_ref':
        raise ValueError('node %s is kind %r, not secret_ref' % (node_id, node['kind']))
    ref = node['body']['floor']['ref']
    if not ref.startswith('op://'):
        raise OneTableViolation('secret_ref %s ref %r is not an op:// reference'
                                % (node_id, ref))
    return resolver(ref)
