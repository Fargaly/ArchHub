"""Where the model the founder picked actually goes.

The picker offered four families -- the founder's ArchHub cloud, OpenRouter,
LM Studio and Ollama on this machine -- and every one of them posted to the
one hardcoded OpenRouter URL and came back answering as gpt-4o. Picking a
local model still spent OpenRouter credit; picking a cloud model never
reached the cloud. Nothing on screen said so.

This module is the router that was missing. One function takes the route
string the picker holds and the messages, and sends them to the endpoint that
route names, in that provider's payload shape, with that provider's key. A
provider that is not running, and a key that is nowhere on this machine, come
back as one short sentence the composer can show. Never a substitution.

The wire shape is the ordinary OpenAI chat-completions one for the cloud,
OpenRouter and LM Studio (LM Studio serves it verbatim); Ollama has its own
/api/chat body and answer field, so it gets its own reader.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Optional, Sequence

from .universal_cell import InvalidCell

OPENROUTER_CHAT = "https://openrouter.ai/api/v1/chat/completions"
LM_STUDIO_CHAT = "http://127.0.0.1:1234/v1/chat/completions"
OLLAMA_CHAT = "http://127.0.0.1:11434/api/chat"
CLOUD_CHAT_PATH = "/v1/chat/completions"

_FAMILY_PREFIXES = {
    "lmstudio/": "lmstudio",
    "ollama/": "ollama",
    "cloud/": "cloud",
    "openrouter/": "openrouter",
}
_PROVIDER_NAMES = {
    "lmstudio": "LM Studio",
    "ollama": "Ollama",
    "cloud": "the ArchHub cloud",
    "openrouter": "OpenRouter",
}
# Ordered key discovery, written out per family so the refusal can name the
# exact thing a person has to set. A colleague on a fresh install had none of
# these and the composer failed with nothing on screen at all.
_KEY_PLAN = {
    "openrouter": {
        "variable": "OPENROUTER_API_KEY",
        "secret": "openrouter",
        "from_cloud_session": False,
        "missing": (
            "No OpenRouter key on this machine: set OPENROUTER_API_KEY, or "
            "save an openrouter key in the ArchHub secrets store, then ask "
            "again."
        ),
    },
    "cloud": {
        "variable": "ARCHHUB_CLOUD_TOKEN",
        "secret": "archhub-cloud",
        "from_cloud_session": True,
        "missing": (
            "No ArchHub cloud session on this machine: sign in to the ArchHub "
            "cloud, or set ARCHHUB_CLOUD_TOKEN, then ask again."
        ),
    },
}
_DISCOVER = object()


class ModelRouteRefused(InvalidCell):
    """One short sentence about why no answer came, fit to show a person."""


@dataclass(frozen=True)
class ModelRoute:
    """One resolved destination: which family, which endpoint, which model."""

    family: str
    model: str
    url: str
    provider: str
    needs_key: bool


def resolve_model_route(
    route: object, *, cloud_base_url: Optional[str] = None
) -> ModelRoute:
    """The chosen route as a destination, or a refusal naming what was wrong."""
    text = str(route or "").strip()
    if not text:
        raise ModelRouteRefused(
            "No model was chosen: pick one in the model picker, then ask again."
        )
    for prefix, family in _FAMILY_PREFIXES.items():
        if text.startswith(prefix):
            model = text[len(prefix):].strip("/").strip()
            if not model:
                raise ModelRouteRefused(
                    "The route %r names %s but no model."
                    % (text, _PROVIDER_NAMES[family])
                )
            return _destination(family, model, cloud_base_url)
    # A bare "vendor/model" is exactly what an OpenRouter id looks like, and
    # exactly what the picker's BYO rows carry.
    parts = [part for part in text.split("/") if part.strip()]
    if len(parts) == 2 and "/" in text:
        return _destination("openrouter", text, cloud_base_url)
    raise ModelRouteRefused(
        "The model route %r names no provider this app can reach: use "
        "cloud/, openrouter/, lmstudio/ or ollama/." % text
    )


def _destination(
    family: str, model: str, cloud_base_url: Optional[str]
) -> ModelRoute:
    if family == "lmstudio":
        return ModelRoute(family, model, LM_STUDIO_CHAT, "LM Studio", False)
    if family == "ollama":
        return ModelRoute(family, model, OLLAMA_CHAT, "Ollama", False)
    if family == "openrouter":
        return ModelRoute(family, model, OPENROUTER_CHAT, "OpenRouter", True)
    base = str(cloud_base_url or _default_cloud_base()).rstrip("/")
    return ModelRoute(
        family, model, base + CLOUD_CHAT_PATH, "the ArchHub cloud", True
    )


def _default_cloud_base() -> str:
    from .cloud_relay import DEFAULT_BASE  # noqa: PLC0415

    return DEFAULT_BASE


def founder_secrets_key(name: str) -> str:
    """The founder's own secrets store, when the production sibling is here.

    A colleague's install has no sibling repository at all, so this is a
    source that is allowed to be absent, never an import that can fail a turn.
    """
    configured = os.environ.get("ARCHHUB_PRODUCTION_ROOT")
    production = (
        Path(configured)
        if configured
        else Path(__file__).resolve().parents[2] / "12.PRODUCTION"
    )
    if not production.is_dir():
        return ""
    if str(production) not in sys.path:
        sys.path.insert(0, str(production))
    try:
        from app import secrets_store  # noqa: PLC0415

        return str(secrets_store.load_api_key(name) or "")
    except Exception:
        return ""


def discover_key(
    family: str,
    *,
    environ: Optional[Mapping[str, str]] = None,
    secrets_loader: Optional[Callable[[str], str]] = None,
    cloud_session: Optional[Mapping[str, object]] = None,
) -> tuple:
    """Environment, then the founder's secrets store, then the cloud session.

    Returns the key and the name of the place it came from, so a person can
    be told which one answered.
    """
    plan = _KEY_PLAN.get(family)
    if plan is None:
        return "", "not required"
    values = os.environ if environ is None else environ
    loader = founder_secrets_key if secrets_loader is None else secrets_loader
    from_environment = str(values.get(plan["variable"], "") or "").strip()
    if from_environment:
        return from_environment, "environment"
    from_store = str(loader(plan["secret"]) or "").strip()
    if from_store:
        return from_store, "secrets store"
    if plan["from_cloud_session"] and cloud_session:
        from_session = str(cloud_session.get("token") or "").strip()
        if from_session:
            return from_session, "cloud session"
    raise ModelRouteRefused(plan["missing"])


def provider_rows(*, environ=None, secrets_loader=None, cloud_session=None,
                  local_probe=None) -> list:
    """What each provider really is on this machine: keyed or not, running or not.

    The studio's Providers tab showed 'ant-****e2af  $23.84 this month' and
    friends: invented keys and invented spend, typed into a fixture. Nothing
    here is invented. A cloud provider is 'keyed' with the place the key came
    from, or 'no key'. A local runtime is 'running' or 'not running'. There is
    no spend figure because nothing on this machine measures one.
    """
    rows = []
    labels = {"openrouter": "OpenRouter", "cloud": "ArchHub cloud",
              "anthropic": "Anthropic", "openai": "OpenAI"}
    for family, plan in _KEY_PLAN.items():
        try:
            _key, source = discover_key(
                family, environ=environ, secrets_loader=secrets_loader,
                cloud_session=cloud_session)
            rows.append({"id": family, "name": labels.get(family, family.title()),
                         "state": "keyed", "source": source, "sets": plan["variable"]})
        except ModelRouteRefused:
            rows.append({"id": family, "name": labels.get(family, family.title()),
                         "state": "no key", "source": "", "sets": plan["variable"]})
    probe = local_probe
    if probe is None:
        def probe(host, port):
            import socket
            s = socket.socket()
            s.settimeout(0.4)
            try:
                return s.connect_ex((host, int(port))) == 0
            except Exception:
                return False
            finally:
                s.close()
    for family, name, port in (("lmstudio", "LM Studio", 1234), ("ollama", "Ollama", 11434)):
        rows.append({"id": family, "name": name,
                     "state": "running" if probe("127.0.0.1", port) else "not running",
                     "source": "127.0.0.1:%d" % port, "sets": ""})
    return rows


def default_cloud_session() -> Optional[dict]:
    """The founder's recorded cloud session, or nothing on a machine without one."""
    appdata = os.environ.get("APPDATA", "")
    if not appdata:
        return None
    try:
        from .cloud_relay import load_cloud_session  # noqa: PLC0415

        return load_cloud_session(Path(appdata))
    except Exception:
        return None


def _checked_messages(messages: object) -> list:
    rows = list(messages or ())
    if not rows:
        raise ModelRouteRefused("There was nothing to send to the model.")
    checked = []
    for row in rows:
        if not isinstance(row, Mapping) or not row.get("content"):
            raise ModelRouteRefused(
                "A message for the model must carry a role and content."
            )
        content = row["content"]
        if isinstance(content, (list, tuple)):
            # A message with parts: text and images, the OpenAI shape every
            # non-ollama family here speaks. Each part must say what it is.
            parts = []
            for part in content:
                if not isinstance(part, Mapping) or part.get("type") not in ("text", "image_url"):
                    raise ModelRouteRefused(
                        "A message part must be text or an image_url."
                    )
                parts.append(dict(part))
            if not parts:
                raise ModelRouteRefused("A message with parts must carry at least one.")
            content = parts
        else:
            content = str(content)
        checked.append({
            "role": str(row.get("role") or "user"),
            "content": content,
        })
    return checked


def _carries_an_image(messages: Sequence) -> bool:
    for row in messages:
        content = row.get("content") if isinstance(row, Mapping) else None
        if isinstance(content, list) and any(
            isinstance(part, Mapping) and part.get("type") == "image_url" for part in content
        ):
            return True
    return False


def _body(
    destination: ModelRoute,
    messages: Sequence,
    max_tokens: int,
    temperature: float,
) -> dict:
    if destination.family == "ollama":
        if _carries_an_image(messages):
            raise ModelRouteRefused(
                "An ollama route cannot carry an image in this build; pick a "
                "vision model on openrouter or the cloud."
            )
        return {
            "model": destination.model,
            "messages": list(messages),
            "stream": False,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }
    return {
        "model": destination.model,
        "messages": list(messages),
        "max_tokens": max_tokens,
        "temperature": temperature,
    }


def _answer_text(destination: ModelRoute, payload: object) -> str:
    if isinstance(payload, Mapping):
        if destination.family == "ollama":
            message = payload.get("message")
            if isinstance(message, Mapping) and message.get("content") is not None:
                return str(message["content"])
        else:
            choices = payload.get("choices")
            if isinstance(choices, (list, tuple)) and choices:
                first = choices[0]
                if isinstance(first, Mapping):
                    message = first.get("message")
                    if (
                        isinstance(message, Mapping)
                        and message.get("content") is not None
                    ):
                        return str(message["content"])
    raise ModelRouteRefused(
        "%s answered in a shape this app does not read." % destination.provider
    )


def _host_of(url: str) -> str:
    rest = url.split("//", 1)[-1]
    return rest.split("/", 1)[0]


def route_chat(
    route: object,
    messages: object,
    *,
    max_tokens: int = 900,
    temperature: float = 0.0,
    timeout: float = 60.0,
    opener: Optional[Callable] = None,
    environ: Optional[Mapping[str, str]] = None,
    secrets_loader: Optional[Callable[[str], str]] = None,
    cloud_session: object = _DISCOVER,
) -> dict:
    """Send these messages to the provider this route names, and read its answer."""
    session = (
        default_cloud_session() if cloud_session is _DISCOVER else cloud_session
    )
    base = None
    if isinstance(session, Mapping):
        base = str(session.get("base_url") or "") or None
    destination = resolve_model_route(route, cloud_base_url=base)
    rows = _checked_messages(messages)
    headers = {"Content-Type": "application/json"}
    key_source = "not required"
    if destination.needs_key:
        key, key_source = discover_key(
            destination.family,
            environ=environ,
            secrets_loader=secrets_loader,
            cloud_session=session if isinstance(session, Mapping) else None,
        )
        headers["Authorization"] = "Bearer " + key
    request = urllib.request.Request(
        destination.url,
        data=json.dumps(
            _body(destination, rows, max_tokens, temperature)
        ).encode("utf-8"),
        method="POST",
        headers=headers,
    )
    send = urllib.request.urlopen if opener is None else opener
    try:
        with send(request, timeout=timeout) as answer:
            payload = json.loads(answer.read().decode("utf-8"))
    except urllib.error.HTTPError as refused:
        raise ModelRouteRefused(
            "%s refused this request: HTTP %s. Check the key or pick another "
            "model." % (destination.provider, refused.code)
        ) from refused
    except (urllib.error.URLError, OSError) as unreachable:
        raise ModelRouteRefused(
            "%s is not answering at %s. Start it, or pick another model."
            % (destination.provider, _host_of(destination.url))
        ) from unreachable
    except ValueError as unreadable:
        raise ModelRouteRefused(
            "%s did not answer with JSON." % destination.provider
        ) from unreadable
    return {
        "ok": True,
        "text": _answer_text(destination, payload),
        "family": destination.family,
        "model": destination.model,
        "url": destination.url,
        "provider": destination.provider,
        "key_source": key_source,
    }


__all__ = [
    "CLOUD_CHAT_PATH",
    "LM_STUDIO_CHAT",
    "ModelRoute",
    "ModelRouteRefused",
    "OLLAMA_CHAT",
    "OPENROUTER_CHAT",
    "default_cloud_session",
    "discover_key",
    "founder_secrets_key",
    "resolve_model_route",
    "route_chat",
]
