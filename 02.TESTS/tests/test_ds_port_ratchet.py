"""The ratchet CLI accepts held counts and rejects growth in either DS metric.

DS-PORT's separate Studio court requires this lane's counts to drop against b16;
the reusable ratchet remains a non-growth gate after its baseline is refreshed.
"""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest


RATCHET = Path(__file__).resolve().parents[2] / "03.TOOLS/tools" / "ratchet.py"
SPEC = importlib.util.spec_from_file_location("ds_port_ratchet", RATCHET)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


@pytest.mark.parametrize("change, expected_code, verdict", [
    ("held", 0, "RATCHET PASS"),
    ("dropped", 0, "RATCHET PASS"),
    ("local_button_helpers", 1, "RATCHET FAIL: local_button_helpers"),
    ("inline_styles", 1, "RATCHET FAIL: inline_styles"),
])
def test_ratchet_compare_preserves_non_growth_contract(tmp_path, change, expected_code, verdict):
    studio = tmp_path / "nodelang" / "studio"
    studio.mkdir(parents=True)
    (studio / "fixture.jsx").write_text(
        'const fixtureBtn = () => ({color: "red"});\n'
        'const fixture = <div style={{color: "red"}} />;\n',
        encoding="utf-8",
    )
    counts = MODULE.measure(tmp_path)
    assert counts["local_button_helpers"] == 1
    assert counts["inline_styles"] == 1
    baseline = dict(counts)
    if change == "dropped":
        baseline["local_button_helpers"] += 1
        baseline["inline_styles"] += 1
    elif change != "held":
        baseline[change] -= 1
    baseline_path = tmp_path / "ratchet.json"
    baseline_path.write_text(json.dumps({"counts": baseline}), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(RATCHET), "compare", str(tmp_path), str(baseline_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == expected_code, result.stdout + result.stderr
    assert result.stdout.rstrip().endswith(verdict), result.stdout
    if change == "held":
        assert "| local_button_helpers | 1 | 1 | held |" in result.stdout
        assert "| inline_styles | 1 | 1 | held |" in result.stdout
