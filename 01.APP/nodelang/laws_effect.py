"""nodelang.laws_effect -- the effectful laws over THE ONE TABLE.

SLICE (SPEC.md sections 4, 5b): an effectful node is FROZEN by default. It
carries dry-run / apply / revert, and every step is an append-only history
NODE in the same one table. There is NO second store, NO class per kind: an
effect node is an ordinary node of kind='op' whose floor op is 'effect'; apply
and revert are FUNCTIONS over ``Store`` that route through ``Store.apply_op``
(so they land in history) and mutate an EXTERNAL sink that the caller owns.

The external sink (SPEC section 5b -- "a mutable external sink"): a plain
mutable mapping (a dict, or anything with __getitem__/__setitem__/__contains__
-- e.g. a shelve-backed dict for a file). It is NOT a node and NEVER lives in
the one table; the graph plans changes to it, it never becomes graph state.

The contract (SPEC sections 4 / 5b):

  DRY-RUN (frozen, the default)
      ``store.pull(effect_id)`` computes the PLANNED change and returns it
      WITHOUT touching the sink -- {'fired': False, 'dry_run': True,
      'plan': {'target': k, 'change': v}}. pull() is pure by construction
      (core._compute cannot reach the sink), so nothing mutates.

  APPLY (only after a deliberate unfreeze)
      ``apply_effect(store, node_id, sink)`` refuses while frozen (that IS the
      gate). Once unfrozen it reads the sink's current value at 'target',
      writes 'change', and records a REVERT TOKEN as a history node (the op
      carries the before-image). Idempotent: a second apply with the sink
      already at 'change' is a no-op that still audits (fired=False,
      idempotent=True) so history never lies about what happened.

  REVERT (undo via the token)
      ``revert_effect(store, node_id, sink)`` finds the newest un-reverted
      apply token for this node in history, restores the sink to the token's
      before-image, and records a revert history node. Reverting twice is
      refused (nothing left to revert) -- history is append-only, so a revert
      is a NEW entry, never an erasure (SPEC section 5b / section 19 RFC-6962).

Whitelisted engine coupling: apply/revert read the append-only history nodes
already in ``store.nodes`` (via floor.entry) to find their tokens -- they add
NO new container. The sink is the caller's; we never stash it on the store.
"""
from __future__ import annotations

import copy

from .core import (  # noqa: F401  (re-export for callers)
    FrozenNode, Store, relation_sources, relation_stages, relation_targets,
)


_MISSING = object()  # the sink had no value at 'target' before apply


def _effect_floor(store, node_id):
    """Return the effect node's floor, asserting it IS an effect node."""
    node = store.nodes[node_id]
    if 'floor' not in node['body'] or node['body']['floor'].get('op') != 'effect':
        raise ValueError('laws_effect: %s is not an effect node' % node_id)
    floor = node['body']['floor']
    if 'target' not in floor:
        raise ValueError('laws_effect: effect %s has no target (need target/change '
                         'to mutate a sink)' % node_id)
    return floor


def _plan(store, node_id):
    """The planned change as the dry-run pull reports it (pure)."""
    marker = store.pull(node_id)
    return marker['plan']  # {'target': k, 'change': v}


def _assert_computed_guards(store, node_id):
    """Refuse apply when an incoming relation's executable guard is closed."""
    for relation_id in store.nodes[node_id]['relations']:
        relation = store.nodes.get(relation_id)
        if not relation or relation['kind'] != 'wire':
            continue
        if not any(endpoint.get('node_id') == node_id
                   for endpoint in relation_targets(store.nodes, relation)):
            continue
        guards = [stage for stage in relation_stages(store.nodes, relation)
                  if stage.get('mode') == 'guard']
        if not guards:
            continue
        sources = relation_sources(store.nodes, relation)
        source_values = [store.pull(endpoint['node_id']) for endpoint in sources]
        item = source_values[0] if len(source_values) == 1 else source_values
        for guard in guards:
            if not bool(store.pull(guard['node_id'], {'item': item})):
                raise FrozenNode(
                    'apply_effect: %s computed guard %s is closed'
                    % (node_id, guard['node_id']))


def _apply_tokens(store, node_id):
    """Every 'effect_apply' history token for node_id, oldest -> newest.
    Read straight out of the one table's history nodes (no side container)."""
    tokens = []
    for nid in sorted(store.nodes):  # zero-padded ids sort into creation order
        n = store.nodes[nid]
        if n['kind'] != 'history':
            continue
        entry = n['body']['floor']['entry']
        if entry.get('op') in ('effect_apply', 'effect_revert') and entry.get('effect') == node_id:
            tokens.append((nid, entry))
    return tokens


def _live_token(store, node_id):
    """The newest apply token that has NOT been reverted since, or None.
    Applies and reverts interleave in history order; the last apply with no
    following revert is the one a revert would undo."""
    live = None
    for _hid, entry in _apply_tokens(store, node_id):
        if entry['op'] == 'effect_apply':
            live = entry
        elif entry['op'] == 'effect_revert':
            live = None
    return live


# ------------------------------------------------------------- dry-run

def dry_run(store, node_id):
    """The planned change, computed WITHOUT touching any sink. Convenience
    over ``store.pull`` that also asserts the node is frozen (the default
    safe state). Returns the plan dict {'target', 'change'}."""
    node = store.nodes[node_id]
    if not node['meta'].get('frozen'):
        raise FrozenNode('dry_run: %s is unfrozen; pull would report a live '
                         'plan, use apply_effect to actually fire' % node_id)
    _effect_floor(store, node_id)
    return _plan(store, node_id)


# ------------------------------------------------------------- apply

def apply_effect(store, node_id, sink, actor='user'):
    """Perform the real mutation on ``sink`` -- ONLY when the effect node has
    been deliberately unfrozen. Records a revert token as a history node.

    Returns {'fired': bool, 'target', 'before', 'after', ...}. Idempotent: if
    the sink already holds 'change', nothing is written but the fact is still
    audited (fired=False, idempotent=True)."""
    node = store.nodes[node_id]
    if node['meta'].get('frozen'):
        raise FrozenNode('apply_effect: %s is frozen -- unfreeze deliberately '
                         'before firing (SPEC section 4/5b)' % node_id)
    _assert_computed_guards(store, node_id)
    floor = _effect_floor(store, node_id)
    plan = _plan(store, node_id)            # while unfrozen, plan reflects live floor
    target, change = plan['target'], plan['change']

    before = sink[target] if target in sink else _MISSING
    if before is not _MISSING and before == change:
        # already there: a second apply is a no-op, but still audits truthfully
        op = {'op': 'effect_apply', 'effect': node_id, 'target': target,
              'before': copy.deepcopy(change), 'after': copy.deepcopy(change),
              'fired': False, 'idempotent': True, 'actor': actor}
        store.apply_op(op)
        return {'fired': False, 'idempotent': True, 'target': target,
                'before': copy.deepcopy(change), 'after': copy.deepcopy(change)}

    sink[target] = copy.deepcopy(change)     # THE real mutation
    before_token = None if before is _MISSING else copy.deepcopy(before)
    op = {'op': 'effect_apply', 'effect': node_id, 'target': target,
          'before': before_token, 'before_missing': before is _MISSING,
          'after': copy.deepcopy(change), 'fired': True, 'actor': actor}
    store.apply_op(op)                        # revert token = history node
    return {'fired': True, 'idempotent': False, 'target': target,
            'before': before_token, 'before_missing': before is _MISSING,
            'after': copy.deepcopy(change)}


# ------------------------------------------------------------- revert

def revert_effect(store, node_id, sink, actor='user'):
    """Undo the newest un-reverted apply via its token: restore the sink to the
    before-image (or delete the key if it did not exist before). Records a
    revert history node. Refuses when there is nothing live to revert."""
    _effect_floor(store, node_id)
    token = _live_token(store, node_id)
    if token is None:
        raise ValueError('revert_effect: %s has no applied effect to revert' % node_id)
    target = token['target']
    if token.get('before_missing'):
        restored = _MISSING
        if target in sink:
            del sink[target]                 # THE real un-mutation
    else:
        restored = copy.deepcopy(token['before'])
        sink[target] = restored              # THE real un-mutation
    op = {'op': 'effect_revert', 'effect': node_id, 'target': target,
          'restored': None if restored is _MISSING else copy.deepcopy(restored),
          'restored_missing': restored is _MISSING, 'actor': actor}
    store.apply_op(op)                        # a revert is a NEW entry, never an erasure
    return {'reverted': True, 'target': target,
            'restored': None if restored is _MISSING else copy.deepcopy(restored),
            'restored_missing': restored is _MISSING}
