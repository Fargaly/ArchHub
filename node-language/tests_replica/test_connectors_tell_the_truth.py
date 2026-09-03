"""A connector shows green only when the product can drive it."""
from __future__ import annotations

from nodelang.pipeline_engines import probe_connectors


def test_every_connector_row_declares_whether_it_can_be_driven():
    rows = probe_connectors()
    ids = {row["id"] for row in rows}
    assert {"revit", "autocad", "rhino", "speckle"} <= ids
    for row in rows:
        assert "drive" in row, row["id"]
    driven = {row["id"]: row["drive"] for row in rows if row["drive"]}
    assert driven == {"revit": "revit.build_walls", "autocad": "cad.host_lines"}, (
        "only hosts with an engine behind them may claim a drive"
    )


def test_no_row_is_green_off_a_running_process():
    rows = probe_connectors()
    assert not {"outlook", "dropbox", "blender"} & {row["id"] for row in rows}, (
        "a process being open is not a connection; these rows had nothing behind them"
    )
    for row in rows:
        if not row["drive"]:
            assert row["state"] != "connected", row["id"]
            assert "no wire" in row["detail"], row["id"]
