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
        assert cards[engine]['ports'] == {'source': spec['out'], 'target': spec['in']}
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
