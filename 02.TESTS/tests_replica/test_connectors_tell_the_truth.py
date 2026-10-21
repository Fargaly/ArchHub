"""A connector row is a fact: every program the founder works with is listed,
each with its real state and the engine that drives it -- and nothing shows
green off a bare process name."""
from __future__ import annotations

from nodelang.pipeline_engines import PIPELINE_ENGINES, probe_connectors


def test_every_program_is_listed_and_names_its_wire():
    rows = probe_connectors()
    ids = {row["id"] for row in rows}
    assert {"revit", "autocad", "rhino", "speckle", "max", "blender", "excel", "word",
            "powerpoint", "outlook", "notion", "dropbox"} <= ids
    for row in rows:
        assert "drive" in row and "state" in row and row["detail"], row["id"]
        if row["drive"]:
            assert row["drive"] in PIPELINE_ENGINES, (row["id"], row["drive"])


def test_no_row_is_green_off_a_running_process():
    for row in probe_connectors():
        if row["state"] == "running":
            assert "no wire" in row["detail"], row["id"]
        if row["state"] == "connected":
            # A live session, an answering port, an open COM application or a
            # present token -- never a process name seen in tasklist.
            assert any(mark in row["detail"] for mark in ("session", "answering", "open", "token", "bridge", "add-on", "MaxMCP", "\\")), row
