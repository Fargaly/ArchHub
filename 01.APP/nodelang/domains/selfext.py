"""Node-native self-extension, court, installation, and rollback.

The extension is data in the one table, never a hidden plugin registry.  A
proposal opens into editable parameters, requirement leaves, generated generic
node records, court evidence, approval, and reversible effect plans.  External
mutation is available only through the guarded helpers at the bottom: both
re-read the live approval and court nodes, temporarily unfreeze the appropriate
effect, apply it through the audited effect law, and freeze it again.
"""
from __future__ import annotations

import math
import json
import re
import copy
from collections.abc import Iterable, Mapping, MutableMapping
from pathlib import Path
from typing import Any

from ..core import Store
from ..laws_effect import apply_effect
from ..enforce import defaults as _enforce_defaults
from ..universal_cell import NULL_CELL_ID, Cell, CellStore, InvalidCell, Snapshot


DEFAULT_PROPOSAL = {
    "intent": "Build a reusable node subgraph",
    "target_scope": "10.PRODUCT/11.ARCHHUB-APP",
    "requested_by": "founder",
    "mode": "plan",
}

DEFAULT_REQUIREMENTS = (
    {
        "id": "one-table",
        "predicate": "every generated component is in the one node table",
        "gate_kind": "assertion",
        "expected": True,
        "status": "open",
    },
    {
        "id": "reversible",
        "predicate": "installation has an explicit rollback plan",
        "gate_kind": "assertion",
        "expected": True,
        "status": "open",
    },
)

DEFAULT_GENERATED = (
    {
        "role": "value",
        "title": "Generated input",
        "primitive": "value",
        "configuration": {"value": None},
    },
    {
        "role": "behavior",
        "title": "Generated behavior",
        "primitive": "merge",
        "configuration": {"fn": "first"},
    },
)

DEFAULT_COURT_EVIDENCE = {
    "impossible_state_passed": False,
    "confidence": 0.0,
    "confidence_threshold": 0.95,
    "spec_tests_passed": False,
    "tail_coverage": 0.0,
    "required_coverage": 1.0,
    "independent_judge": False,
    "juror_diversity": 0.0,
    "required_diversity": 0.5,
    "evidence_present": False,
    "evidence_refs": [],
}

MOD_MANIFEST_NAMES = ("archhub.mod.json", "mod.json", "manifest.json")
MOD_WRITE_PERMISSIONS = {"host.write", "write.host", "write_model", "rename sheets", "add a chip to tasks"}
MOD_HARM_PERMISSIONS = {"filesystem.write", "shell", "network", "credential", "secret"}
SHIPPED_MOD_ROWS = (
    {
        "id": "blast-radius", "name": "Blast radius", "version": "1",
        "author": "ArchHub", "enabled": True, "status": "built-in", "error": "",
        "description": "previews host, document, and element scope before governed writes",
        "permissions": ["observe settings"], "nodes": [], "tutorials": [], "hooks": ["before_write"],
        "fired_today": 0, "shipped": True,
    },
    {
        "id": "element-limit", "name": "Element limit", "version": "1",
        "author": "ArchHub", "enabled": True, "status": "built-in", "error": "",
        "description": "blocks governed writes that exceed the configured element count",
        "permissions": ["observe settings"], "nodes": [{"id": "limit", "title": "Element limit", "params": {"Limit": 100}}],
        "tutorials": [], "hooks": ["before_write"], "fired_today": 0, "shipped": True,
    },
    {
        "id": "enforce", "name": "Enforce", "version": "1",
        "author": "ArchHub", "enabled": True, "status": "built-in", "error": "",
        "description": "compiler admission of the exact pending code, model, document or post before approval",
        "permissions": ["observe settings"],
        "nodes": [{"id": "enforce", "title": "Enforce", "params": _enforce_defaults()}],
        "tutorials": [], "hooks": ["before_write"], "fired_today": 0, "shipped": True,
    },
)
SHIPPED_MOD_IDS = {str(row["id"]) for row in SHIPPED_MOD_ROWS}
MODS_OWNER_ROOT = "app:archhub:mods:owner"
MOD_STATE_SCHEMA = "archhub.mods.owner-state.v1"
LEGACY_MODS_OWNER_GRAPH = "mods-owner.graph.json"
LEGACY_OWNER_PARAMS = "owner-params.json"


def _mod_slug(value: Any) -> str:
    slug = re.sub(r"[^a-z0-9._-]+", "-", str(value or "").strip().lower()).strip("-._")
    if not slug:
        raise ValueError("mod identity must name the mod")
    return slug[:80]


def _mod_manifest_path(folder: Path) -> Path:
    for name in MOD_MANIFEST_NAMES:
        path = folder / name
        if path.is_file():
            return path
    raise FileNotFoundError("mod manifest was not found")


def read_mod_manifest(folder: str | Path) -> dict[str, Any]:
    root = Path(folder).expanduser().resolve()
    manifest_path = _mod_manifest_path(root)
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError("mod manifest is not valid JSON") from exc
    return _validated_mod_manifest(raw)


def _validated_mod_manifest(raw):
    if not isinstance(raw, dict):
        raise ValueError("mod manifest must be an object")
    identity = raw.get("identity") if isinstance(raw.get("identity"), dict) else {}
    name = str(identity.get("name") or raw.get("name") or "").strip()
    mod_id = _mod_slug(identity.get("id") or name)
    version = str(raw.get("version") or identity.get("version") or "0.1.0").strip()
    permissions = [str(p).strip() for p in (raw.get("permissions") or raw.get("requested_permissions") or []) if str(p).strip()]
    contents = raw.get("contents") if isinstance(raw.get("contents"), dict) else raw
    node_kinds = contents.get("node_kinds") or contents.get("nodes") or []
    tutorials = contents.get("tutorials") or contents.get("tutorial_nodes") or []
    hooks = contents.get("hooks") or raw.get("hooks") or []
    if not name:
        raise ValueError("mod name is required")
    if not isinstance(node_kinds, list):
        raise ValueError("mod node kinds must be a list")
    clean_nodes = []
    for index, node in enumerate(node_kinds):
        if not isinstance(node, dict):
            raise ValueError("mod node kind %d must be an object" % (index + 1))
        title = str(node.get("title") or node.get("name") or "").strip()
        if not title:
            raise ValueError("mod node kind %d needs a name" % (index + 1))
        node_id = _mod_slug(node.get("id") or title)
        category = str(node.get("category") or "Change").strip() or "Change"
        clean_nodes.append({
            "id": node_id,
            "title": title,
            "category": category,
            "summary": str(node.get("summary") or node.get("description") or title).strip(),
            "params": dict(node.get("params") or {}),
            "behavior": dict(node.get("behavior") or {}),
        })
    return {
        "id": mod_id,
        "name": name,
        "version": version,
        "author": str(identity.get("author") or raw.get("author") or "").strip(),
        "permissions": permissions,
        "nodes": clean_nodes,
        "tutorials": [str(t.get("name") if isinstance(t, dict) else t).strip() for t in tutorials if str(t.get("name") if isinstance(t, dict) else t).strip()],
        "hooks": [str(h).strip() for h in hooks if str(h).strip()],
        "description": str(raw.get("description") or raw.get("summary") or "").strip(),
    }


def _require_mods_store(store: CellStore) -> CellStore:
    if not isinstance(store, CellStore):
        raise InvalidCell("Mods state requires the application graph")
    return store


def _legacy_mods_root(store: CellStore) -> Path | None:
    database = store.database_path
    if not database:
        return None
    path = Path(database)
    if path.suffix:
        return path.with_suffix(path.suffix + ".mods")
    return path.with_name(path.name + ".mods")


def _mod_state_root(mod_id: str) -> str:
    return "%s:%s" % (MODS_OWNER_ROOT, _mod_slug(mod_id))


def _default_builtin_state(base: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "enabled": bool(base.get("enabled", True)),
        "fired_today": int(base.get("fired_today") or 0),
        "params": {},
    }


def _decode_mod_state(snapshot: Snapshot, base: Mapping[str, Any]) -> dict[str, Any]:
    mod_id = str(base["id"])
    cell = snapshot.cells.get(_mod_state_root(mod_id))
    if cell is None:
        return _default_builtin_state(base)
    try:
        raw = json.loads(bytes(cell.atom).decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise InvalidCell("Mods state is unreadable: %s" % mod_id) from exc
    if not isinstance(raw, dict) or raw.get("schema") != MOD_STATE_SCHEMA or raw.get("id") != mod_id:
        raise InvalidCell("Mods state is unreadable: %s" % mod_id)
    params = raw.get("params") if isinstance(raw.get("params"), dict) else {}
    return {
        "enabled": bool(raw.get("enabled")),
        "fired_today": int(raw.get("fired_today") or 0),
        "params": dict(params),
        **{k: raw[k] for k in ('manifest', 'digest', 'removed') if k in raw},
    }


def _encode_mod_state(mod_id: str, state: Mapping[str, Any]) -> bytes:
    return json.dumps(
        {
            "schema": MOD_STATE_SCHEMA,
            "id": mod_id,
            "enabled": bool(state.get("enabled")),
            "fired_today": int(state.get("fired_today") or 0),
            "params": dict(state.get("params") or {}),
            **{k: state[k] for k in ('manifest', 'digest', 'removed') if k in state},
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _commit_mod_state(store: CellStore, base: Mapping[str, Any], state: Mapping[str, Any]) -> dict[str, Any]:
    mod_id = str(base["id"])
    root = _mod_state_root(mod_id)
    snapshot = store.snapshot()
    create: list[Cell] = []
    replace: list[Cell] = []
    owner = snapshot.cells.get(MODS_OWNER_ROOT)
    if state.get('manifest'):
        packages = [] if owner is None or bytes(owner.atom) == b'mods-owner' else json.loads(bytes(owner.atom))
        if mod_id not in packages:
            packages.append(mod_id)
        owner_cell = Cell(MODS_OWNER_ROOT, NULL_CELL_ID, NULL_CELL_ID, json.dumps(packages).encode('utf-8'))
        (replace if owner is not None else create).append(owner_cell)
    elif owner is None:
        create.append(Cell(MODS_OWNER_ROOT, NULL_CELL_ID, NULL_CELL_ID, b"mods-owner"))
    cell = Cell(root, MODS_OWNER_ROOT, NULL_CELL_ID, _encode_mod_state(mod_id, state))
    if root in snapshot.cells:
        replace.append(cell)
    else:
        create.append(cell)
    if create or replace:
        store.commit(snapshot.revision, create=tuple(create), replace=tuple(replace))
    readback = _decode_mod_state(store.snapshot(), base)
    expected = {
        "enabled": bool(state.get("enabled")),
        "fired_today": int(state.get("fired_today") or 0),
        "params": dict(state.get("params") or {}),
        **{k: state[k] for k in ('manifest', 'digest', 'removed') if k in state},
    }
    if readback != expected:
        raise InvalidCell("Mods state readback failed: %s" % mod_id)
    return readback


def _coerce_legacy_mod_state(base: Mapping[str, Any], held: Mapping[str, Any]) -> dict[str, Any]:
    state = _default_builtin_state(base)
    if "enabled" in held:
        state["enabled"] = bool(held["enabled"])
    if "fired_today" in held:
        state["fired_today"] = int(held.get("fired_today") or 0)
    if isinstance(held.get("params"), Mapping):
        state["params"] = dict(held["params"])
    return state


def _archive_legacy_mods_file(path: Path) -> None:
    target = path.with_name(path.name + ".migrated")
    counter = 1
    while target.exists():
        target = path.with_name("%s.%d.migrated" % (path.name, counter))
        counter += 1
    path.rename(target)


def _legacy_state_from_owner_params(path: Path) -> dict[str, dict[str, Any]]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise InvalidCell("Legacy Mods state is unreadable: %s" % path.name) from exc
    if not isinstance(raw, dict):
        raise InvalidCell("Legacy Mods state is unreadable: %s" % path.name)
    builtins = raw.get("builtins") if isinstance(raw.get("builtins"), dict) else raw
    migrated: dict[str, dict[str, Any]] = {}
    for base in SHIPPED_MOD_ROWS:
        mod_id = str(base["id"])
        held = builtins.get(mod_id) if isinstance(builtins, dict) else None
        if isinstance(held, Mapping):
            migrated[mod_id] = _coerce_legacy_mod_state(base, held)
    return migrated


def _legacy_state_from_owner_graph(path: Path) -> dict[str, dict[str, Any]]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise InvalidCell("Legacy Mods owner graph is unreadable: %s" % path.name) from exc
    nodes = raw.get("nodes") if isinstance(raw, dict) else None
    if not isinstance(nodes, dict):
        raise InvalidCell("Legacy Mods owner graph is unreadable: %s" % path.name)
    try:
        legacy_store = Store.load([node for node in nodes.values() if isinstance(node, dict)])
    except Exception as exc:  # noqa: BLE001
        raise InvalidCell("Legacy Mods owner graph is unreadable: %s" % path.name) from exc
    migrated: dict[str, dict[str, Any]] = {}
    for base in SHIPPED_MOD_ROWS:
        mod_id = str(base["id"])
        owner = next((node for node in legacy_store.nodes.values()
                      if node.get("kind") == "group" and node.get("title") == "Mod owner: %s" % mod_id), None)
        if owner is None:
            continue
        refs = owner.get("params", {})

        def value(name: str, default: Any) -> Any:
            node_id = refs.get(name) if isinstance(refs, dict) else None
            if not node_id:
                return default
            try:
                return legacy_store.pull(str(node_id))
            except Exception:  # noqa: BLE001
                return default

        migrated[mod_id] = {
            "enabled": bool(value("enabled", base.get("enabled", True))),
            "fired_today": int(value("fired_today", base.get("fired_today") or 0) or 0),
            "params": dict(value("params", {}) or {}),
        }
    return migrated


def _migrate_legacy_mods_state(store: CellStore) -> None:
    root = _legacy_mods_root(store)
    if root is None:
        return
    legacy_files = (
        (root / LEGACY_OWNER_PARAMS, _legacy_state_from_owner_params),
        (root / LEGACY_MODS_OWNER_GRAPH, _legacy_state_from_owner_graph),
    )
    present = [(path, loader) for path, loader in legacy_files if path.is_file()]
    if not present:
        return
    migrated: dict[str, dict[str, Any]] = {}
    for path, loader in present:
        migrated.update(loader(path))
    snapshot = store.snapshot()
    for base in SHIPPED_MOD_ROWS:
        mod_id = str(base["id"])
        held = migrated.get(mod_id)
        if not isinstance(held, Mapping):
            continue
        if _mod_state_root(mod_id) in snapshot.cells:
            continue
        _commit_mod_state(store, base, held)
        snapshot = store.snapshot()
    for path, _loader in present:
        _archive_legacy_mods_file(path)


def load_mods_state(mods_store: CellStore) -> dict[str, Any]:
    store = _require_mods_store(mods_store)
    _migrate_legacy_mods_state(store)
    snapshot = store.snapshot()
    builtins: dict[str, dict[str, Any]] = {}
    for base in SHIPPED_MOD_ROWS:
        mod_id = str(base["id"])
        held = _decode_mod_state(snapshot, base)
        if held != _default_builtin_state(base):
            builtins[mod_id] = held
    return {"builtins": builtins}


def save_mods_state(mods_store: CellStore, state: Mapping[str, Any]) -> None:
    store = _require_mods_store(mods_store)
    _migrate_legacy_mods_state(store)
    builtins = state.get("builtins") if isinstance(state.get("builtins"), dict) else {}
    for base in SHIPPED_MOD_ROWS:
        mod_id = str(base["id"])
        held = builtins.get(mod_id)
        if not isinstance(held, Mapping):
            continue
        current = _decode_mod_state(store.snapshot(), base)
        if "enabled" in held:
            current["enabled"] = bool(held["enabled"])
        if "fired_today" in held:
            current["fired_today"] = int(held.get("fired_today") or 0)
        if isinstance(held.get("params"), Mapping):
            current["params"] = dict(held["params"])
        _commit_mod_state(store, base, current)


def _increment_builtin_fire(mods_store: CellStore, mod_id: str) -> None:
    store = _require_mods_store(mods_store)
    _migrate_legacy_mods_state(store)
    base = next((row for row in SHIPPED_MOD_ROWS if str(row["id"]) == str(mod_id)), None)
    if base is None:
        return
    held = _decode_mod_state(store.snapshot(), base)
    held["fired_today"] = int(held.get("fired_today") or 0) + 1
    _commit_mod_state(store, base, held)


def _mod_needs_write_grant(manifest: Mapping[str, Any]) -> bool:
    perms = {str(p).strip().lower() for p in manifest.get("permissions", [])}
    return bool(perms & MOD_WRITE_PERMISSIONS) or any("write" in p for p in perms)


def _mod_has_real_harm(manifest: Mapping[str, Any]) -> bool:
    perms = {str(p).strip().lower() for p in manifest.get("permissions", [])}
    return bool(perms & MOD_HARM_PERMISSIONS)


def review_mod_package(folder: str | Path) -> dict[str, Any]:
    import hashlib
    from ..cell_brain_secrets import assert_not_a_secret
    from ..library_engines import STEM_RUN_ENGINES
    path = _mod_manifest_path(Path(folder).resolve())
    if path.stat().st_size > 65536:
        raise ValueError('Choose a mod manifest within 64 KiB.')
    raw = path.read_bytes()
    assert_not_a_secret(raw.decode('utf-8'), 'mod manifest')
    manifest = _validated_mod_manifest(json.loads(raw))
    if manifest['id'] in SHIPPED_MOD_IDS:
        raise ValueError('A package cannot replace a built-in mod.')
    # shortcut: packages compose pure stream engines only; executable plugins need their reviewed adapter.
    if set(manifest['permissions']) - {'observe settings'} or manifest['hooks']:
        raise ValueError('This package needs an executable permission or hook adapter. Use pure stream nodes without hooks.')
    if not manifest['nodes']:
        raise ValueError('Add at least one executable stream node to the manifest.')
    for node in manifest['nodes']:
        engine = node['behavior'].get('engine')
        if set(node['behavior']) != {'engine'} or engine not in STEM_RUN_ENGINES or not str(engine).startswith('shape.'):
            raise ValueError('Mod nodes must name an existing shape.* stream engine.')
        if any(type(v) not in (str, int, float, bool) or type(v) is float and not math.isfinite(v)
               for v in node['params'].values()):
            raise ValueError('Mod node parameters must be scalar values.')
    return {**manifest, 'path': str(Path(folder).resolve()), 'digest': hashlib.sha256(raw).hexdigest()}


def install_mod_package(mods_root: str | Path, folder: str | Path, *, granted: bool = False,
                        reviewed_digest: str = '') -> dict[str, Any]:
    store = _require_mods_store(mods_root)
    manifest = review_mod_package(folder)
    if not reviewed_digest or manifest['digest'] != reviewed_digest:
        raise ValueError('The package changed. Review the current manifest before installing.')
    state = {'enabled': True, 'fired_today': 0, 'params': {}, 'manifest': manifest,
             'digest': reviewed_digest, 'removed': False}
    _commit_mod_state(store, manifest, state)
    return next(r for r in mods_rows(store)['rows'] if r['id'] == manifest['id'])


def _package_bases(snapshot):
    result = []
    owner = snapshot.cells.get(MODS_OWNER_ROOT)
    packages = [] if owner is None or bytes(owner.atom) == b'mods-owner' else json.loads(bytes(owner.atom))
    for identity in packages:
        cell = snapshot.cells[_mod_state_root(identity)]
        held = json.loads(bytes(cell.atom).decode('utf-8'))
        if held.get('schema') == MOD_STATE_SCHEMA and isinstance(held.get('manifest'), dict):
            result.append(held['manifest'])
    return result


def set_mod_enabled(mods_store: CellStore, mod_id: str, enabled: bool) -> dict[str, Any]:
    store = _require_mods_store(mods_store)
    _migrate_legacy_mods_state(store)
    key = str(mod_id)
    base = next((row for row in (*SHIPPED_MOD_ROWS, *_package_bases(store.snapshot())) if str(row['id']) == key), None)
    if base is None or type(enabled) is not bool:
        raise ValueError('Choose an installed mod and a boolean enabled value.')
    held = _decode_mod_state(store.snapshot(), base)
    if held.get('removed'):
        raise ValueError('The mod was removed. Review and install its package again.')
    held["enabled"] = bool(enabled)
    _commit_mod_state(store, base, held)
    return next(row for row in mods_rows(store)["rows"] if row["id"] == key)


def set_mod_param(mods_store: CellStore, mod_id: str, param: str, value: Any) -> dict[str, Any]:
    store = _require_mods_store(mods_store)
    _migrate_legacy_mods_state(store)
    key = str(mod_id)
    name = str(param).strip()
    if key not in SHIPPED_MOD_IDS or not name:
        raise KeyError("mod parameter is not installed")
    base = next(row for row in SHIPPED_MOD_ROWS if str(row["id"]) == key)
    held = _decode_mod_state(store.snapshot(), base)
    params = dict(held.get("params") or {})
    params[name] = int(value) if str(value).strip().isdigit() else str(value)
    held["params"] = params
    _commit_mod_state(store, base, held)
    return next(row for row in mods_rows(store)["rows"] if row["id"] == key)


def remove_mod_package(mods_root: str | Path, mod_id: str) -> dict[str, Any]:
    store = _require_mods_store(mods_root)
    base = next((r for r in _package_bases(store.snapshot()) if r['id'] == mod_id), None)
    if base is None:
        raise ValueError('Built-in protection mods stay installed. Disable their optional behavior in Settings.')
    held = _decode_mod_state(store.snapshot(), base)
    held.update(enabled=False, removed=True)
    _commit_mod_state(store, base, held)
    return {'manifest': base, 'removed': True}


def mods_rows(mods_store: CellStore) -> dict[str, Any]:
    store = _require_mods_store(mods_store)
    _migrate_legacy_mods_state(store)
    snapshot = store.snapshot()
    rows = []
    for base in SHIPPED_MOD_ROWS:
        row = copy.deepcopy(base)
        held = _decode_mod_state(snapshot, base)
        row["enabled"] = bool(held["enabled"])
        row["fired_today"] = int(held["fired_today"])
        params = held.get("params")
        if isinstance(params, dict):
            for node in row.get("nodes", []):
                if isinstance(node.get("params"), dict):
                    for key, value in params.items():
                        if key in node["params"]:
                            node["params"][key] = value
        row["status"] = "built-in" if row.get("enabled") else "off"
        rows.append(row)
    built_in = len(rows)
    for base in _package_bases(snapshot):
        held = _decode_mod_state(snapshot, base)
        if not held.get('removed'):
            rows.append({**base, 'enabled': held['enabled'], 'status': 'Installed' if held['enabled'] else 'off'})
    return {"installed": len(rows) - built_in, "built_in": built_in, "failed": 0, "rows": rows}


def merge_mod_library(groups: list[dict[str, Any]], mods_root: str | Path) -> list[dict[str, Any]]:
    return groups


def run_mod_node(params: Mapping[str, Any], context: Mapping[str, Any] | None = None):
    behavior = params.get("behavior") if isinstance(params.get("behavior"), dict) else {}
    result = behavior.get("result", params.get("text") or params.get("name") or "mod ran")
    shown = str(behavior.get("message") or result)
    return {"out": result}, shown


def _write_element_count(arguments: Mapping[str, Any]) -> int:
    for key in ("elements", "rows", "ids"):
        value = arguments.get(key)
        if isinstance(value, list):
            return len(value)
    return 0


def _blast_radius(arguments: Mapping[str, Any], element_count: int, host: str = "revit") -> dict[str, Any]:
    return {
        "host": host,
        "document": arguments.get("document") or arguments.get("instance") or "",
        "elements": element_count,
        "operation_scope": "document" if element_count == 0 else "selection",
    }


def before_write_hooks(mods_store: CellStore | None, op_id: str, arguments: Mapping[str, Any]) -> list[dict[str, Any]]:
    # An opaque host command cannot prove the exact pending value. Refuse it
    # before host invocation; an unbound store must never disable enforcement.
    from ..enforce import inspect_pending, graph_parameters, display_diagnostics
    pending = arguments.get("pending_write")
    actual = {key: value for key, value in arguments.items()
              if key not in {"grant", "approval", "permit", "instance", "mods_store", "pending_write"}}
    if not isinstance(pending, Mapping) or pending.get("operation") != op_id or pending.get("content") != actual:
        raise PermissionError("error[E0010]: %s has no exact typed pending-write adapter\nhelp: bind the actual host arguments, then retry" % op_id)
    result = inspect_pending(pending, graph_parameters(mods_store))
    if not result["ok"]:
        raise PermissionError(display_diagnostics(result["diagnostics"]))
    if mods_store is None:
        return []
    rows = mods_rows(mods_store)["rows"]
    enabled = [
        row for row in rows
        if row.get("enabled") and "before_write" in row.get("hooks", [])
    ]
    annotations: list[dict[str, Any]] = []
    element_count = _write_element_count(arguments)
    # Resolve refusal hooks first, independent of their presentation order.
    # A rejected attempt records its refusing hook, never an allowed-write preview.
    for row in enabled:
        if row["id"] == "element-limit":
            limit = 0
            for node in row.get("nodes", []):
                params = node.get("params") if isinstance(node, Mapping) else None
                if isinstance(params, Mapping) and "Limit" in params:
                    try:
                        limit = int(params["Limit"])
                    except (TypeError, ValueError):
                        limit = 0
            if limit and element_count > limit:
                _increment_builtin_fire(mods_store, "element-limit")
                raise PermissionError(
                    "Element limit refused %s: %d elements exceeds Limit %d"
                    % (op_id, element_count, limit)
                )
    for row in enabled:
        if row["id"] == "blast-radius":
            annotation = {
                "mod": "blast-radius",
                "label": "Blast radius",
                **_blast_radius(arguments, element_count, op_id.split(".", 1)[0]),
            }
            annotations.append(annotation)
            _increment_builtin_fire(mods_store, "blast-radius")
    return annotations

_PROPOSAL_FIELDS = frozenset(DEFAULT_PROPOSAL)
_REQUIREMENT_FIELDS = frozenset(DEFAULT_REQUIREMENTS[0])
_GENERATED_FIELDS = frozenset(DEFAULT_GENERATED[0])
_COURT_FIELDS = frozenset(DEFAULT_COURT_EVIDENCE)


def _exact_fields(record: Mapping[str, Any], allowed: frozenset[str], label: str) -> None:
    missing = sorted(allowed - set(record))
    unknown = sorted(set(record) - allowed)
    if missing or unknown:
        raise ValueError(
            "%s fields mismatch; missing=%r unknown=%r" % (label, missing, unknown)
        )


def _text(value: Any, label: str, *, allow_empty: bool = False) -> str:
    clean = str(value).strip()
    if not clean and not allow_empty:
        raise ValueError("%s must be a non-empty string" % label)
    return clean


def _ratio(value: Any, label: str) -> float:
    number = float(value)
    if not math.isfinite(number) or number < 0.0 or number > 1.0:
        raise ValueError("%s must be between 0 and 1" % label)
    return number


def _param(store: Store, title: str, value: Any, actor: str) -> str:
    return store.add(
        "param", title, floor={"op": "value", "value": value}, actor=actor
    )


def _wire(
    store: Store,
    source: str,
    target: str,
    title: str,
    actor: str,
) -> str:
    return store.relation(
        [
            {
                "role": "source", "direction": "out", "node_id": source,
                "port_id": "value", "cardinality": "one",
            },
            {
                "role": "target", "direction": "in", "node_id": target,
                "port_id": "value", "cardinality": "one",
            },
        ],
        title=title,
        actor=actor,
    )


def _op(
    store: Store,
    title: str,
    floor: Mapping[str, Any],
    sources: Iterable[str],
    inner: list[str],
    relations: list[str],
    actor: str,
) -> str:
    node = store.add("op", title, floor=dict(floor), actor=actor)
    inner.append(node)
    for source in sources:
        relations.append(_wire(store, source, node, "Input to %s" % title, actor))
    return node


def _record_group(
    store: Store,
    title: str,
    record: Mapping[str, Any],
    actor: str,
    *,
    kind: str = "group",
    frozen: bool = False,
) -> tuple[str, str, dict[str, str], list[str]]:
    params = {
        name: _param(store, "%s: %s" % (title, name), value, actor)
        for name, value in record.items()
    }
    inner = list(params.values())
    relations: list[str] = []
    assembled = _op(
        store,
        "Assemble %s" % title,
        {"op": "merge", "fn": "record", "keys": list(record)},
        params.values(),
        inner,
        relations,
        actor,
    )
    group = store.add(
        kind, title, inner=inner, params=params, frozen=frozen, actor=actor
    )
    return group, assembled, params, relations


def _validated_proposal(raw: Mapping[str, Any]) -> dict[str, Any]:
    record = dict(raw)
    _exact_fields(record, _PROPOSAL_FIELDS, "proposal")
    return {
        "intent": _text(record["intent"], "proposal intent"),
        "target_scope": _text(record["target_scope"], "proposal target scope"),
        "requested_by": _text(record["requested_by"], "proposal requester"),
        "mode": _text(record["mode"], "proposal mode"),
    }


def _validated_requirements(
    records: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    out = []
    for raw in records:
        record = dict(raw)
        _exact_fields(record, _REQUIREMENT_FIELDS, "requirement")
        out.append({
            "id": _text(record["id"], "requirement id"),
            "predicate": _text(record["predicate"], "requirement predicate"),
            "gate_kind": _text(record["gate_kind"], "requirement gate kind"),
            "expected": record["expected"],
            "status": _text(record["status"], "requirement status"),
        })
    if not out:
        raise ValueError("self-extension needs at least one requirement")
    ids = [item["id"] for item in out]
    if len(ids) != len(set(ids)):
        raise ValueError("requirement ids must be unique")
    return out


def _validated_generated(
    records: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    out = []
    for raw in records:
        record = dict(raw)
        _exact_fields(record, _GENERATED_FIELDS, "generated component")
        configuration = record["configuration"]
        if not isinstance(configuration, Mapping):
            raise ValueError("generated component configuration must be a mapping")
        out.append({
            "role": _text(record["role"], "generated role"),
            "title": _text(record["title"], "generated title"),
            "primitive": _text(record["primitive"], "generated primitive"),
            "configuration": dict(configuration),
        })
    if not out:
        raise ValueError("self-extension needs at least one generated component")
    return out


def _validated_evidence(raw: Mapping[str, Any]) -> dict[str, Any]:
    record = dict(raw)
    _exact_fields(record, _COURT_FIELDS, "court evidence")
    refs = record["evidence_refs"]
    if isinstance(refs, (str, bytes)) or not isinstance(refs, Iterable):
        raise ValueError("court evidence refs must be an iterable")
    return {
        "impossible_state_passed": bool(record["impossible_state_passed"]),
        "confidence": _ratio(record["confidence"], "court confidence"),
        "confidence_threshold": _ratio(
            record["confidence_threshold"], "court confidence threshold"
        ),
        "spec_tests_passed": bool(record["spec_tests_passed"]),
        "tail_coverage": _ratio(record["tail_coverage"], "court tail coverage"),
        "required_coverage": _ratio(
            record["required_coverage"], "court required coverage"
        ),
        "independent_judge": bool(record["independent_judge"]),
        "juror_diversity": _ratio(
            record["juror_diversity"], "court juror diversity"
        ),
        "required_diversity": _ratio(
            record["required_diversity"], "court required diversity"
        ),
        "evidence_present": bool(record["evidence_present"]),
        "evidence_refs": [_text(item, "court evidence reference") for item in refs],
    }


def build_self_extension_domain(
    store: Store,
    *,
    proposal: Mapping[str, Any] = DEFAULT_PROPOSAL,
    requirements: Iterable[Mapping[str, Any]] = DEFAULT_REQUIREMENTS,
    generated: Iterable[Mapping[str, Any]] = DEFAULT_GENERATED,
    court_evidence: Mapping[str, Any] = DEFAULT_COURT_EVIDENCE,
    baseline: Any = None,
    actor: str = "self-extension-domain",
) -> dict[str, Any]:
    """Build one inspectable and inert-by-default self-extension graph."""
    proposal_record = _validated_proposal(proposal)
    requirement_records = _validated_requirements(requirements)
    generated_records = _validated_generated(generated)
    evidence_record = _validated_evidence(court_evidence)

    all_relations: list[str] = []
    proposal_group, proposal_record_node, proposal_params, relations = _record_group(
        store, "Extension proposal", proposal_record, actor,
        kind="proposal", frozen=True,
    )
    all_relations.extend(relations)

    requirement_groups: dict[str, str] = {}
    requirement_params: dict[str, dict[str, str]] = {}
    requirement_records_nodes: list[str] = []
    for record in requirement_records:
        group, assembled, params, relations = _record_group(
            store, "Requirement: %s" % record["id"], record, actor
        )
        requirement_groups[record["id"]] = group
        requirement_params[record["id"]] = params
        requirement_records_nodes.append(assembled)
        all_relations.extend(relations)
    requirements_inner = list(requirement_groups.values())
    requirements_list = _op(
        store, "Requirement leaves", {"op": "merge", "fn": "list"},
        requirement_records_nodes, requirements_inner, all_relations, actor,
    )
    requirements_group = store.add(
        "group", "Requirement tree", inner=requirements_inner, actor=actor
    )

    library_query = _param(
        store, "Library search query", proposal_record["intent"], actor
    )
    library_matches = _param(store, "Library matches", [], actor)
    library_no_duplicate = _param(store, "No duplicate capability", True, actor)
    library_record_inner = [library_query, library_matches, library_no_duplicate]
    library_record = _op(
        store, "Library-first search result",
        {"op": "merge", "fn": "record",
         "keys": ["query", "matches", "no_duplicate"]},
        [library_query, library_matches, library_no_duplicate],
        library_record_inner, all_relations, actor,
    )
    library_group = store.add(
        "group", "Library-first search", inner=library_record_inner,
        params={
            "query": library_query,
            "matches": library_matches,
            "no_duplicate": library_no_duplicate,
        },
        actor=actor,
    )

    generated_groups: list[str] = []
    generated_params: list[dict[str, str]] = []
    generated_records_nodes: list[str] = []
    for index, record in enumerate(generated_records):
        group, assembled, params, relations = _record_group(
            store, "Generated component %d: %s" % (index + 1, record["title"]),
            record,
            actor,
        )
        generated_groups.append(group)
        generated_params.append(params)
        generated_records_nodes.append(assembled)
        all_relations.extend(relations)
    generated_inner = list(generated_groups)
    generated_manifest = _op(
        store, "Generated subgraph manifest", {"op": "merge", "fn": "list"},
        generated_records_nodes, generated_inner, all_relations, actor,
    )
    generated_group = store.add(
        "group", "Generated node subgraph", inner=generated_inner, actor=actor
    )

    evidence_group, evidence_record_node, evidence_params, relations = _record_group(
        store, "Court evidence", evidence_record, actor
    )
    all_relations.extend(relations)
    true_node = store.add(
        "value", "True", floor={"op": "value", "value": True}, actor=actor
    )
    empty_node = store.add(
        "value", "Empty", floor={"op": "value", "value": ""}, actor=actor
    )

    court_inner: list[str] = [evidence_group]
    impossible_gate = _op(
        store, "Impossible-state gate",
        {"op": "compare", "cmp": "=="},
        [evidence_params["impossible_state_passed"], true_node],
        court_inner, all_relations, actor,
    )
    confidence_gate = _op(
        store, "Calibrated confidence gate",
        {"op": "compare", "cmp": ">="},
        [evidence_params["confidence"], evidence_params["confidence_threshold"]],
        court_inner, all_relations, actor,
    )
    spec_gate = _op(
        store, "Spec-derived tests gate",
        {"op": "compare", "cmp": "=="},
        [evidence_params["spec_tests_passed"], true_node],
        court_inner, all_relations, actor,
    )
    coverage_gate = _op(
        store, "Tail and coverage gate",
        {"op": "compare", "cmp": ">="},
        [evidence_params["tail_coverage"], evidence_params["required_coverage"]],
        court_inner, all_relations, actor,
    )
    independence_gate = _op(
        store, "Independent judge gate",
        {"op": "compare", "cmp": "=="},
        [evidence_params["independent_judge"], true_node],
        court_inner, all_relations, actor,
    )
    diversity_gate = _op(
        store, "Juror diversity gate",
        {"op": "compare", "cmp": ">="},
        [evidence_params["juror_diversity"], evidence_params["required_diversity"]],
        court_inner, all_relations, actor,
    )
    evidence_gate = _op(
        store, "Evidence is present",
        {"op": "compare", "cmp": "=="},
        [evidence_params["evidence_present"], true_node],
        court_inner, all_relations, actor,
    )
    court_verdict = _op(
        store, "Court verdict",
        {"op": "math", "fn": "*"},
        [impossible_gate, confidence_gate, spec_gate, coverage_gate,
         independence_gate, diversity_gate, evidence_gate,
         library_no_duplicate],
        court_inner, all_relations, actor,
    )
    court_group = store.add(
        "group", "Independent court", inner=court_inner, actor=actor
    )

    approved = _param(store, "Installation approved", False, actor)
    approver = _param(store, "Installation approver", "", actor)
    approved_at = _param(store, "Installation approved at", "", actor)
    approved_digest = _param(store, "Installation approved content SHA-256", "", actor)
    approval_inner = [approved, approver, approved_at, approved_digest]
    approved_true = _op(
        store, "Approval is explicit", {"op": "compare", "cmp": "=="},
        [approved, true_node], approval_inner, all_relations, actor,
    )
    approver_present = _op(
        store, "Approver is identified", {"op": "compare", "cmp": "!="},
        [approver, empty_node], approval_inner, all_relations, actor,
    )
    timestamp_present = _op(
        store, "Approval is timestamped", {"op": "compare", "cmp": "!="},
        [approved_at, empty_node], approval_inner, all_relations, actor,
    )
    approval_gate = _op(
        store, "Approval gate", {"op": "math", "fn": "*"},
        [approved_true, approver_present, timestamp_present],
        approval_inner, all_relations, actor,
    )
    approval_group = store.add(
        "group", "Founder approval", inner=approval_inner,
        params={"approved": approved, "approver": approver,
                "approved_at": approved_at, "content_sha256": approved_digest}, actor=actor,
    )

    installed = _param(store, "Extension installed", False, actor)
    install_target = _param(
        store, "Installation target", proposal_record["target_scope"], actor
    )
    install_change = _param(
        store, "Installation change",
        {"action": "attach_subgraph", "subgraph": generated_group,
         "manifest": generated_manifest},
        actor,
    )
    install_effect = store.add(
        "op", "Frozen installation effect",
        floor={"op": "effect", "target": proposal_record["target_scope"],
               "change": {"$param": "change"}},
        params={"target": install_target, "change": install_change},
        frozen=True,
        actor=actor,
    )
    installation_group = store.add(
        "group", "Installation plan",
        inner=[install_target, install_change, install_effect],
        params={"target": install_target, "change": install_change},
        actor=actor,
    )
    install_result = store.add(
        "op", "Installation result", floor={"op": "merge", "fn": "list"},
        actor=actor,
    )
    install_relation = store.relation(
        [
            {"role": "source", "direction": "out", "node_id": generated_group,
             "port_id": "candidate", "cardinality": "one"},
            {"role": "target", "direction": "in", "node_id": install_result,
             "port_id": "result", "cardinality": "one"},
        ],
        title="Approved court-green installation",
        stages=[
            {"role": "approval", "mode": "guard", "node_id": approval_gate},
            {"role": "court", "mode": "guard", "node_id": court_verdict},
            {"role": "installation", "mode": "map", "node_id": installation_group},
        ],
        actor=actor,
    )
    all_relations.append(install_relation)

    rollback_approved = _param(store, "Rollback approved", False, actor)
    rollback_approver = _param(store, "Rollback approver", "", actor)
    rollback_approved_at = _param(store, "Rollback approved at", "", actor)
    rollback_digest = _param(store, "Rollback approved content SHA-256", "", actor)
    rollback_inner = [rollback_approved, rollback_approver, rollback_approved_at, rollback_digest]
    rollback_true = _op(
        store, "Rollback approval is explicit",
        {"op": "compare", "cmp": "=="},
        [rollback_approved, true_node], rollback_inner, all_relations, actor,
    )
    rollback_actor_present = _op(
        store, "Rollback approver is identified",
        {"op": "compare", "cmp": "!="},
        [rollback_approver, empty_node], rollback_inner, all_relations, actor,
    )
    rollback_time_present = _op(
        store, "Rollback approval is timestamped",
        {"op": "compare", "cmp": "!="},
        [rollback_approved_at, empty_node], rollback_inner, all_relations, actor,
    )
    installed_gate = _op(
        store, "Extension is installed", {"op": "compare", "cmp": "=="},
        [installed, true_node], rollback_inner, all_relations, actor,
    )
    rollback_gate = _op(
        store, "Rollback approval gate", {"op": "math", "fn": "*"},
        [rollback_true, rollback_actor_present, rollback_time_present,
         installed_gate], rollback_inner, all_relations, actor,
    )
    rollback_approval_group = store.add(
        "group", "Rollback approval", inner=rollback_inner,
        params={"approved": rollback_approved, "approver": rollback_approver,
                "approved_at": rollback_approved_at, "content_sha256": rollback_digest}, actor=actor,
    )

    rollback_target = _param(
        store, "Rollback target", proposal_record["target_scope"], actor
    )
    rollback_change = _param(
        store, "Rollback change",
        {"action": "restore_baseline", "subgraph": generated_group,
         "baseline": baseline},
        actor,
    )
    rollback_effect = store.add(
        "op", "Frozen rollback effect",
        floor={"op": "effect", "target": proposal_record["target_scope"],
               "change": {"$param": "change"}},
        params={"target": rollback_target, "change": rollback_change},
        frozen=True,
        actor=actor,
    )
    rollback_group = store.add(
        "group", "Rollback plan",
        inner=[rollback_target, rollback_change, rollback_effect],
        params={"target": rollback_target, "change": rollback_change},
        actor=actor,
    )
    rollback_result = store.add(
        "op", "Rollback result", floor={"op": "merge", "fn": "list"},
        actor=actor,
    )
    rollback_relation = store.relation(
        [
            {"role": "source", "direction": "out", "node_id": installation_group,
             "port_id": "installed-change", "cardinality": "one"},
            {"role": "target", "direction": "in", "node_id": rollback_result,
             "port_id": "rollback-result", "cardinality": "one"},
        ],
        title="Approved court-green rollback",
        stages=[
            {"role": "approval", "mode": "guard", "node_id": rollback_gate},
            {"role": "court", "mode": "guard", "node_id": court_verdict},
            {"role": "rollback", "mode": "map", "node_id": rollback_group},
        ],
        actor=actor,
    )
    all_relations.append(rollback_relation)

    lifecycle_relations = [
        _wire(store, proposal_group, requirements_group,
              "Proposal becomes requirements", actor),
        _wire(store, requirements_group, library_group,
              "Requirements search the library", actor),
        _wire(store, library_group, generated_group,
              "Library result drives composition", actor),
        _wire(store, generated_group, evidence_group,
              "Generated graph requires evidence", actor),
        _wire(store, evidence_group, court_group,
              "Evidence is judged by court", actor),
        _wire(store, installation_group, rollback_group,
              "Installation has an explicit inverse", actor),
    ]
    all_relations.extend(lifecycle_relations)

    session = store.add(
        "session", "Self-Extension Domain",
        inner=[proposal_group, requirements_group, library_group, generated_group,
               evidence_group, court_group, approval_group, installation_group,
               install_result, rollback_approval_group, rollback_group,
               rollback_result] + lifecycle_relations +
              [install_relation, rollback_relation],
        actor=actor,
    )
    return {
        "session": session,
        "proposal": proposal_group,
        "proposal_record": proposal_record_node,
        "proposal_params": proposal_params,
        "requirements": requirements_group,
        "requirements_list": requirements_list,
        "requirement_groups": requirement_groups,
        "requirement_params": requirement_params,
        "library": library_group,
        "library_record": library_record,
        "library_params": {
            "query": library_query, "matches": library_matches,
            "no_duplicate": library_no_duplicate,
        },
        "generated": generated_group,
        "generated_manifest": generated_manifest,
        "generated_groups": generated_groups,
        "generated_params": generated_params,
        "evidence": evidence_group,
        "evidence_record": evidence_record_node,
        "evidence_params": evidence_params,
        "court": court_group,
        "court_gates": {
            "impossible_state": impossible_gate,
            "confidence": confidence_gate,
            "spec_tests": spec_gate,
            "tail_coverage": coverage_gate,
            "independence": independence_gate,
            "juror_diversity": diversity_gate,
            "evidence": evidence_gate,
        },
        "court_verdict": court_verdict,
        "approval": approval_group,
        "approval_params": {
            "approved": approved, "approver": approver, "approved_at": approved_at,
            "content_sha256": approved_digest,
        },
        "approval_gate": approval_gate,
        "installed": installed,
        "installation": installation_group,
        "install_effect": install_effect,
        "install_result": install_result,
        "install_relation": install_relation,
        "rollback_approval": rollback_approval_group,
        "rollback_approval_params": {
            "approved": rollback_approved, "approver": rollback_approver,
            "approved_at": rollback_approved_at,
            "content_sha256": rollback_digest,
        },
        "rollback_gate": rollback_gate,
        "rollback": rollback_group,
        "rollback_effect": rollback_effect,
        "rollback_result": rollback_result,
        "rollback_relation": rollback_relation,
        "lifecycle_relations": lifecycle_relations,
        "relations": all_relations,
    }


def _set_parameter(
    store: Store,
    params: Mapping[str, str],
    name: str,
    value: Any,
    actor: str,
) -> str:
    if name not in params:
        raise KeyError("unknown self-extension parameter %r" % name)
    node_id = str(params[name])
    store.edit(node_id, ["body", "floor", "value"], value, actor=actor)
    return node_id


def set_proposal_parameter(
    store: Store,
    domain: Mapping[str, Any],
    name: str,
    value: Any,
    *,
    actor: str = "proposal-editor",
) -> str:
    """Edit a proposal's parameter node without mutating the frozen proposal."""
    return _set_parameter(store, domain["proposal_params"], name, value, actor)


def set_court_evidence(
    store: Store,
    domain: Mapping[str, Any],
    name: str,
    value: Any,
    *,
    actor: str = "court",
) -> str:
    if name in {
        "confidence", "confidence_threshold", "tail_coverage",
        "required_coverage", "juror_diversity", "required_diversity",
    }:
        value = _ratio(value, "court %s" % name)
    return _set_parameter(store, domain["evidence_params"], name, value, actor)


def set_install_approval(
    store: Store,
    domain: Mapping[str, Any],
    approved: bool,
    *,
    approver: str = "",
    approved_at: str = "",
    actor: str = "founder",
) -> list[str]:
    params = domain["approval_params"]
    from ..enforce import pending_digest
    values = {
        "content_sha256": pending_digest(_selfext_pending(store, domain, str(domain["install_effect"]))) if approved else "",
        "approved": bool(approved),
        "approver": _text(approver, "approver", allow_empty=not approved),
        "approved_at": _text(
            approved_at, "approval timestamp", allow_empty=not approved
        ),
    }
    return [_set_parameter(store, params, name, value, actor)
            for name, value in values.items()]


def set_rollback_approval(
    store: Store,
    domain: Mapping[str, Any],
    approved: bool,
    *,
    approver: str = "",
    approved_at: str = "",
    actor: str = "founder",
) -> list[str]:
    params = domain["rollback_approval_params"]
    from ..enforce import pending_digest
    values = {
        "content_sha256": pending_digest(_selfext_pending(store, domain, str(domain["rollback_effect"]))) if approved else "",
        "approved": bool(approved),
        "approver": _text(approver, "rollback approver", allow_empty=not approved),
        "approved_at": _text(
            approved_at, "rollback approval timestamp", allow_empty=not approved
        ),
    }
    return [_set_parameter(store, params, name, value, actor)
            for name, value in values.items()]


def _gate_is_open(store: Store, node_id: str) -> bool:
    return bool(store.pull(node_id))


def _selfext_pending(store, domain, effect):
    """Read only the generated graph's actual pure dependency closure.

    The existing one-table validator supplies parameter/reference/port types.
    Effectful or unfamiliar primitives in a generated manifest are refused
    before pull, so inspecting a proposal cannot itself invoke a host.
    """
    from ..core import validate_node, relation_sources, relation_targets, relation_stages
    visited = set()

    def visit(root):
        if root in visited:
            return
        visited.add(root)
        node = store.nodes[root]
        validate_node(store.nodes, node)
        body = node["body"]
        if "floor" in body and body["floor"]["op"] not in {"value", "merge"}:
            raise ValueError("generated graph has no pure rule for primitive %s" % body["floor"]["op"])
        for child in [*node["params"].values(), *body.get("inner", ())]:
            visit(child)
        for relation_id in node["relations"]:
            relation = store.nodes[relation_id]
            validate_node(store.nodes, relation)
            if any(end["node_id"] == root for end in relation_targets(store.nodes, relation)):
                endpoints = [*relation_sources(store.nodes, relation), *relation_targets(store.nodes, relation)]
                if any(end.get("port_id") != "value" or end.get("cardinality") != "one" for end in endpoints):
                    raise ValueError("generated relation has an unsupported socket type or cardinality")
                for endpoint in relation_sources(store.nodes, relation):
                    visit(endpoint["node_id"])
                for stage in relation_stages(store.nodes, relation):
                    visit(stage["node_id"])

    generated = str(domain["generated"])
    manifest = str(domain["generated_manifest"])
    visit(generated)
    if store.nodes[generated]["kind"] != "group" or manifest not in store.nodes[generated]["body"].get("inner", ()):
        raise ValueError("generated manifest is not owned by its subgraph")
    records = []
    for group, parameters in zip(domain["generated_groups"], domain["generated_params"], strict=True):
        if group not in store.nodes[generated]["body"]["inner"] or store.nodes[group]["params"] != parameters:
            raise ValueError("generated component has mismatched parameter ownership")
        record = {}
        for key, parameter in parameters.items():
            node = store.nodes[parameter]
            if node["kind"] != "param" or node["body"].get("floor", {}).get("op") != "value":
                raise ValueError("generated component parameter is not a typed value node")
            record[key] = copy.deepcopy(node["body"]["floor"]["value"])
        records.append(record)
    records = _validated_generated(records)
    for record in records:
        primitive, configuration = record["primitive"], record["configuration"]
        if primitive == "value":
            if set(configuration) != {"value"}:
                raise ValueError("value primitive requires exactly its value parameter")
        elif primitive == "merge":
            if set(configuration) != {"fn"} or configuration["fn"] not in {"first", "list", "record", "sum", "concat"}:
                raise ValueError("merge primitive has an unsupported function signature")
        else:
            raise ValueError("generated primitive %s has no type rule" % primitive)
    if store.pull(manifest) != records:
        raise ValueError("computed manifest differs from its typed parameter nodes")
    validate_node(store.nodes, store.nodes[effect])
    def literal_parameter(name):
        node = store.nodes[store.nodes[effect]["params"][name]]
        validate_node(store.nodes, node)
        if node["kind"] != "param" or node["body"].get("floor", {}).get("op") != "value":
            raise ValueError("effect %s is not a typed value parameter" % name)
        return copy.deepcopy(node["body"]["floor"]["value"])
    target = literal_parameter("target")
    change = literal_parameter("change")
    if not isinstance(change, Mapping) or change.get("subgraph") != generated:
        raise ValueError("effect targets a different generated subgraph")
    if change.get("action") == "attach_subgraph":
        if set(change) != {"action", "subgraph", "manifest"} or change["manifest"] != manifest:
            raise ValueError("installation does not bind the checked manifest")
    elif change.get("action") == "restore_baseline":
        if set(change) != {"action", "subgraph", "baseline"}:
            raise ValueError("rollback has an unsupported baseline signature")
    else:
        raise ValueError("self-extension action has no type rule")
    # Runtime graph admission uses the released identity, never proposal prose
    # as authority. The exact proposal remains bound into approval and readback.
    from ..enforce import pending_digest
    proposal_node = store.nodes[str(domain["proposal"])]
    validate_node(store.nodes, proposal_node)
    if proposal_node["kind"] != "proposal" or not proposal_node["meta"]["frozen"]:
        raise ValueError("self-extension intent source is not a frozen proposal")
    proposal = {}
    for key, parameter in domain["proposal_params"].items():
        node = store.nodes[parameter]
        validate_node(store.nodes, node)
        if node["kind"] != "param" or node["body"].get("floor", {}).get("op") != "value":
            raise ValueError("intent source parameter has no value type")
        proposal[key] = copy.deepcopy(node["body"]["floor"]["value"])
    proposal = _validated_proposal(proposal)
    if proposal_node["params"] != domain["proposal_params"] or proposal["target_scope"] != target:
        raise ValueError("effect scope differs from its approved proposal source")
    requirements = _validated_requirements(store.pull(str(domain["requirements_list"])))
    source = {"proposal_root": str(domain["proposal"]), "requirements_root": str(domain["requirements"]),
              "session_root": str(domain["session"]), "author": proposal["requested_by"],
              "intent": proposal["intent"], "scope": [target],
              "semantic_revision_sha256": pending_digest({"proposal": proposal, "requirements": requirements, "generated": records})}
    return {"kind": "model", "format": "archhub-graph-v1", "target": target,
            "intent": "SELFEXT-RUNTIME", "author": proposal["requested_by"], "why": proposal["intent"],
            "content": copy.deepcopy(change), "graph": {"root": generated, "manifest": manifest, "records": records},
            "intent_source": source}


def _enforced_selfext_effect(store, domain, effect, sink, actor):
    from ..enforce import guarded_write, pending_digest
    try:
        pending = _selfext_pending(store, domain, effect)
    except (ValueError, KeyError, TypeError) as error:
        raise PermissionError("error[E0009]: %s\nhelp: repair the generated graph before approving again" % error) from error

    def validate(candidate):
        if pending_digest(_selfext_pending(store, domain, effect)) != pending_digest(candidate):
            raise ValueError("self-extension proposal changed after inspection")

    def write(candidate):
        validate(candidate)
        # Re-read the same real court and approval immediately before mutation.
        gate = "approval_gate" if effect == domain["install_effect"] else "rollback_gate"
        approval = "approval_params" if effect == domain["install_effect"] else "rollback_approval_params"
        if store.pull(domain[approval]["content_sha256"]) != pending_digest(candidate):
            raise PermissionError("self-extension content changed since exact approval; approve the current diff")
        if not _gate_is_open(store, str(domain[gate])) or not _gate_is_open(store, str(domain["court_verdict"])):
            raise PermissionError("self-extension approval or court changed before write")
        store.apply_op({"op": "unfreeze", "id": effect, "actor": actor})
        try:
            store.edit(effect, ["body", "floor", "target"], candidate["target"], actor=actor)
            return apply_effect(store, effect, sink, actor=actor)
        finally:
            store.apply_op({"op": "freeze", "id": effect, "actor": actor})

    def readback(candidate, receipt):
        current = _selfext_pending(store, domain, effect)
        current["content"] = copy.deepcopy(sink[candidate["target"]])
        return current

    checked = guarded_write(pending, write, readback=readback, graph_validator=validate)
    if not checked["ok"]:
        raise PermissionError(checked["display"])
    return {**checked["receipt"], "enforcement": {
        "content_sha256": checked["content_sha256"], "readback_sha256": checked["readback_sha256"],
        "rule_context_sha256": checked["rule_context_sha256"], "observation": checked["observation"]}}


def apply_installation(
    store: Store,
    domain: Mapping[str, Any],
    sink: MutableMapping[Any, Any],
    *,
    actor: str = "founder",
) -> dict[str, Any]:
    """Apply the external change only while approval and court are live-green."""
    if not _gate_is_open(store, str(domain["approval_gate"])):
        raise PermissionError("installation approval gate is closed")
    if not _gate_is_open(store, str(domain["court_verdict"])):
        raise PermissionError("installation court gate is closed")
    effect = str(domain["install_effect"])
    result = _enforced_selfext_effect(store, domain, effect, sink, actor)
    store.edit(
        str(domain["installed"]), ["body", "floor", "value"], True, actor=actor
    )
    return result


def apply_rollback(
    store: Store,
    domain: Mapping[str, Any],
    sink: MutableMapping[Any, Any],
    *,
    actor: str = "founder",
) -> dict[str, Any]:
    """Apply the explicit inverse only while rollback approval and court are green."""
    if not _gate_is_open(store, str(domain["rollback_gate"])):
        raise PermissionError("rollback approval gate is closed")
    if not _gate_is_open(store, str(domain["court_verdict"])):
        raise PermissionError("rollback court gate is closed")
    effect = str(domain["rollback_effect"])
    result = _enforced_selfext_effect(store, domain, effect, sink, actor)
    store.edit(
        str(domain["installed"]), ["body", "floor", "value"], False, actor=actor
    )
    return result
