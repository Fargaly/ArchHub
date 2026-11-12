"""Previews court: Home step cards, Canvas nodes and the Inspector show what each step made. Synthetic T0 fixture, disposable profile."""
import os, sys, json, subprocess, tempfile, shutil, base64, io
from pathlib import Path

root = Path(__file__).resolve().parents[3]
profile = Path(tempfile.mkdtemp(prefix='previews-', dir=root / '.cache'))
for name in ('USERPROFILE', 'HOME', 'LOCALAPPDATA', 'APPDATA', 'TEMP', 'TMP'):
    path = profile / name
    path.mkdir()
    os.environ[name] = str(path)
os.environ.update(ARCHHUB_TEST_STATE_DIR=str(profile / 'state'), ARCHHUB_TEST_NO_OPEN='1', ARCHHUB_TEST_SECRET_STORE='memory')
sys.path[:0] = [str(root / '01.APP'), str(root / '02.TESTS/tests')]
from PIL import Image, ImageDraw
from nodelang.nograph_server import NoGraphServer
from test_task_session_roundtrip import _Studio
NoGraphServer._probe_hosts = staticmethod(lambda: [])
sheet = Image.new('RGB', (240, 150), 'white')
pen = ImageDraw.Draw(sheet)
pen.rectangle((6, 6, 233, 143), outline='black')
pen.rectangle((170, 110, 233, 143), outline='black')
pen.line((30, 110, 150, 110), fill='black', width=3)
pen.line((60, 110, 60, 40), fill='black', width=2)
pen.line((60, 40, 140, 40), fill='black', width=2)
pen.text((176, 120), 'DET-07-014', fill='black')
held = io.BytesIO()
sheet.save(held, 'PNG')
server = NoGraphServer(profile / 'state').start()
client = _Studio(server)
try:
    planned = client.workshop('createTask', 'Check every detail against office rules')
    client.workshop('setTaskSession', planned['taskId'], {'agents': ['Sheet checker'], 'plan': ['Read details index', 'Check each detail']})
    assert [n['id'] for n in client.workshop('openTaskGraph', planned['taskId'])['workflow'] if n['id'].startswith('plan-')] == ['plan-1', 'plan-2']
    task = client.workshop('createTask', 'Details library')
    titles = ['Read details index', 'Convert DWG to data', 'Split one detail per file', 'Describe and review', 'Make native Revit details']
    client.workshop('setTaskSession', task['taskId'], {
        'scope': ', '.join(titles), 'agents': ['Details assistant', 'Sheet checker'], 'rules': ['Ask first'],
        'messages': [{'id': 'one', 'who': 'You', 'text': 'Make the details library.'}, {'id': 'two', 'who': 'Details assistant', 'text': 'INDEX.csv lists 624 details: 15 assigned, 609 to review. Pilot: 10 DWG converted and split into 10 details.'}]})
    opened = client.workshop('openTaskGraph', task['taskId'])
    doc = client.files('read', path=opened['path'])['document']
    outputs = [
        [{'detail': 'DET-03-001', 'title': 'Footing edge'}, {'detail': 'DET-07-014', 'title': 'Parapet'}, {'detail': 'DET-08-022', 'title': 'Window head'}, {'detail': 'DET-09-005', 'title': 'Skirting'}],
        {'name': 'Parapet, 1 of 10 DWG', 'thumbnail': 'data:image/png;base64,' + base64.b64encode(held.getvalue()).decode()},
        [{'file': 'DET-03-001.dwg', 'size': '84 KB'}, {'file': 'DET-07-014.dwg', 'size': '112 KB'}, {'file': 'DET-08-022.dwg', 'size': '96 KB'}],
        {'described': 7, 'to review': 3, 'last': 'DET-07-014 Parapet'}, None]
    for i, title in enumerate(titles):
        doc['nodes'].append({'id': 'demo-' + str(i), 'type': 'script.python', 'title': title, 'pure': i < 3,
            'params': {'code': 'result = data', 'kind': 'pure' if i < 3 else 'effect', 'timeout': 10},
            'ports': {'target': [{'id': 'data', 'type': 'text'}], 'source': [{'id': 'result', 'type': 'text'}]},
            'position': {'x': 396 * (i + 1), 'y': 0}, 'result': {'status': 'Done' if i < 4 else 'Idle', 'output': outputs[i]}})
        if i:
            doc['wires'].append({'id': 'demo-wire-' + str(i), 'from': {'node': 'demo-' + str(i - 1), 'socket': 'result'}, 'to': {'node': 'demo-' + str(i), 'socket': 'data'}})
    doc['wires'].append({'id': 'session-feed', 'from': {'node': 'start', 'socket': 'value'}, 'to': {'node': 'demo-0', 'socket': 'data'}})
    client.files('save', path=opened['path'], document=doc)
    from nodelang.agent_work import request_approval
    effect = next(node for node in doc['nodes'] if node['id'] == 'demo-4')
    effect.update(type='thing.file.write', params={'path': str(profile / 'reviewed-detail.txt'), 'text': 'Reviewed fixture detail'},
                  paramDefs=[{'id': 'path', 'name': 'File', 'type': 'file'}, {'id': 'text', 'name': 'Text', 'type': 'text'}])
    request_approval(effect, effect['params'], {}, continuation={'document': doc, 'source': doc, 'roots': ['demo-4'], 'completed': {}, 'path': opened['path'], 'depth': 0})
    effect['result'] = {'status': 'Waiting for approval', 'output': {}}
    client.files('save', path=opened['path'], document=doc)
    result = subprocess.run(['node', str(Path(__file__).with_suffix('.cjs'))], input=json.dumps({'url': server.public_url, 'cookie': server._cookie_token, 'task': task['taskId'], 'planned': planned['taskId']}), text=True, cwd=root)
    assert result.returncode == 0
finally:
    client.close()
    server.close()
    assert profile.parent == root / '.cache' and profile.name.startswith('previews-') and not profile.is_symlink()
    shutil.rmtree(profile, ignore_errors=True)
