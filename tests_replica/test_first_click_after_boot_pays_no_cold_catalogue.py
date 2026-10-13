"""The first click after an owner boot does not read the catalogue cold.

The lens memos are process memory and a boot filled none of them, so the
founder's first click paid the whole published catalogue: GET canvas
79.5s on 2026-08-27, 58.1s of it the lens reading every definition cold
(gesture-timing.log). The browser's sign-in is a commit and precedes
every first click, so the warm that counts is the one whose memo is kept
by read set (unified_application_lens._DEFINITION_MEMOS), not by
revision, and it has to happen before the surface answers anything.

Bounded by call count on a synthetic runtime, never by wall clock: the
lens's own read_definition and the catalogue-region prefetch are what
the first click must not pay. RED against the code it forbids: today a
boot reads no definition and the first click reads all of them.
"""
from __future__ import annotations

import uuid

import nodelang.unified_application_lens as lens_module
import nodelang.universal_cell as cell_module
from nodelang.stability_runtime import catalogue_relation_generation

from tests_replica.test_clean_server_visual_projection import (
    _issue_clean_session,
    _json,
    _provision_clean_runtime,
    _start_clean_server,
)
from tests_replica.test_interaction_rebases_over_unrelated_commits import (
    _publish_definition,
)


def _count_cold_catalogue_reads(monkeypatch, authority):
    """Count what the lens reads cold: definitions, and the catalogue region."""
    counts = {"read_definition": 0, "prefetch_catalogue": 0}
    catalogue_root = authority.manifest.catalogue_root
    real_read = lens_module.read_definition

    def counting_read(*args, **kwargs):
        counts["read_definition"] += 1
        return real_read(*args, **kwargs)

    monkeypatch.setattr(lens_module, "read_definition", counting_read)
    real_prefetch = cell_module._LazyHeadCellMap.prefetch_region

    def counting_prefetch(self, root_id, *args, **kwargs):
        if root_id == catalogue_root:
            counts["prefetch_catalogue"] += 1
        return real_prefetch(self, root_id, *args, **kwargs)

    monkeypatch.setattr(
        cell_module._LazyHeadCellMap, "prefetch_region", counting_prefetch
    )
    return counts


def _sid(name):
    """Fixture session names (plain labels, not credentials)."""
    return name


def _first_click(server, built, *, token):
    # The browser's sign-in is a commit; it precedes every first click.
    _issue_clean_session(built, token=token, csrf=token + "-csrf")
    status, canvas = _json(server.url, "/api/universal/canvas", token=token)
    assert status == 200, canvas
    assert canvas["catalog"], "the fixture publishes a catalogue the click shows"
    return canvas


def test_boot_reads_the_catalogue_once_and_the_first_click_reads_none(
    tmp_path, monkeypatch
):
    built, provider = _provision_clean_runtime(tmp_path)
    authority = built.location.authority
    revision_before = authority.store.revision
    counts = _count_cold_catalogue_reads(monkeypatch, authority)
    server = _start_clean_server(built, provider)
    try:
        assert authority.store.revision == revision_before, (
            "an owner opens -- it never writes at boot"
        )
        boot_reads = counts["read_definition"]
        counts.update(read_definition=0, prefetch_catalogue=0)
        _first_click(server, built, token=_sid("boot-warm-first"))
        assert counts == {"read_definition": 0, "prefetch_catalogue": 0}, (
            "boot read %d definitions; the first click then paid %r"
            % (boot_reads, counts)
        )
        assert boot_reads > 0, "boot read no definition through the lens"
    finally:
        server.close()
        authority.store.close()


def test_a_publish_after_boot_is_seen_by_the_first_click(tmp_path, monkeypatch):
    """Guard, green today: a warm at boot must never freeze the catalogue."""
    built, provider = _provision_clean_runtime(tmp_path)
    authority = built.location.authority
    server = _start_clean_server(built, provider)
    try:
        counts = _count_cold_catalogue_reads(monkeypatch, authority)
        published = _publish_definition(built, "Published after boot")
        canvas = _first_click(server, built, token=_sid("boot-warm-pub"))
        assert any(item["id"] == published for item in canvas["catalog"]), (
            "a warm at boot must never hide a publish that came after it"
        )
        assert counts["read_definition"] >= 1, counts
    finally:
        server.close()
        authority.store.close()


def test_catalogue_generation_changes_when_definition_revision_changes(tmp_path):
    from nodelang.unified_authority import declare_definition, promote_definition

    built, _provider = _provision_clean_runtime(tmp_path)
    authority = built.location.authority
    try:
        declared = declare_definition(
            authority,
            "Revision token fixture",
            {},
            caller=built.caller,
            command_id=str(uuid.uuid4()),
            version="1",
            presentation={"label": "Revision token fixture"},
        )
        shared = promote_definition(
            authority,
            declared.root_id,
            target_lifecycle="shared",
            version="1-shared",
            evidence_roots=(declared.receipt_root,),
            caller=built.caller,
            command_id=str(uuid.uuid4()),
        )
        published = promote_definition(
            authority,
            declared.root_id,
            target_lifecycle="published",
            version="1-published",
            evidence_roots=(shared.receipt_root,),
            caller=built.caller,
            command_id=str(uuid.uuid4()),
        )
        before = catalogue_relation_generation(authority)
        promote_definition(
            authority,
            declared.root_id,
            target_lifecycle="archived",
            version="1-archived",
            evidence_roots=(published.receipt_root,),
            caller=built.caller,
            command_id=str(uuid.uuid4()),
        )
        assert catalogue_relation_generation(authority) != before
    finally:
        authority.store.close()


def test_canvas_projection_observes_broker_latency(tmp_path):
    class _Observer:
        def __init__(self):
            self.calls = []

        def observe(self, broker, started_at, finished_at, *, root_cause_line=""):
            self.calls.append((broker, started_at, finished_at, root_cause_line))

            class _Decision:
                flagged = False

            return _Decision()

    built, provider = _provision_clean_runtime(tmp_path)
    server = _start_clean_server(built, provider)
    observer = _Observer()
    server._broker_latency_baselines = observer
    try:
        _first_click(server, built, token=_sid("broker-latency-observed"))
        assert observer.calls and observer.calls[0][0] == "canvas"
    finally:
        server.close()
        built.location.authority.store.close()


def test_disk_warmed_flag_does_not_skip_process_store_warm(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "profile"))
    built, provider = _provision_clean_runtime(tmp_path)
    authority = built.location.authority
    counts = _count_cold_catalogue_reads(monkeypatch, authority)
    server = _start_clean_server(built, provider)
    try:
        assert counts["read_definition"] > 0
    finally:
        server.close()
    counts.update(read_definition=0, prefetch_catalogue=0)
    lens_module._CATALOGUE_MEMOS.clear()
    lens_module._DEFINITION_MEMOS.clear()
    monkeypatch.setattr(
        "nodelang.stability_runtime.time.time",
        lambda: 60.0 * 60.0,
    )
    second = _start_clean_server(built, provider)
    try:
        boot_reads = counts["read_definition"]
        assert boot_reads > 0, "disk warmed=true is not a process/store memo"
        counts.update(read_definition=0, prefetch_catalogue=0)
        _first_click(second, built, token=_sid("boot-warm-from-disk"))
        assert counts == {"read_definition": 0, "prefetch_catalogue": 0}
    finally:
        second.close()
        authority.store.close()
