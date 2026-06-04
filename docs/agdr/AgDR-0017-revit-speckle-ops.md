---
id: AgDR-0017
timestamp: 2026-05-21T00:00:00Z
agent: claude-code (Sonnet)
session: m1-shipping · founder /loop till finalize · "don't sleep"
trigger: /loop next — close end-to-end Max-mass → Revit-family litmus from AgDR-0016 with the M2-Python connector ops
status: executed
status-evidence: |
  Flipped proposed → executed 2026-05-30 (governance reconciliation). SHIPPED
  as "M2-Python" — app/connectors/revit_speckle_ops.py on disk with
  send_to_speckle / receive_from_speckle / build_create_script; 2 ConnectorOps
  (revit.send_to_speckle read, revit.receive_from_speckle action+destructive)
  registered in RevitConnector.build_ops(); 21 tests + Max→Revit litmus chain
  (tests/test_litmus_max_to_revit.py) green. See ROADMAP "M2-Python ✓ SHIPPED
  2026-05-21". The deferred M2-Bundle (official Speckle Revit add-in) remains a
  separate OPEN roadmap item — it does not gate this AgDR's IPC-path decision.
category: architecture
projects: [archhub]
extends:
  - AgDR-0012 §"M2 Revit Speckle connector" line 72 — picks the
    Python-side shipping shape that doesn't block on the external
    .NET bundle
  - AgDR-0016 §"Implementation order" line 5 — "M2 · Bundle Speckle
    Revit connector (or IPC)"
---

# Revit ↔ Speckle Ops — `revit.send_to_speckle` + `revit.receive_from_speckle` · ADAPTER-Annotation → Native-Creation C# Generator

> In the context of AgDR-0016's M2 milestone ("Bundle Speckle Revit
> connector (or IPC) + wire adapter annotations to native
> creation"), I decided to **ship the Python-side connector ops
> first, IPC-only via the existing RevitMCP `/exec` C# escape
> hatch, NOT bundling the official Speckle Revit add-in**. Two new
> connector ops on the Revit family: `revit.send_to_speckle`
> wraps `value` as a Speckle `Base` (Foreign passthrough for
> already-Base items, JSON-wrap for plain dicts/scalars) and
> writes to the per-project `SpeckleWire`; `revit.receive_from_speckle`
> pulls the model + walks items + reads `revit_*` ADAPTER
> annotations (from AgDR-0016) + EMITS a single C# transaction
> script that creates native Revit elements (`Wall.Create`,
> `DirectShape.CreateElement`, `Doc.Create.NewFamilyInstance`)
> and POSTs it through `/exec`. Accepting: official Speckle Revit
> add-in bundling stays deferred (huge surface, separate .NET
> repo, blocked on the Roslyn 4.11/3.4 AppDomain conflict the
> founder flagged); first-shot create-script is conservative —
> Walls / DirectShapes / FamilyInstances only — matching the 3
> ADAPTER node types shipped in AgDR-0016; receive op surfaces
> per-item created/error counts so a partial run is honest.

## Context

After AgDR-0016 shipped, the litmus chain Max-mass → Revit-family
is half-built:

- ✅ SpeckleWire substrate (`app/speckle_wire.py`)
- ✅ Speckle Server lifecycle (`app/speckle_server.py`)
- ✅ 3 SHARE nodes (`share.server`, `share.publish`, `share.subscribe`)
- ✅ 3 ADAPTER nodes (`adapter.cad_to_revit_wall`, `adapter.to_revit_directshape`, `adapter.max_to_revit_family`)
- ❌ **Revit-side**: nothing yet reads adapter annotations and creates natives.

Without the Revit-side, the user can wire `[max.get_mass] →
[adapter.max_to_revit_family] → [share.publish]` and a model URL
shows up — but **no one consumes it**.

Two paths to close this:

1. **Bundle the official Speckle Revit add-in.** Authoritative,
   feature-rich, but ~50MB of .NET assemblies, Roslyn version
   conflict with RevitMCP 4.11 (founder-screenshot 2026-05-20),
   separate build pipeline. Multi-week effort.

2. **Generate native-creation C# on the fly + ship via existing
   `/exec` route.** Reuses the RevitMCP `/exec` endpoint already
   used by every other Revit op. Same code path, same execution
   model, no version conflict. Smaller surface, ships TODAY.

Path 2 is the right MVP — it unblocks the litmus end-to-end + the
official bundle slides in later behind the same op surface.

## Options Considered

### Fork 1 — How to do native creation Revit-side

| Option | Picked | Why |
|---|---|---|
| Bundle official Speckle Revit add-in (separate DLL) | no (deferred) | Big surface · Roslyn conflict · separate repo · multi-week |
| **Generate C# script from ADAPTER annotations + POST to existing `/exec`** | **YES** | Reuses the RevitMCP path · zero new infra · ships TODAY · supports the same 3 ADAPTER kinds AgDR-0016 picked |
| Custom IPC with a per-element JSON protocol | no | Same effort as the official add-in but worse compatibility — reinvents the wheel |

**Pick: Generate C#.**

### Fork 2 — Where the C# generation lives

| Option | Picked | Why |
|---|---|---|
| Inside `revit_connector.py` next to other ops | no | 600+ line `_create_script_for(items)` blows out an already-big file |
| **New `app/connectors/revit_speckle_ops.py` module** | **YES** | Single responsibility · easy to test in isolation · clean import from `revit_connector` |
| Inside `app/workflows/nodes/adapter.py` (where annotations are written) | no | Adapter doesn't know about Revit execution — would couple a pure annotation node to host plumbing |

**Pick: New module.**

### Fork 3 — Transaction granularity

| Option | Picked | Why |
|---|---|---|
| One `/exec` call per item | no | N HTTP round-trips · weak transaction (per-element undo) |
| **One `/exec` per receive call wrapping every item in a single C# transaction** | **YES** | Atomic undo step · single round-trip · matches Revit's transaction model · ops_id `_TX_WRITE` honest |
| Hybrid (batch but split very large jobs) | no | Premature opt; the per-receive load is bounded by the source's content addressable hash size |

**Pick: One transaction per receive.**

### Fork 4 — Failure mode (some items create, others fail)

| Option | Picked | Why |
|---|---|---|
| Abort the whole transaction on first failure | no | Loses good work for one bad annotation; not what the user wants |
| **Try every item · collect per-item result {created/failed/skipped} · commit successful subset** | **YES** | Honest reporting · partial progress preserved · the C# wraps each item in a try/catch |
| Two-phase: validate all then commit | no | Validation duplicates execution logic; cost of the wasted dry-run is the same as the real run |

**Pick: Per-item try/catch.**

### Fork 5 — `revit.send_to_speckle` shape

| Option | Picked | Why |
|---|---|---|
| Wraps the WHOLE upstream `value` as one Base | no | A list of 200 walls would become a single 200-deep Base — opaque to consumers |
| **List input → preserves shape; dict input → wraps once; scalar → wraps once. Speckle commit holds N items** | **YES** | Matches SpeckleWire's JSON-wrap contract · consumers get the right shape back |
| Forces dict-of-categories shape (`{walls:[...], doors:[...]}`) | no | Too rigid; lets the adapter graph decide the shape |

**Pick: Preserve upstream shape.**

## Decision

### New module — `app/connectors/revit_speckle_ops.py`

```python
def send_to_speckle(value, *, model_name, project_dir=None,
                     server_push=False, server_url=None) -> dict:
    """Wrap `value` + write through SpeckleWire. Returns
       {url, hash, item_count, mode}."""

def receive_from_speckle(source_url, *, instance=None,
                          project_dir=None) -> dict:
    """Pull via SpeckleWire → scan items for `revit_*` annotations
       → emit C# transaction → POST to /exec → return per-item
       results."""

def build_create_script(items: list,
                         transaction_name: str) -> str:
    """Pure function: list of dicts (with `revit_*` annotations)
       → one C# script body to run inside `/exec`."""
```

### `build_create_script` annotation handling

| Annotation | Generated C# |
|---|---|
| `revit_target_category == "Walls"` + `revit_polyline` + `revit_level` | `Wall.Create(doc, curve, levelId, structural)` per polyline segment |
| `revit_directshape_category` | `DirectShape.CreateElement(doc, BuiltInCategory.X)` + `SetShape(geometry)` |
| `revit_family_name` + `revit_target_category` | `doc.Create.NewFamilyInstance(point, symbol, level, StructuralType.NonStructural)` + per-parameter `Set` |
| (other / missing) | item skipped; logged as `skipped: "no recognised annotation"` |

Each item wrapped in:
```csharp
try {
    /* per-annotation creation */
    created.Add(new { idx = i, kind = "wall", id = el.Id.IntegerValue });
} catch (Exception ex) {
    errors.Add(new { idx = i, error = ex.Message });
}
```

### Two new `ConnectorOp`s on Revit

```python
ConnectorOp(
    op_id="revit.send_to_speckle", host="revit", kind="action",
    label="Send to Speckle",
    description="Wrap upstream value + write through SpeckleWire. "
                "Optionally push to a Speckle Server.",
    inputs=[inst, ParamSpec("model_name", ...),
            ParamSpec("server_push", type="boolean", ...),
            ParamSpec("server_url", type="text", ...)],
    output_type="string", destructive=False,
    fn=_op_send_to_speckle,
)
ConnectorOp(
    op_id="revit.receive_from_speckle", host="revit", kind="action",
    label="Receive from Speckle",
    description="Pull a model + create native elements per "
                "ADAPTER annotations.",
    inputs=[inst, ParamSpec("source_url", ..., required=True)],
    output_type="any", destructive=True,
    fn=_op_receive_from_speckle,
)
```

### Engine wiring

The `revit.send_to_speckle` op takes its `value` from the upstream
wire (the standard connector-op param flow already passes node
inputs to the op's `ctx`). The op uses the same project dir as
the workflow runner so the SpeckleWire instance matches.

## Consequences

### What ships (this slice)

- `app/connectors/revit_speckle_ops.py` — new module: 3 functions
  (send / receive / build_create_script).
- `app/connectors/revit_connector.py` — 2 new `ConnectorOp` rows.
- Tests:
  - `build_create_script` annotation handling (Walls / DirectShape / Family)
  - Per-item try/catch shape in generated C#
  - Skip-with-reason for unrecognised annotations
  - Send op shape (dict / list / scalar value passthrough)
- Roadmap: mark "M2-Python ✓ SHIPPED" under M2 entry; flag the
  official-bundle deferral with an explicit "M2-Bundle pending"
  follow-up.

### What collapses

- The "no consumer" gap for ADAPTER annotations. The Max-mass →
  Revit-family litmus now has a real Revit-side endpoint.

### What's reinforced

- The IPC path (`/exec` C# script) as the universal Revit fallback
  — same model as every other Revit op.
- Annotation-driven creation is JUST data → script translation.
  Pure function. Testable without Revit.

### Risks

- The C# script grows with the number of items. For 10000 items
  the script body could exceed `/exec`'s body limit. Mitigation:
  in `_op_receive_from_speckle`, if `len(items) > 500`, batch
  into multiple `/exec` calls (each its own transaction). Not
  shipping today — the Speckle commit size cap effectively bounds
  the per-receive load.
- Revit API surface changes between versions could break the
  generated C#. The `_TX_WRITE` script targets API 2020-2024
  compatible features (`Wall.Create(doc, curve, levelId, struct)`
  is stable since 2014).
- Some ADAPTER annotations require resolving a `family_name` to
  an actual `FamilySymbol` in the current document. Strategy:
  the generated C# does a `FilteredElementCollector` lookup +
  surfaces a per-item error if the family is not loaded.

### Tests

| Test | What it proves |
|---|---|
| `test_send_to_speckle_wraps_dict_value` | Dict value writes as one Speckle commit, hash returned |
| `test_send_to_speckle_preserves_list_shape` | A list of items round-trips its length on receive |
| `test_build_create_script_wall_annotation` | A polyline + Walls annotation produces `Wall.Create` C# |
| `test_build_create_script_directshape_annotation` | DirectShape annotation produces `DirectShape.CreateElement` |
| `test_build_create_script_family_annotation` | Family annotation produces `NewFamilyInstance` |
| `test_build_create_script_skips_unannotated` | Item with no `revit_*` annotation surfaces in `skipped` |
| `test_build_create_script_per_item_try_catch` | Generated C# wraps each item in `try` / `catch` |
| `test_receive_from_speckle_offline_path` | Receive without a live broker → typed `not_running` error, never a fake create count |

## Implementation order

1. ✓ This AgDR (done).
2. `app/connectors/revit_speckle_ops.py` + 8 tests.
3. Wire 2 new ops into `RevitConnector.build_ops()`.
4. Run suite, expect +8 tests, no regressions.
5. Update ROADMAP for the M2-Python sub-milestone.
6. Founder sign-off → flip status to `executed`.

## Open forks for founder

1. **Bundle the official Speckle Revit add-in (M2-Bundle).**
   Currently DEFERRED. Required if/when the IPC C#-generation path
   hits a limit (e.g. analytical model creation, room separation
   lines, sheets with viewports). For the litmus + 80% of use
   cases, the IPC path is enough.
2. **AutoCAD / 3ds Max symmetry.** Same shape works for those
   hosts (`acad.send_to_speckle` / `acad.receive_from_speckle`,
   ditto Max). Ship after Revit lands + founder confirms shape.

## Artifacts

- This AgDR.
- Pending: `app/connectors/revit_speckle_ops.py` (new),
  `app/connectors/revit_connector.py` edits,
  `tests/test_revit_speckle_ops.py` (new).
