"""R92: retain the newest N copies (default 3) within the Settings byte budget.

Dates break ties when a reboot equalizes folder timestamps. Real application
recovery uses temporary graphs; retention never touches the installed profile.
"""
import os
import re
from datetime import date
from pathlib import Path

LAUNCHER = Path(__file__).resolve().parents[1] / "nodelang/launcher.py"
HEX = "0123456789abcdef" * 2


def test_retention_keeps_three_copies_when_a_reboot_equalizes_their_times(tmp_path):
    from nodelang.backup_retention import prune_backups
    backups = tmp_path / "backups"
    names = ["20260918-integrated-r5-closed", "graph-repair-r3-20260920", "application-recovery-20260921-" + HEX,
             "20260922-integrated-r7-closed", "application-recovery-" + HEX, ".application-recovery-stage",
             "application-recovery-20260923-" + HEX]
    for name in names:
        (backups / name).mkdir(parents=True)
        (backups / name / "graph.sqlite3").write_bytes(b"x")
    (backups / "note-20200101.txt").write_text("a plain file", encoding="utf-8")
    for entry in backups.iterdir():
        os.utime(entry, (1_790_000_000, 1_790_000_000))   # one reboot minute for every folder
    result = prune_backups(backups, keep=backups / names[-1], today=date(2026, 9, 23))
    left = sorted(entry.name for entry in backups.iterdir())
    assert set(result["removed"]) == {names[0], names[1], names[4]}, result
    assert left == sorted([names[2], names[3], names[5], names[6], "note-20200101.txt"]), left
    assert result["undated_kept"] == []
    assert len(result["kept"]) == 3


def test_nothing_is_deleted_without_a_new_verified_backup_inside_the_directory(tmp_path):
    import pytest
    from nodelang.backup_retention import prune_backups
    backups = tmp_path / "backups"
    (backups / "20200101-old").mkdir(parents=True)
    with pytest.raises(ValueError):
        prune_backups(backups, keep=tmp_path / "elsewhere", today=date(2026, 9, 23))
    assert (backups / "20200101-old").is_dir()


def test_application_recovery_folder_names_carry_their_date(tmp_path):
    from nodelang.application_server import ApplicationServer
    from nodelang.cell_secret_keys import MemorySigningKeyProvider
    provider = MemorySigningKeyProvider("archhub.local.relationship-authority", b"r" * 32)
    provider.add_key("archhub.local.court-attestation", b"c" * 32)
    server = ApplicationServer(universal_state_path=tmp_path / "graph.sqlite3", universal_key_provider=provider,
        enable_machine_transport=False, enable_universal_cloud_gateway=False, live_watch=False).start()
    try:
        recovery = server.conversation_content.backup_recovery(tmp_path / "backups",
            authentication_context=server.universal_registry.authorization.session.context(),
            timeout_seconds=60.0)
    finally:
        server.close()
    assert re.fullmatch(r"application-recovery-[0-9]{8}-[0-9a-f]{32}", recovery.name), recovery.name
    assert recovery.name.split("-")[2] == date.today().strftime("%Y%m%d")


def test_the_launcher_applies_retention_after_each_verified_backup():
    source = LAUNCHER.read_text(encoding="utf-8")
    assert 'server.close(recovery_directory=backup_dir' not in source
    assert '_prune_backups(' not in source
    assert 'arm_update(state_dir' in source


def test_retention_preserves_unrelated_directories_even_inside_backups(tmp_path):
    from nodelang.backup_retention import prune_backups
    old, new, unrelated = (tmp_path / name for name in ('old', 'new', '20200101-personal'))
    for path in (old, new, unrelated):
        path.mkdir()
    for path in (old, new):
        (path / 'graph.sqlite3').write_bytes(b'fixture backup')
    (unrelated / 'notes.txt').write_text('preserve this user file', encoding='utf-8')
    result = prune_backups(tmp_path, keep=new, keep_count=1)
    assert not old.exists() and result['kept'] == ['new']
    assert (unrelated / 'notes.txt').read_text(encoding='utf-8') == 'preserve this user file'


def test_unverified_migration_copy_cannot_prune_the_previous_backup(tmp_path, monkeypatch):
    import pytest
    from nodelang import persistence, backup_retention
    from nodelang.universal_cell import CellStore
    prior = tmp_path / 'backups' / '20200101-prior'
    prior.mkdir(parents=True)
    (prior / 'graph.sqlite3').write_bytes(b'previous verified fixture')
    monkeypatch.setattr(backup_retention, 'backup_policy', lambda *_: {'keep_count':1, 'max_bytes':1024**2})
    with CellStore(tmp_path / 'authority.sqlite3') as owner:
        revision = owner.revision
        monkeypatch.setattr(owner, 'backup_to', lambda target: Path(target).write_bytes(b'corrupt fixture copy'))
        with pytest.raises(ValueError, match='backup verification failed'):
            persistence._migration_backup(owner, {}, 'fixture-migration')
        assert owner.revision == revision
    assert (prior / 'graph.sqlite3').read_bytes() == b'previous verified fixture'


def test_final_close_refuses_new_growth_beside_an_armed_recovery_and_keeps_ownership(tmp_path, monkeypatch):
    import json
    import pytest
    from nodelang import application_recovery_files, backup_retention
    from nodelang.application_server import ApplicationServer
    from nodelang.cell_secret_keys import MemorySigningKeyProvider
    provider = MemorySigningKeyProvider('archhub.local.relationship-authority', b'r' * 32)
    provider.add_key('archhub.local.court-attestation', b'c' * 32)
    graph, backups = tmp_path / 'authority.sqlite3', tmp_path / 'backups'
    server = ApplicationServer(universal_state_path=graph, universal_key_provider=provider,
        enable_machine_transport=False, enable_universal_cloud_gateway=False, live_watch=False).start()
    protected = backups / 'armed-update'
    protected.mkdir(parents=True)
    protected_graph = protected / 'graph.sqlite3'
    with protected_graph.open('wb') as stream:
        stream.write(b'preserve-existing-recovery')
        stream.truncate(16 * 1024**2)
    marker = tmp_path / 'updates' / 'update-ready.json'
    marker.parent.mkdir()
    marker.write_text(json.dumps({'recovery': {'path': str(protected)}}), encoding='utf-8')
    copied = []
    monkeypatch.setattr(backup_retention, 'backup_policy', lambda *_:
        {'keep_count': 3, 'max_bytes': protected_graph.stat().st_size})
    monkeypatch.setattr(application_recovery_files, '_backup_sqlite', lambda *args: copied.append(args))
    try:
        with pytest.raises(ValueError, match='configured backup disk budget'):
            server.close(recovery_directory=backups,
                recovery_authentication_context=server.universal_registry.authorization.session.context(),
                recovery_timeout_seconds=60)
        assert not copied
        assert list(backups.iterdir()) == [protected]
        assert protected_graph.stat().st_size == 16 * 1024**2
        with protected_graph.open('rb') as stream:
            assert stream.read(len(b'preserve-existing-recovery')) == b'preserve-existing-recovery'
        assert server._close_completed is False
        assert server._runtime_fence_release is not None
        primary = server.universal_store.sqlite_storage()[0]
        assert primary.execute('PRAGMA main.locking_mode').fetchone()[0] == 'exclusive'
    finally:
        marker.unlink()
        server.close()
