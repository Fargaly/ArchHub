"""ArchHub workflows package.

Phase 1: graph data model, executor, node registry, chat capture, library,
triggers. No canvas UI yet (phase 3).

Typical use:

    from workflows import Workflow, WorkflowExecutor, chat_to_workflow, save_workflow
    from workflows.nodes import register_tool_nodes

    register_tool_nodes()                            # one-time at app boot
    wf = chat_to_workflow(chat_window.history)
    save_workflow(wf)
    result = WorkflowExecutor(router, tool_engine, manager).run(wf, inputs={"prompt": "..."})
"""
from .graph import (
    Workflow, Node, Edge, Port, PortType, Trigger, SCHEMA_VERSION,
)
from .executor import WorkflowExecutor, ExecutionContext, ExecutionEvent, ExecutionResult
from .registry import NodeSpec, register, get, all_specs, all_specs_by_category
from .chat_to_workflow import chat_to_workflow
from .library import (
    save_workflow, load_workflow, list_workflows, get_workflow, delete_workflow,
    WORKFLOWS_DIR,
)

# Importing the nodes subpackage registers all built-in non-tool node types.
# Tool nodes are registered separately via register_tool_nodes() once
# tool_engine.TOOLS is available.
from . import nodes  # noqa: F401
# Importing the subgraph module registers `subgraph.user` + the internal
# `subgraph._seed` helper used during nested cooks.
from . import subgraph  # noqa: F401

__all__ = [
    "Workflow", "Node", "Edge", "Port", "PortType", "Trigger", "SCHEMA_VERSION",
    "WorkflowExecutor", "ExecutionContext", "ExecutionEvent", "ExecutionResult",
    "NodeSpec", "register", "get", "all_specs", "all_specs_by_category",
    "chat_to_workflow",
    "save_workflow", "load_workflow", "list_workflows", "get_workflow", "delete_workflow",
    "WORKFLOWS_DIR",
]
