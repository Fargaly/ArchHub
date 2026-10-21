"""Durable local provisioning for v2 revision-checkpoint authority."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path

from .cell_revision_checkpoint import (
    RevisionCheckpointDenied,
    RevisionCheckpointGuard,
    RevisionCheckpointSigningAuthority,
)
from .cell_signing_authority import (
    SigningAuthorityDenied,
    bootstrap_signing_authority_protocol,
    build_signing_key_descriptor,
    project_signing_authority_protocol,
    read_signing_key_descriptor,
    verify_signing_key_descriptor,
)
from .universal_cell import NULL_CELL_ID, Cell, CellStore
from .windows_cng_signing_provider import (
    PLATFORM_PROVIDER_ID,
    SOFTWARE_PROVIDER_ID,
    WindowsCngSigningAuthorityProvider,
)


def _identity(database_identity: str | os.PathLike[str]) -> str:
    return hashlib.sha256(
        str(Path(database_identity).expanduser().resolve())
        .casefold()
        .encode("utf-8")
    ).hexdigest()


def default_checkpoint_authority_path(
    database_identity: str | os.PathLike[str],
) -> Path:
    local = os.environ.get("LOCALAPPDATA")
    if not local:
        raise RevisionCheckpointDenied("LOCALAPPDATA is unavailable")
    return (
        Path(local)
        / "ArchHub"
        / "authorities"
        / ("revision-checkpoint-%s.sqlite3" % _identity(database_identity))
    )


def default_checkpoint_key_name(
    database_identity: str | os.PathLike[str],
) -> str:
    return "ArchHub.RevisionCheckpoint.%s.v1" % _identity(database_identity)[:32]


def provision_windows_revision_checkpoint_authority(
    database_identity: str | os.PathLike[str],
    *,
    authority_path: str | os.PathLike[str] | None = None,
    provider_id: str | None = None,
    key_name: str | None = None,
) -> RevisionCheckpointSigningAuthority:
    """Create once or reopen one exact CNG key and its separate Cell graph."""
    identity = _identity(database_identity)
    path = (
        Path(authority_path).expanduser().resolve()
        if authority_path is not None
        else default_checkpoint_authority_path(database_identity)
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    store = CellStore(path)
    prefix = "checkpoint-authority:%s:signing" % identity
    descriptor_root = "checkpoint-authority:%s:descriptor:v2" % identity
    authorization_root = "checkpoint-authority:%s:authorization" % identity
    release_root = "checkpoint-authority:%s:release" % identity
    selected_key_name = key_name or default_checkpoint_key_name(database_identity)
    existing = descriptor_root in store.snapshot().cells

    try:
        if existing:
            protocol = project_signing_authority_protocol(
                store.snapshot(), prefix=prefix
            )
            recorded = read_signing_key_descriptor(
                store.snapshot(), protocol, descriptor_root
            )
            recorded_provider = recorded.values["provider-id"]
            if provider_id is not None and provider_id != recorded_provider:
                raise RevisionCheckpointDenied(
                    "checkpoint authority provider selection mismatched"
                )
            selected_provider_id = recorded_provider
            provider = WindowsCngSigningAuthorityProvider(
                provider_id=selected_provider_id,
                key_name=selected_key_name,
                create=False,
            )
        else:
            unexpected = set(store.snapshot().cells) - {NULL_CELL_ID}
            if unexpected:
                raise RevisionCheckpointDenied(
                    "checkpoint authority graph is incomplete"
                )
            candidates = (
                (PLATFORM_PROVIDER_ID, SOFTWARE_PROVIDER_ID)
                if provider_id is None
                else (provider_id,)
            )
            provider = None
            failures: list[Exception] = []
            for candidate in candidates:
                try:
                    provider = WindowsCngSigningAuthorityProvider(
                        provider_id=candidate,
                        key_name=selected_key_name,
                        create=True,
                    )
                    selected_provider_id = candidate
                    break
                except SigningAuthorityDenied as exc:
                    failures.append(exc)
            if provider is None:
                raise RevisionCheckpointDenied(
                    "no admitted Windows checkpoint signing provider is available"
                ) from failures[-1]
            protocol = bootstrap_signing_authority_protocol(
                store, prefix=prefix
            )
            now = datetime.now(timezone.utc).isoformat(
                timespec="microseconds"
            ).replace("+00:00", "Z")
            store.commit(
                store.revision,
                create=(
                    Cell(
                        authorization_root,
                        NULL_CELL_ID,
                        NULL_CELL_ID,
                        b"Local desktop checkpoint authority bootstrap",
                    ),
                    Cell(
                        release_root,
                        NULL_CELL_ID,
                        NULL_CELL_ID,
                        ("WIP local authority provisioned " + now).encode("ascii"),
                    ),
                ),
            )
            build_signing_key_descriptor(
                store,
                protocol,
                provider,
                descriptor_id=descriptor_root,
                resource_version=provider.current_resource,
                authority_id="archhub.local.revision-checkpoint.%s" % identity,
                purpose=RevisionCheckpointGuard.SIGNING_PURPOSE,
                valid_from=now,
                valid_until="none",
                authorization_evidence=authorization_root,
                release_evidence=release_root,
            )

        descriptor = verify_signing_key_descriptor(
            store.snapshot(),
            protocol,
            provider,
            descriptor_root,
            require_signing=True,
        )
        expected = {
            "authority-id": "archhub.local.revision-checkpoint.%s" % identity,
            "purpose": RevisionCheckpointGuard.SIGNING_PURPOSE,
            "provider-id": selected_provider_id,
            "resource-version": provider.current_resource,
            "authorization-evidence": authorization_root,
            "release-evidence": release_root,
        }
        for name, value in expected.items():
            if descriptor.values[name] != value:
                raise RevisionCheckpointDenied(
                    "checkpoint authority %s mismatched" % name
                )
        if authorization_root not in store.snapshot().cells:
            raise RevisionCheckpointDenied(
                "checkpoint authority authorization evidence is missing"
            )
        if release_root not in store.snapshot().cells:
            raise RevisionCheckpointDenied(
                "checkpoint authority release evidence is missing"
            )
        return RevisionCheckpointSigningAuthority(
            store,
            protocol,
            provider,
            descriptor_root,
            authorization_root,
        )
    except Exception:
        store.close()
        raise


__all__ = [
    "default_checkpoint_authority_path",
    "default_checkpoint_key_name",
    "provision_windows_revision_checkpoint_authority",
]
