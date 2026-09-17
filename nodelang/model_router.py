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
import importlib.util
import base64
import hmac
import http.client
import os
import stat
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from contextlib import ExitStack
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

    def __init__(self, message, *, reason_code="response_refused"):
        super().__init__(message)
        self.reason_code = reason_code


@dataclass(frozen=True)
class ModelRoute:
    """One resolved destination: which family, which endpoint, which model."""

    family: str
    model: str
    url: str
    provider: str
    needs_key: bool


def _legacy_free_route(route: object) -> bool:
    text = str(route or "").strip()
    parts = text.split("/")
    return (len(parts) == 2 and all(parts) and text.endswith(":free")
            and not any(char.isspace() for char in text)
            and not any(text.startswith(prefix) for prefix in _FAMILY_PREFIXES))


def resolve_model_route(
    route: object, *, cloud_base_url: Optional[str] = None
) -> ModelRoute:
    """The chosen route as a destination, or a refusal naming what was wrong."""
    text = str(route or "").strip()
    if not text:
        raise ModelRouteRefused(
            "No model was chosen: pick one in the model picker, then ask again."
        )
    if text == "openrouter/free":
        return _destination("openrouter", text, cloud_base_url)
    for prefix, family in _FAMILY_PREFIXES.items():
        if text.startswith(prefix):
            model = text[len(prefix):].strip("/").strip()
            if not model:
                raise ModelRouteRefused(
                    "The route %r names %s but no model."
                    % (text, _PROVIDER_NAMES[family])
                )
            return _destination(family, model, cloud_base_url)
    # Existing sealed Workshop requests use this explicitly free OpenRouter
    # spelling. Preserve their identity; route_chat always enforces zero price.
    if _legacy_free_route(text):
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


_CREDENTIAL_LOCK = threading.RLock()
_CREDENTIAL_FILE_LIMIT = 1024 * 1024
_CREDENTIAL_DPAPI_MARK = b"ARCHHUB-DPAPI-1:"
_CREDENTIAL_ERRORS = {
    "invalid_credential": "Enter a raw OpenRouter key of 1 to 8192 ASCII characters without whitespace. Credential aliases are not supported here.",
    "secure_store_unavailable": "The Windows-protected credential store is unavailable. No save was confirmed.",
    "secure_store_invalid": "The existing credential store is not readable Windows-protected data. It was not replaced.",
    "secure_store_changed": "The credential store changed during saving. Refresh its status before retrying.",
    "save_not_admitted": "Credential saving is no longer authorized. Sign in again before retrying.",
    "save_unconfirmed": "The credential save could not be confirmed. Check provider status before retrying.",
    "invalid_social_credential": "Enter a social- vault entry name, linkedin or meta, its operator-declared account id and a raw ASCII token. Credential aliases are not supported here.",
    "social_entry_collision": "That vault entry already holds a credential that is not a social account record. It was not replaced.",
    "social_account_changed": "That vault entry is declared for another provider account. Enroll the new account under a new name.",
    "invalid_social_revocation": "Name a social- vault entry, linkedin or meta, and its declared account id to remove it locally.",
    "removal_not_admitted": "Credential removal is no longer authorized. Sign in again before retrying.",
    "removal_unconfirmed": "The credential removal could not be confirmed. Check its status before retrying.",
    "secure_store_busy": "Another ArchHub process is changing the credential store. Nothing was changed; retry shortly.",
}


class ProviderCredentialError(InvalidCell):
    """A fixed public error; storage/provider exception text must never escape."""

    def __init__(self, reason_code):
        self.reason_code = reason_code
        super().__init__(_CREDENTIAL_ERRORS[reason_code])


def _application_secrets_store():
    """Load credential code belonging to this application source or installation."""
    module_path = Path(__file__).resolve().parents[1] / "app" / "secrets_store.py"
    if not module_path.is_file():
        raise ProviderCredentialError("secure_store_unavailable")
    # Do not select another installed application's code or a cached `app`
    # package. The credential bytes still belong to the current Windows user.
    spec = importlib.util.spec_from_file_location("_archhub_application_secrets", module_path)
    if spec is None or spec.loader is None:
        raise ProviderCredentialError("secure_store_unavailable")
    store = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(store)
    return store


_CREDENTIAL_LOCK_MODULE = None


def _application_credential_lock():
    """This application's credential_lock.py beside its secrets_store.py, loaded once."""
    global _CREDENTIAL_LOCK_MODULE
    with _CREDENTIAL_LOCK:
        if _CREDENTIAL_LOCK_MODULE is None:
            module_path = Path(__file__).resolve().parents[1] / "app" / "credential_lock.py"
            spec = importlib.util.spec_from_file_location("_archhub_credential_lock", module_path)
            if spec is None or spec.loader is None:
                raise ProviderCredentialError("secure_store_unavailable")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            _CREDENTIAL_LOCK_MODULE = module
        return _CREDENTIAL_LOCK_MODULE


def _credential_file_bytes(path):
    """Bounded physical read; reject redirects before touching credential bytes."""
    for ancestor in (path, *path.parents):
        try:
            info = ancestor.lstat()
        except FileNotFoundError:
            # A fresh profile has no directory yet. Reads remain read-only;
            # still inspect every existing ancestor for redirected custody.
            continue
        if stat.S_ISLNK(info.st_mode) or (
            getattr(info, "st_file_attributes", 0)
            & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        ):
            raise ProviderCredentialError("secure_store_invalid")
    try:
        with path.open("rb") as stream:
            raw = stream.read(_CREDENTIAL_FILE_LIMIT + 1)
    except FileNotFoundError:
        return None
    if len(raw) > _CREDENTIAL_FILE_LIMIT:
        raise ProviderCredentialError("secure_store_invalid")
    return raw


def _credential_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ProviderCredentialError("secure_store_invalid")
        result[key] = value
    return result


def _protected_credential_entries(store, raw):
    if raw is None:
        return {}
    if not raw.startswith(_CREDENTIAL_DPAPI_MARK):
        raise ProviderCredentialError("secure_store_invalid")
    try:
        encrypted = base64.b64decode(raw[len(_CREDENTIAL_DPAPI_MARK):], validate=True)
        plain = store._dpapi(encrypted, protect=False)
        if len(plain) > _CREDENTIAL_FILE_LIMIT:
            raise ValueError
        entries = json.loads(plain.decode("utf-8"), object_pairs_hook=_credential_pairs)
        if type(entries) is not dict or any(type(key) is not str or type(value) is not str for key, value in entries.items()):
            raise ValueError
        return entries
    except Exception:
        raise ProviderCredentialError("secure_store_invalid") from None


def _mutate_protected_entries(mutate, *, before_replace=None, not_admitted="save_not_admitted",
                              unconfirmed="save_unconfirmed"):
    """The one protected secrets.dat mutation protocol; True when the file was replaced.

    mutate(entries) edits the decrypted entries in place and returns True to
    write them or False to leave the store untouched; it refuses by raising
    ProviderCredentialError. The protocol holds _CREDENTIAL_LOCK and the file's
    cross-process named mutex (app/credential_lock.py), uses this
    application's own secrets.dat and its existing DPAPI primitive, bounds the
    read and the payload to 1 MiB, stages an fsync'd task-owned temporary,
    refuses an observed outside change, runs the trusted owner's callback
    immediately before replacement, and confirms the replaced bytes. A failure
    after replacement began is reported unconfirmed; only the temporary is ever
    removed, never the destination or another writer's file.
    """
    if before_replace is not None and not callable(before_replace):
        raise TypeError("before_replace must be callable")
    if os.name != "nt":
        raise ProviderCredentialError("secure_store_unavailable")
    temporary = None
    replacement_attempted = False
    try:
        with _CREDENTIAL_LOCK, ExitStack() as exclusive:
            store = _application_secrets_store()
            path = Path(store.SECRETS_FILE)
            if not path.is_absolute() or path.name != "secrets.dat" or path.parent != Path(store.APP_DIR):
                raise ProviderCredentialError("secure_store_unavailable")
            exclusive.enter_context(_application_credential_lock().exclusive(
                path, wait_milliseconds=0,
                busy=lambda: ProviderCredentialError("secure_store_busy")))
            original = _credential_file_bytes(path)
            entries = _protected_credential_entries(store, original)
            if not mutate(entries):
                return False
            plain = json.dumps(entries, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
            if len(plain) > _CREDENTIAL_FILE_LIMIT:
                raise ProviderCredentialError("secure_store_invalid")
            encrypted = store._dpapi(plain, protect=True)
            payload = _CREDENTIAL_DPAPI_MARK + base64.b64encode(encrypted)
            if len(payload) > _CREDENTIAL_FILE_LIMIT:
                raise ProviderCredentialError("secure_store_invalid")
            # The app owner lock serializes admitted requests; this lock also
            # serializes direct calls in the process. Refuse observed outside
            # changes rather than overwriting a newer set of credentials.
            path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(mode="wb", dir=path.parent,
                    prefix=".archhub-secrets-", suffix=".tmp", delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            if _credential_file_bytes(path) != original:
                raise ProviderCredentialError("secure_store_changed")
            if before_replace is not None:
                try:
                    before_replace()
                except Exception:
                    raise ProviderCredentialError(not_admitted) from None
            replacement_attempted = True
            os.replace(temporary, path)
            temporary = None
            observed = _credential_file_bytes(path)
            if observed is None or not hmac.compare_digest(observed, payload):
                raise ProviderCredentialError(unconfirmed)
        return True
    except ProviderCredentialError:
        if replacement_attempted:
            raise ProviderCredentialError(unconfirmed) from None
        raise
    except Exception:
        raise ProviderCredentialError(
            unconfirmed if replacement_attempted else "secure_store_unavailable"
        ) from None
    finally:
        if temporary is not None:
            try:
                temporary.unlink()
            except OSError:
                # At worst an encrypted, task-owned temporary remains. Never
                # remove the destination or another writer's file on failure.
                pass


def save_provider_key(body, *, before_replace=None):
    """Physical save only; caller holds current browser/owner/policy admission.

    Use the existing store's DPAPI primitive, not a user-configurable keyring
    backend that might store plaintext. Only secrets.dat changes; no graph,
    settings registry, credential alias, provider call, or worker is created.
    The trusted owner's callback rechecks admission immediately before replacing
    the protected file; it is never taken from the request body.
    """
    if before_replace is not None and not callable(before_replace):
        raise TypeError("before_replace must be callable")
    if type(body) is not dict or set(body) != {"provider", "key"}:
        raise ProviderCredentialError("invalid_credential")
    key = body["key"]
    if type(body["provider"]) is not str or body["provider"] != "openrouter" or type(key) is not str or not 1 <= len(key) <= 8192 or (
        not key.isascii() or any(not 33 <= ord(char) <= 126 for char in key)
        or "://" in key or key.lower().startswith("inline:")
    ):
        raise ProviderCredentialError("invalid_credential")
    def put(entries):
        entries["openrouter"] = key
        return True

    _mutate_protected_entries(put, before_replace=before_replace)
    return {"ok": True, "provider": "openrouter", "state": "keyed", "source": "secrets store"}


def founder_secrets_key(name: str) -> str:
    """Read the selected runtime's protected entry before legacy key discovery."""
    if isinstance(name, str) and name.startswith("social-"):
        return ""
    try:
        with _CREDENTIAL_LOCK:
            store = _application_secrets_store()
            raw = _credential_file_bytes(Path(store.SECRETS_FILE))
            if raw is not None and raw.startswith(_CREDENTIAL_DPAPI_MARK):
                protected = _protected_credential_entries(store, raw).get(name)
                if protected:
                    return protected
            return str(store.load_api_key(name) or "")
    except Exception:
        return ""


def _secrets_listing_loader():
    """One read of the secrets store for a whole provider listing.

    A listing loaded the store module and decrypted its protected file once
    for every name it checked (2026-09-17). Here the store is loaded once and
    its protected entries decrypted once, under the credential lock; the
    returned loader answers each name from that read. Values never leave it
    except to the caller that asked for a name.
    """
    with _CREDENTIAL_LOCK:
        try:
            store = _application_secrets_store()
            raw = _credential_file_bytes(Path(store.SECRETS_FILE))
            protected = (
                _protected_credential_entries(store, raw)
                if raw is not None and raw.startswith(_CREDENTIAL_DPAPI_MARK)
                else {})
        except Exception:
            return lambda name: ""

    def load(name):
        if not isinstance(name, str) or name.startswith("social-"):
            return ""
        try:
            with _CREDENTIAL_LOCK:
                return protected.get(name) or str(store.load_api_key(name) or "")
        except Exception:
            return ""
    return load


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
              "anthropic": "Anthropic", "openai": "OpenAI", "google": "Google"}
    loader = _secrets_listing_loader() if secrets_loader is None else secrets_loader
    for family, plan in _KEY_PLAN.items():
        try:
            _key, source = discover_key(
                family, environ=environ, secrets_loader=loader,
                cloud_session=cloud_session)
            rows.append({"id": family, "name": labels.get(family, family.title()),
                         "state": "keyed", "source": source, "sets": plan["variable"]})
        except ModelRouteRefused:
            rows.append({"id": family, "name": labels.get(family, family.title()),
                         "state": "no key", "source": "", "sets": plan["variable"]})
    # Providers the graph registry admits (cell_model_providers) whose key
    # this machine holds. Their keys were stored with no row at all
    # (2026-09-17). The router has no direct route for them, so the row says
    # what reaching their models takes on this machine right now.
    from .cell_model_providers import ADMITTED_PROVIDERS
    through_openrouter = any(
        row["id"] == "openrouter" and row["state"] == "keyed" for row in rows)
    for name, description in ADMITTED_PROVIDERS.items():
        if name in _KEY_PLAN or not str(loader(name) or "").strip():
            continue
        rows.append({"id": name, "name": labels.get(name, description),
                     "state": "keyed, not routed", "sets": "",
                     "source": (
                         "key in the secrets store; no direct route in this build, "
                         "its models are reached through OpenRouter"
                         if through_openrouter else
                         "key in the secrets store; no direct route in this build; "
                         "add an OpenRouter key to reach these models")})
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


def _read_bounded_response(answer, limit: int) -> bytes:
    """Bound retained body bytes; socket timeout remains an I/O timeout only."""
    raw = bytearray()
    headers = getattr(answer, "headers", None)
    declared = headers.get("Content-Length") if headers is not None else None
    expected = None
    if declared is not None:
        if type(declared) is not str or not declared.isascii() or not declared.isdigit() or len(declared) > 20:
            raise ModelRouteRefused("The response length was invalid.", reason_code="response_incomplete")
        expected = int(declared)
        if expected > limit:
            raise ModelRouteRefused("The response exceeded its byte limit.", reason_code="response_too_large")
    read = getattr(answer, "read1", None)
    if not callable(read):
        read = answer.read
    try:
        while True:
            remaining = limit - len(raw)
            size = min(16 * 1024, remaining + 1)
            chunk = read(size)
            if type(chunk) is not bytes:
                raise ModelRouteRefused("The response body was not readable.", reason_code="response_incomplete")
            if len(chunk) > remaining or len(chunk) > size:
                raise ModelRouteRefused("The response exceeded its byte limit.", reason_code="response_too_large")
            if not chunk:
                if expected is not None and len(raw) != expected:
                    raise ModelRouteRefused("The response body did not complete.", reason_code="response_incomplete")
                return bytes(raw)
            raw.extend(chunk)
    except ModelRouteRefused:
        raise
    except TimeoutError:
        failure = ("The response body timed out.", "response_timeout")
    except urllib.error.URLError as error:
        failure = (("The response body timed out.", "response_timeout")
                   if isinstance(error.reason, TimeoutError)
                   else ("The response body was interrupted.", "response_incomplete"))
    except (http.client.HTTPException, OSError):
        failure = ("The response body was interrupted.", "response_incomplete")
    # Raise outside the handler: IncompleteRead.partial and provider exception
    # text must not remain in the propagated exception's cause or context.
    raise ModelRouteRefused(failure[0], reason_code=failure[1])


def _payload_from_event_stream(raw: bytes, *, require_complete: bool = False) -> dict:
    """One OpenAI-shaped payload assembled from an SSE chat stream."""
    pieces: list[str] = []
    finish = None
    metadata = {}
    complete = False
    for line in raw.decode("utf-8", errors="strict" if require_complete else "replace").splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        body = line[5:].strip()
        if require_complete and complete:
            raise ModelRouteRefused("The response stream has trailing events.", reason_code="response_incomplete")
        if body == "[DONE]":
            complete = True
            continue
        if not body:
            continue
        try:
            event = json.loads(body)
        except ValueError:
            if require_complete:
                raise ModelRouteRefused("The response stream contains an incomplete event.", reason_code="response_incomplete")
            continue
        if isinstance(event, Mapping):
            for name in ("model", "usage"):
                if name in event:
                    metadata[name] = event[name]
        choices = event.get("choices") if isinstance(event, Mapping) else None
        if not isinstance(choices, (list, tuple)) or not choices:
            continue
        first = choices[0] if isinstance(choices[0], Mapping) else {}
        delta = first.get("delta") if isinstance(first.get("delta"), Mapping) else None
        message = first.get("message") if isinstance(first.get("message"), Mapping) else None
        text = (delta or message or {}).get("content")
        if isinstance(text, str):
            pieces.append(text)
        if first.get("finish_reason"):
            finish = first["finish_reason"]
    if require_complete and (not complete or type(finish) is not str or not finish):
        raise ModelRouteRefused("The response stream did not complete.", reason_code="response_incomplete")
    return {**metadata, "choices": [{"message": {"role": "assistant", "content": "".join(pieces)}, "finish_reason": finish}]}


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
    free_only: bool = False,
    reasoning_effort: Optional[str] = None,
    response_byte_limit: Optional[int] = None,
    before_dispatch: Optional[Callable] = None,
) -> dict:
    """Send these messages to the provider this route names, and read its answer.

    response_byte_limit opts into bounded body reads and complete-response
    checks. It does not turn timeout into an absolute elapsed-time deadline.
    """
    if type(free_only) is not bool:
        raise ModelRouteRefused("free_only must be true or false.")
    if before_dispatch is not None and not callable(before_dispatch):
        raise ModelRouteRefused("The request dispatch guard is invalid.")
    free_only = free_only or _legacy_free_route(route)
    if response_byte_limit is not None and (
        type(response_byte_limit) is not int or not 1 <= response_byte_limit <= 1024 * 1024
    ):
        raise ModelRouteRefused("The response byte limit is invalid.")
    if free_only:
        # Refuse an incompatible route before looking up any credentials.
        session = None
        destination = resolve_model_route(route)
        parts = destination.model.split("/")
        explicit_free = (
            len(parts) == 2 and all(parts)
            and not any(char.isspace() for char in destination.model)
            and destination.model.endswith(":free")
        )
        if destination.family != "openrouter" or not (
            destination.model == "openrouter/free" or explicit_free
        ):
            raise ModelRouteRefused(
                "Free-only requests require openrouter/free or vendor/model:free."
            )
    else:
        session = (
            default_cloud_session() if cloud_session is _DISCOVER else cloud_session
        )
        base = None
        if isinstance(session, Mapping):
            base = str(session.get("base_url") or "") or None
        destination = resolve_model_route(route, cloud_base_url=base)
    if reasoning_effort is not None and (
        type(reasoning_effort) is not str
        or reasoning_effort not in {"none", "minimal", "low", "medium", "high", "xhigh"}
        or destination.family != "openrouter"
    ):
        raise ModelRouteRefused("This reasoning effort requires a supported OpenRouter route.")
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
    body = _body(destination, rows, max_tokens, temperature)
    if reasoning_effort is not None:
        body["reasoning"] = {"effort": reasoning_effort}
    if free_only:
        body["provider"] = {
            "max_price": {"prompt": 0, "completion": 0, "request": 0, "image": 0},
            "allow_fallbacks": False,
        }
    request = urllib.request.Request(
        destination.url,
        data=json.dumps(body).encode("utf-8"),
        method="POST",
        headers=headers,
    )
    send = urllib.request.urlopen if opener is None else opener
    if before_dispatch is not None:
        before_dispatch()
    try:
        with send(request, timeout=timeout) as answer:
            raw = answer.read() if response_byte_limit is None else _read_bounded_response(answer, response_byte_limit)
            headers = getattr(answer, "headers", None)
            kind = str(headers.get("Content-Type", "") if headers is not None else "")
            if "text/event-stream" in kind.casefold() or raw.lstrip().startswith(b"data:"):
                # The founder's cloud always streams (proxy.py: Server-Sent
                # Events); a reader that expected one JSON document saw the
                # cloud family as never answering (audit 2026-09-06).
                payload = _payload_from_event_stream(raw, require_complete=response_byte_limit is not None)
            else:
                payload = json.loads(raw.decode("utf-8"))
    except ModelRouteRefused:
        raise
    except urllib.error.HTTPError as refused:
        if refused.code == 429:
            # The status is sufficient. Do not expose provider bodies or retry
            # a user turn merely because a different route might answer.
            refused.close()
            raise ModelRouteRefused(
                "The model provider is rate-limiting requests (HTTP 429). Wait before sending again, or choose another model.",
                reason_code="provider_rate_limited") from refused
        if response_byte_limit is not None:
            # A complete HTTP refusal is known; an oversized/interrupted body
            # stays uncertain. Never expose provider body text in this path.
            try:
                _read_bounded_response(refused, min(response_byte_limit, 4096))
            finally:
                refused.close()
            raise ModelRouteRefused("The provider refused the request: HTTP %s." % refused.code) from refused
        detail = ""
        try:
            detail = refused.read().decode("utf-8", errors="replace").strip()[:240]
        except Exception:
            detail = ""
        raise ModelRouteRefused(
            "%s refused this request: HTTP %s%s. Check the key or pick another "
            "model." % (destination.provider, refused.code, (": " + detail) if detail else "")
        ) from refused
    except (urllib.error.URLError, OSError) as unreachable:
        if response_byte_limit is not None:
            timed_out = isinstance(unreachable, TimeoutError) or isinstance(
                getattr(unreachable, "reason", None), TimeoutError)
            raise ModelRouteRefused("The provider request did not return a response.",
                reason_code="dispatch_timeout" if timed_out else "dispatch_transport_uncertain") from unreachable
        raise ModelRouteRefused(
            "%s is not answering at %s. Start it, or pick another model."
            % (destination.provider, _host_of(destination.url))
        ) from unreachable
    except ValueError as unreadable:
        if response_byte_limit is not None:
            raise ModelRouteRefused("The response was not complete JSON.", reason_code="response_incomplete") from unreadable
        raise ModelRouteRefused(
            "%s did not answer with JSON." % destination.provider
        ) from unreadable
    choices = payload.get("choices") if isinstance(payload, Mapping) else None
    first = choices[0] if isinstance(choices, (list, tuple)) and choices else None
    if response_byte_limit is not None and (
        not isinstance(first, Mapping) or type(first.get("finish_reason")) is not str or not first["finish_reason"]
    ):
        raise ModelRouteRefused("The response has no completion marker.", reason_code="response_incomplete")
    message = first.get("message") if isinstance(first, Mapping) else None
    if (isinstance(message, Mapping) and not message.get("content")
            and first.get("finish_reason") == "length"):
        raise ModelRouteRefused(
            "The model used its output budget before returning an answer.",
            reason_code="output_truncated")
    text = _answer_text(destination, payload)
    if not text.strip():
        raise ModelRouteRefused("The model returned an empty answer.", reason_code="empty_answer")
    usage = payload.get("usage") if isinstance(payload, Mapping) else None
    if not isinstance(usage, Mapping):
        usage = None
    if free_only and usage is not None and "cost" in usage:
        cost = usage["cost"]
        # Strict type plus equality rejects booleans, NaN and infinities too.
        if type(cost) not in (int, float) or cost != 0:
            raise ModelRouteRefused("The free-only request reported an invalid or nonzero cost.",
                reason_code="invalid_cost")
    return {
        "ok": True,
        "text": text,
        "family": destination.family,
        "model": destination.model,
        "actual_model": payload.get("model") if isinstance(payload, Mapping) else None,
        "url": destination.url,
        "provider": destination.provider,
        "key_source": key_source,
        "usage": usage,
        "finish_reason": first.get("finish_reason") if isinstance(first, Mapping) else None,
    }


__all__ = [
    "CLOUD_CHAT_PATH",
    "LM_STUDIO_CHAT",
    "ModelRoute",
    "ModelRouteRefused",
    "ProviderCredentialError",
    "OLLAMA_CHAT",
    "OPENROUTER_CHAT",
    "default_cloud_session",
    "discover_key",
    "founder_secrets_key",
    "resolve_model_route",
    "route_chat",
    "save_provider_key",
]


def protected_credential_entry(name: str) -> str:
    """One entry of this runtime's DPAPI-protected secrets.dat and nothing else.

    No environment variable, keyring backend, credential alias or legacy
    obfuscated file is consulted, and no provider_meta breadcrumb is written.
    """
    if type(name) is not str or not name:
        raise ProviderCredentialError("secure_store_unavailable")
    with _CREDENTIAL_LOCK:
        store = _application_secrets_store()
        path = Path(store.SECRETS_FILE)
        if path.name != "secrets.dat" or path.parent != Path(store.APP_DIR):
            raise ProviderCredentialError("secure_store_invalid")
        raw = _credential_file_bytes(path)
        value = _protected_credential_entries(store, raw).get(name)
    if type(value) is not str or not value:
        raise ProviderCredentialError("secure_store_unavailable")
    return value


_SOCIAL_CREDENTIAL_FORMAT = "archhub-social-credential-1"
_SOCIAL_ENTRY_PREFIX = "social-"


def _social_record(value):
    """The social account record held in one protected value, or None if it is not one."""
    try:
        record = json.loads(value, object_pairs_hook=_credential_pairs)
    except Exception:
        return None
    if (type(record) is not dict or set(record) != {"format", "provider", "account_id", "token"}
            or record["format"] != _SOCIAL_CREDENTIAL_FORMAT
            or any(type(item) is not str for item in record.values())):
        return None
    return record


def save_social_credential(body, *, before_replace=None):
    """Enroll one operator-declared social account record in the protected store.

    The physical protocol is save_provider_key's: the existing DPAPI primitive on
    this runtime's secrets.dat, _CREDENTIAL_LOCK, refusal of an observed outside
    change, the trusted owner's before_replace recheck immediately before
    replacement, and confirmation afterwards. The account id is declared by the
    enrolling operator; nothing here asks the provider, so the record is never
    provider-verified identity. A name already holding a non-social credential
    is refused, and an existing record is replaced only for the same provider
    account (token rotation). No graph, settings index, alias or worker changes.
    """
    from .social_connectors import _GRAPH_ID, _LINKEDIN_PERSON, _VAULT_ENTRY

    if before_replace is not None and not callable(before_replace):
        raise TypeError("before_replace must be callable")
    if type(body) is not dict or set(body) != {"vault_entry", "provider", "account_id", "token"}:
        raise ProviderCredentialError("invalid_social_credential")
    name, provider, account_id, token = body["vault_entry"], body["provider"], body["account_id"], body["token"]
    if (type(name) is not str or not name.startswith(_SOCIAL_ENTRY_PREFIX) or not _VAULT_ENTRY.fullmatch(name)
            or type(provider) is not str or provider not in ("linkedin", "meta")
            or type(account_id) is not str
            or not (_LINKEDIN_PERSON if provider == "linkedin" else _GRAPH_ID).fullmatch(account_id)
            or type(token) is not str or not 1 <= len(token) <= 16384
            or any(not 33 <= ord(char) <= 126 for char in token)
            or "://" in token or token.lower().startswith("inline:")):
        raise ProviderCredentialError("invalid_social_credential")
    value = json.dumps({"format": _SOCIAL_CREDENTIAL_FORMAT, "provider": provider,
                        "account_id": account_id, "token": token},
                       separators=(",", ":"), sort_keys=True, ensure_ascii=True)
    def put(entries):
        if name in entries:
            existing = _social_record(entries[name])
            if existing is None:
                raise ProviderCredentialError("social_entry_collision")
            if (existing["provider"], existing["account_id"]) != (provider, account_id):
                raise ProviderCredentialError("social_account_changed")
        entries[name] = value
        return True

    _mutate_protected_entries(put, before_replace=before_replace)
    return {"ok": True, "vault_entry": name, "provider": provider, "account_id": account_id,
            "account_binding": "operator-declared", "state": "enrolled", "source": "secrets store"}


def revoke_social_credential(body, *, before_replace=None):
    """Remove one operator-declared social account record from local protected custody.

    Local removal only: the provider token is not revoked at LinkedIn or Meta and
    nothing is sent anywhere, so the result always reports
    provider_token_revoked False. The request names the exact provider account;
    a stored record for another account, or a name holding a non-social value,
    is refused. A missing entry is an idempotent no-op: no rewrite and no owner
    callback. The same protected mutation protocol as saves preserves every
    other entry, and the owner's callback rechecks admission before replacement.
    """
    from .social_connectors import _GRAPH_ID, _LINKEDIN_PERSON, _VAULT_ENTRY

    if before_replace is not None and not callable(before_replace):
        raise TypeError("before_replace must be callable")
    if type(body) is not dict or set(body) != {"vault_entry", "provider", "account_id"}:
        raise ProviderCredentialError("invalid_social_revocation")
    name, provider, account_id = body["vault_entry"], body["provider"], body["account_id"]
    if (type(name) is not str or not name.startswith(_SOCIAL_ENTRY_PREFIX) or not _VAULT_ENTRY.fullmatch(name)
            or type(provider) is not str or provider not in ("linkedin", "meta")
            or type(account_id) is not str
            or not (_LINKEDIN_PERSON if provider == "linkedin" else _GRAPH_ID).fullmatch(account_id)):
        raise ProviderCredentialError("invalid_social_revocation")

    def remove(entries):
        if name not in entries:
            return False
        existing = _social_record(entries[name])
        if existing is None:
            raise ProviderCredentialError("social_entry_collision")
        if (existing["provider"], existing["account_id"]) != (provider, account_id):
            raise ProviderCredentialError("social_account_changed")
        entries.pop(name)
        return True

    removed = _mutate_protected_entries(remove, before_replace=before_replace,
                                        not_admitted="removal_not_admitted", unconfirmed="removal_unconfirmed")
    return {"ok": True, "vault_entry": name, "provider": provider, "account_id": account_id,
            "state": "removed" if removed else "absent", "provider_token_revoked": False,
            "source": "secrets store"}
