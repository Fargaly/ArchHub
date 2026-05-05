"""Speckle pull runner.

Fetches the latest commit from a Speckle branch, downloads the root object,
and injects its `parameters` dict back into the live session.

Injection rules:
  - If a parameter already exists in the session, its value is updated and
    the step's upstream chain is marked dirty so dependent steps re-run.
  - If a parameter does NOT exist in the session, it is created as a STRING
    parameter (the LLM plan step may later refine its type if the user asks).
  - If a `geometry_ref` is present in the pulled object, it is stored as the
    session parameter `speckle_geometry_ref` (STRING / GEOMETRY).

Step config keys:
  project_id   — Speckle project/stream id (required; falls back to session param)
  branch       — branch / model name (default "archhub/main")

Emits session events on_parameter_added / on_parameter_changed for every
parameter touched, which will refresh the parameters sidebar in real time.
"""
from __future__ import annotations

from typing import Any

from session import ChainStep, Session, StepOutput, Parameter, ParamType

_DEFAULT_BRANCH = "archhub/main"

# Parameter types we try to infer from the pulled value
_INT_TYPES   = (int,)
_FLOAT_TYPES = (float,)
_BOOL_TYPES  = (bool,)


def run(step: ChainStep, session: Session, router, manager,
        on_progress=None) -> StepOutput:
    """Pull the latest Speckle commit into the session. Returns a StepOutput."""

    def progress(msg: str) -> None:
        if on_progress: on_progress(msg)

    project_id = step.config.get("project_id") or session.get("speckle_project_id")
    if not project_id:
        return StepOutput(
            kind="text",
            value="Speckle pull failed: no project_id. Set it in step config or "
                  "as session parameter 'speckle_project_id'.",
            metadata={"error": "missing_project_id"},
        )

    branch = step.config.get("branch", _DEFAULT_BRANCH)

    progress(f"Pulling from Speckle project {project_id} ← {branch}…")

    try:
        from speckle_client import SpeckleClient
        client = SpeckleClient()
        result = client.pull_parameters(project_id=project_id, branch=branch)
    except Exception as ex:
        return StepOutput(kind="text",
                          value=f"Speckle pull exception: {ex}",
                          metadata={"error": str(ex)})

    if result.get("status") != "ok":
        err = result.get("error", "unknown error")
        return StepOutput(kind="text",
                          value=f"Speckle pull failed: {err}",
                          metadata={"error": err})

    parameters: dict[str, Any] = result.get("parameters") or {}
    geometry_ref: str | None   = result.get("geometry_ref")
    commit_id  = result.get("commit_id", "")
    object_id  = result.get("object_id", "")

    # Inject parameters into session
    injected_new: list[str] = []
    injected_updated: list[str] = []

    for name, value in parameters.items():
        if name in session.parameters:
            dirty = session.update_parameter(name, value)
            if dirty:
                injected_updated.append(name)
            else:
                injected_updated.append(name)  # value set, no dirty (unchanged)
        else:
            param = _make_parameter(name, value)
            session.add_parameter(param)
            injected_new.append(name)

    # Inject geometry ref
    if geometry_ref:
        _upsert_param(session, "speckle_geometry_ref", geometry_ref,
                      ParamType.GEOMETRY, "Speckle geometry reference from last pull")
        injected_updated.append("speckle_geometry_ref")

    # Record commit / object ids
    _upsert_param(session, "speckle_version_id", commit_id,
                  ParamType.STRING, "Speckle version/commit id from last pull")
    _upsert_param(session, "speckle_object_id", object_id,
                  ParamType.STRING, "Speckle object id from last pull")

    progress("Pull complete.")

    n_new     = len(injected_new)
    n_updated = len(injected_updated)
    summary = (
        f"Pulled from Speckle.\n"
        f"Project: {project_id}\n"
        f"Branch:  {branch}\n"
        f"Commit:  {commit_id or '(unknown)'}\n"
        f"New parameters:     {n_new}  ({', '.join(injected_new[:5])}{'…' if n_new > 5 else ''})\n"
        f"Updated parameters: {n_updated}"
    )
    return StepOutput(
        kind="text",
        value=summary,
        metadata={
            "commit_id":       commit_id,
            "object_id":       object_id,
            "branch":          branch,
            "project_id":      project_id,
            "new_params":      injected_new,
            "updated_params":  injected_updated,
        },
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_parameter(name: str, value: Any) -> Parameter:
    """Infer a Parameter type from the pulled value."""
    label = name.replace("_", " ").title()
    if isinstance(value, bool):
        ptype, val = ParamType.BOOLEAN, bool(value)
    elif isinstance(value, int):
        ptype, val = ParamType.INTEGER, int(value)
    elif isinstance(value, float):
        ptype, val = ParamType.NUMBER, float(value)
    else:
        ptype, val = ParamType.STRING, str(value) if value is not None else ""

    return Parameter(
        name=name, label=label, type=ptype,
        value=val, default=val,
        description=f"Pulled from Speckle",
    )


def _upsert_param(session: Session, name: str, value: Any,
                  ptype: ParamType, description: str = "") -> None:
    """Create or update a parameter in the session."""
    if name in session.parameters:
        session.update_parameter(name, value)
    else:
        param = Parameter(
            name=name, label=name.replace("_", " ").title(),
            type=ptype, value=value, default=value,
            description=description,
        )
        session.add_parameter(param)
