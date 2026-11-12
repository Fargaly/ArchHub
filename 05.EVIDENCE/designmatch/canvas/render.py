import os, sys, json, subprocess, tempfile, shutil
from pathlib import Path

root = Path(__file__).resolve().parents[3]
profile = Path(tempfile.mkdtemp(prefix='designmatch-', dir=root / '.cache'))
for name in ('USERPROFILE', 'HOME', 'LOCALAPPDATA', 'APPDATA', 'TEMP', 'TMP'):
    path = profile / name
    path.mkdir()
    os.environ[name] = str(path)
os.environ['ARCHHUB_TEST_STATE_DIR'] = str(profile / 'state')
os.environ['ARCHHUB_TEST_NO_OPEN'] = '1'
os.environ['ARCHHUB_TEST_SECRET_STORE'] = 'memory'
sys.path[:0] = [str(root / '01.APP'), str(root / '02.TESTS/tests')]
from nodelang.nograph_server import NoGraphServer
from test_task_session_roundtrip import _Studio
NoGraphServer._probe_hosts = staticmethod(lambda: [])
server = NoGraphServer(profile / 'state').start()
client = _Studio(server)
try:
    task = client.workshop('createTask', 'Details library')
    titles = ['Read details index','Convert DWG to data','Split one detail per file','Describe and review','Make native Revit details','Sync CAD on Office Export','Publish to office share']
    client.workshop('setTaskSession', task['taskId'], {
        'scope': ', '.join(titles), 'agents':['Details assistant','Sheet checker','OpenCode'], 'rules':['Ask first'],
        'references':['Office standard, current'], 'plan':titles,
        'progress':{title:'done' for title in titles[:4]},
        'messages':[{'id':'fixture-one','who':'You','text':'Make the details library.'}, {'id':'fixture-two','who':'Details assistant','text':'INDEX.csv lists 624 details: 15 assigned, 609 to review. Pilot: 10 DWG converted with AutoCAD hidden and split into 10 details. Describing them now.'}]})
    opened = client.workshop('openTaskGraph', task['taskId'])
    doc = client.files('read', path=opened['path'])['document']
    for node in doc['nodes']:
        if node['type']=='thing.session': node['params']['model']='claude-sonnet'
    previews = ['DET-03-001    Footing edge\nDET-07-014    Parapet\nDET-08-022    Window head\nDET-09-005    Skirting\n624 details', 'Parapet, 1 of 10 DWG', '10 details, one per file', 'DET-07-014 Parapet\n100 mm rigid insulation; the membrane turns up 150 mm under the coping.\n7 of 10 described', 'Will create 10 drafting views', 'Will write 10 DWG next to them', 'INDEX.csv updated']
    for i, title in enumerate(titles):
        doc['nodes'].append({'id':'demo-'+str(i),'type':'script.python','title':title,
            'pure':i<3, 'params':{'code':'result = data', 'kind':'pure' if i<3 else 'effect', 'timeout':10, 'sections':['03 Concrete','07 Thermal','08 Openings','09 Finishes'], 'source': ['INDEX.csv','01-CAD','10','claude-sonnet','OFFICE-TEMPLATE-2024.rte','02-CAD-EXPORT','01-DETAILS-LIBRARY'][i]},
            'paramDefs':[{'id':'source','name':['Index file','Source folder','Min entities','Model','Template','Export folder','Share folder'][i],'type':'file' if i==0 else 'text'}, {'id':'sections','name':'Sections','type':'list'}],
            'ports':{'target':[{'id':'data','type':'text','label':['task','rows','json','details','described','views','dwg'][i]}], 'source':[{'id':'result','type':'text','label':['rows','json','details','described','views','dwg','receipt'][i]}]},
            'position':{'x':396*(i+1),'y':0},
            'result':{'status':'Done' if i<4 else 'Idle','output':previews[i]}})
        if i:
            doc['wires'].append({'id':'demo-wire-'+str(i),'from':{'node':'demo-'+str(i-1),'socket':'result'},'to':{'node':'demo-'+str(i),'socket':'data'}})
    doc['wires'].append({'id':'session-feed','from':{'node':'start','socket':'value'},'to':{'node':'demo-0','socket':'data'}})
    client.files('save', path=opened['path'], document=doc)
    from nodelang.agent_work import request_approval
    effect = next(node for node in doc['nodes'] if node['id']=='demo-4')
    effect.update(type='thing.file.write', params={'path':str(profile/'reviewed-detail.txt'),'text':'Reviewed fixture detail'},
                  paramDefs=[{'id':'path','name':'File','type':'file'},{'id':'text','name':'Text','type':'text'}])
    card = request_approval(effect, effect['params'], {}, continuation={
        'document':doc,'source':doc,'roots':['demo-4'],'completed':{},'path':opened['path'],'depth':0})
    effect['result'] = {'status':'Waiting for approval','output':{}}
    for node in doc['nodes']:
        if node['id'] in ('demo-5','demo-6'): node['result']={'status':'Idle','output':{}}
    client.files('save', path=opened['path'], document=doc)
    result = subprocess.run(['node',str(Path(__file__).with_suffix('.cjs'))],input=json.dumps({'url':server.public_url,'cookie':server._cookie_token,'path':opened['path'],'task':task['taskId']}),text=True,cwd=root)
    assert result.returncode == 0
finally:
    client.close()
    server.close()
    assert profile.parent == root / '.cache' and profile.name.startswith('designmatch-') and not profile.is_symlink()
    shutil.rmtree(profile)
