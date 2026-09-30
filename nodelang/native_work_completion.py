"""Stop admission from the current native Work authority, without replaying work.

The completion court owns acceptance. A Stop hook only observes that state; it
does not run a second test evaluator or invent submission/artifact evidence.

Every block names each unfinished Work of this session and its one step (live
717 and Ping, 2026-09-30). A submitted Work has no accepted verdict until its
submitter runs native.work_request_court; the "stop-gate" read says whether the
court admits the submission as it stands (work_review_wait).
"""
from __future__ import annotations


def _step(root, state, wait):
    if state != 'review':
        return '%s is %s' % (root, state)
    court = ('%s has no accepted verdict; run native.work_request_court (attach it first: '
             'native.work_task_attach %s)' % (root, root))
    if wait['wait'] == 'reconcile':
        return court + ('. Its court refuses this submission as it stands (%s), so reconcile it with '
                        "the Work's owner" % wait['reason'])
    if wait['wait'] == 'unknown':
        return court + '. This gate could not check the submission (%s)' % wait['reason']
    return court


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
    # An application without the "stop-gate" read names a submitted Work with the court step.
    waits = status.get('review_waits') if type(status.get('review_waits')) is dict else {}
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
                return True, 'Open Work %s retains a claimant; reconcile its graph state.' % item['root']
            if state in {'claimed', 'review', 'blocked'}:
                owned.append((item['root'], state, waits.get(item['root'], {'wait': 'court', 'reason': ''})))
    if len(owned) > 1:
        return True, ('This session has %d unfinished Works, each its own step: %s.'
                      % (len(owned), '; '.join(_step(*row) for row in owned[:20]))
                      + (' And %d more.' % (len(owned) - 20) if len(owned) > 20 else '')
                      + ' This Stop hook does not rerun execution, submit evidence or grant completion.')
    if owned:
        root, state, wait = owned[0]
        text = (_step(root, state, wait) + '.' if state == 'review' else
                'Current Work %s remains %s. Publish and independently review its real result, then submit '
                'through the Work court.' % (root, state))
        return True, text + ' This Stop hook does not rerun execution, submit evidence or grant completion.'
    # Ending this turn is not a declaration that the product or every Work is done.
    return False, ''
