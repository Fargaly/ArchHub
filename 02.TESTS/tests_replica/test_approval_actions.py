"""Six approval owners on a real isolated graph, including actual SQLite reopen."""
import hashlib
import secrets
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from nodelang import commit_intent, social_approval, universal_application as app
from nodelang import application_server as server_module
from nodelang.application_server import ApplicationServer
from nodelang.cell_adapters import read_permission
from nodelang.cell_authorization import AuthorizationDenied
from nodelang.cell_connector_execution import read_connector_delegation
from nodelang.cell_secret_keys import MemorySigningKeyProvider
from nodelang.cell_signing_authority import LocalEd25519KmsProvider
from nodelang.universal_cell import InvalidCell
from nodelang.workshop_api import dispatch
from tests_replica import test_social_approval_graph as support
from tests_replica.test_workshop_execution_gate import TARGET, _container, _founder_post

RUBRIC = 'Target and revision match'

def _prepared(name):
    w = support.world()
    inputs = {'operation':'linkedin.post', 'account_id':'urn:li:person:782bbtaQ',
        'vault_entry':'social-linkedin-founder', 'arguments':{'text':'Approval court post'}}
    with commit_intent.declare(commit_intent.USER_ACTION, actor='court', reason='scoped social Work'):
        session, _ = app.begin_universal_runtime_agent_session(w.store, w.registry,
            session_root='app:agent-session:runtime:approval-'+name, runtime='baboom-execution',
            external_session_fingerprint=hashlib.sha256(name.encode()).hexdigest(),
            catalog_entry_root='app:agent-body-catalog:entry:baboom-execution', authentication_context=w.context)
        work, _, _ = app.create_universal_governed_work(w.store, w.registry,
            title='Approval '+name, description='One scoped approval court effect', x=400.0, y=400.0,
            external_key='court:approval:'+name, references={'scope':w.registry.workshop_root},
            structured_references={'inputs':inputs, 'cde-container':_container('court:approval:'+name)},
            compact_references=True, select_created=False, authentication_context=w.context)
        app.claim_universal_governed_work(w.store, w.registry, agent_session_root=session.root_id,
            work_root=work, authentication_context=w.context)
    _founder_post(w.server,'plan',[work],[],'approval-plan-'+name)
    _founder_post(w.server,'research',[work],[],'approval-research-'+name,capture=TARGET)
    with commit_intent.declare(commit_intent.USER_ACTION,actor='court',reason='prepare scoped approval'):
        return support.social.prepare_social_work(w.server,work_root=work,session_root=session.root_id,
            context=w.context,note='')



@pytest.fixture
def approvals(tmp_path, monkeypatch, request):
    durable = not request.node.name.endswith('_in_memory')
    monkeypatch.setenv('ARCHHUB_STATE_DIR', str(tmp_path))
    monkeypatch.setenv('ARCHHUB_GRAND_MAP_PATH', str(Path(app.__file__).parent/'data/public_runtime_map.json'))
    source = tmp_path/TARGET
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text('# isolated approval research source\n', encoding='utf-8')
    keys = MemorySigningKeyProvider('archhub.local.relationship-authority', secrets.token_bytes(32))
    keys.add_key('archhub.local.court-attestation', secrets.token_bytes(32))
    from tests_replica.test_application_machine_transport import _green_runtime_compliance
    machine_keys = MemorySigningKeyProvider('archhub.local.universal-runtime-pipe', b'g'*32)
    cde = LocalEd25519KmsProvider(provider_id='court.execution-gate', authority_id='court-execution-gate')

    class Surface:
        server = None
        sequence = 0

        def start(self):
            storage = {'universal_state_path':tmp_path/'APPROVALS.sqlite3',
                'universal_key_provider':keys} if durable else {}
            self.server = ApplicationServer(**storage, universal_workspace_root=tmp_path,
                enable_machine_transport=True, machine_descriptor_path=tmp_path/'RUNTIME.json',
                machine_key_provider=machine_keys, runtime_compliance_runner=_green_runtime_compliance,
                enable_universal_cloud_gateway=False, enable_machine_projection_prewarm=False,
                live_watch=False).start()
            with commit_intent.declare(commit_intent.USER_ACTION, actor='court', reason='approval fixture signing'):
                root = server_module._ensure_cde_write_signing_authority(
                    self.server.universal_store, self.server.universal_registry, cde,
                    descriptor_root='court:execution-gate-signing:v1')
            self.server.cde_write_signing_provider = cde
            self.server.cde_write_signing_descriptor_root = root
            self.binding = self.server._resolve_browser_session(self.server.browser_session_token)
            self.registry = self.server.universal_registry
            self.store = self.server.universal_store
            support._CURRENT['world'] = SimpleNamespace(server=self.server, store=self.store,
                registry=self.registry, binding=self.binding, context=self.binding.context)
            social_approval._PENDING_CACHE.update(key=None, items=())

        def call(self, method, *args):
            self.sequence += 1
            body = {'action':'data-api', 'function':method, 'args':list(args),
                'root':self.registry.workshop_root, 'scope':self.registry.canvas_root,
                'request_id':'approval-court-'+str(self.sequence)}
            with commit_intent.declare(commit_intent.USER_ACTION,
                    actor=self.binding.subject_root, reason='approval action court'):
                return dispatch(self.server, self.binding, body, guard=lambda:None,
                    route='/api/universal/workshop')['result']

        def card(self, root):
            return next(row for row in self.call('listApprovals') if row['id'] == root)

        def lifecycle(self, root):
            delegation = read_connector_delegation(self.store.snapshot(),
                self.registry.baboom_connector_execution_protocol, self.registry.adapter_protocol, root)
            permission = read_permission(self.store.snapshot(), self.registry.adapter_protocol, delegation.permission_root)
            return {value:key for key,value in self.registry.adapter_protocol.states.items()}[permission.lifecycle_root]

        def decide(self, request, decision='approve'):
            with commit_intent.declare(commit_intent.USER_ACTION, actor=self.binding.subject_root,
                    reason='explicit founder approval court'):
                return social_approval.decide(self.server, self.binding, {
                    'delegation':request['delegation'], 'input_digest':request['input_digest'], 'decision':decision})

        def reopen(self, expected):
            events = {root:self.store.snapshot().cells[root] for root in expected['events']}
            self.server.close()
            self.start()
            actual = self.card(expected['id'])
            for field in ('id','delegation','work','input_digest','status','rows','rubric','events'):
                assert actual[field] == expected[field], field
            # A fresh successor has no decision; its predecessor holds refresh history.
            for root, cell in events.items():
                assert self.store.snapshot().cells[root] == cell
            return actual

    surface = Surface()
    surface.start()
    try:
        yield surface
    finally:
        support._CURRENT.pop('world', None)
        surface.server.close()


def test_postpone_approval_persists_and_keeps_requested_permission(approvals):
    request = _prepared('postpone-'+uuid4().hex)
    card = approvals.call('postponeApproval', request['delegation'])
    assert card['status'] == 'postponed'
    assert approvals.lifecycle(card['id']) == 'requested'
    with pytest.raises((AuthorizationDenied, InvalidCell)):
        approvals.decide(request)
    approvals.reopen(card)
    assert approvals.lifecycle(card['id']) == 'requested'


def test_resume_approval_persists_without_granting(approvals):
    request = _prepared('resume-'+uuid4().hex)
    approvals.call('postponeApproval', request['delegation'])
    card = approvals.call('resumeApproval', request['delegation'])
    assert card['status'] == 'pending'
    assert approvals.lifecycle(card['id']) == 'requested'
    approvals.reopen(card)
    assert approvals.lifecycle(card['id']) == 'requested'
    assert approvals.decide(request)['decision'] == 'approved'


def test_contest_decision_persists_reason_and_blocks_grant(approvals):
    request = _prepared('contest-'+uuid4().hex)
    approvals.decide(request, 'deny')
    card = approvals.call('contestDecision', request['delegation'], 'Evidence does not support the decision')
    assert card['status'] == 'contested'
    assert approvals.lifecycle(card['id']) == 'revoked'
    approvals.reopen(card)
    with pytest.raises((AuthorizationDenied, InvalidCell)):
        approvals.decide(request)
    event_text = b' '.join(approvals.store.snapshot().cells[root].atom for root in card['events'])
    assert b'Evidence does not support the decision' in event_text


def test_refresh_approval_persists_new_request_and_old_history(approvals):
    request = _prepared('refresh-'+uuid4().hex)
    approvals.call('postponeApproval', request['delegation'])
    old = approvals.card(request['delegation'])
    card = approvals.call('refreshApproval', request['delegation'])
    assert card['id'] != old['id'] and card['work'] == old['work']
    assert card['status'] == 'pending'
    assert approvals.lifecycle(old['id']) == 'requested'
    with pytest.raises((AuthorizationDenied, InvalidCell)):
        approvals.decide(request)
    assert approvals.lifecycle(card['id']) == 'requested'
    superseded = approvals.card(old['id'])
    assert superseded['status'] == 'superseded'
    assert set(old['events']).issubset(superseded['events'])
    approvals.reopen(superseded)
    assert approvals.card(card['id'])['status'] == 'pending'
    assert approvals.card(old['id'])['status'] == 'superseded'
    assert approvals.lifecycle(card['id']) == 'requested'


def test_review_proof_row_persists_and_reject_blocks_approve(approvals):
    request = _prepared('proof-'+uuid4().hex)
    assert approvals.card(request['delegation'])['rows']
    card = approvals.call('reviewProofRow', request['delegation'], 0, 'Reject')
    assert card['rows'][0]['decision'] == 'Reject'
    approvals.reopen(card)
    with pytest.raises((AuthorizationDenied, InvalidCell)):
        approvals.decide(request)
    card = approvals.call('reviewProofRow', request['delegation'], 0, 'Accept')
    assert card['rows'][0]['decision'] == 'Accept'
    assert approvals.decide(request)['decision'] == 'approved'


def test_set_approval_rubric_persists_and_false_blocks_approve(approvals):
    request = _prepared('rubric-'+uuid4().hex)
    card = approvals.call('setApprovalRubric', request['delegation'], RUBRIC, False)
    assert card['rubric'][RUBRIC] is False
    approvals.reopen(card)
    with pytest.raises((AuthorizationDenied, InvalidCell)):
        approvals.decide(request)
    card = approvals.call('setApprovalRubric', request['delegation'], RUBRIC, True)
    assert card['rubric'][RUBRIC] is True
    assert approvals.decide(request)['decision'] == 'approved'


def test_invalid_review_arguments_never_change_graph(approvals):
    request = _prepared('invalid-'+uuid4().hex)
    root = request['delegation']
    for method,args in [('reviewProofRow',(root,-1,'Accept')),
                        ('reviewProofRow',(root,0,'Maybe')),
                        ('setApprovalRubric',(root,'Unknown criterion',True)),
                        ('setApprovalRubric',(root,RUBRIC,'yes')),
                        ('contestDecision',(root,''))]:
        revision = approvals.store.revision
        with pytest.raises(InvalidCell):
            approvals.call(method,*args)
        assert approvals.store.revision == revision


def test_contest_of_approved_request_blocks_existing_native_permission_in_memory(approvals):
    request = _prepared('held-native-'+uuid4().hex)
    approvals.decide(request)
    assert approvals.lifecycle(request['delegation']) == 'granted'
    delegation = read_connector_delegation(approvals.store.snapshot(),
        approvals.registry.baboom_connector_execution_protocol, approvals.registry.adapter_protocol,
        request['delegation'])
    card = approvals.call('contestDecision',request['delegation'],'Recheck this granted decision')
    assert card['status'] == 'contested'
    assert approvals.lifecycle(card['id']) == 'granted'
    assert approvals.card(card['id'])['status'] == 'contested'
    with pytest.raises((AuthorizationDenied, InvalidCell)):
        app.authorize_universal_baboom_connector_execution(approvals.store,approvals.registry,
            agent_session_root=delegation.session_root,delegation_root=delegation.root_id,
            authentication_context=approvals.binding.context)


def test_model_refresh_reseals_cognition_and_creates_new_delegation_in_memory(approvals):
    social = _prepared('model-refresh-'+uuid4().hex)
    old_social = read_connector_delegation(approvals.store.snapshot(),
        approvals.registry.baboom_connector_execution_protocol, approvals.registry.adapter_protocol,
        social['delegation'])
    options = dict(agent_session_root=old_social.session_root,work_root=old_social.work_root,
        authentication_context=approvals.binding.context)
    with commit_intent.declare(commit_intent.USER_ACTION,actor=approvals.binding.subject_root,
            reason='prepare isolated model review'):
        app.draft_universal_baboom_work_plan(approvals.store,approvals.registry,**options)
        request,_ = app.prepare_universal_baboom_model_cognition_request(approvals.store,
            approvals.registry,**options,provider='local',model='qwen3:8b',
            content_service=approvals.server.conversation_content)
        delegation,_,_ = app.request_universal_baboom_model_execution(approvals.store,
            approvals.registry,**options,provider='local',model='qwen3:8b',data_class='internal-text',
            cognition_request_root=request.root_id,content_service=approvals.server.conversation_content)
    approvals.call('postponeApproval',delegation.root_id)
    fresh = approvals.call('refreshApproval',delegation.root_id)
    assert fresh['id'] != delegation.root_id
    assert fresh['status'] == 'pending' and fresh['input_digest']
    old = approvals.card(delegation.root_id)
    assert old['status'] == 'superseded'
    assert approvals.card(old['id'])['status'] == 'superseded'
    assert approvals.card(fresh['id'])['status'] == 'pending'
