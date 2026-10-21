"""Execute the rehearsal's host boundary without ever starting Setup/Sandbox."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import xml.etree.ElementTree as ET

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / '01.APP/installer' / 'rollback-rehearsal.ps1'
PWSH = str(Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe') if os.name == 'nt' else shutil.which('pwsh')


def invocation(tmp_path):
    releases = tmp_path / 'releases'
    releases.mkdir()
    old = releases / '0400.exe'
    new = releases / 'main.exe'
    old.write_bytes(b'dry-run only legacy; never executable')
    new.write_bytes(b'dry-run only main; never executable')
    output = tmp_path / 'result'
    args = [PWSH, '-NoProfile', '-File', str(SCRIPT), '-LegacyInstaller', str(old),
            '-MainInstaller', str(new), '-MainSha256', hashlib.sha256(new.read_bytes()).hexdigest(),
            '-MainBuildId', 'main-dryrun', '-OutputDirectory', str(output), '-DryRun']
    return args, output, old, new


def test_parse_and_dry_run_emit_read_only_releases_and_exact_hashes(tmp_path):
    args, output, old, new = invocation(tmp_path)
    run = subprocess.run(args, capture_output=True, text=True, check=False)
    assert run.returncode == 0, run.stdout + run.stderr
    report = json.loads((output / 'dry-run.json').read_text(encoding='utf-8-sig'))
    assert report['state'] == 'DRY-RUN'
    assert report['installers_started'] == 0
    assert report['real0400'] is False
    assert len(report['steps']) == 3
    assert report['legacy_sha256'].lower() == hashlib.sha256(old.read_bytes()).hexdigest()
    assert report['main_sha256'].lower() == hashlib.sha256(new.read_bytes()).hexdigest()
    xml = ET.parse(output / 'rollback.wsb').getroot()
    mappings = xml.findall('MappedFolders/MappedFolder')
    assert [row.findtext('ReadOnly') for row in mappings] == ['true', 'true', 'true', 'false']
    assert mappings[-1].findtext('HostFolder') == str(output / 'results')
    assert xml.findtext('ClipboardRedirection') == 'Disable'
    assert xml.findtext('Networking') == 'Disable'
    plan = json.loads((output / 'input/plan.json').read_text(encoding='utf-8-sig'))
    assert plan['minimum_guest_free_bytes'] == 25 * 1024**3 + plan['guest_working_bytes']
    assert '-Guest' in xml.findtext('LogonCommand/Command')
    assert (output / 'input' / 'rollback-rehearsal.ps1').read_bytes() == SCRIPT.read_bytes()
    assert not (output / 'results' / 'result.json').exists(), 'dry-run cannot produce acceptance'


def test_main_hash_mismatch_refuses_before_creating_output(tmp_path):
    args, output, _, _ = invocation(tmp_path)
    args[args.index('-MainSha256') + 1] = '0' * 64
    run = subprocess.run(args, capture_output=True, text=True, check=False)
    assert run.returncode != 0
    assert 'Main installer SHA-256 mismatch' in run.stderr
    assert not output.exists()


def test_previous_evidence_is_not_overwritten(tmp_path):
    args, output, _, _ = invocation(tmp_path)
    output.mkdir()
    prior = output / 'previous.txt'
    prior.write_text('keep this evidence')
    run = subprocess.run(args, capture_output=True, text=True, check=False)
    assert run.returncode != 0
    assert 'previous evidence is never overwritten' in run.stderr
    assert prior.read_text() == 'keep this evidence'


@pytest.mark.parametrize('spoof', [False, True])
def test_guest_mode_refuses_host_before_any_plan_read(spoof):
    environment = dict(os.environ)
    if spoof:
        environment.update(USERNAME='WDAGUtilityAccount', USERPROFILE='C:\\Users\\WDAGUtilityAccount')
    run = subprocess.run([PWSH, '-NoProfile', '-File', str(SCRIPT), '-Guest',
                          '-PlanPath', 'C:\\MainrelInput\\plan.json' if spoof else 'C:\\not-the-guest\\plan.json'],
                         capture_output=True, text=True, check=False, env=environment)
    assert run.returncode != 0
    assert 'requires the Windows Sandbox account and mapped plan' in run.stderr


def test_real_run_refuses_dummy_0400_before_sandbox_launch(tmp_path):
    args, output, _, _ = invocation(tmp_path)
    args.remove('-DryRun')
    run = subprocess.run(args, capture_output=True, text=True, check=False)
    assert run.returncode != 0
    assert 'not the real installed 0400 installer' in run.stderr
    assert not output.exists()


@pytest.mark.parametrize('filename', ['big-measurement.json', 'big-backup-only.json'])
def test_typed_measurement_values_preserve_original_observations(filename):
    root = SCRIPT.parents[1]
    # Original dbf86743 receipt values; no dependency on a lane's private Git objects.
    expected = ((227.70879669999704, 4.34308580000652, True) if filename == 'big-measurement.json'
                else (249.55643360002432, 0.7602302999584936, True))
    current = json.loads((root / '05.EVIDENCE' / 'mainrel' / filename).read_text())
    for name, observed in zip(('backup_seconds', 'migration_seconds', 'startup_within_30_seconds'), expected):
        assert current[name]['value'] == observed
        assert current[name]['mutability'] == 'measured'
        assert current[name]['type'] in {'number', 'boolean'}
    assert current['fixture_bytes'] == 8937168896
    assert current['candidates'] == 5
