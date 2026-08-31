"""Courts for what the public page claims: derived, in voice, and released."""
from __future__ import annotations

import pytest

from nodelang.cell_website_meta import (
    DRAFT,
    META_ROOT,
    changelog,
    describe_page,
    downloads,
    offer_download,
    page_meta,
    record_release,
    set_origin,
)
from nodelang.universal_cell import NULL_CELL_ID, Cell, CellStore, InvalidCell

PATH = "/website/features"


def _store():
    store = CellStore()
    store.commit(store.revision, create=(
        Cell("artifact:installer", NULL_CELL_ID, NULL_CELL_ID, b"installer"),))
    set_origin(store, "https://archhub.io")
    describe_page(
        store, path=PATH, title="One graph",
        description="Everything the product holds is one persisted shape.",
    )
    return store


def test_a_page_says_what_it_is_with_a_canonical_from_the_graph():
    store = _store()
    meta = page_meta(store.snapshot(), PATH)
    assert meta.title == "One graph"
    assert meta.canonical == "https://archhub.io/website/features"


def test_without_an_origin_no_canonical_link_can_be_built():
    store = CellStore()
    describe_page(store, path=PATH, title="One graph", description="A shape.")
    with pytest.raises(InvalidCell):
        page_meta(store.snapshot(), PATH)


def test_a_non_https_origin_is_refused():
    store = _store()
    with pytest.raises(InvalidCell):
        set_origin(store, "http://archhub.io")


def test_a_page_with_no_description_says_nothing_and_is_refused():
    store = _store()
    with pytest.raises(InvalidCell):
        describe_page(store, path="/website/x", title="Title", description="  ")


def test_a_page_that_breaks_the_voice_rules_is_refused():
    store = _store()
    with pytest.raises(InvalidCell):
        describe_page(
            store, path="/website/x", title="Seamless",
            description="It works instantly.",
        )


def test_a_page_that_never_described_itself_answers_nothing():
    store = _store()
    with pytest.raises(InvalidCell):
        page_meta(store.snapshot(), "/website/nowhere")


def test_the_changelog_holds_only_released_revisions():
    store = _store()
    record_release(store, revision="r2", summary="The canvas opens on the work.")
    record_release(
        store, revision="r3", summary="A draft note.", state=DRAFT)
    assert [note.revision for note in changelog(store.snapshot())] == ["r2"]


def test_a_release_with_no_summary_is_progress_theatre_and_is_refused():
    store = _store()
    with pytest.raises(InvalidCell):
        record_release(store, revision="r9", summary="   ")


def test_a_release_summary_must_be_in_voice():
    store = _store()
    with pytest.raises(InvalidCell):
        record_release(store, revision="r9", summary="Revolutionary release!")


def test_a_revision_cannot_enter_the_changelog_twice():
    store = _store()
    record_release(store, revision="r2", summary="The canvas opens on the work.")
    with pytest.raises(InvalidCell):
        record_release(store, revision="r2", summary="Again.")


def test_an_unreleased_revision_must_not_be_offered_for_download():
    store = _store()
    record_release(store, revision="r3", summary="A draft note.", state=DRAFT)
    with pytest.raises(InvalidCell):
        offer_download(store, artifact_root="artifact:installer", revision="r3")
    assert downloads(store.snapshot()) == ()


def test_a_released_revision_can_be_offered_once():
    store = _store()
    record_release(store, revision="r2", summary="The canvas opens on the work.")
    offer_download(store, artifact_root="artifact:installer", revision="r2")
    assert downloads(store.snapshot()) == ("r2",)
    with pytest.raises(InvalidCell):
        offer_download(store, artifact_root="artifact:installer", revision="r2")


def test_an_artifact_the_graph_does_not_hold_cannot_be_offered():
    store = _store()
    record_release(store, revision="r2", summary="The canvas opens on the work.")
    with pytest.raises(InvalidCell):
        offer_download(store, artifact_root="artifact:ghost", revision="r2")


def test_no_meta_claims_nothing():
    store = CellStore()
    assert META_ROOT not in store.snapshot().cells
    assert changelog(store.snapshot()) == ()
    assert downloads(store.snapshot()) == ()
