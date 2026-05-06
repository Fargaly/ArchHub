# ArchHub Quickstart — what to try first

Five things that exercise the whole product. Each takes under a minute
once your tools are open.

## Before you start

1. Open Revit. Wait until the project loads.
2. Open Blender. Empty scene is fine.
3. (Optional) Open AutoCAD if you want to test that path too.
4. Launch ArchHub via the Start menu shortcut.
5. ⚙ menu → **Reality Check**. You should see green ticks for at least
   Revit + Blender + LLM router. If a row is amber/red, fix that one
   thing before continuing.

If Reality Check is all-green, the rest of this guide will work.

## 1. Talk to your Revit project

In ArchHub chat, type:

```
What's the title of the active document?
```

Expected: chat replies with the actual file name from Revit (within 1-3
seconds). This is the smoke test that the whole stack — chat → LLM →
tool engine → Revit MCP → Roslyn — is wired correctly.

## 2. Annotate the active view

```
Annotate this view
```

ArchHub's matcher proposes the **Annotate active view** Skill. Click
**Run**. ArchHub:

- dimensions every wall whose curve is visible,
- tags every door + window whose host is in the view,
- labels every room.

Each pass is wrapped in its own Revit Transaction, so you can Undo any
one of them from Revit's Undo history if it misfires on your project's
conventions.

## 3. Export every sheet to AutoCAD

```
Export all sheets to DWG
```

Matcher proposes **Export Revit drawings to AutoCAD**. Click **Run**.
You'll get one .dwg file per ViewSheet under
`<project_folder>\<project>_DWG\` (or `Documents\ArchHub-DWG\` if the
project hasn't been saved).

Replace "all sheets" with "this view" or "this sheet" to scope down.

## 4. Sketch → 3D mass

Drag a sketch image (PNG, JPG, screenshot, hand drawing) into the chat
input bar. Then type:

```
Build this in 3D, gabled, around 6 m wide
```

Matcher proposes **Extract mass from sketch**. Click **Run**. Claude
reads the sketch, infers width / depth / storeys / roof type, and
builds the corresponding mass in Blender under a `Mass_Sketch`
collection.

## 5. Build site context from a map link

```
Build the site context from this map link
https://www.google.com/maps/@24.4539,54.3773,17z
```

ArchHub detects the Maps URL automatically and proposes **Build site
context from a map link**. Click **Run**. ArchHub fetches surrounding
buildings from OpenStreetMap (no API key, no money) and extrudes them
to their real heights in Blender as a `Site_Context` collection. Drop
your sketch mass into that scene and you have a real urban-context
massing.

You can also just paste lat/lng like `24.4539, 54.3773` and ArchHub
parses it directly.

---

## When something fails

1. ⚙ menu → **Reality Check**. Tells you which layer is broken.
2. Tool cards expand to show the actual exception text.
3. Skill stepper shows which stage of a multi-stage Skill failed.
4. If LLM-generated code is off, edit the Skill's framing prompt:
   ⚙ → **Skills…** → click **Edit** on the Skill → switch to the
   Workflows tab → tweak the `data.template` node's text.

## Pipeline

The flagship is **Sketch to production** — six chained stages from a
pasted sketch all the way to plans / sections / elevations / room
schedule on A1 sheets. Run it after the individual stages above are
proven on your project.

```
Take this sketch all the way to production drawings
```

(attach a sketch image first)
