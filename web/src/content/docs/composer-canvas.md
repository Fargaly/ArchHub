---
title: "The app — composer, canvas, nodes, library"
description: "A plain-English tour of the ArchHub desktop app: the canvas substrate, the composer you drive it with, the nodes you connect, and the library you build from. No jargon, no developer setup."
key: composer-canvas
---

# The app — composer, canvas, nodes, library

This is the part of ArchHub you actually open and work in: the desktop app. It is a single window that runs on your Windows machine. Inside it you find four things that work together — a **canvas** to lay out your work, a **composer** to drive it in plain language, **nodes** that do the real work (talking to Revit, AutoCAD, Word, your AI model, and so on), and a **library** you create those nodes from.

This page walks you through each one the way you would actually meet it, the first time you open the app. It is written for an architect or a studio principal, not a programmer.

---

## Before anything: getting in

You do not need a terminal. Install the app one of these ways:

- **winget** (Windows package manager): `winget install Fargaly.ArchHub`
- **scoop** or **choco**, if you already use them
- Or download `ArchHub-Setup-x.y.z.exe` directly from the [Releases page](https://github.com/Fargaly/ArchHub/releases/latest) and double-click it.

The installer puts a desktop icon and a Start-menu shortcut in place. (Until the app has a code-signing certificate, Windows SmartScreen may show a warning the first time — that is expected for new installers.)

On first launch, a short sign-in wizard connects you to a cloud AI model so the app can think. It uses a **magic link** — you type your email, click the link it sends, and you are in. The free tier comes with a number of included trial messages and asks for **no credit card**.

> **Known launch gotcha:** on some NVIDIA graphics cards the window opens but the inside renders blank. The current workaround is to set the environment variable `ARCHHUB_VERIFY_NO_GPU=1` and relaunch. An automatic fallback for this is planned but not yet built.

---

## Home — where every session starts

When the app opens you land on **Home**. It shows:

- the ArchHub **wordmark**,
- a grid of your **recent sessions** as cards with thumbnails (so you can jump back into yesterday's work),
- a **graph-health** chip you can click to see the real health detail of your current graph,
- and an **account chip** in the corner showing your live account — your email, your plan, and how many messages you have left. These are read from your actual cloud account, not placeholder text.

From Home you create a new session, or open a recent one, to get to the canvas.

---

## The canvas — your working surface

The **canvas** is the substrate everything sits on. It is a custom, infinite working surface — not a generic flowchart tool — built specifically for this app.

On it you place **nodes** and draw **wires** between them. A few things you can do:

- **Move, duplicate, group** nodes. Grouping opens a small dialog so you can name and tidy a cluster of related work.
- **Freeze** or **bypass** a node when you want it left alone or temporarily skipped.
- Watch each node's **state dot**, which tells you at a glance whether it is idle, running, or has a problem.
- Use the **canvas toolbar** and right-click **canvas menu** for the common actions.
- Keep your bearings on a large graph with the **mini-map**.
- If a connection breaks, ArchHub points it out and offers to **repair the broken wire** through a small dialog rather than leaving you to hunt for it.

Different nodes show different **bodies** depending on what they do — a node that talks to a host program (like Revit) looks different from one that runs an AI step, filters data, transforms it, reads or watches something, or just holds a note or annotation. You do not have to memorise these; the body simply shows the controls that node needs.

---

## The composer — how you drive it

The **composer** is the primary way you make things happen. It is a floating text box where you type what you want in plain language, and the app turns that into work on the canvas. (You can also dictate with the built-in **voice** input.)

The important part is how carefully it treats **changes that touch your real files and programs**. Every action that would write something goes through an **approval queue** with three modes you choose:

- **Plan** — the app proposes what it would do and waits for you. Nothing is applied until you say so.
- **Auto** — it carries out steps for you, within the limits you have set.
- **YOLO** — fewest interruptions, for when you trust the run.

You also get a **plan history** — a record of the AI's proposed plans you can look back through — and a **court verdict queue**, which is the app's own checking step before results are accepted. The point of all this is that the app never quietly changes your model or documents behind your back; writes are gated and visible.

---

## Nodes and connectors — the work itself

The real muscle is the **connectors**. ArchHub ships with **19 connectors** covering **155 operations** between them. Each connector links the app to one program you already use, and each operation is one specific thing it can do.

The connectors, with how many operations each has:

| Connector | Operations | Connector | Operations |
|---|---|---|---|
| Revit | 19 | Notion | 7 |
| Blender | 10 | Illustrator | 6 |
| AutoCAD | 10 | Speckle | 6 |
| 3ds Max | 10 | Dropbox | 6 |
| Word | 9 | ComfyUI | 6 |
| Outlook | 9 | Teams | 5 |
| Procore | 8 | PowerPoint | 7 |
| Rhino | 8 | Photoshop | 7 |
| DashScope | 8 | InDesign | 7 |
| Excel | 7 | | |

Each operation is either a **read** (it looks at something — lists your walls, reads a range, fetches RFIs) or an **action** (it changes something — sets a parameter, posts a message, exports a PDF). Every operation reports an **honest status** so you always know where you stand:

- **live** — connected and ready,
- **loaded** but the host is not running,
- **missing** — the host program is not installed,
- or **unauthorized** — it needs sign-in or permission first.

Under the hood the connectors reach each program the right way for that program — through a small companion add-in for Revit, AutoCAD, 3ds Max and Blender; directly for Office and Adobe apps; and over the web for cloud services like Procore, Notion, Dropbox, Teams, Speckle, DashScope and ComfyUI. Some hosts need a one-time activation (for example, Revit needs its add-in manifest in place, AutoCAD needs an auto-load setting). You run an operation by dropping its connector node on the canvas and triggering it; the node body shows the inputs and the result.

> **What you can add today:** you can add and activate **connectors**. The app cannot yet build brand-new interface screens or new kinds of nodes for you on demand — that is a future direction, not a shipped feature.

---

## The library — building your toolkit

The **library** is where nodes come from. Open it from the side, or hit **Cmd-K** to bring up the command palette and search across everything.

In the library you can:

- **Browse** node types by category,
- **search** for the operation you need,
- **create a new node type** from what is available,
- and **save your own skills** — a useful arrangement you want to reuse — so they are there next time.

This is how a one-off setup becomes a repeatable part of your studio's workflow.

---

## The brain — memory that carries over

ArchHub keeps a personal **brain**: a local store of facts, decisions and learned skills that lives on your own machine. Inside the app you can:

- **browse it as folders**, organised into a tree you can navigate,
- **search** it,
- explore your **memory**,
- and **back it up to the cloud** so it is safe.

The cloud copy is **write-only from your machine** — your desktop pushes changes up to a private replica that is yours alone, and secrets are stripped before anything leaves. It is a backup, not a public feed.

---

## Sessions, skills, communities, self-heal

A few more surfaces you will meet:

- **Sessions** — create, open, rename, fork, duplicate or delete your work sessions, and sync them to the cloud so they follow you.
- **Skills** — save a piece of work as a reusable skill, and (when you choose) promote it to a shared one.
- **Communities** — slots for sharing brain knowledge with a group.
- **Self-heal inspector** — a panel that surfaces the app's own self-checks and repairs, so problems are visible rather than silent.

---

## Settings — models, providers, preferences

Open **Settings** to manage:

- your **AI model and providers** — pick a model, see the router status and which providers are reachable, and which one is serving you. ArchHub can also **detect local models** (for example via Ollama) and prefer them when present, so you can run on your own machine.
- **permissions** for what actions are allowed,
- **theme** and **accessibility** preferences.

Your account details (email, plan, messages remaining) are handled through the native account settings.

> **A note on cloud AI:** a fully free, zero-setup cloud model out of the box is still being finished — depending on your setup a hosted model may ask for a key. Local models (above) are the reliable no-cost path today.

---

## On the web

You do not have to be in the app for everything. [archhub.io](https://archhub.io) has:

- the **landing** page, **features**, **pricing**, **security**, **community** and **changelog**,
- **Sign in / Get started** via the same magic link,
- and an **Account** page that shows your plan and messages remaining once you are signed in.

Use the website to **download** the desktop app, manage your account, and read what is new.

---

## Coming soon (honest status)

So you are never surprised, here is what is **not** finished yet and should not be relied on as done:

- **A self-building agent** that takes any request and builds the whole feature for you, end to end. The pieces exist (the composer, the checking step, the brain), and there are early **Plan-only** building slots that never apply on their own — but the full "ask for anything, it builds it and proves it" loop is not assembled and shipped.
- **The website brain portal** (a signed-in view of your cloud brain on the web) — planned, not yet on the live site's main build.
- **Sign in with Google** — the code is in place but needs the provider configured before it works; today it returns "not configured."
- **A free, no-key cloud AI model** out of the box — in progress.
- **Automatic recovery from the blank-on-NVIDIA issue** — for now use the environment-variable workaround above.
- **Live purchasing** (Stripe/Polar) — checkout exists but real prices are not switched on yet; the UI says "Coming soon" where that applies.

Everything else described on this page is live in the app today.
