# ArchHub — Open-Core Structure

ArchHub uses an **open-core** business model. Here's what that means
in practice:

## What's in this repo (MIT, free forever)

This entire desktop client repository is MIT-licensed (see `LICENSE`).
You can:

- Use it commercially without paying us anything
- Modify the source and ship your own fork
- Sell support / customization services around it
- Bundle it inside a larger product (with attribution per MIT)

Including:

- **Every host connector** — Revit, AutoCAD, 3ds Max, Blender, Outlook
- **The workflow canvas** — node editor, undo/redo, minimap
- **The Skills system** — local library + cloud sync via your own GitHub
- **Marketplace client** — install signed Skills from any registry you trust
- **Brand-voice extraction** — fine-tune messaging from your firm's documents
- **All onboarding flows** — including the silent Ollama auto-installer
- **Multi-instance @session routing** — drive 5 Revit windows at once
- **Reality Check sparklines** — per-host 24h health history

## What's NOT in this repo (proprietary, paid)

The following components are **separate, closed-source projects**
operated by ArchHub (Fargool):

- `cloud.archhub.io` — managed AI proxy. Subscribers get an
  OpenAI-compatible API endpoint that routes their chat traffic to
  Claude / GPT / Gemini without ever exposing provider keys.
- The Stripe billing integration that backs the Solo / Studio / Firm
  tiers.
- The official marketplace publishing key (Ed25519 private half).
  The public half is pinned in `app/marketplace_signing.py`.
- The signed-update channel CDN.

These pieces exist to make money so we can keep building the open
parts. None of them are required to use ArchHub — you can run the
entire desktop client offline with a local AI brain and never touch
our servers.

## What you can do without paying us

- **Run ArchHub offline forever.** Local Ollama, your own files, your
  own connectors. No internet required after install.
- **Bring your own provider keys.** Paste an Anthropic / OpenAI /
  Gemini key into Settings and never see our brand again on the
  network.
- **Self-host the relay.** If you want a firm-wide managed setup but
  don't want to pay us, host your own OpenAI-compatible relay (LiteLLM,
  AnyScale, vLLM) and point ArchHub at it via Settings → Firm relay.
- **Run your own Skill marketplace.** Fork the marketplace catalog,
  generate your own signing keys, point your team at it.
- **Sell support.** The Red Hat model is fair game. We'd appreciate a
  link back, but the MIT license doesn't require it.

## Why open-core?

Three reasons:

1. **Architects trust software they can read.** AEC firms have been
   burned by abandoned plug-ins and proprietary file formats. MIT
   source they can inspect + fork is a much easier procurement
   conversation than a closed-source SaaS-only product.

2. **Local AI is a real option for our users.** Ollama works. Some
   architects will never want our cloud — and that's fine. Charging
   them for software they could run themselves is a losing fight.

3. **The cloud + support businesses are where margins live anyway.**
   Most users pick paid Cloud for convenience even when free local AI
   is available. Firms pay for support contracts because their lawyers
   demand SLAs. We don't need to extract money from the architects who
   genuinely want to run everything themselves.

## Contributing

PRs welcome. The open parts are open in good faith — we won't pull a
"contributor agreement that secretly relicenses your patches" move.
Your patch stays MIT, just like the rest of the file you touched.

If you contribute something that materially competes with our paid
backend (e.g. a community Stripe-replacement), we'll still merge it
if it's good. We're betting the open client adoption is worth more
than the protection.
