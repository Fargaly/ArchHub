"""Tests for the SELF-EXTENSION UI RUNG (free-form agent UI + guardrails).

Founder steer: "ALLOW AGENT FREE-FORM UI CODE BUT PUT GUARDRAILS AGAINST BAD
EDITS." These tests prove, programmatically (NO live app — the live ui_renders
court launch is SKIPPED via ARCHHUB_UI_RENDERS_SKIP=1 so the suite stays
hermetic):

  WIDGET TOOL   create_ui_widget is on the composer BUILD surface + gated.
  PERSIST       _build_ui_widget writes a REAL widget to the jailed LOCALAPPDATA
                widgets registry (sanitized id), not the repo tree.
  COURT         court_verify maps ui_renders → the live probe; with the live
                launch skipped the verdict is needs_root (inconclusive), NEVER a
                false green — the probe fail-closes / escalates, it never greens
                blind.
  AUTO-REVERT   a RED ui_renders verdict auto-unregisters the widget (the
                guardrail); a NON-green verdict that is needs_root does NOT
                revert (the widget is fine, only unverified).
  JAIL          the revert/delete primitive is path-confined to the widgets dir —
                a crafted id can never escape it.
  PROBE         make_ui_renders_probe greens ONLY on rendered+app_alive+no-errors,
                refutes on app-blank / errors / not-rendered, and treats a
                non-runnable env as inapplicable (→ needs_root, not green).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_BRAIN_SRC = _ROOT / "personal-brain-mcp" / "src"
if str(_BRAIN_SRC) not in sys.path:
    sys.path.insert(0, str(_BRAIN_SRC))

pytest.importorskip("pydantic")
pytest.importorskip("personal_brain.roma")

import widgets                                # noqa: E402
from agents import composer_agent             # noqa: E402
from agents import self_extend                # noqa: E402


_WID = "selfext_probe_widget"
# A minimal valid free-form widget body (returns a React element). data-testid is
# set on the root so the court's live probe can assert it.
_GOOD_CODE = (
    "return React.createElement('div', "
    "{'data-testid': 'agent-widget-" + _WID + "'}, 'hello from a widget');"
)


@pytest.fixture(autouse=True)
def _isolate_widgets(tmp_path, monkeypatch):
    """Point the widgets registry at a throwaway dir so the test never touches
    the founder's real LOCALAPPDATA widgets, and SKIP the live ui_renders launch
    (hermetic suite — no app spawn)."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("ARCHHUB_UI_RENDERS_SKIP", "1")
    # widgets_dir reads LOCALAPPDATA fresh each call, so the env override is live.
    yield


def _store():
    from personal_brain.storage import BrainStore
    return BrainStore.open(":memory:")


# ── WIDGET TOOL — create_ui_widget on the composer BUILD surface ─────────────


def test_create_ui_widget_in_tool_schema_and_build_tools():
    names = {t["name"] for t in composer_agent.TOOL_SCHEMA}
    assert "create_ui_widget" in names
    assert "create_ui_widget" in composer_agent.BUILD_TOOLS
    assert "create_ui_widget" in composer_agent.WRITE_TOOLS
    assert self_extend.is_build_tool("create_ui_widget")


def test_create_ui_widget_is_gated_in_plan_and_auto():
    # A build is a WRITE → gated under Plan/Auto, free under YOLO.
    assert composer_agent.mode_gates_write("plan", "create_ui_widget") is True
    assert composer_agent.mode_gates_write("auto", "create_ui_widget") is True
    assert composer_agent.mode_gates_write("yolo", "create_ui_widget") is False


# ── PERSIST — the build writes a REAL widget to the jailed registry ───────────


def test_build_ui_widget_persists_to_registry():
    build = self_extend.build_artifact("create_ui_widget", {
        "id": _WID, "title": "Probe", "code": _GOOD_CODE, "slots": ["get_models"],
    })
    assert build["ok"] is True
    assert build["kind"] == "ui_widget"
    assert build["widget_id"] == _WID
    assert build["gate_kind"] == "ui_renders"
    assert build["gate_spec"]["widget_id"] == _WID
    # The widget really persisted + is listed.
    got = widgets.get_widget(_WID)
    assert got is not None and got["id"] == _WID and got["code"] == _GOOD_CODE
    assert any(w["id"] == _WID for w in widgets.list_widgets())


def test_build_ui_widget_sanitizes_a_dangerous_id():
    build = self_extend.build_artifact("create_ui_widget", {
        "id": "../../etc/passwd", "code": _GOOD_CODE,
    })
    assert build["ok"] is True
    wid = build["widget_id"]
    assert "/" not in wid and ".." not in wid and "\\" not in wid
    # The file lives directly under the jail, named by the sanitized id.
    assert widgets.widget_path(wid).parent == widgets.widgets_dir()


def test_build_ui_widget_rejects_empty_code():
    build = self_extend.build_artifact("create_ui_widget", {"id": "x", "code": ""})
    assert build["ok"] is False
    assert "code" in build["error"].lower()


# ── COURT — ui_renders never greens blind; with launch skipped → needs_root ──


def test_court_ui_renders_needs_root_when_live_skipped():
    build = self_extend.build_artifact("create_ui_widget",
                                       {"id": _WID, "code": _GOOD_CODE})
    store = _store()
    try:
        court = self_extend.court_verify(build, store=store)
    finally:
        store.close()
    assert court["gate_kind"] == "ui_renders"
    # The live launch is skipped → the artifact lens is INAPPLICABLE → the court
    # escalates (needs_root). It NEVER greens an unverified free-form widget.
    assert court["green"] is False
    assert court["verdict"] == "needs_root"


# ── AUTO-REVERT — a RED verdict unregisters the widget (the guardrail) ───────


def test_auto_revert_on_red_verdict(monkeypatch):
    build = self_extend.build_artifact("create_ui_widget",
                                       {"id": _WID, "code": _GOOD_CODE})
    assert widgets.get_widget(_WID) is not None  # built first

    # Force the court to RED (simulate a widget that blanked the app / errored)
    # so we exercise the auto-revert branch deterministically.
    monkeypatch.setattr(self_extend, "court_verify",
                        lambda b, **k: {"ok": True, "green": False,
                                        "verdict": "red", "gate_kind": "ui_renders",
                                        "court_reason": "ANTI-BLANK FAIL (simulated)"})
    # No brain write should happen on a red verdict (learn skips).
    receipt = self_extend.run_self_extend(
        "create_ui_widget", {"id": _WID, "code": _GOOD_CODE},
        brain_call=lambda *a, **k: {"ops_applied": 1})
    assert receipt["auto_reverted"] is True
    assert receipt["reverted"]["ok"] is True
    # The widget is GONE — the app is restored, no broken widget left applied.
    assert widgets.get_widget(_WID) is None
    assert receipt["seams"]["brain"] is False  # never learned a refuted widget


def test_needs_root_does_not_revert(monkeypatch):
    self_extend.build_artifact("create_ui_widget", {"id": _WID, "code": _GOOD_CODE})
    monkeypatch.setattr(self_extend, "court_verify",
                        lambda b, **k: {"ok": True, "green": False,
                                        "verdict": "needs_root",
                                        "gate_kind": "ui_renders"})
    receipt = self_extend.run_self_extend(
        "create_ui_widget", {"id": _WID, "code": _GOOD_CODE},
        brain_call=lambda *a, **k: {"ops_applied": 1})
    # needs_root = unverified, not refuted → the widget STAYS (founder verifies).
    assert receipt.get("auto_reverted") in (False, None)
    assert widgets.get_widget(_WID) is not None


# ── JAIL — revert/delete is path-confined to the widgets dir ─────────────────


def test_revert_ui_widget_is_path_jailed():
    # A crafted id cannot escape the jail; delete_widget sanitizes + commonpath-
    # confines, so a traversal id is neutralized (it can only target a sanitized
    # file inside the jail, which does not exist → idempotent ok/removed False).
    res = self_extend.revert_ui_widget("../../../../Windows/system32/evil")
    assert res["ok"] is True
    assert res.get("removed") is False  # nothing dangerous was touched


def test_revert_removes_a_built_widget():
    self_extend.build_artifact("create_ui_widget", {"id": _WID, "code": _GOOD_CODE})
    assert widgets.get_widget(_WID) is not None
    res = self_extend.revert_ui_widget(_WID)
    assert res["ok"] is True and res["removed"] is True
    assert widgets.get_widget(_WID) is None


# ── PROBE — make_ui_renders_probe verdict logic (the 3 assertions) ───────────


def _probe_with(result):
    from personal_brain.court_harness import make_ui_renders_probe
    return make_ui_renders_probe(live_probe=lambda gs, ctx: result)


def test_probe_green_only_on_all_three():
    probe = _probe_with({"applied": True, "rendered": True, "app_alive": True,
                         "errors": [], "evidence_ref": "cdp:ui_widget:w"})
    res = probe({"widget_id": "w"}, {})
    assert res.passed is True and res.applied is True


def test_probe_refutes_on_app_blank():
    probe = _probe_with({"applied": True, "rendered": True, "app_alive": False,
                         "errors": []})
    res = probe({"widget_id": "w"}, {})
    assert res.passed is False and res.applied is True
    assert "ANTI-BLANK" in res.detail


def test_probe_refutes_on_console_errors():
    probe = _probe_with({"applied": True, "rendered": True, "app_alive": True,
                         "errors": ["boom"]})
    res = probe({"widget_id": "w"}, {})
    assert res.passed is False and "error" in res.detail.lower()


def test_probe_refutes_when_not_rendered():
    probe = _probe_with({"applied": True, "rendered": False, "app_alive": True,
                         "errors": []})
    res = probe({"widget_id": "w"}, {})
    assert res.passed is False and "render" in res.detail.lower()


def test_probe_inapplicable_when_env_cannot_run():
    probe = _probe_with({"applied": False, "detail": "no app / no CDP"})
    res = probe({"widget_id": "w"}, {})
    # applied=False → the court turns this into needs_root, never a green.
    assert res.applied is False and res.passed is False


def test_probe_fail_closed_on_live_probe_exception():
    def _boom(gs, ctx):
        raise RuntimeError("launch exploded")
    from personal_brain.court_harness import make_ui_renders_probe
    probe = make_ui_renders_probe(live_probe=_boom)
    res = probe({"widget_id": "w"}, {})
    # A crashing live probe REFUTES (applied=True, passed=False) — an unprovable
    # widget is not a working widget (fail-closed, mirrors node_cooks).
    assert res.applied is True and res.passed is False
