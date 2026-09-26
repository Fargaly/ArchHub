"""Court: the application's Brain answers from the graph; nothing dials :8473.

The personal-brain daemon is retired; its store is ported into the graph. The
brain cards, the Brain panel (list, edit, forget, remember), the map's brain
facts, the resource probe and the governance probes all answer from
``nodelang.app_brain`` over the running application's graph. With no
application bound they say so -- never a network fallback.
"""
from __future__ import annotations

import json
import socket
from pathlib import Path
from types import SimpleNamespace

import pytest

from nodelang import app_brain, pipeline_engines
from nodelang.brain_store_port import FOUNDER_OWNER_ROOT, ensure_port_session
from nodelang.cell_brain_memory import remember
from nodelang.cell_catalog import bootstrap_assembly_protocol
from nodelang.governance_probe import run_governance_probe
from nodelang.resource_probe import run_resource_probe
from nodelang.universal_cell import NULL_CELL_ID, Cell, CellStore

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def no_network(monkeypatch):
    def refuse(*_args, **_kwargs):
        raise AssertionError("the application Brain dialed the network")
    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)


@pytest.fixture
def brain(no_network):
    store = CellStore()
    protocol = bootstrap_assembly_protocol(store)
    store.commit(store.snapshot().revision, create=(
        Cell(FOUNDER_OWNER_ROOT, NULL_CELL_ID, NULL_CELL_ID, b"founder"),))
    session = ensure_port_session(store)
    remember(store, session_root=session, fragment_id="f-walls", text="Exterior walls are 200 mm",
             kind="fact", origin="court", clock=1000, confidence="extracted")
    remember(store, session_root=session, fragment_id="f-sheets", text="Client prefers A3 sheets",
             kind="fact", origin="court", clock=1001, confidence="extracted")
    registry = SimpleNamespace(authorization=SimpleNamespace(subject_root=FOUNDER_OWNER_ROOT),
                               assembly_protocol=protocol)
    app_brain.bind(store, registry)
    yield store
    app_brain.unbind(store)


def test_unbound_the_cards_say_so_and_dial_nothing(no_network):
    app_brain.unbind()
    _out, said = pipeline_engines.brain_facts({}, {})
    assert said == "no fact count: no application Brain is bound in this process"
    _out, said = pipeline_engines.brain_recall({"prompt": "walls"}, {})
    assert said.startswith("no recall: no application Brain")


def test_the_cards_read_the_graph(brain):
    out, said = pipeline_engines.brain_facts({}, {})
    assert out["facts"] == 2 and said.startswith("2 fact row(s) in the brain")
    out, said = pipeline_engines.brain_recall({"prompt": "how thick are the walls"}, {})
    assert out["out"] == "- Exterior walls are 200 mm" and said.startswith("1 context line(s)")


def test_the_brain_panel_edits_forgets_and_remembers_in_the_graph(brain):
    listing = json.loads(pipeline_engines._brain_call("brain.list_facts", {"limit": 10}))
    assert listing["held"] == 2 and {f["id"] for folder in listing["folders"] for f in folder["facts"]} == {
        "f-walls", "f-sheets"}
    assert json.loads(pipeline_engines._brain_call("brain.edit_fact", {
        "fragment_id": "f-walls", "text": "Exterior walls are 250 mm"}))["edited"] is True
    assert json.loads(pipeline_engines._brain_call("brain.delete_fact", {"fragment_id": "f-sheets"}))["ok"]
    assert json.loads(pipeline_engines._brain_call("brain.write", {"ops": [
        {"op": "add", "fragment": {"id": "f-new", "kind": "fact", "text": "Doors are 900 mm"}}]}))["written"] == 1
    held = json.loads(pipeline_engines._brain_call("brain.list_facts", {}))
    texts = {f["id"]: f["body"] for folder in held["folders"] for f in folder["facts"]}
    assert texts == {"f-walls": "Exterior walls are 250 mm", "f-new": "Doors are 900 mm"}


def test_a_tool_the_application_brain_does_not_provide_is_named(brain):
    with pytest.raises(pipeline_engines.BrainSilent, match="does not provide brain.grand_map_work_sync"):
        pipeline_engines._brain_call("brain.grand_map_work_sync", {})


def test_the_resource_and_governance_probes_ask_the_application_brain(brain, tmp_path, monkeypatch):
    probe = run_resource_probe({"locator": "authority://application-brain"})
    assert probe["ok"] is True and probe["detail"] == "application Brain holds 2 fact(s)"
    health = run_governance_probe({"check": "brain-health"})
    assert health["ok"] is True and health["detail"] == "brain.health reachable"
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    coverage = run_governance_probe({"check": "hook-coverage"})
    assert coverage["ok"] is False and coverage["status"] == "missing"   # no client configs here


def test_no_product_code_dials_the_retired_brain_port():
    for path in list((ROOT / "nodelang").rglob("*.py")) + [ROOT / "launch_archhub_test.py"]:
        text = path.read_text(encoding="utf-8")
        assert "http://127.0.0.1:8473" not in text and "BRAIN_DAEMON_URL" not in text, path.name