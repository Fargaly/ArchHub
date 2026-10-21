"""Exercise WIRE additions against the existing admitted graph, never founder data."""
import os
import secrets
from pathlib import Path
import pytest
from nodelang import commit_intent, universal_application as app
from nodelang.application_server import ApplicationServer
from nodelang.cell_secret_keys import MemorySigningKeyProvider
from nodelang.workshop_api import WorkshopAPI
from nodelang.universal_cell import InvalidCell

@pytest.fixture(scope='module')
def surface(tmp_path_factory):
    tmp=tmp_path_factory.mktemp('WIRE')
    os.environ['ARCHHUB_GRAND_MAP_PATH']=str(Path(app.__file__).parent/'data/public_runtime_map.json')
    keys=MemorySigningKeyProvider('archhub.local.relationship-authority',secrets.token_bytes(32))
    keys.add_key('archhub.local.court-attestation',secrets.token_bytes(32))
    server=ApplicationServer(universal_state_path=tmp/'PROFILE.sqlite3',universal_key_provider=keys,
        universal_workspace_root=tmp,enable_machine_transport=False,enable_universal_cloud_gateway=False,
        enable_machine_projection_prewarm=False,live_watch=False).start()
    binding=server._resolve_browser_session(server.browser_session_token)
    root=server.universal_registry.workshop_root
    api=WorkshopAPI(server,binding,root,server.universal_registry.canvas_root,guard=lambda:None,request_id='wire-test',route='/api/universal/workshop')
    with commit_intent.declare(commit_intent.USER_ACTION,actor=server.universal_registry.authorization.subject_root,reason='WIRE isolated check'):
        yield api
    server.close()

def test_profile_is_read_back_from_the_same_store(surface):
    revision=surface.owner.universal_store.revision
    assert surface.setAgentProfile('codex',{'purpose':'Review real outputs'})['purpose']=='Review real outputs'
    assert surface.owner.universal_store.revision>revision
    assert surface.getAgentSurface()['agentProfiles']['codex']['purpose']=='Review real outputs'
    assert surface._parameter('studio:agentProfiles')['codex']['purpose']=='Review real outputs'

def test_invalid_profile_never_mutates(surface):
    revision=surface.owner.universal_store.revision
    for args in [('unknown',{'purpose':'x'}),('codex',{'questionsPerDay':-1}),('codex',{'token':'secret'})]:
        with pytest.raises(InvalidCell):surface.setAgentProfile(*args)
    assert surface.owner.universal_store.revision==revision

def test_intake_creates_edits_and_rejects_unknown_rows(surface):
    row=surface.setIntakeRule(None,{'synonym':'mm','canonical':'millimetres'})
    assert surface.setIntakeRule(row['id'],{'unit':'mm'})['unit']=='mm'
    assert len(surface.getAgentSurface()['intakeRules'])==1
    with pytest.raises(InvalidCell):surface.setIntakeRule('missing',{'unit':'m'})

def test_metadata_cannot_fabricate_a_court_pass(surface):
    surface.setGraphMetadata(surface.scope,{'documentation':'Actual instructions'})
    assert surface.getGraphMetadata()['documentation']=='Actual instructions'
    revision=surface.owner.universal_store.revision
    with pytest.raises(InvalidCell):surface.setGraphMetadata(surface.scope,{'courtStatus':'Pass'})
    assert surface.owner.universal_store.revision==revision

def test_onboarding_and_learning_survive_readback(surface):
    assert surface.setOnboarding({'role':'Architect'})['role']=='Architect'
    surface.setLearningLayer('Agent',{'checkResults':True})
    assert surface.getAgentSurface()['learning']['layers']['Agent']['checkResults'] is True
