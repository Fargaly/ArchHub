"""Node Smith — turn a natural-language description into a custom node.

Founder demand 2026-05-16: "user should be able to custom-make nodes on
a whim using AI." The user types what they want ("a node that keeps only
walls taller than 3m"); an LLM designs the full custom-node spec — type
id, category, typed inputs/outputs, icon, and a SANDBOXED Python
`execute(config, inputs, ctx)` body — which `workflows.custom_nodes`
registers as a real, runnable node.

The generated `code` runs in a fresh empty namespace (no project imports,
see `custom_nodes._build_executor`), so a bad script cannot reach the
rest of the runtime. We additionally reject code that references imports
or dunder escapes before it is ever written to disk.
"""
from __future__ import annotations

import json
import re
from typing import Any


_CATEGORIES = ("read", "filter", "transform", "logic", "compose",
               "annotate", "output", "ai", "host")

_SYSTEM = """You design ONE custom node for ArchHub, a graph workspace \
for architects. Output ONLY a JSON object — no prose, no markdown fence.

Schema:
{
  "type": "custom.<short_snake_id>",
  "category": one of read|filter|transform|logic|compose|annotate|output|ai,
  "display_name": "Short Title Case name",
  "description": "one sentence, what it does",
  "icon": "single character glyph",
  "inputs":  [{"name": "...", "type": "list|number|text|bool|any"}],
  "outputs": [{"name": "...", "type": "list|number|text|bool|any"}],
  "code": "def execute(config, inputs, ctx):\\n    ...\\n    return {<output_name>: value}"
}

Rules for `code`:
- Define exactly `def execute(config, inputs, ctx):` and return a dict
  keyed by your declared output names.
- `inputs` is a dict keyed by your declared input names.
- PURE PYTHON ONLY — no `import`, no `__`, no file/network/system access.
  The sandbox blocks it; code that needs an import is invalid.
- Keep it small and correct. If the task truly needs a host (Revit,
  Excel...), do NOT fake it — set category to the host's family and
  leave code as a passthrough `return dict(inputs)`; the user will wire
  a real connector-op node instead.
Return the JSON object only."""


def _extract_json_object(text: str) -> str:
    """Pull the first balanced {...} JSON object out of an LLM reply.

    Robust to prose before/after the object and to ``` fences. It
    brace-counts while respecting string literals + escapes, so it
    returns exactly ONE object — unlike a naive first-`{`..last-`}`
    slice, which spans two objects when the model emits trailing
    commentary and makes `json.loads` raise 'Extra data'.
    """
    t = (text or "").strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*\n?", "", t)
        t = re.sub(r"\n?```\s*$", "", t).strip()
    start = t.find("{")
    if start < 0:
        return ""
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(t)):
        c = t[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return t[start:i + 1]
    return t[start:]   # unbalanced — let json.loads report the fault


def _safe_code(code: str) -> tuple[bool, str]:
    """Reject obviously unsafe generated code before it touches disk.
    The custom_nodes sandbox is the real guard; this is a fast pre-check.
    """
    c = code or ""
    if "def execute" not in c:
        return False, "generated code lacks a def execute(...)"
    banned = ("import ", "__import__", "__builtins__", "__globals__",
              "open(", "eval(", "exec(", "compile(", "subprocess",
              "os.", "sys.")
    for b in banned:
        if b in c:
            return False, f"generated code uses a blocked construct: {b!r}"
    return True, ""


def design_node_spec(description: str, *, router: Any = None) -> dict:
    """Ask the LLM to design a custom-node spec from a NL description.
    Returns a spec dict ready for `custom_nodes.write_spec`, or
    `{"error": "..."}`.
    """
    desc = (description or "").strip()
    if not desc:
        return {"error": "empty description"}
    if router is None:
        return {"error": "no router configured"}
    try:
        # `system_override` puts _SYSTEM in as the real system prompt and
        # suppresses the chat tool surface — the model answers with JSON
        # directly. A fake `role:"system_override"` history message (the
        # earlier approach) was silently dropped by the provider clients,
        # so the schema instructions never reached the model and it
        # replied with prose.
        resp = router.complete(
            history=[{"role": "user",
                      "content": f"Design a node that: {desc}"}],
            model="auto",
            system_override=_SYSTEM,
        )
    except Exception as ex:
        return {"error": f"LLM call failed: {type(ex).__name__}: {ex}"}

    raw = getattr(resp, "text", "") or ""
    try:
        spec = json.loads(_extract_json_object(raw))
    except Exception as ex:
        head = " ".join((raw or "").split())[:160]
        return {"error": f"could not parse AI spec: {ex} · raw head: {head!r}"}
    if not isinstance(spec, dict):
        return {"error": "AI spec was not a JSON object"}

    # ── normalise + validate ────────────────────────────────────────
    t = str(spec.get("type", "")).strip()
    if not t:
        t = "custom." + re.sub(r"[^a-z0-9]+", "_", desc.lower())[:24].strip("_")
    if not t.startswith("custom."):
        t = "custom." + re.sub(r"[^a-zA-Z0-9_.]+", "_", t)
    spec["type"] = t

    cat = str(spec.get("category", "transform")).strip().lower()
    spec["category"] = cat if cat in _CATEGORIES else "transform"

    spec["display_name"] = (str(spec.get("display_name", "")).strip()
                            or t.replace("custom.", "").replace("_", " ").title())
    spec["description"] = str(spec.get("description", "")).strip() or desc
    spec["icon"] = (str(spec.get("icon", "") or "⊕")[:1]) or "⊕"

    def _ports(v):
        out = []
        for p in (v or []):
            if isinstance(p, str):
                out.append({"name": p, "type": "any"})
            elif isinstance(p, dict) and p.get("name"):
                out.append({"name": str(p["name"]),
                             "type": str(p.get("type", "any"))})
        return out
    spec["inputs"] = _ports(spec.get("inputs")) or [{"name": "in", "type": "any"}]
    spec["outputs"] = _ports(spec.get("outputs")) or [{"name": "out", "type": "any"}]

    code = spec.get("code")
    if isinstance(code, str) and code.strip():
        ok, why = _safe_code(code)
        if not ok:
            # Unsafe / malformed code — drop it; the node registers as a
            # passthrough rather than failing the whole creation. Honest:
            # the spec still lands, just without the rejected body.
            spec["code"] = ""
            spec["description"] += f"  (note: AI code rejected — {why})"
        else:
            spec["code"] = code
    else:
        spec["code"] = ""
    return spec
