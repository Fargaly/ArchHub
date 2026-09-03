from __future__ import annotations

import base64
import json

import pytest

from nodelang.cell_secret_keys import MemorySigningKeyProvider
from nodelang.runtime_caller_capability import WindowsDpapiCallerKeyStore
from nodelang.unified_authority import (
    composition_root,
    create_unified_authority,
    declare_definition,
)
from nodelang.universal_cell import CellStore, InvalidCell


pytestmark = pytest.mark.skipif(
    __import__("os").name != "nt",
    reason="DPAPI is a Windows custody boundary",
)


def test_dpapi_caller_key_survives_restart_and_governs_the_graph(tmp_path):
    path = tmp_path / "caller.dpapi.json"
    first_store = WindowsDpapiCallerKeyStore(path)
    public_key = first_store.ensure("founder.bootstrap")
    raw = path.read_bytes()
    assert base64.b64encode(public_key) in raw

    authority = create_unified_authority(
        CellStore(),
        MemorySigningKeyProvider(
            "caller-court", b"caller-court-authority-key" + b"0" * 6
        ),
        key_id="caller-court",
        application_label="ArchHub",
        principal_label="Founder",
        bootstrap_session_label="Founder bootstrap",
        bootstrap_session_public_key=public_key,
        composition_labels=("Governance", "Projects"),
    )
    restarted_store = WindowsDpapiCallerKeyStore(path)
    assert restarted_store.ensure("founder.bootstrap") == public_key
    caller = restarted_store.bind_bootstrap(authority, "founder.bootstrap")
    definition = declare_definition(
        authority,
        "Restart-governed definition",
        {"value": "accepted"},
        caller=caller,
        command_id="71951091-ed1f-482b-aacb-fdc796a9894f",
    )
    assert definition.root_id in authority.store.snapshot().cells
    assert composition_root(
        authority, "Governance", caller=caller
    ) in authority.store.snapshot().cells


def test_dpapi_caller_key_rejects_corrupt_or_mismatched_record(tmp_path):
    path = tmp_path / "caller.dpapi.json"
    store = WindowsDpapiCallerKeyStore(path)
    store.ensure("founder.bootstrap")
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["keys"]["founder.bootstrap"]["public"] = base64.b64encode(
        b"x" * 32
    ).decode("ascii")
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(InvalidCell, match="do not match"):
        WindowsDpapiCallerKeyStore(path).public_key("founder.bootstrap")
