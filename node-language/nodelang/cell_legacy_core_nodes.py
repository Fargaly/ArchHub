"""Universal Cell bridge for legacy typed core node behavior.

The old core node module contains host, document, and conversation executors.
This bridge does not call those executors. It publishes their effect boundaries
as released adapter/provider compositions so migration courts can prove exact
permission, grants, and receipts through the existing Cell protocols.
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
from .cell_model_execution import (
    BaboomModelExecutionProtocol,
    ModelProviderProjection,
    register_model_provider,
)
from .cell_protocols import read_relation
from .universal_cell import CellStore, InvalidCell


# The boundary fact is product state and lives with the module that
# publishes it; this bridge re-exports it so its own courts and callers
# keep their names.
from .clean_host_boundaries import (  # noqa: E402
    DOC_FAMILIES,
    HOST_FAMILIES,
    document_operation,
    host_operation,
)
_CONNECTOR_CATALOG_ROOT = "legacy-core-node:adapter-catalog:connector:v1"
_MODEL_CATALOG_ROOT = "legacy-core-node:adapter-catalog:model:v1"


@dataclass(frozen=True, slots=True)
class LegacyCoreNodeAuthority:
    connector_catalog_root: str
    model_catalog_root: str
    host_providers: Mapping[str, ConnectorProviderProjection]
    document_providers: Mapping[str, ConnectorProviderProjection]
    conversation_provider: ModelProviderProjection


def _first_member(snapshot, relation_root: str, role_root: str) -> str:
    roots = tuple(
        member.participant_id
        for member in read_relation(snapshot, relation_root, budget=100_000)
        if member.role_id == role_root
    )
    if len(roots) != 1:
        raise InvalidCell("legacy core node adapter binding is not exact")
    return roots[0]


def _many_members(snapshot, relation_root: str, role_root: str) -> tuple[str, ...]:
    roots = tuple(
        member.participant_id
        for member in read_relation(snapshot, relation_root, budget=100_000)
        if member.role_id == role_root
    )
    if not roots or len(roots) != len(set(roots)):
        raise InvalidCell("legacy core node adapter datatypes are invalid")
    return roots


def _ensure_adapter(
    store: CellStore,
    adapters: AdapterProtocol,
    *,
    adapter_id: str,
    name: str,
    actions: tuple[str, ...],
    locations: tuple[str, ...],
    datatypes: tuple[str, ...],
    evidence: str,
):
    if adapter_id not in store.snapshot().cells:
        built = build_adapter_definition(
            store,
            adapters,
            adapter_id=adapter_id,
            name=name,
            actions=actions,
            locations=locations,
            datatypes=datatypes,
            evidence=evidence,
        )
        release_adapter_definition(store, adapters, built.root_id)
    return verify_released_adapter(store.snapshot(), adapters, adapter_id)


def _provider_roots(
    snapshot,
    adapters: AdapterProtocol,
    adapter_root: str,
) -> tuple[str, str, tuple[str, ...]]:
    return (
        _first_member(snapshot, adapter_root, adapters.role("action")),
        _first_member(snapshot, adapter_root, adapters.role("location")),
        _many_members(snapshot, adapter_root, adapters.role("datatype")),
    )


def build_legacy_core_node_authority(
    store: CellStore,
    adapters: AdapterProtocol,
    connector_protocol: BaboomConnectorExecutionProtocol,
    model_protocol: BaboomModelExecutionProtocol,
) -> LegacyCoreNodeAuthority:
    """Publish old host/doc/chat behavior as exact Cell provider boundaries."""
    host_providers: dict[str, ConnectorProviderProjection] = {}
    doc_providers: dict[str, ConnectorProviderProjection] = {}
    connector_adapter_roots = []
    for family in HOST_FAMILIES:
        adapter = _ensure_adapter(
            store,
            adapters,
            adapter_id="legacy-core-node:adapter:host:%s:v1" % family,
            name="Legacy core host boundary: %s" % family,
            actions=("host.dispatch",),
            locations=("host:%s" % family,),
            datatypes=("host-action-json", "host-state-json"),
            evidence=(
                "Legacy typed host node effect boundary; direct execution is "
                "non-authority and must migrate to Cell connector delegation."
            ),
        )
        snapshot = store.snapshot()
        action, location, datatypes = _provider_roots(
            snapshot, adapters, adapter.root_id
        )
        host_providers[family] = register_connector_provider(
            store,
            connector_protocol,
            adapters,
            provider_id="legacy-core-node:provider:host:%s:v1" % family,
            adapter_root=adapter.root_id,
            action_root=action,
            location_root=location,
            datatype_roots=datatypes,
            operation=host_operation(family),
        )
        connector_adapter_roots.append(adapter.root_id)
    for family in DOC_FAMILIES:
        adapter = _ensure_adapter(
            store,
            adapters,
            adapter_id="legacy-core-node:adapter:document:%s:v1" % family,
            name="Legacy core document boundary: %s" % family,
            actions=("document.read",),
            locations=("document:%s" % family,),
            datatypes=("document-metadata-json", "document-content-digest"),
            evidence=(
                "Legacy typed document node read/projection boundary; raw file "
                "contents stay in the admitted adapter runtime or are redacted."
            ),
        )
        snapshot = store.snapshot()
        action, location, datatypes = _provider_roots(
            snapshot, adapters, adapter.root_id
        )
        doc_providers[family] = register_connector_provider(
            store,
            connector_protocol,
            adapters,
            provider_id="legacy-core-node:provider:document:%s:v1" % family,
            adapter_root=adapter.root_id,
            action_root=action,
            location_root=location,
            datatype_roots=datatypes,
            operation=document_operation(family),
        )
        connector_adapter_roots.append(adapter.root_id)
    if _CONNECTOR_CATALOG_ROOT not in store.snapshot().cells:
        build_adapter_catalog(
            store,
            adapters,
            tuple(connector_adapter_roots),
            catalog_id=_CONNECTOR_CATALOG_ROOT,
            version="1.0.0",
        )
    connector_catalog = verify_adapter_catalog(
        store.snapshot(), adapters, _CONNECTOR_CATALOG_ROOT
    )
    if connector_catalog.adapter_roots != tuple(connector_adapter_roots):
        raise InvalidCell("legacy core connector adapter catalog drifted")

    model_adapter = _ensure_adapter(
        store,
        adapters,
        adapter_id="legacy-core-node:adapter:conversation:v1",
        name="Legacy core conversation model boundary",
        actions=("conversation.complete",),
        locations=("model-router:configured-provider",),
        datatypes=("internal-text", "conversation-response-digest"),
        evidence=(
            "Legacy typed conversation node model boundary; prompts, provider "
            "tokens, and raw outputs stay outside Cells and receipts are redacted."
        ),
    )
    snapshot = store.snapshot()
    action, location, datatypes = _provider_roots(
        snapshot, adapters, model_adapter.root_id
    )
    conversation = register_model_provider(
        store,
        model_protocol,
        adapters,
        provider_id="legacy-core-node:provider:conversation:v1",
        adapter_root=model_adapter.root_id,
        action_root=action,
        location_root=location,
        datatype_roots=datatypes,
    )
    if _MODEL_CATALOG_ROOT not in store.snapshot().cells:
        build_adapter_catalog(
            store,
            adapters,
            (model_adapter.root_id,),
            catalog_id=_MODEL_CATALOG_ROOT,
            version="1.0.0",
        )
    model_catalog = verify_adapter_catalog(
        store.snapshot(), adapters, _MODEL_CATALOG_ROOT
    )
    if model_catalog.adapter_roots != (model_adapter.root_id,):
        raise InvalidCell("legacy core model adapter catalog drifted")
    return LegacyCoreNodeAuthority(
        connector_catalog_root=_CONNECTOR_CATALOG_ROOT,
        model_catalog_root=_MODEL_CATALOG_ROOT,
        host_providers=MappingProxyType(dict(host_providers)),
        document_providers=MappingProxyType(dict(doc_providers)),
        conversation_provider=conversation,
    )


__all__ = [
    "DOC_FAMILIES",
    "HOST_FAMILIES",
    "LegacyCoreNodeAuthority",
    "build_legacy_core_node_authority",
]
