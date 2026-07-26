"""The governance layer must be visible on the real node-language canvas."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nodelang import validate_store  # noqa: E402
from nodelang.graph_api import level_view  # noqa: E402

import serve_governance  # noqa: E402


def test_governance_surface_builds_a_live_node_language_session():
    store, policy, root = serve_governance.build(commands=("codex", "claude"))

    assert root == policy["session"]
    assert validate_store(store) is True

    level = level_view(store, root)
    titles = {node["title"] for node in level["nodes"]}
    assert "Desktop app: codex" in titles
    assert "Desktop app: claude" in titles
    assert "Probe: brain-health" in titles
    assert "Probe: hook-coverage" in titles
    assert "Probe: process-ancestry-governed" in titles
    assert "Probe: normal-app-watchdog" in titles

    probe_values = [
        node["value"]
        for node in level["nodes"]
        if node["title"].startswith("Probe: ")
    ]
    assert probe_values
    assert all(value["kind"] == "governance" for value in probe_values)
    assert all(value["check"] for value in probe_values)
