---
id: AgDR-0020
timestamp: 2026-05-21T00:00:00Z
agent: claude-code (Sonnet)
session: m1-shipping · founder /loop "till you finalize" · "don't sleep"
trigger: ROADMAP §SLICE-L — Dynamo Node-to-Code (deferred · separate AgDR)
status: proposed
category: architecture
projects: [archhub]
extends:
  - AgDR-0001 §SLICE-L line — "Dynamo 'Node-to-Code' — select
    transform chain → flatten to expression"
---

# SLICE L — Node-to-Code · `code.expression` + `code.python` engine + `code` typed primitive (foundation)

> In the context of ROADMAP §SLICE-L deferred from the original
> NODE-SYSTEM REDESIGN slice list ("Dynamo 'Node-to-Code' — select
> transform chain → flatten to expression"), I decided to **ship
> the engine foundation first** in this tick: two new executors
> (`code.expression` for one-liners, `code.python` for multi-line
> function bodies), a typed grammar primitive `code` resolving via
> a `mode` selector. The JSX "Flatten chain to code" action is
> deferred to a follow-up tick — it's UI, and the engine has to
> ship first so the JSX has a real target. Accepting: sandboxing
> is RESTRICTIVE by default (no `import`, no `__` attrs, no
> network); the user explicitly opts in to broader access via the
> `safe_mode` param (eventually gated by the user-agency settings
> floor — for now just a config flag, with `safe_mode=True` the
> default so a maliciously-saved graph can't escape).

## Context

Dynamo's "Node-to-Code" flattens a chain of nodes into a single
DesignScript expression. Grasshopper has C# Script + Python Script
nodes as escape hatches that ALSO serve as compression targets
(power user collapses 5 components into one script). ComfyUI has
group-nodes (already shipped as `skill` in slice G — see AgDR-0010).

ArchHub's existing escape hatch is `glue.script` (per AgDR-0007),
but it's not in the typed grammar yet. SLICE L promotes the
escape hatch into the typed grammar and adds the compression /
flatten-to-code action.

This AgDR ships ONLY the engine + grammar foundation. The
flatten-to-code JSX action follows in a separate tick once this
ships and runs.

## Options Considered

### Fork 1 — One executor or two

| Option | Picked | Why |
|---|---|---|
| Single `code.run` executor with a `mode` param (`expression`/`function`) | no | Expression vs full function have different sandbox / parse / return semantics — conflating them muddies error messages |
| **Two executors: `code.expression` (one-line eval) + `code.python` (multi-line exec)** | **YES** | Each has its own param schema · clearer error surface · each can have its own grammar primitive later if needed |
| Three executors (add `code.jsx` for JavaScript) | no | JS sandboxing in Python is non-trivial; not needed for the founder's listed use case (numeric / list / text transforms) |

**Pick: Two executors.**

### Fork 2 — Sandboxing default

| Option | Picked | Why |
|---|---|---|
| Open globals (Python `eval(code)` directly) | no | A saved graph from anywhere could run arbitrary code on first cook — security floor breach |
| **Restricted globals (no `__builtins__`, no `import`, no dunder attr access, no network) — `safe_mode=True` default** | **YES** | User-agency mandate: "every AI write is approval-gated by default" · same floor for user-authored code · explicit opt-out for power users |
| Full sandbox via separate process / WASM | no | Massive surface for a foundation slice · MVP value doesn't need it |

**Pick: Restricted-by-default sandbox.**

### Fork 3 — Returns

| Option | Picked | Why |
|---|---|---|
| Expression: the value of the expression. Function: whatever `result = ...` was set to | **YES** | Matches Python's REPL + Dynamo's "the last expression is the output" |
| Always require `return` keyword | no | Awkward for expressions (`return a + b` instead of `a + b`) |
| Multiple outputs via dict (`return {x: ..., y: ...}`) | partial | Yes — `code.python` accepts a final dict; each key becomes a separate output port. Out of MVP scope for this slice — single output for now |

**Pick: Single output, last-expression returns.**

### Fork 4 — JSX flatten action

| Option | Picked | Why |
|---|---|---|
| Ship the flatten-to-code action this tick | no | UI work; engine ships first |
| **Defer flatten-to-code to a follow-up tick** | **YES** | Engine surface needs to settle first; the JSX implementation reads the engine spec |
| Skip flatten entirely; only ship the code node | no | The flatten action is THE founder-asked feature; just deferred, not dropped |

**Pick: Defer.** Implementation order: engine first, JSX action next tick.

## Decision

### Two new engine types

```python
register(
    NodeSpec(
        type="code.expression",
        category="code",
        display_name="Expression",
        description="Evaluate a single Python expression with wired "
                    "inputs as locals. Returns the expression value.",
        inputs=[Port(name="a", type=PortType.ANY),
                Port(name="b", type=PortType.ANY),
                Port(name="c", type=PortType.ANY)],
        outputs=[Port(name="value", type=PortType.ANY)],
        config_schema={
            "expr":      {"type": "string"},
            "safe_mode": {"type": "boolean", "default": True},
        },
        icon="∑",
    ),
    _code_expression_executor,
)
register(
    NodeSpec(
        type="code.python",
        category="code",
        display_name="Python",
        description="Run a Python function body with `inputs` dict "
                    "available. The variable named `result` (set "
                    "anywhere in the body) becomes the output.",
        inputs=[Port(name="a", type=PortType.ANY),
                Port(name="b", type=PortType.ANY),
                Port(name="c", type=PortType.ANY)],
        outputs=[Port(name="value", type=PortType.ANY)],
        config_schema={
            "body":      {"type": "string"},
            "safe_mode": {"type": "boolean", "default": True},
        },
        icon="␣",
    ),
    _code_python_executor,
)
```

### One typed grammar primitive

The grammar gets ONE entry, `code`, with a `mode` selector picking
the engine type:

```python
Primitive(
    "code", "Code", "code", "mode",
    {"expression": "code.expression", "python": "code.python"},
    READY,
    "Run a Python expression OR function body with wired inputs.",
    params=({"k": "mode", "v": "expression", "type": "text"},
            {"k": "expr", "v": "a + b", "type": "text"},
            {"k": "body", "v": "result = a", "type": "text"},
            {"k": "safe_mode", "v": True, "type": "boolean"}),
    blurb="Expression or Python function body",
),
```

(One primitive with selector — not split per Slice I — because
expression vs function is a MODE on the same conceptual node,
where Slice I's split was per fundamentally different actions.)

### Sandbox

```python
_SAFE_BUILTINS = {
    "abs", "min", "max", "sum", "len", "range", "enumerate", "zip",
    "sorted", "reversed", "map", "filter", "round", "int", "float",
    "str", "bool", "list", "dict", "tuple", "set", "any", "all",
    "isinstance", "type",
}
# Forbidden substrings in source code (fast pre-check):
_FORBIDDEN_TOKENS = {
    "__import__", "__builtins__", "__globals__", "__class__",
    "open(", "exec(", "eval(", "compile(", "subprocess",
    "import os", "import sys", "import socket",
    "from os", "from sys", "from socket",
}
```

In `safe_mode=True`, the pre-check rejects source containing any
forbidden token. The exec/eval is run with `{"__builtins__":
restricted_builtins}` so even if a clever bypass slips through,
no `open` / `import` is reachable. In `safe_mode=False`, the
pre-check is skipped + full builtins are available — the user
explicitly opted in.

### Engine semantics

```python
def _code_expression_executor(config, inputs, ctx):
    expr = (config or {}).get("expr") or ""
    safe = bool((config or {}).get("safe_mode", True))
    if safe and _has_forbidden_token(expr):
        return {"value": None, "status": "error",
                "error": "expression contains forbidden tokens "
                         "(set safe_mode=False to opt out)"}
    env = {**_SAFE_GLOBALS if safe else _OPEN_GLOBALS,
           **inputs}
    try:
        result = eval(expr, env)  # noqa: PIE790 — sandboxed
    except Exception as ex:
        return {"value": None, "status": "error",
                "error": f"{type(ex).__name__}: {ex}"}
    return {"value": result}


def _code_python_executor(config, inputs, ctx):
    body = (config or {}).get("body") or ""
    safe = bool((config or {}).get("safe_mode", True))
    if safe and _has_forbidden_token(body):
        return {"value": None, "status": "error",
                "error": "body contains forbidden tokens "
                         "(set safe_mode=False to opt out)"}
    env = {**_SAFE_GLOBALS if safe else _OPEN_GLOBALS,
           "inputs": inputs, **inputs}
    try:
        exec(body, env)  # noqa: PIE790 — sandboxed
    except Exception as ex:
        return {"value": None, "status": "error",
                "error": f"{type(ex).__name__}: {ex}"}
    return {"value": env.get("result")}
```

## Consequences

### What ships (this slice)

- `app/workflows/nodes/code.py` (NEW) — 2 executors + 1 grammar entry registration.
- `app/workflows/node_grammar.py` — `code` typed primitive.
- `app/workflows/nodes/__init__.py` — import for registration.
- Tests: 12+ covering expression / python / safe_mode rejection /
  unsafe opt-out / error path / null inputs / multi-input wire.

### What collapses

- The "no escape hatch in the typed grammar" loose end.

### What's reinforced

- The user-agency floor: code execution is restrictive-by-default.
- The typed-grammar pattern remains the canon — even an open-ended
  escape hatch like Code lives as a typed primitive with a clear
  param schema.

### Risks

- **Sandbox escape.** Python sandboxes are notoriously hard to
  secure (frame access / generator closures / etc.). The pre-check
  + restricted builtins is a TWO-LAYER defence + the user-agency
  mandate covers the rest (every save is reversible via Speckle
  Versions). For high-security use the user can keep `safe_mode`
  on; for power users the opt-out is one config click.
- **3-input cap.** Initial inputs are `a`/`b`/`c`. A future slice
  can add dynamic input ports (matching the wire count). Out of
  MVP scope.
- **`result` variable contract for `code.python`.** Documented in
  the description; not enforced by syntax. A user who forgets
  `result =` gets `None` back — honest, not silent failure.

### Tests

| Test | What it proves |
|---|---|
| `test_code_expression_basic_arithmetic` | `a + b` with a=2, b=3 returns 5 |
| `test_code_expression_uses_builtin_funcs` | `sum([a, b, c])` works |
| `test_code_python_sets_result` | `result = a * 2` returns 2*a |
| `test_code_python_no_result_returns_none` | Missing `result` → None (honest) |
| `test_safe_mode_rejects_import` | `__import__("os")` → error |
| `test_safe_mode_rejects_open` | `open("x")` → error |
| `test_safe_mode_opt_out_allows_import` | safe_mode=False + open allowed (user opt-in) |
| `test_code_error_surfaces_typed_error` | A bad expression returns `{value:None, status:"error", error:...}` |
| `test_code_python_can_use_inputs_dict` | `result = inputs["a"]` works |
| `test_code_grammar_primitive_registered` | `code` typed primitive exists, mode selector resolves correctly |
| `test_code_grammar_resolves_to_engines` | `engine_type("code", {mode:"expression"})` and `mode:"python"` resolve right |
| `test_code_grammar_count_after_slice_l` | PRIMITIVES still ≤75; payload ≤70 |

## Implementation order

1. ✓ This AgDR.
2. `app/workflows/nodes/code.py` + sandbox helpers + executors.
3. Grammar primitive registration in `node_grammar.PRIMITIVES`.
4. Tests.
5. ROADMAP update.
6. **Follow-up tick: JSX "Flatten chain to code" action.**

## Open forks for founder

1. **Multi-output `code.python`.** Today single `value` output.
   Future: detect `result` as dict → spread keys as multiple output
   ports. Out of scope.
2. **Dynamic input ports.** Today fixed `a`/`b`/`c`. Future: a port
   for each wired connection. Out of scope.
3. **Library template.** The Code node could land with `expr = a + b`
   pre-filled. Today it does. Open question: should new placements
   land empty or with a hint?

## Artifacts

- This AgDR.
- Pending: `app/workflows/nodes/code.py`, `app/workflows/node_grammar.py`,
  `app/workflows/nodes/__init__.py`, `tests/test_code_nodes.py`.
