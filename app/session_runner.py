"""Session runner — orchestrates StepKind runners over the session chain.

Two entry points:

  run_from_prompt(text, images, session, router, manager, on_event)
      Creates a USER_PROMPT + LLM_PLAN step, runs it, then runs all
      downstream steps that were created by the plan.

  rerun_dirty(session, router, manager, on_event)
      Finds the first DIRTY step in the chain and re-runs it plus all
      downstream steps.

Both functions are synchronous (called from a QThread worker). They emit
events via on_event so the UI can stream progress.

Event dict shape:
  {"type": "progress", "message": "..."}
  {"type": "step_started",  "step_id": "...", "label": "..."}
  {"type": "step_done",     "step_id": "...", "output": StepOutput}
  {"type": "step_error",    "step_id": "...", "error": "..."}
  {"type": "response",      "text": "..."}   # friendly text to show in chat
  {"type": "image",         "path": "..."}   # image to show in chat
  {"type": "done"}
"""
from __future__ import annotations

import uuid
from typing import Any, Callable, Optional

from session import (
    Session, ChainStep, StepKind, StepStatus, StepOutput,
    new_step,
)

EventFn = Callable[[dict], None]


def run_from_prompt(
    text: str,
    images: list[str],    # list of image file paths (pasted sketches)
    session: Session,
    router,
    manager,
    on_event: Optional[EventFn] = None,
) -> None:
    """Process a new user prompt through the full pipeline."""
    ev = on_event or (lambda _: None)

    # 1. Add a USER_PROMPT step (records what was asked)
    user_step = new_step(StepKind.USER_PROMPT, text[:80],
                         config={"prompt": text, "images": images})
    session.add_step(user_step)
    session.set_status(user_step, StepStatus.OK)
    if images:
        session.attach_output(user_step, StepOutput(kind="image", value=images[0]))

    # 2. Add an LLM_PLAN step
    plan_step = new_step(StepKind.LLM_PLAN, "Plan from prompt",
                         config={"prompt": text, "images": images})
    session.add_step(plan_step)

    # 3. Run the plan step
    ev({"type": "step_started", "step_id": plan_step.id, "label": plan_step.label})
    session.set_status(plan_step, StepStatus.RUNNING)

    import runners
    plan_runner = runners.get("llm.plan")
    if plan_runner is None:
        session.set_status(plan_step, StepStatus.ERROR, "No llm.plan runner registered")
        ev({"type": "step_error", "step_id": plan_step.id, "error": "No llm.plan runner"})
        ev({"type": "done"})
        return

    try:
        plan_output = plan_runner(
            plan_step, session, router, manager,
            on_progress=lambda msg: ev({"type": "progress", "message": msg})
        )
        session.set_status(plan_step, StepStatus.OK)
        session.attach_output(plan_step, plan_output)
        ev({"type": "step_done", "step_id": plan_step.id, "output": plan_output})

        # Emit the friendly response text
        if plan_output.metadata and plan_output.metadata.get("response"):
            ev({"type": "response", "text": plan_output.metadata["response"]})

    except Exception as ex:
        session.set_status(plan_step, StepStatus.ERROR, str(ex))
        ev({"type": "step_error", "step_id": plan_step.id, "error": str(ex)})
        ev({"type": "done"})
        return

    # 4. Run all PENDING steps that were added by the plan (downstream of plan_step)
    _run_pending_steps(session, router, manager, ev)
    ev({"type": "done"})


def rerun_dirty(
    session: Session,
    router,
    manager,
    on_event: Optional[EventFn] = None,
) -> None:
    """Re-run from the first DIRTY step onwards."""
    ev = on_event or (lambda _: None)

    # Find first dirty step
    first_dirty_idx = None
    for i, step in enumerate(session.chain):
        if step.status == StepStatus.DIRTY:
            first_dirty_idx = i
            break

    if first_dirty_idx is None:
        ev({"type": "done"})
        return

    # Re-run from that index onwards
    for step in session.chain[first_dirty_idx:]:
        if step.status not in (StepStatus.DIRTY, StepStatus.PENDING):
            continue
        _run_one_step(step, session, router, manager, ev)

    ev({"type": "done"})


# ---------------------------------------------------------------------------
def _run_pending_steps(session: Session, router, manager, ev: EventFn) -> None:
    """Run all PENDING steps in the chain (those added by plan)."""
    for step in session.chain:
        if step.status != StepStatus.PENDING:
            continue
        _run_one_step(step, session, router, manager, ev)


def _run_one_step(step: ChainStep, session: Session, router, manager,
                  ev: EventFn) -> None:
    """Run a single step, update its status, emit events."""
    import runners

    kind_str = step.kind.value
    runner = runners.get(kind_str)
    if runner is None:
        session.set_status(step, StepStatus.ERROR, f"No runner for {kind_str}")
        ev({"type": "step_error", "step_id": step.id,
            "error": f"No runner for {kind_str}"})
        return

    ev({"type": "step_started", "step_id": step.id, "label": step.label})
    session.set_status(step, StepStatus.RUNNING)

    try:
        output = runner(
            step, session, router, manager,
            on_progress=lambda msg: ev({"type": "progress", "message": msg})
        )
        session.set_status(step, StepStatus.OK)
        session.attach_output(step, output)
        ev({"type": "step_done", "step_id": step.id, "output": output})

        # Emit image to chat if this was an image output
        if output.kind == "image" and output.value:
            ev({"type": "image", "path": output.value})

    except Exception as ex:
        session.set_status(step, StepStatus.ERROR, str(ex))
        ev({"type": "step_error", "step_id": step.id, "error": str(ex)})
