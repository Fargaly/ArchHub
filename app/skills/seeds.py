"""Starter skills shipped with ArchHub.

On first launch (or whenever the user's library is missing them) we materialise
a small set of vetted Skills so the matcher has something useful to find. Each
seed is built from primitives — input.parameter, data.template, llm.complete_with_tools,
output.parameter — wired into a four-node chain:

    prompt ──► template (skill-specific framing) ──► LLM (with tools) ──► answer

The template node injects the Skill's role and goals so the LLM stays on
task. The `allowed_tools` whitelist on the LLM node restricts the tool palette
to the connectors this Skill actually needs.

Idempotent: each seed has a stable id; if already present in the library we
skip it. Users who edit a seed keep their changes — we never overwrite.
"""
from __future__ import annotations

import uuid

from workflows.graph import Workflow, Node, Edge, Port, PortType, Trigger

from .library import list_skills, save_skill
from .metadata import SkillMeta, SCOPE_USER


# ---------------------------------------------------------------------------
def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def _build_chain(
    *,
    workflow_id: str,
    name: str,
    description: str,
    framing_template: str,
    allowed_tools: list[str],
    model: str = "auto",
) -> Workflow:
    """Build the four-node prompt → template → LLM → output chain."""
    wf = Workflow(id=workflow_id, name=name, description=description,
                  triggers=[Trigger(id=_id("trigger"), type="manual")])

    input_node = Node(
        id=_id("input"), type="input.parameter", label="Prompt",
        config={"name": "prompt", "type": "string",
                "description": "What the architect typed in chat.",
                "default": ""},
        outputs=[Port(name="value", type=PortType.STRING)],
    )
    wf.add_node(input_node)
    wf.inputs.append(Port(name="prompt", type=PortType.STRING,
                          description="User's natural-language request",
                          required=True))

    template_node = Node(
        id=_id("tmpl"), type="data.template", label="Skill framing",
        config={"template": framing_template},
        inputs=[Port(name="var1", type=PortType.STRING)],
        outputs=[Port(name="text", type=PortType.STRING)],
    )
    wf.add_node(template_node)
    wf.add_edge(Edge(id=_id("edge"), src_node=input_node.id, src_port="value",
                     dst_node=template_node.id, dst_port="var1"))

    llm_node = Node(
        id=_id("llm"), type="llm.complete_with_tools", label="Reasoning",
        config={"model": model, "allowed_tools": allowed_tools},
        inputs=[Port(name="prompt", type=PortType.STRING, required=True)],
        outputs=[
            Port(name="text",             type=PortType.STRING),
            Port(name="tool_invocations", type=PortType.LIST),
            Port(name="model",            type=PortType.STRING),
        ],
    )
    wf.add_node(llm_node)
    wf.add_edge(Edge(id=_id("edge"), src_node=template_node.id, src_port="text",
                     dst_node=llm_node.id, dst_port="prompt"))

    output_node = Node(
        id=_id("output"), type="output.parameter", label="Answer",
        config={"name": "answer"},
        inputs=[Port(name="value", type=PortType.STRING, required=True)],
        outputs=[Port(name="value", type=PortType.STRING)],
    )
    wf.add_node(output_node)
    wf.add_edge(Edge(id=_id("edge"), src_node=llm_node.id, src_port="text",
                     dst_node=output_node.id, dst_port="value"))
    wf.outputs.append(Port(name="answer", type=PortType.STRING,
                           description="Final assistant text"))
    return wf


# ---------------------------------------------------------------------------
# Seed catalogue. Each entry: (stable_id, factory) so we can re-seed without
# duplicates after the user clears their library.
SEED_DIMENSION_WALLS_ID    = "seed-dimension-walls-v1"
SEED_ROOM_TAGS_ID          = "seed-room-tags-v1"
SEED_PUSH_TO_SPECKLE_ID    = "seed-push-to-speckle-v1"


def _seed_dimension_walls() -> tuple[Workflow, SkillMeta]:
    wf = _build_chain(
        workflow_id=SEED_DIMENSION_WALLS_ID,
        name="Dimension walls in active view",
        description=(
            "Add Linear dimensions to every wall visible in the currently "
            "active Revit view, using the project's primary linear dimension type."
        ),
        framing_template=(
            "You are running the ArchHub skill 'Dimension walls in active view'. "
            "GOAL: place Linear dimensions on all walls visible in the active "
            "Revit view, wrapped in a single Revit Transaction. \n"
            "Procedure:\n"
            "  1. Call revit_info to confirm a document is open and to read the active view.\n"
            "  2. Call revit_execute_csharp with C# that enumerates Walls in the active view, "
            "uses the project's primary GetDefaultElementTypeId(ElementTypeGroup.LinearDimensionType), "
            "and creates Dimension elements aligned to each wall's location curve.\n"
            "  3. Wrap the geometry edits in a single Transaction named 'ArchHub: Dimension walls'.\n"
            "  4. Be defensive: skip walls without a LocationCurve, log how many were skipped.\n"
            "  5. Return a short summary: number of walls dimensioned, number skipped, view name.\n\n"
            "User request: {var1}"
        ),
        allowed_tools=["revit_info", "revit_execute_csharp"],
    )
    meta = SkillMeta(
        intent="Auto-dimension every wall in the active Revit view.",
        keywords=[
            "dimension", "dimensions", "dim", "annotate", "wall", "walls",
            "auto-dimension", "linear dimension",
        ],
        when_to_use=(
            "User asks to add dimensions to walls in the current Revit view "
            "or wants to annotate wall geometry."
        ),
        examples=[
            {"prompt": "Dimension all the walls in the active view",
             "expected_outcome": "Linear dimensions appear on every visible wall."},
            {"prompt": "Auto-dim my walls",
             "expected_outcome": "Same as above."},
        ],
        tags=["revit", "annotation"],
        requires=["revit"],
        author="ArchHub",
        scope=SCOPE_USER,
    )
    return wf, meta


def _seed_room_tags() -> tuple[Workflow, SkillMeta]:
    wf = _build_chain(
        workflow_id=SEED_ROOM_TAGS_ID,
        name="Tag every room in active view",
        description=(
            "Place a Room Tag at the centre of each Room visible in the "
            "active Revit floor plan view."
        ),
        framing_template=(
            "You are running the ArchHub skill 'Tag every room in active view'. "
            "GOAL: place a Room Tag at the location point of each Room visible "
            "in the active view. \n"
            "Procedure:\n"
            "  1. Call revit_info; confirm the active view is a FloorPlan.\n"
            "  2. Call revit_execute_csharp: collect Rooms whose Level matches "
            "the view's GenLevel, build a Reference per room, and call "
            "doc.Create.NewRoomTag(...) using the project's default RoomTagType.\n"
            "  3. Wrap edits in a Transaction named 'ArchHub: Tag rooms'.\n"
            "  4. Skip Rooms with Area == 0 (unplaced); count and report skipped.\n"
            "  5. Return: number tagged, number skipped, level name.\n\n"
            "User request: {var1}"
        ),
        allowed_tools=["revit_info", "revit_execute_csharp"],
    )
    meta = SkillMeta(
        intent="Tag every Room in the active Revit floor plan with the default Room Tag.",
        keywords=[
            "tag", "tags", "room", "rooms", "annotate", "label", "room-tag",
        ],
        when_to_use=(
            "User asks to add room tags or labels to the rooms in their "
            "active Revit floor plan view."
        ),
        examples=[
            {"prompt": "Tag all rooms on this level",
             "expected_outcome": "Each room receives a Room Tag at its centre."},
            {"prompt": "Add room labels to the active view",
             "expected_outcome": "Same as above."},
        ],
        tags=["revit", "annotation"],
        requires=["revit"],
        author="ArchHub",
        scope=SCOPE_USER,
    )
    return wf, meta


def _seed_push_to_speckle() -> tuple[Workflow, SkillMeta]:
    wf = _build_chain(
        workflow_id=SEED_PUSH_TO_SPECKLE_ID,
        name="Push current model to Speckle",
        description=(
            "Capture the active Revit document state and push it to a Speckle "
            "stream as a new commit."
        ),
        framing_template=(
            "You are running the ArchHub skill 'Push current model to Speckle'. "
            "GOAL: serialize the active Revit document and create a Speckle commit. \n"
            "Procedure:\n"
            "  1. Call revit_info; capture document title.\n"
            "  2. Call speckle_list_projects; pick the project whose name best matches "
            "the document title, or ask the user if none matches.\n"
            "  3. Use revit_execute_csharp to collect a structured snapshot "
            "(walls, levels, rooms — element ids + parameters) into a JSON object.\n"
            "  4. Call speckle_get_project to confirm branch existence; default branch 'main'.\n"
            "  5. Report: project name, branch, commit id (when push tools become available).\n"
            "If a push tool is not in the active toolset, return the prepared snapshot text "
            "and tell the user to enable Speckle push in the Connectors panel.\n\n"
            "User request: {var1}"
        ),
        allowed_tools=[
            "revit_info", "revit_execute_csharp",
            "speckle_list_projects", "speckle_get_project",
        ],
    )
    meta = SkillMeta(
        intent="Push the active Revit document to Speckle as a new commit.",
        keywords=[
            "push", "speckle", "commit", "sync", "publish", "share", "upload",
        ],
        when_to_use=(
            "User wants to send the current Revit model to Speckle for sharing, "
            "coordination, or to make it visible to other tools."
        ),
        examples=[
            {"prompt": "Push this model to Speckle",
             "expected_outcome": "A new Speckle commit containing the document snapshot."},
            {"prompt": "Sync to Speckle",
             "expected_outcome": "Same as above."},
        ],
        tags=["revit", "speckle"],
        requires=["revit", "speckle"],
        author="ArchHub",
        scope=SCOPE_USER,
    )
    return wf, meta


# ---------------------------------------------------------------------------
SEED_FACTORIES = (
    _seed_dimension_walls,
    _seed_room_tags,
    _seed_push_to_speckle,
)


def ensure_starter_skills() -> list[str]:
    """Materialise any starter skill missing from the library. Idempotent.

    Returns a list of skill ids that were freshly seeded this call.
    """
    existing_ids = {s["id"] for s in list_skills()}
    seeded: list[str] = []
    for factory in SEED_FACTORIES:
        wf, meta = factory()
        if wf.id in existing_ids:
            continue
        save_skill(wf, meta)
        seeded.append(wf.id)
    return seeded
