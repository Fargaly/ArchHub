"""What the public page says about itself, derived and refused when unproven.

Page metadata was hand-written beside the pages, so it drifted, and the download
button pointed at whatever the last build produced whether or not it was
released. Both are the same mistake: telling the public something the graph has
not proven.

Every string here goes through the voice rules on the way in, so the site cannot
say something the product would refuse to say. A changelog entry exists only for
a RELEASED revision, and a download exists only for a RELEASED artifact. There
is no default origin -- a canonical link the graph cannot justify is refused.

An artifact is held by the address that names its own revision and by its
sha256, so a later build can never stand in for the one that was released.

The application serves the site under /website; the public export puts it at
the root. A canonical link names the public address, never the in-app one.
"""
from __future__ import annotations

import re
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

IN_APP_PREFIX = "/website"
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")


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


@dataclass(frozen=True, slots=True)
class DownloadOffer:
    revision: str
    url: str
    sha256: str
    artifact_root: str


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


def public_path(path):
    """Where a page lives on the public site: /website is /, /website/x is /x/."""
    if not path.startswith("/"):
        raise InvalidCell("a page path must be rooted")
    if path == IN_APP_PREFIX:
        return "/"
    if path.startswith(IN_APP_PREFIX + "/"):
        path = path[len(IN_APP_PREFIX):]
    return path if path.endswith("/") else path + "/"


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


def page_texts(snapshot, path):
    """Title and description of a described page; no origin is needed."""
    page_root = "%s:page:%s" % (META_ROOT, path)
    if page_root not in snapshot.cells:
        raise InvalidCell("no page describes itself at %s" % path)
    return (
        _text(snapshot, page_root + ":title"),
        _text(snapshot, page_root + ":description"),
    )


def page_meta(snapshot, path):
    """Title, description and canonical, all out of the graph.

    The canonical link is the exported root address, so it matches the
    static site byte for byte rather than the in-app /website route.
    """
    title, description = page_texts(snapshot, path)
    if ORIGIN_ROOT not in snapshot.cells:
        raise InvalidCell("no origin is set, so no canonical link can be built")
    origin = _text(snapshot, ORIGIN_ROOT)
    return PageMeta(path, title, description, origin + public_path(path))


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
    """A download exists only for a revision the changelog calls released.

    The write rule is the read rule: an offer download_offers would refuse is
    never written, so a stored offer cannot later refuse the website.
    """
    snapshot = store.snapshot()
    if artifact_root not in snapshot.cells:
        raise InvalidCell("cannot offer an artifact the graph does not hold")
    released = {note.revision for note in changelog(snapshot)}
    if revision not in released:
        raise InvalidCell(
            "revision %s is not released, so it must not be offered" % revision)
    _proven_artifact(snapshot, artifact_root, revision)
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


def _pinned_address(url, revision):
    """An https address that names its revision; a moving address is refused."""
    if (
        not url.startswith("https://")
        or any(character.isspace() for character in url)
        or "/%s/" % revision not in url
        or "/latest/" in url
    ):
        raise InvalidCell(
            "an artifact address must be https and name revision %s" % revision)
    return url


def hold_artifact(store, *, revision, url, sha256):
    """The graph holds a built artifact by its pinned address and its sha256."""
    revision = str(revision).strip()
    if not revision:
        raise InvalidCell("an artifact names the revision it was built from")
    url = _pinned_address(str(url).strip(), revision)
    sha256 = str(sha256).strip().lower()
    if not SHA256_PATTERN.fullmatch(sha256):
        raise InvalidCell("an artifact is held with its sha256")
    ensure_meta(store)
    snapshot = store.snapshot()
    artifact_root = "%s:artifact:%s" % (META_ROOT, revision)
    if artifact_root in snapshot.cells:
        raise InvalidCell("that artifact is already held")
    store.commit(snapshot.revision, create=(
        _terminal(artifact_root + ":sha256", sha256),
        _terminal(artifact_root, url),
    ))
    return artifact_root


def _proven_artifact(snapshot, artifact_root, revision):
    """The one rule an offered artifact meets, on write and on read.

    It is the artifact held for its revision, its address names that revision,
    and its sha256 is held beside it.
    """
    if artifact_root != "%s:artifact:%s" % (META_ROOT, revision):
        raise InvalidCell(
            "an offer names the artifact held for revision %s" % revision)
    url = _pinned_address(_text(snapshot, artifact_root), revision)
    sha_root = artifact_root + ":sha256"
    sha256 = _text(snapshot, sha_root) if sha_root in snapshot.cells else ""
    if not SHA256_PATTERN.fullmatch(sha256):
        raise InvalidCell("an offered artifact has no sha256")
    return url, sha256


def download_offers(snapshot):
    """Every offered download, oldest offer first, read back through the rule.

    Each one is a released revision, an artifact the graph holds, an address
    that names that revision, and a sha256; anything less is refused.
    """
    if META_ROOT not in snapshot.cells:
        return ()
    released = {note.revision for note in changelog(snapshot)}
    offers = []
    for member in read_relation(snapshot, META_ROOT, budget=100_000):
        if member.role_id != ARTIFACT_ROLE:
            continue
        revision = member.participant_id.rsplit(":download:", 1)[-1]
        if revision not in released:
            raise InvalidCell(
                "revision %s is offered but not released" % revision)
        artifacts = [
            m.participant_id
            for m in read_relation(snapshot, member.participant_id, budget=16)
            if m.role_id == ARTIFACT_ROLE
        ]
        if len(artifacts) != 1:
            raise InvalidCell("a download offers exactly one artifact")
        url, sha256 = _proven_artifact(snapshot, artifacts[0], revision)
        offers.append(DownloadOffer(revision, url, sha256, artifacts[0]))
    return tuple(offers)
