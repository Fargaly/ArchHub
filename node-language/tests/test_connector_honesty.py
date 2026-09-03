"""Connector honesty — CON-01 + CON-02 (P0).

The founder contract (CLAUDE.md + connectors/base.py): connectors report
honest status (live/loaded_dead/missing/unauthorized) and NEVER fabricate
data / mislabel a result when a host can't actually produce it.

Two specific honesty bugs are pinned here:

CON-01 — an op returns an EMPTY DirectShape (the real geometry is missing
         but the op reports it as a created element). Covered structurally in
         test_revit_speckle_ops.py (the C# generator) AND here at the
         status-derivation boundary.

CON-02 — a write op is MISLABELED: `revit.receive_from_speckle` /
         `revit.batch_set_parameters` reported ok / status="ok" whenever the
         `/exec` HTTP call returned 200, EVEN WHEN the Revit-side script
         created/updated ZERO elements and errored on everything. A write
         that wrote nothing was reported as a success. The fix derives the
         status from the per-item Revit outcome (created/updated vs errors),
         so a zero-write-all-error result is `ok=False` / status="error",
         and a some-made-some-failed result is an honest "partial".
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

from connectors.base import OpResult  # noqa: E402
from connectors.revit_speckle_ops import (  # noqa: E402
    _status_from_create_result,
    _status_from_set_params_result,
)


# ─── CON-02 · status derivation (pure) ───────────────────────────────
#
# These pin the exact truth table the founder's honesty contract demands.

_ITEMS = [{"revit_directshape_category": "OST_GenericModel"}]


def test_create_all_failed_is_error_not_ok():
    """created==0, errors>0 → a FAILED write. Must be status=error (this
    is the exact CON-02 lie: the old code returned ok here)."""
    host = {"created_count": 0, "error_count": 3,
            "created": [], "errors": [{"e": 1}, {"e": 2}, {"e": 3}],
            "skipped_count": 0, "skipped": []}
    out = _status_from_create_result(_ITEMS, host)
    assert out["status"] == "error"
    assert out["created_count"] == 0
    assert out["error_count"] == 3
    assert "no elements were created" in out["error"].lower()


def test_create_partial_is_partial():
    """created>0, errors>0 → honest 'partial', with the failure surfaced."""
    host = {"created_count": 2, "error_count": 1,
            "created": [{"id": 1}, {"id": 2}], "errors": [{"e": 1}],
            "skipped_count": 0, "skipped": []}
    out = _status_from_create_result(_ITEMS, host)
    assert out["status"] == "partial"
    assert out["created_count"] == 2 and out["error_count"] == 1
    assert "failed" in out["error"].lower()


def test_create_clean_is_ok():
    host = {"created_count": 1, "error_count": 0,
            "created": [{"id": 1}], "errors": [],
            "skipped_count": 0, "skipped": []}
    out = _status_from_create_result(_ITEMS, host)
    assert out["status"] == "ok"
    assert out.get("error", "") == ""


def test_create_zero_made_zero_error_with_items_is_error():
    """Items were sent but none created and none errored (all skipped /
    unrecognised) — reporting ok would be the same lie."""
    host = {"created_count": 0, "error_count": 0,
            "created": [], "errors": [],
            "skipped_count": 1, "skipped": [0]}
    out = _status_from_create_result(_ITEMS, host)
    assert out["status"] == "error"
    assert "no elements were created" in out["error"].lower()


def test_create_empty_items_is_ok():
    """Genuinely nothing to do (no items) → ok, not a fake failure."""
    host = {"created_count": 0, "error_count": 0,
            "created": [], "errors": [], "skipped_count": 0, "skipped": []}
    out = _status_from_create_result([], host)
    assert out["status"] == "ok"


def test_counts_derived_from_lists_when_count_keys_missing():
    """A malformed payload that omits the *_count keys must NOT be read as
    a clean zero — counts derive from the list lengths so a hidden error
    can't masquerade as success."""
    host = {"created": [], "errors": [{"e": 1}, {"e": 2}]}  # no count keys
    out = _status_from_create_result(_ITEMS, host)
    assert out["error_count"] == 2
    assert out["status"] == "error"


def test_non_dict_result_is_not_a_success():
    """A non-dict /exec result can't prove any element was created."""
    out = _status_from_create_result(_ITEMS, "weird-non-dict")
    assert out["status"] == "error"


def test_set_params_all_failed_is_error():
    host = {"updated_count": 0, "error_count": 2,
            "updated": [], "errors": [{"e": 1}, {"e": 2}],
            "skipped_count": 0, "skipped": []}
    out = _status_from_set_params_result(_ITEMS, host)
    assert out["status"] == "error"
    assert out["updated_count"] == 0
    assert "no parameters were set" in out["error"].lower()


def test_set_params_partial_is_partial():
    host = {"updated_count": 1, "error_count": 1,
            "updated": [{"id": 1}], "errors": [{"e": 1}],
            "skipped_count": 0, "skipped": []}
    out = _status_from_set_params_result(_ITEMS, host)
    assert out["status"] == "partial"


def test_set_params_clean_is_ok():
    host = {"updated_count": 3, "error_count": 0,
            "updated": [{"id": 1}, {"id": 2}, {"id": 3}], "errors": [],
            "skipped_count": 0, "skipped": []}
    out = _status_from_set_params_result(_ITEMS, host)
    assert out["status"] == "ok"


# ─── CON-02 · connector wrappers (end-to-end through the op) ──────────
#
# These exercise the real connector ops with a monkeypatched `_exec`
# (no live Revit) to prove the OpResult the rest of ArchHub sees carries
# the honest ok/False — the mislabeled-write is fixed at the boundary the
# workflow runner + LLM tool path actually consume.


@pytest.fixture()
def _sandbox_speckle(tmp_path, monkeypatch):
    """Redirect SpeckleWire to a sandbox + seed one DirectShape item so a
    receive call reaches the (patched) /exec step."""
    import speckle_wire
    monkeypatch.setattr(speckle_wire, "default_project_dir",
                        lambda: str(tmp_path), raising=False)
    from connectors.revit_speckle_ops import send_to_speckle
    sent = send_to_speckle(
        value=[{"revit_directshape_category": "OST_GenericModel",
                "revit_geometry_json": {"vertices": [[0, 0, 0], [1, 0, 0],
                                                     [0, 1, 0]],
                                        "faces": [[0, 1, 2]]}}],
        project_dir=str(tmp_path))
    return sent["url"]


def _force_broker_alive(monkeypatch):
    """Make the wrapper's broker-offline guard pass so we reach /exec."""
    import connectors.revit_connector as rc
    if rc.revit_broker is None:
        pytest.skip("revit_broker module not present in this build")
    monkeypatch.setattr(rc.revit_broker, "is_any_alive",
                        lambda: True, raising=False)


def test_receive_op_reports_failure_when_revit_created_nothing(
        _sandbox_speckle, monkeypatch):
    """CON-02 end-to-end: /exec runs (HTTP 200) but every element failed in
    Revit (created_count=0, error_count>0). The op MUST return ok=False —
    the old code returned ok=True for this 'wrote nothing' result."""
    import connectors.revit_connector as rc
    _force_broker_alive(monkeypatch)

    def _fake_exec(op_id, code, **kw):
        # Mimic RunCSharpScript's ctx.result on an all-failed create.
        return {"created_count": 0, "error_count": 1,
                "created": [], "errors": [{"idx": 0, "kind": "directshape",
                                           "error": "boom"}],
                "skipped_count": 0, "skipped": []}

    monkeypatch.setattr(rc, "_exec", _fake_exec, raising=True)
    res = rc._receive_from_speckle_op(source_url=_sandbox_speckle)
    assert isinstance(res, OpResult)
    assert res.ok is False, "a write that created 0 elements must not be ok"
    assert res.error  # carries why


def test_receive_op_reports_partial(_sandbox_speckle, monkeypatch):
    """Some created + some failed → ok=True (work landed) but the error
    detail + a PARTIAL preview ride along so the partial failure is honest,
    not hidden behind a clean 'ok'."""
    import connectors.revit_connector as rc
    _force_broker_alive(monkeypatch)

    def _fake_exec(op_id, code, **kw):
        return {"created_count": 1, "error_count": 1,
                "created": [{"idx": 0, "id": 12345}],
                "errors": [{"idx": 1, "error": "boom"}],
                "skipped_count": 0, "skipped": []}

    monkeypatch.setattr(rc, "_exec", _fake_exec, raising=True)
    res = rc._receive_from_speckle_op(source_url=_sandbox_speckle)
    assert res.ok is True
    assert "PARTIAL" in res.value_preview
    assert res.error and "failed" in res.error.lower()


def test_receive_op_ok_on_clean_create(_sandbox_speckle, monkeypatch):
    """A genuinely clean create stays ok=True with no error noise."""
    import connectors.revit_connector as rc
    _force_broker_alive(monkeypatch)

    def _fake_exec(op_id, code, **kw):
        return {"created_count": 1, "error_count": 0,
                "created": [{"idx": 0, "id": 12345}], "errors": [],
                "skipped_count": 0, "skipped": []}

    monkeypatch.setattr(rc, "_exec", _fake_exec, raising=True)
    res = rc._receive_from_speckle_op(source_url=_sandbox_speckle)
    assert res.ok is True
    assert res.error == ""
    assert "created=1" in res.value_preview


def test_batch_set_params_op_reports_failure_when_nothing_updated(
        tmp_path, monkeypatch):
    """CON-02 sibling: batch_set_parameters that updates 0 elements while
    erroring must return ok=False, not a fake success."""
    import speckle_wire
    monkeypatch.setattr(speckle_wire, "default_project_dir",
                        lambda: str(tmp_path), raising=False)
    import connectors.revit_connector as rc
    _force_broker_alive(monkeypatch)
    from connectors.revit_speckle_ops import send_to_speckle
    sent = send_to_speckle(
        value=[{"revit_element_id": 1001, "revit_parameters": {"W": 5}}],
        project_dir=str(tmp_path))

    def _fake_exec(op_id, code, **kw):
        return {"updated_count": 0, "error_count": 1,
                "updated": [], "errors": [{"idx": 0, "error": "no such el"}],
                "skipped_count": 0, "skipped": []}

    monkeypatch.setattr(rc, "_exec", _fake_exec, raising=True)
    res = rc._batch_set_parameters_op(source_url=sent["url"])
    assert isinstance(res, OpResult)
    assert res.ok is False
    assert res.error
