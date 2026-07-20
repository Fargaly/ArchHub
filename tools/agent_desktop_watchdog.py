#!/usr/bin/env python
"""ArchHub governed desktop session auditor.

Normal Windows app launches can bypass shell/profile shims. This watchdog is
the user-level visibility layer: audit desktop agent processes and log the
result. A founder-initiated ``--apply`` run may migrate an ungoverned primary
GUI app through brainwrap, but automatic startup is deliberately audit-only so
background governance never terminates a live session.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

if __package__ is None:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

import governed_sessions as gs  # noqa: E402


def _log_path() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    if base:
        return Path(base) / "ArchHub" / "governed-desktop" / "watchdog.jsonl"
    return Path.home() / ".archhub" / "governed-desktop" / "watchdog.jsonl"


def _append_log(event: dict) -> None:
    try:
        path = _log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, sort_keys=True) + "\n")
    except Exception:
        pass


def run_once(*, apply: bool) -> dict:
    status = gs.summarize_running_sessions(gs.audit_running_sessions())
    actions = gs.desktop_watchdog_plan(status)
    results = gs.apply_desktop_watchdog_actions(actions, dry_run=not apply)
    event = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "apply": apply,
        "current_sessions_total": status.get("current_sessions_total", 0),
        "current_sessions_governed": status.get("current_sessions_governed", 0),
        "current_sessions_need_restart": status.get("current_sessions_need_restart", 0),
        "planned": len(actions),
        "results": results,
    }
    _append_log(event)
    return event


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ArchHub governed desktop watchdog")
    parser.add_argument("--interval-sec", type=float, default=30.0)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args(argv)

    while True:
        run_once(apply=args.apply)
        if args.once:
            return 0
        time.sleep(max(1.0, args.interval_sec))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
