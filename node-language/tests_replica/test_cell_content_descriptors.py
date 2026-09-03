from __future__ import annotations

import pytest

from nodelang.cell_content_descriptors import (
    bootstrap_content_descriptor_protocol,
    compose_content_descriptor,
    content_identity_bytes,
    read_content_descriptor,
    verify_content_descriptor,
)
from nodelang.cell_protocols import compose_relation_cells
from nodelang.universal_cell import NULL_CELL_ID, Cell, CellStore, InvalidCell


def _cell(root: str, atom: bytes) -> Cell:
    return Cell(root, NULL_CELL_ID, NULL_CELL_ID, atom)


def test_descriptor_is_a_closed_graph_that_pins_but_does_not_reach_subject():
    store = CellStore()
    protocol = bootstrap_content_descriptor_protocol(
        store, prefix="test:descriptor"
    )
    subject = "test:live-subject"
    store.commit(store.revision, create=(_cell(subject, b"live"),))
    content = content_identity_bytes(
        "application/vnd.archhub.test.v1", subject, b"release-digest"
    )
    built = compose_content_descriptor(
        store.snapshot(),
        protocol,
        descriptor_id="test:release:descriptor",
        subject_root=subject,
        media_type="application/vnd.archhub.test.v1",
        content=content,
    )
    store.commit(store.revision, create=built.cells)

    descriptor = verify_content_descriptor(
        store.snapshot(),
        protocol,
        built.root_id,
        content=content,
        expected_subject_root=subject,
        expected_media_type="application/vnd.archhub.test.v1",
    )
    reached = set()
    pending = [built.root_id]
    snapshot = store.snapshot()
    while pending:
        root = pending.pop()
        if root in reached or root == NULL_CELL_ID:
            continue
        reached.add(root)
        cell = snapshot.cells[root]
        pending.extend((cell.link0, cell.link1))

    assert descriptor.subject_root == subject
    assert subject not in reached
    assert all(
        snapshot.cells[root].atom != subject.encode("ascii")
        or snapshot.cells[root].link0 == NULL_CELL_ID
        for root in reached
    )


@pytest.mark.parametrize("field", ("subject-id", "media-type", "digest", "size"))
def test_descriptor_field_tampering_fails_closed(field: str):
    store = CellStore()
    protocol = bootstrap_content_descriptor_protocol(
        store, prefix="test:descriptor"
    )
    subject = "test:subject"
    store.commit(store.revision, create=(_cell(subject, b"subject"),))
    content = content_identity_bytes("test/v1", subject, "v1")
    built = compose_content_descriptor(
        store.snapshot(),
        protocol,
        descriptor_id="test:descriptor:release",
        subject_root=subject,
        media_type="test/v1",
        content=content,
    )
    store.commit(store.revision, create=built.cells)
    root = built.root_id + ":" + field
    original = store.read(root)
    replacement = {
        "subject-id": b"test:other-subject",
        "media-type": b"test/v2",
        "digest": b"sha256:" + b"0" * 64,
        "size": b"999",
    }[field]
    store.commit(
        store.revision,
        replace=(Cell(root, original.link0, original.link1, replacement),),
    )

    with pytest.raises(InvalidCell):
        verify_content_descriptor(
            store.snapshot(),
            protocol,
            built.root_id,
            content=content,
            expected_subject_root=subject,
            expected_media_type="test/v1",
        )


def test_partial_duplicate_and_nonterminal_descriptor_fields_are_rejected():
    store = CellStore()
    protocol = bootstrap_content_descriptor_protocol(
        store, prefix="test:descriptor"
    )
    subject = "test:subject"
    value = "test:partial:subject-id"
    store.commit(
        store.revision,
        create=(_cell(subject, b"subject"), _cell(value, subject.encode("ascii"))),
    )
    partial = compose_relation_cells(
        ((protocol.role("subject-id"), value),),
        relation_id="test:partial",
    )
    store.commit(store.revision, create=partial.cells)
    with pytest.raises(InvalidCell, match="exactly one"):
        read_content_descriptor(store.snapshot(), protocol, partial.build.root_id)

    content = content_identity_bytes("test/v1", subject, "v1")
    built = compose_content_descriptor(
        store.snapshot(),
        protocol,
        descriptor_id="test:complete",
        subject_root=subject,
        media_type="test/v1",
        content=content,
    )
    store.commit(store.revision, create=built.cells)
    subject_cell = store.read(built.root_id + ":subject-id")
    store.commit(
        store.revision,
        replace=(Cell(
            subject_cell.id,
            subject,
            subject_cell.link1,
            subject_cell.atom,
        ),),
    )
    with pytest.raises(InvalidCell, match="terminal"):
        read_content_descriptor(store.snapshot(), protocol, built.root_id)

    duplicate_value = "test:duplicate:subject-id"
    store.commit(
        store.revision,
        create=(_cell(duplicate_value, subject.encode("ascii")),),
    )
    duplicate = compose_relation_cells(
        (
            (protocol.role("subject-id"), value),
            (protocol.role("subject-id"), duplicate_value),
        ),
        relation_id="test:duplicate",
    )
    store.commit(store.revision, create=duplicate.cells)
    with pytest.raises(InvalidCell, match="exactly one"):
        read_content_descriptor(store.snapshot(), protocol, duplicate.build.root_id)
