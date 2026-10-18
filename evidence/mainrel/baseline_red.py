"""Reproduce two guard failures using only the original two module sources."""
from pathlib import Path
import importlib.util
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
BASE = 'd89a50fd2304ea4cbda75e1313c08ed187404f2f'
target = ROOT / 'tmp-base'
target.mkdir(exist_ok=True)
owned = []
try:
    import nodelang
    for leaf in ('application_update_recovery', 'application_machine_transport'):
        output = target / (leaf + '.py')
        if output.exists():
            raise RuntimeError('baseline slice already exists; refusing replacement')
        output.write_bytes(subprocess.check_output(['git', 'show', f'{BASE}:nodelang/{leaf}.py'], cwd=ROOT))
        owned.append(output)
        spec = importlib.util.spec_from_file_location('nodelang.' + leaf, output)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        setattr(nodelang, leaf, module)
        spec.loader.exec_module(module)
    import pytest
    result = pytest.main(['-q', '-p', 'no:cacheprovider', '--tb=short',
        'tests_replica/test_mainrel_update.py::test_arm_without_app_copy_preserves_drift_refusal',
        'tests_replica/test_application_machine_transport.py::test_baboom_context_transport_accepts_bounded_founder_approval_count_and_rejects_bad_values'])
finally:
    for output in owned:
        output.unlink()
raise SystemExit(result)
