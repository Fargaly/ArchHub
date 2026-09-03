"""Serve desktop/agent governance as the visual node-language canvas.

This is not a generated report. It builds the governance policy into the
one-table node language and serves the existing CanvasServer over that session,
so Brain, hooks, running sessions, watchdog effects, and probes are visible as
nodes that pull live evidence.
"""
from __future__ import annotations

import argparse
import os
import sys
import webbrowser

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from nodelang import Store, validate_store  # noqa: E402
from nodelang.governance_policy import (  # noqa: E402
    DEFAULT_DESKTOP_COMMANDS,
    build_desktop_launch_policy,
)
from nodelang.serve_canvas import CanvasServer  # noqa: E402


def build(commands=DEFAULT_DESKTOP_COMMANDS):
    store = Store()
    policy = build_desktop_launch_policy(store, commands=commands)
    validate_store(store)
    return store, policy, policy["session"]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Serve ArchHub governance as node-language canvas."
    )
    parser.add_argument("--port", type=int, default=8479)
    parser.add_argument("--open", action="store_true")
    parser.add_argument("--commands", default=",".join(DEFAULT_DESKTOP_COMMANDS))
    args = parser.parse_args(argv)

    commands = [part.strip() for part in args.commands.split(",") if part.strip()]
    store, policy, root = build(commands=commands)
    server = CanvasServer(store, root, reg=None, port=args.port).start()
    print("GOVERNANCE CANVAS serving at", server.url, flush=True)
    print("nodes in the one table:", len(server.store.nodes), flush=True)
    print("root session:", root, flush=True)
    print("probes:", ", ".join(policy["probes"]), flush=True)
    if args.open:
        try:
            webbrowser.open(server.url)
        except Exception:
            pass
    try:
        import time
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        server.stop()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
