"""Daily-work pack (S8): six canvas nodes under contract C2, exercised on generated public samples."""
import hashlib
import zipfile
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def profile(tmp_path, monkeypatch):
    for name in ('LOCALAPPDATA', 'APPDATA', 'USERPROFILE', 'HOME'):
        monkeypatch.setenv(name, str(tmp_path / name))
        (tmp_path / name).mkdir()
    monkeypatch.setenv('ARCHHUB_TEST_STATE_DIR', str(tmp_path / 'state'))
    monkeypatch.setenv('WORKSHOP_STATE_DIR', str(tmp_path / 'transport'))
    yield tmp_path


def make_pdf(path, pages):
    """A real PDF: each page a list of ('text', x, y, words) and ('box', x, y, w, h) marks, 595 x 842 pt."""
    objects = ['<< /Type /Catalog /Pages 2 0 R >>', None, '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>']
    kids = []
    for marks in pages:
        ops = []
        for mark in marks:
            if mark[0] == 'text':
                words = mark[3].replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')
                ops.append('BT /F1 10 Tf %d %d Td (%s) Tj ET' % (mark[1], mark[2], words))
            else:
                ops.append('0 0 0 rg %d %d %d %d re f' % mark[1:])
        stream = '\n'.join(ops)
        objects.append('<< /Length %d >>\nstream\n%s\nendstream' % (len(stream), stream))
        objects.append('<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 3 0 R >> >> '
                       '/Contents %d 0 R >>' % (len(objects)))
        kids.append(len(objects))
    objects[1] = '<< /Type /Pages /Kids [%s] /Count %d >>' % (' '.join('%d 0 R' % k for k in kids), len(kids))
    body, offsets = b'%PDF-1.4\n', []
    for number, text in enumerate(objects, 1):
        offsets.append(len(body))
        body += ('%d 0 obj\n%s\nendobj\n' % (number, text)).encode('latin-1')
    xref = len(body)
    body += ('xref\n0 %d\n0000000000 65535 f \n' % (len(objects) + 1)).encode()
    body += b''.join(b'%010d 00000 n \n' % o for o in offsets)
    body += ('trailer << /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n' % (len(objects) + 1, xref)).encode()
    Path(path).write_bytes(body)
    return str(path)


def title_block(project, number, revision=None):
    rows = [('text', 470, 200, 'Project: ' + project), ('text', 470, 180, 'Drawing No: ' + number),
            ('text', 470, 140, 'Scale: 1:100'), ('text', 470, 120, 'Date: 2026-10-29'), ('text', 470, 100, 'Drawn: AF')]
    if revision:
        rows.append(('text', 470, 160, 'Revision: ' + revision))
    return rows


def test_every_daily_node_carries_the_node_contract():
    from nodelang.canvas_documents import THING_ENGINES, is_pure
    from nodelang.daily_work_nodes import DAILY_ENGINES
    from nodelang.session_files import catalogue
    cards = {row['engine']: row for row in catalogue() if row['id'].startswith('daily:')}
    assert set(cards) == set(DAILY_ENGINES) and len(cards) == 6
    for engine, spec in DAILY_ENGINES.items():
        assert THING_ENGINES[engine] is spec and is_pure(engine) is spec['pure']
        assert spec['budget']['seconds'] > 0 and all(p['type'] != 'any' for p in spec['in'] + spec['out'])
        assert cards[engine]['ports']['source'] == spec['out']
        assert {row['id'] for row in cards[engine]['ports']['target']} == {row['id'] for row in spec['in']} | set(spec['params'])
        assert all(port in cards[engine]['ports']['target'] for port in spec['in'])
    assert {e for e, s in DAILY_ENGINES.items() if s['pure']} == {'daily.titleblock_qa', 'daily.revision_compare'}


def test_title_block_qa_reads_fields_and_flags_missing_duplicate_and_mismatch(tmp_path):
    from nodelang.daily_work_nodes import titleblock_qa
    sheets = make_pdf(tmp_path / 'set.pdf', [
        title_block('Tower A', 'A-101', 'P02') + [('text', 40, 700, 'Revision: X99 general note')],
        title_block('Tower A', 'A-102'),
        title_block('Tower B', 'A-101', 'P01'),
    ])
    out, shown = titleblock_qa({'fields': 'Project, Drawing No, Revision, Scale, Date, Drawn', 'region': 'right'},
                               {'pdf': sheets})
    first, second, third = out['sheets']
    assert first['fields']['Revision'] == 'P02' and first['sheet_number'] == 'A-101'  # the note outside the block is ignored
    assert second['missing'] == ['Revision'] and second['fields']['Project'] == 'Tower A'
    assert third['fields']['Project'] == 'Tower B' and third['fields']['Revision'] == 'P01'
    issues = {(i['page'], i['issue']) for i in out['issues']}
    assert (2, 'missing Revision') in issues
    assert (1, 'duplicate sheet number A-101') in issues and (3, 'duplicate sheet number A-101') in issues
    assert (0, 'Project differs across sheets: Tower A | Tower B') in issues
    assert not any(s['ok'] for s in out['sheets']) and shown.startswith('3 sheet(s), 4 issue(s)')


def test_revision_compare_finds_where_a_drawing_changed(tmp_path):
    from nodelang.daily_work_nodes import revision_compare
    common = [('text', 60, 780, 'Ground floor plan')]
    old = make_pdf(tmp_path / 'old.pdf', [common + [('box', 100, 100, 50, 50), ('text', 60, 60, 'Door D1')], common])
    new = make_pdf(tmp_path / 'new.pdf', [common + [('box', 300, 400, 50, 50), ('text', 60, 60, 'Door D2')], common,
                                          common])
    out, shown = revision_compare({'dpi': 72}, {'old': old, 'new': new})
    first, second, third = out['pages']
    assert second == {'page': 2, 'status': 'same', 'changed_ratio': 0.0, 'regions': [], 'text_added': [], 'text_removed': []}
    assert third['status'] == 'added' and first['status'] == 'changed'
    assert first['text_added'] == ['Door D2'] and first['text_removed'] == ['Door D1']

    def covers(box, x, y):
        return box[0] - 6 <= x <= box[2] + 6 and box[1] - 6 <= y <= box[3] + 6
    for x, y in ((125, 125), (325, 425)):  # the box that left and the box that arrived
        assert any(covers(box, x, y) for box in first['regions']), first['regions']
    assert not any(covers(box, 500, 700) for box in first['regions'])
    assert len(out['overlays']) == 1 and Path(out['overlays'][0]).is_file()
    assert shown == '3 page(s) compared, 2 changed: 1, 3'


def test_area_schedule_totals_wired_room_rows_by_level():
    from nodelang.daily_work_nodes import area_schedule
    rows = [{'number': '101', 'name': 'Office', 'level': 'L1', 'area': '20.5'},
            {'number': '102', 'name': 'Meeting', 'level': 'L1', 'area': 14.25},
            {'number': '201', 'name': 'Office', 'level': 'L2', 'area': '1,020.0'}]
    out, shown = area_schedule({'group_by': 'level'}, {'rows': rows})
    assert out['totals'] == {'L1': 34.75, 'L2': 1020.0} and out['total'] == 1054.75
    assert out['csv'].splitlines()[0] == 'number,name,level,area' and len(out['csv'].splitlines()) == 4
    assert shown == '3 space(s), 1054.75 m2 total over 2 level group(s)'
    with pytest.raises(ValueError, match='area is not a number on Office'):
        area_schedule({}, {'rows': [{'name': 'Office', 'area': 'big'}]})


def test_editing_solves_pdf_nodes_at_once_and_heavy_nodes_wait_for_run(tmp_path):
    from nodelang.canvas_documents import solve
    from nodelang.daily_work_nodes import runtimes_root
    from nodelang.session_files import catalogue, new_document
    cards = {row['id']: row for row in catalogue()}
    sheets = make_pdf(tmp_path / 'one.pdf', [title_block('Tower A', 'A-101', 'P01')])
    doc = new_document('Daily')
    for key, item in (('qa', 'daily:titleblock_qa'), ('ocr', 'daily:arabic_ocr')):
        doc['nodes'].append({'id': key, 'item': item, 'type': cards[item]['engine'], 'title': cards[item]['title'],
                             'params': dict(cards[item]['params']), 'position': {'x': 0, 'y': 0}})
    doc['nodes'][0]['params']['pdf'] = sheets
    doc['nodes'][1]['params']['image'] = sheets
    result = solve(doc, ['qa', 'ocr'])
    assert result['solved'] == ['qa'] and result['stale'] == ['ocr']
    assert doc['nodes'][0]['result']['status'] == 'Done' and doc['nodes'][0]['result']['output']['issues'] == []
    assert doc['nodes'][1]['result']['status'] == 'Out of date'
    assert not runtimes_root().exists()  # an edit never reaches the network


def test_a_runtime_file_with_the_wrong_checksum_is_refused_and_leaves_nothing(tmp_path, monkeypatch):
    from nodelang import daily_work_nodes as daily
    archive = tmp_path / 'tool.zip'
    with zipfile.ZipFile(archive, 'w') as bundle:
        bundle.writestr('tool/run.txt', 'ok')
    good = hashlib.sha256(archive.read_bytes()).hexdigest()
    url = archive.as_uri()
    monkeypatch.setitem(daily.RUNTIMES, 'probe', {'lock': '', 'files': [
        {'url': url, 'sha256': '0' * 64, 'bytes': archive.stat().st_size, 'unzip': 'bin'}]})
    with pytest.raises(ValueError, match='failed its checksum'):
        daily.ensure_runtime('probe')
    assert not list(daily.runtimes_root().glob('probe-*/ready.json'))
    assert not list((daily.runtimes_root() / 'downloads').glob('*'))
    with pytest.raises(ValueError, match='larger than its pin'):
        daily.fetch(url, good, 10, tmp_path / 'short' / 'tool.zip')
    daily.RUNTIMES['probe']['files'][0]['sha256'] = good
    home = daily.ensure_runtime('probe')
    assert (home / 'bin' / 'tool' / 'run.txt').read_text() == 'ok' and (home / 'ready.json').is_file()
    assert daily.ensure_runtime('probe') == home  # a second Run reuses it


def test_a_heavy_job_is_stopped_at_its_budget(tmp_path, monkeypatch):
    from nodelang import daily_work_nodes as daily
    slow = tmp_path / 'slow_worker.py'
    slow.write_text('import time\ntime.sleep(30)\n', encoding='utf-8')
    monkeypatch.setattr(daily, 'WORKER', slow)
    with pytest.raises(TimeoutError, match='budget of 1 s'):
        daily.run_worker('ocr', {}, site=None, budget_s=1)
    answer = tmp_path / 'answer_worker.py'
    answer.write_text('print("noise")\nprint("ARCHHUB-RESULT " + \'{"error": "bad image"}\')\n', encoding='utf-8')
    monkeypatch.setattr(daily, 'WORKER', answer)
    with pytest.raises(RuntimeError, match='bad image'):
        daily.run_worker('ocr', {}, site=None, budget_s=20)


def test_side_effect_nodes_pass_the_c3_decision_before_they_act(tmp_path, monkeypatch):
    from nodelang import daily_work_nodes as daily
    from nodelang.canvas_documents import run_thing
    asked = []
    monkeypatch.setattr(daily, 'DECIDE', lambda payload, vendor: asked.append((payload['tool_name'], vendor)) or
                        {'decision': 'ask', 'reason': 'Approve card shown'})
    with pytest.raises(PermissionError, match='daily.arabic_ocr is waiting for approval: Approve card shown'):
        run_thing('daily.arabic_ocr', {'image': str(tmp_path / 'scan.png')}, {})
    assert asked == [('daily.arabic_ocr', 'archhub-canvas')] and not daily.runtimes_root().exists()
    sheets = make_pdf(tmp_path / 'one.pdf', [title_block('Tower A', 'A-101', 'P01')])
    out, _shown = run_thing('daily.titleblock_qa', {'pdf': sheets, 'fields': 'Project'}, {})
    assert out['issues'] == [] and len(asked) == 1  # a pure read never asks


@pytest.fixture
def bcf_xml_site(monkeypatch):
    import os
    site = os.environ.get('ARCHHUB_BCF_TEST_SITE')
    if site:
        monkeypatch.syspath_prepend(site)
    pytest.importorskip('bcf.xml_parser', reason='real pinned BCF XML runtime is required')
    return site


def make_bcf_archive(path, version):
    import importlib
    from bcf.xml_parser import XmlParserSerializer
    from xsdata.models.datatype import XmlDateTime
    model = importlib.import_module('bcf.v%s.model' % version[0])
    serializer = XmlParserSerializer()
    guid = '11111111-1111-4111-8111-111111111111'
    view = '22222222-2222-4222-8222-222222222222'
    date = XmlDateTime.from_string('2026-11-20T09:00:00Z')
    comment = model.Comment(guid='33333333-3333-4333-8333-333333333333', date=date, author='Reviewer', comment='Keep this comment')
    point = model.ViewPoint(guid=view, viewpoint='viewpoint.bcfv', snapshot='snapshot.png')
    topic = model.Topic(guid=guid, title='Archive round trip', creation_date=date, creation_author='Architect', description='Preserve every attachment', topic_type='Issue', topic_status='Open')
    if version == '2.1':
        markup = model.Markup(topic=topic, comment=[comment], viewpoints=[point])
    else:
        topic.comments = model.TopicComments(comment=[comment])
        topic.viewpoints = model.TopicViewpoints(view_point=[point])
        markup = model.Markup(topic=topic)
    camera = dict(camera_view_point=model.Point(x=0,y=0,z=5), camera_direction=model.Direction(x=0,y=0,z=-1), camera_up_vector=model.Direction(x=0,y=1,z=0),view_to_world_scale=10)
    if version == '3.0':camera['aspect_ratio']=1
    viewpoint = model.VisualizationInfo(guid=view, orthogonal_camera=model.OrthogonalCamera(**camera))
    with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED) as archive:
        archive.comment = b'Preserve archive metadata'
        archive.writestr('bcf.version',serializer.serialize(model.Version(version_id=version)))
        archive.writestr(guid+'/markup.bcf',serializer.serialize(markup))
        archive.writestr(guid+'/viewpoint.bcfv',serializer.serialize(viewpoint))
        archive.writestr(guid+'/snapshot.png',bytes.fromhex('89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d49444154789c63d008a8f80f00038401f0696a165b0000000049454e44ae426082'))
        archive.writestr('documents/source-note.txt','Original attached document')
    return guid


@pytest.mark.parametrize('version',['2.1','3.0'])
def test_real_bcf_archive_reads_writes_and_preserves_all_metadata(tmp_path, bcf_xml_site, version):
    import xml.etree.ElementTree as ET
    from nodelang import daily_work_nodes as daily
    source,target=tmp_path/'source.bcfzip',tmp_path/'copy.bcfzip'
    guid=make_bcf_archive(source,version)
    result=daily.run_worker('bcf_exchange',{'source':str(source),'target':str(target),'version':version},site=Path(bcf_xml_site) if bcf_xml_site else None,budget_s=15)
    assert result['version']==version and result['issues'][0]['guid']==guid
    assert target.read_bytes()==source.read_bytes()
    # Independent reader: stdlib ZIP/XML, no production worker or BCF serializer code.
    with zipfile.ZipFile(target) as archive:
        assert archive.testzip() is None and archive.comment==b'Preserve archive metadata'
        assert ET.fromstring(archive.read('bcf.version')).attrib['VersionId']==version
        markup=ET.fromstring(archive.read(guid+'/markup.bcf'))
        assert any(node.text=='Keep this comment' for node in markup.iter())
        assert archive.read('documents/source-note.txt')==b'Original attached document'
        assert archive.read(guid+'/snapshot.png').startswith(b'\x89PNG')
    wrong=tmp_path/'wrong.bcfzip'
    with pytest.raises(RuntimeError,match='Cross-version'):
        daily.run_worker('bcf_exchange',{'source':str(source),'target':str(wrong),'version':'3.0' if version=='2.1' else '2.1'},site=Path(bcf_xml_site) if bcf_xml_site else None,budget_s=15)
    assert not wrong.exists()


def test_bcf_scoped_default_and_explicit_parameter_reach_the_existing_worker(tmp_path, monkeypatch, bcf_xml_site):
    from nodelang import daily_work_nodes as daily, canvas_documents as canvas,session_files as files,settings_owner
    from nodelang.nograph_server import JsonFile
    from nodelang.user_paths import state_directory
    root=tmp_path/'registered';root.mkdir()
    roots=JsonFile(state_directory()/'settings/workspaces.json',{'roots':[]})
    roots.write({'roots':[{'root_id':'probe','label':'Probe','path':str(root),'settings':{'Projects.BCF version':'3.0'}}]})
    prefs=JsonFile(files.profile_directory()/'settings/settings.json',{})
    settings_owner.preference_settings('setAppearance',['Projects.BCF version','2.1'],prefs)
    document=files.new_document('BCF scope');document['properties']['project']='probe'
    source=root/'source.bcfzip';make_bcf_archive(source,'3.0')
    captured=[]
    original=daily.run_worker
    def worker(job,args,**kwargs):
        captured.append(dict(args));return original(job,args,**kwargs)
    monkeypatch.setattr(daily,'run_worker',worker)
    approved=[]
    monkeypatch.setattr(daily,'DECIDE',lambda payload,vendor:approved.append(payload['tool_input']['bcf_version']) or {'decision':'allow'})
    params={**daily.DAILY_ENGINES['daily.ifc_check_bcf']['params'],'bcf':str(source)}
    result=canvas.run_thing('daily.ifc_check_bcf',params,{},document)[0]
    assert captured[-1]['version']=='3.0' and approved[-1]=='3.0' and result['version']=='3.0'
    assert any(daily.runtimes_root().glob('bcf-*/ready.json')) and not list(daily.runtimes_root().glob('ifc-*'))
    document['properties']['settings']={'Projects.BCF version':'2.1'}
    canvas.run_thing('daily.ifc_check_bcf',params,{},document)
    assert captured[-1]['version']=='2.1'
    canvas.run_thing('daily.ifc_check_bcf',{**params,'bcf_version':'3.0'},{},document)
    assert captured[-1]['version']=='3.0' and approved[-1]=='3.0'
    canvas.run_thing('daily.ifc_check_bcf',params,{'bcf_version':'3.0'},document)
    assert captured[-1]['version']=='3.0' and approved[-1]=='3.0'
    before=prefs.path.read_bytes()
    with pytest.raises(ValueError):settings_owner.preference_settings('setAppearance',['Projects.BCF version','9.0'],prefs)
    assert prefs.path.read_bytes()==before


@pytest.mark.parametrize('case',['unsafe path','duplicate path','unsupported version','expanded budget','external entity','negative budget'])
def test_bcf_refusals_preserve_existing_output(tmp_path, bcf_xml_site, case):
    from nodelang import daily_work_nodes as daily
    source,target=tmp_path/'input.bcfzip',tmp_path/'held.bcfzip'
    make_bcf_archive(source,'2.1');target.write_bytes(b'Keep the existing output')
    with zipfile.ZipFile(source,'a',zipfile.ZIP_DEFLATED) as archive:
        if case=='unsafe path':archive.writestr('../escape.txt','bad')
        elif case=='duplicate path':archive.writestr('bcf.version','duplicate')
        elif case=='unsupported version':
            pass
        elif case=='expanded budget':archive.writestr('large.txt','x'*100000)
        elif case=='external entity':archive.writestr('extra.bcfv','<!DOCTYPE x [<!ENTITY y SYSTEM "file:///not-read">]><VisualizationInfo/>')
    if case=='unsupported version':
        with zipfile.ZipFile(source,'r') as archive:entries={name:archive.read(name) for name in archive.namelist()}
        entries['bcf.version']=b'<Version VersionId="4.0"/>'
        with zipfile.ZipFile(source,'w') as archive:
            for name,data in entries.items():archive.writestr(name,data)
    with pytest.raises(RuntimeError):
        daily.run_worker('bcf_exchange',{'source':str(source),'target':str(target),'version':'2.1','archive_bytes':-1 if case=='negative budget' else 80000},site=Path(bcf_xml_site) if bcf_xml_site else None,budget_s=15)
    assert target.read_bytes()==b'Keep the existing output'


def test_new_bcf_nodes_inherit_design_default_old_files_keep_explicit_legacy_behavior(tmp_path, monkeypatch):
    from nodelang import canvas_documents as canvas,daily_work_nodes as daily,settings_owner,session_files as files
    assert settings_owner.preference_setting('Projects.BCF version')['value']=='3.0'
    document=files.new_document('Portable old BCF workflow')
    document['nodes']=[{'id':'old','type':'daily.ifc_check_bcf','params':{'ifc':'sample.ifc'},'position':{'x':0,'y':0}}]
    path=files.document_path(files.sessions_directory(),document);files.write_document(path,document)
    before=path.read_bytes();reopened=files.read_document(path)
    asked=[]
    monkeypatch.setattr(daily,'DECIDE',lambda payload,vendor:asked.append(payload['tool_input']['bcf_version']) or {'decision':'ask','reason':'Fixture approval'})
    with pytest.raises(PermissionError):canvas.run_thing('daily.ifc_check_bcf',reopened['nodes'][0]['params'],{},reopened)
    assert asked[-1]=='2.1' and path.read_bytes()==before and 'bcf_version' not in files.read_document(path)['nodes'][0]['params']
    with pytest.raises(PermissionError):canvas.run_thing('daily.ifc_check_bcf',daily.DAILY_ENGINES['daily.ifc_check_bcf']['params'],{},document)
    assert asked[-1]=='3.0'
    with pytest.raises(PermissionError):canvas.run_thing('daily.ifc_check_bcf',reopened['nodes'][0]['params'],{'bcf_version':'3.0'},reopened)
    assert asked[-1]=='3.0'


def test_normal_bcf_entry_requires_file_write_approval_and_rejects_other_files(tmp_path,monkeypatch,bcf_xml_site):
    import os
    from nodelang import canvas_documents as canvas,daily_work_nodes as daily
    from nodelang.hook_decision import _RELEASING
    source=tmp_path/'input.bcfzip';make_bcf_archive(source,'3.0')
    held=tmp_path/'keep.txt';held.write_bytes(b'Keep this file')
    params={**daily.DAILY_ENGINES['daily.ifc_check_bcf']['params'],'bcf':str(source),'bcf_path':str(held)}
    monkeypatch.setattr(daily,'DECIDE',lambda *args:{'decision':'allow'})
    with pytest.raises(ValueError,match='.bcf'):canvas.run_thing('daily.ifc_check_bcf',params,{})
    assert held.read_bytes()==b'Keep this file' and not daily.runtimes_root().exists()
    alias=tmp_path/'alias.bcf';os.link(source,alias)
    with pytest.raises(ValueError,match='differ'):canvas.run_thing('daily.ifc_check_bcf',{**params,'bcf_path':str(alias)},{})
    assert alias.read_bytes()==source.read_bytes()
    output=tmp_path/'out.bcfzip';params['bcf_path']=str(output)
    with pytest.raises(PermissionError,match='Approve card'):canvas.run_thing('daily.ifc_check_bcf',params,{})
    assert not output.exists() and not daily.runtimes_root().exists()
    token=_RELEASING.set(True)
    try:result=canvas.run_thing('daily.ifc_check_bcf',params,{})[0]
    finally:_RELEASING.reset(token)
    assert result['version']=='3.0' and output.read_bytes()==source.read_bytes()
    for budget in (-1,0,64*1024*1024+1):
        with pytest.raises(ValueError,match='budgets'):canvas.run_thing('daily.ifc_check_bcf',{**params,'bcf_path':'','archive_bytes':budget},{})
    assert output.read_bytes()==source.read_bytes()


@pytest.mark.parametrize('legacy',[False,True])
def test_saved_bcf_node_run_creates_actionable_approval_and_reads_back(tmp_path,bcf_xml_site,legacy):
    import copy
    from nodelang import session_files as files
    from nodelang.hook_decision import ask_apply,ask_reviews
    version='2.1' if legacy else '3.0'
    source,target=tmp_path/'source.bcfzip',tmp_path/'approved.bcfzip';make_bcf_archive(source,version)
    item=next(row for row in files.catalogue() if row['id']=='daily:ifc_check_bcf')
    node={'id':'exchange','item':item['id'],'type':item['engine'],'params':copy.deepcopy(item['params']),
          'ports':copy.deepcopy(item['ports']),'paramDefs':copy.deepcopy(item.get('paramDefs',[])),'position':{'x':0,'y':0}}
    node['params'].update(bcf=str(source),bcf_path=str(target))
    if legacy:node['params'].pop('bcf_version',None);node['paramDefs']=[]
    assert 'approvalRequired' not in node
    document=files.new_document('BCF approval');document['nodes']=[node]
    path=tmp_path/'approved.archhub';files.write_document(path,document)
    owner=files.SessionFiles(tmp_path/'sessions')
    run=owner.dispatch({'action':'run','path':str(path),'document':files.read_document(path)})
    assert run.get('approvalId') and not target.exists()
    card=next(card for card in ask_reviews() if card['id']==run['approvalId'])
    decided=ask_apply(card['id'],card['input_digest'],'approve')
    assert decided['status']=='approved',decided
    assert target.exists(),decided
    assert target.read_bytes()==source.read_bytes()
    result=files.read_document(path)['nodes'][0]['result']
    assert result['status']=='Done' and result['output']['version']==version
    assert 'approvalRequired' not in files.read_document(path)['nodes'][0]


@pytest.mark.parametrize('change',['setting','source'])
def test_bcf_approval_cannot_silently_change_inputs(tmp_path,bcf_xml_site,change):
    import copy
    from nodelang import session_files as files,settings_owner
    from nodelang.hook_decision import ask_apply,ask_reviews
    source,target=tmp_path/'source.bcfzip',tmp_path/'must-not-write.bcfzip';make_bcf_archive(source,'3.0')
    item=next(row for row in files.catalogue() if row['id']=='daily:ifc_check_bcf')
    node={'id':'exchange','item':item['id'],'type':item['engine'],'params':{**copy.deepcopy(item['params']),'bcf':str(source),'bcf_path':str(target)},'paramDefs':copy.deepcopy(item.get('paramDefs',[])),'position':{'x':0,'y':0}}
    document=files.new_document('BCF revalidation');document['nodes']=[node]
    path=tmp_path/'held.archhub';files.write_document(path,document);owner=files.SessionFiles(tmp_path/'sessions')
    waiting=owner.dispatch({'action':'run','path':str(path),'document':files.read_document(path)})
    card=next(card for card in ask_reviews() if card['id']==waiting['approvalId'])
    if change=='setting':settings_owner.preference_settings('setAppearance',['Projects.BCF version','2.1'])
    else:
        with zipfile.ZipFile(source,'a') as archive:archive.writestr('changed.txt','Input changed after the card')
    with pytest.raises(ValueError,match='changed after'):
        ask_apply(card['id'],card['input_digest'],'approve')
    assert not target.exists()


def test_saved_bcf_read_without_output_stays_usable_without_write_card(tmp_path,bcf_xml_site):
    import copy
    from nodelang import session_files as files
    from nodelang.hook_decision import ask_reviews
    source=tmp_path/'read.bcfzip';make_bcf_archive(source,'2.1')
    item=next(row for row in files.catalogue() if row['id']=='daily:ifc_check_bcf')
    document=files.new_document('Read BCF');document['nodes']=[{'id':'read','item':item['id'],'type':item['engine'],'params':{**copy.deepcopy(item['params']),'bcf':str(source)},'position':{'x':0,'y':0}}]
    path=tmp_path/'read.archhub';files.write_document(path,document)
    result=files.SessionFiles(tmp_path/'sessions').dispatch({'action':'run','path':str(path),'document':files.read_document(path)})
    assert not result.get('approvalId') and not [card for card in ask_reviews() if card['status']=='pending']
    assert files.read_document(path)['nodes'][0]['result']['output'].get('version')=='2.1',result


def test_ifc_report_serialization_failure_preserves_destination(tmp_path,bcf_xml_site):
    from nodelang.daily_work_worker import save_bcf_report
    target=tmp_path/'existing.bcfzip';make_bcf_archive(target,'3.0');before=target.read_bytes()
    class BrokenArchive:
        def save(self,path):
            with zipfile.ZipFile(path,'w') as partial:partial.writestr('partial.txt','Incomplete serialization')
            raise RuntimeError('Serialization failed')
    with pytest.raises(RuntimeError,match='Serialization failed'):save_bcf_report(BrokenArchive(),target)
    assert target.read_bytes()==before and not list(tmp_path.glob('.bcf-*'))


def test_two_real_processes_share_one_managed_bcf_runtime(tmp_path,bcf_xml_site):
    import json,subprocess,sys,time
    from concurrent.futures import ThreadPoolExecutor
    from nodelang import daily_work_nodes as daily
    module=Path(daily.__file__).resolve()
    package=Path(__import__('nodelang').__file__).resolve().parent.parent
    code = """import importlib.util,sys,json,time
from pathlib import Path
sys.path.insert(0,sys.argv[1])
import nodelang
spec=importlib.util.spec_from_file_location('nodelang.daily_work_nodes',sys.argv[2]);daily=importlib.util.module_from_spec(spec);sys.modules[spec.name]=daily;nodelang.daily_work_nodes=daily;spec.loader.exec_module(daily)
barrier=Path(sys.argv[3]);(barrier/(sys.argv[4]+'.ready')).write_text('ready')
end=time.monotonic()+20
while not (barrier/'go').exists():
 if time.monotonic()>end:raise TimeoutError('Fixture barrier')
 time.sleep(.01)
home=daily.ensure_runtime('bcf',budget_s=20)
print(json.dumps({'home':str(home),'ready':(home/'ready.json').read_text(),'files':len(list((home/'site').rglob('*.py')))}))
"""
    with ThreadPoolExecutor(max_workers=2) as callers:
        pending=[callers.submit(subprocess.run,[sys.executable,'-B','-c',code,str(package),str(module),str(tmp_path),str(i)],stdin=subprocess.DEVNULL,capture_output=True,text=True,encoding='utf-8',timeout=45,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0)) for i in range(2)]
        end=time.monotonic()+20
        while len(list(tmp_path.glob('*.ready')))!=2:
            assert time.monotonic()<end
            time.sleep(.01)
        (tmp_path/'go').write_text('go')
        results=[]
        for caller in pending:
            completed=caller.result(timeout=50);assert completed.returncode==0,completed.stderr
            results.append(json.loads(completed.stdout.strip().splitlines()[-1]))
    assert results[0]==results[1] and results[0]['files']>0
    home=Path(results[0]['home']);published=(home/'ready.json').read_bytes()
    assert daily.ensure_runtime('bcf',budget_s=10)==home and (home/'ready.json').read_bytes()==published
    assert not list(daily.runtimes_root().glob('bcf-*.building')) and not list(daily.runtimes_root().glob('ifc-*'))


def test_oversized_compressed_input_refuses_before_card_or_runtime(tmp_path,bcf_xml_site):
    import copy
    from nodelang import session_files as files,daily_work_nodes as daily
    from nodelang.hook_decision import ask_reviews
    source=tmp_path/'input.bcfzip';make_bcf_archive(source,'3.0')
    item=next(row for row in files.catalogue() if row['id']=='daily:ifc_check_bcf')
    document=files.new_document('Bound BCF input');document['nodes']=[{'id':'bound','item':item['id'],'type':item['engine'],'params':{**copy.deepcopy(item['params']),'bcf':str(source),'bcf_path':str(tmp_path/'output.bcfzip'),'archive_bytes':source.stat().st_size-1},'position':{'x':0,'y':0}}]
    path=tmp_path/'bounded.archhub';files.write_document(path,document)
    result=files.SessionFiles(tmp_path/'sessions').dispatch({'action':'run','path':str(path),'document':files.read_document(path)})
    assert not result.get('approvalId') and not ask_reviews() and not daily.runtimes_root().exists()
    assert 'compressed archive' in files.read_document(path)['nodes'][0]['result']['error']
    assert not (tmp_path/'output.bcfzip').exists()
