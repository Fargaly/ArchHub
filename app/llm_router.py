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
from dataclasses import dataclass
from typing import Callable, Optional

from secrets_store import load_api_key, list_keys
from tool_engine import ToolEngine, ToolInvocation


ROUTE_AUTO = "auto"


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
    ("relay:auto",                                      "Firm relay"),
]


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
        elif "401" in short or "auth" in short or "invalid" in short and "key" in short:
            label = "invalid key"
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

    def configured_providers(self) -> list[str]:
        # `list_keys()` returns providers with an entry in the secrets
        # store — including ones whose value is empty (a placeholder
        # row left over from a half-completed Sign-ins flow). That made
        # the model picker show e.g. anthropic / openai / google as
        # "live" even when the actual key string was 0 chars, which
        # caused chats to hang on send. Filter through `load_api_key`
        # so only providers with a NON-EMPTY key count as configured.
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
                   "google": "GOOGLE_API_KEY", "openrouter": "OPENROUTER_API_KEY"}
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
        return sorted(p for p in providers if not self.is_provider_blocked(p))

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

    def _route(self, history: list[dict], requested_model: str) -> tuple[str, str, str]:
        """Return (provider, model_name, note)."""
        if requested_model and requested_model != ROUTE_AUTO:
            provider, _, model = requested_model.partition(":")
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
        # Free local subscriptions first — claude_cli preferred (it is
        # tool-capable via the ArchHub MCP server), codex_cli next.
        # Either one missing from `configured` means it's blocked after
        # a recent failure — routing then falls through to the metered
        # API providers below.
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

        # Default
        if "anthropic" in configured:
            return "anthropic", "claude-sonnet-4-6", "auto: default → Claude Sonnet 4.6"
        if "openrouter" in configured:
            return "openrouter", "anthropic/claude-sonnet-4", "auto: default → OpenRouter · Claude Sonnet 4"
        if "openai" in configured:
            return "openai", "gpt-4o", "auto: default → GPT-4o"
        if "google" in configured:
            return "google", "gemini-2.5-pro", "auto: default → Gemini 2.5 Pro"
        if "relay" in configured:
            return "relay", "auto", "auto: default → firm relay"
        if "archhub_cloud" in configured:
            return "archhub_cloud", "auto", "auto: default → ArchHub Cloud"
        if "ollama" in configured:
            m = self._pick_ollama_model("default")
            if m:
                return "ollama", m, f"auto: default → local Ollama {m}"
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
        session_pin: Optional[str] = None,
        system_override: Optional[str] = None,
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
        specialised instructions never reached the model."""
        on_chunk = on_chunk or (lambda _: None)
        on_tool_invocation = on_tool_invocation or (lambda _: None)
        on_reasoning = on_reasoning or (lambda _: None)
        on_status = on_status or (lambda _: None)

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
        # Fallback budget — enough rounds to fail through every
        # cloud provider AND the refusal-detector before reaching
        # Ollama. Six providers max: anthropic / openai / google /
        # openrouter / archhub_cloud / relay / ollama.
        for fallback_round in range(7):
            provider, model_name, note = self._route(history, model)
            if provider in attempts:
                # Same provider re-picked because nothing else available.
                break
            attempts.append(provider)
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
                        self.block_provider(
                            provider, reason="refused tool use"
                        )
                        model = ROUTE_AUTO
                        last_error = RuntimeError(
                            f"{provider} refused to use tools"
                        )
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
                        last_error = RuntimeError(
                            f"{provider} fabricated tool-call markup"
                        )
                        model = ROUTE_AUTO
                        continue
                except Exception:
                    pass
                return response
            except Exception as ex:
                last_error = ex
                try:
                    import os as _os, time as _t
                    from pathlib import Path as _P
                    _lp = (_P(_os.environ.get("LOCALAPPDATA", str(_P.home())))
                           / "ArchHub" / "logs")
                    _lp.mkdir(parents=True, exist_ok=True)
                    with open(_lp / "llm_trace.log", "a", encoding="utf-8") as _fh:
                        _fh.write(f"{_t.strftime('%Y-%m-%d %H:%M:%S')} "
                                  f"[{provider}] EXCEPTION "
                                  f"{type(ex).__name__}: {str(ex)[:600]}\n")
                except Exception:
                    pass
                # Local CLI providers (claude_cli / codex_cli) failing —
                # CLI missing, not logged in, timeout, crash — is a SOFT
                # failure: block briefly + re-route down the chain
                # (claude_cli → codex_cli → metered APIs → ollama) rather
                # than hard-raising and killing the whole turn.
                if not (_looks_like_auth_or_quota(ex)
                        or provider in ("claude_cli", "codex_cli")):
                    raise
                self.block_provider(provider, reason=str(ex)[:200])
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
        raise RuntimeError(
            f"All configured LLM providers exhausted (tried {attempts}). "
            f"Last error: {last_error}"
        )

    def _complete_once(
        self, *, history, provider, model_name, note, client,
        on_chunk, on_tool_invocation, on_reasoning=None,
        on_status=None,
        session_pin: Optional[str] = None,
        system_override: Optional[str] = None,
    ):
        on_reasoning = on_reasoning or (lambda _: None)
        on_status = on_status or (lambda _: None)
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

        # Tool-use loop. The cap prevents runaway loops when a model
        # gets stuck calling itself, but it also has to be high enough
        # for legitimate multi-stage Skills like sketch-to-production
        # (six stages, ~2 iterations each). Tier the cap by model
        # quality — bigger models get more rope because they're less
        # prone to runaway and more likely to need extra rounds for
        # complex tool chains.
        all_invocations: list[ToolInvocation] = []
        full_text = ""
        # Working copy for tool round-tripping — only real conversational
        # turns (system messages were folded into system_prompt above).
        messages = [m for m in convo_history]

        max_iters = self._max_iterations(model_name)
        # Diagnostic log — captures every iteration of the tool-use
        # loop to %LOCALAPPDATA%/ArchHub/logs/llm_trace.log so we can
        # see what each provider actually returned. Helps diagnose
        # "empty response" complaints without rebuilding state.
        def _trace(msg: str) -> None:
            try:
                import os, time as _t
                from pathlib import Path as _P
                p = (_P(os.environ.get("LOCALAPPDATA",
                                         str(_P.home())))
                     / "ArchHub" / "logs")
                p.mkdir(parents=True, exist_ok=True)
                with open(p / "llm_trace.log", "a",
                           encoding="utf-8") as fh:
                    fh.write(f"{_t.strftime('%Y-%m-%d %H:%M:%S')} "
                              f"[{provider}:{model_name}] {msg}\n")
            except Exception:
                pass

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
                assistant_text, raw_tool_calls = client.complete(
                    system=system_prompt,
                    history=messages,
                    model=model_name,
                    tools=tool_schemas,
                    on_chunk=chunk_handler,
                    on_reasoning=on_reasoning,
                )
                full_text += assistant_text
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
                try:
                    stream = client.stream_completion(
                        on_reasoning=on_reasoning, **stream_kwargs,
                    )
                except TypeError:
                    stream = client.stream_completion(**stream_kwargs)
                assistant_text = stream.get("text", "")
                full_text += assistant_text
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

        return LLMResponse(
            text=full_text,
            model=f"{provider}:{model_name}",
            tool_invocations=all_invocations,
            routing_note=note,
        )

    @staticmethod
    def _max_iterations(model_name: str) -> int:
        """Per-model tool-use loop cap. Bigger models get more rope."""
        m = (model_name or "").lower()
        if "opus" in m:
            return 32
        if "sonnet" in m or "gpt-4o" in m or "claude-4" in m:
            return 24
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
