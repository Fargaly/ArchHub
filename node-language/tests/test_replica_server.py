import json
import sys
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from legacy_engine import grand_replica_server


def get_json(url):
    with urllib.request.urlopen(url, timeout=120) as resp:
        assert resp.status == 200
        return json.loads(resp.read().decode("utf-8"))


def post_json(url, payload):
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        assert resp.status == 200
        return json.loads(resp.read().decode("utf-8"))


@pytest.fixture(scope="module")
def replica_server():
    server = grand_replica_server.ReplicaServer(port=0).start()
    try:
        yield server
    finally:
        server.stop()


@pytest.fixture(scope="module")
def api_state(replica_server):
    return get_json(replica_server.url + "/api/state")


def test_api_state_returns_domains_and_real_nodes_with_live_values(api_state):
    domains = [nid for nid in api_state if nid.startswith("domain:")]
    assert len(domains) == 15
    assert "domain:ui" in api_state
    assert api_state["domain:ui"]["kind"] == "group"

    real_nodes = [
        node
        for node in api_state.values()
        if node["kind"] in {"host_read", "probe"}
    ]
    assert real_nodes
    assert any(node["value"] is not None for node in real_nodes)
    assert any(
        isinstance(node["value"], (int, float, bool, str, list, dict))
        for node in real_nodes
    )


def test_editing_vision_status_recooks_node_and_domain(replica_server, api_state):
    target_id = None
    for nid, node in api_state.items():
        if node["kind"] != "status_score":
            continue
        if node["params"].get("status") != "vision":
            continue
        if node.get("domain") == "domain:ui":
            target_id = nid
            break
    assert target_id is not None

    resp = post_json(
        replica_server.url + "/edit",
        {"id": target_id, "key": "status", "val": "live"},
    )

    assert resp["ok"] is True
    assert resp["id"] == target_id
    assert resp["before"] == 0.0
    assert resp["value"] == 1.0
    assert resp["value"] > resp["before"]
    assert resp["domain"]["id"] == "domain:ui"
    # the domain re-cooked: one more of its nodes is LIVE now (real live-count).
    assert resp["domain"]["value"] > resp["domain"]["before"]
    # the group node's live value carries the real {live_nodes,total}.
    assert isinstance(resp["domain"]["group_value"], dict)
    assert resp["domain"]["group_value"]["live_nodes"] >= 1


def test_home_page_renders_arch_and_domain_key(replica_server):
    with urllib.request.urlopen(replica_server.url + "/", timeout=120) as resp:
        assert resp.status == 200
        html = resp.read().decode("utf-8")

    assert "ARCH" in html
    assert "domain:ui" in html
