"""BABOOM performs; it does not narrate.

2026-09-04 the founder: "what is BABOOM for, standing there doing nothing, just
a reporter?". A 68-agent audit of the seams found why: the confirm control that
reaches the execute route was gated on intent == "assign-task", and the host and
transport validators rejected every other act's result shape. Running an engine,
telling an agent, interrupting one and installing an update all reached that gate
and were dropped. These courts hold each seam open."""
from __future__ import annotations

import inspect
from pathlib import Path

import nodelang.universal_application as ua

ROOT = Path(__file__).resolve().parents[1]


def test_every_act_intent_is_declared_once():
    assert ua._BABOOM_ACT_INTENTS == {
        "assign-task", "run-engine", "agent-message", "agent-interrupt",
        "restart-to-update", "open-host",
    }
    catalogued = {intent for intent, _aliases in ua._BABOOM_COMMAND_SPECS}
    assert ua._BABOOM_ACT_INTENTS - {"assign-task"} <= catalogued


def test_the_responder_asks_before_every_act_it_can_perform():
    src = inspect.getsource(ua.respond_universal_baboom_utterance)
    # run-engine used to fall through to "not-in-this-build": the right-click
    # "Graph: run on the canvas" entries said the build could not do it.
    assert 'intent == "run-engine"' in src and '"engine-ready"' in src
    assert src.count('"requires": "explicit execute"') >= 2
    assert '"engine-unknown"' in src


def test_the_companion_offers_a_control_for_any_act_not_only_a_task():
    src = inspect.getsource(Path(ROOT, "nodelang", "baboom_native_companion.py").read_text)  # noqa: F841
    text = (ROOT / "nodelang" / "baboom_native_companion.py").read_text(encoding="utf-8")
    apply_start = text.index("def _apply_response")
    apply_src = text[apply_start:text.index("def _execute_task", apply_start)]
    assert 'data.get("requires") == "explicit execute"' in apply_src
    assert 'command.get("intent") == "assign-task"' not in apply_src, (
        "the confirm control must not be gated on one intent again")
    for intent in ("run-engine", "agent-message", "agent-interrupt", "restart-to-update"):
        assert intent in text, intent
    prompts = {}
    exec(compile(text[text.index("_BABOOM_ACT_PROMPTS"):text.index("_BABOOM_ACT_GLYPHS")], "<prompts>", "exec"), prompts)
    assert set(prompts["_BABOOM_ACT_PROMPTS"]) == set(ua._BABOOM_ACT_INTENTS)


def test_the_host_and_transport_admit_an_act_result():
    host = (ROOT / "nodelang" / "baboom_native_host.py").read_text(encoding="utf-8")
    execute = host[host.index("def execute_input"):host.index("def _run(")]
    assert 'result.get("intent") == "assign-task"' in execute      # the Work shape still exact
    assert '"BABOOM native act execution is invalid"' in execute   # and every other act admitted
    transport = (ROOT / "nodelang" / "application_machine_transport.py").read_text(encoding="utf-8")
    tx = transport[transport.index("def execute_baboom_command"):]
    tx = tx[:tx.index("\n    def ", 10)] if "\n    def " in tx[10:] else tx
    assert 'if result.get("intent") == "assign-task":' in tx
    assert 'type(result.get("kind")) is not str' in tx


def test_the_executor_performs_each_act_on_the_real_seam():
    src = inspect.getsource(ua.execute_universal_baboom_utterance)
    assert "baboom_agent_link.send_message" in src and "baboom_agent_link.interrupt_agent" in src
    assert "create_engine_node" in src and "run_universal_pipeline" in src


def test_restart_to_update_reads_the_response_not_the_envelope():
    server = (ROOT / "nodelang" / "application_server.py").read_text(encoding="utf-8")
    assert '_answer = result.get("response") if isinstance(result.get("response"), dict) else result' in server
    assert '_answer.get("kind") == "update-ready"' in server
    # the old check read result["kind"], which is never present: respond returns
    # {"command": ..., "response": ...} -- the restart branch could not fire.
    assert 'if result.get("kind") == "update-ready"' not in server
