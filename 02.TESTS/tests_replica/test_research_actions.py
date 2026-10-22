"""Real isolated graph effects and save/reopen; never user profile/provider data."""
import os
from pathlib import Path
import json
import sys
import pytest

if 'ARCHHUB_RESEARCH_FIXTURE' not in os.environ:
    # This court asserts the whole process is redirected into its fixture (the SETTINGS lane read live
    # credentials without that); run it through PROOF/RESEARCHNODES/RUN.ps1-style isolation.
    pytest.skip('needs the isolated research fixture environment', allow_module_level=True)
FIXTURE = Path(os.environ['ARCHHUB_RESEARCH_FIXTURE']).resolve()
assert FIXTURE.name == 'FIXTURE' and FIXTURE.parent.name == 'PRODUCT'
for name in ('LOCALAPPDATA','APPDATA','USERPROFILE','HOME','TEMP','TMP','ARCHHUB_STATE_DIR','ARCHHUB_TEST_STATE_DIR'):
    assert Path(os.environ[name]).resolve().is_relative_to(FIXTURE), name
assert os.environ['OLLAMA_HOST'] == 'http://127.0.0.1:9'


@pytest.fixture(scope='session',autouse=True)
def isolated_session():
    for name,value in os.environ.items():
        if name.startswith('ARCHHUB_') and (':/' in value.replace('\\','/') or value.startswith('/')):
            assert Path(value).resolve().is_relative_to(FIXTURE.parent), name
    real_data = Path('C:/Users/fargaly/AppData').resolve()
    allowed = (FIXTURE.parent,Path(sys.base_prefix).resolve())
    def audit(event,args):
        if event == 'open' and isinstance(args[0],(str,bytes)):
            path = Path(os.fsdecode(args[0])).resolve()
            assert not path.is_relative_to(real_data) or any(path.is_relative_to(root) for root in allowed), str(path)
    sys.addaudithook(audit)
    return FIXTURE

from nodelang import commit_intent, universal_pipeline
from nodelang.canvas_graph_owner import CanvasOwner
from nodelang.universal_cell import InvalidCell
from nodelang.workshop_api import WorkshopAPI
from tests_replica import test_watcher_actions as support


@pytest.fixture(scope='module')
def graph(tmp_path_factory,isolated_session):
    assert tmp_path_factory.getbasetemp().resolve().is_relative_to(isolated_session)
    patch = pytest.MonkeyPatch()
    def forbidden(*args, **kwargs):
        raise AssertionError('Physical provider/credential access forbidden')
    patch.setattr('urllib.request.urlopen', forbidden)
    from nodelang import model_router
    patch.setattr(model_router, '_application_secrets_store', forbidden)
    patch.setattr(model_router, 'default_cloud_session', forbidden)
    patch.setattr(model_router, 'list_social_credentials', lambda: {'ok':True, 'items':[]})
    fixture = support.shared_app.__wrapped__(tmp_path_factory)
    try:
        yield next(fixture)
    finally:
        try:
            next(fixture)
        except StopIteration:
            pass
        patch.undo()


def create(graph, engine, **params):
    with commit_intent.declare(commit_intent.USER_ACTION, actor=graph.binding.subject_root, reason='isolated research inputs'):
        return universal_pipeline.create_engine_node(graph.store, graph.registry,
            title=engine, engine=engine, properties=params, authentication_context=graph.binding.context)['root']


def reopen(graph):
    graph.server.close()
    graph.start()
    return graph.call('readResearchState')


def test_runValuation_scores_real_wired_rows_and_reopens(graph):
    rows = [{'id':'first','cost':10,'quality':0.8},{'id':'second','cost':20,'quality':0.6}]
    source = create(graph,'data.constant',value=json.dumps(rows))
    criteria = [{'field':'cost','weight':0.4,'direction':'minimize'},{'field':'quality','weight':0.6,'direction':'maximize'}]
    target = create(graph,'research.weighted',criteria=json.dumps(criteria))
    with commit_intent.declare(commit_intent.USER_ACTION, actor=graph.binding.subject_root, reason='wire actual rows'):
        CanvasOwner(graph.store,graph.registry,graph.binding.context)._connect(source,target,names=('value','in'))
    result = graph.call('runValuation',target)
    assert result['output'][0]['id'] == 'first' and result['output'][0]['score'] == 1
    assert result['output'][1]['id'] == 'second' and result['output'][1]['score'] == 0
    assert reopen(graph)['nodes'][target]['output'] == result['output']


def test_setResearchReview_item_state_and_real_preset_reopen(graph):
    target = create(graph,'text.ops',text='red,blue',operation='split',separator=',')
    assert graph.call('runResearchNode',target)['output'] == ['red','blue']
    reviewed = graph.call('setResearchReview',target,{'item':'0','state':'excluded'})
    assert reviewed['review']['items']['0'] == 'excluded'
    with commit_intent.declare(commit_intent.USER_ACTION, actor=graph.binding.subject_root, reason='change real input'):
        CanvasOwner(graph.store,graph.registry,graph.binding.context).set_property(target,'text','changed')
    restored = graph.call('setResearchReview',target,{'usePreset':True})
    assert restored['preset']['text'] == 'red,blue'
    assert reopen(graph)['nodes'][target]['review']['items']['0'] == 'excluded'
    assert CanvasOwner(graph.store,graph.registry,graph.binding.context)._rows(None,target)['text']['value'] == 'red,blue'
    before = graph.store.revision
    with pytest.raises(InvalidCell): graph.call('setResearchReview',target,{'item':'99','state':'included'})
    with pytest.raises(InvalidCell): graph.call('setResearchReview',target,{'item':'0','state':'invented'})
    assert graph.store.revision == before


def test_runResearchNode_registered_executor_effect_reopens(graph):
    target = create(graph,'text.ops',text='old roof',pattern='old',replacement='new')
    assert graph.call('runResearchNode',target)['output'] == 'new roof'
    assert reopen(graph)['nodes'][target]['output'] == 'new roof'


def test_runSpecialNode_unknown_semantics_stays_refused(graph):
    target = create(graph,'note')
    before = graph.store.revision
    with pytest.raises(InvalidCell): graph.call('runSpecialNode',target)
    assert graph.store.revision == before
    assert 'runSpecialNode' not in graph.call('readResearchState')['actions']


def test_correctAnswerSource_new_message_revision_reopens(graph,monkeypatch):
    source = create(graph,'note')
    from tests_replica.test_approval_actions import _prepared
    work = _prepared('research-citation')['work']
    other_work = _prepared('research-shared-citation')['work']
    with commit_intent.declare(commit_intent.USER_ACTION, actor=graph.binding.subject_root, reason='actual cited message'):
        message = graph.server.conversation_content.append_authenticated(
            space_root=graph.registry.workshop_root,actor_root=graph.binding.subject_root,
            category_root=graph.registry.workshop_category_roots['note'],content='Evidence-backed answer',
            idempotency_key='research-answer',reference_roots=(work,other_work),evidence_roots=(source,),
            authentication_context=graph.binding.context,expected_revision=graph.store.revision)['message']
    corrected = graph.call('correctAnswerSource',message['id'],0,{'excerpt':'Actual corrected quote','status':'Corrected'})
    assert corrected['sources'][0]['sourceId'] == source
    assert corrected['sourceRevisions'][0]['sources'][0]['excerpt'] == ''
    assert corrected['sourceRevisions'][-1]['sources'][0]['excerpt'] == 'Actual corrected quote'
    reopen(graph)
    api = WorkshopAPI(graph.server,graph.binding,graph.registry.workshop_root,graph.registry.canvas_root,
        guard=lambda:None,request_id='read',route='/api/universal/workshop')
    messages = api._messages(work)[0]
    saved = next(row for row in messages if row['id'] == message['id'])
    assert saved['sources'] == corrected['sources'] and saved['sourceRevisions'] == corrected['sourceRevisions']
    shared = next(row for row in api._messages(other_work)[0] if row['id'] == message['id'])
    assert shared['sources'] == corrected['sources']
    with monkeypatch.context() as patch:
        def no_canvas(self):
            raise AssertionError('Message sources must not depend on the selected canvas')
        patch.setattr(CanvasOwner,'canvas',no_canvas)
        assert next(row for row in api._messages(work)[0] if row['id'] == message['id'])['sourceRevisions'] == corrected['sourceRevisions']
    before = graph.store.revision
    for index in (-1,99):
        with pytest.raises(InvalidCell): graph.call('correctAnswerSource',message['id'],index,{'status':'Excluded'})
    with pytest.raises(InvalidCell): graph.call('correctAnswerSource','unrelated',0,{'status':'Excluded'})
    assert graph.store.revision == before


def test_research_frozen_and_effectful_ancestors_refuse(graph):
    target = create(graph,'text.ops',text='locked')
    ops = CanvasOwner(graph.store,graph.registry,graph.binding.context)
    with commit_intent.declare(commit_intent.USER_ACTION,actor=graph.binding.subject_root,reason='freeze research node'):
        ops.set_property(target,'frozen','true')
    before = graph.store.revision
    with pytest.raises(InvalidCell,match='Unfreeze'): graph.call('runResearchNode',target)
    assert graph.store.revision == before
    terminal = create(graph,'library.terminal')
    downstream = create(graph,'text.ops')
    with commit_intent.declare(commit_intent.USER_ACTION,actor=graph.binding.subject_root,reason='effectful upstream fixture'):
        ops._connect(terminal,downstream,names=('out','text'))
    before = graph.store.revision
    with pytest.raises(InvalidCell,match='upstream'): graph.call('runResearchNode',downstream)
    assert graph.store.revision == before


def test_weighted_engine_rejects_invalid_typed_criteria():
    from nodelang.library_engines import weighted_valuation
    for weight in (-1,0,float('inf'),float('nan'),True):
        with pytest.raises(ValueError):
            weighted_valuation({'criteria':[{'field':'cost','weight':weight,'direction':'minimize'}]},{'in':[{'cost':1}]})
    criteria = [{'field':'cost','weight':1,'direction':'maximize'}]
    result = weighted_valuation({'criteria':'[]'},{'criteria':criteria,'in':[{'cost':1},{'cost':2}]})[0]
    assert result['out'][0]['cost'] == 2
