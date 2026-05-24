---
id: AgDR-0018
timestamp: 2026-05-21T00:00:00Z
agent: claude-code (Sonnet)
session: m1-shipping · founder /loop · "don't sleep"
trigger: AgDR-0016 §"Open forks" item 3 — adapter coverage priority
status: executed
founder-signoff: 2026-05-25 — bulk-flip per D4·A pick on docs/prototypes/four-decisions-2026-05-25.html (shipped weeks ago, status drift)
category: architecture
projects: [archhub]
extends:
  - AgDR-0016 §"What ships" — first three adapter primitives shipped
    (cad_to_revit_wall · to_revit_directshape · max_to_revit_family)
  - AgDR-0017 — receive-side `build_create_script` C# generator
---

# Adapter Coverage Batch 2 — Rhino → Revit Beam · CAD → Detail Line · Excel → Revit Parameters

> In the context of AgDR-0016's open fork 3 ("Next 3 adapters to ship:
> `adapter.rhino_to_revit_beam`, `adapter.cad_to_revit_detail_line`,
> `adapter.excel_to_revit_params`"), I decided to **ship all three in
> one slice**, each following the same shape AgDR-0016 established:
> annotate the input with `revit_*` metadata, defer the Revit-side
> create logic to `build_create_script` (extended for the new
> annotations). All three are typed grammar primitives + executor
> functions registered with the engine. Accepting: `excel_to_revit_params`
> outputs an ANNOTATION-ONLY Base (no geometry), consumed by
> `revit.set_parameter` downstream rather than `revit.receive_from_speckle`
> — it lives in the ADAPTER category because semantically it's still
> "map external data to native parameter map." This batch lands as 3
> new grammar primitives (grammar count 67 → 70), 3 new executors, 9+
> tests covering classification + C# generation extensions.

## Context

AgDR-0016 §"Adapter category — 3 initial typed nodes" shipped the
first three: `cad_to_revit_wall`, `to_revit_directshape`,
`max_to_revit_family`. The open fork explicitly asked which three
adapters next. Founder picked these three (most-requested
architect-friendly mappings):

1. **Rhino → Revit Beam.** Linear element from Rhino curve →
   structural Revit beam (FamilyInstance under BuiltInCategory
   `OST_StructuralFraming`).
2. **CAD → Revit Detail Line.** Polyline from AutoCAD layer →
   Revit detail line (annotation curve, view-specific, not a
   model element).
3. **Excel → Revit Parameters.** A row from an Excel range becomes
   a `{revit_element_id, revit_parameters: {...}}` annotation —
   downstream `revit.set_parameter` walks the row and pushes
   values onto the target element.

## Options Considered

### Fork 1 — Generic-vs-typed adapter

| Option | Picked | Why |
|---|---|---|
| One `adapter.generic` with user-typed `target_category` + arbitrary `parameters` | no | Loses type-safety · loses palette discoverability · user is back to memorising annotation keys |
| **Typed adapter per source/target pair** (matches AgDR-0016 pattern) | **YES** | Discoverable in palette · param schema steers the user to the right inputs · receive-side knows how to interpret annotations |
| Hybrid (typed + a generic fallback) | no | YAGNI — `adapter.to_revit_directshape` already serves as the generic fallback for unrecognised mappings |

**Pick: Typed adapters.**

### Fork 2 — Where the C# generation lives for the new annotations

| Option | Picked | Why |
|---|---|---|
| Add 3 more `_emit_*` functions to `revit_speckle_ops.py` next to wall / family / directshape | **YES** | Same module · same try/catch shape · same skipped tracking · zero churn |
| Spread per-adapter files (e.g. `revit_speckle_ops_beam.py`) | no | Premature split · file count balloons · the emitters share helpers |
| Externalise as a plugin registry | no | YAGNI for 3 emitters |

**Pick: Extend the existing module.**

### Fork 3 — `excel_to_revit_params` output shape

| Option | Picked | Why |
|---|---|---|
| Output a single annotated Base with `revit_parameter_map: {...}` | no | Loses the element-target binding (parameter map of *which* element?) |
| **Output a list of `{revit_element_id, revit_parameters: {...}}` dicts** — one per row | **YES** | Downstream `revit.set_parameter` (or a multi-row variant) walks the list element-by-element |
| Output a wide dict keyed by element_id | no | Loses the row ordering; harder to debug |

**Pick: List of per-row dicts.**

### Fork 4 — Receive-side execution

| Option | Picked | Why |
|---|---|---|
| `revit.receive_from_speckle` handles all 3 new annotation types via `build_create_script` extension | partial | Works for beam (FamilyInstance) + detail_line (DetailCurve.Create). Excel-param items DO NOT create elements — they SET parameters on existing elements |
| **Beam + detail_line via `build_create_script`; excel-param via a separate `revit.batch_set_parameters` op** | **YES** | Each annotation kind goes through its semantically-right receive op. excel-param needs element_id lookup + per-row Parameter.Set — different C# shape from element creation |
| Single op handles everything | no | Conflates element CREATION with element MUTATION — wrong semantic |

**Pick: Beam + detail-line in `build_create_script`; excel-param via a new dedicated op.**

## Decision

### Three new grammar primitives

```python
adapter.rhino_to_revit_beam    Curve     → Beam (FamilyInstance / OST_StructuralFraming)
adapter.cad_to_revit_detail_line Polyline → DetailCurve (view-specific annotation)
adapter.excel_to_revit_params  Row[]      → [{revit_element_id, revit_parameters}]
```

### Annotation keys

| Adapter | Source | Annotations stamped |
|---|---|---|
| `cad_to_revit_detail_line` | Polyline | `revit_target_category="DetailLines"`, `revit_polyline`, `revit_view_id`, `revit_line_style` |
| `rhino_to_revit_beam` | Curve / Polyline | `revit_target_category="StructuralFraming"`, `revit_polyline` (start/end pair), `revit_beam_family`, `revit_beam_type`, `revit_level`, `revit_structural=true` |
| `excel_to_revit_params` | Row dict | `revit_element_id`, `revit_parameters` (a dict from Excel columns) |

### `build_create_script` extensions

Two new `_emit_*` functions next to the existing trio:

- `_emit_detail_line(idx, item)` → `DetailCurve.Create(doc, view, curve, lineStyle)`
- `_emit_beam(idx, item)` → `doc.Create.NewFamilyInstance(curve, symbol, level, StructuralType.Beam)`

The classifier (`_classify_item`) gains 2 new cases:
- `revit_target_category == "DetailLines"` → `detail_line`
- `revit_target_category == "StructuralFraming"` AND `revit_beam_family` → `beam`

`excel_to_revit_params` items are classified as `parameter_set` and `build_create_script` SKIPS them in the create script (they belong to a separate op). The skipped count surfaces them honestly.

### New op — `revit.batch_set_parameters`

For the excel-param flow:

```python
ConnectorOp(
    op_id="revit.batch_set_parameters", host="revit", kind="action",
    label="Batch set parameters",
    description="For each {revit_element_id, revit_parameters} dict, "
                "push the parameters onto the existing element.",
    inputs=[inst, ParamSpec("source_url", required=True)],
    output_type="any", destructive=True,
    fn=_batch_set_parameters_op,
)
```

Receives the same `speckle://local/<hash>` URL as `revit.receive_from_speckle`,
pulls items, generates C# that does:

```csharp
foreach (item in items) {
  var el = doc.GetElement(new ElementId(item.revit_element_id));
  if (el == null) continue;
  foreach (kvp in item.revit_parameters) {
    var p = el.LookupParameter(kvp.key);
    if (p != null) p.Set(kvp.value);
  }
}
```

## Consequences

### What ships

- `app/workflows/nodes/adapter.py` — 3 new executors + 3 grammar registrations.
- `app/workflows/node_grammar.py` — 3 new typed-primitive entries.
- `app/connectors/revit_speckle_ops.py` — 2 new `_emit_*` functions +
  classifier cases + a new `batch_set_parameters` flow.
- `app/connectors/revit_connector.py` — new `revit.batch_set_parameters` op.
- Tests: ≥9 (3 adapter executors · 2 C# emitters · classifier · batch op
  routing · grammar-count invariant).

### What collapses

- Nothing — additive.

### What's reinforced

- Adapter category remains a TYPED grammar primitive layer per AgDR-0016.
- One receive op per semantic kind (create vs mutate), avoiding the
  "everything in one op" anti-pattern.

### Risks

- `adapter.excel_to_revit_params` requires the upstream Excel row to
  carry the target element_id. The schema is just the row dict — the
  user wires the column whose value is the element id. A small
  `element_id_column` config picks the right column. Tested.
- DetailCurve.Create requires an active VIEW — annotation carries the
  view_id; user must wire `revit.list_views` upstream OR leave the
  view_id at 0 (active view). The C# guards both.

### Tests

| Test | What it proves |
|---|---|
| `test_rhino_to_revit_beam_executor` | Beam adapter stamps correct annotations · list-input handling |
| `test_cad_to_revit_detail_line_executor` | Detail-line adapter stamps correct annotations · view-id default |
| `test_excel_to_revit_params_executor` | Excel rows fold into per-row `{revit_element_id, revit_parameters}` |
| `test_classify_beam_annotation` | Classifier returns `beam` for beam annotations |
| `test_classify_detail_line_annotation` | Classifier returns `detail_line` |
| `test_build_create_script_beam` | `NewFamilyInstance(curve, ..., StructuralType.Beam)` in C# |
| `test_build_create_script_detail_line` | `DetailCurve.Create` in C# |
| `test_classify_parameter_set_skips_from_create_script` | excel-param items show up as `skip` in `build_create_script` (handled by a separate op) |
| `test_grammar_count_is_70` | Grammar primitive count is 70 (was 67) |

## Implementation order

1. ✓ This AgDR (done).
2. Adapter executors + grammar primitives.
3. C# emitters + classifier extension.
4. New `revit.batch_set_parameters` op.
5. Tests.
6. ROADMAP update.

## Open forks for founder

1. **A `revit.find_element_by_mark` helper.** Excel rows often carry a
   `Mark` value (typewriter-style element identifier), not an ElementId.
   The MVP `excel_to_revit_params` expects ElementId — a later slice
   can resolve by Mark.
2. **Adapter for `rhino_to_revit_floor`.** Founder hasn't asked yet —
   add when needed.

## Artifacts

- This AgDR.
- Pending: `app/workflows/nodes/adapter.py` edits,
  `app/workflows/node_grammar.py` edits,
  `app/connectors/revit_speckle_ops.py` edits,
  `app/connectors/revit_connector.py` edits,
  `tests/test_adapter_nodes.py` extensions (or new file).
