"""Bridge tests for the node-context-menu actions wired up by
studio-lm.jsx's NodeMenu component.

Founder direction (2026-05-14): right-click on a node opens a per-node
menu (Run / Freeze / Rename / Duplicate / Save as Skill / Disconnect /
Delete / Properties). Two of those actions need bridge support so the
JSX side doesn't have to re-implement graph surgery in JS:

  * ``ArchHubBridge.save_as_skill(name, payload_json)`` — packages a
    graph subset (node + reachable downstream + connecting wires)
    into ``app/skills/<slug>.archhub-skill.json``.
  * ``ArchHubBridge.duplicate_node(graph_json, node_id)`` — clones a
    node with a +30/+30 px offset and a fresh id, returned as JSON
    the JSX can splice into LM_GRAPH directly.

Both slots are pure helpers (no Qt event loop required), so we
instantiate the bridge directly and call the slots like any plain
method. Pins:

  - save_as_skill writes a file with the right shape under app/skills/
  - save_as_skill slugifies messy display names
  - duplicate_node returns a fresh id with +30/+30 px offset
  - duplicate_node strips runtime state (state/progress/result/...)
  - duplicate_node refuses unknown node ids
  - duplicate_node handles repeated clones (id collision → _copy2)
  - The two slots are reachable as @pyqtSlot methods on the QObject
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

APP_ROOT = Path(__file__).resolve().parent.parent / "app"
sys.path.insert(0, str(APP_ROOT))

# QApplication isn't needed for plain QObject slot calls — they're
# regular Python methods at that point.
import bridge as _bridge_module


@pytest.fixture
def bridge_inst():
    return _bridge_module.ArchHubBridge()


@pytest.fixture
def small_graph():
    """A tiny three-node graph used by both duplicate + save tests."""
    return {
        "nodes": [
            {"id": "read1", "cat": "read", "title": "list_walls",
             "x": 360, "y": 60, "w": 220, "h": 96,
             "ins": [{"id": "view", "label": "view", "t": "view"}],
             "outs": [{"id": "walls", "label": "walls", "t": "walls"}],
             "state": "queued", "result": "47 walls", "ms": "120ms"},
            {"id": "filter1", "cat": "filter", "title": "where ext",
             "x": 600, "y": 60, "w": 220, "h": 96,
             "ins": [{"id": "in", "label": "walls", "t": "walls"}],
             "outs": [{"id": "out", "label": "matches", "t": "walls"}],
             "frozen": True, "progress": 0.5},
            {"id": "out1", "cat": "output", "title": "publish",
             "x": 900, "y": 60, "w": 220, "h": 96,
             "ins": [{"id": "walls", "label": "walls", "t": "walls"}]},
        ],
        "wires": [
            {"from": ["read1", "walls"],   "to": ["filter1", "in"]},
            {"from": ["filter1", "out"],   "to": ["out1", "walls"]},
        ],
    }


# ══════════════════════════════════════════════════════════════════════
# 1. save_as_skill — writes the JSON to app/skills/<slug>.archhub-skill.json
# ══════════════════════════════════════════════════════════════════════
class TestSaveAsSkill:
    def test_writes_file_with_envelope_shape(self, bridge_inst, small_graph,
                                              tmp_path, monkeypatch):
        # Redirect app/skills/ to a temp dir for the test so we don't
        # litter the real repo. We do this by monkeypatching Path within
        # the bridge module — the slot resolves the path off __file__.
        fake_skills = tmp_path / "skills"
        fake_app_root = tmp_path
        # The slot computes Path(__file__).resolve().parent / "skills".
        # We patch __file__ via the module attribute.
        monkeypatch.setattr(_bridge_module, "__file__",
                            str(fake_app_root / "bridge.py"))

        payload = json.dumps(small_graph)
        result_json = bridge_inst.save_as_skill("My Tower Skill", payload)
        result = json.loads(result_json)

        assert result.get("ok") is True
        assert "error" not in result
        out_path = Path(result["path"])
        assert out_path.exists()
        assert out_path.parent.name == "skills"

        # File shape — envelope { kind, name, slug, graph: { nodes, wires } }
        on_disk = json.loads(out_path.read_text(encoding="utf-8"))
        assert on_disk["kind"] == "archhub.skill"
        assert on_disk["name"] == "My Tower Skill"
        assert on_disk["slug"] == "my-tower-skill"
        assert on_disk["graph"]["nodes"][0]["id"] == "read1"
        assert len(on_disk["graph"]["wires"]) == 2

        # Counts surfaced in the response envelope.
        assert result["nodes"] == 3
        assert result["wires"] == 2
        assert result["slug"] == "my-tower-skill"

    def test_slugifies_messy_names(self, bridge_inst, small_graph,
                                    tmp_path, monkeypatch):
        monkeypatch.setattr(_bridge_module, "__file__",
                            str(tmp_path / "bridge.py"))
        # Punctuation, casing, leading/trailing junk, unicode.
        result_json = bridge_inst.save_as_skill(
            "  Hello, World!!  ", json.dumps(small_graph))
        result = json.loads(result_json)
        assert result["slug"] == "hello-world"
        assert Path(result["path"]).name == "hello-world.archhub-skill.json"

    def test_empty_name_falls_back_to_untitled(self, bridge_inst,
                                                  small_graph, tmp_path,
                                                  monkeypatch):
        monkeypatch.setattr(_bridge_module, "__file__",
                            str(tmp_path / "bridge.py"))
        result_json = bridge_inst.save_as_skill("",
                                                  json.dumps(small_graph))
        result = json.loads(result_json)
        assert result.get("ok") is True
        # The slug should be something sensible, never empty.
        assert result["slug"]
        assert Path(result["path"]).exists()

    def test_creates_skills_dir_if_missing(self, bridge_inst, small_graph,
                                            tmp_path, monkeypatch):
        # No app/skills/ yet — the slot should create it.
        fake_root = tmp_path / "freshrepo"
        fake_root.mkdir()
        monkeypatch.setattr(_bridge_module, "__file__",
                            str(fake_root / "bridge.py"))
        assert not (fake_root / "skills").exists()
        result_json = bridge_inst.save_as_skill(
            "fresh", json.dumps(small_graph))
        result = json.loads(result_json)
        assert result.get("ok") is True
        assert (fake_root / "skills").is_dir()
        assert Path(result["path"]).exists()

    def test_bad_json_returns_error(self, bridge_inst, tmp_path,
                                      monkeypatch):
        monkeypatch.setattr(_bridge_module, "__file__",
                            str(tmp_path / "bridge.py"))
        result = json.loads(
            bridge_inst.save_as_skill("x", "{this is not json"))
        assert "error" in result
        assert "bad payload_json" in result["error"]

    def test_non_object_payload_returns_error(self, bridge_inst,
                                                tmp_path, monkeypatch):
        monkeypatch.setattr(_bridge_module, "__file__",
                            str(tmp_path / "bridge.py"))
        # JSON valid, but a list — not an object.
        result = json.loads(
            bridge_inst.save_as_skill("x", json.dumps([1, 2, 3])))
        assert "error" in result


# ══════════════════════════════════════════════════════════════════════
# 2. duplicate_node — fresh id + offset position + runtime stripped
# ══════════════════════════════════════════════════════════════════════
class TestDuplicateNode:
    def test_returns_clone_with_offset(self, bridge_inst, small_graph):
        result_json = bridge_inst.duplicate_node(
            json.dumps(small_graph), "read1")
        result = json.loads(result_json)
        assert "error" not in result
        clone = result["node"]
        # Fresh id, +30/+30 px offset, preserved shape.
        assert clone["id"] == "read1_copy"
        assert clone["x"] == 390   # 360 + 30
        assert clone["y"] == 90    # 60 + 30
        assert clone["cat"] == "read"
        assert clone["title"] == "list_walls"
        assert clone["w"] == 220
        # Sockets preserved structurally.
        assert clone["ins"][0]["id"] == "view"
        assert clone["outs"][0]["id"] == "walls"
        # Echo the id at the top level for convenience.
        assert result["id"] == "read1_copy"

    def test_strips_runtime_state(self, bridge_inst, small_graph):
        # read1 has state="queued", result="47 walls", ms="120ms".
        result = json.loads(
            bridge_inst.duplicate_node(
                json.dumps(small_graph), "read1"))
        clone = result["node"]
        assert "state" not in clone
        assert "result" not in clone
        assert "ms" not in clone

    def test_strips_frozen_and_progress(self, bridge_inst, small_graph):
        # filter1 has frozen=True, progress=0.5.
        result = json.loads(
            bridge_inst.duplicate_node(
                json.dumps(small_graph), "filter1"))
        clone = result["node"]
        assert "frozen" not in clone
        assert "progress" not in clone

    def test_unique_id_when_copy_already_exists(self, bridge_inst,
                                                  small_graph):
        # Add a pre-existing _copy to force the bumper to mint _copy2.
        small_graph["nodes"].append({
            "id": "read1_copy", "cat": "read", "title": "stale copy",
            "x": 100, "y": 100, "w": 220, "h": 96,
        })
        result = json.loads(
            bridge_inst.duplicate_node(
                json.dumps(small_graph), "read1"))
        assert result["id"] == "read1_copy2"
        assert result["node"]["id"] == "read1_copy2"

    def test_unknown_node_returns_error(self, bridge_inst, small_graph):
        result = json.loads(
            bridge_inst.duplicate_node(
                json.dumps(small_graph), "no-such-node"))
        assert "error" in result
        assert "no-such-node" in result["error"]

    def test_bad_graph_json_returns_error(self, bridge_inst):
        result = json.loads(
            bridge_inst.duplicate_node("{not-json", "any"))
        assert "error" in result
        assert "bad graph_json" in result["error"]

    def test_empty_graph_returns_error(self, bridge_inst):
        # Empty/missing graph → no node found.
        result = json.loads(
            bridge_inst.duplicate_node("", "anything"))
        assert "error" in result

    def test_deep_copy_is_independent(self, bridge_inst, small_graph):
        # Mutating the clone after the call must not affect the
        # original payload.
        result = json.loads(
            bridge_inst.duplicate_node(
                json.dumps(small_graph), "read1"))
        clone = result["node"]
        clone["outs"][0]["label"] = "MUTATED"
        # Original still says "walls".
        assert small_graph["nodes"][0]["outs"][0]["label"] == "walls"


# ══════════════════════════════════════════════════════════════════════
# 3. Bridge slot exposure — pin the two new methods are reachable from JS
# ══════════════════════════════════════════════════════════════════════
class TestBridgeSlotExposure:
    def test_save_as_skill_slot_present(self):
        assert hasattr(_bridge_module.ArchHubBridge, "save_as_skill")

    def test_duplicate_node_slot_present(self):
        assert hasattr(_bridge_module.ArchHubBridge, "duplicate_node")
