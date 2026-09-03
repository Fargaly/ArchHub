"""Universal Cell bridge for the legacy self-extension loop.

The old self-extension module can build files, run courts, and write learned
facts. This bridge does not perform those effects. It publishes them as exact
Cell connector providers so each step can be requested, granted, receipted, and
audited through the existing adapter authority.
"""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from .cell_adapters import (
    AdapterProtocol,
    build_adapter_catalog,
    build_adapter_definition,
    release_adapter_definition,
    verify_adapter_catalog,
    verify_released_adapter,
)
from .cell_connector_execution import (
    BaboomConnectorExecutionProtocol,
    ConnectorProviderProjection,
    register_connector_provider,
)
from .cell_protocols import read_relation
from .universal_cell import CellStore, InvalidCell


SELF_EXTENSION_STEPS = ("build", "court", "learn")
_CATALOG_ROOT = "legacy-self-extension:adapter-catalog:v1"
_STEP_SPECS = {
    "build": {
        "action": "self-extension.build",
        "location": "workspace:local-product-scope",
        "datatypes": ("build-request-digest", "artifact-digest"),
        "operation": "self-extension.build-artifact",
        "evidence": (
            "Legacy self-extension build effect; artifact bytes stay in the "
            "local workspace and the graph records only bounded request and "
            "artifact digests."
        ),
    },
    "court": {
        "action": "self-extension.court",
        "location": "governance:roma-court",
        "datatypes": ("court-request-digest", "court-result-digest"),
        "operation": "self-extension.run-court",
        "evidence": (
            "Legacy self-extension court effect; detailed court logs stay in "
            "the admitted court runtime and graph receipts bind digests."
        ),
    },
    "learn": {
        "action": "self-extension.learn",
        "location": "brain:owner-scoped-memory",
        "datatypes": ("learn-request-digest", "learn-receipt-digest"),
        "operation": "self-extension.write-learned-fact",
        "evidence": (
            "Legacy self-extension Brain write effect; learned fact content is "
            "owner-scoped and receipts bind the persisted write result."
        ),
    },
}


@dataclass(frozen=True, slots=True)
class LegacySelfExtensionAuthority:
    catalog_root: str
    providers: Mapping[str, ConnectorProviderProjection]


def _first_member(snapshot, relation_root: str, role_root: str) -> str:
    values = tuple(
        member.participant_id
        for member in read_relation(snapshot, relation_root, budget=100_000)
        if member.role_id == role_root
    )
    if len(values) != 1:
        raise InvalidCell("legacy self-extension adapter binding is not exact")
    return values[0]


def _many_members(snapshot, relation_root: str, role_root: str) -> tuple[str, ...]:
    values = tuple(
        member.participant_id
        for member in read_relation(snapshot, relation_root, budget=100_000)
        if member.role_id == role_root
    )
    if not values or len(values) != len(set(values)):
        raise InvalidCell("legacy self-extension datatypes are invalid")
    return values


def _ensure_step_adapter(
    store: CellStore,
    adapters: AdapterProtocol,
    step: str,
):
    spec = _STEP_SPECS[step]
    adapter_root = "legacy-self-extension:adapter:%s:v1" % step
    if adapter_root not in store.snapshot().cells:
        adapter = build_adapter_definition(
            store,
            adapters,
            adapter_id=adapter_root,
            name="Legacy self-extension %s boundary" % step,
            actions=(spec["action"],),
            locations=(spec["location"],),
            datatypes=spec["datatypes"],
            evidence=spec["evidence"],
        )
        release_adapter_definition(store, adapters, adapter.root_id)
    return verify_released_adapter(store.snapshot(), adapters, adapter_root)


def build_legacy_self_extension_authority(
    store: CellStore,
    adapters: AdapterProtocol,
    connector_protocol: BaboomConnectorExecutionProtocol,
) -> LegacySelfExtensionAuthority:
    providers: dict[str, ConnectorProviderProjection] = {}
    adapter_roots = []
    for step in SELF_EXTENSION_STEPS:
        adapter = _ensure_step_adapter(store, adapters, step)
        snapshot = store.snapshot()
        action_root = _first_member(snapshot, adapter.root_id, adapters.role("action"))
        location_root = _first_member(
            snapshot, adapter.root_id, adapters.role("location")
        )
        datatype_roots = _many_members(
            snapshot, adapter.root_id, adapters.role("datatype")
        )
        providers[step] = register_connector_provider(
            store,
            connector_protocol,
            adapters,
            provider_id="legacy-self-extension:provider:%s:v1" % step,
            adapter_root=adapter.root_id,
            action_root=action_root,
            location_root=location_root,
            datatype_roots=datatype_roots,
            operation=_STEP_SPECS[step]["operation"],
        )
        adapter_roots.append(adapter.root_id)
    if _CATALOG_ROOT not in store.snapshot().cells:
        build_adapter_catalog(
            store,
            adapters,
            tuple(adapter_roots),
            catalog_id=_CATALOG_ROOT,
            version="1.0.0",
        )
    catalog = verify_adapter_catalog(store.snapshot(), adapters, _CATALOG_ROOT)
    if catalog.adapter_roots != tuple(adapter_roots):
        raise InvalidCell("legacy self-extension adapter catalog drifted")
    return LegacySelfExtensionAuthority(
        catalog_root=_CATALOG_ROOT,
        providers=MappingProxyType(dict(providers)),
    )


__all__ = [
    "SELF_EXTENSION_STEPS",
    "LegacySelfExtensionAuthority",
    "build_legacy_self_extension_authority",
]
