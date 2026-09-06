"""The cockpit is not hostage to the companion, and a refusal says why.

On 2026-09-06 the founder's launch printed "BABOOM : not attached -- runtime
device proof challenge is invalid" and, because the relay start lived INSIDE
the BABOOM block, his whole cockpit went dark: every control on the web read
"waiting for the app push" and nothing said why. Two defects, one court.
"""
from __future__ import annotations

import inspect
import re
from pathlib import Path

import nodelang.application_server as application_server

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = (ROOT / "launch_archhub_test.py").read_text(encoding="utf-8")


def _baboom_failure_block() -> str:
    start = LAUNCHER.index('except Exception as refusal:\n    print("  BABOOM     : not attached')
    return LAUNCHER[start:start + 3000]


def test_a_companion_that_cannot_attach_does_not_take_the_cockpit_with_it():
    block = _baboom_failure_block()
    assert "start_cloud_relay" in block, (
        "the relay must start even when BABOOM does not attach")
    assert "relay on, answers only" in block


def test_the_relay_without_a_companion_answers_but_refuses_to_act():
    """Reads are safe unsigned; an act needs the companion's signed session."""
    block = _baboom_failure_block()
    assert "respond_universal_baboom_utterance" in block
    assert "companion-absent" in block
    # The execute side must NOT be wired to anything that mutates.
    execute = re.search(r"execute=([A-Za-z_]+)", block)
    assert execute and execute.group(1) == "_refuse_without_baboom", block[:400]


def test_the_relay_start_is_not_nested_inside_the_baboom_success_path():
    """It was, and that is exactly how one failure became two."""
    attach = LAUNCHER.index("BABOOM: the ambient companion")
    failure = LAUNCHER.index('except Exception as refusal:\n    print("  BABOOM     : not attached')
    inside = LAUNCHER[attach:failure]
    assert inside.count("start_cloud_relay") == 1, (
        "the happy path keeps its own relay start; the fallback has the other")
    assert LAUNCHER.count("start_cloud_relay") >= 2


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
