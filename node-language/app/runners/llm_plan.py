"""LLM Plan runner.

Takes a user prompt and the current session state. Calls the LLM to:
1. Extract named parameters (width, height, roof_pitch, etc.)
2. Decide which pipeline steps to create (GEOMETRY_BUILD + RENDER + IMAGE_PROCESS)
3. Optionally generate initial Blender code

Returns a StepOutput with kind="json" and value = the plan dict.
Side-effects: adds parameters and downstream steps to the session.
"""
from __future__ import annotations

import json
import re
import uuid
from typing import Optional

from session import (
    ChainStep, Session, StepKind, StepOutput, StepStatus, Parameter, ParamType,
    length_param, angle_param, integer_param, enum_param, new_step,
)


PLAN_SYSTEM_PROMPT = """\
You are ArchHub's planning assistant. The user wants to create a 3D architectural model.

Your job is to extract parametric design intent and output a JSON plan. Respond ONLY with
valid JSON — no markdown fences, no explanation.

JSON schema:
{
  "parameters": [
    {
      "name": "snake_case_name",
      "label": "Human Label",
      "type": "length|angle|integer|number|boolean|string|enum|color",
      "value": <current_value>,
      "default": <same_as_value>,
      "min": <optional_number>,
      "max": <optional_number>,
      "step": <optional_number>,
      "unit": "m|mm|ft|°|null",
      "options": ["only for enum type"],
      "description": "one sentence"
    }
  ],
  "steps": [
    {"kind": "geometry.build", "label": "Build geometry in Blender"},
    {"kind": "render",         "label": "Render the model"},
    {"kind": "image.process",  "label": "Post-process render"}
  ],
  "response": "The friendly message to show the user explaining what you understood."
}

Rules:
- Extract ALL geometric parameters mentioned or implied. For a house: width, depth, storeys, roof_pitch, wall_height.
- Use metric (m) for lengths. Convert if user says feet.
- Always include geometry.build and render steps. Add image.process only if user mentions style/mood.
- If the user's prompt is purely conversational (no model intent), return parameters=[] and steps=[].
- Keep parameter names short: roof_pitch not roofPitchAngle.
"""


def run(step: ChainStep, session: Session, router, manager,
        on_progress=None) -> StepOutput:
    """Run the LLM_PLAN step. Populates session parameters + downstream steps."""
    def progress(msg: str) -> None:
        if on_progress: on_progress(msg)

    prompt = step.config.get("prompt", "")
    progress("Planning your design…")

    # Build parameter context from existing session
    existing_params = ""
    if session.parameters:
        lines = [f"  {p.name}={p.value} ({p.type.value})"
                 for p in session.parameters.values()]
        existing_params = "Existing parameters:\n" + "\n".join(lines) + "\n\n"

    user_content = f"{existing_params}User says: {prompt}"

    history = [
        {"role": "user", "content": user_content}
    ]

    # Use the fastest capable model for planning
    text = ""
    def on_chunk(t: str) -> None:
        nonlocal text
        text += t

    try:
        resp = router.complete(
            history,
            model="anthropic:claude-haiku-4-5-20251001",
            on_chunk=on_chunk,
            on_tool_invocation=lambda _inv: None,
        )
        text = resp.text if resp.text else text
    except Exception as ex:
        return StepOutput(kind="text", value=f"Planning failed: {ex}")

    # Parse JSON from response (strip any accidental markdown)
    plan = _parse_json(text)
    if plan is None:
        return StepOutput(
            kind="text",
            value=text,
            metadata={"raw": text, "parse_failed": True}
        )

    progress("Adding parameters…")

    # Add parameters to session
    introduced: list[str] = []
    for p_dict in plan.get("parameters") or []:
        pname = p_dict.get("name", "")
        if not pname:
            continue
        if pname in session.parameters:
            # Update value if changed
            new_val = p_dict.get("value")
            if new_val is not None:
                session.update_parameter(pname, new_val)
            continue

        param = _make_param(p_dict, step.id)
        session.add_parameter(param)
        introduced.append(pname)

    step.parameters_introduced = introduced

    # Add downstream steps
    progress("Building pipeline…")
    param_names = list(session.parameters.keys())
    for s_dict in plan.get("steps") or []:
        kind_str = s_dict.get("kind", "")
        label    = s_dict.get("label", kind_str)
        try:
            kind = StepKind(kind_str)
        except ValueError:
            continue
        chain_step = new_step(
            kind, label,
            parameters_used=param_names,
        )
        session.add_step(chain_step)

    response_text = plan.get("response", "Ready to build.")
    return StepOutput(
        kind="json",
        value=plan,
        metadata={"response": response_text, "introduced": introduced}
    )


# ---------------------------------------------------------------------------
def _parse_json(text: str) -> Optional[dict]:
    text = text.strip()
    # Strip markdown fences if present
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text.rstrip())
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Try to find a JSON object in the text
        m = re.search(r"\{[\s\S]+\}", text)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                pass
    return None


def _make_param(d: dict, step_id: str) -> Parameter:
    name  = d.get("name", f"param_{uuid.uuid4().hex[:4]}")
    label = d.get("label", name.replace("_", " ").title())
    ptype_str = d.get("type", "number")
    value = d.get("value", 0)
    default = d.get("default", value)
    description = d.get("description", "")
    unit = d.get("unit")
    options = d.get("options")

    # Map type string to ParamType
    type_map = {
        "length":  ParamType.LENGTH,
        "angle":   ParamType.ANGLE,
        "integer": ParamType.INTEGER,
        "number":  ParamType.NUMBER,
        "boolean": ParamType.BOOLEAN,
        "string":  ParamType.STRING,
        "enum":    ParamType.ENUM,
        "color":   ParamType.COLOR,
        "image":   ParamType.IMAGE,
    }
    ptype = type_map.get(ptype_str, ParamType.NUMBER)

    return Parameter(
        name=name, label=label, type=ptype,
        value=value, default=default,
        min=d.get("min"), max=d.get("max"), step=d.get("step"),
        unit=unit, options=options,
        description=description,
        introduced_by=step_id,
    )
