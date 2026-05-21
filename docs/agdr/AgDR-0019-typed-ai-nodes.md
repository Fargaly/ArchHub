---
id: AgDR-0019
timestamp: 2026-05-21T00:00:00Z
agent: claude-code (Sonnet)
session: m1-shipping · founder /loop "till you finalize" · "don't sleep"
trigger: AgDR-0001 §"Loose ends" — `ai` action-specific rail
status: proposed
category: architecture
projects: [archhub]
extends:
  - AgDR-0001 §"What collapses" line 67 — "ai action-specific rail (non-chat actions)" left as loose end
  - Slice H+I pattern — typed-node split per category (input/logic/shape/watch/trigger/output)
---

# Typed AI nodes — split `ai` master into AI Chat · AI Complete · AI Classify · AI Tools (matching Slice I pattern)

> In the context of the founder's "loose ends to sweep alongside" call-out
> in AgDR-0001 §SLICE-K notes ("`ai` action-specific rail (non-chat
> actions)"), and given the Slice I pattern that already split
> `logic`/`shape`/`watch`/`trigger`/`output` into typed-per-action nodes,
> I decided to **apply the same split to `ai`**. Today the `ai` primitive
> carries one `action` parameter that selects one of 4 engine types
> (`conversation.chat` / `llm.complete` / `llm.complete_with_tools` /
> `llm.classify`); the right-panel rail shows generic params for ALL 4
> actions. Split: 4 typed nodes — AI Chat / AI Complete / AI Classify
> / AI Tools — each with action-relevant params surfaced in the rail.
> Legacy `ai` primitive stays HIDDEN (engine resolution + back-compat
> for saved graphs). Accepting: the 4 typed AI nodes share the same
> chat-style inspector for `chat` only; non-chat actions render the
> generic param rail (today's grammar param surface), with the
> action-specific params now declared on the typed primitive so the
> rail shows the RIGHT inputs (no more "Complete? Tools? Classify?
> all look the same"). Grammar count: 70 → 74 (under ≤75 cap).

## Context

Slice I (SHIPPED 2026-05-21) split `logic`/`shape`/`watch`/`trigger`/`output`
into typed-per-action primitives. `ai` was deliberately kept as one
master because chat-mode dominated and the conversational UI is
special. The cost: a placed `ai` node with `action=complete` (or
`classify` / `tools`) shows the chat-UI in the right panel —
WRONG for non-chat actions, but the only thing the rail knows how
to do.

The fix is the same shape as Slice I: typed primitives per action,
each declaring its specific param surface in the grammar. The
inspector reads the primitive's params and renders them generically
— the typed-node DECLARATION steers it to the right schema.

## Options Considered

### Fork 1 — Split shape

| Option | Picked | Why |
|---|---|---|
| Keep `ai` master, add action-specific params via a dynamic schema | no | Bloats the master's param list; conditionals in the inspector (show this when action=X, hide that when action=Y) — exactly what Slice I rejected |
| **Split into 4 typed primitives (AI Chat / AI Complete / AI Classify / AI Tools), hide `ai`** | **YES** | Matches Slice H/I pattern · each typed node's param list is exactly what the action needs · zero conditionals in the inspector · the master stays in `PRIMITIVES` (hidden) for engine resolution + legacy back-compat |
| Add 4 typed nodes alongside `ai` (master stays visible) | no | Two ways to place the same node → discovery confusion · the founder-mandated "no decorative nodes" applies |

**Pick: Split + hide master.**

### Fork 2 — Per-action param surface

Each typed node declares only its action's relevant params:

| Typed node | Engine type | Params surfaced in rail |
|---|---|---|
| AI Chat | `conversation.chat` | `model` (text, default 'auto') — chat UI is the primary surface; no other config needed |
| AI Complete | `llm.complete` | `model` (text), `prompt` (text — default if input not wired) |
| AI Classify | `llm.classify` | `model` (text), `options` (text — comma-separated label list) |
| AI Tools | `llm.complete_with_tools` | `model` (text), `prompt` (text), `allowed_tools` (text — comma-separated tool-name whitelist) |

`options` and `allowed_tools` are stored as comma-separated strings
in the rail (the only string-type the grammar param surface supports
today). The engine executors already accept lists OR comma-strings —
verified via the runner's coerce path. A future slice (UI Polish)
could add a "tag chip" widget for these; out of scope here.

### Fork 3 — Legacy `ai` master node behaviour

| Option | Picked | Why |
|---|---|---|
| Delete `ai` primitive entirely | no | Saved graphs with `cat: 'ai'` would orphan — bad UX for users with on-disk graphs |
| **Hide `ai` from palette, keep in `PRIMITIVES` for engine resolution + back-compat (Slice H/I pattern)** | **YES** | Saved graphs still cook · no engine-side break · new placements come from typed primitives only |
| Convert legacy placements at load time | no | Migration risk; "stays as legacy" is the established pattern |

**Pick: Hide + keep.**

## Decision

### 4 new typed primitives in `node_grammar.PRIMITIVES`

```python
Primitive(
    "ai_chat", "AI Chat", "ai", "",
    {"": "conversation.chat"}, READY,
    "conversation.chat — full chat UI with streaming + tool calls",
    params=({"k": "model", "v": "auto", "type": "text"},),
    blurb="Chat with Claude — streaming, tool-use",
),
Primitive(
    "ai_complete", "AI Complete", "ai", "",
    {"": "llm.complete"}, READY,
    "llm.complete — single-shot prompt → text completion",
    params=({"k": "model", "v": "auto", "type": "text"},
            {"k": "prompt", "v": "", "type": "text"}),
    blurb="Single-shot LLM completion",
),
Primitive(
    "ai_classify", "AI Classify", "ai", "",
    {"": "llm.classify"}, READY,
    "llm.classify — pick one option from a list",
    params=({"k": "model", "v": "auto", "type": "text"},
            {"k": "options", "v": "", "type": "text"}),
    blurb="Classify text into one of N options",
),
Primitive(
    "ai_tools", "AI Tools", "ai", "",
    {"": "llm.complete_with_tools"}, READY,
    "llm.complete_with_tools — full tool-use loop",
    params=({"k": "model", "v": "auto", "type": "text"},
            {"k": "prompt", "v": "", "type": "text"},
            {"k": "allowed_tools", "v": "", "type": "text"}),
    blurb="LLM with tool-use loop · optional whitelist",
),
```

### Existing `ai` master → hidden

```python
Primitive(
    "ai", "AI", "ai", "action",
    {
        "chat": "conversation.chat",
        "complete": "llm.complete",
        "tools": "llm.complete_with_tools",
        "classify": "llm.classify",
    }, READY,
    "legacy — replaced by typed AI Chat / AI Complete / "
    "AI Classify / AI Tools (slice K loose-end fix)",
    params=({"k": "action", "v": "chat", "type": "text"},),
    blurb="Ask Claude — chat, complete, classify",
    hidden=True,  # ← NEW (was visible before this AgDR)
),
```

### Grammar count

| Before | After |
|---|---|
| `ai` visible (1 primitive in `◇ AI`) | `ai` hidden + 4 typed primitives in `◇ AI` (chat/complete/classify/tools) |
| `len(PRIMITIVES)` = 70 | `len(PRIMITIVES)` = 74 (under ≤75 cap) |
| `grammar_payload()` count = 61 | `grammar_payload()` count = 64 (still ≤70 bridge cap) |

### JSX surface

No JSX changes required — the existing `addNodeFromLibrary` already
walks `g.params` to lay down param rows. Each typed AI node lands
with its specific params, and the inspector renders the right
fields.

The chat-specific rail (the conversation UI panel) keys off
`n.cat === 'ai'` (lines 793/826/1038/etc) AND a node that has
`messages: []`. Today every `ai` node carries `messages`; the chat
rail shows. For typed AI Complete / AI Classify / AI Tools, the
node does NOT have `messages` — the generic param rail renders
instead. This separation falls out for free: `cat === 'ai'` + has
`messages` → chat UI; `cat === 'ai'` + no `messages` → param rail.

The existing addNodeFromLibrary `_grammar` branch will need a
small tweak: for `ai_chat`, seed `messages: []`. For the others,
do not. This matches the conversation node's existing shape.

## Consequences

### What ships (this slice)

- `app/workflows/node_grammar.py` — 4 new typed primitives + `ai`
  master flipped to `hidden=True`.
- `app/web_ui/studio-lm.jsx` — `addNodeFromLibrary` `_grammar` branch
  seeds `messages: []` on `ai_chat` placements (preserves the chat UI).
- Tests: typed-AI primitives are registered, the `ai` master is
  hidden, grammar count stays under cap, engine types resolve.

### What collapses

- The "ai master shows wrong UI for non-chat actions" loose end.
- The slice K notes' last unresolved item.

### What's reinforced

- The typed-node pattern (Slice H/I) — every category split into
  one-typed-node-per-action surface.
- The inspector becomes dumber + the grammar smarter — the right
  place for action-specific config (the primitive's param list)
  is the only place that needs to change.

### Risks

- A user with a saved graph containing `ai` (master) nodes still
  cooks correctly because the engine type resolution uses the
  hidden primitive's `action` selector. The palette never offers
  the master again — new placements use typed nodes.
- The `options` + `allowed_tools` params are strings (comma-separated)
  rather than lists. The engine accepts both. UX polish (tag-chip
  widget) can come later.

### Tests

| Test | What it proves |
|---|---|
| `test_typed_ai_primitives_registered` | All 4 typed AI primitives exist + resolve to the right engine type |
| `test_legacy_ai_master_is_hidden` | The `ai` primitive's `hidden=True` flag survives + the grammar_payload skips it |
| `test_grammar_count_after_ai_split` | `len(PRIMITIVES) <= 75`, `len(grammar_payload()) <= 70` |
| `test_ai_chat_inherits_conversation_chat_engine` | `engine_type("ai_chat") == "conversation.chat"` |
| `test_ai_complete_inherits_llm_complete` | `engine_type("ai_complete") == "llm.complete"` |
| `test_ai_classify_inherits_llm_classify` | `engine_type("ai_classify") == "llm.classify"` |
| `test_ai_tools_inherits_llm_complete_with_tools` | `engine_type("ai_tools") == "llm.complete_with_tools"` |
| `test_ai_chat_carries_model_param` | The typed primitive declares `model` so the rail surfaces it |
| `test_ai_complete_carries_prompt_param` | AI Complete declares `prompt` |
| `test_ai_classify_carries_options_param` | AI Classify declares `options` |
| `test_ai_tools_carries_allowed_tools_param` | AI Tools declares `allowed_tools` |

## Implementation order

1. ✓ This AgDR (done).
2. Grammar: 4 typed primitives + `ai.hidden=True`.
3. JSX `_grammar` branch: seed `messages: []` on `ai_chat` only.
4. Tests.
5. ROADMAP update.

## Open forks for founder

1. **Future tag-chip widget for `options` + `allowed_tools`.** Today
   they're comma-separated strings; later a chip-input would be nicer.
2. **Action-specific icons.** The 4 typed AI nodes share the `ai`
   category color today. A more specific icon per action (✦ for
   Complete, ◈ for Tools, etc.) is a polish slice.
3. **`temperature` / `max_tokens` params.** Out of scope for this
   MVP — they're available on the underlying engine but rarely
   tuned by users. Add when requested.

## Artifacts

- This AgDR.
- Pending: `app/workflows/node_grammar.py` edits,
  `app/web_ui/studio-lm.jsx` edit, `tests/test_typed_ai_nodes.py` (new).
