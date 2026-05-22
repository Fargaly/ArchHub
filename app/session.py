"""Parametric session — the new core of ArchHub.

A Session is the live state of a working conversation. Where the old chat
history was a flat list of messages, a Session is a directed chain of
ChainStep objects, each producing typed Outputs and consuming named
Parameters from a shared Parameter pool.

When a Parameter changes, the Session marks every downstream ChainStep
dirty and re-runs them in order. Outputs are cached per (step_id, input_hash)
so an unchanged step that runs again returns instantly.

This module knows nothing about LLMs, Blender, or Qt. It is pure data and
state machinery. The runner (executed by chat_window) drives it; the UI
(parameters_panel) renders the live parameter pool; the chat hands the
session new prompts which become new ChainSteps.
"""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Callable, Optional


# ---------------------------------------------------------------------------
# Parameters — typed, named, live values that persist across the session.
# ---------------------------------------------------------------------------

class ParamType(str, Enum):
    NUMBER   = "number"     # generic numeric
    LENGTH   = "length"     # number with length unit (m, mm, ft)
    ANGLE    = "angle"      # number in degrees
    INTEGER  = "integer"
    BOOLEAN  = "boolean"
    STRING   = "string"
    ENUM     = "enum"        # pick one of a fixed set
    COLOR    = "color"       # hex string
    IMAGE    = "image"       # path or URL to an image
    GEOMETRY = "geometry"    # Speckle hash, glTF path, etc.
    POINT3   = "point3"      # [x, y, z]


@dataclass
class Parameter:
    name: str                                     # e.g. "roof_pitch" — unique within a session
    label: str                                    # human label for the sidebar
    type: ParamType
    value: Any
    default: Any = None
    min: Optional[float] = None
    max: Optional[float] = None
    step: Optional[float] = None                  # slider step
    unit: Optional[str] = None                    # "°", "m", "mm"
    options: Optional[list[str]] = None           # ENUM choices
    description: str = ""
    introduced_by: Optional[str] = None           # ChainStep.id that first created this parameter

    def to_dict(self) -> dict:
        d = asdict(self)
        d["type"] = self.type.value
        return d

    @staticmethod
    def from_dict(d: dict) -> "Parameter":
        return Parameter(
            name=d["name"], label=d.get("label", d["name"]),
            type=ParamType(d.get("type", "string")),
            value=d.get("value"), default=d.get("default"),
            min=d.get("min"), max=d.get("max"), step=d.get("step"),
            unit=d.get("unit"), options=d.get("options"),
            description=d.get("description", ""),
            introduced_by=d.get("introduced_by"),
        )


# ---------------------------------------------------------------------------
# Chain steps — each one is a node in the live DAG.
# ---------------------------------------------------------------------------

class StepStatus(str, Enum):
    PENDING  = "pending"     # never run
    RUNNING  = "running"     # currently executing
    OK       = "ok"          # ran successfully, output is fresh
    DIRTY    = "dirty"       # an upstream parameter changed; needs re-run
    ERROR    = "error"


class StepKind(str, Enum):
    """Coarse categories of work. Each kind has a registered runner."""
    USER_PROMPT     = "user.prompt"      # the user's chat message that triggered this step
    LLM_PLAN        = "llm.plan"          # LLM decides what parameters to introduce + which step kinds to chain
    GEOMETRY_BUILD  = "geometry.build"   # generate or modify model geometry
    RENDER          = "render"           # produce an image from geometry
    IMAGE_PROCESS   = "image.process"    # post-process a render
    SPECKLE_PUSH    = "speckle.push"
    SPECKLE_PULL    = "speckle.pull"


@dataclass
class StepOutput:
    kind: str                                    # "image", "geometry", "text", "json"
    value: Any                                   # the actual payload (path for image/geom, str for text)
    preview: Optional[str] = None                # optional file path or thumbnail
    metadata: dict = field(default_factory=dict)


@dataclass
class ChainStep:
    id: str
    kind: StepKind
    label: str                                   # short human description
    parameters_used: list[str] = field(default_factory=list)  # parameter names this step consumes
    parameters_introduced: list[str] = field(default_factory=list)  # parameter names this step first created
    config: dict = field(default_factory=dict)   # static config that's NOT a parameter (e.g. host_id, prompt text)
    status: StepStatus = StepStatus.PENDING
    output: Optional[StepOutput] = None
    error: Optional[str] = None
    started_at: Optional[float] = None
    finished_at: Optional[float] = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["kind"]   = self.kind.value
        d["status"] = self.status.value
        if self.output is not None:
            d["output"] = asdict(self.output)
        return d


# ---------------------------------------------------------------------------
# Session — the live state.
# ---------------------------------------------------------------------------

class Session:
    """Live parametric session. Owns the parameter pool and the chain.

    Notification hooks:
      - on_parameter_added(param)      — new parameter appeared in the pool
      - on_parameter_changed(param)    — value updated
      - on_step_added(step)            — new chain step
      - on_step_status(step)           — status moved (PENDING → RUNNING → OK/ERROR/DIRTY)
    """

    def __init__(self) -> None:
        self.id: str = uuid.uuid4().hex
        self.created_at: float = time.time()
        self.parameters: dict[str, Parameter] = {}
        self.chain: list[ChainStep] = []
        # ADR-003 Phase 2: dual-write a graph projection alongside the
        # legacy chain. `graph` carries the Workflow.to_dict() shape from
        # app.workflows.graph. Sessions without an explicit graph keep
        # `graph=None` and behave as before; legacy chats migrate by
        # wrapping their messages in a single `conversation.chat` node
        # at save time (see session_graph_migrator.wrap_legacy_as_graph).
        # We hold the dict shape (not the Workflow class) so session.py
        # stays import-cheap and UI/engine-agnostic.
        self.graph: Optional[dict] = None

        self.on_parameter_added:   Optional[Callable[[Parameter], None]] = None
        self.on_parameter_changed: Optional[Callable[[Parameter], None]] = None
        self.on_step_added:        Optional[Callable[[ChainStep], None]] = None
        self.on_step_status:       Optional[Callable[[ChainStep], None]] = None

    # ---- parameters ----

    def add_parameter(self, param: Parameter) -> Parameter:
        if param.name in self.parameters:
            return self.parameters[param.name]    # idempotent
        self.parameters[param.name] = param
        if self.on_parameter_added:
            try: self.on_parameter_added(param)
            except Exception: pass
        return param

    def update_parameter(self, name: str, value: Any) -> list[ChainStep]:
        """Change a parameter value. Returns the list of steps marked DIRTY."""
        if name not in self.parameters:
            return []
        param = self.parameters[name]
        if param.value == value:
            return []
        param.value = value
        if self.on_parameter_changed:
            try: self.on_parameter_changed(param)
            except Exception: pass
        return self._mark_downstream_dirty(name)

    def get(self, name: str, default: Any = None) -> Any:
        p = self.parameters.get(name)
        return p.value if p is not None else default

    # ---- chain ----

    def add_step(self, step: ChainStep) -> ChainStep:
        self.chain.append(step)
        if self.on_step_added:
            try: self.on_step_added(step)
            except Exception: pass
        return step

    def get_step(self, step_id: str) -> Optional[ChainStep]:
        return next((s for s in self.chain if s.id == step_id), None)

    def set_status(self, step: ChainStep, status: StepStatus,
                   error: Optional[str] = None) -> None:
        step.status = status
        if status == StepStatus.RUNNING:
            step.started_at = time.time()
        if status in (StepStatus.OK, StepStatus.ERROR):
            step.finished_at = time.time()
        if status == StepStatus.ERROR:
            step.error = error
        if self.on_step_status:
            try: self.on_step_status(step)
            except Exception: pass

    def attach_output(self, step: ChainStep, output: StepOutput) -> None:
        step.output = output
        # If this step introduced parameters, mark them as having an introducing step
        for pname in step.parameters_introduced:
            if pname in self.parameters and self.parameters[pname].introduced_by is None:
                self.parameters[pname].introduced_by = step.id

    # ---- dirty propagation ----

    def _mark_downstream_dirty(self, parameter_name: str) -> list[ChainStep]:
        """Mark every step that uses this parameter (or comes after such a step) as DIRTY.

        The chain is linear v0 — a step is downstream of another iff it comes
        later in `self.chain`. When the canvas lands and chains become real DAGs
        this becomes a topological walk, but for now position in list = order.
        """
        first_affected_index = None
        for i, step in enumerate(self.chain):
            if parameter_name in step.parameters_used:
                first_affected_index = i
                break
        if first_affected_index is None:
            return []
        affected: list[ChainStep] = []
        for step in self.chain[first_affected_index:]:
            if step.status == StepStatus.OK:
                self.set_status(step, StepStatus.DIRTY)
                affected.append(step)
        return affected

    # ---- serialization ----

    def to_dict(self) -> dict:
        d = {
            "id": self.id, "created_at": self.created_at,
            "parameters": [p.to_dict() for p in self.parameters.values()],
            "chain": [s.to_dict() for s in self.chain],
        }
        # ADR-003 Phase 2: dual-write graph projection when present.
        # Older session files without `graph` round-trip unchanged.
        if self.graph is not None:
            d["graph"] = self.graph
        return d

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, default=str)

    # ---- helpers ----

    def hash_inputs_for(self, step: ChainStep) -> str:
        """Stable hash of the parameters this step consumes, plus its config.
        Used by runners to short-circuit when nothing relevant changed."""
        h = hashlib.sha256()
        for name in sorted(step.parameters_used):
            p = self.parameters.get(name)
            h.update(name.encode())
            h.update(b"=")
            h.update(json.dumps(p.value if p else None, default=str, sort_keys=True).encode())
            h.update(b";")
        h.update(b"|config|")
        h.update(json.dumps(step.config, default=str, sort_keys=True).encode())
        return h.hexdigest()


# ---------------------------------------------------------------------------
# Helper factories — chat code calls these instead of building dataclasses by hand.
# ---------------------------------------------------------------------------

def new_step(kind: StepKind, label: str, *,
             config: Optional[dict] = None,
             parameters_used: Optional[list[str]] = None,
             parameters_introduced: Optional[list[str]] = None) -> ChainStep:
    return ChainStep(
        id=f"step_{uuid.uuid4().hex[:10]}",
        kind=kind, label=label,
        config=dict(config or {}),
        parameters_used=list(parameters_used or []),
        parameters_introduced=list(parameters_introduced or []),
    )


def length_param(name: str, label: str, value: float, *,
                 unit: str = "m", min: float = 0.0, max: float = 100.0,
                 step: float = 0.1, description: str = "") -> Parameter:
    return Parameter(name=name, label=label, type=ParamType.LENGTH,
                     value=value, default=value, min=min, max=max,
                     step=step, unit=unit, description=description)


def angle_param(name: str, label: str, value: float, *,
                min: float = -180.0, max: float = 180.0, step: float = 1.0,
                description: str = "") -> Parameter:
    return Parameter(name=name, label=label, type=ParamType.ANGLE,
                     value=value, default=value, min=min, max=max,
                     step=step, unit="°", description=description)


def integer_param(name: str, label: str, value: int, *,
                  min: int = 0, max: int = 100, step: int = 1,
                  description: str = "") -> Parameter:
    return Parameter(name=name, label=label, type=ParamType.INTEGER,
                     value=value, default=value, min=min, max=max,
                     step=step, description=description)


def enum_param(name: str, label: str, value: str, options: list[str],
               description: str = "") -> Parameter:
    return Parameter(name=name, label=label, type=ParamType.ENUM,
                     value=value, default=value, options=options,
                     description=description)
