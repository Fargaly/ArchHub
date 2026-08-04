from __future__ import annotations

import hashlib
import json
import inspect
import re
import threading
import time
import uuid
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

import nodelang.application_server as application_server_module
from nodelang.application_server import ApplicationServer
from nodelang.cell_protocols import read_relation
from nodelang.cell_secret_keys import MemorySigningKeyProvider
from nodelang.clean_browser_authority import (
    issue_clean_browser_session,
    revise_clean_browser_focus,
    revoke_clean_browser_session,
)
from nodelang.clean_runtime_bootstrap import provision_clean_runtime
from nodelang.runtime_caller_capability import WindowsDpapiCallerKeyStore
from nodelang.unified_application_lens import project_unified_scope
from nodelang.unified_authority import audit_authority_history, composition_root
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


def _foreign_map_source() -> bytes:
    payload = json.loads(_map_source().decode("utf-8"))
    payload[1]["title"] = "UI and Design System - Foreign"
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


def _provision_clean_runtime(
    tmp_path,
    *,
    root_name: str,
    grand_map_source: bytes | None = None,
):
    root = tmp_path / root_name
    provider = MemorySigningKeyProvider(
        "archhub.unified.bootstrap",
        b"clean-server-admission-key" + b"0" * 7,
    )
    caller_keys = WindowsDpapiCallerKeyStore(root / "callers.dpapi.json")
    specification = (Path(__file__).parents[1] / "SPEC.md").read_bytes()
    grand_map = grand_map_source if grand_map_source is not None else _map_source()
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


def _start_clean_server(built, provider, *, scope_root):
    assert hasattr(ApplicationServer, "from_unified_authority"), (
        "clean server admission requires "
        "ApplicationServer.from_unified_authority("
        "authority, browser_authority=..., scope_caller=..., "
        "scope_root=..., authority_key_provider=...)"
    )
    return ApplicationServer.from_unified_authority(
        built.location.authority,
        browser_authority=built.browser,
        scope_caller=built.caller,
        scope_root=scope_root,
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


def _json(url, path, payload=None, *, token=None, headers=None):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    headers_map = {"Content-Type": "application/json"}
    if token is not None:
        headers_map["X-ArchHub-Session"] = token
    if headers:
        headers_map.update(headers)
    request = Request(
        _request_url(url, path),
        data=data,
        headers=headers_map,
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


def _current_authority_head_root(authority):
    snapshot = authority.store.snapshot()
    members = tuple(
        member for member in read_relation(
            snapshot,
            authority.manifest.head_index_root,
            budget=32,
        )
        if member.role_id == authority.role("current-head")
    )
    assert len(members) == 1
    return members[0].participant_id


def _relation_participants(snapshot, relation_root):
    participants = {}
    for member in read_relation(snapshot, relation_root, budget=256):
        participants.setdefault(member.role_id, []).append(member.participant_id)
    return participants


def _scalar_text(snapshot, value_root):
    return snapshot.cells[value_root].atom.decode("utf-8")


def _assert_canvas_projects_same_root(canvas, snapshot, expected_root):
    assert canvas["revision"] == snapshot.revision
    assert canvas["root"] == expected_root
    assert canvas["catalog"]
    assert canvas["properties"]
    assert canvas["wires"]
    assert any(node["ports"] for node in canvas["nodes"])
    assert any(node["openable"] for node in canvas["nodes"])
    assert all(node["id"] in snapshot.cells for node in canvas["nodes"])
    assert all("ports" in node for node in canvas["nodes"])
    assert all(wire["id"] in snapshot.cells for wire in canvas["wires"])
    assert all("participants" in wire for wire in canvas["wires"])
    assert all(item["id"] in snapshot.cells for item in canvas["catalog"])
    assert all(row["relation"] in snapshot.cells for row in canvas["properties"])


def _expected_selected_properties(
    built,
    *,
    scope_root: str,
    view_root: str,
    selected_root: str,
    revision: int,
):
    lens = project_unified_scope(
        built.location.authority,
        scope_root,
        caller=built.caller,
        view_root=view_root,
        at_revision=revision,
    )
    node = next(item for item in lens.nodes if item.root_id == selected_root)
    return [(row.name, row.value) for row in node.properties]


def _request_url(url, path):
    if path in ("", "/"):
        return url
    if path.startswith("?"):
        return url + path
    return url + path


def test_from_unified_authority_binding_has_zero_growth_and_no_registry_sidecar(
    tmp_path,
    monkeypatch,
):
    built, provider = _provision_clean_runtime(
        tmp_path,
        root_name="clean-server-binding",
    )
    snapshot = built.location.authority.store.snapshot()
    revision = snapshot.revision
    cell_count = len(snapshot.cells)
    source = Path(application_server_module.__file__).read_text(
        encoding="utf-8"
    )
    method_source = inspect.getsource(ApplicationServer.from_unified_authority)

    assert "project_unified_scope(" in source, (
        "clean canvas admission must be routed through the clean scope lens"
    )
    assert "scope_lens_payload(" in source, (
        "clean canvas admission must serialize the clean scope lens"
    )
    assert "verify_clean_browser_session(" in source, (
        "clean browser admission must use the clean browser authority"
    )
    assert "scope_caller=None" not in method_source
    assert re.search(r"\\.registry\\b|\\.universal_registry\\b", method_source) is None
    assert "UniversalRegistry(" not in method_source

    def reject_registry_build(*_args, **_kwargs):
        raise AssertionError(
            "from_unified_authority must not build a compatibility registry"
        )

    monkeypatch.setattr(
        application_server_module,
        "build_universal_application",
        reject_registry_build,
    )

    server = ApplicationServer.from_unified_authority(
        built.location.authority,
        browser_authority=built.browser,
        scope_caller=built.caller,
        scope_root=built.grand_map.root_id,
        authority_key_provider=provider,
    )
    assert getattr(server, "clean_authority", None) is built.location.authority
    assert getattr(server, "clean_store", None) is built.location.authority.store
    assert getattr(server, "clean_browser_authority", None) is built.browser
    assert getattr(server, "clean_caller", None) is built.caller
    assert getattr(server, "authority_key_provider", None) is provider
    assert not hasattr(server, "universal_registry")
    assert not hasattr(server, "universal_store")
    assert built.location.authority.store.revision == revision
    assert len(built.location.authority.store.snapshot().cells) == cell_count


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
        grand_map_source=_foreign_map_source(),
    )
    server = _start_clean_server(
        built,
        provider,
        scope_root=built.grand_map.root_id,
    )
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
        _assert_canvas_projects_same_root(
            canvas,
            snapshot,
            built.grand_map.root_id,
        )

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

    foreign_server = _start_clean_server(
        built,
        provider,
        scope_root=foreign.grand_map.root_id,
    )
    try:
        _issue_clean_session(
            built,
            token="foreign-scope-token",
            csrf="foreign-scope-csrf",
        )
        foreign_status, foreign_denied = _json(
            foreign_server.url,
            "/api/universal/canvas",
            token="foreign-scope-token",
        )
        assert foreign_status == 403
        assert "scope" in foreign_denied["error"].lower()
    finally:
        foreign_server.close()

    missing_server = _start_clean_server(
        built,
        provider,
        scope_root="app:missing-clean-scope-root",
    )
    try:
        _issue_clean_session(
            built,
            token="missing-scope-token",
            csrf="missing-scope-csrf",
        )
        missing_status, missing_denied = _json(
            missing_server.url,
            "/api/universal/canvas",
            token="missing-scope-token",
        )
        assert missing_status == 403
        assert "scope" in missing_denied["error"].lower()
    finally:
        missing_server.close()


def test_clean_browser_session_http_projects_graph_held_focus_and_properties_from_same_view_session(
    tmp_path,
):
    built, provider = _provision_clean_runtime(
        tmp_path,
        root_name="clean-server-focus-projection",
    )
    server = _start_clean_server(
        built,
        provider,
        scope_root=built.grand_map.root_id,
    )
    try:
        issued = _issue_clean_session(
            built,
            token="focus-browser-token",
            csrf="focus-browser-csrf",
        )
        status, before = _json(
            server.url,
            "/api/universal/canvas",
            token="focus-browser-token",
        )
        assert status == 200
        assert before["selected"] is None
        assert before["selection"] == []
        assert before["properties"] == []

        target = before["nodes"][1]["id"]
        focused = revise_clean_browser_focus(
            built.location.authority,
            built.browser,
            issued.root_id,
            scope_root=built.grand_map.root_id,
            selected_roots=(target,),
            primary_root=target,
            caller=built.caller,
            command_id=str(uuid.uuid4()),
            expected_revision=before["revision"],
        )
        status, after = _json(
            server.url,
            "/api/universal/canvas",
            token="focus-browser-token",
        )
        assert status == 200
        assert after["revision"] == focused.revision
        assert after["root"] == built.grand_map.root_id
        assert after["selected"] == target
        assert after["focus"] == target
        assert after["selection"] == [target]
        selected = next(node for node in after["nodes"] if node["id"] == target)
        assert selected["selected"] is True
        assert selected["focused"] is True
        assert after["selected_title"] == selected["label"]
        assert after["authorization"]["browser_sessions"] == [
            {"root": issued.root_id}
        ]
        assert [row["label"] for row in after["properties"]] == [
            row["label"] for row in selected["properties"]
        ]
    finally:
        server.close()


def test_clean_browser_session_http_focus_command_persists_selection_and_reopens(
    tmp_path,
):
    built, provider = _provision_clean_runtime(
        tmp_path,
        root_name="clean-server-focus-http",
    )
    server = _start_clean_server(
        built,
        provider,
        scope_root=built.grand_map.root_id,
    )
    try:
        issued = _issue_clean_session(
            built,
            token="focus-http-token",
            csrf="focus-http-csrf",
        )
        status, before = _json(
            server.url,
            "/api/universal/canvas",
            token="focus-http-token",
        )
        assert status == 200
        assert before["selected"] is None
        target = before["nodes"][1]["id"]
        command_id = str(uuid.uuid4())
        focus_request = {
            "scope_root": built.grand_map.root_id,
            "selected_roots": [target],
            "primary_root": target,
            "revision": before["revision"],
            "command_id": command_id,
        }

        status, focused = _json(
            server.url,
            "/api/universal/focus",
            focus_request,
            token="focus-http-token",
            headers={"X-ArchHub-CSRF": "focus-http-csrf"},
        )
        assert status == 200
        assert focused["root"] == built.grand_map.root_id
        assert focused["selected"] == target
        assert focused["focus"] == target
        assert focused["selection"] == [target]
        assert focused["accepted_revision"] > before["revision"]
        assert focused["revision"] == focused["accepted_revision"]
        assert focused["authorization"]["browser_sessions"] == [
            {"root": issued.root_id}
        ]
        selected = next(node for node in focused["nodes"] if node["id"] == target)
        assert selected["selected"] is True
        assert selected["focused"] is True
        expected_properties = _expected_selected_properties(
            built,
            scope_root=built.grand_map.root_id,
            view_root=issued.view_root,
            selected_root=target,
            revision=focused["accepted_revision"],
        )
        assert focused["properties"]
        assert all(row["relation"] == target for row in focused["properties"])
        assert [(row["label"], row["value"]) for row in focused["properties"]] == [
            (name, value) for name, value in expected_properties
        ]
        focus_snapshot = built.location.authority.store.at(focused["accepted_revision"])
        assert focused["receipt"] in focus_snapshot.cells
        participants = _relation_participants(focus_snapshot, focused["receipt"])
        assert participants[built.location.authority.role("result")] == [
            focused["focus_root"]
        ]
        focus_revision = focused["accepted_revision"]
        focus_cells = len(built.location.authority.store.snapshot().cells)
        status, replayed = _json(
            server.url,
            "/api/universal/focus",
            focus_request,
            token="focus-http-token",
            headers={"X-ArchHub-CSRF": "focus-http-csrf"},
        )
        assert status == 200
        assert replayed["accepted_revision"] == focus_revision
        assert replayed["revision"] == focused["revision"]
        assert replayed["root"] == focused["root"]
        assert replayed["selection"] == focused["selection"]
        assert replayed["focus_root"] == focused["focus_root"]
        assert replayed["receipt"] == focused["receipt"]
        assert len(built.location.authority.store.snapshot().cells) == focus_cells

        different_target = before["nodes"][0]["id"]
        status, conflicted = _json(
            server.url,
            "/api/universal/focus",
            {
                **focus_request,
                "selected_roots": [different_target],
                "primary_root": different_target,
            },
            token="focus-http-token",
            headers={"X-ArchHub-CSRF": "focus-http-csrf"},
        )
        assert status == 403
        assert "idempotency" in conflicted["error"].lower()
    finally:
        server.close()

    reopened = _start_clean_server(
        built,
        provider,
        scope_root=built.grand_map.root_id,
    )
    try:
        status, after = _json(
            reopened.url,
            "/api/universal/canvas",
            token="focus-http-token",
        )
        assert status == 200
        assert after["selected"] == target
        assert after["focus"] == target
        assert after["selection"] == [target]
        assert after["authorization"]["browser_sessions"] == [
            {"root": issued.root_id}
        ]
    finally:
        reopened.close()


def test_clean_browser_session_http_focus_command_requires_exact_csrf_and_keeps_revision_stable(
    tmp_path,
):
    built, provider = _provision_clean_runtime(
        tmp_path,
        root_name="clean-server-focus-http-csrf",
    )
    server = _start_clean_server(
        built,
        provider,
        scope_root=built.grand_map.root_id,
    )
    try:
        _issue_clean_session(
            built,
            token="focus-http-csrf-token",
            csrf="focus-http-csrf-value",
        )
        status, before = _json(
            server.url,
            "/api/universal/canvas",
            token="focus-http-csrf-token",
        )
        assert status == 200
        target = before["nodes"][1]["id"]
        request = {
            "scope_root": built.grand_map.root_id,
            "selected_roots": [target],
            "primary_root": target,
            "revision": before["revision"],
            "command_id": str(uuid.uuid4()),
        }
        before_revision = built.location.authority.store.revision

        status, missing = _json(
            server.url,
            "/api/universal/focus",
            request,
            token="focus-http-csrf-token",
        )
        assert status == 403
        assert "csrf" in missing["error"].lower()
        assert built.location.authority.store.revision == before_revision

        status, wrong = _json(
            server.url,
            "/api/universal/focus",
            request,
            token="focus-http-csrf-token",
            headers={"X-ArchHub-CSRF": "wrong-focus-http-csrf"},
        )
        assert status == 403
        assert "csrf" in wrong["error"].lower()
        assert built.location.authority.store.revision == before_revision
    finally:
        server.close()


def test_clean_browser_session_http_request_does_not_walk_prior_authority_revisions(
    tmp_path,
    monkeypatch,
):
    built, provider = _provision_clean_runtime(
        tmp_path,
        root_name="clean-server-request-head-verify",
    )
    server = _start_clean_server(
        built,
        provider,
        scope_root=built.grand_map.root_id,
    )
    try:
        _issue_clean_session(
            built,
            token="head-verify-browser-token",
            csrf="head-verify-browser-csrf",
        )
        before_revision = built.location.authority.store.revision
        original_at = built.location.authority.store.at
        seen_revisions = []

        def traced_at(revision):
            seen_revisions.append(revision)
            return original_at(revision)

        monkeypatch.setattr(built.location.authority.store, "at", traced_at)
        status, _ = _json(
            server.url,
            "/api/universal/canvas",
            token="head-verify-browser-token",
        )
        assert status == 200
        assert not any(revision < before_revision for revision in seen_revisions)
    finally:
        server.close()


def test_clean_browser_session_http_focus_command_serializes_stale_competition(
    tmp_path,
):
    built, provider = _provision_clean_runtime(
        tmp_path,
        root_name="clean-server-focus-http-concurrency",
    )
    server = _start_clean_server(
        built,
        provider,
        scope_root=built.grand_map.root_id,
    )
    try:
        issued = _issue_clean_session(
            built,
            token="focus-http-race-token",
            csrf="focus-http-race-csrf",
        )
        status, before = _json(
            server.url,
            "/api/universal/canvas",
            token="focus-http-race-token",
        )
        assert status == 200
        targets = [before["nodes"][0]["id"], before["nodes"][1]["id"]]
        barrier = threading.Barrier(2)
        results = []
        result_lock = threading.Lock()

        def attempt(target):
            barrier.wait()
            outcome = _json(
                server.url,
                "/api/universal/focus",
                {
                    "scope_root": built.grand_map.root_id,
                    "selected_roots": [target],
                    "primary_root": target,
                    "revision": before["revision"],
                    "command_id": str(uuid.uuid4()),
                },
                token="focus-http-race-token",
                headers={"X-ArchHub-CSRF": "focus-http-race-csrf"},
            )
            with result_lock:
                results.append((target, outcome))

        first = threading.Thread(target=attempt, args=(targets[0],))
        second = threading.Thread(target=attempt, args=(targets[1],))
        first.start()
        second.start()
        first.join(timeout=30)
        second.join(timeout=30)
        assert not first.is_alive()
        assert not second.is_alive()

        successes = [
            (target, payload)
            for target, (status, payload) in results
            if status == 200
        ]
        failures = [
            (target, payload)
            for target, (status, payload) in results
            if status == 403
        ]
        assert len(successes) == 1
        assert len(failures) == 1
        winner_target, winner = successes[0]
        loser_target, loser = failures[0]
        assert winner["revision"] == winner["accepted_revision"]
        assert winner["selection"] == [winner_target]
        assert winner["focus"] == winner_target
        assert "stale" in loser["error"].lower() or "idempotency" in loser["error"].lower()

        status, after = _json(
            server.url,
            "/api/universal/canvas",
            token="focus-http-race-token",
        )
        assert status == 200
        assert after["revision"] == winner["accepted_revision"]
        assert after["selection"] == [winner_target]
        assert after["focus"] == winner_target
        assert loser_target != winner_target
        assert after["authorization"]["browser_sessions"] == [
            {"root": issued.root_id}
        ]
    finally:
        server.close()


def test_clean_browser_session_http_fails_closed_on_wrong_subject_expiry_and_revocation(
    tmp_path,
):
    built, provider = _provision_clean_runtime(
        tmp_path,
        root_name="clean-server-expiry",
    )
    server = _start_clean_server(
        built,
        provider,
        scope_root=built.grand_map.root_id,
    )
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
    finally:
        server.close()

    built, provider = _provision_clean_runtime(
        tmp_path,
        root_name="clean-server-expiry-only",
    )
    server = _start_clean_server(
        built,
        provider,
        scope_root=built.grand_map.root_id,
    )
    try:
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
    finally:
        server.close()

    built, provider = _provision_clean_runtime(
        tmp_path,
        root_name="clean-server-revocation-only",
    )
    server = _start_clean_server(
        built,
        provider,
        scope_root=built.grand_map.root_id,
    )
    try:
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
    server = _start_clean_server(
        built,
        provider,
        scope_root=built.grand_map.root_id,
    )
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
        status, advanced = _json(
            server.url,
            "/api/universal/focus",
            {
                "scope_root": built.grand_map.root_id,
                "selected_roots": [canvas["nodes"][0]["id"]],
                "primary_root": canvas["nodes"][0]["id"],
                "revision": before,
                "command_id": str(uuid.uuid4()),
            },
            token="stale-browser-token",
            headers={"X-ArchHub-CSRF": "stale-browser-csrf"},
        )
        assert status == 200
        assert advanced["accepted_revision"] > before
        advanced_revision = advanced["accepted_revision"]
        assert built.location.authority.store.revision == advanced_revision

        status, rejected = _json(
            server.url,
            "/api/universal/interaction",
            _scope_interaction_request(canvas, target["id"]),
            token="stale-browser-token",
            headers={"X-ArchHub-CSRF": "stale-browser-csrf"},
        )
        assert status == 400
        assert rejected["error"] == (
            "expected revision %s, current revision is %s"
            % (canvas["revision"], advanced_revision)
        )
        assert built.location.authority.store.revision == advanced_revision
    finally:
        server.close()


def test_clean_browser_session_http_source_has_no_hidden_pulse_or_magic_scope_dispatch():
    server_source = inspect.getsource(application_server_module._CleanAuthorityHttpServer)
    projector_source = inspect.getsource(
        application_server_module.project_clean_visual_canvas
    )
    assert "_pulse_root" not in server_source
    assert "_touch_gesture_revision" not in server_source
    assert 'interaction == "scope:%s" % control' not in server_source
    assert '"scope:%s" % node["id"]' not in projector_source


def test_clean_browser_session_http_rejects_unsigned_gesture_commits_and_keeps_revision_stable(
    tmp_path,
):
    built, provider = _provision_clean_runtime(
        tmp_path,
        root_name="clean-server-gesture-red",
    )
    server = _start_clean_server(
        built,
        provider,
        scope_root=built.grand_map.root_id,
    )
    try:
        _issue_clean_session(
            built,
            token="gesture-browser-token",
            csrf="gesture-browser-csrf",
        )
        status, canvas = _json(
            server.url,
            "/api/universal/canvas",
            token="gesture-browser-token",
        )
        assert status == 200
        before_revision = built.location.authority.store.revision
        viewport = canvas["viewport"]

        status, denied = _json(
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
            token="gesture-browser-token",
            headers={"X-ArchHub-CSRF": "gesture-browser-csrf"},
        )
        assert status == 403
        assert "gesture" in denied["error"].lower()
        assert built.location.authority.store.revision == before_revision
    finally:
        server.close()


def test_clean_browser_session_http_scope_interaction_requires_signed_graph_command(
    tmp_path,
):
    built, provider = _provision_clean_runtime(
        tmp_path,
        root_name="clean-server-scope-command-red",
    )
    server = _start_clean_server(
        built,
        provider,
        scope_root=built.grand_map.root_id,
    )
    try:
        _issue_clean_session(
            built,
            token="scope-browser-token",
            csrf="scope-browser-csrf",
        )
        status, canvas = _json(
            server.url,
            "/api/universal/canvas",
            token="scope-browser-token",
        )
        assert status == 200
        target = next(node for node in canvas["nodes"] if node["openable"])
        binding = next(
            item for item in canvas["interaction_projection"]["bindings"]
            if item["control"] == target["id"]
        )
        snapshot_before = built.location.authority.store.snapshot()
        assert binding["interaction"] in snapshot_before.cells
        assert binding["control"] in snapshot_before.cells
        assert binding["event"] in snapshot_before.cells
        before_revision = built.location.authority.store.revision
        before_head = _current_authority_head_root(built.location.authority)

        status, projected = _json(
            server.url,
            "/api/universal/interaction",
            _scope_interaction_request(canvas, target["id"]),
            token="scope-browser-token",
            headers={"X-ArchHub-CSRF": "scope-browser-csrf"},
        )
        assert status == 200
        assert projected["root"] == target["id"]
        assert projected["accepted_revision"] > before_revision
        assert built.location.authority.store.revision == projected["accepted_revision"]
        receipt_root = projected["receipt"]
        snapshot = built.location.authority.store.at(projected["accepted_revision"])
        assert receipt_root in snapshot.cells
        assert _current_authority_head_root(built.location.authority) != before_head
        participants = _relation_participants(snapshot, receipt_root)
        command_root = participants[built.location.authority.role("command")][0]
        head_root = participants[built.location.authority.role("head")][0]
        result_root = participants[built.location.authority.role("result")][0]
        assert result_root == target["id"]
        assert head_root == _current_authority_head_root(built.location.authority)
        command = _relation_participants(snapshot, command_root)
        assert command[built.location.authority.role("object")] == [target["id"]]
        assert command[built.location.authority.role("scope")] == [canvas["root"]]
        intent_root = command[built.location.authority.role("intent")][0]
        assert "scope" in _scalar_text(snapshot, intent_root).lower()
        audit_authority_history(built.location.authority)
    finally:
        server.close()


def test_clean_browser_session_http_fails_closed_on_invalid_authority_head_tamper(
    tmp_path,
):
    built, provider = _provision_clean_runtime(
        tmp_path,
        root_name="clean-server-head-tamper-red",
    )
    server = _start_clean_server(
        built,
        provider,
        scope_root=built.grand_map.root_id,
    )
    try:
        issued = _issue_clean_session(
            built,
            token="tamper-browser-token",
            csrf="tamper-browser-csrf",
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

        status, denied = _json(
            server.url,
            "/api/universal/canvas",
            token="tamper-browser-token",
        )
        assert status == 403
        assert "authority head" in denied["error"].lower()
    finally:
        server.close()
