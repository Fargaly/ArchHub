"""Explicit selected-Work MCP inventory over existing admitted application APIs.

The configured root restricts this client; it grants no graph permission. Work
submission requests review, and only the application court can judge it. This
profile exposes no filesystem, execution, permit, administrator or registry tools.
"""
from __future__ import annotations

import json
import copy
import threading
from contextlib import contextmanager

from mcp.server.fastmcp import FastMCP
from .application_machine_transport import MachineTransportError, MachineResponseError
from .native_agent_hooks import user_prompt_submit_context, stop_context


WORKSHOP_TASK_TOOL_NAMES = (
    'native.work_current', 'native.work_assignment', 'native.work_claim', 'native.work_release', 'native.work_material',
    'native.work_plan_draft', 'native.work_plan_read', 'native.work_submit', 'native.work_configuration',
    'native.work_configure',
    'native.work_request_court', 'native.work_reconcile', 'native.hook_user_prompt_submit',
    'native.hook_stop',
    'coordination.read_messages', 'coordination.read_message',
    'coordination.send_message', 'coordination.acknowledge_message',
    'native.work_artifact_material', 'native.work_publish_artifact',
    'native.work_read_artifact', 'native.work_review_artifact',
)


def _text(value, maximum=512):
    return type(value) is str and bool(value.strip()) and '\0' not in value and len(value.encode('utf-8')) <= maximum


def _revision(value):
    return type(value) is int and 0 <= value < 2**53


def _refuse(message):
    raise MachineTransportError(message)


def validate_selected_work(root):
    if (not _text(root) or root.strip() != root or not root.startswith('assembly-instance:')
            or not root[len('assembly-instance:'):]):
        _refuse('workshop-task requires one exact configured Work root')
    return root


class _SelectedWork:
    def __init__(self, control, root):
        self.control, self.root = control, validate_selected_work(root)
        self.pending = None
        self.release_response_received = False
        # Serializes only this profile's local uncertain-response bookkeeping.
        # Graph admission remains with the existing owner and application.
        self._effect_lock = threading.RLock()

    def assignment(self, client, *, states=None, allow_none=True):
        result = client.current_work_assignment()
        if (type(result) is not dict or set(result) != {'agent_session','revision','projection','work'}
                or result['agent_session'] != client.agent_session_root
                or result['projection'] != 'assignment' or not _revision(result['revision'])):
            _refuse('Selected Work assignment identity is invalid')
        work = result['work']
        if work is None:
            if not allow_none:
                _refuse('The selected Work is not currently assigned; no completion is implied')
            return result
        if (type(work) is not dict or work.get('root') != self.root
                or work.get('claimant_session') != client.agent_session_root
                or not _text(work.get('claimant_agent_body')) or not _text(work.get('claim_binding'))
                or type(work.get('operational')) is not dict
                or type(work['operational'].get('current_state_label')) is not str):
            _refuse('The current claim does not match the configured Work and session')
        state = work['operational']['current_state_label'].casefold()
        if state not in (states or {'claimed','review','blocked'}):
            _refuse('The selected Work state does not admit this operation')
        return result

    @contextmanager
    def effect(self, operation, states):
        with self._effect_lock:
            with self.control.bound_client() as client:
                if self.pending is not None:
                    _refuse('A Work response is unresolved; use work_reconcile before another effect')
                before = self.assignment(client,states=states,allow_none=operation=='claim')
                if operation == 'claim' and before['work'] is not None:
                    _refuse('This session already has the selected assignment; read it instead of claiming again')
                # Keep the latch through the owner's post-return integrity check.
                self.pending = (operation, before['revision'],
                    before['work']['claim_binding'] if before['work'] else None)
                self.release_response_received = False
                yield client, before
            self.pending = None

    def receipt(self, result, client, event, before):
        if (type(result) is not dict or result.get('projection') != 'receipt-v1'
                or result.get('event') != event or result.get('work_root') != self.root
                or result.get('agent_session') != client.agent_session_root
                or not _revision(result.get('revision')) or result['revision'] < before
                or type(result.get('history_root')) is not str
                or event == 'submit' and (not _text(result['history_root'])
                    or not _revision(result.get('admission_revision'))
                    or result['admission_revision'] < result['revision'])):
            _refuse('Selected Work transition receipt could not be confirmed; do not replay')

    def plan(self, client, before):
        result = client.request('POST', '/api/universal/work-plan-read', {'root':self.root},
            response_timeout_seconds=10.0)
        if (type(result) is not dict or set(result) != {'work','plan','plan_root','revision'}
                or result['work'] != self.root or not _revision(result['revision']) or result['revision'] < before):
            _refuse('Selected Work plan identity is invalid')
        plan = result['plan']
        if plan is None and result['plan_root'] is None:
            return result
        if (not _text(result['plan_root']) or type(plan) is not dict or plan.get('state') != 'draft'
                or plan.get('execution') != 'none' or plan.get('model_output') != 'not-used'
                or not _text(plan.get('summary'), 512) or type(plan.get('priority_assessment')) is not dict
                or plan['priority_assessment'].get('model_authority') != 'none'
                or type(plan.get('steps')) not in (tuple,list) or not 1 <= len(plan['steps']) <= 16):
            _refuse('Selected Work plan is not a bounded unapproved draft')
        for order, step in enumerate(plan['steps'],1):
            if (type(step) is not dict or type(step.get('order')) is not int or step['order'] != order
                    or not _text(step.get('title')) or step.get('effect') not in ('none','approval-required')):
                _refuse('Selected Work plan steps are invalid')
        if len(json.dumps(result, allow_nan=False).encode('utf-8')) > 65536:
            _refuse('Selected Work plan response exceeds its bound')
        return result

    def court(self, result, client, before):
        if (type(result) is not dict or type(result.get('passed')) is not bool
                or result.get('projection') != 'status'
                or result.get('event') != ('accept' if result['passed'] else 'return')
                or not _revision(result.get('revision')) or result['revision'] <= before
                or any(not _text(result.get(key)) for key in ('attestation_root','decision_evidence_root','history_root'))):
            _refuse('Independent court receipt is unconfirmed; do not replay')
        status = result.get('status')
        if (type(status) is not dict or status.get('registry') != client._pinned_runtime_descriptor.work_registry_root
                or not _revision(status.get('revision')) or status['revision'] < result['revision']
                or type(status.get('items')) not in (tuple,list) or len(status['items']) > 4096):
            _refuse('Independent court status identity is invalid')
        rows = [row for row in status['items'] if type(row) is dict and row.get('root') == self.root]
        if (len(rows) != 1 or type(rows[0].get('operational')) is not dict
                or type(rows[0]['operational'].get('current_state_label')) is not str
                or rows[0]['operational']['current_state_label'].casefold() != ('complete' if result['passed'] else 'claimed')
                or not result['passed'] and rows[0].get('claimant_session') != client.agent_session_root):
            _refuse('The independent court did not confirm this selected Work outcome')
        # The existing court projects a registry internally. Do not expose any
        # other Work or use global counts as proof of this Work's completion.
        return {key:result[key] for key in ('passed','event','attestation_root','decision_evidence_root',
            'history_root','revision')} | {'work_root':self.root, 'agent_session':client.agent_session_root,
            'state':'complete' if result['passed'] else 'claimed', 'judged_by':'application-court'}


def register_artifact_tools(server, control, *, selected_work=None):
    """One tool adapter for general and selected-Work native sessions.

    The server derives actors and permissions. Selection only narrows roots;
    it never allows a reviewer to claim another agent's Work.
    """
    def call(work, phase, **values):
        validate_selected_work(work)
        if selected_work is not None and work != selected_work:
            _refuse('Artifact Work does not match the configured Work')
        with control.bound_client() as client:
            return client.request('POST', '/api/universal/work-artifact',
                                  {'phase': phase, 'work': work, **values})

    @server.tool(name='native.work_artifact_material')
    def artifact_material(work: str) -> dict[str, object]:
        """Read the current admitted publication material; not execution approval."""
        return call(work, 'material')

    @server.tool(name='native.work_publish_artifact')
    def publish_artifact(work: str, material_digest: str, idempotency_key: str,
                         patch: str, summary: str) -> dict[str, object]:
        """Publish a review patch for your admitted Work; never apply it to source.

        Keep the same idempotency key and exact content when reconciling a lost
        response. Publication is not successful execution or Work completion.
        """
        return call(work, 'publish', material_digest=material_digest,
                    idempotency_key=idempotency_key, patch=patch, summary=summary)

    @server.tool(name='native.work_read_artifact')
    def read_artifact(work: str, publication: str) -> dict[str, object]:
        """Read an admitted saved artifact with its physical digest rechecked."""
        return call(work, 'read', publication=publication)

    @server.tool(name='native.work_review_artifact')
    def review_artifact(work: str, publication: str, artifact_digest: str,
                        idempotency_key: str, verdict: str, notes: str) -> dict[str, object]:
        """Record your review of exact bytes; requires a distinct authorized reviewer.

        Review does not accept Work or approve applying the patch. The existing
        application court remains responsible for final adjudication.
        """
        return call(work, 'review', publication=publication,
                    artifact_digest=artifact_digest, idempotency_key=idempotency_key,
                    verdict=verdict, notes=notes)

    names = {'native.work_artifact_material', 'native.work_publish_artifact',
             'native.work_read_artifact', 'native.work_review_artifact'}
    for tool in server._tool_manager.list_tools():
        if tool.name in names:
            model = tool.fn_metadata.arg_model
            model.model_config.update(extra='forbid', strict=True)
            model.model_rebuild(force=True)
            tool.parameters = model.model_json_schema(by_alias=True)


def build_workshop_task_server(control, selected_work):
    held = _SelectedWork(control, selected_work)
    server = FastMCP('archhub-native-workshop-task')

    @server.tool(name='native.work_assignment')
    def work_assignment() -> dict[str, object]:
        """Read the selected pending claim, including review/blocked; null is not completion."""
        with control.bound_client() as client:
            return held.assignment(client)

    @server.tool(name='native.work_current')
    def work_current() -> dict[str, object]:
        """Read the selected assignment. This grants no execution or write permission."""
        return work_assignment()

    @server.tool(name='native.work_claim')
    def work_claim() -> dict[str, object]:
        """Explicitly claim only the launch-selected Work; no execution is started."""
        with held.effect('claim',None) as (client,before):
            result = control.call('claim_work', {'work_root':held.root})
            held.receipt(result,client,'claim',before['revision'])
        return result

    @server.tool(name='native.work_release')
    def work_release() -> dict[str, object]:
        """Release this session's selected claim for reconfiguration; never complete it.

        A lost response stays unresolved. A missing assignment is not proof of
        release, and this adapter never retries the transition automatically.
        """
        with held.effect('release', {'claimed'}) as (client, before):
            try:
                result = client.request('POST', '/api/universal/work-transition', {
                    'root': held.root, 'event': 'release', 'evidence': '',
                    'projection': 'receipt-v1'}, response_timeout_seconds=10.0)
            except MachineTransportError as error:
                # A completed response is not proof of non-execution. Reconcile
                # it against exact history and the original live claim first.
                held.release_response_received = getattr(error, 'response_received', False) is True
                raise
            held.receipt(result, client, 'release', before['revision'])
            if result['revision'] <= before['revision'] or not _text(result['history_root']):
                _refuse('Selected Work release receipt is unconfirmed; do not replay')
        return result

    @server.tool(name='native.work_material')
    def work_material() -> dict[str, object]:
        """Read only this claimed Work's inputs and requirements, at one observed revision.

        Existing active-canvas and resource audience permissions still apply.
        Refuses revision drift; never retries or exposes an arbitrary root reader.
        The returned serialized task material is bounded to 64 KiB.
        """
        with control.bound_client() as client:
            before = held.assignment(client,states={'claimed'},allow_none=False)
            interfaces = before['work'].get('interfaces')
            if type(interfaces) not in (list,tuple) or len(interfaces) > 256:
                _refuse('Selected Work material interfaces are invalid')
            values = {}
            for name in ('inputs','requirements'):
                selected = [row for row in interfaces if type(row) is dict and row.get('name') == name]
                if (len(selected) != 1 or selected[0].get('owner') != held.root
                        or not _text(selected[0].get('id')) or not _text(selected[0].get('target'))):
                    _refuse('Selected Work material interface is missing or ambiguous')
                target = selected[0]['target']
                response = client.request('POST','/api/universal/value',{'root':target},response_timeout_seconds=10.0)
                if (type(response) is not dict or set(response) != {'root','value','revision'}
                        or response['root'] != target or response['revision'] != before['revision']
                        or not _revision(response['revision'])):
                    _refuse('Selected Work material changed during the read')
                values[name] = {'interface':selected[0]['id'],'target':target,'value':response['value']}
                if len(json.dumps(values,allow_nan=False,ensure_ascii=False).encode('utf-8')) > 65536:
                    _refuse('Selected Work material exceeds 64 KiB')
            after = held.assignment(client,states={'claimed'},allow_none=False)
            if after['revision'] != before['revision'] or after['work']['claim_binding'] != before['work']['claim_binding']:
                _refuse('Selected Work claim changed during the material read')
            result = {'work_root':held.root,'agent_session':client.agent_session_root,'revision':before['revision'],**values}
            if len(json.dumps(result,allow_nan=False,ensure_ascii=False).encode('utf-8')) > 65536:
                _refuse('Selected Work material exceeds 64 KiB')
            return result

    @server.tool(name='native.work_configuration')
    def work_configuration(revision_id: str | None = None) -> dict[str, object]:
        """Read the configured Work, including released drafts; grant no execution."""
        with control.bound_client() as client:
            result = client.selected_work_configuration(held.root,
                **({'revision_id':revision_id} if revision_id is not None else {}))
            if (type(result) is not dict or result.get('agent_session') != client.agent_session_root
                    or type(result.get('work')) is not dict or result['work'].get('root') != held.root):
                _refuse('Selected Work configuration identity changed')
            return result

    @server.tool(name='native.work_configure')
    def work_configure(revision_id: str, expected_revision: int, purpose: str,
                       fields: dict[str, object]) -> dict[str, object]:
        """Stage this OPEN unclaimed draft for founder binding; preserve current inputs.

        On an uncertain response call work_reconcile; never resend the edit.
        """
        proposal = copy.deepcopy({'work_root':held.root, 'revision_id':revision_id,
            'expected_revision':expected_revision, 'purpose':purpose, 'fields':fields})
        if len(json.dumps(proposal, allow_nan=False).encode()) > 65536:
            _refuse('Selected Work configuration exceeds 64 KiB')
        with held._effect_lock:
            with control.bound_client() as client:
                if held.pending is not None:
                    _refuse('A Work response is unresolved; use work_reconcile before another effect')
                held.pending = ('configure', expected_revision, proposal)
                try:
                    result = client.configure_selected_work(proposal)
                except MachineResponseError:
                    held.pending = None
                    raise
            held.pending = None
            return result

    @server.tool(name='native.work_plan_read')
    def work_plan_read() -> dict[str, object]:
        """Read this claimed Work's current draft through the existing planning authority."""
        with control.bound_client() as client:
            before = held.assignment(client,states={'claimed'},allow_none=False)
            return held.plan(client,before['revision'])

    @server.tool(name='native.work_plan_draft')
    def work_plan_draft() -> dict[str, object]:
        """Request an unapproved deterministic draft, never a model call or execution."""
        with held.effect('plan',{'claimed'}) as (client,before):
            def validate(result):
                if (type(result) is not dict or set(result) != {'work','plan','state','reused','revision'}
                        or result['work'] != held.root or not _text(result['plan']) or result['state'] != 'draft'
                        or type(result['reused']) is not bool or not _revision(result['revision'])
                        or result['revision'] < before['revision']):
                    _refuse('Selected Work draft response is unconfirmed; do not replay')
            result = client.request('POST','/api/universal/work-plan',{'root':held.root},response_timeout_seconds=10.0)
            validate(result)
        return result

    @server.tool(name='native.work_submit')
    def work_submit(evidence: str) -> dict[str, object]:
        """Submit bounded evidence for review. This is not acceptance or completion."""
        if not _text(evidence,65536):
            _refuse('Submission evidence must be nonempty text of at most 65536 UTF-8 bytes')
        with held.effect('submit',{'claimed'}) as (client,before):
            result = client.request('POST','/api/universal/work-transition',{
                'root':held.root,'event':'submit','evidence':evidence,'projection':'receipt-v1',
                'expected_revision':before['revision']},response_timeout_seconds=10.0)
            held.receipt(result,client,'submit',before['revision'])
        return result

    @server.tool(name='native.work_request_court')
    def work_request_court() -> dict[str, object]:
        """Ask the independent application court to verify this submitted Work; never self-judge."""
        with held.effect('court',{'review'}) as (client,before):
            result = client.adjudicate_work(held.root,expected_revision=before['revision'])
            selected = held.court(result,client,before['revision'])
        return selected

    @server.tool(name='native.work_reconcile')
    def work_reconcile() -> dict[str, object]:
        """Read after an uncertain response; never repeat the prior operation or invent a receipt.

        A missing pending assignment cannot prove an uncertain court succeeded.
        Such outcomes remain unresolved for exact application receipt review.
        """
        with held._effect_lock:
            if held.pending is not None and held.pending[0] == 'configure':
                with control.bound_client() as client:
                    recovery = client.configure_selected_work(held.pending[2], reconcile=True)
                resolved = recovery['staged'] or recovery['not_staged']
                if resolved:
                    held.pending = None
                return {'selected_work':held.root, 'reconciled':resolved,
                    'pending_operation':None if held.pending is None else 'configure',
                    'receipt_reconstructed':False, 'configuration_recovery':recovery}
            with control.bound_client() as client:
                current = held.assignment(client)
                pending = held.pending
                resolved = pending is None
                work = current['work']
                state = work['operational']['current_state_label'].casefold() if work else None
                recovery = None
                if pending and pending[0] == 'release':
                    recovery = client.work_release_recovery(held.root, pending[2], pending[1])
                    if (type(recovery) is not dict or recovery.get('projection') != 'release-recovery'
                            or recovery.get('work_root') != held.root
                            or recovery.get('agent_session') != client.agent_session_root
                            or recovery.get('claim_binding') != pending[2]
                            or recovery.get('after_revision') != pending[1]
                            or not _revision(recovery.get('revision')) or recovery['revision'] < pending[1]
                            or type(recovery.get('released')) is not bool
                            or recovery.get('receipt_reconstructed') is not False
                            or recovery['released'] and not _text(recovery.get('history_root'))):
                        _refuse('Selected Work release recovery identity is invalid')
                    resolved = recovery['released']
                    if (not resolved and held.release_response_received and state == 'claimed'
                            and work['claim_binding'] == pending[2]
                            and current['revision'] == recovery['revision']):
                        resolved = True
                if (pending and pending[0] != 'release' and current['revision'] >= pending[1]
                        and (pending[2] is None or work and work['claim_binding'] == pending[2])):
                    operation = pending[0]
                    resolved = ((operation == 'claim' and state == 'claimed')
                        or (operation == 'submit' and state == 'review')
                        or (operation == 'court' and state == 'claimed'))
                    if operation == 'plan' and state == 'claimed':
                        resolved = held.plan(client,current['revision'])['plan_root'] is not None
            if resolved:
                held.pending = None
            return {'selected_work':held.root,'assignment':current,'reconciled':resolved,
                'pending_operation':None if held.pending is None else held.pending[0], 'receipt_reconstructed':False,
                **({'release_recovery':recovery} if recovery is not None else {})}

    @server.tool(name='native.hook_stop')
    def hook_stop() -> dict[str, object]:
        """Read the retained actor's completion gate; no submission or enrollment."""
        return stop_context(control)

    @server.tool(name='native.hook_user_prompt_submit')
    def hook_user_prompt_submit() -> dict[str, object]:
        """Read selected Work and ordinary peer context; no acknowledgement or execution."""
        with control.bound_client() as client:
            held.assignment(client)
            result = user_prompt_submit_context(control)
            context = json.loads(result['hookSpecificOutput']['additionalContext'].split('\n',1)[1])
            current = context['current_work']
            if current is not None and current['root'] != held.root:
                _refuse('Prompt context changed to a different Work')
            return result

    @server.tool(name='coordination.read_messages')
    def read_messages(limit: int = 10, before: int | None = None) -> dict[str, object]:
        """Read one bounded ordinary Workshop page with its actual audience checks."""
        return control.call('read_messages',{'limit':limit,'before':before})

    @server.tool(name='coordination.read_message')
    def read_message(message_id: str, sequence: int) -> dict[str, object]:
        """Read one exact ordinary message; does not acknowledge it."""
        return control.call('read_message',{'message_id':message_id,'sequence':sequence})

    @server.tool(name='coordination.send_message')
    def send_message(target: str, message: str, idempotency_key: str, reply_to: str | None = None) -> dict[str, object]:
        """Send using a caller-held stable key; no generated key or automatic retry."""
        return control.call('send_message',{'target':target,'message':message,
            'idempotency_key':idempotency_key,'reply_to':reply_to})

    @server.tool(name='coordination.acknowledge_message')
    def acknowledge_message(message_id: str, sequence: int, idempotency_key: str) -> dict[str, object]:
        """Send an explicit acknowledgement reply for an actually addressed message."""
        return control.call('acknowledge_message',{'message_id':message_id,'sequence':sequence,'idempotency_key':idempotency_key})

    register_artifact_tools(server, control, selected_work=selected_work)

    # These models belong only to this new server. Reject undeclared tool fields
    # rather than silently discarding a caller-supplied alternate Work identity.
    tools = server._tool_manager.list_tools()
    if {tool.name for tool in tools} != set(WORKSHOP_TASK_TOOL_NAMES):
        _refuse('Selected Work MCP inventory changed')
    for tool in tools:
        model = tool.fn_metadata.arg_model
        model.model_config.update(extra='forbid',strict=True)
        model.model_rebuild(force=True)
        tool.parameters = model.model_json_schema(by_alias=True)
    return server
