"""Fail-closed configuration courts for the remote Universal runtime."""
from __future__ import annotations

import importlib
import json

import pytest

from nodelang.cell_secret_keys import SigningKeyError
from nodelang.universal_cell import InvalidCell


_RELATIONSHIP_ARN = (
    "arn:aws:kms:me-central-1:111122223333:"
    "key/11111111-1111-1111-1111-111111111111"
)
_COURT_ARN = (
    "arn:aws:kms:me-central-1:111122223333:"
    "key/22222222-2222-2222-2222-222222222222"
)


def _module():
    return importlib.import_module("nodelang.cloud_runtime_bootstrap")


def _environment():
    return {
        "ARCHHUB_UNIVERSAL_POSTGRES_DSN": (
            "postgresql://fixture.invalid/archhub?sslmode=require"
        ),
        "ARCHHUB_UNIVERSAL_POSTGRES_AUTHORITY_ID": "archhub-production",
        "ARCHHUB_AWS_KMS_HMAC_KEYS": json.dumps(
            {
                "archhub.local.relationship-authority": {
                    "1": _RELATIONSHIP_ARN,
                },
                "archhub.local.court-attestation": {
                    "1": _COURT_ARN,
                },
            }
        ),
        "ARCHHUB_DYNAMODB_REVISION_WITNESS_TABLE": (
            "archhub-production-revision-witness"
        ),
        "HOST": "0.0.0.0",
        "PORT": "8482",
    }


def test_cloud_configuration_is_complete_bounded_and_secret_safe():
    configuration = _module().load_cloud_runtime_configuration(_environment())

    assert configuration.authority_id == "archhub-production"
    assert configuration.host == "0.0.0.0"
    assert configuration.port == 8482
    assert (
        configuration.revision_witness_table
        == "archhub-production-revision-witness"
    )
    assert configuration.kms_keys[
        "archhub.local.relationship-authority"
    ][1] == _RELATIONSHIP_ARN
    assert "never-render" not in repr(configuration)
    assert configuration.postgres_dsn not in repr(configuration)


def test_cloud_configuration_rejects_partial_or_extra_key_authority():
    module = _module()
    for missing in (
        "ARCHHUB_UNIVERSAL_POSTGRES_DSN",
        "ARCHHUB_UNIVERSAL_POSTGRES_AUTHORITY_ID",
        "ARCHHUB_AWS_KMS_HMAC_KEYS",
        "ARCHHUB_DYNAMODB_REVISION_WITNESS_TABLE",
    ):
        environment = _environment()
        secret = environment["ARCHHUB_UNIVERSAL_POSTGRES_DSN"]
        del environment[missing]
        with pytest.raises(InvalidCell) as captured:
            module.load_cloud_runtime_configuration(environment)
        assert secret not in str(captured.value)

    environment = _environment()
    environment["ARCHHUB_AWS_KMS_HMAC_KEYS"] = json.dumps(
        {
            "archhub.local.relationship-authority": {
                "1": _RELATIONSHIP_ARN,
            },
        }
    )
    with pytest.raises(SigningKeyError, match="required logical"):
        module.load_cloud_runtime_configuration(environment)


def test_cloud_server_factory_preserves_kms_store_fence_server_order(
    monkeypatch,
):
    module = _module()
    configuration = module.load_cloud_runtime_configuration(_environment())
    events = []

    class Kms:
        def __init__(self, keys, *, client=None):
            events.append(("kms", keys, client))

    class Journal:
        def __init__(
            self,
            dsn,
            *,
            authority_id,
            connection_factory=None,
        ):
            events.append(
                (
                    "journal",
                    dsn,
                    authority_id,
                    connection_factory,
                )
            )

    class WitnessProvider:
        def __init__(self, table, *, client=None):
            events.append(("witness-provider", table, client))

    class WitnessedJournal:
        def __init__(
            self,
            journal,
            provider,
            *,
            authority_id,
            provision_genesis=False,
        ):
            events.append(
                (
                    "witnessed-journal",
                    journal,
                    provider,
                    authority_id,
                    provision_genesis,
                )
            )

    class Store:
        def __init__(self, *, journal):
            events.append(("store", journal))

    class Prepared:
        def create_server(self, host, port, **kwargs):
            events.append(("server", host, port, kwargs))
            return "server"

    def prepare(store, **kwargs):
        events.append(("prepare", store, kwargs))
        return Prepared()

    monkeypatch.setattr(module, "AwsKmsHmacSigningKeyProvider", Kms)
    monkeypatch.setattr(module, "PostgresCellJournal", Journal)
    monkeypatch.setattr(
        module,
        "DynamoDbRevisionWitnessProvider",
        WitnessProvider,
    )
    monkeypatch.setattr(module, "WitnessedCellJournal", WitnessedJournal)
    monkeypatch.setattr(module, "CellStore", Store)
    monkeypatch.setattr(module, "prepare_shared_universal_runtime", prepare)

    result = module.create_cloud_application_server(
        configuration,
        kms_client="kms-client",
        dynamodb_client="dynamodb-client",
        connection_factory="connection-factory",
        court_workspace_root="court-root",
    )

    assert result == "server"
    assert [event[0] for event in events] == [
        "kms",
        "witness-provider",
        "journal",
        "witnessed-journal",
        "store",
        "prepare",
        "server",
    ]
    assert events[-1] == (
        "server",
        "0.0.0.0",
        8482,
        {
            "live_watch": False,
            "universal_workspace_root": "court-root",
        },
    )
