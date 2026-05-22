"""Library seeds — initial ModularNodeSpec entries for the engine grammar.

Reference: docs/agdr/AgDR-0014-library-design-system.md (design tokens)

The engine's `workflows.registry.NodeSpec` dataclass already declares each
node-type's type / display_name / inputs / outputs / config_schema. It does
NOT declare `examples`, `side_effects`, or the AgDR-0014 category taxonomy.
This module adapts the engine specs to ModularNodeSpec shape and ships them
as the LIBRARY's initial seeds — what the user sees when they open the
library, what `library.search` ranks against from the first turn.

Seeded primitives (5 representative — full 13-primitive migration arrives
with M3 polish):
    data.constant      input    pure
    input.parameter    input    pure
    connector.run      connector  host_write
    watch.preview      watch    pure
    output.parameter   output   host_write

Skipped:
    note  (UX-only — no engine I/O; needs a `pure_visual` extension to
           ModularNodeSpec — flagged as M3.x polish in AgDR-0014).
    Per-host connector specialisations (revit/autocad/excel/…) — those
    arrive with M2 Speckle connector work.

Each seed below carries:
  • A description ≥80 chars (AgDR-0014 token 2).
  • Examples count tier-matched to side_effects (pure ≥1, host_write ≥2).
  • Category from the AgDR-0014 11-value enum.
  • side_effects + status fields.
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# Seeds — every entry MUST pass library_validator.validate().


PRIMITIVE_SEEDS: list[dict] = [
    # ── data.constant ─────────────────────────────────────────────────
    {
        "type": "data.constant",
        "display_name": "Constant",
        "category": "input",
        "inputs": [],
        "outputs": [
            {
                "name": "value",
                "port_type": "any",
                "description": "The literal value pinned at design time.",
            },
        ],
        "config_schema": {
            "properties": {
                "value": {
                    "type": ["string", "number", "boolean", "object", "array"],
                    "description": "Literal value emitted on every run.",
                },
                "value_type": {
                    "type": "string",
                    "enum": ["string", "number", "boolean", "object", "array"],
                    "default": "string",
                },
            }
        },
        "description": (
            "Emits a fixed literal value on every run. Use this when a "
            "downstream node needs a constant input (a prompt template, "
            "a model name, a magic number) that you pin at design time."
        ),
        "examples": [
            {
                "input": {},
                "output": {"value": "claude-sonnet-4-5"},
                "note": "Holds the model name a chat node will use.",
            },
        ],
        "side_effects": "pure",
        "status": "registered",
    },

    # ── input.parameter ───────────────────────────────────────────────
    {
        "type": "input.parameter",
        "display_name": "Input",
        "category": "input",
        "inputs": [],
        "outputs": [
            {
                "name": "value",
                "port_type": "any",
                "description": "The run-time value bound to this parameter.",
            },
        ],
        "config_schema": {
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Parameter name the runner binds at run-time.",
                },
                "type": {
                    "type": "string",
                    "enum": ["string", "number", "boolean", "object"],
                    "default": "string",
                },
                "description": {"type": "string"},
                "default": {},
            },
            "required": ["name"],
        },
        "description": (
            "A workflow-level input. Bound at run time by the caller "
            "(the user via the Run dialog, a Skill caller, or the "
            "Composer). Use one Input node per parameter the workflow "
            "expects from outside."
        ),
        "examples": [
            {
                "input": {},
                "output": {"value": "<bound at run time>"},
                "note": "User-provided file path; bound from the Run dialog.",
            },
        ],
        "side_effects": "pure",
        "status": "registered",
    },

    # ── connector.run ─────────────────────────────────────────────────
    {
        "type": "connector.run",
        "display_name": "Connector",
        "category": "connector",
        "inputs": [],
        "outputs": [
            {
                "name": "value",
                "port_type": "any",
                "description": "The op's return payload (shape depends on op).",
            },
        ],
        "config_schema": {
            "properties": {
                "host": {
                    "type": "string",
                    "enum": [
                        "revit", "autocad", "excel", "word", "powerpoint",
                        "outlook", "photoshop", "illustrator", "indesign",
                        "speckle", "notion", "dropbox", "teams", "blender",
                        "rhino", "max",
                    ],
                    "description": "Which host application this op targets.",
                },
                "op": {
                    "type": "string",
                    "description": "Op id (e.g. 'list_views', 'read_range').",
                },
            },
            "required": ["host", "op"],
        },
        "description": (
            "Runs a single operation on a connected host application "
            "(Revit, Excel, AutoCAD, Outlook, Speckle, …). `host` + `op` "
            "select the operation; the remaining config rows are its "
            "typed parameters. The connector layer probes the host first "
            "and surfaces a typed error if it is unreachable."
        ),
        "examples": [
            {
                "input": {},
                "output": {"value": [{"id": "v1", "name": "Level 1"}]},
                "note": "Revit list_views — happy path, host reachable.",
            },
            {
                "input": {},
                "output": {
                    "status": "error",
                    "error": "host unreachable: revit not running",
                },
                "note": (
                    "Host offline — typed error with named recovery "
                    "(start Revit or pick another host)."
                ),
            },
        ],
        "side_effects": "host_write",
        "status": "registered",
    },

    # ── watch.preview ─────────────────────────────────────────────────
    {
        "type": "watch.preview",
        "display_name": "Watch",
        "category": "watch",
        "inputs": [
            {
                "name": "value",
                "port_type": "any",
                "required": True,
                "description": "Whatever upstream emits — rendered + passed through.",
            },
        ],
        "outputs": [
            {
                "name": "value",
                "port_type": "any",
                "description": "Identity passthrough so Watch can sit mid-graph.",
            },
        ],
        "config_schema": {
            "properties": {
                "as": {
                    "type": "string",
                    "enum": ["list", "table", "json", "image", "view", "model"],
                    "default": "json",
                    "description": "Render hint for the body (slice E).",
                },
            }
        },
        "description": (
            "Inline preview that renders incoming data and passes it "
            "downstream unchanged. Place mid-graph to inspect a stream "
            "without breaking it. The `as` config picks the renderer — "
            "list / table / json / image / view / model."
        ),
        "examples": [
            {
                "input": {"value": ["walls", "doors", "windows"]},
                "output": {"value": ["walls", "doors", "windows"]},
                "note": "List passthrough — body renders as <ul>.",
            },
        ],
        "side_effects": "pure",
        "status": "registered",
    },

    # ── output.parameter ──────────────────────────────────────────────
    {
        "type": "output.parameter",
        "display_name": "Output",
        "category": "output",
        "inputs": [
            {
                "name": "value",
                "port_type": "any",
                "required": True,
                "description": "Whatever upstream emits; captured as the result.",
            },
        ],
        "outputs": [
            {
                "name": "value",
                "port_type": "any",
                "description": "Identity passthrough — downstream may chain.",
            },
        ],
        "config_schema": {
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Result key the runner reports out under.",
                },
            },
            "required": ["name"],
        },
        "description": (
            "A workflow-level output sink. Whatever connects here is "
            "what the workflow Run returns to the caller. Use one Output "
            "node per result key. The runner reports the bound value "
            "under `config.name`."
        ),
        "examples": [
            {
                "input": {"value": 42},
                "output": {"value": 42},
                "note": "Pure capture — number passed back to caller.",
            },
            {
                "input": {"value": None},
                "output": {"value": None},
                "note": (
                    "Empty value — caller sees `null` for this result key. "
                    "Approval-gate UX surfaces this before commit."
                ),
            },
        ],
        "side_effects": "host_write",
        "status": "registered",
    },

    # ── llm.classify ──────────────────────────────────────────────────
    {
        "type": "llm.classify",
        "display_name": "Classify",
        "category": "ai",
        "inputs": [
            {
                "name": "value",
                "port_type": "any",
                "required": True,
                "description": "Text / data the model classifies.",
            },
        ],
        "outputs": [
            {
                "name": "label",
                "port_type": "string",
                "description": "Predicted label from the categories list.",
            },
            {
                "name": "confidence",
                "port_type": "number",
                "description": "Confidence 0..1 reported by the model.",
            },
        ],
        "config_schema": {
            "properties": {
                "categories": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Allowed labels — model picks one.",
                },
                "model": {
                    "type": "string",
                    "default": "claude-sonnet-4-5",
                },
                "instructions": {
                    "type": "string",
                    "description": "System prompt steering the classifier.",
                },
            },
            "required": ["categories"],
        },
        "description": (
            "Constrains an LLM to picking one label from a predefined "
            "list. Use when you need a clean categorical decision (room "
            "type, drawing scale band, RFI severity). Returns the label "
            "AND a confidence score for downstream gating."
        ),
        "examples": [
            {
                "input": {"value": "Living Room 220 sqft"},
                "output": {"label": "Living", "confidence": 0.97},
                "note": "Standard happy path — room-type classification.",
            },
            {
                "input": {"value": "<network timeout>"},
                "output": {
                    "status": "error",
                    "error": "request_timeout: model unreachable after 30s",
                },
                "note": "Network failure — typed error, retry / fall back.",
            },
        ],
        "side_effects": "network",
        "status": "registered",
    },

    # ── llm.complete ──────────────────────────────────────────────────
    {
        "type": "llm.complete",
        "display_name": "Complete",
        "category": "ai",
        "inputs": [
            {
                "name": "prompt",
                "port_type": "string",
                "required": True,
                "description": "Prompt text sent to the model.",
            },
        ],
        "outputs": [
            {
                "name": "text",
                "port_type": "string",
                "description": "Model's generated text response.",
            },
        ],
        "config_schema": {
            "properties": {
                "model": {
                    "type": "string",
                    "default": "claude-sonnet-4-5",
                },
                "temperature": {
                    "type": "number",
                    "default": 0.7,
                    "minimum": 0,
                    "maximum": 2,
                },
                "system": {
                    "type": "string",
                    "description": "Optional system prompt.",
                },
                "max_tokens": {
                    "type": "integer",
                    "default": 1024,
                },
            },
        },
        "description": (
            "One-shot completion — sends the prompt to the configured "
            "model and returns the response text. No tool use; for "
            "tool-using turns use `llm.complete_with_tools`. Pair with "
            "Constant to pin the system prompt."
        ),
        "examples": [
            {
                "input": {"prompt": "Summarise this RFI in 1 line."},
                "output": {"text": "Slab edge offset query for grid B-3."},
                "note": "Standard happy path — short summary.",
            },
            {
                "input": {"prompt": "<too long for model context>"},
                "output": {
                    "status": "error",
                    "error": "context_length_exceeded: 200000 tokens > model limit",
                },
                "note": "Context overflow — typed error, caller chunks input.",
            },
        ],
        "side_effects": "network",
        "status": "registered",
    },

    # ── control.if ────────────────────────────────────────────────────
    {
        "type": "control.if",
        "display_name": "If Branch",
        "category": "logic",
        "inputs": [
            {
                "name": "value",
                "port_type": "any",
                "required": True,
                "description": "Input forwarded to the matching branch.",
            },
            {
                "name": "condition",
                "port_type": "boolean",
                "required": True,
                "description": "Truthy → `true_out`; falsy → `false_out`.",
            },
        ],
        "outputs": [
            {
                "name": "true_out",
                "port_type": "any",
                "description": "Emits `value` when `condition` is truthy.",
            },
            {
                "name": "false_out",
                "port_type": "any",
                "description": "Emits `value` when `condition` is falsy.",
            },
        ],
        "config_schema": {
            "properties": {
                "passthrough_falsy": {
                    "type": "boolean",
                    "default": False,
                    "description": "If true, empty/zero/none also count as falsy.",
                },
            },
        },
        "description": (
            "Routes `value` to one of two output branches based on the "
            "`condition` input. Used for skill-internal branching, "
            "approval gating, and dirty-tracking. Only one output fires "
            "per run."
        ),
        "examples": [
            {
                "input": {"value": "<10 Walls>", "condition": True},
                "output": {"true_out": "<10 Walls>", "false_out": None},
                "note": "True branch fires.",
            },
        ],
        "side_effects": "pure",
        "status": "registered",
    },

    # ── filter.apply ──────────────────────────────────────────────────
    {
        "type": "filter.apply",
        "display_name": "Filter",
        "category": "shape",
        "inputs": [
            {
                "name": "items",
                "port_type": "list",
                "required": True,
                "description": "List to filter.",
            },
        ],
        "outputs": [
            {
                "name": "kept",
                "port_type": "list",
                "description": "Items where the predicate matched.",
            },
            {
                "name": "dropped",
                "port_type": "list",
                "description": "Items that did not match (use for diagnostics).",
            },
        ],
        "config_schema": {
            "properties": {
                "field": {
                    "type": "string",
                    "description": "Object field to test (empty = the item itself).",
                },
                "op": {
                    "type": "string",
                    "enum": [
                        "truthy", "eq", "neq", "gt", "lt", "gte", "lte",
                        "contains", "startswith", "endswith", "matches",
                    ],
                    "default": "truthy",
                },
                "match": {
                    "description": "Comparison value (ignored for `truthy`).",
                },
            },
        },
        "description": (
            "Keeps items from `items` whose `field` satisfies the "
            "`op match` predicate. Dropped items go to `dropped` so the "
            "graph can audit what was removed. Works on flat lists OR "
            "lists of objects."
        ),
        "examples": [
            {
                "input": {"items": [{"h": 3}, {"h": 9}, {"h": 12}]},
                "output": {
                    "kept": [{"h": 9}, {"h": 12}],
                    "dropped": [{"h": 3}],
                },
                "note": "Filter walls by height >= 8 (config: field=h, op=gte, match=8).",
            },
        ],
        "side_effects": "pure",
        "status": "registered",
    },

    # ── llm.complete_with_tools ───────────────────────────────────────
    {
        "type": "llm.complete_with_tools",
        "display_name": "Complete with Tools",
        "category": "ai",
        "inputs": [
            {
                "name": "prompt",
                "port_type": "string",
                "required": True,
                "description": "Prompt sent to the model.",
            },
        ],
        "outputs": [
            {
                "name": "text",
                "port_type": "string",
                "description": "Final assistant text after tool loop.",
            },
            {
                "name": "tool_calls",
                "port_type": "list",
                "description": "Tool invocations the model ran during the turn.",
            },
        ],
        "config_schema": {
            "properties": {
                "model": {
                    "type": "string",
                    "default": "claude-sonnet-4-5",
                },
                "tools_allowlist": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Tool names the model may call (empty = all).",
                },
                "max_iterations": {
                    "type": "integer",
                    "default": 8,
                    "description": "Cap on tool-use round-trips per turn.",
                },
            },
        },
        "description": (
            "Multi-turn LLM call with tool access. The model can call "
            "the ArchHub tool surface (library_*, graph_*, connectors, "
            "speckle_*) and the runner loops until the model emits a "
            "final assistant text. Pair with library_* tools for "
            "composer-style workflows."
        ),
        "examples": [
            {
                "input": {"prompt": "List the walls in level 1."},
                "output": {
                    "text": "Found 12 walls on Level 1.",
                    "tool_calls": [
                        {"name": "revit__list_walls",
                         "args": {"level": "Level 1"}},
                    ],
                },
                "note": "Happy path — one tool call resolves the question.",
            },
            {
                "input": {"prompt": "List the walls — but Revit is closed."},
                "output": {
                    "status": "error",
                    "error": "host_unreachable: revit not running",
                },
                "note": "Host offline mid-tool-loop — typed error bubbles up.",
            },
        ],
        "side_effects": "network",
        "status": "registered",
    },

    # ── control.merge ─────────────────────────────────────────────────
    {
        "type": "control.merge",
        "display_name": "Merge",
        "category": "logic",
        "inputs": [
            {
                "name": "a",
                "port_type": "any",
                "description": "First branch input — emits if non-null.",
            },
            {
                "name": "b",
                "port_type": "any",
                "description": "Second branch input — emits if `a` was null.",
            },
        ],
        "outputs": [
            {
                "name": "value",
                "port_type": "any",
                "description": "The first non-null of (a, b).",
            },
        ],
        "config_schema": {
            "properties": {
                "strict_null": {
                    "type": "boolean",
                    "default": True,
                    "description": "If false, treat 0 / '' / [] as null too.",
                },
            },
        },
        "description": (
            "Funnel two upstream branches into one output. Emits the "
            "first non-null input. Use to recombine branches after an "
            "If split or to fall back from a primary source to a "
            "secondary one."
        ),
        "examples": [
            {
                "input": {"a": None, "b": "fallback"},
                "output": {"value": "fallback"},
                "note": "Branch a was null → emit b.",
            },
        ],
        "side_effects": "pure",
        "status": "registered",
    },

    # ── control.foreach ───────────────────────────────────────────────
    {
        "type": "control.foreach",
        "display_name": "For Each",
        "category": "logic",
        "inputs": [
            {
                "name": "items",
                "port_type": "list",
                "required": True,
                "description": "List the body executes once per item.",
            },
            {
                "name": "body",
                "port_type": "any",
                "description": (
                    "Subgraph reference — runs once per item with the "
                    "current item bound as `item`."
                ),
            },
        ],
        "outputs": [
            {
                "name": "results",
                "port_type": "list",
                "description": "Per-item body output, in input order.",
            },
        ],
        "config_schema": {
            "properties": {
                "parallel": {
                    "type": "boolean",
                    "default": False,
                    "description": "Run iterations in parallel (no order guarantee).",
                },
                "halt_on_error": {
                    "type": "boolean",
                    "default": True,
                },
            },
        },
        "description": (
            "Iterates `body` over `items`. Each iteration binds the "
            "current item; the body's output is collected into "
            "`results`. Optionally parallel. Standard map operation — "
            "use with Filter + Transform to build pipeline queries."
        ),
        "examples": [
            {
                "input": {
                    "items": [{"id": 1}, {"id": 2}, {"id": 3}],
                    "body": "<subgraph>",
                },
                "output": {"results": ["a-1", "a-2", "a-3"]},
                "note": "Map each item via a small subgraph that prefixes id.",
            },
        ],
        "side_effects": "pure",
        "status": "registered",
    },

    # ── transform.apply ───────────────────────────────────────────────
    {
        "type": "transform.apply",
        "display_name": "Transform",
        "category": "shape",
        "inputs": [
            {
                "name": "items",
                "port_type": "list",
                "required": True,
                "description": "Input list to reshape.",
            },
        ],
        "outputs": [
            {
                "name": "value",
                "port_type": "any",
                "description": "Reshaped result — list or scalar depending on op.",
            },
        ],
        "config_schema": {
            "properties": {
                "op": {
                    "type": "string",
                    "enum": [
                        "identity", "count", "first", "last", "unique",
                        "sort", "reverse", "flatten", "pluck", "sum",
                    ],
                    "default": "identity",
                },
                "field": {
                    "type": "string",
                    "description": "Field for pluck / sum / sort by-key.",
                },
                "reverse": {
                    "type": "boolean",
                    "default": False,
                    "description": "Reverse sort order.",
                },
            },
            "required": ["op"],
        },
        "description": (
            "Reshape / summarise a list. `op` picks the transform — "
            "count, pluck a field, sort, deduplicate, flatten nested "
            "lists, sum a numeric field. Pair with Filter to build "
            "pipeline-style queries on host data."
        ),
        "examples": [
            {
                "input": {"items": [{"name": "A"}, {"name": "B"}, {"name": "A"}]},
                "output": {"value": [{"name": "A"}, {"name": "B"}]},
                "note": "Deduplicate (config: op=unique, field=name).",
            },
        ],
        "side_effects": "pure",
        "status": "registered",
    },
]


# ---------------------------------------------------------------------------
# Bootstrap


def seed_library() -> dict[str, int]:
    """Register every PRIMITIVE_SEED into the in-process library.

    Returns `{registered: N, skipped: M, rejected: K}` for caller diagnostics.
    Idempotent: re-seeding an already-seeded registry counts as `skipped`.
    A seed that fails validator (drift bug) is counted as `rejected` and
    logged — never raised, so bootstrap NEVER kills the bridge boot.
    """
    from library import (
        DuplicateTypeError,
        RegistrationError,
        create_node_type,
    )

    registered = 0
    skipped = 0
    rejected = 0
    for spec in PRIMITIVE_SEEDS:
        try:
            create_node_type(spec)
            registered += 1
        except DuplicateTypeError:
            skipped += 1
        except RegistrationError:
            # A drift bug — seed no longer satisfies the validator. Skip
            # so bootstrap survives; the test layer catches the drift via
            # test_all_primitive_seeds_validate.
            rejected += 1
    return {
        "registered": registered, "skipped": skipped, "rejected": rejected,
    }
