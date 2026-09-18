"""Run the shipped Studio drag court in Node against the shipped client file."""
import shutil
import subprocess
from pathlib import Path


def test_studio_layout_save_sends_one_request_per_drag():
    node = shutil.which("node")
    assert node, "Node is required for the shipped Studio drag court"
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [node, "--test", "tests_replica/test_studio_layout_save_requests.cjs"],
        cwd=root, capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
