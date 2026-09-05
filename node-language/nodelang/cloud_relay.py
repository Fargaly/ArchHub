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
import urllib.request
from pathlib import Path
from typing import Callable, Mapping, Optional

CLAIM_PATH = "/founder/api/agent-tasks/claim"
RESULT_PATH = "/founder/api/agent-tasks/%s/result"
MAP_PATH = "/founder/map-state"
DEFAULT_BASE = "https://api.archhub.io"
APP_KINDS = ("app", "app-execute")


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
    base = str(held.get("cloud_base_url") or DEFAULT_BASE).rstrip("/")
    return {"token": str(token), "base_url": base}


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
        self.last_error: str = ""
        self.answered = 0
        self._map_digest = ""
        self._map_pushed_at = 0.0

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
        claimed = self._call(CLAIM_PATH, {"claimed_by": self.claimed_by, "kinds": list(APP_KINDS)})
        task = claimed.get("task")
        if not isinstance(task, Mapping) or not task.get("id"):
            return None
        utterance = str(task.get("directive") or "").strip()
        try:
            if task.get("kind") == "app-execute":
                result = self.execute(utterance)
            else:
                result = self.respond(utterance)
            ok, text = True, render_answer(result)
        except Exception as exc:  # the refusal IS the answer; never a silent drop
            ok, text = False, "%s: %s" % (type(exc).__name__, exc)
        self._call(RESULT_PATH % str(task["id"]), {"ok": ok, "result": text[:8000]})
        self.answered += 1
        return {"task": str(task["id"]), "ok": ok, "result": text}

    def push_map(self, *, force: bool = False, min_interval: float = 60.0) -> Optional[dict]:
        """Re-publish the live projection when it changed (or on demand)."""
        if self.map_script is None:
            return None
        now = time.monotonic()
        if not force and now - self._map_pushed_at < min_interval:
            return None
        script = self.map_script()
        body = script.split("window.ATLAS_MAP = ", 1)[1].rsplit("; window.ATLAS_LIVE", 1)[0]
        body = self._with_control(body)
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
        """
        try:
            model = json.loads(body)
        except ValueError:
            return body
        control: dict[str, object] = {"agents": [], "work_summary": "", "work_items": [], "hosts": []}
        try:
            agents = self.respond("agents")
            answer = agents.get("response") if isinstance(agents.get("response"), Mapping) else agents
            control["agents"] = list(((answer.get("data") or {}).get("agents") or []))[:24]
        except Exception:
            pass
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
        try:
            rows = self.hosts() if callable(self.hosts) else []
            control["hosts"] = [
                {"id": str(r.get("id") or ""), "name": str(r.get("name") or ""), "state": str(r.get("state") or ""), "detail": str(r.get("detail") or "")[:120]}
                for r in (rows or []) if isinstance(r, Mapping)
            ][:40]
        except Exception:
            pass
        if isinstance(model, dict):
            model["control"] = control
            return json.dumps(model, separators=(",", ":"))
        return body

    def run_forever(self, *, interval: float = 4.0, stop: Optional[threading.Event] = None) -> None:
        stop = stop or threading.Event()
        while not stop.is_set():
            try:
                worked = self.poll_once()
                self.last_error = ""
                if worked is not None:
                    continue  # drain the queue before sleeping
                self.push_map()
            except Exception as exc:
                self.last_error = "%s: %s" % (type(exc).__name__, exc)
            stop.wait(interval)


def start_cloud_relay(
    *,
    appdata: Path,
    state_dir: Path,
    respond: Callable[[str], Mapping[str, object]],
    execute: Callable[[str], Mapping[str, object]],
    map_script: Optional[Callable[[], str]] = None,
    hosts: Optional[Callable[[], object]] = None,
) -> Optional[CloudRelay]:
    """Start the relay thread when the founder's session and consent exist."""
    from .cloud_publish_consent import cloud_publish_allowed

    if not cloud_publish_allowed(state_dir):
        return None
    session = load_cloud_session(appdata)
    if session is None:
        return None
    relay = CloudRelay(
        base_url=session["base_url"], token=session["token"],
        respond=respond, execute=execute, map_script=map_script, hosts=hosts,
    )
    threading.Thread(target=relay.run_forever, name="archhub-cloud-relay", daemon=True).start()
    return relay


__all__ = [
    "CloudRelay", "load_cloud_session", "render_answer", "start_cloud_relay",
    "CLAIM_PATH", "RESULT_PATH", "MAP_PATH",
]
