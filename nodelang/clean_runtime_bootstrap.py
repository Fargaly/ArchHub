"""Atomic composition of the accepted sources into one selected authority."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
from typing import Protocol
import uuid

from .agent_session_catalogue import (
    AgentSessionCatalogue,
    install_agent_session_catalogue,
)
from .cell_secret_keys import SigningKeyProvider
from .coordination_workshop import WorkshopCatalogue, install_workshop_catalogue
from .clean_browser_authority import (
    CleanBrowserAuthority,
    install_clean_browser_authority,
)
from .clean_visual_authority import (
    CleanVisualSystem,
    install_clean_visual_system,
)
from .requirement_graph_import import (
    RequirementGraphImportResult,
    SpecificationGraphImportResult,
    import_requirement_graph,
    import_specification_graph,
)
from .runtime_caller_capability import Ed25519CallerCapability
from .unified_authority import UnifiedAuthority
from .unified_authority_runtime import AuthorityLocation, provision_unified_authority
from .universal_cell import InvalidCell


BOOTSTRAP_NAMESPACE = uuid.UUID("f0a1688b-031e-4965-9ac4-dd0c1a43d76d")
COMPOSITION_LABELS = (
    "Governance",
    "Grand Map",
    "Workshop",
    "Agent Sessions",
    "Projects",
    "Brain",
    "Cockpit",
    "Cloud",
    "Website",
    "Interface",
)


class CallerKeyStore(Protocol):
    def ensure(self, key_id: str) -> bytes: ...

    def bind_bootstrap(
        self,
        authority: UnifiedAuthority,
        key_id: str,
    ) -> Ed25519CallerCapability: ...


@dataclass(frozen=True, slots=True)
class CleanRuntimeComponents:
    location: AuthorityLocation
    caller: Ed25519CallerCapability
    sessions: AgentSessionCatalogue
    workshop: WorkshopCatalogue
    visual: CleanVisualSystem
    browser: CleanBrowserAuthority
    specification: SpecificationGraphImportResult
    grand_map: RequirementGraphImportResult


def _command(label: str) -> str:
    return str(uuid.uuid5(BOOTSTRAP_NAMESPACE, label))


def _digest(source: bytes, expected: str, label: str) -> str:
    actual = hashlib.sha256(source).hexdigest()
    if actual != expected:
        raise InvalidCell("%s source digest does not match" % label)
    return actual


def provision_clean_runtime(
    root: str | Path,
    authority_key_provider: SigningKeyProvider,
    caller_key_store: CallerKeyStore,
    *,
    caller_key_id: str,
    specification_source: bytes,
    specification_sha256: str,
    grand_map_source: bytes,
    grand_map_sha256: str,
    replace_invalid_current: str | None = None,
) -> CleanRuntimeComponents:
    """Stage the complete clean foundation before selecting its generation."""
    spec_digest = _digest(
        specification_source,
        specification_sha256,
        "specification",
    )
    map_digest = _digest(grand_map_source, grand_map_sha256, "Grand Map")
    public_key = caller_key_store.ensure(caller_key_id)
    built: list[
        tuple[
            Ed25519CallerCapability,
            AgentSessionCatalogue,
            WorkshopCatalogue,
            CleanVisualSystem,
            CleanBrowserAuthority,
            SpecificationGraphImportResult,
            RequirementGraphImportResult,
        ]
    ] = []

    def initialize(authority: UnifiedAuthority) -> None:
        caller = caller_key_store.bind_bootstrap(authority, caller_key_id)
        specification = import_specification_graph(
            authority,
            specification_source,
            expected_sha256=spec_digest,
            caller=caller,
            command_id=_command("specification:" + spec_digest),
        )
        grand_map = import_requirement_graph(
            authority,
            grand_map_source,
            expected_sha256=map_digest,
            caller=caller,
            command_id=_command("grand-map:" + map_digest),
        )
        sessions = install_agent_session_catalogue(
            authority,
            operation_id=_command("agent-session-catalogue:v1"),
            caller=caller,
        )
        workshop = install_workshop_catalogue(
            authority,
            operation_id=_command("workshop-catalogue:v1"),
            caller=caller,
        )
        visual = install_clean_visual_system(
            authority,
            caller=caller,
            command_id=_command("clean-visual-system:v1"),
        )
        browser = install_clean_browser_authority(
            authority,
            caller=caller,
            command_id=_command("clean-browser-authority:v1"),
        )
        built.append((
            caller,
            sessions,
            workshop,
            visual,
            browser,
            specification,
            grand_map,
        ))

    location = provision_unified_authority(
        root,
        authority_key_provider,
        key_id="archhub.unified.bootstrap",
        application_label="ArchHub",
        principal_label="Founder",
        bootstrap_session_label="Founder governed bootstrap",
        bootstrap_session_public_key=public_key,
        composition_labels=COMPOSITION_LABELS,
        replace_invalid_current=replace_invalid_current,
        initialize=initialize,
    )
    if len(built) != 1:
        location.authority.store.close()
        raise InvalidCell("clean runtime initializer did not produce one foundation")
    (
        caller,
        sessions,
        workshop,
        visual,
        browser,
        specification,
        grand_map,
    ) = built[0]
    return CleanRuntimeComponents(
        location,
        caller,
        sessions,
        workshop,
        visual,
        browser,
        specification,
        grand_map,
    )


__all__ = [
    "COMPOSITION_LABELS",
    "CleanRuntimeComponents",
    "provision_clean_runtime",
]
