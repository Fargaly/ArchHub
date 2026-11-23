"""Invite to watch (D-047): one named account sees one saved session, read-only, while the owner's app shares it.

The owner right-clicks a Home session and invites a signed-in account. The grant lives in the cloud
(/v1/watch-grants, owner-scoped; never an office role). This module is the app side:

* project(document) builds the only thing a watcher ever receives. It is fail closed: it carries no
  free-form text from the document (no titles, params, notes, properties, results' strings or error
  messages), only product-defined engine labels, safe ids, positions, a fixed status vocabulary and
  numeric result shapes. Anything else is dropped, not scrubbed.
* invite/stop/list call the owner's cloud session (cloud_call); a cloud without these routes answers
  404, which keeps the Home menu disabled with its reason.
* push(...) runs on the existing cloud relay cycle: only active grants this account owns, only while
  the session stays in a registered workspace whose privacy is "Internal". The cloud refuses a
  projection older than 30 s, so a closed app or a stopped share goes stale on its own.
Local metadata (grant id -> session file) is account preferences, never the .archhub file.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

SAFE_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")
GRANT_ID = re.compile(r"[A-Za-z0-9_-]{8,128}")
EMAIL = re.compile(r"[^@\s]{1,64}@[^@\s]{1,190}\.[^@\s]{2,63}")
# The session's own node result vocabulary (session_files run engine) -> the watch vocabulary.
STATUSES = {"done": "done", "error": "failed", "skipped": "skipped", "blocked": "blocked", "stopped": "stopped",
            "disabled": "disabled", "waiting": "waiting", "waiting for approval": "approval",
            "unconfirmed": "unconfirmed", "retry requested": "retry", "out of date": "stale", "running": "running"}
# Last pushed digest per (owner account, grant): survives the relay's fresh owner object every cycle and
# never crosses accounts, so an account switch starts over with a full projection.
_DIGESTS = {}
SHARE_TIER = "Internal"
MAX_NODES = 10000
ENDS = ("stop", "1h", "today")
UNAVAILABLE = "Read-only watcher invitations are unavailable."
# How often a watcher's view re-reads: well inside the cloud's 30 s freshness window. Ended views stop.
WATCH_NODE = {"id": "watch.view", "params": {"poll_ms": 3000}}


def has_local_shares(account_file):
    """True when any account preferences in this file hold a watch share (a cheap read, no cloud call)."""
    try:
        data = json.loads(Path(account_file).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(data, dict) and any(isinstance(v, dict) and v.get("watchSessions") for v in data.values())


SKILL_LABEL = "Skill"


def _user_skill(engine):
    return engine == "skill" or engine.startswith("skill.")


def engine_labels():
    """Product-authored card titles by engine id, from the static Library tables only.

    Never the assembled catalogue: that loads the user's saved skills and Canvases (load_skills), whose
    titles are user text. Every skill engine gets the generic SKILL_LABEL instead (see project).
    """
    from .library_engines import LIBRARY_ITEM_ENGINES, LIBRARY_PRESENTATION
    titles = {row[0]: row[1] for _category, rows in LIBRARY_PRESENTATION for row in rows}
    labels = {}
    for item, wiring in dict(LIBRARY_ITEM_ENGINES).items():
        engine = wiring.get("engine") if isinstance(wiring, dict) else None
        if isinstance(engine, str) and item in titles and engine not in labels and not _user_skill(engine):
            labels[engine] = titles[item]
    return labels


def _number(value):
    return type(value) in (int, float) and math.isfinite(value) and abs(value) < 1e12


def _result_shape(result):
    """Typed facts only: the status vocabulary, an error flag, list sizes and plain numbers. No strings."""
    if not isinstance(result, dict):
        return None, None
    status = result.get("status")
    status = (STATUSES.get(status.strip().lower(), "unknown") if isinstance(status, str)
              else ("unknown" if status is not None else None))
    shape = {}
    if "error" in result and result.get("error"):
        shape["error"] = True
    items = sum(len(value) for value in result.values() if isinstance(value, list))
    if items:
        shape["items"] = items
    if _number(result.get("count")) and not isinstance(result.get("count"), bool):
        shape["count"] = result["count"]
    return status, shape or None


def project(document, labels):
    """The watcher view of one session. Raises ValueError for a document that is not a session."""
    if not isinstance(document, dict) or document.get("format") != "archhub" or not isinstance(document.get("nodes"), list):
        raise ValueError("Only a saved ArchHub session can be watched.")
    nodes = document["nodes"][:MAX_NODES]
    ids, out = {}, []
    for index, node in enumerate(nodes):
        if not isinstance(node, dict):
            continue
        # Every node gets an opaque projection-only id; the document's ids (often user-authored) never leave.
        raw, safe = node.get("id"), "n%d" % index
        if isinstance(raw, str) and raw not in ids:
            ids[raw] = safe
        engine = node.get("type")
        if isinstance(engine, str) and _user_skill(engine):
            row = {"id": safe, "engine": "skill", "label": SKILL_LABEL}  # a user skill's own name never leaves
        else:
            label = labels.get(engine) if isinstance(engine, str) and not _user_skill(engine) else None
            row = {"id": safe, "engine": engine if label else "step", "label": label or "Step"}
        position = node.get("position")
        if isinstance(position, dict) and _number(position.get("x")) and _number(position.get("y")):
            row["position"] = {"x": position["x"], "y": position["y"]}
        status, shape = _result_shape(node.get("result"))
        row["status"] = status or "pending"
        if shape:
            row["result"] = shape
        out.append(row)
    wires = []
    for wire in document.get("wires") or []:
        try:
            a, b = ids.get(wire["from"]["node"]), ids.get(wire["to"]["node"])
        except (KeyError, TypeError):
            continue
        if a and b:
            wires.append([a, b])
    groups = []
    for group in document.get("groups") or []:
        children = [ids[c] for c in (group.get("children") or []) if isinstance(c, str) and c in ids] if isinstance(group, dict) else []
        if children:
            groups.append({"children": children})
    return {"schema": "archhub-watch/v1", "nodes": out, "wires": wires, "groups": groups}


def _expiry(ends, now):
    if ends not in ENDS:
        raise ValueError("Choose when watching ends: when you stop it, after 1 hour, or at the end of today.")
    if ends == "stop":
        return None  # live while this app shares it; the cloud refuses a projection older than 30 s
    if ends == "1h":
        moment = now + timedelta(hours=1)
    else:
        local = now.astimezone()
        moment = local.replace(hour=23, minute=59, second=59, microsecond=0)
    return moment.astimezone(timezone.utc).isoformat()


def _workshop_task_session(task):
    """The session file the Workshop task row owns; the owner's strictly read-only lookup."""
    from .workshop_tasks import bound_session_path
    return bound_session_path(task)


def _active(grant, now):
    if not isinstance(grant, dict) or grant.get("revoked_at"):
        return False
    expires = grant.get("expires_at")
    if expires:
        try:
            return datetime.fromisoformat(str(expires).replace("Z", "+00:00")) > now
        except ValueError:
            return False
    return True


class WatchGrants:
    """App side of watching, bound to the signed-in owner's account and preferences."""

    def __init__(self, *, cloud, account, workspace, policy, read_prefs, save_prefs, labels=engine_labels,
                 read_document=None, clock=None, sessions=None, task_session=None):
        from .session_files import read_document as default_read, sessions_directory
        self.cloud, self.account, self.workspace, self.policy = cloud, account, workspace, policy
        self.read_prefs, self.save_prefs = read_prefs, save_prefs
        self.labels = labels
        self.read_document = read_document or default_read
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.sessions = sessions or sessions_directory
        self.task_session = task_session or _workshop_task_session

    # -- eligibility ---------------------------------------------------------------------------
    def _eligible(self, session_path):
        """The saved session, its id and root, or ValueError: a Home task session that is the Workshop
        task's own bound file in the app's sessions folder with an explicitly assigned registered project,
        or a file inside its registered project folder; either way the root must be Internal."""
        if type(session_path) is not str or not session_path.strip():
            raise ValueError("Save this session first.")
        path = Path(session_path).resolve()
        document = self.read_document(str(path))
        identity = document.get("id")
        if not isinstance(identity, str) or not SAFE_ID.fullmatch(identity):
            raise ValueError("This session has no saved identity. Save it again, then retry.")
        properties = document.get("properties") or {}
        if path.parent == Path(self.sessions()).resolve():
            # A Home task: only the file its Workshop task owns counts (a copied file's claims grant nothing),
            # and only an explicitly assigned project; a legacy project label never grants sharing.
            context = properties.get("taskContext") if isinstance(properties.get("taskContext"), dict) else {}
            bound = self.task_session(context.get("task"))
            if not bound or Path(bound).resolve() != path:
                raise ValueError("This file is not a Home task's own session; open the task and invite from there.")
            root_id = properties["project"] if "project" in properties else context.get("workspace")
            if not isinstance(root_id, str) or not root_id:
                raise ValueError("Choose a project for this session before inviting a watcher.")
            self.workspace(root_id)  # raises for an unknown or unregistered root
        else:
            root_id = properties.get("project")
            if not isinstance(root_id, str) or not root_id:
                raise ValueError("Move this session into a registered project folder before inviting a watcher.")
            root = self.workspace(root_id)  # raises for an unknown or unregistered root
            try:
                path.relative_to(Path(root["path"]).resolve())
            except ValueError:
                raise ValueError("This session file is outside its project folder; it cannot be watched.") from None
        if self.policy(root_id) != SHARE_TIER:
            raise ValueError("Set this project's privacy to Internal to let someone watch it. "
                             "Confidential and Secret work is never shared.")
        return document, identity, str(path)

    # -- owner actions -------------------------------------------------------------------------
    def capability(self):
        from .settings_owner import CloudRouteUnavailable
        try:
            grants = self.cloud("GET", "/v1/watch-grants").get("grants", [])
        except CloudRouteUnavailable:
            return {"capability": False, "reason": UNAVAILABLE, "grants": []}
        except ValueError as refused:
            return {"capability": False, "reason": str(refused), "grants": []}
        now, sessions = self.clock(), self.read_prefs().get("watchSessions", {})
        rows = [{"id": g.get("id"), "grantee": g.get("grantee_email"), "expires": g.get("expires_at"),
                 "session": sessions.get(g.get("id"), {}).get("path", ""), "active": _active(g, now)}
                for g in grants if isinstance(g, dict) and GRANT_ID.fullmatch(str(g.get("id", "")))]
        return {"capability": True, "reason": "", "grants": rows}

    def invite(self, session_path, email, ends):
        me = self.account()
        if type(email) is not str or not EMAIL.fullmatch(email.strip()):
            raise ValueError("Enter the watcher's email address.")
        email = email.strip().lower()
        if email == str(me.get("email", "")).lower():
            raise ValueError("You already see your own session; invite someone else.")
        _document, identity, path = self._eligible(session_path)
        expires = _expiry(ends, self.clock())
        grant = self.cloud("POST", "/v1/watch-grants", {"session_id": identity, "session_file_id": identity,
                                                        "grantee_email": email, "expires_at": expires}).get("grant")
        if not isinstance(grant, dict) or not GRANT_ID.fullmatch(str(grant.get("id", ""))) or grant.get("session_id") != identity:
            raise ValueError("The cloud did not confirm the invitation. Nothing is shared.")
        held = {"path": path, "session_id": identity}
        try:
            # The account and the project's tier may have changed while the grant was being created.
            if self.account().get("user_id") != me.get("user_id"):
                raise ValueError("Your account changed while inviting. Nothing is shared.")
            self._push_one(grant["id"], held, owner=me.get("user_id"))
        except ValueError:
            try:
                self.cloud("DELETE", "/v1/watch-grants/{grant_id}".format(grant_id=grant["id"]))
            finally:
                _DIGESTS.pop((me.get("user_id"), grant["id"]), None)
            raise
        sessions = dict(self.read_prefs().get("watchSessions", {}))
        sessions[grant["id"]] = held
        self.save_prefs({"watchSessions": sessions})
        return {"grant": {"id": grant["id"], "grantee": email, "expires": expires},
                "message": "%s can watch this session while ArchHub shares it." % email}

    def stop(self, grant_id):
        if type(grant_id) is not str or not GRANT_ID.fullmatch(grant_id):
            raise ValueError("Choose a watcher from the list.")
        owner = self.account().get("user_id")
        self.cloud("DELETE", "/v1/watch-grants/{grant_id}".format(grant_id=grant_id))
        sessions = {k: v for k, v in self.read_prefs().get("watchSessions", {}).items() if k != grant_id}
        self.save_prefs({"watchSessions": sessions})
        _DIGESTS.pop((owner, grant_id), None)
        return {"message": "Watching stopped."}

    # -- relay cycle -----------------------------------------------------------------------------
    def _push_one(self, grant_id, held, *, owner):
        """Re-read and re-check the session (root, tier, identity), then push it or a heartbeat."""
        document, identity, _path = self._eligible(held["path"])
        if identity != held.get("session_id"):
            raise ValueError("The session file changed identity.")
        projection = project(document, self.labels())
        body = json.dumps(projection, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
        key = (owner, grant_id)
        payload = ({"heartbeat": True, "session_id": held["session_id"], "privacy": SHARE_TIER}
                   if _DIGESTS.get(key) == digest else
                   {"projection": projection, "session_id": held["session_id"], "privacy": SHARE_TIER})
        self.cloud("PUT", "/v1/watch-grants/{grant_id}/projection".format(grant_id=grant_id), payload)
        _DIGESTS[key] = digest
        return "heartbeat" if "heartbeat" in payload else "projection"

    def push(self):
        """One relay cycle: push or heartbeat each active owned grant; a refused one stops locally."""
        state = self.capability()
        if not state["capability"]:
            return {}
        owner = self.account().get("user_id")
        sessions = self.read_prefs().get("watchSessions", {})
        outcome, keep = {}, {}
        for row in state["grants"]:
            held = sessions.get(row["id"])
            if not row["active"] or not held:
                continue
            try:
                outcome[row["id"]] = self._push_one(row["id"], held, owner=owner)
                keep[row["id"]] = held
            except ValueError as refused:
                outcome[row["id"]] = "stopped: %s" % refused
                try:
                    self.cloud("DELETE", "/v1/watch-grants/{grant_id}".format(grant_id=row["id"]))
                except ValueError as unconfirmed:
                    # Nothing more is pushed either way; the cloud's 30 s staleness rule ends the share.
                    outcome[row["id"]] += " (revoke not confirmed: %s)" % unconfirmed
        if keep != sessions:
            self.save_prefs({"watchSessions": keep})
        return outcome

    # -- recipient ---------------------------------------------------------------------------------
    def watching(self):
        """Sessions shared with this account: the cloud lists only its unexpired, unrevoked grants."""
        from .settings_owner import CloudRouteUnavailable
        try:
            grants = self.cloud("GET", "/v1/watching").get("grants", [])
        except CloudRouteUnavailable:
            return {"capability": False, "reason": UNAVAILABLE, "watching": []}
        except ValueError as refused:
            return {"capability": False, "reason": str(refused), "watching": []}
        now, rows = self.clock(), []
        for grant in grants if isinstance(grants, list) else []:
            if not isinstance(grant, dict) or not GRANT_ID.fullmatch(str(grant.get("id", ""))) or not _active(grant, now):
                continue
            rows.append({"id": grant["id"], "expires": _iso(grant.get("expires_at")),
                         "updated": _iso(grant.get("updated_at")),
                         "state": "shared" if _iso(grant.get("updated_at")) else "waiting"})
        return {"capability": True, "reason": "", "watching": rows}

    def view(self, grant_id):
        """One shared session, read-only. Every node label comes from this app's own Library tables."""
        if type(grant_id) is not str or not GRANT_ID.fullmatch(grant_id):
            raise ValueError("Choose a shared session from the list.")
        try:
            answer = self.cloud("GET", "/v1/watching/{grant_id}".format(grant_id=grant_id))
        except WatchEnded:
            # The cloud answers one opaque 410 for stale, revoked, expired and unknown; the list tells them apart.
            listed = any(row["id"] == grant_id for row in self.watching()["watching"])
            return ({"state": "paused", "message": "Not live right now. It comes back when the owner's ArchHub shares it again.",
                     "pollMs": WATCH_NODE["params"]["poll_ms"]}
                    if listed else {"state": "ended", "message": "Watching has ended."})
        return {"state": "live", "projection": clean_projection(answer.get("projection"), self.labels()),
                "updated": _iso(answer.get("updated_at")), "pollMs": WATCH_NODE["params"]["poll_ms"]}


class WatchEnded(ValueError):
    """The cloud's opaque 410 for a shared session that cannot be shown now."""


WATCH_STATUSES = frozenset(STATUSES.values()) | {"pending", "unknown"}
NODE_ID = re.compile(r"n\d{1,6}")


def _iso(value):
    """A UTC ISO timestamp string from the cloud, or None; anything else is dropped."""
    if not isinstance(value, str) or len(value) > 40:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc).isoformat()
    except ValueError as malformed:  # untrusted cloud text: dropped, never shown
        import logging
        logging.getLogger(__name__).debug("watch timestamp dropped: %s", malformed)
        return None


def clean_projection(raw, labels):
    """The recipient's copy of a projection: re-validated field by field, labels re-derived locally.

    The cloud and the owner's app are untrusted here; nothing but the fixed shape reaches the screen.
    """
    if not isinstance(raw, dict) or raw.get("schema") != "archhub-watch/v1" or not isinstance(raw.get("nodes"), list):
        raise ValueError("This shared session could not be read.")
    nodes, ids = [], set()
    for node in raw["nodes"][:MAX_NODES]:
        if not isinstance(node, dict) or not isinstance(node.get("id"), str) or not NODE_ID.fullmatch(node["id"]) or node["id"] in ids:
            continue
        ids.add(node["id"])
        engine = node.get("engine")
        label = SKILL_LABEL if isinstance(engine, str) and _user_skill(engine) else (labels.get(engine) if isinstance(engine, str) else None) or "Step"
        row = {"id": node["id"], "label": label, "status": node.get("status") if node.get("status") in WATCH_STATUSES else "unknown"}
        position = node.get("position")
        if isinstance(position, dict) and _number(position.get("x")) and _number(position.get("y")):
            row["position"] = {"x": position["x"], "y": position["y"]}
        result, shape = node.get("result"), {}
        if isinstance(result, dict):
            if result.get("error") is True:
                shape["error"] = True
            for key in ("items", "count"):
                if _number(result.get(key)) and not isinstance(result.get(key), bool):
                    shape[key] = result[key]
        if shape:
            row["result"] = shape
        nodes.append(row)
    wires = [[w[0], w[1]] for w in raw.get("wires") or [] if isinstance(w, list) and len(w) == 2 and w[0] in ids and w[1] in ids]
    groups = []
    for group in raw.get("groups") or []:
        children = [c for c in (group.get("children") or []) if c in ids] if isinstance(group, dict) and isinstance(group.get("children"), list) else []
        if children:
            groups.append({"children": children})
    return {"schema": "archhub-watch/v1", "nodes": nodes, "wires": wires, "groups": groups}
