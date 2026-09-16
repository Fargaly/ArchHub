"""The offer is one record: declared once from a founder account, read by every surface."""
import pytest

from nodelang.cell_accounts import (
    BETA_OFFER, declare_offer, ensure_accounts, published_offer, read_offer,
    set_offer_field,
)
from nodelang.universal_cell import CellStore, InvalidCell

FOUNDER = "ahmed.fargaly98@gmail.com"


def _store():
    store = CellStore()
    ensure_accounts(store, founder_email=FOUNDER)
    return store


def test_signing_in_never_declares_the_offer():
    store = _store()
    ensure_accounts(store, founder_email=FOUNDER)
    assert read_offer(store.snapshot()) is None
    assert published_offer(store.snapshot()) is None


def test_the_founder_declares_the_beta_offer_once():
    store = _store()
    assert declare_offer(store, founder_account=FOUNDER) == BETA_OFFER
    revision = store.snapshot().revision
    again = declare_offer(store, founder_account=FOUNDER, offer={
        "availability": "paid", "pricing-visible": "true", "public-label": "Paid"})
    assert again == BETA_OFFER, "a second declaration must not rewrite the offer"
    assert store.snapshot().revision == revision


def test_a_non_founder_cannot_declare_or_change_the_offer():
    store = _store()
    with pytest.raises(InvalidCell, match="only a founder"):
        declare_offer(store, founder_account="colleague@example.com")
    declare_offer(store, founder_account=FOUNDER)
    with pytest.raises(InvalidCell, match="only a founder"):
        set_offer_field(store, "public-label", "Cheap", founder_account="colleague@example.com")
    assert read_offer(store.snapshot()) == BETA_OFFER


def test_offer_fields_are_validated():
    store = _store()
    declare_offer(store, founder_account=FOUNDER)
    for field, value in (("pricing-visible", "maybe"), ("public-label", ""),
                         ("public-label", "x" * 81), ("availability", "Free During Beta"),
                         ("price", "0")):
        with pytest.raises(InvalidCell):
            set_offer_field(store, field, value, founder_account=FOUNDER)
    assert read_offer(store.snapshot()) == BETA_OFFER


def test_the_published_offer_is_one_stable_form():
    store = _store()
    declare_offer(store, founder_account=FOUNDER)
    one = published_offer(store.snapshot())
    assert set(one) == {"revision", "sha256", "availability", "pricing_visible", "public_label"}
    assert one["availability"] == "free-during-beta"
    assert one["pricing_visible"] is False
    assert one["public_label"] == "Free during beta"
    set_offer_field(store, "public-label", "Free while in beta", founder_account=FOUNDER)
    two = published_offer(store.snapshot())
    assert two["public_label"] == "Free while in beta" and two["sha256"] != one["sha256"]
    set_offer_field(store, "public-label", "Free during beta", founder_account=FOUNDER)
    assert published_offer(store.snapshot())["sha256"] == one["sha256"]


def test_the_second_founder_account_may_change_the_offer():
    store = _store()
    declare_offer(store, founder_account=FOUNDER)
    set_offer_field(store, "pricing-visible", "true", founder_account=" AhmedFargale@gmail.com ")
    assert read_offer(store.snapshot())["pricing-visible"] == "true"