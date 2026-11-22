"""Connector archives are sourced from the release wheelhouse, never the build host's site."""
import importlib.metadata
import json
import os
from pathlib import Path
import re
import shutil
import site
import subprocess
import sys
import zipfile

import pytest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / '03.TOOLS/packaging'))
import pack_runtime  # noqa: E402


def test_release_packs_with_the_python_version_setup_supplies():
    yaml = pytest.importorskip('yaml')
    installer = (ROOT / '03.TOOLS/installer/ArchHub.iss').read_text(encoding='utf-8')
    version = re.search(r"PythonFile = 'python-([\d.]+)-amd64.exe'", installer)[1]
    workflow = yaml.safe_load((ROOT / '.github/workflows/release.yml').read_text(encoding='utf-8'))
    steps = {step.get('id'): step for step in workflow['jobs']['build']['steps']}
    assert steps['runtime_python']['with']['python-version'] == version
    assert steps['runtime_python']['with']['update-environment'] is False
    assert steps['runtime_python']['if'] == steps['installer']['if']
    assert 'steps.runtime_python.outputs.python-path' in steps['installer']['env']['RUNTIME_PYTHON_PATH']
    assert '-RuntimePythonPath $env:RUNTIME_PYTHON_PATH' in steps['installer']['run']


def test_wheelhouse_packing_excludes_host_packages_and_preserves_connector_import(tmp_path, monkeypatch):
    pytest.importorskip('mcp')
    pytest.importorskip('pip')
    distribution = importlib.metadata.distribution('mcp')
    wheelhouse = tmp_path / 'wheelhouse'
    wheelhouse.mkdir()
    # Repackage the test environment's real MCP Python files as an offline wheel fixture.
    metadata = f'mcp-{distribution.version}.dist-info'
    with zipfile.ZipFile(wheelhouse / f'mcp-{distribution.version}-py3-none-any.whl', 'w') as wheel:
        for file in distribution.files:
            name = file.as_posix()
            if (name.startswith(('mcp/', metadata + '/')) and '__pycache__' not in file.parts
                    and file.name != 'RECORD' and distribution.locate_file(file).is_file()):
                wheel.write(distribution.locate_file(file), name)
        wheel.writestr(metadata + '/RECORD', '')

    host_site = tmp_path / 'host' / 'site-packages'
    host_site.mkdir(parents=True)
    (host_site / 'host_only_fixture.py').write_text('ORIGIN = "host"', encoding='utf-8')
    monkeypatch.setattr(site, 'getsitepackages', lambda: [str(host_site)])
    monkeypatch.setenv('PYTHONPATH', str(host_site))
    monkeypatch.setenv('PIP_TARGET', str(host_site))
    monkeypatch.setattr(pack_runtime, 'pack_stdlib', lambda output: zipfile.ZipFile(output, 'w').close())
    assert pack_runtime.main(['--out', str(tmp_path / 'legacy'), '--site-packages', str(host_site)]) == 0
    with zipfile.ZipFile(tmp_path / 'legacy/site.zip') as archive:
        assert 'host_only_fixture.pyc' in archive.namelist()

    app = tmp_path / 'app'
    package = app / 'nodelang'
    package.mkdir(parents=True)
    source = ROOT / '01.APP/nodelang'
    shutil.copyfile(source / '__init__.py', package / '__init__.py')
    packed = app / 'packed'
    assert pack_runtime.main(['--out', str(packed), '--wheelhouse', str(wheelhouse)]) == 0
    stamp = packed / 'stamp.json'
    metadata = json.loads(stamp.read_text(encoding='utf-8'))
    assert metadata['packages'] == ['mcp']
    assert metadata['hexversion'] == sys.hexversion
    with zipfile.ZipFile(packed / 'site.zip') as archive:
        assert 'host_only_fixture.pyc' not in archive.namelist()
    assert not (host_site / 'mcp').exists()
    probe = '''
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import nodelang
nodelang.__path__.append(sys.argv[2])
from nodelang.native_agent_mcp import FastMCP
from mcp.server import fastmcp
assert FastMCP is fastmcp.FastMCP
archive = Path(sys.argv[1], 'packed/site.zip')
assert (archive in Path(fastmcp.__file__).parents) == (sys.argv[3] == 'packed'), fastmcp.__file__
assert (str(archive) in sys.path) == (sys.argv[3] == 'packed')
'''
    command = [sys.executable, '-I', '-B', '-c', probe, str(app), str(source)]
    env = {**os.environ, 'ARCHHUB_COORDINATION_VENDOR': 'fixture'}
    subprocess.run([*command, 'packed'], check=True, env=env)
    stamp.write_text(json.dumps({**metadata, 'hexversion': sys.hexversion ^ 0x100}), encoding='utf-8')
    subprocess.run([*command, 'disk'], check=True, env=env)
