# Reliability & Known Limits

_Last updated: 2026-05-07._

This page sets practical expectations for ArchHub's flagship workflows.

## Scope

These expectations apply to currently documented quickstart workflows and may vary by project size, model quality, and host application state.

## Workflow expectations

### Revit smoke test (document title query)

- Typical completion: 1–3 seconds.
- Success criteria: returns active document name from Revit.
- Common failures: Revit MCP bridge not running, no active document, host permission issues.

### Annotate active view

- Typical completion: a few seconds to under 1 minute depending on view complexity.
- Success criteria: dimensions walls, tags doors/windows, labels rooms.
- Common failures: unsupported geometry in view, element visibility/filter conflicts, missing families/tags.

### Export sheets to DWG

- Typical completion: depends on sheet count and export options.
- Success criteria: one or more DWG files exported to expected folder.
- Common failures: unsaved project path ambiguity, export settings mismatch, file write permissions.

### Sketch to 3D mass (Blender)

- Typical completion: under 1 minute for basic masses.
- Success criteria: generated mass objects under expected collection.
- Common failures: ambiguous sketch geometry, insufficient prompt constraints, model hallucination of dimensions.

### Construction doc sprint pack

- Typical completion: 60–90 minutes on real projects (project-dependent).
- Success criteria: chained stages complete with QC report generated.
- Common failures: project standards mismatch, missing title blocks/families, large-model transaction timeouts.

## Host-specific constraints

| Host | Common constraints |
|---|---|
| Revit | Active document required; family/type availability affects annotation and schedule output. |
| Blender | Scene scale/unit ambiguity from sketch prompts may require follow-up constraints. |
| AutoCAD | Drawing hygiene and layer states can affect audit/export behavior. |
| 3ds Max | Connector/runtime path and host startup state can impact tool availability. |

## Operational guidance

- Use **Reality Check** before running complex multi-stage skills.
- For production use, run workflows on a duplicated model first.
- Prefer explicit prompts with measurable constraints (sizes, levels, target views).
- Treat generated output as assistant-authored draft requiring human review.
