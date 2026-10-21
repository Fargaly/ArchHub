"""Universal Cell bridge for legacy custom-node execution specs.

This module does not execute legacy custom-node code. It turns one legacy spec
into graph-held adapter authority: exact capability relation, released adapter,
permission request, and later invocation authorization.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
import time
from types import MappingProxyType
from typing import Any, Mapping

from .cell_adapters import (
    AdapterProtocol,
    authorize_adapter_invocation,
    build_adapter_catalog,
    build_adapter_definition,
    build_permission_request,
    read_permission,
    release_adapter_definition,
    verify_adapter_catalog,
    verify_released_adapter,
)
from .cell_protocols import CellBatch, RelationMember, read_relation
from .universal_cell import NULL_CELL_ID, Cell, CellStore, InvalidCell, Snapshot


ROLE_NAMES = (
    "vocabulary-member",
    "custom-node-capability",
    "spec",
    "type",
    "impl-kind",
    "safe-mode",
    "input-contract",
    "output-contract",
    "spec-digest",
)
ALLOWED_IMPL_KINDS = frozenset({
    "passthrough",
    "graph",
    "python",
    "connector",
    "ai",
})
_TYPE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.\-]{0,127}$")


@dataclass(frozen=True, slots=True)
class LegacyCustomNodeProtocol:
    root_id: str
    roles: Mapping[str, str]

    def role(self, name: str) -> str:
        try:
            return self.roles[name]
        except KeyError as exc:
            raise InvalidCell("unknown legacy custom-node role %r" % name) from exc


@dataclass(frozen=True, slots=True)
class LegacyCustomNodeBridge:
    adapter_root: str
    catalog_root: str
    permission_root: str
    capability_root: str
    spec_root: str
    spec_digest_root: str
    spec_digest: str
    user_root: str
    action_root: str
    location_root: str
    datatype_root: str


def bootstrap_legacy_custom_node_protocol(
    store: CellStore,
    *,
    prefix: str = "legacy-custom-node-protocol:v1",
) -> LegacyCustomNodeProtocol:
    roles = {name: "%s:role:%s" % (prefix, name) for name in ROLE_NAMES}
    root_id = prefix + ":root"
    snapshot = store.snapshot()
    if root_id in snapshot.cells:
        return project_legacy_custom_node_protocol(snapshot, prefix=prefix)
    batch = CellBatch(store)
    for name, root in roles.items():
        batch.add(Cell(root, NULL_CELL_ID, NULL_CELL_ID, name.encode("utf-8")))
    batch.relation(
        ((roles["vocabulary-member"], root) for root in roles.values()),
        relation_id=root_id,
    )
    batch.commit()
    return LegacyCustomNodeProtocol(root_id, MappingProxyType(roles))


def project_legacy_custom_node_protocol(
    snapshot: Snapshot,
    *,
    prefix: str = "legacy-custom-node-protocol:v1",
) -> LegacyCustomNodeProtocol:
    roles = {name: "%s:role:%s" % (prefix, name) for name in ROLE_NAMES}
    root_id = prefix + ":root"
    missing = {root for root in (root_id, *roles.values()) if root not in snapshot.cells}
    if missing:
        raise InvalidCell("legacy custom-node protocol is incomplete")
    members = read_relation(snapshot, root_id, budget=100_000)
    expected = tuple(roles.values())
    if (
        tuple(member.participant_id for member in members) != expected
        or any(member.role_id != roles["vocabulary-member"] for member in members)
    ):
        raise InvalidCell("legacy custom-node vocabulary drifted")
    return LegacyCustomNodeProtocol(root_id, MappingProxyType(roles))


def canonical_legacy_custom_node_spec(spec: Mapping[str, Any]) -> bytes:
    if not isinstance(spec, Mapping):
        raise InvalidCell("custom-node spec must be a mapping")
    type_name = str(spec.get("type") or "").strip()
    if not _TYPE_RE.match(type_name):
        raise InvalidCell("custom-node spec type is invalid")
    impl = spec.get("impl")
    if isinstance(impl, Mapping) and impl.get("kind"):
        impl_kind = str(impl.get("kind") or "").strip()
    elif str(spec.get("code") or "").strip():
        impl_kind = "python"
    else:
        impl_kind = "passthrough"
    if impl_kind not in ALLOWED_IMPL_KINDS:
        raise InvalidCell("custom-node impl kind is not admitted")
    canonical = {
        "type": type_name,
        "category": str(spec.get("category") or "misc"),
        "display_name": str(spec.get("display_name") or type_name),
        "description": str(spec.get("description") or ""),
        "inputs": spec.get("inputs") or [],
        "outputs": spec.get("outputs") or [],
        "impl": dict(impl) if isinstance(impl, Mapping) else (
            {"kind": "python", "code": str(spec.get("code") or "")}
            if impl_kind == "python"
            else {"kind": impl_kind}
        ),
    }
    return json.dumps(
        canonical,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")


def legacy_custom_node_spec_digest(spec: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_legacy_custom_node_spec(spec)).hexdigest()


def _impl_kind(spec: Mapping[str, Any]) -> str:
    impl = spec.get("impl")
    if isinstance(impl, Mapping) and impl.get("kind"):
        return str(impl.get("kind") or "").strip()
    if str(spec.get("code") or "").strip():
        return "python"
    return "passthrough"


def _safe_mode(spec: Mapping[str, Any]) -> str:
    impl = spec.get("impl")
    if _impl_kind(spec) != "python":
        return "not-applicable"
    if isinstance(impl, Mapping):
        return "true" if bool(impl.get("safe_mode", True)) else "false"
    return "true"


def _port_names(spec: Mapping[str, Any], key: str) -> tuple[str, ...]:
    out = []
    for item in spec.get(key) or ():
        if isinstance(item, str):
            value = item.strip()
        elif isinstance(item, Mapping):
            value = str(item.get("name") or item.get("id") or "").strip()
        else:
            value = ""
        if value:
            out.append(value)
    return tuple(out)


def _ensure_terminal(store: CellStore, root_id: str, value: bytes) -> None:
    snapshot = store.snapshot()
    existing = snapshot.cells.get(root_id)
    if existing is None:
        store.commit(
            snapshot.revision,
            create=(Cell(root_id, NULL_CELL_ID, NULL_CELL_ID, value),),
        )
        return
    if (
        existing.link0 != NULL_CELL_ID
        or existing.link1 != NULL_CELL_ID
        or existing.atom != value
    ):
        raise InvalidCell("legacy custom-node bridge terminal drifted")


def _one(members: tuple[RelationMember, ...], role_id: str, label: str) -> str:
    values = tuple(
        member.participant_id for member in members if member.role_id == role_id
    )
    if len(values) != 1:
        raise InvalidCell("legacy custom-node capability requires one %s" % label)
    return values[0]


def _build_capability_relation(
    store: CellStore,
    protocol: LegacyCustomNodeProtocol,
    *,
    spec: Mapping[str, Any],
    digest: str,
    capability_root: str,
) -> tuple[str, str]:
    canonical = canonical_legacy_custom_node_spec(spec)
    type_name = str(spec.get("type") or "").strip()
    impl_kind = _impl_kind(spec)
    fields = {
        "spec": (capability_root + ":spec", canonical),
        "type": (capability_root + ":type", type_name.encode("utf-8")),
        "impl-kind": (capability_root + ":impl-kind", impl_kind.encode("utf-8")),
        "safe-mode": (capability_root + ":safe-mode", _safe_mode(spec).encode("utf-8")),
        "input-contract": (
            capability_root + ":inputs",
            json.dumps(_port_names(spec, "inputs"), separators=(",", ":")).encode("ascii"),
        ),
        "output-contract": (
            capability_root + ":outputs",
            json.dumps(_port_names(spec, "outputs"), separators=(",", ":")).encode("ascii"),
        ),
        "spec-digest": (capability_root + ":digest", digest.encode("ascii")),
    }
    for root_id, value in fields.values():
        _ensure_terminal(store, root_id, value)
    snapshot = store.snapshot()
    if capability_root in snapshot.cells:
        members = read_relation(snapshot, capability_root, budget=100_000)
        if _one(members, protocol.role("spec"), "spec") != fields["spec"][0]:
            raise InvalidCell("legacy custom-node capability drifted")
        return fields["spec"][0], fields["spec-digest"][0]
    batch = CellBatch(store)
    batch.relation(
        (
            (protocol.role("custom-node-capability"), protocol.root_id),
            *((protocol.role(name), root_id) for name, (root_id, _value) in fields.items()),
        ),
        relation_id=capability_root,
    )
    batch.commit()
    return fields["spec"][0], fields["spec-digest"][0]


def build_legacy_custom_node_execution_request(
    store: CellStore,
    custom_protocol: LegacyCustomNodeProtocol,
    adapter_protocol: AdapterProtocol,
    *,
    spec: Mapping[str, Any],
    user_root: str,
    request_id: str,
    catalog_id: str | None = None,
    expires_at: float | None = None,
    max_invocations: int = 1,
) -> LegacyCustomNodeBridge:
    """Bind one legacy custom-node spec to exact Cell adapter permission."""
    digest = legacy_custom_node_spec_digest(spec)
    short = digest[:32]
    capability_root = "legacy-custom-node:capability:%s" % short
    spec_root, digest_root = _build_capability_relation(
        store,
        custom_protocol,
        spec=spec,
        digest=digest,
        capability_root=capability_root,
    )
    adapter_root = "legacy-custom-node:adapter:%s" % short
    snapshot = store.snapshot()
    if adapter_root not in snapshot.cells:
        impl_kind = _impl_kind(spec)
        adapter = build_adapter_definition(
            store,
            adapter_protocol,
            adapter_id=adapter_root,
            name="Legacy custom-node execution: %s" % str(spec["type"]).strip(),
            actions=("custom-node.execute.%s" % impl_kind,),
            locations=(),
            location_roots=(capability_root,),
            datatypes=("custom-node.output",),
            evidence=(
                "Legacy typed custom-node spec bridged into released Universal "
                "Cell adapter authority; execution remains a physical adapter."
            ),
        )
        release_adapter_definition(store, adapter_protocol, adapter.root_id)
    adapter = verify_released_adapter(
        store.snapshot(), adapter_protocol, adapter_root
    )
    catalog_root = catalog_id or "legacy-custom-node:adapter-catalog:%s" % short
    if catalog_root not in store.snapshot().cells:
        build_adapter_catalog(
            store,
            adapter_protocol,
            (adapter_root,),
            catalog_id=catalog_root,
            version="1.0.0",
        )
    catalog = verify_adapter_catalog(store.snapshot(), adapter_protocol, catalog_root)
    if catalog.adapter_roots != (adapter_root,):
        raise InvalidCell("legacy custom-node adapter catalog is not exact")
    permission_root = build_permission_request(
        store,
        adapter_protocol,
        catalog_root,
        request_id=request_id,
        adapter_root=adapter_root,
        user_root=user_root,
        action_roots=(adapter.action_roots[0],),
        location_roots=(capability_root,),
        datatype_roots=(adapter.datatype_roots[0],),
        expires_at=time.time() + 120.0 if expires_at is None else expires_at,
        max_invocations=max_invocations,
    )
    permission = read_permission(store.snapshot(), adapter_protocol, permission_root)
    return LegacyCustomNodeBridge(
        adapter_root=adapter_root,
        catalog_root=catalog_root,
        permission_root=permission_root,
        capability_root=capability_root,
        spec_root=spec_root,
        spec_digest_root=digest_root,
        spec_digest=digest,
        user_root=user_root,
        action_root=permission.action_roots[0],
        location_root=permission.location_roots[0],
        datatype_root=permission.datatype_roots[0],
    )


def authorize_legacy_custom_node_invocation(
    snapshot: Snapshot,
    adapter_protocol: AdapterProtocol,
    bridge: LegacyCustomNodeBridge,
    *,
    invocation_count: int,
    now: float | None = None,
):
    return authorize_adapter_invocation(
        snapshot,
        adapter_protocol,
        bridge.catalog_root,
        bridge.permission_root,
        adapter_root=bridge.adapter_root,
        user_root=bridge.user_root,
        action_root=bridge.action_root,
        location_root=bridge.location_root,
        datatype_root=bridge.datatype_root,
        invocation_count=invocation_count,
        now=now,
    )


__all__ = [
    "ALLOWED_IMPL_KINDS",
    "LegacyCustomNodeBridge",
    "LegacyCustomNodeProtocol",
    "authorize_legacy_custom_node_invocation",
    "bootstrap_legacy_custom_node_protocol",
    "build_legacy_custom_node_execution_request",
    "canonical_legacy_custom_node_spec",
    "legacy_custom_node_spec_digest",
    "project_legacy_custom_node_protocol",
]
