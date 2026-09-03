"""Step runners -- one per StepKind."""
from __future__ import annotations
from typing import Callable, Optional, Any

from session import ChainStep, Session, StepOutput

ProgressFn = Callable[[str], None]
RunnerFn   = Callable[[ChainStep, Session, Any, Any, Optional[ProgressFn]], StepOutput]

_REGISTRY: dict[str, RunnerFn] = {}


def register(kind: str, fn: RunnerFn) -> None:
    _REGISTRY[kind] = fn


def get(kind: str) -> Optional[RunnerFn]:
    return _REGISTRY.get(kind)


from .llm_plan       import run as _llm_plan_run
from .geometry_build import run as _geometry_run
from .render_runner  import run as _render_run
from .image_process  import run as _image_process_run
from .speckle_push   import run as _speckle_push_run
from .speckle_pull   import run as _speckle_pull_run

register("llm.plan",       _llm_plan_run)
register("geometry.build", _geometry_run)
register("render",         _render_run)
register("image.process",  _image_process_run)
register("speckle.push",   _speckle_push_run)
register("speckle.pull",   _speckle_pull_run)
