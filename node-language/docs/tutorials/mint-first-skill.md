---
slug: mint-first-skill
title: Mint your first skill
prerequisites:
  - ArchHub is running.
  - The brain daemon is alive on port 8473.
  - At least one MCP host is connected and green (Revit, Blender, or AutoCAD).
scope: user
replay_skill_id: sk-mint-first-skill
freshness:
  source_paths:
    - personal-brain-mcp/src/personal_brain/reflexion.py
    - personal-brain-mcp/src/personal_brain/server.py
  last_verified: 2026-05-26
generator: manual
---

# Mint your first skill

> Run a real workflow once. ArchHub watches the trace, distils it into
> a reusable **skill**, and adds a one-click run button you can use
> forever after.

This is the core ArchHub loop: the second time you do the same thing,
it's a button. The first time taught the app what to do.

## Prerequisites

- ArchHub is running.
- The brain daemon is alive. Quick check: visit
  `http://127.0.0.1:8473/mcp` in your browser — you should see a
  JSON-RPC error response (that's good; it means the daemon answered).
- At least one MCP host is wired and green in Reality Check. The Revit
  tutorial above walks you through wiring one if you haven't yet.

## Steps

1. **Pick a workflow you actually do.** Annotating a view in Revit.
   Exporting sheets to DWG. Listing every layer in an open AutoCAD
   drawing. Any small, repeatable task.

2. **Run it once through the chat panel.** Type the request in plain
   English — for example, *"annotate this view."* ArchHub calls the
   right tools in sequence. Watch each tool card stream its progress.

3. **Confirm the result on the host.** Flip back to Revit (or whichever
   host you used) and verify the output matches what you asked for.
   This single human confirmation is what tells the brain the trace
   succeeded.

4. **Close the session or wait for the Stop hook.** When the
   conversation turn ends, ArchHub fires `brain.skill_mint` against
   the trace. The reflexion worker runs the Voyager-style critic
   pipeline off-thread, so the chat panel never freezes.

5. **Open Settings → Skills.** Within 5–10 seconds you'll see a new
   row appear with an auto-generated name (something like
   `revit_annotate_view_flow`). The row shows:
   - The plain-English description the worker extracted.
   - How many sandbox honing trials passed (target is at least 2 of 3).
   - The triggers that will fire this skill next time.

6. **Trigger the skill from chat.** Type one of the listed triggers
   (or anything close in meaning). ArchHub proposes the new skill as a
   **Run** card. Click **Run** and watch your workflow execute from a
   single button.

## Expected outcome

In your ArchHub window:

- **Settings → Skills** lists your new skill with a green status.
- Typing one of its triggers in chat shows a **Run** card with the
  skill's name and description.
- Clicking **Run** executes the same flow you did manually in step 2
  — same tools, same order, same result.

## Replay this tutorial

<!-- replay-button-placeholder
Renderer replaces this with a live "Replay" button that fires
brain.skill_mint against a known-good seed trace and verifies a fresh
skill appears in the library.
-->

## Why this exists

ArchHub's promise is **the second time is a button**. That promise
relies on the reflexion pipeline working end-to-end on a real trace.
This tutorial is the smallest possible exercise of that pipeline — a
single workflow, a single skill, a verified replay. Once you see this
work, everything else (firm-scoped skills, community skills, replay
gating) follows the same shape.

If no skill appears within 30 seconds, check **Settings → Brain** for
the last `skill_mint` log line. The worker tells you exactly which gate
the trace failed (classifier, dedupe, honing, or validator).

---

<details>
<summary>Engineering details (collapsed by default)</summary>

- Source: `personal-brain-mcp/src/personal_brain/reflexion.py`,
  `personal-brain-mcp/src/personal_brain/server.py::brain_skill_mint`.
- The reflexion pipeline runs: classify → extract → dedupe → hone (3
  sandbox trials) → eval-query generation → validate → publish. All
  off-thread per AgDR-0044 Slice 5 so the chat panel never blocks.
- Dedupe threshold: cosine similarity ≥ 0.85 against the existing
  library → UPDATE, below → new skill candidate.

</details>
