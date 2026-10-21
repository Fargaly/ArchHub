"""ADOPT courts: synthetic profiles only, never a desktop profile."""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import time

from nodelang import persistence
from nodelang.universal_cell import CellStore
from tests_replica import test_ogboot_upgrade_selection as upgrade

isolated_profile = upgrade.isolated_profile


def closed_backup(root, source, *, include_content_when_absent=True):
    """The installer's exact verified final-close manifest, synthetic bytes."""
    backup = root / "backups/20261017-court-closed"
    backup.mkdir(parents=True)
    content = Path(str(source) + '.conversations.sqlite3')
    if not content.exists() and include_content_when_absent:
        with closing(sqlite3.connect(content)) as db:
            db.execute('CREATE TABLE installer_fixture(singleton INTEGER PRIMARY KEY)')
            db.commit()
    records = []
    for path in (source, *((content,) if content.exists() else ())):
        shutil.copyfile(path, backup / path.name)
        records.append(dict(name=path.name, bytes=path.stat().st_size,
            sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    manifest = dict(kind="closed-file-preservation", runtime="1"*32, build="20261017-court", files=records)
    (backup / "closed-files.json").write_text(json.dumps(manifest))
    return backup


def fixture(local):
    root = local / "ArchHub"
    stale = upgrade._selected(root)
    source = upgrade._journal(local / "ArchHub-Test/archhub-test.universal.sqlite3", "saved edit", 200)
    backup = closed_backup(source.parent, source)
    return root, stale, source, backup


def test_upgrade_never_calls_the_blocking_copy(isolated_profile, monkeypatch):
    from nodelang import application_recovery_files
    root, stale, source, backup = fixture(isolated_profile)
    before = hashlib.sha256(stale.read_bytes()).hexdigest()
    physical = (source.stat().st_dev, source.stat().st_ino)
    def slow_copy(*_args, **_kwargs):
        raise AssertionError("RED: full journal copy blocks Studio boot")
    monkeypatch.setattr(application_recovery_files, "_backup_sqlite", slow_copy)
    started = time.monotonic()
    result = persistence.prepare_application_database(root, stale)
    selected = persistence.application_database_path(root)
    assert (selected.stat().st_dev, selected.stat().st_ino) == physical
    assert source.is_file() and selected == source
    assert result["state"] == "adopted"
    assert result["backup_path"] == str(backup)
    assert hashlib.sha256(stale.read_bytes()).hexdigest() == before
    with CellStore(selected) as store:
        assert store.snapshot().cells["app:archhub"].atom == b"saved edit"
    seconds = time.monotonic() - started
    assert seconds < 45
    print("ADOPT_BOOT_SECONDS", seconds)


def test_missing_installer_backup_opens_and_preserves_old_selection_bytes(isolated_profile):
    root = isolated_profile / "ArchHub"
    stale = upgrade._selected(root)
    source = upgrade._journal(isolated_profile / "ArchHub-Test/archhub-test.universal.sqlite3", "saved", 200)
    before = stale.read_bytes()
    result = persistence.prepare_application_database(root, stale)
    assert persistence.application_database_path(root) == source
    assert stale.read_bytes() == before
    assert result['backup_path']
    with CellStore(source) as reopened:
        assert reopened.read('app:archhub').atom == b'saved'
