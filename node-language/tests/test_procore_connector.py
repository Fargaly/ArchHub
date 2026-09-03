"""Tests for the Procore connector — the uniform-contract wrapper around
`connectors.procore_runner`.

Mirrors `tests/test_rest_connectors.py`:
  * Runs fully OFFLINE — `urllib.request.urlopen` is mocked everywhere;
    no test opens a socket.
  * Runs with NO token (for the unauthorized-probe + honest-fail tests)
    or a fake token (for the HTTP-mocked happy paths).
  * Asserts the op set the connector exposes.
  * Asserts `probe()` returns 'unauthorized' cleanly when no token, and
    never raises / never hits the network in that branch.
  * Asserts response parsing against small recorded fixtures.
  * Asserts the connector `register()`s onto the base registry and that
    `run_op` resolves a procore op end-to-end.

The token gate every runner op funnels through is
`procore_runner._load_token`, so that is what we patch — flowing through
both the connector ops AND `probe()`.
"""
from __future__ import annotations

import io
import json
import sys
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

APP_ROOT = Path(__file__).resolve().parent.parent / "app"
sys.path.insert(0, str(APP_ROOT))

from connectors import procore_connector, procore_runner  # noqa: E402
from connectors import base as connectors_base  # noqa: E402


# ===========================================================================
# HTTP mock helpers — same shape as test_rest_connectors.py
# ===========================================================================
def _mock_urlopen(payload, *, headers: dict | None = None):
    if isinstance(payload, (dict, list)):
        body = json.dumps(payload).encode("utf-8")
    elif isinstance(payload, bytes):
        body = payload
    else:
        body = str(payload).encode("utf-8")
    resp = MagicMock()
    resp.read.return_value = body
    hdrs = MagicMock()
    hdrs.get.side_effect = lambda k, d=None: (headers or {}).get(k, d)
    resp.headers = hdrs
    cm = MagicMock()
    cm.__enter__ = lambda self_: resp
    cm.__exit__ = lambda self_, *a: False
    return cm


def _mock_http_error(code: int, body: str = ""):
    return urllib.error.HTTPError(
        url="https://api.procore.com", code=code, msg="err",
        hdrs=None, fp=io.BytesIO(body.encode("utf-8")),
    )


UO = "urllib.request.urlopen"


# ===========================================================================
# Recorded fixture payloads — small but realistic Procore responses.
# Procore list endpoints return a bare JSON array; get/create return an
# object. The runner's _request wraps arrays as {"items": [...]} and
# objects as {"data": {...}}.
# ===========================================================================
PROCORE_ME = {
    "id": 7788, "login": "rivka@studio.test", "name": "Rivka Stein",
}
PROCORE_PROJECTS = [
    {"id": 101, "name": "Tower A", "project_number": "23-001",
     "active": True, "address": "1 Main St"},
    {"id": 102, "name": "Annex", "project_number": "23-002",
     "active": True, "address": "2 Side St"},
]
PROCORE_USERS = [
    {"id": 5001, "name": "Dana Cole", "email_address": "dana@gc.test",
     "job_title": "PM", "vendor": {"name": "GC Co"}},
]
PROCORE_RFIS = [
    {"id": 9001, "number": "RFI-014", "subject": "Slab edge detail",
     "status": "open", "due_date": "2026-06-10",
     "assignees": [{"name": "Dana Cole"}]},
    {"id": 9002, "full_number": "RFI-015", "subject": "Curtain wall anchor",
     "status": "closed", "due_date": "2026-05-20", "assignees": []},
]
PROCORE_RFI = {
    "id": 9001, "number": "RFI-014", "subject": "Slab edge detail",
    "status": "open",
    "question": {"body": "What is the slab edge condition at grid C?"},
}
PROCORE_SUBMITTALS = [
    {"id": 4001, "number": "SUB-003", "title": "Rebar shop drawings",
     "status": {"name": "Open"}, "ball_in_court": {"name": "Architect"}},
]
PROCORE_CHANGE_ORDERS = [
    {"id": 3001, "number": "CCO-002", "title": "Added canopy",
     "status": "pending", "amount": "12500.00"},
]
PROCORE_DAILY_LOGS = [
    {"id": 2001, "log_date": "2026-05-29",
     "weather": {"description": "Clear"},
     "notes": "Poured columns L3.",
     "created_by": {"name": "Dana Cole"}},
]
PROCORE_RFI_CREATED = {
    "id": 9100, "number": "RFI-016", "subject": "New RFI",
    "status": "open",
}


# ===========================================================================
# 1. Registration — the connector lands on the base registry.
# ===========================================================================
class TestRegistration:
    def test_procore_registers(self):
        connectors_base.load_all_connectors()
        assert connectors_base.get("procore") is not None, \
            "procore connector did not register"

    def test_host_and_mechanism(self):
        inst = procore_connector.ProcoreConnector()
        assert inst.host == "procore"
        assert inst.mechanism == "rest"
        assert inst.display_name == "Procore"

    def test_registry_instance_is_correct_type(self):
        connectors_base.load_all_connectors()
        assert isinstance(connectors_base.get("procore"),
                          procore_connector.ProcoreConnector)

    def test_appears_in_all_connectors_with_ops(self):
        """all_connectors() exposes procore with its op list — the
        'Procore appears in the connector list' acceptance check."""
        connectors_base.load_all_connectors()
        hosts = {c.host: c for c in connectors_base.all_connectors()}
        assert "procore" in hosts
        d = hosts["procore"].to_dict()
        op_ids = {o["op_id"] for o in d["ops"]}
        assert "procore.list_rfis" in op_ids
        assert len(op_ids) == 8


# ===========================================================================
# 2. Op set — the connector exposes exactly the expected operations.
# ===========================================================================
class TestOpSet:
    def test_procore_op_set(self):
        ops = {o.op_id for o in procore_connector.ProcoreConnector().ops()}
        assert ops == {
            "procore.list_projects", "procore.list_users",
            "procore.list_rfis", "procore.get_rfi",
            "procore.list_submittals", "procore.list_change_orders",
            "procore.list_daily_logs", "procore.create_rfi",
        }

    def test_destructive_ops_flagged(self):
        """create_rfi is the only write — destructive action; the rest
        are non-destructive reads."""
        conn = procore_connector.ProcoreConnector()
        for o in conn.ops():
            if o.op_id == "procore.create_rfi":
                assert o.destructive is True and o.kind == "action", \
                    "create_rfi should be a destructive action"
            else:
                assert o.destructive is False and o.kind == "read", \
                    f"{o.op_id} should be a non-destructive read"

    def test_every_op_has_an_implementation(self):
        for o in procore_connector.ProcoreConnector().ops():
            assert callable(o.fn), f"{o.op_id} has no fn"

    def test_op_lookup_by_id(self):
        conn = procore_connector.ProcoreConnector()
        assert conn.op("procore.list_rfis") is not None
        assert conn.op("procore.nonexistent") is None

    def test_required_inputs_present(self):
        conn = procore_connector.ProcoreConnector()
        get_rfi = conn.op("procore.get_rfi")
        assert any(p.id == "rfi_id" and p.required for p in get_rfi.inputs)
        create = conn.op("procore.create_rfi")
        req = {p.id for p in create.inputs if p.required}
        assert {"subject", "question"} <= req


# ===========================================================================
# 3. probe() honesty — no token => unauthorized, cleanly, never raising.
# ===========================================================================
class TestProbeUnauthorized:
    def test_procore_probe_unauthorized(self):
        with patch.object(procore_runner, "_load_token", return_value=None):
            p = procore_connector.ProcoreConnector().probe()
        assert p["status"] == "unauthorized"
        assert "token" in p["note"].lower()
        assert "settings" in p["note"].lower()

    def test_probe_unauthorized_makes_no_http_call(self):
        """The unauthorized branch must short-circuit before urlopen."""
        with patch.object(procore_runner, "_load_token",
                          return_value=None), \
             patch(UO) as uo:
            procore_connector.ProcoreConnector().probe()
            uo.assert_not_called()

    def test_to_dict_never_raises_without_token(self):
        with patch.object(procore_runner, "_load_token", return_value=None):
            d = procore_connector.ProcoreConnector().to_dict()
        assert d["status"] == "unauthorized"
        assert isinstance(d["ops"], list) and d["ops"]


# ===========================================================================
# 4. probe() live + missing — real lightweight /me auth-check call.
# ===========================================================================
class TestProbeLiveAndMissing:
    def test_procore_probe_live(self):
        with patch.object(procore_runner, "_load_token",
                          return_value="tok"), \
             patch.object(procore_runner, "_load_company_id",
                          return_value=None), \
             patch(UO, return_value=_mock_urlopen(PROCORE_ME)):
            p = procore_connector.ProcoreConnector().probe()
        assert p["status"] == "live"
        assert "Rivka Stein" in p["note"]

    def test_procore_probe_unauthorized_on_401(self):
        with patch.object(procore_runner, "_load_token",
                          return_value="tok"), \
             patch.object(procore_runner, "_load_company_id",
                          return_value=None), \
             patch(UO, side_effect=_mock_http_error(401, "bad token")):
            p = procore_connector.ProcoreConnector().probe()
        assert p["status"] == "unauthorized"
        assert "token" in p["note"].lower()

    def test_procore_probe_missing_on_network_error(self):
        with patch.object(procore_runner, "_load_token",
                          return_value="tok"), \
             patch.object(procore_runner, "_load_company_id",
                          return_value=None), \
             patch(UO, side_effect=urllib.error.URLError("no route")):
            p = procore_connector.ProcoreConnector().probe()
        assert p["status"] == "missing"

    def test_procore_probe_missing_on_500(self):
        with patch.object(procore_runner, "_load_token",
                          return_value="tok"), \
             patch.object(procore_runner, "_load_company_id",
                          return_value=None), \
             patch(UO, side_effect=_mock_http_error(500, "boom")):
            p = procore_connector.ProcoreConnector().probe()
        assert p["status"] == "missing"


# ===========================================================================
# 5. Ops — honest no-token failure (the core acceptance check).
# A read op with NO token returns an honest unauthorized-style failure,
# never crashing, never hitting the network.
# ===========================================================================
class TestOpsNoTokenHonest:
    def _run(self, op_id, **params):
        conn = procore_connector.ProcoreConnector()
        return conn.op(op_id).run(**params)

    @pytest.mark.parametrize("op_id,params", [
        ("procore.list_projects", {}),
        ("procore.list_users", {}),
        ("procore.list_rfis", {}),
        ("procore.get_rfi", {"rfi_id": 9001}),
        ("procore.list_submittals", {}),
        ("procore.list_change_orders", {}),
        ("procore.list_daily_logs", {}),
        ("procore.create_rfi", {"subject": "x", "question": "y"}),
    ])
    def test_read_op_no_token_fails_cleanly(self, op_id, params):
        with patch.object(procore_runner, "_load_token",
                          return_value=None), \
             patch(UO) as uo:
            r = self._run(op_id, **params)
        assert r.ok is False
        assert "token" in r.error.lower()
        assert r.op_id == op_id
        uo.assert_not_called()   # honest failure, no network round-trip


# ===========================================================================
# 6. Ops — response parsing against recorded fixtures (token + mocked HTTP).
# ===========================================================================
class TestProcoreOps:
    def _run(self, op_id, **params):
        conn = procore_connector.ProcoreConnector()
        return conn.op(op_id).run(**params)

    def test_list_projects_parses(self):
        with patch.object(procore_runner, "_load_token",
                          return_value="tok"), \
             patch.object(procore_runner, "_load_company_id",
                          return_value=55), \
             patch(UO, return_value=_mock_urlopen(PROCORE_PROJECTS)):
            r = self._run("procore.list_projects", limit=10)
        assert r.ok is True
        assert isinstance(r.value, list) and len(r.value) == 2
        assert r.value[0]["id"] == 101
        assert r.value[0]["name"] == "Tower A"

    def test_list_users_parses(self):
        with patch.object(procore_runner, "_load_token",
                          return_value="tok"), \
             patch.object(procore_runner, "_load_company_id",
                          return_value=55), \
             patch.object(procore_runner, "_load_project_id",
                          return_value=101), \
             patch(UO, return_value=_mock_urlopen(PROCORE_USERS)):
            r = self._run("procore.list_users")
        assert r.ok is True
        assert len(r.value) == 1
        assert r.value[0]["name"] == "Dana Cole"
        assert r.value[0]["email"] == "dana@gc.test"

    def test_list_rfis_parses(self):
        with patch.object(procore_runner, "_load_token",
                          return_value="tok"), \
             patch.object(procore_runner, "_load_company_id",
                          return_value=55), \
             patch.object(procore_runner, "_load_project_id",
                          return_value=101), \
             patch(UO, return_value=_mock_urlopen(PROCORE_RFIS)):
            r = self._run("procore.list_rfis", limit=20)
        assert r.ok is True
        assert len(r.value) == 2
        assert r.value[0]["number"] == "RFI-014"
        assert r.value[0]["assignee"] == "Dana Cole"

    def test_get_rfi_parses(self):
        with patch.object(procore_runner, "_load_token",
                          return_value="tok"), \
             patch.object(procore_runner, "_load_company_id",
                          return_value=55), \
             patch.object(procore_runner, "_load_project_id",
                          return_value=101), \
             patch(UO, return_value=_mock_urlopen(PROCORE_RFI)):
            r = self._run("procore.get_rfi", rfi_id=9001)
        assert r.ok is True
        assert r.value["id"] == 9001
        assert r.value["subject"] == "Slab edge detail"

    def test_get_rfi_requires_id(self):
        with patch.object(procore_runner, "_load_token",
                          return_value="tok"):
            r = self._run("procore.get_rfi")
        assert r.ok is False
        assert "rfi_id" in r.error

    def test_list_submittals_parses(self):
        with patch.object(procore_runner, "_load_token",
                          return_value="tok"), \
             patch.object(procore_runner, "_load_company_id",
                          return_value=55), \
             patch.object(procore_runner, "_load_project_id",
                          return_value=101), \
             patch(UO, return_value=_mock_urlopen(PROCORE_SUBMITTALS)):
            r = self._run("procore.list_submittals")
        assert r.ok is True
        assert len(r.value) == 1
        assert r.value[0]["title"] == "Rebar shop drawings"
        assert r.value[0]["status"] == "Open"

    def test_list_change_orders_parses(self):
        with patch.object(procore_runner, "_load_token",
                          return_value="tok"), \
             patch.object(procore_runner, "_load_company_id",
                          return_value=55), \
             patch.object(procore_runner, "_load_project_id",
                          return_value=101), \
             patch(UO, return_value=_mock_urlopen(PROCORE_CHANGE_ORDERS)):
            r = self._run("procore.list_change_orders")
        assert r.ok is True
        assert len(r.value) == 1
        assert r.value[0]["number"] == "CCO-002"

    def test_list_daily_logs_parses(self):
        with patch.object(procore_runner, "_load_token",
                          return_value="tok"), \
             patch.object(procore_runner, "_load_company_id",
                          return_value=55), \
             patch.object(procore_runner, "_load_project_id",
                          return_value=101), \
             patch(UO, return_value=_mock_urlopen(PROCORE_DAILY_LOGS)):
            r = self._run("procore.list_daily_logs")
        assert r.ok is True
        assert len(r.value) == 1
        assert r.value[0]["date"] == "2026-05-29"
        assert r.value[0]["weather"] == "Clear"

    def test_create_rfi_writes(self):
        with patch.object(procore_runner, "_load_token",
                          return_value="tok"), \
             patch.object(procore_runner, "_load_company_id",
                          return_value=55), \
             patch.object(procore_runner, "_load_project_id",
                          return_value=101), \
             patch(UO, return_value=_mock_urlopen(PROCORE_RFI_CREATED)):
            r = self._run("procore.create_rfi", subject="New RFI",
                          question="Why?")
        assert r.ok is True
        assert r.value["id"] == 9100

    def test_create_rfi_requires_subject_and_question(self):
        with patch.object(procore_runner, "_load_token",
                          return_value="tok"):
            r1 = self._run("procore.create_rfi", question="y")
            r2 = self._run("procore.create_rfi", subject="x")
        assert r1.ok is False and "subject" in r1.error
        assert r2.ok is False and "question" in r2.error

    def test_rfis_no_project_fails_cleanly(self):
        """Token present but no active project => honest error from the
        runner, surfaced as a clean failed OpResult (not a crash)."""
        with patch.object(procore_runner, "_load_token",
                          return_value="tok"), \
             patch.object(procore_runner, "_load_company_id",
                          return_value=55), \
             patch.object(procore_runner, "_load_project_id",
                          return_value=None):
            r = self._run("procore.list_rfis")
        assert r.ok is False
        assert "project" in r.error.lower()

    def test_list_rfis_401_message(self):
        with patch.object(procore_runner, "_load_token",
                          return_value="tok"), \
             patch.object(procore_runner, "_load_company_id",
                          return_value=55), \
             patch.object(procore_runner, "_load_project_id",
                          return_value=101), \
             patch(UO, side_effect=_mock_http_error(401, "nope")):
            r = self._run("procore.list_rfis")
        assert r.ok is False
        assert "token" in r.error.lower()

    def test_run_never_raises_on_unexpected_exception(self):
        """ConnectorOp.run wraps everything — a urlopen blowing up with a
        non-HTTP error still yields a clean failed OpResult."""
        with patch.object(procore_runner, "_load_token",
                          return_value="tok"), \
             patch.object(procore_runner, "_load_company_id",
                          return_value=55), \
             patch.object(procore_runner, "_load_project_id",
                          return_value=101), \
             patch(UO, side_effect=ValueError("kaboom")):
            r = self._run("procore.list_rfis")
        assert r.ok is False
        assert r.error


# ===========================================================================
# 7. Cross-cutting — run_op resolution through the base registry.
# ===========================================================================
class TestRunOpIntegration:
    def test_run_op_resolves_and_runs(self):
        """connectors.base.run_op must route a procore op_id to the
        procore connector — exercised offline with a mocked HTTP layer."""
        connectors_base.load_all_connectors()
        with patch.object(procore_runner, "_load_token",
                          return_value="tok"), \
             patch.object(procore_runner, "_load_company_id",
                          return_value=55), \
             patch(UO, return_value=_mock_urlopen(PROCORE_PROJECTS)):
            r = connectors_base.run_op("procore.list_projects")
        assert r.ok is True
        assert r.op_id == "procore.list_projects"

    def test_run_op_no_token_returns_honest_unauthorized(self):
        """The headline acceptance check: run_op on a read op with no
        token returns an honest failure rather than crashing."""
        connectors_base.load_all_connectors()
        with patch.object(procore_runner, "_load_token",
                          return_value=None), \
             patch(UO) as uo:
            r = connectors_base.run_op("procore.list_rfis")
        assert r.ok is False
        assert "token" in r.error.lower()
        uo.assert_not_called()
