"""nodelang.drivers -- ONE GRAPH, TWO DRIVERS (SPEC sections 12, 5b, 4).

The law:
  * ONE running graph (one Store). The user and the AI drive the SAME graph
    through the SAME single edit path (Store.apply_op). No second engine,
    no AI-private mutation path.
  * The USER driver edits directly: user_edit() -> apply_op with actor='user'.
  * The AI driver NEVER silently mutates. ai_propose() lands a kind='proposal'
    NODE in the one table -- visible, openable (its body holds the proposed
    op), state 'pending', frozen so nobody tampers with what was proposed.
    The graph the proposal targets DOES NOT CHANGE.
  * approve() applies the proposed op via apply_op (recording the approving
    actor + a 'via_proposal' link -- the history shows the proposal->apply
    chain). reject() leaves the graph untouched.
  * FROZEN targets (SPEC section 4/5b): a frozen node refuses 'set'. Approving
    a proposal against a frozen node is a deliberate TWO-STEP: an explicit
    'unfreeze' op (audited) and then the edit. approve(..., unfreeze_target=True)
    performs exactly those two audited ops; without it the approval raises
    FrozenNode and the graph stays untouched.

Everything here is a thin choreography over Store.apply_op -- proposals,
their state changes, unfreezes and the applied edits ALL land as history
nodes in the ONE table. There is no proposal registry, no pending queue,
no second container: a proposal IS a node; "pending" is data in its body.
"""
from __future__ import annotations

import copy

from .core import FrozenNode

USER = 'user'
AI = 'ai'


# --------------------------------------------------------------- user driver

def user_edit(store, nid, path, value, actor=USER):
    """The direct driver: a plain audited edit on the one graph."""
    return store.apply_op({'op': 'set', 'id': nid, 'path': list(path),
                           'value': value, 'actor': actor})


# ----------------------------------------------------------------- AI driver

def ai_propose(store, op, actor=AI, note=''):
    """The AI's ONLY write: land a kind='proposal' node. The proposed op is
    the proposal's BODY (open the node, see exactly what would happen).
    The target graph does not change. Returns the proposal node id."""
    node = store._blank(
        'proposal',
        'proposal:%s' % op.get('op', '?'),
        None,
        {'floor': {'op': 'value',
                   'value': {'proposed_op': copy.deepcopy(op),
                             'state': 'pending',
                             'note': note}}},
        True,  # frozen: the proposed op cannot be tampered with while pending
    )
    return store.apply_op({'op': 'add_node', 'node': node, 'actor': actor})


def proposal_state(store, pid):
    return store.nodes[pid]['body']['floor']['value']['state']


def _set_state(store, pid, state, actor):
    """Proposal state transitions are themselves audited ops: the proposal is
    frozen, so flipping its state is the explicit unfreeze/set/freeze dance --
    three history nodes, no back door."""
    store.apply_op({'op': 'unfreeze', 'id': pid, 'actor': actor})
    store.apply_op({'op': 'set', 'id': pid,
                    'path': ['body', 'floor', 'value', 'state'],
                    'value': state, 'actor': actor})
    store.apply_op({'op': 'freeze', 'id': pid, 'actor': actor})


def approve(store, pid, actor=USER, unfreeze_target=False):
    """Apply a pending proposal via the ONE edit path.

    If the proposed op targets a FROZEN node this raises FrozenNode and the
    graph stays untouched (the proposal stays pending) -- unless
    unfreeze_target=True, in which case an explicit audited 'unfreeze' op is
    applied first (the two-step of SPEC section 5b).
    Returns whatever apply_op returned for the proposed op."""
    prop = store.nodes[pid]
    if prop['kind'] != 'proposal':
        raise ValueError('%s is kind %r, not a proposal' % (pid, prop['kind']))
    state = proposal_state(store, pid)
    if state != 'pending':
        raise ValueError('proposal %s is %r, not pending' % (pid, state))

    inner = copy.deepcopy(prop['body']['floor']['value']['proposed_op'])
    inner['actor'] = actor              # the APPROVER drives the apply
    inner['via_proposal'] = pid         # the history chain proposal -> apply

    target_id = inner.get('id')
    target = store.nodes.get(target_id) if target_id else None
    if target is not None and target['meta'].get('frozen') \
            and inner.get('op') not in ('freeze', 'unfreeze'):
        if not unfreeze_target:
            # refuse BEFORE touching anything; graph + proposal unchanged
            raise FrozenNode(
                'proposal %s targets frozen node %s; approve with '
                'unfreeze_target=True (explicit two-step)' % (pid, target_id))
        store.apply_op({'op': 'unfreeze', 'id': target_id,
                        'actor': actor, 'via_proposal': pid})

    out = store.apply_op(inner)
    _set_state(store, pid, 'approved', actor)
    return out


def reject(store, pid, actor=USER):
    """Reject a pending proposal: the target graph is left untouched; only
    the proposal's own state flips (audited)."""
    prop = store.nodes[pid]
    if prop['kind'] != 'proposal':
        raise ValueError('%s is kind %r, not a proposal' % (pid, prop['kind']))
    if proposal_state(store, pid) != 'pending':
        raise ValueError('proposal %s is not pending' % pid)
    _set_state(store, pid, 'rejected', actor)
    return pid


# ------------------------------------------------------------------ helpers

def add_effect(store, title, payload, frozen=True, actor=USER):
    """An effectful node (SPEC section 4): frozen by default -- pulling it
    yields a dry-run marker, never a firing, until an explicit unfreeze op."""
    return store.add('op', title, floor={'op': 'effect', 'payload': payload},
                     frozen=frozen, actor=actor)


def history_entries(store):
    """The complete audit: every applied op, in order, straight from the
    history NODES in the one table (no side log exists to consult)."""
    hist = [n for n in store.nodes.values() if n['kind'] == 'history']
    hist.sort(key=lambda n: n['meta']['seq'])
    return [n['body']['floor']['entry'] for n in hist]
