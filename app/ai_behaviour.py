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

# Per-host suffix → default policy. Lookup proceeds:
#   1) family of the tool ("revit", "max", "outlook", …)
#   2) suffix match within that family's table (longest match wins)
#   3) cross-family fallback (`_FAMILY_DEFAULTS` row below)
#   4) generic per-suffix fallback (`_GENERIC_RULES`)
#
# Why per-host: an "execute_python" in Blender (read-only sandbox)
# is much lower-risk than "execute_python" in Outlook (talks to
# corporate email). Per-host lets us nudge sensible defaults.
_FAMILY_DEFAULTS: dict[str, dict[str, str]] = {
    "revit": {
        "ping": "allow", "info": "allow",
        "execute_csharp": "ask", "execute_python": "ask",
        "push_parameters": "ask", "pull_parameters": "allow",
        "screenshot": "ask",
    },
    "acad": {
        "ping": "allow", "info": "allow",
        "execute_csharp": "ask", "execute_python": "ask",
        "execute_lisp": "ask",
    },
    "max": {
        "ping": "allow", "info": "allow",
        "execute_python": "ask", "execute_maxscript": "ask",
        "screenshot": "ask",
    },
    "blender": {
        "ping": "allow", "info": "allow",
        "execute_python": "ask",  # sandbox but can still hose a .blend
        "save": "ask", "render": "ask",
    },
    "outlook": {
        "ping": "allow", "info": "allow",
        "list_inbox": "allow", "list_sent_items": "allow",
        "list_folders": "allow", "list_distinct_senders": "allow",
        "search_threads": "allow", "read_thread": "allow",
        "draft_reply": "ask",
        "send_draft": "ask",
        "save_attachments": "ask",
        "create_folder": "ask", "move_to_folder": "ask",
        "mark_read": "ask", "flag_for_followup": "ask",
        "set_categories": "ask", "set_categories_by_filter": "ask",
        "auto_categorize_by_sender": "ask",
        "auto_categorize_by_subject_keywords": "ask",
        "execute_python": "ask",  # COM escape hatch — risky
    },
    "speckle": {
        "list_projects": "allow", "get_project": "allow",
        "push_parameters": "ask",
    },
    "archhub": {
        # Local helpers — always safe.
        "list_connectors": "allow",
        "list_skills": "allow",
        "run_skill": "ask",
    },
    "_local": {
        # tool_engine.TOOLS uses "_local" as the family for ArchHub's
        # own helpers (archhub_*). Alias of the "archhub" family above.
        "list_connectors": "allow",
        "list_skills": "allow",
        "run_skill": "ask",
    },
    "ai": {
        # AI-as-tool — primary model delegates to another LLM. Calling
        # an LLM is a read (no mutation of user data) so defaults are
        # "allow". The user can flip any specific tool to "ask" if they
        # want a confirmation before spending tokens on the second LLM.
        "chatgpt_ask":   "allow",
        "gemini_ask":    "allow",
        "lmstudio_ask":  "allow",
        "antigravity_ask": "allow",
        "list_providers":  "allow",
    },
}

# Generic per-suffix fallback when a tool's family isn't yet known
# (e.g. brand-new connector that hasn't been wired into ai_behaviour).
# Longest suffix wins, so `execute_python` beats `execute`.
_GENERIC_RULES: tuple[tuple[str, str], ...] = (
    # Mutating / writing ops → ask.
    ("execute_python", "ask"),
    ("execute_csharp", "ask"),
    ("execute_maxscript", "ask"),
    ("execute_lisp", "ask"),
    ("execute", "ask"),
    ("draft_reply", "ask"),
    ("send_draft", "ask"),
    ("save_attachments", "ask"),
    ("set_categories_by_filter", "ask"),
    ("set_categories", "ask"),
    ("auto_categorize_by_sender", "ask"),
    ("auto_categorize_by_subject_keywords", "ask"),
    ("auto_categorize", "ask"),
    ("create_folder", "ask"),
    ("move_to_folder", "ask"),
    ("mark_read", "ask"),
    ("flag_for_followup", "ask"),
    ("push_parameters", "ask"),
    ("screenshot", "ask"),
    ("render", "ask"),
    ("save", "ask"),
    # Read-only.
    ("ping", "allow"),
    ("info", "allow"),
    ("list_", "allow"),
    ("search_", "allow"),
    ("read_", "allow"),
    ("pull_parameters", "allow"),
    ("get_", "allow"),
)

# Legacy public name retained for any external caller — same semantics.
_DEFAULT_RULES = _GENERIC_RULES


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
def _family_of(tool_name: str) -> str:
    """Best-effort guess of the host family for a tool name.

    Pattern: tools are named `<family>_<verb>` (revit_ping, outlook_list_inbox,
    archhub_list_connectors). Take the prefix up to the first underscore.
    """
    n = (tool_name or "").lower()
    if "_" not in n:
        return n
    return n.split("_", 1)[0]


def _suffix_of(tool_name: str) -> str:
    n = (tool_name or "").lower()
    if "_" not in n:
        return ""
    return n.split("_", 1)[1]


def _default_policy_for(tool_name: str) -> str:
    """Decide the default policy ('allow' / 'ask' / 'deny') for a tool.

    Priority chain:
      1. Family-specific override (`_FAMILY_DEFAULTS[family][suffix]`)
      2. Family-specific longest-suffix substring match (e.g.
         `list_distinct_senders` falls through to `list_` in family
         table when present)
      3. Generic suffix rules (`_GENERIC_RULES`), longest match wins
      4. Catch-all: `"allow"` (user can tighten via Settings)
    """
    family = _family_of(tool_name)
    suffix = _suffix_of(tool_name)

    fam_table = _FAMILY_DEFAULTS.get(family, {})
    # Exact suffix hit in family.
    if suffix and suffix in fam_table:
        return fam_table[suffix]
    # Longest-prefix-of-suffix hit in family (longest first).
    for key in sorted(fam_table.keys(), key=len, reverse=True):
        if suffix.startswith(key) or key in suffix:
            return fam_table[key]

    # Generic rules — longest pattern first.
    n = (tool_name or "").lower()
    for pattern, policy in sorted(_GENERIC_RULES, key=lambda kv: len(kv[0]), reverse=True):
        if pattern in n:
            return policy

    return "allow"


# ---------------------------------------------------------------------------
def tools_grouped_by_host() -> dict[str, list[dict]]:
    """Snapshot of the live `tool_engine.TOOLS` registry grouped by
    host family, with each tool dict carrying:

        { "name":        "outlook_list_inbox",
          "description": "List the N most recent emails…",
          "policy":      "allow",                      # active policy
          "default":     "allow",                      # built-in default
          "overridden":  False }                       # user-set?

    Group ordering: revit → acad → max → outlook → blender → speckle
    → archhub → anything else alphabetically. Tools within a group
    sort alphabetically.

    Used by Settings → AI Behaviour to render a section per connected
    host. If a host's tools aren't registered (broker offline / not
    installed) the corresponding section just doesn't appear.
    """
    try:
        from tool_engine import TOOLS  # local import — avoid circular at module load
    except Exception:
        return {}

    overrides = _load_overrides()
    bucket: dict[str, list[dict]] = {}
    for t in TOOLS:
        name = t.get("name") or ""
        if not name:
            continue
        fam = (t.get("family") or _family_of(name)).lower()
        default = _default_policy_for(name)
        policy = overrides.get(name, default)
        bucket.setdefault(fam, []).append({
            "name":        name,
            "description": t.get("description") or "",
            "policy":      policy,
            "default":     default,
            "overridden":  name in overrides,
        })

    # Preferred display order; unknown families appended alphabetically.
    order = ("revit", "acad", "max", "outlook", "blender", "speckle",
             "ai", "archhub", "_local")
    out: dict[str, list[dict]] = {}
    for fam in order:
        if fam in bucket:
            out[fam] = sorted(bucket.pop(fam), key=lambda d: d["name"])
    for fam in sorted(bucket.keys()):
        out[fam] = sorted(bucket[fam], key=lambda d: d["name"])
    return out


def host_display_label(family: str) -> str:
    """Human label for a host family — used in Settings section headers."""
    return {
        "revit":   "Revit",
        "acad":    "AutoCAD",
        "max":     "3ds Max",
        "outlook": "Outlook (classic)",
        "blender": "Blender",
        "speckle": "Speckle",
        "ai":      "AI delegations (ChatGPT · Gemini · LM Studio · Antigravity)",
        "archhub": "ArchHub (local)",
        "_local":  "ArchHub (local)",
    }.get((family or "").lower(), (family or "").title())


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
