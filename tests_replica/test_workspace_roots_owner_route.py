"""The owner's Workspaces route on the clean server: session-admitted, key-approved.

A throwaway clean runtime (with its Governance composition) and a court key standing
in for the Windows key store; the hooks' files go to a temporary folder.
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
import uuid
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import (
    decode_dss_signature,
    encode_dss_signature,
)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_clean_server_admission import (  # noqa: E402
    _issue_clean_session,
    _provision_clean_runtime,
    _start_clean_server,
)
from nodelang import workspace_roots_catalogue as roots  # noqa: E402
from nodelang import workspace_roots_signing as signing  # noqa: E402

ROUTE = "/api/universal/workspace-roots"
PRIVATE = ec.generate_private_key(ec.SECP256R1())


def _blob():
    numbers = PRIVATE.public_key().public_numbers()
    return (b"ECS1" + (32).to_bytes(4, "little")
            + numbers.x.to_bytes(32, "big") + numbers.y.to_bytes(32, "big"))


class _Owner:
    approve = True
    prompts = 0
    key_exists = False  # the desktop window's first approval creates the key


class _Signer:
    def __init__(self, key_name, *, protect=True, pinned_fingerprint=None, **_kwargs):
        assert key_name == roots.KEY_NAME and protect is True
        self.pinned = pinned_fingerprint

    def public_blob(self):
        """The window reads the key's public half (the owner never opens the key)."""
        return _blob() if _Owner.key_exists else None

    def sign(self, payload):
        _Owner.prompts += 1
        if not _Owner.approve:
            raise signing.SigningUnavailable("the owner declined (0x800704c7)")
        if payload == roots.KEY_CHECK:
            _Owner.key_exists = True
        if self.pinned is not None and self.pinned != hashlib.sha256(_blob()).hexdigest():
            raise signing.SigningUnavailable("the existing signing key is not the pinned key; refused")
        r, s = decode_dss_signature(PRIVATE.sign(payload, ec.ECDSA(hashes.SHA256())))
        return (r.to_bytes(32, "big") + s.to_bytes(32, "big")).hex()


class _Verifier:
    def __init__(self, key_name):
        assert key_name == roots.KEY_NAME

    def public_fingerprint(self):
        return hashlib.sha256(_blob()).hexdigest()

    def protected_public_blob(self):
        raise AssertionError("the graph's owner opened the key")

    def public_blob(self):
        raise AssertionError("the graph's owner opened the key")

    def verify_blob(self, blob, key_id, version, payload, signature):
        return blob == _blob() and self.verify(key_id, version, payload, signature)

    def verify(self, key_id, version, payload, signature):
        try:
            raw = bytes.fromhex(signature)
            if key_id != roots.KEY_ID or version != 1 or len(raw) != 64:
                return False
            PRIVATE.public_key().verify(
                encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big")),
                payload, ec.ECDSA(hashes.SHA256()))
            return True
        except (InvalidSignature, ValueError):
            return False


def _post(server, payload, *, token="roots-token", csrf="roots-csrf"):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["X-ArchHub-Session"] = token
    if csrf:
        headers["X-ArchHub-CSRF"] = csrf
    request = Request(server.url + ROUTE, data=json.dumps(payload).encode("utf-8"),
                      headers=headers, method="POST")
    try:
        with urlopen(request, timeout=60) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        return error.code, json.loads(error.read().decode("utf-8"))


@pytest.fixture()
def runtime(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "localappdata"))
    monkeypatch.setattr(roots, "default_snapshot_path", lambda: home / "workspace-roots.json")
    monkeypatch.setattr(roots, "default_pin_path", lambda: home / "workspace-roots.pin")
    monkeypatch.setattr(roots, "default_last_good_path", lambda: home / "workspace-roots.last-good.json",
                        raising=False)
    monkeypatch.setattr(signing, "CngSigner", _Signer)
    monkeypatch.setattr(signing, "CngVerifier", _Verifier)
    _Owner.approve, _Owner.prompts, _Owner.key_exists = True, 0, False
    built, provider = _provision_clean_runtime(tmp_path, root_name="workspace-roots-route")
    server = _start_clean_server(
        built, provider, scope_root=built.grand_map.root_id,
        private_root_grants_path=tmp_path / "private-root-grants.json")
    _issue_clean_session(built, token="roots-token", csrf="roots-csrf")
    deadline = time.monotonic() + 30
    while server.workspace_roots_boot == "checking" and time.monotonic() < deadline:
        time.sleep(0.05)
    try:
        yield server, built, home, tmp_path
    finally:
        server.close()


class _Refused(Exception):
    def __init__(self, status, answer):
        super().__init__(answer.get("error"))
        self.status, self.answer = status, answer


def _change(server, body, **auth):
    """A change exactly as the desktop makes it: the app route signs silently with
    its DPAPI app key and commits it."""
    def forward(payload):
        status, answer = _post(server, payload, **auth)
        if status != 200:
            raise _Refused(status, answer)
        return {key: value for key, value in answer.items() if key != "ok"}
    try:
        return 200, roots.approve_in_this_window(body, window_handle=0x10, forward=forward)
    except _Refused as refused:
        return refused.status, refused.answer
    except roots.WorkspaceRootRefused as exc:
        return 403, {"ok": False, "error": str(exc)}


def _register(server, folder, root_id="client-a", privacy="private"):
    return _change(server, {"action": "register", "id": root_id, "path": str(folder),
                            "privacy": privacy, "profile": "client", "writers": ["claude"]})


def test_the_boot_check_finds_nothing_registered_and_list_commits_nothing(runtime):
    server, built, home, _tmp = runtime
    assert server.workspace_roots_boot == "missing"
    before = built.location.authority.store.revision
    status, view = _post(server, {"action": "list"})
    assert status == 200 and view["roots"] == [] and view["boot"] == "missing"
    assert view["built_in"]["removable"] is False
    assert view["promise"] == roots.PROMISE
    assert built.location.authority.store.revision == before, "listing changed the graph"
    assert not home.exists()


@pytest.mark.parametrize("token,csrf", [(None, "roots-csrf"), ("roots-token", None),
                                        ("forged-token", "roots-csrf"), ("roots-token", "wrong")],
                         ids=["no-session", "no-csrf", "forged-session", "wrong-csrf"])
def test_no_browser_session_no_change(runtime, token, csrf):
    server, built, home, tmp_path = runtime
    folder = tmp_path / "client-a"
    folder.mkdir()
    before = built.location.authority.store.revision
    status, _body = _post(server, {"action": "register", "id": "client-a", "path": str(folder),
                                   "privacy": "private", "profile": "client",
                                   "writers": ["claude"]}, token=token, csrf=csrf)
    assert status == 403
    assert built.location.authority.store.revision == before
    assert _Owner.prompts == 0 and not home.exists()


def test_register_and_unregister_through_the_route_project_matching_files(runtime):
    server, built, home, tmp_path = runtime
    folder = tmp_path / "client-a"
    folder.mkdir()
    (folder / "drawing.dwg").write_bytes(b"client drawing")
    status, view = _register(server, folder)
    assert status == 200, view
    assert view["projection"] == "match" and view["boot"] == "match" and view["key_pinned"]
    assert [(r["root_id"], r["state"]) for r in view["roots"]] == [("client-a", "registered")]
    assert _Owner.prompts == 0
    document = json.loads((home / "workspace-roots.json").read_text(encoding="utf-8"))
    assert document["key_id"] == roots.APP_KEY_ID
    assert [entry["id"] for entry in document["roots"]] == ["client-a"]
    status, view = _change(server, {"action": "unregister", "id": "client-a"})
    assert status == 200 and view["projection"] == "match"
    assert [(r["root_id"], r["state"]) for r in view["roots"]] == [("client-a", "unregistered")]
    assert (folder / "drawing.dwg").read_bytes() == b"client drawing", "a file was touched"
    assert json.loads((home / "workspace-roots.json").read_text(encoding="utf-8"))["roots"] == []


def test_next_settings_write_migrates_legacy_cng_pin_without_opening_cng(runtime):
    server, _built, home, tmp_path = runtime
    catalogue = roots.find_workspace_root_catalogue(server.clean_authority, caller=server.clean_caller)
    if catalogue is None:
        catalogue = roots.install_workspace_root_catalogue(
            server.clean_authority, operation_id=str(uuid.uuid4()), caller=server.clean_caller)
    old_pin = hashlib.sha256(_blob()).hexdigest()
    roots.pin_signing_key(server.clean_authority, catalogue, old_pin,
                          caller=server.clean_caller, operation_id=str(uuid.uuid4()),
                          key_id=roots.KEY_ID)
    old_body = roots.snapshot_body([], old_pin, key_id=roots.KEY_ID)
    old_signature = _Signer(roots.KEY_NAME).sign(roots.canonical(old_body))
    _Owner.prompts = 0
    roots.write_projection(old_body, old_signature, _blob(),
                           snapshot_path=home / "workspace-roots.json",
                           pin_path=home / "workspace-roots.pin")

    folder = tmp_path / "client-a"
    folder.mkdir()
    status, view = _post(server, {"action": "register", "id": "client-a", "path": str(folder),
                                  "privacy": "private", "profile": "client",
                                  "writers": ["claude"]})
    assert status == 200, view
    assert _Owner.prompts == 0
    document = json.loads((home / "workspace-roots.json").read_text(encoding="utf-8"))
    pin = json.loads((home / "workspace-roots.pin").read_text(encoding="utf-8"))
    assert document["key_id"] == roots.APP_KEY_ID
    assert pin["key_id"] == roots.APP_KEY_ID
    assert document["key_fingerprint"] != old_pin


def test_settings_register_update_writers_and_unregister_need_no_owner_prompt(runtime):
    server, built, home, tmp_path = runtime
    folder = tmp_path / "BBC4"
    folder.mkdir()
    status, view = _post(server, {
        "action": "register",
        "id": "BBC4",
        "path": str(folder),
        "privacy": "private",
        "writers": list(roots.OPEN_AGENT_RUNTIMES),
    })
    assert status == 200, view
    assert _Owner.prompts == 0, "settings writes must not open the owner-protected key"
    assert [(r["root_id"], r["writers"]) for r in view["roots"]] == [
        ("bbc4", list(roots.OPEN_AGENT_RUNTIMES))]
    assert json.loads((home / "workspace-roots.json").read_text(encoding="utf-8"))["roots"][0]["id"] == "bbc4"

    status, view = _post(server, {
        "action": "update-writers",
        "id": "bbc4",
        "writers": ["codex"],
    })
    assert status == 200, view
    assert _Owner.prompts == 0
    assert [(r["root_id"], r["writers"]) for r in view["roots"] if r["state"] == "registered"] == [
        ("bbc4", ["codex"])]

    status, view = _post(server, {"action": "unregister", "id": "bbc4"})
    assert status == 200, view
    assert _Owner.prompts == 0
    assert [(r["root_id"], r["state"]) for r in view["roots"]] == [("bbc4", "unregistered")]


def test_legacy_owner_decline_flag_is_not_used_by_silent_app_write(runtime):
    server, built, home, tmp_path = runtime
    folder = tmp_path / "client-a"
    folder.mkdir()
    _Owner.approve = False
    status, body = _register(server, folder)
    assert status == 200, body
    assert _Owner.prompts == 0
    catalogue = roots.find_workspace_root_catalogue(built.location.authority, caller=built.caller)
    assert roots.read_state(built.location.authority, catalogue, caller=built.caller)[1]
    assert (home / "workspace-roots.json").exists() and (home / "workspace-roots.pin").exists()


def test_a_mismatched_registry_refuses_changes_until_republished(runtime):
    server, built, home, tmp_path = runtime
    for name in ("client-a", "client-b"):
        (tmp_path / name).mkdir()
    assert _register(server, tmp_path / "client-a")[0] == 200
    (home / "workspace-roots.json").unlink()
    server._check_workspace_roots()
    assert server.workspace_roots_boot == "mismatch"
    status, body = _register(server, tmp_path / "client-b", root_id="client-b")
    assert status == 403 and "republish" in body["error"]
    status, view = _post(server, {"action": "list"})
    assert status == 200 and view["boot"] == "mismatch" and view["projection"] == "mismatch"
    status, view = _change(server, {"action": "republish"})
    assert status == 200 and view["projection"] == "match" and view["boot"] == "match"
    assert _register(server, tmp_path / "client-b", root_id="client-b")[0] == 200


def test_legacy_cng_substitute_key_is_not_consulted_by_app_write(runtime, monkeypatch):
    server, built, home, tmp_path = runtime
    for name in ("client-a", "client-b"):
        (tmp_path / name).mkdir()
    assert _register(server, tmp_path / "client-a")[0] == 200
    global PRIVATE
    monkeypatch.setattr(sys.modules[__name__], "PRIVATE", ec.generate_private_key(ec.SECP256R1()))
    catalogue = roots.find_workspace_root_catalogue(built.location.authority, caller=built.caller)
    before = roots.read_state(built.location.authority, catalogue, caller=built.caller)
    status, body = _register(server, tmp_path / "client-b", root_id="client-b")
    assert status == 200, body
    assert _Owner.prompts == 0
    assert roots.read_state(built.location.authority, catalogue, caller=built.caller) != before


def test_direct_settings_change_is_app_written_and_never_prompts(runtime):
    """Settings writes are admitted by the browser session and signed by the local
    app key, not by the retired owner-protected prompt path."""
    server, built, home, tmp_path = runtime
    for name in ("client-a", "client-b"):
        (tmp_path / name).mkdir()
    status, body = _post(server, {"action": "register", "id": "client-a",
                                  "path": str(tmp_path / "client-a"), "privacy": "private",
                                  "profile": "client", "writers": ["claude"]})
    assert status == 200, body
    assert _Owner.prompts == 0 and home.exists()
    prompts = _Owner.prompts
    catalogue = roots.find_workspace_root_catalogue(built.location.authority, caller=built.caller)
    before = roots.read_state(built.location.authority, catalogue, caller=built.caller)
    for change in ({"action": "register", "id": "client-b", "path": str(tmp_path / "client-b"),
                    "privacy": "private", "profile": "client", "writers": ["claude"]},
                   {"action": "unregister", "id": "client-a"}, {"action": "republish"}):
        status, body = _post(server, change)
        assert status == 200, (change, body)
    assert _Owner.prompts == prompts
    assert roots.read_state(built.location.authority, catalogue, caller=built.caller) != before


def test_unsigned_private_root_grant_and_revoke_are_refused_before_store_mutation(runtime, monkeypatch):
    server, _built, _home, tmp_path = runtime
    folder = tmp_path / "client-a"
    folder.mkdir()
    assert _register(server, folder)[0] == 200
    document = json.loads((_home / "workspace-roots.json").read_text(encoding="utf-8"))
    signed = {key: value for key, value in document.items() if key != "signature"}
    monkeypatch.setattr(roots, "verified_graph_state",
                        lambda: {"registry_digest": roots.registry_digest(signed)})
    _container, digest, registration = roots.root_bound_registration(
        "workspace-roots/client-a/__grant__", runtime="claude")
    assert registration["privacy"] == "private"

    grant_body = {
        "action": "grant-private-root",
        "id": "client-a",
        "runtime": "claude",
        "session_id": "app:agent-session:unsigned",
        "operations": ["write_file"],
    }
    status, body = _post(server, grant_body)
    assert status == 403 and "authenticated workspace-roots settings admission" in body["error"]
    receipts = (tmp_path / "private-grant-events.log").read_text(encoding="utf-8").splitlines()
    receipt = json.loads(receipts[-1])
    assert (receipt["stage"], receipt["outcome"], receipt["id"]) == ("owner", "refused", "client-a")
    assert receipt["message"] == ("WorkspaceRootRefused: the authenticated workspace-roots "
                                  "settings admission is required; nothing was changed")
    assert server.private_root_grants.status(
        root_id="client-a",
        runtime="claude",
        session_id="app:agent-session:unsigned",
        operation="write_file",
        root_digest=digest,
    )["granted"] is False

    server.private_root_grants.grant(
        root_id="client-a",
        runtime="claude",
        session_id="app:agent-session:unsigned",
        root_digest=digest,
        operations=("write_file",),
    )
    status, body = _post(server, {**grant_body, "action": "revoke-private-root"})
    assert status == 403 and "authenticated workspace-roots settings admission" in body["error"]
    assert server.private_root_grants.status(
        root_id="client-a",
        runtime="claude",
        session_id="app:agent-session:unsigned",
        operation="write_file",
        root_digest=digest,
    )["granted"] is True
