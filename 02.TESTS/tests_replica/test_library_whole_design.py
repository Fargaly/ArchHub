"""Behavioral verification for AG-10, AG-11, AG-12, AG-12a..d, and AG-16 (Library whole design)."""
from __future__ import annotations

import asyncio
import base64
import json
import re
from pathlib import Path

import pytest

from nodelang import host_brokers, nodeslib_v2_engines
from nodelang.canvas_documents import is_pure, solve
from nodelang.hook_decision import _RELEASING
from nodelang.library_engines import (
    LIBRARY_ITEMS_WITHOUT_ENGINE,
    LIBRARY_TREE,
    NOT_BUILT,
    check_model_engine,
    library_catalogue,
    model_json_engine,
    place_views_on_sheets_engine,
    remote_tunnel_engine,
)
from nodelang.native_agent_mcp import build_server
from nodelang.native_host_tools import HOST_TOOLS, HostToolRefused
from nodelang.pipeline_engines import PIPELINE_ENGINES
from nodelang.session_files import new_document, read_document, sessions_directory, write_document

PNG_1X1_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


EXPECTED_LIBCATS = [
    ("host", "Programs", "canvas"),
    ("file", "Files", "folder"),
    ("skill", "Workflows and skills", "group"),
    ("trigger", "Starts a run", "clock"),
    ("governance", "Checks and standards", "check"),
    ("ai", "Agents and AI", "brain"),
    ("shape", "Lists and data", "library"),
    ("transform", "Change geometry", "arrange"),
    ("logic", "Decide and branch", "arrange"),
    ("input", "Inputs and project data", "settings"),
    ("math", "Maths", "code"),
    ("text", "Text", "edit"),
    ("document", "Drawings and media", "docs"),
    ("watch", "Watch for changes", "eye"),
    ("output", "Deliver and send", "send"),
    ("note", "Notes and team", "users"),
    ("connect", "Connected services and scripts", "link"),
    ("office", "Office library (BABOOM)", "library"),
    ("settings", "Settings", "settings"),
]


def _isolate_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    for name in ("LOCALAPPDATA", "APPDATA", "USERPROFILE", "HOME"):
        folder = tmp_path / name
        folder.mkdir(parents=True, exist_ok=True)
        monkeypatch.setenv(name, str(folder))
    state = tmp_path / "LOCALAPPDATA" / "ArchHub"
    state.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("ARCHHUB_TEST_STATE_DIR", str(state))
    return state


def test_library_tree_programs_settings_skills_and_zero_not_built(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _isolate_env(tmp_path, monkeypatch)

    # Save a 3-step workflow skill to verify the exact AG-11 subtitle.
    wf = new_document("Door QA")
    wf["id"] = "door-qa"
    wf["nodes"] = [
        {"id": "n1", "type": "data.constant", "params": {"value": "DOR"}, "position": {"x": 0, "y": 0}},
        {"id": "n2", "type": "office_library.doors", "params": {"search": ""}, "position": {"x": 320, "y": 0}},
        {"id": "n3", "type": "watch.preview", "params": {}, "position": {"x": 640, "y": 0}},
    ]
    write_document(str(sessions_directory() / "door-qa.archhub"), wf)

    assert [(row, label, icon) for row, label, icon, _cats in LIBRARY_TREE] == EXPECTED_LIBCATS
    assert LIBRARY_ITEMS_WITHOUT_ENGINE == {}

    groups = library_catalogue()
    items = [item for group in groups for item in group["items"] if not item.get("hidden")]
    by_id = {item["id"]: item for item in items}

    # Zero Coming soon / NOT_BUILT / inert survivors anywhere in the Library.
    assert not [item["id"] for item in items if item.get("available") is False]
    assert not [item["id"] for item in items if item.get("noEngine")]
    assert not [item["id"] for item in items if item.get("soon")]
    assert not [item["id"] for item in items if item.get("reason") == NOT_BUILT]

    # Skill subtitle uses the exact AG-11 copy.
    assert by_id["skill:door-qa"]["sub"] == "Your workflow · 3 steps · drops in as one node"

    # Host items annotate all 7 canonical programs.
    host_items = [item for item in items if item["cat"] == "host"]
    programs = {item.get("program") for item in host_items if item.get("program")}
    assert {"Revit", "AutoCAD", "Excel", "Outlook", "3ds Max", "Rhino", "Blender"} <= programs

    # All 5 Settings area nodes appear under Settings and execute purely.
    settings_titles = {item["title"] for item in items if item["cat"] == "settings"}
    assert {"Projects", "Agents", "Connections", "Account"} <= settings_titles
    assert ("This PC" in settings_titles) and ("You" in settings_titles)
    for sid, expected_socket in (
        ("settings_projects", "standard"),
        ("settings_agents", "policy"),
        ("settings_connections", "programs"),
        ("settings_account", "account"),
        ("settings_this_pc", "profile"),
    ):
        card = by_id[sid]
        assert card["pure"] is True
        out, _label = PIPELINE_ENGINES[card["engine"]]({}, {})
        assert expected_socket in out and out[expected_socket] != ""


def test_ag16_three_typed_host_nodes_unreachable_and_live_execution(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    state_dir = _isolate_env(tmp_path, monkeypatch)
    items = {item["id"]: item for group in library_catalogue() for item in group["items"]}

    # 1. Exact catalogue contracts for Render a view, Bake geometry, Render scene.
    max_card = items["max_render_view"]
    assert max_card["title"] == "Render a view"
    assert max_card["program"] == "3ds Max"
    assert max_card["engine"] == "max.render_view"
    assert max_card["params"] == {"Camera": "Camera01", "Quality": "Draft"}
    assert {"id": "task", "type": "event"} in max_card["ports"]["target"]
    assert max_card["ports"]["source"] == [{"id": "image", "type": "file"}]
    # A render runs code in 3ds Max and writes a file: an effect behind the Approve card.
    assert max_card["pure"] is False and is_pure("max.render_view") is False
    assert max_card["approvalRequired"] is True
    max_defs = {d["id"]: d for d in max_card["paramDefs"]}
    assert max_defs["Camera"]["type"] == "text"
    assert max_defs["Quality"]["type"] == "choice" and max_defs["Quality"]["options"] == ["Draft", "Final"]

    rhino_card = items["rhino_bake_geometry"]
    assert rhino_card["title"] == "Bake geometry"
    assert rhino_card["program"] == "Rhino"
    assert rhino_card["engine"] == "rhino.bake_geometry"
    assert rhino_card["pure"] is False and is_pure("rhino.bake_geometry") is False
    assert rhino_card["approvalRequired"] is True
    assert rhino_card["params"] == {"Layer": "ArchHub"}
    assert rhino_card["ports"]["source"][0]["id"] == "out" and rhino_card["ports"]["source"][0]["type"] == "elements"
    assert any(p["id"] == "geometry" and p["type"] == "elements" for p in rhino_card["ports"]["target"])

    blender_card = items["blender_render_scene"]
    assert blender_card["title"] == "Render scene"
    assert blender_card["program"] == "Blender"
    assert blender_card["engine"] == "blender.render_scene"
    assert blender_card["params"] == {"Samples": 64}
    assert {"id": "task", "type": "event"} in blender_card["ports"]["target"]
    assert blender_card["ports"]["source"] == [{"id": "image", "type": "file"}]
    assert blender_card["pure"] is False and is_pure("blender.render_scene") is False
    assert blender_card["approvalRequired"] is True
    s_def = next(d for d in blender_card["paramDefs"] if d["id"] == "Samples")
    assert (s_def["type"], s_def["min"], s_def["max"], s_def["step"]) == ("integer", 8, 1024, 8)

    # All 3 are also exposed in HOST_TOOLS (one registry).
    host_tool_ids = {spec["id"] for spec in HOST_TOOLS}
    assert {"max_render_view", "rhino_bake_geometry", "blender_render_scene"} <= host_tool_ids

    # 2. Honest unreachable messages when bridges are closed.
    monkeypatch.setattr(host_brokers, "_max_endpoint", lambda timeout=1.5: None)
    monkeypatch.setattr(host_brokers, "_port_open", lambda port, timeout=0.15: False)

    max_unreach, max_msg = host_brokers.max_render_view({"Camera": "CamA", "Quality": "Draft"}, {})
    assert max_unreach["ok"] is False and max_unreach["image"] == "" and "MaxMCP" in max_msg

    bl_unreach, bl_msg = host_brokers.blender_render_scene({"Samples": 64}, {})
    assert bl_unreach["ok"] is False and bl_unreach["image"] == "" and ":9876" in bl_msg

    # 3. Bake geometry requires Approve / host_effects gate BEFORE touching :9879.
    calls: list[tuple[str, dict]] = []
    monkeypatch.setattr(host_brokers, "_port_open", lambda port, timeout=0.15: True)

    def _extract_out_file(code: str, fallback: Path) -> Path:
        match = re.search(r"out_file\s*=\s*(\"[^\"]+\")", code)
        target = Path(json.loads(match.group(1))) if match else fallback
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(PNG_1X1_BYTES)
        return target

    def fake_bridge_call(url: str, body=None, timeout: float = 20.0):
        payload = dict(body or {})
        calls.append((url, payload))
        if url.endswith("/max-mcp/exec"):
            written = _extract_out_file(payload.get("code", ""), state_dir / "renders" / "max.png")
            return {"status": "ok", "result": json.dumps({"image": str(written), "camera": "HeroCam", "quality": "Final"})}
        if url.endswith(":9879/execute"):
            return {"ok": True, "result": json.dumps({"baked": [{"id": "guid-1", "layer": "Facade", "kind": "line"}], "layer": "Facade", "undoRecord": 7})}
        if url.endswith(":9876/execute"):
            written = _extract_out_file(payload.get("code", ""), state_dir / "renders" / "blender.png")
            return {"ok": True, "result": json.dumps({"image": str(written), "samples": 128})}
        raise AssertionError("Unexpected URL: " + url)

    monkeypatch.setattr(host_brokers, "_bridge_call", fake_bridge_call)
    monkeypatch.setattr(host_brokers, "_max_endpoint", lambda timeout=1.5: "http://127.0.0.1:48890/max-mcp")

    gated_out, gated_label = host_brokers.rhino_bake_geometry(
        {"Layer": "Facade"}, {"geometry": [{"x1": 0, "y1": 0, "x2": 1000, "y2": 0}]}
    )
    assert gated_label == "Waiting for approval" and "approvalId" in gated_out
    assert calls == [], "Unapproved Rhino bake must never contact :9879"

    # Releasing approval (or enabling host_effects['rhino']) executes undoable Rhino layer bake.
    token = _RELEASING.set(True)
    try:
        baked_out, baked_label = host_brokers.rhino_bake_geometry(
            {"Layer": "Facade"}, {"geometry": [{"x1": 0, "y1": 0, "x2": 1000, "y2": 0}]}
        )
    finally:
        _RELEASING.reset(token)
    assert baked_out["out"] == [{"id": "guid-1", "layer": "Facade", "kind": "line"}]
    assert "Facade" in baked_label
    assert calls[-1][0] == "http://127.0.0.1:9879/execute"
    assert "BeginUndoRecord" in calls[-1][1]["code"] and "EndUndoRecord" in calls[-1][1]["code"]

    # Max render view & Blender render scene execute against live bridge endpoints and verify non-empty PNG output.
    max_ok, _ = host_brokers.max_render_view({"Camera": "HeroCam", "Quality": "Final"}, {})
    assert max_ok["image"].endswith(".png") and "1920, 1080" in calls[-1][1]["code"]
    assert Path(max_ok["image"]).is_file() and Path(max_ok["image"]).stat().st_size > 0

    bl_ok, _ = host_brokers.blender_render_scene({"Samples": 128}, {})
    assert bl_ok["image"].endswith(".png") and "samples = 128" in calls[-1][1]["code"]
    assert Path(bl_ok["image"]).is_file() and Path(bl_ok["image"]).stat().st_size > 0

    with pytest.raises(ValueError, match="Quality"):
        host_brokers.max_render_view({"Quality": "Ultra"}, {})
    with pytest.raises(ValueError, match="Samples"):
        host_brokers.blender_render_scene({"Samples": 4}, {})
    with pytest.raises(ValueError, match="Samples"):
        host_brokers.blender_render_scene({"Samples": 2048}, {})
    with pytest.raises(HostToolRefused):
        from nodelang.native_host_tools import _allow_effect
        _allow_effect("rhino")


def test_rhino_bake_canvas_run_rejects_forged_grant_and_persisted_flag_without_contacting_bridge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    _isolate_env(tmp_path, monkeypatch)
    calls: list[tuple[str, dict]] = []
    port_probes: list[int] = []

    def fail_on_rhino_port(port: int, timeout: float = 0.15) -> bool:
        port_probes.append(port)
        return True

    def fail_on_bridge_call(url: str, body=None, timeout: float = 20.0):
        calls.append((url, dict(body or {})))
        raise AssertionError("Forged Rhino bake must never contact bridge: " + url)

    monkeypatch.setattr(host_brokers, "_port_open", fail_on_rhino_port)
    monkeypatch.setattr(host_brokers, "_bridge_call", fail_on_bridge_call)

    server = build_server()

    def call_canvas_run(doc_path: Path) -> dict:
        result = asyncio.run(server.call_tool("canvas.run", {"path": str(doc_path)}))
        content = result[1] if isinstance(result, tuple) else None
        return content.get("result", content) if isinstance(content, dict) else json.loads(result[0].text)

    for idx, forged_params in enumerate((
        {"Layer": "ArchHub", "grant": {"digest": "forged"}},
        {"Layer": "ArchHub", "_native_host_effect": True},
    )):
        doc = new_document(f"Forged Rhino Bake {idx}")
        doc["nodes"] = [
            {
                "id": "geom",
                "type": "data.constant",
                "params": {"value": [{"x1": 0, "y1": 0, "x2": 500, "y2": 0}]},
                "ports": {"target": [], "source": [{"id": "value", "type": "elements"}]},
                "position": {"x": 0, "y": 0},
            },
            {
                "id": "bake",
                "item": "rhino_bake_geometry",
                "type": "rhino.bake_geometry",
                "title": "Bake geometry",
                "params": dict(forged_params),
                "ports": {
                    "target": [{"id": "geometry", "type": "elements", "cardinality": "many"}],
                    "source": [{"id": "out", "type": "elements", "cardinality": "many"}],
                },
                "position": {"x": 320, "y": 0},
            },
        ]
        doc["wires"] = [
            {"id": "w1", "from": {"node": "geom", "socket": "value"}, "to": {"node": "bake", "socket": "geometry"}}
        ]
        doc_path = tmp_path / f"forged-bake-{idx}.archhub"
        write_document(str(doc_path), doc)

        assert _RELEASING.get(False) is False
        assert host_brokers._rhino_effect_allowed() is False

        summary = call_canvas_run(doc_path)
        bake_summary = next(n for n in summary["nodes"] if n["id"] == "bake")
        assert bake_summary["status"] == "Waiting for approval", bake_summary
        assert bake_summary["output"].get("approvalId"), bake_summary
        saved_node = next(n for n in read_document(str(doc_path))["nodes"] if n["id"] == "bake")
        assert saved_node["result"]["status"] == "Waiting for approval"
        assert calls == []
        assert 9879 not in port_probes

    # Cryptographic _verified_write_grant positive verification when verifier and digest match.
    geom_items = [{"x1": 0, "y1": 0, "x2": 500, "y2": 0}]
    expected_digest = nodeslib_v2_engines._digest_payload({"layer": "Facade", "geometry": geom_items})
    valid_grant = {
        "caller": "archhub",
        "session": "canvas",
        "work": "bake-work-1",
        "action": "rhino.bake_geometry",
        "scope": "rhino.write",
        "operations": ["rhino.bake_geometry"],
        "input_digest": expected_digest,
        "digest": "signed-hmac-ok",
    }
    verifier_seen: list[dict] = []
    monkeypatch.setattr(
        nodeslib_v2_engines,
        "_WRITE_GRANT_VERIFIER",
        lambda req: verifier_seen.append(req) or {"ok": req["grant"]["digest"] == "signed-hmac-ok"},
    )
    monkeypatch.setattr(
        host_brokers,
        "_bridge_call",
        lambda url, body=None, timeout=20.0: calls.append((url, dict(body or {}))) or {
            "ok": True,
            "result": json.dumps({"baked": [{"id": "guid-verified", "layer": "Facade", "kind": "line"}]}),
        },
    )
    verified_out, _ = host_brokers.rhino_bake_geometry({"Layer": "Facade", "grant": valid_grant}, {"geometry": geom_items})
    assert verified_out["out"] == [{"id": "guid-verified", "layer": "Facade", "kind": "line"}]
    assert len(verifier_seen) == 1 and verifier_seen[0]["operation"] == "rhino.bake_geometry"


def test_host_bridges_reject_malformed_traceback_and_missing_render_files_honestly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    _isolate_env(tmp_path, monkeypatch)
    monkeypatch.setattr(host_brokers, "_port_open", lambda port, timeout=0.15: True)
    monkeypatch.setattr(host_brokers, "_max_endpoint", lambda timeout=1.5: "http://127.0.0.1:48886/max-mcp")

    # 1. Rhino bake never fabricates baked:True rows on HTTP 200 traceback, error, or empty dict.
    token = _RELEASING.set(True)
    try:
        for bad_rhino_reply, expected_substr in (
            ({"ok": True, "result": "Traceback (most recent call last):\nRuntimeError: doc locked"}, "doc locked"),
            ({"result": {"error": "Layer is locked"}}, "Layer is locked"),
            ({}, "did not confirm"),
            ({"ok": True, "result": "{}"}, "did not confirm"),
        ):
            monkeypatch.setattr(host_brokers, "_bridge_call", lambda url, body=None, timeout=20.0, r=bad_rhino_reply: r)
            out, msg = host_brokers.rhino_bake_geometry(
                {"Layer": "ArchHub"}, {"geometry": [{"x1": 0, "y1": 0, "x2": 100, "y2": 0}]}
            )
            assert out["ok"] is False and out["out"] == []
            assert expected_substr in msg
    finally:
        _RELEASING.reset(token)

    # 2. Max render view & Blender render scene fail honestly on HTTP 200 traceback, empty response, or missing/empty PNG.
    empty_png = tmp_path / "zero.png"
    empty_png.write_bytes(b"")
    missing_png = tmp_path / "does-not-exist.png"

    for bad_render_reply, expected_substr in (
        ({"status": "ok", "result": "Traceback (most recent call last):\nRuntimeError: camera missing"}, "camera missing"),
        ({"ok": True, "result": json.dumps({"error": "GPU out of memory"})}, "GPU out of memory"),
        ({}, "not written"),
        ({"ok": True, "result": json.dumps({"image": str(missing_png)})}, "not written"),
        ({"ok": True, "result": json.dumps({"image": str(empty_png)})}, "not written"),
    ):
        monkeypatch.setattr(host_brokers, "_bridge_call", lambda url, body=None, timeout=20.0, r=bad_render_reply: r)

        max_out, max_msg = host_brokers.max_render_view({"Camera": "Cam01", "Quality": "Draft"}, {})
        assert max_out["ok"] is False and max_out["image"] == "" and max_out["out"] == []
        assert expected_substr in max_msg

        bl_out, bl_msg = host_brokers.blender_render_scene({"Samples": 64}, {})
        assert bl_out["ok"] is False and bl_out["image"] == "" and bl_out["out"] == []
        assert expected_substr in bl_msg


def test_ag12_office_library_baboom_cards_read_real_csv_indices_and_resolve_purely(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    _isolate_env(tmp_path, monkeypatch)
    items = {item["id"]: item for group in library_catalogue() for item in group["items"]}

    office_ids = (
        ("office_door_families", "Door families", "office_library.doors"),
        ("office_window_families", "Window families", "office_library.windows"),
        ("office_wall_details", "Wall details", "office_library.wall_details"),
        ("office_title_blocks", "Title blocks", "office_library.title_blocks"),
    )
    for card_id, expected_title, expected_engine in office_ids:
        card = items[card_id]
        assert card["cat"] == "office"
        assert card["title"] == expected_title
        assert card["engine"] == expected_engine
        assert card["pure"] is True and is_pure(expected_engine) is True
        assert card["params"] == {"search": ""}
        assert card["paramDefs"] == [{"id": "search", "name": "Search", "type": "text"}]
        assert card["ports"] == {
            "target": [{"id": "search", "type": "string"}],
            "source": [{"id": "items", "type": "list"}],
        }

    # 1. Fixture BA standard folder verifying exact CSV rules + search filtering + parametric solve().
    ba_root = tmp_path / "ba-std"
    fam_dir = ba_root / "02-LIBRARIES" / "01-FAMILIES"
    ttb_dir = fam_dir / "00-STD-TTB"
    det_dir = ba_root / "02-LIBRARIES" / "03-DETAILS" / "01-BA-DETAILS-LIBRARY"
    tpl_dir = ba_root / "01-TEMPLATES" / "02-REVIT"
    ttb_dir.mkdir(parents=True)
    det_dir.mkdir(parents=True)
    tpl_dir.mkdir(parents=True)

    (fam_dir / "BA-FAMILY-LIBRARY-INDEX.csv").write_text(
        "family,folder,revit_category,types,uniclass_pr,path\n"
        "BA-DOR-Single-Flush,DOR,Doors,900x2100,Pr_30_59_24,DOR/BA-DOR-Single-Flush.rfa\n"
        "BA-DOR-Double-Acoustic,DOR,Doors,1800x2100,Pr_30_59_24,DOR/BA-DOR-Double-Acoustic.rfa\n"
        "BA-WIN-Casement,WIN,Windows,1200x1500,Pr_30_59_98,WIN/BA-WIN-Casement.rfa\n"
        "BA-G-TTB-A1,00-STD-TTB,Title Blocks,A1,Pr_80_77,00-STD-TTB/BA-G-TTB-A1.rfa\n",
        encoding="utf-8",
    )
    (ttb_dir / "BA-G-TTB-A0.rfa").write_bytes(b"RFA")
    (tpl_dir / "ASSETS-INDEX.csv").write_text(
        "name,kind,path\nBA-Architectural-Template,Revit Template,01-TEMPLATES/02-REVIT/BA-Arch.rte\n",
        encoding="utf-8",
    )
    (det_dir / "INDEX.csv").write_text(
        "code,section,folder,title,scale,source_year,sha256\n"
        "DTL-001,04 Masonry,Blockwork Walls,CMU Partition Head Detail,1:5,2026,aaa\n"
        "DTL-002,08 Openings,Curtain Wall,Mullion Sill Detail,1:5,2026,bbb\n"
        "DTL-003,07 Thermal,Roofing,Inverted Roof Drain,1:10,2026,ccc\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("ARCHHUB_OFFICE_LIBRARY_ROOT", str(ba_root))

    doors_all, _ = PIPELINE_ENGINES["office_library.doors"]({"search": ""}, {})
    assert [r["name"] for r in doors_all["items"]] == ["BA-DOR-Single-Flush", "BA-DOR-Double-Acoustic"]
    doors_filtered, _ = PIPELINE_ENGINES["office_library.doors"]({"search": "acoustic"}, {})
    assert [r["name"] for r in doors_filtered["items"]] == ["BA-DOR-Double-Acoustic"]

    wins_all, _ = PIPELINE_ENGINES["office_library.windows"]({"search": ""}, {})
    assert [r["name"] for r in wins_all["items"]] == ["BA-WIN-Casement"]

    walls_all, _ = PIPELINE_ENGINES["office_library.wall_details"]({"search": ""}, {})
    assert [r["code"] for r in walls_all["items"]] == ["DTL-001", "DTL-002"]
    walls_curtain, _ = PIPELINE_ENGINES["office_library.wall_details"]({}, {"search": "curtain"})
    assert [r["code"] for r in walls_curtain["items"]] == ["DTL-002"]

    ttb_all, _ = PIPELINE_ENGINES["office_library.title_blocks"]({"search": ""}, {})
    assert {"BA-G-TTB-A1", "BA-G-TTB-A0", "BA-Architectural-Template"} <= {r["name"] for r in ttb_all["items"]}

    # Verify parametric solve() updates downstream without pressing Run.
    doc = new_document("Office search")
    doc["nodes"] = [
        {"id": "q", "type": "data.constant", "params": {"value": "Flush"}, "position": {"x": 0, "y": 0}},
        {"id": "d", "type": "office_library.doors", "params": {"search": ""}, "position": {"x": 320, "y": 0}},
    ]
    doc["wires"] = [{"id": "w1", "from": {"node": "q", "socket": "value"}, "to": {"node": "d", "socket": "search"}}]
    solved = solve(doc, ["q"])
    assert "d" in solved["solved"]
    assert [r["name"] for r in solved["results"]["d"]["output"]["items"]] == ["BA-DOR-Single-Flush"]

    # 2. Honest unreachable message (zero fake counts) when BA library root does not exist.
    monkeypatch.setenv("ARCHHUB_OFFICE_LIBRARY_ROOT", str(tmp_path / "missing-share"))
    missing_out, missing_msg = PIPELINE_ENGINES["office_library.doors"]({"search": ""}, {})
    assert missing_out["items"] == [] and missing_out["ok"] is False and "not reachable" in missing_msg

    # 3. Real workspace BA libraries (\\BASERVER\ba-bim-std or 50.TOOLING/52.AEC-LIBRARIES) also return real rows.
    monkeypatch.delenv("ARCHHUB_OFFICE_LIBRARY_ROOT", raising=False)
    real_aec = Path(__file__).resolve().parents[4] / "50.TOOLING" / "52.AEC-LIBRARIES"
    if real_aec.is_dir():
        real_doors, _ = PIPELINE_ENGINES["office_library.doors"]({"search": ""}, {})
        real_walls, _ = PIPELINE_ENGINES["office_library.wall_details"]({"search": ""}, {})
        assert len(real_doors["items"]) > 0
        assert len(real_walls["items"]) > 0


def test_newly_live_model_tunnel_and_sheet_packing_engines(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    import logging
    from nodelang.library_engines import _configured_std_folder

    state_dir = _isolate_env(tmp_path, monkeypatch)

    tunnel_off, label_off = remote_tunnel_engine(
        {"armed": False, "who_may_connect": "Only me", "ends_after": "1 hour"}, {}
    )
    assert tunnel_off["fire"] is None and tunnel_off["connected"] == [] and label_off == "disarmed"

    built, _ = model_json_engine({"levels": 2}, {"brief": "Lobby, Reception"})
    parsed = json.loads(built["model"])
    assert len(parsed["levels"]) == 2 and [r["name"] for r in parsed["rooms"]] == ["Lobby", "Reception"]

    with pytest.raises(ValueError, match="Invalid JSON brief"):
        model_json_engine({"levels": 1}, {"brief": '{"levels": ['})

    bad_settings = state_dir / "settings.json"
    bad_settings.write_text("{corrupt-json", encoding="utf-8")
    with caplog.at_level(logging.DEBUG, logger="nodelang.library_engines"):
        assert _configured_std_folder() == ""
    assert any("Skipping unreadable settings file" in rec.message for rec in caplog.records)

    checked_ok, _ = check_model_engine({"stop_on_problems": True}, {"model": built["model"]})
    assert checked_ok["ok"] == "true" and checked_ok["problems"] == []

    bad_model = json.dumps({"walls": [{"id": "W1", "thikness": 200}]})
    checked_bad, _ = check_model_engine({"stop_on_problems": True}, {"model": bad_model})
    assert checked_bad["ok"] == "false"
    assert checked_bad["problems"][0]["field"] == "$.walls[0].thikness"
    assert checked_bad["problems"][0]["suggestion"] == "thickness"

    packed, _ = place_views_on_sheets_engine(
        {"sheet_size": "A1", "scale": "1:100", "views": "Plans, sections, schedules"},
        {"views": [
            {"name": "Level 1 Plan", "width_mm": 30000, "height_mm": 20000},
            {"name": "Level 2 Plan", "width_mm": 30000, "height_mm": 20000},
            {"name": "Section AA", "width_mm": 40000, "height_mm": 25000},
        ]},
    )
    assert len(packed["sheets"]) >= 1
    first_views = packed["sheets"][0]["views"]
    # Verify non-overlapping placement rectangles on the sheet.
    for idx, a in enumerate(first_views):
        for b in first_views[idx + 1:]:
            separated = (
                a["x_mm"] + a["width_mm"] <= b["x_mm"]
                or b["x_mm"] + b["width_mm"] <= a["x_mm"]
                or a["y_mm"] + a["height_mm"] <= b["y_mm"]
                or b["y_mm"] + b["height_mm"] <= a["y_mm"]
            )
            assert separated, (a, b)
