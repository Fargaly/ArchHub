"""R193: a spec or report PDF reaches an agent as text, extracted once and cached in app state."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / '01.APP'))

from nodelang import clean_office_adapter as office  # noqa: E402
from nodelang import hook_decision  # noqa: E402


def test_pdf_text_is_extracted_once_and_cached_in_app_state_not_beside_the_file(tmp_path, monkeypatch):
    project = tmp_path / 'project'
    project.mkdir()
    pdf = project / 'spec.pdf'
    pdf.write_bytes(b'%PDF-1.4 fixture')
    state = tmp_path / 'state'
    monkeypatch.setattr('nodelang.user_paths.state_directory', lambda: state)
    calls = []

    def fake_read(operation, params, *, owner_admitted=False):
        calls.append(params['path'])
        return {'out': [{'page': 1, 'text': 'Doors shall be FD60.', 'path': params['path']}]}

    monkeypatch.setattr(office, '_pdf_read', fake_read)
    params = {'path': str(pdf), 'pages': []}
    first = office._pdf_coordination('pdf.extract_text', params)
    second = office._pdf_coordination('pdf.extract_text', params)
    assert first['out'] == second['out'] and second['cached'] is True
    assert calls == [str(pdf)], 'the PDF is read once'
    assert sorted(p.name for p in project.iterdir()) == ['spec.pdf'], 'nothing is written beside his file'
    assert len(list((state / 'pdf-text').glob('*.json'))) == 1

    pdf.write_bytes(b'%PDF-1.4 fixture, changed')
    office._pdf_coordination('pdf.extract_text', params)
    assert len(calls) == 2, 'a changed PDF is read again'


def test_the_cache_keeps_only_the_newest_entries(tmp_path, monkeypatch):
    state = tmp_path / 'state'
    monkeypatch.setattr('nodelang.user_paths.state_directory', lambda: state)
    monkeypatch.setattr(office, 'PDF_TEXT_KEEP', 2)
    monkeypatch.setattr(office, '_pdf_read', lambda op, params, **kw: {'out': [{'page': 1, 'text': 'x'}]})
    for index in range(4):
        pdf = tmp_path / ('r%d.pdf' % index)
        pdf.write_bytes(b'%PDF ' + bytes([index]))
        office._pdf_coordination('pdf.extract_text', {'path': str(pdf), 'pages': []})
    assert len(list((state / 'pdf-text').glob('*.json'))) == 2


def test_an_agent_reading_a_pdf_is_pointed_at_the_text_tool_without_being_stopped(tmp_path):
    for tool in ('Read', 'read_file', 'read'):
        _action, facts = hook_decision.classify(
            {'tool': tool, 'input': {'file_path': str(tmp_path / 'Spec.PDF')}, 'cwd': str(tmp_path)}, {})
        assert facts['pdf_read'] is True
    _action, facts = hook_decision.classify(
        {'tool': 'Read', 'input': {'file_path': str(tmp_path / 'notes.md')}, 'cwd': str(tmp_path)}, {})
    assert facts['pdf_read'] is False
    assert 'pdf_extract_text' in hook_decision.PDF_TEXT_NOTE
