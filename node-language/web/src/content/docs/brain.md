---
title: "The brain — local memory, folders, and the cloud portal"
description: "How ArchHub's brain remembers your work locally, organizes it into folders, backs it up to the cloud, and what each plan tier gives you."
key: brain
---

# The brain — local memory, folders, and the cloud portal

ArchHub has a **brain**: a memory that learns from your work as you use the app, keeps it organized, and (if you sign in) backs it up to your private cloud space. This page explains, in plain language, what the brain is, where your data lives, how to see and search it inside the app, and how the plan tiers govern it.

No developer knowledge is needed. Everything below is a real button, panel, or behavior in the app today.

---

## What the brain is

The brain is a small **memory engine that runs on your own computer**, alongside the ArchHub desktop app. As you work — drafting on the canvas, running connectors, talking to the composer — useful facts get remembered so the app can recall them later instead of starting from scratch each time.

Two things make it distinctive:

1. **It's local first.** Your memory database lives on your machine, in your own user folder. Nothing has to leave your computer for the brain to work.
2. **It's organized like folders.** Instead of one undifferentiated pile of notes, the brain sorts what it learns into folders and facets you can browse, just like files on disk.

---

## Where your memory lives

Your brain is a database file kept under your Windows user data:

```
%APPDATA%\ArchHub\brain\brain.db
```

That single file is *your* brain. It is created automatically the first time the app runs — you don't set it up by hand.

The brain runs as a quiet background helper (the `personal-brain` service) that the app starts for you. You never have to launch it manually.

---

## Seeing your brain inside the app

Open ArchHub (launch **ArchHub** from your desktop or Start menu). Everything brain-related lives inside the desktop window. The main places to look:

### The brain browser

A panel that lists what the brain currently knows. From here you can **search** your memory by typing a few words and read the facts that come back. Behind the scenes this uses the app's built-in brain search and browse.

### Brain as folders

ArchHub presents your memory as a **folder tree** rather than a flat list. Open the **Brain folders** view and you'll see:

- a tree of folders down the side,
- facet lanes that group related facts,
- the facts themselves when you drill in.

This is the easiest way to get a feel for everything the brain has picked up — you navigate it the same way you'd navigate a project folder.

### Brain cards and chips

While you work, small **brain cards** and **brain chips** surface relevant memory in context — for example, recalling something pertinent right where you're typing — so you don't have to go hunting for it.

### Memory explorer

A dedicated explorer view lets you look through your stored facts in more detail when you want the full picture rather than the in-context glimpses.

---

## How the brain learns (the five quiet loops)

You don't have to teach the brain manually. It learns through five automatic loops that run in the background as you use ArchHub's assistant:

1. **Recall** — before answering you, it pulls in relevant memory so the assistant has context.
2. **Remember** — after an action runs, it writes down what's worth keeping.
3. **Skills** — when a useful pattern emerges, it can mint a reusable skill.
4. **Wiring** — at the start of a session it reconnects everything so your tools are known.
5. **Tool help** — it can augment a step with the right tool when one is needed.

You can also **add a memory fact yourself** from inside the app when you want to record something deliberately.

---

## Backing up and syncing to the cloud

If you sign in (see [Pricing](/pricing) and the in-app sign-in), the desktop app can **back up your brain to your own private cloud space**.

A few honest details about how this works:

- **It's a one-way backup.** The desktop pushes changes *up* to the cloud; the cloud copy is a write-only replica for safekeeping, kept per user.
- **Secrets are stripped.** Sensitive values are removed before anything is sent — your API keys and credentials are not uploaded with your memory.
- **You trigger it from the app.** There's a **brain backup** control inside the brain views; the cloud copy lands in your personal replica.

> **Coming soon:** a web page at archhub.io for browsing your synced brain in a browser is in progress but not yet part of the live website on its main branch. For now, browse and search your brain **inside the desktop app**, which is the complete experience.

---

## Sharing across a team (communities and firms)

The brain isn't only personal. ArchHub includes slots for **communities** and **firm** sharing, so memory and learned patterns can be shared within a group rather than staying on one machine. You'll find a communities panel in the app and firm/seat controls governed by your plan (below).

---

## Self-healing and quality

ArchHub watches its own health. A **Self-Heal Inspector** shows you self-heal activity and statistics, and a **graph-health** badge on the Home screen tells you honestly whether your current work is in good shape — clickable for the real detail, not a fake green light.

---

## Plans and tiers

The brain — and ArchHub overall — is governed by your plan. There are three tiers:

| Tier | Who it's for |
| --- | --- |
| **Solo** | An individual architect or small practice. |
| **Studio** | A studio / team. |
| **Firm** | A larger firm or enterprise — per-seat volume, 10+ seats, SSO + audit. |

Your plan sets the caps that govern how much the brain and the hosted assistant can do. You can see your current plan and how many messages you have remaining:

- **In the app:** the **account chip** on the Home screen shows your email, plan, and messages remaining — read live, never a placeholder.
- **On the web:** sign in at archhub.io and the **Account** page shows the same — your email, plan, and remaining messages.

### A note on billing (coming soon where noted)

ArchHub offers a free tier with a set number of trial messages — **no credit card to start**. Paid tiers and an add-on credit pack (a $10 / 1,000-message top-up) are built into the cloud backend. Where a live purchase isn't yet wired for your region, the app will honestly show **"Coming soon"** rather than pretend a checkout exists. See [Pricing](/pricing) for current details.

---

## Bringing your own AI key vs. hosted AI

The brain works regardless of which AI you use. ArchHub supports two modes:

- **Bring your own key (BYO):** plug in your own provider key in **Settings** and run against it.
- **Hosted AI:** let ArchHub's cloud handle the model for you (subject to your plan's message allowance).

> **Coming soon:** a fully free, zero-configuration cloud model out of the box is still in progress — until then a hosted model may ask for a key or a credit top-up. The local-first brain itself does not depend on this; it works either way.

---

## Quick start with the brain

1. **Install and open ArchHub.** (Windows: `winget install Fargaly.ArchHub`, or download the installer from the [releases page](https://github.com/Fargaly/ArchHub/releases/latest) and double-click.)
2. **Sign in** through the first-run wizard (a magic link to your email — free tier, no card).
3. **Work normally** — draft on the canvas, run a connector, talk to the composer. The brain learns as you go.
4. **Open the Brain folders view** to browse what it has remembered.
5. **Search** your memory any time from the brain browser.
6. **Turn on cloud backup** from the brain views to keep a private, secret-stripped copy safe.

That's the brain: it remembers your work, keeps it in tidy folders, and (when you want) backs it up — all starting on your own machine.

---

### Known launch note

On some NVIDIA graphics setups the app window can open blank. If that happens, set the environment variable `ARCHHUB_VERIFY_NO_GPU=1` and relaunch. An automatic fallback for this is on the roadmap.
