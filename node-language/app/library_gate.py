"""Library gate — Layer 3 of the LIBRARY-FIRST enforcement model.

Reference: docs/agdr/AgDR-0013-multi-llm-library-first-enforcement.md §"Layer 3"
Reference: docs/agdr/AgDR-0014-library-design-system.md §"Token 4 — Tool visibility"
Reference: docs/agdr/AgDR-0012-architecture-direction-x.md §"Mandate 1 — LIBRARY FIRST"

The gate runs in `llm_router._complete_once` BETWEEN tool-call extraction and
`ToolEngine.invoke()` dispatch. It is the model-agnostic structural backstop
that holds even when an LLM ignores the system prompt or the provider does
not support strict tool mode (Ollama / LM Studio).

Per-call rules:

  1. If `inv.tool_name == "library.create_node_type"`:
       • require `turn_state.library_searched is True`
       • require `validator.validate(inv.arguments["spec"]).ok`
       → on fail: return `GateDecision(allow=False, reason, retry_hint)`
  2. If `inv.tool_name == "library.search"`:
       • mark `turn_state.library_searched = True`
       → allow
  3. All other tools → allow.

TurnState resets at the START of each user turn (the router constructs a
fresh `TurnState` per call to `_complete_once`). The gate is stateless;
state lives on TurnState.

On deny, the router converts `GateDecision` into a `tool_result` with
`status: "error"` and the `reason` field as the error message. The LLM
sees this like any other tool error and the next iteration of the tool-use
loop retries. The `retry_hint` payload gives the LLM a structured hint
about what to do next (e.g. "call library.search first with intent=...").
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from library_validator import ValidationResult, validate as validate_spec


# The set of library tools the gate recognises. Everything else passes
# through. Other tools (graph.*, speckle.*, node.*, skill.*) are governed
# by their own logic — the LIBRARY-FIRST gate only cares about creating
# new node types.
#
# Canonical names use dots (AgDR-0013 docs). Wire-format names use
# underscores (provider tool-name validation rejects dots in some shapes).
# `_canonicalise_name()` collapses both wire formats to canonical so the
# gate is wire-shape agnostic.
_LIBRARY_TOOLS = frozenset({
    "library.search",
    "library.list_node_types",
    "library.inspect",
    "library.create_node_type",
    "library.delete_node_type",
})


def _canonicalise_name(tool_name: str) -> str:
    """Map wire-format tool names back to the canonical dot form.

    Accepts:
      library.search      (canonical — pass through)
      library_search      (single-underscore wire format, ToolEngine TOOLS list)
      library__search     (double-underscore wire format, connector-op convention)
    """
    if not tool_name:
        return tool_name
    if tool_name.startswith("library."):
        return tool_name
    if tool_name.startswith("library__"):
        return "library." + tool_name[len("library__"):]
    if tool_name.startswith("library_"):
        return "library." + tool_name[len("library_"):]
    return tool_name


@dataclass
class TurnState:
    """Per-turn state observed by the gate.

    A "turn" = one round-trip from user message to assistant final message
    (with potentially many internal tool iterations). State persists across
    tool iterations WITHIN one turn but resets per user message.
    """

    library_searched: bool = False
    # Useful for diagnostics + future heuristics. Not used by the gate's
    # decision logic today.
    invocations: list[dict] = field(default_factory=list)

    def reset(self) -> None:
        self.library_searched = False
        self.invocations = []


@dataclass
class GateDecision:
    """Result of `LibraryGate.check()`.

    `allow=True` → router proceeds to `ToolEngine.invoke()`.
    `allow=False` → router converts to a tool_result with `status:"error"`,
    `error: reason`, and `retry_hint: <hint dict>`; the LLM sees this and
    retries on the next iteration of the tool-use loop.
    """

    allow: bool
    reason: str = ""
    retry_hint: Optional[dict] = None


# Sentinel for the retry hint when search is the missing prerequisite.
def _retry_hint_call_search_first(spec: Any) -> dict:
    """Build a structured retry hint pointing the LLM at library.search."""
    intent_guess = ""
    if isinstance(spec, dict):
        intent_guess = (
            spec.get("display_name")
            or spec.get("description", "")[:60]
            or spec.get("type", "")
        )
    return {
        "call": "library.search",
        "with_args": {"intent": intent_guess} if intent_guess else {},
        "then": "if no match ≥0.75 similarity, retry library.create_node_type with the same spec",
    }


def _retry_hint_fix_spec(violations: list[str]) -> dict:
    """Build a structured retry hint listing the spec violations to fix."""
    return {
        "call": "library.create_node_type",
        "fix": violations,
        "then": "resubmit with these violations corrected",
    }


class LibraryGate:
    """The Layer-3 gate. Model-agnostic. Stateless (state lives on TurnState).

    Usage in `llm_router._complete_once`:

        gate = LibraryGate()
        turn_state = TurnState()
        for tc in tool_calls:
            inv = ToolInvocation(...)
            decision = gate.check(inv, turn_state)
            if not decision.allow:
                # synthesize a tool_result with error + retry_hint
                ...
                continue
            # otherwise: ToolEngine.invoke(inv) as normal
    """

    def check(self, tool_name: str, arguments: dict,
              turn_state: TurnState) -> GateDecision:
        """Decide whether the named tool call may proceed.

        `tool_name` and `arguments` are extracted from the provider's
        tool_call payload (router has already normalised them).
        Wire-format underscores are collapsed to canonical dot names so
        the gate's logic stays wire-shape agnostic.
        """
        canonical = _canonicalise_name(tool_name)

        # Always log the invocation for diagnostics. Logs the CANONICAL
        # name so downstream tooling sees a single namespace.
        turn_state.invocations.append({
            "tool": canonical,
            "args_keys": list((arguments or {}).keys()),
        })

        # Rule 2: library.search marks the prerequisite flag and is always
        # allowed (gating it would be a deadlock — nothing else can run
        # before it).
        if canonical == "library.search":
            turn_state.library_searched = True
            return GateDecision(allow=True)

        # Rule 1: library.create_node_type requires (a) prior search this
        # turn AND (b) a modular spec.
        if canonical == "library.create_node_type":
            spec = (arguments or {}).get("spec")

            if not turn_state.library_searched:
                return GateDecision(
                    allow=False,
                    reason=(
                        "library.search must run first this turn — the "
                        "LIBRARY-FIRST mandate (AgDR-0012) requires "
                        "checking for an existing node before composing "
                        "a new one. Call library.search with an intent "
                        "string and re-try this call only if no match "
                        "≥0.75 similarity is found."
                    ),
                    retry_hint=_retry_hint_call_search_first(spec),
                )

            # Validator (Layer 4) is the structural floor on modularity.
            result: ValidationResult = validate_spec(spec or {})
            if not result.ok:
                return GateDecision(
                    allow=False,
                    reason=(
                        "library.create_node_type rejected — the spec is "
                        "not modular. Fix the violations and re-try: "
                        + "; ".join(result.violations)
                    ),
                    retry_hint=_retry_hint_fix_spec(result.violations),
                )

            return GateDecision(allow=True)

        # Rule 3: everything else passes the gate. Other gates / guards
        # (e.g. approval gating for host_write — USER-AGENCY mandate) live
        # elsewhere.
        return GateDecision(allow=True)

    def is_library_tool(self, tool_name: str) -> bool:
        """True if the tool is one of the library.* tools the gate knows.

        Wire-format underscore names are accepted via canonicalisation.
        """
        return _canonicalise_name(tool_name) in _LIBRARY_TOOLS
