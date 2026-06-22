---
title: "Getting started — install, first launch, first win"
description: "Install ArchHub, sign in, and run your first node graph — a plain-English guide for architects and studio leads, no developer setup required."
key: getting-started
---

# Getting started with ArchHub

ArchHub is a desktop app for architects and design studios. It gives you a
visual canvas where you connect your real tools — Revit, AutoCAD, Rhino, Excel,
Word, Outlook, and more — into a graph you can read, run, and reuse. You drive
it by typing what you want into a composer, and it drafts the steps for you to
approve.

This guide takes a brand-new user from nothing to a first working result. You
do not need to be a developer, and you do not need to touch a terminal.

---

## 1. Install ArchHub (Windows, click-only)

Pick whichever of these you prefer. All three install the same app.

**Option A — Direct download (simplest):**

1. Go to **[github.com/Fargaly/ArchHub/releases/latest](https://github.com/Fargaly/ArchHub/releases/latest)**.
2. Download the file named **`ArchHub-Setup-x.y.z.exe`** (the `x.y.z` is the
   version number).
3. Double-click it and follow the installer.

> **Heads-up about the Windows warning.** Windows SmartScreen may show a blue
> "Windows protected your PC" dialog the first time, because the app is not yet
> code-signed. Click **More info → Run anyway** to continue. (Code signing is
> on the roadmap.)

**Option B — winget** (if you use the Windows package manager):

```
winget install Fargaly.ArchHub
```

**Option C — scoop or choco:**

```
scoop install https://raw.githubusercontent.com/Fargaly/ArchHub/main/installer/scoop/archhub.json
```
```
choco install archhub
```

The installer creates a **desktop icon** and a **Start-menu shortcut**, so after
this you launch ArchHub like any normal Windows app.

> **Running from source (any OS, optional, for technical users).** Clone the
> repository, then run `pip install -r app/requirements.txt` followed by
> `pythonw app/main.py`. Most users should use the installer above.

---

## 2. First launch

Double-click the **ArchHub** icon. A single application window opens — this is
the whole product; everything happens inside it.

On the very first run, a short **sign-in step** appears. ArchHub signs you in to
a cloud account so it can give you a chat-capable AI to drive your graphs:

1. Enter your email address.
2. ArchHub sends you a **magic link** — open the email and click the link to
   confirm. (There is no password to create.)
3. You land back in the app, signed in on the **free open-beta tier**. No credit
   card is required to start, and a number of trial messages are included.

> **Note on sign-in options.** Email magic-link sign-in is the supported path
> today. "Sign in with Google" is built but not yet switched on — it needs
> final account configuration, so use email for now.

> **Note on the AI model.** The free trial gives you a working hosted AI to get
> started. A permanently free, zero-setup cloud model is still being finalized,
> so once your trial messages run low you may be asked to add your own AI
> provider key or pick a paid plan. You can also point ArchHub at a **local
> model** you run yourself (see *Settings* below) — those are detected
> automatically and preferred when available.

### If the window opens but stays blank

On some NVIDIA graphics cards the embedded view can render as a blank window.
If that happens, set this Windows environment variable and relaunch:

```
ARCHHUB_VERIFY_NO_GPU=1
```

(Open **Start → "Edit the system environment variables" → Environment
Variables → New**, name it `ARCHHUB_VERIFY_NO_GPU`, value `1`.) This switches
to software rendering and fixes the blank screen. An automatic fallback is on
the roadmap.

---

## 3. The Home screen — what you're looking at

When you're signed in, you land on **Home**. Here's what's on it:

- **The ArchHub wordmark** at the top.
- **Your recent sessions** — a grid of cards (with thumbnails) for the graphs
  you've worked on. It's empty on day one; this is where your work will collect.
- **An account chip** showing your real account state — your email, your plan,
  and how many AI messages you have remaining. (These are live numbers, not
  placeholders.)
- **A graph-health indicator** that, once you have a graph open, tells you
  whether it's wired up cleanly. Click it for the detail.

Think of Home as your project shelf: each session is one canvas you can reopen.

---

## 4. Your first win — run something on the canvas

Here's the shortest path to seeing ArchHub actually do work.

### Step 1 — Open a canvas

From Home, **create a new session**. This opens the **canvas** — the open
workspace where your graph lives. You'll see a toolbar and an empty grid.

### Step 2 — Tell the composer what you want

At the bottom of the canvas is the **composer** — a text box you type into,
like a chat. Describe what you want in plain language (for example, "list the
sheets in my open Revit model" or "read the values from my open spreadsheet").

ArchHub turns your request into a **plan**: a set of steps shown for you to
review. Nothing runs automatically without your say-so. You choose how much
control you want:

- **Plan mode** — ArchHub proposes the steps and waits; you approve each one.
- **Auto mode** — ArchHub runs the approved steps for you.
- **YOLO mode** — for when you trust it to run straight through.

Approving a step is how a plan becomes a real action. The history of these
plans is saved with the session, so you can look back at what ran.

> **Tip:** You can also click the microphone in the composer to dictate instead
> of type.

### Step 3 — Add a tool (connector) node

ArchHub ships with **19 connectors covering 155 operations** — the real apps
architects use. To add one to your canvas, open the **library** with **Cmd-K**
(or the library button), search for the app you want, and drop its node onto the
canvas.

Each connector operation is honest about its status: it tells you whether the
target app is **live** (running and reachable), **loaded but not running**,
**not installed**, or **needs authorization**. So you always know whether a
step can actually run before you run it.

A few examples of what's available out of the box:

- **Revit** — list sheets, walls, doors, windows, levels, rooms, families,
  warnings; set parameters; place tags. (19 operations.)
- **AutoCAD** — list layers, blocks, entities, layouts, xrefs; run commands.
- **Rhino** — read document info, layers, objects; run scripts.
- **Excel / Word / PowerPoint / Outlook** — read and write workbooks, find and
  replace in documents, build slides, draft email.
- **Photoshop / Illustrator / InDesign** — list documents, layers, artboards;
  export.
- **Procore / Notion / Dropbox / Teams / Speckle** — RFIs, submittals, pages,
  files, messages, model exchange.

The desktop apps (Revit, AutoCAD, 3ds Max, Blender) connect through a small
helper that ArchHub installs into the app; Office and Adobe apps connect
directly; cloud services connect over the web. The first time you use a desktop
connector, ArchHub will tell you what one-time activation step it needs (for
example, an add-in for Revit).

### Step 4 — Run it and read the result

Run the operation (via your approved plan, or by running the node directly). The
result comes back into the canvas, where you can wire it into the next node.
That wiring — output of one tool feeding the input of the next — is the whole
idea: you build a small, readable pipeline you can run again tomorrow.

**That's your first win:** a real operation, against a real tool, on a canvas
you can save and reopen.

---

## 5. What else is in the app

Once you're comfortable, these are the other surfaces worth exploring:

- **Library** — browse and search every node type, create your own node types,
  and save a useful arrangement as a reusable **skill**.
- **Sessions** — create, open, rename, duplicate, fork, or delete your graphs,
  and sync them to the cloud so they follow you between machines.
- **The Brain** — a personal memory that learns from your work. You can browse
  it as folders, search your facts, and back it up to the cloud. (Your brain
  backup is write-only and has secrets stripped before it leaves your machine.)
- **Settings** — choose your AI providers and see router status, set
  permissions, pick a theme, and adjust accessibility preferences. This is also
  where you point ArchHub at a **local model** if you run one. Account details
  (email, plan, messages remaining) open here too.
- **Self-Heal Inspector** — shows when ArchHub has repaired its own wiring.

> **What's still coming.** ArchHub is in open beta. A few things are built but
> not yet switched on for everyone: a self-extension loop that lets the agent
> build new connectors for you (today it only proposes; it never applies on its
> own), the website's signed-in brain portal, Google sign-in, and a permanently
> free cloud model. The features described above are live today.

---

## 6. Using ArchHub from the website

You can also start from **[archhub.io](https://archhub.io)**:

- **Download** takes you to the desktop installer.
- **Sign in / Get started** runs the same email magic-link flow as the app.
- **Account** shows your plan and how many messages you have remaining.
- **Features**, **Pricing**, **Security**, **Community**, and **Changelog**
  pages explain the product in more depth.

The desktop app is where the real work happens; the website is for downloading,
signing in, and managing your account.

---

## You're set

You've installed ArchHub, signed in on the free tier, opened a canvas, and run
a real operation against one of your tools. From here, keep stacking nodes into
graphs, save the good ones as skills, and let the Brain learn your patterns.

Welcome to ArchHub — drafted, not generated.
