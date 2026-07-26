"""Generic deployment evidence expressed with the universal node primitives."""
from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping
from pathlib import Path

from .core import Store, validate_store


DEPLOYMENT_EVIDENCE_ENV = "ARCHHUB_DEPLOYMENT_EVIDENCE"
DEPLOYMENT_EVIDENCE_PATH = (
    Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
    / "ArchHub" / "deployment-evidence.json"
)
_FIELDS = (
    "provider", "project_ref", "version_ref", "deployment_ref", "url",
    "status", "visibility", "observed_at", "source_commit", "content_hash",
)
_SECRET = re.compile(
    r"(?i)(?:password|secret|token|api[_-]?key|private[_-]?key|bearer\s)"
)


def _empty_record() -> dict[str, str]:
    return {name: "" for name in _FIELDS} | {
        "status": "not-connected", "visibility": "private",
    }


def load_deployment_evidence(path=None) -> dict[str, str]:
    source = Path(path or os.environ.get(DEPLOYMENT_EVIDENCE_ENV)
                  or DEPLOYMENT_EVIDENCE_PATH)
    if not source.is_file():
        return _empty_record()
    value = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or set(value) != set(_FIELDS):
        raise ValueError("deployment evidence fields must be exactly %r" % list(_FIELDS))
    record = {name: str(value[name]).strip() for name in _FIELDS}
    if _SECRET.search(json.dumps(record, sort_keys=True)):
        raise ValueError("deployment evidence may not contain credentials")
    if record["url"] and not record["url"].startswith("https://"):
        raise ValueError("deployment evidence URL must use HTTPS")
    return record


def _param(store: Store, title: str, value) -> str:
    return store.add("param", title, floor={"op": "value", "value": value},
                     actor="deployment-evidence")


def _nonempty(store: Store, title: str, source: str) -> str:
    empty = _param(store, title + " empty", "")
    result = store.add("op", title, floor={"op": "compare", "cmp": "!="},
                       actor="deployment-evidence")
    store.wire(source, result, title="Evidence field", actor="deployment-evidence")
    store.wire(empty, result, title="Required non-empty value",
               actor="deployment-evidence")
    return result


def build_deployment_evidence(store: Store, record: Mapping[str, object] | None = None):
    values = load_deployment_evidence() if record is None else {
        name: str(record.get(name, "")).strip() for name in _FIELDS
    }
    fields = {name: _param(store, "Deployment evidence: " + name, values[name])
              for name in _FIELDS}
    merged = store.add(
        "op", "Deployment evidence record",
        floor={"op": "merge", "fn": "record", "keys": list(_FIELDS)},
        actor="deployment-evidence")
    for name, node_id in fields.items():
        store.wire(node_id, merged, title=name + " enters deployment evidence",
                   actor="deployment-evidence")
    succeeded = _param(store, "Required deployment status", "succeeded")
    status_ok = store.add("op", "Deployment succeeded",
                          floor={"op": "compare", "cmp": "=="},
                          actor="deployment-evidence")
    store.wire(fields["status"], status_ok, actor="deployment-evidence")
    store.wire(succeeded, status_ok, actor="deployment-evidence")
    conditions = [status_ok] + [
        _nonempty(store, "Deployment %s present" % name, fields[name])
        for name in ("provider", "url", "observed_at", "source_commit", "content_hash")
    ]
    gate = store.add("op", "Deployment evidence gate",
                     floor={"op": "math", "fn": "*"},
                     actor="deployment-evidence")
    for condition in conditions:
        store.wire(condition, gate, title="Deployment evidence condition",
                   actor="deployment-evidence")
    group = store.add(
        "group", "Deployment evidence",
        inner=list(fields.values()) + [merged, succeeded] + conditions + [gate],
        params=fields, actor="deployment-evidence")
    session = store.add(
        "session", "Publication and Deployment",
        inner=[group],
        params={"evidence": store.add(
            "param", "Deployment evidence reference",
            floor={"op": "reference", "target": group},
            actor="deployment-evidence")},
        actor="deployment-evidence")
    validate_store(store)
    return {"session": session, "group": group, "record": merged,
            "fields": fields, "conditions": conditions, "gate": gate}


__all__ = ["DEPLOYMENT_EVIDENCE_ENV", "DEPLOYMENT_EVIDENCE_PATH",
           "build_deployment_evidence", "load_deployment_evidence"]
