"""AI Behaviour settings — extended-thinking budget + per-tool permissions.

User-facing controls that live in Settings → AI Behaviour. The model
honours both: the LLM router reads thinking_effort and passes the
mapped budget to each provider; the tool engine reads tool_policy
and either fires, prompts, or blocks each invocation.

Two stores, both via secrets_store.save_setting/load_setting:

  • thinking_effort: 'off' | 'low' | 'medium' | 'high'
        Maps to per-provider native knobs:
          anthropic: thinking={'type':'enabled','budget_tokens': N}
          google:    thinkingConfig.thinkingBudget = N
          openai:    reasoning_effort = 'low' | 'medium' | 'high'
                     (only for o-series; gpt-4o ignores)
          ollama:    no native; models with <think> tags self-budget

  • tool_policies: {tool_name: 'allow' | 'ask' | 'deny'}
        Defaults by tool kind:
          read-only (info, list, ping, search, read_thread) → allow
          mutate    (execute_*, set_*, draft_reply, move_*, mark_*,
                     create_*, save_attachments, push_parameters)  → ask
          destructive (none today)                                  → deny

Anything the user doesn't override falls to the default for that
kind (see _default_policy_for).

Public API
----------
    get_thinking_effort() -> 'off' | 'low' | 'medium' | 'high'
    set_thinking_effort(level) -> None
    thinking_budget_tokens(level=None) -> int
        Maps level → native budget (0 / 1024 / 4096 / 16384).
    get_tool_policy(tool_name) -> 'allow' | 'ask' | 'deny'
    set_tool_policy(tool_name, policy) -> None
    list_tool_policies() -> dict[str, str]
    reset_tool_policies() -> None
"""
from __future__ import annotations

from typing import Optional


_THINKING_LEVELS = ("off", "low", "medium", "high")
_POLICY_VALUES = ("allow", "ask", "deny")

# Token budgets per level. Anthropic-style; other providers either
# accept the same budget or convert via a small map below.
_THINKING_BUDGETS = {
    "off": 0,
    "low": 1024,
    "medium": 4096,
    "high": 16384,
}

# Openai o-series effort labels (no token count — categorical).
_OPENAI_EFFORT_MAP = {
    "off": None,        # don't set reasoning_effort (model decides)
    "low": "low",
    "medium": "medium",
    "high": "high",
}

# Tool-name patterns to default policy. Order matters — first match wins.
_DEFAULT_RULES: tuple[tuple[str, str], ...] = (
    # Deny path is reserved for future destructive ops. None today.
    # Mutating / writing ops → ask. User confirms each call.
    ("_execute_python", "ask"),
    ("_execute_csharp", "ask"),
    ("_execute_maxscript", "ask"),
    ("_set_categories", "ask"),
    ("_set_categories_by_filter", "ask"),
    ("_auto_categorize", "ask"),
    ("_draft_reply", "ask"),
    ("_save_attachments", "ask"),
    ("_create_folder", "ask"),
    ("_move_to_folder", "ask"),
    ("_mark_read", "ask"),
    ("_flag_for_followup", "ask"),
    ("_push_parameters", "ask"),
    ("_screenshot", "ask"),
    # Read-only / status calls → allow.
    ("_ping",     "allow"),
    ("_info",     "allow"),
    ("_list",     "allow"),
    ("_search",   "allow"),
    ("_read_",    "allow"),
    ("_pull_parameters", "allow"),
    ("_get_",     "allow"),
    # Local helpers → allow.
    ("archhub_",  "allow"),
)


def get_thinking_effort() -> str:
    try:
        from secrets_store import load_setting
        v = (load_setting("thinking_effort") or "").strip().lower()
        if v in _THINKING_LEVELS:
            return v
    except Exception:
        pass
    return "off"


def set_thinking_effort(level: str) -> None:
    lvl = (level or "").strip().lower()
    if lvl not in _THINKING_LEVELS:
        raise ValueError(f"invalid thinking_effort: {level!r}")
    try:
        from secrets_store import save_setting
        save_setting("thinking_effort", lvl)
    except Exception:
        pass


def thinking_budget_tokens(level: Optional[str] = None) -> int:
    """Return the anthropic-style budget for the given level (or
    the saved level when not specified). 0 disables thinking."""
    lvl = (level or get_thinking_effort()).lower()
    return int(_THINKING_BUDGETS.get(lvl, 0))


def openai_reasoning_effort(level: Optional[str] = None) -> Optional[str]:
    """Return the openai o-series reasoning_effort string, or None
    when thinking is off / level is unknown."""
    lvl = (level or get_thinking_effort()).lower()
    return _OPENAI_EFFORT_MAP.get(lvl, None)


# ---------------------------------------------------------------------------
def _default_policy_for(tool_name: str) -> str:
    n = (tool_name or "").lower()
    for pattern, policy in _DEFAULT_RULES:
        if pattern in n or n.startswith(pattern.lstrip("_")):
            return policy
    # Fallback: unknown → allow. Better to err on usability; user can
    # tighten any specific tool to ask/deny in Settings.
    return "allow"


def _load_overrides() -> dict[str, str]:
    try:
        from secrets_store import load_setting
        d = load_setting("tool_policies") or {}
        if not isinstance(d, dict):
            return {}
        return {str(k): str(v) for k, v in d.items()
                if v in _POLICY_VALUES}
    except Exception:
        return {}


def _save_overrides(d: dict[str, str]) -> None:
    try:
        from secrets_store import save_setting
        save_setting("tool_policies", dict(d))
    except Exception:
        pass


def get_tool_policy(tool_name: str) -> str:
    """User-set override if present, else the default for the tool's
    name pattern."""
    overrides = _load_overrides()
    if tool_name in overrides:
        return overrides[tool_name]
    return _default_policy_for(tool_name)


def set_tool_policy(tool_name: str, policy: str) -> None:
    if policy not in _POLICY_VALUES:
        raise ValueError(f"invalid policy {policy!r}; expected one of "
                          f"{_POLICY_VALUES}")
    d = _load_overrides()
    d[str(tool_name)] = policy
    _save_overrides(d)


def list_tool_policies() -> dict[str, str]:
    """Snapshot of the user's overrides only (defaults excluded)."""
    return _load_overrides()


def reset_tool_policies() -> None:
    """Clear every user override. Defaults re-apply for all tools."""
    _save_overrides({})
