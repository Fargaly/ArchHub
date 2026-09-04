"""Legacy cockpit drive-channel drainer shared by two callers.

The cockpit ask-bar queues an intent (POST /v1/cockpit/orchestrate). Something
on the founder's machine must DRAIN that queue and do the real thing, or the
ask-bar is a dead box. This module is that drain logic, shared by:

  * the always-on path — ``CockpitDrainWorker`` in ``workers.py`` (the brain
    daemon already runs always-on, on the founder's machine, holding the
    ``cloud.json`` token), and
  * the standalone debug path — ``cloud_backend/cockpit_executor.py`` (a manual
    ``python cockpit_executor.py <TOKEN>`` for one-off driving), which now
    delegates here so there is ONE handler, never two.

Pure stdlib (json / urllib / re). No personal_brain imports, so the standalone
script can load it by path without dragging the brain package in.

Token resolution (first hit wins):
  1. an explicit token argument,
  2. env ``ARCHHUB_COCKPIT_TOKEN`` / ``AH_CLOUD_TOKEN``,
  3. ``cloud.json`` (``%APPDATA%/ArchHub/brain/cloud.json``) — the SAME file the
     desktop app + the brain's personal-cloud sync already read. So the drainer
     drives the signed-in account with zero extra config.

No token resolves -> every call is an inert, logged no-op. It never blocks the
daemon and never touches the network without a token.
"""
from __future__ import annotations

LEGACY_MIGRATION_ONLY = True
AUTHORITY_STATUS = "control_plane_projection_until_universal_cell_policy"
ACTIVE_AUTHORITY = "10.PRODUCT/13.NODE-LANGUAGE"
PROMOTION_ALLOWED = False

import json
import os
import re
import urllib.request
from pathlib import Path
from typing import Any, Callable, Optional

BASE = os.environ.get("ARCHHUB_COCKPIT_BASE", "https://archhub-cloud.fly.dev")

STATUSES = {"live", "partial", "vision", "blocked", "planned", "prototype", "deprecated"}

_STOP = {"the", "a", "an", "to", "of", "my", "this", "that", "node", "status",
         "please", "it", "is", "set", "flip", "make", "mark", "move", "turn"}


# ── token ────────────────────────────────────────────────────────────────────

def _cloud_json_candidates() -> list[Path]:
    out: list[Path] = []
    appdata = os.environ.get("APPDATA")
    if appdata:
        out.append(Path(appdata) / "ArchHub" / "brain" / "cloud.json")
    home = Path.home()
    out.append(home / "AppData" / "Roaming" / "ArchHub" / "brain" / "cloud.json")
    out.append(home / ".archhub" / "cloud.json")
    return out


def resolve_token(explicit: Optional[str] = None) -> str:
    if explicit and explicit.strip():
        return explicit.strip()
    for key in ("ARCHHUB_COCKPIT_TOKEN", "AH_CLOUD_TOKEN"):
        v = (os.environ.get(key) or "").strip()
        if v:
            return v
    for p in _cloud_json_candidates():
        try:
            if p.is_file():
                data = json.loads(p.read_text(encoding="utf-8"))
                tok = (data.get("token") or data.get("access_token") or "").strip()
                if tok:
                    return tok
        except Exception:
            continue
    return ""


# ── HTTP ─────────────────────────────────────────────────────────────────────

def make_api(token: str, tries: int = 3) -> Callable[..., Any]:
    H = {"Authorization": "Bearer " + token}

    def call(path: str, body: Any = None) -> Any:
        last: Optional[Exception] = None
        for i in range(tries):
            try:
                req = urllib.request.Request(
                    BASE + path,
                    data=(json.dumps(body).encode() if body is not None else None),
                    headers={**H, "Content-Type": "application/json"},
                    method=("POST" if body is not None else "GET"))
                return json.loads(urllib.request.urlopen(req, timeout=25).read())
            except Exception as ex:  # pragma: no cover - network
                last = ex
        if last is not None:
            raise last
    return call


# ── node matching (canonical — was duplicated in cockpit_executor) ───────────

def match_node(model: dict, ref: str) -> Optional[dict]:
    ref = (ref or "").strip().lower()
    nodes = model.get("nodes", [])
    for n in nodes:
        if n["id"].lower() == ref or (ref and ref in n.get("title", "").lower()):
            return n
    words = [w for w in re.split(r"[^a-z0-9]+", ref) if len(w) > 2 and w not in _STOP]
    best, bestscore = None, 0
    for n in nodes:
        hay = (n.get("title", "") + " " + n["id"]).lower()
        score = sum(1 for w in words if w in hay)
        if words and score == len(words):
            return n
        if score > bestscore:
            best, bestscore = n, score
    if words and bestscore >= 2 and bestscore >= len(words) - 1:
        return best
    return None


# ── intent handler ───────────────────────────────────────────────────────────

def handle(intent: str, model: dict, call: Callable[..., Any]) -> tuple[str, Optional[str]]:
    """Do the REAL action for one intent. Returns (result_text, touched_id|None).

    The three deterministic verbs (status / param / add-node) act immediately,
    court-gated by the cloud. Anything richer (build / explain / plan / deploy)
    returns the 'flagged' marker — Phase 2 wires that to a real, gated model
    call. Behaviour matches the original cockpit_executor.handle 1:1.
    """
    t = intent.strip()
    low = t.lower()

    m = re.search(r"(?:flip|set|mark|move|make|turn)\s+(.+?)\s+(?:to|->|=|into)\s+([a-z]+)", low)
    if m and m.group(2) in STATUSES:
        node = match_node(model, m.group(1)); st = m.group(2)
        if not node:
            return ("no node matched '%s'" % m.group(1).strip(), None)
        cmd = {"action": "set_status", "node": node["id"], "value": st}
        if st == "live":
            cmd["evidence"] = "runtime:file=cockpit.py"
        r = call("/v1/cockpit/command", cmd)
        return ("%s -> %s [%s]" % (node["title"], st, r.get("verdict")), node["id"])

    m = re.search(r"set\s+(.+?)\.([\w.]+)\s*=\s*(.+)", t, re.I)
    if m:
        node = match_node(model, m.group(1))
        if not node:
            return ("no node matched '%s'" % m.group(1).strip(), None)
        r = call("/v1/cockpit/command", {"action": "set_param", "node": node["id"],
                                         "param": m.group(2), "value": m.group(3).strip()})
        return ("%s.%s set [%s]" % (node["title"], m.group(2), r.get("verdict")), node["id"])

    m = re.search(r"add (?:a )?node (?:called |named )?[\"']?(.+?)[\"']?(?:\s+in\s+(\w+))?$", t, re.I)
    if m:
        title = m.group(1).strip(); dom = (m.group(2) or "cockpit").strip().lower()
        nid = "exec_" + re.sub(r"[^a-z0-9]+", "_", title.lower())[:40]
        mdl = call("/v1/cockpit/state")["model"]
        if any(x.get("id") == nid or x.get("title", "").lower() == title.lower() for x in mdl["nodes"]):
            return ("node '%s' already on the map" % title, nid)
        mdl["nodes"].append({"id": nid, "dom": dom, "cat": "output", "title": title,
                             "sub": "created live by the cockpit drainer", "status": "partial",
                             "authority_source": "drainer", "evidence_ref": "", "last_verified": "",
                             "bim_phase": "Setup", "standard": "-",
                             "params": [{"k": "from_intent", "v": intent[:60]}], "x": 2120, "y": 1900})
        call("/v1/cockpit/save", {"model": mdl})
        return ("added node '%s' to %s" % (title, dom), nid)

    return ("flagged for the Claude orchestrator (build/deploy/complex)", None)


# ── one drain pass ───────────────────────────────────────────────────────────

def drain_once(token: Optional[str] = None) -> dict:
    """Drain every open intent ONCE. Inert (no network) when no token resolves.

    Returns a small summary dict for worker status / logging.
    """
    tok = resolve_token(token)
    if not tok:
        return {"inert": True, "reason": "no token", "drained": 0}
    call = make_api(tok)
    try:
        opens = call("/v1/cockpit/intents?status=open").get("intents", [])
    except Exception as ex:
        return {"inert": False, "error": "%s: %s" % (type(ex).__name__, ex), "drained": 0}
    if not opens:
        return {"inert": False, "drained": 0}
    model = call("/v1/cockpit/state")["model"]
    results = []
    for it in reversed(opens):                # oldest first
        try:
            res, nid = handle(it["intent"], model, call)
        except Exception as ex:
            res, nid = ("error: %s: %s" % (type(ex).__name__, ex), None)
        try:
            call("/v1/cockpit/intent_done", {"id": it["id"], "result": res})
        except Exception:
            pass
        results.append({"id": it["id"], "intent": it["intent"][:60], "result": res, "node": nid})
    return {"inert": False, "drained": len(results), "results": results}
