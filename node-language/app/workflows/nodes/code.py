"""Code nodes — SLICE L (AgDR-0020).

Two executors:
  • code.expression — eval a single Python expression with wired
    inputs as locals; returns the expression value.
  • code.python — exec a Python function body; the variable named
    `result` (set anywhere in the body) becomes the output.

Sandbox is RESTRICTIVE by default (`safe_mode=True`): no `import`,
no `__` attrs, no `open` / `exec` / `eval` / `compile` /
`subprocess`. Two layers — source-token pre-check + restricted
`__builtins__`. Power users opt out with `safe_mode=False`.

Per AgDR-0020: this slice ships only the engine + grammar. The
JSX "Flatten chain to code" action is a follow-up tick.
"""
from __future__ import annotations

from ..graph import Port, PortType
from ..registry import NodeSpec, register


# ── Sandbox helpers ──────────────────────────────────────────────────

# Safe built-ins — common, pure, side-effect-free.
#
# The exception CLASSES at the tail are pure, harmless type objects (they open
# no file, touch no host, and `_FORBIDDEN_TOKENS` still blocks the dangerous
# dunders / import / open / exec). They are present so a sandboxed `code.python`
# body can actually USE the `try/except` the grammar already permits — without a
# name to catch, `except (TypeError, ValueError):` raised `NameError` inside the
# restricted namespace, making error-handling silently impossible. This closes
# that latent gap so a composed stem-cell can mirror a bespoke's literal
# `try/except` (e.g. the `int(x)`-or-0 coercion in adapter.excel_to_revit_params)
# byte-identically, instead of re-deriving the builtin's grammar by hand.
_SAFE_BUILTIN_NAMES = {
    "abs", "min", "max", "sum", "len", "range", "enumerate", "zip",
    "sorted", "reversed", "map", "filter", "round", "int", "float",
    "str", "bool", "list", "dict", "tuple", "set", "any", "all",
    "isinstance", "type", "print", "repr",
    # Pure exception classes — make `try/except` usable in a sandboxed body.
    "Exception", "ValueError", "TypeError", "KeyError", "IndexError",
    "AttributeError", "ZeroDivisionError", "StopIteration",
}

# Source tokens that the user must not include in safe-mode source.
_FORBIDDEN_TOKENS = (
    "__import__", "__builtins__", "__globals__", "__class__",
    "__bases__", "__subclasses__", "__mro__", "__code__",
    "__getattribute__", "__getattr__",
    "open(", "exec(", "eval(", "compile(",
    "subprocess", "socket",
    "import ", " import",  # word `import` with space on either side
    "from os", "from sys",
)


def _build_safe_builtins() -> dict:
    """Construct the restricted builtins dict for safe-mode eval/exec."""
    import builtins as _b
    out: dict = {}
    for name in _SAFE_BUILTIN_NAMES:
        if hasattr(_b, name):
            out[name] = getattr(_b, name)
    return out


_SAFE_GLOBALS = {"__builtins__": _build_safe_builtins()}
_OPEN_GLOBALS: dict = {}  # Python provides real __builtins__ when empty.


def _has_forbidden_token(source: str) -> bool:
    """Quick source-string check — rejects safe-mode code that
    contains any obviously-dangerous token."""
    if not source:
        return False
    s = str(source)
    for tok in _FORBIDDEN_TOKENS:
        if tok in s:
            return True
    return False


# ── Executors ────────────────────────────────────────────────────────


def _code_expression_executor(config: dict, inputs: dict, ctx) -> dict:
    config = config or {}
    expr = str(config.get("expr") or "").strip()
    if not expr:
        return {"value": None, "status": "error",
                "error": "empty expression"}
    safe = bool(config.get("safe_mode", True))
    if safe and _has_forbidden_token(expr):
        return {"value": None, "status": "error",
                "error": "expression contains forbidden tokens "
                         "(set safe_mode=False to opt out)"}
    env: dict = dict(_SAFE_GLOBALS if safe else _OPEN_GLOBALS)
    env.update(inputs or {})
    try:
        result = eval(expr, env)  # noqa: S307 — sandboxed
    except Exception as ex:
        return {"value": None, "status": "error",
                "error": f"{type(ex).__name__}: {ex}"}
    return {"value": result, "status": "ok"}


def _code_python_executor(config: dict, inputs: dict, ctx) -> dict:
    config = config or {}
    body = str(config.get("body") or "")
    if not body.strip():
        return {"value": None, "status": "error",
                "error": "empty body"}
    safe = bool(config.get("safe_mode", True))
    if safe and _has_forbidden_token(body):
        return {"value": None, "status": "error",
                "error": "body contains forbidden tokens "
                         "(set safe_mode=False to opt out)"}
    env: dict = dict(_SAFE_GLOBALS if safe else _OPEN_GLOBALS)
    env["inputs"] = inputs or {}
    env.update(inputs or {})
    try:
        exec(body, env)  # noqa: S102 — sandboxed
    except Exception as ex:
        return {"value": None, "status": "error",
                "error": f"{type(ex).__name__}: {ex}"}
    return {"value": env.get("result"), "status": "ok"}


# ── Registration ─────────────────────────────────────────────────────

register(
    NodeSpec(
        type="code.expression",
        category="code",
        display_name="Expression",
        description="Evaluate a Python expression with wired inputs "
                    "as locals. Returns the expression value. "
                    "Sandboxed by default (no import, no `open`, "
                    "no `__` attrs).",
        inputs=[
            Port(name="a", type=PortType.ANY),
            Port(name="b", type=PortType.ANY),
            Port(name="c", type=PortType.ANY),
        ],
        outputs=[Port(name="value", type=PortType.ANY)],
        config_schema={
            "expr":      {"type": "string",
                           "description": "Python expression to evaluate."},
            "safe_mode": {"type": "boolean", "default": True,
                           "description": "If true, reject source with "
                                          "forbidden tokens + restrict builtins."},
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
        description="Run a Python function body with wired inputs + "
                    "the `inputs` dict available. Set `result = ...` "
                    "anywhere in the body for the output. Sandboxed "
                    "by default.",
        inputs=[
            Port(name="a", type=PortType.ANY),
            Port(name="b", type=PortType.ANY),
            Port(name="c", type=PortType.ANY),
        ],
        outputs=[Port(name="value", type=PortType.ANY)],
        config_schema={
            "body":      {"type": "string",
                           "description": "Python function body. Assign "
                                          "`result = ...` for the output."},
            "safe_mode": {"type": "boolean", "default": True},
        },
        icon="␣",
    ),
    _code_python_executor,
)
