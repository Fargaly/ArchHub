"""nodelang.laws_structure -- the structural laws over THE ONE TABLE.

SLICE 2 of the ground-up build (SPEC.md sections 1, 3, 7, 8; section 19
forcing). Everything here is a FUNCTION over ``Store`` -- there is no class
per kind, no second container, no meta-layer. Every mutation routes through
``Store.apply_op`` (so every move lands in the append-only history, in the
same one table).

The laws:

  RELATION OPENS INTO A GATE (section 7)
      A relation IS a node (kind='wire' is its presentational role in the one
      table). It opens into ordered endpoint parameter nodes and ordinary
      executable stage nodes. ``set_gate`` puts any truthy/falsy node inside
      the relation and names it as the gate stage; ``clear_gate`` removes that
      stage assignment. Gate
      false -> the wire conducts its last held value, or NO value if it never
      conducted (downstream input lists omit it). Gate true -> conducts live.
      Because the gate is an ordinary node read through the ordinary dirty
      chain, flipping a value the gate READS recooks downstream without ever
      touching the wire.

  GROUP RUNS AS NODE (sections 3, 4)
      ``group`` puts ONE group node in the table whose body lists the inner
      ids; its computed ports are the wires crossing the boundary (core's
      ``_compute_group``); its value is the live result of the inners.
      ``ungroup`` is the exact inverse (collapse-then-expand = identity):
      the group node dissolves, children splice back where the group stood.
      Regrouping the same nodes differently MUST NOT change any pulled value
      (the operad forcing, section 19) -- wires bind node ids, and grouping
      adds structure without rewriting a single wire.

  PARAM-AS-NODE (section 2, table row 1)
      ``promote_param`` pulls an inline floor field out into a real node of
      kind='param' in the same one table, wires it in via the owner's
      ``params`` map, and leaves a {'$param': name} marker in the floor.
      Editing the param NODE recooks the owner. ``demote_param`` is the
      inverse: the literal returns to the floor -- identity.

  SCALE = GROUPING (section 8)
      There is no other mechanism. Nesting groups IS scale; ``Store.open``
      shows exactly one level; pulling at the top runs through all levels.
"""
from __future__ import annotations

from .core import (  # noqa: F401  (re-export NO_VALUE)
    NO_VALUE, FrozenNode, Store, relation_stages, validate_node,
)


# --------------------------------------------------------- relation stages

def set_relation_stage(store, relation_id, role, stage_id, mode='map'):
    """Assign an ordinary inner node as an executable relation stage.

    The assignment is itself a parameter node. Nothing authoritative is kept
    in metadata or a side registry.
    """
    relation = store.nodes[relation_id]
    if relation['kind'] != 'wire':
        raise ValueError('set_relation_stage: %s is not a relation' % relation_id)
    if stage_id not in store.nodes:
        raise KeyError('set_relation_stage: stage %r not in the one table' % stage_id)
    if mode not in ('guard', 'map', 'tap'):
        raise ValueError('set_relation_stage: invalid mode %r' % mode)

    existing = next((stage for stage in relation_stages(store.nodes, relation)
                     if stage.get('role') == role), None)
    old_stage_id = existing.get('node_id') if existing else None
    inner = list(relation['body']['inner'])
    if stage_id not in inner:
        inner.append(stage_id)

    spec = {'role': str(role), 'mode': mode, 'node_id': stage_id}
    if existing:
        store.edit(existing['assignment_param'], ['body', 'floor', 'value'], spec)
    else:
        indexes = [int(name.split(':', 1)[1]) for name in relation['params']
                   if name.startswith('stage:') and name.split(':', 1)[1].isdigit()]
        name = 'stage:%03d' % ((max(indexes) + 1) if indexes else 0)
        assignment = store.add('param', name,
                               floor={'op': 'value', 'value': spec})
        params = dict(relation['params'])
        params[name] = assignment
        store.edit(relation_id, ['params'], params)
        inner.append(assignment)

    remaining_stage_ids = {stage.get('node_id')
                           for stage in relation_stages(store.nodes, relation)}
    if old_stage_id and old_stage_id != stage_id and old_stage_id not in remaining_stage_ids:
        inner = [nid for nid in inner if nid != old_stage_id]
    store.edit(relation_id, ['body', 'inner'], list(dict.fromkeys(inner)))
    validate_node(store.nodes, relation)
    return relation_id


def clear_relation_stage(store, relation_id, role):
    """Detach a stage assignment; the ordinary stage node remains reusable."""
    relation = store.nodes[relation_id]
    if relation['kind'] != 'wire':
        raise ValueError('clear_relation_stage: %s is not a relation' % relation_id)
    existing = next((stage for stage in relation_stages(store.nodes, relation)
                     if stage.get('role') == role), None)
    if not existing:
        return relation_id
    params = {name: pid for name, pid in relation['params'].items()
              if pid != existing['assignment_param']}
    store.edit(relation_id, ['params'], params)
    still_used = {stage.get('node_id') for stage in relation_stages(store.nodes, relation)}
    remove_ids = {existing['assignment_param']}
    if existing.get('node_id') not in still_used:
        remove_ids.add(existing.get('node_id'))
    store.edit(relation_id, ['body', 'inner'],
               [nid for nid in relation['body']['inner'] if nid not in remove_ids])
    validate_node(store.nodes, relation)
    return relation_id


# ---------------------------------------------------------- relation gates

def set_gate(store, wire_id, gate_id):
    """Put an ordinary node inside a relation and assign it as its gate stage."""
    wire = store.nodes[wire_id]
    if wire['kind'] != 'wire':
        raise ValueError('set_gate: %s is kind %r, not wire' % (wire_id, wire['kind']))
    if gate_id not in store.nodes:
        raise KeyError('set_gate: gate %r not in the one table' % (gate_id,))
    return set_relation_stage(store, wire_id, 'gate', gate_id, mode='guard')


def clear_gate(store, wire_id):
    """Remove the gate-stage assignment without deleting the gate node."""
    wire = store.nodes[wire_id]
    if wire['kind'] != 'wire':
        raise ValueError('clear_gate: %s is kind %r, not wire' % (wire_id, wire['kind']))
    return clear_relation_stage(store, wire_id, 'gate')


# ------------------------------------------------------------- group / ungroup

def group(store, node_ids, title='group'):
    """Lasso node_ids -> ONE group node in the one table. Its ports and value
    are computed by the engine from the wires crossing the boundary."""
    node_ids = list(node_ids)
    if not node_ids:
        raise ValueError('group: nothing to group')
    for nid in node_ids:
        if nid not in store.nodes:
            raise KeyError('group: %r not in the one table' % (nid,))
    return store.add('group', title, inner=node_ids)


def ungroup(store, group_id):
    """Dissolve a group: children return to where the group stood (spliced
    into any parent group's inner list). group-then-ungroup = identity."""
    node = store.nodes[group_id]
    if 'inner' not in node['body']:
        raise ValueError('ungroup: %s is not group-ish' % group_id)
    children = list(node['body']['inner'])
    store.apply_op({'op': 'dissolve_group', 'id': group_id})
    return children


# ------------------------------------------------------------- param-as-node

def promote_param(store, node_id, param_name):
    """The inline floor field ``param_name`` becomes a real param NODE in the
    one table, wired in via the owner's params map. Returns the param id."""
    node = store.nodes[node_id]
    if 'floor' not in node['body']:
        raise ValueError('promote_param: %s is group-ish; its params derive '
                         'from its inners (section 3)' % node_id)
    floor = node['body']['floor']
    if param_name not in floor:
        raise KeyError('promote_param: %s floor has no field %r' % (node_id, param_name))
    raw = floor[param_name]
    if isinstance(raw, dict) and '$param' in raw:
        raise ValueError('promote_param: %s.%s is already promoted' % (node_id, param_name))
    pid = store.add('param', '%s.%s' % (node['title'] or node_id, param_name),
                    floor={'op': 'value', 'value': raw})
    store.edit(node_id, ['params', param_name], pid)
    store.edit(node_id, ['body', 'floor', param_name], {'$param': param_name})
    return pid


def demote_param(store, node_id, param_name):
    """Inverse of promote: the param node's current value returns to the floor
    as a literal and the params entry is dropped. promote-then-demote =
    identity. (The param node stays in the table, unreferenced -- the table
    is append-friendly; nothing points at it any more.)"""
    node = store.nodes[node_id]
    pid = node['params'].get(param_name)
    if pid is None:
        raise KeyError('demote_param: %s has no promoted param %r' % (node_id, param_name))
    marker = node['body']['floor'].get(param_name)
    if not (isinstance(marker, dict) and marker.get('$param') == param_name):
        raise ValueError('demote_param: %s.%s floor field is not a $param marker'
                         % (node_id, param_name))
    value = store.pull(pid)
    store.edit(node_id, ['body', 'floor', param_name], value)
    store.edit(node_id, ['params'],
               {k: v for k, v in node['params'].items() if k != param_name})
    return node_id
