"""The user's canvas holds the user's work; everything else lives in its lens.

The founder opened the canvas and understood nothing (audit, graph revision
134132): one hardcoded seed put twelve cards on it, seven of them status
readers with no inputs or outputs; Workshop contact routing records landed
on it as raw JSON cells; every runtime agent session and every Work card
was written into the same relation at one fixed point; a second seeded set
sat in the Workbench. SPEC 6 names the lenses (Brain, Cockpit, Workshop)
and the Use layer shows no raw Cells or JSON.

So: a new graph seeds only the pipeline on the canvas and each status card
in its lens; an old graph is moved there by ONE admitted migration that
moves membership, tombstones the duplicate set by marker and loses no root;
and every placement takes a free slot instead of a constant.
"""
from __future__ import annotations

import json

import pytest

from nodelang.canvas_placement import (
    arrange_on_open,
    card_size,
    free_slot,
    intersects,
)
from nodelang.map_import import resolve_map_path
from nodelang.universal_application import (
    _canvas_roots,
    build_universal_application,
    create_universal_property,
    instantiate_universal_definition,
    instantiate_universal_primitive,
    project_universal_canvas,
    select_universal_root,
    read_relation,
)
from nodelang.universal_pipeline import (
    _ALL_SEED,
    _LENS_OF_MARKER,
    _SEED,
    _SEED_MARKER,
    _owner_properties,
    lens_scope_root,
    migration_tombstones,
    seed_wall_pipeline,
    settle_canvas_content,
)

PIPELINE = {properties[_SEED_MARKER] for _t, _x, _y, properties in _SEED}
# The old seed table's pipeline points (git 454e78a / dddccf6).
OLD_TABLE = {
    "sketch-lines": (240.0, 200.0), "cad-lines": (240.0, 380.0),
    "line-watcher": (560.0, 290.0), "revit-walls": (880.0, 290.0),
    "revit-sessions": (880.0, 470.0),
}


def _members(snapshot, registry, scope):
    return {
        member.participant_id
        for member in read_relation(snapshot, scope, budget=300_000)
        if member.role_id == registry.roles["member"]
    }


def _user_markers(store, registry):
    owned = _owner_properties(store.snapshot(), registry)
    projection = project_universal_canvas(store, registry)
    return [
        ((owned.get(node["id"]) or {}).get(_SEED_MARKER) or ("", ""))[1]
        for node in projection["nodes"] if not node.get("application")
    ], projection


@pytest.fixture(scope="module")
def fresh():
    store, registry = build_universal_application(resolve_map_path())
    try:
        seeded = seed_wall_pipeline(store, registry)
        yield store, registry, seeded
    finally:
        store.close()


@pytest.fixture(scope="module")
def migrated():
    """A graph in the shape the pre-2026-09-28 seed and writers left it."""
    store, registry = build_universal_application(resolve_map_path())
    try:
        catalogue = project_universal_canvas(store, registry)["catalog"]
        definition = next(
            str(item["id"]) for item in catalogue if item.get("name") == "Ordered List"
        )

        def old_seed_card(title, properties, x, y):
            # Exactly what the pre-2026-09-28 seed wrote: a card on the top
            # canvas, then its rows.
            root, _ = instantiate_universal_definition(
                store, registry, definition, x=x, y=y, title_override=title,
            )
            for label, value in properties.items():
                create_universal_property(store, registry, root, label, str(value))
            return root

        placed = {}
        for index, (title, properties) in enumerate(_ALL_SEED):
            # Where the old seed table put each card (git 454e78a): the
            # pipeline on its own points, the status readers on a grid.
            x, y = OLD_TABLE.get(properties[_SEED_MARKER], (
                240.0 + (index % 4) * 320.0, 560.0 + (index // 4) * 180.0))
            placed[properties[_SEED_MARKER]] = old_seed_card(title, properties, x, y)
        # The duplicate chain: a second Sketch Lines carrying the same marker.
        duplicate = old_seed_card(
            "Sketch Lines", {"seed": "sketch-lines", "engine": "vision.sketch_lines"},
            240.0, 200.0,
        )
        contact, _ = instantiate_universal_primitive(
            store, registry, x=240.0, y=200.0, title="Contact: a live session",
            atom=json.dumps({"kind": "native-contact", "version": 1}),
        )
        before = set(store.snapshot().cells)
        members_before = set(_canvas_roots(store.snapshot(), registry)[0])
        import threading
        lock = threading.Lock()
        first = settle_canvas_content(store, registry, batch_size=3, lock=lock, pause=0)
        revision = store.revision
        second = settle_canvas_content(store, registry)
        yield {
            "store": store, "registry": registry, "placed": placed,
            "duplicate": duplicate, "contact": contact, "before": before,
            "members_before": members_before, "first": first,
            "second": second, "revision": revision,
        }
    finally:
        store.close()


def test_a_new_graph_seeds_only_the_pipeline_on_the_canvas(fresh):
    store, registry, seeded = fresh
    markers, _projection = _user_markers(store, registry)
    stamped = sorted(marker for marker in markers if marker)
    assert stamped == sorted(PIPELINE), stamped
    assert seeded["counts"]["declared"] == len(_ALL_SEED)
    assert seeded["skipped"] == [], seeded["skipped"]


def test_each_status_card_is_seeded_into_its_lens(fresh):
    store, registry, seeded = fresh
    snapshot = store.snapshot()
    canvas = set(_canvas_roots(snapshot, registry)[0])
    for title, properties in _ALL_SEED:
        lens = _LENS_OF_MARKER.get(properties[_SEED_MARKER])
        if lens is None:
            continue
        root = seeded["placed"][title]
        assert root in _members(snapshot, registry, lens_scope_root(registry, lens)), title
        assert root not in canvas, "%s is still an app:canvas member" % title


def test_lens_cards_take_free_slots_not_one_point(fresh):
    store, registry, seeded = fresh
    owned = _owner_properties(store.snapshot(), registry)
    by_lens = {}
    for title, properties in _ALL_SEED:
        lens = _LENS_OF_MARKER.get(properties[_SEED_MARKER])
        if lens is None:
            continue
        rows = owned[seeded["placed"][title]]
        by_lens.setdefault(lens, []).append((
            float(rows["position_x"][1]), float(rows["position_y"][1]), *card_size()))
    for lens, rects in by_lens.items():
        for index, left in enumerate(rects):
            for right in rects[index + 1:]:
                assert not intersects(left, right), (lens, left, right)


def test_the_migration_moves_membership_in_one_commit(migrated):
    first = migrated["first"]
    assert first["committed"] is True and first["skipped"] == [], first["skipped"]
    assert first["by_reason"] == {
        "lens": sum(1 for _t, p in _ALL_SEED if p[_SEED_MARKER] in _LENS_OF_MARKER),
        "contact": 1,
    }, first["by_reason"]
    assert first["tombstoned"] == 1
    # Idempotent: the record is held, the next boot commits nothing.
    assert migrated["second"]["committed"] is False
    assert migrated["store"].revision == migrated["revision"]


def test_the_migration_runs_in_small_batches_that_hold_the_lock_briefly(migrated):
    """Smoothness is a gate: preparation runs off the lock, each batch holds
    it only for its own commit, and the batches add up to the whole move."""
    batches = migrated["first"]["batches"]
    assert len(batches) > 1, batches
    assert all(batch["committed"] for batch in batches)
    assert sum(batch["roots"] for batch in batches) == (
        migrated["first"]["moved"] + migrated["first"]["tombstoned"]
        + len(migrated["first"]["skipped"]))
    assert max(batch["lock_seconds"] for batch in batches) < 1.0, batches


def test_after_migration_the_canvas_shows_only_the_pipeline(migrated):
    store, registry = migrated["store"], migrated["registry"]
    markers, projection = _user_markers(store, registry)
    assert sorted(m for m in markers if m) == sorted(PIPELINE)
    labels = [node.get("label") for node in projection["nodes"] if not node.get("application")]
    assert not any(str(label).startswith("Contact:") for label in labels), labels
    # And none of what stays overlaps: the old grid put Revit Sessions under
    # Sketch Lines' last rows; the migration re-placed it.
    assert projection["layout"] == {"arrange_on_open": [], "overlap_badge": []}, projection["layout"]
    assert migrated["first"]["spaced"], "nothing overlapped in the old layout"


def test_after_migration_every_card_is_in_its_lens(migrated):
    store, registry = migrated["store"], migrated["registry"]
    snapshot = store.snapshot()
    for marker, root in migrated["placed"].items():
        lens = _LENS_OF_MARKER.get(marker)
        if lens is not None:
            assert root in _members(snapshot, registry, lens_scope_root(registry, lens)), marker
    assert migrated["contact"] in _members(snapshot, registry, registry.workshop_workbench_root)
    # Each lens holds its arrivals in free space.
    from nodelang.canvas_placement import overlapping
    from nodelang.universal_pipeline import scope_card_bounds
    for lens in set(_LENS_OF_MARKER.values()):
        bounds = scope_card_bounds(snapshot, registry, lens_scope_root(registry, lens))
        arrived = {root for marker, root in migrated["placed"].items()
                   if _LENS_OF_MARKER.get(marker) == lens}
        assert not (overlapping(bounds) & arrived), (lens, overlapping(bounds) & arrived)


def test_the_duplicate_is_tombstoned_by_marker_and_nothing_is_lost(migrated):
    store, registry = migrated["store"], migrated["registry"]
    snapshot = store.snapshot()
    canvas = set(_canvas_roots(snapshot, registry)[0])
    kept = migrated["placed"]["sketch-lines"]
    assert kept in canvas and migrated["duplicate"] not in canvas
    assert migrated["duplicate"] in migration_tombstones(snapshot, registry)
    # Append-only: every cell that existed before the migration still exists.
    missing = migrated["before"] - set(snapshot.cells)
    assert not missing, sorted(missing)[:5]
    # Every root that left the canvas is held somewhere: a lens or the record.
    left = migrated["members_before"] - canvas
    homes = set()
    for scope in (
        *(lens_scope_root(registry, lens) for lens in set(_LENS_OF_MARKER.values())),
        registry.workshop_workbench_root,
    ):
        homes |= _members(snapshot, registry, scope)
    homes |= migration_tombstones(snapshot, registry)
    assert left <= homes, sorted(left - homes)


def test_free_slot_never_lands_on_a_card():
    occupied = [(240.0, 200.0, 240.0, 120.0), (528.0, 200.0, 520.0, 300.0)]
    x, y = free_slot(occupied, (240.0, 120.0))
    candidate = (x, y, 240.0, 120.0)
    assert not any(intersects(candidate, rect, 48.0) for rect in occupied)
    assert free_slot([], (240.0, 120.0)) == (240.0, 200.0)


def test_an_ai_card_is_placed_by_its_real_width():
    assert card_size("ai.chat")[0] == 520.0
    assert card_size("lines.watch")[0] == 240.0


def test_overlaps_are_arranged_unless_pinned():
    nodes = [
        {"id": "a", "x": 0, "y": 0, "pinned": False},
        {"id": "b", "x": 10, "y": 10, "pinned": True},
        {"id": "c", "x": 2000, "y": 2000, "pinned": False},
    ]
    verdict = arrange_on_open(nodes)
    assert verdict == {"arrange": ["a"], "badge": ["b"]}
    assert [node["overlap"] for node in nodes] == ["arrange", "pinned", None]


def test_the_canvas_answer_carries_the_layout_contract(fresh):
    store, registry, _seeded = fresh
    projection = project_universal_canvas(store, registry)
    assert set(projection["layout"]) == {"arrange_on_open", "overlap_badge"}
    assert all("overlap" in node for node in projection["nodes"] if not node.get("application"))


# ---------------------------------------------- the canvas never stalls --
# Each migration batch commits in the background while the app is open. A
# canvas read after a commit used to re-project the whole graph (22-26 s on
# the founder's graph, once per batch). The batch leaves an accelerator note
# and carries the remembered answer across; the note is disposable: delete
# or corrupt it and the answer is the same, only rebuilt.

def _old_shape_graph():
    store, registry = build_universal_application(resolve_map_path())
    catalogue = project_universal_canvas(store, registry)["catalog"]
    definition = next(
        str(item["id"]) for item in catalogue if item.get("name") == "Ordered List"
    )

    def old_seed_card(title, properties, x, y):
        root, _ = instantiate_universal_definition(
            store, registry, definition, x=x, y=y, title_override=title,
        )
        for label, value in properties.items():
            create_universal_property(store, registry, root, label, str(value))
        return root

    roots = [
        old_seed_card(title, properties,
                      240.0 + (index % 4) * 320.0, 200.0 + (index // 4) * 180.0)
        for index, (title, properties) in enumerate(_ALL_SEED)
    ]
    old_seed_card("Sketch Lines", {"seed": "sketch-lines",
                                   "engine": "vision.sketch_lines"}, 240.0, 200.0)
    instantiate_universal_primitive(
        store, registry, x=240.0, y=200.0, title="Contact: a live session",
        atom=json.dumps({"kind": "native-contact", "version": 1}),
    )
    # The founder works on the pipeline: a kept card is the one selected.
    # (A selected card that leaves is never carried; that read rebuilds.)
    select_universal_root(store, registry, roots[0])
    return store, registry


def _rebuilt(store, registry):
    """The canvas answer from scratch: the interpreter, no accelerator."""
    from nodelang.universal_application import _project_universal_canvas_interpreter
    answer = _project_universal_canvas_interpreter(store, registry)
    verdict = arrange_on_open([n for n in answer["nodes"] if not n.get("application")])
    answer["layout"] = {"arrange_on_open": verdict["arrange"],
                        "overlap_badge": verdict["badge"]}
    return json.loads(json.dumps(answer))


def _migrate_reading_after_each_batch(note_hook=None, monkeypatch=None, lens=None):
    import time
    from nodelang import universal_application as application
    store, registry = _old_shape_graph()
    if lens is not None:
        application.set_universal_scope(store, registry, lens_scope_root(registry, lens))
    project_universal_canvas(store, registry)  # the Studio has the canvas open
    if note_hook is not None:
        real = application.note_canvas_membership_change
        monkeypatch.setattr(application, "note_canvas_membership_change",
                            lambda store_, **note: note_hook(real, store_, note))
    reads = []

    def after(batch):
        started = time.perf_counter()
        fast = json.loads(json.dumps(project_universal_canvas(store, registry)))
        fast_seconds = time.perf_counter() - started
        started = time.perf_counter()
        full = _rebuilt(store, registry)
        full_seconds = time.perf_counter() - started
        reads.append({"batch": batch, "fast": fast, "full": full,
                      "fast_seconds": fast_seconds, "full_seconds": full_seconds})

    settle_canvas_content(store, registry, batch_size=3, pause=0, after_batch=after)
    store.close()
    return reads


def test_a_read_after_each_batch_is_carried_not_rebuilt():
    reads = _migrate_reading_after_each_batch()
    assert len(reads) > 1
    for read in reads:
        assert read["batch"]["canvas_carried"] is True, read["batch"]
        assert read["fast"] == read["full"], read["batch"]
        # The stated bound, and the rebuild it avoids shown on the same graph.
        assert read["fast_seconds"] < 1.0, read["fast_seconds"]
        assert read["fast_seconds"] < read["full_seconds"], (
            read["fast_seconds"], read["full_seconds"])


@pytest.mark.parametrize("damage", ["deleted", "corrupted"])
def test_the_batch_note_is_only_an_accelerator(damage, monkeypatch):
    from nodelang.universal_application import clear_canvas_membership_notes

    def hook(real, store, note):
        if damage == "deleted":
            real(store, **note)
            clear_canvas_membership_notes(store)
        else:
            cells = list(note["cells"])
            real(store, **{**note, "cells": cells[1:] + ["app:not-a-cell-of-this-batch"]})

    reads = _migrate_reading_after_each_batch(hook, monkeypatch)
    assert reads
    for read in reads:
        assert read["batch"]["canvas_carried"] is False, read["batch"]
        # Same meaning, only rebuilt.
        assert read["fast"] == read["full"], read["batch"]


def test_a_view_standing_inside_a_lens_is_rebuilt_not_carried():
    """Cards ARRIVE in a lens: that answer is never carried, only rebuilt."""
    reads = _migrate_reading_after_each_batch(lens="brain")
    assert reads
    for read in reads:
        assert read["batch"]["canvas_carried"] is False, read["batch"]
        assert read["fast"] == read["full"], read["batch"]


def test_a_studio_that_did_not_read_between_batches_is_still_carried(monkeypatch):
    """The Studio may read once after several batches: the notes chain."""
    import time
    from nodelang import universal_application as application
    store, registry = _old_shape_graph()
    try:
        project_universal_canvas(store, registry)
        # Nothing carries the answer batch by batch: only the next read can.
        monkeypatch.setattr(application, "advance_canvas_accelerator",
                            lambda *args, **kwargs: False)
        real = application._canvas_membership_delta
        answered = []

        def spy(*args, **kwargs):
            result = real(*args, **kwargs)
            answered.append(result is not None)
            return result

        monkeypatch.setattr(application, "_canvas_membership_delta", spy)
        outcome = settle_canvas_content(store, registry, batch_size=3, pause=0)
        assert len(outcome["batches"]) > 1
        started = time.perf_counter()
        fast = json.loads(json.dumps(project_universal_canvas(store, registry)))
        fast_seconds = time.perf_counter() - started
        assert answered == [True], answered
        assert fast == _rebuilt(store, registry)
        assert fast_seconds < 1.0, fast_seconds
    finally:
        store.close()


# ------------------------------------------ v2: what the migration may do --
# The verifier of v1 (2026-09-28) found four ways it could lose or misstate
# the founder's work. Each court below is shown RED on v1.

def _graph_with_copies(copies):
    """An old-shape graph plus extra copies: (title, properties, wire_to)."""
    store, registry = build_universal_application(resolve_map_path())
    catalogue = project_universal_canvas(store, registry)["catalog"]
    definition = next(
        str(item["id"]) for item in catalogue if item.get("name") == "Ordered List"
    )

    def old_seed_card(title, properties, x, y):
        root, _ = instantiate_universal_definition(
            store, registry, definition, x=x, y=y, title_override=title,
        )
        for label, value in properties.items():
            create_universal_property(store, registry, root, label, str(value))
        return root

    placed = {
        properties[_SEED_MARKER]: old_seed_card(
            title, properties, 240.0 + (index % 4) * 320.0, 200.0 + (index // 4) * 180.0)
        for index, (title, properties) in enumerate(_ALL_SEED)
    }
    extra = []
    for index, (title, properties) in enumerate(copies):
        extra.append(old_seed_card(title, properties, 1600.0 + index * 300.0, 900.0))
    return store, registry, placed, extra


def _seed_properties(marker):
    return next(dict(p) for _t, p in _ALL_SEED if p[_SEED_MARKER] == marker)


def _batch_relations(snapshot):
    """Every committed batch relation, read by key order (no v2 helper)."""
    from nodelang.universal_cell import ids_with_prefix
    from nodelang.universal_pipeline import CANVAS_CONTENT_MIGRATION_ROOT
    prefix = CANVAS_CONTENT_MIGRATION_ROOT + ":batch:"
    return sorted(root for root in ids_with_prefix(snapshot.cells, prefix)
                  if len(root) == len(prefix) + 32)


def _batches_naming(snapshot, registry, root):
    return [batch for batch in _batch_relations(snapshot)
            if root in _members(snapshot, registry, batch)]


def test_an_edited_copy_is_never_tombstoned():
    edited = {**_seed_properties("cad-lines"), "layer": "A-WALL"}
    store, registry, placed, (copy,) = _graph_with_copies([("CAD Lines", edited)])
    try:
        outcome = settle_canvas_content(store, registry, batch_size=4, pause=0)
        gone = migration_tombstones(store.snapshot(), registry)
        assert copy not in gone and placed["cad-lines"] not in gone, sorted(gone)
        # Reported, not silently kept or dropped.
        assert any(copy in skip["roots"] for skip in outcome["skipped"]), outcome["skipped"]
    finally:
        store.close()


def test_a_copy_that_differs_only_in_its_last_answer_is_still_tombstoned():
    """"status" is what the run last answered, rewritten on the next run:
    on the founder's graph two copies differed only there (rehearsal,
    2026-09-29). That is not the founder's edit, so it is not kept."""
    answered = {**_seed_properties("brain-facts"), "status": "2580 fact row(s)"}
    store, registry, placed, (copy,) = _graph_with_copies([("Brain Facts", answered)])
    try:
        create_universal_property(store, registry, placed["brain-facts"], "status",
                                  "2613 fact row(s)")
        outcome = settle_canvas_content(store, registry, batch_size=4, pause=0)
        gone = migration_tombstones(store.snapshot(), registry)
        assert outcome["skipped"] == [], outcome["skipped"]
        assert len({copy, placed["brain-facts"]} & gone) == 1, sorted(gone)
    finally:
        store.close()


def test_a_wired_copy_is_kept_and_the_untouched_one_goes():
    """The copy the founder wired is the one kept, even when it came later."""
    from nodelang.universal_application import connect_universal_roots
    from nodelang.universal_pipeline import _ensure_pipeline_node_interfaces
    store, registry, placed, (copy,) = _graph_with_copies(
        [("Line Watcher", _seed_properties("line-watcher"))])
    try:
        target = placed["revit-walls"]
        for root in (copy, target):
            _ensure_pipeline_node_interfaces(store, registry, root)
        # The seed reads the canvas here: that read settles the visibility of
        # the interfaces it just made. Then the same wire the seed draws.
        project_universal_canvas(store, registry)
        connect_universal_roots(
            store, registry, copy, target,
            source_interface="app:pipeline-interface:%s:source" % copy.rsplit(":", 1)[-1],
            target_interface="app:pipeline-interface:%s:target" % target.rsplit(":", 1)[-1],
        )
        project_universal_canvas(store, registry)
        settle_canvas_content(store, registry, batch_size=4, pause=0)
        snapshot = store.snapshot()
        gone = migration_tombstones(snapshot, registry)
        assert copy not in gone, "the wired copy was tombstoned"
        assert copy in set(_canvas_roots(snapshot, registry)[0])
        assert placed["line-watcher"] in gone, "the untouched copy should go"
    finally:
        store.close()


def test_an_interrupted_run_is_finished_and_the_record_names_every_batch():
    from nodelang.universal_pipeline import CANVAS_CONTENT_MIGRATION_ROOT
    _migration_batch_relations = _batch_relations
    store, registry, placed, copies = _graph_with_copies([
        ("CAD Lines", _seed_properties("cad-lines")),
        ("Line Watcher", _seed_properties("line-watcher")),
    ])
    try:
        class Stop(Exception):
            pass

        def interrupt(batch):
            if _migration_batch_relations(store.snapshot()):
                raise Stop()

        with pytest.raises(Stop):
            settle_canvas_content(store, registry, batch_size=1, pause=0,
                                  after_batch=interrupt)
        first_batches = _migration_batch_relations(store.snapshot())
        assert len(first_batches) == 1, first_batches
        finished = settle_canvas_content(store, registry, batch_size=1, pause=0)
        snapshot = store.snapshot()
        every = set(_migration_batch_relations(snapshot))
        assert len(every) == 2, every
        # The record names the interrupted run's batch too, not only its own.
        assert _members(snapshot, registry, CANVAS_CONTENT_MIGRATION_ROOT) == every
        assert finished.get("done") is True, finished
    finally:
        store.close()


def test_a_refused_move_is_recorded_not_done_and_not_retried_unchanged(monkeypatch):
    from nodelang import universal_application as application
    from nodelang.universal_cell import InvalidCell
    from nodelang.universal_pipeline import CANVAS_CONTENT_MIGRATION_ROOT
    store, registry, placed, _copies = _graph_with_copies([])
    refused = placed["brain-recall"]
    real = application.prepare_universal_retraction

    def refuse(snapshot, registry_, view_session, root, *args, **kwargs):
        if root == refused:
            raise InvalidCell("court: this move is refused")
        return real(snapshot, registry_, view_session, root, *args, **kwargs)

    try:
        monkeypatch.setattr(application, "prepare_universal_retraction", refuse)
        first = settle_canvas_content(store, registry, batch_size=4, pause=0)
        # Nothing is "done" while a root was left behind.
        assert CANVAS_CONTENT_MIGRATION_ROOT not in store.snapshot().cells
        assert [skip["root"] for skip in first["skipped"]] == [refused], first["skipped"]
        assert first.get("done") is False
        # The next open does not retry it unchanged: nothing is written.
        revision = store.revision
        again = settle_canvas_content(store, registry, batch_size=4, pause=0)
        assert store.revision == revision, again
        assert again["skipped"] == [] and again.get("recorded_skips") == 1, again
        # Once the card changes, it is planned again, and this time it moves.
        monkeypatch.setattr(application, "prepare_universal_retraction", real)
        create_universal_property(store, registry, refused, "note", "moved by hand")
        last = settle_canvas_content(store, registry, batch_size=4, pause=0)
        assert last.get("done") is True, last
        assert refused in _members(store.snapshot(), registry,
                                   lens_scope_root(registry, "brain"))
    finally:
        store.close()


@pytest.mark.parametrize("forged", ["position", "removed"])
def test_a_forged_note_is_rebuilt_never_carried(forged, monkeypatch):
    """The note names exactly the Cells that changed, but lies about them."""
    from nodelang import universal_application as application
    store, registry = _old_shape_graph()
    try:
        project_universal_canvas(store, registry)  # the Studio has the canvas open
        view_session, _context = application._view_session_for_context(registry, None)
        real = application.note_canvas_membership_change

        def forge(store_, **note):
            snapshot = store_.snapshot()
            owned = _owner_properties(snapshot, registry)
            shown = {
                member.participant_id
                for member in read_relation(snapshot, view_session.visibility_root, budget=300_000)
                if member.role_id == registry.roles["visible"]
            }
            # Still drawn, not selected, never moved by this run: CAD Lines.
            victim = next(root for root in shown
                          if ((owned.get(root) or {}).get(_SEED_MARKER) or ("", ""))[1]
                          == "cad-lines")
            if forged == "position":
                note["positions"] = {**dict(note.get("positions") or {}),
                                     victim: (13.0, 17.0)}
            else:
                note["removed"] = (*tuple(note.get("removed") or ()), victim)
            real(store_, **note)

        monkeypatch.setattr(application, "note_canvas_membership_change", forge)
        reads = []

        def after(batch):
            reads.append({"batch": batch,
                          "fast": json.loads(json.dumps(project_universal_canvas(store, registry))),
                          "full": _rebuilt(store, registry)})

        settle_canvas_content(store, registry, batch_size=3, pause=0, after_batch=after)
        assert reads
        for read in reads:
            assert read["batch"]["canvas_carried"] is False, read["batch"]
            assert read["fast"] == read["full"], read["batch"]
    finally:
        store.close()

def test_seeding_while_the_migration_runs_starts_no_second_run():
    import threading
    store, registry, placed, _copies = _graph_with_copies([
        ("CAD Lines", _seed_properties("cad-lines")),
        ("Line Watcher", _seed_properties("line-watcher")),
    ])
    paused, resume = threading.Event(), threading.Event()
    outcome = {}

    def after(batch):
        if not paused.is_set():
            paused.set()
            resume.wait(60)

    def background():
        outcome["background"] = settle_canvas_content(
            store, registry, batch_size=1, pause=0, after_batch=after,
            lock=threading.Lock())

    worker = threading.Thread(target=background)
    try:
        worker.start()
        assert paused.wait(60), "the background run never reached its first batch"
        seeded = seed_wall_pipeline(store, registry)
        resume.set()
        worker.join(120)
        assert seeded["settled"].get("in_flight") is True, seeded["settled"]
        assert outcome["background"].get("done") is True, outcome
        snapshot = store.snapshot()
        for root in migration_tombstones(snapshot, registry):
            assert len(_batches_naming(snapshot, registry, root)) == 1, root
    finally:
        resume.set()
        worker.join(5)
        store.close()


# ------------------------------------------ v3: judged when its batch acts --
# The v2 reviewer (2026-09-29): the plan was made once, so a card the
# founder touched while the run was under way was still tombstoned or moved;
# a card moved by hand before "placed" existed was re-placed; a grouped copy
# lost its canvas row. Each court below is shown RED on v2.

def _rows(store, registry, root):
    return {k: v for k, (_r, v) in (_owner_properties(store.snapshot(), registry).get(root) or {}).items()}


@pytest.mark.parametrize("touch", ["edit", "pin"])
def test_a_copy_touched_while_the_run_is_under_way_is_not_tombstoned(touch):
    """The run is planned batch by batch: a card the user changes after the
    run began is judged by what it is when its own batch commits."""
    from nodelang.universal_application import _USER_PLACEMENT
    store, registry, placed, (copy,) = _graph_with_copies(
        [("Line Watcher", _seed_properties("line-watcher"))])
    try:
        touched = []

        def after(batch):
            if touched:
                return
            touched.append(batch)
            if touch == "edit":
                create_universal_property(store, registry, copy, "note", "the founder's")
            else:
                create_universal_property(store, registry, copy, "placed", _USER_PLACEMENT)

        outcome = settle_canvas_content(store, registry, batch_size=1, pause=0,
                                        after_batch=after)
        assert touched, "the run never reached a second batch"
        gone = migration_tombstones(store.snapshot(), registry)
        assert copy not in gone, outcome.get("tombstones")
    finally:
        store.close()


def test_a_card_moved_by_hand_before_placed_existed_is_never_re_placed():
    """"placed" exists only since 2026-09-25 (4f981f0). A seed card standing
    anywhere but a point a seed table gave it was moved by someone: even
    overlapping another card, the migration leaves it where it is."""
    from nodelang.universal_application import edit_universal_property
    store, registry, placed, _copies = _graph_with_copies([])
    try:
        sketch = placed["sketch-lines"]
        rows = _owner_properties(store.snapshot(), registry)[sketch]
        cad = _rows(store, registry, placed["cad-lines"])
        # Dragged long ago onto CAD Lines' rows, before "placed" was written.
        x, y = float(cad["position_x"]) + 10.0, float(cad["position_y"]) + 10.0
        edit_universal_property(store, registry, rows["position_x"][0], str(x))
        edit_universal_property(store, registry, rows["position_y"][0], str(y))
        assert "placed" not in _rows(store, registry, sketch)
        settle_canvas_content(store, registry, batch_size=4, pause=0)
        after = _rows(store, registry, sketch)
        assert (float(after["position_x"]), float(after["position_y"])) == (x, y)
    finally:
        store.close()


def test_a_grouped_copy_keeps_its_group_and_is_never_tombstoned():
    from nodelang.universal_application import (
        group_universal_selection,
        set_universal_selection,
    )
    store, registry, placed, (copy,) = _graph_with_copies(
        [("CAD Lines", _seed_properties("cad-lines"))])
    try:
        set_universal_selection(store, registry, [copy, placed["line-watcher"]])
        group_universal_selection(store, registry,
                                  projected_canvas=project_universal_canvas(store, registry))
        assert copy in set(_canvas_roots(store.snapshot(), registry)[0])
        settle_canvas_content(store, registry, batch_size=4, pause=0)
        snapshot = store.snapshot()
        assert copy not in migration_tombstones(snapshot, registry)
        assert copy in set(_canvas_roots(snapshot, registry)[0]), "the grouped copy lost its canvas row"
        project_universal_canvas(store, registry)  # the canvas still opens
    finally:
        store.close()


def test_a_card_inside_an_application_scope_is_not_in_a_user_group():
    """The Workshop Workbench is built like a group but the application made it
    (rehearsal 2026-09-29: 177 of 178 sessions on the founder's canvas sit in
    it). Only a group the USER made counts as touched."""
    from nodelang.universal_pipeline import prepare_append_relation_members
    store, registry, placed, (copy,) = _graph_with_copies(
        [("CAD Lines", _seed_properties("cad-lines"))])
    try:
        snapshot = store.snapshot()
        patch = prepare_append_relation_members(
            snapshot, registry.workshop_workbench_root,
            ((registry.roles["member"], copy),), budget=300_000)
        store.commit(snapshot.revision, create=patch.create, replace=patch.replace)
        assert copy in _members(store.snapshot(), registry, registry.workshop_workbench_root)
        settle_canvas_content(store, registry, batch_size=4, pause=0)
        assert copy in migration_tombstones(store.snapshot(), registry)
    finally:
        store.close()

def test_a_graph_holding_a_user_group_is_migrated_and_still_opens():
    """A group anywhere on the canvas: every batch that takes a card off
    beside it signs the group's grants anew, and the run still finishes."""
    from nodelang.universal_application import (
        group_universal_selection,
        set_universal_selection,
    )
    from nodelang.universal_pipeline import CANVAS_CONTENT_MIGRATION_ROOT
    store, registry, placed, (copy,) = _graph_with_copies(
        [("CAD Lines", _seed_properties("cad-lines"))])
    try:
        set_universal_selection(store, registry, [placed["line-watcher"], placed["revit-walls"]])
        group_universal_selection(store, registry,
                                  projected_canvas=project_universal_canvas(store, registry))
        result = settle_canvas_content(store, registry, batch_size=1, pause=0)
        snapshot = store.snapshot()
        assert result["done"] and CANVAS_CONTENT_MIGRATION_ROOT in snapshot.cells
        assert copy in migration_tombstones(snapshot, registry)
        on_canvas = set(_canvas_roots(snapshot, registry)[0])
        assert {placed["line-watcher"], placed["revit-walls"]} <= on_canvas
        assert not {root for marker, root in placed.items() if marker in _LENS_OF_MARKER} & on_canvas
        project_universal_canvas(store, registry)  # the canvas still opens
    finally:
        store.close()


def test_a_graph_with_nothing_to_move_records_that_it_is_done():
    """A first look that finds nothing to do writes the done record once, so
    the next open does not plan again."""
    from nodelang.universal_pipeline import CANVAS_CONTENT_MIGRATION_ROOT
    store, registry = build_universal_application(resolve_map_path())
    try:
        seed_wall_pipeline(store, registry)
        assert CANVAS_CONTENT_MIGRATION_ROOT in store.snapshot().cells
        revision = store.revision
        again = settle_canvas_content(store, registry, batch_size=4, pause=0)
        assert again["committed"] is False and store.revision == revision
    finally:
        store.close()
