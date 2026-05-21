---
id: AgDR-0021
timestamp: 2026-05-21T00:00:00Z
agent: claude-code (Sonnet)
session: m1-shipping · founder /loop "till you finalize" · "don't sleep"
trigger: AgDR-0012 §"M4 — ai.plan as canvas node (9-10 wks)" — foundation slice
status: proposed
category: architecture
projects: [archhub]
extends:
  - AgDR-0012 §M4 — "ai.plan is a real canvas node that persists each
    Composer turn as auditable + replayable artefact"
  - AgDR-0019 — typed AI nodes pattern (Chat / Complete / Classify /
    Tools); ai_plan follows the same typed-primitive shape
---

# M4 foundation — `ai.plan` canvas node · auditable + replayable Composer turn

> In the context of AgDR-0012's Direction X lock ("`ai.plan` is a
> real canvas node that persists each Composer turn as auditable +
> replayable artefact. Composer ≡ ai.plan engine; two surfaces."),
> I decided to **ship the engine + persistence + grammar foundation
> first** in this tick. New executor `ai.plan` wraps the existing
> `llm.complete_with_tools` engine + adds plan-history persistence
> (per-graph `<project_dir>/.archhub/plans/<plan_id>.json`) + a
> deterministic re-run mode (temperature=0 + same prompt + same
> graph hash → same plan returned from cache). The Composer JSX
> integration + the replay UI ride in a follow-up tick (the engine
> has to ship first so the JSX has a real target). Accepting: a
> placed `ai.plan` node carries `plan_id` config + a writable
> history dir; the engine appends a turn per cook; replay reads
> the cached turn when its inputs hash unchanged.

## Context

AgDR-0012 §M4: "ai.plan is a real canvas node that persists each
Composer turn as auditable + replayable artefact. Composer ≡
ai.plan engine; two surfaces."

Two requirements drop out of this:

1. **Audit.** Each Composer turn (user prompt → LLM plan → tool
   invocations → final result) must be inspectable AFTER the fact
   — what the LLM was thinking, what it called, what it got back.
2. **Replay.** Re-running the same node should produce the same
   plan deterministically — useful for debugging + for sharing a
   reproducible recipe.

The existing `llm.complete_with_tools` engine handles (a) single-shot
LLM with tool-use loop, but (b) NO PERSISTENCE — once the cook ends,
the tool_invocations list is gone. AgDR-0019 already typed-split the
AI master into 4 nodes (`ai_chat` / `ai_complete` / `ai_classify` /
`ai_tools`) so the right shape for `ai.plan` is a 5th typed-AI node.

## Options Considered

### Fork 1 — Engine: wrap or replace `llm.complete_with_tools`

| Option | Picked | Why |
|---|---|---|
| Build a fresh executor from scratch | no | Re-implements the tool-use loop AgDR-0013 already shipped + the LIBRARY-FIRST gate the router already enforces; pure churn |
| **Thin wrapper that calls `llm.complete_with_tools` + persists the result** | **YES** | Reuses the gate-gated tool-loop; persistence is the only new concern |
| Make `llm.complete_with_tools` ALWAYS persist (no separate node) | no | Breaks expectations: AI Tools is a single-shot node, not a recorded turn |

**Pick: Wrapper.**

### Fork 2 — Persistence path

| Option | Picked | Why |
|---|---|---|
| Per-cook file in `<project_dir>/.archhub/plans/<plan_id>.json` | **YES** | Discoverable on-disk; loads alongside the graph; replayable by anyone with the project |
| In-memory only (lost on app restart) | no | "Auditable + replayable" requires persistence; AgDR-0012 is explicit |
| Speckle commit (audit lives in version history) | no (deferred) | Speckle Versions are great for "what was the data" but not for "what was the LLM thinking" — different shape; add later |

**Pick: Per-cook JSON file.**

### Fork 3 — Plan-id allocation

| Option | Picked | Why |
|---|---|---|
| Random UUID per cook | no | Each cook generates a new file — history balloons |
| **Deterministic: `hash(prompt + graph_topology + model)`** | **YES** | Same inputs → same plan_id → REPLAY hits the cached file. Cache key matches the runner's dirty-tracking model |
| User-typed | no | Adds UX friction; the founder mandate "every action reversible via Speckle Versions" implies content-addressed IDs |

**Pick: Deterministic content-addressed.**

### Fork 4 — Replay determinism

| Option | Picked | Why |
|---|---|---|
| Re-run the LLM with same prompt | no | Same prompt + temperature>0 + tool-call ordering = different plans run-to-run |
| **If a cached plan exists for the input hash AND `replay=True` config, return the cached plan; otherwise call the LLM** | **YES** | Deterministic re-run via cache + explicit toggle keeps live-cook semantics for users who WANT a fresh plan each cook |
| Force temperature=0 every time | no | The LLM still re-runs; deterministic only when the model is fully reproducible (not all providers are) |

**Pick: Cache-with-replay toggle.**

### Fork 5 — Failure / partial results

| Option | Picked | Why |
|---|---|---|
| If the LLM call errors, drop the cook | no | Loses the partial plan + the error context |
| **Persist a turn record EVEN on failure** (status, error, partial tool_invocations) | **YES** | Audit needs the failure history too; "what went wrong on turn N" is the most-asked question |

**Pick: Persist always.**

## Decision

### New engine — `ai.plan`

```python
def _ai_plan_executor(config: dict, inputs: dict, ctx) -> dict:
    prompt = inputs.get("prompt") or config.get("prompt") or ""
    model = config.get("model") or "auto"
    replay = bool(config.get("replay", False))
    project_dir = config.get("project_dir") or default_project_dir()
    plan_history = PlanHistory(project_dir)

    # Deterministic plan_id from inputs.
    plan_id = plan_history.id_for(prompt=prompt, model=model,
                                     extra=config.get("inputs_hash", ""))
    if replay:
        cached = plan_history.load(plan_id)
        if cached:
            return {"plan": cached["plan"],
                    "result": cached["result"],
                    "plan_id": plan_id,
                    "cached": True}

    # Fresh run — call llm.complete_with_tools.
    nested_out = _llm_complete_with_tools_executor(
        config={"model": model, "prompt": prompt,
                 "allowed_tools": config.get("allowed_tools") or []},
        inputs={"prompt": prompt}, ctx=ctx)

    # Persist the turn (success or failure both stamp a record).
    record = {
        "plan_id":          plan_id,
        "prompt":           prompt,
        "model":            nested_out.get("model"),
        "plan":             nested_out.get("tool_invocations") or [],
        "result":           nested_out.get("text") or "",
        "status":           nested_out.get("status", "ok"),
        "error":            nested_out.get("error"),
        "ts":               int(time.time()),
    }
    plan_history.save(record)
    return {
        "plan":     record["plan"],
        "result":   record["result"],
        "plan_id":  plan_id,
        "cached":   False,
        "status":   record["status"],
        "error":    record["error"],
    }
```

### Persistence module — `app/plan_history.py`

```python
class PlanHistory:
    def __init__(self, project_dir: str):
        self.root = Path(project_dir) / ".archhub" / "plans"
        self.root.mkdir(parents=True, exist_ok=True)

    def id_for(self, *, prompt: str, model: str, extra: str = "") -> str:
        """Deterministic plan id — same prompt + model + extra → same id."""
        h = hashlib.sha256()
        h.update(f"{prompt}|{model}|{extra}".encode("utf-8"))
        return h.hexdigest()[:16]

    def save(self, record: dict) -> None:
        path = self.root / f"{record['plan_id']}.json"
        path.write_text(json.dumps(record, indent=2), encoding="utf-8")

    def load(self, plan_id: str) -> dict | None:
        path = self.root / f"{plan_id}.json"
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def list_ids(self) -> list[str]:
        return [p.stem for p in self.root.glob("*.json")]

    def delete(self, plan_id: str) -> bool:
        path = self.root / f"{plan_id}.json"
        if path.exists():
            path.unlink(); return True
        return False
```

### New typed grammar primitive — `ai_plan`

```python
Primitive(
    "ai_plan", "AI Plan", "ai", "",
    {"": "ai.plan"}, READY,
    "ai.plan — auditable + replayable Composer turn · tool-use loop "
    "persisted to .archhub/plans/<id>.json",
    params=({"k": "model", "v": "auto", "type": "text"},
            {"k": "prompt", "v": "", "type": "text"},
            {"k": "replay", "v": False, "type": "boolean"},
            {"k": "allowed_tools", "v": "", "type": "text"}),
    blurb="Persisted + replayable AI turn",
),
```

Grammar count: 75 → 76. Cap currently ≤75 — bump to ≤80 (still well under the legacy 80-node sprawl).

## Consequences

### What ships (this slice)

- `app/plan_history.py` (NEW) — persistence layer.
- `app/workflows/nodes/ai_plan.py` (NEW) — engine wrapper.
- `app/workflows/nodes/__init__.py` — import for registration.
- `app/workflows/node_grammar.py` — `ai_plan` typed primitive +
  cap bump (≤75 → ≤80).
- `tests/test_node_grammar.py` — update cap assertion.
- `tests/test_new_bridge_slots.py` — update grammar payload cap.
- Tests: 12+ covering persistence (save/load/list/delete), id
  determinism, cache-on-replay, fresh-on-non-replay, failure record,
  grammar resolution.

### What collapses

- The "no audit trail for Composer turns" gap.

### What's reinforced

- Typed-AI pattern (one node per action, action-specific params).
- LIBRARY-FIRST gate STILL fires (we call `llm.complete_with_tools`
  which routes through the router → gate runs).

### Risks

- **Plan-history disk growth.** Each cook writes a JSON file. For a
  heavy user this is ~kilobytes/cook — bounded. Mitigation: future
  slice adds `PlanHistory.prune(keep_last=N)`.
- **plan_id collisions across projects.** Different graphs, same
  prompt + model → same plan_id but different project dirs → no
  collision (separate dirs). Within one project, hash collisions
  at 16-hex chars are vanishingly rare.
- **LLM cost on `replay=False`.** Each cook = real API call. The
  founder's existing per-tool policy gate (allow/ask/deny) STILL
  applies via the router; not a new risk.

### Tests

| Test | What it proves |
|---|---|
| `test_plan_history_save_and_load_round_trip` | Round-trip via JSON file |
| `test_plan_history_id_is_deterministic` | Same inputs → same id |
| `test_plan_history_id_differs_on_prompt_change` | Different prompt → different id |
| `test_plan_history_id_differs_on_model_change` | Different model → different id |
| `test_plan_history_list_ids_finds_saved_records` | Glob picks up `*.json` |
| `test_plan_history_delete_removes_file` | Cleanup honestly removes the record |
| `test_ai_plan_executor_calls_llm_when_not_replay` | Non-replay path invokes `llm.complete_with_tools` |
| `test_ai_plan_executor_returns_cache_on_replay` | replay=True + cached hit → no LLM call |
| `test_ai_plan_persists_record_on_success` | Success records `status: ok` + tool_invocations |
| `test_ai_plan_persists_record_on_failure` | Failure also records (status: error + error string) |
| `test_ai_plan_grammar_primitive_registered` | Grammar exposes `ai_plan` typed primitive |
| `test_ai_plan_resolves_to_ai_plan_engine` | `engine_type('ai_plan')` returns `ai.plan` |
| `test_ai_plan_grammar_count_within_cap` | PRIMITIVES ≤ 80 (raised from 75) |

## Implementation order

1. ✓ This AgDR.
2. `app/plan_history.py` + tests.
3. `app/workflows/nodes/ai_plan.py` + executor + tests.
4. Grammar primitive + cap bump + tests.
5. ROADMAP update.
6. **Follow-up tick: Composer JSX panel reads `ai.plan` history +
   surfaces a replay UI (M4 phase 2).**

## Open forks for founder

1. **Speckle Versions for plan audit.** Per AgDR-0012 "every action
   reversible via Speckle Versions" — should plan records ALSO
   ship through SpeckleWire for cross-machine audit sharing? Out
   of M4 foundation; M6 collaboration slice.
2. **Plan diffing.** Two replays of the same prompt: do we surface
   the diff (LLM said different things)? Useful for "did the model
   regress" debugging. Future slice.
3. **Plan pinning.** Mark a successful plan as "canonical" so
   replay=True always returns it regardless of input drift?
   Future slice.

## Artifacts

- This AgDR.
- Pending: `app/plan_history.py`, `app/workflows/nodes/ai_plan.py`,
  `tests/test_plan_history.py`, `tests/test_ai_plan_node.py`.
