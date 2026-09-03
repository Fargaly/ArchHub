---
title: "Account & website — sign in, your license, plan, and brain portal"
key: account-web
description: "How to sign in or sign up, where to see your plan and remaining messages, how billing works, and where your brain lives — across the desktop app and archhub.io."
---

# Account & website

This page explains the parts of ArchHub that sit *around* the work: how you sign
in, where your account and plan live, how billing works, and where to find your
synced brain. It is written for the person running the firm, not a developer —
no terminal required.

There are two places you'll touch your account:

- **The desktop app** (the studio where you actually do the work).
- **The website, [archhub.io](https://archhub.io)** (where you download the app,
  sign in, and check your plan from any browser).

Both read the *same* account, so your email, plan, and remaining messages match
wherever you look.

---

## 1. Signing in (or signing up)

ArchHub uses **magic-link sign-in** — there is no password to remember.

### From the website

1. Go to **[archhub.io](https://archhub.io)**.
2. In the top navigation, click **Sign in** (or **Get started** if you're new).
3. You land on the **Sign in** page. Enter your email address.
4. ArchHub emails you a link. Open the email and click the link — that signs you in.

No credit card is required to create an account. New accounts start on a free
tier with a set number of trial messages included, so you can try the product
before paying.

### From the desktop app

The **first time you launch the app**, a short first-run setup walks you through
signing in to a cloud model using the same magic-link flow. Once you're signed
in, the app remembers you.

> **A note on "Sign in with Google":** the Google sign-in button may appear, but
> Google sign-in is **not switched on yet** — it needs configuration on our side
> first. For now, please use the **email magic link**, which works today. Google
> sign-in is coming soon.

---

## 2. Where your account lives in the app

When you open the desktop app you land on the **Home** view. Home shows three
things tied to your account:

- **Your recent sessions** — a grid of cards (with thumbnails) for the graphs
  you've been working on, so you can jump back in.
- **The account chip** — shows your **email**, your **plan**, and how many
  **messages you have remaining**. These are read live from your real account —
  nothing here is hardcoded.
- **A graph-health indicator** — a small chip/badge that tells you the health of
  your current work and opens a real detail view when clicked.

To change account-level things, open **Settings**. The account settings open in
a native dialog that shows your **email, plan, and remaining messages**, pulled
from your live account. Settings is also where you manage your AI model
providers, the model router, permissions, theme, and accessibility preferences.

---

## 3. Your account on the website

You can also check your account from any browser without opening the app.

1. Go to **[archhub.io](https://archhub.io)** and **Sign in** (magic link).
2. Use the **Account** link in the navigation.
3. The **Account** page shows your **email**, your **plan**, and your
   **messages remaining** — the same numbers you see in the app.

The website navigation also gives you the rest of the public site: **Home**,
**Features**, **Pricing**, **Community**, **Security**, and **Changelog**, plus
**Download** (to get the desktop app) and **Get started**.

---

## 4. Your license and plan

ArchHub has three tiers — **Solo**, **Studio**, and **Firm** — plus a **free
trial** tier for new accounts. Your tier governs how much you can do (for
example, the caps on your usage and how your brain scales).

There are two ways to run the AI behind ArchHub:

- **Bring-your-own-key (BYO):** you plug in your own model provider key, and
  ArchHub uses it.
- **Hosted AI:** ArchHub runs the model for you through its cloud, metered in
  messages.

You can see which plan you're on, and how many messages remain, from the
**account chip on Home**, from **Settings**, or from the **Account** page on the
website.

### Buying and managing your plan

- **Pricing** lives on the **[Pricing](https://archhub.io/pricing)** page.
- Plans are billed through **Stripe** (with Polar as an optional alternative).
  There is also a **message credit pack** — roughly **$10 for 1,000 messages** —
  for topping up hosted-AI usage.
- A **billing portal** is available to manage your subscription after you've
  purchased.

> **Heads-up on purchasing:** live checkout and the published prices are still
> being finalized. Where a plan isn't ready to buy yet, you'll see a **"Coming
> soon"** label instead of a checkout button. Treat live purchase as **coming
> soon** rather than guaranteed today.

> **A note on free cloud AI:** a zero-setup free cloud model is **not** promised
> yet. If you use hosted AI without a configured key or credits, a request may be
> declined until billing or a key is in place. The reliable free path today is
> the **trial messages** on a new account, or **bringing your own key**.

---

## 5. Your brain (and where it lives)

The **brain** is ArchHub's personal memory. It learns from your work and feeds
context back into the app so it gets more useful over time.

- **In the app**, you can browse your brain directly: a **Brain browser** and a
  **folders view** organize your facts into folders and facets, and you can
  search, browse, and view individual facts and memories. You can also see brain
  status and statistics, and add memory facts.
- **Cloud backup / sync:** the desktop app can push your brain to the cloud as a
  backup. This sync is **write-only** and **strips secrets** before sending — it
  copies your knowledge to your own private per-user replica, it does not pull a
  shared brain back down.

### The brain portal on the website

The website is intended to give you a **brain portal** — a place to see your
synced cloud brain after signing in. Today this portal is **still being built**
(it is a work in progress and not yet a finished, shipped feature). For now,
**the in-app brain browser is the reliable place** to explore your memory. The
web brain portal is coming soon.

---

## 6. Getting started, end to end

A clean path for a brand-new user:

1. **Install the app (Windows, no terminal needed).** From
   **[archhub.io](https://archhub.io)** click **Download**, or install via
   `winget install Fargaly.ArchHub`. You can also download the
   **ArchHub-Setup** installer from the project's GitHub releases and
   double-click it. The installer adds a desktop icon and a Start-menu shortcut.
   - *On first launch you may see a Windows SmartScreen warning* (until the app
     is code-signed) — this is expected; choose to run anyway.
2. **First launch & sign-in.** The app opens and walks you through signing in to
   a cloud model with a **magic link** — free tier, **no credit card**, trial
   messages included.
3. **First action.** You land on **Home** (recent sessions + account chip +
   graph health). Create a session, open the canvas, and start working — type in
   the composer to drive your graph, or drop a connector node and run it.
4. **Check your account from the web** anytime: visit
   **[archhub.io](https://archhub.io)** → **Account** to see your **plan** and
   **messages remaining**.

> **Known launch issue (workaround):** on some NVIDIA graphics cards the app
> window can open **blank**. If that happens, set the environment variable
> `ARCHHUB_VERIFY_NO_GPU=1` and relaunch. An automatic fallback for this is on
> the way.

---

## Quick reference

| What you want | Where to find it |
| --- | --- |
| Sign in / sign up | **Sign in** on archhub.io, or first-run in the app (magic link) |
| Your email, plan, messages left | Account chip on **Home**, **Settings**, or **Account** on the web |
| Buy / manage a plan | **Pricing** page + billing portal (some options "coming soon") |
| Top up usage | $10 / 1,000-message credit pack |
| Explore your memory | **Brain browser / folders** in the app |
| Back up your brain | Cloud backup (write-only, secrets stripped) in the app |

*Coming soon: Google sign-in, the website brain portal, finalized live checkout,
a zero-config free cloud model, and automatic GPU fallback.*
