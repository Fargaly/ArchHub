"""The model picker's list, read live -- never a table typed in 2025.

Three sources, each best effort and each honest about what it knows:
  CLOUD  -- what the founder's ArchHub cloud actually serves (/v1/models with
            his own session token); price is the subscription, so no number.
  BYO    -- OpenRouter's public catalogue with its real per-token prices.
  LOCAL  -- LM Studio and Ollama on this machine.
The founder saw "Claude Sonnet 4.5 / Opus 4.1 / GPT-4o" and asked whether that
was really everything (2026-09-05). It was a hard-coded list.
"""
from __future__ import annotations

import json
import threading
import time
import urllib.request
from typing import Callable, Mapping, Optional

OPENROUTER_MODELS = "https://openrouter.ai/api/v1/models"
LM_STUDIO_MODELS = "http://127.0.0.1:1234/v1/models"
OLLAMA_TAGS = "http://127.0.0.1:11434/api/tags"
_CACHE_SECONDS = 600.0
_VENDOR_COLOURS = {
    "anthropic": "#cc785c", "openai": "#10a37f", "google": "#4285f4", "meta-llama": "#0668e1",
    "mistralai": "#ff7000", "deepseek": "#3a6acc", "qwen": "#6f42c1", "x-ai": "#222222",
    "nvidia": "#76b900", "local": "#3fb950",
}
_lock = threading.Lock()
_cache: dict[str, object] = {"at": 0.0, "value": None}


def _get_json(url: str, *, headers: Optional[Mapping[str, str]] = None, timeout: float, opener: Callable) -> object:
    request = urllib.request.Request(url, headers=dict(headers or {}), method="GET")
    with opener(request, timeout=timeout) as answer:
        return json.loads(answer.read().decode("utf-8"))


def _vendor(route: str) -> str:
    return route.split("/", 1)[0] if "/" in route else (route.split(":", 1)[0] if ":" in route else "")


def _per_million(value: object) -> Optional[float]:
    try:
        return float(value) * 1_000_000.0
    except (TypeError, ValueError):
        return None


def _money(value: Optional[float]) -> str:
    if value is None:
        return "?"
    if value == 0:
        return "$0"
    return ("$%.2f" % value) if value >= 0.1 else ("$%.3f" % value)


def _ctx(tokens: object) -> str:
    try:
        n = int(tokens)
    except (TypeError, ValueError):
        return ""
    return "%dk" % round(n / 1000) if n >= 1000 else str(n)


def cloud_models(session: Optional[Mapping[str, str]], *, opener: Callable, timeout: float) -> list[dict]:
    if not session or not session.get("token"):
        return []
    data = _get_json(str(session["base_url"]).rstrip("/") + "/v1/models",
                     headers={"Authorization": "Bearer " + str(session["token"]), "Accept": "application/json"},
                     timeout=timeout, opener=opener)
    rows = data.get("data") if isinstance(data, Mapping) else data
    items = []
    for row in rows or []:
        if not isinstance(row, Mapping) or not row.get("id"):
            continue
        route = str(row["id"])
        vendor = str(row.get("owned_by") or _vendor(route) or "cloud")
        items.append({
            "name": str(row.get("name") or route), "route": route, "vendor": vendor,
            "tag": "CLOUD", "ctx": _ctx(row.get("context_length")), "cost": "subscription",
            "col": _VENDOR_COLOURS.get(vendor.lower(), "#d97757"),
        })
    return items


def openrouter_models(*, opener: Callable, timeout: float) -> list[dict]:
    data = _get_json(OPENROUTER_MODELS, headers={"Accept": "application/json"}, timeout=timeout, opener=opener)
    items = []
    for row in (data.get("data") if isinstance(data, Mapping) else []) or []:
        if not isinstance(row, Mapping) or not row.get("id"):
            continue
        route = str(row["id"])
        pricing = row.get("pricing") if isinstance(row.get("pricing"), Mapping) else {}
        prompt, completion = _per_million(pricing.get("prompt")), _per_million(pricing.get("completion"))
        vendor = _vendor(route)
        items.append({
            "name": str(row.get("name") or route), "route": route, "vendor": vendor, "tag": "BYO",
            "ctx": _ctx(row.get("context_length")),
            "cost": "%s / %s per M" % (_money(prompt), _money(completion)),
            "col": _VENDOR_COLOURS.get(vendor, "#3a6acc"),
        })
    items.sort(key=lambda item: item["name"].lower())
    return items


def local_models(*, opener: Callable, timeout: float) -> list[dict]:
    items = []
    try:
        data = _get_json(LM_STUDIO_MODELS, timeout=timeout, opener=opener)
        for row in (data.get("data") if isinstance(data, Mapping) else []) or []:
            if isinstance(row, Mapping) and row.get("id"):
                items.append({"name": str(row["id"]), "route": "lmstudio/" + str(row["id"]), "vendor": "LM Studio",
                              "tag": "LOCAL", "ctx": "", "cost": "free · local", "col": _VENDOR_COLOURS["local"]})
    except Exception:
        pass
    try:
        data = _get_json(OLLAMA_TAGS, timeout=timeout, opener=opener)
        for row in (data.get("models") if isinstance(data, Mapping) else []) or []:
            if isinstance(row, Mapping) and row.get("name"):
                items.append({"name": str(row["name"]), "route": "ollama/" + str(row["name"]), "vendor": "Ollama",
                              "tag": "LOCAL", "ctx": "", "cost": "free · local", "col": _VENDOR_COLOURS["local"]})
    except Exception:
        pass
    return items


def live_model_groups(session: Optional[Mapping[str, str]] = None, *, opener: Optional[Callable] = None,
                      timeout: float = 6.0, now: Optional[float] = None) -> dict:
    """Groups for the picker, cached ten minutes; every source best effort."""
    opener = opener or urllib.request.urlopen
    moment = time.time() if now is None else now
    with _lock:
        held = _cache["value"]
        if held is not None and moment - float(_cache["at"]) < _CACHE_SECONDS:
            return held
    errors: dict[str, str] = {}
    groups = []
    for name, fn in (("CLOUD · subscription", lambda: cloud_models(session, opener=opener, timeout=timeout)),
                     ("BYO · OpenRouter", lambda: openrouter_models(opener=opener, timeout=timeout)),
                     ("LOCAL · this machine", lambda: local_models(opener=opener, timeout=timeout))):
        try:
            items = fn()
        except Exception as exc:
            errors[name] = "%s: %s" % (type(exc).__name__, str(exc)[:120])
            items = []
        if items:
            groups.append({"name": name, "items": items})
    result = {"ok": True, "live": True, "groups": groups, "count": sum(len(g["items"]) for g in groups),
              "source_errors": errors, "read_at": moment}
    with _lock:
        _cache["at"] = moment
        _cache["value"] = result
    return result


def routable_route(item: Mapping[str, object]) -> str:
    """The string the router needs to send this row to its own provider.

    A cloud model id and an OpenRouter id are the same shape ("anthropic/x"),
    so a founder who picked the CLOUD row was answered by OpenRouter. The row
    already knows which family it belongs to, and local rows already carry
    their prefix, so the tag supplies the missing one.
    """
    route = str(item.get("route") or "").strip()
    if str(item.get("tag") or "").upper() == "CLOUD" and not route.startswith("cloud/"):
        return "cloud/" + route
    return route


def groups_with_routes(payload: Mapping[str, object]) -> dict:
    """The picker's answer with a routable string on every row.

    The rows themselves keep the ids their source published; `routed` is the
    one extra field, and it is what the composer and the chat rail send.
    """
    groups = []
    for group in payload.get("groups") or ():
        if not isinstance(group, Mapping):
            continue
        groups.append({
            **group,
            "items": [
                {**item, "routed": routable_route(item)}
                for item in group.get("items") or ()
                if isinstance(item, Mapping)
            ],
        })
    return {**payload, "groups": groups}


def reset_cache() -> None:
    with _lock:
        _cache["at"] = 0.0
        _cache["value"] = None


__all__ = ["live_model_groups", "cloud_models", "openrouter_models", "local_models",
           "routable_route", "groups_with_routes", "reset_cache"]
