---
id: AgDR-0038
timestamp: 2026-05-22
status: proposed
category: architecture
supersedes: none
builds-on: [AgDR-0013, AgDR-0019, AgDR-0020, AgDR-0021, AgDR-0028]
---

# AgDR-0038 — Composer-driven Capability Nodes

> **Proposed.** Founder sign-off required before code (AgDR mandate).
> Drop into `ArchHub/docs/agdr/` once reviewed.

## Context

Building a domain workflow as a node graph today is O(n) hand-design. Each node
type needs, by hand: a grammar `Primitive`, a registry `NodeSpec`, an executor, a
library entry — and, for anything architecture-shaped, an AgDR. For a real
workflow (e.g. structural revision-table reconciliation) that is dozens of bespoke
nodes. The bottleneck is **node-type design**, not graphing.

The fallback — drop the logic into `code.python` nodes — produces opaque, untyped
blobs (fixed `a/b/c → result` ports, no config schema, not reusable). Rejected by
the founder as a design.

**What already exists (and must be incorporated, not wiped):**

`app/workflows/custom_nodes.py` is ~60% of the answer already:
- Declarative node specs as JSON — `{type, category, display_name, description,
  inputs[], outputs[], config_schema, code}`.
- `inputs`/`outputs` accept typed `{name, type}` → real typed `Port`s.
- `register_spec()` registers a spec to the live `registry._REGISTRY` with an
  executor synthesised by the **one generic factory** `_build_executor()`.
- Persisted to `%LOCALAPPDATA%\ArchHub\custom_nodes\*.json`, reloaded on boot.
- `delete_spec()` (AgDR-0028), `load_all()`, `list_specs()`.
- Once registered, a custom node already renders typed ports on the canvas —
  `node_grammar._ports_for()` reads ports from the registry `NodeSpec`.

So the registry, typed ports, persistence, and per-spec executor synthesis are
**already built**. Four gaps stop the Composer from using it:

1. **No Composer tool surface.** `register_spec` is reachable only from the UI
   ("MY NODES"). The Composer (`tool_engine.py` TOOLS) has no `node.create` /
   `node.place` / `graph.wire`. The Composer cannot mint or wire a node.
2. **Executor substrate is thin.** `_build_executor` handles only raw `code`
   (`execute(config, inputs, ctx)`) or passthrough. No way to wrap an existing
   connector op, no AI substrate. Most domain nodes are "call a host op with
   mapped args" — unsupported.
3. **No search → reuse → promote loop.** Custom nodes do not auto-register to the
   library; the LIBRARY-FIRST gate (AgDR-0013) is not enforced on minted nodes →
   silent duplicates, library does not grow by use.
4. **The `code` path is not sandboxed.** `_build_executor` execs with full
   `__builtins__` (line 117) despite the docstring claiming otherwise — `open`,
   `__import__` reachable. Real security hole.

This AgDR closes those four gaps. The cost is paid **once**; after it ships,
every future domain node is a Composer tool call with a data spec — **zero
per-node dev, zero per-node AgDR.** O(n) hand-design → O(1).

## Options considered

| # | Option | Verdict |
|---|--------|---------|
| 1 | Status quo — `code.python` blobs for custom logic | ✗ opaque, untyped, not reusable — founder-rejected |
| 2 | Hand-design every node type (Primitive + NodeSpec + executor + AgDR each) | ✗ the O(n) bottleneck this AgDR exists to remove |
| 3 | **Complete `custom_nodes.py` into a Composer-driven capability system** | ✓ **chosen** — builds on shipped work, one AgDR, O(1) thereafter |
| 4 | New visual human node-builder UI | ✗ deferred — solves the human path, not the Composer path; can layer on later |

## Decision

A **Capability Node** = a registered node type whose entire contract — typed
I/O, config schema, behaviour — is **data** (a JSON spec), executed by the one
generic factory. Each spec registers as its own type; the Composer authors specs
as tool calls. Four additive deltas to existing files.

### Delta 1 — Composer tool surface  (`app/tool_engine.py`)

Add to `TOOLS` (the LLM's real tool surface, Anthropic `strict: true`):

| Tool | Purpose |
|------|---------|
| `node.search(intent, io_schema)` | LIBRARY-FIRST — return registry/library hits ranked by similarity on intent + I/O shape. **Called before `node.create`.** |
| `node.create(spec)` | Validate (`_spec_from_dict`) → `register_spec` → persist. Returns `{type, inputs[], outputs[]}`. Refused if `node.search` returns a ≥0.75 match — reuse instead. |
| `node.place(type, config)` | Add an instance of any registered type to the active graph. Returns `node_id` + resolved ports. |
| `graph.wire(src_node, src_port, dst_node, dst_port)` | Add a typed edge. Type-checked via `graph.validate()` + port-type compatibility. |

A Composer turn becomes: **search → reuse or create → place → wire.** Node-type
*design* is now a tool call carrying a data spec. The Composer wires freely;
`graph.validate()` (already in `graph.py`) rejects type-incompatible or cyclic
wiring with a typed error — no fabrication (connector-honesty mandate).

### Delta 2 — typed executor substrate  (`app/workflows/custom_nodes.py`)

Replace the bare `code` key with an `impl` discriminator. `_build_executor`
dispatches on `impl.kind`:

```jsonc
"impl": {
  "kind": "python" | "connector" | "ai" | "passthrough",
  // kind=python    → { "code": "def execute(config, inputs, ctx): ..." }   (sandboxed, Delta 4)
  // kind=connector → { "host": "revit", "op": "exec", "arg_map": { ... } } → calls connector.run via ctx
  // kind=ai        → { "model": "auto", "prompt_template": "...", "output_parse": "json" }
  // kind=passthrough → {}  (current default behaviour)
}
```

`connector` is the high-value case: most domain nodes are a typed thin wrapper
over a host op — declared, not coded. The executor result is **validated against
`spec.outputs` types**; a mismatch is an honest typed error.

**Back-compat:** a spec with a top-level `code` key and no `impl` is treated as
`impl.kind = "python"`. Existing custom-node files keep working untouched.

### Delta 3 — search → reuse → promote loop  (`custom_nodes.py` + `library*.py`)

- `node.create` runs `node.search` first; a ≥0.75 similarity hit on intent + I/O
  → return the existing type, refuse the duplicate (AgDR-0013 LIBRARY-FIRST,
  now enforced for Composer-minted nodes).
- Every created Capability Node auto-registers to the library. The spec is
  modular by construction — typed I/O + `config_schema` + `description` +
  `examples` → passes `library_validator.py`.
- The library grows by use. The second time a workflow needs "extract PDF
  revision table", `node.search` finds it; no re-creation.
- **Optional harden path:** a stable, hot Capability Node can later have its
  `impl.python` body ported to a code-defined executor for performance. Optional,
  never required — the data spec is the default and is sufficient.

### Delta 4 — sandbox the python substrate  (`custom_nodes.py`)

`_build_executor` currently execs with full `__builtins__`. Fix at the root:
restricted builtins allow-list + reuse the `safe_mode` contract `code.python`
already enforces (AgDR-0020). Not a patch around a symptom — the whole class of
"a minted node reads the filesystem" closes.

### Capability spec — canonical shape

```jsonc
{
  "type": "pdf.extract_revisions",          // unique, [A-Za-z][A-Za-z0-9_.-]*
  "category": "document",
  "display_name": "PDF Revision Table",
  "description": "Extract a redline title-block revision table for a drawing.",
  "icon": "▤",
  "inputs":  [ {"name": "drawing_no", "type": "string"},
               {"name": "pdf_roots",  "type": "list"} ],
  "outputs": [ {"name": "revisions",  "type": "object"},
               {"name": "pdf_file",   "type": "path"} ],
  "config_schema": {
    "discipline": {"type": "string", "default": "Structural"},
    "match_mode": {"type": "enum", "options": ["exact","numeric_tail"], "default": "exact"}
  },
  "impl": { "kind": "python", "code": "def execute(config, inputs, ctx): ..." },
  "examples": [ {"drawing_no": "99-CC-266-370125", "pdf_roots": ["..."]} ]
}
```

`type` values in `PortType` (see `graph.py`) — `string · number · boolean ·
object · list · host · path · file · image · geometry · element · any` — so
wires are real typed wires; group-collapse, save-as-skill, type-check all keep
working unchanged (they operate on port lists, and the port list is sourced from
the spec via the existing `_ports_for` path).

## Worked example — the revision-reconciliation workflow

The two "new nodes" from `MEMO-revfix-nodes.md` are no longer hand-designed. The
Composer emits two specs:

- `pdf.extract_revisions` — `impl.kind: python`; body = `find_pdf()` +
  `extract_pdf()` from `revfix_orchestrator.py`.
- `revit.reconcile_revision_table` — `impl.kind: python`; body builds the C#
  fix script and posts it through the Revit connector via `ctx`.
  (A simpler 1:1 host-op node would use `impl.kind: connector`.)

The Composer then `node.place`s trigger / foreach / file / result (existing
types) and `graph.wire`s the lot. The graph in `revfix-prototype.html` builds
itself — no developer, no per-node AgDR.

## Consequences

**Gains**
- Node-type design becomes a Composer output (data), not a dev ticket.
- Typed throughout — real wires, type-checking, no `code.python` opacity.
- LIBRARY-FIRST enforced for minted nodes; library grows by use.
- Closes a live sandbox-escape hole.
- One AgDR. Future domain nodes need none — they are data.

**Costs / risks**
- `impl.kind=connector|ai` executors must resolve hosts/LLM through `ctx` —
  `ExecutionContext` may need a connector accessor (verify in `executor.py`).
- Similarity matching for `node.search` needs a cheap, good-enough metric
  (intent embedding + I/O-shape overlap). Start simple; tune.
- Composer can mint low-quality nodes — mitigated by the library validator and
  the search-first refusal.

**Builds on / incorporates**
- `custom_nodes.py` — extended, not replaced.
- AgDR-0013 LIBRARY-FIRST · AgDR-0019 typed nodes · AgDR-0020 node-to-code
  (`safe_mode`) · AgDR-0021 `ai.plan` (the Composer turn that emits specs is an
  `ai.plan` step — auditable + replayable) · AgDR-0028 `delete_spec`.

## Build slices

1. `impl` discriminator + `_build_executor` dispatch (`python` sandboxed,
   `passthrough`) + back-compat for bare `code`. Grounding test.
2. `impl.kind = connector` + `impl.kind = ai`.
3. Composer tools — `node.search` / `node.create` / `node.place` /
   `graph.wire` in `tool_engine.py`.
4. Search → reuse → library auto-promotion loop.

## Artifacts

| File | Change |
|------|--------|
| `app/workflows/custom_nodes.py` | `impl` discriminator; `_build_executor` dispatch; sandbox |
| `app/tool_engine.py` | `node.search/create/place`, `graph.wire` tools |
| `app/workflows/registry.py` | unchanged (already sufficient) |
| `app/workflows/executor.py` | `ExecutionContext` connector/LLM accessor if missing |
| `app/library_validator.py` | accept Capability specs as modular node types |
| `tests/test_capability_nodes.py` | new — spec round-trip, dispatch, sandbox, search-first |
| `docs/ROADMAP.md` | slices 1–4 appended |
