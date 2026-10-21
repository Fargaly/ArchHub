"""Courts for the brain's secret vault: it holds the place, never the secret."""
from __future__ import annotations

import pytest

from nodelang.cell_brain_secrets import (
    ADMITTED_CUSTODY,
    VAULT_ROOT,
    admit_secret,
    project_vault,
    read_secret_reference,
    resolve_secret,
)
from nodelang.universal_cell import CellStore, InvalidCell

REAL_LOOKING_SECRET = "ah_live_9f3c1b7e5d2a8460bb17e4c9f0d3a25e"


def _vault():
    store = CellStore()
    admit_secret(
        store,
        name="anthropic",
        reference="op://archhub/models/anthropic",
        custody="operator-vault",
    )
    return store


def test_the_vault_holds_where_a_secret_lives_and_who_holds_it():
    store = _vault()
    entry = read_secret_reference(store.snapshot(), "anthropic")
    assert entry.reference == "op://archhub/models/anthropic"
    assert entry.custody == "operator-vault"


def test_a_real_looking_credential_is_refused_and_nothing_changes():
    store = _vault()
    before = store.snapshot().revision
    with pytest.raises(InvalidCell):
        admit_secret(
            store, name="leak", reference=REAL_LOOKING_SECRET,
            custody="operator-vault",
        )
    assert store.snapshot().revision == before
    assert [e.name for e in project_vault(store.snapshot())] == ["anthropic"]


def test_a_reference_that_is_not_a_place_is_refused():
    store = _vault()
    with pytest.raises(InvalidCell):
        admit_secret(
            store, name="plain", reference="just-a-string",
            custody="operator-vault",
        )


def test_custody_the_graph_does_not_admit_is_refused():
    store = _vault()
    with pytest.raises(InvalidCell):
        admit_secret(
            store, name="elsewhere", reference="op://archhub/x",
            custody="the-graph-itself",
        )
    assert "the-graph-itself" not in ADMITTED_CUSTODY


def test_no_projection_of_the_vault_can_contain_a_secret():
    store = _vault()
    admit_secret(
        store, name="aws", reference="kms://archhub/relations/aes",
        custody="cloud-kms",
    )
    rendered = repr(project_vault(store.snapshot()))
    assert REAL_LOOKING_SECRET not in rendered
    for cell in store.snapshot().cells.values():
        assert REAL_LOOKING_SECRET.encode() not in bytes(cell.atom)


def test_resolution_goes_through_custody_and_writes_nothing_back():
    store = _vault()
    asked = []

    def resolver(reference: str, custody: str) -> str:
        asked.append((reference, custody))
        return REAL_LOOKING_SECRET

    before = store.snapshot().revision
    value = resolve_secret(store.snapshot(), "anthropic", resolver)
    assert value == REAL_LOOKING_SECRET
    assert asked == [("op://archhub/models/anthropic", "operator-vault")]
    assert store.snapshot().revision == before
    for cell in store.snapshot().cells.values():
        assert REAL_LOOKING_SECRET.encode() not in bytes(cell.atom)


def test_custody_returning_nothing_is_an_error_not_an_empty_secret():
    store = _vault()
    with pytest.raises(InvalidCell):
        resolve_secret(store.snapshot(), "anthropic", lambda ref, custody: "")


def test_an_unknown_name_is_refused_rather_than_answered_emptily():
    store = _vault()
    with pytest.raises(InvalidCell):
        read_secret_reference(store.snapshot(), "does-not-exist")


def test_the_same_name_cannot_be_admitted_twice():
    store = _vault()
    with pytest.raises(InvalidCell):
        admit_secret(
            store, name="anthropic", reference="op://archhub/other",
            custody="os-keystore",
        )


def test_no_vault_remembers_nothing():
    store = CellStore()
    assert VAULT_ROOT not in store.snapshot().cells
    assert project_vault(store.snapshot()) == ()
