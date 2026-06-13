"""ai.plan node — M4 foundation (AgDR-0021).

Wraps `llm.complete_with_tools` + persists each cook's tool-call
plan + final result under `<project_dir>/.archhub/plans/<plan_id>.json`.

Replay mode (`config.replay=True`) returns a cached record without
re-calling the LLM — same prompt + model → same plan deterministically.

The LIBRARY-FIRST gate (AgDR-0013) STILL fires because this executor
delegates to `llm.complete_with_tools` which the router gate-guards
before invocation.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

from ..graph import Port, PortType
from ..registry import NodeSpec, register


def _project_dir(config: dict) -> str:
    pd = (config or {}).get("project_dir")
    if pd:
        return str(pd)
    try:
        # Lazy import to avoid circulars.
        APP = Path(__file__).resolve().parents[2]
        if str(APP) not in sys.path:
            sys.path.insert(0, str(APP))
        from speckle_wire import default_project_dir
        return str(default_project_dir())
    except Exception:
        return str(Path.cwd())


def _lint_plan(text):
    try:
        import sys as _sys
        from pathlib import Path as _P
        _tools = str(_P(__file__).resolve().parents[3] / "tools")
        if _tools not in _sys.path:
            _sys.path.insert(0, _tools)
        import completion_gate as _cg
        defer = _cg.scan_deferral(text or "")
    except Exception:
        defer = []
    if defer:
        return {"action": "block", "deferral": defer,
                "reason": "plan defers work (" + ", ".join(defer)
                          + "); reject bare later — finish or tag "
                            "depends-on: / safety-gated:."}
    return {"action": "allow", "deferral": []}


def _ai_plan_executor(config: dict, inputs: dict, ctx) -> dict:
    config = config or {}
    inputs = inputs or {}
    prompt = (inputs.get("prompt") or config.get("prompt") or "").strip()
    model = (config.get("model") or "auto").strip()
    replay = bool(config.get("replay", False))
    allowed_tools_raw = config.get("allowed_tools")
    if isinstance(allowed_tools_raw, str):
        allowed_tools = [s.strip() for s in allowed_tools_raw.split(",")
                          if s.strip()]
    elif isinstance(allowed_tools_raw, list):
        allowed_tools = [str(s).strip() for s in allowed_tools_raw
                          if str(s).strip()]
    else:
        allowed_tools = []

    # Lazy import the history layer.
    try:
        APP = Path(__file__).resolve().parents[2]
        if str(APP) not in sys.path:
            sys.path.insert(0, str(APP))
        from plan_history import PlanHistory
    except Exception as ex:
        return {"plan": [], "result": "", "plan_id": "",
                "cached": False,
                "status": "error",
                "error": f"PlanHistory unavailable: {ex}"}

    history = PlanHistory(_project_dir(config))
    plan_id = PlanHistory.id_for(
        prompt=prompt, model=model,
        extra=",".join(sorted(allowed_tools)))

    if replay:
        cached = history.load(plan_id)
        if cached:
            return {
                "plan":    cached.get("plan", []),
                "result":  cached.get("result", ""),
                "plan_id": plan_id,
                "cached":  True,
                "status":  cached.get("status", "ok"),
                "error":   cached.get("error"),
            }

    # Fresh run — delegate to llm.complete_with_tools.
    # Resolve the executor via the registry so we pick up the
    # gate-guarded version that's already registered.
    try:
        from ..registry import get as _reg_get
        tup = _reg_get("llm.complete_with_tools")
    except Exception as ex:
        return {"plan": [], "result": "", "plan_id": plan_id,
                "cached": False,
                "status": "error",
                "error": f"llm.complete_with_tools unavailable: {ex}"}
    if not tup:
        return {"plan": [], "result": "", "plan_id": plan_id,
                "cached": False,
                "status": "error",
                "error": "llm.complete_with_tools not registered"}
    _spec, _ex = tup
    nested_cfg = {"model": model, "prompt": prompt}
    if allowed_tools:
        nested_cfg["allowed_tools"] = allowed_tools
    nested_inputs = {"prompt": prompt}
    nested_out = _ex(nested_cfg, nested_inputs, ctx)

    record = {
        "plan_id": plan_id,
        "prompt":  prompt,
        "model":   nested_out.get("model") or model,
        "plan":    nested_out.get("tool_invocations") or [],
        "result":  nested_out.get("text") or "",
        "status":  nested_out.get("status") or "ok",
        "error":   nested_out.get("error"),
        "ts":      int(time.time()),
    }
    record["completion"] = _lint_plan(record.get("result", ""))
    if record["completion"]["action"] == "block" and record.get("status") == "ok":
        record["status"] = "needs_rework"
    # Persist regardless of success/failure — audit needs the
    # failure trail too.
    history.save(record)
    return {
        "plan":    record["plan"],
        "result":  record["result"],
        "plan_id": plan_id,
        "cached":  False,
        "status":  record["status"],
        "error":   record["error"],
        "completion": record["completion"],
    }


register(
    NodeSpec(
        type="ai.plan",
        category="ai",
        display_name="AI Plan",
        description="Auditable + replayable Composer turn. Wraps "
                    "llm.complete_with_tools + persists the plan to "
                    "`.archhub/plans/<id>.json`. Same prompt + model "
                    "→ same plan_id; replay=True returns the cached "
                    "record without re-calling the LLM.",
        inputs=[Port(name="prompt", type=PortType.STRING, required=True)],
        outputs=[
            Port(name="plan",    type=PortType.LIST),
            Port(name="result",  type=PortType.STRING),
            Port(name="plan_id", type=PortType.STRING),
        ],
        config_schema={
            "model":         {"type": "string", "default": "auto"},
            "prompt":        {"type": "string"},
            "replay":        {"type": "boolean", "default": False,
                                "description": "When true, return the "
                                               "cached plan for the input "
                                               "hash if one exists."},
            "allowed_tools": {"type": "string", "default": "",
                                "description": "Comma-separated tool-name "
                                               "whitelist."},
            "project_dir":   {"type": "string",
                                "description": "Where to store .archhub/plans/. "
                                               "Defaults to default_project_dir."},
        },
        icon="✶",
    ),
    _ai_plan_executor,
)
