from __future__ import annotations

import hashlib
import json
import time
import uuid
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from nodelang.application_server import ApplicationServer
from nodelang.cell_protocols import read_relation
from nodelang.cell_secret_keys import MemorySigningKeyProvider
from nodelang.clean_browser_authority import (
    issue_clean_browser_session,
    revoke_clean_browser_session,
)
from nodelang.clean_runtime_bootstrap import provision_clean_runtime
from nodelang.runtime_caller_capability import WindowsDpapiCallerKeyStore
from nodelang.unified_authority import composition_root
from nodelang.universal_cell import Cell


def _map_source() -> bytes:
    return json.dumps(
        [
            {
                "key": "brain",
                "title": "Brain and Memory",
                "nodes": [
                    {
                        "id": "brain_attention",
                        "cat": "behavior",
                        "title": "Persistent Attention",
                        "sub": "Keep accepted work visible across sessions",
                        "status": "partial",
                        "params": [
                            {"k": "mode", "v": "steady"},
                            {"k": "window_ms", "v": "150"},
                        ],
                        "evidence_ref": "court:clean-server-admission",
                        "authority_source": "founder",
                    },
                    {
                        "id": "brain_focus",
                        "cat": "logic",
                        "title": "Focus Contract",
                        "sub": "Carry one live focus through the graph",
                        "status": "partial",
                        "params": [
                            {"k": "selection_policy", "v": "exact"},
                        ],
                        "evidence_ref": "court:clean-server-admission",
                        "authority_source": "founder",
                    },
                ],
                "wires": [
                    ["brain_attention", "brain_focus"],
                ],
                "cross": [
                    {
                        "from": "brain_attention",
                        "to_domain": "ui",
                        "why": "Attention must stay visible in the interface",
                    }
                ],
            },
            {
                "key": "ui",
                "title": "UI and Design System",
                "nodes": [
                    {
                        "id": "ui_properties",
                        "cat": "interface",
                        "title": "Properties Rail",
                        "sub": "Edit graph-held parameters",
                        "status": "partial",
                        "params": [
                            {"k": "tabs", "v": ["Use", "Build", "Govern"]},
                        ],
                        "evidence_ref": "court:clean-server-admission",
                        "authority_source": "founder",
                    }
                ],
                "wires": [],
                "cross": [],
            },
        ],
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


def _provision_clean_runtime(tmp_path, *, root_name: str):
    root = tmp_path / root_name
    provider = MemorySigningKeyProvider(
        "archhub.unified.bootstrap",
        b"clean-server-admission-key" + b"0" * 7,
    )
    caller_keys = WindowsDpapiCallerKeyStore(root / "callers.dpapi.json")
    specification = (Path(__file__).parents[1] / "SPEC.md").read_bytes()
    grand_map = _map_source()
    built = provision_clean_runtime(
        root,
        provider,
        caller_keys,
        caller_key_id="founder.bootstrap",
        specification_source=specification,
        specification_sha256=hashlib.sha256(specification).hexdigest(),
        grand_map_source=grand_map,
        grand_map_sha256=hashlib.sha256(grand_map).hexdigest(),
    )
    return built, provider


def _start_clean_server(built, provider):
    assert hasattr(ApplicationServer, "from_unified_authority"), (
        "clean server admission requires "
        "ApplicationServer.from_unified_authority("
        "authority, browser_authority=..., authority_key_provider=...)"
    )
    return ApplicationServer.from_unified_authority(
        built.location.authority,
        browser_authority=built.browser,
        authority_key_provider=provider,
    ).start()


def _issue_clean_session(
    built,
    *,
    token: str,
    csrf: str,
    lifetime: float = 120.0,
):
    return issue_clean_browser_session(
        built.location.authority,
        built.browser,
        token=token,
        csrf_token=csrf,
        lifetime_seconds=lifetime,
        caller=built.caller,
        command_id=str(uuid.uuid4()),
    )


def _json(url, path, payload=None, *, token=None):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if token is not None:
        headers["X-ArchHub-Session"] = token
    request = Request(
        _request_url(url, path),
        data=data,
        headers=headers,
        method="GET" if payload is None else "POST",
    )
    try:
        with urlopen(request, timeout=30) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        return error.code, json.loads(error.read().decode("utf-8"))


def _interaction_request(
    projection,
    control_root,
    *,
    projection_mode="interaction-delta-v1",
):
    binding = next(
        item for item in projection["interaction_projection"]["bindings"]
        if item["control"] == control_root
    )
    return {
        "interaction": binding["interaction"],
        "control": binding["control"],
        "event": binding["event"],
        "revision": projection["interaction_projection"]["revision"],
        "projection_mode": projection_mode,
    }


def _scope_interaction_request(projection, control_root):
    return _interaction_request(
        projection,
        control_root,
        projection_mode="topology-delta-v1",
    )


def _replace_relation_participant(authority, relation_root, role_id, participant_id):
    snapshot = authority.store.snapshot()
    member = next(
        item for item in read_relation(snapshot, relation_root, budget=256)
        if item.role_id == role_id
    )
    authority.store.commit(
        snapshot.revision,
        replace=(Cell(member.incidence_id, member.role_id, participant_id, b""),),
    )


def _assert_canvas_projects_same_root(canvas, snapshot):
    assert canvas["revision"] == snapshot.revision
    assert canvas["catalog"]
    assert canvas["properties"]
    assert canvas["wires"]
    assert any(node["openable"] for node in canvas["nodes"])
    assert all(node["id"] in snapshot.cells for node in canvas["nodes"])
    assert all(wire["id"] in snapshot.cells for wire in canvas["wires"])
    assert all(item["id"] in snapshot.cells for item in canvas["catalog"])
    assert all(row["relation"] in snapshot.cells for row in canvas["properties"])


def _request_url(url, path):
    if path in ("", "/"):
        return url
    if path.startswith("?"):
        return url + path
    return url + path


def test_bootstrap_url_root_requests_keep_the_document_url_intact():
    bootstrap_url = "http://127.0.0.1:8482/?bootstrap=token"
    assert _request_url(bootstrap_url, "/") == bootstrap_url
    assert _request_url(bootstrap_url, "") == bootstrap_url


def test_clean_browser_session_http_admits_exact_graph_and_projects_one_selected_revision(
    tmp_path,
):
    built, provider = _provision_clean_runtime(
        tmp_path,
        root_name="clean-server-admission",
    )
    foreign, _foreign_provider = _provision_clean_runtime(
        tmp_path,
        root_name="foreign-clean-server-admission",
    )
    server = _start_clean_server(built, provider)
    try:
        issued = _issue_clean_session(
            built,
            token="clean-browser-token",
            csrf="clean-browser-csrf",
        )
        status, canvas = _json(
            server.url,
            "/api/universal/canvas",
            token="clean-browser-token",
        )
        assert status == 200
        snapshot = built.location.authority.store.snapshot()
        assert canvas["authorization"]["subject"] == built.caller.actor_root
        assert [
            item["root"] for item in canvas["authorization"]["browser_sessions"]
        ] == [issued.root_id]
        _assert_canvas_projects_same_root(canvas, snapshot)

        _issue_clean_session(
            foreign,
            token="foreign-browser-token",
            csrf="foreign-browser-csrf",
        )
        denied_status, denied = _json(
            server.url,
            "/api/universal/canvas",
            token="foreign-browser-token",
        )
        assert denied_status == 403
        assert "browser session" in denied["error"].lower()

        bootstrap_status, bootstrap_denied = _json(
            server.url,
            "/api/universal/browser-handoff",
        )
        assert bootstrap_status == 403
        assert "clean" in bootstrap_denied["error"].lower()
    finally:
        server.close()


def test_clean_browser_session_http_fails_closed_on_wrong_subject_expiry_and_revocation(
    tmp_path,
):
    built, provider = _provision_clean_runtime(
        tmp_path,
        root_name="clean-server-expiry",
    )
    server = _start_clean_server(built, provider)
    try:
        issued = _issue_clean_session(
            built,
            token="wrong-subject-token",
            csrf="wrong-subject-csrf",
        )
        wrong_subject = composition_root(
            built.location.authority,
            "Workshop",
            caller=built.caller,
        )
        _replace_relation_participant(
            built.location.authority,
            issued.root_id,
            built.browser.protocol.role("subject"),
            wrong_subject,
        )
        subject_status, subject_denied = _json(
            server.url,
            "/api/universal/canvas",
            token="wrong-subject-token",
        )
        assert subject_status == 403
        assert "subject" in subject_denied["error"].lower()

        _issue_clean_session(
            built,
            token="expiring-browser-token",
            csrf="expiring-browser-csrf",
            lifetime=0.01,
        )
        time.sleep(0.05)
        expired_status, expired = _json(
            server.url,
            "/api/universal/canvas",
            token="expiring-browser-token",
        )
        assert expired_status == 403
        assert "expired" in expired["error"].lower()

        issued = _issue_clean_session(
            built,
            token="revoked-browser-token",
            csrf="revoked-browser-csrf",
        )
        revoke_clean_browser_session(
            built.location.authority,
            built.browser,
            issued.root_id,
            reason="court revocation",
            caller=built.caller,
            command_id=str(uuid.uuid4()),
        )
        revoked_status, revoked = _json(
            server.url,
            "/api/universal/canvas",
            token="revoked-browser-token",
        )
        assert revoked_status == 403
        assert "revoked" in revoked["error"].lower()
    finally:
        server.close()


def test_clean_browser_session_http_rejects_stale_revision_interactions(tmp_path):
    built, provider = _provision_clean_runtime(
        tmp_path,
        root_name="clean-server-stale-revision",
    )
    server = _start_clean_server(built, provider)
    try:
        _issue_clean_session(
            built,
            token="stale-browser-token",
            csrf="stale-browser-csrf",
        )
        status, canvas = _json(
            server.url,
            "/api/universal/canvas",
            token="stale-browser-token",
        )
        assert status == 200
        target = next(node for node in canvas["nodes"] if node["openable"])
        before = built.location.authority.store.revision
        viewport = canvas["viewport"]
        status, advanced = _json(
            server.url,
            "/api/universal/gesture",
            {
                "viewport": {
                    "pan_x": viewport["pan_x"] + 1.0,
                    "pan_y": viewport["pan_y"],
                    "zoom": viewport["zoom"],
                },
                "projection": False,
            },
            token="stale-browser-token",
        )
        assert status == 200
        assert advanced["touched"] == before + 1
        advanced_revision = built.location.authority.store.revision

        status, rejected = _json(
            server.url,
            "/api/universal/interaction",
            _scope_interaction_request(canvas, target["id"]),
            token="stale-browser-token",
        )
        assert status == 400
        assert rejected["error"] == (
            "expected revision %s, current revision is %s"
            % (canvas["revision"], advanced_revision)
        )
        assert built.location.authority.store.revision == advanced_revision
    finally:
        server.close()
