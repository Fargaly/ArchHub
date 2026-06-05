"""ArchHub node grammar — the canonical primitive node set.

Single source of truth for the redesigned node system. See
`docs/NODE_GRAMMAR.md` for the rationale.

The old model enumerated 80 `LM_LIBRARY` nodes the engine never caught
up to — 0 of 80 ran. This module replaces that catalogue with a SMALL
set of primitive node *kinds*. Users compose everything from these
primitives plus saved Skills.

A primitive is NOT a single node type — it is a family. Its concrete
engine `type` (the registry key `WorkflowRunner` dispatches on) is
selected by the primitive's defining parameter. Example: the `ai`
primitive resolves to `conversation.chat` / `llm.complete` /
`llm.complete_with_tools` / `llm.classify` depending on its `action`.

`engine_type(kind, params)` returns the registry type a placed node
dispatches to (or `None` for the connector / note special cases).

Honesty guarantee: `engine_types` only ever names types that are
*actually registered* in `workflows.registry`. The grounding test
(`tests/test_node_grammar.py`) asserts this — so this file can never
drift back into an aspirational catalogue. A primitive whose executor
does not exist yet is `NEEDS_EXECUTOR` with an empty `engine_types`
and a roadmap-slice note; it is not placeable until the slice ships.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# ── Build status ──────────────────────────────────────────────────────
READY = "ready"                  # every engine type it resolves to exists
NEEDS_EXECUTOR = "needs-executor"  # executor must be built — see `note`
UX_ONLY = "ux-only"              # never executes (e.g. a sticky note)

# Primitives that run via a path OTHER than the node registry. As of
# slice 2 the `connector` master node became a real registry executor
# (`connector.run`), so this set is empty — kept as the mechanism for
# any future non-registry kind. The grounding test exempts members of
# this set from the registry-resolution check.
NON_REGISTRY_KINDS: set[str] = set()


@dataclass(frozen=True)
class Primitive:
    """One primitive node kind in the grammar."""
    kind: str          # canvas-facing node kind, e.g. "connector"
    display: str       # human label
    cat: str           # display group / colour family
    selector: str      # param whose value picks the engine type ("" = fixed)
    engine_types: dict[str, str]  # selector-value -> REGISTERED engine type
                                  # ("" key = the fixed type when selector is "")
    status: str        # READY | NEEDS_EXECUTOR | UX_ONLY
    note: str = ""        # engineering note (internal — NOT a UI string)
    params: tuple = ()    # default {k,v,type} rows a placed node lands with
    blurb: str = ""       # short, plain, user-facing line — the palette subtitle
    hidden: bool = False  # if True: kept for engine resolution + legacy
                          # graph back-compat, but skipped from the palette
                          # payload (typed nodes have taken over the slot).

    def engine_type_for(self, params: dict | None) -> str | None:
        """The registry type this node dispatches on, given its params.
        None for non-registry kinds, UX-only kinds, or an unresolved
        selector value."""
        if not self.engine_types:
            return None
        if not self.selector:
            return self.engine_types.get("")
        params = params or {}
        return self.engine_types.get(str(params.get(self.selector, "")))


# ── The grammar — typed-node catalogue per docs/NODE_GRAMMAR.md.
# Order = library display order. Categories hold MULTIPLE typed nodes.
# `input` + `constant` below stay HIDDEN — they resolve legacy saved
# graphs to engine types but no longer surface in the palette; the
# typed INPUT nodes (Number / Text / Boolean / File / Color) take over
# the palette slot.
PRIMITIVES: list[Primitive] = [
    # Legacy back-compat — hidden from palette but kept for engine
    # resolution so graphs saved before slice H still cook.
    Primitive(
        "input", "Input", "input", "",
        {"": "input.parameter"}, READY,
        "legacy — replaced by `parameter` typed input",
        params=({"k": "name", "v": "input", "type": "text"},
                {"k": "default", "v": "", "type": "text"}),
        blurb="A value you feed into the graph",
        hidden=True,
    ),
    Primitive(
        "constant", "Constant", "input", "",
        {"": "data.constant"}, READY,
        "legacy — replaced by typed Number / Text / Boolean / File / Color",
        params=({"k": "value", "v": "", "type": "text"},),
        blurb="A fixed value",
        hidden=True,
    ),
    # ── INPUT category — typed value sources (slice H).
    # Each maps to `data.constant` with `value_type` pre-set so the
    # engine knows the output shape and the canvas can render the
    # right widget. The grammar entry IS the typed node — engine type
    # is shared, kind is unique.
    Primitive(
        "number", "Number", "input", "",
        {"": "data.constant"}, READY,
        "data.constant typed as number — slider/spinner widget",
        params=({"k": "value", "v": 0, "type": "number"},
                {"k": "value_type", "v": "number", "type": "text"}),
        blurb="A number value",
    ),
    Primitive(
        "text", "Text", "input", "",
        {"": "data.constant"}, READY,
        "data.constant typed as string",
        params=({"k": "value", "v": "", "type": "text"},
                {"k": "value_type", "v": "string", "type": "text"}),
        blurb="A text value",
    ),
    Primitive(
        "boolean", "Boolean", "input", "",
        {"": "data.constant"}, READY,
        "data.constant typed as boolean — toggle widget",
        # Param type 'boolean' (not 'bool') so the inspector's FullParam
        # widget dispatches to the toggle renderer rather than text.
        params=({"k": "value", "v": False, "type": "boolean"},
                {"k": "value_type", "v": "boolean", "type": "text"}),
        blurb="True or false",
    ),
    Primitive(
        "file", "File", "input", "",
        {"": "data.constant"}, READY,
        "data.constant typed as file path — file-picker widget",
        params=({"k": "value", "v": "", "type": "text"},
                {"k": "value_type", "v": "string", "type": "text"},
                {"k": "extensions", "v": "", "type": "text"}),
        blurb="A file on disk",
    ),
    Primitive(
        "color", "Color", "input", "",
        {"": "data.constant"}, READY,
        "data.constant typed as hex colour — color-picker widget",
        params=({"k": "value", "v": "#d97757", "type": "text"},
                {"k": "value_type", "v": "string", "type": "text"}),
        blurb="A colour value",
    ),
    Primitive(
        "parameter", "Parameter", "input", "",
        {"": "input.parameter"}, READY,
        "input.parameter — run-time-bound input the caller supplies",
        params=({"k": "name", "v": "input", "type": "text"},
                {"k": "type", "v": "string", "type": "text"},
                {"k": "default", "v": "", "type": "text"}),
        blurb="A run-time-bound input",
    ),
    Primitive(
        "connector", "Connector", "connector", "",
        {"": "connector.run"}, READY,
        "connector.run — `host`+`op` select the op; folds the run_op "
        "path into the runner",
        params=({"k": "host", "v": "", "type": "text"},
                {"k": "op", "v": "", "type": "text"}),
        blurb="Run any app — Revit, Excel, Outlook…",
    ),
    Primitive(
        "ai", "AI", "ai", "action",
        {
            "chat": "conversation.chat",
            "complete": "llm.complete",
            "tools": "llm.complete_with_tools",
            "classify": "llm.classify",
        }, READY,
        "legacy — replaced by typed AI Chat / AI Complete / "
        "AI Classify / AI Tools (AgDR-0019 loose-end fix)",
        params=({"k": "action", "v": "chat", "type": "text"},),
        blurb="Ask Claude — chat, complete, classify",
        hidden=True,
    ),
    # ── AI category — typed-per-action primitives (AgDR-0019).
    # Mirrors the Slice H+I pattern: one node per action so the
    # right-panel rail surfaces ONLY the action's relevant params.
    Primitive(
        "ai_chat", "AI Chat", "ai", "",
        {"": "conversation.chat"}, READY,
        "conversation.chat — chat UI · streaming · tool calls",
        params=({"k": "model", "v": "auto", "type": "text"},),
        blurb="Chat with Claude — streaming + tool-use",
    ),
    Primitive(
        "ai_complete", "AI Complete", "ai", "",
        {"": "llm.complete"}, READY,
        "llm.complete — single-shot prompt → text",
        params=({"k": "model", "v": "auto", "type": "text"},
                {"k": "prompt", "v": "", "type": "text"}),
        blurb="Single-shot LLM completion",
    ),
    Primitive(
        "ai_classify", "AI Classify", "ai", "",
        {"": "llm.classify"}, READY,
        "llm.classify — pick one of N options",
        params=({"k": "model", "v": "auto", "type": "text"},
                {"k": "options", "v": "", "type": "text"}),
        blurb="Classify text into N options",
    ),
    Primitive(
        "ai_tools", "AI Tools", "ai", "",
        {"": "llm.complete_with_tools"}, READY,
        "llm.complete_with_tools — tool-use loop · optional whitelist",
        params=({"k": "model", "v": "auto", "type": "text"},
                {"k": "prompt", "v": "", "type": "text"},
                {"k": "allowed_tools", "v": "", "type": "text"}),
        blurb="LLM with tool-use loop",
    ),
    # M4 foundation (AgDR-0021) — auditable + replayable Composer turn.
    Primitive(
        "ai_plan", "AI Plan", "ai", "",
        {"": "ai.plan"}, READY,
        "ai.plan — wraps tool-use + persists per-cook to "
        ".archhub/plans/<id>.json; replay=True reads the cache",
        params=({"k": "model", "v": "auto", "type": "text"},
                {"k": "prompt", "v": "", "type": "text"},
                {"k": "replay", "v": False, "type": "boolean"},
                {"k": "allowed_tools", "v": "", "type": "text"}),
        blurb="Persisted, replayable AI turn",
    ),
    # Legacy back-compat — hidden from palette but kept for engine
    # resolution so graphs saved before slice I still cook.
    Primitive(
        "logic", "Logic", "logic", "kind",
        {
            "if": "control.if",
            "merge": "control.merge",
            "foreach": "control.foreach",
            "switch": "control.switch",
        }, READY,
        "legacy — replaced by typed If / For Each / Switch / Merge",
        params=({"k": "kind", "v": "if", "type": "text"},),
        blurb="Branch, merge, or loop",
        hidden=True,
    ),
    # ── LOGIC category — typed control-flow nodes (slice I).
    # Each maps to its specific control.* engine — no selector.
    Primitive(
        "if", "If/Else", "logic", "",
        {"": "control.if"}, READY,
        "control.if — predicate routes value to true_out / false_out",
        params=({"k": "passthrough_falsy", "v": False, "type": "boolean"},),
        blurb="Route value by predicate",
    ),
    Primitive(
        "foreach", "For Each", "logic", "",
        {"": "control.foreach"}, READY,
        "control.foreach — iterate body per item",
        params=({"k": "parallel", "v": False, "type": "boolean"},),
        blurb="Iterate over a list",
    ),
    Primitive(
        "switch", "Switch", "logic", "",
        {"": "control.switch"}, READY,
        "control.switch — multi-way branch by key value",
        params=({"k": "cases", "v": "", "type": "text"},),
        blurb="Multi-way branch",
    ),
    Primitive(
        "merge", "Merge", "logic", "",
        {"": "control.merge"}, READY,
        "control.merge — first non-null of (a, b)",
        params=({"k": "strict_null", "v": True, "type": "boolean"},),
        blurb="Combine two branches",
    ),
    # ── OUTPUT category — typed sinks (slice I follow-up).
    # Each maps to its specific engine: result-key sink, file write,
    # console log, or final display.
    Primitive(
        "result", "Result", "output", "",
        {"": "output.parameter"}, READY,
        "output.parameter — graph result key",
        params=({"k": "name", "v": "result", "type": "text"},),
        blurb="The graph's result",
    ),
    Primitive(
        "file_save", "File Save", "output", "",
        {"": "output.file"}, READY,
        "output.file — write to disk; JSON for objects/lists",
        params=({"k": "path", "v": "", "type": "text"},
                {"k": "append", "v": False, "type": "boolean"}),
        blurb="Save to a file",
    ),
    Primitive(
        "console", "Console", "output", "",
        {"": "output.console"}, READY,
        "output.console — log to engine trace",
        params=({"k": "label", "v": "", "type": "text"},),
        blurb="Log to console",
    ),
    Primitive(
        "display", "Display", "output", "",
        {"": "output.display"}, READY,
        "output.display — final display sink",
        params=({"k": "as", "v": "auto", "type": "text"},),
        blurb="Show the final value",
    ),
    # Legacy back-compat — hidden, kept for engine resolution of
    # graphs saved before the OUTPUT split.
    Primitive(
        "output", "Output", "output", "",
        {"": "output.parameter"}, READY,
        "legacy — replaced by typed Result / File Save / Console / Display",
        params=({"k": "name", "v": "result", "type": "text"},),
        blurb="The graph's result",
        hidden=True,
    ),
    Primitive(
        "skill", "Skill", "skill", "",
        {"": "subgraph.user"}, READY,
        "subgraph.user — a saved Skill graph placed as ONE node "
        "(recursive; subgraph reference semantics)",
        blurb="A saved skill, reused as one node",
    ),
    Primitive(
        "filter", "Filter", "shape", "",
        {"": "filter.apply"}, READY,
        "filter.apply — keep/drop list items by a field/op/match "
        "predicate",
        params=({"k": "field", "v": "", "type": "text"},
                {"k": "op", "v": "truthy", "type": "text"},
                {"k": "match", "v": "", "type": "text"}),
        blurb="Keep only the items you want",
    ),
    # Legacy back-compat — hidden, kept for engine resolution.
    Primitive(
        "transform", "Transform", "shape", "",
        {"": "transform.apply"}, READY,
        "legacy — replaced by typed Sort / Group / Unique / Pluck / …",
        params=({"k": "op", "v": "identity", "type": "text"},
                {"k": "field", "v": "", "type": "text"}),
        blurb="Reshape or summarise data",
        hidden=True,
    ),
    # ── SHAPE category — typed pure-transform nodes (slice I).
    # All map to `transform.apply` with `op` pre-set.
    Primitive(
        "sort", "Sort", "shape", "",
        {"": "transform.apply"}, READY,
        "transform.apply op=sort — sort list by field",
        params=({"k": "op", "v": "sort", "type": "text"},
                {"k": "field", "v": "", "type": "text"},
                {"k": "reverse", "v": False, "type": "boolean"}),
        blurb="Sort a list",
    ),
    Primitive(
        "unique", "Unique", "shape", "",
        {"": "transform.apply"}, READY,
        "transform.apply op=unique — dedupe",
        params=({"k": "op", "v": "unique", "type": "text"},
                {"k": "field", "v": "", "type": "text"}),
        blurb="Deduplicate a list",
    ),
    Primitive(
        "pluck", "Pluck", "shape", "",
        {"": "transform.apply"}, READY,
        "transform.apply op=pluck — extract field from objects",
        params=({"k": "op", "v": "pluck", "type": "text"},
                {"k": "field", "v": "", "type": "text"}),
        blurb="Extract a field",
    ),
    Primitive(
        "count", "Count", "shape", "",
        {"": "transform.apply"}, READY,
        "transform.apply op=count — list length",
        params=({"k": "op", "v": "count", "type": "text"},),
        blurb="Count items",
    ),
    Primitive(
        "flatten", "Flatten", "shape", "",
        {"": "transform.apply"}, READY,
        "transform.apply op=flatten — nested lists to flat list",
        params=({"k": "op", "v": "flatten", "type": "text"},),
        blurb="Flatten nested lists",
    ),
    Primitive(
        "first", "First", "shape", "",
        {"": "transform.apply"}, READY,
        "transform.apply op=first — first item only",
        params=({"k": "op", "v": "first", "type": "text"},),
        blurb="First item",
    ),
    Primitive(
        "last", "Last", "shape", "",
        {"": "transform.apply"}, READY,
        "transform.apply op=last — last item only",
        params=({"k": "op", "v": "last", "type": "text"},),
        blurb="Last item",
    ),
    # ── AgDR-0040 slice 2 — aggregate primitives. The modular-logic
    # vocab grew 4 list ops (reduce / accumulate / sort / group_by);
    # three surface here so the palette exposes them. `data.sort` is
    # registered + executable but the existing shape/sort (transform.apply
    # op=sort) already owns the palette slot — same UX.
    Primitive(
        "reduce", "Reduce", "shape", "",
        {"": "data.reduce"}, READY,
        "data.reduce — fold a list to one value "
        "(sum/product/min/max/count/concat/and/or)",
        params=({"k": "op", "v": "sum", "type": "text"},),
        blurb="Fold a list into one value",
    ),
    Primitive(
        "accumulate", "Accumulate", "shape", "",
        {"": "data.accumulate"}, READY,
        "data.accumulate — running fold; emits the intermediate series",
        params=({"k": "op", "v": "sum", "type": "text"},),
        blurb="Running fold over a list",
    ),
    Primitive(
        "group_by", "Group by", "shape", "",
        {"": "data.group_by"}, READY,
        "data.group_by — partition a list of records by a key field",
        params=({"k": "key", "v": "", "type": "text"},),
        blurb="Partition a list by key",
    ),
    # ── stem-rebuild Phase-0 — the reconcile core. `data.join` matches
    # two lists on a key and partitions into matched / left_only /
    # right_only; the relational match that turns a bespoke reconcile
    # code-blob (BBC4 QC, Excel↔Revit sync, DD↔DWG match) into a cell.
    Primitive(
        "join", "Join", "shape", "",
        {"": "data.join"}, READY,
        "data.join — match two lists on a key → matched / left_only / "
        "right_only (how = inner/left/right/outer)",
        params=({"k": "key", "v": "", "type": "text"},
                {"k": "how", "v": "inner", "type": "text"}),
        blurb="Reconcile two lists on a key",
    ),
    # ── stem-rebuild Phase-0 — the per-node verify gate + branch primitive.
    # `verify.assert` runs a predicate over `value` → passed / report /
    # value(pass-through). Wire `passed` into If/Switch to branch, or let the
    # ROMA court gate a leaf on it. Reuses code.expression / math.op (no new
    # evaluator). cat="logic" — it lives with the control.* branch primitives.
    Primitive(
        "assert", "Assert", "logic", "",
        {"": "verify.assert"}, READY,
        "verify.assert — predicate over value → passed/report/value "
        "(branch primitive + per-node verify gate)",
        params=({"k": "mode", "v": "expression", "type": "text"},
                {"k": "expr", "v": "value", "type": "text"}),
        blurb="Check a condition, branch on pass/fail",
    ),
    # ── stem-rebuild Phase-0 — the PROPERTY-checker sibling of verify.assert.
    # `sense.extract` reads a property of `value` (length / type / keys /
    # exists / is_empty / in_bounds / contains / shape) → value(the property) /
    # passed / report. assert tests a relation; sense reads an attribute. Wire
    # `passed` into If/Switch to branch, or feed the extracted `value` (e.g. a
    # row count) downstream. Reuses math.op for the in_bounds fences (no new
    # evaluator). cat="logic" — it lives with the control.* branch primitives.
    Primitive(
        "sense", "Sense", "logic", "",
        {"": "sense.extract"}, READY,
        "sense.extract — read a property of value (length/type/keys/exists/"
        "is_empty/in_bounds/contains/shape) → value/passed/report",
        params=({"k": "op", "v": "length", "type": "text"},),
        blurb="Read a property of a value, branch on it",
    ),
    # ── stem-rebuild Phase-0 — the IO read cell. `fs.list` is a READ-ONLY
    # directory listing → typed file-rows {path,name,ext,size,is_dir,mtime}.
    # Turns the raw os.walk/glob blob that file-walk jobs (BBC4 submittal QC)
    # dropped to into a stem cell. Pure primitive (no fs host — scandir is
    # in-process, needs no probe/auth). List only — write/move are LATER cells.
    Primitive(
        "list_files", "List Files", "input", "",
        {"": "fs.list"}, READY,
        "fs.list — READ-ONLY directory listing → typed file-rows "
        "{path,name,ext,size,is_dir,mtime} + count (glob/recursive)",
        params=({"k": "path", "v": "", "type": "text"},
                {"k": "pattern", "v": "", "type": "text"}),
        blurb="List files in a folder",
    ),
    # ── stem-rebuild Phase-0 — the IO read cell's twin. `fs.read` is a
    # READ-ONLY single-file read → decoded `text` + metrics {size, bytes_read,
    # truncated, lines, ext}. fs.list finds files, fs.read reads one. Turns the
    # raw open()/read()/decode blob into a stem cell. Pure (no fs host — open is
    # in-process, needs no probe/auth). Read only — write/move are LATER cells.
    Primitive(
        "read_file", "Read File", "input", "",
        {"": "fs.read"}, READY,
        "fs.read — READ-ONLY single-file read → decoded text + metrics "
        "{size, bytes_read, truncated, lines, ext} (encoding + max_bytes cap)",
        params=({"k": "path", "v": "", "type": "text"},
                {"k": "encoding", "v": "utf-8", "type": "text"}),
        blurb="Read a file's contents",
    ),
    # ── stem-rebuild Phase-0 — the IO-write cell. `fs.write` is the write half
    # of the fs stem family (fs.list finds, fs.read reads, fs.write writes):
    # give it a path + `text`; it encodes with `encoding` and writes the bytes,
    # returning the abspath + {bytes_written, created}. Side-effecting by design
    # but clobber-guarded (overwrite flag) + total-tolerant (a bad input is a
    # typed error, never a raise). Pure cell (no fs host — open is in-process).
    Primitive(
        "write_file", "Write File", "output", "",
        {"": "fs.write"}, READY,
        "fs.write — WRITE text to a file → abspath + {bytes_written, created} "
        "(encoding; overwrite guard; make_dirs)",
        params=({"k": "path", "v": "", "type": "text"},
                {"k": "overwrite", "v": False, "type": "boolean"}),
        blurb="Write text to a file",
    ),
    # ── stem-rebuild Phase-0 — the IO-move cell. `fs.move` is the move half of
    # the fs stem family: give it `src` + `dst`; it relocates src to dst
    # (shutil.move — handles files + whole folders, across filesystems),
    # returning the abspaths + a `moved` flag. Side-effecting by design but
    # clobber-guarded (overwrite flag) + total-tolerant (a bad input is a typed
    # error, never a raise). Pure cell (no fs host — shutil is in-process).
    Primitive(
        "move_file", "Move File", "output", "",
        {"": "fs.move"}, READY,
        "fs.move — MOVE / rename a file or directory → abspaths + `moved` "
        "(overwrite guard; make_dirs)",
        params=({"k": "src", "v": "", "type": "text"},
                {"k": "dst", "v": "", "type": "text"}),
        blurb="Move or rename a file",
    ),
    # ── stem-rebuild Phase-0 — the reconcile dedupe cell. `data.dedupe` drops
    # duplicate rows, keeping one per identity in stable first-seen order
    # (key = field to dedupe on; keep = first/last). The pipeline twin of
    # data.join — it collapses a doubled submittal log / re-imported param dump
    # to its distinct rows. Distinct from group_by, which partitions instead.
    Primitive(
        "dedupe", "Dedupe", "shape", "",
        {"": "data.dedupe"}, READY,
        "data.dedupe — drop duplicate rows, keep one per identity in stable "
        "first-seen order (key = field; keep = first/last)",
        params=({"k": "key", "v": "", "type": "text"},
                {"k": "keep", "v": "first", "type": "text"}),
        blurb="Remove duplicate rows",
    ),
    # ── stem-rebuild Phase-0 — the JSON codec cell. `data.json` is one
    # mode-selected engine: mode=parse reads `text` → `value`; mode=stringify
    # reads `value` → JSON `text`. The JSON twin of text.op (one engine, op in
    # config) — turns the ad-hoc json.loads/json.dumps blob into a stem cell.
    # Pure (json is stdlib, in-process — no host/probe/auth).
    Primitive(
        "json_codec", "JSON", "shape", "",
        {"": "data.json"}, READY,
        "data.json — one mode-selected JSON codec: parse (text→value) or "
        "stringify (value→text), with indent + sort_keys knobs",
        params=({"k": "mode", "v": "parse", "type": "text"},),
        blurb="Parse or stringify JSON",
    ),
    # ── MATH category — typed arithmetic / comparison / logic (slice J).
    # All map to `math.op` with `op` pre-set. One engine, many typed nodes.
    Primitive(
        "add", "Add", "math", "",
        {"": "math.op"}, READY,
        "math.op op=add — a + b",
        params=({"k": "op", "v": "add", "type": "text"},),
        blurb="Add two numbers",
    ),
    Primitive(
        "subtract", "Subtract", "math", "",
        {"": "math.op"}, READY,
        "math.op op=sub — a − b",
        params=({"k": "op", "v": "sub", "type": "text"},),
        blurb="Subtract two numbers",
    ),
    Primitive(
        "multiply", "Multiply", "math", "",
        {"": "math.op"}, READY,
        "math.op op=mul — a × b",
        params=({"k": "op", "v": "mul", "type": "text"},),
        blurb="Multiply two numbers",
    ),
    Primitive(
        "divide", "Divide", "math", "",
        {"": "math.op"}, READY,
        "math.op op=div — a ÷ b",
        params=({"k": "op", "v": "div", "type": "text"},),
        blurb="Divide two numbers",
    ),
    Primitive(
        "modulo", "Modulo", "math", "",
        {"": "math.op"}, READY,
        "math.op op=mod — a % b",
        params=({"k": "op", "v": "mod", "type": "text"},),
        blurb="Remainder",
    ),
    Primitive(
        "round", "Round", "math", "",
        {"": "math.op"}, READY,
        "math.op op=round — round to nearest integer",
        params=({"k": "op", "v": "round", "type": "text"},),
        blurb="Round a number",
    ),
    Primitive(
        "equal", "Equal", "math", "",
        {"": "math.op"}, READY,
        "math.op op=eq — a == b returns boolean",
        params=({"k": "op", "v": "eq", "type": "text"},),
        blurb="Test equality",
    ),
    Primitive(
        "greater", "Greater Than", "math", "",
        {"": "math.op"}, READY,
        "math.op op=gt — a > b returns boolean",
        params=({"k": "op", "v": "gt", "type": "text"},),
        blurb="a > b?",
    ),
    Primitive(
        "less", "Less Than", "math", "",
        {"": "math.op"}, READY,
        "math.op op=lt — a < b returns boolean",
        params=({"k": "op", "v": "lt", "type": "text"},),
        blurb="a < b?",
    ),
    Primitive(
        "and_op", "And", "math", "",
        {"": "math.op"}, READY,
        "math.op op=and — boolean and",
        params=({"k": "op", "v": "and", "type": "text"},),
        blurb="Boolean AND",
    ),
    Primitive(
        "or_op", "Or", "math", "",
        {"": "math.op"}, READY,
        "math.op op=or — boolean or",
        params=({"k": "op", "v": "or", "type": "text"},),
        blurb="Boolean OR",
    ),
    Primitive(
        "not_op", "Not", "math", "",
        {"": "math.op"}, READY,
        "math.op op=not — boolean not",
        params=({"k": "op", "v": "not", "type": "text"},),
        blurb="Boolean NOT",
    ),
    # ── TEXT category — typed string operations (slice J).
    # All map to `text.op` with `op` pre-set.
    Primitive(
        "concat", "Concat", "text", "",
        {"": "text.op"}, READY,
        "text.op op=concat — a + separator + b",
        params=({"k": "op", "v": "concat", "type": "text"},
                {"k": "separator", "v": "", "type": "text"}),
        blurb="Join two strings",
    ),
    Primitive(
        "split", "Split", "text", "",
        {"": "text.op"}, READY,
        "text.op op=split — split by separator",
        params=({"k": "op", "v": "split", "type": "text"},
                {"k": "separator", "v": ",", "type": "text"}),
        blurb="Split by separator",
    ),
    Primitive(
        "replace", "Replace", "text", "",
        {"": "text.op"}, READY,
        "text.op op=replace — pattern → replacement",
        params=({"k": "op", "v": "replace", "type": "text"},
                {"k": "pattern", "v": "", "type": "text"},
                {"k": "replacement", "v": "", "type": "text"}),
        blurb="Replace text",
    ),
    Primitive(
        "format", "Format", "text", "",
        {"": "text.op"}, READY,
        "text.op op=format — Python format template",
        params=({"k": "op", "v": "format", "type": "text"},
                {"k": "template", "v": "{a}", "type": "text"}),
        blurb="Format with template",
    ),
    Primitive(
        "match", "Match", "text", "",
        {"": "text.op"}, READY,
        "text.op op=match — regex match returns boolean",
        params=({"k": "op", "v": "match", "type": "text"},
                {"k": "pattern", "v": "", "type": "text"}),
        blurb="Regex match",
    ),
    # Regex ops — the text.op executor already implements regex_findall /
    # regex_match / regex_replace / regex_split (math_text.py:229-242) and lists
    # them in the op dropdown, but they had NO discoverable library primitive
    # (a user could only reach them by spawning a generic Text node + switching
    # the dropdown). Expose each by name so the library surfaces them like
    # concat/split/replace/match. (Finishes "extend text.op with regex".)
    Primitive(
        "regex_findall", "Regex Find All", "text", "",
        {"": "text.op"}, READY,
        "text.op op=regex_findall — every regex match as a list",
        params=({"k": "op", "v": "regex_findall", "type": "text"},
                {"k": "pattern", "v": "", "type": "text"},
                {"k": "ignore_case", "v": False, "type": "boolean"}),
        blurb="All regex matches → list",
    ),
    Primitive(
        "regex_match", "Regex Match", "text", "",
        {"": "text.op"}, READY,
        "text.op op=regex_match — first match: {matched, groups, group0}",
        params=({"k": "op", "v": "regex_match", "type": "text"},
                {"k": "pattern", "v": "", "type": "text"},
                {"k": "ignore_case", "v": False, "type": "boolean"}),
        blurb="First regex match + groups",
    ),
    Primitive(
        "regex_replace", "Regex Replace", "text", "",
        {"": "text.op"}, READY,
        "text.op op=regex_replace — regex sub (backrefs in repl)",
        params=({"k": "op", "v": "regex_replace", "type": "text"},
                {"k": "pattern", "v": "", "type": "text"},
                {"k": "repl", "v": "", "type": "text"},
                {"k": "ignore_case", "v": False, "type": "boolean"}),
        blurb="Regex replace",
    ),
    Primitive(
        "regex_split", "Regex Split", "text", "",
        {"": "text.op"}, READY,
        "text.op op=regex_split — split a string by a regex",
        params=({"k": "op", "v": "regex_split", "type": "text"},
                {"k": "pattern", "v": "", "type": "text"},
                {"k": "ignore_case", "v": False, "type": "boolean"}),
        blurb="Split by regex → list",
    ),
    # ── SHARE category — Speckle worksharing (M1.5).
    # Founder decision 2026-05-21: DiskTransport default, server opt-in
    # via these nodes. share.server starts the localhost Docker stack
    # on demand. share.publish / share.subscribe send / receive via
    # the wire (local always; server when URL is wired in).
    Primitive(
        "speckle_server", "Speckle Server", "share", "",
        {"": "share.server"}, READY,
        "share.server — ensures localhost Speckle Server running",
        params=({"k": "port", "v": 3000, "type": "number"},
                {"k": "auto_start", "v": True, "type": "boolean"}),
        blurb="Start local Speckle server",
    ),
    Primitive(
        "speckle_publish", "Publish to Speckle", "share", "",
        {"": "share.publish"}, READY,
        "share.publish — push value via DiskTransport + optional ServerTransport",
        params=({"k": "model_name", "v": "default", "type": "text"},
                {"k": "server_url", "v": "", "type": "text"}),
        blurb="Publish a value to Speckle",
    ),
    Primitive(
        "speckle_subscribe", "Subscribe to Speckle", "share", "",
        {"": "share.subscribe"}, READY,
        "share.subscribe — pull Base from speckle://local or http(s) URL",
        params=({"k": "refresh_interval", "v": 0, "type": "number"},),
        blurb="Pull data from Speckle",
    ),
    # ── ADAPTER category — cross-host native mapping.
    # Annotates the wired Base with target-host metadata. Speckle's
    # receive-side connector reads the annotations + creates native
    # FamilyInstance / Wall / DirectShape on the target host.
    Primitive(
        "cad_to_revit_wall", "CAD → Revit Wall", "adapter", "",
        {"": "adapter.cad_to_revit_wall"}, READY,
        "adapter.cad_to_revit_wall — annotate polyline as Revit Wall",
        params=({"k": "level", "v": "Level 1", "type": "text"},
                {"k": "wall_type", "v": "Generic - 200mm", "type": "text"},
                {"k": "height", "v": 3000, "type": "number"},
                {"k": "top_offset", "v": 0, "type": "number"},
                {"k": "structural", "v": False, "type": "boolean"}),
        blurb="CAD polyline to Revit Wall",
    ),
    Primitive(
        "to_revit_directshape", "→ Revit DirectShape", "adapter", "",
        {"": "adapter.to_revit_directshape"}, READY,
        "adapter.to_revit_directshape — generic DirectShape fallback",
        params=({"k": "target_category", "v": "Generic Models", "type": "text"},
                {"k": "category_name", "v": "ArchHub Direct", "type": "text"},
                {"k": "builtin_category", "v": "OST_GenericModel", "type": "text"}),
        blurb="Geometry to Revit DirectShape",
    ),
    Primitive(
        "max_to_revit_family", "3ds Max → Revit Family", "adapter", "",
        {"": "adapter.max_to_revit_family"}, READY,
        "adapter.max_to_revit_family — annotate mass as Revit Family",
        params=({"k": "target_category", "v": "Mass", "type": "text"},
                {"k": "family_name", "v": "ArchHubMass", "type": "text"},
                {"k": "family_template", "v": "Metric Mass.rft", "type": "text"}),
        blurb="3ds Max mass to Revit Family",
    ),
    # Batch 2 (AgDR-0018) — 3 more typed adapters.
    Primitive(
        "cad_to_revit_detail_line", "CAD → Revit Detail Line",
        "adapter", "",
        {"": "adapter.cad_to_revit_detail_line"}, READY,
        "adapter.cad_to_revit_detail_line — view-specific annotation curve",
        params=({"k": "view_id", "v": 0, "type": "number"},
                {"k": "line_style", "v": "Thin Lines", "type": "text"}),
        blurb="CAD polyline to Revit Detail Line",
    ),
    Primitive(
        "rhino_to_revit_beam", "Rhino → Revit Beam", "adapter", "",
        {"": "adapter.rhino_to_revit_beam"}, READY,
        "adapter.rhino_to_revit_beam — curve to native StructuralFraming",
        params=({"k": "beam_family", "v": "W-Wide Flange", "type": "text"},
                {"k": "beam_type", "v": "W12X26", "type": "text"},
                {"k": "level", "v": "Level 1", "type": "text"}),
        blurb="Rhino curve to Revit Beam",
    ),
    Primitive(
        "excel_to_revit_params", "Excel → Revit Parameters",
        "adapter", "",
        {"": "adapter.excel_to_revit_params"}, READY,
        "adapter.excel_to_revit_params — row → parameter set",
        params=({"k": "element_id_column", "v": "ElementId", "type": "text"},
                {"k": "ignore_columns", "v": "", "type": "text"}),
        blurb="Excel row to Revit parameter set",
    ),
    # ── SLICE L (AgDR-0020) — typed Code primitive (legacy with
    # `mode` selector kept HIDDEN for back-compat saved graphs).
    Primitive(
        "code", "Code", "code", "mode",
        {"expression": "code.expression",
         "python":     "code.python"}, READY,
        "legacy — replaced by typed Code Expression / Code Python "
        "(removes the mode-dropdown per Slice I typed-per-action pattern)",
        params=({"k": "mode", "v": "expression", "type": "text"},
                {"k": "expr", "v": "a + b", "type": "text"},
                {"k": "body", "v": "result = a", "type": "text"},
                {"k": "safe_mode", "v": True, "type": "boolean"}),
        blurb="Python expression or function body",
        hidden=True,
    ),
    # SLICE I pattern applied to CODE — typed-per-action so the
    # right panel shows only the relevant params (no `mode` dropdown).
    Primitive(
        "code_expr", "Code Expression", "code", "",
        {"": "code.expression"}, READY,
        "code.expression — one-line Python eval with a/b/c inputs",
        params=({"k": "expr", "v": "a + b", "type": "text"},
                {"k": "safe_mode", "v": True, "type": "boolean"}),
        blurb="Python expression",
    ),
    Primitive(
        "code_py", "Code Python", "code", "",
        {"": "code.python"}, READY,
        "code.python — multi-line body; `result = ...` is the output",
        params=({"k": "body", "v": "result = a", "type": "text"},
                {"k": "safe_mode", "v": True, "type": "boolean"}),
        blurb="Python function body",
    ),
    # Legacy back-compat — hidden, kept for engine resolution.
    Primitive(
        "watch", "Watch", "watch", "",
        {"": "watch.preview"}, READY,
        "legacy — replaced by typed Table / List / JSON / Image",
        params=({"k": "as", "v": "json", "type": "text"},),
        blurb="Preview data as it flows",
        hidden=True,
    ),
    # ── WATCH category — typed inline viewers (slice I).
    # All map to `watch.preview` with `as` pre-set (slice E renderer).
    Primitive(
        "table", "Table", "watch", "",
        {"": "watch.preview"}, READY,
        "watch.preview as=table — auto-columned grid",
        params=({"k": "as", "v": "table", "type": "text"},),
        blurb="Preview as table",
    ),
    Primitive(
        "list", "List", "watch", "",
        {"": "watch.preview"}, READY,
        "watch.preview as=list — bullet list",
        params=({"k": "as", "v": "list", "type": "text"},),
        blurb="Preview as list",
    ),
    Primitive(
        "json", "JSON", "watch", "",
        {"": "watch.preview"}, READY,
        "watch.preview as=json — pretty JSON",
        params=({"k": "as", "v": "json", "type": "text"},),
        blurb="Preview as JSON",
    ),
    Primitive(
        "image", "Image", "watch", "",
        {"": "watch.preview"}, READY,
        "watch.preview as=image — image preview",
        params=({"k": "as", "v": "image", "type": "text"},),
        blurb="Preview an image",
    ),
    # Legacy back-compat — hidden, kept for engine resolution.
    Primitive(
        "trigger", "Trigger", "trigger", "",
        {"": "trigger.emit"}, READY,
        "legacy — replaced by typed Manual Run / Schedule / Webhook / File Watch",
        params=({"k": "on", "v": "manual", "type": "text"},),
        blurb="Start the graph",
        hidden=True,
    ),
    # ── TRIGGER category — typed event sources (slice I).
    # cat="trigger" splits them out from WATCH viewers in the palette.
    Primitive(
        "manual_run", "Manual Run", "trigger", "",
        {"": "trigger.emit"}, READY,
        "trigger.emit on=manual — user-driven start",
        params=({"k": "on", "v": "manual", "type": "text"},),
        blurb="Run on click",
    ),
    Primitive(
        "schedule", "Schedule", "trigger", "",
        {"": "trigger.emit"}, READY,
        "trigger.emit on=schedule — cron string; auto-fire daemon ships separately",
        params=({"k": "on", "v": "schedule", "type": "text"},
                {"k": "cron", "v": "", "type": "text"}),
        blurb="Run on a schedule",
    ),
    Primitive(
        "webhook", "Webhook", "trigger", "",
        {"": "trigger.emit"}, READY,
        "trigger.emit on=webhook — HTTP listener ships separately",
        params=({"k": "on", "v": "webhook", "type": "text"},
                {"k": "path", "v": "/hook", "type": "text"}),
        blurb="Run on HTTP POST",
    ),
    Primitive(
        "file_watch", "File Watch", "trigger", "",
        {"": "trigger.emit"}, READY,
        "trigger.emit on=file — file watcher ships separately",
        params=({"k": "on", "v": "file", "type": "text"},
                {"k": "path", "v": "", "type": "text"}),
        blurb="Run on file change",
    ),
    Primitive(
        "note", "Note", "note", "",
        {}, UX_ONLY,
        "never executes",
        params=({"k": "text",
                 "v": "_Note — double-click to edit_",
                 "type": "markdown"},),
        blurb="A sticky note",
    ),
    # AgDR-0007: reroute is a wire-organising dot — engine identity.
    # Tiny visual on the canvas (24x24 round dot). Grammar count
    # stays small (13 ≤ 20 of test_grammar_is_small).
    Primitive(
        "reroute", "Reroute", "note", "",
        {"": "data.passthrough"}, READY,
        "data.passthrough — wire-organising dot; identity passthru",
        blurb="A wire-organising dot",
    ),
]

# The founder's primitive families (the 2026-05-18 intent). The grammar
# must cover each; the grounding test asserts coverage so a future edit
# cannot quietly drop one.
FOUNDER_FAMILIES = ("input", "output", "connector", "ai", "watch", "logic")

_BY_KIND: dict[str, Primitive] = {p.kind: p for p in PRIMITIVES}


def get_primitive(kind: str) -> Primitive | None:
    return _BY_KIND.get(kind)


def engine_type(kind: str, params: dict | None = None) -> str | None:
    """Registry type a placed node of `kind` dispatches on, given its
    params. None for connector (run_op path), note (UX-only), and any
    not-yet-built primitive.

    Identity fallback (AgDR-0041 / Tier 1 + Tier 2 / shipped Skills):
    if `kind` is not a hardcoded grammar primitive but IS itself a
    registered engine type (registry or library), use it directly.
    This is what lets a dropped `render.comfyui` / `skill.revit_hero_render`
    node resolve without inflating PRIMITIVES with every typed primitive."""
    p = _BY_KIND.get(kind)
    if p is not None:
        return p.engine_type_for(params)
    # Identity fallback — kind == registered type.
    try:
        from .registry import get as _reg_get
        if _reg_get(kind):
            return kind
    except Exception:
        pass
    try:
        import library as _lib
        if _lib.inspect(kind):
            return kind
    except Exception:
        pass
    return None


# Type-prefix → palette category map. New synthesized grammar entries
# (Tier 1 host primitives, Tier 2 render/vision/mesh/anim/llm typed
# nodes, shipped Skills from the library) use this to pick which
# collapsible section they appear under in the palette. Order doesn't
# matter — longest prefix wins.
_PREFIX_CAT: list[tuple[str, str]] = [
    ("skill.",   "skill"),
    ("host.",    "connector"),
    ("render.",  "ai"),
    ("vision.",  "ai"),
    ("mesh.",    "ai"),
    ("anim.",    "ai"),
    ("llm.",     "ai"),
]

# Short user-facing blurbs per synthesized kind. Hand-written so the
# palette stays scannable — descriptions from the spec are too long
# AND tend to include dev jargon (registry / executor / subgraph) that
# the palette UX test refuses. New kinds get a generated fallback.
_SYNTH_BLURBS: dict[str, str] = {
    # Tier 1 typed host nodes (AgDR-0041 P1)
    "host.import_mesh":     "Drop a mesh into the host",
    "host.read_walls":      "Read walls from the host",
    "host.export_viewport": "Export host viewport + depth",
    "host.run_script":      "Run a script in the host",
    # Tier 2 typed primitives over comfyui + dashscope
    "render.comfyui":     "Run a ComfyUI workflow",
    "render.image_edit":  "Image-to-image edit (Qwen)",
    "render.task_poll":   "Poll a DashScope async task",
    "vision.describe":    "Describe an image (Qwen-VL)",
    "mesh.from_image":    "Single image → 3D mesh",
    "anim.wan_i2v":       "Image → video (Wan)",
    "llm.qwen":           "Cheap text completion (Qwen)",
    # Shipped Skills
    "skill.revit_hero_render":    "Revit view → hero render",
    "skill.photo_to_rhino_mass":  "Photo → host mass block",
    "skill.drone_to_revit_walls": "Drone shots → Revit walls",
}


def _prefix_cat(t: str) -> str:
    for pre, cat in _PREFIX_CAT:
        if t.startswith(pre):
            return cat
    return "node"


def _synth_blurb(kind: str, display: str) -> str:
    """Short palette subtitle for a synthesized entry. Hand-written
    entries take priority; otherwise fall back to display capped at
    40 chars, then a final generic."""
    if kind in _SYNTH_BLURBS:
        return _SYNTH_BLURBS[kind]
    if display and len(display) <= 40:
        return display
    return (display or kind)[:40]


def _synthesized_primitives() -> list[dict]:
    """Grammar entries auto-surfaced from the registry + library so the
    palette reflects every shipped primitive / Skill without manually
    extending PRIMITIVES.

    Inclusion rules:
    - Registry types whose prefix is in `_PREFIX_CAT` (Tier 1 host_typed
      + Tier 2 render/vision/mesh/anim/llm primitives) — EXCEPT those
      already covered by a hardcoded primitive's `engine_types` (don't
      double-list `llm.complete` etc., which the `ai` primitive resolves
      to via selector).
    - Library Capability specs (the 3 shipped Skills + any user-saved).

    Skips: anything already in `_BY_KIND`, anything already named by a
    primitive's `engine_types`, anything without a registered executor.
    """
    out: list[dict] = []
    # Build the "already covered by a Primitive" set so we don't shadow
    # the existing selector-driven entries.
    covered: set = set()
    for p in PRIMITIVES:
        for t in p.engine_types.values():
            if t:
                covered.add(t)
    # 1. Registry-backed typed primitives.
    try:
        from .registry import all_specs as _all_specs
        for spec in _all_specs():
            t = getattr(spec, "type", "") or ""
            if not t or t in covered or t in _BY_KIND:
                continue
            cat = _prefix_cat(t)
            if cat == "node":
                # Not a known prefix — skip; we only want the deliberate
                # surfaces (host/render/vision/mesh/anim/llm). Other
                # registry types (data.constant etc.) are PRIMITIVES.
                continue
            out.append({
                "kind": t, "display": getattr(spec, "display_name", t) or t,
                "cat": cat, "selector": "", "engine_types": {"": t},
                "status": READY,
                "note": "auto-surfaced from registry",
                "blurb": _synth_blurb(
                    t, getattr(spec, "display_name", "") or t),
                "ports": _ports_for(t),
                "config_schema": _config_schema_for(t),   # ← ADDITIVE
                "params": [],
                "_source": "registry",
            })
    except Exception:
        pass
    # 2. Library-backed Skills (impl.kind=graph composites).
    try:
        import library as _lib
        for s in _lib.list_node_types(category=None):
            t = s.get("type", "") or ""
            if not t or t in covered or t in _BY_KIND:
                continue
            # Only the Skills surface here — library may also hold raw
            # primitives (seeded), but those are already PRIMITIVES.
            cat = _prefix_cat(t)
            if cat == "node" and not t.startswith("skill."):
                continue
            spec = _lib.inspect(t) or {}
            inputs = spec.get("inputs") or []
            outputs = spec.get("outputs") or []

            def _to_port(p: dict) -> dict:
                name = p.get("name") or p.get("id") or ""
                pt = (p.get("port_type") or p.get("type")
                      or "any")
                return {"id": name, "type": str(pt).upper()}
            out.append({
                "kind": t,
                "display": spec.get("display_name") or s.get("name") or t,
                "cat": cat, "selector": "", "engine_types": {"": t},
                "status": READY,
                "note": "auto-surfaced from library",
                "blurb": _synth_blurb(
                    t, spec.get("display_name") or s.get("name") or t),
                "ports": {"in":  [_to_port(p) for p in inputs],
                          "out": [_to_port(p) for p in outputs]},
                # Library Capability specs derive no config_schema today
                # (audit's "graph-Capability I/O derive" gap; out of scope)
                # → empty schema means the inspector falls through to the
                # flat-param rendering, exactly as before.
                "config_schema": {},
                "params": [],
                "_source": "library",
            })
    except Exception:
        pass
    return out


def _ports_for(engine_t: str) -> dict:
    """The {in, out} ports of an engine type, read from its registry
    NodeSpec. Empty when the type is not registered. The canvas needs
    port ids that MATCH the engine port names — wires reference port
    ids and the runner reads inputs by that name — so the palette
    sources ports from the engine, never invents them."""
    if not engine_t:
        return {"in": [], "out": []}
    try:
        from .registry import get as _reg_get
        tup = _reg_get(engine_t)
    except Exception:
        tup = None
    if not tup:
        return {"in": [], "out": []}
    spec = tup[0]

    def _p(ports) -> list[dict]:
        out: list[dict] = []
        for prt in ports or []:
            ptype = getattr(getattr(prt, "type", None), "name", None) or "ANY"
            out.append({"id": getattr(prt, "name", ""), "type": ptype})
        return out
    return {"in": _p(spec.inputs), "out": _p(spec.outputs)}


def _config_schema_for(engine_t: str) -> dict:
    """The config_schema of an engine type, read from its registry
    NodeSpec. Empty {} when the type is not registered. Additive twin
    of _ports_for — the canvas renders each property as a typed field
    (string→text, number→number, boolean→checkbox, options→select) so a
    placed cell (map/join/assert/…) is TUNABLE on the canvas, not a flat
    read-only param list. The fields write back into node.params, which
    the engine folds to config via `_params_to_config` (unchanged)."""
    if not engine_t:
        return {}
    try:
        from .registry import get as _reg_get
        tup = _reg_get(engine_t)
    except Exception:
        tup = None
    if not tup:
        return {}
    schema = getattr(tup[0], "config_schema", None)
    return dict(schema) if isinstance(schema, dict) else {}


def grammar_payload() -> list[dict]:
    """Serialisable grammar — what the bridge exposes to the JSX canvas
    so the library palette is built from ONE source (no JS-side copy
    that can drift). Each entry carries the engine ports (from the
    registry) the canvas needs to draw + wire a placed node. Consumed
    by the `get_node_grammar` bridge slot.

    Returns hardcoded PRIMITIVES first (palette display order matters)
    then `_synthesized_primitives()` — Tier 1 host_typed + Tier 2
    render/vision/mesh/anim/llm + shipped Skills. Synthesized entries
    let new types land in the palette without manual PRIMITIVES edits."""
    out: list[dict] = []
    for p in PRIMITIVES:
        if p.hidden:
            # Hidden primitives stay in PRIMITIVES for engine resolution
            # + legacy graph back-compat (e.g. `input` / `constant` before
            # slice H typed-node split) but never surface in the palette.
            continue
        # Representative engine type for the port shape. Selector
        # primitives (ai/logic) refine ports when the selector value
        # changes — that refinement is handled canvas-side.
        rep = next(iter(p.engine_types.values()), "")
        out.append({
            "kind": p.kind, "display": p.display, "cat": p.cat,
            "selector": p.selector, "engine_types": dict(p.engine_types),
            "status": p.status, "note": p.note, "blurb": p.blurb,
            "ports": _ports_for(rep),
            "config_schema": _config_schema_for(rep),   # ← ADDITIVE
            "params": [dict(x) for x in p.params],
        })
    # AgDR-0041 / Tier 0/1/2 — surface registry + library entries.
    out.extend(_synthesized_primitives())
    return out


# ── canvas → engine adapter ───────────────────────────────────────────
def _params_to_config(params) -> dict:
    """Fold a canvas node's `params` into the flat `config` dict the
    engine executors read. Canvas params are a list of `{k, v, ...}`;
    an already-dict form (engine-native nodes) passes through."""
    if isinstance(params, dict):
        return dict(params)
    cfg: dict = {}
    for p in params or []:
        if isinstance(p, dict) and "k" in p:
            cfg[p["k"]] = p.get("v")
    return cfg


# ── Slice C3 — group nesting → recursive member-set ──────────────────
def expand_group_members(group_id: str, all_groups: list,
                          _visited: set | None = None,
                          _depth: int = 0) -> set:
    """Recursive node-id set for a group — walks `childGroupIds`,
    returns the flat union of every descendant LEAF node id. Pure:
    same input → same output, no mutation.

    Cycle-safe: visited-set + 16-level depth cap. A group that
    references itself (directly or indirectly) returns its
    truncated descendants — no `RecursionError`."""
    if _visited is None:
        _visited = set()
    if group_id in _visited or _depth > 16:
        return set()
    _visited = _visited | {group_id}
    g = next((x for x in (all_groups or []) if x.get("id") == group_id),
             None)
    if not g:
        return set()
    out: set = set(g.get("nodeIds") or [])
    for cid in (g.get("childGroupIds") or []):
        out |= expand_group_members(cid, all_groups, _visited,
                                     _depth + 1)
    return out


def would_create_cycle(parent_id: str, candidate_child_id: str,
                        all_groups: list) -> bool:
    """True iff adding `candidate_child_id` to
    `parent_id.childGroupIds` would close a cycle in the group
    tree. Two cycle types:
      (a) parent == candidate (self-reference);
      (b) parent is an ancestor of candidate already (candidate
          is descended from parent; adding it back creates a
          loop).
    Use BEFORE mutating to refuse the operation safely."""
    if parent_id == candidate_child_id:
        return True
    seen: set = set()
    # Walk the candidate's subtree (descendants). If parent is in
    # the subtree, adding candidate as parent's child creates a
    # cycle.
    stack = [candidate_child_id]
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        if cur == parent_id:
            return True
        g = next((x for x in (all_groups or [])
                  if x.get("id") == cur), None)
        if not g:
            continue
        for cid in (g.get("childGroupIds") or []):
            stack.append(cid)
    return False


# ── Slice C2 — group collapse → boundary-port auto-promotion ─────────
def _promoted_ports_for(group: dict, nodes: list, wires: list,
                         all_groups: list | None = None) -> dict:
    """Boundary-port promotion for a collapsed group.

    A member-node port is BOUNDARY if either (a) it carries no wire OR
    (b) the wire's counter-end node is NOT in `group.nodeIds`. Boundary
    inbound ports become group `in` sockets; boundary outbound ports
    become group `out` sockets. Order is deterministic = traversal over
    `group.nodeIds` × engine port order. Pure function — same inputs
    yield identical promotion every call.

    Returns `{"ins": [...], "outs": [...]}` where each entry is
    `{groupSocket, memberId, portName, portType}`.

    `groupSocket` id encoding = `<groupId>:in:<idx>` / `<groupId>:out:<idx>`.
    The index is stable across re-collapses (function of member set +
    wires).

    Slice C3 (AgDR-0006): when `all_groups` is passed AND the group
    has `childGroupIds`, the member-set is RECURSIVE (every descendant
    leaf node, via `expand_group_members`). The boundary check
    then promotes ports whose counter-end is OUTSIDE the entire
    recursive subtree."""
    gid = group.get("id") or ""
    if all_groups and (group.get("childGroupIds") or []):
        # Recursive member-set via the group tree. Iteration order
        # is the union of (declared nodeIds) + (descendants in
        # nodeIds order), deterministic across re-collapses.
        leaf_set = expand_group_members(gid, all_groups)
        ordered: list[str] = []
        # Preserve nodeIds order, then append leaves not already
        # listed (in stable name order).
        for nid in group.get("nodeIds") or []:
            if nid in leaf_set and nid not in ordered:
                ordered.append(nid)
        for nid in sorted(leaf_set - set(ordered)):
            ordered.append(nid)
        member_ids = ordered
        member_set = leaf_set
    else:
        member_ids = list(group.get("nodeIds") or [])
        member_set = set(member_ids)
    by_id = {n.get("id"): n for n in nodes or []}

    def _wire_src(w):
        f = w.get("from") or [w.get("src_node"), w.get("src_port")]
        f = list(f) + [None, None]
        return (f[0], f[1])

    def _wire_dst(w):
        t = w.get("to") or [w.get("dst_node"), w.get("dst_port")]
        t = list(t) + [None, None]
        return (t[0], t[1])

    wires = list(wires or [])
    ins: list[dict] = []
    outs: list[dict] = []
    for mid in member_ids:
        node = by_id.get(mid)
        if not node:
            continue
        engine_t = node.get("type")
        if not engine_t:
            kind = node.get("kind") or node.get("cat") or ""
            cfg = (node["config"] if isinstance(node.get("config"), dict)
                   else _params_to_config(node.get("params")))
            engine_t = engine_type(kind, cfg)
        ports = _ports_for(engine_t or "")
        for prt in ports.get("in") or []:
            port_name = prt.get("id") or ""
            incoming = [w for w in wires
                        if _wire_dst(w)[0] == mid
                        and _wire_dst(w)[1] == port_name]
            external = (not incoming) or any(
                _wire_src(w)[0] not in member_set for w in incoming)
            if external:
                ins.append({
                    "groupSocket": f"{gid}:in:{len(ins)}",
                    "memberId": mid,
                    "portName": port_name,
                    "portType": prt.get("type") or "ANY",
                })
        for prt in ports.get("out") or []:
            port_name = prt.get("id") or ""
            outgoing = [w for w in wires
                        if _wire_src(w)[0] == mid
                        and _wire_src(w)[1] == port_name]
            external = (not outgoing) or any(
                _wire_dst(w)[0] not in member_set for w in outgoing)
            if external:
                outs.append({
                    "groupSocket": f"{gid}:out:{len(outs)}",
                    "memberId": mid,
                    "portName": port_name,
                    "portType": prt.get("type") or "ANY",
                })
    return {"ins": ins, "outs": outs}


def expand_collapsed_groups(graph: dict) -> dict:
    """Pre-pass for `normalize_canvas_graph`: rewrite wires whose
    endpoint references a collapsed-group socket (`<gid>:in:<i>` /
    `<gid>:out:<i>`) back to the underlying member-port. The runner
    sees a FLAT graph identical to the expanded case — same cooked
    result, collapsed or not.

    No-op when no group has `collapsed=True`. Pure: returns a new
    graph, never mutates the input."""
    if not isinstance(graph, dict):
        return graph
    groups = graph.get("groups") or []
    if not any(g.get("collapsed") for g in groups):
        return graph
    nodes = graph.get("nodes") or []
    wires = graph.get("wires") or []
    rewrite: dict[str, tuple[str, str]] = {}
    for g in groups:
        if not g.get("collapsed"):
            continue
        promoted = _promoted_ports_for(g, nodes, wires,
                                         all_groups=groups)
        for p in promoted["ins"]:
            rewrite[p["groupSocket"]] = (p["memberId"], p["portName"])
        for p in promoted["outs"]:
            rewrite[p["groupSocket"]] = (p["memberId"], p["portName"])
    if not rewrite:
        return graph

    def _rewrite_endpoint(ep_id, ep_port):
        if ep_id in rewrite:
            mid, port = rewrite[ep_id]
            return mid, port
        return ep_id, ep_port

    out_wires = []
    for w in wires:
        nw = dict(w)
        # from-side
        if isinstance(nw.get("from"), (list, tuple)):
            f = list(nw["from"]) + [None, None]
            f0, f1 = _rewrite_endpoint(f[0], f[1])
            nw["from"] = [f0, f1]
        elif isinstance(nw.get("from"), dict):
            f0, f1 = _rewrite_endpoint(nw["from"].get("id"),
                                        nw["from"].get("port"))
            nw["from"] = {**nw["from"], "id": f0, "port": f1}
        elif "src_node" in nw:
            nw["src_node"], nw["src_port"] = _rewrite_endpoint(
                nw.get("src_node"), nw.get("src_port"))
        # to-side
        if isinstance(nw.get("to"), (list, tuple)):
            t = list(nw["to"]) + [None, None]
            t0, t1 = _rewrite_endpoint(t[0], t[1])
            nw["to"] = [t0, t1]
        elif isinstance(nw.get("to"), dict):
            t0, t1 = _rewrite_endpoint(nw["to"].get("id"),
                                        nw["to"].get("port"))
            nw["to"] = {**nw["to"], "id": t0, "port": t1}
        elif "dst_node" in nw:
            nw["dst_node"], nw["dst_port"] = _rewrite_endpoint(
                nw.get("dst_node"), nw.get("dst_port"))
        out_wires.append(nw)
    return {**graph, "wires": out_wires}


def normalize_canvas_graph(graph: dict) -> dict:
    """Stamp each canvas node with the engine `type` + `config` that
    `WorkflowRunner` dispatches on — the canvas/engine "one node model".

    The runner already normalises EDGES ({from,to} ↔ {src_node,...});
    only nodes need this. Rules:
      - a node that already carries a real `type` is left untouched
        (engine-native nodes);
      - otherwise `type` is resolved from the node's `kind` (new model)
        or `cat` (legacy) via `engine_type()`;
      - a node whose kind/cat does not resolve is left WITHOUT a `type`
        — the runner then returns an honest `no executor` error rather
        than fabricating a result.

    SLICE B (AgDR-0002): the four disable verbs apply HERE as graph
    rewriting — true effect, not decorative state.
      - `pinned` (with `pinned_value`): node type → `data.constant`
        of the snapshot. Highest priority.
      - `frozen` (with valid `node.cooked.value`): node type →
        `data.constant` of the cached value. (Frozen with no cooked =
        no-op until first successful cook.)
      - `bypass`: node is wire-rewired (first inbound → first
        outbound) and dropped. Multi-port nodes: only the first
        port-pair rewires; others drop. Documented limitation.
      - `preview_off`: UI-only; not engine-touched here.

    `config` is always present, folded from `params` unless already a
    dict. Pure: returns a new graph, never mutates the input.

    Slice C2: Pre-pass `expand_collapsed_groups` rewrites wires
    targeting collapsed-group sockets back to the underlying member
    port — the runner sees the same flat graph collapsed or expanded.
    """
    if not isinstance(graph, dict):
        return graph
    graph = expand_collapsed_groups(graph)
    out_nodes = []
    for n in graph.get("nodes") or []:
        n = dict(n)
        cfg = (n["config"] if isinstance(n.get("config"), dict)
               else _params_to_config(n.get("params")))
        n["config"] = cfg
        # PIN — wins over freeze; return snapshot regardless of upstream.
        # Strip the disable-verb metadata after rewriting so the runner's
        # own `node.get("frozen")` short-circuit (runner.py:422) doesn't
        # second-guess our `data.constant` rewrite. The new node is a
        # clean constant of the snapshot value.
        if n.get("pinned") and n.get("pinned_value") is not None:
            n["type"] = "data.constant"
            n["config"] = {"value": n["pinned_value"]}
            for _k in ("pinned", "pinned_value", "pinned_at",
                       "frozen", "cooked"):
                n.pop(_k, None)
        # FREEZE — return last cooked value. If no cooked, fall through.
        elif n.get("frozen") and isinstance(n.get("cooked"), dict) \
                and n["cooked"].get("value") is not None:
            n["type"] = "data.constant"
            n["config"] = {"value": n["cooked"]["value"]}
            for _k in ("frozen", "cooked"):
                n.pop(_k, None)
        elif not n.get("type"):
            kind = n.get("kind") or n.get("cat") or ""
            t = engine_type(kind, cfg)
            if t:
                n["type"] = t
        out_nodes.append(n)

    # BYPASS — graph surgery. Done in a second pass so PIN/FREEZE
    # type-stamping settles before rewiring.
    wires = list(graph.get("wires") or [])
    bypassed = {n["id"] for n in out_nodes if n.get("bypass")}
    if bypassed:
        def _src(w):
            f = w.get("from") or [w.get("src_node"), w.get("src_port")]
            f = list(f) + [None, None]
            return (f[0], f[1])

        def _dst(w):
            t = w.get("to") or [w.get("dst_node"), w.get("dst_port")]
            t = list(t) + [None, None]
            return (t[0], t[1])

        rewired = []
        for bid in bypassed:
            inbound = next((w for w in wires if _dst(w)[0] == bid),
                           None)
            outbound = next((w for w in wires if _src(w)[0] == bid),
                            None)
            if inbound and outbound:
                src_node, src_port = _src(inbound)
                dst_node, dst_port = _dst(outbound)
                rewired.append({"from": [src_node, src_port],
                                "to": [dst_node, dst_port]})
        # Drop every wire touching a bypassed node.
        wires = [w for w in wires
                 if _src(w)[0] not in bypassed
                 and _dst(w)[0] not in bypassed]
        wires.extend(rewired)
        # Drop the bypassed nodes themselves.
        out_nodes = [n for n in out_nodes if n["id"] not in bypassed]

    return {**graph, "nodes": out_nodes, "wires": wires}
