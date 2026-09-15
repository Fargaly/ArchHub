"""Bounded read of existing Work history for one authenticated prior claim."""
from .cell_protocols import read_relation
from .cell_state_machine import _read_transition_event
from .universal_cell import InvalidCell, MatchBudgetExceeded


def read_release_recovery(snapshot, registry, *, authentication_context,
                          agent_session_root, work_root, claim_binding, after_revision):
    """Return positive release evidence only; absence never proves non-execution.

    The machine route must hold its mutation/admission lock and derive the session
    and context itself. No supplied identity becomes an execution permission.
    """
    from . import universal_application as app

    if type(after_revision) is not int or not 0 <= after_revision <= snapshot.revision:
        raise InvalidCell('Release recovery revision is invalid')
    for value in (work_root, claim_binding, agent_session_root):
        if type(value) is not str or not value or len(value.encode('utf-8')) > 512 or '\0' in value:
            raise InvalidCell('Release recovery identity is invalid')
    view, context = app._view_session_for_context(registry, authentication_context)
    visible, _, _ = app._session_canvas_roots(snapshot, registry, view)
    if work_root not in visible:
        raise InvalidCell('Release recovery Work is outside the admitted view')
    app._require_application_authorization(snapshot, registry, 'read', work_root,
                                           authentication_context=context)
    binding = app._read_governed_work_claim_binding(snapshot, registry, claim_binding)
    if binding['work'] != work_root or binding['session'] != agent_session_root:
        raise InvalidCell('Release recovery claim belongs to another Work or session')
    protocol = registry.standard_library.state_machine_protocol
    machine = app.read_instance_state_machine(snapshot, registry.assembly_protocol, protocol, work_root)
    try:
        members = read_relation(snapshot, machine.history_root, budget=4096)
    except MatchBudgetExceeded as error:
        raise InvalidCell('Release history exceeds the bounded read; exact receipt inspection is required, do not retry release') from error
    if any(row.role_id != protocol.role('history-member') for row in members):
        raise InvalidCell('Release recovery history is malformed')
    events = [_read_transition_event(snapshot, protocol, row.participant_id) for row in members]
    claims = [index for index, event in enumerate(events)
              if claim_binding in event.context_roots
              and app._text(snapshot, event.event_root).casefold() == 'claim'
              and app._text(snapshot, event.to_state_root).casefold() == 'claimed'
              and event.actor_root == agent_session_root
              and work_root in event.context_roots]
    if len(claims) != 1:
        raise InvalidCell('Release recovery cannot identify the exact original claim')
    receipt = None
    for event in events[claims[0]+1:]:
        name = app._text(snapshot, event.event_root).casefold()
        if name == 'claim':
            break
        if name == 'release':
            if (event.actor_root != agent_session_root or work_root not in event.context_roots
                    or app._text(snapshot, event.from_state_root).casefold() != 'claimed'
                    or app._text(snapshot, event.to_state_root).casefold() != 'open'):
                raise InvalidCell('Release recovery history does not match the original claimant')
            receipt = event.root_id
            break
    return {'projection':'release-recovery', 'work_root':work_root,
            'agent_session':agent_session_root, 'claim_binding':claim_binding,
            'revision':snapshot.revision, 'after_revision':after_revision,
            'released':receipt is not None, 'history_root':receipt,
            'receipt_reconstructed':False}
