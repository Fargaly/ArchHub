"""Tests for the LEDGER UNIFICATION (ONE-SYSTEM, AgDR-0054 S1).

Court defect #1 was a FORKED store: `tools/active_work.py` wrote a separate JSON
file ledger while `personal_brain.active_work` wrote `brain.db`. These tests
prove the fork is gone — `tools/completion_gate.py` + `tools/active_work.py` now
read/write THROUGH the brain ledger (one store), via `tools/brain_ledger.py`.

The headline gate (`test_completion_gate_reads_brain_ledger_one_store`) FAILS on
the pre-fix gate (which only ever read the local file, so a leaf living only in
the brain was invisible to it) and PASSES after — proving the gate now reads the
brain.

Run under pytest. They use an isolated temp brain.db via $ARCHHUB_BRAIN_DB and a
fresh in-process import of brain_ledger, with NO daemon up (so the in-process
transport is exercised — still the ONE brain store, just reached without the
daemon).
"""
from __future__ import annotations

import importlib
import io
import json
import os
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_TOOLS = _REPO / "tools"
_BRAIN_SRC = _REPO / "personal-brain-mcp" / "src"
for p in (str(_TOOLS), str(_BRAIN_SRC)):
    if p not in sys.path:
        sys.path.insert(0, p)


@pytest.fixture()
def isolated_brain(monkeypatch):
    """A fresh temp brain.db + a fresh brain_ledger import, no daemon.

    brain_ledger memoises its store + daemon probe at module scope, so we reload
    it per test and point it at a temp DB. We force the daemon 'down' so the
    in-process transport (the SAME brain.db) is what answers — proving the gate
    reaches the one brain store even with no daemon running."""
    with tempfile.TemporaryDirectory() as d:
        db = Path(d) / "brain.db"
        monkeypatch.setenv("ARCHHUB_BRAIN_DB", str(db))
        # ensure a stable owner regardless of the host env.
        monkeypatch.setenv("BRAIN_OWNER_USER", "founder")
        # reload brain_ledger so its module-level memo (store/daemon) is fresh.
        import brain_ledger as bl
        bl = importlib.reload(bl)
        # force the daemon probe to 'down' -> exercise the in-process path.
        monkeypatch.setattr(bl, "_call_daemon", lambda *a, **k: None)
        bl._daemon_up = False
        bl._store = None
        bl._store_tried = False
        # reload completion_gate too so it binds to THIS brain_ledger.
        import completion_gate as cg
        cg = importlib.reload(cg)
        try:
            yield bl, cg
        finally:
            # close the in-process BrainStore so Windows can remove the tempdir
            # (the module-level memo holds brain.db open otherwise).
            try:
                if getattr(bl, "_store", None) is not None:
                    bl._store.close()
            except Exception:
                pass
            bl._store = None
            bl._store_tried = False


def test_brain_ledger_transport_is_inproc_not_file(isolated_brain):
    """With no daemon but the package importable, the authoritative transport is
    the in-process brain.db — NOT the legacy file. (If this said 'file' the store
    would be forked again.)"""
    bl, _ = isolated_brain
    assert bl.transport() == "inproc"


def test_completion_gate_reads_brain_ledger_one_store(isolated_brain):
    """THE unification proof. Enqueue a RED leaf into the BRAIN ledger only (no
    local file written), then run the gate. The gate must BLOCK because it READS
    the brain ledger — and tag the verdict source as 'brain:*'. On the old
    file-only gate nothing was registered (no file) so it ALLOWED (no output):
    this test FAILS there and PASSES now."""
    bl, cg = isolated_brain
    with tempfile.TemporaryDirectory() as work:
        # a leaf whose gate is RED: a file that does not exist.
        missing = "definitely_absent_artifact.py"
        bl.add_leaves([{
            "title": "produce the artifact",
            "gate_kind": "file_exists",
            "gate_spec": {"path": missing},
        }])
        # sanity: it really went into the BRAIN ledger (one store), no file.
        assert bl.transport() == "inproc"
        st = bl.status()
        assert st["counts"]["open"] == 1

        # run the gate from a cwd where the artifact is missing.
        old_cwd = os.getcwd()
        os.chdir(work)
        try:
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = cg.main([])  # no argv -> must consult the brain, not a file
            out = buf.getvalue().strip()
        finally:
            os.chdir(old_cwd)

        assert rc == 0
        assert out, "gate produced no verdict — it did not read the brain ledger"
        payload = json.loads(out)
        assert payload.get("decision") == "block", payload
        assert "produce the artifact" in payload.get("reason", "")
        # the verdict explicitly came from the BRAIN store (not a file fork).
        assert str(payload.get("source", "")).startswith("brain:"), payload


def test_completion_gate_allows_when_brain_leaf_done(isolated_brain):
    """When the brain leaf's gate is satisfiable (the artifact exists), the gate
    ALLOWS — proving it evaluates the brain leaf's REAL predicate, not a stale
    file copy."""
    bl, cg = isolated_brain
    with tempfile.TemporaryDirectory() as work:
        present = "present_artifact.py"
        (Path(work) / present).write_text("x = 1\n", encoding="utf-8")
        bl.add_leaves([{
            "title": "artifact that exists",
            "gate_kind": "file_exists",
            "gate_spec": {"path": present},
        }])
        old_cwd = os.getcwd()
        os.chdir(work)
        try:
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = cg.main([])
            out = buf.getvalue().strip()
        finally:
            os.chdir(old_cwd)
        assert rc == 0
        assert out == "", f"gate should ALLOW (no block) when the leaf is green, got: {out}"


def test_tools_active_work_register_writes_to_brain(isolated_brain):
    """The producer side is unified too: tools/active_work.register enqueues into
    the BRAIN ledger (not a forked file). Read it back via the brain ledger."""
    bl, _ = isolated_brain
    import active_work as taw
    taw = importlib.reload(taw)
    res = taw.register([
        {"name": "wire it", "kind": "file_exists", "arg": "z.py",
         "machine_resolvable": True},
    ])
    assert res["ok"] and res["transport"] == "inproc"
    led = bl.get_ledger()
    assert led is not None
    titles = {lf["title"] for lf in led["leaves"].values()}
    assert "wire it" in titles


def test_no_forked_file_written_on_authoritative_path(isolated_brain):
    """ONE-SYSTEM guard: when the brain is reachable, the producer must NOT also
    write the legacy JSON file (that would re-fork the store). The brain is the
    sole writer on the authoritative path."""
    bl, _ = isolated_brain
    import active_work as taw
    taw = importlib.reload(taw)
    with tempfile.TemporaryDirectory() as work:
        old_cwd = os.getcwd()
        os.chdir(work)
        try:
            taw.register([{"name": "x", "kind": "manual",
                           "machine_resolvable": False}])
            # the legacy default file path must NOT have been created.
            assert not (Path(work) / ".archhub" / "active_work.json").exists(), (
                "a forked JSON ledger was written on the authoritative path")
        finally:
            os.chdir(old_cwd)
