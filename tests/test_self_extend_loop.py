"""Integration test for the universal self-extension loop (SEAM 1→4).

Drives ask → BUILD → ROMA COURT → BRAIN programmatically — NO live app, NO live
brain daemon (the conftest neutralises it; we inject a fake brain transport to
capture the write) — on a TINY real capability, and asserts EACH seam fired:

  SEAM 1  the composer agent EXPOSES the build tools + the bridge gate routes
          an approved build into the loop.
  SEAM 1  build_artifact writes the REAL artifact locally (a base.py-contract
          connector file that py_compiles + instantiates + registers).
  SEAM 1  LIBRARY-FIRST: a second build of the same capability REUSES (no dup).
  SEAM 2+3 court_verify AUTO-hands the artifact to the ROMA court with a REAL
          gate (py_compile on the new file); a GREEN sweep requires the real
          artifact to pass; a missing/broken artifact does NOT pass.
  SEAM 4  on GREEN, learn_capability AUTO-builds a brain.write op 'add' with
          owner_user + full provenance (contributing_agent, contributing_user,
          created_at, accessed_resources) + kind 'fact' + scope 'user'.
  E2E     run_self_extend reports seams {build, court, brain} all True.

The court runs in-process against an ephemeral ':memory:' BrainStore — the same
organs the proof-run used (roma + court_harness + requirement_tree), no parallel
engine.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_BRAIN_SRC = _ROOT / "personal-brain-mcp" / "src"
if str(_BRAIN_SRC) not in sys.path:
    sys.path.insert(0, str(_BRAIN_SRC))

pytest.importorskip("pydantic")
pytest.importorskip("personal_brain.roma")

from agents import composer_agent          # noqa: E402
from agents import self_extend             # noqa: E402
from connectors import scaffold            # noqa: E402


# A tiny throwaway capability that is cheap to build + verify.
_HOST = "selfext_probe"
_CONN_PATH = scaffold.connector_path(_HOST)


@pytest.fixture(autouse=True)
def _clean_artifact():
    """Remove the scaffolded connector before + after so the test is hermetic
    and reversible (delete-to-undo is the self-extension reversibility floor)."""
    if _CONN_PATH.exists():
        _CONN_PATH.unlink()
    yield
    if _CONN_PATH.exists():
        _CONN_PATH.unlink()


def _store():
    from personal_brain.storage import BrainStore
    return BrainStore.open(":memory:")


# ── SEAM 1 — the build tools EXIST on the composer surface + are gated ───────


def test_seam1_build_tools_in_tool_schema():
    names = {t["name"] for t in composer_agent.TOOL_SCHEMA}
    assert "create_node_type" in names
    assert "create_connector" in names


def test_seam1_build_tools_are_gated_writes():
    # A build self-extends the machine → it is an approve-able WRITE under Plan.
    assert composer_agent.mode_gates_write("plan", "create_connector") is True
    assert composer_agent.mode_gates_write("plan", "create_node_type") is True
    # YOLO lets it through (opt-in, reversible).
    assert composer_agent.mode_gates_write("yolo", "create_connector") is False
    assert {"create_node_type", "create_connector"} <= composer_agent.BUILD_TOOLS


# ── SEAM 1 — build writes the REAL artifact locally ─────────────────────────


def test_seam1_build_connector_writes_real_artifact():
    build = self_extend.build_artifact("create_connector", {
        "host": _HOST, "label": "Self-Ext Probe", "mechanism": "rest",
        "operations": [{"op_id": "list_things", "kind": "read",
                        "label": "List things"}],
    })
    assert build["ok"] is True
    assert build["reused"] is False
    assert build["kind"] == "connector"
    assert _CONN_PATH.exists(), "the connector file was not written to disk"
    # The artifact is a real base.py-contract connector: it compiles + the gate
    # the court will run is py_compile on this exact file.
    assert build["gate_kind"] == "py_compile"
    import py_compile
    py_compile.compile(str(_CONN_PATH), doraise=True)


def test_seam1_library_first_reuses_existing(monkeypatch):
    # First build writes it; second build of the same host must REUSE (no dup).
    first = self_extend.build_artifact("create_connector", {"host": _HOST})
    assert first["ok"] and first["reused"] is False
    second = self_extend.build_artifact("create_connector", {"host": _HOST})
    assert second["ok"] is True
    assert second["reused"] is True, "LIBRARY-FIRST: an existing host must be reused, not clobbered"


# ── SEAM 2+3 — the artifact is AUTO-verified by the ROMA court ──────────────


def test_seam23_court_greens_a_real_artifact():
    build = self_extend.build_artifact("create_connector", {"host": _HOST})
    assert build["ok"]
    court = self_extend.court_verify(build, store=_store())
    assert court["ok"] is True
    assert court["green"] is True, f"court should green a compiling artifact: {court}"
    assert court["verdict"] == "green"
    # Real sweep: one leaf, green, root green, no needs_root.
    sweep = court["sweep"]
    assert sweep["dry"] is True and sweep["root_green"] is True
    assert sweep["green_leaves"] == sweep["total_leaves"] == 1
    assert not sweep["needs_root"]   # no escalated leaves (empty list)


def test_seam23_court_refuses_a_broken_artifact():
    # A build pointing the gate at a non-compiling / missing file must NOT pass.
    fake_build = {"ok": True, "kind": "connector", "host": "nope",
                  "detail": "fabricated", "gate_kind": "py_compile",
                  "gate_spec": {"path": "app/connectors/does_not_exist_xyz.py"}}
    court = self_extend.court_verify(fake_build, store=_store())
    assert court["green"] is False
    assert court["verdict"] in ("red", "needs_root")


# ── SEAM 4 — a GREEN court AUTO-writes a learned fragment via brain.write ────


def test_seam4_green_writes_learned_fragment():
    build = self_extend.build_artifact("create_connector", {"host": _HOST})
    court = self_extend.court_verify(build, store=_store())
    assert court["green"]

    captured = {}

    def _fake_brain(tool_name, args):
        captured["tool"] = tool_name
        captured["args"] = args
        return {"ops_applied": 1, "fragments_added": 1}

    learn = self_extend.learn_capability(build, court, brain_call=_fake_brain)
    assert learn["ok"] is True
    assert captured["tool"] == "brain.write"

    ops = captured["args"]["ops"]
    assert len(ops) == 1
    op = ops[0]
    assert op["op"] == "add"
    frag = op["fragment"]
    assert frag["kind"] == "fact"
    assert frag["scope"] == "user"
    assert frag["owner_user"] == self_extend.DEFAULT_OWNER_USER
    prov = frag["provenance"]
    assert prov["contributing_agent"]
    assert prov["contributing_user"] == self_extend.DEFAULT_OWNER_USER
    assert "created_at" in prov
    assert prov["accessed_resources"] == []
    assert _HOST in frag["text"]

    # The written fragment validates against the REAL brain Fragment model —
    # proving the op the loop produces is a genuine, persistable brain write.
    from personal_brain.models import Fragment
    Fragment.model_validate(frag)


def test_seam4_red_court_never_learns():
    # A capability the court did NOT green is NEVER recorded in the brain.
    build = self_extend.build_artifact("create_connector", {"host": _HOST})
    red_court = {"green": False, "verdict": "red", "tree_id": "t", "gate_kind": "py_compile"}
    calls = []
    learn = self_extend.learn_capability(build, red_court,
                                         brain_call=lambda *a: calls.append(a))
    assert learn["ok"] is False
    assert learn["skipped"] == "court_not_green"
    assert calls == [], "a non-green capability must not write to the brain"


# ── E2E — the ONE mechanism: ask → build → court → learn ────────────────────


def test_end_to_end_all_seams_fire():
    captured = {}

    def _fake_brain(tool_name, args):
        captured["tool"] = tool_name
        captured["args"] = args
        return {"ops_applied": 1, "fragments_added": 1}

    result = self_extend.run_self_extend(
        "create_connector",
        {"host": _HOST, "label": "Self-Ext Probe",
         "operations": [{"op_id": "list_things", "kind": "read"}]},
        store=_store(), brain_call=_fake_brain,
    )
    assert result["ok"] is True, f"loop did not complete green: {result}"
    seams = result["seams"]
    assert seams["build"] is True   # SEAM 1 — real artifact written
    assert seams["court"] is True   # SEAM 2+3 — ROMA court greened it
    assert seams["brain"] is True   # SEAM 4 — learned fragment written

    # The artifact is real on disk + the brain write actually happened.
    assert _CONN_PATH.exists()
    assert captured["tool"] == "brain.write"
    assert result["court"]["verdict"] == "green"
    assert result["learn"]["fragment_id"].startswith("self_extend::connector::")


def test_run_self_extend_rejects_non_build_tool():
    out = self_extend.run_self_extend("spawn_node", {}, store=_store())
    assert out["ok"] is False
    assert "not a self-extend build tool" in out["error"]


# ── node-type path (the OTHER build tool) — build via the REAL library organ ──

_NODE_SPEC = {
    "type": "selfext.area_filter", "display_name": "Area Filter",
    "category": "logic",
    "description": ("Filter a list of rooms keeping only those whose area is at "
                    "or above a configurable minimum threshold, returning the "
                    "surviving rooms list."),
    "inputs": [{"name": "rooms", "port_type": "list"}],
    "outputs": [{"name": "filtered", "port_type": "list"}],
    "config_schema": {"min_area": {"type": "number", "default": 10}},
    "examples": [{"in": "rooms", "out": "rooms over min_area"}],
}


@pytest.fixture
def _clean_lib():
    import library as lib
    try:
        lib.reset_registry()
    except Exception:
        pass
    yield
    try:
        if "selfext.area_filter" in [i.get("type") for i in lib.list_node_types()]:
            lib.delete_node_type("selfext.area_filter")
    except Exception:
        pass


def test_node_type_path_all_seams_fire(_clean_lib):
    captured = {}
    result = self_extend.run_self_extend(
        "create_node_type", dict(_NODE_SPEC), store=_store(),
        brain_call=lambda t, a: (captured.update(tool=t, args=a) or {"ops_applied": 1}),
    )
    assert result["seams"] == {"build": True, "court": True, "brain": True}, result
    # The node-type gate is the REAL library-registration probe, not py_compile.
    assert result["court"]["gate_kind"] == "registered_node"
    assert captured["tool"] == "brain.write"
    assert result["learn"]["fragment_id"] == "self_extend::node_type::selfext.area_filter"


def test_node_type_library_first_reuse(_clean_lib):
    first = self_extend.build_artifact("create_node_type", dict(_NODE_SPEC))
    assert first["ok"] and first["reused"] is False
    second = self_extend.build_artifact("create_node_type", dict(_NODE_SPEC))
    assert second["ok"] is True and second["reused"] is True


# ── THE FREE-FORM LOOP — ask → build → COURT-PER-LEAF → learn-per-green ──────
# bridge.self_extend_loop → run_self_extend_loop: a free-form request atomizes
# into a MULTI-leaf ROMA tree, the composer-as-executor BUILDS each leaf on the
# real machine, the external court verifies it on the REAL artifact leaf-by-leaf,
# every GREEN leaf is learned. The court — not the executor — flips green.


@pytest.fixture
def _isolated_marker(tmp_path, monkeypatch):
    """Point %APPDATA% at a throwaway dir so the marker file + the brain store
    land in tmp — never the founder's real brain/marker. Reversible by teardown
    (tmp_path is auto-removed)."""
    monkeypatch.setenv("APPDATA", str(tmp_path))
    marker = composer_agent._appdata_self_extend_dir()
    return Path(marker) / "hello_marker.py"


def test_atomize_vision_default_decomposition():
    specs = composer_agent.atomize_vision("add a hello marker file")
    assert len(specs) == 3
    assert [s["gate_kind"] for s in specs] == ["file_exists", "py_compile", "file_exists"]
    # The contains-sentinel gate carries the proof string.
    assert specs[2]["gate_spec"]["contains"] == "self-extend proven"


def test_atomize_vision_passthrough():
    custom = [{"title": "x", "gate_kind": "py_compile", "gate_spec": {"path": "a.py"}}]
    assert composer_agent.atomize_vision("anything", decomposition=custom) == custom


def test_compose_evidence_shape_reads_real_file(tmp_path):
    p = tmp_path / "m.py"
    p.write_text("GREETING = 'self-extend proven'\n", encoding="utf-8")
    run_result = {"actions": [{"tool": "write_file", "args": {"path": str(p)}}],
                  "text": "wrote it", "gated": 0}

    class _Leaf:
        title = "marker"
    ev = composer_agent.compose_evidence("u", {}, _Leaf(), run_result)
    assert ev["last_message"] == "wrote it"
    assert ev["touched_files"] == [str(p)]
    assert "self-extend proven" in ev["file_contents"][str(p)]
    assert ev["session_signals"]["actions"] == 1


def test_loop_court_gated_green_and_learns(_isolated_marker):
    marker = _isolated_marker
    if marker.exists():
        marker.unlink()
    captured = []
    out = self_extend.run_self_extend_loop(
        "add a hello marker file proving self-extend works",
        graph={"nodes": [], "wires": []},
        router=None,                       # deterministic marker executor builds it
        brain_call=lambda t, a: (captured.append((t, a)) or {"ok": True}),
        store=_store(),
    )
    # The court flipped a FULL green sweep on the REAL artifact.
    assert marker.exists(), "executor must write the REAL marker file"
    assert out["dry"] is True and out["ok"] is True
    leaf_rows = [p for p in out["leaves"] if not p["terminal"]]
    assert len(leaf_rows) == 3
    assert all(p["verdict"] == "green" for p in leaf_rows)
    # Each green carries a NAMED evidence_ref (no trust-me green).
    assert all(p["evidence_ref"] for p in leaf_rows)
    # SEAM 4 — one USER-scope learned fact per green leaf.
    writes = [a for (t, a) in captured if t == "brain.write"]
    assert len(writes) == 3
    frags = [w["ops"][0]["fragment"] for w in writes]
    assert all(f["scope"] == "user" for f in frags)
    assert all(f["predicate"] == "self_extend_verified" for f in frags)
    assert all(p["learned"] for p in leaf_rows)
    # Terminal sweep emit closes the loop.
    assert out["leaves"][-1]["terminal"] is True
    assert out["leaves"][-1]["verdict"] == "green"


def test_loop_court_refuses_absent_artifact(_isolated_marker, monkeypatch):
    """The court — not the executor — is the gate: with the artifact absent AND
    the deterministic executor disabled (router=None → no LLM build), NO leaf
    greens. Proves a green rests on the real artifact, never the agent's word."""
    marker = _isolated_marker
    if marker.exists():
        marker.unlink()
    monkeypatch.setattr(self_extend, "_materialize_default_marker",
                        lambda spec: {"actions": [], "text": "", "gated": 0})
    captured = []
    out = self_extend.run_self_extend_loop(
        "add a hello marker file proving self-extend works",
        graph={"nodes": [], "wires": []},
        router=None,
        brain_call=lambda t, a: (captured.append((t, a)) or {"ok": True}),
        store=_store(),
    )
    assert not marker.exists()
    assert out["dry"] is False and out["ok"] is False
    leaf_rows = [p for p in out["leaves"] if not p["terminal"]]
    assert all(p["verdict"] != "green" for p in leaf_rows)
    assert [a for (t, a) in captured if t == "brain.write"] == []  # nothing learned
