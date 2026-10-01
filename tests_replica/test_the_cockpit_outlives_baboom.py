"""The cockpit is not hostage to the companion, and a refusal says why.

On 2026-09-06 the founder's launch printed "BABOOM : not attached -- runtime
device proof challenge is invalid" and, because the relay start lived INSIDE
the BABOOM block, his whole cockpit went dark: every control on the web read
"waiting for the app push" and nothing said why. Two defects, one court.
"""
from __future__ import annotations

import inspect

import pytest
from pathlib import Path

import nodelang.application_server as application_server

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = (ROOT / "launch_archhub_test.py").read_text(encoding="utf-8")


def _start_actual_relay_block(monkeypatch):
    import ast
    import os
    from types import SimpleNamespace
    import threading
    from nodelang import cloud_relay
    from tests_replica.test_baboom_startup_lifecycle import launcher_names

    starts = []
    monkeypatch.setenv("APPDATA", "unused-court-appdata")

    def start(**kwargs):
        relay = SimpleNamespace(**kwargs)
        starts.append(relay)
        return relay

    monkeypatch.setattr(cloud_relay, "start_cloud_relay", start)
    # Every launcher callback the relay start wires (b026613 added the offer pair).
    ns = launcher_names(
        "_cockpit_respond", "_cockpit_execute", "_cockpit_offer", "_cockpit_offer_command",
        _baboom_stop=threading.Event(),
        baboom_host=None, Path=Path, os=os, state_dir=Path("unused"),
        server=SimpleNamespace(),
        _baboom_off_reason=None,
    )
    blocks = [node for node in ast.parse(LAUNCHER).body if isinstance(node, ast.Try)
              and any(isinstance(child, ast.ImportFrom) and child.module == "nodelang.cloud_relay"
                      and any(alias.name == "start_cloud_relay" for alias in child.names)
                      for child in ast.walk(node))]
    assert len(blocks) == 1, "one relay starts independently of attachment"
    exec(compile(ast.Module(body=blocks, type_ignores=[]), "launcher relay", "exec"), ns)
    assert len(starts) == 1
    return ns, starts[0]





def test_a_companion_that_cannot_attach_does_not_take_the_cockpit_with_it(monkeypatch):
    ns, relay = _start_actual_relay_block(monkeypatch)
    assert ns["cloud_relay"] is relay
    assert relay.respond is ns["_cockpit_respond"]
    assert relay.execute is ns["_cockpit_execute"]
    assert relay.offer is ns["_cockpit_offer"]
    assert relay.offer_command is ns["_cockpit_offer_command"]


def test_the_relay_without_a_companion_answers_but_refuses_to_act(monkeypatch):
    """Reads are safe unsigned; an act needs the companion's signed session."""
    import threading
    from types import SimpleNamespace

    import nodelang.universal_application as ua

    ns, relay = _start_actual_relay_block(monkeypatch)
    with pytest.raises(RuntimeError, match="no action was performed"):
        relay.execute("run task")
    calls = []
    ns["baboom_host"] = SimpleNamespace(execute_input=lambda text: calls.append(text) or {"signed": True})
    assert relay.execute("run task") == {"signed": True}
    assert calls == ["run task"]
    # Without a companion a read is answered unsigned, from the graph, under the lock.
    asked = []
    monkeypatch.setattr(ua, "respond_universal_baboom_utterance",
                        lambda store, registry, *, utterance, authentication_context:
                        asked.append((store, utterance, authentication_context)) or {"kind": "answer"})
    ns["baboom_host"] = None
    ns["server"] = SimpleNamespace(
        mutation_lock=threading.Lock(), universal_store="the-graph",
        universal_registry=SimpleNamespace(authorization=SimpleNamespace(
            session=SimpleNamespace(context=lambda: "unsigned-read"))))
    assert relay.respond("status") == {"kind": "answer"}
    assert asked == [("the-graph", "status", "unsigned-read")]
    # Turned off in Settings: the refusal says so, and nothing acts.
    ns["_baboom_off_reason"] = "BABOOM is turned off in Settings; no action was performed."
    with pytest.raises(RuntimeError, match="turned off in Settings"):
        relay.execute("run task")


def test_the_relay_start_is_not_nested_inside_the_baboom_success_path(monkeypatch):
    """It was, and that is exactly how one failure became two."""
    ns, relay = _start_actual_relay_block(monkeypatch)
    assert ns["baboom_host"] is None
    assert ns["cloud_relay"] is relay


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
    apart), keeps one identity, stops the host it could not hand over, and a
    late companion still projects. One source: the lifecycle helpers run the
    launcher's real _keep_attaching."""
    from tests_replica.test_baboom_startup_lifecycle import (
        Host,
        NoResponse,
        test_first_frame_retry_retains_one_prepared_host_and_identity,
        test_policy_refusal_is_not_retried_under_new_identity,
        worker_namespace,
    )
    test_first_frame_retry_retains_one_prepared_host_and_identity(monkeypatch)
    test_policy_refusal_is_not_retried_under_new_identity(monkeypatch)

    def busy(host):
        raise NoResponse("universal runtime did not respond")

    host = Host(busy)
    ns, stop, prepared, delivered, _ = worker_namespace(monkeypatch, host)
    ns["_keep_attaching"]()
    assert len(prepared) == 1 and host.connect_calls == 40
    assert stop.waits == [0.0] + [15.0] * 39, "each retry waits 15 s"
    assert not delivered and host.stop_calls >= 1, "an undelivered host is stopped"
    land = LAUNCHER[LAUNCHER.index("    def land(self, host):"):LAUNCHER.index("_baboom_attachment = _BaboomAttachment(app)")]
    assert "companion.start_projection()" in land, "a late companion still projects"
