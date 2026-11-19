"""F17: no copy follows the retired installer preference to another drive.

backup-location.json "auto" once sent 40 GB to E:/ArchHub-backups and created
D:/ArchHub-backups on the System Reserved partition. The one remaining writer
(the legacy credential archive) now stays in the app state folder.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / '01.APP'))

from app import secrets_store  # noqa: E402


def _state(tmp_path, monkeypatch):
    profile = tmp_path / 'profile'
    state = profile / 'ArchHub'
    state.mkdir(parents=True)
    monkeypatch.setattr(secrets_store, 'APP_DIR', state)
    monkeypatch.setattr(secrets_store, 'SECRETS_FILE', state / 'secrets.dat')
    monkeypatch.setattr(secrets_store, 'os_store_refused', lambda: False)
    return profile, state


@pytest.mark.skipif(os.name != 'nt', reason='the legacy archive is Windows-only')
def test_legacy_archive_stays_in_the_app_folder_not_the_old_backup_drive(tmp_path, monkeypatch):
    profile, state = _state(tmp_path, monkeypatch)
    # The retired installer pick: a per-profile folder on another "drive".
    identity = hashlib.sha256(str(profile.resolve()).casefold().encode('utf-8')).hexdigest()
    old = tmp_path / 'other-drive' / 'ArchHub-backups' / ('profile-' + identity)
    (state / 'backup-location.json').write_text(json.dumps(
        {'location': 'auto', 'directory': str(old), 'managed_directories': []}), encoding='utf-8')
    raw = b'{"openai": "legacy-plaintext-fixture"}'
    (state / 'secrets.dat').write_bytes(raw)

    secrets_store.archive_legacy_credentials()

    assert not (tmp_path / 'other-drive').exists(), 'nothing is written to the old backup location'
    written = sorted(p.name for p in (state / 'backups').iterdir())
    digest = hashlib.sha256(raw).hexdigest()
    assert written == ['secrets-legacy-' + digest + '.dat', 'secrets-legacy-' + digest + '.sha256']
    assert (state / 'backups' / written[0]).read_bytes() == raw
    assert sum(p.stat().st_size for p in (state / 'backups').iterdir()) < 4096, 'one small archive, never a multi-GB copy'
    assert not (state / 'secrets.dat').exists(), 'the legacy file moved into the archive'


@pytest.mark.skipif(os.name != 'nt', reason='junctions are Windows-only')
def test_a_linked_backup_folder_is_refused(tmp_path, monkeypatch):
    _profile, state = _state(tmp_path, monkeypatch)
    elsewhere = tmp_path / 'other-drive'
    elsewhere.mkdir()
    link = state / 'backups'
    made = subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(elsewhere)],
                          capture_output=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if made.returncode:
        pytest.skip('junctions unavailable here')
    try:
        with pytest.raises(ValueError, match='link'):
            secrets_store._local_backup_directory()
    finally:
        os.rmdir(link)  # removes the junction itself, never its target
    assert elsewhere.is_dir()
