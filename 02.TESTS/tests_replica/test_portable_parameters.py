"""F169: typed paths move with the document; legacy saves keep their bytes."""
import json
import shutil
from pathlib import Path

import pytest


def parameter(kind, value):
    from nodelang.session_files import new_document
    doc = new_document('Portable input')
    doc['nodes'] = [{'id': 'input', 'type': 'param.value', 'params': {'type': kind, 'value': value},
                     'paramDefs': [{'id': 'value', 'name': 'Input', 'type': kind}], 'position': {'x': 0, 'y': 0}}]
    return doc


@pytest.mark.parametrize('kind', ['file', 'folder', 'path'])
def test_typed_path_saved_relative_and_runs_after_move(tmp_path, kind):
    from nodelang.session_files import SessionFiles, read_document
    root = tmp_path / 'project'
    root.mkdir()
    inputs = root / 'inputs'
    inputs.mkdir()
    source = inputs if kind == 'folder' else inputs / 'data.txt'
    if kind != 'folder':
        source.write_text('Portable input', encoding='utf-8')
    doc = parameter(kind, str(source))
    doc['nodes'].append({'id': 'read', 'type': 'thing.file', 'params': {'path': ''},
                         'paramDefs': [{'id': 'path', 'name': 'Path', 'type': 'file'}],
                         'position': {'x': 300, 'y': 0}})
    doc['wires'] = [{'id': 'file', 'from': {'node': 'input', 'socket': 'value'},
                     'to': {'node': 'read', 'socket': 'param:path'}}]
    owner = SessionFiles(tmp_path / 'owner')
    path = root / 'portable.archhub'
    saved = owner.dispatch({'action': 'save', 'path': str(path), 'document': doc})
    expected = 'inputs' if kind == 'folder' else 'inputs/data.txt'
    assert read_document(path)['nodes'][0]['params']['value'] == expected
    first = owner.dispatch({'action': 'run', 'path': str(path), 'document': saved['document']})
    assert first['results']['input']['output']['value'] == expected
    assert first['results']['read']['output']['path'] == str(source)
    moved = tmp_path / 'moved'
    assert root.resolve().is_relative_to(tmp_path.resolve()) and moved.resolve().is_relative_to(tmp_path.resolve())
    shutil.move(str(root), str(moved))
    path = moved / path.name
    reopened = owner.dispatch({'action': 'open', 'path': str(path)})['document']
    assert reopened['nodes'][0]['params']['value'] == expected
    ran = owner.dispatch({'action': 'run', 'path': str(path), 'document': reopened})
    resolved = moved / expected
    assert ran['results']['input']['output']['value'] == expected
    assert ran['results']['read']['output']['path'] == str(resolved)
    assert resolved.is_dir() if kind == 'folder' else resolved.read_text(encoding='utf-8') == 'Portable input'


def test_file_node_reads_moved_input_and_custom_paths(tmp_path):
    from nodelang.session_files import SessionFiles, read_document
    root = tmp_path / 'project'
    root.mkdir()
    source = root / 'input.txt'
    source.write_text('Read after move', encoding='utf-8')
    doc = parameter('file', str(source))
    doc['nodes'].append({'id': 'read', 'type': 'thing.file', 'params': {'path': str(source)},
                         'paramDefs': [{'id': 'extra', 'name': 'Folder', 'type': 'folder'}],
                         'position': {'x': 300, 'y': 0}})
    doc['nodes'][1]['params']['extra'] = str(root)
    owner = SessionFiles(tmp_path / 'owner')
    path = root / 'read.archhub'
    owner.dispatch({'action': 'save', 'path': str(path), 'document': doc})
    stored = read_document(path)
    assert stored['nodes'][1]['params'] == {'path': 'input.txt', 'extra': '.'}
    moved = tmp_path / 'moved'
    assert root.resolve().is_relative_to(tmp_path.resolve()) and moved.resolve().is_relative_to(tmp_path.resolve())
    shutil.move(str(root), str(moved))
    path = moved / path.name
    opened = owner.dispatch({'action': 'open', 'path': str(path)})['document']
    ran = owner.dispatch({'action': 'run', 'path': str(path), 'document': opened})
    assert ran['results']['read']['output']['text'] == 'Read after move'


def test_legacy_absolute_save_keeps_bytes_and_external_stays_absolute(tmp_path):
    from nodelang.session_files import SessionFiles, read_document
    owner = SessionFiles(tmp_path / 'owner')
    project = tmp_path / 'project'
    project.mkdir()
    source = project / 'old.txt'
    source.write_text('Old absolute', encoding='utf-8')
    doc = parameter('file', str(source))
    path = project / 'old.archhub'
    path.write_text(json.dumps(doc, separators=(',', ':')), encoding='utf-8')
    before = path.read_bytes()
    opened = owner.dispatch({'action': 'open', 'path': str(path)})['document']
    owner.dispatch({'action': 'save', 'path': str(path), 'document': opened})
    assert path.read_bytes() == before
    opened['title'] = 'Metadata edit only'
    owner.dispatch({'action': 'save', 'path': str(path), 'document': opened})
    assert read_document(path)['nodes'][0]['params']['value'] == str(source)
    outside = tmp_path / 'outside.txt'
    outside.write_text('External', encoding='utf-8')
    opened['nodes'][0]['params']['value'] = str(outside)
    owner.dispatch({'action': 'save', 'path': str(path), 'document': opened})
    assert read_document(path)['nodes'][0]['params']['value'] == str(outside)
    opened['nodes'][0]['params']['value'] = str(source)
    owner.dispatch({'action': 'save', 'path': str(path), 'document': opened})
    assert read_document(path)['nodes'][0]['params']['value'] == 'old.txt'


def test_relative_write_uses_existing_approve_and_readback(tmp_path):
    from nodelang.session_files import SessionFiles, read_document, new_document
    from nodelang.hook_decision import ask_apply, ask_reviews
    doc = new_document('Portable output')
    target = tmp_path / 'output.txt'
    doc['nodes'] = [{'id': 'write', 'type': 'thing.file.write',
                     'params': {'path': str(target), 'content': 'Approved portable output'},
                     'position': {'x': 0, 'y': 0}}]
    owner = SessionFiles(tmp_path / 'owner')
    path = tmp_path / 'write.archhub'
    saved = owner.dispatch({'action': 'save', 'path': str(path), 'document': doc})
    assert saved['document']['nodes'][0]['params']['path'] == 'output.txt'
    paused = owner.dispatch({'action': 'run', 'path': str(path), 'document': saved['document']})
    assert not target.exists()
    card = next(c for c in ask_reviews() if c['id'] == paused['approvalId'])
    ask_apply(card['id'], card['input_digest'], 'approve')
    assert target.read_text(encoding='utf-8') == 'Approved portable output'
    assert read_document(path)['nodes'][0]['params']['path'] == 'output.txt'
    assert read_document(path)['nodes'][0]['result']['output']['path'] == str(target)


def test_promoted_file_parameter_solve_resolves_from_owner(tmp_path):
    from nodelang import canvas_documents
    from nodelang.node_params import add_param, promote
    from nodelang.session_files import SessionFiles, new_document
    source = tmp_path / 'input.txt'
    source.write_text('Promoted file', encoding='utf-8')
    doc = new_document('Bound path')
    doc['nodes'] = [{'id': 'read', 'type': 'thing.file', 'params': {}, 'position': {'x': 300, 'y': 0}}]
    add_param(doc, 'read', 'Path', 'file', str(source))
    promoted = promote(doc, 'read', 'path')[0]
    owner = SessionFiles(tmp_path / 'owner')
    path = tmp_path / 'promoted.archhub'
    saved = owner.dispatch({'action': 'save', 'path': str(path), 'document': doc})['document']
    solved = canvas_documents.solve(saved, ['read', promoted], path=path)
    assert solved['results'][promoted]['output']['value'] == 'input.txt'
    assert solved['results']['read']['output']['path'] == str(source)
    assert solved['results']['read']['output']['text'] == 'Promoted file'


def test_file_trigger_uses_document_relative_folder(tmp_path):
    from nodelang.canvas_triggers import TriggerService
    from nodelang.session_files import SessionFiles, new_document
    inputs = tmp_path / 'inputs'
    inputs.mkdir()
    doc = new_document('Relative file trigger')
    doc['nodes'] = [{'id': 'watch', 'type': 'trigger.file',
                     'params': {'folder': str(inputs), 'pattern': '*', 'debounce_seconds': 3600},
                     'position': {'x': 0, 'y': 0}}]
    owner = SessionFiles(tmp_path / 'owner')
    saved = owner.dispatch({'action': 'save', 'path': str(tmp_path / 'watch.archhub'), 'document': doc})
    assert saved['document']['nodes'][0]['params']['folder'] == 'inputs'
    service = TriggerService(owner)
    try:
        armed = service.refresh()
        assert armed[0]['params']['folder'] == str(inputs)
    finally:
        service.close()


def test_relative_escape_and_normalization(tmp_path, monkeypatch):
    from nodelang.session_files import resolve_file_parameter
    from nodelang.settings_owner import SettingsOwner
    monkeypatch.setattr(SettingsOwner, '_roots', lambda self: [])
    project = tmp_path / 'project'
    project.mkdir()
    path = project / 'test.archhub'
    with pytest.raises(ValueError, match='escapes'):
        resolve_file_parameter('../outside.txt', path)
    assert resolve_file_parameter('inputs/../inside.txt', path) == str(project / 'inside.txt')


def test_symlink_escape_is_refused(tmp_path, monkeypatch):
    from nodelang.session_files import resolve_file_parameter
    from nodelang.settings_owner import SettingsOwner
    monkeypatch.setattr(SettingsOwner, '_roots', lambda self: [])
    project = tmp_path / 'project'
    project.mkdir()
    outside = tmp_path / 'outside'
    outside.mkdir()
    link = project / 'link'
    # Directory junctions exercise Windows reparse-point resolution without symlink privilege.
    import subprocess
    result = subprocess.run(['cmd', '/d', '/c', 'mklink', '/J', str(link), str(outside)], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    try:
        normalized = resolve_file_parameter('link/../outside.txt', project / 'test.archhub')
        assert normalized == str((project / 'link/../outside.txt').resolve())
        assert Path(normalized).is_relative_to(project)
        with pytest.raises(ValueError, match='escapes'):
            resolve_file_parameter('link/input.txt', project / 'test.archhub')
    finally:
        link.rmdir()


def test_named_workspace_root_follows_settings_relocation(tmp_path, monkeypatch):
    from nodelang.session_files import SessionFiles, resolve_file_parameter
    from nodelang.settings_owner import SettingsOwner
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    source = workspace / 'input.txt'
    source.write_text('workspace input', encoding='utf-8')
    roots = [{'root_id': 'shared-inputs', 'path': str(workspace)}]
    monkeypatch.setattr(SettingsOwner, '_roots', lambda self: roots)
    project = tmp_path / 'project'
    project.mkdir()
    path = project / 'portable.archhub'
    owner = SessionFiles(tmp_path / 'owner')
    doc = owner.dispatch({'action': 'save', 'path': str(path), 'document': parameter('file', str(source))})['document']
    reference = doc['nodes'][0]['params']['value']
    assert reference == 'workspace://shared-inputs/input.txt'
    moved = tmp_path / 'relocated'
    workspace.rename(moved)
    roots[0]['path'] = str(moved)
    assert resolve_file_parameter(reference, path) == str(moved / 'input.txt')
    assert Path(resolve_file_parameter(reference, path)).read_text(encoding='utf-8') == 'workspace input'
