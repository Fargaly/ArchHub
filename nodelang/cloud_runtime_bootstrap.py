"""Sealed WIP bootstrap for one remote Universal Cell application authority.

This module creates no second semantic store. It admits physical PostgreSQL and
AWS KMS capabilities, then delegates graph build/restore and runtime ownership
to the existing Universal Application.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
from types import MappingProxyType
from typing import Mapping

from .application_server import prepare_shared_universal_runtime
from .cell_secret_keys import (
    AwsKmsHmacSigningKeyProvider,
    SigningKeyError,
)
from .external_revision_witness import (
    DynamoDbRevisionWitnessProvider,
    WitnessedCellJournal,
)
from .postgres_cell_journal import (
    PostgresCellJournal,
    postgres_authority_identity,
)
from .universal_cell import CellStore, InvalidCell


_REQUIRED_KMS_KEYS = frozenset(
    (
        "archhub.local.relationship-authority",
        "archhub.local.court-attestation",
    )
)
_KEY_MAP_LIMIT = 65_536
_DSN_LIMIT = 8_192


@dataclass(frozen=True, slots=True)
class CloudRuntimeConfiguration:
    """Validated physical capabilities; the DSN is always redacted from repr."""

    authority_id: str
    kms_keys: Mapping[str, Mapping[int, str]]
    revision_witness_table: str
    host: str
    port: int
    postgres_dsn: str = field(repr=False)


def _required_text(
    environment: Mapping[str, str],
    name: str,
    *,
    maximum_bytes: int,
) -> str:
    value = environment.get(name)
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value.encode("utf-8")) > maximum_bytes
    ):
        raise InvalidCell("cloud runtime configuration is incomplete")
    return value.strip()


def _parse_key_map(raw: str) -> Mapping[str, Mapping[int, str]]:
    try:
        decoded = json.loads(raw)
    except (TypeError, ValueError):
        raise SigningKeyError("AWS KMS key map is invalid") from None
    if not isinstance(decoded, dict) or not decoded:
        raise SigningKeyError("AWS KMS key map is invalid")
    normalized: dict[str, Mapping[int, str]] = {}
    for key_id, versions in decoded.items():
        if not isinstance(versions, dict) or not versions:
            raise SigningKeyError("AWS KMS key map is invalid")
        admitted_versions: dict[int, str] = {}
        for raw_version, key_arn in versions.items():
            if (
                not isinstance(raw_version, str)
                or not raw_version.isascii()
                or not raw_version.isdecimal()
                or not 1 <= len(raw_version) <= 10
            ):
                raise SigningKeyError("AWS KMS key map version is invalid")
            version = int(raw_version)
            if version in admitted_versions:
                raise SigningKeyError("AWS KMS key map version is ambiguous")
            admitted_versions[version] = key_arn
        normalized[key_id] = MappingProxyType(admitted_versions)
    missing = _REQUIRED_KMS_KEYS.difference(normalized)
    if missing:
        raise SigningKeyError(
            "AWS KMS key map lacks a required logical authority"
        )
    AwsKmsHmacSigningKeyProvider(normalized, client=object())
    return MappingProxyType(normalized)


def load_cloud_runtime_configuration(
    environment: Mapping[str, str],
) -> CloudRuntimeConfiguration:
    """Validate one complete environment without rendering secret values."""
    if not isinstance(environment, Mapping):
        raise TypeError("cloud runtime environment must be a mapping")
    dsn = _required_text(
        environment,
        "ARCHHUB_UNIVERSAL_POSTGRES_DSN",
        maximum_bytes=_DSN_LIMIT,
    )
    if not (
        dsn.startswith("postgresql://")
        or dsn.startswith("postgres://")
    ):
        raise InvalidCell("cloud runtime database capability is invalid")
    authority_id = _required_text(
        environment,
        "ARCHHUB_UNIVERSAL_POSTGRES_AUTHORITY_ID",
        maximum_bytes=128,
    )
    postgres_authority_identity(authority_id)
    raw_keys = _required_text(
        environment,
        "ARCHHUB_AWS_KMS_HMAC_KEYS",
        maximum_bytes=_KEY_MAP_LIMIT,
    )
    kms_keys = _parse_key_map(raw_keys)
    revision_witness_table = _required_text(
        environment,
        "ARCHHUB_DYNAMODB_REVISION_WITNESS_TABLE",
        maximum_bytes=255,
    )
    DynamoDbRevisionWitnessProvider(
        revision_witness_table,
        client=object(),
    )
    host = environment.get("HOST", "0.0.0.0")
    if not isinstance(host, str) or not host or len(host) > 255:
        raise InvalidCell("cloud runtime host is invalid")
    try:
        port = int(environment.get("PORT", "8482"))
    except (TypeError, ValueError):
        raise InvalidCell("cloud runtime port is invalid") from None
    if not 1 <= port <= 65_535:
        raise InvalidCell("cloud runtime port is invalid")
    return CloudRuntimeConfiguration(
        authority_id=authority_id,
        kms_keys=kms_keys,
        revision_witness_table=revision_witness_table,
        host=host,
        port=port,
        postgres_dsn=dsn,
    )


def create_cloud_application_server(
    configuration: CloudRuntimeConfiguration,
    *,
    kms_client=None,
    dynamodb_client=None,
    connection_factory=None,
    map_path=None,
    court_workspace_root=None,
    runtime_compliance_runner=None,
):
    """Construct, but do not start, one fenced remote application server."""
    if not isinstance(configuration, CloudRuntimeConfiguration):
        raise TypeError("cloud runtime configuration is invalid")
    key_provider = AwsKmsHmacSigningKeyProvider(
        configuration.kms_keys,
        client=kms_client,
    )
    witness_provider = DynamoDbRevisionWitnessProvider(
        configuration.revision_witness_table,
        client=dynamodb_client,
    )
    journal = PostgresCellJournal(
        configuration.postgres_dsn,
        authority_id=configuration.authority_id,
        connection_factory=connection_factory,
    )
    witnessed_journal = WitnessedCellJournal(
        journal,
        witness_provider,
        authority_id=configuration.authority_id,
        provision_genesis=False,
    )
    try:
        store = CellStore(journal=witnessed_journal)
    except Exception:
        witnessed_journal.close()
        raise
    prepared = prepare_shared_universal_runtime(
        store,
        map_path=map_path,
        key_provider=key_provider,
        court_workspace_root=court_workspace_root,
        runtime_compliance_runner=runtime_compliance_runner,
    )
    server_kwargs = {
        "live_watch": False,
    }
    if court_workspace_root is not None:
        server_kwargs["universal_workspace_root"] = court_workspace_root
    return prepared.create_server(
        configuration.host,
        configuration.port,
        **server_kwargs,
    )


__all__ = [
    "CloudRuntimeConfiguration",
    "load_cloud_runtime_configuration",
    "create_cloud_application_server",
]
