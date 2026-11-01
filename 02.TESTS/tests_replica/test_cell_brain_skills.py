"""Courts for the brain's skill library: learned, evidenced, recalled."""
from __future__ import annotations

import pytest

from nodelang.cell_brain_skills import (
    SKILL_LIBRARY_ROOT,
    mint_skill,
    read_skill,
    recall_skills,
)
from nodelang.cell_catalog import bootstrap_assembly_protocol
from nodelang.universal_cell import NULL_CELL_ID, Cell, CellStore, InvalidCell


def _store():
    store = CellStore()
    protocol = bootstrap_assembly_protocol(store)
    work = "work:harbor-revision-clouds"
    court = "court:harbor-revision-clouds:passed"
    store.commit(store.revision, create=(
        Cell(work, NULL_CELL_ID, NULL_CELL_ID, b"Harbor revision clouds"),
        Cell(court, NULL_CELL_ID, NULL_CELL_ID, b"passed"),
    ))
    return store, protocol, work, court


def test_a_minted_skill_is_a_draft_that_remembers_where_it_came_from():
    store, protocol, work, court = _store()
    root = mint_skill(
        store, protocol,
        skill_id="skill:place-revision-clouds",
        name="Place revision clouds",
        purpose="mark changed regions on a drawing",
        learned_from=(work,),
        evidence_roots=(court,),
    )
    skill = read_skill(store.snapshot(), protocol, root)
    assert skill.name == "Place revision clouds"
    assert skill.purpose == "mark changed regions on a drawing"
    assert work in skill.learned_from
    assert skill.released is False


def test_a_skill_without_a_purpose_is_refused():
    store, protocol, work, court = _store()
    with pytest.raises(InvalidCell):
        mint_skill(
            store, protocol, skill_id="skill:mute", name="Mute",
            purpose="   ", learned_from=(work,), evidence_roots=(court,),
        )


def test_a_skill_that_names_no_source_work_is_refused():
    store, protocol, _work, court = _store()
    with pytest.raises(InvalidCell):
        mint_skill(
            store, protocol, skill_id="skill:rootless", name="Rootless",
            purpose="appear from nowhere", learned_from=(), evidence_roots=(court,),
        )


def test_recall_with_no_library_remembers_nothing():
    store = CellStore()
    protocol = bootstrap_assembly_protocol(store)
    assert SKILL_LIBRARY_ROOT not in store.snapshot().cells
    assert recall_skills(store.snapshot(), protocol, "anything") == ()

