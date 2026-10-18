"""Controlled free-space counters only for this lane's disposable court roots."""
import os
from pathlib import Path
import shutil
import pytest

@pytest.fixture(autouse=True)
def isolated_backup_disk_counter(monkeypatch):
    from nodelang import application_recovery_files as files
    original = shutil.disk_usage
    sandbox = Path(os.environ['TEMP']).resolve()
    def usage(path):
        value = original(path)
        return value._replace(free=100 * 1024**3) if Path(path).resolve().is_relative_to(sandbox) else value
    monkeypatch.setattr(files.shutil, 'disk_usage', usage)
    monkeypatch.setattr(files, '_fixed_backup_drives', lambda: [])
