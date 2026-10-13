"""Graph-held on/off switches for host connector nodes."""
from __future__ import annotations

import re
import queue
import threading
import time
from collections.abc import Iterable, Mapping

from .cell_protocols import compose_relation_cells, read_relation
from .unified_authority import (
    COMMAND_BUDGET,
    commit_with_receipt,
    digest,
    validate_command_participants,
)
from .universal_cell import Cell, InvalidCell, NULL_CELL_ID


OWNER_STARTING_REASON = "Can't change this right now: ArchHub's graph service is starting."
OWNER_UNAVAILABLE_REASON = "Can't change this right now: ArchHub's graph service is unavailable."
OWNER_TIMED_OUT_REASON = "Can't change this right now: ArchHub's graph service timed out."
HOST_ENABLE_OWNER_DEADLINE_SECONDS = 1.5
_HOST_ENABLE_CACHE_LOCK = threading.Lock()
_HOST_ENABLE_CACHE: dict[int, dict[str, dict[str, object]]] = {}


def _part(value: str) -> str:
    text = re.sub(r"[^a-z0-9._-]+", "-", str(value).strip().lower())
    return text.strip("-") or "host"


def canonical_host_id(host_id: str) -> str:
    normalized = _part(host_id)
    aliases = {
        "acad": "autocad",
        "known-autocad": "autocad",
        "3ds-max": "max",
        "3dsmax": "max",
        "known-3ds-max": "max",
    }
    if normalized.startswith("known-"):
        normalized = normalized[len("known-"):]
    return aliases.get(normalized, normalized)


def host_node_root(host_id: str) -> str:
    normalized = canonical_host_id(host_id)
    if not normalized:
        raise InvalidCell("host id is invalid")
    return "app:host-connector:%s" % normalized


def _label_root(key: str) -> str:
    return "app:label:%s" % _part(key)


def _value_root(host_id: str, key: str) -> str:
    return "app:value:%s:field:%s" % (_part(host_node_root(canonical_host_id(host_id))), _part(key))


def _property_root(host_id: str, key: str) -> str:
    return "app:property:%s:field:%s" % (_part(host_node_root(canonical_host_id(host_id))), _part(key))


def _atom(value: object) -> bytes:
    if isinstance(value, bool):
        return (b"true" if value else b"false")
    return str(value).encode("utf-8")


def _decode_bool(value: bytes) -> bool:
    text = value.decode("utf-8", errors="replace").strip().lower()
    if text == "true":
        return True
    if text == "false":
        return False
    raise InvalidCell("host enabled parameter is not boolean")


def _stage_label(snapshot, create: dict[str, Cell], key: str) -> str:
    root = _label_root(key)
    if root not in snapshot.cells and root not in create:
        create[root] = Cell(root, NULL_CELL_ID, NULL_CELL_ID, _atom(key))
    return root


def _stage_property(authority, snapshot, create: dict[str, Cell],
                    host_id: str, key: str, value: object) -> str:
    relation_root = _property_root(host_id, key)
    if relation_root in snapshot.cells:
        read_relation(snapshot, relation_root, budget=32)
        return relation_root
    value_root = _value_root(host_id, key)
    if value_root in snapshot.cells:
        raise InvalidCell("partial host connector parameter exists")
    create[value_root] = Cell(value_root, NULL_CELL_ID, NULL_CELL_ID, _atom(value))
    relation = compose_relation_cells((
        (authority.role("owner"), host_node_root(host_id)),
        (authority.role("label"), _stage_label(snapshot, create, key)),
        (authority.role("value"), value_root),
    ), relation_id=relation_root)
    for cell in relation.cells:
        create[cell.id] = cell
    return relation_root


def ensure_host_enable_parameter(authority, host_id: str, *, name: str | None = None) -> str:
    host_id = canonical_host_id(host_id)
    root = host_node_root(host_id)
    snapshot = authority.store.snapshot()
    create: dict[str, Cell] = {}
    if root not in snapshot.cells:
        relation = compose_relation_cells((
            (authority.role("label"), _stage_label(snapshot, create, name or display_host_name(host_id))),
        ), relation_id=root)
        for cell in relation.cells:
            create[cell.id] = cell
    _stage_property(authority, snapshot, create, host_id, "enabled", True)
    _stage_property(authority, snapshot, create, host_id, "enabled_type", "boolean")
    if create:
        raise InvalidCell("host connector parameter has not been admitted to the graph")
    return _property_root(host_id, "enabled")


def _enabled_value_cell(snapshot, authority, host_id: str) -> str | None:
    relation_root = _property_root(host_id, "enabled")
    if relation_root not in snapshot.cells:
        return None
    members = read_relation(snapshot, relation_root, budget=32)
    values = [member.participant_id for member in members
              if member.role_id == authority.role("value")]
    if len(values) != 1:
        raise InvalidCell("host enabled parameter requires one value")
    return values[0]


def host_enabled(store, registry, host_id: str) -> bool:
    authority = getattr(registry, "authority", None)
    if authority is None:
        authority = getattr(registry, "authorization", None)
    # UniversalApplicationRegistry does not expose the wrapper authority;
    # callers that only have store/registry need the standard role ids.
    role_value = registry.roles["value"]
    relation_root = _property_root(host_id, "enabled")
    snapshot = store.snapshot()
    if relation_root not in snapshot.cells:
        return True
    members = read_relation(snapshot, relation_root, budget=32)
    values = [member.participant_id for member in members if member.role_id == role_value]
    if len(values) != 1:
        raise InvalidCell("host enabled parameter requires one value")
    return _decode_bool(snapshot.cells[values[0]].atom)


def authority_host_enabled(authority, host_id: str, *, name: str | None = None) -> bool:
    snapshot = authority.store.snapshot()
    value = _enabled_value_cell(snapshot, authority, host_id)
    return True if value is None else _decode_bool(snapshot.cells[value].atom)


def _owner_error_reason(exc: BaseException) -> str:
    if isinstance(exc, TimeoutError):
        return OWNER_TIMED_OUT_REASON
    text = str(exc).lower()
    if "starting" in text:
        return OWNER_STARTING_REASON
    if isinstance(exc, (ConnectionError, OSError)) or any(
        token in text for token in ("unavailable", "refused", "connect", "offline")
    ):
        return OWNER_UNAVAILABLE_REASON
    return OWNER_UNAVAILABLE_REASON


def _read_enabled_states(authority, host_ids: Iterable[str],
                         deadline: float) -> tuple[dict[str, bool] | None, str | None]:
    host_ids = [canonical_host_id(host_id) for host_id in host_ids]
    results: queue.Queue[tuple[str, object]] = queue.Queue(maxsize=1)

    def worker() -> None:
        try:
            snapshot = authority.store.snapshot()
            states: dict[str, bool] = {}
            for host_id in host_ids:
                value = _enabled_value_cell(snapshot, authority, host_id)
                states[host_id] = True if value is None else _decode_bool(snapshot.cells[value].atom)
            results.put(("ok", states))
        except BaseException as exc:  # noqa: BLE001
            results.put(("error", exc))

    thread = threading.Thread(target=worker, name="host-enable-owner-read", daemon=True)
    thread.start()
    try:
        kind, payload = results.get(timeout=max(0.0, float(deadline)))
    except queue.Empty:
        return None, OWNER_TIMED_OUT_REASON
    if kind == "ok":
        return payload, None
    return None, _owner_error_reason(payload)


def _cached_state(authority, host_id: str) -> dict[str, object] | None:
    with _HOST_ENABLE_CACHE_LOCK:
        value = _HOST_ENABLE_CACHE.get(id(authority), {}).get(canonical_host_id(host_id))
        return dict(value) if value else None


def _remember_states(authority, states: Mapping[str, bool]) -> None:
    now = time.time()
    with _HOST_ENABLE_CACHE_LOCK:
        cache = _HOST_ENABLE_CACHE.setdefault(id(authority), {})
        for host_id, enabled in states.items():
            cache[canonical_host_id(host_id)] = {"enabled": bool(enabled), "confirmed_at": now}


def _host_enable_patch(authority, snapshot, host_id: str, enabled: bool, name: str):
    create: dict[str, Cell] = {}
    replace: dict[str, Cell] = {}
    root = host_node_root(host_id)
    if root not in snapshot.cells:
        relation = compose_relation_cells((
            (authority.role("label"), _stage_label(snapshot, create, name)),
        ), relation_id=root)
        for cell in relation.cells:
            create[cell.id] = cell
    value_root = _enabled_value_cell(snapshot, authority, host_id)
    if value_root is None:
        _stage_property(authority, snapshot, create, host_id, "enabled", enabled)
    else:
        current = snapshot.cells[value_root]
        atom = _atom(enabled)
        if current.atom != atom:
            replace[current.id] = Cell(current.id, current.link0, current.link1, atom)
    if _property_root(host_id, "enabled_type") not in snapshot.cells:
        _stage_property(authority, snapshot, create, host_id, "enabled_type", "boolean")
    return tuple(create.values()), tuple(replace.values())


def set_host_enabled(authority, host_id: str, enabled: bool, *, name: str | None = None,
                     caller=None, command_id: str | None = None) -> dict[str, object]:
    if type(enabled) is not bool:
        raise InvalidCell("host enabled value must be boolean")
    if caller is None or type(command_id) is not str or not command_id.strip():
        raise InvalidCell("host enabled write requires a signed command")
    host_id = canonical_host_id(host_id)
    name = name or display_host_name(host_id)
    snapshot = authority.store.snapshot()
    create, replace = _host_enable_patch(authority, snapshot, host_id, enabled, name)
    if create or replace:
        request_digest = digest({
            "intent": "host-enabled",
            "host": host_id,
            "enabled": enabled,
        })
        authenticated, policy_proof = validate_command_participants(
            authority,
            snapshot,
            caller,
            command_id,
            intent="host-enabled",
            request_digest=request_digest,
            object_root=authority.manifest.catalogue_root,
            scope_root=authority.manifest.catalogue_root,
            budget=COMMAND_BUDGET,
        )
        commit_with_receipt(
            authority,
            snapshot,
            resource_create=create,
            resource_replace=replace,
            authenticated=authenticated,
            result_root=host_node_root(host_id),
            policy_proof=policy_proof,
        )
    return {"id": host_id, "name": name, "enabled": enabled}


def display_host_name(host_id: str) -> str:
    names = {
        "revit": "Revit",
        "autocad": "AutoCAD",
        "acad": "AutoCAD",
        "max": "3ds Max",
        "rhino": "Rhino",
        "blender": "Blender",
        "speckle": "Speckle",
    }
    normalized = canonical_host_id(host_id)
    if normalized in names:
        return names[normalized]
    return " ".join(part.capitalize() for part in normalized.split("-") if part) or "Host"


def disabled_reason(authority, host_id: str, *, name: str | None = None) -> str | None:
    if authority_host_enabled(authority, host_id, name=name):
        return None
    return "%s is turned off in Settings \u203a Connectors." % (name or display_host_name(host_id))


def annotate_host_rows(authority, rows: Iterable[Mapping[str, object]] | None, *,
                       owner_deadline: float = HOST_ENABLE_OWNER_DEADLINE_SECONDS) -> list[dict[str, object]]:
    annotated = []
    pending: list[tuple[str, str, dict[str, object]]] = []
    for row in rows or ():
        if not isinstance(row, Mapping):
            continue
        host_id = str(row.get("id") or "").strip()
        if not host_id:
            continue
        name = str(row.get("name") or display_host_name(host_id))
        item = dict(row)
        pending.append((canonical_host_id(host_id), name, item))
        annotated.append(item)
    states, reason = _read_enabled_states(authority, [host_id for host_id, _name, _item in pending], owner_deadline)
    if states is not None:
        _remember_states(authority, states)
    now = time.time()
    for host_id, _name, item in pending:
        if states is not None:
            item["enabled"] = bool(states.get(host_id, True))
            item["enabled_state"] = "confirmed"
            item["enabled_freshness_seconds"] = 0
            item.pop("enable_disabled_reason", None)
            continue
        cached = _cached_state(authority, host_id)
        if cached is not None:
            item["enabled"] = bool(cached["enabled"])
            item["enabled_state"] = "last_confirmed"
            item["enabled_freshness_seconds"] = max(0, int(now - float(cached["confirmed_at"])))
        else:
            item["enabled"] = False
            item["enabled_state"] = "unknown"
        item["enable_disabled_reason"] = reason or OWNER_UNAVAILABLE_REASON
    return annotated


def find_annotated_host(authority, rows: Iterable[Mapping[str, object]], host_id: str) -> dict[str, object]:
    normalized = canonical_host_id(host_id)
    for row in annotate_host_rows(authority, rows):
        if canonical_host_id(str(row.get("id") or "")) == normalized:
            return row
    raise InvalidCell("unknown host id: %s" % host_id)


__all__ = [
    "OWNER_STARTING_REASON",
    "OWNER_TIMED_OUT_REASON",
    "OWNER_UNAVAILABLE_REASON",
    "annotate_host_rows",
    "authority_host_enabled",
    "canonical_host_id",
    "disabled_reason",
    "display_host_name",
    "ensure_host_enable_parameter",
    "find_annotated_host",
    "host_enabled",
    "host_node_root",
    "set_host_enabled",
]
