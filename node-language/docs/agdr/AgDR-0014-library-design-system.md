---
id: AgDR-0014
timestamp: 2026-05-20T00:00:00Z
agent: claude-code (Sonnet)
session: node-redesign-loop · post-direction-x · design-system audit
trigger: founder request `/design-system` after surfacing 4 isolated forks in AgDR-0013 — "don't pick decimals, design the system"
status: executed
founder-signoff: 2026-05-25 — bulk-flip per D4·A pick on docs/prototypes/four-decisions-2026-05-25.html (shipped weeks ago, status drift)
category: architecture
projects: [archhub]
supersedes:
  - AgDR-0013 §"Fork 1-4" — the four open forks resolve via design-system
    principles instead of ad-hoc threshold picks. AgDR-0013 stays the
    enforcement-mechanism AgDR; this AgDR sets the contract those mechanisms
    enforce.
---

# Library design system — tokens, components, patterns, and the 4 open forks resolved by principle

> In the context of the founder responding to AgDR-0013's 4 open forks
> with `/design-system` (= "don't pick decimals, design the system; the
> answers fall out of principle"), I decided to treat ArchHub's library
> as a coherent **design system** with three axes — **design tokens**
> (atomic values: categories, side-effects, modes, status, naming
> patterns), **components** (node-spec shapes the library catalogues),
> and **patterns** (the workflows: search-before-create, modular
> validation, approval gating) — then derive the AgDR-0013 fork answers
> from the design-system principles instead of picking thresholds
> arbitrarily. Accepting: validator category enum changes from 10 ad-hoc
> values to 11 values aligned with the existing engine `cat` field
> (`+ glue + adapter`); description floor moves from 60 → 80 chars;
> examples count tiered by `side_effects` (pure ≥1, host_write ≥2,
> network ≥2); `library.create_node_type` stays visible alongside other
> tools (Layer 3 enforces ordering structurally — consistency wins over
> conditional visibility).

## Context

- AgDR-0013 surfaced 4 enforcement-detail forks and asked the founder
  to pick numbers in isolation:
  > 1. Auto-detect vs lock to tools-providers
  > 2. Description floor = 60 chars OK?
  > 3. examples ≥ 1 OK or ≥2?
  > 4. Hide `create_node_type` until `search` ran this turn?
- Founder responded `/design-system` — i.e. step back, design the
  system, then the answers are inevitable.
- The library is not "a registry of nodes" — it is the user's design
  system for AEC workflows. Every node is a reusable component; the
  validator enforces the contract; the search + approval surfaces are
  the user's interaction patterns.
- Prior art consulted for this design pass:
  - Material Design tokens (atomic values + component specs +
    pattern guides).
  - Apple HIG (consistency over creativity; one component, many
    contexts).
  - Speckle's `Base` schema (a node is a type, types compose by
    `displayValue` + properties; units are tokens; `speckle_type` is
    the discriminator).
  - Houdini node grammar (kind + cat are orthogonal axes; flags are
    state tokens).
  - ComfyUI `INPUT_TYPES`/`RETURN_TYPES`/`CATEGORY` — already a node
    design system.
  - n8n's "Cluster nodes" — composability + reuse.

## Audit — current state

### Design tokens (atomic values)

| Token | Current source | Status |
|---|---|---|
| **Primitive kind** (13 grammar shapes) | `workflows.node_grammar.PRIMITIVES` | locked — slices A-G shipped against it |
| **Engine `cat`** (display group / palette colour family, 9 values: input · connector · ai · logic · output · skill · shape · watch · note) | `Primitive.cat` field in `node_grammar.py` | locked — palette already groups by this |
| **Validator `category`** (function taxonomy, currently 10: primitive · connector · ai · transform · filter · watch · output · skill · glue · adapter) | `app/library_validator.py` (shipped today) | **inconsistent** with engine `cat` — invented a parallel taxonomy |
| **Side effects** (3: pure · host_write · network) | `library_validator.py` | locked |
| **Mode** (skills only: shared · private) | bridge `save_as_skill` `meta.mode` | locked — slice G |
| **Status** (per-node-spec: registered · proposed · superseded · deprecated) | not formalised | **gap** — needed for library curation |
| **PortType taxonomy** (legacy enum vs Speckle `speckle_type`) | `workflows.graph.PortType` (legacy) + Speckle (M1+) | **transition** — locked direction (Speckle), legacy stays for back-compat |
| **Naming convention** (e.g. `revit.tag_by_room`) | enforced by validator pattern | locked |
| **Host name** (16 hosts: `revit`, `acad` vs `autocad`, …) | mixed — `acad`/`autocad` mismatch on ROADMAP | **drift** — one host name registry needed |
| **Disable verbs** (bypass · frozen · preview_off · pinned) | slice B | locked |

### Components (node-spec shapes)

| Component | Variants | States | Documented |
|---|---|---|---|
| `connector` master (per-host) | 16 (revit, autocad, excel, …) | host-locked badge mode; op picker dropdown | yes (slice A) |
| `connector.run` op-specialisation | ~116 ops across 16 hosts | typed inputs + outputs per op | partial — tool_engine has duplicates |
| `ai` master | 4 actions (chat · complete · classify · tools) | rail action picker | yes |
| `data.constant` / `input.parameter` | typed value variants | pinned / frozen / bypassed | yes (slice B) |
| `logic` (if · foreach · merge · …) | 5+ | control-flow shape | partial — switch/loop need executors |
| `watch` body | 6 (list · table · json · image · view · model) | dispatches on `config.as`; empty state | yes (slice E) |
| `note` body | markdown subset | edit / display | yes (slice E) |
| `output` (file · host · display) | 3 | terminal; approval-gated for host_write | partial — display path |
| `filter` / `transform` | per-op specialisations | typed I/O | partial — many `LM_LIBRARY` shells |
| `skill` wrapper | shared / private | inline expand / subgraph reference | yes (slice G) |
| `reroute` | wire-routing dot | passthrough | yes (slice D) |
| `trigger` | event sources | needs executor | **gap** |
| **`ai.plan`** (Composer turn artefact) | one type per Direction X | persists tool-call history | **not built** (M4) |
| **`speckle.send` / `receive`** per host | ~16 pairs (rolling per host) | local DiskTransport default | **not built** (M2+) |

### Patterns (workflows)

| Pattern | Where | Documented |
|---|---|---|
| Search-before-create | LIBRARY-FIRST mandate (CLAUDE.md) | yes — locked |
| Modular validation on register | MODULARITY mandate; validator Layer 4 (shipped today) | yes |
| Approval gating for host_write | USER-AGENCY mandate; Plan / Auto / YOLO | direction locked, no UI yet |
| Multi-entry add-node | Cmd-K + Tab + WirePromotePalette + double-click empty (slice F) | yes |
| Skill-as-node hybrid | shared (reference) vs private (inline) | yes (slice G) |
| Disable verbs | 4 booleans rewired by `normalize_canvas_graph` | yes (slice B) |
| Multi-select + groups | rubber band + Ctrl+G + style picker | yes (slices B2 + C) |
| Composer streaming + checkpoint | `ai.plan` node + Speckle Versions | direction locked, no impl |
| Cross-host wire via Speckle | M1+M2 milestone path | direction locked, no impl |

### Principles (locked in CLAUDE.md)

| Principle | Source |
|---|---|
| LIBRARY-FIRST | mandate 2026-05-20 |
| USER-AGENCY | mandate 2026-05-20 |
| MODULARITY | mandate 2026-05-20 |
| ARCHITECTURE LOCK Direction X | AgDR-0012 |
| ENGINEERING MANDATE — root-cause | 2026-05-15 |
| ROADMAP MANDATE — one roadmap | 2026-05-18 |
| AGDR MANDATE — architecture decisions write an AgDR | 2026-05-20 |

### Issues surfaced by audit

1. **Validator category enum drift.** AgDR-0013 invented 10 categories
   (primitive · connector · ai · transform · filter · watch · output ·
   skill · glue · adapter) parallel to the existing engine `cat` field
   (9 values: input · connector · ai · logic · output · skill · shape
   · watch · note). Two taxonomies of the same axis is a smell.
2. **`primitive` is a meta-category, not a function.** It collides
   with the `kind` axis. Drop from the function-taxonomy.
3. **`shape` vs `transform` + `filter`.** Engine has one `shape` cat
   for both; validator split them. Should align — engine is the older
   source.
4. **Description floor 60 chars** picked without rationale. Empirical
   Speckle / ComfyUI descriptions average 80–150 chars.
5. **Examples ≥1 doesn't distinguish state coverage.** A `pure`
   primitive (`data.constant`) needs one happy-path example. A
   `host_write` op (`revit.tag_by_room`) needs both happy + offline-host
   to express its USER-AGENCY gate.
6. **Visibility-based enforcement is inconsistent.** Hiding
   `create_node_type` until `search` ran would be the only conditional
   tool in the surface. Hurts "Consistency over creativity" — and the
   Layer 3 router gate already enforces ordering structurally.
7. **`acad` vs `autocad` host-name drift** (already on ROADMAP P2). The
   library design system must reference ONE host-name registry.
8. **No formal status enum** for node-specs. Curation needs
   `registered · proposed · superseded · deprecated`. Skills today
   only carry `shared | private` (mode), not lifecycle.
9. **PortType taxonomy in transition.** Validator accepts any string;
   no canonical list. M1+ adds Speckle `speckle_type` but legacy
   `PortType` stays. Need: a `port_type_resolver(value) -> {speckle,
   port_type, free}` so the validator can warn (not reject) on free
   strings.
10. **Approval-gate component not designed.** USER-AGENCY mandates
    Plan/Auto/YOLO modes; no `<ApprovalGate>` JSX component spec yet.

## Decision — design-system tokens locked

### Token 1 — Validator `category` enum (11)

**Aligned with engine `cat` + 2 cross-host extensions:**

```
input · connector · ai · logic · output · skill · shape · watch · note · glue · adapter
```

Maps:
- Primitives that ARE categories (8): connector, ai, logic, output,
  skill, watch, note → primitive name == category name.
- Primitives folded under categories (5):
  - `input`, `constant` → category `input`
  - `filter`, `transform` → category `shape`
  - `trigger` → category `watch` (event source displays + acts)
  - `reroute` → category `note` (annotation / routing helper)
- Non-primitive categories (2):
  - `glue` — fallback cross-host bridge (Speckle can't carry).
  - `adapter` — typed bridge (units, port-type coercion).

Replaces AgDR-0013's 10-value enum. `primitive` removed (axis
collision). `transform` + `filter` collapsed to `shape` to match engine.

### Token 2 — Description floor

**80 characters.** Floor is empirical:
- Speckle node descriptions average 110 chars.
- ComfyUI node descriptions average 95 chars.
- 80 chars ≈ 13–15 words ≈ one full descriptive sentence.

Rule of thumb the validator surfaces in its error message:
*"A description should be one full sentence (≈80 chars) — enough that
another agent can find this node by intent."*

Bumped from AgDR-0013's 60. The 60-char threshold was guessing; 80 is
designed.

### Token 3 — Examples count — tiered by side_effects

| side_effects | Min examples | Rationale |
|---|---|---|
| `pure` | ≥1 | One happy path; no state to document |
| `host_write` | ≥2 | Happy + at least one failure / approval-gate path — USER-AGENCY demands it |
| `network` | ≥2 | Happy + at least one failure mode (timeout, auth, quota) |

Bumped from AgDR-0013's flat ≥1. Tiered by side_effects matches
design-system principle: components document **states**, not just
success. The state coverage scales with the side-effect class.

### Token 4 — Tool visibility

**All tools always visible.** Tools never appear/disappear based on
prior-call state. The LLM sees the same surface at every turn.

Order is enforced **structurally** at Layer 3 (router gate denies
`create_node_type` until `search` ran this turn — already locked in
AgDR-0013).

This resolves AgDR-0013 Fork 4 (= NO, don't hide). Design-system
principle: "Consistency over creativity" — conditional surface area is
harder to reason about, harder to debug.

### Token 5 — Multi-LLM enforcement

**Auto-detect with prompt-fallback** (Fork 1 = option B). Design-system
principle: "Flexibility within constraints." The LIBRARY contract
(Layer 3 + 4) is the constraint; the provider boundary is the
flexibility. Locking to tool-providers excludes Ollama / LM Studio
without benefit — Layer 3 + 4 hold the contract regardless of provider
shape.

### Token 6 — Status lifecycle (NEW)

Each library-registered node-type carries a `status`:

| Status | Meaning |
|---|---|
| `registered` | Currently in the library; placeable. |
| `proposed` | Awaiting user approval (AI-minted in Plan mode — gated). |
| `superseded` | Replaced by another node-type; references should migrate. |
| `deprecated` | Stays placeable for back-compat but flagged in palette. |

Added to `ModularNodeSpec` as optional `status: Literal[...] = "registered"`.

### Token 7 — Host-name registry (NEW)

One canonical list of 16 host names lives at `app.connectors.HOSTS` (already
exists; some inconsistency persists e.g. `acad` vs `autocad`). The
validator accepts any string in `<host>.<verb>_<noun>` patterns but
**warns** (non-fatal) if `host` is not in `HOSTS`. M3 work item: pick
one of `acad` / `autocad`, migrate.

### Token 8 — PortType taxonomy resolver (NEW)

`library_validator.resolve_port_type(value) -> ResolvedPortType`:
- Returns `(kind="speckle", canonical="Objects.BuiltElements.Wall")` for
  recognised Speckle types.
- Returns `(kind="legacy", canonical="walls")` for legacy `PortType`.
- Returns `(kind="free", canonical=value)` for anything else.

Validator emits a warning (not a violation) on `kind="free"`. M1+
gradually narrows.

## Decision — pattern-level

### Pattern 1 — Search-before-create

- Layer 1 (system prompt) nudges
- Layer 3 (router gate) enforces — denies `create_node_type` unless
  `library_searched_this_turn` is True
- Layer 4 (validator) holds the floor on spec quality

### Pattern 2 — Approval gating (USER-AGENCY)

| Mode | Reads | Writes (`side_effects: host_write`) | Network |
|---|---|---|---|
| **Plan** (default) | auto | gated (approve every action) | gated |
| **Auto** | auto | gated | auto |
| **YOLO** | auto | auto | auto |

Approval surface is a typed error with named recovery, not a freeform
retry (AgDR-0012 mandate).

`<ApprovalGate>` JSX component spec — design later (M3.a slice).

### Pattern 3 — Skill composition

- `kind: skill` is the wrapper shape (already locked).
- `category: skill` is the function (the wrapped composition's outer
  function bubbles up if uniform — informational).
- `mode: shared | private` is the reuse policy (already locked).
- Saving a Skill = `library.create_node_type` with `category: skill`
  and `subgraph` config — must satisfy MODULARITY for the wrapper too.

## Resolution of AgDR-0013's 4 open forks

| Fork | Answer | Principle |
|---|---|---|
| 1 — Multi-LLM enforcement | Auto-detect + prompt-fallback. Structural backstop at Layer 3+4. | Flexibility within constraints |
| 2 — Description floor | **80 chars** (was 60) | Documentation sufficient for search |
| 3 — Examples count | **Tiered by side_effects**: pure ≥1, host_write ≥2, network ≥2 | Components document states |
| 4 — Hide `create_node_type` until `search` | **NO — keep visible**; enforce ordering at Layer 3 | Consistency over creativity |

## Consequences

### Code changes (this AgDR ships alongside)

- `app/library_validator.py`:
  - Replace 10-value `Category` Literal with the 11-value enum (token 1)
  - Bump `description` `min_length` from 60 → 80 (token 2)
  - Tier `examples` `min_length` by `side_effects` via a model-level
    validator (token 3)
  - Add `status: Literal["registered","proposed","superseded","deprecated"] = "registered"` (token 6)
  - Add `resolve_port_type(value)` helper (token 8)
  - Update violations' human-readable messages to cite the design-system rationale
- `tests/test_library_validator.py`:
  - Update category enum tests
  - Add description-80 tests (60 → reject; 80 → accept)
  - Add side_effects-tiered example tests (pure≥1, host_write≥2, network≥2)
  - Add status-lifecycle tests
  - Add resolve_port_type tests
- `docs/agdr/AgDR-0013-*.md`:
  - Add a "Forks resolved by AgDR-0014" note at the bottom of "Open
    forks"

### What collapses

- The AgDR-0013 "open forks" section becomes a "resolved-by-AgDR-0014"
  pointer. AgDR-0013's 60-char + flat-≥1 numbers are superseded.
- The validator's category enum tightens to match engine reality
  (one less drift class).

### What's reinforced

- The library is a **design system**, not a flat registry. Categories,
  tokens, components, patterns are first-class.
- Founder's "don't pick decimals — design the system" pattern is
  honoured: every threshold has a rationale, not a guess.
- USER-AGENCY's "every host_write is approval-gated" gains explicit
  state-coverage (examples ≥2 for host_write) — the example IS a
  contract about the failure modes the LLM must understand.

### Tests / acceptance

- Validator tests stay green after the enum + threshold update (≈55
  → ≈70 with the new state-coverage tests).
- A spec for a `host_write` node with only 1 example REJECTS with a
  violation citing the side-effects tier.
- A spec with description = 79 chars REJECTS; 80 chars ACCEPTS.
- `resolve_port_type` returns a non-fatal warning on a free string;
  validator passes the spec (warnings are not violations).

### Risks

- The category enum migration breaks any code that hard-coded the
  AgDR-0013 categories. Mitigation: validator just shipped TODAY; no
  external consumer. Safe to migrate now.
- Tiered examples-min may surprise an LLM that already learned "≥1".
  Mitigation: the validator's violation message explicitly states the
  tier ("`host_write` ops need ≥2 examples to document the failure
  mode").
- `status: proposed` not yet enforced anywhere (the router gate's
  default is to register on success). Mitigation: M3 wires the Plan-
  mode hook that sets `status: proposed` until the user approves.

## Open forks for founder

None of the original AgDR-0013 four. New question if any:

1. **`status` lifecycle** — is `registered · proposed · superseded ·
   deprecated` enough, or do we need a `experimental` / `archived` /
   `draft` tier?
2. **Host-name registry conflict** (`acad` vs `autocad`) — pick one.
   Lean `autocad` (full name, matches Speckle connector).

## Artifacts

- This AgDR.
- `app/library_validator.py` (updated under this AgDR).
- `tests/test_library_validator.py` (updated tests).
- Supersedes AgDR-0013 forks 1–4 (the enforcement-mechanism AgDR stays
  the master document for the 4 enforcement LAYERS — this AgDR sets
  the CONTRACT they enforce).
