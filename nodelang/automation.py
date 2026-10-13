from __future__ import annotations

import copy
import hashlib
import json
import time
from datetime import datetime, timedelta, timezone


MISSING_HOST_EVENT_PATHS = {
    "revit.document_changed": "No graph-resident Revit document-changed event bridge was found.",
    "revit.document_saved": "No graph-resident Revit document-saved event bridge was found.",
}


class AutomationRefused(RuntimeError):
    pass


class WebhookAuthRequired(AutomationRefused):
    pass


class HostWriteApprovalRequired(AutomationRefused):
    pass


def create_trigger_node(store, trigger_kind, config=None, *, title=None):
    config = dict(config or {})
    trigger = {"kind": trigger_kind, **config}
    return store.add(
        "op",
        title or trigger_kind,
        floor={"op": "automation_trigger", "trigger": trigger},
    )


def create_automation(
    store,
    *,
    graph_id,
    trigger_ids,
    title="Automation",
    missed_policy="skip",
    batch=None,
):
    if missed_policy not in ("skip", "run_once"):
        raise ValueError("missed_policy must be skip or run_once")
    floor = {
        "op": "automation",
        "version": 1,
        "graph_id": graph_id,
        "trigger_ids": list(trigger_ids),
        "missed_policy": missed_policy,
        "batch": copy.deepcopy(batch),
        "state": {
            "paused": False,
            "stopped": False,
            "next_fire": {},
            "file_seen": {},
            "file_pending": {},
            "approved_grants": [],
            "runs": [],
        },
    }
    return store.add("op", title, floor=floor)


def pause_automation(store, automation_id):
    _set_state_flag(store, automation_id, "paused", True)


def resume_automation(store, automation_id):
    _set_state_flag(store, automation_id, "paused", False)


def stop_automation(store, automation_id):
    _set_state_flag(store, automation_id, "stopped", True)


def record_manual_run(store, graph_id, inputs):
    node_id = _manual_repeat_node(store)
    floor = copy.deepcopy(store.nodes[node_id]["body"]["floor"])
    key = _stable_key(inputs)
    graphs = floor.setdefault("graphs", {})
    graph = graphs.setdefault(graph_id, {})
    record = graph.setdefault(key, {"inputs": copy.deepcopy(inputs), "count": 0})
    record["count"] += 1
    store.apply_op({"op": "set", "id": node_id, "path": ["body", "floor"], "value": floor})
    return copy.deepcopy(record)


def baboom_automation_candidates(store, *, min_count=2):
    node_id = _manual_repeat_node(store)
    floor = store.nodes[node_id]["body"]["floor"]
    out = []
    for graph_id, graph in floor.get("graphs", {}).items():
        for input_hash, record in graph.items():
            if record.get("count", 0) >= min_count:
                out.append({
                    "graph_id": graph_id,
                    "input_hash": input_hash,
                    "inputs": copy.deepcopy(record.get("inputs")),
                    "manual_runs": record.get("count", 0),
                })
    return out


def missing_host_event_paths():
    return copy.deepcopy(MISSING_HOST_EVENT_PATHS)


class AutomationEngine:
    def __init__(
        self,
        store,
        *,
        runner,
        clock=None,
        fs=None,
        auth=None,
        stop_all=None,
    ):
        self.store = store
        self.runner = runner
        self.clock = clock or time.time
        self.fs = fs
        self.auth = auth
        self.stop_all = stop_all or (lambda: False)

    def boot(self):
        for automation_id in _automation_ids(self.store):
            floor = _automation_floor(self.store, automation_id)
            changed = False
            state = floor["state"]
            for trigger_id in floor["trigger_ids"]:
                trigger = _trigger_floor(self.store, trigger_id)
                if trigger["kind"] == "schedule":
                    if trigger_id not in state["next_fire"]:
                        state["next_fire"][trigger_id] = _initial_fire(trigger, self.now())
                        changed = True
                    if (floor["missed_policy"] == "skip"
                            and state["next_fire"][trigger_id] < self.now()):
                        state["next_fire"][trigger_id] = _advance_fire(
                            trigger, state["next_fire"][trigger_id], self.now())
                        changed = True
            if changed:
                _write_floor(self.store, automation_id, floor)

    def tick(self):
        if self.stop_all():
            return []
        fired = []
        for automation_id in _automation_ids(self.store):
            floor = _automation_floor(self.store, automation_id)
            if _inactive(floor):
                continue
            for trigger_id in floor["trigger_ids"]:
                trigger = _trigger_floor(self.store, trigger_id)
                if trigger["kind"] == "schedule":
                    if self.now() >= floor["state"]["next_fire"].get(trigger_id, float("inf")):
                        fired.append(self._run_and_advance(automation_id, trigger_id, trigger))
                elif trigger["kind"] == "file_changed":
                    maybe = self._poll_file(automation_id, trigger_id, trigger)
                    if maybe is not None:
                        fired.append(maybe)
        return fired

    def emit_host_event(self, event_kind, payload=None):
        return self._emit("host_event", {"event": event_kind, "payload": payload or {}})

    def grant_approval(self, grant_id, payload=None):
        accepted = []
        for automation_id in _automation_ids(self.store):
            floor = _automation_floor(self.store, automation_id)
            grants = floor["state"].setdefault("approved_grants", [])
            if grant_id not in grants:
                grants.append(grant_id)
                _write_floor(self.store, automation_id, floor)
        accepted.extend(self._emit("approval_granted", {"grant_id": grant_id, "payload": payload or {}}))
        return accepted

    def handle_webhook(self, automation_id, *, token=None, browser_session=None, payload=None):
        floor = _automation_floor(self.store, automation_id)
        if _inactive(floor):
            return {"accepted": False, "status": "inactive"}
        for trigger_id in floor["trigger_ids"]:
            trigger = _trigger_floor(self.store, trigger_id)
            if trigger["kind"] != "webhook":
                continue
            if not self._webhook_authorized(trigger, token, browser_session):
                entry = self._record_refusal(automation_id, trigger_id, "webhook", "unauthenticated")
                return {"accepted": False, "status": entry["status"], "run": entry}
            entry = self._run(automation_id, trigger_id, "webhook", payload or {})
            return {"accepted": True, "status": entry["status"], "run": entry}
        return {"accepted": False, "status": "no_webhook_trigger"}

    def now(self):
        return float(self.clock())

    def _emit(self, trigger_kind, payload):
        fired = []
        for automation_id in _automation_ids(self.store):
            floor = _automation_floor(self.store, automation_id)
            if _inactive(floor):
                continue
            for trigger_id in floor["trigger_ids"]:
                trigger = _trigger_floor(self.store, trigger_id)
                if trigger["kind"] != trigger_kind:
                    continue
                if trigger_kind == "host_event" and trigger.get("event") != payload["event"]:
                    continue
                if trigger_kind == "approval_granted" and trigger.get("grant_id") != payload["grant_id"]:
                    continue
                fired.append(self._run(automation_id, trigger_id, trigger_kind, payload))
        return fired

    def _poll_file(self, automation_id, trigger_id, trigger):
        if self.fs is None:
            return None
        floor = _automation_floor(self.store, automation_id)
        state = floor["state"]
        token = self.fs.snapshot(trigger["path"])
        if token is None:
            return None
        seen = state["file_seen"].get(trigger_id)
        if seen is None:
            state["file_seen"][trigger_id] = token
            _write_floor(self.store, automation_id, floor)
            return None
        pending = state["file_pending"].get(trigger_id)
        if token != seen and (pending is None or pending["token"] != token):
            state["file_pending"][trigger_id] = {
                "token": token,
                "due": self.now() + float(trigger.get("debounce_seconds", 0)),
            }
            _write_floor(self.store, automation_id, floor)
            return None
        if pending and self.now() >= pending["due"]:
            entry = self._run(automation_id, trigger_id, "file_changed", {"path": trigger["path"]})
            floor = _automation_floor(self.store, automation_id)
            floor["state"]["file_seen"][trigger_id] = pending["token"]
            floor["state"]["file_pending"].pop(trigger_id, None)
            _write_floor(self.store, automation_id, floor)
            return entry
        return None

    def _run_and_advance(self, automation_id, trigger_id, trigger):
        entry = self._run(automation_id, trigger_id, "schedule", {})
        floor = _automation_floor(self.store, automation_id)
        next_fire = floor["state"]["next_fire"][trigger_id]
        floor["state"]["next_fire"][trigger_id] = _advance_fire(trigger, next_fire, self.now())
        _write_floor(self.store, automation_id, floor)
        return entry

    def _run(self, automation_id, trigger_id, trigger_kind, payload):
        floor = _automation_floor(self.store, automation_id)
        start = self.now()
        try:
            output = _execute_graph(self.runner, floor, payload)
            missing_grant = _missing_host_write_grant(
                output, floor["state"].get("approved_grants", []))
            if missing_grant:
                raise HostWriteApprovalRequired(missing_grant)
            status = "ok"
            summary = _summary(output)
        except AutomationRefused as exc:
            status = "refused"
            summary = {"reason": str(exc)}
        except Exception as exc:
            status = "failed"
            summary = {"reason": str(exc)}
        entry = {
            "trigger": trigger_kind,
            "trigger_id": trigger_id,
            "start": start,
            "end": self.now(),
            "status": status,
            "outputs_summary": summary,
        }
        floor = _automation_floor(self.store, automation_id)
        floor["state"].setdefault("runs", []).append(entry)
        _write_floor(self.store, automation_id, floor)
        return entry

    def _record_refusal(self, automation_id, trigger_id, trigger_kind, reason):
        floor = _automation_floor(self.store, automation_id)
        entry = {
            "trigger": trigger_kind,
            "trigger_id": trigger_id,
            "start": self.now(),
            "end": self.now(),
            "status": "refused",
            "outputs_summary": {"reason": reason},
        }
        floor["state"].setdefault("runs", []).append(entry)
        _write_floor(self.store, automation_id, floor)
        return entry

    def _webhook_authorized(self, trigger, token, browser_session):
        auth = trigger.get("auth") or {}
        if auth.get("token") and token == auth["token"]:
            return True
        if browser_session and self.auth and self.auth.is_browser_session(browser_session):
            return True
        return False


def run_history(store, automation_id):
    return copy.deepcopy(_automation_floor(store, automation_id)["state"].get("runs", []))


def _execute_graph(runner, floor, payload):
    batch = floor.get("batch")
    if batch:
        items = list(batch.get("items") or [])
        subgraph_id = batch.get("subgraph_id") or floor["graph_id"]
        results = []
        for item in items:
            results.append(runner(subgraph_id, {"item": item, "trigger": payload}))
        return {
            "batch": True,
            "count": len(results),
            "concurrency": int(batch.get("concurrency", 1)),
            "results": results,
        }
    return runner(floor["graph_id"], payload)


def _summary(output):
    if output.get("batch"):
        return {
            "batch": True,
            "count": output["count"],
            "concurrency": output["concurrency"],
            "results": copy.deepcopy(output["results"]),
        }
    return copy.deepcopy(output.get("outputs", output))


def _missing_host_write_grant(output, approved_grants):
    approved = set(approved_grants)
    if output.get("batch"):
        for result in output.get("results", []):
            missing = _missing_host_write_grant(result, approved)
            if missing:
                return missing
        return None
    required = output.get("required_grant") or output.get("requires_host_write_grant")
    if output.get("would_write_host") and required not in approved:
        return required or "host-write"
    return None


def _set_state_flag(store, automation_id, key, value):
    floor = _automation_floor(store, automation_id)
    floor["state"][key] = value
    _write_floor(store, automation_id, floor)


def _inactive(floor):
    state = floor.get("state", {})
    return bool(state.get("paused") or state.get("stopped"))


def _automation_ids(store):
    return [nid for nid, node in store.nodes.items()
            if node.get("body", {}).get("floor", {}).get("op") == "automation"]


def _automation_floor(store, automation_id):
    floor = copy.deepcopy(store.nodes[automation_id]["body"]["floor"])
    if floor.get("op") != "automation":
        raise KeyError("%s is not an automation node" % automation_id)
    return floor


def _trigger_floor(store, trigger_id):
    floor = store.nodes[trigger_id]["body"]["floor"]
    if floor.get("op") != "automation_trigger":
        raise KeyError("%s is not an automation trigger node" % trigger_id)
    return copy.deepcopy(floor["trigger"])


def _write_floor(store, node_id, floor):
    store.apply_op({"op": "set", "id": node_id, "path": ["body", "floor"], "value": floor})


def _initial_fire(trigger, now):
    if "start_at" in trigger:
        return float(trigger["start_at"])
    if "daily_at" in trigger:
        return _next_daily(trigger["daily_at"], now)
    return now + float(trigger.get("every_seconds", trigger.get("interval_seconds", 60)))


def _advance_fire(trigger, previous, now):
    if "daily_at" in trigger:
        next_fire = _next_daily(trigger["daily_at"], previous + 1)
        while next_fire <= now:
            next_fire = _next_daily(trigger["daily_at"], next_fire + 1)
        return next_fire
    step = float(trigger.get("every_seconds", trigger.get("interval_seconds", 60)))
    next_fire = previous + step
    while next_fire <= now:
        next_fire += step
    return next_fire


def _next_daily(hhmm, now):
    hour, minute = [int(part) for part in hhmm.split(":", 1)]
    base = datetime.fromtimestamp(float(now), tz=timezone.utc)
    candidate = base.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate.timestamp() < now:
        candidate += timedelta(days=1)
    return candidate.timestamp()


def _manual_repeat_node(store):
    for nid, node in store.nodes.items():
        floor = node.get("body", {}).get("floor", {})
        if floor.get("op") == "automation_insights":
            return nid
    return store.add("value", "BABOOM automation candidates",
                     floor={"op": "automation_insights", "graphs": {}})


def _stable_key(value):
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
