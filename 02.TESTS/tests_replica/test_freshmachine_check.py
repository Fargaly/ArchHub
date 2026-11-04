"""The installer court refuses a live Windows account before starting any child."""
import importlib.util
from pathlib import Path

import pytest


@pytest.fixture
def checker():
    root = Path(__file__).resolve().parents[2]
    source = root / '03.TOOLS/tools/fresh_machine_check.py'
    spec = importlib.util.spec_from_file_location('fresh_machine_check', source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_protected_account_cannot_launch_installer(checker, monkeypatch, tmp_path):
    def refuse():
        raise ValueError('protected account')
    monkeypatch.setattr(checker, 'require_disposable_account', refuse)
    def forbidden(*args, **kwargs):
        pytest.fail('installer launched before account safety check')
    monkeypatch.setattr(checker.subprocess, 'run', forbidden)
    with pytest.raises(ValueError, match='protected account'):
        checker.check(tmp_path / 'setup.exe', tmp_path)


def test_inventory_records_locations_without_exporting_matching_lines(checker, monkeypatch, tmp_path):
    source = tmp_path / '01.APP'
    source.mkdir()
    (tmp_path / '03.TOOLS/installer').mkdir(parents=True)
    (source / 'example.py').write_text('API_KEY = "never-export-this-value"\n', encoding='utf-8')
    monkeypatch.setattr(checker, 'ROOT', tmp_path)
    report = tmp_path / 'report.md'
    checker.inventory(report)
    text = report.read_text(encoding='utf-8')
    assert '01.APP/example.py:1' in text
    assert 'never-export-this-value' not in text
