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




from collections.abc import Mapping


from pathlib import Path


from typing import Any






from ..enforce import defaults as _enforce_defaults




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


def review_mod_package(folder: str | Path) -> dict[str, Any]:
    import hashlib
    from ..runtime_credentials import assert_not_a_secret
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


_PROPOSAL_FIELDS = frozenset(DEFAULT_PROPOSAL)


_REQUIREMENT_FIELDS = frozenset(DEFAULT_REQUIREMENTS[0])


_GENERATED_FIELDS = frozenset(DEFAULT_GENERATED[0])


_COURT_FIELDS = frozenset(DEFAULT_COURT_EVIDENCE)




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


def before_write_hooks(mods_store: object | None, op_id: str, arguments: Mapping[str, Any]) -> list[dict[str, Any]]:
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
    from ..nograph_server import _mods_rows, JsonFile
    from ..user_paths import state_directory
    mods_store = mods_store or JsonFile(state_directory() / 'settings/mods.json', {'packages': {}, 'enabled': {}})
    rows = _mods_rows(mods_store)['rows']
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


def _increment_builtin_fire(store, mod_id):
    held = store.read()
    counts = held.get('fired_today', {})
    store.update({'fired_today': {**counts, mod_id: int(counts.get(mod_id, 0)) + 1}})
