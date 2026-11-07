"""The installer must stage a self-contained preflight, including lazy imports."""
import importlib.util
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    'preflight_imports', ROOT / '03.TOOLS/packaging/preflight_imports.py')
preflight = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(preflight)


def test_generated_extraction_imports_every_preflight_entry_in_isolation(tmp_path):
    generated = tmp_path / 'includes'
    files = preflight.generate(ROOT / '01.APP', generated)
    assert Path('nodelang/user_paths.py') in files
    assert Path('nodelang/runtime_credentials.py') in files
    staged = tmp_path / 'mainrel-connectors'
    (staged / 'nodelang').mkdir(parents=True)
    (staged / 'nodelang/__init__.py').write_text('', encoding='utf-8')
    # Reconstruct from the actual Inno artifacts, rather than copying a second list.
    sources = dict((name, Path(source)) for source, name in re.findall(
        r'Source: "([^"]+)"; DestName: "([^"]+)";',
        (generated / 'preflight-files.iss').read_text(encoding='utf-8')))
    code = (generated / 'preflight-code.iss').read_text(encoding='utf-8')
    copies = re.findall(r"FileCopy\(ExpandConstant\('\{tmp\}\\([^']+)'\), ConnectorTemp \+ '\\([^']+)'", code)
    assert len(copies) == len(files) == len(sources)
    for archived, relative in copies:
        destination = staged / Path(relative.replace('\\', '/'))
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(sources[archived], destination)
    script = '''
import importlib, pathlib, sys
sys.path.insert(0, sys.argv[1])
for name in sys.argv[2:]:
    module = importlib.import_module(name)
    assert pathlib.Path(module.__file__).is_relative_to(sys.argv[1]), module.__file__
from nodelang.runtime_credentials import protect_current_user_data, unprotect_current_user_data
payload = b'preflight fixture data'
encrypted = protect_current_user_data(payload, purpose='preflight-import-court')
assert encrypted != payload
assert unprotect_current_user_data(encrypted, purpose='preflight-import-court') == payload
print('isolated preflight imports passed')
'''
    result = subprocess.run([sys.executable, '-I', '-B', '-c', script,
                             str(staged), *preflight.ENTRIES],
                            cwd=tmp_path, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'isolated preflight imports passed' in result.stdout


def test_closure_tracks_new_lazy_transitive_and_package_imports(tmp_path):
    package = tmp_path / 'nodelang'
    nested = package / 'nested'
    nested.mkdir(parents=True)
    (package / '__init__.py').write_text('raise RuntimeError("must remain a stub")')
    (package / 'entry.py').write_text('def lazy():\n from .nested import child\n')
    (nested / '__init__.py').write_text('from .. import initializer_dependency\n')
    (nested / 'child.py').write_text('import nodelang.transitive\n')
    (package / 'transitive.py').write_text('from . import entry\n')
    (package / 'initializer_dependency.py').write_text('')
    assert preflight.import_closure(tmp_path, ['nodelang.entry']) == sorted(map(Path, (
        'nodelang/entry.py', 'nodelang/nested/__init__.py', 'nodelang/nested/child.py',
        'nodelang/transitive.py', 'nodelang/initializer_dependency.py')))


def test_missing_entry_refuses_generation(tmp_path):
    with pytest.raises(ValueError, match='Missing preflight entry modules'):
        preflight.generate(tmp_path, tmp_path / 'output')
    assert not (tmp_path / 'output').exists()


def test_generated_inno_includes_compile(tmp_path):
    compiler = Path(os.environ.get('ProgramFiles(x86)', 'C:/Program Files (x86)')) / 'Inno Setup 6/ISCC.exe'
    if not compiler.is_file():
        pytest.skip('Inno Setup compiler is unavailable')
    preflight.generate(ROOT / '01.APP', tmp_path)
    harness = tmp_path / 'preflight.iss'
    harness.write_text(r'''
[Setup]
AppName=Preflight import court
AppVersion=1
DefaultDirName={tmp}\\preflight-court
PrivilegesRequired=lowest
Uninstallable=no
CreateAppDir=no
Compression=none
OutputDir=.
[Files]
#include PreflightFilesPath
[Code]
procedure StagePreflight(ConnectorTemp: String);
begin
#include PreflightCodePath
end;
''', encoding='utf-8')
    result = subprocess.run([str(compiler), '/Q',
                            '/DPreflightFilesPath=' + str(tmp_path / 'preflight-files.iss'),
                            '/DPreflightCodePath=' + str(tmp_path / 'preflight-code.iss'),
                            str(harness)], cwd=tmp_path,
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
