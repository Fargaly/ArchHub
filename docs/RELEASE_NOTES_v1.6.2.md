# ArchHub v1.6.2 — release notes

> Reference — not the roadmap; see [docs/ROADMAP.md](ROADMAP.md).

The "nothing for show only" release. Every surface you click now does something
real — the shells are gone, and a chat session opens as a readable graph.

## What you will see

- **The left rail works from Home.** Deck, Nodes, Skills, Search, and Share each
  open their real panel from the home screen (they used to do nothing there).
- **A real Share panel.** Lists your skills + sessions with Copy link / Export /
  Publish — no fake rows.
- **Browse your brain as folders.** The Brain view has a Cards / Folders toggle;
  Folders is a real tree — scope → project → fact — that drills to each note.
- **Settings are all real.** The fake language selector is gone; default-model,
  show-local-models, Communities subscribe, the per-provider Keys "Test"
  buttons, and your profile all take effect and persist.
- **Graph-health chip opens the real issue list** in one click, and on Home it
  honestly reads "no canvas open" instead of a misleading green.
- **"Clear all nodes" actually clears** the whole canvas (the toast tells the
  truth).
- **Your account chip is real** — your email + plan, sourced from the live cloud
  account, not a hardcoded name.
- **A chat session opens as a logical graph** — repeated reasoning turns collapse
  into one node, the real steps lay out as a left-to-right flow, instead of a
  wall of identical cards.

## Under the hood

- Free AI fleet wired: local models (ollama / LM Studio) + flat-rate Codex +
  NVIDIA NIM free frontier models (DeepSeek R1, Nemotron, Llama 3.3) — the
  standing dispatcher runs on these at zero marginal cost.
- Reference docs for the cloud, user database, permissions, and brain.
- Cloud sign-in hardened (Google id_token verified locally via JWKS).
