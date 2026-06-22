---
title: "Connectors — your AEC stack, wired into ArchHub"
description: "Connect Revit, AutoCAD, Rhino, 3ds Max, Blender, the Office and Adobe suites, and your cloud project tools to ArchHub, then run real operations from the canvas."
---

# Connectors — your AEC stack, wired in

ArchHub talks to the software you already use. Instead of jumping between Revit, AutoCAD, Rhino, Excel, Outlook and your project portals, you connect each one to ArchHub once, then drive it from a single canvas.

A **connector** is ArchHub's live link to one application. Today there are **19 connectors** covering **155 operations** in total — from "list every wall in the open Revit model" to "create an RFI in Procore" to "write a range of cells in Excel."

This page explains what's available, how each one connects, and how to actually run an operation. No setup-script gymnastics — most of it is click-and-go.

---

## The 19 connectors at a glance

Each connector exposes a set of **operations**. Every operation is one of two kinds:

- **Read** — looks at something and reports back (e.g. *list walls*, *read a cell range*, *list RFIs*). Safe; changes nothing.
- **Action** — does something (e.g. *set a parameter*, *write cells*, *create an RFI*). These are the ones that change your files or records.

| Connector | Operations | What it's for |
|---|---|---|
| **Revit** | 19 | List/inspect walls, doors, windows, rooms, levels, sheets, views, families, warnings; set parameters; place tags; create dimensions; import meshes; export viewports |
| **AutoCAD** | 10 | List documents, layers, layouts, blocks, xrefs, entities; run commands; manage layers |
| **3ds Max** | 10 | Scene info; list objects, materials, cameras, lights; run MaxScript; import meshes; export viewports |
| **Blender** | 10 | Scene info; list objects, materials, collections; run scripts; render; import meshes; export viewports |
| **Rhino** | 8 | Document info; list objects and layers; run scripts; import meshes; export viewports; toggle layer visibility |
| **Word** | 9 | List documents; read/insert text; find-and-replace; list headings, paragraphs, tables, comments; export PDF |
| **Excel** | 7 | List workbooks and worksheets; read and write cell ranges; list named ranges; export PDF |
| **PowerPoint** | 7 | List presentations and slides; add slides; set shape text; read notes; export PDF |
| **Outlook** | 9 | List inbox, drafts, contacts, calendar; read and mark mail; create drafts; unread count |
| **Photoshop** | 7 | Document info; list documents and layers; run actions; toggle layer visibility; export |
| **Illustrator** | 6 | List documents, artboards, layers, swatches; toggle layer visibility; export |
| **InDesign** | 7 | List documents, spreads, text frames, paragraph styles, links; update links; export PDF |
| **Procore** | 8 | List projects, RFIs, submittals, change orders, daily logs, users; create and fetch RFIs |
| **Notion** | 7 | Search; list and query databases; get/create/update pages; append blocks |
| **Dropbox** | 6 | List folders; upload/download; get metadata; list revisions; create shared links |
| **Microsoft Teams** | 5 | List teams, channels, messages, meetings; post a message |
| **Speckle** | 6 | List projects, models, versions; send and receive geometry |
| **DashScope** | 8 | Text and vision AI, text-to-image and image editing (Alibaba Cloud models) |
| **ComfyUI** | 6 | Probe; list models; queue prompts; run workflows; fetch generated images |

> The number you see on the homepage and on [archhub.io](https://archhub.io) — **"19 connectors, 155 operations"** — is this exact list. It is generated from the connectors that actually load, not a marketing figure.

---

## How a connector actually links to your software

Connectors don't all work the same way, because the apps don't. ArchHub uses whichever method each application supports:

- **In-app bridge (broker).** For **Revit, AutoCAD, 3ds Max and Blender**, ArchHub talks to a small add-in running *inside* the application over a local connection. The app stays open; ArchHub reaches into the live session.
- **COM automation.** For the **Microsoft Office** suite (Word, Excel, PowerPoint, Outlook) and the **Adobe** suite (Photoshop, Illustrator, InDesign), ArchHub uses the application's built-in automation interface on your Windows machine.
- **Python API.** **Rhino** is driven through its scripting API.
- **Cloud / REST.** **Procore, Notion, Dropbox, Teams, Speckle, DashScope and ComfyUI** connect over the internet to their services.

You don't have to remember which is which — the connector handles it. What matters is the **activation** step for the desktop apps, below.

---

## Turning a connector on (the desktop apps)

Cloud connectors just need you to be signed in to that service. The desktop apps need a one-time **activation** so they'll accept ArchHub's link:

- **Revit** — ArchHub writes a small add-in manifest (`.addin`). The connector goes live the next time Revit picks it up.
- **AutoCAD** — ArchHub registers an auto-load entry so its add-in loads with AutoCAD.
- **3ds Max / Blender** — ArchHub copies a startup script into the app's startup folder.
- **Rhino, Speckle, SketchUp, Fusion** — these use a passive marker; no file changes, ArchHub just notes them as available.

You manage all of this from the **Connector rail** inside ArchHub — you don't edit registry keys or copy files by hand.

---

## Honest status — you always know if it's really live

Connectors don't pretend. When ArchHub checks a connector ("probes" it), it reports one of four honest states:

- **Live** — the app is open and responding. Operations will run for real.
- **Loaded but not responding** — ArchHub found the connector but the app isn't answering right now (e.g. Revit is closed, or busy on a dialog).
- **Missing** — the connector or its add-in isn't installed/activated yet.
- **Not authorized** — for cloud services, you're not signed in or lack permission.

This means a connector that *can't* do the job will tell you so, rather than silently reporting an empty result as if it succeeded. If you see "loaded but not responding" for Revit, the usual fix is simply: open the model, and clear any open dialog.

---

## Running your first connector operation

Here's the end-to-end path, in plain steps, inside the ArchHub desktop app:

1. **Open the app** and land on **Home**, then open or create a session and go to the **canvas**.
2. **Find the Connector rail.** This lists your connectors with their live status dots.
3. **Pick a connector** (say, Revit) and look at its operations. Start with a **read** operation — they're risk-free.
4. **Drop a connector operation onto the canvas.** It appears as a node (the connector-operation node) you can wire up like any other.
5. **Run it.** A read like *list walls* returns the data right there. An action like *set parameter* will change your model — so ArchHub treats it as a write (see the safety note below).
6. **Wire the result onward** — feed a Revit door list into a filter, a transform, an AI node, or out to Excel. That's the point of the canvas: one connector's output becomes another's input.

> **Tip:** Press **Cmd-K** (Ctrl-K) to open the command palette / node library and search for a connector or operation by name instead of hunting through the rail.

### A worked example (read → act, safely)

A common AEC task: *retag a batch of doors.*

1. **Revit › list doors** (read) → returns every door in the open model.
2. Filter or review the list on the canvas.
3. **Revit › place tags** or **Revit › set parameter / batch set parameters** (action) → applies the change back to the live model.

Because step 3 changes your model, it runs as a **gated write**. ArchHub's composer has three approval modes — **Plan**, **Auto** and **YOLO** — so you decide whether changes wait for your approval or go straight through. New users should stay in **Plan** mode: nothing touches your model until you approve it.

---

## What flows between connectors

The reason connectors live on a canvas (and not as 19 separate buttons) is that their results connect:

- Pull a **wall / door / room** list out of **Revit**, filter it, and push a schedule into **Excel**.
- Send geometry from **Rhino**, **Blender** or **3ds Max** to **Speckle**, and receive it in **Revit**.
- Take a **Procore** RFI list and draft a summary email in **Outlook**.
- Render with **ComfyUI** or generate an image with **DashScope**, then drop it into a **PowerPoint** or **InDesign** layout.

Every one of these is built from the operations in the table above — no scripting required to wire them.

---

## Frequently asked

**Do I need to install anything in Revit/AutoCAD myself?**
No. ArchHub handles activation (the add-in manifest, the auto-load entry, the startup script) for you. You manage it from the Connector rail.

**Will a connector change my file without asking?**
Only **action** operations change anything, and they run as gated writes. Keep the composer in **Plan** mode and you approve every change before it happens.

**The Revit connector says "loaded but not responding."**
Open the model and dismiss any open Revit dialog. ArchHub reaches into the live session, so the app has to be open and idle.

**Can I add a brand-new connector for an app that isn't on the list?**
ArchHub is built so connectors can be added and activated over time — that's how the count grows. (Today, adding entirely new node kinds or UI from scratch isn't a self-serve feature; new connector coverage ships through ArchHub updates.)

---

## A note on what's coming

A few connector-adjacent capabilities are still in progress and are **not** presented as finished here:

- **Sign in with Google** for the cloud side is built but needs final account configuration before it's switched on — magic-link sign-in works today.
- A **free, zero-setup cloud AI model** out of the box is on the roadmap; for now, AI-backed operations (and the DashScope/ComfyUI connectors) use either a key you provide or your hosted-AI plan.

Everything in the table above, and the read/act workflow, is live in the current release and runs against your real software.
