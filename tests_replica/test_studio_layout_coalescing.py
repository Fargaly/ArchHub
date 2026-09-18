"""Run the shipped Studio coalescing court in Node against the shipped client."""
import shutil
import subprocess
from pathlib import Path


def test_a_burst_of_drags_is_one_layout_write():
    node = shutil.which("node")
    assert node, "Node is required for the shipped Studio coalescing court"
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [node, "--test", "tests_js/studio_layout_coalescing.test.cjs"],
        cwd=root, capture_output=True, text=True, timeout=300,
    )
    assert result.returncode == 0, result.stdout + result.stderr