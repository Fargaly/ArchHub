"""Node type registry.

Every node type (e.g. "llm.complete", "tool.revit_execute_csharp",
"control.foreach") registers an executor here. The executor is a callable:

    executor(node_config: dict, inputs: dict, ctx: ExecutionContext) -> dict

It returns a dict mapping output port names to values.

A node type also declares its IO contract — a NodeSpec — so the executor
and any UI know what ports exist for a given type.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from .graph import Port, PortType


@dataclass
class NodeSpec:
    type: str                                  # e.g. "llm.complete"
    category: str                              # "io" | "data" | "llm" | "tool" | "control" | "speckle"
    display_name: str
    description: str
    inputs: list[Port] = field(default_factory=list)
    outputs: list[Port] = field(default_factory=list)
    config_schema: dict = field(default_factory=dict)   # JSON Schema for `node.config`
    icon: str = ""                                       # short letter for UI


# Executor signature: takes (config, inputs_dict, ctx), returns outputs_dict
NodeExecutor = Callable[[dict, dict, "ExecutionContext"], dict]


_REGISTRY: dict[str, tuple[NodeSpec, NodeExecutor]] = {}


def register(spec: NodeSpec, executor: NodeExecutor) -> None:
    if spec.type in _REGISTRY:
        raise ValueError(f"Node type '{spec.type}' is already registered.")
    _REGISTRY[spec.type] = (spec, executor)


def get(type_name: str) -> Optional[tuple[NodeSpec, NodeExecutor]]:
    return _REGISTRY.get(type_name)


def all_specs() -> list[NodeSpec]:
    return [spec for spec, _ in _REGISTRY.values()]


def all_specs_by_category() -> dict[str, list[NodeSpec]]:
    out: dict[str, list[NodeSpec]] = {}
    for spec, _ in _REGISTRY.values():
        out.setdefault(spec.category, []).append(spec)
    return out
