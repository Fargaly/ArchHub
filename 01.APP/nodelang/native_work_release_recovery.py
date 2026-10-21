"""Bounded read of existing Work history for one authenticated prior claim."""
import json

from .cell_protocols import read_relation
from .cell_state_machine import _read_transition_event, read_evidence
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


_VERDICT_DETAILS = 16
_VERDICT_TEXT = 300


def court_verdict(snapshot, registry, attestation_root):
    """The court's own bounded verdict from its signed attestation: result, checks, details.

    The full signed statement stays in the graph under attestation_root.
    """
    from .cell_attestations import read_court_attestation

    attestation = read_court_attestation(snapshot, registry.attestation_protocol, attestation_root)
    if attestation.court_root != registry.work_completion_court_root:
        raise InvalidCell('Court verdict attestation belongs to another court')
    try:
        predicate = json.loads(snapshot.cells[attestation.payload_root].atom.decode('utf-8'))['predicate']
        result, checks, details = predicate['result'], predicate['checks'], predicate['details']
        invocation = predicate['invocation']
    except (KeyError, TypeError, ValueError, UnicodeError) as error:
        raise InvalidCell('Court verdict attestation is malformed') from error
    if (result not in ('pass', 'fail') or type(checks) is not dict or type(details) is not dict
            or type(invocation) is not dict or len(checks) > _VERDICT_DETAILS
            or any(type(name) is not str or type(value) is not bool for name, value in checks.items())):
        raise InvalidCell('Court verdict attestation is malformed')
    return {'result': result, 'checks': dict(sorted(checks.items())),
            'details': {str(key)[:64]: str(value)[:_VERDICT_TEXT]
                        for key, value in sorted(details.items())[:_VERDICT_DETAILS]},
            'submit_event': str(invocation.get('submitEvent', ''))[:512],
            'attestation_root': attestation_root}


def _claim_history(snapshot, registry, *, authentication_context, agent_session_root, work_root, claim_binding):
    """The Work's events after its exact original claim, up to the next claim or release."""
    from . import universal_application as app

    for value in (work_root, claim_binding, agent_session_root):
        if type(value) is not str or not value or len(value.encode('utf-8')) > 512 or '\0' in value:
            raise InvalidCell('Court recovery identity is invalid')
    view, context = app._view_session_for_context(registry, authentication_context)
    visible, _, _ = app._session_canvas_roots(snapshot, registry, view)
    if work_root not in visible:
        raise InvalidCell('Court recovery Work is outside the admitted view')
    app._require_application_authorization(snapshot, registry, 'read', work_root,
                                           authentication_context=context)
    binding = app._read_governed_work_claim_binding(snapshot, registry, claim_binding)
    if binding['work'] != work_root or binding['session'] != agent_session_root:
        raise InvalidCell('Court recovery claim belongs to another Work or session')
    protocol = registry.standard_library.state_machine_protocol
    machine = app.read_instance_state_machine(snapshot, registry.assembly_protocol, protocol, work_root)
    try:
        members = read_relation(snapshot, machine.history_root, budget=4096)
    except MatchBudgetExceeded as error:
        raise InvalidCell('Court history exceeds the bounded read; exact receipt inspection is '
                          'required, do not retry the court') from error
    if any(row.role_id != protocol.role('history-member') for row in members):
        raise InvalidCell('Court recovery history is malformed')
    events = [_read_transition_event(snapshot, protocol, row.participant_id) for row in members]

    def name(event):
        return app._text(snapshot, event.event_root).casefold()

    claims = [index for index, event in enumerate(events)
              if claim_binding in event.context_roots and name(event) == 'claim'
              and event.actor_root == agent_session_root and work_root in event.context_roots]
    if len(claims) != 1:
        raise InvalidCell('Court recovery cannot identify the exact original claim')
    held = []
    for event in events[claims[0]+1:]:
        if name(event) in ('claim', 'release'):
            break
        held.append(event)
    return held, name, events[-1], protocol


def read_court_submission(snapshot, registry, *, authentication_context, agent_session_root,
                          work_root, claim_binding):
    """The exact submission a court request now would judge: this claim's latest event, a submit.

    The Work tool pins it in its latch before the court runs, so a lost court
    reply is later correlated with this submission and no other.
    """
    held, name, last, _protocol = _claim_history(
        snapshot, registry, authentication_context=authentication_context,
        agent_session_root=agent_session_root, work_root=work_root, claim_binding=claim_binding)
    if not held or held[-1] is not last or name(last) != 'submit' or last.actor_root != agent_session_root:
        raise InvalidCell('The Work has no submission of this claim awaiting its court')
    return {'projection': 'court-submission', 'work_root': work_root, 'agent_session': agent_session_root,
            'claim_binding': claim_binding, 'revision': snapshot.revision, 'submit_event': last.root_id}


def read_court_recovery(snapshot, registry, *, authentication_context, agent_session_root,
                        work_root, claim_binding, submit_event, after_revision):
    """The exact verdict the court committed on one pinned submission, or none yet.

    The pinned submission must be this claim's claimant's submit; the event
    right after it, by the court, is its verdict, and the verdict's attestation
    must name that same submission. Anything else after it is refused. With no
    event after it, no verdict is committed yet: that is not proof that none
    will be, and nothing here is replayed or reconstructed.
    """
    if type(after_revision) is not int or not 0 <= after_revision <= snapshot.revision:
        raise InvalidCell('Court recovery revision is invalid')
    if type(submit_event) is not str or not submit_event or len(submit_event.encode('utf-8')) > 512:
        raise InvalidCell('Court recovery submission is invalid')
    held, name, _last, protocol = _claim_history(
        snapshot, registry, authentication_context=authentication_context,
        agent_session_root=agent_session_root, work_root=work_root, claim_binding=claim_binding)
    at = [index for index, event in enumerate(held) if event.root_id == submit_event]
    if (len(at) != 1 or name(held[at[0]]) != 'submit' or held[at[0]].actor_root != agent_session_root):
        raise InvalidCell('Court recovery cannot find the pinned submission under the exact claim')
    result = {'projection': 'court-recovery', 'work_root': work_root,
              'agent_session': agent_session_root, 'claim_binding': claim_binding,
              'submit_event': submit_event, 'revision': snapshot.revision, 'after_revision': after_revision,
              'decided': False, 'event': None, 'passed': None, 'history_root': None,
              'decision_evidence_root': None, 'verdict': None, 'receipt_reconstructed': False}
    following = held[at[0]+1:at[0]+2]
    if not following:
        return result
    event = following[0]
    if (name(event) not in ('accept', 'return') or event.actor_root != registry.work_completion_court_root
            or agent_session_root not in event.context_roots or len(event.evidence_roots) != 1):
        raise InvalidCell('The pinned submission was followed by something other than its court')
    evidence = read_evidence(snapshot, protocol, event.evidence_roots[0])
    try:
        decision = json.loads(evidence.payload)
    except (TypeError, ValueError, UnicodeError) as error:
        raise InvalidCell('Court recovery decision evidence is malformed') from error
    if (evidence.issuer_root != registry.work_completion_court_root or type(decision) is not dict
            or decision.get('result') != ('pass' if name(event) == 'accept' else 'fail')
            or decision.get('attestation_root') not in event.context_roots):
        raise InvalidCell('Court recovery decision evidence does not match the court')
    verdict = court_verdict(snapshot, registry, decision['attestation_root'])
    if verdict['result'] != decision['result'] or verdict['submit_event'] != submit_event:
        raise InvalidCell('Court recovery verdict judged another submission')
    return dict(result, decided=True, event=name(event), passed=name(event) == 'accept',
                history_root=event.root_id, decision_evidence_root=event.evidence_roots[0],
                verdict=verdict)
