from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import threading
import uuid

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from nodelang.cell_secret_keys import MemorySigningKeyProvider
from nodelang.unified_authority import declare_definition
from nodelang.unified_authority_runtime import (
    open_current_authority,
    provision_unified_authority,
)
from nodelang.universal_cell import DatabaseOwnerConflict, InvalidCell


SECRET = b"archhub-clean-runtime-test-key" + b"0" * 8
CALLER_PRIVATE = Ed25519PrivateKey.from_private_bytes(bytes(range(1, 33)))
CALLER_PUBLIC = CALLER_PRIVATE.public_key().public_bytes(
    serialization.Encoding.Raw,
    serialization.PublicFormat.Raw,
)


class _Caller:
    def __init__(self, authority):
        self.actor_root = authority.manifest.principal_root
        self.session_root = authority.manifest.bootstrap_session_root
        self.public_key = CALLER_PUBLIC

    def sign(self, payload: bytes) -> bytes:
        return CALLER_PRIVATE.sign(payload)


def _provider():
    return MemorySigningKeyProvider("clean-runtime", SECRET)


def _provision(root):
    return provision_unified_authority(
        root,
        _provider(),
        key_id="clean-runtime",
        application_label="ArchHub",
        principal_label="Founder",
        bootstrap_session_label="Runtime test session",
        bootstrap_session_public_key=CALLER_PUBLIC,
        composition_labels=("Brain", "Projects", "Interface"),
    )


def test_provision_selects_one_complete_generation_and_reuses_it(tmp_path):
    first = _provision(tmp_path / "runtime")
    graph_id = first.authority.manifest.graph_id
    database = first.database_path
    manifest = first.manifest_path
    first.authority.store.close()

    second = _provision(tmp_path / "runtime")
    try:
        assert second.authority.manifest.graph_id == graph_id
        assert second.database_path == database
        assert second.manifest_path == manifest
        generations = tuple(
            item for item in (tmp_path / "runtime" / "generations").iterdir()
            if item.is_dir() and not item.name.startswith(".")
        )
        assert len(generations) == 1
        assert (tmp_path / "runtime" / "CURRENT").read_text() == graph_id
    finally:
        second.authority.store.close()


def test_concurrent_provisioning_never_mints_two_graph_roots(tmp_path):
    root = tmp_path / "runtime"
    start = threading.Barrier(2)

    def provision_once():
        start.wait(timeout=10)
        try:
            location = _provision(root)
        except DatabaseOwnerConflict:
            return "active-owner", None
        try:
            return "opened", location.authority.manifest.graph_id
        finally:
            location.authority.store.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(executor.map(lambda _: provision_once(), range(2)))

    graph_ids = {graph_id for _, graph_id in results if graph_id is not None}
    assert len(graph_ids) == 1
    assert {status for status, _ in results} <= {"opened", "active-owner"}
    current = open_current_authority(root, _provider())
    try:
        assert current.authority.manifest.graph_id == next(iter(graph_ids))
        generations = tuple(
            candidate
            for candidate in (root / "generations").iterdir()
            if candidate.is_dir() and not candidate.name.startswith(".")
        )
        assert len(generations) == 1
    finally:
        current.authority.store.close()


def test_current_pointer_fails_closed_on_escape_or_unknown_generation(tmp_path):
    root = tmp_path / "runtime"
    root.mkdir()
    (root / "CURRENT").write_text("../outside", encoding="ascii")
    with pytest.raises(InvalidCell, match="pointer"):
        open_current_authority(root, _provider())

    (root / "CURRENT").write_text(str(uuid.uuid4()), encoding="ascii")
    with pytest.raises(InvalidCell, match="incomplete"):
        open_current_authority(root, _provider())


def test_complete_unselected_generation_is_recovered_without_duplication(tmp_path):
    root = tmp_path / "runtime"
    first = _provision(root)
    graph_id = first.authority.manifest.graph_id
    first.authority.store.close()
    (root / "CURRENT").unlink()

    recovered = _provision(root)
    try:
        assert recovered.authority.manifest.graph_id == graph_id
        assert (root / "CURRENT").read_text() == graph_id
        generations = tuple(
            item for item in (root / "generations").iterdir()
            if item.is_dir() and not item.name.startswith(".")
        )
        assert len(generations) == 1
    finally:
        recovered.authority.store.close()


def test_invalid_generation_is_preserved_and_replaced_only_by_exact_identity(tmp_path):
    root = tmp_path / "runtime"
    first = _provision(root)
    old_graph_id = first.authority.manifest.graph_id
    old_generation = first.generation_root
    first.authority.store.close()
    (old_generation / "bootstrap.json").write_text("{}", encoding="utf-8")

    with pytest.raises(InvalidCell):
        _provision(root)
    with pytest.raises(InvalidCell, match="changed before replacement"):
        provision_unified_authority(
            root,
            _provider(),
            key_id="clean-runtime",
            application_label="ArchHub",
            principal_label="Founder",
            bootstrap_session_label="Runtime test session",
            bootstrap_session_public_key=CALLER_PUBLIC,
            composition_labels=("Brain", "Projects", "Interface"),
            replace_invalid_current=str(uuid.uuid4()),
        )

    replacement = provision_unified_authority(
        root,
        _provider(),
        key_id="clean-runtime",
        application_label="ArchHub",
        principal_label="Founder",
        bootstrap_session_label="Runtime test session",
        bootstrap_session_public_key=CALLER_PUBLIC,
        composition_labels=("Brain", "Projects", "Interface"),
        replace_invalid_current=old_graph_id,
    )
    try:
        assert replacement.authority.manifest.graph_id != old_graph_id
        assert old_generation.is_dir()
        assert (root / "CURRENT").read_text() == replacement.authority.manifest.graph_id
    finally:
        replacement.authority.store.close()


def test_staged_initializer_must_pass_before_current_pointer_changes(tmp_path):
    root = tmp_path / "runtime"
    created: list[str] = []

    def fail_after_write(authority):
        declare_definition(
            authority,
            "Rejected staged definition",
            {"state": "candidate"},
            caller=_Caller(authority),
            command_id="7029117e-d38a-4fe4-b0f6-9c4207de0b15",
        )
        raise RuntimeError("initializer court failure")

    with pytest.raises(RuntimeError, match="initializer court failure"):
        provision_unified_authority(
            root,
            _provider(),
            key_id="clean-runtime",
            application_label="ArchHub",
            principal_label="Founder",
            bootstrap_session_label="Runtime test session",
            bootstrap_session_public_key=CALLER_PUBLIC,
            composition_labels=("Brain", "Projects", "Interface"),
            initialize=fail_after_write,
        )
    assert not (root / "CURRENT").exists()

    def pass_initializer(authority):
        result = declare_definition(
            authority,
            "Accepted staged definition",
            {"state": "accepted"},
            caller=_Caller(authority),
            command_id="bbe1ab26-689c-4c18-9e23-41f08f884d4a",
        )
        created.append(result.root_id)

    accepted = provision_unified_authority(
        root,
        _provider(),
        key_id="clean-runtime",
        application_label="ArchHub",
        principal_label="Founder",
        bootstrap_session_label="Runtime test session",
        bootstrap_session_public_key=CALLER_PUBLIC,
        composition_labels=("Brain", "Projects", "Interface"),
        initialize=pass_initializer,
    )
    try:
        assert len(created) == 1
        assert created[0] in accepted.authority.store.snapshot().cells
        assert (root / "CURRENT").read_text() == accepted.authority.manifest.graph_id
    finally:
        accepted.authority.store.close()
