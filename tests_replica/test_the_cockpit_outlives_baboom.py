"""The cockpit is not hostage to the companion, and a refusal says why.

On 2026-09-06 the founder's launch printed "BABOOM : not attached -- runtime
device proof challenge is invalid" and, because the relay start lived INSIDE
the BABOOM block, his whole cockpit went dark: every control on the web read
"waiting for the app push" and nothing said why. Two defects, one court.
"""
from __future__ import annotations

import inspect

import pytest
import re
from pathlib import Path

import nodelang.application_server as application_server

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = (ROOT / "launch_archhub_test.py").read_text(encoding="utf-8")


def _relay_start_chain():
    """The statements enclosing the launcher's one relay start (326b657: the relay
    is started once, at top level, and resolves BABOOM per request)."""
    import ast

    from tests_replica.launcher_functions import ancestors

    def is_start(node):
        return (isinstance(node, ast.Assign) and isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Name) and node.value.func.id == "_start_relay")

    chain = ancestors(is_start)
    assert chain, "the launcher must start the cloud relay"
    return chain


def _cockpit(monkeypatch, **overrides):
    import threading
    from types import SimpleNamespace

    import nodelang.universal_application as ua
    from tests_replica.launcher_functions import Stop, load

    asked = []

    def responder(store, registry, *, utterance, authentication_context):
        asked.append((store, utterance, authentication_context))
        return {"kind": "answer", "summary": "read only"}

    monkeypatch.setattr(ua, "respond_universal_baboom_utterance", responder)
    registry = SimpleNamespace(authorization=SimpleNamespace(
        session=SimpleNamespace(context=lambda: "unsigned-read")))
    server = SimpleNamespace(mutation_lock=threading.Lock(), universal_store="the-graph",
                             universal_registry=registry)
    namespace = dict(_baboom_stop=Stop(), baboom_host=None, _baboom_off_reason=None, server=server)
    namespace.update(overrides)
    return load("_cockpit_respond", "_cockpit_execute", **namespace), asked


def test_a_companion_that_cannot_attach_does_not_take_the_cockpit_with_it():
    import ast

    chain = _relay_start_chain()
    assert [type(node) for node in chain] == [ast.Module, ast.Try], (
        "the relay must start at top level, not behind the companion")
    handler = chain[-1].handlers[0]
    assert "relay unavailable" in ast.unparse(handler), "a relay failure is named, not raised"
    assert "relay on (actions wait for signed BABOOM attachment)" in LAUNCHER
    assert "respond=_cockpit_respond" in ast.unparse(chain[-1])
    assert "execute=_cockpit_execute" in ast.unparse(chain[-1])


def test_the_relay_without_a_companion_answers_but_refuses_to_act(monkeypatch):
    """Reads are safe unsigned; an act needs the companion's signed session."""
    ns, asked = _cockpit(monkeypatch)
    assert ns["_cockpit_respond"]("status") == {"kind": "answer", "summary": "read only"}
    assert asked == [("the-graph", "status", "unsigned-read")]
    with pytest.raises(RuntimeError, match="no action was performed"):
        ns["_cockpit_execute"]("run the publish node")
    ns, _ = _cockpit(monkeypatch, _baboom_off_reason="BABOOM is turned off in Settings; no action was performed.")
    with pytest.raises(RuntimeError, match="turned off in Settings"):
        ns["_cockpit_execute"]("run the publish node")


def test_the_relay_start_is_not_nested_inside_the_baboom_success_path():
    """It was, and that is exactly how one failure became two."""
    import ast

    chain = _relay_start_chain()
    assert not any(isinstance(node, (ast.FunctionDef, ast.ClassDef, ast.If)) for node in chain)
    assert LAUNCHER.count("_start_relay(") == 1, "one relay, started once"
    for body in ("def _keep_attaching()", "class _BaboomAttachment("):
        block = LAUNCHER[LAUNCHER.index(body):]
        block = block[:block.index("\ndef ", 1) if "\ndef " in block[1:] else len(block)]
        assert "start_cloud_relay" not in block and "_start_relay(" not in block, body


def test_the_device_proof_refusal_names_which_cause_fired():
    """One message covered six causes, so nothing could be diagnosed."""
    source = inspect.getsource(
        application_server.ApplicationServer._verify_universal_runtime_device_credential)
    for cause in ("no challenge with that id is held",
                  "that challenge was already spent",
                  "it expired",
                  "another Agent Body entry",
                  "not %r",
                  "another runtime instance"):
        assert cause in source, cause
    assert 'raise AuthorizationDenied("runtime device proof challenge is invalid")' not in source


def test_the_same_observation_from_a_new_session_is_not_a_reused_identity():
    """BABOOM could not attach at all on a second launch.

    launcher.log 2026-09-06: 'BABOOM : not attached -- BABOOM Steward signal
    identity was reused'. The idempotency key covers the observation (kind,
    source, summary and the state behind it); every launch binds a FRESH agent
    session, so comparing the recorded provenance against the current session
    made an identical observation illegal the second time it was seen.
    """
    import inspect

    import nodelang.universal_application as ua

    source = inspect.getsource(ua.record_universal_baboom_steward_signal)
    body = source[source.index("existing = snapshot.cells.get(signal_root)"):]
    checks = body[:body.index('raise InvalidCell("BABOOM Steward signal identity was reused")')]
    assert "signal.provenance_root != session.root_id" not in checks, (
        "who noticed an observation is not part of its identity")
    # everything the fingerprint DOES cover stays strict
    for guard in ("signal.observer_root != entry.body_root",
                  "signal.trust_root != entry.policy_root",
                  "signal.idempotency_key != fingerprint",
                  "signal.lifecycle_root != registry.attention_protocol.state"):
        assert guard in checks, guard
    assert '"kind": "baboom-steward-observation/v1"' in checks


def test_a_stale_quit_marker_never_closes_a_fresh_build():
    """A marker written for the copy that is already gone made a freshly
    installed build quit itself the moment it finished booting."""
    launcher = (ROOT / "launch_archhub_test.py").read_text(encoding="utf-8")
    watcher = launcher[launcher.index("def _watch_quit_request()"):]
    watcher = watcher[:watcher.index("    timer.start()")]
    clear = watcher.index("marker.unlink()")
    look = watcher.index("def _look()")
    assert clear < look, "the stale marker must be cleared BEFORE the watch starts"


def test_a_show_marker_brings_the_window_up_on_the_qt_thread():
    """An updater or a verification run can open ArchHub the way the tray
    click does: a show-request file in the state directory, handled by the
    same watcher as quit-request, on the Qt thread. Showing the window from
    outside (ShowWindow on the HWND) leaves Qt believing the widget is hidden
    and paints nothing (2026-09-06). A stale show marker is cleared before
    the watch starts, like the quit marker."""
    launcher = (ROOT / "launch_archhub_test.py").read_text(encoding="utf-8")
    watcher = launcher[launcher.index("def _watch_quit_request()"):]
    watcher = watcher[:watcher.index("    timer.start()")]
    assert 'shower = state_dir / "show-request"' in watcher
    look = watcher.index("def _look()")
    assert watcher.index("shower.unlink()") < look, "stale show marker cleared first"
    inside = watcher[look:]
    assert "shower.is_file()" in inside and "_tray_open()" in inside
    assert inside.index("_tray_open()") < inside.index("_tray_quit()"), "show is read before quit"


def test_the_tray_open_settles_after_qt_and_writes_a_receipt():
    """The foreground dance runs after Qt has applied the shown state, not
    the same instant as showNormal(); it restores once more if something
    minimized the window meanwhile and prints where the window ended up,
    so the launcher log answers "did it open" instead of a guess
    (2026-09-06: a screen-capture tool that minimizes every window it is
    not allowed to see made the window look minimized by us)."""
    launcher = (ROOT / "launch_archhub_test.py").read_text(encoding="utf-8")
    body = launcher[launcher.index("def _tray_open()"):]
    body = body[:body.index("def _tray_check_updates()")]
    assert "window.showNormal()" in body
    assert "_QT.singleShot(" in body, "the dance is deferred past the show"
    assert body.index("def _settle()") < body.index("_QT.singleShot("), "deferred, not skipped"
    assert "_force_foreground(window.winId())" in body[body.index("def _settle()"):]
    assert "if user32.IsIconic(handle):" in body and "ShowWindow(handle, 9)" in body
    assert 'print("  show       : window %dx%d at %d,%d iconic=%s"' in body


def test_a_confirmed_act_runs_its_one_node_under_the_founders_binding():
    """The run-engine branch ran EVERY engine node on the canvas after each
    confirm (a once-confirmed publish_pdf exported the sheets again on every
    later confirm of anything), without the founder's binding, and summed
    up with a node count instead of the engine's answer (audit 2026-09-06)."""
    ua = (ROOT / "nodelang" / "universal_application.py").read_text(encoding="utf-8")
    branch = ua[ua.index('if command["intent"] == "run-engine":'):]
    branch = branch[:branch.index('if command["intent"] not in {"assign-task"')]
    assert "only_roots=[root]" in branch and "authentication_context=authentication_context, only_roots" in branch
    assert 'said = str(display.get(root) or pending.get(root) or "").strip()' in branch
    assert "node(s) ran" not in branch, "the receipt is the engine's words, not a canvas count"
    pipeline = (ROOT / "nodelang" / "universal_pipeline.py").read_text(encoding="utf-8")
    assert "only_roots: object = None" in pipeline
    assert "node_ids &= {str(root) for root in only_roots}" in pipeline


def test_a_busy_boot_does_not_cost_the_founder_his_companion(monkeypatch):
    """Six tries over fifteen seconds was the whole budget: on 2026-09-07 the
    app was busy for all of it and the founder had no companion for the
    session. The launcher keeps asking in the background (40 tries, 15 s
    apart) and hands the host to the Qt thread. Runs the real _keep_attaching."""
    from nodelang.application_machine_transport import MachineTransportError
    from tests_replica.launcher_functions import run_attach

    busy = [MachineTransportError("machine request timed out")] * 5 + [TimeoutError("busy"), None]
    prepared, attachment, hosts, stop = run_attach(monkeypatch, busy)
    assert len(prepared) == 1 and attachment.landed == hosts and hosts[0].connects == 7
    assert stop.waits == [0.0] + [15.0] * 6, "the first try is immediate, each retry waits 15 s"
    prepared, attachment, hosts, stop = run_attach(monkeypatch, [TimeoutError("busy")] * 40)
    assert attachment.landed == [] and hosts[0].connects == 40 and hosts[0].stopped
    assert stop.waits == [0.0] + [15.0] * 39
    prepared, attachment, hosts, stop = run_attach(monkeypatch, [ValueError("device proof refused")])
    assert attachment.landed == [] and hosts[0].connects == 1 and hosts[0].stopped
    launcher = (ROOT / "launch_archhub_test.py").read_text(encoding="utf-8")
    starter = launcher[launcher.index("def _start_baboom_attachment()"):]
    starter = starter[:starter.index("_BaboomTimer.singleShot(0, _start_baboom_attachment)")]
    assert "target=_keep_attaching" in starter and "daemon=True" in starter
    land = launcher[launcher.index("    def land(self, host):"):launcher.index("_baboom_attachment = _BaboomAttachment(app)")]
    assert "companion.start_projection()" in land, "a late companion still projects"
