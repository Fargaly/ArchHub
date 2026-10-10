"""Small in-process frame hub for the Studio tool rail and waiting strip."""

from __future__ import annotations

from typing import Mapping, Sequence

HUB_OWNED_FILES = ("tools.json", "wires.json", "waiting.json", "activity.log")
TOOL_STATE_WORDS = {
    "running": "RUNNING",
    "starting": "STARTING",
    "off": "OFF",
    "failed": "DIDN'T START",
    "not_installed": "NOT INSTALLED",
}

TOOL_ROWS = (
    {
        "id": "studio",
        "label": "Studio",
        "state": "running",
        "state_word": "RUNNING",
        "description": "Canvas, chats and graph sessions.",
        "stat_line": "0 sessions · 0 running.",
        "off_sentence": "Switched off. Sessions are kept.",
        "wire_summary": "Studio → Brain · Connectors · Workshop",
        "empty_title": "Studio is off",
        "empty_line": "Canvas view unavailable. The window itself stays up.",
    },
    {
        "id": "workshop",
        "label": "Workshop",
        "state": "running",
        "state_word": "RUNNING",
        "description": "Projects, tasks and governed work.",
        "stat_line": "Workshop graph ready.",
        "off_sentence": "Workshop owner is not attached.",
        "wire_summary": "Workshop → Studio · Connectors · Brain",
        "empty_title": "Workshop is off",
        "empty_line": "No agent loop, no tasks run, no router. Chat still works locally.",
    },
    {
        "id": "brain",
        "label": "Brain",
        "state": "starting",
        "state_word": "STARTING",
        "description": "Memory, facts and local classification.",
        "stat_line": "Checking local Brain.",
        "off_sentence": "Local Brain is not answering.",
        "wire_summary": "Brain → Studio · Workshop · Cloud",
        "empty_title": "Brain is off",
        "empty_line": "What ArchHub remembers. Everything else keeps running.",
    },
    {
        "id": "baboom",
        "label": "BABOOM",
        "state": "starting",
        "state_word": "NOT ATTACHED",
        "description": "Desktop companion and approved execution.",
        "stat_line": "No signed runtime attached.",
        "off_sentence": "No signed companion runtime is attached.",
        "wire_summary": "BABOOM ← Studio · Workshop",
        "empty_title": "BABOOM is off",
        "empty_line": "The companion is closed. Nothing else changes.",
    },
    {
        "id": "connectors",
        "label": "Connectors",
        "state": "starting",
        "state_word": "STARTING",
        "description": "Host bridges and Speckle access.",
        "stat_line": "Checking host probes.",
        "off_sentence": "No host bridge is answering.",
        "wire_summary": "Connectors → Studio · Workshop · Speckle",
        "empty_title": "Connectors are off",
        "empty_line": "No host reads or writes. Pinned host outputs still feed downstream.",
    },
    {
        "id": "cloud",
        "label": "Cloud",
        "state": "starting",
        "state_word": "NOT SIGNED IN",
        "description": "Devices, grants and cloud agents.",
        "stat_line": "Not signed in.",
        "off_sentence": "Cloud owner state is unavailable.",
        "wire_summary": "Cloud ← Brain · Workshop",
        "empty_title": "Cloud is off",
        "empty_line": "No tunnel, heartbeat, or sync. Everything local is unchanged.",
    },
)

PRODUCER_DECISION_PATHS = {
    "model_delegation": {"approve": "/api/universal/model-delegation-approve", "reject": "/api/universal/work-transition"},
    "social_approve": {"approve": "existing-workshop.decideSocialApproval:approve", "reject": "existing-workshop.decideSocialApproval:deny"},
    "baboom_execute": {"approve": "/api/universal/connector-delegation-approve", "reject": "/api/universal/work-transition"},
    "host_write": {"approve": "/api/universal/connector-delegation-approve", "reject": "/api/universal/work-transition"},
}
WAITING_PRODUCERS = set(PRODUCER_DECISION_PATHS) | {"workshop_gate"}


def _plural(count: int, singular: str, plural: str | None = None) -> str:
    word = singular if count == 1 else (plural or singular + "s")
    return f"{count} {word}"


def _studio_stat_line(sessions: Sequence[Mapping[str, object]]) -> str:
    running = sum(1 for session in sessions if session.get("state") == "running")
    return f"{_plural(len(sessions), 'session')} · {_plural(running, 'running', 'running')}."


def _set_state(row: dict[str, object], state: str, stat_line: str,
               *, state_word: str | None = None) -> None:
    row["state"] = state
    row["state_word"] = state_word or TOOL_STATE_WORDS.get(state, state.replace("_", " ").upper())
    row["stat_line"] = stat_line


def _apply_workshop(row: dict[str, object], state: Mapping[str, object] | None) -> None:
    if not state:
        return
    attached = bool(state.get("native_host_attached"))
    available = bool(state.get("available"))
    if attached:
        _set_state(row, "running", "Native Workshop owner attached.")
    elif available:
        _set_state(row, "running", "Workshop graph ready.")
    else:
        _set_state(row, "off", "No Workshop graph in this scope.")


def _apply_brain(row: dict[str, object], state: Mapping[str, object] | None) -> None:
    if not state:
        return
    ok = state.get("ok")
    facts = int(state.get("facts") or 0)
    if ok is True:
        _set_state(row, "running", f"{_plural(facts, 'fact')} in local Brain.")
    elif ok is False:
        _set_state(row, "off", "Local Brain is not answering.")
    else:
        _set_state(row, "starting", "Checking local Brain.")


def _apply_baboom(row: dict[str, object], presence: Mapping[str, object] | None) -> None:
    if not presence:
        return
    sessions = int(presence.get("active_runtime_sessions") or 0)
    if presence.get("baboom_connected"):
        _set_state(
            row, "running",
            f"Attached signed runtime · {_plural(sessions, 'runtime session')}.",
            state_word="ATTACHED",
        )
    else:
        _set_state(row, "starting", "No signed runtime attached.", state_word="NOT ATTACHED")


def _apply_connectors(row: dict[str, object], host_rows, *, probing: bool = False) -> None:
    if probing:
        _set_state(row, "starting", "Checking host probes.")
        return
    if not isinstance(host_rows, Sequence) or isinstance(host_rows, (str, bytes)):
        return
    total = len([item for item in host_rows if isinstance(item, Mapping)])
    running = sum(
        1 for item in host_rows
        if isinstance(item, Mapping) and item.get("state") in ("connected", "listening")
    )
    _set_state(row, "running", f"{running}/{total} hosts running.")


def _apply_cloud(row: dict[str, object], state: Mapping[str, object] | None) -> None:
    if not state:
        return
    name = str(state.get("state") or "signed_out")
    email = str(state.get("email") or "").strip()
    if state.get("signed_in") and email:
        _set_state(row, "running", email, state_word="SIGNED IN")
    elif name == "expired":
        _set_state(row, "failed", "Sign in expired.", state_word="EXPIRED")
    else:
        _set_state(row, "starting", "Not signed in.", state_word="NOT SIGNED IN")


def project_tools(*, sessions=(), workshop_state=None, brain_state=None,
                  baboom_presence=None, host_rows=None, hosts_probing=False,
                  cloud_state=None) -> dict[str, object]:
    rows = [dict(row) for row in TOOL_ROWS]
    if isinstance(sessions, Sequence) and not isinstance(sessions, (str, bytes)):
        session_rows = [row for row in sessions if isinstance(row, Mapping)]
        for row in rows:
            if row.get("id") == "studio":
                row["stat_line"] = _studio_stat_line(session_rows)
                break
    for row in rows:
        if row.get("id") == "workshop":
            _apply_workshop(row, workshop_state)
        elif row.get("id") == "brain":
            _apply_brain(row, brain_state)
        elif row.get("id") == "baboom":
            _apply_baboom(row, baboom_presence)
        elif row.get("id") == "connectors":
            _apply_connectors(row, host_rows, probing=hosts_probing)
        elif row.get("id") == "cloud":
            _apply_cloud(row, cloud_state)
    return {
        "ok": True,
        "tools": rows,
        "owned_files": list(HUB_OWNED_FILES),
    }


def project_wires() -> dict[str, object]:
    return {
        "ok": True,
        "wires": [
            {"tool": row["id"], "summary": row["wire_summary"]}
            for row in TOOL_ROWS
        ],
        "owned_files": ["wires.json", "activity.log"],
    }


def producer_decision_path(item: Mapping[str, object], decision: str) -> str:
    producer = str(item.get("producer") or item.get("source") or "").strip()
    path = PRODUCER_DECISION_PATHS.get(producer, {}).get(decision)
    if not path:
        raise ValueError("waiting item has no existing producer decision path")
    return path


def waiting_item_from_producer(producer: str, item: Mapping[str, object]) -> dict[str, object]:
    summary = str(item.get("summary") or item.get("label") or item.get("title") or "").strip()
    from_name = str(item.get("from") or item.get("asker") or item.get("who") or producer).strip()
    to_name = str(item.get("to") or "you").strip()
    action = str(item.get("action") or "approve").strip()
    if not summary:
        summary = f"{from_name} wants {to_name} to {action}"
    clean = {
        "id": str(item.get("id") or item.get("delegation") or item.get("work") or f"{producer}:waiting"),
        "summary": summary,
        "from": from_name,
        "to": to_name,
        "action": action,
        "who": str(item.get("who") or from_name),
        "for": str(item.get("for") or "you"),
        "time": str(item.get("time") or item.get("asked_at") or ""),
        "plan_hash": str(item.get("plan_hash") or item.get("plan") or ""),
        "file": str(item.get("file") or item.get("model") or item.get("host_file") or ""),
        "producer": producer,
        "root": str(item.get("root") or item.get("workshop") or ""),
        "work": str(item.get("work") or ""),
        "delegation": str(item.get("delegation") or ""),
        "input_digest": str(item.get("input_digest") or ""),
        "revision": item.get("revision"),
        "open_target": str(item.get("open_target") or item.get("task") or item.get("work") or ""),
        "host_ids": [str(value) for value in item.get("host_ids", ()) if str(value)],
        "asker_alive": bool(item.get("asker_alive", True)),
    }
    if producer in PRODUCER_DECISION_PATHS:
        clean.update({
            "approve_path": producer_decision_path({"producer": producer}, "approve"),
            "reject_path": producer_decision_path({"producer": producer}, "reject"),
        })
    if producer == "workshop_gate":
        clean.update({
            "open_label": "Open in Approvals",
            "open_tab": "approvals",
        })
    if bool(item.get("second_approval")):
        clean.update({
            "second_approval": True,
            "approvals_done": int(item.get("approvals_done", 1)),
            "approvals_required": int(item.get("approvals_required", 2)),
            "ask_member": str(item.get("ask_member") or "member"),
        })
    return clean


def project_waiting(*, items=(), errors=()) -> dict[str, object]:
    clean = []
    for index, item in enumerate(items):
        if not isinstance(item, Mapping):
            continue
        producer = str(item.get("producer") or item.get("source") or "").strip()
        if producer not in WAITING_PRODUCERS:
            continue
        row = waiting_item_from_producer(producer, item)
        if not row["id"]:
            row["id"] = "waiting-%d" % index
        clean.append(row)
    error_rows = [str(error) for error in errors if str(error)]
    return {
        "ok": not error_rows,
        "items": clean,
        "errors": error_rows,
        "owned_files": ["waiting.json", "activity.log"],
        "decision_paths": PRODUCER_DECISION_PATHS,
    }


def workshop_gate_waiting(item: Mapping[str, object]) -> dict[str, object]:
    return waiting_item_from_producer("workshop_gate", item)


def model_delegation_waiting(item: Mapping[str, object]) -> dict[str, object]:
    return waiting_item_from_producer("model_delegation", item)


def social_approve_waiting(item: Mapping[str, object]) -> dict[str, object]:
    return waiting_item_from_producer("social_approve", item)


def baboom_execute_waiting(item: Mapping[str, object]) -> dict[str, object]:
    return waiting_item_from_producer("baboom_execute", item)


def host_write_waiting(item: Mapping[str, object]) -> dict[str, object]:
    return waiting_item_from_producer("host_write", item)
