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
CLOUD_GROUP = "CLOUD · subscription"
BYO_GROUP = "BYO · OpenRouter"
LOCAL_GROUP = "LOCAL · this machine"
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
    for name, fn in ((CLOUD_GROUP, lambda: cloud_models(session, opener=opener, timeout=timeout)),
                     (BYO_GROUP, lambda: openrouter_models(opener=opener, timeout=timeout)),
                     (LOCAL_GROUP, lambda: local_models(opener=opener, timeout=timeout))):
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
        elif name == CLOUD_GROUP and not (session and session.get("token")):
            notes[name] = CLOUD_ABSENT_NOTE
    result = {"ok": True, "live": True, "groups": groups, "count": sum(len(g["items"]) for g in groups),
              "source_errors": errors, "source_notes": notes, "stale": False, "read_at": moment}
    with _lock:
        _cache["at"] = moment
        _cache["identity"] = identity
        _cache["value"] = copy.deepcopy(result)
    return result


def held_model_groups(session: Optional[Mapping[str, str]] = None, *, opener: Optional[Callable] = None,
                      timeout: float = 6.0, now: Optional[float] = None) -> Optional[dict]:
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
    answer["refreshing"] = _start_refresh(session, identity, opener=opener, timeout=timeout, now=now)
    return answer


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


def reset_cache() -> None:
    with _lock:
        _cache["at"] = 0.0
        _cache["value"] = None
        _cache["identity"] = None
        _refreshing.clear()


__all__ = ["live_model_groups", "held_model_groups", "cloud_models", "openrouter_models",
           "local_models", "routable_route", "groups_with_routes", "reset_cache"]
