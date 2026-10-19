"""Installer custody guards, exercised without a person's profile."""
import shutil
import sqlite3

import pytest

from nodelang import application_recovery_files as files


@pytest.fixture(autouse=True)
def installer_fixtures_stay_in_lane(monkeypatch):
    monkeypatch.setattr(files, '_fixed_backup_drives', lambda: [])


def journal(profile):
    path = profile / 'ArchHub-Test' / 'archhub-test.universal.sqlite3'
    path.parent.mkdir(parents=True)
    with sqlite3.connect(path) as database:
        database.execute('CREATE TABLE work (value TEXT)')
        database.execute("INSERT INTO work VALUES ('saved work')")
    database.close()
    return path


def test_installer_keeps_25_gib_after_copy(tmp_path, monkeypatch):
    source = journal(tmp_path)
    before = source.read_bytes()
    usage = shutil.disk_usage(tmp_path)
    monkeypatch.setattr(files.shutil, 'disk_usage', lambda _: usage._replace(free=25 * 1024**3))
    with pytest.raises(OSError, match='25 GiB'):
        files.preserve_closed_application_journals(tmp_path, 'low-space')
    assert source.read_bytes() == before
    assert not list(tmp_path.rglob('*-closed'))


def test_installer_refuses_over_budget_before_copy(tmp_path):
    journal(tmp_path)
    with pytest.raises(ValueError, match='over budget'):
        files.preserve_closed_application_journals(tmp_path, 'over-budget', max_bytes=1)
    assert not list(tmp_path.rglob('*-closed'))


def test_installer_reports_every_backup_stage(tmp_path):
    journal(tmp_path)
    events = []
    completed = files.preserve_closed_application_journals(tmp_path, 'progress', progress=events.append)
    assert len(completed) == 1
    for stage in ('Selecting', 'Hashing', 'Copying', 'Verifying', 'Complete'):
        assert any(stage in event for event in events), (stage, events)


def test_all_candidate_copies_have_one_installer_container(tmp_path):
    source = journal(tmp_path)
    root = tmp_path / 'ArchHub'
    root.mkdir()
    for name in ('authority.sqlite3', 'archhub-test.universal.sqlite3', 'node-native-wip.json.gz.universal.sqlite3'):
        shutil.copyfile(source, root / name)
    paths = files.preserve_closed_application_journals(tmp_path, 'one-container')
    assert len(paths) == 4
    from pathlib import Path
    assert all(Path(path).is_relative_to(root / 'backups') for path in paths)
    assert not (source.parent / 'backups').exists()
    assert len({Path(path).parent for path in paths}) == 4


def test_installer_rechecks_reserve_after_copy_before_payload_replacement(tmp_path, monkeypatch):
    source = journal(tmp_path)
    usage = shutil.disk_usage(tmp_path)
    calls = []
    def available(_):
        calls.append(True)
        return usage._replace(free=(24 if list(tmp_path.rglob('*-closed')) else 100) * 1024**3)
    monkeypatch.setattr(files.shutil, 'disk_usage', available)
    with pytest.raises(OSError, match='after backup'):
        files.preserve_closed_application_journals(tmp_path, 'concurrent-disk-pressure')
    assert source.is_file()
    assert len(list(tmp_path.rglob('*-closed'))) == 1
