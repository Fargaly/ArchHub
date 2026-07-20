from __future__ import annotations

import sys
from pathlib import Path


REPO = Path(__file__).resolve().parent.parent
NODE_COURTS = REPO / "personal-brain-mcp" / "node_courts"
if str(NODE_COURTS) not in sys.path:
    sys.path.insert(0, str(NODE_COURTS))

import run_all as node_court_suite  # noqa: E402


def test_universal_cell_node_court_suite_is_green():
    result = node_court_suite.run_all()
    green = {key: value for key, value in result.items() if key.startswith("C")}

    assert green
    assert all(value == "GREEN" for value in green.values())
    assert result["cells"] > 0
