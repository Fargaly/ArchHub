"""A request the sender closed, reassigned, or cannot reach stops being chased.

Cases are the live ones (2026-09-29): 50011a84 to the OpenCode control bridge, closed by
0609e22a; 717's e2f9b3e8 to "Codex Archhub work takeover", closed by f9abb898. The block
text no longer promises "once per item": it repeats on a cadence and says how to close.
"""
import json

from tests_replica.test_native_stop_followup import ASK, _at, _prompt, _stop

BRIDGE = "opencode-session-link-74588"
TAKEOVER = "Codex Archhub work takeover"


def _send(seconds, to, message, msg_id, *, success=True, note=None):
    tool_id = "toolu_%d" % seconds
    result = {"success": success}
    if msg_id:
        result["msg_id"] = msg_id
    if note:
        result["message"] = note
    return [
        {"type": "assistant", "timestamp": _at(seconds), "message": {"content": [
            {"type": "tool_use", "id": tool_id, "name": "SendMessage", "input": {"to": to, "message": message}}]}},
        {"type": "user", "timestamp": _at(seconds + 1), "message": {"content": [
            {"type": "tool_result", "tool_use_id": tool_id, "content": json.dumps(result)}]}},
    ]


TAIL = [_prompt(900, "task-notification")]
ASK_ID = "50011a84-9d3b-4f76-b490-9cf955ac1d7f"


def test_a_request_closed_by_its_msg_id_is_not_chased_the_control_bridge_case(tmp_path):
    entries = (_send(0, BRIDGE, ASK, ASK_ID)
               + _send(300, BRIDGE, "FOLLOW-UP #1 (closing) re " + ASK_ID + ", from verifier f1edab9a: CLOSED. "
                       "Please do NOT make the call it asked for. No reply needed.",
                       "0609e22a-5341-4bc7-9b1e-c759416bc29e") + TAIL)
    assert _stop(tmp_path, entries, 1000) is None


def test_a_request_closed_with_no_reply_needed_is_not_chased_the_takeover_case(tmp_path):
    ask_id = "e2f9b3e8-0000-4000-8000-000000000001"
    entries = (_send(0, TAKEOVER, ASK, ask_id)
               + _send(300, TAKEOVER, "FOLLOW-UP #2 (closing) re " + ask_id + ": the work moved elsewhere. "
                       "No reply needed.", "f9abb898-0000-4000-8000-000000000002") + TAIL)
    assert _stop(tmp_path, entries, 1000) is None


def test_a_reassignment_notice_closes_the_request(tmp_path):
    entries = (_send(0, TAKEOVER, ASK, "e1") + _send(300, TAKEOVER, "This task is reassigned to another verifier.", "e2")
               + TAIL)
    assert _stop(tmp_path, entries, 1000) is None


def test_an_unreachable_peer_closes_the_request_as_unreachable(tmp_path):
    entries = (_send(0, BRIDGE, ASK, ASK_ID)
               + _send(300, BRIDGE, "FOLLOW-UP #1 re " + ASK_ID + ": still need the result?", None, success=False,
                       note="No agent named " + BRIDGE + " is reachable.") + TAIL)
    assert _stop(tmp_path, entries, 1000) is None


def test_closing_another_msg_id_does_not_close_this_one(tmp_path):
    entries = _send(0, BRIDGE, ASK, ASK_ID) + _send(300, BRIDGE, "re some-other-id: CLOSED.", "x") + TAIL
    assert _stop(tmp_path, entries, 1000)["decision"] == "block"


def test_a_close_sent_to_another_peer_does_not_close_it(tmp_path):
    entries = _send(0, BRIDGE, ASK, ASK_ID) + _send(300, TAKEOVER, "re " + ASK_ID + ": CLOSED.", "x") + TAIL
    assert _stop(tmp_path, entries, 1000)["decision"] == "block"


def test_a_close_sent_before_the_request_does_not_close_it(tmp_path):
    entries = _send(0, BRIDGE, "re " + ASK_ID + ": CLOSED.", "x") + _send(300, BRIDGE, ASK, ASK_ID) + TAIL
    assert _stop(tmp_path, entries, 1000)["decision"] == "block"


def test_a_reassignment_question_is_a_new_request_not_a_close(tmp_path):
    entries = (_send(0, TAKEOVER, ASK, "e1") + _send(300, TAKEOVER, "Should this be reassigned?", "e2") + TAIL)
    assert _stop(tmp_path, entries, 1000)["decision"] == "block"


def test_the_block_text_states_its_cadence_and_how_to_close(tmp_path):
    reason = _stop(tmp_path, _send(0, BRIDGE, ASK, ASK_ID) + TAIL, 1000)["reason"]
    assert "once per item" not in reason
    assert "repeats every 10 minutes" in reason and "CLOSED" in reason
