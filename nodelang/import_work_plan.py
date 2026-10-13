"""Import plan JSON rows as native Work proposals.

This CLI attaches to the installed app through the same native session path as
the MCP server. It posts unbound proposals only; the founder still binds them.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .native_agent_mcp import build_server
from .native_agent_session import NativeAgentSession


def _default_container(plan_path: Path) -> dict[str, object]:
    return {
        "container_id": "GM.nodes.cde-authority",
        "source_requirement": "plan-import:" + plan_path.name,
        "domain": "nodes",
        "tier": "T1",
        "suitability_status": "S0",
        "revision": "P01",
        "owner": "founder",
        "checker": "court",
        "gate_kind": "pytest",
        "gate_spec": {"path": "10.PRODUCT/13.NODE-LANGUAGE/tests_replica/test_agent_work_proposals.py"},
    }


def _default_grants(path: Path) -> list[dict[str, object]]:
    workspace = Path(os.environ.get("ARCHHUB_WORKSPACE_ROOT", r"C:\Users\fargaly\00.ARCHUB"))
    try:
        root = path.parent.resolve().relative_to(workspace.resolve()).as_posix()
    except ValueError:
        root = path.parent.as_posix()
    return [{"path": root, "scope": "descendants", "operations": ["apply_patch"]}]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Import plan JSON rows as unbound Work proposals")
    parser.add_argument("plan_json", type=Path)
    args = parser.parse_args(argv)
    rows = json.loads(args.plan_json.read_text(encoding="utf-8"))
    owner = NativeAgentSession(environment=os.environ)
    server = build_server(session=owner)
    tools = {tool.name: tool.fn for tool in server._tool_manager.list_tools()}
    result = tools["native.work_plan_import"](
        rows=rows,
        container=_default_container(args.plan_json),
        write_grants=_default_grants(args.plan_json),
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
