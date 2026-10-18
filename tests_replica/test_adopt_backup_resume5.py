"""Synthetic installer custody stays bounded across daily upgrades."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3

import pytest

from nodelang import application_recovery_files as files
from nodelang.backup_retention import prune_backups


def _journal(profile):
    path = profile / 'ArchHub-Test/archhub-test.universal.sqlite3'
    path.parent.mkdir(parents=True)
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE work (value TEXT)')
        db.execute("INSERT INTO work VALUES ('original graph')")
    return path


def _edit(path, value):
    with sqlite3.connect(path) as db:
        db.execute('INSERT INTO work VALUES (?)', (value,))


def test_five_identical_installs_reuse_verified_copy_before_disk_reserve(tmp_path, monkeypatch):
    source = _journal(tmp_path)
    first = files.preserve_closed_application_journals(tmp_path, 'install-0')
    monkeypatch.setattr(files, '_require_disk_reserve', lambda *_:
        pytest.fail('RED: identical journal requires another full-copy disk reserve'))
    for number in range(1, 5):
        assert files.preserve_closed_application_journals(tmp_path, f'install-{number}') == first
    backups = list((source.parent / 'backups').glob('*-closed'))
    assert len(backups) == 1
    assert (backups[0] / source.name).read_bytes() == source.read_bytes()


def test_same_head_with_derived_index_reuses_custody_but_changed_rows_do_not(tmp_path, monkeypatch):
    from tests_replica.test_ogboot_upgrade_selection import _journal as cell_journal
    source = cell_journal(tmp_path / 'ArchHub-Test/archhub-test.universal.sqlite3', 'graph', 300)
    original = files.preserve_closed_application_journals(tmp_path, 'original')
    before = source.read_bytes()
    with closing(sqlite3.connect(source)) as db:
        db.execute('CREATE INDEX derived_installer_probe ON current_cells(link0)')
        db.commit()
    assert source.read_bytes() != before
    with monkeypatch.context() as guard:
        guard.setattr(files, '_require_disk_reserve', lambda *_:
            pytest.fail('same head with a derivable index requires another copy'))
        assert files.preserve_closed_application_journals(tmp_path, 'derived') == original
    # An out-of-band edit cannot masquerade as the same logical journal head.
    with closing(sqlite3.connect(source)) as db:
        for (trigger,) in db.execute("SELECT name FROM sqlite_master WHERE type='trigger'").fetchall():
            db.execute('DROP TRIGGER "' + trigger.replace('"', '""') + '"')
        db.execute("UPDATE current_cells SET atom=x'74616d7065726564' WHERE cell_id='app:archhub'")
        db.commit()
    changed = files.preserve_closed_application_journals(tmp_path, 'changed')
    assert changed != original
    assert (Path(changed[0]) / source.name).read_bytes() == source.read_bytes()


def test_changed_installs_keep_one_pre_adopt_pin_and_three_normal_copies(tmp_path):
    source = _journal(tmp_path)
    first = Path(files.preserve_closed_application_journals(tmp_path, 'initial')[0])
    # Adoption's existing locator marks that future backups are ordinary recovery.
    Path(str(source) + '.adoption.json').write_text('{}')
    for number in range(5):
        _edit(source, str(number))
        files.preserve_closed_application_journals(tmp_path, f'changed-{number}')
    backups = list((source.parent / 'backups').glob('*-closed'))
    pinned = [path for path in backups if json.loads((path / 'closed-files.json').read_text())
              .get('retain_until_user_deletes') is True]
    assert pinned == [first]
    assert len(backups) == 4
    assert sum((path / source.name).stat().st_size for path in backups) <= 4 * source.stat().st_size


def test_latest_pre_adopt_copy_replaces_previous_pin(tmp_path):
    source = _journal(tmp_path)
    first = Path(files.preserve_closed_application_journals(tmp_path, 'initial')[0])
    _edit(source, 'new graph')
    latest = Path(files.preserve_closed_application_journals(tmp_path, 'later')[0])
    assert json.loads((latest / 'closed-files.json').read_text())['retain_until_user_deletes'] is True
    assert json.loads((first / 'closed-files.json').read_text())['retain_until_user_deletes'] is False
    assert files.preserve_closed_application_journals(tmp_path, 'unchanged') == [str(latest)]


def test_newer_empty_candidate_cannot_unpin_selected_work(tmp_path):
    from tests_replica.test_ogboot_upgrade_selection import _journal as cell_journal
    import uuid
    source = cell_journal(tmp_path / 'ArchHub/authority.sqlite3', 'actual work', 300)
    stale = source.with_name('node-native-wip.json.gz.universal.sqlite3')
    from nodelang.universal_cell import CellStore
    with CellStore(stale):
        pass
    generation = str(uuid.uuid4())
    directory = source.parent / 'unified-authority/generations' / generation
    directory.mkdir(parents=True)
    (directory / 'migration.json').write_text(json.dumps({
        'adoption': 'flat-in-place', 'journal_relative_path': source.name}))
    (directory.parent.parent / 'CURRENT').write_text(generation)
    for number in range(5):
        files.preserve_closed_application_journals(tmp_path, f'install-{number}')
    backups = list((source.parent / 'backups').glob('*-closed'))
    pinned = [path for path in backups if json.loads((path / 'closed-files.json').read_text())
              .get('retain_until_user_deletes') is True]
    assert len(pinned) == 1
    assert (pinned[0] / source.name).read_bytes() == source.read_bytes()
    assert not (pinned[0] / stale.name).exists()
    assert len(backups) == 2


def test_graph_control_work_inside_trace_prefix_outranks_empty_selection(tmp_path):
    from nodelang.universal_cell import Cell, CellStore, NULL_CELL_ID
    source = tmp_path / 'ArchHub-Test/archhub-test.universal.sqlite3'
    source.parent.mkdir()
    with CellStore(source) as store:
        store.commit(store.revision, create=(Cell('app:workshop:conversation:graph:control',
            NULL_CELL_ID, NULL_CELL_ID, b'graph work'),))
    empty = tmp_path / 'ArchHub/authority.sqlite3'
    empty.parent.mkdir()
    with CellStore(empty):
        pass
    files.preserve_closed_application_journals(tmp_path, 'graph-control')
    pinned = [path for parent in (source.parent, empty.parent)
              for path in (parent / 'backups').glob('*-closed')
              if json.loads((path / 'closed-files.json').read_text())['retain_until_user_deletes']]
    assert len(pinned) == 1
    assert (pinned[0] / source.name).read_bytes() == source.read_bytes()
    assert not Path(str(source) + '-wal').exists()
    assert not Path(str(empty) + '-wal').exists()


def test_armed_update_custody_survives_normal_installer_pruning(tmp_path):
    source = _journal(tmp_path)
    files.preserve_closed_application_journals(tmp_path, 'initial', keep_count=1)
    Path(str(source) + '.adoption.json').write_text('{}')
    _edit(source, 'armed graph')
    armed = files.preserve_closed_application_journals(tmp_path, 'armed', keep_count=1)[0]
    updates = tmp_path / 'ArchHub/updates'
    updates.mkdir(parents=True)
    (updates / 'update-ready.json').write_text(json.dumps({'recovery': {'path': armed}}))
    for number in range(3):
        _edit(source, str(number))
        files.preserve_closed_application_journals(tmp_path, f'later-{number}', keep_count=1)
    assert Path(armed).is_dir()


def test_flat_closed_backups_participate_in_runtime_retention(tmp_path):
    source = _journal(tmp_path)
    paths = [Path(files.preserve_closed_application_journals(tmp_path, 'initial')[0])]
    Path(str(source) + '.adoption.json').write_text('{}')
    for number in range(2):
        _edit(source, str(number))
        paths.append(Path(files.preserve_closed_application_journals(tmp_path, f'changed-{number}')[0]))
    removed = []
    result = prune_backups(source.parent / 'backups', keep=paths[-1], keep_count=1,
                          remove=lambda path: removed.append(path.name))
    assert result['kept'] == sorted((paths[0].name, paths[-1].name))
    assert removed == [paths[1].name]


@pytest.mark.parametrize('hot', [False, True])
def test_reuse_refuses_tampered_backup_or_hot_source(tmp_path, hot):
    source = _journal(tmp_path)
    backup = Path(files.preserve_closed_application_journals(tmp_path, 'initial')[0])
    if hot:
        Path(str(source) + '-wal').write_bytes(b'hot writer')
    else:
        with (backup / source.name).open('ab') as writer:
            writer.write(b'tampered')
    with pytest.raises(ValueError):
        files.preserve_closed_application_journals(tmp_path, 'repeat')


def test_installer_script_runs_with_only_extracted_stdlib_owners(tmp_path):
    import subprocess
    import sys
    source = _journal(tmp_path / 'profile')
    extracted = tmp_path / 'setup'
    extracted.mkdir()
    for module in ('application_recovery_files.py', 'backup_retention.py', 'conversation_trace_shapes.py'):
        (extracted / module).write_bytes((Path(files.__file__).parent / module).read_bytes())
    for build in ('one', 'two'):
        result = subprocess.run([sys.executable, str(extracted / 'application_recovery_files.py'),
            '--closed-profile', str(tmp_path / 'profile'), '--build', build], cwd=extracted,
            capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, result.stderr
    assert len(list((source.parent / 'backups').glob('*-closed'))) == 1
