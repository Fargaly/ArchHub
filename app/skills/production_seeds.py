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
SEED_EXPORT_REVIT_TO_DWG_ID  = "seed-export-revit-to-dwg-v1"
SEED_OSM_CONTEXT_MASS_ID     = "seed-osm-context-mass-v1"
SEED_DETAIL_PASS_ID          = "seed-revit-detail-pass-v1"
SEED_ACAD_DWG_INVENTORY_ID   = "seed-acad-dwg-inventory-v1"
SEED_CONSTRUCTION_DOC_SPRINT_ID = "seed-construction-doc-sprint-v1"
SEED_SKILL_BUILDER_ID           = "seed-skill-builder-v1"
SEED_SKILL_FINDER_ID            = "seed-skill-finder-v1"


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
def _seed_export_revit_to_dwg() -> tuple[Workflow, SkillMeta]:
    wf = _build_chain(
        workflow_id=SEED_EXPORT_REVIT_TO_DWG_ID,
        name="Export Revit drawings to AutoCAD",
        description=(
            "Export the active view, the active sheet, or all sheets in the "
            "current sheet set to AutoCAD .dwg files in a folder of the "
            "user's choice (defaults to the project folder)."
        ),
        framing_template=(
            "You are running the ArchHub skill 'Export Revit drawings to "
            "AutoCAD'. GOAL: produce one or more .dwg files matching what "
            "the architect described.\n"
            "Procedure:\n"
            "  1. Call revit_info; capture document title, path, and active view.\n"
            "  2. Decide the export set from the user request:\n"
            "       - 'this view' / no scope → just the active view\n"
            "       - 'this sheet' / 'current sheet' → active view IF it's a Sheet, else fail clearly\n"
            "       - 'all sheets' / 'every sheet' / 'sheet set' → all ViewSheet elements\n"
            "       - explicit sheet-name list → those ViewSheets only\n"
            "  3. Call revit_execute_csharp INSIDE a single transaction-free C# block (DWG export does not require Transactions but does require a fresh DWGExportOptions):\n"
            "       - Create DWGExportOptions(); set FileVersion = ACA2018, MergedViews = false, HideUnreferenceViewTags = true.\n"
            "       - Determine outDir: if the document has a save path, write next to it under '<filename>_DWG/'. Otherwise %USERPROFILE%/Documents/ArchHub-DWG/.\n"
            "       - Build a ViewSet of the chosen views.\n"
            "       - Call doc.Export(outDir, '<base>', viewSet, dwgOptions). Use the document title as <base>; Revit appends view names per file.\n"
            "       - Capture the list of files Revit reports as written.\n"
            "  4. Return: total files written, full output folder path, sheet/view names exported, any sheets skipped + why.\n\n"
            "User request: {var1}"
        ),
        allowed_tools=["revit_info", "revit_execute_csharp"],
    )
    meta = SkillMeta(
        intent="Export the active view, current sheet, or all sheets in Revit to AutoCAD .dwg files.",
        keywords=[
            "export", "dwg", "autocad", "drawings", "extract",
            "to-cad", "from-revit", "convert", "save-as",
        ],
        when_to_use=(
            "User asks to extract / export / convert Revit views or sheets "
            "to AutoCAD or .dwg format."
        ),
        examples=[
            {"prompt": "Export all sheets to DWG",
             "expected_outcome": "One .dwg per ViewSheet in <project>_DWG/."},
            {"prompt": "Save the current sheet as AutoCAD",
             "expected_outcome": "Single .dwg of the active sheet."},
            {"prompt": "Convert this view to dwg",
             "expected_outcome": "Single .dwg of the active view."},
        ],
        tags=["revit", "autocad", "export", "production"],
        requires=["revit"],
        author="ArchHub",
        scope=SCOPE_USER,
    )
    return wf, meta


def _seed_osm_context_mass() -> tuple[Workflow, SkillMeta]:
    wf = _build_chain(
        workflow_id=SEED_OSM_CONTEXT_MASS_ID,
        name="Build site context from a map link",
        description=(
            "Take a Google Maps URL (or lat/long coordinates), fetch the "
            "surrounding building footprints from OpenStreetMap, and extrude "
            "them as context masses in Blender so the architect can model "
            "their proposal inside the real urban context."
        ),
        framing_template=(
            "You are running the ArchHub skill 'Build site context from a map link'. "
            "GOAL: read the location from the user's request (Google Maps URL "
            "or explicit coordinates), fetch surrounding buildings from "
            "OpenStreetMap (no API key required), and build them as massing "
            "geometry in Blender so the architect's site fits in real context.\n"
            "Procedure:\n"
            "  1. Parse the user's request:\n"
            "       - Google Maps URL: extract the @lat,lng,zoom triple from the path. Pattern: /@<lat>,<lng>,<zoom>z\n"
            "       - 'maps.app.goo.gl' / 'maps.google.com/?q=<lat>,<lng>': extract from query.\n"
            "       - Plain '<lat>, <lng>' string: parse directly.\n"
            "       - Default radius: 250 m unless the user says otherwise.\n"
            "  2. Call blender_execute_python with a SINGLE script that:\n"
            "       - imports urllib.request, json, bpy, math\n"
            "       - builds the Overpass query for buildings within the radius:\n"
            "           [out:json][timeout:30];\n"
            "           way[\"building\"](around:<r>,<lat>,<lng>);\n"
            "           out geom;\n"
            "       - POSTs to https://overpass-api.de/api/interpreter\n"
            "       - For each returned way:\n"
            "           - Convert each lat/lng node to local meters using a simple equirectangular projection centred on the input (delta_lat * 111000, delta_lng * 111000 * cos(lat)).\n"
            "           - Read 'height' tag in metres if present; else 'building:levels' * 3.0; else default 9.0.\n"
            "           - Create a Mesh from the polygon, extrude to the height, name 'OSM_<id>'.\n"
            "       - Group every created object under a new collection 'Site_Context'.\n"
            "       - Add a Plane sized 2*radius below to represent the ground.\n"
            "       - Add a small Empty at world origin labelled with the lat/lng so the architect knows where the site centre is.\n"
            "       - Print a one-line summary: how many buildings imported, total footprint area, time taken.\n"
            "  3. After execution, return: number of buildings, centre lat/lng, radius used, and a 'Site_Context' collection name. Tell the user they can now model their proposal inside this context.\n\n"
            "User request: {var1}"
        ),
        allowed_tools=["blender_ping", "blender_execute_python"],
    )
    meta = SkillMeta(
        intent="Pull surrounding buildings from OpenStreetMap and build a Blender context massing from a map link.",
        keywords=[
            "google", "maps", "map", "osm", "openstreetmap",
            "context", "site", "surroundings", "neighbourhood",
            "neighborhood", "urban", "lat", "long", "coordinates",
            "from-map", "build-context",
        ],
        when_to_use=(
            "User pastes a Google Maps URL or coordinates and asks for the "
            "surrounding buildings as a Blender massing."
        ),
        examples=[
            {"prompt": "Build the site context from this map link <url>",
             "expected_outcome": "Buildings within ~250 m extruded to their real heights as a Blender Site_Context collection."},
            {"prompt": "Mass the surroundings at 24.4539, 54.3773",
             "expected_outcome": "Same as above; coordinates parsed directly."},
        ],
        tags=["blender", "context", "massing", "site", "maps"],
        requires=["blender"],
        author="ArchHub",
        scope=SCOPE_USER,
    )
    return wf, meta


def _seed_revit_detail_pass() -> tuple[Workflow, SkillMeta]:
    wf = _build_chain(
        workflow_id=SEED_DETAIL_PASS_ID,
        name="Annotate active view (dimensions + tags + room labels)",
        description=(
            "Run a one-pass annotation: dimension every wall, tag every "
            "door / window / room visible in the active view. Each pass "
            "wrapped in its own Revit Transaction so the architect can "
            "Undo selectively if a category mis-fires."
        ),
        framing_template=(
            "You are running the ArchHub skill 'Annotate active view'. "
            "GOAL: produce a clean construction-document-ready annotation "
            "pass on whatever view is active.\n"
            "Procedure:\n"
            "  1. Call revit_info to confirm a document and active view.\n"
            "  2. Call revit_execute_csharp ONCE with a C# block that "
            "performs THREE separate Revit Transactions in sequence "
            "(named 'ArchHub: Dimension walls', 'ArchHub: Tag openings', "
            "'ArchHub: Tag rooms'):\n"
            "     a. Dimension every Wall whose LocationCurve is in the "
            "active view, using the project's default LinearDimensionType.\n"
            "     b. Place a DoorTag and WindowTag on every Door / Window "
            "FamilyInstance whose Host is a wall in the active view. "
            "Activate the default tag symbols if not already active.\n"
            "     c. Place a RoomTag at the centre of every Room whose Level "
            "matches the active view's GenLevel and whose Area > 0.\n"
            "  3. Be defensive: skip elements without a stable reference "
            "(e.g. doors with no host curve), count + report skipped.\n"
            "  4. Return per-pass counts: walls dimensioned, openings "
            "tagged, rooms tagged, total skipped, view name.\n\n"
            "User request: {var1}"
        ),
        allowed_tools=["revit_info", "revit_execute_csharp"],
    )
    meta = SkillMeta(
        intent="Run a one-pass annotation: dimension walls + tag openings + tag rooms in the active Revit view.",
        keywords=[
            "annotate", "annotation", "dimension", "tag", "tags",
            "label", "labels", "detail", "construction-doc",
            "annotate-view", "doc-up", "drawing-set",
        ],
        when_to_use=(
            "User wants the active view fully annotated for construction "
            "documents in one click."
        ),
        examples=[
            {"prompt": "Annotate this view",
             "expected_outcome": "Wall dimensions + door/window tags + room labels appear."},
            {"prompt": "Doc this floor plan up",
             "expected_outcome": "Same as above."},
        ],
        tags=["revit", "annotation", "production"],
        requires=["revit"],
        author="ArchHub",
        scope=SCOPE_USER,
    )
    return wf, meta


def _seed_acad_dwg_inventory() -> tuple[Workflow, SkillMeta]:
    wf = _build_chain(
        workflow_id=SEED_ACAD_DWG_INVENTORY_ID,
        name="Inventory the open AutoCAD drawing",
        description=(
            "Walk the active AutoCAD drawing and produce a normalised "
            "inventory: every layer with entity counts, every block with "
            "insertion count, every text style, plus drawing units, "
            "extents, and any obvious issues (zero-width polylines, "
            "frozen-but-used layers, blocks on layer 0, etc.). The "
            "architect gets a Markdown audit they can paste into a "
            "drawing-set hand-over note."
        ),
        framing_template=(
            "You are running the ArchHub skill 'Inventory the open AutoCAD drawing'. "
            "GOAL: read the active DWG and return a clean Markdown audit. "
            "DO NOT mutate the drawing.\n"
            "Procedure:\n"
            "  1. Call acad_ping then acad_info to confirm a document is open. If none, fail with a clear instruction to open the .dwg first.\n"
            "  2. Call acad_execute_csharp ONCE with a read-only block (no Transaction needed for reads, but use OpenMode.ForRead). Globals: Doc, Db, Ed.\n"
            "       - Iterate the LayerTable: capture name, IsFrozen, IsLocked, IsOff, Color.\n"
            "       - Iterate ModelSpace: count entities per layer; track BlockReference inserts grouped by BlockTableRecord name.\n"
            "       - Iterate the TextStyleTable: capture name, font, height.\n"
            "       - Iterate the BlockTable for non-anonymous, non-layout blocks: capture name + how many ModelSpace inserts each has.\n"
            "       - Capture: drawing units (Db.Insunits), extents (Db.Extmin/Extmax), total entity count.\n"
            "       - Build issues list:\n"
            "           * blocks inserted but only on layer '0' (= no layer hygiene)\n"
            "           * polylines with ConstantWidth == 0 AND Width zero on every vertex (= invisible if printed by lineweight)\n"
            "           * frozen layers that still have geometry\n"
            "           * layers named like 'Layer1', 'Defpoints' with content, layers with no entities\n"
            "  3. Return ONE single Markdown document with:\n"
            "       - '# Drawing inventory — <filename>'\n"
            "       - bullet line for units / extents / total entities\n"
            "       - '## Layers' table (name | entities | frozen | locked | colour)\n"
            "       - '## Blocks' table (name | inserts)\n"
            "       - '## Text styles' table\n"
            "       - '## Issues found' list (bulleted, severity)\n"
            "       - '## Suggested clean-up' (3-5 imperative bullets the user can act on).\n\n"
            "User request: {var1}"
        ),
        allowed_tools=["acad_ping", "acad_info", "acad_execute_csharp"],
    )
    meta = SkillMeta(
        intent="Audit the open AutoCAD drawing — list layers, blocks, text styles, plus drawing-hygiene issues.",
        keywords=[
            "acad", "autocad", "dwg", "inventory", "audit", "layers",
            "blocks", "text-styles", "extract", "summary", "clean-up",
            "hand-over", "drawing-set",
        ],
        when_to_use=(
            "User wants to know what's inside an AutoCAD drawing — layers, "
            "blocks, hygiene issues — before integrating it into a Revit "
            "project or handing it to a client."
        ),
        examples=[
            {"prompt": "Inventory this drawing",
             "expected_outcome": "Markdown audit with layer / block / text-style tables and a hygiene issue list."},
            {"prompt": "What's inside this DWG?",
             "expected_outcome": "Same Markdown audit."},
            {"prompt": "Audit the layers in this AutoCAD file",
             "expected_outcome": "Same Markdown audit, focused on layer hygiene."},
        ],
        tags=["autocad", "audit", "extract", "production"],
        requires=["autocad"],
        author="ArchHub",
        scope=SCOPE_USER,
    )
    return wf, meta


def _seed_construction_doc_sprint() -> tuple[Workflow, SkillMeta]:
    """**The flagship paid product** — Construction Doc Sprint Pack.

    Drop a Revit model in any pre-CD state, click run, and 60-90
    minutes later you have a production-ready sheet set: floor plans,
    elevations, sections, schedules (filled, not empty), keynotes
    placed, dimensions + tags + room labels applied. The architect's
    junior-staff cost replacement, packaged as one Skill.

    Six chained stages, each its own Revit Transaction so any pass
    can be Undone independently if it misfires. Stage 6 emits a
    Markdown audit summarising what was created vs skipped — the
    BIM lead pastes that into the project's hand-over note.
    """
    wf = Workflow(
        id=SEED_CONSTRUCTION_DOC_SPRINT_ID,
        name="Construction doc sprint pack",
        description=(
            "Drop a Revit model → sheets, schedules, keynotes, "
            "dimensions, room labels in one click. Six chained passes "
            "each in its own Revit Transaction so the architect can "
            "Undo any one independently. Final stage emits a Markdown "
            "audit of what was created vs skipped."
        ),
        triggers=[Trigger(id=_id("trigger"), type="manual")],
    )

    input_node = Node(
        id=_id("input"), type="input.parameter", label="Prompt",
        config={"name": "prompt", "type": "string",
                "description": "Optional refinements (e.g. 'A1 sheets, metric, no schedules').",
                "default": ""},
        outputs=[Port(name="value", type=PortType.STRING)],
    )
    wf.add_node(input_node)
    wf.inputs.append(Port(name="prompt", type=PortType.STRING,
                          description="Optional user refinements", required=False))

    stages: list[tuple[str, str, list[str]]] = [
        ("stage_audit", (
            "STAGE 1 OF 6 — Audit the active document.\n"
            "Call revit_info to confirm a project is open. Then call "
            "revit_execute_csharp (read-only, no Transaction) that returns "
            "JSON with: levels (count + names), grids (count), "
            "WallTypes (count), DoorTypes (count), WindowTypes (count), "
            "existing ViewSheets (count + names), existing Schedules "
            "(count + names), TitleBlockSymbols (count + first name), "
            "Rooms (count + how many have nonzero Area), and a 'gaps' "
            "list flagging anything missing that downstream stages will "
            "need (no TitleBlockSymbol, no Rooms, no WallTypes).\n"
            "Output: that JSON pretty-printed, plus a one-line summary.\n\n"
            "User refinements: {var1}"
        ), ["revit_info", "revit_execute_csharp"]),

        ("stage_sheets", (
            "STAGE 2 OF 6 — Build the sheet set.\n"
            "Call revit_execute_csharp ONCE with the C# below, filled in.\n"
            "Use Transaction name 'ArchHub: Sheet set'. Use only these "
            "exact namespaces (already imported by the runner): "
            "Autodesk.Revit.DB, System, System.Linq, System.Collections.Generic.\n"
            "DO NOT redeclare 'doc', 'tx', or 'created' — they exist in "
            "the runner scope.\n\n"
            "C# scaffold (fill the THREE marked blocks; leave structure):\n"
            "```csharp\n"
            "// Stage 2: floor plans only. Stages elevations + sections come later.\n"
            "var levels = new FilteredElementCollector(doc)\n"
            "    .OfClass(typeof(Level)).Cast<Level>().ToList();\n"
            "ViewFamilyType planType = new FilteredElementCollector(doc)\n"
            "    .OfClass(typeof(ViewFamilyType)).Cast<ViewFamilyType>()\n"
            "    .First(v => v.ViewFamily == ViewFamily.FloorPlan);\n"
            "var existingPlanNames = new HashSet<string>(\n"
            "    new FilteredElementCollector(doc).OfClass(typeof(ViewPlan))\n"
            "        .Cast<ViewPlan>().Where(v => !v.IsTemplate).Select(v => v.Name));\n"
            "int created = 0; int skipped = 0;\n"
            "var madeNames = new List<string>();\n"
            "foreach (var lvl in levels) {\n"
            "    string name = $\"AH - {lvl.Name} - Plan\";\n"
            "    if (existingPlanNames.Contains(name)) { skipped++; continue; }\n"
            "    var v = ViewPlan.Create(doc, planType.Id, lvl.Id);\n"
            "    v.Name = name;\n"
            "    created++;\n"
            "    madeNames.Add(name);\n"
            "}\n"
            "ctx.result = new {\n"
            "    plans_created = created,\n"
            "    plans_skipped = skipped,\n"
            "    new_view_names = madeNames,\n"
            "};\n"
            "```\n\n"
            "Output AFTER the call: a 1-line summary of plans_created vs "
            "plans_skipped, then the list of new_view_names.\n\n"
            "Audit context: {var1}"
        ), ["revit_info", "revit_execute_csharp"]),

        ("stage_schedules", (
            "STAGE 3 OF 6 — Fill the standard schedules.\n"
            "Use revit_execute_csharp INSIDE ONE Transaction named "
            "'ArchHub: Schedule fixer' to:\n"
            "  - If a 'Room schedule' doesn't exist, create one with "
            "    fields: Number, Name, Level, Area.\n"
            "  - If a 'Door schedule' doesn't exist, create one with "
            "    fields: Mark, Type, Width, Height, Level.\n"
            "  - If a 'Window schedule' doesn't exist, create one with "
            "    fields: Mark, Type, Width, Height, Sill Height, Level.\n"
            "  - For every existing element of each category whose Mark "
            "    is empty, auto-number sequentially: D-001, W-001, "
            "    R-001 etc. NEVER overwrite a non-empty Mark.\n"
            "  - For every element of each category whose Type Name "
            "    contains 'Default' or is empty, set a project-prefixed "
            "    Comments value 'TODO: pick a real type'.\n"
            "Return: counts of schedules created vs already-present, "
            "Mark assignments made, TODO Comments inserted.\n\n"
            "Sheets context: {var1}"
        ), ["revit_info", "revit_execute_csharp"]),

        ("stage_keynotes", (
            "STAGE 4 OF 6 — Place keynote tags on visible elements.\n"
            "Use revit_execute_csharp INSIDE ONE Transaction named "
            "'ArchHub: Keynote pass' to: in every Plan view that was "
            "just created (or all Plan views if none new), iterate "
            "FamilyInstances of category Doors, Windows, Furniture, "
            "and place a KeynoteTag at the element's centroid using the "
            "default keynote tag symbol (activate it if needed). Skip "
            "elements whose Type Name is 'Default'. Use the User Keynote "
            "table — the value comes from the element's Type-level "
            "'Keynote' parameter, set to '<category-prefix>-<typename>' "
            "if currently empty.\n"
            "Return: tags placed per category + skipped count.\n\n"
            "Schedule context: {var1}"
        ), ["revit_info", "revit_execute_csharp"]),

        ("stage_annotations", (
            "STAGE 5 OF 6 — Annotation pass: dimensions + tags + rooms.\n"
            "This stage is the same logic as the standalone 'Annotate "
            "active view' Skill, but applied to EACH Plan view that "
            "was just created (or all Plan views if none new). Use "
            "revit_execute_csharp INSIDE THREE separate Transactions, "
            "one per pass, named 'ArchHub: Dim walls', 'ArchHub: Tag "
            "openings', 'ArchHub: Tag rooms'. For each Plan view: "
            "dimension every Wall whose LocationCurve is in view, place "
            "DoorTags + WindowTags on every Door/Window FamilyInstance "
            "hosted by an in-view wall, place a RoomTag at the centre "
            "of every Room whose Level matches the view's GenLevel and "
            "whose Area > 0. Activate default tag symbols if needed.\n"
            "Return: per-view counts (walls dimensioned, openings "
            "tagged, rooms tagged, total skipped).\n\n"
            "Keynote context: {var1}"
        ), ["revit_info", "revit_execute_csharp"]),

        ("stage_qc", (
            "STAGE 6 OF 6 — Final QC report.\n"
            "DO NOT run any more Transactions. Read the cumulative "
            "stage outputs (stages 1-5) and produce ONE Markdown audit "
            "titled '# Construction Doc Sprint — <project name>'.\n"
            "Sections, in order:\n"
            "  ## Snapshot — total elements / levels / grids / sheets "
            "now in document.\n"
            "  ## What this run created — bullet list with counts of "
            "  sheets, schedules, keynotes, dimensions, tags, room labels.\n"
            "  ## Skipped (and why) — table of skipped items + reason "
            "  (already existed, no host, default type, etc.).\n"
            "  ## TODOs left for a human — bullet list of every element "
            "  whose Comments now contains 'TODO:' (from stage 3) and "
            "  every Type whose Keynote was set to a placeholder "
            "  (from stage 4).\n"
            "  ## Suggested next moves — 3 bullets the BIM lead can "
            "  paste into the project hand-over note.\n"
            "No invented numbers — if a section is empty, write "
            "'(none this run)'.\n\n"
            "Annotation context: {var1}"
        ), []),
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
        wf.add_edge(Edge(id=_id("edge"), src_node=prev_source[0],
                         src_port=prev_source[1],
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
        id=_id("output"), type="output.parameter", label="Audit",
        config={"name": "answer"},
        inputs=[Port(name="value", type=PortType.STRING, required=True)],
        outputs=[Port(name="value", type=PortType.STRING)],
    )
    wf.add_node(output_node)
    wf.add_edge(Edge(id=_id("edge"), src_node=prev_source[0],
                     src_port=prev_source[1],
                     dst_node=output_node.id, dst_port="value"))
    wf.outputs.append(Port(name="answer", type=PortType.STRING,
                           description="Final Markdown audit"))

    meta = SkillMeta(
        intent=(
            "Take a Revit model from any pre-CD state to a production-ready "
            "sheet set + schedules + keynotes + dimensions in one run."
        ),
        keywords=[
            "construction", "doc", "documentation", "sprint", "sheets",
            "production-ready", "cd-set", "construction-documents",
            "doc-up", "production", "deliverables", "drawing-set",
            "schedule", "keynotes", "dimensions", "annotate", "all",
        ],
        when_to_use=(
            "User has a Revit model that needs to ship as a CD set "
            "fast — typical at the SD→DD or DD→CD handoff."
        ),
        examples=[
            {"prompt": "Run the construction doc sprint pack on this project",
             "expected_outcome": "Sheets, schedules, keynotes, dimensions, room labels — all created in 60-90 min, plus an audit Markdown."},
            {"prompt": "Doc this whole project up",
             "expected_outcome": "Same as above."},
            {"prompt": "Build a CD set",
             "expected_outcome": "Same as above."},
        ],
        tags=["revit", "production", "pipeline", "flagship", "paid", "construction-docs"],
        requires=["revit"],
        author="ArchHub",
        scope=SCOPE_USER,
    )
    return wf, meta


def _seed_skill_builder() -> tuple[Workflow, SkillMeta]:
    """Meta-skill: 'Build me a Skill that does X' → drafts a new
    .archhub-workflow.json into the user's library."""
    wf = _build_chain(
        workflow_id=SEED_SKILL_BUILDER_ID,
        name="Build a new Skill from a description",
        description=(
            "One-line description in, ready-to-edit Skill out. The "
            "model proposes a workflow graph (input → template → "
            "llm.complete_with_tools → output), names it, sets keywords + "
            "intent + tags, and lists allowed_tools. The architect "
            "reviews + saves from the Skills panel."
        ),
        framing_template=(
            "You are the ArchHub Skill builder. The user describes one "
            "thing they want a re-runnable Skill to do. You output a "
            "single ArchHub workflow JSON that, when saved into the "
            "library, becomes a new Skill the matcher can find.\n\n"
            "Required keys at the top level: id, name, description, "
            "nodes (an input.parameter, a data.template, an "
            "llm.complete_with_tools, and an output.parameter), edges "
            "wiring them in order, and a SkillMeta block under "
            "'metadata' with intent / keywords / when_to_use / examples / "
            "tags / requires.\n\n"
            "Available connector tool name prefixes: revit_, acad_, "
            "max_, blender_, speckle_. Keep the framing template "
            "concrete: name the exact Revit/Blender APIs to use, the "
            "Transactions to wrap, the safety checks to make.\n\n"
            "Output ONLY the JSON. No prose. No code fences.\n\n"
            "User description: {var1}"
        ),
        allowed_tools=[],          # pure generation; no live tools
    )
    meta = SkillMeta(
        intent="Generate a new ArchHub Skill JSON from a one-line description.",
        keywords=[
            "build", "create", "new-skill", "meta", "make-skill",
            "skill-builder", "draft-skill",
        ],
        when_to_use=(
            "User wants ArchHub to draft a brand-new Skill they can save "
            "and share."
        ),
        examples=[
            {"prompt": "Build me a Skill that exports every Revit sheet as PDF",
             "expected_outcome": "A workflow JSON the user can save."},
            {"prompt": "Make a new skill: rename every wall whose Mark starts with TEMP",
             "expected_outcome": "JSON ready to drop into the library."},
        ],
        tags=["meta", "skill-builder", "platform"],
        requires=[],
        author="ArchHub",
        scope=SCOPE_USER,
    )
    return wf, meta


def _seed_skill_finder() -> tuple[Workflow, SkillMeta]:
    """Meta-skill: scan online repos (pyRevit / Dynamo / Grasshopper /
    blender-mcp etc.) for workflows worth porting into ArchHub Skills.

    Doesn't actually crawl the web (the agent has no browser); it reads
    a curated list of source URLs from docs/PEER_LIBRARIES.md and
    emits a Markdown 'discovery report' with the top candidates."""
    wf = _build_chain(
        workflow_id=SEED_SKILL_FINDER_ID,
        name="Find Skills worth porting from peer ecosystems",
        description=(
            "Walks the curated peer-library list (pyRevit extensions, "
            "Dynamo packages, Grasshopper components, blender-mcp "
            "tools, Hypar functions) and produces a discovery report "
            "of the top 10 workflows the architect should consider "
            "porting into ArchHub as Skills."
        ),
        framing_template=(
            "You are the ArchHub Market-Watcher. Read the peer-library "
            "context provided, then produce a Markdown report titled "
            "'# Skills to port — <date>' with these sections:\n"
            "  ## Top 10 candidates  (table: source repo | workflow | "
            "what it does | port effort | architect demand signal)\n"
            "  ## Quick wins (next 7 days)  — 3 bullets, exact Skill "
            "names + a 1-line implementation plan each.\n"
            "  ## Skip list — workflows we should NOT port and why.\n\n"
            "Cite repo + file path on every row. Never invent. If the "
            "context is empty, say 'peer-library list pending'.\n\n"
            "User refinements: {var1}"
        ),
        allowed_tools=[],
    )
    meta = SkillMeta(
        intent="Discover peer-ecosystem workflows worth porting into ArchHub as new Skills.",
        keywords=[
            "discover", "find", "port", "import", "peer", "watch",
            "scan", "library", "candidates", "workflows-to-port",
        ],
        when_to_use=(
            "User wants to expand the Skill library with proven "
            "workflows from the AEC open-source ecosystem."
        ),
        examples=[
            {"prompt": "Find Skills worth porting",
             "expected_outcome": "Markdown report ranking top 10 + 3 quick wins."},
            {"prompt": "What pyRevit / Dynamo workflows should we add?",
             "expected_outcome": "Same report scoped to those ecosystems."},
        ],
        tags=["meta", "discovery", "platform", "growth"],
        requires=[],
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
    _seed_export_revit_to_dwg,
    _seed_osm_context_mass,
    _seed_revit_detail_pass,
    _seed_acad_dwg_inventory,
    _seed_construction_doc_sprint,
    _seed_skill_builder,
    _seed_skill_finder,
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
