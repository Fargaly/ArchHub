"""FIN-05 — DashScope spend must be visible: a real balance probe.

The gap (FIN-05): the DashScope connector shipped an image-gen MCP with a live
key but NO way to see what it costs — there was no `dashscope.balance` op, and
DashScope's own `sk-` API has no billing endpoint. Spend was invisible.

The fix: `dashscope.balance` performs the REAL Alibaba BSS OpenAPI
`QueryAccountBalance` call (RPC, version 2017-12-14, signature method **V3**
``ACS3-HMAC-SHA256`` signed with a RAM AccessKey pair resolved through the
canonical op:// resolver) and returns the live AvailableAmount + Currency. When
the AccessKey pair is not configured it returns an honest `ok=False` naming the
op:// refs to set — it NEVER fabricates a figure and NEVER raises.

These tests pin three things that all go RED on origin/main (where `_balance`,
`_sign_v3`, and the `dashscope.balance` op do not exist → AttributeError):

  1. the op is REGISTERED on the connector (discoverable + callable);
  2. the V3 signature matches Alibaba's published canonical example
     byte-for-byte (proves the signer is real, not a stub — a fake signer
     would never authenticate the live call). V3 signs with HMAC-SHA256,
     superseding the legacy V1 HMAC-SHA1 RPC scheme;
  3. the honest-status contract: missing AccessKey → ok=False naming the refs
     and a None balance (no fabrication); a stubbed BSS 200 → the real figure
     is parsed out and returned.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

import connectors.dashscope_connector as dash  # noqa: E402
from connectors.base import get, OpResult       # noqa: E402


# ── 1 · the op exists + is registered ───────────────────────────────


def test_dashscope_balance_op_registered():
    """The whole gap was 'no probe'. The op must be on the connector — this
    is the line that does not exist on origin/main."""
    c = get("dashscope")
    op_ids = {o.op_id for o in c.ops()}
    assert "dashscope.balance" in op_ids
    op = c.op("dashscope.balance")
    assert op is not None
    assert op.kind == "read"
    assert op.fn is dash._balance


# ── 2 · the signer is REAL (Alibaba V3 canonical example) ────────────


def test_sign_v3_matches_alibaba_canonical_example():
    """Alibaba's documented signature-method-V3 (ACS3-HMAC-SHA256) worked
    example reproduces byte-for-byte. Inputs + expected signature are from the
    official spec (sdk/product-overview/v3-request-structure-and-signature):
    AccessKeySecret 'YourAccessKeySecret', POST RunInstances, this exact header
    + query set → this exact hex signature. A stub/placeholder signer cannot
    reproduce it; a real one does. This is what authenticates the live billing
    call — and it is HMAC-SHA256 (V3), not the legacy SHA-1."""
    params = {
        "ImageId": "win2019_1809_x64_dtc_zh-cn_40G_alibase_20230811.vhd",
        "RegionId": "cn-shanghai",
    }
    headers = {
        "host": "ecs.cn-shanghai.aliyuncs.com",
        "x-acs-action": "RunInstances",
        "x-acs-content-sha256":
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        "x-acs-date": "2023-10-26T10:22:32Z",
        "x-acs-signature-nonce": "3156853299f313e23d1673dc12e1703d",
        "x-acs-version": "2014-05-26",
    }
    sig, signed_headers = dash._sign_v3("POST", params, headers,
                                        "YourAccessKeySecret")
    assert sig == (
        "06563a9e1b43f5dfe96b81484da74bceab24a1d853912eee15083a6f0f3283c0")
    assert signed_headers == (
        "host;x-acs-action;x-acs-content-sha256;x-acs-date;"
        "x-acs-signature-nonce;x-acs-version")


# ── 3 · honest-status contract ───────────────────────────────────────


def test_balance_missing_accesskey_is_honest_fail_no_fabrication(monkeypatch):
    """No AccessKey configured (and the model sk- key alone can't read
    billing) → ok=False, balance None, the op:// refs named. The banned
    behaviour is fabricating a number; this proves it doesn't."""
    # Model key present — proves it is NOT what unlocks billing.
    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-model-key")
    monkeypatch.delenv("DASHSCOPE_AK_ID", raising=False)
    monkeypatch.delenv("DASHSCOPE_AK_SECRET", raising=False)
    # Resolver returns nothing (no op CLI / keyring / env) → unconfigured.
    monkeypatch.setattr(dash, "_resolve_secret", lambda ref: None)

    res = dash._balance()
    assert isinstance(res, OpResult)
    assert res.ok is False
    assert res.value["available"] is None
    assert res.value["configured"] is False
    # Names the exact references the founder must set — not a vague error.
    assert dash._AK_ID_REF in res.error
    assert dash._AK_SECRET_REF in res.error
    # And it must never have raised.


def test_balance_parses_real_figure_from_signed_bss_call(monkeypatch):
    """With an AccessKey pair (here via the dev-env escape hatch) and a stubbed
    BSS 200 envelope, the op signs + posts a real request and parses the live
    AvailableAmount/Currency out of the BSS Data block."""
    monkeypatch.setenv("DASHSCOPE_AK_ID", "testid")
    monkeypatch.setenv("DASHSCOPE_AK_SECRET", "testsecret")

    captured = {}

    class _Resp:
        status = 200

        def __init__(self, payload):
            self._p = payload

        def read(self):
            import json
            return json.dumps(self._p).encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def _fake_urlopen(req, timeout=0):
        # Capture the real signed request the op built.
        captured["url"] = req.full_url
        captured["data"] = (req.data or b"").decode("utf-8")
        # Header keys are normalised to .capitalize() by urllib's Request.
        captured["headers"] = {k.lower(): v for k, v in req.header_items()}
        return _Resp({
            "Code": "Success",
            "Success": True,
            "RequestId": "REQ-123",
            "Data": {
                "AvailableAmount": "42.50",
                "Currency": "USD",
                "AvailableCashAmount": "42.50",
                "CreditAmount": "0",
                "MybankCreditAmount": "0",
            },
        })

    monkeypatch.setattr(dash.urllib.request, "urlopen", _fake_urlopen)

    res = dash._balance()
    assert res.ok is True
    assert res.value["available"] == "42.50"
    assert res.value["currency"] == "USD"
    assert res.value["request_id"] == "REQ-123"
    assert "42.50" in res.value_preview and "USD" in res.value_preview
    # The request the op actually built was a signature-method-V3 (SHA256)
    # BSS QueryAccountBalance: action/version in x-acs-* headers, an
    # ACS3-HMAC-SHA256 Authorization header, and no fabricated body.
    hdrs = captured["headers"]
    assert hdrs.get("x-acs-action") == "QueryAccountBalance"
    assert hdrs.get("x-acs-version") == "2017-12-14"
    auth = hdrs.get("authorization", "")
    assert auth.startswith("ACS3-HMAC-SHA256 ")
    assert "Credential=testid" in auth
    assert "Signature=" in auth
    # The raw signed response is NOT leaked back into the op's value.
    assert "raw" not in res.value


def test_balance_bss_rejection_is_honest_fail(monkeypatch):
    """A BSS error envelope (e.g. AccessKey not authorized for billing) must
    surface as ok=False with the code — never a silent or fake success."""
    monkeypatch.setenv("DASHSCOPE_AK_ID", "testid")
    monkeypatch.setenv("DASHSCOPE_AK_SECRET", "testsecret")

    class _Resp:
        status = 200

        def read(self):
            import json
            return json.dumps({
                "Code": "Forbidden.RAM",
                "Success": False,
                "Message": "not authorized",
            }).encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(dash.urllib.request, "urlopen",
                        lambda req, timeout=0: _Resp())
    res = dash._balance()
    assert res.ok is False
    assert "Forbidden.RAM" in res.error
    assert res.value["available"] is None
