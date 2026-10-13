from __future__ import annotations

import hashlib
import json
from pathlib import Path
import time

from nodelang.cell_secret_keys import MemorySigningKeyProvider
from nodelang.clean_coordination_host import (
    CleanCoordinationHost,
    _base_catalogue_reconciliation_decision,
)
from nodelang.clean_runtime_bootstrap import provision_clean_runtime
from nodelang.runtime_caller_capability import WindowsDpapiCallerKeyStore
from nodelang.unified_authority_runtime import open_current_authority


def test_base_catalogue_reopen_is_bounded_on_large_fixture(tmp_path):
    root = tmp_path / "runtime"
    provider = MemorySigningKeyProvider(
        "archhub.unified.bootstrap",
        b"clean-coordination-host-key" + b"0" * 5,
    )
    key_store = WindowsDpapiCallerKeyStore(tmp_path / "callers.dpapi.json")
    specification = (Path(__file__).parents[1] / "SPEC.md").read_bytes()
    grand_map = json.dumps(
        [{"key": "brain", "title": "Brain", "nodes": [], "wires": [], "cross": []}],
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    built = provision_clean_runtime(
        root,
        provider,
        key_store,
        caller_key_id="founder.bootstrap",
        specification_source=specification,
        specification_sha256=hashlib.sha256(specification).hexdigest(),
        grand_map_source=grand_map,
        grand_map_sha256=hashlib.sha256(grand_map).hexdigest(),
    )
    built.location.authority.store.close()

    opened = open_current_authority(root, provider)
    try:
        start = time.perf_counter()
        CleanCoordinationHost(opened.authority, key_store, runtime_root=root)
        first = time.perf_counter() - start
    finally:
        opened.authority.store.close()

    reopened = open_current_authority(root, provider)
    try:
        start = time.perf_counter()
        CleanCoordinationHost(reopened.authority, key_store, runtime_root=root)
        bounded = time.perf_counter() - start
        cells = len(reopened.authority.store.snapshot().cells)
    finally:
        reopened.authority.store.close()

    print(
        "CATALOGUE_FIXTURE cells=%d first_install=%.3fs bounded_reopen=%.3fs"
        % (cells, first, bounded)
    )
    assert cells >= 5297
    assert bounded <= 10.0


def test_absent_generation_state_reconciles_all_present_old_contracts(tmp_path):
    should_install, reconcile_existing = _base_catalogue_reconciliation_decision(
        tmp_path / "runtime",
        {},
        False,
        (),
    )
    assert should_install is True
    assert reconcile_existing is True


def test_mixed_missing_and_stale_catalogue_reconciles_existing_too(tmp_path):
    should_install, reconcile_existing = _base_catalogue_reconciliation_decision(
        tmp_path / "runtime",
        {"source_hash": "old", "generation": "old", "warmed": True},
        True,
        ("Properties",),
    )
    assert should_install is True
    assert reconcile_existing is True
