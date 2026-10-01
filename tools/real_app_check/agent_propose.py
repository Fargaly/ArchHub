"""A run-local agent proposes one governed Work through the product's own native.work_propose.

Runs as a Job-owned helper under the run's environment (LOCALAPPDATA and state in the run folder), so
the agent session binds to THIS run's app through its own signed runtime descriptor; it never reads the
founder's descriptor or keys. Nothing is granted: a proposal is a Workshop message the founder decides.
argv: <code root> <runtime descriptor> <agent session id> <title>
"""
import json
import os
import sys

code_root, descriptor, session_id, title = sys.argv[1:5]
sys.path.insert(0, code_root)
from nodelang import native_agent_mcp  # noqa: E402
from nodelang.native_agent_session import NativeAgentSession  # noqa: E402

# The same scoped grant and CDE container the product's own proposal court proposes.
CONTAINER = {"container_id": "GM.nodes.cde-authority", "source_requirement": "court:proposals",
             "domain": "nodes", "tier": "T1", "suitability_status": "S0", "revision": "P01",
             "owner": "founder", "checker": "court", "gate_kind": "pytest",
             "gate_spec": {"path": "10.PRODUCT/13.NODE-LANGUAGE/tests_replica/test_cell_cde_authority.py"}}
GRANTS = [{"path": "10.PRODUCT/13.NODE-LANGUAGE/nodelang/cell_cde_authority.py", "scope": "exact",
           "operations": ["apply_patch"]}]

environment = dict(os.environ, CLAUDE_CODE_SESSION_ID=session_id)
owner = NativeAgentSession(environment=environment, descriptor_path=descriptor)
server = native_agent_mcp.build_server(session=owner)
tools = {tool.name: tool.fn for tool in server._tool_manager.list_tools()}
sent = tools["native.work_propose"](title=title, description="proposed by this run's own agent session",
                                    priority=100, purpose="general", inputs={}, requirements={},
                                    container=CONTAINER, write_grants=GRANTS)
print(json.dumps({"ok": True, "agent_session": owner.owner_status().get("agent_session"), **sent}), flush=True)
os._exit(0)          # the session's lease keeper is a thread; the helper's own Job ends anything left
