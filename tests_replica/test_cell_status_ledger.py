"""Courts for the generic, append-only authority status ledger."""

import pytest

from nodelang.cell_status_ledger import (
    assert_subject_usable,
    bootstrap_status_ledger_protocol,
    current_status,
    open_status_ledger_protocol,
    prepare_status_event,
    read_status_event,
)
from nodelang.universal_cell import NULL_CELL_ID, Cell, CellStore, InvalidCell


def _terminal(root: str, atom: str) -> Cell:
    return Cell(root, NULL_CELL_ID, NULL_CELL_ID, atom.encode("utf-8"))


@pytest.fixture()
def world():
    store = CellStore()
    protocol = bootstrap_status_ledger_protocol(store, prefix="test:status")
    roots = {
        "subject": "authority:released",
        "actor": "identity:reviewer",
        "policy": "policy:authority",
        "action": "action:revoke",
        "rule": "rule:explicit-permit",
        "receipt": "receipt:authorization",
    }
    store.commit(
        store.revision,
        create=tuple(_terminal(root, root) for root in roots.values()),
    )
    return store, protocol, roots


def _revoke(world, *, event_id="status:event:1"):
    store, protocol, roots = world
    patch = prepare_status_event(
        store.snapshot(),
        protocol,
        event_id=event_id,
        subject_root=roots["subject"],
        subject_digest="f" * 64,
        state_root=protocol.state("revoked"),
        actor_root=roots["actor"],
        policy_root=roots["policy"],
        action_root=roots["action"],
        rule_roots=(roots["rule"],),
        reason="explicit-permit",
        authorization_receipt_root=roots["receipt"],
    )
    store.commit(
        store.revision,
        create=patch.create,
        replace=patch.replace,
    )
    return read_status_event(store.snapshot(), protocol, event_id)


def test_protocol_and_revocation_are_graph_held_and_reopenable(world):
    store, protocol, roots = world
    assert open_status_ledger_protocol(
        store.snapshot(), prefix="test:status"
    ) == protocol

    event = _revoke(world)
    assert event.subject_root == roots["subject"]
    assert event.subject_digest == "f" * 64
    assert event.state_root == protocol.state("revoked")
    assert event.rule_roots == (roots["rule"],)
    assert current_status(
        store.snapshot(), protocol, roots["subject"]
    ) == event
    with pytest.raises(InvalidCell, match="revoked"):
        assert_subject_usable(
            store.snapshot(), protocol, roots["subject"], "f" * 64
        )


def test_revocation_is_irreversible_and_cannot_be_duplicated(world):
    _revoke(world)
    store, protocol, roots = world
    with pytest.raises(InvalidCell, match="already revoked"):
        prepare_status_event(
            store.snapshot(),
            protocol,
            event_id="status:event:2",
            subject_root=roots["subject"],
            subject_digest="f" * 64,
            state_root=protocol.state("revoked"),
            actor_root=roots["actor"],
            policy_root=roots["policy"],
            action_root=roots["action"],
            rule_roots=(roots["rule"],),
            reason="explicit-permit",
            authorization_receipt_root=roots["receipt"],
        )


def test_subject_digest_and_event_digest_are_fail_closed(world):
    event = _revoke(world)
    store, protocol, roots = world
    with pytest.raises(InvalidCell, match="digest does not match"):
        assert_subject_usable(
            store.snapshot(), protocol, roots["subject"], "0" * 64
        )

    snapshot = store.snapshot()
    digest_cell = snapshot.cells[event.digest_root]
    store.commit(
        snapshot.revision,
        replace=(Cell(
            digest_cell.id,
            digest_cell.link0,
            digest_cell.link1,
            b"0" * len(digest_cell.atom),
        ),),
    )
    with pytest.raises(InvalidCell, match="status event has drifted"):
        read_status_event(store.snapshot(), protocol, event.root_id)


def test_protocol_vocabulary_tamper_is_rejected(world):
    store, protocol, _roots = world
    snapshot = store.snapshot()
    role = snapshot.cells[protocol.role("status-subject")]
    store.commit(
        snapshot.revision,
        replace=(Cell(role.id, role.link0, role.link1, b"other"),),
    )
    with pytest.raises(InvalidCell, match="vocabulary"):
        open_status_ledger_protocol(store.snapshot(), prefix="test:status")
