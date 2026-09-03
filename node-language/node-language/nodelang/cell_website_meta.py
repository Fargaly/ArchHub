"""What the public page says about itself, derived and refused when unproven.

Page metadata was hand-written beside the pages, so it drifted, and the download
button pointed at whatever the last build produced whether or not it was
released. Both are the same mistake: telling the public something the graph has
not proven.

Every string here goes through the voice rules on the way in, so the site cannot
say something the product would refuse to say. A changelog entry exists only for
a RELEASED revision, and a download exists only for a RELEASED artifact. There
is no default origin -- a canonical link the graph cannot justify is refused.
"""
from __future__ import annotations

from dataclasses import dataclass

from .cell_protocols import prepare_append_relation_members, read_relation
from .cell_voice import assert_in_voice
from .universal_cell import NULL_CELL_ID, Cell, InvalidCell

META_ROOT = "app:website:meta"
ORIGIN_ROOT = META_ROOT + ":origin"
PAGE_ROLE = META_ROOT + ":role:page"
TITLE_ROLE = META_ROOT + ":role:title"
DESCRIPTION_ROLE = META_ROOT + ":role:description"
RELEASE_ROLE = META_ROOT + ":role:release"
ARTIFACT_ROLE = META_ROOT + ":role:artifact"

RELEASED = META_ROOT + ":state:released"
DRAFT = META_ROOT + ":state:draft"


@dataclass(frozen=True, slots=True)
class PageMeta:
    path: str
    title: str
    description: str
    canonical: str


@dataclass(frozen=True, slots=True)
class ReleaseNote:
    revision: str
    summary: str


def _terminal(root_id, value):
    return Cell(root_id, NULL_CELL_ID, NULL_CELL_ID, str(value).encode("utf-8"))


def _text(snapshot, root_id):
    cell = snapshot.cells.get(root_id)
    if cell is None:
        raise InvalidCell("website meta text is missing at %s" % root_id)
    return bytes(cell.atom).decode("utf-8")


def ensure_meta(store):
    snapshot = store.snapshot()
    if META_ROOT in snapshot.cells:
        return META_ROOT
    store.commit(snapshot.revision, create=(
        _terminal(PAGE_ROLE, "page"), _terminal(TITLE_ROLE, "title"),
        _terminal(DESCRIPTION_ROLE, "description"),
        _terminal(RELEASE_ROLE, "release"), _terminal(ARTIFACT_ROLE, "artifact"),
        _terminal(RELEASED, "released"), _terminal(DRAFT, "draft"),
        Cell(META_ROOT, NULL_CELL_ID, NULL_CELL_ID, b"relation"),
    ))
    return META_ROOT


def set_origin(store, origin):
    """The one origin every canonical link is built from."""
    origin = origin.strip().rstrip("/")
    if not origin.startswith("https://"):
        raise InvalidCell("a public origin must be https")
    ensure_meta(store)
    snapshot = store.snapshot()
    cell = _terminal(ORIGIN_ROOT, origin)
    if ORIGIN_ROOT in snapshot.cells:
        store.commit(snapshot.revision, replace=(cell,))
    else:
        store.commit(snapshot.revision, create=(cell,))
    return origin


def describe_page(store, *, path, title, description):
    """A page says what it is. Silence is not an option, and nor is drift."""
    if not path.startswith("/"):
        raise InvalidCell("a page path must be rooted")
    title = title.strip()
    description = description.strip()
    if not title or not description:
        raise InvalidCell("a page with no title or description says nothing")
    assert_in_voice(title, "page title")
    assert_in_voice(description, "page description")
    ensure_meta(store)
    snapshot = store.snapshot()
    page_root = "%s:page:%s" % (META_ROOT, path)
    title_root = page_root + ":title"
    description_root = page_root + ":description"
    if page_root in snapshot.cells:
        store.commit(snapshot.revision, replace=(
            _terminal(title_root, title),
            _terminal(description_root, description),
        ))
        return page_root
    store.commit(snapshot.revision, create=(
        _terminal(title_root, title),
        _terminal(description_root, description),
        Cell(page_root, NULL_CELL_ID, NULL_CELL_ID, b"relation"),
    ))
    snapshot = store.snapshot()
    patch = prepare_append_relation_members(snapshot, page_root, (
        (TITLE_ROLE, title_root),
        (DESCRIPTION_ROLE, description_root),
    ), budget=10_000)
    store.commit(snapshot.revision, create=patch.create, replace=patch.replace)
    snapshot = store.snapshot()
    index = prepare_append_relation_members(
        snapshot, META_ROOT, ((PAGE_ROLE, page_root),), budget=100_000)
    store.commit(snapshot.revision, create=index.create, replace=index.replace)
    return page_root


def page_meta(snapshot, path):
    """Title, description and canonical, all out of the graph."""
    page_root = "%s:page:%s" % (META_ROOT, path)
    if page_root not in snapshot.cells:
        raise InvalidCell("no page describes itself at %s" % path)
    if ORIGIN_ROOT not in snapshot.cells:
        raise InvalidCell("no origin is set, so no canonical link can be built")
    origin = _text(snapshot, ORIGIN_ROOT)
    return PageMeta(
        path,
        _text(snapshot, page_root + ":title"),
        _text(snapshot, page_root + ":description"),
        origin + path,
    )


def record_release(store, *, revision, summary, state=RELEASED):
    """A changelog entry exists for a revision, not for an intention."""
    summary = summary.strip()
    if not summary:
        raise InvalidCell("a release with no summary is progress theatre")
    if state not in (RELEASED, DRAFT):
        raise InvalidCell("a release is either released or draft")
    assert_in_voice(summary, "release summary")
    ensure_meta(store)
    snapshot = store.snapshot()
    release_root = "%s:release:%s" % (META_ROOT, revision)
    if release_root in snapshot.cells:
        raise InvalidCell("that revision is already in the changelog")
    summary_root = release_root + ":summary"
    store.commit(snapshot.revision, create=(
        _terminal(summary_root, summary),
        Cell(release_root, NULL_CELL_ID, NULL_CELL_ID, b"relation"),
    ))
    snapshot = store.snapshot()
    patch = prepare_append_relation_members(snapshot, release_root, (
        (DESCRIPTION_ROLE, summary_root),
        (RELEASE_ROLE, state),
    ), budget=10_000)
    store.commit(snapshot.revision, create=patch.create, replace=patch.replace)
    snapshot = store.snapshot()
    index = prepare_append_relation_members(
        snapshot, META_ROOT, ((RELEASE_ROLE, release_root),), budget=100_000)
    store.commit(snapshot.revision, create=index.create, replace=index.replace)
    return release_root


def changelog(snapshot):
    """Only released revisions. A draft is not a public claim."""
    if META_ROOT not in snapshot.cells:
        return ()
    notes = []
    for member in read_relation(snapshot, META_ROOT, budget=100_000):
        if member.role_id != RELEASE_ROLE:
            continue
        release_root = member.participant_id
        entry = read_relation(snapshot, release_root, budget=10_000)
        states = [m.participant_id for m in entry if m.role_id == RELEASE_ROLE]
        if states != [RELEASED]:
            continue
        notes.append(ReleaseNote(
            release_root.rsplit(":release:", 1)[-1],
            _text(snapshot, release_root + ":summary"),
        ))
    return tuple(sorted(notes, key=lambda note: note.revision))


def offer_download(store, *, artifact_root, revision):
    """A download exists only for a revision the changelog calls released."""
    snapshot = store.snapshot()
    if artifact_root not in snapshot.cells:
        raise InvalidCell("cannot offer an artifact the graph does not hold")
    released = {note.revision for note in changelog(snapshot)}
    if revision not in released:
        raise InvalidCell(
            "revision %s is not released, so it must not be offered" % revision)
    ensure_meta(store)
    snapshot = store.snapshot()
    offer_root = "%s:download:%s" % (META_ROOT, revision)
    if offer_root in snapshot.cells:
        raise InvalidCell("that revision is already offered")
    store.commit(snapshot.revision, create=(
        Cell(offer_root, NULL_CELL_ID, NULL_CELL_ID, b"relation"),))
    snapshot = store.snapshot()
    patch = prepare_append_relation_members(
        snapshot, offer_root, ((ARTIFACT_ROLE, artifact_root),), budget=10_000)
    store.commit(snapshot.revision, create=patch.create, replace=patch.replace)
    snapshot = store.snapshot()
    index = prepare_append_relation_members(
        snapshot, META_ROOT, ((ARTIFACT_ROLE, offer_root),), budget=100_000)
    store.commit(snapshot.revision, create=index.create, replace=index.replace)
    return offer_root


def downloads(snapshot):
    if META_ROOT not in snapshot.cells:
        return ()
    return tuple(sorted(
        m.participant_id.rsplit(":download:", 1)[-1]
        for m in read_relation(snapshot, META_ROOT, budget=100_000)
        if m.role_id == ARTIFACT_ROLE
    ))
