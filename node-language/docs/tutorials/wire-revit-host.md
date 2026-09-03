---
slug: wire-revit-host
title: Wire ArchHub to Revit
prerequisites:
  - Revit 2024 or 2025 is installed.
  - ArchHub is installed and launches without errors.
  - A `csc.exe` is available (see Prerequisites below).
scope: user
replay_skill_id: sk-wire-revit-host
freshness:
  source_paths:
    - docs/RUN-REVIT.md
    - app/connectors/revit.py
  last_verified: 2026-05-26
generator: manual
---

# Wire ArchHub to Revit

> Get the Revit host showing **green** inside ArchHub so chat can talk
> to your open Revit project.

This walkthrough connects the two pieces: Revit running on your machine,
and the ArchHub app. After this you can ask ArchHub questions like
"what's the title of the active document?" and get a real answer from
your live project.

## Prerequisites

- **Revit 2024 or 2025** is installed.
- **ArchHub** is installed and launches without errors.
- A working **C# compiler** (`csc.exe`) is available. Most Windows
  machines already have one at:
  `C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe`. If yours
  doesn't, install the free
  [Visual Studio Build Tools](https://aka.ms/vs/17/release/vs_BuildTools.exe)
  and tick *"C# and Visual Basic build tools"*.

## Steps

1. **Open Revit and load any project.** A blank template is fine — you
   just need Revit running and idle. The status bar at the bottom of
   Revit must read **"Ready"**.

2. **Confirm ArchHub's Revit add-in is loaded.** Look for `ArchHub` in
   Revit's **Add-Ins** ribbon tab. If it's missing, copy the ArchHub
   `.addin` file into
   `%APPDATA%\Autodesk\Revit\Addins\2025\` and restart Revit.

3. **Launch ArchHub.** Use the Start menu shortcut, or run
   `pythonw app/main.py` from the repo root.

4. **Open the Reality Check panel.** Click the gear (⚙) menu in
   ArchHub's top-right, then choose **Reality Check**. A row labelled
   **Revit** appears.

5. **Wait for the Revit row to turn green.** The probe takes 2–5
   seconds on first run while the broker spawns. A green tick means the
   wire is live.

6. **Send a smoke-test message in the chat panel.** Type
   `What's the title of the active document?` and hit Enter. ArchHub
   replies with your actual Revit file name within a few seconds.

## Expected outcome

In your ArchHub window you now see:

- A green **Revit** row in Reality Check.
- A chat reply containing your real Revit project's title (not a
  placeholder, not an error).

That confirms the chain works: chat → LLM → tool engine → Revit MCP →
your Revit session.

## Replay this tutorial

<!-- replay-button-placeholder
Renderer replaces this with a live "Replay" button that re-runs
brain.skill_mint against `sk-wire-revit-host` to confirm the flow still
works on today's build.
-->

## Why this exists

Without this connection ArchHub is just a chat window — every recipe in
the rest of the tutorials assumes the Revit row is green. We put this
first so you only have to debug the wire once.

If the Revit row stays amber or red, see the troubleshooting table in
`docs/RUN-REVIT.md` — it covers the three most common causes (broker
port collision, missing `csc.exe`, conflicting add-in).

---

<details>
<summary>Engineering details (collapsed by default)</summary>

- Source: `docs/RUN-REVIT.md`, AgDR-0023, AgDR-0030.
- Broker default port: 48884.
- ArchHub uses subprocess `csc.exe` (not in-process Roslyn) so it
  coexists with pyRevit, Speckle, and other Revit add-ins. See
  AgDR-0023 for the architectural reason.

</details>
