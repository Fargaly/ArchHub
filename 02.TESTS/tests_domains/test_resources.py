from pathlib import Path

import pytest

from nodelang.core import FrozenNode, NO_VALUE, Store, relation_sources, relation_targets
from nodelang.domains.resources import (
    bind_resource_authority,
    build_resource_domain,
    connect_resource,
    resource_status,
)
from nodelang.laws_effect import apply_effect
from nodelang.resource_probe import run_resource_probe


def _resource(locator, *, write_enabled=False):
    return {
        "id": "test-resource",
        "title": "Test resource",
        "resource_type": "urn:test:resource",
        "locator": locator,
        "privacy_tier": "T1 INTERNAL",
        "lifecycle": "WIP",
        "schema_ref": "urn:test:schema",
        "schema_version": "1",
        "read_enabled": True,
        "write_enabled": write_enabled,
        "founder_only": True,
        "probe": {"mode": "resource"},
        "ports": [
            {"id": "read", "direction": "out", "logical_type": "urn:test:value"},
            {"id": "write", "direction": "in", "logical_type": "urn:test:value"},
        ],
    }


def _pairs(store):
    pairs = set()
    for relation in store.nodes.values():
        if relation["kind"] != "wire":
            continue
        for source in relation_sources(store.nodes, relation):
            for target in relation_targets(store.nodes, relation):
                pairs.add((source["node_id"], target["node_id"]))
    return pairs


def test_resource_adapter_is_an_open_node_composition_with_parameter_ports(tmp_path, monkeypatch):
    root = tmp_path / "workspace"
    target = root / "00.GOVERNANCE" / "WORKSPACE-STANDARD.md"
    target.parent.mkdir(parents=True)
    target.write_text("authority", encoding="utf-8")
    monkeypatch.setenv("ARCHHUB_WORKSPACE_ROOT", str(root))

    store = Store()
    domain = build_resource_domain(
        store,
        resources=[_resource("workspace://00.GOVERNANCE/WORKSPACE-STANDARD.md")],
    )
    resource = domain["resources"]["test-resource"]

    assert store.open(resource["adapter"])
    assert set(resource["ports"]) == {"read", "write"}
    assert all(store.nodes[node_id]["kind"] == "param" for node_id in resource["ports"].values())
    assert store.pull(resource["probe"])["ok"] is True
    assert store.pull(resource["health_ok"]) == 1.0
    assert resource_status(store, domain, "test-resource")["status"] == "readable"


def test_resource_write_requires_live_health_explicit_policy_founder_signal_and_unfreeze(
    tmp_path, monkeypatch,
):
    root = tmp_path / "workspace"
    target = root / "resource.json"
    root.mkdir(parents=True)
    target.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("ARCHHUB_WORKSPACE_ROOT", str(root))

    store = Store()
    domain = build_resource_domain(
        store, resources=[_resource("workspace://resource.json", write_enabled=True)]
    )
    resource = domain["resources"]["test-resource"]
    founder = store.add("value", "Founder verdict", floor={"op": "value", "value": False})
    authority_relation = bind_resource_authority(store, resource, founder)

    assert (founder, resource["authority_signal"]) in _pairs(store)
    assert authority_relation in store.nodes[founder]["relations"]
    assert store.pull(resource["write_gate"]) == 0
    assert store.pull(resource["write_relation"]) is NO_VALUE

    store.edit(founder, ["body", "floor", "value"], True, actor="founder")
    assert store.pull(resource["write_gate"]) == 1
    assert store.pull(resource["write_relation"])["resource_id"] == "test-resource"

    with pytest.raises(FrozenNode):
        apply_effect(store, resource["effect"], {})
    store.apply_op({"op": "unfreeze", "id": resource["effect"], "actor": "founder"})
    sink = {}
    result = apply_effect(store, resource["effect"], sink, actor="founder")
    assert result["fired"] is True
    assert sink["workspace://resource.json"]["resource_id"] == "test-resource"


def test_computed_guard_blocks_an_unfrozen_effect_when_founder_authority_is_false(
    tmp_path, monkeypatch,
):
    root = tmp_path / "workspace"
    root.mkdir(parents=True)
    (root / "resource.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("ARCHHUB_WORKSPACE_ROOT", str(root))
    store = Store()
    domain = build_resource_domain(
        store, resources=[_resource("workspace://resource.json", write_enabled=True)]
    )
    resource = domain["resources"]["test-resource"]
    founder = store.add("value", "Founder verdict", floor={"op": "value", "value": False})
    bind_resource_authority(store, resource, founder)
    store.apply_op({"op": "unfreeze", "id": resource["effect"], "actor": "founder"})

    with pytest.raises(FrozenNode, match="computed guard"):
        apply_effect(store, resource["effect"], {}, actor="founder")


def test_resource_connections_are_payload_described_authoritative_relations():
    store = Store()
    domain = build_resource_domain(
        store, resources=[_resource("service://unconfigured")]
    )
    target = store.add("group", "Consumer", inner=[])
    relation = connect_resource(
        store, domain, "test-resource", target, target_port="resource"
    )
    relation_node = store.nodes[relation]

    assert (domain["resources"]["test-resource"]["adapter"], target) in _pairs(store)
    assert "payload" in relation_node["params"]
    payload_ref = relation_node["params"]["payload"]
    envelope = store.nodes[payload_ref]["body"]["floor"]["target"]
    assert store.pull(store.nodes[envelope]["params"]["logical_type"]) == "urn:test:resource"
    assert resource_status(store, domain, "test-resource")["status"] == "offline"


def test_raw_secret_values_are_rejected():
    store = Store()
    raw = _resource("service://provider")
    raw["probe"] = {"mode": "resource", "api_key": "sk-not-allowed"}
    with pytest.raises(ValueError, match="secret"):
        build_resource_domain(store, resources=[raw])


def test_http_resource_probe_can_execute_a_json_health_contract(monkeypatch):
    observed = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def getcode(self):
            return 200

        def read(self, _limit):
            return b'event: message\ndata: {"jsonrpc":"2.0","result":{"ok":true}}\n\n'

    def fake_urlopen(request, timeout):
        observed.update(url=request.full_url, method=request.method,
                        data=request.data, timeout=timeout,
                        accept=request.headers.get("Accept"))
        return Response()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    result = run_resource_probe({
        "locator": "http://127.0.0.1:8473/mcp", "method": "POST",
        "headers": {"Accept": "application/json, text/event-stream"},
        "json": {"jsonrpc": "2.0", "method": "tools/call",
                 "params": {"name": "brain.health", "arguments": {}}},
        "contains": "\"result\"", "timeout": 2.0,
    })

    assert result["ok"] is True
    assert observed["method"] == "POST"
    assert b'"brain.health"' in observed["data"]
    assert observed["accept"] == "application/json, text/event-stream"


def test_http_resource_probe_can_select_one_capability_from_a_shared_report(monkeypatch):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def getcode(self):
            return 200

        def read(self, _limit):
            return (b'{"capabilities":{"database":{"ok":true},'
                    b'"email":{"ok":false}}}')

    monkeypatch.setattr("urllib.request.urlopen", lambda *_args, **_kwargs: Response())
    base = {
        "locator": "https://cloud.example/readyz",
        "response_path": ["capabilities", "database", "ok"],
        "expected_value": True,
    }
    assert run_resource_probe(base)["ok"] is True
    base["response_path"] = ["capabilities", "email", "ok"]
    assert run_resource_probe(base)["ok"] is False
