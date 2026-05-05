"""Speckle push runner.

Serialises the current session's Parameter pool (and optionally a geometry
reference from the last GEOMETRY_BUILD step) into a Speckle object, uploads it
to the configured Speckle project, and creates a commit on the target branch.

After a successful push the following session parameters are created/updated:

  speckle_version_id   (STRING) — the commit id returned by Speckle
  speckle_object_id    (STRING) — SHA256 hash of the uploaded object

Step config keys (all optional):
  project_id   — Speckle project/stream id (required; error if missing)
  branch       — branch / model name (default "archhub/main")
  message      — commit message (default "ArchHub push")
"""
from __future__ import annotations

import json
from typing import Any, Optional

from session import ChainStep, Session, StepOutput, Parameter, ParamType

_DEFAULT_BRANCH = "archhub/main"


def run(step: ChainStep, session: Session, router, manager,
        on_progress=None) -> StepOutput:
    """Push session parameters to Speckle. Returns a StepOutput with kind="text"."""

    def progress(msg: str) -> None:
        if on_progress: on_progress(msg)

    project_id = step.config.get("project_id") or session.get("speckle_project_id")
    if not project_id:
        return StepOutput(
            kind="text",
            value="Speckle push failed: no project_id. Set it in step config or "
                  "as session parameter 'speckle_project_id'.",
            metadata={"error": "missing_project_id"},
        )

    branch  = step.config.get("branch", _DEFAULT_BRANCH)
    message = step.config.get("message", "ArchHub push")

    # Collect all session parameters as a plain dict
    params_snapshot: dict[str, Any] = {
        name: p.value for name, p in session.parameters.items()
    }

    # Grab geometry ref from most recent GEOMETRY_BUILD step
    geometry_ref: Optional[str] = _find_geometry_ref(session)

    progress(f"Pushing parameters to Speckle project {project_id} → {branch}…")

    try:
        from speckle_client import SpeckleClient
        client = SpeckleClient()
        result = client.push_parameters(
            project_id=project_id,
            branch=branch,
            parameters=params_snapshot,
            geometry_ref=geometry_ref,
            message=message,
        )
    except Exception as ex:
        return StepOutput(kind="text",
                          value=f"Speckle push exception: {ex}",
                          metadata={"error": str(ex)})

    if result.get("status") != "ok":
        err = result.get("error", "unknown error")
        return StepOutput(kind="text",
                          value=f"Speckle push failed: {err}",
                          metadata={"error": err})

    commit_id = result.get("commit_id", "")
    object_id = result.get("object_id", "")

    # Store commit + object ids back into the session
    _upsert_string_param(session, "speckle_version_id", commit_id,
                         "Speckle version/commit id from last push")
    _upsert_string_param(session, "speckle_object_id", object_id,
                         "Speckle object id from last push")

    progress("Push complete.")

    summary = (
        f"Pushed {len(params_snapshot)} parameters to Speckle.\n"
        f"Project: {project_id}\n"
        f"Branch:  {branch}\n"
        f"Commit:  {commit_id or '(unknown)'}\n"
        f"Object:  {object_id}"
    )
    return StepOutput(
        kind="text",
        value=summary,
        metadata={
            "commit_id":  commit_id,
            "object_id":  object_id,
            "branch":     branch,
            "project_id": project_id,
            "param_count": len(params_snapshot),
        },
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_geometry_ref(session: Session) -> Optional[str]:
    """Walk the chain backwards for the most recent GEOMETRY_BUILD output."""
    from session import StepKind
    for step in reversed(session.chain):
        if step.kind == StepKind.GEOMETRY_BUILD and step.output is not None:
            v = step.output.value
            if isinstance(v, str):
                return v
            if isinstance(v, dict):
                return v.get("hash") or v.get("path") or json.dumps(v)
    return None


def _upsert_string_param(session: Session, name: str, value: str,
                         description: str = "") -> None:
    """Create or update a STRING parameter in the session."""
    if name in session.parameters:
        session.update_parameter(name, value)
    else:
        param = Parameter(
            name=name, label=name.replace("_", " ").title(),
            type=ParamType.STRING, value=value, default=value,
            description=description,
        )
        session.add_parameter(param)
