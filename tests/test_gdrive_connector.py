"""Court gate (artifact lens) for the self-extension Google Drive connector.

This is the machine-checkable leaf the ROMA court runs against the REAL
artifact on a clean machine with nothing installed and no Google account:

  * GDriveConnector().probe()['status'] is honest when no token is present
    — it must be 'missing' or 'unauthorized', NEVER 'live' and NEVER
    fabricated data (the excel_connector.py:547 / dropbox honest-status
    contract).
  * ops_status()['ok'] is True — build_ops() did not raise; the capability
    layer is real, not a silent-empty shell.
  * every op_id starts 'gdrive.' and is a well-formed ConnectorOp.
  * the connector self-registers in the global registry (the app discovers
    it) and run_op dispatches an op against it, returning a real typed
    OpResult envelope (honest failure, not a crash, when no token).

Runs with NO Google credentials and NO external app — the whole point of
the honest-status contract.
"""
from __future__ import annotations

import sys
from pathlib import Path

# app/ is the import root for connectors, same as the other connector tests.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))

from connectors.base import (  # noqa: E402
    Connector, ConnectorOp, OpResult, get, load_all_connectors, run_op,
)
from connectors.gdrive_connector import GDriveConnector  # noqa: E402


_VALID_STATUS = {"live", "loaded_dead", "missing", "unauthorized"}


def test_probe_is_honest_without_credentials():
    """No token on a clean machine -> honest missing/unauthorized, never
    a fabricated 'live'."""
    st = GDriveConnector().probe()
    assert isinstance(st, dict)
    assert st.get("status") in _VALID_STATUS
    # Without a token the connector cannot be authenticated — it must say so.
    assert st.get("status") in {"missing", "unauthorized"}, (
        f"probe() returned {st.get('status')!r} with no credentials — "
        "must be 'missing' or 'unauthorized', never fabricated 'live'")


def test_ops_status_ok_and_real():
    """build_ops() succeeded (not a raising shell) and yields real ops."""
    c = GDriveConnector()
    status = c.ops_status()
    assert status["ok"] is True, f"ops_status not ok: {status}"
    assert status["count"] >= 1
    assert status["error"] == ""


def test_every_op_id_is_namespaced_and_wellformed():
    """Every op is a real ConnectorOp under the 'gdrive.' namespace with a
    callable fn and a valid kind."""
    c = GDriveConnector()
    ops = c.ops()
    assert ops, "no ops — shell connector"
    for o in ops:
        assert isinstance(o, ConnectorOp)
        assert o.op_id.startswith("gdrive."), (
            f"op_id {o.op_id!r} not under 'gdrive.' namespace")
        assert o.host == "gdrive"
        assert callable(o.fn), f"{o.op_id}: fn not callable (stub)"
        assert o.kind in {"read", "action"}
    # A read op and an action op both exist (list_files + upload).
    kinds = {o.kind for o in ops}
    assert "read" in kinds and "action" in kinds


def test_connector_registers_and_dispatches():
    """It self-registers in the global registry and run_op dispatches a
    real typed OpResult envelope — an honest failure (no token) rather
    than fabricated data or a crash."""
    load_all_connectors()
    c = get("gdrive")
    assert isinstance(c, Connector), "gdrive not in the connector registry"
    res = run_op("gdrive.list_files")
    assert isinstance(res, OpResult), "run_op did not return an OpResult"
    assert res.op_id == "gdrive.list_files"
    # With no token this must be an honest failure, not fabricated data.
    assert res.ok is False
    assert res.value is None
    assert "token" in (res.error or "").lower()
