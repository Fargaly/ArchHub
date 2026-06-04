"""AI-as-tool runner — call other models from inside a chat turn.

Architects increasingly mix AIs: Claude for reasoning, GPT for code,
Gemini for vision/long context, LM Studio for offline privacy-bound
work. Treating each as a TOOL (not a routing destination) means the
primary model can delegate mid-conversation:

    > Architect: "Have Gemini summarise these 30 PDFs while you draft
    > the Revit script."
    > Claude (primary): [calls ai_gemini_ask({prompt: "Summarise…"})]
                        [in parallel runs revit_execute_csharp]

Public functions (one per provider) — each returns
`{status: "ok", text: str, model: str, provider: str}` on success or
`{status: "error", error: str}` on failure.

  • chatgpt_ask(prompt, model=None, system=None, temperature=None,
                max_tokens=None)
  • gemini_ask(prompt, model=None, system=None, temperature=None)
  • lmstudio_ask(prompt, model=None, system=None, base_url=None,
                  temperature=None)
  • antigravity_ask(prompt, ...) — stub; documents the setup path
                                    when Google publishes a public API.

Keys come from `secrets_store.load_api_key(<provider>)` so the user
configures each provider once in Settings → Sign-ins and every tool
call reuses the same credential.
"""
from __future__ import annotations

import json
import urllib.request
import urllib.error
from typing import Optional


# ---------------------------------------------------------------------------
# Defaults — kept conservative so a tool call doesn't accidentally use
# an expensive frontier model when a fast/cheap one suffices.
DEFAULT_OPENAI_MODEL    = "gpt-5.4-mini"     # bumped 2026-04-23 release
DEFAULT_CODEX_MODEL     = "gpt-5.3-codex"    # newest codex variant
DEFAULT_GEMINI_MODEL    = "gemini-2.5-flash"
DEFAULT_LMSTUDIO_URL    = "http://localhost:1234/v1"
DEFAULT_LMSTUDIO_MODEL  = "auto"        # LM Studio resolves locally
DEFAULT_TIMEOUT_SECONDS = 60


# ---------------------------------------------------------------------------
def _load_key(provider: str) -> Optional[str]:
    """Pull the saved key for a provider, or None if missing."""
    try:
        from secrets_store import load_api_key
        k = load_api_key(provider)
        return k or None
    except Exception:
        return None


# ---------------------------------------------------------------------------
def codex_ask(prompt: str, model: Optional[str] = None,
              system: Optional[str] = None,
              temperature: Optional[float] = None,
              max_tokens: Optional[int] = None) -> dict:
    """Ask OpenAI Codex (gpt-5.3-codex / gpt-5.1-codex-max / ...) for
    code-focused work. Same wire format as `chatgpt_ask` but defaults
    to a code-tuned model + temperature 0.1.

    Use this when the primary model wants a second opinion on a patch,
    refactor, or test case. Stays cheap relative to gpt-5.5 because
    Codex variants are priced lower.
    """
    return chatgpt_ask(
        prompt=prompt,
        model=model or DEFAULT_CODEX_MODEL,
        system=system,
        temperature=0.1 if temperature is None else temperature,
        max_tokens=max_tokens,
    )


# ---------------------------------------------------------------------------
def chatgpt_ask(prompt: str, model: Optional[str] = None,
                system: Optional[str] = None,
                temperature: Optional[float] = None,
                max_tokens: Optional[int] = None) -> dict:
    """Ask OpenAI (ChatGPT / GPT-4o / o-series) and return the text."""
    if not prompt:
        return {"status": "error", "error": "prompt is required"}
    api_key = _load_key("openai")
    if not api_key:
        return {"status": "error",
                "error": "OpenAI API key not set. Open Settings → Sign-ins → OpenAI."}
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
        messages: list[dict] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        chosen_model = model or DEFAULT_OPENAI_MODEL
        params: dict = {"model": chosen_model, "messages": messages}
        # GPT-5+ Pro and o-series ignore `temperature` (must be omitted)
        # and use `max_completion_tokens` instead of `max_tokens`.
        is_pro = chosen_model.endswith("-pro") or chosen_model.startswith("o")
        is_gpt5_family = chosen_model.startswith("gpt-5")
        if not is_pro and temperature is not None:
            params["temperature"] = float(temperature)
        if max_tokens is not None:
            if is_gpt5_family or is_pro:
                params["max_completion_tokens"] = int(max_tokens)
            else:
                params["max_tokens"] = int(max_tokens)
        resp = client.chat.completions.create(**params)
        text = (resp.choices[0].message.content or "").strip()
        usage = getattr(resp, "usage", None)
        return {
            "status":   "ok",
            "provider": "openai",
            "model":    resp.model or params["model"],
            "text":     text,
            "tokens":   {
                "prompt":     getattr(usage, "prompt_tokens", None),
                "completion": getattr(usage, "completion_tokens", None),
                "total":      getattr(usage, "total_tokens", None),
            } if usage else None,
        }
    except Exception as ex:
        return {"status": "error", "error": f"{type(ex).__name__}: {ex}"}


# ---------------------------------------------------------------------------
def gemini_ask(prompt: str, model: Optional[str] = None,
               system: Optional[str] = None,
               temperature: Optional[float] = None) -> dict:
    """Ask Google Gemini and return the text."""
    if not prompt:
        return {"status": "error", "error": "prompt is required"}
    api_key = _load_key("google")
    if not api_key:
        return {"status": "error",
                "error": "Google AI API key not set. Open Settings → Sign-ins → Google."}
    try:
        # google.generativeai is the public SDK. New `google-genai`
        # SDK is the GA replacement; we support both.
        try:
            import google.generativeai as genai
            genai.configure(api_key=api_key)
            cfg = {}
            if temperature is not None:
                cfg["temperature"] = float(temperature)
            m = genai.GenerativeModel(
                model_name=model or DEFAULT_GEMINI_MODEL,
                system_instruction=system,
                generation_config=cfg or None,
            )
            resp = m.generate_content(prompt)
            text = (getattr(resp, "text", "") or "").strip()
            model_used = model or DEFAULT_GEMINI_MODEL
        except ImportError:
            # Fail-OVER (not fail-soft): the SDK isn't installed, so hit
            # the REST endpoint directly. `_gemini_via_rest` RAISES on a
            # transport error OR an API-level error payload, so a real
            # failure propagates to the outer `except` below and is
            # reported honestly — it is never masked as ok here. The
            # success return lives OUTSIDE this block so both paths share
            # one honest envelope.
            text, model_used = _gemini_via_rest(api_key, prompt, model, system,
                                                 temperature)
        return {"status": "ok", "provider": "google",
                "model": model_used, "text": text}
    except Exception as ex:
        return {"status": "error", "error": f"{type(ex).__name__}: {ex}"}


def _gemini_via_rest(api_key: str, prompt: str, model: Optional[str],
                      system: Optional[str],
                      temperature: Optional[float]) -> tuple[str, str]:
    m = model or DEFAULT_GEMINI_MODEL
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{m}:generateContent?key={api_key}")
    body: dict = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
    }
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}
    if temperature is not None:
        body["generationConfig"] = {"temperature": float(temperature)}
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=DEFAULT_TIMEOUT_SECONDS) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    # Gemini returns HTTP 200 even for several failure modes (the SDK
    # would have raised). Surface those as a RAISE so the caller reports
    # status:error instead of an empty-text "ok" lie:
    #   1. an explicit {"error": {...}} envelope, and
    #   2. a prompt that was blocked (no candidates + a blockReason).
    err = payload.get("error")
    if err:
        msg = err.get("message") if isinstance(err, dict) else str(err)
        raise RuntimeError(f"Gemini API error: {msg or err}")
    cands = payload.get("candidates") or []
    if not cands:
        reason = (payload.get("promptFeedback", {}) or {}).get("blockReason")
        raise RuntimeError(
            f"Gemini returned no candidates"
            + (f" (blocked: {reason})" if reason else ""))
    parts = cands[0].get("content", {}).get("parts") or []
    text = "".join(p.get("text", "") for p in parts).strip()
    return text, m


# ---------------------------------------------------------------------------
def lmstudio_ask(prompt: str, model: Optional[str] = None,
                 system: Optional[str] = None,
                 base_url: Optional[str] = None,
                 temperature: Optional[float] = None) -> dict:
    """Ask LM Studio (local OpenAI-compatible server) and return the text.

    LM Studio defaults to `http://localhost:1234/v1`. The user picks
    the model inside LM Studio's UI; we pass `model="auto"` so the
    server returns whichever model is currently loaded.

    No API key is required for the default localhost endpoint. If the
    user has put LM Studio behind a reverse proxy with auth, they can
    save a key under the `lmstudio` provider in Settings.
    """
    if not prompt:
        return {"status": "error", "error": "prompt is required"}
    url = (base_url or _load_setting("lmstudio_base_url")
           or DEFAULT_LMSTUDIO_URL).rstrip("/")
    api_key = _load_key("lmstudio") or "lm-studio"  # placeholder — SDK requires non-empty
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key, base_url=url)
        messages: list[dict] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        params = {
            "model": model or DEFAULT_LMSTUDIO_MODEL,
            "messages": messages,
        }
        if temperature is not None:
            params["temperature"] = float(temperature)
        resp = client.chat.completions.create(**params)
        text = (resp.choices[0].message.content or "").strip()
        return {
            "status":   "ok",
            "provider": "lmstudio",
            "model":    resp.model or params["model"],
            "base_url": url,
            "text":     text,
        }
    except Exception as ex:
        return {"status": "error",
                "error": f"{type(ex).__name__}: {ex}. "
                         f"Is LM Studio running at {url} with a model loaded?"}


def _load_setting(key: str) -> Optional[str]:
    try:
        from secrets_store import load_setting
        v = load_setting(key)
        return v or None
    except Exception:
        return None


# ---------------------------------------------------------------------------
def antigravity_ask(prompt: str, model: Optional[str] = None,
                    system: Optional[str] = None) -> dict:
    """Stub for Google Antigravity.

    Antigravity is Google's experimental coding-agent platform. As of
    v1.0.3 there is no public stable API for third-party callers; the
    tool exists so the LLM can DISCOVER it in the tool list and the
    error message tells the user what to do.

    When Google ships a public REST/SDK we replace this body — the
    schema stays stable so models written against the tool today keep
    working.
    """
    return {
        "status": "error",
        "error": (
            "Antigravity (Google) has no public API yet. Track "
            "https://blog.google/technology/google-deepmind/ for "
            "an SDK announcement. In the meantime, ask the architect "
            "to copy the prompt into Antigravity manually."
        ),
        "provider":  "antigravity",
        "available": False,
    }


# ---------------------------------------------------------------------------
def list_providers() -> dict:
    """Inventory of which AI-as-tool providers are configured.

    Returns:
        {"openai":      {"configured": True, "models": ["gpt-4o", …]},
         "google":      {"configured": True, "models": ["gemini-2.5-flash", …]},
         "lmstudio":    {"configured": False, "reachable": False,
                          "base_url": "http://localhost:1234/v1"},
         "antigravity": {"configured": False, "available": False}}

    The LLM uses this to decide which `ai_*_ask` tool to call. The
    Settings UI uses it to show per-provider status.
    """
    out: dict[str, dict] = {}
    out["openai"] = {
        "configured": bool(_load_key("openai")),
        "models": [DEFAULT_OPENAI_MODEL, "gpt-5.5", "gpt-5.5-pro",
                    "gpt-5.4", "gpt-5.4-mini", "gpt-5.4-nano",
                    DEFAULT_CODEX_MODEL, "gpt-5.1-codex-max",
                    "gpt-5.1-codex-mini"],
    }
    out["google"] = {
        "configured": bool(_load_key("google")),
        "models": [DEFAULT_GEMINI_MODEL, "gemini-2.5-pro",
                   "gemini-2.0-flash"],
    }
    base_url = (_load_setting("lmstudio_base_url")
                or DEFAULT_LMSTUDIO_URL).rstrip("/")
    out["lmstudio"] = {
        "configured": True,  # localhost path needs no key
        "base_url":   base_url,
        "reachable":  _lmstudio_reachable(base_url),
    }
    out["antigravity"] = {
        "configured": False,
        "available":  False,
        "note":       "No public API yet.",
    }
    return {"status": "ok", "providers": out}


def detect_local(force: bool = False) -> dict:
    """Wrapper around app/llm_detector.detect_all so the tool engine
    can route ai_detect_local to it. Adds the call-time timestamp."""
    try:
        # llm_detector lives next to ai_runner under app/; sys.path
        # already includes app/ when the tool engine runs.
        import sys
        from pathlib import Path
        app_root = str(Path(__file__).resolve().parent.parent)
        if app_root not in sys.path:
            sys.path.insert(0, app_root)
        from llm_detector import detect_all  # type: ignore
    except Exception as ex:
        return {"status": "error",
                "error": f"detector unavailable: {type(ex).__name__}: {ex}"}
    import datetime as _dt
    results = detect_all(force=bool(force))
    summary = {
        "live":      [p for p, i in results.items()
                      if i.get("status") == "live"],
        "available": [p for p, i in results.items()
                      if i.get("status") == "available"],
        "missing":   [p for p, i in results.items()
                      if i.get("status") == "missing"],
    }
    return {
        "status":  "ok",
        "ts":      _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "summary": summary,
        "providers": results,
    }


def _lmstudio_reachable(base_url: str) -> bool:
    """Quick GET /models probe — LM Studio responds even before a model
    is loaded, so this is a 'process up' check, not 'model loaded'."""
    try:
        req = urllib.request.Request(base_url.rstrip("/") + "/models",
                                       method="GET")
        with urllib.request.urlopen(req, timeout=1.5) as resp:
            return 200 <= resp.status < 300
    except Exception:
        return False
