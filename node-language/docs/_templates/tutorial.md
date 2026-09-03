---
slug: example-slug
title: Plain-English title that reads like a user task
prerequisites:
  - ArchHub is running.
  - The relevant MCP is connected.
scope: user        # user | project | firm | community
replay_skill_id:   # set by the reflexion worker after the skill is minted; leave blank for hand-written drafts
freshness:
  source_paths:
    - docs/tutorials/<slug>.md
  last_verified:   # ISO date; updated by tools/tutorial_record.py on successful replay
generator:         # "manual" | "reflexion-worker"
---

# {{ title }}

> A short sentence the user would actually say out loud to describe why
> they came here. No jargon. No slice numbers. No AgDR ids. Plain English.

## Prerequisites

A bullet list mirroring the YAML `prerequisites` field, written so a
first-time user can confirm them in under 60 seconds.

- ArchHub is running.
- Step 1 of `QUICKSTART.md` (Reality Check is all green) passed.

## Steps

Numbered, one action per item. Each step names: what to click or type,
and what the user will see in response. No internal jargon — write as
if the reader has never read the ArchHub repo.

1. **Do this thing.** Where to click, what to type. What you'll see.
2. **Then this.** Same shape.
3. **Then this.** Same shape.

## Expected outcome

One paragraph the user can compare against the real outcome on their
screen. If their screen doesn't look like this, the tutorial is stale
and the replay button below will fail loudly — that's a feature, not a
bug.

## Replay this tutorial

<!-- replay-button-placeholder
This block is replaced by the docs portal renderer with a live "Replay"
button that fires `brain.skill_mint` against `replay_skill_id` in a
fresh session. CI runs this nightly; failures auto-deprecate the page.
-->

{{ replay_button_placeholder }}

## Why this exists

A short note explaining where the tutorial came from — a real successful
trace minted by the reflexion worker, or a hand-written seed. Either way
the user knows this is a recipe that actually worked, not marketing.

---

<!-- engine-details, collapsed by default in the docs portal renderer -->

<details>
<summary>Engineering details (collapsed by default)</summary>

- AgDR / source: `<link>`
- Skill body: `personal-brain-mcp/src/personal_brain/skills/<slug>.json`
- Last reflexion trace: `<trace_id>`

</details>
