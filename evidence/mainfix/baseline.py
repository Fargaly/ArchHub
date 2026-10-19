"""Run the unchanged courts against one ce671c2e source extraction, then remove it."""
import importlib.util
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(root))
import nodelang
import pytest

directory = root / 'tmp-base'
directory.mkdir(exist_ok=True)
path = directory / 'persistence.py'
try:
    path.write_bytes(subprocess.check_output(['git', 'show', 'ce671c2e:nodelang/persistence.py'], cwd=root))
    spec = importlib.util.spec_from_file_location('nodelang.persistence', path)
    module = importlib.util.module_from_spec(spec)
    sys.modules['nodelang.persistence'] = module
    nodelang.persistence = module
    spec.loader.exec_module(module)
    raise SystemExit(pytest.main(['-q', '-p', 'no:cacheprovider', '--basetemp', sys.argv[1],
        'tests_replica/test_mainfix.py']))
finally:
    path.unlink(missing_ok=True)
    if not any(directory.iterdir()):
        directory.rmdir()
