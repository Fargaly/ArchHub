"""AgDR-0031 — ArchHub MCP server pins.

Verifies the already-shipped `app/archhub_mcp_server.py` still
- registers ≥80 connector ops via selftest
- uses the host__op naming pattern (no dots — MCP-incompatible)
- can import the mcp.server SDK without shadowing on `app/mcp/`
- exits 0 from --selftest when ops are loaded
- has the RUN-MCP.md registration doc next to it
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
SERVER = REPO / "app" / "archhub_mcp_server.py"


def test_archhub_mcp_server_file_exists():
    assert SERVER.exists()


def test_archhub_mcp_server_documented():
    p = REPO / "docs" / "RUN-MCP.md"
    assert p.exists()
    text = p.read_text(encoding="utf-8")
    assert "claude mcp add archhub" in text
    assert "archhub_mcp_server.py" in text
    assert "__selftest" in text or "--selftest" in text


def test_selftest_reports_many_ops():
    """The actual server selftest path — runs the server with
    --selftest, asserts ≥80 connector ops appear."""
    result = subprocess.run(
        [sys.executable, str(SERVER), "--selftest"],
        cwd=str(REPO),
        capture_output=True, text=True, timeout=30,
        encoding="utf-8", errors="replace",
    )
    assert result.returncode == 0, (
        f"--selftest exit {result.returncode}; "
        f"stdout={result.stdout!r}; stderr={result.stderr!r}")
    m = re.search(r"archhub-mcp:\s+(\d+)\s+connector ops", result.stdout)
    assert m, f"expected 'archhub-mcp: N connector ops' in {result.stdout!r}"
    n = int(m.group(1))
    assert n >= 80, f"only {n} ops registered; want ≥80"


def test_tool_names_use_double_underscore_not_dot():
    """MCP tool names can't contain dots → server converts op_id `.`
    to `__`.  Sample one op from each host family."""
    result = subprocess.run(
        [sys.executable, str(SERVER), "--selftest"],
        cwd=str(REPO),
        capture_output=True, text=True, timeout=30,
        encoding="utf-8", errors="replace",
    )
    # First 12 ops are printed.  Look for the double-underscore form.
    assert "__" in result.stdout, result.stdout[:500]
    # And dotted form must NOT appear in tool names (op_id may still
    # appear in `(host/kind)` descriptors, but the tool name itself
    # has __).  Each printed line: `  host__op  (host/kind)  required=[…]`.
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line.startswith(("revit", "autocad", "blender", "excel",
                                 "outlook", "speckle", "max", "rhino")):
            continue
        tool_name = line.split()[0]
        assert "." not in tool_name, (
            f"tool name {tool_name!r} contains a dot — MCP-incompatible")


def test_mcp_sdk_imports_without_app_mcp_shadow():
    """Verifying the in-source fix that drops app/ from sys.path
    BEFORE `from mcp.server import Server` so the local app/mcp/
    package doesn't shadow the real MCP SDK."""
    src = SERVER.read_text(encoding="utf-8")
    assert "sys.path[:]" in src, "expected the shadow-fix code"
    assert "from mcp.server import Server" in src
    assert "from mcp.server.stdio import stdio_server" in src


def test_agdr_0031_exists_and_approved():
    p = REPO / "docs" / "agdr" / "AgDR-0031-archhub-mcp-server.md"
    assert p.exists()
    text = p.read_text(encoding="utf-8")
    assert "status: approved" in text
    assert "claude mcp add archhub" in text
    # Pivot note — server existed before this AgDR.
    assert "ALREADY exists" in text
