"""Every agent's wiring (hooks + MCP servers) must launch under every shell.

Runs tools/agent_wiring_court.py on the founder's workstation, where the agent
configs live; skipped where there are none (CI checkouts)."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
CONFIGS = (Path.home() / ".claude" / "settings.json", Path.home() / ".claude.json")


@pytest.mark.skipif(os.name != "nt" or not all(p.exists() for p in CONFIGS), reason="agent configs live on the Windows workstation")
def test_every_hook_and_mcp_server_launches_under_every_shell():
    proc = subprocess.run([sys.executable, str(REPO / "tools" / "agent_wiring_court.py")], capture_output=True, text=True, timeout=900)
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-500:]
    assert "FAIL" not in proc.stdout
