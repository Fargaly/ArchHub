# Revit Finishes Pipeline — Skills + Workflow

Reference doc from a long working session that built a finish-walls system across a 7-level project (BA-649-A-TA-01-B1-00). Captures the techniques, gotchas, and pipelines that actually worked. Use as a guide for similar tasks.

---

## 1. Connection

ArchHub bridge MCP runs on `localhost:48884` for Revit. Direct call:

```powershell
$body = @{ code = "result = Doc.Title;"; transaction_name = "p" } | ConvertTo-Json
Invoke-WebRequest -Uri "http://localhost:48884/exec" -Method POST -Body $body -ContentType "application/json" -UseBasicParsing -TimeoutSec 30
```

Globals in C# Roslyn script: `Doc`, `UIDoc`, `UIApp`. Imports auto-included: `Autodesk.Revit.DB`, `Autodesk.Revit.UI`, `System.Linq`, etc. Set `result` to return.

`/ping` for liveness, `/exec` for C#, `/screenshot` for view PNG.

---

## 2. Discovery — Wall Treatment Master Views

Every level has an **OVERALLS** master view that owns the detail group (BA-PNT-01, BA-WP-06, etc) line elements. Sub-views (PART 01, PART 02…) are dependents — they don't own the lines.

| Level | Master view ID range | Naming pattern |
|---|---|---|
| GR FLOOR (covers LGR + GR) | 5747940 | `GROUND FLOOR - WALL TREATMENT LAYOUT - OVERALLS` |
| 1ST FLOOR | 5750676 | `FIRST FLOOR - WALL TREATMENT LAYOUT - OVERALLS` |
| 2ND FLOOR | 5750872 | `SECOND FLOOR - WALL TREATMENT LAYOUT - OVERALLS` |
| 3RD FLOOR | 5750995 | `THIRD FLOOR - WALL TREATMENT LAYOUT - OVERALLS` |
| 4TH FLOOR | 813597  | `FOURTH WALL TREATMENT LAYOUT - PART 01` |
| 5TH FLOOR | 3542863 | `FIFTH WALL TREATMENT LAYOUT - PART 01` |

Find them by `CurveElement.OwnerViewId` filter — much faster than scanning all views (1.1s vs 49s per level).

LGR LEVEL **has no plan view** — its detail group lines live in the GR FLOOR master view.

---

## 3. Wall Type + Material Setup

9 wall types, all 20mm thick, single-layer Generic finish:

| WF code | Wall type name | Material (color RGB) | Description |
|---|---|---|---|
| WF-01 | `WF-01_PNT_20mm` | 245,245,242 | FENOMASTIC WHITE PAINT (JOTUN-10878) |
| WF-02 | `WF-02_SKR_20mm` | 218,200,170 | 100MM MR MDF SKIRTING |
| WF-03 | `WF-03_TIL_20mm` | 220,215,205 | 600x1200 PORCELAIN TILES |
| WF-04 | `WF-04_TIL_20mm` | 180,175,165 | 600x1200 HEAVY DUTY BACKSPLASH |
| WF-05 | `WF-05_TIL_20mm` | 230,225,215 | 600x600 NORWAY BIANCO |
| WF-06 | `WF-06_PNT_20mm` | 220,205,180 | SPECIAL PAINT BEIGE |
| WF-07 | `WF-07_PNT_20mm` | 240,235,225 | SPECIAL PAINT OFF-WHITE |
| WF-08 | `WF-08_PNT_20mm` | 235,230,220 | ACOUSTIC OFF-WHITE |
| WF-09 | `WF-09_PNT_20mm` | 190,210,200 | ACOUSTIC RENDER |

Surface patterns: `600` for tile types (matches existing model pattern), `wood` for skirting.

Cut pattern: solid filled with the color. Set `Type Mark = WF-XX` and `Description` (CAPS).

---

## 4. Indicative Line ↔ WF Mapping

Detail group line styles map to WF codes by row position in legend `LGND-WALL LINES`:

```
BA-PNT-01 → WF-01    BA-WP-01 → WF-06
BA-SKR-01 → WF-02    BA-WP-06 → WF-07
BA-PNT-06 → WF-03    BA-WP-05 → WF-08
BA-PNT-04 → WF-04    BA-ART-06 → WF-09
BA-PNT-05 → WF-05
```

---

## 5. Finish Wall Placement Algorithm

Per room, single `/exec`:

1. Get room boundary loops via `room.GetBoundarySegments(SpatialElementBoundaryLocation.Finish)`.
2. **Outer loop** (segs[0]) = room perimeter. **Inner loops** = engulfed columns.
3. For each segment:
   - Skip: tiny (`<100mm`), curtain wall hosts, glazing wall types (name contains `GLZ`), ModelLine separators.
   - Compute perpendicular `n = (-dir.Y, dir.X, 0)`.
   - Sanity test: `room.IsPointInRoom(mid + n*50mm)` — if false, flip `n`.
   - For inner loops use **loop centroid** (mean of seg endpoints) for direction sanity instead of room centroid (room surrounds column → centroid trick fails).
4. Place paint wall: curve offset `+10mm` along `n`, type `WF-01_PNT_20mm`.
5. Place skirting: curve offset `+30mm` along `n`, type `WF-02_SKR_20mm`, height 100mm.
6. **Column wraps**: extend curve by `±10mm` at each end so adjacent walls overlap → auto-join produces clean miters.
7. Set `WALL_ATTR_ROOM_BOUNDING = 0` (non-bounding) — preserves room boundary.
8. Set `ELEM_PARTITION_PARAM = 830` (workset BA-I-FIN).

Inherit host wall's top/base constraints when host is a Wall:
```csharp
paint.get_Parameter(WALL_HEIGHT_TYPE).Set(host.WALL_HEIGHT_TYPE);
paint.get_Parameter(WALL_TOP_OFFSET).Set(host.WALL_TOP_OFFSET);
```

---

## 6. Retype by Indicative Line Proximity

For each paint wall (default WF-01), find nearest matching detail line:

```csharp
// Build spatial bin (10ft cells) of all BA-XX lines from master view
foreach BA-XX line: bins[(floor(mx/10), floor(my/10))].Add(line)

// For each paint wall midpoint, search 3x3 cell neighborhood
foreach line in bin:
    if line.WF == "WF-02": continue  // skip skirting style
    if abs(dot(wallDir, lineDir)) < 0.85: continue  // not parallel
    perpD = abs((lineMid - wallMid) · perpDir)
    alongD = abs((lineMid - wallMid) · lineDir)
    if perpD > 2.0 ft: continue  // 600mm tolerance
    if alongD > line.len/2 + 1.0: continue
    score = perpD*5 + alongD*0.05  // perpendicular distance dominates
    pick best
```

For toilets (room name contains TOILET/WC/BATH/HANDICAP/SHOWER/LAV, or WallFinish has WF-03 + WF-04), **default unmatched paints to WF-03** (primary tile).

---

## 7. View Filters (BA-AI-WLLTRT template)

9 filters by `Type Mark` parameter on Walls category:

| Filter | Color | Pattern (LinePatternElement ID) | Weight |
|---|---|---|---|
| WF-01 | 255,0,128 | BA-Dash-Narrow (249640) | 10 |
| WF-02 | 128,255,0 | BA-Overhead (19) | 10 |
| WF-03 | 128,0,255 | BA-Dash-Narrow | 10 |
| WF-04 | 0,128,192 | BA-Dash-Narrow | 10 |
| WF-05 | 0,128,128 | BA-Dash-Narrow | 10 |
| WF-06 | 255,128,128 | BA-Dash-Dot-Narrow (168343) | 8 |
| WF-07 | 64,0,0 | BA-Dash-Dot-Narrow | 8 |
| WF-08 | 128,128,64 | BA-Dash-Dot-Narrow | 8 |
| WF-09 | 143,224,192 | BA-Double-Dash (14) | 1 |

Plus halftone filter `BA-FIN-HALFTONE-NOT-IN-FIN-WORKSET`: rule = `ELEM_PARTITION_PARAM != 830`, applies halftone to 25 categories (Walls, Doors, Windows, Furniture, Casework, Floors, Ceilings, Roofs, Stairs, Railings, Curtain Panels, Mullions, Columns, Structural Columns/Framing, Light/Plumbing/Mechanical/Electrical Fixtures, Generic Model, Specialty Equipment, Parking, Site, Planting). Result: WF walls pop, everything else fades.

---

## 8. Curtain Panel → Wall Conversion

Basic Walls embedded in curtain walls have `BuiltInParameter.HOST_PANEL_SCHEDULE_AS_PANEL_PARAM`:
- `0` = categorized as Wall
- `1` = categorized as Panel

Set to `0` to make finishes apply. Across this project, 339 GPSM Basic Walls were `Panel` → flipped to `Wall`.

---

## 9. GPSM Curtain Panel Wrap

381 `BA-AI-WAL-GPSM_150MM` walls (panels in glazing curtain walls) wrapped with WF-09 finish + WF-02 skirting on **all 4 faces** (2 long sides + 2 end caps):

- Long-side paint: curve offset `±(host.Width/2 + 10mm)` perpendicular
- End-cap paint: short perpendicular wall at `host.start - 10mm * dir` and `host.end + 10mm * dir`, length = host width + 20mm
- Long-side skirting: `±(host.Width/2 + 30mm)`
- End-cap skirting: same offset

Heights inherit from host wall.

---

## 10. Slab Clash Cap

Per level, find next level above. For each non-skirting WF wall:
- If top constraint = unconnected → set `WALL_HEIGHT_TYPE = nextLevel` + `WALL_TOP_OFFSET = -200mm` (typical slab thickness)
- If existing top elevation > nextLevel - 100mm → cap to next level - 200mm

---

## 11. Inside-Host Clash Detection

For each WF wall, compute its midpoint. Search non-WF Basic walls in spatial bin. For each candidate host:
- Project WF midpoint onto host's location curve
- Compute `along` (parallel) + `perp` (perpendicular) distance
- If `0 ≤ along ≤ host.Length` AND `perp < host.Width/2 - 0.01` → WF is INSIDE host → delete

Caught **1,250 mis-placed walls** across 7 levels.

---

## 12. Redundant Room Fix Pipeline

When two rooms share an enclosed region (Revit warning "Multiple Rooms in same enclosed region"):

1. **Diagnose**: identify absorbed room (`area = 0`) and absorbing room.
2. **Restore host bounding**: any non-WF Basic wall with `WALL_ATTR_ROOM_BOUNDING = 0` should be `1`. (Earlier ops accidentally flipped 414 host walls non-bounding — restore.)
3. **Floor outline as separation**: get the absorbed room's floor element (point-in-bbox of floor list), extract top face edges via `solid.Faces.Where(normal.Z > 0.95).EdgeLoops`, project to level Z, create as `Doc.Create.NewRoomBoundaryLines`.
4. **Re-place trick**: `ElementTransformUtils.MoveElement(doc, room.Id, new XYZ(0.001, 0, 0))` then move back `(-0.001, 0, 0)` — forces Revit to re-evaluate room placement. Often picks up new enclosed region.
5. **Manual selection → separation**: user picks specific lines in Revit; convert via `UIDoc.Selection.GetElementIds()` + `Doc.Create.NewRoomBoundaryLines()`.

This pipeline fixed 11/11 redundant rooms in one session.

---

## 13. Saving Workshared Models

`Doc.Save()` fails inside Roslyn transaction. Use `UIApplication.PostCommand`:

```csharp
UIApp.PostCommand(RevitCommandId.LookupPostableCommandId(PostableCommand.Save));
```

Save runs **after** transaction commits. Caveat: workshared sync may revert ID assignments — re-fetch wall types **by name** (not cached IDs) at start of every script.

---

## 14. Performance Rules (machine-friendly)

- **Never** scan `FilteredElementCollector` over all views. Filter by `OwnerViewId` against known view ID set.
- Build spatial bins **once per `/exec`**. Don't rebuild per element.
- Process **per level, single `/exec`**. Avoids regen avalanche.
- 5-room batches OK for single-`/exec` call; 50+ may stall Revit.
- Avoid wall-to-wall O(N²) joins; use bbox-binned proximity check.
- Don't `JoinGeometry` between WF and host walls if room boundary integrity matters — joining can corrupt boundary segments at corners.

---

## 15. Common Gotchas

- **Anonymous types** in `.Select()` Roslyn fail silently. Use `Tuple.Create(...)` instead.
- **`Doc.GetWorksetTable().SetActiveWorksetId(WorksetId)` is instance method** — `WorksetTable.SetActiveWorksetId(Doc, id)` is wrong (no such overload).
- **Wall.Create with auto-join** trims walls at corners — set `WallUtils.DisallowWallJoinAtEnd` if exact length matters; else extend curve `+10mm` each end and let auto-join clean up.
- **`WALL_ATTR_ROOM_BOUNDING` set on instance doesn't always stick** — call `Doc.Regenerate()` after batch + verify.
- **Inner loop perpendicular**: use loop centroid, not room centroid (room wraps column → room centroid points wrong direction on far faces).
- **Room re-place** doesn't happen automatically when separation lines added — must trigger via `MoveElement` (microscopic).

---

## 16. Workflow Summary (B1 project, 7 levels, ~14k WF walls)

```
PHASE 1 — Setup (single /exec)
  ├── GPSM Panel→Wall: 339 conversions
  ├── Create 9 WF wall types + materials (CAPS descriptions)
  └── Create 9 view filters + halftone filter on BA-AI-WLLTRT template

PHASE 2 — Per-level placement (one /exec per level)
  For each: LGR → GR → 1ST → 2ND → 3RD → 4TH → 5TH
    ├── Scan master view for BA-XX lines (1-2s)
    ├── Build spatial bin
    ├── Per room:
    │     ├── Place paint walls + skirtings on host walls
    │     ├── Wrap inner-loop columns (auto-join, no DisallowJoin)
    │     ├── Set non-room-bounding + workset BA-I-FIN
    │     └── Retype paint walls per nearest BA-XX line
    └── PostCommand Save

PHASE 3 — Cleanup (one /exec per level)
  ├── Inside-host clash deletion
  ├── Slab top cap (next level - 200mm)
  ├── Toilet skirting deletion
  └── Floor-outline separation lines for redundant rooms

PHASE 4 — Curtain panel wrap (single /exec)
  └── 381 GPSM_150 walls × 8 finish walls each = 3,048 walls

PHASE 5 — Redundant room fix (interactive)
  ├── Restore host walls' bounding state (414 walls)
  ├── Floor outline separation per absorbed room
  ├── ElementTransformUtils.MoveElement re-place trick
  └── User-selected lines → Room Separation Lines (UIDoc.Selection)
```

**Final result**: 14,228 finish walls, 0 redundant warnings, all rooms placed, workset assigned, view filters working.

---

## 17. What I'd Do Differently Next Time

1. **Prove non-bounding mass-set on hosts BEFORE running** — the 414-wall regression was a silent bug that took multiple sessions to catch.
2. **Don't `JoinGeometry` WF↔host** — the join doesn't propagate door/window cuts as user expected, and it corrupts boundary segments.
3. **Always check active doc** before each `/exec` — user can switch docs without notice (linked models, detached versions, B2 vs B1).
4. **Scan only specific views** (master OVERALLS) — never iterate all plan views.
5. **Batch 5-10 rooms per `/exec`** — `One per /exec` is too slow (545 calls for 7 levels), `all at once` overwhelms graphics regen. 5-10 is sweet spot.
6. **PostCommand Save isn't free** — workshared sync can revert local changes. Use sparingly; warn user before relying on auto-save.
7. **Re-fetch wall type IDs by name** at start of every script. Saved/synced docs may shift IDs.
