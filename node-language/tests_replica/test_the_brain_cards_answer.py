"""The two brain cards answer instead of timing out.

Both cards on the founder's canvas posted a bare tools/call and read the
response to EOF with a 15 second timeout. A streamable HTTP server may hold
the stream open after it has answered, so every launch and every Run the
cards sat for the full 15 seconds and landed "timed out". These courts pin
the wire the cards speak and, above all, pin that a silent daemon produces a
short honest line inside the budget instead of a hang.
"""
from __future__ import annotations

import email.message
import io
import json
import socket
import time

import pytest

from nodelang import pipeline_engines


class _FakeResponse:
    """What urlopen hands back: an iterable body plus real MIME headers."""

    def __init__(self, body, headers=None, status=200, hold_open=False):
        self._stream = io.BytesIO(body.encode("utf-8"))
        self.headers = email.message.Message()
        for name, value in (headers or {}).items():
            self.headers[name] = value
        self.status = status
        self._hold_open = hold_open

    def __iter__(self):
        for line in self._stream:
            yield line
        if self._hold_open:
            # A server that keeps the stream open after answering: iterating
            # to EOF here would block, which is the defect under test.
            raise AssertionError("read past the first frame")

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self._stream.close()
        return False


def _sse(payload):
    return "event: message\ndata: %s\n\n" % json.dumps(payload)


def _tool_result(text):
    return {"jsonrpc": "2.0", "id": 2,
            "result": {"content": [{"type": "text", "text": text}],
                       "isError": False}}


def _initialize_result():
    return {"jsonrpc": "2.0", "id": 1,
            "result": {"protocolVersion": "2025-06-18",
                       "capabilities": {}, "serverInfo": {"name": "brain"}}}


class _Daemon:
    """A fake brain: records every request, answers what the test scripts."""

    def __init__(self, session="", stall=0.0, refuse="", hold_open=False,
                 payload=None):
        self.session = session
        self.stall = stall
        self.refuse = refuse
        self.hold_open = hold_open
        # brain.health is what the fact card asks for now: one small object
        # carrying the count, instead of all 54,076 fact rows.
        self.payload = ('{"ok": true, "facts": 0, "skills": 0}'
                        if payload is None else payload)
        self.seen = []

    def __call__(self, request, timeout=None):
        body = json.loads(request.data.decode("utf-8"))
        self.seen.append((body.get("method"), dict(request.headers), timeout))
        if self.stall:
            if self.stall >= (timeout or 0):
                raise socket.timeout("timed out")
            time.sleep(self.stall)
        method = body.get("method")
        if method == "initialize":
            headers = {"Content-Type": "text/event-stream"}
            if self.session:
                headers["mcp-session-id"] = self.session
            return _FakeResponse(_sse(_initialize_result()), headers)
        if method == "notifications/initialized":
            return _FakeResponse("", {}, status=202)
        if method == "tools/call":
            if self.refuse:
                return _FakeResponse(_sse({
                    "jsonrpc": "2.0", "id": 2,
                    "error": {"code": -32601, "message": self.refuse}}))
            return _FakeResponse(
                _sse(_tool_result(self.payload)),
                {"Content-Type": "text/event-stream"},
                hold_open=self.hold_open)
        raise AssertionError("unexpected method %r" % method)


@pytest.fixture
def daemon(monkeypatch):
    """Install a fake brain in place of the live one."""
    import urllib.request

    def install(**kwargs):
        fake = _Daemon(**kwargs)
        monkeypatch.setattr(urllib.request, "urlopen", fake)
        return fake

    return install


def test_the_handshake_happens_before_the_call(daemon):
    """A bare tools/call is what hung; initialize comes first now."""
    fake = daemon()
    pipeline_engines.brain_facts({}, {})
    assert [method for method, _headers, _t in fake.seen] == [
        "initialize", "notifications/initialized", "tools/call"]


def test_the_session_id_is_echoed_on_the_call(daemon):
    """A stateful server hands back a session id; later POSTs carry it."""
    fake = daemon(session="brain-7f3a")
    pipeline_engines.brain_facts({}, {})
    sent = [headers for method, headers, _t in fake.seen
            if method != "initialize"]
    assert sent, "nothing was sent after the handshake"
    for headers in sent:
        assert headers.get("Mcp-session-id") == "brain-7f3a"
    first = fake.seen[0][1]
    assert "Mcp-session-id" not in first, "initialize cannot carry a session"


def test_a_stateless_daemon_needs_no_session(daemon):
    """The founder's daemon issues no session id; the cards still answer."""
    fake = daemon(session="", payload='{"ok": true, "facts": 2, "skills": 5}')
    _outputs, display = pipeline_engines.brain_facts({}, {})
    assert display == "2 fact row(s) in the brain, 5 skill(s)"
    assert all("Mcp-session-id" not in headers
               for _m, headers, _t in fake.seen)


def test_every_request_declares_the_streamable_http_accept_pair(daemon):
    fake = daemon()
    pipeline_engines.brain_facts({}, {})
    for _method, headers, _t in fake.seen:
        assert headers["Accept"] == "application/json, text/event-stream"
        assert (headers["Mcp-protocol-version"]
                == pipeline_engines.BRAIN_PROTOCOL_VERSION)


def test_an_sse_answer_is_parsed(daemon):
    daemon(payload="one line\nsecond line")
    outputs, display = pipeline_engines.brain_recall({"prompt": "canvas"}, {})
    assert outputs["out"] == "one line\nsecond line"
    assert display == "2 context line(s) for 'canvas'"


def test_a_plain_json_answer_is_parsed(monkeypatch):
    """Some servers answer application/json; one frame reader takes both."""
    import urllib.request

    def answer(request, timeout=None):
        body = json.loads(request.data.decode("utf-8"))
        if body.get("method") == "initialize":
            return _FakeResponse(json.dumps(_initialize_result()))
        if body.get("method") == "notifications/initialized":
            return _FakeResponse("", status=202)
        return _FakeResponse(json.dumps(
            _tool_result('{"ok": true, "facts": 3, "skills": 1}')))

    monkeypatch.setattr(urllib.request, "urlopen", answer)
    _outputs, display = pipeline_engines.brain_facts({}, {})
    assert display == "3 fact row(s) in the brain, 1 skill(s)"


def test_the_stream_is_not_read_past_the_first_frame(daemon):
    """A server that holds the stream open must not hold the card open."""
    daemon(hold_open=True)
    _outputs, display = pipeline_engines.brain_facts({}, {})
    assert display == "0 fact row(s) in the brain, 0 skill(s)"


def test_a_silent_daemon_yields_an_honest_line_inside_the_budget(daemon):
    """The founder's live failure: the daemon is up but never answers."""
    daemon(stall=99.0)
    started = time.monotonic()
    outputs, display = pipeline_engines.brain_facts({}, {})
    spent = time.monotonic() - started
    assert spent < pipeline_engines.BRAIN_BUDGET_SECONDS + 1.0
    assert display.startswith("no fact count:")
    assert "busy" in display
    assert "timed out" not in display
    assert outputs["out"] == ""


def test_a_slow_daemon_answers_the_recall_card_too(daemon):
    daemon(stall=99.0)
    outputs, display = pipeline_engines.brain_recall({"prompt": "walls"}, {})
    assert display.startswith("no recall:")
    assert outputs["out"] == ""


def test_a_dead_daemon_names_the_port(monkeypatch):
    import urllib.error
    import urllib.request

    def refused(request, timeout=None):
        raise urllib.error.URLError(ConnectionRefusedError(61, "refused"))

    monkeypatch.setattr(urllib.request, "urlopen", refused)
    _outputs, display = pipeline_engines.brain_facts({}, {})
    assert display == ("no fact count: no brain daemon is listening on"
                       " 127.0.0.1:8473")


def test_a_refused_tool_is_named_not_swallowed(daemon):
    daemon(refuse="Method not found: brain.list_facts")
    _outputs, display = pipeline_engines.brain_facts({}, {})
    assert "brain.list_facts" in display
    assert "refused" in display


def test_the_handshake_can_never_eat_the_budget_the_question_needs(daemon):
    """Three round trips must not become three full timeouts.

    The courtesy handshake gets a small slice of its own. This daemon is
    stateless and needs no initialize at all, so a slow greeting must never
    leave nothing for the tools/call: the measured failure was a card that
    spent its entire budget saying hello and never asked its question.
    """
    fake = daemon()
    pipeline_engines.brain_facts({}, {})
    seen = [(method, budget) for method, _headers, budget in fake.seen]
    handshake = [budget for method, budget in seen if method != "tools/call"]
    question = [budget for method, budget in seen if method == "tools/call"]
    assert max(handshake) <= 3.5, (
        "the handshake takes a slice, never the budget: %r" % handshake)
    assert question and question[0] > max(handshake), (
        "the question needs more time than the greeting: %r vs %r"
        % (question, handshake))
    assert question[0] <= pipeline_engines.BRAIN_BUDGET_SECONDS


def test_an_empty_prompt_is_still_the_callers_mistake():
    """Not the brain's silence: this one stays a refusal the card shows red."""
    with pytest.raises(ValueError):
        pipeline_engines.brain_recall({}, {})


def _brain_is_reachable():
    probe = socket.socket()
    probe.settimeout(0.2)
    try:
        return probe.connect_ex(("127.0.0.1", 8473)) == 0
    finally:
        probe.close()


@pytest.mark.skipif(not _brain_is_reachable(),
                    reason="no brain daemon on 127.0.0.1:8473")
def test_the_live_daemon_gets_an_answer_out_of_the_card():
    """Against the real daemon: the count itself, not merely some words.

    The first version of this court asserted only that the card said
    SOMETHING and did not contain "timed out". A card answering "the daemon
    did not answer" satisfied that forever, so it certified nothing. It now
    requires the number the card exists to show.
    """
    started = time.monotonic()
    outputs, display = pipeline_engines.brain_facts({}, {})
    spent = time.monotonic() - started
    assert spent < pipeline_engines.BRAIN_BUDGET_SECONDS + 1.0, (
        "the card waited %.1fs" % spent)
    assert "did not answer" not in display and "unreachable" not in display, display
    facts = outputs.get("facts")
    assert isinstance(facts, int) and facts > 0, (
        "the card produced no fact count: %r / %r" % (outputs, display))
    assert str(facts) in display and "fact row" in display, display

    started = time.monotonic()
    recalled, said = pipeline_engines.brain_recall({"prompt": "ArchHub"}, {})
    assert time.monotonic() - started < pipeline_engines.BRAIN_BUDGET_SECONDS + 1.0
    assert "did not answer" not in said and "unreachable" not in said, said
    assert str(recalled.get("out") or "").strip(), "recall came back empty: %s" % said
