"""The Python court runs the rendered rail and task-face click court."""
from pathlib import Path
import subprocess


def test_rendered_raildoors():
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        ["node", "--test", str(root / "02.TESTS/tests_js/raildoors.test.cjs")],
        cwd=root, capture_output=True, text=True, encoding="utf-8", timeout=180,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    print(result.stdout)
    assert result.returncode == 0, result.stdout + result.stderr
