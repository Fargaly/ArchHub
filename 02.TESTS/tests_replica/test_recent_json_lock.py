"""Recent metadata serializes readers/writers and reports exhausted Windows retries."""
import json
from concurrent.futures import ThreadPoolExecutor

import pytest

import test_node_params as fixtures

profile = fixtures.profile


def test_concurrent_open_save_fifty(profile):
    from nodelang.session_files import SessionFiles, new_document, write_document
    directory = profile / 'sessions'
    owners = [SessionFiles(directory) for _ in range(4)]
    paths = [directory / ('recent-%d.archhub' % i) for i in range(10)]
    for path in paths:
        write_document(path, new_document(path.stem))

    def pair(i):
        owner, path = owners[i % 4], paths[i % 10]
        opened = owner.dispatch({'action': 'open', 'path': str(path)})
        owner.dispatch({'action': 'save', 'path': str(path), 'document': opened['document']})
        assert owner.recent()

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(pair, range(50)))
    rows = json.loads((directory / 'recent.json').read_text(encoding='utf-8'))
    assert len(rows) == 10
    assert {row['path'] for row in rows} == set(map(str, paths))
    assert all(row['title'] == row['name'] for row in rows)
    assert not list(directory.glob('*.tmp'))
    print('RECENT-JSON-LOCK: concurrent open+save x50; no WinError 5; all 10 recent paths intact')


@pytest.mark.parametrize('code', [5, 32, 33])
def test_sharing_retry_then_success_and_visible_exhaustion(profile, monkeypatch, code):
    from nodelang import session_files
    owner = session_files.SessionFiles(profile / 'sessions')
    target = owner.metadata / 'recent.json'
    owner.remember(profile / 'first.archhub', {'title': 'First'})
    original = session_files.os.replace
    calls = []

    def blocked(source, destination):
        calls.append(destination)
        if len(calls) <= 2:
            error = PermissionError('Sharing violation')
            error.winerror = code
            raise error
        return original(source, destination)

    monkeypatch.setattr(session_files.os, 'replace', blocked)
    monkeypatch.setattr(session_files.time, 'sleep', lambda seconds: None)
    owner.remember(profile / 'second.archhub', {'title': 'Second'})
    assert len(calls) == 3 and len(owner.recent()) == 2
    before = target.read_bytes()

    def always_blocked(*args):
        error = PermissionError('Recent list is locked')
        error.winerror = code
        raise error

    monkeypatch.setattr(session_files.os, 'replace', always_blocked)
    with pytest.raises(PermissionError, match='Recent list is locked'):
        owner.remember(profile / 'third.archhub', {'title': 'Third'})
    assert target.read_bytes() == before
    assert not list(owner.metadata.glob('*.tmp'))
