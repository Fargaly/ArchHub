from __future__ import annotations

import json
from pathlib import Path
import uuid

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from nodelang.clean_antigravity_hook import (
    CleanAntigravityHook,
    identity_from_hook,
    main,
)
from nodelang.clean_coordination_host import CoordinationIdentity


class _Signer:
    def __init__(self) -> None:
        self._private = Ed25519PrivateKey.from_private_bytes(bytes(range(1, 33)))

    @property
    def key_id(self) -> str:
        return "agent-session.test"

    def sign(self, payload: bytes) -> bytes:
        return self._private.sign(payload)

    def verify(self, payload: bytes, signature: bytes) -> None:
        self._private.public_key().verify(signature, payload)


class _Client:
    def __init__(self, identity: CoordinationIdentity, message: dict[str, object]):
        self.identity = identity
        self.message = message
        self.calls: list[tuple[str, dict[str, object]]] = []

    def call(self, method, parameters=None, *, timeout_seconds=35.0):
        payload = dict(parameters or {})
        self.calls.append((method, payload))
        if method == "register_session":
            return {
                "ok": True,
                "self": {"session_root": "agent:antigravity"},
                "revision": 31,
            }
        if method == "inbox":
            return {"ok": True, "messages": [dict(self.message)], "revision": 31}
        if method == "send_message":
            return {
                "ok": True,
                "message": {"root_id": "reply:1", **payload},
                "revision": 32,
            }
        if method == "mark_message_read":
            return {"ok": True, "message": dict(self.message), "revision": 33}
        raise AssertionError("unexpected method: " + method)


def _event(tmp_path: Path) -> tuple[dict[str, object], Path]:
    conversation = "05d2b2f5-42b9-4145-9ce2-bbaa926e35a1"
    transcript = tmp_path / "brain" / conversation / "transcript.jsonl"
    transcript.parent.mkdir(parents=True)
    transcript.write_text("", encoding="utf-8")
    return {
        "conversationId": conversation,
        "transcriptPath": str(transcript),
    }, transcript


def _message() -> dict[str, object]:
    return {
        "root_id": "coordination:message:one",
        "sender_root": "agent:codex",
        "recipient_root": "agent:antigravity",
        "category": "message",
        "body": "Review the exact accepted graph revision.",
        "state": "sent",
        "created_revision": 31,
        "reply_to_root": None,
    }


def test_hook_binds_exact_native_conversation_without_fallback(tmp_path):
    event, _ = _event(tmp_path)
    identity = identity_from_hook(event)
    assert identity == CoordinationIdentity(
        "antigravity",
        "ide-conversation:05d2b2f5-42b9-4145-9ce2-bbaa926e35a1",
        "provider-selected",
    )

    invalid = dict(event)
    invalid.pop("conversationId")
    try:
        identity_from_hook(invalid)
    except ValueError as exc:
        assert "required" in str(exc)
    else:
        raise AssertionError("missing provider identity was accepted")


def test_native_round_trip_is_signed_graph_backed_and_replay_stable(tmp_path):
    event, transcript = _event(tmp_path)
    identity = identity_from_hook(event)
    client = _Client(identity, _message())
    bridge = CleanAntigravityHook(client, _Signer())

    projected = bridge.pre_invocation(event)
    assert [name for name, _ in client.calls] == ["register_session", "inbox"]
    inbound = projected["injectSteps"][0]["userMessage"]
    assert "UNTRUSTED PEER MESSAGE" in inbound
    assert _message()["body"] in inbound

    transcript.write_text(
        json.dumps({
            "type": "USER_INPUT",
            "source": "SYSTEM",
            "status": "DONE",
            "content": inbound,
        })
        + "\n"
        + json.dumps({
            "type": "MODEL_RESPONSE",
            "source": "MODEL",
            "status": "DONE",
            "step_index": 9,
            "content": "The graph revision is accepted.",
        })
        + "\n",
        encoding="utf-8",
    )

    client.calls.clear()
    bridge.post_invocation(event)
    first = list(client.calls)
    assert [name for name, _ in first] == [
        "register_session",
        "send_message",
        "mark_message_read",
    ]
    assert first[1][1]["target"] == "agent:codex"
    assert first[1][1]["reply_to"] == "coordination:message:one"
    assert first[1][1]["message"] == "The graph revision is accepted."
    uuid.UUID(first[1][1]["idempotency_key"])
    uuid.UUID(first[2][1]["idempotency_key"])

    client.calls.clear()
    bridge.post_invocation(event)
    replay = list(client.calls)
    assert replay[1][1]["idempotency_key"] == first[1][1]["idempotency_key"]
    assert replay[2][1]["idempotency_key"] == first[2][1]["idempotency_key"]


def test_tampered_inbound_envelope_cannot_route_a_reply(tmp_path):
    event, transcript = _event(tmp_path)
    identity = identity_from_hook(event)
    client = _Client(identity, _message())
    bridge = CleanAntigravityHook(client, _Signer())
    inbound = bridge.pre_invocation(event)["injectSteps"][0]["userMessage"]
    inbound = inbound.replace("agent:codex", "agent:other", 1)
    transcript.write_text(
        json.dumps({
            "type": "USER_INPUT",
            "source": "SYSTEM",
            "status": "DONE",
            "content": inbound,
        })
        + "\n"
        + json.dumps({
            "type": "MODEL_RESPONSE",
            "source": "MODEL",
            "status": "DONE",
            "content": "Do not route this.",
        })
        + "\n",
        encoding="utf-8",
    )
    client.calls.clear()
    bridge.post_invocation(event)
    assert [name for name, _ in client.calls] == ["register_session"]


def test_hook_source_has_no_coordination_side_ledger_or_hidden_sender():
    source = (
        Path(__file__).parents[1] / "nodelang" / "clean_antigravity_hook.py"
    ).read_text(encoding="utf-8")
    for forbidden in (
        "sqlite3",
        "jsonl.open",
        "message_queue",
        "external_session_id",
        "agent_coordination_server",
        "UniversalRuntimeSessionManager",
    ):
        assert forbidden not in source


def test_invalid_or_unbound_hook_identity_fails_closed(monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO("{}"))
    assert main(["pre"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "clean Antigravity coordination denied: ValueError\n"
