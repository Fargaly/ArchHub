"""Production-pipeline seed Skills — sketch all the way to deliverables.

The competitive brief flagged that "sketch to mass" is table stakes once
GPT-4V-level vision is universal. To stay ahead the product has to take
the architect from a hand sketch through to *production-ready* Revit
output: mass, project setup, walls, openings, annotations, and sheets.

These seeds give the chat skill matcher concrete entry points for each
stage of that pipeline, plus a master `sketch-to-production` skill that
chains every stage end-to-end inside a single workflow graph.

Each stage is an `llm.complete_with_tools` node with:
  - A focused framing prompt that tells the model exactly which
    Revit/Blender APIs to use, which Transactions to wrap, and which
    safety checks to make.
  - An `allowed_tools` whitelist so the model can't reach for unrelated
    connectors mid-stage.

The actual code is generated fresh per project by whichever LLM the
router picks — Claude for Revit C#, qwen2.5-coder when local. The
Skill carries the *intent and constraints*, not the implementation.
That's the moat: even when foundation models get smarter at Revit, the
Skills layer captures the firm's accumulated practice. Better models
make Skills more valuable, not less.
"""
from __future__ import annotations

import uuid

from workflows.graph import Workflow, Node, Edge, Port, PortType, Trigger

from .library import save_skill, list_skills
from .metadata import SkillMeta, SCOPE_USER
from .seeds import _build_chain    # reuses the input → template → llm → output chain


# ---------------------------------------------------------------------------
def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


# Stable IDs — let ensure_starter_skills idempotently re-seed without dupes.
SEED_EXTRACT_MASS_ID         = "seed-extract-mass-from-sketch-v1"
SEED_SETUP_REVIT_PROJECT_ID  = "seed-setup-revit-project-v1"
SEED_MASS_TO_WALLS_ID        = "seed-mass-to-walls-v1"
SEED_PLACE_OPENINGS_ID       = "seed-place-openings-v1"
SEED_GENERATE_SHEETS_ID      = "seed-generate-production-sheets-v1"
SEED_SKETCH_TO_PRODUCTION_ID = "seed-sketch-to-production-v1"


# ---------------------------------------------------------------------------
def _seed_extract_mass() -> tuple[Workflow, SkillMeta]:
    wf = _build_chain(
        workflow_id=SEED_EXTRACT_MASS_ID,
        name="Extract mass from sketch",
        description=(
            "Read an attached sketch, extract building parameters "
            "(width, depth, storeys, roof type), and build a parametric "
            "mass in Blender."
        ),
        framing_template=(
            "You are running the ArchHub skill 'Extract mass from sketch'. "
            "GOAL: take the user's attached sketch image, infer architectural "
            "parameters, and create the corresponding mass geometry in Blender.\n"
            "Procedure:\n"
            "  1. Read the sketch carefully. Identify: footprint shape, "
            "approximate width × depth in metres, number of storeys, roof "
            "type (flat / gabled / hipped / shed / butterfly), pitch if any, "
            "any setbacks or projections.\n"
            "  2. Pick sensible defaults when something isn't visible: "
            "storey height = 3.0 m; roof pitch = 30° if gabled; doors and "
            "windows are NOT placed at this stage.\n"
            "  3. Call blender_execute_python with code that:\n"
            "       - clears the default cube\n"
            "       - extrudes the footprint to (storeys × 3.0 m)\n"
            "       - adds the roof matching the inferred type\n"
            "       - names the parent collection 'Mass_Sketch'\n"
            "  4. Return a one-line summary that lists every parameter you "
            "inferred plus the rough confidence (high / medium / low). "
            "This becomes input for the next stage of the pipeline.\n\n"
            "User request: {var1}"
        ),
        allowed_tools=["blender_ping", "blender_execute_python"],
    )
    meta = SkillMeta(
        intent="Read a sketch image and build the corresponding mass in Blender.",
        keywords=[
            "sketch", "mass", "massing", "extract", "parse", "image",
            "build", "interpret", "model", "blender", "from-sketch",
        ],
        when_to_use=(
            "User attaches a sketch or screenshot and asks to build the "
            "depicted building as a 3D mass."
        ),
        examples=[
            {"prompt": "Build this in 3D, ~6m wide, gabled",
             "expected_outcome": "Parametric mass appears in Blender."},
            {"prompt": "Make a mass from this sketch",
             "expected_outcome": "Same as above with parameters inferred."},
        ],
        tags=["blender", "vision", "mass", "concept"],
        requires=["blender"],
        author="ArchHub",
        scope=SCOPE_USER,
    )
    return wf, meta


def _seed_setup_revit_project() -> tuple[Workflow, SkillMeta]:
    wf = _build_chain(
        workflow_id=SEED_SETUP_REVIT_PROJECT_ID,
        name="Set up Revit project",
        description=(
            "Initialise a Revit project for production: levels at standard "
            "heights, primary grids, project units (mm), default wall + "
            "door + window types, and a starter sheet."
        ),
        framing_template=(
            "You are running the ArchHub skill 'Set up Revit project'. "
            "GOAL: take a freshly-opened Revit document and bring it to a "
            "production-ready starting state.\n"
            "Procedure:\n"
            "  1. Call revit_info; abort with a clear error if no document "
            "is open.\n"
            "  2. Call revit_execute_csharp inside ONE Transaction named "
            "'ArchHub: Project setup' that:\n"
            "       - sets project units to millimetres\n"
            "       - creates levels named L1–L<n> at storey_height intervals\n"
            "       - creates an A–E × 1–5 grid (or matches grid_count when given)\n"
            "       - duplicates the default WallType, DoorType, WindowType "
            "into project-prefixed types\n"
            "       - creates one starter A1 sheet titled "
            "'<project_name> — Cover'\n"
            "  3. Be defensive: skip steps whose targets already exist.\n"
            "  4. Return a summary listing what was created vs. skipped.\n\n"
            "User request: {var1}"
        ),
        allowed_tools=["revit_info", "revit_execute_csharp"],
    )
    meta = SkillMeta(
        intent="Initialise a Revit project with levels, grids, units, default types, and a starter sheet.",
        keywords=[
            "setup", "project", "initialise", "initialize", "start",
            "levels", "grids", "units", "template", "skeleton",
        ],
        when_to_use=(
            "User has just opened or created a fresh Revit project and "
            "wants the standard initial structure built automatically."
        ),
        examples=[
            {"prompt": "Set up this Revit project for me",
             "expected_outcome": "Levels, grids, units, default types, cover sheet."},
            {"prompt": "Initialise the project",
             "expected_outcome": "Same as above."},
        ],
        tags=["revit", "setup", "project"],
        requires=["revit"],
        author="ArchHub",
        scope=SCOPE_USER,
    )
    return wf, meta


def _seed_mass_to_walls() -> tuple[Workflow, SkillMeta]:
    wf = _build_chain(
        workflow_id=SEED_MASS_TO_WALLS_ID,
        name="Convert mass to Revit walls",
        description=(
            "Turn the active conceptual mass (or a mass fetched from "
            "Speckle / Blender) into stacked Revit walls per level, using "
            "the project's default wall type."
        ),
        framing_template=(
            "You are running the ArchHub skill 'Convert mass to Revit walls'. "
            "GOAL: extrude wall family instances along the vertical faces "
            "of the active conceptual mass, one stack per level.\n"
            "Procedure:\n"
            "  1. Call revit_info; locate the active mass (FilledRegion "
            "exclusion: only Mass elements). If multiple, pick the one "
            "matching mass_name from session parameters; otherwise the "
            "largest by volume.\n"
            "  2. Call revit_execute_csharp inside ONE Transaction named "
            "'ArchHub: Mass → Walls' that:\n"
            "       - reads each Level in the document\n"
            "       - for each vertical face of the mass, creates a Wall "
            "between Level N and Level N+1 using the project default "
            "WallType\n"
            "       - sets each new Wall's location curve to the face's "
            "bottom edge\n"
            "       - tags each new Wall with a mark = 'AH-<n>'\n"
            "  3. Skip horizontal faces (those become floors / roofs in a "
            "later stage).\n"
            "  4. Return: number of walls created, levels touched, mass id used.\n\n"
            "User request: {var1}"
        ),
        allowed_tools=["revit_info", "revit_execute_csharp"],
    )
    meta = SkillMeta(
        intent="Generate stacked Revit walls along the vertical faces of a conceptual mass.",
        keywords=[
            "mass", "to walls", "extrude", "convert", "walls", "exterior",
            "stack", "split-by-level", "from-mass",
        ],
        when_to_use=(
            "User has a conceptual mass in Revit and wants real Revit "
            "walls built from it as the next step toward documentation."
        ),
        examples=[
            {"prompt": "Convert this mass to walls",
             "expected_outcome": "Wall instances along every vertical face, split by level."},
        ],
        tags=["revit", "production", "walls", "mass"],
        requires=["revit"],
        author="ArchHub",
        scope=SCOPE_USER,
    )
    return wf, meta


def _seed_place_openings() -> tuple[Workflow, SkillMeta]:
    wf = _build_chain(
        workflow_id=SEED_PLACE_OPENINGS_ID,
        name="Place doors and windows",
        description=(
            "Place doors and windows on the active project's walls using "
            "default door/window FamilySymbols. Smart defaults: one door per "
            "exterior wall ground-floor centre; windows distributed at "
            "regular intervals on each wall."
        ),
        framing_template=(
            "You are running the ArchHub skill 'Place doors and windows'. "
            "GOAL: insert FamilyInstances of door + window types along walls "
            "in the active Revit project.\n"
            "Procedure:\n"
            "  1. Call revit_info; abort if no document is open.\n"
            "  2. Call revit_execute_csharp inside ONE Transaction named "
            "'ArchHub: Doors and windows' that:\n"
            "       - collects all Walls grouped by Level\n"
            "       - per wall: places one door at midpoint if Level == "
            "ground floor AND wall is on the exterior boundary\n"
            "       - per wall: places (length / 4 m) windows at regular "
            "intervals at sill height 900 mm\n"
            "       - uses the project's default door/window FamilySymbol; "
            "activates the symbol if not already active\n"
            "       - skips walls shorter than 1.5 m (no openings on stubs)\n"
            "  3. Return: doors placed, windows placed, walls skipped.\n\n"
            "User request: {var1}"
        ),
        allowed_tools=["revit_info", "revit_execute_csharp"],
    )
    meta = SkillMeta(
        intent="Place default doors and windows on the project's walls using sensible defaults.",
        keywords=[
            "door", "doors", "window", "windows", "openings", "place",
            "insert", "fenestration",
        ],
        when_to_use=(
            "User has walls already in the project and wants doors and "
            "windows added with default placement before fine-tuning."
        ),
        examples=[
            {"prompt": "Place doors and windows on the walls",
             "expected_outcome": "Doors at exterior-wall centres, windows distributed per wall."},
        ],
        tags=["revit", "production", "openings"],
        requires=["revit"],
        author="ArchHub",
        scope=SCOPE_USER,
    )
    return wf, meta


def _seed_generate_sheets() -> tuple[Workflow, SkillMeta]:
    wf = _build_chain(
        workflow_id=SEED_GENERATE_SHEETS_ID,
        name="Generate production sheets",
        description=(
            "Create a starter sheet set for the project: floor plans per "
            "level, four building elevations, two key sections, and a "
            "schedule of room areas."
        ),
        framing_template=(
            "You are running the ArchHub skill 'Generate production sheets'. "
            "GOAL: produce a starter set of construction documents.\n"
            "Procedure:\n"
            "  1. Call revit_info; abort if no document is open.\n"
            "  2. Call revit_execute_csharp inside ONE Transaction named "
            "'ArchHub: Production sheets' that:\n"
            "       - duplicates the existing FloorPlan view per Level if "
            "missing, names them 'Plan — <level>'\n"
            "       - creates four ElevationView markers around the model "
            "bounding box (N/S/E/W), names them 'Elevation — <dir>'\n"
            "       - creates two SectionView lines along the longer + "
            "shorter axes through the centre of the bounding box\n"
            "       - creates a Schedule of Rooms with columns "
            "Number / Name / Level / Area\n"
            "       - creates one ViewSheet per category and places the "
            "matching Viewports on each sheet using the project's title block\n"
            "  3. Use existing TitleBlockSymbol; pick the first one if "
            "there are several.\n"
            "  4. Return: sheets created, views placed, schedules created.\n\n"
            "User request: {var1}"
        ),
        allowed_tools=["revit_info", "revit_execute_csharp"],
    )
    meta = SkillMeta(
        intent="Build a starter construction-document sheet set: plans, elevations, sections, room schedule.",
        keywords=[
            "sheets", "production", "drawings", "plans", "elevations",
            "sections", "schedule", "documentation", "deliverables",
            "construction-docs", "issue-set",
        ],
        when_to_use=(
            "User wants a starter set of production sheets built "
            "automatically from the current model."
        ),
        examples=[
            {"prompt": "Generate the production sheets",
             "expected_outcome": "Sheets with plans per level, four elevations, two sections, room schedule."},
        ],
        tags=["revit", "production", "sheets", "drawings"],
        requires=["revit"],
        author="ArchHub",
        scope=SCOPE_USER,
    )
    return wf, meta


def _seed_sketch_to_production() -> tuple[Workflow, SkillMeta]:
    """The flagship multi-stage Skill — sketch → production sheets in one
    workflow. Each stage is its own llm.complete_with_tools node so the
    model picks the right tool per stage with a focused prompt."""
    wf = Workflow(
        id=SEED_SKETCH_TO_PRODUCTION_ID,
        name="Sketch to production",
        description=(
            "End-to-end: read a sketch, extract a mass in Blender, push to "
            "Revit via Speckle, set up the project, build walls, place "
            "openings, generate sheets. One prompt, one click, every stage."
        ),
        triggers=[Trigger(id=_id("trigger"), type="manual")],
    )

    # Workflow input: prompt = the user's natural-language request
    input_node = Node(
        id=_id("input"), type="input.parameter", label="Prompt",
        config={"name": "prompt", "type": "string",
                "description": "The user's natural-language request, optionally with a sketch image attached.",
                "default": ""},
        outputs=[Port(name="value", type=PortType.STRING)],
    )
    wf.add_node(input_node)
    wf.inputs.append(Port(name="prompt", type=PortType.STRING,
                          description="User's request",
                          required=True))

    stages: list[tuple[str, str, list[str]]] = [
        ("stage_extract", (
            "STAGE 1 OF 6 — Extract mass from sketch.\n"
            "Read the attached sketch image. Infer parameters (width, depth, "
            "storeys, roof). Build the mass in Blender via blender_execute_python. "
            "Wrap geometry in a collection 'Mass_Sketch'. Return the inferred "
            "parameters as a one-line summary.\n\n"
            "User request: {var1}"
        ), ["blender_ping", "blender_execute_python"]),

        ("stage_to_speckle", (
            "STAGE 2 OF 6 — Push the Blender mass to Speckle so Revit can pick it up.\n"
            "Call blender_execute_python to export the 'Mass_Sketch' collection as a "
            "Speckle commit on branch 'sketch-to-production'. Return the commit URL.\n\n"
            "Previous stage output: {var1}"
        ), ["blender_execute_python", "speckle_list_projects"]),

        ("stage_setup", (
            "STAGE 3 OF 6 — Set up the Revit project.\n"
            "Use revit_execute_csharp INSIDE ONE Transaction named "
            "'ArchHub: Project setup' to: set units to mm; create levels "
            "L1..Ln at storey_height intervals matching the inferred "
            "parameters; create an A-E x 1-5 grid; duplicate default wall, "
            "door, window types into project-prefixed names; create one A1 "
            "cover sheet. Skip any element that already exists.\n\n"
            "Previous stage output: {var1}"
        ), ["revit_info", "revit_execute_csharp"]),

        ("stage_walls", (
            "STAGE 4 OF 6 — Build walls from the mass.\n"
            "Use revit_execute_csharp INSIDE ONE Transaction named "
            "'ArchHub: Mass to walls' to enumerate the active mass's "
            "vertical faces, create Wall instances stacked by level along "
            "each face's bottom edge, and tag each new wall with mark 'AH-<n>'.\n\n"
            "Previous stage output: {var1}"
        ), ["revit_info", "revit_execute_csharp"]),

        ("stage_openings", (
            "STAGE 5 OF 6 — Place doors and windows.\n"
            "Use revit_execute_csharp INSIDE ONE Transaction named "
            "'ArchHub: Openings' to place: one door per exterior wall on "
            "the ground floor at midpoint; (length/4 m) windows at sill "
            "900 mm distributed along each wall longer than 1.5 m. Use "
            "default door/window FamilySymbols, activating them if needed.\n\n"
            "Previous stage output: {var1}"
        ), ["revit_info", "revit_execute_csharp"]),

        ("stage_sheets", (
            "STAGE 6 OF 6 — Generate the starter production sheet set.\n"
            "Use revit_execute_csharp INSIDE ONE Transaction named "
            "'ArchHub: Production sheets' to create floor plans per level, "
            "four elevations (N/S/E/W), two sections through the centre, a "
            "room schedule (Number, Name, Level, Area), and ViewSheets "
            "placing each on its own A1 sheet using the project's first "
            "TitleBlockSymbol. Return total sheet count.\n\n"
            "Previous stage output: {var1}"
        ), ["revit_info", "revit_execute_csharp"]),
    ]

    prev_source = (input_node.id, "value")
    for label, framing, tools in stages:
        tmpl_node = Node(
            id=_id("tmpl"), type="data.template", label=f"Frame {label}",
            config={"template": framing},
            inputs=[Port(name="var1", type=PortType.STRING)],
            outputs=[Port(name="text", type=PortType.STRING)],
        )
        wf.add_node(tmpl_node)
        wf.add_edge(Edge(id=_id("edge"), src_node=prev_source[0], src_port=prev_source[1],
                         dst_node=tmpl_node.id, dst_port="var1"))

        llm_node = Node(
            id=_id("llm"), type="llm.complete_with_tools", label=label,
            config={"model": "auto", "allowed_tools": tools},
            inputs=[Port(name="prompt", type=PortType.STRING, required=True)],
            outputs=[
                Port(name="text",             type=PortType.STRING),
                Port(name="tool_invocations", type=PortType.LIST),
                Port(name="model",            type=PortType.STRING),
            ],
        )
        wf.add_node(llm_node)
        wf.add_edge(Edge(id=_id("edge"), src_node=tmpl_node.id, src_port="text",
                         dst_node=llm_node.id, dst_port="prompt"))
        prev_source = (llm_node.id, "text")

    output_node = Node(
        id=_id("output"), type="output.parameter", label="Final summary",
        config={"name": "answer"},
        inputs=[Port(name="value", type=PortType.STRING, required=True)],
        outputs=[Port(name="value", type=PortType.STRING)],
    )
    wf.add_node(output_node)
    wf.add_edge(Edge(id=_id("edge"), src_node=prev_source[0], src_port=prev_source[1],
                     dst_node=output_node.id, dst_port="value"))
    wf.outputs.append(Port(name="answer", type=PortType.STRING,
                           description="Final assistant text"))

    meta = SkillMeta(
        intent="From a hand sketch, build a fully-documented Revit project: mass, walls, openings, sheets — every stage automated.",
        keywords=[
            "sketch", "production", "end-to-end", "full-pipeline",
            "documentation", "build-everything", "concept-to-doc",
            "deliver", "finish",
        ],
        when_to_use=(
            "User attaches a sketch and wants the entire pipeline run "
            "without picking a stage manually."
        ),
        examples=[
            {"prompt": "Take this sketch all the way to production drawings",
             "expected_outcome": "Mass in Blender + Revit walls + doors/windows + sheets — all stages run."},
            {"prompt": "Build this and document it",
             "expected_outcome": "Same as above."},
        ],
        tags=["revit", "blender", "speckle", "production", "pipeline", "vision"],
        requires=["revit", "blender", "speckle"],
        author="ArchHub",
        scope=SCOPE_USER,
    )
    return wf, meta


# ---------------------------------------------------------------------------
SEED_FACTORIES = (
    _seed_extract_mass,
    _seed_setup_revit_project,
    _seed_mass_to_walls,
    _seed_place_openings,
    _seed_generate_sheets,
    _seed_sketch_to_production,
)


def ensure_production_skills() -> list[str]:
    """Materialise every production-pipeline starter Skill missing from the
    library. Idempotent. Returns the list of newly-seeded ids."""
    existing_ids = {s["id"] for s in list_skills()}
    seeded: list[str] = []
    for factory in SEED_FACTORIES:
        wf, meta = factory()
        if wf.id in existing_ids:
            continue
        save_skill(wf, meta)
        seeded.append(wf.id)
    return seeded
