"""HTTP court proving the normal desktop host has no raw authoring bypass."""
import copy
import json
import hashlib
import base64
import re
import time
import uuid
from dataclasses import replace
from functools import wraps
from pathlib import Path
from types import MappingProxyType
from http.cookiejar import CookieJar
from urllib.error import HTTPError
from urllib.request import HTTPCookieProcessor, Request, build_opener, urlopen

import pytest

import nodelang.application_server as application_server_module
import nodelang.universal_application as universal_application_module

from nodelang.application_server import ApplicationServer
from nodelang.cell_protocols import (
    prepare_append_relation_members,
    prepare_remove_relation_members,
    read_relation,
)
from nodelang.cell_catalog import read_definition
from nodelang.cell_relation_composer import read_relation_composer_draft
from nodelang.map_import import resolve_map_path
from nodelang.universal_application import (
    build_universal_application,
    instantiate_universal_definition,
    promote_universal_resource_lifecycle,
    provision_universal_view_session,
)
from nodelang.universal_cell import NULL_CELL_ID, Cell, InvalidCell
from nodelang.cell_identity import revoke_authority_relationship
from nodelang.cell_browser_sessions import (
    issue_browser_session as issue_browser_session_relation,
    project_browser_session_protocol,
    read_browser_session,
    revoke_browser_session,
)
from nodelang.cell_secret_keys import MemorySigningKeyProvider
from nodelang.cell_revision_checkpoint import RevisionCheckpointGuard
from nodelang.cell_device_keys import (
    DeviceProofKeyReference,
    PLATFORM_PROVIDER,
)
from nodelang.universal_cell import CellStore
from tests_replica.windows_cng_court import delete_court_key
from nodelang.windows_cng_signing_provider import SOFTWARE_PROVIDER_ID
from nodelang.checkpoint_authority_provisioning import (
    provision_windows_revision_checkpoint_authority,
)


def test_application_server_clean_browser_admission_is_not_yet_bound():
    source = Path(application_server_module.__file__).read_text(
        encoding="utf-8"
    )
    assert "verify_clean_browser_session(" in source, (
        "ApplicationServer still admits browser sessions only through the "
        "legacy browser-session verifier"
    )
    assert "issue_clean_browser_session(" in source, (
        "ApplicationServer still issues browser sessions through the legacy "
        "browser-session path"
    )
    for marker in (
        "self.browser_session_token =",
        "self.browser_csrf_token =",
        "self.browser_bootstrap_token =",
        "self._browser_sessions = {}",
    ):
        assert marker not in source, (
            "ApplicationServer still owns local browser token state: %s"
            % marker
        )


def test_baboom_department_runner_is_released_as_a_closed_connector_provider():
    providers = {
        provider: (adapter, action, location, datatypes, operation)
        for provider, adapter, _name, action, location, datatypes, operation
        in universal_application_module._BABOOM_CONNECTOR_ADAPTER_SPECS
    }
    assert providers["archhub-department-run"] == (
        "app:adapter:connector:archhub-department-run:v1",
        "run-department-cycle",
        "process:archhub-department-runner",
        ("internal-text",),
        "archhub.department.run_once",
    )


def test_baboom_meeting_opener_is_released_as_an_explicit_connector_provider():
    providers = {
        provider: (adapter, action, location, datatypes, operation)
        for provider, adapter, _name, action, location, datatypes, operation
        in universal_application_module._BABOOM_CONNECTOR_ADAPTER_SPECS
    }
    assert providers["teams-open-meeting"] == (
        "app:adapter:connector:teams-open-meeting:v1",
        "open-selected-meeting",
        "device:founder-local-desktop",
        ("internal-metadata",),
        "teams.open_meeting",
    )


class _HttpFakeHardwareKey:
    def __init__(self):
        encode = lambda value: base64.urlsafe_b64encode(value).rstrip(b"=").decode()
        public = {
            "crv": "P-256", "kty": "EC",
            "x": encode(b"h" * 32), "y": encode(b"i" * 32),
        }
        document = json.dumps(public, sort_keys=True, separators=(",", ":"))
        thumbprint = encode(hashlib.sha256(document.encode("ascii")).digest())
        self.reference = DeviceProofKeyReference(
            "ArchHub.Test.HttpHardwareKey",
            PLATFORM_PROVIDER,
            "ES256",
            thumbprint,
            MappingProxyType(public),
            True,
        )
        self.closed = False

    def close(self):
        self.closed = True


def _json(url, path, payload=None, *, token=None):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if token is not None:
        headers["X-ArchHub-Session"] = token
    request = Request(
        url + path,
        data=data,
        headers=headers,
        method="GET" if payload is None else "POST",
    )
    try:
        with urlopen(request, timeout=30) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        return error.code, json.loads(error.read().decode("utf-8"))


def _form_interaction_request(projection, form, values):
    binding = next(
        item for item in projection["interaction_projection"]["bindings"]
        if item["control"] == form["control"]
    )
    return {
        "interaction": binding["interaction"],
        "control": binding["control"],
        "event": binding["event"],
        "event_facts": [
            {"input": form["inputs"][key], "value": value}
            for key, value in values.items()
        ],
        "revision": projection["interaction_projection"]["revision"],
        "projection_mode": "interaction-delta-v1",
    }


def _interaction_request(
    projection, control_root, *, projection_mode="interaction-delta-v1"
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


def _event_fact_interaction_request(
    projection,
    control_root,
    values,
    *,
    projection_mode="interaction-delta-v1",
):
    request = _interaction_request(
        projection, control_root, projection_mode=projection_mode
    )
    binding = next(
        item for item in projection["interaction_projection"]["bindings"]
        if item["control"] == control_root
    )
    by_source = {item["source"]: item for item in binding["event_facts"]}
    request["event_facts"] = [
        {"input": by_source[source]["input"], "value": value}
        for source, value in values.items()
    ]
    return request


def _scope_interaction_request(projection, control_root):
    return _interaction_request(
        projection,
        control_root,
        projection_mode="topology-delta-v1",
    )


def _merge_canvas_delta(previous, result):
    """Apply the same revision-bound graph delta consumed by the canvas."""
    if result.get("projection_mode") not in {
        "interaction-delta-v1", "topology-delta-v1",
    }:
        return result
    merged = {**previous, **result}
    configuration = {
        **previous["configuration"],
        **result["configuration_state"],
    }
    configuration["design_system"] = {
        **previous["configuration"]["design_system"],
        "control_catalog": result["control_state"],
    }
    merged["configuration"] = configuration
    if result.get("topology_recovery") is True:
        merged["nodes"] = result["nodes"]
        merged["wires"] = result["wires"]
        return merged
    patch = result.get("topology_patch")
    if patch is not None:
        nodes = {node["id"]: node for node in previous["nodes"]}
        wires = {
            "%s:%s" % (wire["id"], wire["segment"]): wire
            for wire in previous["wires"]
        }
        for root in patch["remove_nodes"]:
            nodes.pop(root, None)
        for root in patch["remove_wires"]:
            wires.pop(root, None)
        nodes.update({node["id"]: node for node in patch["upsert_nodes"]})
        wires.update({
            "%s:%s" % (wire["id"], wire["segment"]): wire
            for wire in patch["upsert_wires"]
        })
        merged["nodes"] = [nodes[root] for root in patch["node_order"]]
        merged["wires"] = [wires[root] for root in patch["wire_order"]]
    elif result["projection_mode"] == "interaction-delta-v1":
        node_states = {
            state["id"]: state for state in result["node_states"]
        }
        wire_states = {
            "%s:%s" % (state["id"], state["segment"]): state
            for state in result["wire_states"]
        }
        node_patches = {
            node["id"]: node for node in result.get("node_patches", ())
        }
        wire_patches = {
            "%s:%s" % (wire["id"], wire["segment"]): wire
            for wire in result.get("wire_patches", ())
        }
        previous_node_roots = {node["id"] for node in previous["nodes"]}
        previous_wire_roots = {
            "%s:%s" % (wire["id"], wire["segment"])
            for wire in previous["wires"]
        }
        assert result["node_count"] == len(previous_node_roots)
        assert result["wire_count"] == len(previous_wire_roots)
        assert set(node_states) <= previous_node_roots
        assert set(wire_states) <= previous_wire_roots
        merged["nodes"] = [
            {
                **node,
                **node_patches.get(node["id"], {}),
                **node_states.get(node["id"], {}),
            }
            for node in previous["nodes"]
        ]
        merged["wires"] = [
            {
                **wire,
                **wire_patches.get(
                    "%s:%s" % (wire["id"], wire["segment"]), {}
                ),
                **wire_states.get(
                    "%s:%s" % (wire["id"], wire["segment"]), {}
                ),
            }
            for wire in previous["wires"]
        ]
    return merged


def _placement_interaction_request(
    projection, definition_root, x, y, *, viewport=None
):
    binding = next(
        item for item in projection["interaction_projection"]["bindings"]
        if item["control"] == definition_root
    )
    values = {"canvas-point-x": x, "canvas-point-y": y}
    if viewport is not None:
        values.update({
            "canvas-viewport-pan-x": viewport["pan_x"],
            "canvas-viewport-pan-y": viewport["pan_y"],
            "canvas-viewport-zoom": viewport["zoom"],
        })
    by_source = {item["source"]: item for item in binding["event_facts"]}
    return {
        "interaction": binding["interaction"],
        "control": binding["control"],
        "event": binding["event"],
        "event_facts": [
            {"input": by_source[source]["input"], "value": value}
            for source, value in values.items()
        ],
        "revision": projection["interaction_projection"]["revision"],
        "projection_mode": "topology-delta-v1",
    }


def _create_http_primitive(server, token, *, x, y):
    status, projection = _json(
        server.url, "/api/universal/canvas", token=token
    )
    assert status == 200
    if projection["primitive"]["visible"] is not True:
        floor_lens = next(
            lens for lens in projection["inspector"]["lenses"]
            if lens["name"] == "floor"
        )
        status, _delta = _json(
            server.url,
            "/api/universal/interaction",
            _interaction_request(projection, floor_lens["id"]),
            token=token,
        )
        assert status == 200
        status, projection = _json(
            server.url, "/api/universal/canvas", token=token
        )
        assert status == 200
    primitive_root = projection["primitive"]["id"]
    status, created = _json(
        server.url,
        "/api/universal/interaction",
        _placement_interaction_request(projection, primitive_root, x, y),
        token=token,
    )
    assert status == 200
    return created


def test_browser_cookie_hides_session_and_requires_bound_csrf_for_writes():
    server = ApplicationServer().start()
    try:
        jar = CookieJar()
        opener = build_opener(HTTPCookieProcessor(jar))
        bootstrap_url = server.bootstrap_url
        with opener.open(bootstrap_url, timeout=30) as response:
            page = response.read().decode("utf-8")
            cookie_header = response.headers.get("Set-Cookie")
        assert server.browser_session_token not in page
        assert 'meta name="archhub-session"' not in page
        csrf = re.search(
            r'<meta name="archhub-csrf" content="([A-Za-z0-9_-]+)">',
            page,
        ).group(1)
        assert csrf == server.browser_csrf_token
        assert "HttpOnly" in cookie_header
        assert "SameSite=Strict" in cookie_header
        assert "Path=/" in cookie_header

        with pytest.raises(HTTPError) as replay:
            urlopen(bootstrap_url, timeout=30)
        assert replay.value.code == 403
        assert "bootstrap" in replay.value.read().decode("utf-8")

        with opener.open(
            Request(server.url + "/api/universal/canvas"), timeout=30
        ) as response:
            canvas = json.loads(response.read().decode("utf-8"))
        assert canvas["authorization"]["subject"] \
            == server.universal_registry.authorization.subject_root

        missing_csrf = Request(
            server.url + "/api/universal/gesture",
            data=json.dumps({
                "viewport": {"pan_x": 4, "pan_y": 8, "zoom": 1.0}
            }).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with pytest.raises(HTTPError) as denied:
            opener.open(missing_csrf, timeout=30)
        assert denied.value.code == 403
        assert "CSRF" in denied.value.read().decode("utf-8")

        with opener.open(Request(
            server.url + "/api/universal/gesture",
            data=json.dumps({
                "viewport": {"pan_x": 4, "pan_y": 8, "zoom": 1.0}
            }).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "X-ArchHub-CSRF": csrf,
            },
            method="POST",
        ), timeout=30) as response:
            assert json.loads(response.read().decode("utf-8"))["ok"] is True

        status, denied_cross_site = _json(
            server.url, "/api/universal/canvas",
            token=server.browser_session_token,
        )
        assert status == 200
        cross_site = Request(
            server.url + "/api/universal/canvas",
            headers={
                "X-ArchHub-Session": server.browser_session_token,
                "Sec-Fetch-Site": "cross-site",
            },
        )
        with pytest.raises(HTTPError) as denied:
            urlopen(cross_site, timeout=30)
        assert denied.value.code == 403
        assert "cross-site" in denied.value.read().decode("utf-8")
    finally:
        server.close()


def test_browser_bootstrap_does_not_admit_without_clean_signed_session():
    server = ApplicationServer().start()
    try:
        with pytest.raises(HTTPError) as denied:
            urlopen(server.bootstrap_url, timeout=30)
        assert denied.value.code == 403
        body = denied.value.read().decode("utf-8")
        assert "clean" in body
        assert "browser session" in body
    finally:
        server.close()


def test_legacy_local_browser_token_does_not_bypass_clean_admission():
    server = ApplicationServer().start()
    try:
        status, denied = _json(
            server.url,
            "/api/universal/canvas",
            token=server.browser_session_token,
        )
        assert status == 403
        assert "clean" in denied["error"]
        assert "browser session" in denied["error"]
    finally:
        server.close()


def test_browser_routes_group_open_and_ungroup_the_live_governed_canvas():
    server = ApplicationServer().start()
    try:
        token = server.browser_session_token
        status, before = _json(
            server.url, "/api/universal/canvas", token=token
        )
        assert status == 200
        original = tuple(node["id"] for node in before["nodes"])

        domain_root = next(
            node["id"] for node in before["nodes"]
            if node["label"] == "Brain & Memory"
        )
        scope_binding = next(
            item for item in before["interaction_projection"]["bindings"]
            if item["control"] == domain_root
        )
        assert scope_binding["projection_mode"] == "topology-delta-v1"
        status, domain_delta = _json(
            server.url,
            "/api/universal/interaction",
            _scope_interaction_request(before, domain_root),
            token=token,
        )
        assert status == 200
        domain = _merge_canvas_delta(before, domain_delta)
        assert domain["scope"]["current"] == domain_root
        assert domain["scope"]["parent"] \
            == server.universal_registry.canvas_root
        assert domain["nodes"]
        assert all(node["id"] != domain_root for node in domain["nodes"])
        status, before_delta = _json(
            server.url,
            "/api/universal/interaction",
            _scope_interaction_request(
                domain, server.universal_registry.canvas_root
            ),
            token=token,
        )
        assert status == 200
        before = _merge_canvas_delta(domain, before_delta)
        assert tuple(node["id"] for node in before["nodes"]) == original

        selected = original[:2]
        status, selected_projection = _json(
            server.url,
            "/api/universal/gesture",
            {"roots": selected, "focus": selected[-1]},
            token=token,
        )
        assert status == 200
        assert set(selected_projection["selection"]) == set(selected)
        assert selected_projection["focus"]["consent_evidence"] == [
            server.browser_session_root
        ]

        status, grouped_delta = _json(
            server.url,
            "/api/universal/interaction",
            _interaction_request(
                selected_projection,
                "app:control:canvas:group",
                projection_mode="topology-delta-v1",
            ),
            token=token,
        )
        assert status == 200
        grouped = _merge_canvas_delta(selected_projection, grouped_delta)
        composition_root = grouped["created_root"]
        group = next(
            node for node in grouped["nodes"]
            if node["id"] == composition_root
        )
        assert group["composition"] is True
        assert group["member_count"] == 2

        status, nested_delta = _json(
            server.url,
            "/api/universal/interaction",
            _scope_interaction_request(grouped, composition_root),
            token=token,
        )
        assert status == 200
        nested = _merge_canvas_delta(grouped, nested_delta)
        assert tuple(node["id"] for node in nested["nodes"]) == selected
        status, parent_delta = _json(
            server.url,
            "/api/universal/interaction",
            _scope_interaction_request(
                nested, server.universal_registry.canvas_root
            ),
            token=token,
        )
        assert status == 200
        parent = _merge_canvas_delta(nested, parent_delta)
        assert parent["scope"]["current"] \
            == server.universal_registry.canvas_root

        status, parent = _json(
            server.url,
            "/api/universal/gesture",
            {"roots": [composition_root], "focus": composition_root},
            token=token,
        )
        assert status == 200

        status, restored_delta = _json(
            server.url,
            "/api/universal/interaction",
            _interaction_request(
                parent,
                "app:control:canvas:ungroup",
                projection_mode="topology-delta-v1",
            ),
            token=token,
        )
        assert status == 200
        restored = _merge_canvas_delta(parent, restored_delta)
        assert tuple(node["id"] for node in restored["nodes"]) == original
        for path, body in (
            ("/api/universal/group", {"title": "retired"}),
            ("/api/universal/ungroup", {"root": composition_root}),
        ):
            status, retired = _json(
                server.url, path, body, token=token
            )
            assert status == 404
            assert retired["error"] == "not found"
    finally:
        server.close()


def test_governed_work_http_route_reads_and_writes_the_one_cell_registry():
    server = ApplicationServer().start()
    try:
        token = server.browser_session_token

        status, denied = _json(server.url, "/api/universal/work")
        assert status == 403
        assert "authenticated browser session" in denied["error"]

        status, before = _json(
            server.url, "/api/universal/work", token=token
        )
        assert status == 200
        assert before["registry"] \
            == server.universal_registry.governed_work_registry_root
        assert before["items"] == []

        revision = server.universal_store.revision
        status, rejected = _json(
            server.url,
            "/api/universal/work",
            {
                "title": "Forbidden copied field",
                "record": {"state": "OPEN"},
                "projection": False,
            },
            token=token,
        )
        assert status == 400
        assert "undeclared facts" in rejected["error"]
        assert server.universal_store.revision == revision

        brain_root = server.universal_registry.map.domains["brain"]
        status, created = _json(
            server.url,
            "/api/universal/work",
            {
                "title": "Migrate Brain authority",
                "description": "Replace the JSON work ledger with Cells",
                "priority": 100,
                "external_key": "active-work:brain-authority",
                "references": {"scope": brain_root},
                "x": 640,
                "y": 420,
                "projection": False,
            },
            token=token,
        )
        assert status == 200
        assert created["created_root"].startswith("assembly-instance:")
        assert created["membership_wire"].startswith(
            "app:relation:governed-work:"
        )
        assert created["membership_wire"] in (
            server.universal_store.snapshot().cells
        )

        status, after = _json(
            server.url, "/api/universal/work", token=token
        )
        assert status == 200
        assert len(after["items"]) == 1
        item = after["items"][0]
        assert item["root"] == created["created_root"]
        assert item["membership_wire"] == created["membership_wire"]
        assert item["interfaces"]["title"]["value"] \
            == "Migrate Brain authority"
        assert item["interfaces"]["description"]["value"] \
            == "Replace the JSON work ledger with Cells"
        assert item["interfaces"]["priority"]["value"] == "100"
        assert item["interfaces"]["external-key"]["value"] \
            == "active-work:brain-authority"
        assert item["interfaces"]["scope"]["target"] == brain_root
        assert item["operational"]["current_state_label"] == "OPEN"
    finally:
        server.close()


def test_properties_panel_uses_only_its_applicable_graph_interaction():
    server = ApplicationServer().start()
    try:
        token = server.browser_session_token
        registry = server.universal_registry
        status, projection = _json(
            server.url, "/api/universal/canvas", token=token
        )
        assert status == 200
        relations = registry.properties_panel_roots["relations"]
        status, changed = _json(
            server.url,
            "/api/universal/interaction",
            _interaction_request(projection, relations),
            token=token,
        )
        assert status == 200
        assert (
            changed["inspector"]["presentation"]["active"] == relations
        )

        floor = registry.properties_panel_roots["floor"]
        before = server.universal_store.snapshot().revision
        assert not any(
            item["control"] == floor
            for item in changed["interaction_projection"]["bindings"]
        )
        status, rejected = _json(
            server.url,
            "/api/universal/properties-panel",
            {"panel": floor},
            token=token,
        )
        assert status == 404
        assert rejected["error"] == "not found"
        assert server.universal_store.snapshot().revision == before
    finally:
        server.close()


def test_expired_interaction_lease_is_typed_and_retryable_before_execution():
    server = ApplicationServer().start()
    try:
        token = server.browser_session_token
        status, projection = _json(
            server.url, "/api/universal/canvas", token=token
        )
        assert status == 200
        relations = server.universal_registry.properties_panel_roots["relations"]
        binding = next(
            item for item in projection["interaction_projection"]["bindings"]
            if item["control"] == relations
        )
        before = server.universal_store.snapshot().revision
        browser_binding = server._browser_sessions[
            server._browser_token_digest(token)
        ]
        server.interaction_projection_broker.issue(
            browser_binding.interaction_projection_handle,
            server.universal_store.snapshot(),
            server.universal_registry.interaction_protocol,
            tuple(
                item["control"]
                for item in projection["interaction_projection"]["bindings"]
            ),
            tuple(
                item["interaction"]
                for item in projection["interaction_projection"]["bindings"]
            ),
            rule_protocol=server.universal_registry.rule_protocol,
            transaction_protocol=server.universal_registry.transaction_protocol,
            require_released=False,
            lifetime_seconds=60.0,
            now=time.time() - 61.0,
        )
        status, rejected = _json(
            server.url,
            "/api/universal/interaction",
            {
                **_interaction_request(projection, relations),
                "revision": projection["interaction_projection"]["revision"],
                "projection_mode": "interaction-delta-v1",
            },
            token=token,
        )
        assert status == 400
        assert rejected == {
            "ok": False,
            "error": "projection lease expired",
            "code": "projection_lease_expired",
            "retryable": True,
        }
        assert server.universal_store.snapshot().revision == before
    finally:
        server.close()


def test_interaction_receipt_commits_before_fresh_projection_is_requested():
    server = ApplicationServer().start()
    try:
        token = server.browser_session_token
        status, projection = _json(
            server.url, "/api/universal/canvas", token=token
        )
        assert status == 200
        relations = server.universal_registry.properties_panel_roots["relations"]
        request = _interaction_request(
            projection, relations, projection_mode="receipt-v1"
        )

        status, receipt = _json(
            server.url,
            "/api/universal/interaction",
            request,
            token=token,
        )

        assert status == 200
        assert receipt["projection_mode"] == "receipt-v1"
        assert receipt["base_revision"] == projection["revision"]
        assert receipt["committed_revision"] == server.universal_store.revision
        assert receipt["touched"] <= receipt["committed_revision"]
        assert "nodes" not in receipt
        assert "interaction_projection" not in receipt

        status, refreshed = _json(
            server.url, "/api/universal/canvas", token=token
        )
        assert status == 200
        assert refreshed["revision"] >= receipt["committed_revision"]
        assert refreshed["inspector"]["presentation"]["active"] == relations
    finally:
        server.close()


def test_http_placement_reuses_the_exact_leased_scope(monkeypatch):
    server = ApplicationServer().start()
    try:
        token = server.browser_session_token
        status, projection = _json(
            server.url, "/api/universal/canvas", token=token
        )
        assert status == 200
        definition = next(
            item["id"] for item in projection["catalog"]
            if item["name"] == "Ordered List"
        )
        request = _placement_interaction_request(
            projection, definition, 420, 180
        )
        request["projection_mode"] = "receipt-v1"

        def reject_scope_reprojection(*_args, **_kwargs):
            raise AssertionError(
                "leased placement must not rebuild the canvas scope"
            )

        monkeypatch.setattr(
            universal_application_module,
            "_read_view_scope_trail",
            reject_scope_reprojection,
        )
        status, receipt = _json(
            server.url,
            "/api/universal/interaction",
            request,
            token=token,
        )

        assert status == 200
        assert receipt["projection_mode"] == "receipt-v1"
        assert receipt["created_root"] in server.universal_store.snapshot().cells
        assert receipt["base_revision"] == projection["revision"]
        assert receipt["committed_revision"] == server.universal_store.revision
    finally:
        server.close()


def test_secured_http_permission_request_executes_only_allowlisted_adapter():
    key = _HttpFakeHardwareKey()
    server = ApplicationServer(device_key_factory=lambda: key).start()
    try:
        token = server.browser_session_token
        status, canvas = _json(
            server.url, "/api/universal/canvas", token=token
        )
        assert status == 200
        definition = next(
            item["id"] for item in canvas["catalog"]
            if item["name"] == "Permission Request"
        )
        status, created = _json(
            server.url,
            "/api/universal/interaction",
            _placement_interaction_request(
                canvas, definition, 420, 180
            ),
            token=token,
        )
        assert status == 200
        root = created["created_root"]
        values = {
            "requester": server.universal_registry.authorization.subject_root,
            "action": "device-key.enroll",
            "object": "device:this-machine",
            "parameters": '{"algorithm":"ES256","provider":"platform"}',
            "reason": "HTTP device-custody court",
            "expires-at": "2100-01-01T00:00:00Z",
        }
        configured = created
        for name, value in values.items():
            interface = next(
                item for item in configured["selected_interfaces"]
                if item["name"] == name
            )
            interaction = next(
                item
                for item in configured["interaction_projection"]["bindings"]
                if item["control"] == interface["control"]
            )
            status, configured = _json(
                server.url,
                "/api/universal/interaction",
                {
                    "interaction": interaction["interaction"],
                    "control": interaction["control"],
                    "event": interaction["event"],
                    "event_facts": [{
                        "input": interface["event_fact_input"],
                        "value": value,
                    }],
                    "revision": configured["interaction_projection"][
                        "revision"
                    ],
                    "projection_mode": "interaction-delta-v1",
                },
                token=token,
            )
            assert status == 200
        before = server.universal_store.revision
        status, retired = _json(
            server.url,
            "/api/universal/interface-value",
            {"root": root, "interface": "forged", "value": "bypass"},
            token=token,
        )
        assert status == 404
        assert retired["error"] == "not found"
        assert server.universal_store.revision == before
        pending = configured["selected_assembly"]
        approve = next(
            item for item in pending["operational"]["admitted_transitions"]
            if item["event_label"] == "approve"
        )
        status, approved = _json(
            server.url,
            "/api/universal/transition",
            {
                "root": root,
                "event": approve["event"],
                "expected": pending["operational"]["current_state"],
            },
            token=token,
        )
        assert status == 200
        assert approved["selected_assembly"]["operational"][
            "current_state_label"
        ] == "APPROVED"
        status, executed = _json(
            server.url,
            "/api/universal/execute-adapter",
            {"root": root},
            token=token,
        )
        assert status == 200
        assert key.closed is True
        assert executed["created_root"].startswith("device-custody:sha256:")
        assert executed["evidence_root"].startswith("adapter-receipt:")
        assert executed["selected_assembly"]["operational"][
            "current_state_label"
        ] == "SUCCEEDED"
    finally:
        server.close()


def test_http_collection_item_edit_requires_its_graph_interaction_lease():
    server = ApplicationServer().start()
    try:
        token = server.browser_session_token
        status, canvas = _json(
            server.url, "/api/universal/canvas", token=token
        )
        assert status == 200
        definition = next(
            item["id"] for item in canvas["catalog"]
            if item["name"] == "Ordered List"
        )
        status, created = _json(
            server.url,
            "/api/universal/interaction",
            _placement_interaction_request(canvas, definition, 420, 180),
            token=token,
        )
        assert status == 200
        root = created["created_root"]
        interface = created["selected_interfaces"][0]
        assert interface["mode"] == "collection"
        append_binding = next(
            entry
            for entry in created["interaction_projection"]["bindings"]
            if entry["control"] == interface["append_control"]
        )
        status, appended = _json(
            server.url,
            "/api/universal/interaction",
            {
                "interaction": append_binding["interaction"],
                "control": append_binding["control"],
                "event": append_binding["event"],
                "event_facts": [{
                    "input": interface["append_event_fact_input"],
                    "value": "Alpha",
                }],
                "revision": created["interaction_projection"]["revision"],
                "projection_mode": "topology-delta-v1",
            },
            token=token,
        )
        assert status == 200, appended
        item = appended["selected_interfaces"][0]["items"][0]
        binding = next(
            entry
            for entry in appended["interaction_projection"]["bindings"]
            if entry["control"] == item["control"]
        )
        status, edited = _json(
            server.url,
            "/api/universal/interaction",
            {
                "interaction": binding["interaction"],
                "control": binding["control"],
                "event": binding["event"],
                "event_facts": [{
                    "input": item["event_fact_input"],
                    "value": "Alpha updated",
                }],
                "revision": appended["interaction_projection"]["revision"],
                "projection_mode": "interaction-delta-v1",
            },
            token=token,
        )
        assert status == 200
        assert edited["selected_interfaces"][0]["items"][0]["value"] == (
            "Alpha updated"
        )

        before = server.universal_store.revision
        status, rejected = _json(
            server.url,
            "/api/universal/interface",
            {
                "root": root,
                "interface": interface["id"],
                "action": "edit",
                "incidence": item["incidence"],
                "value": "direct bypass",
            },
            token=token,
        )
        assert status == 404
        assert rejected["error"] == "not found"
        assert server.universal_store.revision == before
    finally:
        server.close()


def test_http_collection_structure_uses_graph_relation_member_operations():
    server = ApplicationServer().start()
    try:
        token = server.browser_session_token
        status, projection = _json(
            server.url, "/api/universal/canvas", token=token
        )
        assert status == 200
        definition = next(
            item["id"] for item in projection["catalog"]
            if item["name"] == "Ordered List"
        )
        status, projection = _json(
            server.url,
            "/api/universal/interaction",
            _placement_interaction_request(projection, definition, 420, 180),
            token=token,
        )
        assert status == 200
        root = projection["created_root"]

        def execute(control, facts=None):
            binding = next(
                item
                for item in projection["interaction_projection"]["bindings"]
                if item["control"] == control
            )
            request = {
                "interaction": binding["interaction"],
                "control": binding["control"],
                "event": binding["event"],
                "revision": projection["interaction_projection"]["revision"],
                "projection_mode": "topology-delta-v1",
            }
            if facts is not None:
                request["event_facts"] = facts
            return _json(
                server.url,
                "/api/universal/interaction",
                request,
                token=token,
            )

        interface = projection["selected_interfaces"][0]
        assert interface["mode"] == "collection"
        for value in ("Alpha", "Beta"):
            status, projection = execute(
                interface["append_control"],
                [{
                    "input": interface["append_event_fact_input"],
                    "value": value,
                }],
            )
            assert status == 200
            interface = projection["selected_interfaces"][0]
        assert [item["value"] for item in interface["items"]] == [
            "Alpha", "Beta"
        ]

        status, projection = execute(interface["items"][1]["up_control"])
        assert status == 200
        interface = projection["selected_interfaces"][0]
        assert [item["value"] for item in interface["items"]] == [
            "Beta", "Alpha"
        ]

        status, projection = execute(interface["items"][0]["down_control"])
        assert status == 200
        interface = projection["selected_interfaces"][0]
        assert [item["value"] for item in interface["items"]] == [
            "Alpha", "Beta"
        ]

        status, projection = execute(interface["items"][0]["remove_control"])
        assert status == 200
        interface = projection["selected_interfaces"][0]
        assert [item["value"] for item in interface["items"]] == ["Beta"]

        before = server.universal_store.revision
        for payload in (
            {
                "root": root,
                "interface": interface["id"],
                "action": "append",
                "value": "direct append",
            },
            {
                "root": root,
                "interface": interface["id"],
                "action": "remove",
                "incidence": interface["items"][0]["incidence"],
            },
            {
                "root": root,
                "interface": interface["id"],
                "action": "reorder",
                "order": [interface["items"][0]["incidence"]],
            },
        ):
            status, rejected = _json(
                server.url,
                "/api/universal/interface",
                payload,
                token=token,
            )
            assert status == 404
            assert rejected["error"] == "not found"
            assert server.universal_store.revision == before
    finally:
        server.close()


def test_http_relation_composer_rejects_malformed_bindings_without_a_commit():
    server = ApplicationServer().start()
    try:
        token = server.browser_session_token
        status, canvas = _json(
            server.url, "/api/universal/canvas", token=token
        )
        assert status == 200
        definition = next(
            item for item in canvas["catalog"]
            if item["name"] == "Model Descriptor"
        )
        assert definition["composition_contract"]
        before = server.universal_store.revision
        status, rejected = _json(
            server.url,
            "/api/universal/instantiate",
            {
                "definition": definition["id"],
                "x": 420,
                "y": 180,
                "bindings": [{"role": "missing-participant"}],
            },
            token=token,
        )
        assert status == 400
        assert "binding payload" in rejected["error"]
        assert server.universal_store.revision == before
    finally:
        server.close()


def test_http_primitive_drop_creates_and_edits_one_governed_wip_cell():
    server = ApplicationServer().start()
    try:
        token = server.browser_session_token
        status, canvas = _json(
            server.url, "/api/universal/canvas", token=token
        )
        assert status == 200
        floor_lens = next(
            lens for lens in canvas["inspector"]["lenses"]
            if lens["name"] == "floor"
        )
        status, _lens_delta = _json(
            server.url,
            "/api/universal/interaction",
            _interaction_request(canvas, floor_lens["id"]),
            token=token,
        )
        assert status == 200
        status, floor = _json(
            server.url, "/api/universal/canvas", token=token
        )
        assert status == 200
        primitive_root = floor["primitive"]["id"]
        assert floor["primitive"]["visible"] is True
        before = server.universal_store.revision
        status, created = _json(
            server.url,
            "/api/universal/interaction",
            _placement_interaction_request(floor, primitive_root, 420, 180),
            token=token,
        )
        assert status == 200, created
        assert created["touched"] == before + 1
        assert created["revision"] >= created["touched"]
        root_id = created["created_root"]
        assert created["selected"] == root_id
        assert created["selected_title"] == floor["primitive"]["label"]
        assert created["physical"]["atom"] == ""
        value = next(
            row for row in created["properties"]
            if row["label"] == "value"
        )
        assert value["value_root"] == root_id
        value_binding = next(
            item for item in created["interaction_projection"]["bindings"]
            if item["control"] == value["control"]
        )
        status, edited = _json(
            server.url,
            "/api/universal/interaction",
            {
                "interaction": value_binding["interaction"],
                "control": value_binding["control"],
                "event": value_binding["event"],
                "event_facts": [{
                    "input": value["event_fact_input"],
                    "value": "48",
                }],
                "revision": created["interaction_projection"]["revision"],
                "projection_mode": "interaction-delta-v1",
            },
            token=token,
        )
        assert status == 200
        assert edited["physical"]["identity"] == root_id
        assert edited["physical"]["atom"] == "48"

        bypass_revision = server.universal_store.revision
        status, rejected = _json(
            server.url,
            "/api/universal/instantiate",
            {
                "primitive": True,
                "x": 600,
                "y": 240,
                "title": "Browser-owned title",
                "atom": "Browser-owned atom",
            },
            token=token,
        )
        assert status == 400
        assert "Interaction lease" in rejected["error"]
        assert server.universal_store.revision == bypass_revision
    finally:
        server.close()


def test_http_add_parameter_creates_one_real_property_relation():
    server = ApplicationServer().start()
    try:
        token = server.browser_session_token
        created = _create_http_primitive(server, token, x=420, y=180)
        owner_root = created["created_root"]
        assert created["authoring"]["add_property"] is True
        assert created["authoring"]["add_interface"] is True
        assert created["authoring"]["owner"] == owner_root
        form = created["authoring"]["property_form"]
        valid_payload = _form_interaction_request(created, form, {
            "label": "Acoustic rating",
            "value": "Rw 50",
        })
        for forged, message in (
            ({**valid_payload, "owner": owner_root}, "undeclared facts"),
            (
                {**valid_payload, "control": "forged:control"},
                "admitted",
            ),
            (
                {
                    **valid_payload,
                    "event_facts": [
                        *valid_payload["event_facts"],
                        {"input": "forged:input", "value": "forged"},
                    ],
                },
                "event facts",
            ),
        ):
            before_rejection = server.universal_store.revision
            status, rejected = _json(
                server.url,
                "/api/universal/interaction",
                forged,
                token=token,
            )
            assert status == 400
            assert message in rejected["error"]
            assert server.universal_store.revision == before_rejection
        before = created["revision"]
        status, authored = _json(
            server.url,
            "/api/universal/interaction",
            valid_payload,
            token=token,
        )
        assert status == 200
        assert authored["touched"] == before + 1
        assert authored["revision"] >= authored["touched"]
        relation_root = authored["created_root"]
        row = next(
            item for item in authored["properties"]
            if item["relation"] == relation_root
        )
        assert row["label"] == "Acoustic rating"
        assert row["value"] == "Rw 50"
        assert row["editable"] is True

        before_rejection = server.universal_store.revision
        duplicate_payload = _form_interaction_request(authored, form, {
            "label": "acoustic rating",
            "value": "Rw 55",
        })
        status, rejected = _json(
            server.url,
            "/api/universal/interaction",
            duplicate_payload,
            token=token,
        )
        assert status == 400
        assert "already exists" in rejected["error"]
        assert server.universal_store.revision == before_rejection
    finally:
        server.close()


def test_http_personal_presentation_is_versioned_isolated_and_fail_closed():
    server = ApplicationServer().start()
    try:
        token = server.browser_session_token
        target = server.universal_registry.visible_roots[0]
        status, selected = _json(
            server.url,
            "/api/universal/select",
            {"roots": [target], "focus": target},
            token=token,
        )
        assert status == 200
        color = next(
            row for row in selected["properties"] if row["label"] == "color"
        )
        base_color = color["value"]
        base_cell = server.universal_store.read(color["value_root"])

        def appearance_payload(projection, row, *, reset=False, value=None):
            control = (
                row["presentation_reset_control"]
                if reset else row["presentation_control"]
            )
            binding = next(
                item for item in projection["interaction_projection"]["bindings"]
                if item["control"] == control
            )
            payload = {
                "interaction": binding["interaction"],
                "control": binding["control"],
                "event": binding["event"],
                "revision": projection["interaction_projection"]["revision"],
                "projection_mode": "interaction-delta-v1",
            }
            if not reset:
                payload["event_facts"] = [{
                    "input": row["presentation_event_fact_input"],
                    "value": value,
                }]
            return payload

        rejected_payload = appearance_payload(
            selected, color, value="red"
        )
        before = server.universal_store.revision
        status, rejected = _json(
            server.url,
            "/api/universal/interaction",
            rejected_payload,
            token=token,
        )
        assert status == 400
        assert "requires #RRGGBB" in rejected["error"]
        assert server.universal_store.revision == before

        status, refreshed = _json(
            server.url, "/api/universal/canvas", token=token
        )
        assert status == 200
        color = next(
            row for row in refreshed["properties"] if row["label"] == "color"
        )
        preview_payload = appearance_payload(
            refreshed, color, value="#2f80ed"
        )
        before = server.universal_store.revision
        status, preview = _json(
            server.url,
            "/api/universal/interaction",
            preview_payload,
            token=token,
        )
        assert status == 200
        assert server.universal_store.revision > before
        assert preview["revision"] == server.universal_store.revision
        projected = next(
            row for row in preview["properties"] if row["label"] == "color"
        )
        revision = projected["presentation_revision"]
        assert projected["value"] == "#2f80ed"
        assert projected["presentation_source_mode"] == "personal-wip"
        assert projected["presentation_revision"] == revision
        assert projected["presentation_reset"] is True
        assert server.universal_store.read(color["value_root"]) == base_cell

        status, rejected = _json(
            server.url,
            "/api/universal/property",
            {"relation": color["relation"], "value": "#1177aa"},
            token=token,
        )
        assert status == 404
        assert rejected["error"] == "not found"
        assert server.universal_store.revision == preview["revision"]

        for retired_path in (
            "/api/universal/presentation-preview",
            "/api/universal/presentation-reset",
        ):
            status, retired = _json(
                server.url, retired_path, {}, token=token
            )
            assert status == 404
            assert retired["error"] == "not found"

        reset_payload = appearance_payload(preview, projected, reset=True)
        status, reset = _json(
            server.url,
            "/api/universal/interaction",
            reset_payload,
            token=token,
        )
        assert status == 200
        reset_color = next(
            row for row in reset["properties"] if row["label"] == "color"
        )
        assert reset_color["value"] == base_color
        assert reset_color["presentation_source_mode"] == "inherited"
        assert reset_color["presentation_reset"] is False
        assert len(reset_color["presentation_history"]) == 2
        assert server.universal_store.read(color["value_root"]) == base_cell
        assert reset_color["presentation_reset_control"] is None
        assert all(
            binding["control"] != reset_payload["control"]
            for binding in reset["interaction_projection"]["bindings"]
        )
    finally:
        server.close()


def test_http_personal_theme_preview_and_restore_use_graph_interactions():
    server = ApplicationServer().start()
    try:
        token = server.browser_session_token
        status, canvas = _json(
            server.url, "/api/universal/canvas", token=token
        )
        assert status == 200
        accent = next(
            field for field in canvas["configuration"]["theme_fields"]
            if field["key"] == "accent"
        )
        original = accent["value"]
        preview_request = _interaction_request(canvas, accent["control"])
        preview_request["event_facts"] = [{
            "input": accent["event_fact_input"],
            "value": "#1177aa",
        }]
        assert set(preview_request) == {
            "interaction",
            "control",
            "event",
            "revision",
            "projection_mode",
            "event_facts",
        }
        status, preview = _json(
            server.url,
            "/api/universal/interaction",
            preview_request,
            token=token,
        )
        assert status == 200
        assert preview["configuration_state"]["theme"]["accent"] == "#1177aa"
        historical = next(
            revision for revision in preview["configuration_state"]["history"]
            if revision["current"] is False
        )
        assert isinstance(historical["restore_control"], str)
        restore_request = _interaction_request(
            preview, historical["restore_control"]
        )
        status, restored = _json(
            server.url,
            "/api/universal/interaction",
            restore_request,
            token=token,
        )
        assert status == 200
        assert restored["configuration_state"]["theme"]["accent"] == original
        assert len(restored["configuration_state"]["history"]) == 3
        for retired_path in (
            "/api/universal/theme-preview",
            "/api/universal/theme-restore",
        ):
            status, retired = _json(
                server.url, retired_path, {}, token=token
            )
            assert status == 404
            assert retired["error"] == "not found"
    finally:
        server.close()


def test_theme_interaction_survives_durable_store_restart(tmp_path):
    state_path = tmp_path / "theme-interaction.sqlite3"
    provider = MemorySigningKeyProvider(
        "archhub.local.relationship-authority", b"t" * 32
    )
    provider.add_key("archhub.local.court-attestation", b"u" * 32)
    store, registry = build_universal_application(
        resolve_map_path(), CellStore(state_path), key_provider=provider
    )
    server = ApplicationServer(
        universal_store=store,
        universal_registry=registry,
    ).start()
    try:
        token = server.browser_session_token
        status, canvas = _json(
            server.url, "/api/universal/canvas", token=token
        )
        assert status == 200
        accent = next(
            field for field in canvas["configuration"]["theme_fields"]
            if field["key"] == "accent"
        )
        request = _interaction_request(canvas, accent["control"])
        request["event_facts"] = [{
            "input": accent["event_fact_input"],
            "value": "#215b73",
        }]
        status, changed = _json(
            server.url,
            "/api/universal/interaction",
            request,
            token=token,
        )
        assert status == 200
        expected_revision = changed["configuration_state"][
            "preview_revision"
        ]
    finally:
        server.close()

    reopened = CellStore(state_path)
    reopened, restored = universal_application_module.restore_universal_application(
        resolve_map_path(), reopened, key_provider=provider
    )
    projection = universal_application_module.project_universal_canvas(
        reopened, restored
    )
    assert projection["configuration"]["theme"]["accent"] == "#215b73"
    assert projection["configuration"]["preview_revision"] == expected_revision
    assert any(
        revision["revision"] == expected_revision
        and revision["current"] is True
        for revision in projection["configuration"]["history"]
    )
    reopened.close()


def test_http_add_interface_registers_one_real_typed_socket():
    server = ApplicationServer().start()
    try:
        token = server.browser_session_token
        created = _create_http_primitive(server, token, x=420, y=180)
        owner_root = created["created_root"]
        presentation = next(
            item for item in created["authoring"]["interface_presentations"]
            if item["side"] == "source"
        )
        contract = created["authoring"]["interface_contracts"][0]
        form = created["authoring"]["interface_form"]
        property_form = created["authoring"]["property_form"]
        before_cross_form = server.universal_store.revision
        property_binding = _form_interaction_request(
            created,
            property_form,
            {"label": "Wrong form", "value": ""},
        )
        property_binding["event_facts"] = [
            {"input": form["inputs"]["name"], "value": "Wrong form"},
            {
                "input": form["inputs"]["presentation"],
                "value": presentation["id"],
            },
            {"input": form["inputs"]["contract"], "value": contract["id"]},
        ]
        status, rejected = _json(
            server.url,
            "/api/universal/interaction",
            property_binding,
            token=token,
        )
        assert status == 400
        assert "event facts" in rejected["error"]
        assert server.universal_store.revision == before_cross_form
        before = created["revision"]

        status, authored = _json(
            server.url,
            "/api/universal/interaction",
            _form_interaction_request(created, form, {
                "name": "Acoustic source",
                "presentation": presentation["id"],
                "contract": contract["id"],
            }),
            token=token,
        )
        assert status == 200
        assert authored["touched"] == before + 1
        assert authored["revision"] >= authored["touched"]
        interface_root = authored["created_root"]
        socket = next(
            item for item in authored["selected_interfaces"]
            if item["id"] == interface_root
        )
        assert socket["owner"] == owner_root
        assert socket["name"] == "Acoustic source"
        assert socket["side"] == "source"
        assert socket["contract_root"] == contract["id"]

        before_rejection = server.universal_store.revision
        status, rejected = _json(
            server.url,
            "/api/universal/interaction",
            _form_interaction_request(authored, form, {
                "name": "acoustic source",
                "presentation": presentation["id"],
                "contract": contract["id"],
            }),
            token=token,
        )
        assert status == 400
        assert "already exists" in rejected["error"]
        assert server.universal_store.revision == before_rejection
    finally:
        server.close()


def test_http_relation_role_rewire_preserves_relation_and_incidence_identity():
    server = ApplicationServer().start()
    try:
        token = server.browser_session_token

        def primitive(x):
            created = _create_http_primitive(
                server, token, x=x, y=180
            )
            return created["created_root"]

        first_root = primitive(420)
        second_root = primitive(700)
        status, canvas = _json(
            server.url, "/api/universal/canvas", token=token
        )
        assert status == 200
        definition = next(
            item for item in canvas["catalog"]
            if item["name"] == "Model Descriptor"
        )
        bindings = [
            {
                "role": role["role"],
                "participant": (
                    role["fixed"]["id"] if role["fixed"] else first_root
                ),
            }
            for role in definition["composition_contract"]["roles"]
            for _ in range(role["minimum"])
        ]
        status, created = _json(
            server.url,
            "/api/universal/instantiate",
            {
                "definition": definition["id"],
                "x": 560,
                "y": 320,
                "bindings": bindings,
            },
            token=token,
        )
        assert status == 200, created
        wrapper_root = created["created_root"]
        interface = next(
            item for item in created["selected_assembly"]["interfaces"]
            if (
                item["mode"] == "relation-role"
                and item["fixed_participant"] is None
                and item["items"]
            )
        )
        relation_root = interface["target"]
        incidence_root = interface["items"][0]["incidence"]
        projected_interface = next(
            item for item in created["selected_interfaces"]
            if item["id"] == interface["id"]
        )
        participant_index = next(
            index for index, choice in enumerate(projected_interface["choices"])
            if choice["id"] == second_root
        )
        interaction = next(
            item
            for item in created["interaction_projection"]["bindings"]
            if item["control"]
            == projected_interface["items"][0]["replace_control"]
        )
        before = created["revision"]
        status, edited_delta = _json(
            server.url,
            "/api/universal/interaction",
            {
                "interaction": interaction["interaction"],
                "control": interaction["control"],
                "event": interaction["event"],
                "event_facts": [{
                    "input": projected_interface["items"][0][
                        "replace_event_fact_input"
                    ],
                    "value": participant_index,
                }],
                "revision": created["interaction_projection"]["revision"],
                "projection_mode": "topology-delta-v1",
            },
            token=token,
        )
        assert status == 200
        assert edited_delta["touched"] == before + 1
        assert edited_delta["revision"] >= edited_delta["touched"]
        edited = _merge_canvas_delta(created, edited_delta)
        changed = next(
            item for item in edited["selected_assembly"]["interfaces"]
            if item["id"] == interface["id"]
        )
        assert changed["target"] == relation_root
        assert changed["items"][0]["incidence"] == incidence_root
        assert changed["items"][0]["participant"] == second_root
        leg = next(
            wire for wire in edited["wires"]
            if wire["id"] == relation_root
            and wire["segment"] == incidence_root
        )
        assert leg["source"] == second_root
        assert leg["source_interface"] == incidence_root
        assert leg["target"] == wrapper_root
        assert leg["target_interface"] == interface["id"]

        optional = next(
            item for item in edited["selected_interfaces"]
            if item["mode"] == "relation-role"
            and item["editable"] is True
            and not item["items"]
            and item["choices"]
            and item["maximum"] > 0
        )
        append = next(
            item
            for item in edited["interaction_projection"]["bindings"]
            if item["control"] == optional["append_control"]
        )
        append_index = next(
            index for index, choice in enumerate(optional["choices"])
            if choice["id"] == second_root
        )
        status, appended_delta = _json(
            server.url,
            "/api/universal/interaction",
            {
                "interaction": append["interaction"],
                "control": append["control"],
                "event": append["event"],
                "event_facts": [{
                    "input": optional["append_event_fact_input"],
                    "value": append_index,
                }],
                "revision": edited["interaction_projection"]["revision"],
                "projection_mode": "topology-delta-v1",
            },
            token=token,
        )
        assert status == 200, appended_delta
        appended = _merge_canvas_delta(edited, appended_delta)
        optional = next(
            item for item in appended["selected_interfaces"]
            if item["id"] == optional["id"]
        )
        assert optional["items"][0]["participant"] == second_root
        remove = next(
            item
            for item in appended["interaction_projection"]["bindings"]
            if item["control"] == optional["items"][0]["remove_control"]
        )
        status, removed_delta = _json(
            server.url,
            "/api/universal/interaction",
            {
                "interaction": remove["interaction"],
                "control": remove["control"],
                "event": remove["event"],
                "revision": appended["interaction_projection"]["revision"],
                "projection_mode": "topology-delta-v1",
            },
            token=token,
        )
        assert status == 200, removed_delta
        removed = _merge_canvas_delta(appended, removed_delta)
        assert not next(
            item for item in removed["selected_interfaces"]
            if item["id"] == optional["id"]
        )["items"]

        before_rejected = server.universal_store.revision
        status, rejected = _json(
            server.url,
            "/api/universal/interface",
            {
                "root": wrapper_root,
                "interface": interface["id"],
                "action": "edit",
                "incidence": incidence_root,
                "value": first_root,
            },
            token=token,
        )
        assert status == 404
        assert rejected["error"] == "not found"
        assert server.universal_store.revision == before_rejected
    finally:
        server.close()


def test_browser_session_projects_and_authorizes_the_exact_graph_user():
    store, registry = build_universal_application(resolve_map_path())
    asset_root, _ = instantiate_universal_definition(
        store,
        registry,
        registry.standard_library.definition_roots[2],
        x=420,
        y=180,
    )
    promote_universal_resource_lifecycle(
        store, registry, asset_root, "shared"
    )
    member_root = "test:http:member-browser-session"
    store.commit(store.revision, create=(
        Cell(member_root, NULL_CELL_ID, NULL_CELL_ID, b"Member browser"),
    ))
    provision_universal_view_session(
        store, registry, member_root, visible_roots=(asset_root,)
    )
    authority = registry.authorization
    member_context = authority.broker.mint_authenticated_context(
        member_root,
        tenant_root=authority.tenant_root,
        assurance_root=authority.assurance_root,
        lifetime_seconds=120,
    )
    server = ApplicationServer(
        universal_store=store, universal_registry=registry
    ).start()
    try:
        token, csrf = server.issue_browser_session(member_context)
        status, member_canvas = _json(
            server.url, "/api/universal/canvas", token=token
        )
        assert status == 200
        assert member_canvas["authorization"]["subject"] == member_root
        member_binding = server._resolve_browser_session(token)
        assert [
            session["root"] for session in
            member_canvas["authorization"]["browser_sessions"]
        ] == [member_binding.session_root]
        assert token not in json.dumps(member_canvas)
        status, selected_session = _json(
            server.url,
            "/api/universal/gesture",
            {
                "roots": [],
                "focus": member_binding.session_root,
                "projection": True,
            },
            token=token,
        )
        assert status == 200
        assert selected_session["selected"] == member_binding.session_root
        assert {
            connection["role"]
            for connection in selected_session["connections"]
        } >= {
            "subject", "view", "tenant", "assurance", "state",
            "issued-at", "expires-at",
        }
        connection_values = {
            connection["role"]: connection["participant_label"]
            for connection in selected_session["connections"]
        }
        assert connection_values["tenant"] == "ArchHub founder workspace"
        assert connection_values["issued-at"].endswith("Z")
        assert connection_values["expires-at"].endswith("Z")
        assert connection_values["token-digest"] \
            == "Protected credential digest"
        assert connection_values["csrf-digest"] \
            == "Protected credential digest"
        assert [node["id"] for node in member_canvas["nodes"]] == [asset_root]
        assert member_canvas["selected_assembly"]["lifecycle"][
            "release_scoped"
        ] is True

        with urlopen(Request(
            server.url + "/",
            headers={"X-ArchHub-Session": token},
        ), timeout=30) as response:
            page = response.read().decode("utf-8")
            cookie_header = response.headers.get("Set-Cookie")
        assert token not in page
        assert csrf in page
        assert "ArchHub-Session=%s" % token in cookie_header

        status, denied = _json(
            server.url,
            "/api/universal/instantiate",
            {
                "definition": registry.standard_library.definition_roots[0],
                "x": 600,
                "y": 220,
                "projection": False,
            },
            token=token,
        )
        assert status == 400
        assert "graph Interaction lease" in denied["error"]

        status, denied_export = _json(
            server.url,
            "/api/export?node_id=app:archhub",
            token=token,
        )
        assert status == 403
        assert "legacy export" in denied_export["error"]

        status, founder_canvas = _json(
            server.url,
            "/api/universal/canvas",
            token=server.browser_session_token,
        )
        assert status == 200
        assert founder_canvas["authorization"]["subject"] \
            == authority.subject_root
        assert len(founder_canvas["nodes"]) > len(member_canvas["nodes"])
    finally:
        server.close()


def test_running_http_session_is_denied_immediately_by_graph_revocation():
    server = ApplicationServer().start()
    try:
        binding = server._resolve_browser_session(
            server.browser_session_token
        )
        session = read_browser_session(
            server.universal_store.snapshot(),
            server.universal_registry.browser_session_protocol,
            binding.session_root,
        )
        assert session.subject_root == (
            server.universal_registry.authorization.subject_root
        )
        assert session.view_root == (
            server.universal_registry.authorization.session.root_id
        )
        assert session.state_root == (
            server.universal_registry.browser_session_protocol.states["active"]
        )
        status, canvas = _json(
            server.url,
            "/api/universal/canvas",
            token=server.browser_session_token,
        )
        assert status == 200
        assert any(
            item["root"] == binding.session_root
            and item["state"] == "active"
            for item in canvas["authorization"]["browser_sessions"]
        )

        revoke_browser_session(
            server.universal_store,
            server.universal_registry.browser_session_protocol,
            binding.session_root,
            reason="Founder revoked this browser",
        )
        status, denied = _json(
            server.url,
            "/api/universal/canvas",
            token=server.browser_session_token,
        )
        assert status == 403
        assert "revoked" in denied["error"]
    finally:
        server.close()


def test_server_shutdown_persists_browser_session_revocation(tmp_path):
    state_path = tmp_path / "browser-session-close.sqlite3"
    provider = MemorySigningKeyProvider(
        "archhub.local.relationship-authority", b"a" * 32
    )
    provider.add_key("archhub.local.court-attestation", b"b" * 32)
    store, registry = build_universal_application(
        resolve_map_path(), CellStore(state_path), key_provider=provider
    )
    server = ApplicationServer(
        universal_store=store,
        universal_registry=registry,
    ).start()
    session_root = server.browser_session_root
    server.close()

    reopened = CellStore(state_path)
    protocol = project_browser_session_protocol(
        reopened.snapshot(), prefix="app:browser-session-protocol"
    )
    session = read_browser_session(
        reopened.snapshot(), protocol, session_root
    )
    assert session.state_root == protocol.states["revoked"]
    assert reopened.read(session.revocation_reason_roots[0]).atom \
        == b"Application server closed"
    reopened.close()


def test_restart_revokes_orphaned_process_session_before_issuing_new_one(
    tmp_path,
):
    state_path = tmp_path / "browser-session-recovery.sqlite3"
    checkpoint_path = tmp_path / "session-checkpoint.json"
    authority_path = tmp_path / "session-checkpoint-authority.sqlite3"
    key_name = "ArchHub.Court.%s" % uuid.uuid4()
    provider = MemorySigningKeyProvider(
        "archhub.local.relationship-authority", b"c" * 32
    )
    provider.add_key("archhub.local.court-attestation", b"d" * 32)
    provider.add_key("archhub.local.universal-checkpoint", b"e" * 32)
    store, registry = build_universal_application(
        resolve_map_path(), CellStore(state_path), key_provider=provider
    )
    authority = registry.authorization
    orphan_root, _ = issue_browser_session_relation(
        store,
        registry.browser_session_protocol,
        subject_root=authority.subject_root,
        view_root=authority.session.root_id,
        tenant_root=authority.tenant_root,
        assurance_root=authority.assurance_root,
        token_digest=hashlib.sha256(b"lost-process-token").hexdigest(),
        csrf_digest=hashlib.sha256(b"lost-process-csrf").hexdigest(),
        lifetime_seconds=300,
    )
    try:
        checkpoint_authority = provision_windows_revision_checkpoint_authority(
            state_path,
            authority_path=authority_path,
            provider_id=SOFTWARE_PROVIDER_ID,
            key_name=key_name,
        )
        guard = RevisionCheckpointGuard(
            checkpoint_path,
            database_identity=str(state_path),
            key_provider=provider,
            signing_authority=checkpoint_authority,
        )
        guard.bind(store)
        guard.require_healthy()
        guard.close()
        store.close()
        checkpoint_authority.store.close()

        server = ApplicationServer(
            universal_state_path=state_path,
            universal_key_provider=provider,
            universal_checkpoint_path=checkpoint_path,
            universal_checkpoint_authority_path=authority_path,
            universal_checkpoint_key_name=key_name,
            universal_checkpoint_provider_id=SOFTWARE_PROVIDER_ID,
        ).start()
        try:
            orphan = read_browser_session(
                server.universal_store.snapshot(),
                server.universal_registry.browser_session_protocol,
                orphan_root,
            )
            assert orphan.state_root == (
                server.universal_registry.browser_session_protocol.states[
                    "revoked"
                ]
            )
            assert server.universal_store.read(
                orphan.revocation_reason_roots[0]
            ).atom == b"Owning application process ended before recovery"
            replacement = read_browser_session(
                server.universal_store.snapshot(),
                server.universal_registry.browser_session_protocol,
                server.browser_session_root,
            )
            assert replacement.state_root == (
                server.universal_registry.browser_session_protocol.states[
                    "active"
                ]
            )
            assert replacement.root_id != orphan_root
        finally:
            server.close()
    finally:
        delete_court_key(key_name)


def test_normal_server_is_catalogue_only_and_adapter_deny_by_default():
    universal_store, universal_registry = build_universal_application(
        resolve_map_path()
    )
    server = ApplicationServer(
        universal_store=universal_store,
        universal_registry=universal_registry,
    ).start()
    try:
        status, denied = _json(server.url, "/api/universal/canvas")
        assert status == 403
        assert "authenticated browser session" in denied["error"]

        token = server.browser_session_token
        status, denied = _json(server.url, "/api/edit", {}, token=token)
        assert status == 403
        assert "legacy mutation routes are disabled" in denied["error"]

        status, denied = _json(server.url, "/api/universal/cell", {
            "root": universal_registry.primitive_root,
            "atom": "unrestricted",
            "projection": False,
        }, token=token)
        assert status == 404
        assert denied["error"] == "not found"

        status, canvas = _json(
            server.url, "/api/universal/canvas", token=token
        )
        assert status == 200
        assert canvas["composer"]["admitted_adapters"] == 1
        assert canvas["composer"]["extension_mode"] == "proposal-only"
        assert canvas["authorization"]["native_identity"]["device_custody"][
            "active"
        ] == 0
        assert not any(
            root.startswith("adapter-permission:")
            for root in universal_store.snapshot().cells
        )

        accent = next(
            field for field in canvas["configuration"]["theme_fields"]
            if field["key"] == "accent"
        )
        preview_request = _interaction_request(
            canvas, accent["control"]
        )
        preview_request["event_facts"] = [{
            "input": accent["event_fact_input"],
            "value": "#1177aa",
        }]
        status, preview = _json(
            server.url,
            "/api/universal/interaction",
            preview_request,
            token=token,
        )
        assert status == 200
        assert preview["configuration_state"]["theme"]["accent"] == "#1177aa"
        status, retired = _json(
            server.url,
            "/api/universal/theme-preview",
            {"changes": {"accent": "#ffffff"}},
            token=token,
        )
        assert status == 404
        assert retired["error"] == "not found"
        status, shared = _json(server.url, "/api/universal/theme-share", {
            "revision": preview["configuration_state"]["preview_revision"],
            "projection": False,
        }, token=token)
        assert status == 200
        assert shared["created_root"].startswith("lifecycle:revision:")
        assert shared["evidence_root"].startswith("attestation:evidence:")
        status, canvas = _json(
            server.url, "/api/universal/canvas", token=token
        )
        shared_revision = next(
            revision for revision in canvas["configuration"]["history"]
            if revision["revision"] == shared["created_root"]
        )
        assert shared_revision["state"] == "SHARED"
        assert shared_revision["evidence"][0]["root"] \
            == shared["evidence_root"]

        project_group = "test:http:project-group"
        universal_store.commit(universal_store.revision, create=(
            Cell(project_group, NULL_CELL_ID, NULL_CELL_ID, b"Project group"),
        ))
        status, issued = _json(server.url, "/api/universal/authority-issue", {
            "source": universal_registry.authorization.subject_root,
            "target": project_group,
            "kind": "membership",
            "reason": "HTTP authority court",
            "projection": False,
        }, token=token)
        assert status == 200
        relationship_root = issued["created_root"]
        status, canvas = _json(
            server.url, "/api/universal/canvas", token=token
        )
        relationship = next(
            item for item in canvas["authorization"]["relationships"]
            if item["root"] == relationship_root
        )
        assert relationship["verified"] is True
        assert relationship["state"] == "active"

        status, revoked = _json(server.url, "/api/universal/authority-revoke", {
            "relationship": relationship_root,
            "reason": "HTTP authority court complete",
            "projection": True,
        }, token=token)
        assert status == 200
        relationship = next(
            item for item in revoked["authorization"]["relationships"]
            if item["root"] == relationship_root
        )
        assert relationship["verified"] is True
        assert relationship["state"] == "revoked"

        definition = revoked["catalog"][0]["id"]
        status, created = _json(
            server.url,
            "/api/universal/interaction",
            _placement_interaction_request(
                revoked,
                definition,
                420,
                240,
                viewport={"pan_x": -240, "pan_y": 80, "zoom": 0.82},
            ),
            token=token,
        )
        assert status == 200
        assert created["created_root"].startswith("assembly-instance:")

        status, placed_canvas = _json(
            server.url, "/api/universal/canvas", token=token
        )
        assert status == 200
        assert placed_canvas["viewport"] == {
            "pan_x": -240.0, "pan_y": 80.0, "zoom": 0.82,
        }

        versioned_definition = next(
            item["id"] for item in placed_canvas["catalog"]
            if item["name"] == "Versioned Asset"
        )
        status, versioned = _json(
            server.url,
            "/api/universal/interaction",
            _placement_interaction_request(
                placed_canvas, versioned_definition, 660, 240
            ),
            token=token,
        )
        assert status == 200
        status, versioned_canvas = _json(
            server.url, "/api/universal/canvas", token=token
        )
        assert status == 200
        lifecycle = versioned_canvas["selected_assembly"]["lifecycle"]
        wip_base = next(
            item for item in lifecycle["states"] if item["name"] == "WIP"
        )["revision"]
        status, edited = _json(
            server.url,
            "/api/universal/lifecycle-wip",
            {
                "root": versioned["created_root"],
                "interface": lifecycle["content_interface"],
                "base": wip_base,
                "value": "HTTP-authored immutable WIP",
                "projection": True,
            },
            token=token,
        )
        assert status == 200
        assert edited["created_root"].startswith("lifecycle:revision:")
        assert next(
            item for item in edited["selected_assembly"]["interfaces"]
            if item["id"] == lifecycle["content_interface"]
        )["value"] == "HTTP-authored immutable WIP"
        status, branched = _json(
            server.url,
            "/api/universal/lifecycle-wip",
            {
                "root": versioned["created_root"],
                "interface": lifecycle["content_interface"],
                "base": wip_base,
                "value": "Concurrent HTTP WIP",
                "projection": True,
            },
            token=token,
        )
        assert status == 200
        wip_heads = next(
            item for item in branched["selected_assembly"]["lifecycle"]["states"]
            if item["name"] == "WIP"
        )["heads"]
        assert len(wip_heads) == 2
        status, merged = _json(
            server.url,
            "/api/universal/lifecycle-merge",
            {
                "root": versioned["created_root"],
                "interface": lifecycle["content_interface"],
                "parents": [item["revision"] for item in wip_heads],
                "value": "Resolved HTTP WIP",
                "projection": True,
            },
            token=token,
        )
        assert status == 200
        assert merged["evidence_root"].startswith("attestation:evidence:")
        assert next(
            item for item in merged["selected_assembly"]["lifecycle"]["states"]
            if item["name"] == "WIP"
        )["head_count"] == 1
        status, promoted = _json(
            server.url,
            "/api/universal/resource-promote",
            {
                "root": versioned["created_root"],
                "target": "shared",
                "projection": True,
            },
            token=token,
        )
        assert status == 200
        assert promoted["created_root"].startswith("lifecycle:revision:")
        assert promoted["evidence_root"].startswith("attestation:evidence:")
        shared_state = next(
            item for item in promoted["selected_assembly"]["lifecycle"]["states"]
            if item["name"] == "SHARED"
        )
        assert shared_state["revision"] == promoted["created_root"]
        publish_gate = next(
            item
            for item in promoted["selected_assembly"]["lifecycle"][
                "transitions"
            ]
            if item["target_name"] == "published"
        )
        assert publish_gate["ready"] is True

        existing_wire = canvas["wires"][0]
        status, denied = _json(server.url, "/api/universal/connect", {
            "source": existing_wire["source"],
            "target": existing_wire["target"],
            "source_interface": existing_wire["source_interface"],
            "target_interface": existing_wire["target_interface"],
            "projection": False,
        }, token=token)
        assert status == 404
        assert denied["error"] == "not found"
    finally:
        server.close()


def test_browser_token_cannot_bypass_revoked_graph_authority():
    universal_store, universal_registry = build_universal_application(
        resolve_map_path()
    )
    server = ApplicationServer(
        universal_store=universal_store,
        universal_registry=universal_registry,
    ).start()
    try:
        token = server.browser_session_token
        status, canvas = _json(
            server.url, "/api/universal/canvas", token=token
        )
        assert status == 200
        assert canvas["ok"] is True

        authority = universal_registry.authorization
        handle = authority.relationship_broker.mint_from_trusted_administrator(
            authority.subject_root
        )
        revoke_authority_relationship(
            universal_store,
            authority.identity_protocol,
            authority.relationship_broker,
            handle,
            authority.founder_principal_membership_root,
            administrator_root=authority.subject_root,
            reason="court proves browser token is not permission",
        )

        status, denied = _json(
            server.url, "/api/universal/canvas", token=token
        )
        assert status == 403
        assert denied["error"] == "universal route authorization denied"
    finally:
        server.close()


def test_topology_interaction_connects_rewires_and_detaches_without_direct_ids():
    universal_store, universal_registry = build_universal_application(
        resolve_map_path()
    )
    server = ApplicationServer(
        universal_store=universal_store,
        universal_registry=universal_registry,
    ).start()
    try:
        token = server.browser_session_token
        status, canvas = _json(
            server.url, "/api/universal/canvas", token=token
        )
        assert status == 200
        source_port = next(
            port
            for node in canvas["nodes"]
            for port in node["ports"]
            if len(port.get("connect_choices") or ()) >= 2
        )
        before = universal_store.snapshot()
        before_revision = universal_store.revision
        connect_request = _event_fact_interaction_request(
            canvas,
            source_port["connect_control"],
            {"topology-candidate-index": 0},
            projection_mode="topology-delta-v1",
        )
        assert not {
            "source", "target", "source_interface", "target_interface",
            "relation", "incidence", "participant",
        } & set(connect_request)
        status, connected_delta = _json(
            server.url,
            "/api/universal/interaction",
            connect_request,
            token=token,
        )
        assert status == 200
        assert connected_delta["touched"] == before_revision + 1
        connected = _merge_canvas_delta(canvas, connected_delta)
        relation_root = connected["created_root"]
        wire = next(item for item in connected["wires"] if item["id"] == relation_root)
        rewire_side = next(
            side for side in ("target", "source")
            if any(
                choice["id"] != wire[side + "_interface"]
                for choice in wire[side + "_rewire_choices"]
            )
        )
        choices = wire[rewire_side + "_rewire_choices"]
        candidate_index = next(
            index for index, choice in enumerate(choices)
            if choice["id"] != wire[rewire_side + "_interface"]
        )
        rewire_request = _event_fact_interaction_request(
            connected,
            wire[rewire_side + "_rewire_control"],
            {"topology-candidate-index": candidate_index},
            projection_mode="topology-delta-v1",
        )
        assert not {"relation", "incidence", "participant"} & set(rewire_request)
        status, rewired_delta = _json(
            server.url,
            "/api/universal/interaction",
            rewire_request,
            token=token,
        )
        assert status == 200
        rewired = _merge_canvas_delta(connected, rewired_delta)
        rewired_wire = next(
            item for item in rewired["wires"] if item["id"] == relation_root
        )
        assert rewired_wire[rewire_side + "_interface"] == (
            choices[candidate_index]["id"]
        )
        disconnect_request = _interaction_request(
            rewired,
            rewired_wire["disconnect_control"],
            projection_mode="topology-delta-v1",
        )
        assert not {"relation", "incidence", "participant"} & set(
            disconnect_request
        )
        status, detached_delta = _json(
            server.url,
            "/api/universal/interaction",
            disconnect_request,
            token=token,
        )
        assert status == 200
        detached = _merge_canvas_delta(rewired, detached_delta)
        assert all(item["id"] != relation_root for item in detached["wires"])
        assert relation_root in universal_store.snapshot().cells
        assert set(before.cells).issubset(universal_store.snapshot().cells)

        for path, payload in (
            ("/api/universal/connect", {"source": "forged", "target": "forged"}),
            ("/api/universal/rewire", {"incidence": "forged", "participant": "forged"}),
            ("/api/universal/disconnect", {"relation": relation_root}),
        ):
            for _attempt in range(2):
                status, denied = _json(
                    server.url, path, payload, token=token
                )
                assert status == 404
                assert denied["error"] == "not found"
    finally:
        server.close()


def test_exact_leased_selection_does_not_rescan_the_current_canvas(monkeypatch):
    universal_store, universal_registry = build_universal_application(
        resolve_map_path()
    )
    server = ApplicationServer(
        universal_store=universal_store,
        universal_registry=universal_registry,
    ).start()
    try:
        token = server.browser_session_token
        status, canvas = _json(
            server.url, "/api/universal/canvas", token=token
        )
        assert status == 200
        target = next(
            node["id"] for node in canvas["nodes"]
            if node["id"] not in canvas["selection"]
        )

        def reject_canvas_rescan(*_args, **_kwargs):
            raise universal_application_module.InvalidCell(
                "exact leased selection rescanned the current canvas"
            )

        monkeypatch.setattr(
            universal_application_module,
            "_session_canvas_roots",
            reject_canvas_rescan,
        )
        status, receipt = _json(
            server.url,
            "/api/universal/gesture",
            {
                "roots": [target],
                "focus": target,
                "projection_mode": "receipt-v1",
                "projection_revision": canvas["revision"],
            },
            token=token,
        )
        assert status == 200
        assert receipt["committed_revision"] == universal_store.revision
        assert receipt["committed_revision"] > canvas["revision"]
    finally:
        server.close()


def test_scope_interaction_delta_does_not_call_the_full_canvas_projector(
    monkeypatch,
):
    universal_store, universal_registry = build_universal_application(
        resolve_map_path()
    )
    server = ApplicationServer(
        universal_store=universal_store,
        universal_registry=universal_registry,
    ).start()
    try:
        token = server.browser_session_token
        status, canvas = _json(
            server.url, "/api/universal/canvas", token=token
        )
        assert status == 200
        target = next(node for node in canvas["nodes"] if node["openable"])

        def reject_full_canvas_projection(*_args, **_kwargs):
            raise universal_application_module.InvalidCell(
                "scope interaction rebuilt the full canvas projection"
            )

        monkeypatch.setattr(
            server, "project_interaction_canvas", reject_full_canvas_projection
        )
        status, delta = _json(
            server.url,
            "/api/universal/interaction",
            _interaction_request(
                canvas,
                target["id"],
                projection_mode="topology-delta-v1",
            ),
            token=token,
        )
        assert status == 200
        assert delta["projection_mode"] == "topology-delta-v1"
        assert delta["base_revision"] == canvas["revision"]
        assert delta["revision"] == universal_store.revision
        assert delta["scope"]["current"] == target["id"]
    finally:
        server.close()


def test_scope_binding_consumes_the_broker_verified_batch_once(
    monkeypatch,
):
    universal_store, universal_registry = build_universal_application(
        resolve_map_path()
    )
    server = ApplicationServer(
        universal_store=universal_store,
        universal_registry=universal_registry,
    ).start()
    ensure_names = (
        "ensure_universal_properties_panel_interactions",
        "ensure_universal_relation_form_interactions",
        "ensure_universal_scope_interactions",
        "ensure_universal_inspector_lens_interactions",
        "ensure_universal_composition_interactions",
        "ensure_universal_history_interactions",
        "ensure_universal_property_interactions",
        "ensure_universal_operational_transition_interactions",
        "ensure_universal_presentation_interactions",
        "ensure_universal_interface_value_interactions",
        "ensure_universal_relation_member_interactions",
        "ensure_universal_topology_interactions",
        "ensure_universal_instantiation_interactions",
        "ensure_universal_relation_composer_interactions",
    )
    calls = {name: 0 for name in ensure_names}
    try:
        token = server.browser_session_token
        status, canvas = _json(
            server.url, "/api/universal/canvas", token=token
        )
        assert status == 200
        target = next(node for node in canvas["nodes"] if node["openable"])

        for name in ensure_names:
            original = getattr(application_server_module, name)

            @wraps(original)
            def counted(*args, _name=name, _original=original, **kwargs):
                calls[_name] += 1
                return _original(*args, **kwargs)

            monkeypatch.setattr(application_server_module, name, counted)

        def reject_second_interaction_batch_read(*_args, **_kwargs):
            raise AssertionError(
                "server reread the broker-verified interaction batch"
            )

        monkeypatch.setattr(
            application_server_module,
            "_read_interactions_with_verified_protocol",
            reject_second_interaction_batch_read,
        )
        status, delta = _json(
            server.url,
            "/api/universal/interaction",
            _scope_interaction_request(canvas, target["id"]),
            token=token,
        )
        assert status == 200
        assert calls == {name: 1 for name in ensure_names}
        assert delta["interaction_projection"]["revision"] == (
            universal_store.revision
        )
        assert delta["committed_revision"] == universal_store.revision
    finally:
        server.close()


def test_scope_transition_does_not_use_the_generic_projector_and_matches_it(
    monkeypatch,
):
    universal_store, universal_registry = build_universal_application(
        resolve_map_path()
    )
    server = ApplicationServer(
        universal_store=universal_store,
        universal_registry=universal_registry,
    ).start()
    try:
        token = server.browser_session_token
        status, canvas = _json(
            server.url, "/api/universal/canvas", token=token
        )
        assert status == 200
        target = next(node for node in canvas["nodes"] if node["openable"])
        generic_projector = application_server_module.project_universal_canvas
        validate_library = (
            universal_application_module._validate_node_library_sections
        )
        project_library_metadata = (
            universal_application_module
            ._project_node_library_catalogue_metadata
        )
        read_relation_projection = universal_application_module.read_relation
        registered_interface_projection = (
            universal_application_module._registered_canvas_interfaces
        )
        relation_contract_projection = (
            universal_application_module._project_relation_definition_contract
        )
        open_design_tokens = (
            universal_application_module.open_archhub_design_token_system
        )
        project_design_runtime = (
            universal_application_module.project_design_system_runtime
        )
        project_icons = universal_application_module.project_icon_catalog

        def reject_generic_projection(*_args, **_kwargs):
            raise universal_application_module.InvalidCell(
                "scope transition invoked the generic canvas projector"
            )

        monkeypatch.setattr(
            application_server_module,
            "project_universal_canvas",
            reject_generic_projection,
        )
        dense_snapshot = universal_store.dense_snapshot

        def reject_complete_store_materialization():
            raise AssertionError(
                "scope transition materialized the complete Cell Store"
            )

        monkeypatch.setattr(
            universal_store,
            "dense_snapshot",
            reject_complete_store_materialization,
        )

        def reject_library_rebuild(*_args, **_kwargs):
            raise AssertionError(
                "scope transition rebuilt invariant Node Library metadata"
            )

        monkeypatch.setattr(
            universal_application_module,
            "_validate_node_library_sections",
            reject_library_rebuild,
        )
        monkeypatch.setattr(
            universal_application_module,
            "_project_node_library_catalogue_metadata",
            reject_library_rebuild,
        )

        def reject_complete_properties_lens(snapshot, root, *args, **kwargs):
            view = universal_registry.view_sessions[
                universal_registry.authorization.subject_root
            ]
            if root == view.properties_lens_root:
                raise AssertionError(
                    "scope transition traversed the complete Properties lens"
                )
            return read_relation_projection(snapshot, root, *args, **kwargs)

        monkeypatch.setattr(
            universal_application_module,
            "read_relation",
            reject_complete_properties_lens,
        )

        def require_bounded_registered_interfaces(
            snapshot, registry, *args, **kwargs
        ):
            if kwargs.get("admitted_roots") is None:
                raise AssertionError(
                    "scope transition projected every registered interface"
                )
            return registered_interface_projection(
                snapshot, registry, *args, **kwargs
            )

        monkeypatch.setattr(
            universal_application_module,
            "_registered_canvas_interfaces",
            require_bounded_registered_interfaces,
        )

        def reject_invariant_relation_contract_rebuild(*_args, **_kwargs):
            raise AssertionError(
                "scope transition rebuilt invariant definition contracts"
            )

        monkeypatch.setattr(
            universal_application_module,
            "_project_relation_definition_contract",
            reject_invariant_relation_contract_rebuild,
        )

        def reject_static_design_system_rebuild(*_args, **_kwargs):
            raise AssertionError(
                "scope transition rebuilt invariant design-system data"
            )

        monkeypatch.setattr(
            universal_application_module,
            "open_archhub_design_token_system",
            reject_static_design_system_rebuild,
        )
        monkeypatch.setattr(
            universal_application_module,
            "project_design_system_runtime",
            reject_static_design_system_rebuild,
        )
        monkeypatch.setattr(
            universal_application_module,
            "project_icon_catalog",
            reject_static_design_system_rebuild,
        )
        status, delta = _json(
            server.url,
            "/api/universal/interaction",
            _scope_interaction_request(canvas, target["id"]),
            token=token,
        )
        assert status == 200
        bounded = _merge_canvas_delta(canvas, delta)

        monkeypatch.setattr(
            application_server_module,
            "project_universal_canvas",
            generic_projector,
        )
        monkeypatch.setattr(
            universal_store,
            "dense_snapshot",
            dense_snapshot,
        )
        monkeypatch.setattr(
            universal_application_module,
            "_validate_node_library_sections",
            validate_library,
        )
        monkeypatch.setattr(
            universal_application_module,
            "_project_node_library_catalogue_metadata",
            project_library_metadata,
        )
        monkeypatch.setattr(
            universal_application_module,
            "read_relation",
            read_relation_projection,
        )
        monkeypatch.setattr(
            universal_application_module,
            "_registered_canvas_interfaces",
            registered_interface_projection,
        )
        monkeypatch.setattr(
            universal_application_module,
            "_project_relation_definition_contract",
            relation_contract_projection,
        )
        monkeypatch.setattr(
            universal_application_module,
            "open_archhub_design_token_system",
            open_design_tokens,
        )
        monkeypatch.setattr(
            universal_application_module,
            "project_design_system_runtime",
            project_design_runtime,
        )
        monkeypatch.setattr(
            universal_application_module,
            "project_icon_catalog",
            project_icons,
        )
        binding = server._browser_sessions[
            server._browser_token_digest(token)
        ]
        revision_before_generic = universal_store.revision
        canonical = server.project_interaction_canvas(binding)
        assert universal_store.revision == revision_before_generic

        invariant_fields = (
            "application_root",
            "canvas_root",
            "authorization",
            "catalog",
            "catalog_sections",
            "configuration",
            "interaction_policy",
            "library",
            "obligations",
            "primitive",
        )
        rebuilt_fields = (
            "authoring",
            "inspector",
            "interaction_projection",
            "nodes",
            "physical",
            "properties",
            "scope",
            "selected",
            "selected_interface",
            "selected_interfaces",
            "selected_relation",
            "selection",
            "wires",
        )
        assert {
            field: bounded[field] for field in invariant_fields
        } == {
            field: canonical[field] for field in invariant_fields
        }
        assert {
            field: bounded[field] for field in rebuilt_fields
        } == {
            field: canonical[field] for field in rebuilt_fields
        }
        bindings = bounded["interaction_projection"]["bindings"]
        controls = [binding["control"] for binding in bindings]
        assert len(controls) == len(set(controls))
        assert bounded["interaction_projection"]["revision"] == (
            bounded["revision"]
        )
        assert bounded["interaction_projection"]["revision"] == (
            universal_store.revision
        )
        assert delta["committed_revision"] == universal_store.revision

        previous_nodes = {node["id"] for node in canvas["nodes"]}
        canonical_nodes = {node["id"] for node in canonical["nodes"]}
        previous_wires = {
            "%s:%s" % (wire["id"], wire["segment"])
            for wire in canvas["wires"]
        }
        canonical_wires = {
            "%s:%s" % (wire["id"], wire["segment"])
            for wire in canonical["wires"]
        }
        patch = delta["topology_patch"]
        assert set(patch["remove_nodes"]) == previous_nodes - canonical_nodes
        assert set(patch["remove_wires"]) == previous_wires - canonical_wires
    finally:
        server.close()


def test_scope_transition_fails_closed_on_base_or_subject_drift():
    universal_store, universal_registry = build_universal_application(
        resolve_map_path()
    )
    server = ApplicationServer(
        universal_store=universal_store,
        universal_registry=universal_registry,
    ).start()
    try:
        token = server.browser_session_token
        status, canvas = _json(
            server.url, "/api/universal/canvas", token=token
        )
        assert status == 200
        target = next(node for node in canvas["nodes"] if node["openable"])
        request = _scope_interaction_request(canvas, target["id"])
        binding = server._browser_sessions[
            server._browser_token_digest(token)
        ]
        execution = (
            universal_application_module.submit_universal_scope_interaction(
                universal_store,
                universal_registry,
                server.interaction_projection_broker,
                binding.interaction_projection_handle,
                interaction_root=request["interaction"],
                control_root=request["control"],
                event_root=request["event"],
                expected_revision=request["revision"],
                projected_canvas=canvas,
                authentication_context=binding.context,
            )
        )
        materialization = execution.materialization
        assert materialization is not None
        with pytest.raises(InvalidCell, match="base projection revision"):
            universal_application_module.project_universal_scope_transition(
                universal_store,
                universal_registry,
                authentication_context=binding.context,
                scope_materialization=materialization,
                previous_projection=canvas,
                expected_base_revision=request["revision"] - 1,
            )
        with pytest.raises(InvalidCell, match="materialization revision"):
            universal_application_module.project_universal_scope_transition(
                universal_store,
                universal_registry,
                authentication_context=binding.context,
                scope_materialization=replace(
                    materialization,
                    changed_roots=(),
                ),
                previous_projection=canvas,
                expected_base_revision=request["revision"],
            )
        with pytest.raises(InvalidCell, match="exact view revision"):
            universal_application_module.project_universal_scope_transition(
                universal_store,
                universal_registry,
                authentication_context=binding.context,
                scope_materialization=replace(
                    materialization,
                    subject_root="foreign:subject",
                ),
                previous_projection=canvas,
                expected_base_revision=request["revision"],
            )
        malformed = dict(canvas)
        malformed["catalog_sections"] = ["not-a-graph-projection"]
        with pytest.raises(InvalidCell, match="reusable projection"):
            universal_application_module.project_universal_scope_transition(
                universal_store,
                universal_registry,
                authentication_context=binding.context,
                scope_materialization=materialization,
                previous_projection=malformed,
                expected_base_revision=request["revision"],
            )
        malformed = dict(canvas)
        malformed["catalog"] = ["not-a-catalogue-entry"]
        with pytest.raises(InvalidCell, match="reusable projection"):
            universal_application_module.project_universal_scope_transition(
                universal_store,
                universal_registry,
                authentication_context=binding.context,
                scope_materialization=materialization,
                previous_projection=malformed,
                expected_base_revision=request["revision"],
            )
        malformed = dict(canvas)
        malformed_catalog = json.loads(json.dumps(canvas["catalog"]))
        relation_definition = next(
            item for item in malformed_catalog
            if item.get("composition_contract") is not None
        )
        relation_definition["composition_contract"]["roles"][0][
            "choices"
        ] = "not-a-choice-projection"
        malformed["catalog"] = malformed_catalog
        with pytest.raises(InvalidCell, match="relation role"):
            universal_application_module.project_universal_scope_transition(
                universal_store,
                universal_registry,
                authentication_context=binding.context,
                scope_materialization=materialization,
                previous_projection=malformed,
                expected_base_revision=request["revision"],
            )
        malformed = dict(canvas)
        malformed_configuration = dict(canvas["configuration"])
        malformed_design_system = dict(
            malformed_configuration["design_system"]
        )
        malformed_design_system["tokens"] = "not-a-token-projection"
        malformed_configuration["design_system"] = malformed_design_system
        malformed["configuration"] = malformed_configuration
        with pytest.raises(InvalidCell, match="design system"):
            universal_application_module.project_universal_scope_transition(
                universal_store,
                universal_registry,
                authentication_context=binding.context,
                scope_materialization=materialization,
                previous_projection=malformed,
                expected_base_revision=request["revision"],
            )
    finally:
        server.close()


def test_parent_scope_transition_reuses_only_exact_validated_relations(
    monkeypatch,
):
    import nodelang.cell_protocols as protocol_module

    universal_store, universal_registry = build_universal_application(
        resolve_map_path()
    )
    server = ApplicationServer(
        universal_store=universal_store,
        universal_registry=universal_registry,
    ).start()
    try:
        token = server.browser_session_token
        status, canvas = _json(
            server.url, "/api/universal/canvas", token=token
        )
        assert status == 200
        binding = server._browser_sessions[
            server._browser_token_digest(token)
        ]
        target = next(node for node in canvas["nodes"] if node["openable"])
        entered = universal_application_module._set_universal_scope_execution(
            universal_store,
            universal_registry,
            target["id"],
            expected_revision=canvas["revision"],
            projected_canvas=canvas,
            authentication_context=binding.context,
        )
        nested = universal_application_module.project_universal_scope_transition(
            universal_store,
            universal_registry,
            authentication_context=binding.context,
            scope_materialization=entered.materialization,
            previous_projection=canvas,
            expected_base_revision=canvas["revision"],
        )
        returned = universal_application_module._set_universal_scope_execution(
            universal_store,
            universal_registry,
            universal_registry.canvas_root,
            expected_revision=nested["revision"],
            projected_canvas=nested,
            authentication_context=binding.context,
        )
        materialization = returned.materialization
        assert materialization is not None
        assert materialization.interface_roots
        reusable_roots = {
            entry.relation_root
            for entry in materialization.relation_projections
        }
        required_roots = {
            *materialization.relation_roots,
            *materialization.property_roots,
        }
        assert reusable_roots == required_roots

        original_read_relation = universal_application_module.read_relation
        first_read_was_reused = {}

        def record_first_relation_read(snapshot, relation_root, *args, **kwargs):
            if (
                relation_root in required_roots
                and relation_root not in first_read_was_reused
            ):
                cache = protocol_module._RELATION_PROJECTION_CACHE.get()
                cache_key = (
                    snapshot.revision,
                    id(snapshot.cells),
                    relation_root,
                )
                first_read_was_reused[relation_root] = (
                    cache is not None and cache_key in cache
                )
            return original_read_relation(
                snapshot, relation_root, *args, **kwargs
            )

        monkeypatch.setattr(
            universal_application_module,
            "read_relation",
            record_first_relation_read,
        )
        discover_interfaces = (
            universal_application_module._scope_canvas_interface_roots
        )

        def reject_duplicate_interface_discovery(*_args, **_kwargs):
            raise AssertionError(
                "parent scope rediscovered already validated interfaces"
            )

        monkeypatch.setattr(
            universal_application_module,
            "_scope_canvas_interface_roots",
            reject_duplicate_interface_discovery,
        )
        projected = universal_application_module.project_universal_scope_transition(
            universal_store,
            universal_registry,
            authentication_context=binding.context,
            scope_materialization=materialization,
            previous_projection=nested,
            expected_base_revision=nested["revision"],
        )
        assert projected["scope"]["current"] == universal_registry.canvas_root
        assert set(first_read_was_reused) == required_roots
        assert all(first_read_was_reused.values())
        monkeypatch.setattr(
            universal_application_module,
            "_scope_canvas_interface_roots",
            discover_interfaces,
        )
        canonical = universal_application_module.project_universal_canvas(
            universal_store,
            universal_registry,
            authentication_context=binding.context,
        )
        for field in (
            "nodes",
            "wires",
            "selected_interface",
            "selected_interfaces",
        ):
            assert projected[field] == canonical[field]

        first_reuse = materialization.relation_projections[0]
        first_source = first_reuse.source_cells[0]
        forged_source = Cell(
            first_source.id,
            first_source.link0,
            first_source.link1,
            first_source.atom + b"forged",
        )
        forged_reuse = replace(
            first_reuse,
            source_cells=(forged_source, *first_reuse.source_cells[1:]),
        )
        forged_materialization = replace(
            materialization,
            relation_projections=(
                forged_reuse,
                *materialization.relation_projections[1:],
            ),
        )
        with pytest.raises(
            InvalidCell, match="(source Cell|fingerprint) drifted"
        ):
            universal_application_module.project_universal_scope_transition(
                universal_store,
                universal_registry,
                authentication_context=binding.context,
                scope_materialization=forged_materialization,
                previous_projection=nested,
                expected_base_revision=nested["revision"],
            )
    finally:
        server.close()


def test_scope_request_reuses_its_registered_relation_batch_seal(
    monkeypatch,
):
    """One HTTP turn must not recompute a seal registered in that turn."""
    import nodelang.cell_protocols as protocol_module

    universal_store, universal_registry = build_universal_application(
        resolve_map_path()
    )
    server = ApplicationServer(
        universal_store=universal_store,
        universal_registry=universal_registry,
    ).start()
    try:
        token = server.browser_session_token
        status, canvas = _json(
            server.url, "/api/universal/canvas", token=token
        )
        assert status == 200
        target = next(node for node in canvas["nodes"] if node["openable"])
        status, entered_delta = _json(
            server.url,
            "/api/universal/interaction",
            _scope_interaction_request(canvas, target["id"]),
            token=token,
        )
        assert status == 200
        nested = _merge_canvas_delta(canvas, entered_delta)

        def reject_duplicate_batch_seal(*_args, **_kwargs):
            raise AssertionError(
                "scope request recomputed its registered relation batch seal"
            )

        monkeypatch.setattr(
            protocol_module,
            "relation_projection_fingerprint",
            reject_duplicate_batch_seal,
        )
        status, returned_delta = _json(
            server.url,
            "/api/universal/interaction",
            _scope_interaction_request(
                nested, universal_registry.canvas_root
            ),
            token=token,
        )
        assert status == 200
        returned = _merge_canvas_delta(nested, returned_delta)
        assert returned["scope"]["current"] == universal_registry.canvas_root
        assert len(returned["nodes"]) == 17
        assert len(returned["wires"]) == 136
    finally:
        server.close()


def test_top_scope_reuses_declared_endpoint_indexes_for_every_wire(
    monkeypatch,
):
    universal_store, universal_registry = build_universal_application(
        resolve_map_path()
    )
    snapshot = universal_store.dense_snapshot()
    view_session = universal_registry.view_sessions[
        universal_registry.authorization.subject_root
    ]
    assigned = tuple(
        member.participant_id
        for member in read_relation(
            snapshot, view_session.visibility_root, budget=100_000
        )
        if member.role_id == universal_registry.roles["visible"]
    )
    original_endpoint = universal_application_module._canvas_endpoint
    indexed_calls = []
    unindexed_calls = []

    @wraps(original_endpoint)
    def require_endpoint_indexes(
        snapshot,
        registry,
        member,
        owner_roots=(),
        **kwargs,
    ):
        if len(owner_roots) > 1:
            record = (member.participant_id, member.incidence_id)
            if any(
                kwargs.get(name) is None
                for name in (
                    "interface_cache",
                    "owner_interface_index",
                    "boundary_index",
                )
            ):
                unindexed_calls.append(record)
            else:
                indexed_calls.append(record)
        return original_endpoint(
            snapshot,
            registry,
            member,
            owner_roots,
            **kwargs,
        )

    monkeypatch.setattr(
        universal_application_module,
        "_canvas_endpoint",
        require_endpoint_indexes,
    )
    universal_application_module._canvas_scope_for_assigned(
        snapshot, universal_registry, assigned
    )
    assert indexed_calls
    assert unindexed_calls == []


def test_scope_canvas_reuses_declared_endpoint_indexes_for_every_wire(
    monkeypatch,
):
    universal_store, universal_registry = build_universal_application(
        resolve_map_path()
    )
    server = ApplicationServer(
        universal_store=universal_store,
        universal_registry=universal_registry,
    ).start()
    try:
        token = server.browser_session_token
        status, canvas = _json(
            server.url, "/api/universal/canvas", token=token
        )
        assert status == 200
        target = next(
            node for node in canvas["nodes"]
            if node["id"] == "gm:domain:ui"
        )
        original_endpoint = universal_application_module._canvas_endpoint
        indexed_calls = []
        unindexed_calls = []

        @wraps(original_endpoint)
        def require_endpoint_indexes(
            snapshot,
            registry,
            member,
            owner_roots=(),
            **kwargs,
        ):
            if len(owner_roots) > 1:
                record = (member.participant_id, member.incidence_id)
                if any(
                    kwargs.get(name) is None
                    for name in (
                        "interface_cache",
                        "owner_interface_index",
                        "boundary_index",
                    )
                ):
                    unindexed_calls.append(record)
                else:
                    indexed_calls.append(record)
            return original_endpoint(
                snapshot,
                registry,
                member,
                owner_roots,
                **kwargs,
            )

        monkeypatch.setattr(
            universal_application_module,
            "_canvas_endpoint",
            require_endpoint_indexes,
        )
        status, _delta = _json(
            server.url,
            "/api/universal/interaction",
            _scope_interaction_request(canvas, target["id"]),
            token=token,
        )
        assert status == 200
        assert indexed_calls
        assert unindexed_calls == []
    finally:
        server.close()


def test_top_scope_is_read_from_the_graph_visibility_projection(
    monkeypatch,
):
    store, registry = build_universal_application(resolve_map_path())
    snapshot = store.snapshot()
    view = next(iter(registry.view_sessions.values()))
    visibility_members = read_relation(
        snapshot, view.visibility_root, budget=100_000
    )
    indexed_relations = tuple(
        member.participant_id for member in visibility_members
        if member.role_id == registry.roles["relation"]
    )
    indexed_properties = tuple(
        member.participant_id for member in visibility_members
        if member.role_id == registry.roles["property"]
    )
    indexed_interfaces = tuple(
        member.participant_id for member in visibility_members
        if member.role_id == registry.assembly_protocol.role("interface")
    )
    index_markers = tuple(
        member.participant_id for member in visibility_members
        if member.role_id == registry.roles["migration"]
    )
    assert len(indexed_relations) == 136
    assert len(indexed_properties) == 631
    assigned = {
        member.participant_id for member in visibility_members
        if member.role_id == registry.roles["visible"]
    }
    canonical_interfaces = tuple(
        str(interface["id"])
        for interface in universal_application_module._registered_canvas_interfaces(
            snapshot, registry
        )
        if interface["owner"] in assigned
    )
    assert indexed_interfaces == canonical_interfaces
    assert index_markers == (
        universal_application_module._VISIBILITY_INTERFACE_INDEX_MARKER_ROOT,
    )

    def reject_global_canvas_sweep(*_args, **_kwargs):
        raise AssertionError("top scope swept the global canvas")

    monkeypatch.setattr(
        universal_application_module,
        "_canvas_scope_for_assigned",
        reject_global_canvas_sweep,
    )
    roots, relations, properties = (
        universal_application_module._session_canvas_roots(
            snapshot, registry, view
        )
    )
    assert len(roots) == 17
    assert relations == indexed_relations
    assert properties == indexed_properties


def test_top_scope_visibility_projection_fails_closed_on_hidden_property():
    store, registry = build_universal_application(resolve_map_path())
    snapshot = store.snapshot()
    view = next(iter(registry.view_sessions.values()))
    assigned = {
        member.participant_id for member in read_relation(
            snapshot, view.visibility_root, budget=100_000
        )
        if member.role_id == registry.roles["visible"]
    }
    hidden_property = next(
        property_root
        for property_root in universal_application_module._canvas_roots(
            snapshot, registry
        )[2]
        if universal_application_module._one_for_role(
            read_relation(snapshot, property_root, budget=8),
            registry.roles["owner"],
        ) not in assigned
    )
    patch = prepare_append_relation_members(
        snapshot,
        view.visibility_root,
        ((registry.roles["property"], hidden_property),),
        budget=100_000,
    )
    store.commit(
        snapshot.revision, create=patch.create, replace=patch.replace
    )

    with pytest.raises(InvalidCell, match="visibility projection"):
        universal_application_module._session_canvas_roots(
            store.snapshot(), registry, view
        )


def test_restore_admission_rejects_a_partial_visibility_projection():
    store, registry = build_universal_application(resolve_map_path())
    snapshot = store.snapshot()
    view = next(iter(registry.view_sessions.values()))
    relation_member = next(
        member for member in read_relation(
            snapshot, view.visibility_root, budget=100_000
        )
        if member.role_id == registry.roles["relation"]
    )
    removal = prepare_remove_relation_members(
        snapshot,
        view.visibility_root,
        (relation_member.incidence_id,),
        budget=100_000,
    )
    store.commit(snapshot.revision, replace=removal.replace)

    with pytest.raises(
        InvalidCell, match="persisted visibility relation projection drifted"
    ):
        universal_application_module._ensure_view_visibility_scope_projection(
            store, registry, view
        )


def test_restore_admission_rejects_a_partial_visibility_interface_index():
    store, registry = build_universal_application(resolve_map_path())
    snapshot = store.snapshot()
    view = next(iter(registry.view_sessions.values()))
    interface_member = next(
        member for member in read_relation(
            snapshot, view.visibility_root, budget=100_000
        )
        if member.role_id == registry.assembly_protocol.role("interface")
    )
    removal = prepare_remove_relation_members(
        snapshot,
        view.visibility_root,
        (interface_member.incidence_id,),
        budget=100_000,
    )
    store.commit(snapshot.revision, replace=removal.replace)

    with pytest.raises(
        InvalidCell, match="persisted visibility interface projection drifted"
    ):
        universal_application_module._ensure_view_visibility_scope_projection(
            store, registry, view
        )


def test_top_scope_rejects_an_interface_without_a_visible_graph_owner():
    store, registry = build_universal_application(resolve_map_path())
    snapshot = store.snapshot()
    view = next(iter(registry.view_sessions.values()))
    definition = read_definition(
        snapshot,
        registry.assembly_protocol,
        registry.standard_library.definition_roots[0],
    )
    foreign_interface = definition.interface_roots[0]
    visibility_members = read_relation(
        snapshot, view.visibility_root, budget=100_000
    )
    assert foreign_interface not in {
        member.participant_id for member in visibility_members
    }
    patch = prepare_append_relation_members(
        snapshot,
        view.visibility_root,
        ((registry.assembly_protocol.role("interface"), foreign_interface),),
        budget=100_000,
    )
    store.commit(
        snapshot.revision, create=patch.create, replace=patch.replace
    )

    with pytest.raises(
        InvalidCell, match="visibility interface lacks a visible graph owner"
    ):
        universal_application_module._session_canvas_roots(
            store.snapshot(), registry, view
        )


def test_top_scope_excludes_properties_owned_only_by_hidden_descendants():
    universal_store, universal_registry = build_universal_application(
        resolve_map_path()
    )
    snapshot = universal_store.dense_snapshot()
    view_session = universal_registry.view_sessions[
        universal_registry.authorization.subject_root
    ]
    assigned = tuple(
        member.participant_id
        for member in read_relation(
            snapshot, view_session.visibility_root, budget=100_000
        )
        if member.role_id == universal_registry.roles["visible"]
    )
    visible_roots, relation_roots, property_roots = (
        universal_application_module._canvas_scope_for_assigned(
            snapshot, universal_registry, assigned
        )
    )
    admitted_owners = set(visible_roots) | set(relation_roots)
    projected_owners = {}
    for property_root in property_roots:
        members = read_relation(snapshot, property_root, budget=8)
        owners = tuple(
            member.participant_id for member in members
            if member.role_id == universal_registry.roles["owner"]
        )
        assert len(owners) == 1
        projected_owners[property_root] = owners[0]

    hidden_properties = {
        property_root
        for owner_root, owned_properties
        in universal_registry.root_properties.items()
        if owner_root not in admitted_owners
        for property_root in owned_properties
    }
    assert hidden_properties
    assert hidden_properties.isdisjoint(property_roots)
    assert set(projected_owners.values()).issubset(admitted_owners)


def test_interaction_projection_rejects_missing_or_duplicate_visible_controls(
    monkeypatch,
):
    universal_store, universal_registry = build_universal_application(
        resolve_map_path()
    )
    server = ApplicationServer(
        universal_store=universal_store,
        universal_registry=universal_registry,
    ).start()
    try:
        token = server.browser_session_token
        status, canvas = _json(
            server.url, "/api/universal/canvas", token=token
        )
        assert status == 200
        binding = server._browser_sessions[
            server._browser_token_digest(token)
        ]
        original_panels = (
            application_server_module
            .ensure_universal_properties_panel_interactions
        )
        visible_panel = canvas["inspector"]["presentation"]["panels"][0][
            "id"
        ]

        def omit_one_panel(*args, **kwargs):
            event_root, interactions = original_panels(*args, **kwargs)
            return event_root, {
                control: interaction
                for control, interaction in interactions.items()
                if control != visible_panel
            }

        monkeypatch.setattr(
            application_server_module,
            "ensure_universal_properties_panel_interactions",
            omit_one_panel,
        )
        with pytest.raises(
            InvalidCell,
            match="visible control lacks a graph interaction",
        ):
            server.project_interaction_canvas(binding)

        monkeypatch.setattr(
            application_server_module,
            "ensure_universal_properties_panel_interactions",
            original_panels,
        )
        original_form = application_server_module.read_relation_form_binding
        duplicate_control = canvas["inspector"]["presentation"]["panels"][0][
            "id"
        ]

        def duplicate_form_control(*args, **kwargs):
            form = original_form(*args, **kwargs)
            return replace(form, control_root=duplicate_control)

        monkeypatch.setattr(
            application_server_module,
            "read_relation_form_binding",
            duplicate_form_control,
        )
        with pytest.raises(
            InvalidCell,
            match="projected interaction controls overlap",
        ):
            server.project_interaction_canvas(binding)
    finally:
        server.close()


def test_nested_scope_reads_only_declared_relations_and_owner_properties(
    monkeypatch,
):
    universal_store, universal_registry = build_universal_application(
        resolve_map_path()
    )
    snapshot = universal_store.dense_snapshot()
    target_root = universal_registry.map.domains["ui"]
    expected = universal_application_module._nested_canvas_scope(
        snapshot, universal_registry, target_root
    )
    members = read_relation(snapshot, target_root, budget=100_000)
    visible_roots = tuple(
        member.participant_id for member in members
        if universal_application_module._scope_role_name(
            snapshot, member.role_id
        ) == "member"
    )
    declared_relations = {
        member.participant_id for member in members
        if universal_application_module._scope_role_name(
            snapshot, member.role_id
        ) in {"scope", "relation", "property"}
    }
    owner_properties = {
        property_root
        for root_id in visible_roots
        for property_root in universal_registry.root_properties.get(
            root_id, ()
        )
    }
    interface_role = universal_registry.assembly_protocol.role("interface")
    owner_interfaces = {
        member.participant_id
        for root_id in visible_roots
        for member in read_relation(snapshot, root_id, budget=100_000)
        if member.role_id == interface_role
    }
    allowed = {
        target_root,
        *visible_roots,
        *owner_interfaces,
        *declared_relations,
        *owner_properties,
    }
    read_relation_or_none = (
        universal_application_module._relation_members_or_none
    )
    relation_reads = set()

    def bounded_relation_read(current_snapshot, relation_root):
        if relation_root not in allowed:
            raise AssertionError(
                "scope derivation read an unrelated registered relation"
            )
        if relation_root in relation_reads:
            raise AssertionError(
                "scope derivation reread a declared relation"
            )
        relation_reads.add(relation_root)
        return read_relation_or_none(current_snapshot, relation_root)

    monkeypatch.setattr(
        universal_application_module,
        "_relation_members_or_none",
        bounded_relation_read,
    )
    assert universal_application_module._nested_canvas_scope(
        snapshot, universal_registry, target_root
    ) == expected


def test_scope_interaction_refuses_a_stale_store_revision_without_mutation():
    server = ApplicationServer().start()
    try:
        token = server.browser_session_token
        status, canvas = _json(
            server.url, "/api/universal/canvas", token=token
        )
        assert status == 200
        target = next(node for node in canvas["nodes"] if node["openable"])
        before = server.universal_store.revision
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
            token=token,
        )
        assert status == 200
        assert advanced["touched"] == before + 1
        advanced_revision = server.universal_store.revision

        status, rejected = _json(
            server.url,
            "/api/universal/interaction",
            _scope_interaction_request(canvas, target["id"]),
            token=token,
        )
        assert status == 400
        assert rejected["error"] == (
            "expected revision %s, current revision is %s"
            % (canvas["revision"], advanced_revision)
        )
        assert server.universal_store.revision == advanced_revision
    finally:
        server.close()


def test_scope_interaction_refuses_a_target_absent_from_the_leased_scope():
    server = ApplicationServer().start()
    try:
        token = server.browser_session_token
        status, canvas = _json(
            server.url, "/api/universal/canvas", token=token
        )
        assert status == 200
        target = next(node for node in canvas["nodes"] if node["openable"])
        absent_root = next(
            node["id"] for node in canvas["nodes"]
            if node["id"] != target["id"]
        )
        status, scope_delta = _json(
            server.url,
            "/api/universal/interaction",
            _scope_interaction_request(canvas, target["id"]),
            token=token,
        )
        assert status == 200
        scoped = _merge_canvas_delta(canvas, scope_delta)
        assert absent_root not in {node["id"] for node in scoped["nodes"]}
        before = server.universal_store.revision

        status, rejected = _json(
            server.url,
            "/api/universal/gesture",
            {
                "roots": [absent_root],
                "focus": absent_root,
                "projection_mode": "receipt-v1",
                "projection_revision": scoped["revision"],
            },
            token=token,
        )
        assert status == 400
        assert "outside the active lens" in rejected["error"]
        assert server.universal_store.revision == before
    finally:
        server.close()


def test_exact_leased_noop_selection_creates_no_revision():
    server = ApplicationServer().start()
    try:
        token = server.browser_session_token
        status, canvas = _json(
            server.url, "/api/universal/canvas", token=token
        )
        assert status == 200
        target = canvas["nodes"][0]["id"]
        status, first = _json(
            server.url,
            "/api/universal/gesture",
            {
                "roots": [target],
                "focus": target,
                "projection_mode": "receipt-v1",
                "projection_revision": canvas["revision"],
            },
            token=token,
        )
        assert status == 200
        status, selected = _json(
            server.url, "/api/universal/canvas", token=token
        )
        assert status == 200
        assert selected["selection"] == [target]
        assert selected["selected"] == target
        before = server.universal_store.revision

        status, noop = _json(
            server.url,
            "/api/universal/gesture",
            {
                "roots": list(selected["selection"]),
                "focus": selected["selected"],
                "projection_mode": "receipt-v1",
                "projection_revision": selected["revision"],
            },
            token=token,
        )
        assert status == 200
        assert noop["committed_revision"] == before
        assert server.universal_store.revision == before
    finally:
        server.close()


def test_cached_projection_is_bound_to_the_exact_browser_subject():
    server = ApplicationServer().start()
    try:
        token = server.browser_session_token
        status, canvas = _json(
            server.url, "/api/universal/canvas", token=token
        )
        assert status == 200
        binding = server._browser_sessions[
            server._browser_token_digest(token)
        ]
        foreign_binding = type(binding)(
            session_root=binding.session_root,
            subject_root="test:foreign-projection-subject",
            view_root=binding.view_root,
            tenant_root=binding.tenant_root,
            assurance_root=binding.assurance_root,
            context=binding.context,
            csrf_token=binding.csrf_token,
            interaction_projection_handle=(
                binding.interaction_projection_handle
            ),
        )

        cached = server._cached_browser_canvas_projection(
            binding, canvas["revision"]
        )
        assert cached == {
            key: value for key, value in canvas.items() if key != "ok"
        }
        assert server._cached_browser_canvas_projection(
            foreign_binding, canvas["revision"]
        ) is None
    finally:
        server.close()


def test_discarding_disposable_projection_changes_no_graph_semantics():
    server = ApplicationServer().start()
    try:
        token = server.browser_session_token
        status, first = _json(
            server.url, "/api/universal/canvas", token=token
        )
        assert status == 200
        before = server.universal_store.revision
        semantic_keys = (
            "application_root",
            "canvas_root",
            "scope",
            "selection",
            "selected",
            "nodes",
            "wires",
            "properties",
            "inspector",
        )
        expected = {key: first[key] for key in semantic_keys}

        server._browser_canvas_projections.clear()
        status, rebuilt = _json(
            server.url, "/api/universal/canvas", token=token
        )
        assert status == 200
        assert server.universal_store.revision == before
        assert {key: rebuilt[key] for key in semantic_keys} == expected
    finally:
        server.close()


def test_scope_revisit_uses_only_the_exact_private_target_projection(
    monkeypatch,
):
    """A revisit may reuse presentation, never authority or another identity."""
    server = ApplicationServer().start()
    try:
        token = server.browser_session_token
        status, top = _json(
            server.url, "/api/universal/canvas", token=token
        )
        assert status == 200
        binding = server._browser_sessions[
            server._browser_token_digest(token)
        ]
        cached_scope = getattr(
            server, "_cached_browser_scope_projection", None
        )
        assert callable(cached_scope)
        retained_top = cached_scope(
            binding,
            top["scope"]["current"],
            expected_lineage_revision=top["revision"],
        )
        assert retained_top == {
            key: value for key, value in top.items() if key != "ok"
        }
        retained_top_before = copy.deepcopy(retained_top)

        observed_reuse = []
        original_transition = (
            application_server_module.project_universal_scope_transition
        )

        def record_scope_reuse(*args, **kwargs):
            observed_reuse.append(kwargs.get("reusable_scope_projection"))
            return original_transition(*args, **kwargs)

        monkeypatch.setattr(
            application_server_module,
            "project_universal_scope_transition",
            record_scope_reuse,
        )
        target = next(node for node in top["nodes"] if node["openable"])
        status, entered_delta = _json(
            server.url,
            "/api/universal/interaction",
            _scope_interaction_request(top, target["id"]),
            token=token,
        )
        assert status == 200
        nested = _merge_canvas_delta(top, entered_delta)
        status, parent_delta = _json(
            server.url,
            "/api/universal/interaction",
            _scope_interaction_request(
                nested, top["scope"]["current"]
            ),
            token=token,
        )
        assert status == 200
        parent = _merge_canvas_delta(nested, parent_delta)
        assert observed_reuse[0] is None
        assert observed_reuse[1] is retained_top

        canonical = server.project_interaction_canvas(binding)
        for field in (
            "application_root",
            "canvas_root",
            "authorization",
            "catalog",
            "catalog_sections",
            "inspector",
            "interaction_projection",
            "nodes",
            "properties",
            "scope",
            "selected",
            "selected_interfaces",
            "selection",
            "wires",
        ):
            assert parent[field] == canonical[field]
        assert parent["revision"] == canonical["revision"]
        assert parent["interaction_projection"]["revision"] == (
            canonical["revision"]
        )
        assert retained_top == retained_top_before
    finally:
        server.close()


def test_scope_projection_retention_is_bounded_per_browser_session():
    """Disposable scope acceleration has a fixed per-session memory ceiling."""
    server = ApplicationServer().start()
    try:
        token = server.browser_session_token
        status, canvas = _json(
            server.url, "/api/universal/canvas", token=token
        )
        assert status == 200
        binding = server._browser_sessions[
            server._browser_token_digest(token)
        ]
        seed = server._browser_canvas_projections[binding.session_root]
        with server._browser_session_lock:
            server._browser_scope_canvas_projections = {
                (binding.session_root, f"test:scope:{index}"): seed
                for index in range(
                    application_server_module._BROWSER_SCOPE_PROJECTION_LIMIT
                )
            }
            server._browser_scope_canvas_identities = {
                key: ((), (), (), ())
                for key in server._browser_scope_canvas_projections
            }

        projection = copy.deepcopy(seed.projection)
        projection["scope"]["current"] = "test:scope:newest"
        projected_binding = type(seed)(
            seed.session_root,
            seed.subject_root,
            seed.view_root,
            seed.tenant_root,
            seed.assurance_root,
            projection,
        )
        scope_key = (binding.session_root, "test:scope:newest")
        with server._browser_session_lock:
            server._browser_scope_canvas_projections[scope_key] = (
                projected_binding
            )
            server._browser_scope_canvas_identities[scope_key] = (
                (), (), (), ()
            )
        server._enforce_browser_scope_projection_limit(binding.session_root)

        retained = tuple(
            key
            for key in server._browser_scope_canvas_projections
            if key[0] == binding.session_root
        )
        assert len(retained) == (
            application_server_module._BROWSER_SCOPE_PROJECTION_LIMIT
        )
        assert scope_key in retained
        assert (binding.session_root, "test:scope:0") not in retained
        assert set(server._browser_scope_canvas_identities) == set(
            server._browser_scope_canvas_projections
        )
        assert server.universal_store.revision == canvas["revision"]
    finally:
        server.close()


def test_scope_projection_reuse_discards_foreign_or_unexplained_state():
    server = ApplicationServer().start()
    try:
        token = server.browser_session_token
        status, canvas = _json(
            server.url, "/api/universal/canvas", token=token
        )
        assert status == 200
        binding = server._browser_sessions[
            server._browser_token_digest(token)
        ]
        cached_scope = getattr(
            server, "_cached_browser_scope_projection", None
        )
        assert callable(cached_scope)
        foreign_binding = type(binding)(
            session_root=binding.session_root,
            subject_root="test:foreign-scope-projection-subject",
            view_root=binding.view_root,
            tenant_root=binding.tenant_root,
            assurance_root=binding.assurance_root,
            context=binding.context,
            csrf_token=binding.csrf_token,
            interaction_projection_handle=(
                binding.interaction_projection_handle
            ),
        )
        assert cached_scope(
            foreign_binding,
            canvas["scope"]["current"],
            expected_lineage_revision=canvas["revision"],
        ) is None

        before = server.universal_store.snapshot()
        server.universal_store.commit(
            before.revision,
            create=(Cell(
                "test:unexplained-scope-cache-revision",
                NULL_CELL_ID,
                NULL_CELL_ID,
                b"unexplained",
            ),),
        )
        assert cached_scope(
            binding,
            canvas["scope"]["current"],
            expected_lineage_revision=server.universal_store.revision,
        ) is None
        accepted = server.universal_store.snapshot()
        accepted_cells = dict(accepted.cells)
        server._browser_scope_canvas_projections.clear()
        assert server.universal_store.revision == accepted.revision
        assert dict(server.universal_store.snapshot().cells) == accepted_cells
    finally:
        server.close()


def test_parent_scope_revisit_does_not_rescan_the_global_visibility_index(
    monkeypatch,
):
    """A retained parent scope remains bounded to its accepted graph region."""
    server = ApplicationServer().start()
    try:
        token = server.browser_session_token
        status, top = _json(
            server.url, "/api/universal/canvas", token=token
        )
        assert status == 200
        target = next(node for node in top["nodes"] if node["openable"])
        status, entered_delta = _json(
            server.url,
            "/api/universal/interaction",
            _scope_interaction_request(top, target["id"]),
            token=token,
        )
        assert status == 200
        nested = _merge_canvas_delta(top, entered_delta)

        def reject_global_visibility_rescan(*_args, **_kwargs):
            raise AssertionError(
                "retained parent scope rescanned the global visibility index"
            )

        def reject_endpoint_index_rebuild(*_args, **_kwargs):
            raise AssertionError(
                "retained parent topology rebuilt endpoint indexes"
            )

        original_render_view_template = (
            universal_application_module.render_view_template
        )

        def reject_stable_topology_rerender(
            snapshot, protocol, template_root, values
        ):
            if template_root in {
                universal_application_module.CANVAS_CARD_TEMPLATE_ROOT,
                universal_application_module.CANVAS_PORT_TEMPLATE_ROOT,
                universal_application_module.LIBRARY_DEFINITION_TEMPLATE_ROOT,
            }:
                raise AssertionError(
                    "retained parent scope rerendered stable descriptors"
                )
            return original_render_view_template(
                snapshot, protocol, template_root, values
            )

        monkeypatch.setattr(
            universal_application_module,
            "_visibility_scope_projection",
            reject_global_visibility_rescan,
        )
        monkeypatch.setattr(
            universal_application_module,
            "_nested_scope_endpoint_indexes",
            reject_endpoint_index_rebuild,
        )
        monkeypatch.setattr(
            universal_application_module,
            "render_view_template",
            reject_stable_topology_rerender,
        )
        status, parent_delta = _json(
            server.url,
            "/api/universal/interaction",
            _scope_interaction_request(
                nested, top["scope"]["current"]
            ),
            token=token,
        )
        assert status == 200, parent_delta
        parent = _merge_canvas_delta(nested, parent_delta)
        assert parent["scope"]["current"] == top["scope"]["current"]
        assert [node["id"] for node in parent["nodes"]] == [
            node["id"] for node in top["nodes"]
        ]
    finally:
        server.close()


def test_leased_topology_connection_does_not_rescan_the_current_canvas(
    monkeypatch,
):
    universal_store, universal_registry = build_universal_application(
        resolve_map_path()
    )
    projection = universal_application_module.project_universal_canvas(
        universal_store, universal_registry
    )
    source_node, source_port = next(
        (node, port)
        for node in projection["nodes"]
        for port in node["ports"]
        if port.get("connect_choices")
    )
    target = source_port["connect_choices"][0]

    def reject_canvas_rescan(*_args, **_kwargs):
        raise AssertionError("exact leased topology rescanned the current canvas")

    monkeypatch.setattr(
        universal_application_module,
        "_session_canvas_roots",
        reject_canvas_rescan,
    )
    relation_root, revision = universal_application_module.connect_universal_roots(
        universal_store,
        universal_registry,
        source_node["id"],
        target["owner"],
        source_interface=source_port["id"],
        target_interface=target["id"],
        leased_projection=projection,
    )

    assert revision == universal_store.revision
    assert relation_root in universal_store.snapshot().cells


def test_browser_history_routes_append_session_scoped_move_compensations():
    universal_store, universal_registry = build_universal_application(
        resolve_map_path()
    )
    server = ApplicationServer(
        universal_store=universal_store,
        universal_registry=universal_registry,
    ).start()
    try:
        token = server.browser_session_token
        status, original = _json(
            server.url, "/api/universal/canvas", token=token
        )
        assert status == 200
        root = original["nodes"][0]["id"]
        original_node = next(
            node for node in original["nodes"] if node["id"] == root
        )
        moved_x = float(original_node["x"]) + 144.0
        moved_y = float(original_node["y"]) + 96.0

        status, moved = _json(
            server.url,
            "/api/universal/move",
            {"root": root, "x": moved_x, "y": moved_y},
            token=token,
        )
        assert status == 200
        moved_node = next(node for node in moved["nodes"] if node["id"] == root)
        assert (float(moved_node["x"]), float(moved_node["y"])) == (
            moved_x, moved_y
        )
        moved_controls = {
            control["owner"]: control
            for control in moved["configuration"]["design_system"]
            ["control_catalog"]["controls"]
        }
        assert moved_controls["app:control:canvas:undo"]["applicable"] is True
        assert moved_controls["app:control:canvas:redo"]["applicable"] is False

        status, undone_delta = _json(
            server.url,
            "/api/universal/interaction",
            _interaction_request(
                moved,
                "app:control:canvas:undo",
                projection_mode="topology-delta-v1",
            ),
            token=token,
        )
        assert status == 200
        undone = _merge_canvas_delta(moved, undone_delta)
        undone_node = next(
            node for node in undone["nodes"] if node["id"] == root
        )
        assert (float(undone_node["x"]), float(undone_node["y"])) == (
            float(original_node["x"]), float(original_node["y"])
        )
        undone_controls = {
            control["owner"]: control
            for control in undone["control_state"]["controls"]
        }
        assert undone_controls["app:control:canvas:undo"]["applicable"] is False
        assert undone_controls["app:control:canvas:redo"]["applicable"] is True

        status, redone_delta = _json(
            server.url,
            "/api/universal/interaction",
            _interaction_request(
                undone,
                "app:control:canvas:redo",
                projection_mode="topology-delta-v1",
            ),
            token=token,
        )
        assert status == 200
        redone = _merge_canvas_delta(undone, redone_delta)
        redone_node = next(
            node for node in redone["nodes"] if node["id"] == root
        )
        assert (float(redone_node["x"]), float(redone_node["y"])) == (
            moved_x, moved_y
        )
        history_root = universal_registry.view_sessions[
            universal_registry.authorization.subject_root
        ].action_history_root
        history = read_relation(
            universal_store.snapshot(), history_root, budget=128
        )
        assert len(history) == 3
        assert redone["touched"] == universal_store.revision
        for path, payload in (
            ("/api/universal/control", {"binding": "forged", "revision": 0}),
            ("/api/universal/undo", {}),
            ("/api/universal/redo", {}),
        ):
            status, denied = _json(server.url, path, payload, token=token)
            assert status == 404
            assert denied["error"] == "not found"
    finally:
        server.close()


def test_relation_interactions_accept_only_the_session_owned_cell_draft():
    universal_store, universal_registry = build_universal_application(
        resolve_map_path()
    )
    participant_root = "court:http-relation-composer:terminal"
    universal_store.commit(universal_store.revision, create=(
        Cell(participant_root, NULL_CELL_ID, NULL_CELL_ID, b"Court value"),
    ))
    canvas_patch = prepare_append_relation_members(
        universal_store.snapshot(),
        universal_registry.canvas_root,
        ((universal_registry.roles["member"], participant_root),),
        budget=100_000,
    )
    universal_store.commit(
        universal_store.revision,
        create=canvas_patch.create,
        replace=canvas_patch.replace,
    )
    view = universal_registry.view_sessions[
        universal_registry.authorization.subject_root
    ]
    administrator = universal_registry.authorization.subject_root
    universal_application_module._issue_resource_audience_bindings(
        universal_store,
        universal_registry.authorization,
        resource_roots=(participant_root,),
        lifecycle_root=(
            universal_registry.standard_library.lifecycle_protocol.states["wip"]
        ),
        owner_root=view.subject_root,
        administrator_root=administrator,
    )
    grants = universal_application_module._issue_view_projection_grants(
        universal_store,
        universal_registry.authorization,
        subject_root=view.subject_root,
        visibility_root=view.visibility_root,
        target_roots=(participant_root,),
        administrator_root=administrator,
    )
    snapshot = universal_store.snapshot()
    visibility_patch = prepare_append_relation_members(
        snapshot,
        view.visibility_root,
        ((universal_registry.roles["visible"], participant_root),),
        budget=100_000,
    )
    session_patch = prepare_append_relation_members(
        snapshot,
        view.root_id,
        ((universal_registry.roles["relation"], root) for root in grants),
        budget=100_000,
    )
    universal_store.commit(
        snapshot.revision,
        create=(*visibility_patch.create, *session_patch.create),
        replace=(*visibility_patch.replace, *session_patch.replace),
    )

    server = ApplicationServer(
        universal_store=universal_store,
        universal_registry=universal_registry,
    ).start()
    try:
        token = server.browser_session_token
        status, canvas = _json(
            server.url, "/api/universal/canvas", token=token
        )
        assert status == 200
        definition = next(
            item for item in canvas["catalog"]
            if item["name"] == "Model Descriptor"
        )
        status, selected = _json(
            server.url,
            "/api/universal/gesture",
            {"roots": [], "focus": definition["id"], "projection": True},
            token=token,
        )
        assert status == 200, selected
        composer = selected["selected_definition"]["composer"]
        while True:
            empty = next((
                (role, entry)
                for role in composer["roles"]
                for entry in role["entries"]
                if not entry["value"]
            ), None)
            if empty is None:
                break
            role, entry = empty
            request = _event_fact_interaction_request(
                selected,
                entry["select_control"],
                {"relation-participant-index": 1},
            )
            assert not {
                "definition", "action", "role", "entry", "participant"
            } & set(request)
            status, selected_delta = _json(
                server.url,
                "/api/universal/interaction",
                request,
                token=token,
            )
            assert status == 200
            selected = _merge_canvas_delta(selected, selected_delta)
            composer = selected["selected_definition"]["composer"]

        position_request = _event_fact_interaction_request(
            selected,
            composer["position_control"],
            {"canvas-point-x": 420, "canvas-point-y": 260},
        )
        status, positioned_delta = _json(
            server.url,
            "/api/universal/interaction",
            position_request,
            token=token,
        )
        assert status == 200
        positioned = _merge_canvas_delta(selected, positioned_delta)
        composer = positioned["selected_definition"]["composer"]
        assert composer["x"] == 420.0
        assert composer["y"] == 260.0
        draft = read_relation_composer_draft(
            universal_store.snapshot(),
            universal_registry.relation_composer_protocol,
            view.root_id,
        )
        assert draft is not None
        assert draft.definition_root == definition["id"]
        assert all(entry.participant_root for entry in draft.entries)

        forged = _interaction_request(
            positioned,
            composer["create_control"],
            projection_mode="topology-delta-v1",
        )
        forged["participant"] = participant_root
        status, denied = _json(
            server.url,
            "/api/universal/interaction",
            forged,
            token=token,
        )
        assert status == 400
        assert "undeclared facts" in denied["error"]

        create_request = _interaction_request(
            positioned,
            composer["create_control"],
            projection_mode="topology-delta-v1",
        )
        status, created_delta = _json(
            server.url,
            "/api/universal/interaction",
            create_request,
            token=token,
        )
        assert status == 200
        created = _merge_canvas_delta(positioned, created_delta)
        assert created["created_root"] in {
            node["id"] for node in created["nodes"]
        }
        cleared = read_relation_composer_draft(
            universal_store.snapshot(),
            universal_registry.relation_composer_protocol,
            view.root_id,
        )
        assert cleared is not None
        assert cleared.definition_root is None
        assert cleared.entries == ()
        assert cleared.x is None and cleared.y is None
        for retired_path, retired_payload in (
            (
                "/api/universal/relation-composer",
                {"definition": definition["id"], "action": "initialize"},
            ),
            (
                "/api/universal/relation-create",
                {"definition": definition["id"]},
            ),
        ):
            status, denied = _json(
                server.url, retired_path, retired_payload, token=token
            )
            assert status == 404
            assert denied == {"ok": False, "error": "not found"}
    finally:
        server.close()
