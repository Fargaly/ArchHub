"""Workflow executor.

Runs a Workflow in topological order. Each node's executor is invoked with:
  - its own `config`
  - a dict of resolved inputs (port_name -> value, from upstream edges or workflow inputs)
  - an ExecutionContext (router, tool engine, manager, plus mutable state)

Emits events through the optional `on_event` callback so a UI can stream
progress: node started, node finished, node failed, log line, final outputs.

Sequential v0. Independent branches run sequentially in topo order today;
parallel scheduling is a phase-2 upgrade once we have real workflows that
benefit from it.
"""
from __future__ import annotations

import time
import traceback
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from .graph import Workflow, Node, Edge
from .registry import get as get_node_registration


@dataclass
class ExecutionContext:
    """Services available to a node executor."""
    router: Any                                  # LLMRouter
    tool_engine: Any                             # ToolEngine
    manager: Any                                 # ConnectorManager
    workflow: Workflow
    workflow_inputs: dict = field(default_factory=dict)
    state: dict = field(default_factory=dict)    # node-id -> outputs dict
    log: Callable[[str], None] = lambda _msg: None


@dataclass
class ExecutionEvent:
    """Emitted to on_event callback as the run progresses."""
    type: str                                    # "started" | "node_started" | "node_finished"
                                                 # | "node_failed" | "log" | "finished" | "failed"
    node_id: Optional[str] = None
    node_type: Optional[str] = None
    detail: Any = None
    elapsed_ms: Optional[int] = None
    timestamp: float = field(default_factory=time.time)


@dataclass
class ExecutionResult:
    success: bool
    outputs: dict                                # workflow-level outputs (from output ports)
    node_outputs: dict                           # node-id -> port->value
    errors: list[str] = field(default_factory=list)
    elapsed_ms: int = 0


# ---------------------------------------------------------------------------
class WorkflowExecutor:
    def __init__(self, router, tool_engine, manager):
        self.router = router
        self.tool_engine = tool_engine
        self.manager = manager

    def run(
        self,
        workflow: Workflow,
        inputs: Optional[dict] = None,
        on_event: Optional[Callable[[ExecutionEvent], None]] = None,
    ) -> ExecutionResult:
        on_event = on_event or (lambda _ev: None)
        inputs = inputs or {}

        # Validate
        errs = workflow.validate()
        if errs:
            on_event(ExecutionEvent(type="failed", detail="; ".join(errs)))
            return ExecutionResult(success=False, outputs={}, node_outputs={}, errors=errs)

        order = workflow._topo_sort()
        ctx = ExecutionContext(
            router=self.router, tool_engine=self.tool_engine,
            manager=self.manager, workflow=workflow,
            workflow_inputs=inputs,
            log=lambda msg: on_event(ExecutionEvent(type="log", detail=msg)),
        )

        on_event(ExecutionEvent(type="started", detail=workflow.name))
        t0 = time.time()
        errors: list[str] = []

        for node_id in order:
            node = workflow.get_node(node_id)
            assert node is not None
            n_t0 = time.time()
            on_event(ExecutionEvent(type="node_started",
                                    node_id=node.id, node_type=node.type,
                                    detail=node.label or node.type))

            # Resolve inputs from upstream edges and workflow inputs
            resolved = self._resolve_inputs(workflow, node, ctx)

            registration = get_node_registration(node.type)
            if registration is None:
                msg = f"No executor registered for node type '{node.type}'."
                errors.append(msg)
                on_event(ExecutionEvent(type="node_failed", node_id=node.id,
                                        node_type=node.type, detail=msg,
                                        elapsed_ms=int((time.time() - n_t0) * 1000)))
                continue

            _spec, executor = registration
            try:
                outputs = executor(node.config or {}, resolved, ctx) or {}
            except Exception as ex:
                tb = traceback.format_exc()
                msg = f"{type(ex).__name__}: {ex}"
                errors.append(f"[{node.id}] {msg}")
                on_event(ExecutionEvent(type="node_failed", node_id=node.id,
                                        node_type=node.type, detail=msg,
                                        elapsed_ms=int((time.time() - n_t0) * 1000)))
                ctx.log(tb)
                # Fail-fast for v0; phase 2 adds error-tolerant branches
                break

            ctx.state[node.id] = outputs
            on_event(ExecutionEvent(type="node_finished", node_id=node.id,
                                    node_type=node.type, detail=outputs,
                                    elapsed_ms=int((time.time() - n_t0) * 1000)))

        # Collect workflow-level outputs by looking for `output.parameter` nodes
        wf_outputs: dict = {}
        for node in workflow.nodes:
            if node.type == "output.parameter":
                key = node.config.get("name", node.id)
                node_state = ctx.state.get(node.id, {})
                wf_outputs[key] = node_state.get("value")

        elapsed = int((time.time() - t0) * 1000)
        success = not errors
        on_event(ExecutionEvent(
            type="finished" if success else "failed",
            detail={"outputs": wf_outputs, "errors": errors},
            elapsed_ms=elapsed,
        ))
        return ExecutionResult(success=success, outputs=wf_outputs,
                               node_outputs=ctx.state, errors=errors,
                               elapsed_ms=elapsed)

    # ---- helpers -----------------------------------------------------------

    def _resolve_inputs(self, workflow: Workflow, node: Node,
                        ctx: ExecutionContext) -> dict:
        """For each input port on the node, resolve its value from upstream edges,
        falling back to default values and workflow inputs."""
        resolved: dict[str, Any] = {}

        for port in node.inputs:
            value = port.default

            # Find an edge feeding this port
            incoming = next(
                (e for e in workflow.edges_into(node.id) if e.dst_port == port.name),
                None,
            )
            if incoming is not None:
                up_outputs = ctx.state.get(incoming.src_node, {})
                if incoming.src_port in up_outputs:
                    value = up_outputs[incoming.src_port]

            resolved[port.name] = value

        # `input.parameter` nodes have no edges in; they pull from ctx.workflow_inputs
        if node.type == "input.parameter":
            key = node.config.get("name", node.id)
            if key in ctx.workflow_inputs:
                resolved["__bound_value__"] = ctx.workflow_inputs[key]

        return resolved
