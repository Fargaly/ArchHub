"""The BABOOM frame reads the Workshop tail, and reads it once.

The founder's Workshop holds 16,919 entries. The Workshop report renders
eight of them, but read every entry to slice the last eight -- 4.253s
measured on his live graph. The machine route had no relation projection
scope either, so one frame walked the same 17,004-member Workshop chain
again for every lens it built. The frame budget was 5.0s, so the frame
never returned, BABOOM reported that the universal runtime did not respond,
and the companion never attached (2026-09-07).

These courts hold the three mechanisms that fixed it, and they hold the
absence that matters: the founder report must NOT read an entry it does not
render.
"""
from __future__ import annotations

import inspect
import types

import pytest

from nodelang import application_server as server_module
from nodelang import baboom_native_host as host_module
from nodelang import cell_deliberation as deliberation
from nodelang import universal_application as app_module


def test_the_machine_route_dispatch_holds_a_relation_scope():
    """One machine request may walk one huge relation once, never per lens."""
    source = inspect.getsource(server_module.ApplicationServer)
    marker = "    @with_relation_projection_scope\n    def dispatch_universal_machine_route("
    assert marker in source, (
        "dispatch_universal_machine_route must run under "
        "with_relation_projection_scope; without it the BABOOM frame walks "
        "the founder's Workshop chain once per projected lens"
    )


def test_the_founder_workshop_report_never_reads_every_entry(monkeypatch):
    """Rendering eight entries must not read the sixteen thousand others."""
    limit = app_module._FOUNDER_WORKSHOP_REPORT_LIMIT
    total = limit * 40
    entry_roots = tuple("entry:%d" % index for index in range(1, total + 1))
    read_roots: list[str] = []

    space = types.SimpleNamespace(
        entry_roots=entry_roots, requirement_roots=(), root_id="app:workshop"
    )

    def read_space(snapshot, protocol, space_root, *, budget=None):
        return space

    def read_entry(snapshot, protocol, root, *, budget=None):
        read_roots.append(root)
        return types.SimpleNamespace(
            space_root="app:workshop",
            sequence=entry_roots.index(root) + 1,
            category_root="category:note",
            content="a Workshop entry",
            created_at="2026-09-07T00:00:00+00:00",
        )

    monkeypatch.setattr(deliberation, "read_deliberation_space", read_space)
    monkeypatch.setattr(deliberation, "read_deliberation_entry", read_entry)
    monkeypatch.setattr(app_module, "read_deliberation_space", read_space)
    monkeypatch.setattr(
        app_module,
        "list_recent_deliberation_entries",
        deliberation.list_recent_deliberation_entries,
    )

    store = types.SimpleNamespace(
        snapshot=lambda: types.SimpleNamespace(revision=7, cells={})
    )
    registry = types.SimpleNamespace(
        deliberation_protocol=object(),
        workshop_root="app:workshop",
        workshop_category_roots=types.MappingProxyType({"note": "category:note"}),
    )

    report = app_module.project_universal_founder_workshop_report(store, registry)

    assert len(read_roots) == limit, (
        "the report read %d entries to render %d" % (len(read_roots), limit)
    )
    assert read_roots == list(entry_roots[-limit:])
    assert report["count"] == total, "the total must stay the whole space"
    assert report["truncated"] is True
    assert [row["sequence"] for row in report["entries"]] == list(
        range(total - limit + 1, total + 1)
    )


def test_the_tail_reader_still_proves_where_the_tail_sits(monkeypatch):
    """A tail read must refuse entries whose sequence does not end the space."""
    entry_roots = tuple("entry:%d" % index for index in range(1, 21))
    space = types.SimpleNamespace(entry_roots=entry_roots, requirement_roots=())

    monkeypatch.setattr(
        deliberation, "read_deliberation_space",
        lambda snapshot, protocol, root, *, budget=None: space,
    )
    monkeypatch.setattr(
        deliberation, "read_deliberation_entry",
        lambda snapshot, protocol, root, *, budget=None: types.SimpleNamespace(
            space_root="app:workshop", sequence=1,
        ),
    )
    with pytest.raises(deliberation.InvalidCell):
        deliberation.list_recent_deliberation_entries(
            object(), object(), "app:workshop", limit=4
        )


def test_the_tail_reader_refuses_a_foreign_space(monkeypatch):
    """A tail read must still refuse an entry from another space."""
    entry_roots = ("entry:1", "entry:2")
    space = types.SimpleNamespace(entry_roots=entry_roots, requirement_roots=())
    monkeypatch.setattr(
        deliberation, "read_deliberation_space",
        lambda snapshot, protocol, root, *, budget=None: space,
    )
    monkeypatch.setattr(
        deliberation, "read_deliberation_entry",
        lambda snapshot, protocol, root, *, budget=None: types.SimpleNamespace(
            space_root="app:somewhere-else",
            sequence=entry_roots.index(root) + 1,
        ),
    )
    with pytest.raises(deliberation.InvalidCell):
        deliberation.list_recent_deliberation_entries(
            object(), object(), "app:workshop", limit=2
        )


@pytest.mark.parametrize("limit", [0, -1, True, 1.5, "8"])
def test_the_tail_reader_refuses_an_invalid_limit(limit):
    """A tail limit is a positive integer, never a bool and never text."""
    with pytest.raises(deliberation.InvalidCell):
        deliberation.list_recent_deliberation_entries(
            object(), object(), "app:workshop", limit=limit
        )


def test_the_first_frame_gets_more_time_than_a_steady_frame():
    """A cold boot read must not expire on a steady-state budget."""
    assert host_module._STEADY_FRAME_SECONDS == 5.0
    assert host_module._FIRST_FRAME_SECONDS > host_module._STEADY_FRAME_SECONDS
    source = inspect.getsource(host_module.BaboomNativeHost.connect)
    assert "_FIRST_FRAME_SECONDS" in source, (
        "connect() must ask for the cold-boot frame budget"
    )
    signature = inspect.signature(host_module.BaboomNativeHost.poll)
    assert (
        signature.parameters["response_timeout_seconds"].default
        == host_module._STEADY_FRAME_SECONDS
    ), "an unattended poll must keep the short budget"


def test_the_boot_retries_the_pipeline_run_not_only_the_seed():
    """Both boot writers race the same store, so both must retry.

    Only the seed was retried. BABOOM now attaches during boot and its
    presence lease is another writer, so the RUN lost the race and the
    founder booted with no node run at all (2026-09-07).
    """
    from pathlib import Path

    launcher = (
        Path(__file__).resolve().parents[1] / "launch_archhub_test.py"
    ).read_text(encoding="utf-8")
    run = launcher[launcher.index("outcome = None"):]
    run = run[:run.index('print("  pipeline   : %d node(s) ran"')]
    assert "run_universal_pipeline(" in run
    assert 'if "expected revision" not in str(clash) or attempt == 9:' in run
    assert "for attempt in range(10):" in run
    assert "time.sleep(0.25 * (attempt + 1))" in run
