"""Courts for groups and join codes: fingerprints in, codes never out."""
from __future__ import annotations

import pytest

from nodelang.cell_brain_groups import (
    GROUPS_ROOT,
    code_is_readable,
    create_group,
    issue_join_code,
    join_with_code,
    read_group,
)
from nodelang.universal_cell import NULL_CELL_ID, Cell, CellStore, InvalidCell

OWNER = "identity:founder"
GUEST = "identity:guest"
STRANGER = "identity:stranger"
GROUP = "group:aec-practice"
CODE = "join-me-9f3c1b7e"


def _store():
    store = CellStore()
    store.commit(store.revision, create=tuple(
        Cell(root, NULL_CELL_ID, NULL_CELL_ID, root.encode())
        for root in (OWNER, GUEST, STRANGER)
    ))
    create_group(store, group_root=GROUP, owner_root=OWNER)
    return store


def test_a_group_has_one_owner_who_is_already_a_member():
    store = _store()
    group = read_group(store.snapshot(), GROUP)
    assert group.owner_root == OWNER
    assert group.member_roots == (OWNER,)


def test_the_graph_never_holds_the_join_code_itself():
    store = _store()
    issue_join_code(store, group_root=GROUP, code=CODE, issuer_root=OWNER)
    assert code_is_readable(store.snapshot(), GROUP, CODE) is False


def test_only_the_owner_may_issue_a_code():
    store = _store()
    with pytest.raises(InvalidCell):
        issue_join_code(store, group_root=GROUP, code=CODE, issuer_root=GUEST)


def test_a_short_code_is_refused_as_guessable():
    store = _store()
    with pytest.raises(InvalidCell):
        issue_join_code(store, group_root=GROUP, code="short", issuer_root=OWNER)


def test_the_right_code_joins():
    store = _store()
    issue_join_code(store, group_root=GROUP, code=CODE, issuer_root=OWNER)
    join_with_code(store, group_root=GROUP, code=CODE, member_root=GUEST)
    assert read_group(store.snapshot(), GROUP).member_roots == (OWNER, GUEST)


def test_a_wrong_code_is_refused_and_nobody_joins():
    store = _store()
    issue_join_code(store, group_root=GROUP, code=CODE, issuer_root=OWNER)
    with pytest.raises(InvalidCell):
        join_with_code(
            store, group_root=GROUP, code="join-me-WRONGXX", member_root=STRANGER)
    assert read_group(store.snapshot(), GROUP).member_roots == (OWNER,)


def test_a_code_cannot_be_spent_twice():
    store = _store()
    issue_join_code(store, group_root=GROUP, code=CODE, issuer_root=OWNER)
    join_with_code(store, group_root=GROUP, code=CODE, member_root=GUEST)
    with pytest.raises(InvalidCell):
        join_with_code(store, group_root=GROUP, code=CODE, member_root=STRANGER)


def test_a_code_for_one_group_does_not_open_another():
    store = _store()
    create_group(store, group_root="group:other", owner_root=OWNER)
    issue_join_code(store, group_root=GROUP, code=CODE, issuer_root=OWNER)
    with pytest.raises(InvalidCell):
        join_with_code(
            store, group_root="group:other", code=CODE, member_root=GUEST)


def test_the_same_code_cannot_be_issued_twice():
    store = _store()
    issue_join_code(store, group_root=GROUP, code=CODE, issuer_root=OWNER)
    with pytest.raises(InvalidCell):
        issue_join_code(store, group_root=GROUP, code=CODE, issuer_root=OWNER)


def test_a_group_that_already_exists_is_refused():
    store = _store()
    with pytest.raises(InvalidCell):
        create_group(store, group_root=GROUP, owner_root=OWNER)


def test_joining_a_group_that_does_not_exist_is_refused():
    store = _store()
    with pytest.raises(InvalidCell):
        join_with_code(
            store, group_root="group:nowhere", code=CODE, member_root=GUEST)


def test_no_groups_hold_nothing():
    store = CellStore()
    assert GROUPS_ROOT not in store.snapshot().cells
