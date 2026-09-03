"""Headless workflow runner.

Usage:
    python -m run_workflow <workflow.json|workflow_id> [--input key=value]...

Loads the workflow, runs it through WorkflowExecutor, prints events to stdout
and final outputs as JSON. No UI — suitable for scheduled jobs, CI, scripts.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from llm_router import LLMRouter
from manager import ConnectorManager
from tool_engine import ToolEngine
from workflows import (
    WorkflowExecutor, ExecutionEvent, Workflow, get_workflow, load_workflow,
)
from workflows.nodes import register_tool_nodes


def parse_inputs(pairs: list[str]) -> dict:
    out: dict = {}
    for p in pairs or []:
        if "=" not in p:
            raise SystemExit(f"Bad --input '{p}'. Expected key=value.")
        k, v = p.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Run an ArchHub workflow headless.")
    ap.add_argument("target", help="Path to a workflow JSON file OR a workflow id.")
    ap.add_argument("--input", "-i", action="append", default=[],
                    help="key=value input pairs (repeatable).")
    ap.add_argument("--quiet", action="store_true", help="Suppress per-node events.")
    args = ap.parse_args()

    # Resolve workflow
    target = Path(args.target)
    if target.exists():
        wf = load_workflow(target)
    else:
        wf = get_workflow(args.target)
        if wf is None:
            print(f"No workflow at path or id '{args.target}'.", file=sys.stderr)
            return 2

    # Boot core services
    manager = ConnectorManager()
    manager.refresh()
    tools = ToolEngine(manager)
    router = LLMRouter(tools)
    register_tool_nodes()

    inputs = parse_inputs(args.input)

    def on_event(ev: ExecutionEvent) -> None:
        if args.quiet and ev.type in ("node_started", "node_finished", "log"):
            return
        line = f"[{ev.type:14}] "
        if ev.node_id:
            line += f"{ev.node_id} ({ev.node_type})  "
        if ev.elapsed_ms is not None:
            line += f"{ev.elapsed_ms} ms  "
        if ev.detail is not None:
            line += repr(ev.detail)[:200]
        print(line, file=sys.stderr)

    executor = WorkflowExecutor(router, tools, manager)
    result = executor.run(wf, inputs=inputs, on_event=on_event)

    print(json.dumps({
        "success": result.success,
        "elapsed_ms": result.elapsed_ms,
        "outputs": result.outputs,
        "errors": result.errors,
    }, indent=2, default=str))
    return 0 if result.success else 1


if __name__ == "__main__":
    sys.exit(main())
