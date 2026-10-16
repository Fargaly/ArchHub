"""Single-entry desktop ownership and persistence, without opening any UI."""
from __future__ import annotations

import importlib
import json
from pathlib import Path
import runpy
import uuid

import pytest

from nodelang import desktop, persistence
from nodelang.conversation_history import ConversationHistoryStore
from nodelang.universal_cell import Cell, CellStore, DatabaseOwnerConflict, NULL_CELL_ID


def _cell(name, value=b'user work'):
    return Cell(name, NULL_CELL_ID, NULL_CELL_ID, value)


def _generation(root, ident=None):
    ident = ident or str(uuid.uuid4())
    selected = root / 'unified-authority' / 'generations' / ident
    selected.mkdir(parents=True)
    database = selected / 'authority.sqlite3'
    with CellStore(database):
        pass
    (selected / 'bootstrap.json').write_text(json.dumps({'graph_id': ident}), encoding='utf-8')
    (root / 'unified-authority' / 'CURRENT').write_text(ident, encoding='ascii')
    return database


def test_the_selected_application_graph_survives_reopen(tmp_path):
    database = persistence.application_database_path(tmp_path)
    with CellStore(database) as owner:
        owner.commit(owner.revision, create=(_cell('test:saved-user-work'),))
    with CellStore(database) as owner:
        assert owner.read('test:saved-user-work').atom == b'user work'
        assert owner.database_path == str(database)


def test_closing_history_cannot_close_the_running_graph_owner(tmp_path):
    with CellStore(tmp_path / 'authority.sqlite3') as owner:
        history = ConversationHistoryStore(owner.database_path, instance_id='account', store=owner)
        history.ensure_conversation('room')
        history.append('room', author='person', content='survives', idempotency_key='message')
        history.close()
        owner.commit(owner.revision, create=(_cell('test:still-open'),))
        assert owner.read('test:still-open').atom == b'user work'


def test_invalid_current_pointer_refuses_without_creating_a_replacement(tmp_path):
    current = tmp_path / 'unified-authority' / 'CURRENT'
    current.parent.mkdir()
    current.write_text('../somewhere-else', encoding='ascii')
    with pytest.raises(ValueError):
        persistence.application_database_path(tmp_path)
    assert not (tmp_path / 'authority.sqlite3').exists()


def test_current_selects_one_generation_without_choosing_the_latest_folder(tmp_path):
    selected = _generation(tmp_path)
    unrelated = selected.parent.parent / str(uuid.uuid4())
    unrelated.mkdir()
    assert persistence.application_database_path(tmp_path) == selected
    assert persistence.selected_application_generation(selected)


def test_missing_selected_graph_never_falls_back_to_a_retired_copy(tmp_path):
    selected = _generation(tmp_path)
    selected.unlink()
    with CellStore(tmp_path / 'archhub-test.universal.sqlite3'):
        pass
    with pytest.raises(ValueError, match='missing'):
        persistence.application_database_path(tmp_path)
    assert not (tmp_path / 'authority.sqlite3').exists()


def test_explicit_profile_keeps_all_state_inside_its_declared_folder(tmp_path, monkeypatch):
    selected = tmp_path / 'profile'
    monkeypatch.setenv('ARCHHUB_TEST_STATE_DIR', str(selected))
    assert persistence.application_database_path() == selected / 'authority.sqlite3'
    from nodelang.unified_authority_runtime import default_runtime_root
    assert default_runtime_root() == selected / 'unified-authority'


def test_normal_state_no_longer_defaults_to_node_native_wip(tmp_path, monkeypatch):
    monkeypatch.delenv('ARCHHUB_TEST_STATE_DIR', raising=False)
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path))
    assert persistence.application_database_path() == tmp_path / 'ArchHub' / 'authority.sqlite3'


def test_a_second_owner_of_the_same_graph_is_refused(tmp_path):
    database = tmp_path / 'authority.sqlite3'
    with CellStore(database) as owner:
        owner.commit(owner.revision, create=(_cell('test:active'),))
        with pytest.raises(DatabaseOwnerConflict):
            CellStore(database)
        assert owner.read('test:active').atom == b'user work'


def test_a_retired_store_is_an_import_source_and_never_a_default_head(tmp_path):
    old = tmp_path / 'archhub-test.universal.sqlite3'
    with CellStore(old):
        pass
    assert old in persistence.legacy_application_sources(tmp_path)
    assert persistence.application_database_path(tmp_path) == tmp_path / 'authority.sqlite3'


def test_retired_graph_merge_is_idempotent_and_preserves_unique_work(tmp_path):
    source, target = tmp_path / 'old.sqlite3', tmp_path / 'authority.sqlite3'
    with CellStore(source) as old:
        old.commit(old.revision, create=(_cell('test:old-work'),))
    original = source.read_bytes()
    with CellStore(target) as owner:
        owner.commit(owner.revision, create=(_cell('test:current-work'),))
        result = persistence.migrate_graph_source(owner, source)
        revision = owner.revision
        assert result['state'] == 'migrated' and Path(result['backup_path']).is_dir()
        assert owner.read('test:old-work').atom == b'user work'
        assert owner.read('test:current-work').atom == b'user work'
        assert persistence.migrate_graph_source(owner, source)['state'] == 'already_migrated'
        assert owner.revision == revision
    assert source.read_bytes() == original


def test_conflicting_retired_graph_never_overwrites_or_discards_current_work(tmp_path):
    source = tmp_path / 'old.sqlite3'
    with CellStore(source) as old:
        old.commit(old.revision, create=(_cell('test:shared', b'old'),))
    with CellStore(tmp_path / 'authority.sqlite3') as owner:
        owner.commit(owner.revision, create=(_cell('test:shared', b'current'),))
        revision = owner.revision
        with pytest.raises(ValueError, match='conflicting truth'):
            persistence.migrate_graph_source(owner, source)
        assert owner.revision == revision and owner.read('test:shared').atom == b'current'


def test_historical_server_entry_routes_to_the_installed_desktop(monkeypatch):
    from nodelang import application_server
    calls = []
    monkeypatch.setattr(desktop, 'main', lambda: calls.append('desktop') or 37)
    assert application_server.main() == 37
    assert calls == ['desktop']


def test_import_does_not_construct_an_owner_or_open_qt_and_main_preserves_refusal(monkeypatch):
    from nodelang import application_server
    def forbidden(*args, **kwargs):
        pytest.fail('import constructed a second application')
    monkeypatch.setattr(application_server, 'ApplicationServer', forbidden)
    importlib.reload(desktop)
    def refused(*args, **kwargs):
        raise RuntimeError('fixture boot refusal')
    monkeypatch.setattr(runpy, 'run_path', refused)
    with pytest.raises(RuntimeError, match='fixture boot refusal'):
        desktop.main()
