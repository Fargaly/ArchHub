"""Permanent anti-drift gates for the replacement node-native application."""
from pathlib import Path

from nodelang import Store, validate_store
from nodelang.core import relation_endpoints


ROOT = Path(__file__).resolve().parents[1]
STRICT_SOURCE = ROOT / "nodelang"


def test_strict_kernel_never_imports_legacy_application():
    forbidden = (
        "12.PRODUCTION",
        "app.workflows",
        "studio-lm",
        "node_lang.py",
        "personal_brain_mcp",
    )
    for path in STRICT_SOURCE.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        for marker in forbidden:
            assert marker not in source, f"{path.name} imports legacy authority: {marker}"


def test_relation_is_openable_endpoint_parameter_graph_not_pair_record():
    store = Store()
    source = store.add("value", "source", floor={"op": "value", "value": 7})
    target = store.add("op", "target", floor={"op": "merge", "fn": "first"})
    relation = store.wire(source, target)
    node = store.nodes[relation]

    assert "inner" in node["body"]
    assert "floor" not in node["body"]
    assert set(node["body"].keys()) == {"inner"}
    assert all(store.nodes[node["params"][name]]["kind"] == "param"
               for name in node["params"] if name.startswith("endpoint:"))
    assert [(ep["role"], ep["node_id"]) for ep in relation_endpoints(store.nodes, node)] == [
        ("source", source), ("target", target)
    ]
    assert store.pull(target) == 7
    assert validate_store(store) is True


def test_relation_storage_contains_no_authoritative_from_to_fields():
    source = (STRICT_SOURCE / "core.py").read_text(encoding="utf-8")
    assert "if op == 'wire'" not in source
    assert "{'op': 'wire', 'from':" not in source
    assert "w['body']['floor']['to']" not in source
    assert "w['body']['floor']['from']" not in source


def test_relation_stage_authority_is_not_hidden_in_metadata():
    source = (STRICT_SOURCE / "core.py").read_text(encoding="utf-8")
    structure = (STRICT_SOURCE / "laws_structure.py").read_text(encoding="utf-8")
    assert "meta'].get('stage_nodes'" not in source
    assert "['meta', 'stage_nodes']" not in structure


def test_new_application_never_imports_or_calls_the_previous_runtime():
    for name in ('application.py', 'application_server.py', 'ui_runtime.py'):
        source = (STRICT_SOURCE / name).read_text(encoding='utf-8')
        assert '12.PRODUCTION' not in source
        assert 'studio-lm' not in source
        assert 'app.workflows' not in source
