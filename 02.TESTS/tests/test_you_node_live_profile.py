"""The You node shows the account profile live and never writes it into the .archhub file (spec 3.1 rule 2)."""
import json

from test_task_session_roundtrip import _isolate


def test_you_node_reads_the_profile_live_and_the_file_never_holds_it(tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path / 'desk')
    from nodelang import session_files as files
    from nodelang.canvas_documents import run_thing
    from nodelang.nograph_server import JsonFile
    from nodelang.settings_owner import preference_settings
    settings = JsonFile(files.profile_directory() / 'settings/settings.json', {})
    preference_settings('setAppearance', ['Account.Display name', 'Mona Example'], settings)
    preference_settings('setAppearance', ['Account.Your role', 'Project architect'], settings)
    produced, display = run_thing('thing.you', {}, {})
    assert produced['profile']['name'] == 'Mona Example' and produced['profile']['role'] == 'Project architect'
    assert display == 'Mona Example · Project architect'
    document = files.new_document('Profile probe')
    document['nodes'].append({'id': 'fixed-you', 'type': 'thing.you', 'title': 'You', 'params': {}, 'fixed': True,
                              'position': {'x': 0, 'y': 0}, 'result': {'status': 'Done', 'output': produced}})
    path = files.document_path(files.sessions_directory(), document)
    files.write_document(path, document)
    raw = open(path, encoding='utf-8').read()
    assert 'Mona Example' not in raw and 'Project architect' not in raw, 'account identity reached the file'
    assert 'result' not in next(n for n in json.loads(raw)['nodes'] if n['id'] == 'fixed-you')
