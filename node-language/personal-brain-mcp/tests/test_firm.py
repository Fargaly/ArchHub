"""Slice 9 — firm identity + invite flow tests.

Two-device scenario tested via two separate BrainStore instances on
distinct in-memory DBs. Admin creates firm + invite; second store accepts.
"""
from __future__ import annotations

import time

import pytest

from personal_brain.firm import (
    FirmIdentity,
    InviteToken,
    Seat,
    accept_invite_token,
    create_firm,
    create_invite_token,
    current_firm,
    current_firm_id,
    current_seat,
    decode_invite_token,
    has_ed25519,
    leave_firm,
    list_seats,
    verify_invite_token,
)
from personal_brain.storage import BrainStore


@pytest.fixture
def admin_store():
    s = BrainStore.open(":memory:")
    yield s
    s.close()


@pytest.fixture
def seat_store():
    s = BrainStore.open(":memory:")
    yield s
    s.close()


# ─────────────────────── create firm ──────────────────────────────────


def test_create_firm_returns_identity_with_priv(admin_store):
    f = create_firm(admin_store, name="ArchHub Studio", created_by="fargaly")
    assert f.firm_id.startswith("firm-")
    assert "archhub-studio" in f.firm_id
    assert f.name == "ArchHub Studio"
    assert f.root_pub
    assert f.root_priv  # admin holds the private key
    assert f.created_by == "fargaly"


def test_current_firm_persists(admin_store):
    create_firm(admin_store, name="ArchHub Studio", created_by="fargaly")
    f = current_firm(admin_store)
    assert f is not None
    assert f.name == "ArchHub Studio"


def test_current_firm_none_when_not_set():
    s = BrainStore.open(":memory:")
    try:
        assert current_firm(s) is None
        assert current_firm_id(s) is None
    finally:
        s.close()


def test_admin_seat_recorded(admin_store):
    create_firm(admin_store, name="ArchHub Studio", created_by="fargaly")
    seat = current_seat(admin_store)
    assert seat is not None
    assert seat.user_id == "fargaly"
    assert seat.role == "admin"


def test_list_seats_after_creation(admin_store):
    create_firm(admin_store, name="ArchHub Studio", created_by="fargaly")
    seats = list_seats(admin_store)
    assert len(seats) == 1
    assert seats[0].user_id == "fargaly"
    assert seats[0].role == "admin"


def test_leave_firm_clears_identity(admin_store):
    create_firm(admin_store, name="X", created_by="u")
    assert current_firm_id(admin_store)
    leave_firm(admin_store)
    assert current_firm_id(admin_store) is None
    assert current_seat(admin_store) is None


# ─────────────────────── invite tokens ─────────────────────────────────


def test_create_invite_token_returns_envelope(admin_store):
    create_firm(admin_store, name="ArchHub Studio", created_by="fargaly")
    envelope = create_invite_token(admin_store, role="seat", ttl_hours=24)
    assert "." in envelope
    payload, sig = envelope.split(".", 1)
    assert payload and sig


def test_invite_token_decodes(admin_store):
    create_firm(admin_store, name="ArchHub Studio", created_by="fargaly")
    env = create_invite_token(admin_store, role="seat")
    token, sig = decode_invite_token(env)
    assert token.firm_name == "ArchHub Studio"
    assert token.role == "seat"
    assert token.issued_by == "fargaly"
    assert not token.is_expired()


def test_invite_token_verifies(admin_store):
    create_firm(admin_store, name="ArchHub Studio", created_by="fargaly")
    env = create_invite_token(admin_store, role="seat")
    tok, ok, reason = verify_invite_token(env)
    assert ok, f"verify failed: {reason}"


def test_tampered_invite_rejected(admin_store):
    create_firm(admin_store, name="ArchHub Studio", created_by="fargaly")
    env = create_invite_token(admin_store, role="seat")
    # Flip a byte in the signature half
    payload, sig = env.split(".", 1)
    bad_sig = sig[:-2] + ("AA" if sig[-2:] != "AA" else "BB")
    tampered = payload + "." + bad_sig
    tok, ok, reason = verify_invite_token(tampered)
    assert not ok


def test_expired_invite_rejected(admin_store):
    create_firm(admin_store, name="X", created_by="u")
    # ttl=0 → expires immediately
    env = create_invite_token(admin_store, role="seat", ttl_hours=0)
    time.sleep(0.01)
    tok, ok, reason = verify_invite_token(env)
    assert not ok
    assert "expired" in reason


def test_non_admin_cannot_issue_invite(seat_store):
    # No firm set on this store → create_invite_token should raise
    with pytest.raises(RuntimeError):
        create_invite_token(seat_store, role="seat")


# ─────────────────────── accept invite (two-device) ────────────────────


def test_accept_invite_creates_seat(admin_store, seat_store):
    create_firm(admin_store, name="ArchHub Studio", created_by="fargaly")
    envelope = create_invite_token(admin_store, role="seat")

    # Seat side accepts
    seat = accept_invite_token(seat_store, envelope=envelope, user_id="teammate")
    assert seat.role == "seat"
    assert seat.user_id == "teammate"

    # Seat now has firm identity (without priv)
    f = current_firm(seat_store)
    assert f is not None
    assert f.firm_id == current_firm_id(admin_store)
    assert f.name == "ArchHub Studio"
    assert f.root_priv is None  # seat side gets pub only


def test_seat_cannot_issue_invites(admin_store, seat_store):
    create_firm(admin_store, name="X", created_by="admin")
    env = create_invite_token(admin_store)
    accept_invite_token(seat_store, envelope=env, user_id="seat-user")
    # Seat lacks root_priv → invite issuance must fail
    with pytest.raises(RuntimeError):
        create_invite_token(seat_store)


def test_accept_invalid_token_raises(seat_store):
    with pytest.raises(RuntimeError):
        accept_invite_token(seat_store, envelope="garbage", user_id="x")


def test_two_seats_visible_after_both_accept(admin_store, seat_store):
    """Admin + seat in same firm. After both accept, list_seats on
    admin_store sees admin only (seat fragment lives on seat_store
    until sync). After sync (simulated by writing seat fragment
    back into admin_store), admin sees both."""
    create_firm(admin_store, name="ArchHub Studio", created_by="fargaly")
    env = create_invite_token(admin_store)
    accept_invite_token(seat_store, envelope=env, user_id="teammate")

    # Pre-sync: admin still has 1
    assert len(list_seats(admin_store)) == 1

    # Simulate sync by copying seat fragments from seat_store → admin_store
    seat_frags = seat_store.search_fragments(
        "seat", k=50,
    )
    for f in seat_frags:
        if f.predicate == "seat":
            admin_store.write_fragment(f)

    seats = list_seats(admin_store)
    user_ids = sorted(s.user_id for s in seats)
    assert "fargaly" in user_ids
    assert "teammate" in user_ids


def test_idempotent_accept(seat_store, admin_store):
    create_firm(admin_store, name="X", created_by="u")
    env = create_invite_token(admin_store)
    accept_invite_token(seat_store, envelope=env, user_id="seat-user")
    seat1 = current_seat(seat_store)
    # Second accept overwrites with same seat
    accept_invite_token(seat_store, envelope=env, user_id="seat-user")
    seat2 = current_seat(seat_store)
    assert seat1.user_id == seat2.user_id
    assert seat1.firm_id == seat2.firm_id


def test_ed25519_or_hmac_fallback_works():
    """Whichever crypto path is active, sign+verify roundtrip must work."""
    s = BrainStore.open(":memory:")
    try:
        create_firm(s, name="X", created_by="u")
        env = create_invite_token(s)
        tok, ok, _ = verify_invite_token(env)
        assert ok
        # Document which path we're on (informational only)
        assert isinstance(has_ed25519(), bool)
    finally:
        s.close()
