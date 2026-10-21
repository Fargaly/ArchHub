"""The model picker's list, read live -- never a table typed in 2025.

Four sources, each best effort and each honest about what it knows:
  CLOUD  -- what the founder's ArchHub cloud actually serves (/v1/models with
            his own session token); price is the subscription, so no number.
  BYO    -- OpenRouter's public catalogue with its real per-token prices.
  DIRECT -- OpenAI and Google with this machine's own keys: the cheapest text
            models that each vendor's own list serves, priced by OpenRouter's
            catalogue for the same id. Never a typed id.
  LOCAL  -- LM Studio and Ollama on this machine.
The founder saw "Claude Sonnet 4.5 / Opus 4.1 / GPT-4o" and asked whether that
was really everything (2026-09-05). It was a hard-coded list.
"""
from __future__ import annotations

import json
import copy
import hashlib
import threading
import time
import urllib.error
import urllib.request
from typing import Callable, Mapping, Optional

from .cloud_relay import SIGN_IN_AGAIN, pinned_cloud_base

OPENROUTER_MODELS = "https://openrouter.ai/api/v1/models"
LM_STUDIO_MODELS = "http://127.0.0.1:1234/v1/models"
OLLAMA_TAGS = "http://127.0.0.1:11434/api/tags"
OPENAI_MODELS = "https://api.openai.com/v1/models"
GOOGLE_MODELS = "https://generativelanguage.googleapis.com/v1beta/models"
DIRECT_GROUP = "DIRECT · your keys"
DIRECT_PER_VENDOR = 3
# Ids naming a non-chat model (image, audio, speech, search, embeddings) or a
# Responses-only model; the chat-completions route cannot send to them.
_NOT_CHAT = ("image", "audio", "tts", "transcribe", "realtime", "live", "embed",
             "safety", "guard", "moderation", "rerank", "search", "whisper", "sora", "veo", "lyria", "robotics",
             "computer-use", "deep-research", "banana", "preview", "instruct",
             "babbage", "davinci")
# OpenAI serves these only on its Responses API, not chat completions.
_OPENAI_RESPONSES_ONLY = ("codex", "-pro")
_OPENROUTER_NOT_CHAT = ("safety", "guard", "moderation", "embed", "rerank", "whisper", "tts", "audio",
                        "lyria")
CLOUD_GROUP = "CLOUD · subscription"
BYO_GROUP = "Free cloud (OpenRouter)"
LOCAL_GROUP = "This machine (LM Studio / Ollama)"
SUBSCRIPTION_GROUP = "Your apps (subscription)"
_CACHE_SECONDS = 600.0
# How long a held answer still counts as new. Past this it is handed over all
# the same -- marked stale, with a refresh running behind it -- because reading
# the three sources costs seconds (2.71s for the OpenRouter catalogue alone on
# the founder's machine) and until every one of them had answered the picker
# drew nothing but "Discovering models from connected providers..." (2026-09-18).
_FRESH_SECONDS = 45.0
# What a source that gave no rows is allowed to say for itself. An exception
# carries the URL it failed on and can carry a token, so none of its text
# reaches the picker: only which of these sentences it was.
CLOUD_REFUSED_NOTE = ("The cloud refused this machine's sign-in: it expired or "
                      "was revoked. " + SIGN_IN_AGAIN)
CLOUD_ABSENT_NOTE = "No ArchHub cloud session on this machine. " + SIGN_IN_AGAIN
SOURCE_SILENT_NOTE = "%s did not answer. Refresh to ask again."
_VENDOR_COLOURS = {
    "anthropic": "#cc785c", "openai": "#10a37f", "google": "#4285f4", "meta-llama": "#0668e1",
    "mistralai": "#ff7000", "deepseek": "#3a6acc", "qwen": "#6f42c1", "x-ai": "#222222",
    "nvidia": "#76b900", "local": "#3fb950",
}
_lock = threading.Lock()
_cache: dict[str, object] = {"at": 0.0, "value": None, "identity": None}
# Accounts with a refresh already running behind an answer already given.
_refreshing: set[bytes] = set()


def _get_json(url: str, *, headers: Optional[Mapping[str, str]] = None, timeout: float, opener: Callable) -> object:
    request = urllib.request.Request(url, headers=dict(headers or {}), method="GET")
    with opener(request, timeout=timeout) as answer:
        return json.loads(answer.read().decode("utf-8"))


def _vendor(route: str) -> str:
    return route.split("/", 1)[0] if "/" in route else (route.split(":", 1)[0] if ":" in route else "")


def _per_million(value: object) -> Optional[float]:
    if isinstance(value, bool):
        return None
    try:
        return float(value) * 1_000_000.0
    except (TypeError, ValueError):
        return None


def _price_number(value: object) -> Optional[float]:
    if isinstance(value, bool):
        return None
    try:
        return float(value)
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


def _identity(session: Optional[Mapping[str, str]]) -> bytes:
    """One account, one cache slot. Never answer this account with another's rows."""
    return hashlib.sha256(json.dumps({
        "base_url": str(session.get("base_url", "")) if session else "",
        "token": str(session.get("token", "")) if session else "",
    }, sort_keys=True).encode("utf-8")).digest()


def _source_note(group: str, error: BaseException) -> str:
    """The one fixed sentence this failure is allowed to put on screen."""
    if (group == CLOUD_GROUP and isinstance(error, urllib.error.HTTPError)
            and error.code in (401, 403)):
        return CLOUD_REFUSED_NOTE
    return SOURCE_SILENT_NOTE % group


def cloud_models(session: Optional[Mapping[str, str]], *, opener: Callable, timeout: float) -> list[dict]:
    if not session or not session.get("token"):
        return []
    data = _get_json(pinned_cloud_base(session.get("base_url")) + "/v1/models",
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


def openrouter_models(*, opener: Callable, timeout: float, prices: Optional[dict] = None) -> list[dict]:
    data = _get_json(OPENROUTER_MODELS, headers={"Accept": "application/json"}, timeout=timeout, opener=opener)
    items = []
    for row in (data.get("data") if isinstance(data, Mapping) else []) or []:
        if not isinstance(row, Mapping) or not row.get("id"):
            continue
        route = str(row["id"])
        pricing = row.get("pricing") if isinstance(row.get("pricing"), Mapping) else {}
        prompt, completion = _per_million(pricing.get("prompt")), _per_million(pricing.get("completion"))
        request_price = _price_number(pricing.get("request"))
        image_price = _price_number(pricing.get("image"))
        # Every pricing field OpenRouter sends must be a number equal to zero.
        all_prices_zero = bool(pricing) and all(
            _price_number(value) == 0 for value in pricing.values()
        )
        if prices is not None and prompt is not None and completion is not None:
            prices[route] = (prompt, completion)
        vendor = _vendor(route)
        if not _openrouter_chat_row(row, route) or not _openrouter_free_row(route, pricing):
            continue
        items.append({
            "name": str(row.get("name") or route), "route": route, "vendor": vendor, "tag": "BYO",
            "ctx": _ctx(row.get("context_length")),
            "cost": "free",
            "prompt_price_per_m": prompt,
            "completion_price_per_m": completion,
            "request_price": request_price,
            "image_price": image_price,
            "all_prices_zero": all_prices_zero,
            "input_modalities": _input_modalities(row),
            "output_modalities": _output_modalities(row),
            "supported_parameters": _supported_parameters(row),
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


def subscription_cli_models(*, cli_rows: Optional[list[dict]] = None) -> list[dict]:
    if cli_rows is None:
        from .model_router import provider_rows  # noqa: PLC0415
        cli_rows = provider_rows()
    route_names = {
        "claude-code": "claude", "codex": "codex", "gemini-cli": "gemini",
        "opencode": "opencode", "antigravity": "antigravity", "cursor": "cursor",
    }
    items = []
    for row in cli_rows or []:
        if not isinstance(row, Mapping):
            continue
        state = str(row.get("state") or "").strip()
        if state in ("", "not installed"):
            continue
        row_id = str(row.get("id") or "").strip()
        route_name = route_names.get(row_id)
        if not route_name:
            continue
        name = str(row.get("name") or row_id)
        items.append({
            "name": name, "route": "local-cli/" + route_name, "vendor": name,
            "tag": "SUBSCRIPTION", "ctx": "", "cost": "subscription app",
            "state": state, "readiness": str(row.get("source") or state),
            "col": _VENDOR_COLOURS["local"],
        })
    return items


def _text_chat_id(vendor: str, model_id: str) -> bool:
    if vendor == "openai" and any(word in model_id for word in _OPENAI_RESPONSES_ONLY):
        return False
    return not any(word in model_id for word in _NOT_CHAT)


def _output_modalities(row: Mapping[str, object]) -> list[str]:
    values = []
    for source in (row, row.get("architecture") if isinstance(row.get("architecture"), Mapping) else {}):
        for key in ("output_modalities", "output_modality", "modalities", "output"):
            value = source.get(key) if isinstance(source, Mapping) else None
            if isinstance(value, str):
                values.append(value.casefold())
            elif isinstance(value, (list, tuple, set)):
                values.extend(str(item).casefold() for item in value)
    return values


def _input_modalities(row: Mapping[str, object]) -> list[str]:
    values = []
    for source in (row, row.get("architecture") if isinstance(row.get("architecture"), Mapping) else {}):
        for key in ("input_modalities", "input_modality", "modalities", "input"):
            value = source.get(key) if isinstance(source, Mapping) else None
            if isinstance(value, str):
                values.append(value.casefold())
            elif isinstance(value, (list, tuple, set)):
                values.extend(str(item).casefold() for item in value)
    return values


def _supported_parameters(row: Mapping[str, object]) -> list[str]:
    value = row.get("supported_parameters")
    if not isinstance(value, (list, tuple, set)):
        return []
    return [str(item).casefold() for item in value]


def _modalities_include_text(values: object) -> bool:
    if not isinstance(values, (list, tuple, set)) or not values:
        return False
    return any(str(value).casefold() in {"text", "chat"} for value in values)


def _openrouter_chat_row(row: Mapping[str, object], route: str) -> bool:
    text = route.casefold()
    if any(word in text for word in _OPENROUTER_NOT_CHAT):
        return False
    values = _output_modalities(row)
    return not values or any(value in {"text", "chat"} for value in values)


def _openrouter_free_row(route: str, pricing: Mapping[str, object]) -> bool:
    prompt = _price_number(pricing.get("prompt"))
    completion = _price_number(pricing.get("completion"))
    prompt_completion_zero = prompt == 0 and completion == 0
    suffix_free = route.endswith(":free")
    if not (suffix_free or prompt_completion_zero):
        return False
    for value in pricing.values():
        number = _price_number(value)
        if number is not None and number != 0:
            return False
    return True


def openrouter_free_chat_routes(payload: Mapping[str, object], *, require_tools: bool = False) -> tuple[str, ...]:
    """Free OpenRouter chat ids already present in the picker catalogue."""
    out: list[str] = []
    for group in payload.get("groups") or ():
        if not isinstance(group, Mapping) or group.get("name") != BYO_GROUP:
            continue
        for item in group.get("items") or ():
            if not isinstance(item, Mapping):
                continue
            route = str(item.get("route") or "").strip()
            if route.startswith("openrouter/"):
                route = route.split("/", 1)[1]
            if "/" not in route:
                continue
            prompt = item.get("prompt_price_per_m")
            completion = item.get("completion_price_per_m")
            zero = (
                type(prompt) in (int, float) and prompt == 0
                and type(completion) in (int, float) and completion == 0
            )
            suffix_free = route.endswith(":free")
            if suffix_free:
                zero = True
            request_price = item.get("request_price")
            image_price = item.get("image_price")
            if request_price is not None and (
                type(request_price) not in (int, float) or request_price != 0
            ):
                zero = False
            if image_price is not None and (
                type(image_price) not in (int, float) or image_price != 0
            ):
                zero = False
            if item.get("all_prices_zero") is False:
                zero = False
            if not suffix_free and item.get("all_prices_zero") is not True:
                zero = False
            modalities = item.get("output_modalities")
            if isinstance(modalities, (list, tuple, set)) and modalities:
                if not any(str(value).casefold() in {"text", "chat"} for value in modalities):
                    continue
            if require_tools:
                if "tools" not in _supported_parameters(item):
                    continue
                if not _modalities_include_text(item.get("input_modalities")):
                    continue
                if not _modalities_include_text(item.get("output_modalities")):
                    continue
            if zero and _openrouter_chat_row({}, route) and route not in out:
                out.append(route)
    return tuple(out)


def direct_models(*, opener: Callable, timeout: float, prices: Mapping[str, tuple],
                  secrets_loader: Optional[Callable[[str], str]] = None,
                  environ: Optional[Mapping[str, str]] = None) -> list[dict]:
    """The cheapest text models OpenAI and Google serve to this machine's keys.

    Ids come only from each vendor's own list-models answer; the price is
    OpenRouter's for the same vendor/id. A vendor with no key gives no rows.
    """
    from .model_router import ModelRouteRefused, discover_key

    items: list[dict] = []
    for vendor, family in (("openai", "openai"), ("google", "google")):
        try:
            key, _source = discover_key(family, environ=environ, secrets_loader=secrets_loader)
        except ModelRouteRefused:
            continue
        if vendor == "openai":
            data = _get_json(OPENAI_MODELS, headers={"Authorization": "Bearer " + key},
                             timeout=timeout, opener=opener)
            ids = [str(row.get("id")) for row in (data.get("data") or []) if isinstance(row, Mapping) and row.get("id")]
        else:
            data = _get_json(GOOGLE_MODELS + "?pageSize=1000", headers={"x-goog-api-key": key},
                             timeout=timeout, opener=opener)
            ids = [str(row.get("name", "")).split("/", 1)[-1] for row in (data.get("models") or [])
                   if isinstance(row, Mapping) and "generateContent" in (row.get("supportedGenerationMethods") or [])]
            # Gemma on this endpoint refuses system instructions; chat sends them.
            ids = [model_id for model_id in ids if model_id.startswith("gemini-")]
        priced = []
        for model_id in ids:
            price = prices.get("%s/%s" % (vendor, model_id))
            if price is not None and _text_chat_id(vendor, model_id):
                priced.append((price[0] + price[1], model_id, price))
        priced.sort()
        for _total, model_id, (prompt, completion) in priced[:DIRECT_PER_VENDOR]:
            items.append({
                "name": model_id, "route": "%s-api/%s" % (family, model_id), "vendor": vendor,
                "tag": "DIRECT", "ctx": "",
                "cost": "%s / %s per M" % (_money(prompt), _money(completion)),
                "col": _VENDOR_COLOURS.get(vendor, "#3a6acc"),
            })
    return items


def live_model_groups(session: Optional[Mapping[str, str]] = None, *, opener: Optional[Callable] = None,
                      timeout: float = 6.0, now: Optional[float] = None, force: bool = False) -> dict:
    """Groups for the picker, cached ten minutes; every source best effort."""
    opener = opener or urllib.request.urlopen
    moment = time.time() if now is None else now
    identity = _identity(session)
    with _lock:
        held = _cache["value"]
        if (not force and held is not None and _cache["identity"] == identity
                and 0 <= moment - float(_cache["at"]) < _CACHE_SECONDS):
            return copy.deepcopy(held)
    errors: dict[str, str] = {}
    notes: dict[str, str] = {}
    groups = []
    prices: dict = {}
    for name, fn in ((BYO_GROUP, lambda: openrouter_models(opener=opener, timeout=timeout, prices=prices)),
                     (LOCAL_GROUP, lambda: local_models(opener=opener, timeout=timeout)),
                     (SUBSCRIPTION_GROUP, lambda: subscription_cli_models())):
        failure = None
        try:
            items = fn()
        except Exception as exc:
            errors[name] = "%s: %s" % (type(exc).__name__, str(exc)[:120])
            failure, items = exc, []
        if items:
            groups.append({"name": name, "items": items})
        elif failure is not None:
            # A source that gave nothing says so where its rows would have
            # been. The group simply vanished before, so a refused cloud
            # sign-in looked exactly like a cloud with no models -- and the
            # one thing to do about it was never on screen.
            notes[name] = _source_note(name, failure)
    result = {"ok": True, "live": True, "groups": groups, "count": sum(len(g["items"]) for g in groups),
              "source_errors": errors, "source_notes": notes, "stale": False, "read_at": moment}
    with _lock:
        _cache["at"] = moment
        _cache["identity"] = identity
        _cache["value"] = copy.deepcopy(result)
    return result


def held_model_groups(session: Optional[Mapping[str, str]] = None, *, opener: Optional[Callable] = None,
                      timeout: float = 6.0, now: Optional[float] = None,
                      refresh_stale: bool = True) -> Optional[dict]:
    """The answer already held for THIS account, or None when there is none.

    Every open of the picker paid the whole three-source read, so the founder
    watched "Discovering models from connected providers..." each time. What
    is held is handed over at once instead. Past _FRESH_SECONDS it is handed
    over marked `stale` with its age, and a refresh runs behind it, so an
    answer on screen is never silently old and the next open draws new rows.
    None means nothing usable is held and the caller must read live.
    """
    moment = time.time() if now is None else now
    identity = _identity(session)
    with _lock:
        if _cache["value"] is None or _cache["identity"] != identity:
            return None
        age = moment - float(_cache["at"])
        if age < 0 or age >= _CACHE_SECONDS:
            return None
        answer = copy.deepcopy(_cache["value"])
    if age < _FRESH_SECONDS:
        return answer
    answer["stale"] = True
    answer["age_seconds"] = round(age, 1)
    answer["refreshing"] = (
        _start_refresh(session, identity, opener=opener, timeout=timeout, now=now)
        if refresh_stale else False
    )
    return answer


def held_model_groups_read_only(session: Optional[Mapping[str, str]] = None,
                                *, now: Optional[float] = None) -> Optional[dict]:
    """Read the held picker cache without starting a background source refresh."""
    return held_model_groups(session, now=now, refresh_stale=False)


def _start_refresh(session, identity: bytes, *, opener, timeout: float, now) -> bool:
    """Read the sources again behind an answer already given. One per account."""
    with _lock:
        if identity in _refreshing:
            return True
        _refreshing.add(identity)

    def read() -> None:
        try:
            live_model_groups(session, opener=opener, timeout=timeout, now=now, force=True)
        except Exception:  # noqa: BLE001
            pass
        finally:
            with _lock:
                _refreshing.discard(identity)

    threading.Thread(target=read, name="model-catalogue-refresh", daemon=True).start()
    return True


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
    if str(item.get("tag") or "").upper() == "BYO" and not route.startswith("openrouter/"):
        return "openrouter/" + route
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


def default_route_display_row(payload: Mapping[str, object], route: str,
                              source: str = "") -> Optional[dict]:
    """Return the display row for the server-selected default route.

    The catalogue row wins because it carries the provider's live name. The
    server fallback is deliberately here, beside model_router's default route
    contract, so Studio never has to name the free router itself.
    """
    route = str(route or "").strip()
    if not route:
        return None
    for group in payload.get("groups") or ():
        if not isinstance(group, Mapping):
            continue
        for item in group.get("items") or ():
            if not isinstance(item, Mapping):
                continue
            routed = str(item.get("routed") or item.get("route") or "").strip()
            if routed == route:
                return dict(item)
    if route == "openrouter/free":
        from .model_router import DEFAULT_FREE_ROUTE_ROW
        return dict(DEFAULT_FREE_ROUTE_ROW)
    return {
        "name": route,
        "route": route,
        "routed": route,
        "vendor": "Default",
        "tag": str(source or "default"),
        "ctx": "",
        "col": _VENDOR_COLOURS.get(_vendor(route), "#3a6acc"),
        "latency": None,
    }


def reset_cache() -> None:
    with _lock:
        _cache["at"] = 0.0
        _cache["value"] = None
        _cache["identity"] = None
        _refreshing.clear()


__all__ = ["live_model_groups", "held_model_groups", "held_model_groups_read_only",
           "cloud_models", "openrouter_models", "direct_models", "subscription_cli_models",
           "local_models", "routable_route", "groups_with_routes",
           "default_route_display_row", "reset_cache"]
