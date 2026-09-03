"""LLM Router — the brain.

Holds clients for every configured provider (Anthropic, OpenAI, Google) and
routes prompts to the right model. Three modes:

- ROUTE_AUTO       — heuristic: pick model based on task signal (modeling →
                     Claude Sonnet, image understanding → Claude/GPT-4o,
                     simple chat → fast cheap model).
- specific model   — user picked it in the dropdown, forward as-is.
- agent / future   — agents may override and chain multiple models.

Tool-use loop happens here: send tools to the model, when it asks to invoke
one, run it through ToolEngine, send the result back, continue until the
model returns a final assistant message.
"""
from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from typing import Callable, Optional

from secrets_store import load_api_key, list_keys
from tool_engine import ToolEngine, ToolInvocation


ROUTE_AUTO = "auto"

# The NVIDIA NIM model id that is KNOWN-CALLABLE on the default/free key (the
# exact model the ArchHub Cloud proxy serves successfully). Used whenever a
# `nvidia:` pick names NO specific model (a bare `nvidia` or `nvidia:auto`) so
# the desktop never resolves to an un-callable catalog entry like
# `nvidia/llama-3.1-nemotron-ultra-253b-v1`, which 404s
# "Function-not-found-for-account" on accounts that don't have it provisioned.
NVIDIA_DEFAULT_MODEL = "meta/llama-3.3-70b-instruct"


def _looks_like_auth_or_quota(ex: Exception) -> bool:
    """True if the exception message smells like 'no credits / bad key /
    quota exceeded' — a hard provider failure that re-trying will not fix.
    Covers Anthropic, OpenAI, Google, OpenRouter SDK error strings.
    """
    s = (str(ex) or "").lower()
    needles = (
        "credit balance is too low",
        "insufficient_quota",
        "quota exceeded",
        "exceeded your current quota",
        "exceeded your monthly",
        "rate limit",
        "rate_limit_exceeded",
        "invalid api key",
        "invalid_api_key",
        "incorrect api key",
        "unauthorized",
        "401",
        "403",
        "billing",
        "payment required",
        "402",
        "permission_denied",
        "api key expired",
        # ArchHub Cloud's managed proxy returns 402 with a typed
        # `byo_key_required` body when the user has no managed quota and
        # hasn't pasted a provider key. The stringified openai SDK error
        # usually carries the bare "402" too, but match the worded form
        # explicitly so a body whose numeric code got stripped is STILL
        # classified as "skip to next provider" — never a fatal turn
        # error that leaves the user with nothing while a local provider
        # (claude_cli / codex / ollama) was sitting right there.
        "byo_key_required",
        "byo_key",
        "byo key",
        "bring your own key",
        "no managed quota",
        "quota_exhausted",
    )
    return any(n in s for n in needles)


def _looks_like_uncallable_model(ex: Exception) -> bool:
    """True when the exception means THIS MODEL is not callable on this
    account — a 404 'function not found' / 'model does not exist' / 'unknown
    model'. Distinct from an AUTH failure (the key itself is fine) and from a
    transient blip (retrying the same model won't help). The fix is to mark
    the specific model bad + route onward, NOT to block the whole provider or
    re-try the identical 404 (founder archhub.log:
    `[nvidia] NotFoundError 404 Function-not-found-for-account on model
    nvidia/llama-3.1-nemotron-ultra-253b-v1`).
    """
    s = (str(ex) or "").lower()
    cls = type(ex).__name__.lower()
    # NVIDIA NIM phrasing + the generic OpenAI/SDK 'model not found' family.
    needles = (
        "function-not-found",
        "function not found",
        "model does not exist",
        "model not found",
        "does not exist or you do not have access",
        "no such model",
        "unknown model",
        "model_not_found",
        "the model `",          # openai 'The model `x` does not exist'
        "invalid model",
    )
    if any(n in s for n in needles):
        return True
    # A bare 404 from a NotFoundError is a model/route problem (not auth/quota,
    # which carry 401/403/402). Only treat 404 as uncallable-model — never a
    # generic match that could swallow real network 404s without the class.
    if "notfounderror" in cls and "404" in s:
        return True
    return False


def _claude_cli_is_auth(ex: Exception) -> bool:
    """True when a claude_cli failure is an AUTHENTICATION problem, not a
    generic crash. The Claude Code CLI surfaces a logged-out / expired
    subscription as a worded message — 'not authenticated', 'please log
    in', 'invalid api key', 'oauth token has expired', 'session expired',
    'forbidden' — and sometimes a bare HTTP 401/403, both wrapped in the
    `claude CLI error: …` RuntimeError the client raises. `_looks_like_auth_or_quota`
    already matches the bare 401/403 + 'unauthorized'; this adds the CLI's
    natural-language auth phrasings so an expired token re-routes onward
    (Codex / metered API / Ollama) instead of being treated as a fatal
    turn error. Founder bug 'router not working': a 401'd claude_cli must
    fall through, not blow up the whole reply."""
    s = (str(ex) or "").lower()
    needles = (
        "401",
        "403",
        "unauthorized",
        "not authenticated",
        "unauthenticated",
        "authentication",
        "please log in",
        "please login",
        "log in to",
        "logged out",
        "not logged in",
        "sign in",
        "oauth",
        "token has expired",
        "token expired",
        "session expired",
        "credentials",
        "forbidden",
        "invalid api key",
        "invalid_api_key",
    )
    return any(n in s for n in needles)


def _looks_like_transient_network(ex: Exception) -> bool:
    """True for short-lived network blips that a single retry fixes.
    Examples we've seen in production Sentry:
      - WinError 10054 'forcibly closed by the remote host'
      - httpx ReadError / ConnectError / RemoteProtocolError
      - openai.APIConnectionError 'Connection error.'
      - cloudflare 502/503/504 wrapping the upstream
    These are NOT quota / auth — same provider on retry usually works.
    """
    s = (str(ex) or "").lower()
    cls = type(ex).__name__.lower()
    needles_msg = (
        "forcibly closed",
        "winerror 10054",
        "connection error",
        "connection reset",
        "connection aborted",
        "remote end closed",
        "read timed out",
        "read error",
        "remoteprotocolerror",
        "temporary failure",
        "service unavailable",
        "bad gateway",
        "gateway timeout",
        "502",
        "503",
        "504",
        "529",  # anthropic overloaded
        "overloaded",
    )
    needles_cls = (
        "apiconnectionerror",
        "readerror",
        "connecterror",
        "remoteprotocolerror",
        "readtimeout",
        "connecttimeout",
    )
    if any(n in cls for n in needles_cls):
        return True
    return any(n in s for n in needles_msg)


# Family-level keyword expansions — natural-language nouns the user
# is likely to use that map to a host family. When any keyword on a
# row matches the user's last message, ALL tools whose name starts
# with that family prefix get a strong relevance boost. Solves the
# "READ ALL THE EMAILS AND CATEGORIZE THEM" case where "emails" /
# "categorize" don't substring-match any tool name even though the
# user clearly wants outlook_* tools.
_FAMILY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "outlook": ("outlook", "email", "emails", "mail", "mails",
                 "inbox", "message", "messages", "reply", "draft",
                 "send", "sent", "categorize", "categorise",
                 "categories", "folder", "folders", "attachment",
                 "attachments", "flag", "unread", "thread",
                 "forward", "newsletter", "newsletters", "archive",
                 "sender", "senders", "subject", "from:", "to:"),
    "revit": ("revit", "rvt", "wall", "walls", "door", "doors",
               "window", "windows", "level", "levels", "view",
               "views", "sheet", "sheets", "schedule", "schedules",
               "dimension", "dimensions", "annotate", "annotation",
               "tag", "tags", "family", "families", "room", "rooms",
               "ifc"),
    "acad": ("autocad", "acad", "dwg", "polyline", "polylines",
              "block", "blocks", "xref", "xrefs", "layer", "layers",
              "linetype"),
    "max": ("3ds", "3dsmax", "maxscript", "pymxs", "render",
             "renders", "viewport", "spline"),
    "blender": ("blender", "bpy", "mesh", "meshes", "extrude",
                 "modifier", "modifiers", "scene", "scenes"),
    "speckle": ("speckle", "stream", "streams", "commit", "commits",
                 "branch", "branches"),
}


def _filter_tools_by_relevance(tool_schemas: list[dict],
                                 history: list[dict],
                                 *, cap: int = 12) -> list[dict]:
    """Trim a long tool schema list down to the ones plausibly
    relevant to the user's last message + always-keep "info" tools.

    Why: Gemini Flash refuses to pick from a 30+ tool menu — returns
    completely empty (no text, no tool call) when overwhelmed.

    Strategy (v2 — natural-language aware):
      1. Always-keep set: every host's *_info + *_ping + the
         archhub_list_connectors helper. ~10 tools.
      2. Family promotion: when ANY noun from _FAMILY_KEYWORDS hits
         the user's message, the matching family's tools get a +10
         boost. Solves "emails" → outlook_*, "wall" → revit_*, etc.
      3. Per-tool substring score: small boost for direct
         name-keyword overlap.
      4. Sort by (family boost + per-tool score) desc, fill the
         remaining slots up to cap.
    """
    if not tool_schemas or len(tool_schemas) <= cap:
        return list(tool_schemas)
    last_user = ""
    for m in reversed(history):
        if m.get("role") == "user":
            c = m.get("content") or ""
            if isinstance(c, list):
                c = " ".join(p.get("text", "") for p in c
                              if isinstance(p, dict))
            last_user = str(c).lower()
            break

    def _name(t: dict) -> str:
        return t.get("name") or (t.get("function") or {}).get("name", "") or ""

    # Family promotion — which host families did the user mention?
    promoted_families: set[str] = set()
    for fam, words in _FAMILY_KEYWORDS.items():
        if any(w in last_user for w in words):
            promoted_families.add(fam)

    # Always-keep set is dynamic. If the user mentioned a specific
    # family, keep ONLY those families' info/ping/execute tools +
    # the universal helper — frees ~8 slots for the actual actioning
    # tools the user wants. execute_* is always kept because it's
    # the escape-hatch tool: if no named tool fits the user request,
    # the model writes code + calls execute_*.
    if promoted_families:
        always_keep = {"archhub_list_connectors"}
        for fam in promoted_families:
            for stub in ("info", "ping"):
                always_keep.add(f"{fam}_{stub}")
            # Escape-hatch tools — execute_python / execute_csharp /
            # execute_maxscript. Always keep for the promoted family
            # so the model can write code when no named tool fits.
            for ex in ("execute_python", "execute_csharp",
                        "execute_maxscript"):
                always_keep.add(f"{fam}_{ex}")
    else:
        # No family mentioned in the prompt — model needs escape
        # hatches for ALL hosts plus the cheap info tools. Without
        # this, queries like 'forward all newsletters' (no outlook
        # keyword) leave the model without any execute tool to
        # actually write code with.
        always_keep = {
            "archhub_list_connectors",
            "outlook_info", "revit_info", "acad_info", "max_info",
            "blender_info",
            "outlook_execute_python",
            "revit_execute_csharp",
            "acad_execute_csharp",
            "max_execute_python",
            "blender_execute_python",
        }
    kept = [t for t in tool_schemas if _name(t) in always_keep]

    # Score remaining tools.
    keywords = [w for w in last_user.split() if len(w) > 2]
    scored: list[tuple[int, dict]] = []
    for t in tool_schemas:
        n = _name(t).lower()
        if not n or n in always_keep:
            continue
        score = 0
        # Family promotion adds a big boost so every tool of the
        # mentioned family beats a stray substring hit on another
        # family's tool name.
        for fam in promoted_families:
            if n.startswith(fam + "_"):
                score += 10
                break
        # Per-keyword substring overlap — fine-grained tiebreak.
        for kw in keywords:
            if kw in n:
                score += 1
        if score > 0:
            scored.append((score, t))
    scored.sort(key=lambda kv: -kv[0])

    out = list(kept)
    for _, t in scored:
        if len(out) >= cap:
            break
        out.append(t)
    return out


def _looks_like_refusal(text: str, had_tools: bool,
                         tool_call_count: int) -> bool:
    """True when the model emitted text that smells like a refusal
    AND tools were available but none were called.

    Trip wires (regression class from live traces):
      - 'I cannot read'
      - 'I'm not able to'
      - 'I can only provide'
      - 'My capabilities are limited'
      - 'I do not have the ability'
      - 'Please tell me the specific'
    All seen in Gemini Flash + Pro responses when asked to act on
    outlook data, despite the AUTHORITY grant in the system prompt.
    Treat as a soft failure: block this provider for a few minutes
    and let the fallback chain route to Ollama / Claude (which DO
    use the tools)."""
    if tool_call_count > 0:
        return False
    if not had_tools:
        return False
    if not text or len(text.strip()) < 30:
        return False
    lo = text.lower()
    needles = (
        "i cannot read", "i can't read",
        "i cannot access", "i can't access",
        "i'm not able to", "i am not able to",
        "i can only provide", "i can only give you",
        "my capabilities are limited",
        "i do not have the ability", "i don't have the ability",
        "i cannot directly",
        "i cannot automatically",
        "i'm not authorized", "i am not authorized",
        "i cannot perform",
    )
    return any(n in lo for n in needles)


def _looks_like_fabricated_tools(text: str, tool_call_count: int) -> bool:
    """True when the model TYPED tool-call / tool-result markup into its
    prose instead of making a real structured tool call.

    A model with working tools emits STRUCTURED calls — the router
    executes them out-of-band and the markup never lands in `text`.
    Only a tool-less, mis-routed, or confused model writes a literal
    <function_calls>/<invoke> block — and then a fabricated
    <function_result> and a false conclusion. This is the founder's
    recurring bug: 'No files open in AutoCAD' typed under a fake
    <function_result> while a drawing was open.

    A tool RESULT in the model's own text is ALWAYS fabrication — real
    results are injected by the runtime, never authored by the model.

    GUARD (post-2026-05-16 root fix): the mechanism fix is that every
    provider now carries the tool surface, so the model can make real
    calls. This catches the residual case — every tool-capable provider
    down — so a fabricated answer is re-routed or fails honestly,
    never shown to the user as truth."""
    if tool_call_count > 0:
        return False          # a real tool call grounded this turn
    lo = (text or "").lower()
    return ("<function_result" in lo
            or "<tool_result>" in lo
            or ("<function_calls>" in lo and "<invoke" in lo)
            or "<invoke" in lo)


def _summarise_tool_result(inv) -> str:
    """Build a one-line, human-readable summary of a tool invocation
    so the chat surface has SOMETHING to render when the LLM
    forgot to emit text. Friendlier than 'empty response' and
    actually carries the information the user asked for.

    Examples:
      outlook_info ok → 'Outlook: 966 inbox, 3 unread.'
      revit_info  ok → 'Revit: Tower-A.rvt, level 02 active.'
      <anything>  err→ 'Tool revit_execute_csharp failed: <reason>.'
      <generic>   ok → 'Tool <name> ran successfully.'
    """
    name = getattr(inv, "tool_name", "") or "tool"
    status = getattr(inv, "status", "") or ""
    result = getattr(inv, "result", None) or {}
    if status == "error":
        err = (result.get("error") if isinstance(result, dict)
                else str(result))[:160]
        return f"Tool {name} failed: {err}"
    if not isinstance(result, dict):
        return f"Tool {name} returned: {str(result)[:160]}"
    # Hand-tuned summarisers for the highest-value tools.
    if name == "outlook_info":
        inb = result.get("inbox_total")
        unr = result.get("inbox_unread")
        dft = result.get("drafts_count")
        acct = result.get("default_account_email") or ""
        bits = []
        if inb is not None:
            bits.append(f"{inb} inbox")
        if unr is not None:
            bits.append(f"{unr} unread")
        if dft:
            bits.append(f"{dft} drafts")
        head = f"Outlook ({acct}): " if acct else "Outlook: "
        return head + ", ".join(bits) + "." if bits else "Outlook reachable."
    if name == "revit_info":
        title = result.get("title") or result.get("doc_title") or ""
        view = result.get("active_view") or ""
        ver = result.get("version") or ""
        bits = [b for b in (title, view, ver) if b]
        return f"Revit: {', '.join(bits)}." if bits else "Revit reachable."
    if name == "blender_info":
        path = result.get("filepath") or ""
        scene = result.get("scene") or ""
        objs = result.get("object_count")
        bits = []
        if path:
            bits.append(path.split("\\")[-1].split("/")[-1])
        if scene:
            bits.append(scene)
        if objs is not None:
            bits.append(f"{objs} objects")
        return f"Blender: {', '.join(bits)}." if bits else "Blender reachable."
    if name in ("revit_ping", "acad_ping", "max_ping", "blender_ping"):
        return f"{name.replace('_ping', '').title()} is reachable."
    # Token-based REST connectors (notion / dropbox / teams / procore /
    # speckle) authenticate with a saved token, not a local process. When the
    # token is missing their ping/status returns `reachable: False` (or an
    # `unauthorized` status) — that is "not connected, add your token", NOT a
    # plain success. Surface the actionable message so the model never reports
    # a token-less connector as merely "reachable=False" or as reachable.
    # (Founder bug 2026-06-20: token-not-configured read as "(unknown)".)
    _TOKEN_REST = ("notion", "dropbox", "teams", "procore", "speckle")
    host_prefix = name.split("_", 1)[0] if "_" in name else name
    if host_prefix in _TOKEN_REST:
        disp = "Teams" if host_prefix == "teams" else host_prefix.title()
        rst = str(result.get("status") or "").lower()
        reachable = result.get("reachable")
        note = str(result.get("note") or "").strip()
        if rst == "unauthorized" or reachable is False:
            return (note or
                    f"{disp} not connected — add your integration token in "
                    f"Settings -> Sign-ins -> {disp}.")
        if rst == "live" or reachable is True:
            return f"{disp} is connected{(' — ' + note) if note else '.'}"
    # Generic fallback — find the most informative scalar field.
    interesting = [(k, v) for k, v in result.items()
                   if k != "status" and not isinstance(v, (dict, list))
                   and v not in (None, "")]
    if interesting:
        kv = ", ".join(f"{k}={v}" for k, v in interesting[:4])
        return f"Tool {name}: {kv}."
    return f"Tool {name} ran successfully."


def _looks_like_action(messages: list[dict]) -> bool:
    """Heuristic: did the most recent user message ask for a concrete
    AEC action (vs a Q&A / chitchat)? Used by the procrastination
    detector — we only nudge a non-tool-calling model when the user
    clearly wanted a tool fired.

    True when the last user message contains any verb from the
    catalogue. Generous on purpose — a false positive costs one
    extra round of inference; a false negative lets the model
    procrastinate unchecked."""
    if not messages:
        return False
    last_user = ""
    for m in reversed(messages):
        if m.get("role") == "user":
            c = m.get("content") or ""
            if isinstance(c, list):
                c = " ".join(p.get("text", "") for p in c
                              if isinstance(p, dict))
            last_user = str(c).lower()
            break
    if not last_user:
        return False
    action_verbs = (
        "create", "make", "build", "add", "place", "draw", "model",
        "generate", "delete", "remove", "move", "rotate", "scale",
        "render", "extrude", "tag", "annotate", "dimension",
        "schedule", "push", "pull", "sync", "import", "export",
        "save", "open", "load", "run", "execute", "list", "search",
        "find", "show me", "give me", "fetch", "read", "write",
        "reply", "send", "categorise", "categorize", "flag",
        "mark", "move to",
    )
    return any(v in last_user for v in action_verbs)


# (model_id, label-shown-in-dropdown). model_id is "<provider>:<api_model_name>".
# OpenRouter rows let the user reach Anthropic / OpenAI / Google without
# minting per-provider keys — one OAuth sign-in covers everything below
# the openrouter prefix.
KNOWN_MODELS: list[tuple[str, str]] = [
    # Labels trimmed in v1.3.2 — the dropdown is read at a glance, so the
    # marketing tail ("— best reasoning", "OpenRouter · …") was decoration.
    # Tooltip on the row still surfaces the longer description.
    ("anthropic:claude-opus-4-7",                       "Claude Opus 4.7"),
    ("anthropic:claude-opus-4-6",                       "Claude Opus 4.6"),
    ("anthropic:claude-sonnet-4-6",                     "Claude Sonnet 4.6"),
    ("anthropic:claude-haiku-4-5-20251001",             "Claude Haiku 4.5"),
    ("openai:gpt-4o",                                   "GPT-4o"),
    ("openai:gpt-4o-mini",                              "GPT-4o mini"),
    ("google:gemini-2.5-pro",                           "Gemini 2.5 Pro"),
    ("google:gemini-2.0-flash",                         "Gemini 2.0 Flash"),
    ("openrouter:anthropic/claude-opus-4",              "Claude Opus 4 (OR)"),
    ("openrouter:anthropic/claude-sonnet-4",            "Claude Sonnet 4 (OR)"),
    ("openrouter:openai/gpt-4o",                        "GPT-4o (OR)"),
    ("openrouter:google/gemini-2.5-flash",              "Gemini 2.5 Flash (OR)"),
    ("openrouter:meta-llama/llama-3.3-70b-instruct",    "Llama 3.3 70B (OR)"),
    ("openrouter:qwen/qwen-2.5-coder-32b-instruct",     "Qwen 2.5 Coder 32B (OR)"),
    # NVIDIA NIM (build.nvidia.com) — OpenAI-compatible cloud endpoint; ONE
    # NVIDIA_API_KEY covers every catalog model below the nvidia prefix
    # (founder 2026-06-10 "can we utilize NVIDIA models?").
    #
    # ORDER MATTERS: the FIRST nvidia row is the default the picker shows and
    # the model `nvidia:` resolves to when no specific model is named. It MUST
    # be a known-CALLABLE model. `meta/llama-3.3-70b-instruct` is the exact id
    # the ArchHub Cloud proxy serves successfully (NVIDIA_DEFAULT_MODEL below),
    # so it leads. The big `nemotron-ultra-253b` row stays in the catalog for
    # accounts that DO have it provisioned, but it 404s
    # "Function-not-found-for-account" on the default free key — so it is no
    # longer the head row that an empty `nvidia:` pick would land on (founder
    # archhub.log: repeated `[nvidia] NotFoundError 404 Function-not-found`).
    ("nvidia:meta/llama-3.3-70b-instruct",              "Llama 3.3 70B (NV)"),
    ("nvidia:nvidia/llama-3.3-nemotron-super-49b-v1",   "Nemotron Super 49B (NV)"),
    ("nvidia:deepseek-ai/deepseek-r1",                  "DeepSeek R1 (NV)"),
    ("nvidia:qwen/qwen2.5-coder-32b-instruct",          "Qwen 2.5 Coder 32B (NV)"),
    ("nvidia:nvidia/llama-3.1-nemotron-ultra-253b-v1",  "Nemotron Ultra 253B (NV)"),
    ("relay:auto",                                      "Firm relay"),
]


# Real per-million-token USD prices for cost accounting. Keyed by a
# substring matched case-insensitively against the model name returned by
# the provider. (input_per_M, output_per_M). Only models whose real public
# price we know appear here — anything not matched yields cost_known=False
# so the UI omits a dollar figure rather than fabricating one. Local
# models (ollama / lmstudio / claude_cli / codex_cli subscription) are NOT
# metered per token, so they carry no row → token count shown, no cost.
_MODEL_PRICES_PER_M: dict[str, tuple[float, float]] = {
    "claude-opus-4":    (15.0, 75.0),
    "claude-sonnet-4":  (3.0, 15.0),
    "claude-haiku-4":   (1.0, 5.0),
    "gpt-4o-mini":      (0.15, 0.60),
    "gpt-4o":           (2.5, 10.0),
    "gemini-2.5-pro":   (1.25, 10.0),
    "gemini-2.0-flash": (0.10, 0.40),
    "gemini-2.5-flash": (0.30, 2.5),
}


def _price_for_model(model_name: str) -> Optional[tuple[float, float]]:
    """Return (input_per_M, output_per_M) USD for the model, or None when
    no real price is known (local/subscription models, or a model not in
    the table). Longest-key match wins so 'gpt-4o-mini' beats 'gpt-4o'."""
    lo = (model_name or "").lower()
    best: Optional[tuple[float, float]] = None
    best_len = -1
    for key, price in _MODEL_PRICES_PER_M.items():
        if key in lo and len(key) > best_len:
            best, best_len = price, len(key)
    return best


def ollama_models() -> list[tuple[str, str]]:
    """Return (model_id, label) pairs for every model pulled in Ollama."""
    try:
        from llm_providers.ollama_client import list_local_models
        return [
            (f"ollama:{name}", f"{name} — local (Ollama)")
            for name in list_local_models()
        ]
    except Exception:
        return []


def lmstudio_models() -> list[tuple[str, str]]:
    """Return (model_id, label) pairs for every model loaded in LM Studio.

    Uses llm_detector.probe_lmstudio (which queries the LM Studio local
    server at 127.0.0.1:1234/v1/models). When the LM Studio server is
    NOT running we return []. The probe is cached for 25s per llm_detector
    so the model picker refresh is fast.
    """
    try:
        from llm_detector import probe_lmstudio
        res = probe_lmstudio() or {}
        if res.get("status") != "live":
            return []
        return [
            (f"lmstudio:{name}", f"{name} — local (LM Studio)")
            for name in (res.get("models") or [])
        ]
    except Exception:
        return []


@dataclass
class LLMResponse:
    text: str
    model: str
    tool_invocations: list[ToolInvocation]
    routing_note: str = ""
    # Tools a self-driving CLI provider (claude_cli) executed in-process
    # via its own MCP loop. The router's tool-use loop never sees these
    # (the CLI ran + resolved them itself), so they ride out here for the
    # ai.plan turn record. Shape: [{"name","input","result"}].
    tool_calls_log: list = field(default_factory=list)


# ---------------------------------------------------------------------------
class LLMRouter:
    def __init__(self, tools: ToolEngine):
        self.tools = tools
        self._clients: dict[str, object] = {}
        # Provider → unix-ts when they're allowed back. Set when a 4xx
        # comes back (auth / quota / credits). Auto-router skips
        # blocked providers so the user doesn't keep watching a
        # spinner caused by a dead key.
        self._blocklist: dict[str, float] = {}
        # Provider → human-readable reason for the block. Surfaces in
        # the model picker tooltip + the chat-side fallback toast so
        # the user knows WHY anthropic / openai is greyed out.
        self._block_reasons: dict[str, str] = {}
        # How long to keep a provider blocked after a hard failure.
        # Long enough that the user notices via Reality Check; short
        # enough that adding credits + waiting fixes it without a
        # restart.
        self._BLOCK_SECONDS = 600         # 10 minutes
        # Providers proven SIGNED-OUT / lacking valid auth this process.
        # DISTINCT from `_blocklist` (which is a TIME-BOXED 10-min cooldown
        # for transient 4xx). Founder bug 2026-06-20: claude_cli is on PATH
        # (so `configured_providers` counted it) but the subscription is
        # signed out, so EVERY turn picked it as PRIMARY, 401'd, and churned
        # a "switching provider…" toast. The 10-min blocklist expired and
        # re-churned. A signed-out subscription/CLI provider stays out of the
        # PRIMARY set until it actually authenticates again — no expiry-driven
        # re-churn. `_mark_signed_out` adds; a later SUCCESS on that provider
        # (`_clear_signed_out`, called from `complete`) removes it, so it
        # comes back automatically the moment the user re-signs-in — no app
        # restart, no founder action. We do NOT require claude_cli re-auth;
        # the router simply routes around it to a reachable provider
        # (archhub_cloud / metered API / Ollama).
        self._signed_out: set[str] = set()
        # Providers that have actually returned a successful completion THIS
        # process. Populated by `_clear_signed_out` (called on every success).
        # Used by `_route` to decide whether a local CLI is proven-working
        # this session: a signed-in-cloud user is routed to archhub_cloud
        # FIRST (the working free model) ahead of claude_cli / codex_cli —
        # UNLESS one of those CLIs has already proven it works this session,
        # in which case we don't regress that user. Founder bug 2026-06-23:
        # claude/codex installed but SIGNED OUT → claude 401s fast, codex
        # HANGS to the subprocess timeout before the router reaches the
        # working cloud model. Cloud-first-when-signed-in is the safe default;
        # a proven CLI stays first for the user whose CLI actually works.
        self._proven_ok: set[str] = set()
        # Providers that ERRORED at least once this process (any failure —
        # auth/quota/404/timeout/blocked). The cloud-first guard uses this to
        # prefer the working signed-in cloud over a keyed/CLI provider that has
        # already shown it is broken this session, WITHOUT demoting a fresh BYO
        # key that simply hasn't been exercised yet (founder #241 extended from
        # the CLIs to the keyed providers: broken anthropic/nvidia are not
        # re-tried ahead of cloud; a valid never-failed BYO key still leads).
        self._attempted_failed: set[str] = set()
        # MODELS proven uncallable this process — keyed by "provider:model".
        # A 404 'function not found / model does not exist' marks the SPECIFIC
        # model bad (not the whole provider — the key is fine, other models on
        # it still work). _route skips a bad model + substitutes the provider's
        # known-callable default, so the identical 404 is never repeated
        # (founder archhub.log: nvidia nemotron-253b NotFoundError loop).
        self._bad_models: set[str] = set()
        # REAL provider-reported token usage, accumulated across every
        # completion this process has run. Replaces the old client-side
        # chars/4 ESTIMATE the footer ServerStrip showed. Populated by
        # `_record_usage` from the usage{} block each provider returns
        # (Anthropic message.usage.input/output_tokens, OpenAI
        # chat.completion usage, Ollama prompt_eval_count/eval_count).
        # Stays at zero — honestly — until a real provider call lands,
        # so the footer shows nothing fabricated on a fresh box.
        self._token_usage: dict[str, object] = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "tokens": 0,            # prompt + completion (total)
            "cost": 0.0,            # real $ when the model's price is known
            "cost_known": False,    # False ⇒ omit cost honestly (no price)
            "model": "",            # last model that contributed real usage
            "completions": 0,       # number of real completions counted
        }

    # ---- credentials ------------------------------------------------------

    def has_credentials(self) -> bool:
        if list_keys():
            return True
        # Ollama needs no key
        try:
            from llm_providers.ollama_client import list_local_models
            if list_local_models():
                return True
        except Exception:
            pass
        return False

    def block_provider(self, provider: str, reason: str = "") -> None:
        """Mark a provider as unavailable for ~10 min. Called by client
        wrappers when they get a 4xx (auth / quota / credits / bad key)."""
        import time as _t
        self._blocklist[provider] = _t.time() + self._BLOCK_SECONDS
        # Distill the reason into a short human label so the picker
        # tooltip + fallback toast read cleanly.
        short = (reason or "").lower()
        if "credit" in short or "balance" in short:
            label = "out of credit"
        elif "quota" in short:
            label = "quota exceeded"
        elif "rate" in short and "limit" in short:
            label = "rate limited"
        elif ("401" in short or "403" in short or "auth" in short
              or "unauthorized" in short or "forbidden" in short
              or "log in" in short or "login" in short
              or "sign in" in short or "logged out" in short
              or "token" in short and "expir" in short
              or ("invalid" in short and "key" in short)):
            # Auth-class block (expired key / signed-out claude_cli / 401)
            # — distinct from a generic "blocked" so the picker tooltip +
            # fallback toast tell the user to re-auth, not just "blocked".
            label = "signed out / invalid key"
        else:
            label = "blocked"
        self._block_reasons[provider] = label
        print(f"[llm-router] {provider} BLOCKED for {self._BLOCK_SECONDS}s: {reason}", flush=True)
        try:
            from telemetry import track_event
            track_event("provider_blocked", provider=provider, reason=reason[:120])
        except Exception:
            pass

    def is_provider_blocked(self, provider: str) -> bool:
        import time as _t
        until = self._blocklist.get(provider)
        if until is None:
            return False
        if _t.time() >= until:
            self._blocklist.pop(provider, None)
            self._block_reasons.pop(provider, None)
            return False
        return True

    def block_reason(self, provider: str) -> str:
        """Human-readable label for why a provider is blocked, or ''
        if the provider isn't blocked. Read by the model picker tooltip
        + the chat fallback toast."""
        if not self.is_provider_blocked(provider):
            return ""
        return self._block_reasons.get(provider, "blocked")

    def blocked_providers(self) -> dict[str, str]:
        """Return {provider: reason_label} for every currently-blocked
        provider. Used by chat_window's model picker to surface the
        block in-line so users can see at a glance which keys need
        topping up."""
        out: dict[str, str] = {}
        for p in list(self._blocklist.keys()):
            r = self.block_reason(p)
            if r:
                out[p] = r
        return out

    # ---- signed-out / no-credential providers -----------------------------

    def _is_auth_error(self, provider: str, ex: Exception) -> bool:
        """True when `ex` from `provider` is an AUTH failure (signed out /
        bad key / 401-403 / expired token) — as opposed to quota, network,
        or a generic crash. Subscription/CLI providers also match their
        worded 'not authenticated / please log in' phrasings."""
        if provider in ("claude_cli", "codex_cli") and _claude_cli_is_auth(ex):
            return True
        s = (str(ex) or "").lower()
        auth_needles = (
            "401", "403", "unauthorized", "forbidden",
            "invalid api key", "invalid_api_key", "incorrect api key",
            "api key expired", "not authenticated", "unauthenticated",
            "please log in", "please login", "logged out", "not logged in",
            "sign in", "signed out", "session expired", "token has expired",
            "token expired", "permission_denied", "isn't signed in",
            # ArchHub Cloud 402 byo_key_required / no-managed-quota: the
            # managed tier can't serve this user until they add a key or
            # top up. Treat it like signed-out so the cloud is pre-skipped
            # as primary for the rest of the process and a local provider
            # takes over instead of re-trying the 402 every turn.
            "402", "payment required", "byo_key_required", "byo_key",
            "byo key", "bring your own key", "no managed quota",
        )
        return any(n in s for n in auth_needles)

    def _mark_signed_out(self, provider: str, reason: str = "") -> None:
        """Mark a provider as SIGNED-OUT for the rest of the process (until
        it authenticates again). Keeps it out of the PRIMARY set
        (`configured_providers`) so the auto-router never picks a dead
        subscription as primary turn-after-turn (the per-turn 'switching
        provider…' churn). Re-entry is automatic on the next SUCCESS via
        `_clear_signed_out` — no expiry, no restart, no founder action."""
        if not provider:
            return
        was = provider in self._signed_out
        self._signed_out.add(provider)
        if not was:
            print(f"[llm-router] {provider} SIGNED OUT — pre-skipped as "
                  f"primary until it re-authenticates: {reason[:120]}",
                  flush=True)

    def _mark_attempted_failed(self, provider: str) -> None:
        """Record that `provider` failed at least once this process. Used by
        the cloud-first guard to prefer the working cloud over a keyed/CLI
        provider that has already proven broken — never over a fresh BYO key."""
        if not provider:
            return
        try:
            self._attempted_failed.add(provider)
        except AttributeError:
            self._attempted_failed = {provider}

    def has_provider_failed(self, provider: str) -> bool:
        """True iff `provider` errored at least once this process."""
        return provider in getattr(self, "_attempted_failed", ())

    def _clear_signed_out(self, provider: str) -> None:
        """A SUCCESSFUL completion on `provider` proves it authenticated —
        clear any sticky signed-out flag so it returns to the primary set
        automatically (e.g. the user re-ran `claude login`)."""
        self._signed_out.discard(provider)
        # Record positively that this provider WORKED this session. _route
        # uses this to keep a proven-working local CLI ahead of the
        # cloud-first default (don't regress a user whose CLI actually works).
        try:
            self._proven_ok.add(provider)
        except AttributeError:
            # object.__new__-constructed router (bypassed __init__) — create
            # the set lazily so the positive signal still lands.
            self._proven_ok = {provider}

    def is_provider_proven_ok(self, provider: str) -> bool:
        """True iff `provider` returned a successful completion this process."""
        return provider in getattr(self, "_proven_ok", ())

    def _mark_model_bad(self, provider: str, model_name: str,
                        reason: str = "") -> None:
        """Mark a SPECIFIC model uncallable for the rest of the process. The
        provider stays usable (its key is fine) — only this model is skipped
        from now on, so the same 404 'function not found' is never repeated."""
        key = f"{provider}:{model_name}"
        try:
            bad = self._bad_models
        except AttributeError:
            bad = self._bad_models = set()
        if key not in bad:
            bad.add(key)
            print(f"[llm-router] model {key} UNCALLABLE — skipped for this "
                  f"session: {reason[:120]}", flush=True)

    def is_model_bad(self, provider: str, model_name: str) -> bool:
        """True iff this exact provider:model was proven uncallable (404
        function-not-found / model-does-not-exist) this process."""
        return f"{provider}:{model_name}" in getattr(self, "_bad_models", ())

    def is_provider_signed_out(self, provider: str) -> bool:
        # getattr-guarded: configured_providers() is reached from many entry
        # points, and some construct LLMRouter via object.__new__ (bypassing
        # __init__) — a missing set just means 'nothing signed out yet'.
        return provider in getattr(self, "_signed_out", ())

    # ---- real token accounting --------------------------------------------

    def _record_usage(self, provider: str, model_name: str,
                       usage: Optional[dict]) -> None:
        """Fold one completion's REAL provider-reported usage into the
        running total. `usage` is the {prompt_tokens, completion_tokens}
        block the provider client returns — None / empty means the
        provider didn't report it (local model, older path); we then add
        nothing rather than guess. Cost is only added when the model's
        real price is known; otherwise cost_known stays False so the UI
        omits a dollar figure instead of fabricating one."""
        if not usage:
            return
        try:
            pt = int(usage.get("prompt_tokens") or 0)
            ct = int(usage.get("completion_tokens") or 0)
        except (TypeError, ValueError):
            return
        if pt <= 0 and ct <= 0:
            return
        acc = self._token_usage
        acc["prompt_tokens"] = int(acc["prompt_tokens"]) + pt
        acc["completion_tokens"] = int(acc["completion_tokens"]) + ct
        acc["tokens"] = int(acc["prompt_tokens"]) + int(acc["completion_tokens"])
        acc["completions"] = int(acc["completions"]) + 1
        acc["model"] = f"{provider}:{model_name}"
        price = _price_for_model(model_name)
        if price is not None:
            in_per_m, out_per_m = price
            acc["cost"] = float(acc["cost"]) + (
                pt * in_per_m / 1e6 + ct * out_per_m / 1e6
            )
            acc["cost_known"] = True

    def get_token_usage(self) -> dict:
        """REAL accumulated provider usage for this process. Read by the
        bridge `get_token_usage` slot → footer ServerStrip. Returns a copy
        so callers can't mutate the accumulator. tokens==0 until a real
        completion lands (honest empty state). `cost` is only meaningful
        when `cost_known` is True (a metered model with a known price
        contributed); for local/subscription models cost_known is False
        and the UI shows tokens only."""
        acc = self._token_usage
        return {
            "prompt_tokens": int(acc["prompt_tokens"]),
            "completion_tokens": int(acc["completion_tokens"]),
            "tokens": int(acc["tokens"]),
            "cost": round(float(acc["cost"]), 6),
            "cost_known": bool(acc["cost_known"]),
            "model": acc["model"],
            "completions": int(acc["completions"]),
        }

    def configured_providers_cheap(self) -> list[str]:
        """The configured-provider set WITHOUT any network probe — safe to
        call ON the Qt main thread (e.g. building the model picker at boot).

        APP-01 residual boot-hang: `configured_providers()` reaches
        `llm_detector.probe_lmstudio`, an HTTP GET that pays the full
        ~1.5 s `urlopen` timeout on a HALF-OPEN LM Studio port. The Qt
        model picker (`chat_window._populate_model_picker`) is built INLINE
        in `ChatWindow.__init__` on the GUI thread at launch, so that stall
        froze the app on boot. This variant skips ONLY the LM Studio HTTP
        probe — every other signal (key/env/CLI presence, Ollama's
        already-non-blocking cached list) is cheap. The live `lmstudio`
        row is filled in moments later by the background refresh
        (`_kick_model_picker_probe` → `_model_picker_ready`)."""
        return self.configured_providers(_probe_lmstudio=False)

    def configured_providers(self, *, _probe_lmstudio: bool = True) -> list[str]:
        # `list_keys()` returns providers with an entry in the secrets
        # store — including ones whose value is empty (a placeholder
        # row left over from a half-completed Sign-ins flow). That made
        # the model picker show e.g. anthropic / openai / google as
        # "live" even when the actual key string was 0 chars, which
        # caused chats to hang on send. Filter through `load_api_key`
        # so only providers with a NON-EMPTY key count as configured.
        #
        # `_probe_lmstudio=False` (configured_providers_cheap) skips the one
        # blocking call below so the result is safe on the Qt main thread.
        providers = set()
        for p in list_keys():
            try:
                k = load_api_key(p) or ""
                if k.strip():
                    providers.add(p)
            except Exception:
                continue
        # Add env-var detected providers
        import os
        env_map = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY",
                   "google": "GOOGLE_API_KEY", "openrouter": "OPENROUTER_API_KEY",
                   "nvidia": "NVIDIA_API_KEY"}
        for p, env in env_map.items():
            if (os.environ.get(env) or "").strip():
                providers.add(p)
        # Custom OpenAI-compatible relay (firm path) is "configured" when both
        # the URL setting and the relay key are present.
        try:
            # load_api_key already imported at module scope; only
            # load_setting needs to come in locally.
            from secrets_store import load_setting
            if load_setting("relay_base_url") and load_api_key("relay"):
                providers.add("relay")
        except Exception:
            pass
        # ArchHub Cloud (managed paid tier) — configured when the
        # bearer token is persisted. Token storage handled by
        # cloud_client.set_token() after a successful sign-in.
        try:
            from cloud_client import is_signed_in as _cloud_signed_in
            if _cloud_signed_in():
                providers.add("archhub_cloud")
        except Exception:
            pass
        # Ollama if running
        try:
            from llm_providers.ollama_client import list_local_models
            if list_local_models():
                providers.add("ollama")
        except Exception:
            pass
        # Claude Code CLI — the installed `claude` binary. Runs on the
        # user's Claude subscription (no API key, no metered credit), so
        # it's "configured" whenever the binary is on PATH.
        try:
            from llm_providers.claude_cli_client import claude_cli_path
            if claude_cli_path():
                providers.add("claude_cli")
        except Exception:
            pass
        # Codex CLI — the installed `codex` binary. Runs on the user's
        # ChatGPT/Codex subscription (no API key, no metered quota).
        try:
            from llm_providers.codex_cli_client import codex_cli_path
            if codex_cli_path():
                providers.add("codex_cli")
        except Exception:
            pass
        # LM Studio if running with at least one chat model loaded.
        # Server lives at 127.0.0.1:1234/v1; probe is cached 25s.
        # This is the ONE blocking (HTTP) signal — skipped when the caller
        # asked for the cheap, Qt-main-thread-safe set (APP-01 boot-hang).
        if _probe_lmstudio:
            try:
                from llm_detector import probe_lmstudio
                res = probe_lmstudio() or {}
                if res.get("status") == "live" and res.get("models"):
                    providers.add("lmstudio")
            except Exception:
                pass
        # Drop providers we've blocked due to recent 4xx (no credits,
        # bad key, quota exceeded). They re-enter the set automatically
        # when the blocklist entry expires (~10 min).
        #
        # ALSO drop providers proven SIGNED-OUT this process (e.g.
        # claude_cli on PATH but the subscription is logged out). A
        # signed-out provider must NOT be chosen as PRIMARY — that is the
        # founder bug where every turn tried claude_cli, 401'd, and churned
        # a 'switching provider…' toast. It re-enters automatically on the
        # next successful completion (`_clear_signed_out`).
        return sorted(p for p in providers
                      if not self.is_provider_blocked(p)
                      and not self.is_provider_signed_out(p))

    def _get_client(self, provider: str):
        if provider in self._clients:
            return self._clients[provider]
        # Ollama runs locally — no API key needed
        if provider == "ollama":
            from llm_providers.ollama_client import OllamaClient
            self._clients[provider] = OllamaClient()
            return self._clients[provider]
        # Claude Code CLI — runs on the user's Claude SUBSCRIPTION via
        # `claude -p`. No ANTHROPIC_API_KEY, no per-token credit: it
        # keeps working when the API key is out of credit. Local binary,
        # so short-circuit the api-key gate like ollama.
        if provider == "claude_cli":
            from llm_providers.claude_cli_client import ClaudeCliClient
            self._clients[provider] = ClaudeCliClient()
            return self._clients[provider]
        # Codex CLI — runs on the user's ChatGPT/Codex SUBSCRIPTION via
        # `codex exec`. No OPENAI_API_KEY, no per-token quota. Local
        # binary — short-circuit the api-key gate like claude_cli.
        if provider == "codex_cli":
            from llm_providers.codex_cli_client import CodexCliClient
            self._clients[provider] = CodexCliClient()
            return self._clients[provider]
        # LM Studio also runs locally with no auth by default; built
        # below by reusing CustomOpenAICompatibleClient. Short-circuit
        # the api-key gate so the user doesn't get "No API key
        # configured for lmstudio" when picking a local model.
        if provider == "lmstudio":
            from llm_providers.openrouter_client import CustomOpenAICompatibleClient
            # CRITICAL: do NOT re-import load_api_key here. It's already at
            # module scope (line 24). Re-importing inside the function makes
            # Python treat load_api_key as a function-local for the WHOLE
            # function — so line 641's `api_key = load_api_key(provider)`
            # (executed when provider != 'lmstudio') raises
            # UnboundLocalError. Every chat call dies. Founder bug
            # 2026-05-14: chats hang at "..." with no streaming response.
            from secrets_store import load_setting
            base = (load_setting("lmstudio_base_url")
                    or "http://127.0.0.1:1234/v1").rstrip("/")
            key = load_api_key("lmstudio") or "lm-studio"
            self._clients[provider] = CustomOpenAICompatibleClient(
                api_key=key, base_url=base,
            )
            return self._clients[provider]
        # ArchHub Cloud uses a bearer token via cloud_client, not the
        # provider-key store. Short-circuit before the api_key gate.
        if provider == "archhub_cloud":
            from cloud_client import current_token
            from llm_providers.archhub_cloud_client import ArchHubCloudClient
            tok = current_token()
            if not tok:
                raise RuntimeError(
                    "ArchHub Cloud isn't signed in. Open Settings → "
                    "ArchHub Cloud to sign in."
                )
            self._clients[provider] = ArchHubCloudClient(token=tok)
            return self._clients[provider]
        # NVIDIA NIM — OpenAI-compatible cloud endpoint. Short-circuit the
        # generic api-key gate (like lmstudio/archhub_cloud) so the key can
        # come from the store OR the NVIDIA_API_KEY env var, and a missing key
        # yields the NVIDIA-specific guidance instead of the generic message.
        # (load_api_key stays module-level — do NOT re-import it; see lmstudio.)
        if provider == "nvidia":
            from llm_providers.openrouter_client import CustomOpenAICompatibleClient
            import os as _os
            nv_key = ((load_api_key("nvidia") or "").strip()
                      or (_os.environ.get("NVIDIA_API_KEY") or "").strip())
            if not nv_key:
                raise RuntimeError(
                    "NVIDIA is selected but no key is configured. Save an "
                    "'nvidia' key in Settings → Keys & Secrets or set "
                    "NVIDIA_API_KEY (free keys at build.nvidia.com).")
            self._clients[provider] = CustomOpenAICompatibleClient(
                api_key=nv_key, base_url="https://integrate.api.nvidia.com/v1")
            return self._clients[provider]
        api_key = load_api_key(provider)
        if not api_key:
            raise RuntimeError(f"No API key configured for {provider}. Add one in Settings.")

        if provider == "anthropic":
            from llm_providers.anthropic_client import AnthropicClient
            self._clients[provider] = AnthropicClient(api_key)
        elif provider == "openai":
            from llm_providers.openai_client import OpenAIClient
            self._clients[provider] = OpenAIClient(api_key)
        elif provider == "google":
            from llm_providers.google_client import GoogleClient
            self._clients[provider] = GoogleClient(api_key)
        elif provider == "openrouter":
            from llm_providers.openrouter_client import OpenRouterClient
            self._clients[provider] = OpenRouterClient(api_key)
        elif provider == "relay":
            from llm_providers.openrouter_client import CustomOpenAICompatibleClient
            # Don't re-import load_api_key here — it's already at
            # module scope. Re-importing inside this branch made the
            # whole function treat load_api_key as a local, which
            # made line 127 (the very first use of the module-level
            # name) raise UnboundLocalError. load_setting only is
            # safe to import locally.
            from secrets_store import load_setting
            base_url = load_setting("relay_base_url") or ""
            relay_key = load_api_key("relay") or ""
            if not base_url or not relay_key:
                raise RuntimeError(
                    "Custom relay is selected but base URL or token is missing. "
                    "Open Settings to configure it."
                )
            self._clients[provider] = CustomOpenAICompatibleClient(
                api_key=relay_key, base_url=base_url
            )
        # archhub_cloud handled by short-circuit above (no api_key gate).
        # ollama + lmstudio short-circuit at the top of this function so
        # they don't hit the api_key gate.
        else:
            raise RuntimeError(f"Unknown provider: {provider}")
        return self._clients[provider]

    # ---- routing ----------------------------------------------------------

    # Preference order per task class. The first model present in the
    # local Ollama install wins. v1.0 retuning notes:
    #
    # - Tool-use reliability beats code quality. A coder model that
    #   writes beautiful Revit C# but dumps it into chat instead of
    #   the execute_csharp tool is USELESS — violates rule #1. So
    #   instruction-tuned models go first in every action chain.
    # - command-r7b (Cohere) is purpose-trained for tool calling +
    #   structured output. Underrated for AEC — wins the modeling
    #   chain when present.
    # - llama3.1:8b has the most reliable tool-calling among general
    #   8B-class open models. Safe default everywhere.
    # - deepseek-r1 / qwen3-think / any *-r1 / *-think model: REMOVED
    #   from action chains. They emit <think>...</think> blocks for
    #   1000+ tokens before acting. The user reads this as
    #   "procrastinating" and gives up. Kept in `reasoning` only,
    #   reserved for explicit /think slash commands.
    # - qwen2.5-coder: kept as a LATE fallback for modeling because
    #   it does write the cleanest API code, but only if no
    #   instruction-tuned alternative is present.
    # - gemma4:latest: REMOVED (typo; doesn't exist on Ollama Hub).
    #   Replaced with gemma3 + gemma2 which actually do.
    _OLLAMA_MODEL_PREFERENCES = {
        "modeling": (
            # Tool-trained, then strong general instruct, coder as fallback.
            "command-r7b:latest", "command-r:latest",
            "llama3.1:8b", "llama3.1:latest", "llama3.1",
            "qwen3.5:latest", "qwen3:8b",
            "qwen2.5:7b-instruct", "qwen2.5-coder:7b", "qwen2.5-coder",
        ),
        "analysis": (
            # Same priority — analysis often still ends in a tool call.
            "command-r7b:latest", "command-r:latest",
            "llama3.1:8b", "llama3.1:latest", "llama3.1",
            "qwen3.5:latest", "qwen3:8b",
        ),
        "reasoning": (
            # Explicit reasoning path — only used when the user opts in
            # via /think slash or a Skill that needs chain-of-thought.
            "deepseek-r1:8b", "qwen3-think:8b",
            "llama3.1:8b", "llama3.1:latest",
        ),
        "vision": (
            "qwen3-vl:8b", "llama3.2-vision:latest",
            "llama3.2:latest", "llama3.1:latest",
        ),
        "quick": (
            "llama3.2:3b", "llama3.2:latest",
            "gemma3:latest", "gemma2:latest",
            "llama3.1:8b", "llama3.1:latest",
        ),
        "default": (
            "command-r7b:latest",
            "llama3.1:8b", "llama3.1:latest", "llama3.1",
            "qwen3.5:latest", "qwen3:8b",
            "qwen2.5-coder:7b",
        ),
    }

    def _pick_ollama_model(self, task: str) -> Optional[str]:
        try:
            from llm_providers.ollama_client import list_local_models
            local = list_local_models()
        except Exception:
            return None
        if not local:
            return None
        local_set = set(local)
        for candidate in self._OLLAMA_MODEL_PREFERENCES.get(task, ()):
            if candidate in local_set:
                return candidate
        # No preferred model available — fall back to whatever was first.
        return local[0]

    # Local, no-credential providers in PREFERENCE order. These run on the
    # user's own machine / subscription — no BYO key, no metered cloud quota,
    # so they are the right answer whenever a cloud key is missing or
    # byo-blocked. claude_cli first (tool-capable via the ArchHub MCP
    # server), then codex_cli, then a running Ollama, then LM Studio.
    _LOCAL_PROVIDERS = ("claude_cli", "codex_cli", "ollama", "lmstudio")

    def _first_available_local(self, configured: set) -> Optional[tuple[str, str, str]]:
        """Return (provider, model, note) for the highest-preference LOCAL
        provider present in `configured`, or None if none are available.
        This is the LOCAL-FIRST unblocker: when there is no usable BYO key
        (every cloud provider is missing / blocked / byo-key-required) we
        PREFER an available local provider instead of leaving the user with
        a 402 and an empty bubble. ollama/lmstudio resolve a concrete model;
        the CLIs take an alias the client maps."""
        for p in self._LOCAL_PROVIDERS:
            if p not in configured:
                continue
            if p == "claude_cli":
                return ("claude_cli", "sonnet",
                        "local Claude Code · subscription · no API credit")
            if p == "codex_cli":
                return ("codex_cli", "auto",
                        "local Codex CLI · subscription · no API quota")
            if p == "ollama":
                m = self._pick_ollama_model("default")
                if m:
                    return ("ollama", m, f"local Ollama {m} · no API credit")
                # Ollama running but no model resolved — skip to next local.
                continue
            if p == "lmstudio":
                return ("lmstudio", "auto", "local LM Studio · no API credit")
        return None

    def _route(self, history: list[dict], requested_model: str) -> tuple[str, str, str]:
        """Return (provider, model_name, note)."""
        if requested_model and requested_model != ROUTE_AUTO:
            provider, _, model = requested_model.partition(":")
            # LOCAL-FIRST GUARD (founder 2026-06-22 'composer gives nothing
            # back'): an explicit pick is honoured AS LONG AS the provider is
            # not already PROVEN unusable this session. The 402 dead-end was:
            # a managed-cloud pick (archhub_cloud / relay) that has no managed
            # quota / is byo-key-required answers a turn with HTTP 402 and the
            # turn never fell through to a local provider. Once such a cloud
            # 402s it is marked signed-out / blocked; on the NEXT turn the
            # explicit pick still pointed straight back at it. So: when the
            # named provider is BLOCKED or SIGNED-OUT, redirect to the first
            # available local provider (claude_cli / codex / ollama / lmstudio)
            # if there is one, else fall through to the auto heuristics (which
            # also prefer local). A provider that is merely not-yet-probed but
            # not proven-dead is still honoured verbatim (unchanged behaviour
            # for a normal model-picker selection).
            _dead = (self.is_provider_blocked(provider)
                     or self.is_provider_signed_out(provider))
            if _dead:
                try:
                    configured = set(self.configured_providers())
                except Exception:
                    configured = set()
                local = self._first_available_local(configured)
                if local is not None:
                    prov, mdl, _note = local
                    return (prov, mdl, f"{provider} unavailable → {_note}")
                # No local available — fall through to auto routing so the
                # cloud-fallback chain (and its honest error) takes over
                # rather than dead-ending on the proven-dead explicit pick.
            else:
                # NVIDIA MODEL RESOLUTION (founder archhub.log 404 loop): a
                # `nvidia:` pick with no model, an `auto`, OR a model already
                # proven uncallable this session (404 function-not-found) is
                # substituted with the known-callable default so the desktop
                # never (re-)issues the identical 404. A normal nvidia pick of
                # a good model is honoured verbatim.
                if provider == "nvidia":
                    if (not model or model == ROUTE_AUTO
                            or self.is_model_bad(provider, model)):
                        note = ("nvidia default" if (not model
                                or model == ROUTE_AUTO)
                                else f"nvidia {model} uncallable → default")
                        return (provider, NVIDIA_DEFAULT_MODEL, note)
                return provider, model, ""

        # Auto-routing heuristics
        last_user_msg = next(
            (m for m in reversed(history) if m.get("role") == "user"), {}
        )
        last_user = last_user_msg.get("content", "") if last_user_msg else ""
        has_images = bool(last_user_msg.get("images") if last_user_msg else False)
        text = (last_user or "").lower()

        configured_for_vision = set(self.configured_providers())

        # Vision: if an image was attached, force a multimodal-capable model
        # before falling through to the keyword heuristics. Claude (Sonnet/Opus
        # 4.x), GPT-4o, Gemini 1.5+ and OpenRouter routes to any of those all
        # accept image_url / image content blocks.
        if has_images:
            if "anthropic" in configured_for_vision:
                return "anthropic", "claude-sonnet-4-6", "vision · Claude Sonnet 4.6"
            if "openrouter" in configured_for_vision:
                return ("openrouter", "anthropic/claude-opus-4",
                        "auto: vision → OpenRouter · Claude Opus 4")
            if "openai" in configured_for_vision:
                return "openai", "gpt-4o", "auto: vision → GPT-4o"
            if "google" in configured_for_vision:
                return "google", "gemini-2.5-pro", "auto: vision → Gemini 2.5 Pro"
            # Fall through to text-only routing if no vision provider available;
            # the provider client will simply ignore the image blocks.

        # ── Local Claude Code — the preferred provider for every
        # non-vision turn. Founder demand 2026-05-16: route through the
        # installed `claude` CLI, which runs on the user's Claude
        # SUBSCRIPTION (no ANTHROPIC_API_KEY, no per-token credit) and
        # is fully tool-capable via the ArchHub MCP server. Metered API
        # providers below become the FALLBACK — used only for vision,
        # or when the local CLI fails. (Vision is handled above; `claude
        # -p` headless can't take image attachments here.)
        configured = set(self.configured_providers())
        # ── SIGNED-IN CLOUD GOES FIRST (founder bug 2026-06-23: "first AI
        # call is slow"). The founder has the `claude` + `codex` CLIs
        # installed but SIGNED OUT. claude_cli 401s fast, but codex_cli HANGS
        # to its subprocess timeout — and BOTH used to be tried as PRIMARY
        # before anything else, so the user's FIRST turn stalled before the
        # router ever reached the working archhub_cloud free model.
        #
        # When ArchHub Cloud is signed in (in `configured`) AND the caller did
        # not explicitly choose a provider (we are in auto routing — the
        # explicit-pick branch returned above) AND a local CLI IS installed but
        # has NOT PROVEN it works this session, prefer archhub_cloud AHEAD of
        # that CLI so the first call hits the working free model fast and clean.
        #
        # The guard is SCOPED to "a CLI would otherwise be tried first": it
        # fires ONLY when an unproven claude_cli / codex_cli is configured.
        # That keeps it surgical — it reorders cloud vs the CLIs ONLY, and
        # never demotes a BYO key or a local Ollama/LM Studio (those are
        # resolved by the heuristic priority lists below and are reached
        # unchanged whenever no CLI is in the way). So:
        #   • CLI installed + signed out/hung  → cloud first (the fix).
        #   • CLI proven-working this session   → CLI stays first (no regress).
        #   • No CLI installed                  → guard skipped → BYO/local
        #                                         priority lists run as before.
        #   • Signed-out-everything             → archhub_cloud not configured,
        #                                         guard skipped, honest no-LLM.
        _cli_installed = ("claude_cli" in configured
                          or "codex_cli" in configured)
        _cli_proven = (self.is_provider_proven_ok("claude_cli")
                       or self.is_provider_proven_ok("codex_cli"))
        if ("archhub_cloud" in configured and _cli_installed
                and not _cli_proven):
            return ("archhub_cloud", "auto",
                    "auto: ArchHub Cloud · signed-in · free model")
        # ── #241 EXTENDED TO KEYED PROVIDERS (founder archhub.log: broken
        # anthropic 401 + nvidia 404 re-tried ahead of the working cloud).
        # When signed in to cloud + auto + every NON-cloud provider that the
        # heuristics below would otherwise pick first has ALREADY FAILED this
        # session and is NOT proven-working, prefer archhub_cloud rather than
        # churning a known-broken keyed/CLI/local provider again. A keyed
        # provider that simply hasn't been exercised yet (a fresh BYO key) is
        # NOT demoted — `has_provider_failed` is False for it, so it still
        # leads via the priority lists below (test C BYO/local-beats-cloud
        # stays green). A provider proven-working this session also leads.
        if "archhub_cloud" in configured:
            _non_cloud = [p for p in configured if p != "archhub_cloud"]
            if _non_cloud and all(
                    (self.has_provider_failed(p)
                     and not self.is_provider_proven_ok(p))
                    for p in _non_cloud):
                return ("archhub_cloud", "auto",
                        "auto: ArchHub Cloud · signed-in · free model "
                        "(local providers broken this session)")
        # Free local subscriptions first — claude_cli preferred (it is
        # tool-capable via the ArchHub MCP server), codex_cli next.
        # Either one missing from `configured` means it's blocked after
        # a recent failure — routing then falls through to the metered
        # API providers below. (When cloud is signed in this is reached only
        # for a CLI that PROVED it works this session — see the cloud-first
        # guard above — so a working-CLI user is not regressed.)
        if "claude_cli" in configured:
            return ("claude_cli", "sonnet",
                    "local Claude Code · subscription · no API credit")
        if "codex_cli" in configured:
            return ("codex_cli", "auto",
                    "local Codex CLI · subscription · no API quota")

        modeling_signals = (
            "revit", "autocad", "3ds max", "blender", "model", "wall", "door",
            "window", "geometry", "extrude", "render", "ifc", "rvt", "dwg",
            "create", "make", "build", "add", "draw", "place", "dimension",
        )
        analysis_signals = (
            "schedule", "quantity", "takeoff", "compare", "audit", "report",
            "explain", "why", "analyze", "speckle",
        )
        quick_signals = ("hi", "hello", "thanks", "thank you")

        # `configured` already computed above (claude_cli check).

        # Image present in the last message? Use multimodal.
        # (Future: detect QImage attachments. For now, look for "look at this" etc.)
        if any(s in text for s in modeling_signals):
            if "anthropic" in configured:
                return "anthropic", "claude-sonnet-4-6", "Claude Sonnet 4.6 (fast)"
            if "openrouter" in configured:
                return "openrouter", "anthropic/claude-sonnet-4", "OpenRouter · Claude Sonnet 4"
            if "openai" in configured:
                return "openai", "gpt-4o", "auto: modeling task → GPT-4o (Anthropic unavailable)"
            if "google" in configured:
                return "google", "gemini-2.5-flash", "auto: modeling → Gemini 2.5 Flash (free tier)"
            if "relay" in configured:
                return "relay", "auto", "auto: modeling task → firm relay"
            if "archhub_cloud" in configured:
                return "archhub_cloud", "auto", "auto: modeling task → ArchHub Cloud"
            if "ollama" in configured:
                m = self._pick_ollama_model("modeling")
                if m:
                    return "ollama", m, f"auto: modeling task → local Ollama {m}"

        if any(s in text for s in analysis_signals):
            if "anthropic" in configured:
                return "anthropic", "claude-sonnet-4-6", "auto: analysis → Claude Sonnet 4.6"
            if "openrouter" in configured:
                return "openrouter", "anthropic/claude-sonnet-4", "auto: analysis → OpenRouter · Claude Sonnet 4"
            if "openai" in configured:
                return "openai", "gpt-4o", "auto: analysis → GPT-4o"
            if "google" in configured:
                return "google", "gemini-2.5-flash", "auto: analysis → Gemini 2.5 Flash"
            if "relay" in configured:
                return "relay", "auto", "auto: analysis → firm relay"
            if "archhub_cloud" in configured:
                return "archhub_cloud", "auto", "auto: analysis → ArchHub Cloud"
            if "ollama" in configured:
                m = self._pick_ollama_model("analysis")
                if m:
                    return "ollama", m, f"auto: analysis → local Ollama {m}"

        if any(s in text for s in quick_signals) or len(text) < 24:
            # Short / chatty turns never need host tools — route them to
            # local Claude Code first: runs on the user's subscription,
            # zero API credit. Founder demand 2026-05-16.
            if "claude_cli" in configured:
                return ("claude_cli", "haiku",
                        "auto: short → local Claude Code · no API credit")
            if "anthropic" in configured:
                return "anthropic", "claude-haiku-4-5-20251001", "auto: short → Claude Haiku"
            if "openrouter" in configured:
                return "openrouter", "google/gemini-2.5-flash", "auto: short → OpenRouter · Gemini 2.5 Flash"
            if "openai" in configured:
                return "openai", "gpt-4o-mini", "auto: short → GPT-4o mini"
            if "google" in configured:
                return "google", "gemini-2.5-flash", "auto: short → Gemini 2.5 Flash"
            if "archhub_cloud" in configured:
                return "archhub_cloud", "auto", "auto: short → ArchHub Cloud"
            if "ollama" in configured:
                m = self._pick_ollama_model("quick")
                if m:
                    return "ollama", m, f"auto: short → local Ollama {m}"

        # Default. Direct BYO keys (anthropic/openai/google/openrouter) are
        # user-configured + immediately usable, so they lead. But the MANAGED
        # cloud paths (relay / archhub_cloud) are the 402 source — when the
        # user has no managed quota / hasn't pasted a key, archhub_cloud
        # answers a turn with HTTP 402 byo_key_required. So a running LOCAL
        # provider (ollama / lmstudio) is preferred OVER those managed-cloud
        # fallbacks: better a real local reply than a 402 round-trip.
        if "anthropic" in configured:
            return "anthropic", "claude-sonnet-4-6", "auto: default → Claude Sonnet 4.6"
        if "openrouter" in configured:
            return "openrouter", "anthropic/claude-sonnet-4", "auto: default → OpenRouter · Claude Sonnet 4"
        if "openai" in configured:
            return "openai", "gpt-4o", "auto: default → GPT-4o"
        if "google" in configured:
            return "google", "gemini-2.5-pro", "auto: default → Gemini 2.5 Pro"
        # Local before managed-cloud (avoid the 402 when a local model exists).
        if "ollama" in configured:
            m = self._pick_ollama_model("default")
            if m:
                return "ollama", m, f"auto: default → local Ollama {m}"
        if "lmstudio" in configured:
            return "lmstudio", "auto", "auto: default → local LM Studio"
        if "relay" in configured:
            return "relay", "auto", "auto: default → firm relay"
        if "archhub_cloud" in configured:
            return "archhub_cloud", "auto", "auto: default → ArchHub Cloud"
        # Last resort before giving up: local Claude Code on the user's
        # subscription. Reachable whenever the `claude` binary exists —
        # so a credit-exhausted API never leaves the user with nothing.
        if "claude_cli" in configured:
            return ("claude_cli", "sonnet",
                    "auto: local Claude Code · no API credit")

        raise RuntimeError("No LLM configured. Add an API key in Settings, sign in to ArchHub Cloud, or start Ollama.")

    # ---- complete (tool-use loop) -----------------------------------------

    def complete(
        self,
        history: list[dict],
        model: str,
        on_chunk: Optional[Callable[[str], None]] = None,
        on_tool_invocation: Optional[Callable[[ToolInvocation], None]] = None,
        on_reasoning: Optional[Callable[[str], None]] = None,
        on_status: Optional[Callable[[str], None]] = None,
        on_attempt_reset: Optional[Callable[[str], None]] = None,
        session_pin: Optional[str] = None,
        system_override: Optional[str] = None,
        extra_tools: Optional[list[dict]] = None,
        tool_schemas: Optional[list[dict]] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        allowed_tool_names: Optional[set] = None,
    ) -> LLMResponse:
        """session_pin — optional `@token` parsed out of the user's chat
        message (e.g. `@Tower-A`, `@Pavilion`, `@25232`). Forwarded to
        every tool invocation in this turn so multi-instance hosts (Revit
        × N, Max × N, Outlook accounts) bind to the chosen session
        instead of falling back to the most-recent.

        system_override — when set, REPLACES the router's built-in
        assistant system prompt for this call and suppresses the tool
        surface. This is the supported mechanism for specialised
        one-shot calls (e.g. Node Smith's JSON-spec generation) that
        need their own instructions and must NOT be steered by the
        chat-assistant prompt or tempted into tool calls. Previously
        callers faked this with a `role:"system_override"` history
        message — a role the provider clients silently dropped, so the
        specialised instructions never reached the model.

        extra_tools — caller-supplied, CLIENT-SIDE tool schemas (each in
        Anthropic `{name, description, input_schema}` shape) MERGED into
        the provider tool surface for THIS call only. Use this when the
        caller — not the ToolEngine — owns the tools' execution. The
        Composer agent passes its canvas primitives (spawn_node /
        add_wire / set_node_param / run_node / run_workflow / query_graph
        / chat) here so the LLM can actually see + call them. When the
        model invokes one of these, the router does NOT dispatch it to
        ToolEngine.invoke (which would 'Unknown tool' it); instead it
        records the invocation, fires `on_tool_invocation` so the caller
        collects the action, and feeds a neutral acknowledgement back to
        the model so the tool-use loop continues. The caller replays the
        collected invocations against its own surface (the canvas).

        tool_schemas — back-compat alias for `extra_tools`. The Composer
        originally called `complete(..., tool_schemas=TOOL_SCHEMA)`
        against a signature that never accepted it, so the call raised
        TypeError and silently fell back to a tool-LESS path (the LLM
        never saw the canvas tools — the dead-orchestration bug). Both
        names are accepted now; they merge identically.

        temperature / max_tokens — OPTIONAL sampling params forwarded to
        the provider request for this call. node.config carries these for
        a Conversation node (config_schema declares temperature default
        0.7, max_tokens default 4096) and the UI exposes them, but they
        were never wired through to the provider — the model always ran at
        the client's hardcoded defaults. When None (the chat default) the
        provider keeps its own default; when set they override it.
        Best-effort + back-compat: providers whose stream_completion can't
        accept them silently keep their defaults (see _complete_once).

        allowed_tool_names — OPTIONAL whitelist of ToolEngine tool names.
        When set, the ToolEngine tool surface for THIS call is filtered to
        just these names (client-side extra_tools are unaffected). This is
        the supported, THREAD-SAFE way for the workflow `llm.complete_with_tools`
        node to restrict tools: previously it MUTATED the shared
        ctx.tool_engine.tool_schemas_for, corrupting any concurrent chat /
        workflow turn that shared the same ToolEngine. The filter is now a
        per-call local copy — no shared state is touched. None ⇒ full
        surface (the chat default, unchanged).

        on_attempt_reset — OPTIONAL callback fired with the failed
        provider's name the instant the auto-fallback chain abandons an
        attempt and is about to stream a DIFFERENT provider (auth/quota
        block, refusal re-route, or fabricated-tool re-route). It is the
        ROUTER OUTPUT HYGIENE hook: the caller buffers each attempt's
        on_chunk text and, on this signal, DROPS the half-streamed text
        of the loser so the user only ever sees the WINNING provider's
        message — never a failed provider's truncated half-reply
        concatenated in front of the real answer (founder bug: 'router
        not working' — it routed fine but LEAKED). Fires once per
        abandoned attempt; never fires for the attempt that ultimately
        returns. None ⇒ no-op (back-compat)."""
        on_chunk = on_chunk or (lambda _: None)
        on_tool_invocation = on_tool_invocation or (lambda _: None)
        on_reasoning = on_reasoning or (lambda _: None)
        on_status = on_status or (lambda _: None)
        on_attempt_reset = on_attempt_reset or (lambda _: None)
        # Merge the two accepted spellings into one list. Either may be
        # None (the common case — no client-side tools). Order: explicit
        # extra_tools first, then the alias, de-duped by tool name so a
        # caller passing both never double-registers.
        _merged_extra: list[dict] = []
        _seen_extra: set = set()
        for _src in (extra_tools or [], tool_schemas or []):
            for _t in _src:
                _nm = (_t or {}).get("name")
                if _nm and _nm not in _seen_extra:
                    _seen_extra.add(_nm)
                    _merged_extra.append(_t)
        extra_tools = _merged_extra

        # Soft-route guard: when `auto` is requested but no provider is
        # configured (clean install with no key + no Ollama / Cloud), the
        # _route helper raises RuntimeError. v1.5 requirement: return a
        # neutral LLMResponse instead so the workflow runner + chat
        # bridge can render a clean "(no provider configured)" message
        # rather than hanging or crashing.
        if (not model or model == ROUTE_AUTO):
            try:
                _probe = self.configured_providers()
            except Exception:
                _probe = []
            if not _probe:
                return LLMResponse(
                    text="",
                    model="(no provider configured)",
                    tool_invocations=[],
                    routing_note=(
                        "no LLM provider configured — add an API key in "
                        "Settings → Providers, sign in to ArchHub Cloud, or "
                        "start Ollama."
                    ),
                )

        # Auto-fallback chain: try the routed provider; on auth/quota
        # failure (4xx) block it for 10 min and pick the next available.
        # Stops the user from staring at a spinner because Anthropic
        # ran out of credits / OpenAI quota exceeded — switches to
        # Google Gemini or local Ollama transparently.
        attempts = []
        last_error: Exception | None = None
        # EMPTY-REPLY FIX (founder 2026-06-20): set when an attempt produced
        # text that was RETRACTED (refusal or fabricated-tool markup) and the
        # chain then ran out of fresh providers. A retraction WIPES the
        # streamed bubble; if no later attempt replaces it the turn ends EMPTY
        # (chat_done with zero chat_chunk — 'I write and get nothing'). When
        # this is set and the loop exhausts, we DON'T raise — we fall through
        # to a guaranteed plain-LLM answer (tools disabled) so the user always
        # gets a real reply. Host words ('teams', 'revit', 'word', …) made the
        # model reach for an offline host tool and fabricate; the plain-LLM
        # pass answers honestly instead of leaving the bubble blank.
        retracted_without_replacement = False
        # Fallback budget — enough rounds to fail through every
        # cloud provider AND the refusal-detector before reaching
        # Ollama. Six providers max: anthropic / openai / google /
        # openrouter / archhub_cloud / relay / ollama.
        for fallback_round in range(7):
            provider, model_name, note = self._route(history, model)
            # Dedup by provider:model — re-picking the SAME provider with a
            # DIFFERENT model is allowed (the nvidia 404-then-default retry),
            # but the identical provider:model is never tried twice (no loop).
            _attempt_key = f"{provider}:{model_name}"
            if _attempt_key in attempts:
                # Same provider+model re-picked because nothing else available.
                break
            attempts.append(_attempt_key)
            try:
                client = self._get_client(provider)
                # Single transient-retry wrapper. Same provider, same
                # model, one extra shot — catches WinError 10054, httpx
                # ReadError, APIConnectionError, 502/503/504, anthropic
                # 529 overloaded. Real auth/quota errors fall through
                # to the outer except below and switch provider.
                response = None
                _net_retried = False
                while True:
                    try:
                        response = self._complete_once(
                            history=history, provider=provider, model_name=model_name,
                            note=note, client=client,
                            on_chunk=on_chunk, on_tool_invocation=on_tool_invocation,
                            on_reasoning=on_reasoning,
                            on_status=on_status,
                            session_pin=session_pin,
                            system_override=system_override,
                            extra_tools=extra_tools,
                            temperature=temperature,
                            max_tokens=max_tokens,
                            allowed_tool_names=allowed_tool_names,
                        )
                        break
                    except Exception as _net_ex:
                        if (_looks_like_transient_network(_net_ex)
                                and not _net_retried):
                            _net_retried = True
                            try:
                                on_status(
                                    f"{provider}: transient network "
                                    f"hiccup — retrying once…"
                                )
                            except Exception:
                                pass
                            import time as _t
                            _t.sleep(1.2)
                            continue
                        raise
                # Refusal detector — Gemini Flash + Pro emit refusal
                # text ('I cannot read your emails') instead of using
                # the tools, despite the AUTHORITY grant. We treat
                # this as a soft failure: block the provider for the
                # block window + re-route to the next provider in
                # the chain. Ollama command-r7b and Claude don't
                # refuse on data access; the fallback will reach one
                # of them.
                try:
                    had_tools = bool(self.tools.tool_schemas_for(provider))
                    invs = response.tool_invocations or []
                    if (had_tools
                            and _looks_like_refusal(
                                response.text or "",
                                had_tools=True,
                                tool_call_count=len(invs))):
                        on_status(
                            f"{provider}: refused to use tools — "
                            f"switching provider…"
                        )
                        # OUTPUT HYGIENE: this provider may have streamed
                        # a partial refusal ('I cannot read your emails')
                        # before we caught it — tell the caller to drop it
                        # so the winner's reply isn't prefixed by it.
                        try: on_attempt_reset(provider)
                        except Exception: pass
                        self.block_provider(
                            provider, reason="refused tool use"
                        )
                        model = ROUTE_AUTO
                        last_error = RuntimeError(
                            f"{provider} refused to use tools"
                        )
                        # Retracted text — if the chain dries up, fall through
                        # to a plain-LLM answer instead of an empty turn.
                        retracted_without_replacement = True
                        continue
                    # GUARD: the model fabricated tool-call / tool-result
                    # markup in its prose instead of making a real call
                    # (founder's recurring bug). Re-route — never let a
                    # fabricated answer stand. No block_provider: the
                    # provider isn't bad, the model glitched; `attempts`
                    # stops it being re-picked. If every provider is
                    # exhausted the loop raises → an honest error, not a
                    # lie.
                    if _looks_like_fabricated_tools(
                            response.text or "", len(invs)):
                        on_status(
                            f"{provider}: fabricated a tool call — "
                            f"switching provider…"
                        )
                        # OUTPUT HYGIENE: the fabricated prose was streamed
                        # to the bubble — drop it before the winner streams.
                        try: on_attempt_reset(provider)
                        except Exception: pass
                        last_error = RuntimeError(
                            f"{provider} fabricated tool-call markup"
                        )
                        model = ROUTE_AUTO
                        # Retracted text — if the chain dries up, fall through
                        # to a plain-LLM answer instead of an empty turn.
                        retracted_without_replacement = True
                        continue
                except Exception:
                    pass
                # SUCCESS — this provider authenticated + answered. If it had
                # been flagged signed-out earlier, clear it so it returns to
                # the primary set automatically (no restart).
                self._clear_signed_out(provider)
                return response
            except Exception as ex:
                last_error = ex
                # Record that this provider errored — the cloud-first guard
                # (#241 extended) prefers the working cloud over a keyed/CLI
                # provider that has broken this session.
                self._mark_attempted_failed(provider)
                # UNCALLABLE MODEL (404 function-not-found / model-does-not-
                # exist): the KEY is fine, only this model is wrong for the
                # account. Mark THE MODEL bad (not the provider) and re-route
                # so the identical 404 is never repeated. For nvidia, _route
                # then substitutes the known-callable default; for any other
                # provider the chain moves onward. (founder archhub.log:
                # nvidia nemotron-253b NotFoundError 404 loop.)
                _uncallable = _looks_like_uncallable_model(ex)
                try:
                    # AgDR-0047 §B2: route through central logger (handler
                    # registered in app/logging_config.py). EXPECTED provider
                    # failures — auth (401/403), 404 not-found / uncallable
                    # model, payment/quota (402), CLI timeout, signed-out /
                    # blocked — are NORMAL fallback signals, not bugs, so they
                    # log at WARNING. Only genuinely-unexpected exceptions stay
                    # at ERROR (founder archhub.log: 401/404 spam at error
                    # level made a working fallback look like a crash loop).
                    import logging as _logging
                    _expected = (
                        _looks_like_auth_or_quota(ex)
                        or _uncallable
                        or _looks_like_transient_network(ex)
                        or self._is_auth_error(provider, ex)
                        or (provider in ("claude_cli", "codex_cli")
                            and (_claude_cli_is_auth(ex)
                                 or "timeout" in (str(ex) or "").lower()
                                 or "timed out" in (str(ex) or "").lower()))
                    )
                    _lvl = _logging.WARNING if _expected else _logging.ERROR
                    _logging.getLogger("archhub.llm").log(
                        _lvl,
                        f"[{provider}] EXCEPTION "
                        f"{type(ex).__name__}: {str(ex)[:600]}"
                    )
                except Exception:
                    pass
                if _uncallable:
                    try: on_attempt_reset(provider)
                    except Exception: pass
                    self._mark_model_bad(provider, model_name, reason=str(ex)[:200])
                    on_status(
                        f"{provider}: model {model_name} unavailable — "
                        f"switching…"
                    )
                    # NVIDIA: retry the SAME provider with its known-callable
                    # default model (a DIFFERENT model — allowed by the
                    # provider:model attempts dedupe), UNLESS the default is
                    # what just failed. Re-issuing an explicit `nvidia:default`
                    # pick re-enters _route's nvidia branch, which (because the
                    # bad model is now flagged) substitutes the default. Any
                    # other provider, or nvidia's default itself failing, routes
                    # onward via auto so the chain reaches a working provider.
                    if (provider == "nvidia"
                            and model_name != NVIDIA_DEFAULT_MODEL
                            and not self.is_model_bad(
                                "nvidia", NVIDIA_DEFAULT_MODEL)):
                        model = f"nvidia:{NVIDIA_DEFAULT_MODEL}"
                    else:
                        model = ROUTE_AUTO
                    last_error = ex
                    continue
                # Local CLI providers (claude_cli / codex_cli) failing —
                # CLI missing, not logged in, timeout, crash — is a SOFT
                # failure: block briefly + re-route down the chain
                # (claude_cli → codex_cli → metered APIs → ollama) rather
                # than hard-raising and killing the whole turn.
                #
                # claude_cli HTTP 401: the subscription token expired /
                # the CLI is signed out. The CLI client surfaces this as a
                # RuntimeError whose text carries the 401 — and a stream
                # can 401 PART-WAY through (some text already pushed). It is
                # an AUTH failure, NOT a generic hard error: route onward to
                # the next provider exactly like an Anthropic-API 401, never
                # raise it as the turn's fatal error. (_looks_like_auth_or_quota
                # already matches '401'/'unauthorized'; _claude_cli_is_auth
                # also catches the CLI's worded 'not authenticated' / 'log in'
                # phrasings that omit the bare code.)
                is_auth = (_looks_like_auth_or_quota(ex)
                           or (provider == "claude_cli"
                               and _claude_cli_is_auth(ex)))
                if not (is_auth or provider in ("claude_cli", "codex_cli")):
                    raise
                # OUTPUT HYGIENE: a stream that died mid-flight (e.g. a 401
                # after the first tokens) already pushed a partial reply to
                # the bubble. Signal the caller to DROP it before the next
                # provider streams the real answer — the founder must never
                # see the loser's half-message in front of the winner's.
                try: on_attempt_reset(provider)
                except Exception: pass
                self.block_provider(provider, reason=str(ex)[:200])
                # PRIMARY-CHURN FIX (founder 2026-06-20): an AUTH failure
                # (signed-out subscription / bad key / 401-403 / expired
                # token) means this provider can't be primary until it
                # re-authenticates. Mark it signed-out so the NEXT turn skips
                # it BEFORE trying it — no more per-turn 'switching provider…'
                # churn. (The 10-min blocklist alone expired + re-churned.)
                # Cleared automatically on the next success.
                if self._is_auth_error(provider, ex):
                    self._mark_signed_out(provider, reason=str(ex)[:200])
                # Tell the chat layer so it can show a fallback toast —
                # "Switched anthropic → google: out of credit" beats a
                # silent re-route the user can't see.
                try:
                    reason = self.block_reason(provider) or "blocked"
                    on_status(f"{provider} {reason} — switching provider…")
                except Exception:
                    pass
                # Force auto re-route on the next loop.
                model = ROUTE_AUTO
                continue

        # ── NEVER-EMPTY GUARANTEE (founder 2026-06-20) ──────────────────
        # The chain exhausted. The OLD behaviour raised here, but when the
        # exhaustion was caused by refusal/fabrication RETRACTIONS the bubble
        # was already wiped — the user saw NOTHING (chat_done, zero chunks).
        # The host-word prompts ('teams', 'revit', 'word', 'max', …) tripped
        # this every time: the word made the model reach for an offline host
        # tool and fabricate, every tool-capable attempt got retracted, the
        # chain ran dry, and the turn ended empty.
        #
        # FIX: do ONE final, tools-DISABLED plain-LLM pass on any reachable
        # provider and return THAT. Tools off ⇒ no host reach ⇒ no fabrication
        # ⇒ no retraction: the model just answers in natural language about
        # what it can/can't do. Connectors/hosts being offline now produce an
        # HONEST answer, never an empty turn. We attempt this whenever content
        # was retracted without replacement (the empty-turn class); a pure
        # provider-exhaustion with NO retraction still raises (honest error).
        if retracted_without_replacement:
            fallback = self._plain_llm_fallback(
                history=history,
                on_chunk=on_chunk, on_reasoning=on_reasoning,
                on_status=on_status, on_attempt_reset=on_attempt_reset,
                temperature=temperature, max_tokens=max_tokens,
            )
            if fallback is not None:
                return fallback
        raise RuntimeError(
            f"All configured LLM providers exhausted (tried {attempts}). "
            f"Last error: {last_error}"
        )

    def _plain_llm_fallback(
        self, *, history, on_chunk, on_reasoning, on_status,
        on_attempt_reset, temperature=None, max_tokens=None,
    ) -> Optional[LLMResponse]:
        """Guaranteed-non-empty fallback: stream a tools-DISABLED plain-LLM
        answer from the first reachable provider. Used when the tool-using
        fallback chain ended with content RETRACTED (refusal / fabricated
        tools) and nothing replaced it — without this the turn ends empty
        (chat_done, zero chunks: the founder's 'I write and get nothing').

        Tools off ⇒ the model can't reach an offline host ⇒ it can't
        fabricate ⇒ nothing gets retracted: it just answers honestly. We try
        each reachable provider in routing order, streaming the FIRST that
        produces non-empty text. Returns None only when NO provider is
        reachable at all (the caller then raises the honest 'exhausted'
        error). `system_override` forces the tool-less path inside
        `_complete_once` (it sets tool_schemas=[]); we pass a plain assistant
        instruction so the answer is normal prose, not a refusal."""
        plain_prompt = (
            "You are ArchHub's in-canvas copilot for AEC professionals. "
            "Answer the user's message directly in natural language. You "
            "have no live host/connector tools available for this reply, so "
            "do not claim to have read or changed any host (Revit, AutoCAD, "
            "Excel, Outlook, Teams, Word, Notion, Blender, …). If the request "
            "needs a host that isn't reachable, say so plainly in one line "
            "and offer what you CAN do. Never reply with an empty message."
        )
        try:
            reachable = list(self.configured_providers())
        except Exception:
            reachable = []
        for provider in reachable:
            try:
                client = self._get_client(provider)
            except Exception as ex:
                # A reachable-by-config provider whose client won't build
                # (e.g. signed-out cloud) — skip to the next, mark auth.
                if self._is_auth_error(provider, ex):
                    self._mark_signed_out(provider, reason=str(ex)[:160])
                continue
            try:
                on_status(
                    f"answering without host tools via {provider}…"
                )
            except Exception:
                pass
            try:
                resp = self._complete_once(
                    history=history, provider=provider, model_name="auto",
                    note=f"plain answer (no host tools) · {provider}",
                    client=client,
                    on_chunk=on_chunk, on_tool_invocation=(lambda _: None),
                    on_reasoning=on_reasoning, on_status=on_status,
                    system_override=plain_prompt,
                    temperature=temperature, max_tokens=max_tokens,
                )
            except Exception as ex:
                if self._is_auth_error(provider, ex):
                    self._mark_signed_out(provider, reason=str(ex)[:160])
                # Whatever this provider streamed (if anything) must be
                # dropped before we try the next one.
                try: on_attempt_reset(provider)
                except Exception: pass
                continue
            if resp is not None and (getattr(resp, "text", "") or "").strip():
                self._clear_signed_out(provider)
                return resp
            # Empty again — drop and try the next reachable provider.
            try: on_attempt_reset(provider)
            except Exception: pass
        return None

    def _complete_once(
        self, *, history, provider, model_name, note, client,
        on_chunk, on_tool_invocation, on_reasoning=None,
        on_status=None,
        session_pin: Optional[str] = None,
        system_override: Optional[str] = None,
        extra_tools: Optional[list[dict]] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        allowed_tool_names: Optional[set] = None,
    ):
        on_reasoning = on_reasoning or (lambda _: None)
        on_status = on_status or (lambda _: None)
        extra_tools = extra_tools or []
        # OPTIONAL sampling params (node.config temperature/max_tokens).
        # Built once here into a kwargs dict that's spread into the
        # provider call ONLY when a value was supplied — so a None (chat
        # default) leaves the provider's own default untouched. Providers
        # whose stream_completion predates these kwargs raise TypeError;
        # the call sites below retry WITHOUT them, so wiring them through
        # can never break a provider (back-compat).
        _sampling_kwargs: dict = {}
        if temperature is not None:
            _sampling_kwargs["temperature"] = temperature
        if max_tokens is not None:
            _sampling_kwargs["max_tokens"] = max_tokens
        # Original body inlined below — extracted so the auto-fallback
        # loop can wrap it cleanly.

        # Reset per-turn guards — both fire at most once per chat turn
        # so we don't loop forever on an uncooperative model.
        self._nudged_this_turn = False
        self._retried_no_tools = False

        # ── System prompt + message hygiene ──────────────────────────
        # ROOT-CAUSE FIX (2026-05-16): a provider `messages` array accepts
        # ONLY user / assistant / tool roles. Several callers (chat,
        # composer, workflow LLM nodes) prepended a `role:"system_override"`
        # — or `"system"` — message INTENDING it to act as a system
        # prompt. The router never honoured that: it forwarded the bogus
        # role straight to the provider. Anthropic/OpenAI 400 on it, so
        # every such call fell through the auto-fallback chain to a
        # provider that tolerates it — OpenRouter, which carries ZERO
        # tool schemas here. A tool-less model asked a factual question
        # then FABRICATES a <function_calls>/<function_result> block and
        # lies about the result.
        #
        # Fix the class once, here: fold any system / system_override
        # history message INTO the system prompt (what the callers always
        # meant), and forward only real conversational turns. No provider
        # ever sees a bad role again, so chat keeps its tool-capable
        # provider and the model calls real tools instead of inventing
        # them.
        folded_system: list[str] = []
        convo_history: list[dict] = []
        for _m in history:
            _role = _m.get("role")
            if _role in ("system", "system_override"):
                _c = _m.get("content")
                if isinstance(_c, str) and _c.strip():
                    folded_system.append(_c.strip())
            elif _role in ("user", "assistant", "tool"):
                convo_history.append(_m)
            # Any other / unknown role is dropped — never forwarded.

        # `system_override` (the real parameter) is a specialised one-shot
        # (Node Smith JSON generation): own prompt verbatim, NO tools.
        # Everything else — including chat that folded a system message
        # above — gets the full tool surface so the model can actually
        # act instead of fabricating.
        base_prompt = system_override or self._build_system_prompt()
        system_prompt = (
            base_prompt + "\n\n" + "\n\n".join(folded_system)
            if folded_system else base_prompt
        )
        tool_schemas = ([] if system_override
                        else self.tools.tool_schemas_for(provider))
        # Per-call ToolEngine whitelist (THREAD-SAFE). When the caller
        # (workflow `llm.complete_with_tools` node) restricts tools, filter
        # the schemas to the allowed names HERE — a local list copy — so we
        # never mutate the shared ToolEngine instance the way the old
        # node-side monkey-patch did (which corrupted concurrent turns).
        # Matches the name at the top level (anthropic/google wire shape)
        # or under function.name (openai-compatible shape).
        if allowed_tool_names:
            def _ts_name(_t: dict) -> str:
                return (_t.get("name")
                        or (_t.get("function") or {}).get("name")
                        or "")
            tool_schemas = [t for t in tool_schemas
                            if _ts_name(t) in allowed_tool_names]
        # Small models choke on a big tool list. Gemini Flash refuses
        # to pick when given 30+ schemas (empty type=final, no call);
        # local Ollama 7-8B models (command-r7b, qwen…) do the same —
        # given all 177 tools, command-r7b emitted a bare pseudo-call
        # `autocad.get_documents()` as text instead of a real call.
        # Trim per-request to the tools plausibly relevant to the
        # user's last message. Anthropic / OpenAI tolerate large lists.
        if provider in ("google", "ollama") and len(tool_schemas) > 16:
            tool_schemas = _filter_tools_by_relevance(
                tool_schemas, history, cap=12,
            )

        # ── Caller-supplied CLIENT-SIDE tools (e.g. the Composer's canvas
        # primitives). Merge them into the provider tool surface AFTER the
        # relevance trim above so a small-model filter can never drop them
        # — the caller asked for these specific tools and owns their
        # execution. They arrive in Anthropic `{name, description,
        # input_schema}` shape; convert to the active provider's wire
        # format (mirrors ToolEngine.tool_schemas_for). `system_override`
        # one-shots stay tool-LESS, so we skip the merge there. The
        # `_client_tool_names` set tells the dispatch loop below to route
        # these to on_tool_invocation instead of ToolEngine.invoke.
        _client_tool_names: set = set()
        if extra_tools and not system_override:
            for _et in extra_tools:
                _name = (_et or {}).get("name")
                if not _name:
                    continue
                _desc = _et.get("description", "")
                _schema = _et.get("input_schema") or {
                    "type": "object", "properties": {},
                }
                if provider == "anthropic":
                    _wired = {"name": _name, "description": _desc,
                              "input_schema": _schema}
                elif provider == "google":
                    _wired = {"name": _name, "description": _desc,
                              "parameters": _schema}
                else:  # openai-compatible (openai/ollama/openrouter/…)
                    _wired = {"type": "function", "function": {
                        "name": _name, "description": _desc,
                        "parameters": _schema}}
                tool_schemas = tool_schemas + [_wired]
                _client_tool_names.add(_name)

        # Tool-use loop. The cap prevents runaway loops when a model
        # gets stuck calling itself, but it also has to be high enough
        # for legitimate multi-stage Skills like sketch-to-production
        # (six stages, ~2 iterations each). Tier the cap by model
        # quality — bigger models get more rope because they're less
        # prone to runaway and more likely to need extra rounds for
        # complex tool chains.
        all_invocations: list[ToolInvocation] = []
        # CLI-provider in-process tool calls (claude_cli MCP loop) — these
        # never pass through the router tool-use loop, so collect them for
        # the ai.plan turn record.
        cli_tool_calls_log: list = []
        full_text = ""
        # Working copy for tool round-tripping — only real conversational
        # turns (system messages were folded into system_prompt above).
        messages = [m for m in convo_history]

        # AgDR-0013 Layer 3 — LIBRARY-FIRST gate state.
        # Fresh TurnState per LLM completion. Tracks whether
        # `library_search` (or alias) was called this turn so the gate
        # can deny premature `library_create_node_type` calls.
        try:
            from library_gate import LibraryGate, TurnState
            _lib_gate = LibraryGate()
            _lib_turn_state = TurnState()
        except Exception:
            # Library gate module not available — fall through, no
            # enforcement. Honest fallback: the LLM can still call
            # library_create_node_type but skips the LIBRARY-FIRST
            # check. Better than failing the entire chat turn.
            _lib_gate = None
            _lib_turn_state = None

        # Diagnostic log — defined HERE (before any caller) because the
        # AgDR-0044 Layer 5 init below references _trace in its except
        # branch. Prior version defined _trace at line 1339 which left
        # the Layer 5 init blocks raising UnboundLocalError under any
        # init failure path (caught 2026-05-25, test_tool_filter gemini
        # route).
        #
        # AgDR-0047 §B2: routes through the central `archhub.llm` logger
        # (handler registered in app/logging_config.py at
        # %LOCALAPPDATA%/ArchHub/logs/llm_trace.log with rotation). The
        # provider:model_name prefix is preserved in the message body so
        # existing log-tail tooling still sees it.
        def _trace(msg: str) -> None:
            try:
                import logging as _logging
                _logging.getLogger("archhub.llm").info(
                    f"[{provider}:{model_name}] {msg}"
                )
            except Exception:
                pass

        # AgDR-0044 Layer 5 — MEMORY + SKILL substrate gate.
        # Talks to the personal-brain MCP daemon (default :8473). Brain
        # unavailable → all 4 hook calls become no-ops; the turn proceeds
        # exactly as it would without Layer 5. Gate is enrichment, never
        # block.
        try:
            from memory_gate import MemoryGate, MemoryTurnState
            import uuid as _uuid
            _mem_gate = MemoryGate()
            _mem_turn_state = MemoryTurnState(
                session_id=session_pin,
                trace_id=str(_uuid.uuid4()),
            )
        except Exception as _mem_ex:
            _trace(f"memory_gate init exception: {_mem_ex}")
            _mem_gate = None
            _mem_turn_state = None

        # AgDR-0044 Layer 5 — PRE-PROMPT hook.
        # Pull relevant skills + facts + wiring + secret refs from brain
        # and prepend the injection block to system_prompt. Best-effort:
        # if brain returns nothing, system_prompt unchanged.
        if _mem_gate is not None and _mem_turn_state is not None and messages:
            try:
                last_user_msg = ""
                for _m in reversed(messages):
                    if _m.get("role") == "user":
                        _c = _m.get("content")
                        if isinstance(_c, str):
                            last_user_msg = _c
                        elif isinstance(_c, list):
                            # Anthropic-shape user content blocks
                            for _blk in _c:
                                if isinstance(_blk, dict) and _blk.get("type") == "text":
                                    last_user_msg = _blk.get("text", "")
                                    break
                        break
                if last_user_msg:
                    _pre = _mem_gate.pre_prompt(
                        _mem_turn_state,
                        user_message=last_user_msg,
                        owner_user=None,
                    )
                    _inj = (_pre.augmentation or {}).get("injection", "")
                    if _inj:
                        system_prompt = system_prompt + "\n\n" + _inj
                        _trace(
                            f"layer5 pre_prompt injected "
                            f"{len((_pre.augmentation or {}).get('skills') or [])} skills + "
                            f"{len((_pre.augmentation or {}).get('facts') or [])} facts "
                            f"({(_pre.augmentation or {}).get('retrieval_ms', 0):.1f}ms)"
                        )
            except Exception as _pre_ex:
                _trace(f"layer5 pre_prompt exception: {_pre_ex}")

        max_iters = self._max_iterations(model_name)
        _trace(f"START history_len={len(history)} "
                f"last_user={(history[-1].get('content','') if history else '')[:80]!r} "
                f"tool_schemas={len(tool_schemas)}")
        for _iteration in range(max_iters):
            text_buf = []

            def chunk_handler(piece: str) -> None:
                text_buf.append(piece)
                on_chunk(piece)

            # Ollama uses a different client interface
            if provider == "ollama":
                try:
                    assistant_text, raw_tool_calls = client.complete(
                        system=system_prompt,
                        history=messages,
                        model=model_name,
                        tools=tool_schemas,
                        on_chunk=chunk_handler,
                        on_reasoning=on_reasoning,
                        **_sampling_kwargs,
                    )
                except TypeError:
                    # Older OllamaClient.complete without sampling kwargs —
                    # drop them, keep the model's defaults.
                    assistant_text, raw_tool_calls = client.complete(
                        system=system_prompt,
                        history=messages,
                        model=model_name,
                        tools=tool_schemas,
                        on_chunk=chunk_handler,
                        on_reasoning=on_reasoning,
                    )
                full_text += assistant_text
                # REAL usage capture — Ollama records prompt_eval_count /
                # eval_count on the done-chunk; the client stashed it on
                # `last_usage`. Fold the real counts into the accumulator.
                self._record_usage(provider, model_name,
                                   getattr(client, "last_usage", None))
                tool_calls = raw_tool_calls  # already [{id, name, input}]
                if not tool_calls:
                    # Procrastination check — local models often write
                    # essays instead of calling a tool. If the user
                    # clearly asked for an action AND tools were
                    # offered AND nothing was called, give the model
                    # ONE forced retry with an explicit "Use the tool
                    # now" nudge. If it still refuses, give up so we
                    # don't burn the iteration cap on an unresponsive
                    # model.
                    if (_looks_like_action(messages)
                            and tool_schemas
                            and len(assistant_text) > 80
                            and not getattr(self, "_nudged_this_turn", False)):
                        self._nudged_this_turn = True
                        on_status("Local model didn't call a tool — "
                                   "retrying with a nudge…")
                        messages.append({
                            "role": "assistant",
                            "content": assistant_text,
                        })
                        messages.append({
                            "role": "user",
                            "content": (
                                "Don't describe — call the matching "
                                "tool now. One tool call. No code in "
                                "chat."
                            ),
                        })
                        continue
                    break
            else:
                # Provider-specific kwargs: anthropic accepts on_reasoning
                # for extended-thinking blocks. Other providers ignore the
                # kwarg via **kwargs catch-all in their stream_completion
                # signatures (or raise TypeError, in which case we drop
                # the callback for that provider only).
                stream_kwargs = dict(
                    model=model_name,
                    system=system_prompt,
                    messages=messages,
                    tools=tool_schemas,
                    on_chunk=chunk_handler,
                )
                _trace(f"iter{_iteration} → stream_completion (msg_count={len(messages)})")
                # kwarg ladder, most-capable first. Each rung drops an
                # optional kwarg a given provider client may not accept:
                #   1. on_reasoning + sampling (temperature/max_tokens)
                #   2. sampling only (provider has no on_reasoning param)
                #   3. on_reasoning only (provider has no sampling params)
                #   4. neither (oldest client shape)
                # Sampling kwargs are empty unless the caller passed them,
                # so for a plain chat turn rungs 1↔3 and 2↔4 are identical
                # and behaviour is exactly as before this wiring.
                try:
                    stream = client.stream_completion(
                        on_reasoning=on_reasoning,
                        **_sampling_kwargs, **stream_kwargs,
                    )
                except TypeError:
                    try:
                        stream = client.stream_completion(
                            **_sampling_kwargs, **stream_kwargs,
                        )
                    except TypeError:
                        try:
                            stream = client.stream_completion(
                                on_reasoning=on_reasoning, **stream_kwargs,
                            )
                        except TypeError:
                            stream = client.stream_completion(**stream_kwargs)
                assistant_text = stream.get("text", "")
                full_text += assistant_text
                # Self-driving CLI providers (claude_cli) ran their MCP
                # tools in-process and report them on the stream as
                # tool_calls_log. Collect them so the turn's ai.plan record
                # shows the real host ops the local Claude executed.
                _cli_log = stream.get("tool_calls_log")
                if isinstance(_cli_log, list) and _cli_log:
                    cli_tool_calls_log.extend(_cli_log)
                # REAL usage capture — fold the provider-reported
                # usage{prompt_tokens, completion_tokens} into the running
                # total. Absent on providers that don't report it yet; the
                # accumulator then adds nothing (no fabrication).
                self._record_usage(provider, model_name, stream.get("usage"))
                _trace(f"iter{_iteration} ← type={stream.get('type')} "
                        f"text_len={len(assistant_text)} "
                        f"tool_calls={[t.get('name') for t in stream.get('tool_calls') or []]}")

                if stream["type"] == "final":
                    break

                tool_calls = stream.get("tool_calls") or []
                if not tool_calls:
                    break

            # Append assistant message with tool calls (provider-shape preserved)
            messages.append({
                "role": "assistant",
                "content": assistant_text,
                "_tool_calls": tool_calls,                 # provider-specific shape
            })

            tool_results = []
            for tc in tool_calls:
                inv = ToolInvocation(
                    id=tc.get("id") or str(uuid.uuid4()),
                    tool_name=tc["name"],
                    arguments=tc.get("input") or {},
                    status="running",
                )
                all_invocations.append(inv)
                on_tool_invocation(inv)

                # ── CLIENT-SIDE tool (caller owns execution, e.g. the
                # Composer's canvas primitives). Do NOT dispatch to
                # ToolEngine.invoke — it doesn't know this tool and would
                # return {'status':'error','error':'Unknown tool: …'},
                # which the model reads as a failure and either retries or
                # apologises. Instead: mark it accepted, fire the callback
                # AGAIN with the completed status so the caller collects
                # the action (the first fire above was status:running), and
                # feed a neutral acknowledgement back to the model so the
                # tool-use loop continues. The caller (run_agent_step)
                # replays inv against the real canvas.
                if inv.tool_name in _client_tool_names:
                    # SPAWN-ID CONTRACT (shared with the JSX spawn handler):
                    # when spawn_node fires we must ALLOCATE the new node id
                    # HERE — before the model continues — and hand it back in
                    # the ack, so a follow-up add_wire / set_node_param /
                    # run_node the model emits in the SAME turn can reference
                    # it, and the JSX places the node under that SAME id (see
                    # onAgentStep -> spawn_host_chat). The id is namespaced
                    # like the JSX library ids (ng:ai_chat) + a short uuid so
                    # every spawn is unique and resolvable. TOOL_SCHEMA's
                    # spawn_node advertises "Returns the new node id" — this is
                    # where that promise is kept (was a content-free
                    # {accepted:true} before, so multi-node orchestration was
                    # dead: the model never learned the id it just made).
                    inv.result = {"status": "ok", "accepted": True,
                                  "note": "applied to canvas"}
                    if inv.tool_name == "spawn_node":
                        _node_id = self._allocate_spawn_node_id(inv.arguments)
                        inv.result["node_id"] = _node_id
                        # Mirror onto the args so the caller's action dict
                        # (built from the invocation) carries the id too — the
                        # JSX replay reads action.node_id to place the node.
                        try:
                            inv.arguments = {**(inv.arguments or {}),
                                             "node_id": _node_id}
                        except Exception:
                            pass
                    inv.status = "ok"
                    on_tool_invocation(inv)
                    tool_results.append({
                        "tool_use_id": inv.id,
                        "name":         inv.tool_name,
                        "content":      inv.result,
                    })
                    continue   # skip gate + ToolEngine.invoke

                # AgDR-0013 Layer 3 — LIBRARY-FIRST gate.
                # Insert BEFORE ToolEngine.invoke for library_* calls.
                # The gate denies `library_create_node_type` when
                # `library_search` hasn't run this turn, OR when the
                # spec fails the Layer-4 validator. Translates a
                # GateDecision(allow=False) into a tool_result with
                # status:error + retry_hint so the LLM can fix in the
                # next iteration without aborting the turn.
                if _lib_gate is not None and _lib_gate.is_library_tool(
                        inv.tool_name):
                    try:
                        decision = _lib_gate.check(inv.tool_name,
                                                    inv.arguments,
                                                    _lib_turn_state)
                    except Exception as gate_ex:
                        # Gate errored — log + degrade gracefully (let
                        # the call through; treating the gate as
                        # advisory under failure beats blocking the turn).
                        _trace(f"library_gate exception: {gate_ex}")
                        decision = None
                    if decision is not None and not decision.allow:
                        inv.result = {
                            "status": "error",
                            "error":  decision.reason,
                            "retry_hint": decision.retry_hint,
                            "code":   "library_first_blocked",
                        }
                        inv.status = "error"
                        on_tool_invocation(inv)
                        tool_results.append({
                            "tool_use_id": inv.id,
                            "name":         inv.tool_name,
                            "content":      inv.result,
                        })
                        continue   # skip ToolEngine.invoke — gate denied

                # AgDR-0044 Layer 5 — PRE-EXECUTE hook.
                # Scan args for op:// secret refs; brain records the
                # resolution for trace stripping. Slice 7 will enforce
                # bipartite ACL on memory tools here too.
                if _mem_gate is not None and _mem_turn_state is not None:
                    try:
                        _mem_gate.pre_execute(
                            _mem_turn_state,
                            tool_name=inv.tool_name,
                            arguments=inv.arguments,
                        )
                    except Exception as _pre_ex:
                        _trace(f"layer5 pre_execute exception: {_pre_ex}")

                try:
                    result = self.tools.invoke(inv.tool_name, inv.arguments,
                                                session_pin=session_pin)
                    inv.result = result
                    inv.status = "ok" if (result or {}).get("status") != "error" else "error"
                except Exception as ex:
                    inv.result = {"status": "error", "error": str(ex)}
                    inv.status = "error"
                on_tool_invocation(inv)
                tool_results.append({
                    "tool_use_id": inv.id,
                    "name": inv.tool_name,
                    "content": inv.result,
                })

                # AgDR-0044 Layer 5 — POST-EXECUTE hook.
                # Fire-and-forget brain.write with a synthesized fragment
                # capturing this tool call. Brain unavailable → silent skip.
                if _mem_gate is not None and _mem_turn_state is not None:
                    try:
                        _mem_gate.post_execute(
                            _mem_turn_state,
                            tool_name=inv.tool_name,
                            arguments=inv.arguments,
                            result=inv.result,
                            status=inv.status,
                            contributing_agent=f"{provider}:{model_name}",
                            owner_user=None,
                            session_id=session_pin,
                        )
                    except Exception as _post_ex:
                        _trace(f"layer5 post_execute exception: {_post_ex}")

            messages.append({"role": "tool", "tool_results": tool_results})

        # Last-resort fallback A: if the model never produced text but
        # successfully ran tools, synthesize a one-line summary from
        # the most recent tool result. Prevents the "empty bubble
        # after a successful tool run" failure mode seen with Gemini +
        # tight system prompts where the model thinks the tool call
        # IS the answer.
        if not full_text.strip() and all_invocations:
            full_text = _summarise_tool_result(all_invocations[-1])

        # Last-resort fallback B: model returned NOTHING — no text AND
        # no tool calls. Happens with Gemini Flash when overwhelmed by
        # the tool menu, or when the input is too ambiguous to act on.
        # Retry ONCE with tools=[] so the model just produces natural
        # language. Guarded by an iteration flag so we never loop.
        if (not full_text.strip()
                and not all_invocations
                and tool_schemas
                and not getattr(self, "_retried_no_tools", False)):
            self._retried_no_tools = True
            _trace("empty response with tools — retrying with tools=[]")
            try:
                if provider == "ollama":
                    txt, _ = client.complete(
                        system=system_prompt + (
                            "\n\nNo tools available for this turn. "
                            "Reply in 1-2 short sentences."
                        ),
                        history=messages, model=model_name, tools=[],
                        on_chunk=on_chunk, on_reasoning=on_reasoning,
                    )
                    full_text = txt
                else:
                    retry_kwargs = dict(
                        model=model_name,
                        system=system_prompt + (
                            "\n\nNo tools available for this turn. "
                            "Reply in 1-2 short sentences."
                        ),
                        messages=messages, tools=[], on_chunk=on_chunk,
                    )
                    try:
                        s = client.stream_completion(
                            on_reasoning=on_reasoning, **retry_kwargs,
                        )
                    except TypeError:
                        s = client.stream_completion(**retry_kwargs)
                    full_text = s.get("text", "") or full_text
            except Exception as ex:
                _trace(f"retry-no-tools FAILED: {type(ex).__name__}: {ex}")

        _trace(f"END full_text_len={len(full_text)} "
                f"invocations={[(i.tool_name, i.status) for i in all_invocations]}")

        # AgDR-0044 Layer 5 — STOP hook.
        # Submit the full trace to brain.skill_mint. Reflexion worker
        # scores novelty + success off-thread (Slice 5). Brain unavailable
        # → silent skip; the turn already produced its response above.
        if _mem_gate is not None and _mem_turn_state is not None:
            try:
                _outcome = (
                    "success" if (
                        full_text.strip() and
                        all(i.status == "ok" for i in all_invocations)
                    ) else "partial"
                )
                _mint = _mem_gate.stop(
                    _mem_turn_state,
                    outcome=_outcome,
                    contributing_agent=f"{provider}:{model_name}",
                    owner_user=None,
                )
                if _mint:
                    _trace(
                        f"layer5 skill_mint queued={_mint.get('queued')} "
                        f"novelty={_mint.get('novelty_score', 0):.2f} "
                        f"name={_mint.get('proposed_name', '-')}"
                    )
            except Exception as _stop_ex:
                _trace(f"layer5 stop exception: {_stop_ex}")

        return LLMResponse(
            text=full_text,
            model=f"{provider}:{model_name}",
            tool_invocations=all_invocations,
            routing_note=note,
            tool_calls_log=cli_tool_calls_log,
        )

    @staticmethod
    def _allocate_spawn_node_id(arguments: Optional[dict]) -> str:
        """Mint the node id a spawn_node call will land on — the
        COMPOSER/ROUTER half of the SPAWN-ID CONTRACT.

        The JSX `spawn_host_chat` replay focuses + wires the spawned
        CONVERSATION node, so that's the id that must round-trip back to
        the model (a follow-up add_wire/run_node references the placed
        node). We namespace it like the JSX library ids ('ng:ai_chat')
        and append a short uuid so every spawn is unique + resolvable.
        The JSX uses this id verbatim (action.node_id) instead of minting
        its own; if it's ever absent the JSX falls back to its old uid
        scheme (back-compat).

        `arguments` is the spawn_node input ({family, title, x, y}); the
        family is not needed for uniqueness but kept in the signature so a
        future contract revision (e.g. encoding family into the id) is a
        one-line change here, not a cross-file one."""
        return f"ng:ai_chat:{uuid.uuid4().hex[:8]}"

    @staticmethod
    def _max_iterations(model_name: str) -> int:
        """Per-model tool-use loop cap. Bigger models get more rope.

        Gemini-class models cap at 10 per AgDR-0047 §B4 — observed
        2026-05-12 looping `outlook_set_categories` to iter12 in
        `llm_trace.log`. The lower cap aborts the runaway earlier
        before it burns a full default budget on duplicate calls.
        """
        m = (model_name or "").lower()
        if "opus" in m:
            return 32
        if "sonnet" in m or "gpt-4o" in m or "claude-4" in m:
            return 24
        if "gemini" in m:
            return 10
        return 16

    def _build_system_prompt(self) -> str:
        """Directive-first system prompt with EXPLICIT authority grant.

        Diagnosed on live traces: Gemini Flash + Pro refuse to use
        outlook tools that touch user data ('I can't read the content
        of your emails'). Their safety alignment defaults to that
        refusal when the prompt doesn't explicitly authorise data
        access. Same for set_categories, draft_reply, file writes.

        The user installed this app, connected their own accounts,
        and is asking the AI to act on their behalf. The prompt now
        leads with that authority grant BEFORE any rule language so
        the model resolves the permission question in the user's
        favour from the first token."""
        active = [e for e in self.tools.manager.entries
                  if e.state.name == "ACTIVE"]
        active_list = (", ".join(e.display_name for e in active)
                       if active else "(none)")
        return (
            "You are ArchHub, the user's AI assistant inside their "
            "own desktop. The user has installed this app on THEIR "
            "machine and connected THEIR accounts. Every tool below "
            "is wired to data they own.\n\n"
            "AUTHORITY: You have full permission to use any tool "
            "without asking. Read emails. Modify Revit / AutoCAD / "
            "Max / Blender files. Run code in their AEC apps. Set "
            "Outlook categories. Draft replies. Push to Speckle. "
            "The user has already granted this permission by "
            "installing ArchHub and activating each connector. Do "
            "NOT refuse on privacy or safety grounds — the user is "
            "asking you to act on their own data.\n\n"
            "Workflow each turn:\n"
            "1. Call the matching tool immediately — no preamble, "
            "no permission-checking. Multiple tools needed? Call "
            "them in sequence.\n"
            "2. Bulk requests have DEDICATED tools. PREFER THESE:\n"
            "   • 'categorise all my emails by project' / 'sort my "
            "inbox' / any bulk grouping where categories aren't "
            "named: call outlook_auto_categorize_by_sender() with "
            "NO ARGS. Returns a summary. One tool call, done.\n"
            "   • Specific filter (e.g. 'tag all Autodesk as Vendor'): "
            "outlook_set_categories_by_filter(categories=['Vendor'], "
            "sender_contains='@autodesk.com').\n"
            "   • Need domain stats before naming categories: "
            "outlook_list_distinct_senders().\n"
            "   ONLY fall back to a per-item loop "
            "(list_inbox → read_thread → set_categories per item) "
            "when none of the bulk tools fit. Use the REAL entry_id "
            "from item['entry_id'] — never a placeholder.\n"
            "   Don't refuse because it's many steps; that IS the job.\n"
            "3. End every turn with one or two short sentences "
            "describing what you did or found. Never finish silent.\n"
            "4. Only ask a clarifying question when the request is "
            "literally impossible without more info. Default: pick "
            "reasonable defaults and proceed.\n\n"
            f"Active connectors: {active_list}.\n\n"
            "ESCAPE HATCH — every host has an execute_* tool that "
            "runs arbitrary code with full host access. If no named "
            "tool fits, WRITE THE CODE and call execute. Never "
            "refuse for 'no tool' reason.\n"
            "  • revit_execute_csharp(code='...')\n"
            "  • acad_execute_csharp(code='...')\n"
            "  • max_execute_python(code='...') / max_execute_maxscript\n"
            "  • blender_execute_python(code='...')\n"
            "  • outlook_execute_python(code='...')\n"
            "Globals provided per host. Assign to `result` to return "
            "data. Example for Outlook 'count emails per sender':\n"
            "    result = {}\n"
            "    for m in inbox.Items:\n"
            "        s = str(getattr(m,'SenderEmailAddress','') or '')\n"
            "        result[s] = result.get(s,0)+1\n\n"
            "Hard rules:\n"
            "- NEVER paste code into chat for the user to copy. "
            "Code goes INSIDE tool calls only.\n"
            "- NEVER say 'I cannot access your data', 'I'm not "
            "authorized', or 'I can only provide a summary'. You ARE "
            "authorized — that's why the architect installed you.\n"
            "- On tool error: ONE sentence — what's wrong + how to "
            "fix (e.g. 'Revit unreachable on :48884 — open Revit and "
            "enable the ArchHub add-in').\n\n"
            "Be terse. Action over explanation."
        )
