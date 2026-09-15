"""Stop admission from the current native Work authority, without replaying work.

The completion court owns acceptance. A Stop hook only observes that state; it
does not run a second test evaluator or invent submission/artifact evidence.
"""
from __future__ import annotations


def completion_verdict(cwd=None, *, runtime='', session_id='', transport=None):
    if not callable(transport) or not runtime or not session_id:
        return True, 'Bound native Work authority is required; no fallback enrollment.'
    try:
        status = transport('brain.universal_work_status',
                           {'vendor': runtime, 'session_id': session_id})
    except Exception:
        return True, 'Native Work status is unavailable; retained outcomes must be reconciled.'
    if (type(status) is not dict or status.get('isError')
            or type(status.get('agent_session')) is not str or not status['agent_session']
            or type(status.get('items')) not in (list, tuple)):
        return True, 'Native Work status identity or items are invalid.'
    owned = []
    for item in status['items']:
        if (type(item) is not dict or type(item.get('root')) is not str or not item['root']
                or type(item.get('operational')) is not dict
                or type(item['operational'].get('current_state_label')) is not str):
            return True, 'Native Work status row is invalid.'
        state = item['operational']['current_state_label'].casefold()
        if state not in {'open', 'claimed', 'review', 'blocked', 'complete', 'cancelled'}:
            return True, 'Native Work state is unknown.'
        if item.get('claimant_session') == status['agent_session']:
            if state == 'open':
                return True, 'Open Work retains a claimant; reconcile its graph state.'
            if state in {'claimed', 'review', 'blocked'}:
                owned.append((item['root'], state))
    if len(owned) > 1:
        return True, 'The Agent Session owns multiple unfinished Works; reconcile ownership.'
    if owned:
        return True, ('Current Work remains ' + owned[0][1] +
            '. Publish and independently review its real result, then submit through the Work court. '
            'This Stop hook does not rerun execution, submit evidence or grant completion.')
    # Ending this turn is not a declaration that the product or every Work is done.
    return False, ''
