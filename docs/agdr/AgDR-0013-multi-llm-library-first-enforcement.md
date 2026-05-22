---
id: AgDR-0013
timestamp: 2026-05-20T00:00:00Z
agent: claude-code (Sonnet)
session: node-redesign-loop · post-direction-x
trigger: founder constraint "WHATEVER APPLIES TO ONE AI APPLIES TO ALL — NOT JUST ANTHROPIC" + 4th prototype `composer-library-multi-llm.html`
status: proposed
category: architecture
projects: [archhub]
supersedes:
  - AgDR-0012 §"Composer tool surface" line 122 — replaces the Anthropic-specific
    `strict: true` enforcement claim with a model-agnostic 4-layer enforcement
    model. AgDR-0012 stays the master architecture lock; this AgDR refines
    only its enforcement layer.
---

# Multi-LLM enforcement layer for the LIBRARY-FIRST + MODULARITY mandates

> In the context of locking how ArchHub forces every connected LLM (Anthropic,
> OpenAI, Gemini, Ollama, LM Studio) to honour the LIBRARY-FIRST and
> MODULARITY mandates from AgDR-0012, I decided to enforce them at **four
> layers**: (1) one shared system prompt across all providers; (2) per-provider
> strict-tool-mode where the provider supports it; (3) a model-agnostic
> **router-level pre-execute gate** in `llm_router._complete_once` that runs
> BEFORE every `ToolEngine.invoke()`; (4) a **library validator** that hard-
> rejects any `library.create_node_type(spec)` whose spec is non-modular.
> Layers 3 and 4 are the structural backstops — they hold even when the LLM
> ignores layers 1 and 2 (which it will, especially on Ollama / LM Studio).
> Accepting: every new tool call pays the router-gate's per-call overhead
> (~0.5ms validation + state check); the validator demands `examples`
> upfront and Skills that ship without examples get rejected on save (M3
> migration adds examples to legacy Skills); Ollama / LM Studio fall back
> to "prompt-only" enforcement when the model has no tool-call format —
> the gate still works because the router rewrites pseudo-tool-calls into
> real `ToolInvocation` records before dispatch.

## Context

- AgDR-0012 §"LIBRARY FIRST" mandates that `library.search` is called BEFORE
  `library.create_node_type`. The line that records the enforcement
  mechanism reads: *"Hard rule, enforced in the system prompt + tool-use
  schema (Anthropic `strict: true`)."*
- Founder corrected this 2026-05-20:
  > "DON'T FORGET THAT YOU HAVE MULTI LLM APPLICATION THAT DEALS WITH ALL
  > MODELS... WHATEVER APPLIES TO ONE AI... APPLIES TO ALL... NOT JUST
  > 'ANTHROPIC'"
- Provider tool-call support varies wildly:
  - **Anthropic** — `tool_use` blocks, `strict: true`, `input_json_delta`
    streaming, parallel tool calls.
  - **OpenAI** — `tools` array, `function_call` (legacy) / `tool_calls`
    (new), `strict: true` on JSON Schema, parallel tool calls.
  - **Gemini** — `function_declarations`, `MODE: ANY | AUTO | NONE`, no
    streaming partial-args, parallel only on 1.5+.
  - **Ollama** — `tools` array (since 0.3.x), per-model support varies
    (Llama 3.2, Mistral Small, Qwen 2.5 yes; older 7-8B models often
    fabricate calls — see existing `_looks_like_fabricated_tools` guard
    at `llm_router.py:283`).
  - **LM Studio** — OpenAI-compatible tools API since 0.3.5; same
    per-model variance as Ollama.
- ArchHub's existing tool-use loop is in `llm_router._complete_once`
  (`llm_router.py:1178-1463`). Tool calls are dispatched via
  `self.tools.invoke(inv.tool_name, inv.arguments)` at line 1386. The
  router already normalises per-provider tool-call shapes into a
  uniform `[{id, name, input}]` list (line 1364, 1372). **This is the
  natural insertion point for a model-agnostic gate.**
- AgDR-0012 also defines MODULARITY (typed I/O + parameterised
  `config_schema` + description + `examples`). The 4th prototype
  (`composer-library-multi-llm.html`) demonstrates a validator that
  rejects bare `config_schema` + missing `examples` + short
  `description`, forcing the AI to retry with a modular spec.

## Options Considered

### Fork 1 — Where does enforcement live?

| Option | Picked | Why |
|---|---|---|
| **A) Per-provider strict tool mode only** (Anthropic `strict:true`, OpenAI `strict:true`, Gemini `MODE:ANY`) | partial | Works for the big 3 hosted providers; FAILS on Ollama / LM Studio (no strict mode); FAILS when LLM emits valid-shaped but wrong-ordered calls (e.g. `create_node_type` first) |
| **B) Router-level pre-execute gate** (model-agnostic check in `_complete_once`) | partial | Works across every provider; survives Ollama / LM Studio prompt-fallback; survives pseudo-tool-calls; ~0.5ms overhead per call |
| **C) Both A + B (defense in depth)** | **YES** | A catches early at the provider boundary (cheaper retry — the LLM never even sees the gate denial); B catches what A misses; degrades gracefully if any layer breaks |
| D) System prompt only (honor-system) | no | Fails the moment the LLM ignores instructions — and ROADMAP audit history shows it does (see `_looks_like_fabricated_tools`) |

**Pick: C** — defense in depth. Strict mode at the provider where available, router gate as universal backstop.

### Fork 2 — How is "`library.search` BEFORE `library.create_node_type`" enforced?

| Option | Picked | Why |
|---|---|---|
| A) System prompt instruction only | partial | Necessary but not sufficient — Layer 1 |
| B) Tool ordering hint in provider tool schema (description, `examples` field) | partial | Reinforces but doesn't enforce — Layer 1.5 |
| **C) Router state machine** (per-turn flag: `_library_searched_this_turn`; gate denies `create_node_type` until flag set) | **YES** | Structural enforcement at Layer 3; works across providers |
| D) Validator-only | no | By the time the validator runs, the LLM may have already created cruft |
| E) Hide `create_node_type` from the tool list until `library.search` has been called this turn | partial alt | Cleaner UX but harder to implement in the router (tool schemas are computed once per turn); flagged as a future polish (M3.x) |

**Pick: A + C** — system prompt nudges, router state machine enforces. The "hide tool until prereq" (E) is logged as an M3 polish opportunity.

### Fork 3 — Modularity validator strictness

| Option | Picked | Why |
|---|---|---|
| **A) Hard reject** — no register without typed I/O + `config_schema` + `description ≥ 60 chars` + `examples ≥ 1` | **YES** | Founder mandate "don't compromise on modularity" demands a hard floor. 4th prototype showed this in action — validator rejects, AI retries with modular spec, then accepts |
| B) Warning + register | no | Allows decorative cruft into the library — exactly what slice 4 had to clean up |
| C) Auto-fill missing fields from LLM | no | The LLM filling its own missing fields = circular; the human user is the auth |

**Pick: A** — hard reject. AI retries in the same turn. Founder's "MODULARITY non-negotiable" demands the floor.

### Fork 4 — Per-provider tool-mode coverage

| Option | Picked | Why |
|---|---|---|
| A) Require all providers support tools; drop non-compliant models | no | Locks user out of perfectly good models (e.g. 7-8B Ollama models) |
| **B) Auto-detect per provider/model; degrade gracefully to prompt-fallback** | **YES** | Matches existing `_looks_like_fabricated_tools` heuristic; surfaces "structured mode unavailable on this model" to the user |
| C) Anthropic, OpenAI, Gemini = strict-tools; Ollama / LM Studio = prompt-fallback (no in-between) | partial | A pragmatic default; folded into B as the per-model setting |

**Pick: B** — auto-detect. Provider client surfaces `supports_strict_tools: bool`; router uses it to choose strict-mode vs prompt-fallback. User sees the mode badge on the model pill (prototype shows this).

### Fork 5 — Validator schema definition language

| Option | Picked | Why |
|---|---|---|
| A) JSON Schema directly | partial | Portable but verbose for the validator |
| **B) Pydantic v2 model** in Python; emits JSON Schema for the JSX client | **YES** | One source of truth; the JSX validator (a thin client-side echo) consumes the emitted schema; works with the existing `tool_engine.py` patterns |
| C) Custom Python class hand-written | no | Reinvents Pydantic; harder to evolve |
| D) TypeScript types as source of truth | no | Engine is Python; doesn't fit |

**Pick: B** — Pydantic v2 source of truth. `app/library_validator.py:NodeSpec(BaseModel)`. `NodeSpec.model_json_schema()` → JSX validator consumes the same shape.

## Decision

### The 4 enforcement layers

```
Layer 1 — System prompt
  One shared prompt across every provider. Two mandate lines:
    • "Before composing a new node, call library.search to check for
       an existing match (≥0.75 similarity = use existing)."
    • "Every new node MUST include typed inputs, typed outputs,
       config_schema, description ≥ 60 chars, and at least one
       example."
  Built in `llm_router._build_system_prompt()` (line 1472), with a
  composer-specific addendum loaded only when the composer panel is
  the active surface.

Layer 2 — Per-provider strict tool mode
  Where the provider supports it:
    • Anthropic — `tool_choice: {type: "tool", name: "library.search"}`
       on the first composer turn; later turns use `tool_choice: "auto"`
       with `strict: true` schemas.
    • OpenAI — `tools[*].function.strict: true` + JSON Schema with
       `additionalProperties: false`.
    • Gemini — `function_declarations` with `MODE: ANY` on the first
       composer turn, `MODE: AUTO` thereafter.
    • Ollama / LM Studio — best-effort; per-model auto-detect via the
       client's `supports_strict_tools` probe.

Layer 3 — Router-level pre-execute gate
  Inserted in `llm_router._complete_once` BETWEEN tool-call extraction
  (line ~1376) and `ToolEngine.invoke()` (line 1386). New module
  `app/library_gate.py`:

    class LibraryGate:
        def check(self, inv: ToolInvocation,
                  turn_state: TurnState) -> GateDecision

  Per-call rules:
    1. If `inv.tool_name == "library.create_node_type"`:
         • require `turn_state.library_searched is True`
         • require `validator.validate(inv.arguments["spec"]).ok`
         → on fail: return `GateDecision(deny, reason, retry_hint)`
    2. If `inv.tool_name == "library.search"`:
         • mark `turn_state.library_searched = True`
         → allow
    3. All other tools → allow.

  TurnState is reset at the start of each user turn (`messages` list
  grows by one user message → router constructs new TurnState).

  On deny: router converts `GateDecision` into a `tool_result` with
  `status: "error"`, an actionable `error` field
  (`"library.search must run first — call library.search(intent=...) and try again"`),
  and a `retry_hint` payload. The LLM sees a normal tool error and
  the next iteration of the tool-use loop tries again.

Layer 4 — Library validator
  New module `app/library_validator.py`. Pydantic v2 `ModularNodeSpec`
  model. **Renamed from NodeSpec to avoid collision with the existing
  `workflows.registry.NodeSpec` engine dataclass** — same shape role,
  different module, different layer (validator vs registrar):

    class PortSpec(BaseModel):
        name: str = Field(min_length=1, max_length=40)
        port_type: str  # speckle_type or legacy PortType
        required: bool = False
        description: Optional[str] = Field(default=None, max_length=200)

    class ExampleSpec(BaseModel):
        input: dict
        output: dict
        note: Optional[str] = None

    class ModularNodeSpec(BaseModel):
        type: str = Field(pattern=r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")
        display_name: str = Field(min_length=3, max_length=60)
        category: Literal["primitive","connector","ai","transform",
                          "filter","watch","output","skill","glue","adapter"]
        inputs: list[PortSpec] = Field(default_factory=list)
        outputs: list[PortSpec] = Field(min_length=1)
        config_schema: dict  # JSON Schema; must declare at least one property
        description: str = Field(min_length=60)
        examples: list[ExampleSpec] = Field(min_length=1)
        side_effects: Literal["pure", "host_write", "network"] = "pure"

    class ValidationResult(BaseModel):
        ok: bool
        violations: list[str]  # human-readable, one per failing rule

    def validate(spec: dict) -> ValidationResult: ...

  Called from:
    • Layer 3 (router gate, every `create_node_type` invocation).
    • `bridge.save_as_skill` (so SaveSkillDialog rejects non-modular
       skills client-side too — the JSX form uses the JSON Schema
       emitted by `NodeSpec.model_json_schema()`).
    • Library import (drag a .archskill / .archnode file → validate
       first).
```

### Multi-provider client adapter contract

Every LLM client (`AnthropicClient`, `OpenAIClient`, `GoogleClient`,
`OllamaClient`, `LMStudioClient`) gets a new method:

```python
class LLMClient(Protocol):
    def supports_strict_tools(self, model: str) -> bool: ...
    def make_strict_tool_schema(self, schema: dict) -> dict: ...
```

`make_strict_tool_schema` is the provider's strict-shaped version of a
tool schema. For Anthropic + OpenAI + Gemini it adds the provider's
strict marker. For Ollama / LM Studio with a non-tool-following model,
it returns the schema unchanged AND the router falls back to the
prompt-only path (`tools=[]` in the API call, structured calls embedded
in the system prompt with a parse-on-return heuristic — already exists
for the auto-fallback path; we re-use it).

### TurnState lifecycle

```
class TurnState:
    library_searched: bool = False
    nodes_created: list[str] = []
    invocations_this_turn: list[ToolInvocation] = []

# In _complete_once():
turn_state = TurnState()  # fresh per call to complete()
# ... tool-use loop ...
# At loop top, each iteration: turn_state passed to gate
```

A "turn" = one round-trip from user message to assistant final message
(possibly with many internal tool iterations). TurnState resets per
user message, not per tool iteration.

### UX surfaces (already in 4th prototype, called out here)

- Model pill in composer header shows active provider + mode (
  `strict-tools`, `prompt-fallback`).
- When the gate denies, the composer message shows a small
  `⚠ library check ran` chip in the tool-result block, with the
  error reason; LLM retries, success on round 2 shows in the next
  tool block as normal.
- Library tab shows `REUSED` / `NEW · MODULAR` badges on nodes
  created during a Composer session.

## Consequences

### What ships in M3 (compose v1)

- `app/library_validator.py` — Pydantic v2 NodeSpec + validate().
- `app/library_gate.py` — Router gate + TurnState.
- `app/llm_router.py` — patches at `_complete_once` (line ~1386) to
  call the gate.
- `app/library.py` — new module with `library.search`,
  `library.list_node_types`, `library.inspect`, `library.create_node_type`,
  `library.delete_node_type` tool implementations.
- `tool_engine.py` — registers the 5 new `library.*` tools and the
  9 new `graph.*` tools (per AgDR-0012 §"Composer tool surface").
- `app/web_ui/studio-lm.jsx` — composer panel materialises the gate's
  deny → retry → succeed loop visibly.

### What changes in existing code

- Each LLM client gains `supports_strict_tools` + `make_strict_tool_schema`.
- `_complete_once` adds a TurnState construction at the top and a
  gate check inside the tool-call loop.
- `bridge.save_as_skill` validates the skill spec before writing the
  envelope; rejects with a typed error (existing pattern).
- The system prompt builder (`_build_system_prompt`, line 1472) loads
  a composer-mode addendum when `session_pin` indicates a composer
  session.

### What collapses

- The AgDR-0012 §"Composer tool surface" line "enforced as Anthropic
  `strict: true`" is replaced by the 4-layer model above.
- No code regression — AgDR-0012 was `proposed`; this AgDR refines it
  before any code lands.

### Tests / acceptance

1. **Layer 4 validator unit tests** (`tests/test_library_validator.py`):
   bare spec → reject with 6 violations; spec missing examples → reject
   with 1 violation; spec missing typed outputs → reject; modular spec
   → accept. **30+ tests covering each Pydantic field.**
2. **Layer 3 gate unit tests** (`tests/test_library_gate.py`):
   `create_node_type` before `search` → deny with retry_hint; `search`
   then `create_node_type` with modular spec → allow + register;
   non-library tools → always allow.
3. **Integration test** (`tests/test_composer_library_first.py`):
   end-to-end with a mocked LLM client emitting the EXACT prototype
   sequence — search hits, search miss → create_node_type rejected
   → create_node_type with modular spec accepted. Asserts every
   provider client wired into the same gate.
4. **Cross-provider smoke**: same composer prompt run through
   AnthropicClient + OpenAIClient + GoogleClient with mocked tool
   responses; assert all three pass through the gate identically.

### Risks

- The composer addendum to the system prompt adds ~500 tokens per
  turn. Mitigate: cache the system prompt block (Anthropic prompt
  caching, OpenAI prompt cache, Gemini cached_content).
- Ollama / LM Studio prompt-fallback parsing is fragile. The existing
  `_looks_like_fabricated_tools` heuristic already mitigates; we add
  a structured-JSON-only fallback parser specifically for the library
  tools.
- Validator rejects every legacy Skill that lacks `examples`. M3
  migration includes a one-shot `bridge.migrate_legacy_skills` that
  generates `examples` from the saved input/output snapshots (or
  marks the skill as non-modular and parks it).
- TurnState lives per-router-instance — if multiple ArchHub windows
  share a router, turn state leaks. Confirmed not an issue:
  `LLMRouter` is per-`MainWindow` (one window = one router instance).

## Open forks — RESOLVED by AgDR-0014 (design-system audit)

Founder responded `/design-system` — "don't pick decimals, design the system."
AgDR-0014 audits the library as a design system and derives the answers from
principle:

1. **Multi-LLM enforcement.** ✅ Auto-detect + prompt-fallback. Layers 3 + 4
   are the structural backstop; the provider boundary is degradable.
   "Flexibility within constraints."
2. **Description floor.** ✅ Bumped 60 → **80 chars** (one full descriptive
   sentence; empirical from Speckle ~110 / ComfyUI ~95).
3. **Examples count.** ✅ **Tiered by `side_effects`**: pure ≥1, host_write
   ≥2, network ≥2. State coverage scales with side-effect class.
4. **Hide `create_node_type` until `search` ran.** ✅ **NO — keep visible.**
   Layer 3 router gate enforces order structurally. "Consistency over
   creativity" — conditional tool surfaces are harder to reason about.
5. **Category enum.** ✅ Realigned 10 → **11 values** matching engine `cat`
   (`input · connector · ai · logic · output · skill · shape · watch · note`)
   + `glue · adapter`. `primitive` removed (axis collision); `transform` +
   `filter` collapsed to `shape`.

See **`docs/agdr/AgDR-0014-library-design-system.md`** for the full audit
(tokens, components, patterns) and the rationale chain.

## Artifacts

- This AgDR.
- `docs/prototypes/composer-library-multi-llm.html` — the 4-layer
  enforcement visualisation + live demo of validator rejecting then
  accepting a modular spec.
- Supersedes the Anthropic-specific enforcement claim in
  AgDR-0012 line 122 (which stays the master architecture lock —
  this AgDR only refines its enforcement section).
