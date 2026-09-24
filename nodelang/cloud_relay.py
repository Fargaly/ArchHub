"""The founder's application drains the cockpit.

The cockpit (api.archhub.io/founder) is the map, the map is the graph, and the
graph lives here, in the running application. When the founder types into the
cockpit's ask bar the cloud queues his instruction; this relay claims it, puts
it to BABOOM exactly as if he had typed it into the companion, and posts
BABOOM's answer back. It also re-publishes the live map projection so the
cockpit keeps showing what the application actually holds.

Nothing runs without the founder's cloud session (cloud.json token) and his
recorded cloud-publish consent; without both the relay is inert.
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable, Mapping, Optional

CLAIM_PATH = "/founder/api/agent-tasks/claim"
RESULT_PATH = "/founder/api/agent-tasks/%s/result"
MAP_PATH = "/founder/map-state"
DEFAULT_BASE = "https://api.archhub.io"
# The ONLY hosts a cloud session bearer is ever sent to. cloud.json is editable
# by anyone at the machine, so a base it names outside these is ignored and the
# one address is used. Every cloud reader goes through pinned_cloud_base().
PINNED_BASES = ("https://api.archhub.io", "https://archhub-cloud.fly.dev")
APP_KINDS = ("app", "app-execute")
OFFER_KEYS = ("revision", "sha256", "availability", "pricing_visible", "public_label")


def pinned_cloud_base(value: object) -> str:
    """The cloud base a bearer may go to: a pinned host, else the one address."""
    base = str(value or "").strip().rstrip("/")
    return base if base in PINNED_BASES else DEFAULT_BASE


def load_cloud_session(appdata: Path) -> Optional[dict]:
    """The founder's cloud session as the brain recorded it, or None."""
    cloud = Path(appdata) / "ArchHub" / "brain" / "cloud.json"
    if not cloud.is_file():
        return None
    try:
        held = json.loads(cloud.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    token = held.get("token") if isinstance(held, Mapping) else None
    if not token:
        return None
    return {"token": str(token), "base_url": pinned_cloud_base(held.get("cloud_base_url"))}


def cockpit_url(appdata: Path) -> str:
    """The cockpit address for THIS machine, opened on the app's own session.

    One hand-off, written once in cloud_signin.cockpit_link: the app spends
    its session for a one-time claim link. With no usable session the plain
    address is returned; the cloud's page there says to open the cockpit
    from the app, and never offers a sign-in of its own.
    """
    from . import cloud_signin

    record = Path(appdata) / "ArchHub" / "brain" / "cloud.json"
    link = cloud_signin.cockpit_link(record)
    if link.get("ok"):
        return str(link["url"])
    return cloud_signin.pinned_base(cloud_signin.read_cloud_session(record)) + "/founder"


def published_offer_form(value: object) -> Optional[dict]:
    """The offer as its one published record, or None when nothing valid is declared.

    Only the five published keys travel; the rest of the record stays in the app.
    """
    if not isinstance(value, Mapping) or any(key not in value for key in OFFER_KEYS):
        return None
    digest = value["sha256"]
    if type(value["revision"]) is not int or not isinstance(digest, str) or len(digest) != 64:
        return None
    if not isinstance(value["availability"], str) or not isinstance(value["public_label"], str):
        return None
    if type(value["pricing_visible"]) is not bool:
        return None
    return {key: value[key] for key in OFFER_KEYS}


# What a person can actually do about a sign-in the cloud refuses or this
# machine never had. The model picker's cloud group says exactly this, so it
# is written once and read from here.
SIGN_IN_AGAIN = "Sign in again under Settings, Account."
MODEL_LIMIT = 40
# The cloud refuses an expired or revoked sign-in with 401 (API) or 403 (founder routes). The relay then
# asks again only this often, instead of every poll: on 2026-09-17 it had asked every ~5 s for four days.
REFUSED_BACKOFF = 300.0


def published_models_form(value: object) -> Optional[dict]:
    """The models and routing the app publishes for the cockpit, or None.

    This is the contract the router publishes into, through CloudRelay(models=...):

        {"models": [{"name": str, "provider": str, "available": bool}, ...],
         "routes": [{"task": str, "model": str}, ...]}      # routes may be omitted

    name is 1-80 characters and unique; provider is 1-40; task is 1-40 and unique; a
    route's model names a published model; at most 40 of each. Only those keys travel,
    so no key, endpoint or price leaves the app with them. Anything else makes the whole
    value invalid: the cockpit then says the list is not published, never half a list.
    """
    def text(item, key, limit):
        field = item.get(key) if isinstance(item, Mapping) else None
        return field if isinstance(field, str) and 0 < len(field.strip()) and len(field) <= limit else None

    if not isinstance(value, Mapping):
        return None
    models, routes = value.get("models"), value.get("routes", [])
    if not isinstance(models, list) or not isinstance(routes, list):
        return None
    if len(models) > MODEL_LIMIT or len(routes) > MODEL_LIMIT:
        return None
    published = []
    for item in models:
        name, provider = text(item, "name", 80), text(item, "provider", 40)
        if name is None or provider is None or type(item.get("available")) is not bool:
            return None
        published.append({"name": name, "provider": provider, "available": item["available"]})
    names = [m["name"] for m in published]
    if len(set(names)) != len(names):
        return None
    routing = []
    for item in routes:
        task, model = text(item, "task", 40), text(item, "model", 80)
        if task is None or model not in names:
            return None
        routing.append({"task": task, "model": model})
    if len({r["task"] for r in routing}) != len(routing):
        return None
    return {"models": published, "routes": routing}


def render_answer(result: Mapping[str, object]) -> str:
    """One founder-readable text from a BABOOM response or execution payload."""
    body = result.get("response") if isinstance(result.get("response"), Mapping) else result
    kind = str(body.get("kind") or result.get("kind") or "")
    summary = str(body.get("summary") or result.get("summary") or "").strip()
    data = body.get("data") if isinstance(body.get("data"), Mapping) else {}
    lines = [summary] if summary else []
    for key, value in list(data.items())[:12]:
        if key in ("requires", "command"):
            continue
        if isinstance(value, (str, int, float, bool)):
            lines.append("%s: %s" % (key, value))
        elif isinstance(value, (list, tuple)):
            items = []
            for item in list(value)[:10]:
                if isinstance(item, Mapping):
                    items.append(str(
                        item.get("title") or item.get("session")
                        or item.get("session_root") or item.get("provider")
                        or json.dumps(item, sort_keys=True)[:80]))
                else:
                    items.append(str(item))
            if items:
                lines.append("%s: %s" % (key, "; ".join(items)))
        elif isinstance(value, Mapping):
            lines.append("%s: %s" % (key, json.dumps(value, sort_keys=True)[:300]))
    if data.get("requires"):
        lines.append("Untick 'Confirm before any change' in the cockpit to make BABOOM act.")
    text = "\n".join(lines).strip()
    return text or (kind or "no answer")


class CloudRelay:
    """Claim cockpit instructions, answer them through BABOOM, post the answer."""

    def __init__(
        self,
        *,
        base_url: str,
        token: str,
        respond: Callable[[str], Mapping[str, object]],
        execute: Callable[[str], Mapping[str, object]],
        claimed_by: str = "archhub-app",
        opener: Optional[Callable[..., object]] = None,
        timeout: float = 20.0,
        map_script: Optional[Callable[[], str]] = None,
        hosts: Optional[Callable[[], object]] = None,
        offer: Optional[Callable[[], object]] = None,
        offer_command: Optional[Callable[[str, bool], object]] = None,
        models: Optional[Callable[[], object]] = None,
        session_loader: Optional[Callable[[], Optional[Mapping[str, str]]]] = None,
        session_path: Optional[Path] = None,
        consent: Optional[Callable[[], bool]] = None,
    ) -> None:
        self.base_url = str(base_url).rstrip("/")
        self.token = str(token)
        self.respond = respond
        self.execute = execute
        self.claimed_by = claimed_by
        self.opener = opener or urllib.request.urlopen
        self.timeout = float(timeout)
        self.map_script = map_script
        self.hosts = hosts
        self.offer = offer
        self.offer_command = offer_command
        self.models = models
        self.session_loader = session_loader
        self.session_path = session_path
        # Settings > Account withdraws cloud publish consent by deleting its
        # record; the relay reads it before every claim and stops for good.
        self.consent = consent
        self.last_error: str = ""
        self.answered = 0
        self._map_digest = ""
        self._map_pushed_at = 0.0
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lifecycle_lock = threading.Lock()

    def start(self) -> "CloudRelay":
        """Start the one worker whose lifetime this relay owns."""
        with self._lifecycle_lock:
            if self._stop.is_set() or self._thread is not None:
                raise RuntimeError("cloud relay cannot be started again")
            self._thread = threading.Thread(
                target=self.run_forever, name="archhub-cloud-relay", daemon=True,
            )
            self._thread.start()
        return self

    def request_stop(self) -> None:
        self._stop.set()

    def close(self, *, timeout_seconds: float = 6.0) -> None:
        """Return only once the owned worker can no longer touch its graph."""
        timeout = float(timeout_seconds)
        if not 0 <= timeout <= 30:
            raise ValueError("cloud relay shutdown timeout must be within 30 seconds")
        self.request_stop()
        with self._lifecycle_lock:
            worker = self._thread
        if worker is None:
            return
        if worker is threading.current_thread():
            raise RuntimeError("cloud relay cannot join its own worker")
        worker.join(timeout=timeout)
        if worker.is_alive():
            raise TimeoutError("cloud relay worker is still active; graph close is unsafe")

    def _request(self, path: str, body: Optional[bytes], *, method: str = "POST") -> dict:
        request = urllib.request.Request(
            self.base_url + path, data=body, method=method,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Authorization": "Bearer " + self.token,
            },
        )
        with self.opener(request, timeout=self.timeout) as answer:
            payload = json.loads(answer.read().decode("utf-8"))
        return payload if isinstance(payload, dict) else {"raw": payload}

    def _call(self, path: str, body: Mapping[str, object]) -> dict:
        return self._request(path, json.dumps(body).encode("utf-8"))

    def poll_once(self) -> Optional[dict]:
        """Claim one instruction, answer it, post the answer. None when idle."""
        if self._stop.is_set():
            return None  # stopping: claim nothing new
        if callable(self.consent) and not self.consent():
            self._stop.set()
            self.last_error = "cloud publish consent withdrawn; relay stopped"
            return None
        claimed = self._call(CLAIM_PATH, {"claimed_by": self.claimed_by, "kinds": list(APP_KINDS)})
        task = claimed.get("task")
        if not isinstance(task, Mapping) or not task.get("id"):
            return None
        utterance = str(task.get("directive") or "").strip()
        execute = task.get("kind") == "app-execute"
        handled = None
        try:
            # The offer is one record in this application, so its command is
            # answered from that record here and never handed to BABOOM.
            if callable(self.offer_command):
                handled = self.offer_command(utterance, execute)
            if handled is not None:
                result = handled
            elif execute:
                result = self.execute(utterance)
            else:
                result = self.respond(utterance)
            ok, text = True, render_answer(result)
        except Exception as exc:  # the refusal IS the answer; never a silent drop
            ok, text = False, "%s: %s" % (type(exc).__name__, exc)
        self._call(RESULT_PATH % str(task["id"]), {"ok": ok, "result": text[:8000]})
        self.answered += 1
        if ok and isinstance(handled, Mapping) and handled.get("kind") == "offer-updated":
            # Republish at once, so the cockpit states the changed offer.
            try:
                self.push_map(force=True)
            except Exception as exc:
                self.last_error = "%s: %s" % (type(exc).__name__, exc)
        return {"task": str(task["id"]), "ok": ok, "result": text}

    def push_map(self, *, force: bool = False, min_interval: float = 60.0) -> Optional[dict]:
        """Re-publish the live projection when it changed (or on demand)."""
        if self._stop.is_set() or self.map_script is None:
            return None
        now = time.monotonic()
        if not force and now - self._map_pushed_at < min_interval:
            return None
        script = self.map_script()
        if self._stop.is_set():
            return None
        body = script.split("window.ATLAS_MAP = ", 1)[1].rsplit("; window.ATLAS_LIVE", 1)[0]
        body = self._with_control(body)
        if self._stop.is_set():
            return None
        digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
        self._map_pushed_at = now
        if not force and digest == self._map_digest:
            return None
        answer = self._request(MAP_PATH, body.encode("utf-8"))
        self._map_digest = digest
        return answer

    def _with_control(self, body: str) -> str:
        """Add the CONTROL block the cockpit's domain panel drives from.

        The cockpit is the map and the map is the graph -- and the founder
        controls the graph through BABOOM. So the control block IS BABOOM's
        own answers, read the same way he would: the agents on this machine,
        the governed work, the hosts and their states. Best effort: a silent
        brain or coordination host leaves the field empty, never breaks the push.
        The declared offer travels beside it; an undeclared offer sends no key.
        """
        try:
            model = json.loads(body)
        except ValueError:
            return body
        control: dict[str, object] = {"agents": [], "work_summary": "", "work_items": [], "hosts": []}
        if self._stop.is_set():
            return body
        try:
            agents = self.respond("agents")
            answer = agents.get("response") if isinstance(agents.get("response"), Mapping) else agents
            control["agents"] = list(((answer.get("data") or {}).get("agents") or []))[:24]
        except Exception:
            pass
        if self._stop.is_set():
            return body
        try:
            work = self.respond("show governed work")
            answer = work.get("response") if isinstance(work.get("response"), Mapping) else work
            control["work_summary"] = str(answer.get("summary") or "")[:400]
            data = answer.get("data") if isinstance(answer.get("data"), Mapping) else {}
            items = data.get("items") or data.get("work") or []
            if isinstance(items, list):
                control["work_items"] = [
                    {
                        "title": str((it.get("title") if isinstance(it, Mapping) else it) or "")[:80],
                        "state": str((it.get("state") or it.get("status")) if isinstance(it, Mapping) else "")[:24],
                        "agent": str(it.get("agent") or "")[:40] if isinstance(it, Mapping) else "",
                    }
                    for it in items[:12]
                ]
        except Exception:
            pass
        if self._stop.is_set():
            return body
        try:
            rows = self.hosts() if callable(self.hosts) else []
            control["hosts"] = [
                {"id": str(r.get("id") or ""), "name": str(r.get("name") or ""), "state": str(r.get("state") or ""), "detail": str(r.get("detail") or "")[:120]}
                for r in (rows or []) if isinstance(r, Mapping)
            ][:40]
        except Exception:
            pass
        if callable(self.models) and not self._stop.is_set():
            # No key when the app publishes nothing valid: the cockpit tells "not published"
            # apart from a published empty list.
            try:
                published = published_models_form(self.models())
            except Exception:
                published = None
            if published is not None:
                control["models"] = published["models"]
                control["routes"] = published["routes"]
        offer = None
        if callable(self.offer) and not self._stop.is_set():
            try:
                offer = published_offer_form(self.offer())
            except Exception:
                offer = None
        if isinstance(model, dict):
            model["control"] = control
            if offer is not None:
                model["offer"] = offer
            return json.dumps(model, separators=(",", ":"))
        return body

    def run_forever(self, *, interval: float = 4.0, stop: Optional[threading.Event] = None) -> None:
        stop = stop or self._stop
        while not self._stop.is_set() and not stop.is_set():
            try:
                worked = self.poll_once()
                self.last_error = ""
                if self._stop.is_set() or stop.is_set():
                    break
                if worked is not None:
                    continue  # drain the queue before sleeping
                self.push_map()
            except urllib.error.HTTPError as exc:
                if exc.code in (401, 403):
                    stop.wait(self._after_session_refused(exc))
                    continue
                self.last_error = "%s: %s" % (type(exc).__name__, exc)
            except Exception as exc:
                self.last_error = "%s: %s" % (type(exc).__name__, exc)
            stop.wait(interval)

    def _after_session_refused(self, exc: urllib.error.HTTPError) -> float:
        """The cloud refused this machine's sign-in; return how long to wait before asking again.

        A token lives 90 days on the cloud and cannot be revived. When the founder has signed in
        again, the record on this machine carries a new token: take it and ask at once. Otherwise
        say what to do, never the token, and slow down.
        """
        fresh = None
        if callable(self.session_loader):
            try:
                fresh = self.session_loader()
            except Exception:
                fresh = None
        token = fresh.get("token") if isinstance(fresh, Mapping) else None
        if token and str(token) != self.token:
            self.token = str(token)
            self.base_url = str(fresh.get("base_url") or self.base_url).rstrip("/")
            self.last_error = "cloud sign-in renewed from this machine"
            return 0.0
        self.last_error = (
            "the cloud refused this machine's sign-in (HTTP %d): it expired or was revoked. "
            % exc.code) + SIGN_IN_AGAIN
        if self.session_path is not None:
            # Settings > Account reads this record. A 401 is a refused session;
            # a founder route's 403 may only mean another account, so /v1/me
            # decides before the record says "sign-in expired".
            from .cloud_signin import confirm_with_cloud, record_refusal
            try:
                if exc.code == 401:
                    record_refusal(self.session_path, self.token)
                else:
                    confirm_with_cloud(self.session_path)
            except OSError:
                pass
        return REFUSED_BACKOFF


def start_cloud_relay(
    *,
    appdata: Path,
    state_dir: Path,
    respond: Callable[[str], Mapping[str, object]],
    execute: Callable[[str], Mapping[str, object]],
    map_script: Optional[Callable[[], str]] = None,
    hosts: Optional[Callable[[], object]] = None,
    offer: Optional[Callable[[], object]] = None,
    offer_command: Optional[Callable[[str, bool], object]] = None,
    models: Optional[Callable[[], object]] = None,
) -> Optional[CloudRelay]:
    """Start the relay thread when the founder's session and consent exist.

    Consent is the signed-in account's own (cloud_publish_consent): after a
    sign-out or an account switch the relay does not start, and a running one
    stops at its next poll.
    """
    from .cloud_publish_consent import cloud_publish_allowed
    from .cloud_session import signed_in_cloud_account

    session_path = Path(appdata) / "ArchHub" / "brain" / "cloud.json"

    def consented() -> bool:
        return cloud_publish_allowed(state_dir, signed_in_cloud_account(session_path))

    if not consented():
        return None
    session = load_cloud_session(appdata)
    if session is None:
        return None
    relay = CloudRelay(
        base_url=session["base_url"], token=session["token"],
        respond=respond, execute=execute, map_script=map_script, hosts=hosts,
        offer=offer,
        offer_command=offer_command,
        models=models,
        session_loader=lambda: load_cloud_session(appdata),
        session_path=session_path,
        consent=consented,
    )
    return relay.start()


__all__ = [
    "CloudRelay", "PINNED_BASES", "load_cloud_session", "pinned_cloud_base",
    "published_models_form", "published_offer_form",
    "render_answer",
    "start_cloud_relay",
    "CLAIM_PATH", "RESULT_PATH", "MAP_PATH",
]
