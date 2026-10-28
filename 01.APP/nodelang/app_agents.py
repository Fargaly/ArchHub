"""Approved agent faces over existing owners; no store, launcher or channel.

The HTTP owner supplies its existing WorkshopTransport and native BABOOM
host. Environment is server-owned. Native settings never cross this boundary.
"""
from __future__ import annotations

import inspect
import os
import re
import time


CLIENTS = {"claude": "claude-code", "claude-code": "claude-code", "codex": "codex",
           "opencode": "opencode", "gemini": "gemini-cli", "gemini-cli": "gemini-cli"}
APPS = ("claude", "codex", "opencode", "antigravity", "antigravity-ide")
FUNCTIONS = frozenset({"getAgentChannel", "installAgentChannel", "previewAgentChannel",
                       "repairAgentChannel", "listAgentSessions", "getDesktopCompanion"})


def _client(value):
    if type(value) is not str or value not in CLIENTS:
        raise ValueError("Choose an existing supported agent client")
    return CLIENTS[value]


def _label(value, limit=256):
    return "".join(c for c in value if c.isprintable())[:limit] if type(value) is str else ""


class AgentsAPI:
    def __init__(self, *, transport, companion=None, environment=None, registration=None, settings=None):
        if registration is None:
            from . import assistant_registration as registration
        self.registration = registration
        self.transport = transport
        self.companion = companion
        self.settings = settings
        self.environment = dict(os.environ if environment is None else environment)

    def getAgentChannel(self, id):
        client = _client(id)
        rows = self.registration.readiness(environment=self.environment)["clients"]
        row = next((item for item in rows if item["client"] == client), None)
        if row is None:
            raise RuntimeError("The installed registration owner did not report this client")
        hooks = row.get("hooks", {})
        return {"client": client, "state": _label(row.get("state")),
                "connection": "not_checked", "activationPending": False,
                "hooks": {"available": hooks.get("available") is True,
                          "state": _label(hooks.get("state")),
                          "events": [{"event": _label(item.get("event")),
                                      "state": _label(item.get("state"))}
                                     for item in hooks.get("events", [])]}}

    def installAgentChannel(self, id):
        client = _client(id)
        if client == "gemini-cli":
            raise ValueError("Gemini uses the reviewed hook repair on this surface")
        result = self.registration.register(client, consent=True, environment=self.environment)
        report = self.getAgentChannel(client)
        registered = {"registered", "registered_with_project_overrides"}
        return {**report, "activationPending": result.get("state") in registered
                and report["state"] in registered}

    def previewAgentChannel(self, id):
        client = _client(id)
        preview = self.registration.preview_hooks(client, environment=self.environment)
        return {"client": client, "plan_digest": preview["plan_digest"],
                "changed": preview["changed"], "events": list(preview["events"]),
                "description": "Connect ArchHub's existing end-of-turn check; keep other settings."}

    def repairAgentChannel(self, id, digest):
        client = _client(id)
        if type(digest) is not str or not re.fullmatch(r"[a-f0-9]{64}", digest):
            raise ValueError("Review the current agent-channel changes first")
        result = self.registration.repair_hooks(client, consent=True, plan_digest=digest,
                                                environment=self.environment)
        return {**self.getAgentChannel(client),
                "activationPending": result.get("activation_pending") is True}

    def listAgentSessions(self):
        if self.transport is None:
            raise RuntimeError("The application's existing Workshop transport is unavailable")
        discovered = self.transport.discover(apps=list(APPS))
        if discovered.get("status") != "ok" or type(discovered.get("recipients")) is not list:
            raise RuntimeError("Workshop discovery did not complete; refresh before choosing a session")
        sessions = []
        for row in discovered["recipients"]:
            if (type(row) is not dict or row.get("app") not in APPS
                    or type(row.get("id")) is not str or not row["id"]):
                raise RuntimeError("Workshop returned a session without an identity")
            sessions.append({"app": row["app"], "id": row["id"],
                             "title": _label(row.get("title"))})
        # Discovery is routing evidence. It is never sign-in or delivery proof.
        statuses = discovered.get("providers", {})
        return {"sessions": sessions, "adapters": {
            app: _label(value if type(value) is str else value.get("status"))
            for app, value in statuses.items() if app in APPS and isinstance(value, (str, dict))},
            "truncated": discovered.get("truncated") is True,
            "completeApps": [app for app in discovered.get("complete_apps", []) if app in APPS]}

    def getDesktopCompanion(self, *, now=None):
        preferences = {"companion": self.settings.companionState()} if self.settings is not None else {}
        host = self.companion
        if host is None:
            raise RuntimeError("The native companion owner has not been bound to this view")
        if not host.running:
            return {**preferences, "status": "not_running", "message": "Desktop companion is stopped."}
        frame = host.latest_snapshot
        if frame is None:
            return {**preferences, "status": "awaiting_frame", "message": "Waiting for the native companion's first frame."}
        now = time.time() if now is None else now
        current = now < min(frame.presence_expires_at, frame.frame_expires_at)
        return {**preferences, "status": "current" if current else "expired", "revision": frame.revision,
                "message": _label(frame.directive.get("compact_message"), 4000) if current else
                           "The native companion frame expired; waiting for its owner.",
                "motion": _label(frame.directive.get("motion")) if current else "idle"}


def dispatch(api, body, *, guard):
    """Call only from the authenticated owner's existing route and mutation lock."""
    if (type(body) is not dict or set(body) != {"action", "function", "args"}
            or body["action"] != "agent-channel" or type(body["function"]) is not str
            or body["function"] not in FUNCTIONS or type(body["args"]) is not list):
        raise ValueError("Invalid agent surface request")
    function = getattr(api, body["function"])
    try:
        inspect.signature(function).bind(*body["args"])
    except TypeError:
        raise ValueError("Invalid agent surface arguments") from None
    guard()
    result = function(*body["args"])
    guard()
    return {"ok": True, "result": result}
