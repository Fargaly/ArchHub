#!/usr/bin/env python3
"""Antigravity hook wrapper for the shared ArchHub CDE scope gate."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def _workspace_root() -> Path:
    raw = os.environ.get("ARCHHUB_WORKSPACE_ROOT", "").strip()
    if raw:
        return Path(raw)
    here = Path(__file__).resolve()
    for candidate in (here.parent, *here.parents):
        if (candidate / "00.GOVERNANCE" / "hooks" / "agent_scope_gate.py").is_file():
            return candidate
    return Path.home() / "00.ARCHUB"


def _gate_path() -> Path:
    return _workspace_root() / "00.GOVERNANCE" / "hooks" / "agent_scope_gate.py"


def main() -> int:
    raw = sys.stdin.read()
    gate = _gate_path()
    if not gate.is_file():
        print(json.dumps({
            "decision": "deny",
            "reason": (
                "ArchHub scope gate unavailable: cannot locate "
                "00.GOVERNANCE/hooks/agent_scope_gate.py"
            ),
        }))
        return 0
    proc = subprocess.run(
        [sys.executable or "python", str(gate), "--vendor", "antigravity"],
        input=raw,
        text=True,
        capture_output=True,
    )
    if proc.stderr:
        sys.stderr.write(proc.stderr)
    if proc.stdout.strip():
        sys.stdout.write(proc.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
