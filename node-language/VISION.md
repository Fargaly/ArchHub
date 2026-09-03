# ArchHub — Product Vision

## What ArchHub is

A parametric design environment for architects, with chat as the input
surface and AI as the construction agent. Every step the user takes —
model a mass, render it, post-process the image, change the angle — is
a live parametric node. Parameters never die. They appear in a sidebar
the moment the user mentions them, and stay live forever. Drag a slider
and the entire chain downstream re-runs.

This is not a chat that calls tools. It is Grasshopper for AI agents,
with the canvas hidden.

## Two foundational principles

**1. Connectors build themselves.**

ArchHub does not ship one DLL per host application per version. It ships
a *connector contract* and uses the LLM in the app to generate the
adapter code on demand, per host, per version. Toggle Blender on for
the first time → ArchHub asks Claude to write the addon → installs it →
verifies it. Same for Revit, AutoCAD, 3ds Max, Rhino, anything that
follows. New version of any host = regenerate, no manual maintenance.
Static `payload/sources/` exists only as a cached fallback; the
generative path is primary.

**2. Every step is a parametric node.**

User says "model a small house, 2 storeys, gabled, around 6m wide".
ArchHub creates parameters: `width=6m`, `depth=4m`, `storeys=2`,
`roof_pitch=30°`. Generates Blender Python, executes it, renders, shows
the render in chat. The four parameters appear in the sidebar.

User drags `roof_pitch` to 45° → re-render. Same effect as typing
"steeper roof". Both go through the same chain.

User says "render it golden hour, low angle" → `sun_elevation` and
`camera_height` are added. Render node re-runs.

User says "warmer, more contrast" → a post-process node is appended to
the chain.

User changes `width=8m` → mass node re-runs, render re-runs,
post-process re-runs. Everything downstream of the changed parameter is
dirty and re-evaluates.

## The minimum demo

> 1. Toggle Blender on. ArchHub generates the addon if missing.
> 2. Paste a hand sketch. Type "build this in 3D, ~6m wide, gabled."
> 3. ArchHub creates parameters, runs Blender Python, renders.
> 4. Sidebar shows `width`, `depth`, `roof_pitch`, `storeys`.
> 5. Drag `roof_pitch` to 45° → re-render in 3 seconds.
> 6. "Render at golden hour from a low angle" → 2 new parameters appear.
> 7. "Warmer tones, more contrast" → post-process node added.
> 8. Change `width=8m` → entire chain re-runs.

When this loop works, ArchHub is real.

## Roadmap reframed against this vision

| Phase | What it adds                                                         |
|-------|----------------------------------------------------------------------|
| 1     | Parametric session model + Blender end-to-end + meta-connector       |
| 2     | Auto-built Revit/AutoCAD connectors via the same meta-connector      |
| 3     | Speckle as live data spine — geometry pushes/pulls into the session  |
| 4     | Parameters mapped to exposed Speckle/Revit parameters bidirectionally |
| 5     | Visual canvas as alternative to the sidebar (for power users)        |
| 6     | Native modeling environment (long horizon)                           |

## What this kills

The static `payload/<host>/<year>/*.dll` model. The user-buildable
toggle that requires a terminal. The chat-as-history concept where you
can't go back and tweak. The "single LLM picks tools" architecture —
replaced by a parametric DAG where the LLM is one of many node kinds.

## What this preserves

The single-window UX. The connector toggle paradigm. The multi-LLM
router. The Windows Credential Manager for secrets. The workflow data
model — which becomes the *serialized form* of a session, so any
session can be saved as a workflow and replayed.
