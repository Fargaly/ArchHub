"""The cockpit's offer command: one founder-only revision of the one offer record."""
import pytest

from nodelang.cell_accounts import (
    BETA_OFFER, OFFER_ROOT, apply_offer_command, declare_offer, ensure_accounts,
    parse_offer_command, read_offer,
)
from nodelang.universal_cell import CellStore, InvalidCell

FOUNDER = "founder@example.test"
FOUNDER_TWO = "founder-two@example.test"
COMMAND = 'set offer public-label to "Free while in beta"'


def _store(declared=True):
    store = CellStore()
    ensure_accounts(store, founder_email=FOUNDER)
    if declared:
        declare_offer(store, founder_account=FOUNDER)
    return store


def test_only_offer_commands_are_recognised():
    assert parse_offer_command("what is blocked?") is None
    assert parse_offer_command("run engine x") is None
    assert parse_offer_command(COMMAND) == ("public-label", "Free while in beta")
    assert parse_offer_command('SET OFFER pricing-visible TO "false"') == ("pricing-visible", "false")
    with pytest.raises(InvalidCell, match="set offer"):
        parse_offer_command("set offer public-label Free")


def test_a_non_owner_is_refused_and_nothing_changes():
    store = _store()
    revision = store.snapshot().revision
    for account in ("colleague@example.com", None, ""):
        with pytest.raises(InvalidCell, match="only a founder"):
            apply_offer_command(store, COMMAND, founder_account=account, execute=True)
    assert read_offer(store.snapshot()) == BETA_OFFER
    assert store.snapshot().revision == revision


@pytest.mark.parametrize("label", [
    "$19/mo", "19 USD per month", "AED 49", "\u20ac9 a month", "Pro 39 per seat", "from 29/month",
])
def test_a_monetary_label_is_refused(label):
    store = _store()
    with pytest.raises(InvalidCell, match="price"):
        apply_offer_command(store, 'set offer public-label to "%s"' % label,
                            founder_account=FOUNDER, execute=True)
    assert read_offer(store.snapshot()) == BETA_OFFER


@pytest.mark.parametrize("label", ["", "x" * 81, "line\nbreak"])
def test_an_invalid_label_is_refused(label):
    store = _store()
    with pytest.raises(InvalidCell):
        apply_offer_command(store, 'set offer public-label to "%s"' % label,
                            founder_account=FOUNDER, execute=True)
    assert read_offer(store.snapshot()) == BETA_OFFER


def test_the_owner_changes_the_offer_as_a_new_revision():
    store = _store()
    ensure_accounts(store, founder_email=FOUNDER_TWO)  # the cloud proves the second founder on its own sign-in
    before = store.revisions_touching(OFFER_ROOT)
    result = apply_offer_command(store, COMMAND, founder_account=" Founder-Two@Example.Test ", execute=True)
    assert result["kind"] == "offer-updated"
    assert read_offer(store.snapshot())["public-label"] == "Free while in beta"
    after = store.revisions_touching(OFFER_ROOT)
    assert len(after) == len(before) + 1 and after[:len(before)] == before, "a change appends a revision"


def test_an_unconfirmed_command_changes_nothing():
    store = _store()
    revision = store.snapshot().revision
    preview = apply_offer_command(store, COMMAND, founder_account=FOUNDER, execute=False)
    assert preview["kind"] == "offer-preview" and "Confirm" in preview["summary"]
    assert store.snapshot().revision == revision


def test_the_founder_can_set_an_offer_that_was_never_declared():
    store = _store(declared=False)
    assert read_offer(store.snapshot()) is None
    apply_offer_command(store, COMMAND, founder_account=FOUNDER, execute=True)
    offer = read_offer(store.snapshot())
    assert offer["public-label"] == "Free while in beta"
    assert offer["availability"] == BETA_OFFER["availability"]
    assert offer["pricing-visible"] == "false"