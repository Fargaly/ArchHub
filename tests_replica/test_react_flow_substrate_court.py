"""Bounded renderer comparison court; React Flow is not graph authority."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
PROBE = ROOT / "tests_js" / "react_flow_performance_probe.mjs"


def test_react_flow_projects_250_nodes_and_500_relation_ids():
    completed = subprocess.run(
        ["node", str(PROBE)],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
        env={**os.environ, "NODE_ENV": "production"},
        timeout=90,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["nodeCount"] == 250
    assert result["edgeCount"] == 500
    assert result["selectedId"] == "court:node:249"
    assert result["selectionReconcileMs"] < 250
