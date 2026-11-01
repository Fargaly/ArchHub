"""One Approve card for an Ask-first hold, through the real Workshop API.

The card is the ask-approvals file beside permissions.json. Approve releases
the held connector once. Deny refuses it. A new server on the same directory
still lists the pending card.
"""
from types import SimpleNamespace

import pytest


@pytest.fixture
def desk(tmp_path, monkeypatch):
    root = tmp_path / "desk"
    for name in ("USERPROFILE", "HOME", "LOCALAPPDATA", "APPDATA", "TEMP", "TMP"):
        path = root / name
        path.mkdir(parents=True)
        monkeypatch.setenv(name, str(path))
    state = root / "LOCALAPPDATA" / "ArchHub"
    from nodelang.host_exec import LISTERS, INVOKERS, _LABELS, connector_call, register_connector
    from nodelang.nograph_server import NoGraphServer, r_settings_action, r_workshop

    calls = []

    def invoke(action, arguments):
        calls.append((action, dict(arguments)))
        return {"ok": True}

    register_connector(
        "askcard-mail",
        "Mail",
        lambda: [{"name": "post_message", "title": "Post"}],
        invoke,
    )
    servers = []

    def open_server():
        opened = NoGraphServer(state)
        servers.append(opened)
        return opened

    box = SimpleNamespace(
        state=state,
        calls=calls,
        server=open_server(),
        connector_call=connector_call,
        r_settings_action=r_settings_action,
        r_workshop=r_workshop,
        open_server=open_server,
    )
    try:
        yield box
    finally:
        LISTERS.pop("askcard-mail", None)
        INVOKERS.pop("askcard-mail", None)
        _LABELS.pop("askcard-mail", None)
        for server in servers:
            server.httpd.server_close()


def _settings(desk, function, *args):
    req = SimpleNamespace(method="POST", body={"function": function, "args": list(args)})
    return desk.r_settings_action(desk.server, req)["result"]


def _workshop(desk, function, *args):
    req = SimpleNamespace(
        method="POST",
        body={"action": "data-api", "function": function, "args": list(args), "request_id": "ask-card"},
    )
    return desk.r_workshop(desk.server, req)["result"]


def _ask_first(desk):
    saved = _settings(desk, "setPermissions", {"runMode": "Ask first", "tools": {}})
    assert saved["runMode"] == "Ask first"


def _send(desk, text):
    return desk.connector_call({
        "connector": "askcard-mail",
        "action": "post_message",
        "args": {"text": text},
    })


def _pending(desk):
    listed = _workshop(desk, "listApprovals")
    return [card for card in listed if card.get("approvalKind") == "ask" and card.get("status") == "pending"]


def _answer(desk, card, decision):
    return _workshop(desk, "answerApproval", "ask", card["id"], card["input_digest"], decision)


def test_held_connector_send_is_one_card(desk):
    _ask_first(desk)
    produced, display = _send(desk, "Door schedule is ready.")
    assert display == "Waiting for you"
    assert produced["result"] is None
    assert desk.calls == []
    card = _pending(desk)
    assert len(card) == 1
    assert card[0]["who"] == "Mail"
    assert card[0]["text"] == "Door schedule is ready."
    assert card[0]["textLabel"] == "Text to send"
    assert (desk.state / "settings" / "ask-approvals.json").is_file()

    _send(desk, "Door schedule is ready.")
    still = _pending(desk)
    assert [row["id"] for row in still] == [card[0]["id"]]

    desk.server.httpd.server_close()
    desk.server = desk.open_server()
    kept = _pending(desk)
    assert [row["id"] for row in kept] == [card[0]["id"]]
    assert kept[0]["text"] == "Door schedule is ready."

    approved = _answer(desk, kept[0], "approve")
    assert approved["status"] == "approved"
    assert desk.calls == [("post_message", {"text": "Door schedule is ready."})]
    again = _answer(desk, kept[0], "approve")
    assert again["status"] == "approved"
    assert len(desk.calls) == 1

    produced, display = _send(desk, "Do not send this.")
    assert display == "Waiting for you"
    held = _pending(desk)
    assert len(held) == 1
    assert held[0]["text"] == "Do not send this."
    refused = _answer(desk, held[0], "deny")
    assert refused["status"] == "declined"
    assert desk.calls == [("post_message", {"text": "Door schedule is ready."})]
    assert _pending(desk) == []


def test_remote_hold_and_batch_holds(desk, monkeypatch):
    _ask_first(desk)
    released = []

    def run_remote_effect(tool, arguments):
        released.append((tool, dict(arguments)))
        return {"ok": True}

    monkeypatch.setattr("nodelang.cloud_relay.run_remote_effect", run_remote_effect)
    from nodelang.cloud_relay import remote_gate

    decision = remote_gate("connector.call", {
        "name": "askcard-mail",
        "text": "remote post",
        "params": {"text": "remote post"},
    })
    assert decision["verdict"] == "ask"
    remote = [card for card in _pending(desk) if card.get("who") == "Remote agent"]
    assert len(remote) == 1
    assert remote[0]["text"] == "remote post"
    assert _answer(desk, remote[0], "approve")["status"] == "approved"
    assert released == [("connector.call", {
        "name": "askcard-mail",
        "text": "remote post",
        "params": {"text": "remote post"},
    })]
    assert _answer(desk, remote[0], "approve")["status"] == "approved"
    assert len(released) == 1

    _send(desk, "First item stays.")
    _send(desk, "Second item stays.")
    assert sorted(card["text"] for card in _pending(desk)) == ["First item stays.", "Second item stays."]
