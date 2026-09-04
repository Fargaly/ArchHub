#!/usr/bin/env python3
"""Antigravity PreInvocation adapter for Brain/Workshop context injection."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def _brainwrap_path() -> Path:
    return Path(__file__).resolve().with_name("brainwrap.py")


def _emit_empty() -> None:
    print("{}")


def main() -> int:
    raw = sys.stdin.read()
    brainwrap = _brainwrap_path()
    if not brainwrap.is_file():
        _emit_empty()
        return 0
    try:
        proc = subprocess.run(
            [sys.executable or "python", str(brainwrap), "context", "--vendor", "antigravity"],
            input=raw,
            text=True,
            capture_output=True,
            timeout=8,
        )
    except Exception:
        _emit_empty()
        return 0
    if proc.stderr:
        sys.stderr.write(proc.stderr)
    message = proc.stdout.strip()
    if not message:
        _emit_empty()
        return 0
    print(json.dumps({"injectSteps": [{"ephemeralMessage": message}]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
