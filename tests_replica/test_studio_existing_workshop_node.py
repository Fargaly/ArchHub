"""Court: the existing-Workshop Studio module passes its own Node test.

The Work completion court admits pytest gates only, so this wraps
tests_js/studio_existing_workshop.test.cjs as one pytest selector.
"""
from pathlib import Path
import shutil
import subprocess


def test_studio_existing_workshop_node():
    node = shutil.which("node")
    assert node, "Node is required for the existing-Workshop Studio court"
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [node, "--test", "tests_js/studio_existing_workshop.test.cjs"],
        cwd=root, capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
