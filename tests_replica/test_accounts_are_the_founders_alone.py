"""Identity is an email account with proof; tiers are the founder's dial; one founder."""
import inspect
import json

import pytest

from nodelang.cell_accounts import (
    ACCOUNTS_ROOT, FOUNDER_EMAIL_ROOT, FOUNDERS_ROOT, ensure_accounts, founder_email,
    founder_emails, is_founder, read_accounts, set_tier, upsert_account,
)
from nodelang.cloud_session import signed_in_cloud_account
from nodelang.map_import import resolve_map_path
from nodelang.universal_application import build_universal_application
from nodelang.universal_cell import NULL_CELL_ID, Cell, CellStore, InvalidCell

FOUNDER = "founder@example.test"
FOUNDER_TWO = "founder-two@example.test"


def test_the_founder_tier_is_not_assignable():
    store, _registry = build_universal_application(resolve_map_path())
    ensure_accounts(store, founder_email=FOUNDER)
    upsert_account(store, "colleague@example.com")
    with pytest.raises(InvalidCell, match="founder tier is not assignable"):
        set_tier(store, "colleague@example.com", "founder")
    assert set_tier(store, "colleague@example.com", "pro") == "pro"


def test_signed_in_account_comes_only_from_a_real_cloud_session(tmp_path):
    record = tmp_path / "cloud.json"
    assert signed_in_cloud_account(record) is None
    record.write_text(json.dumps({"email": "Someone@Example.com"}), encoding="utf-8")
    assert signed_in_cloud_account(record) is None, "no token, no session"
    record.write_text(json.dumps({"email": "Someone@Example.com", "token": "t"}), encoding="utf-8")
    assert signed_in_cloud_account(record) == "someone@example.com"


def test_the_routes_demand_proof_and_the_founder_machine():
    import nodelang.application_server as srv
    src = inspect.getsource(srv)
    login = src.index("elif self.path == '/api/universal/login':")
    assert src.index("wanted != signed_in_cloud_account()", login) < src.index("upsert_account(", login)
    accounts = src.index("elif self.path == '/api/universal/accounts':")
    assert src.index("owner._require_founder_machine()", accounts) < src.index("read_accounts(", accounts)
    tier = src.index("elif self.path == '/api/universal/account-tier':")
    assert src.index("owner._require_founder_machine()", tier) < src.index("tier = set_tier(", tier)


def _graph_before_the_founders_relation():
    store = CellStore()
    text = lambda root, value: Cell(root, NULL_CELL_ID, NULL_CELL_ID, value.encode("utf-8"))
    store.commit(store.snapshot().revision, create=(
        text(ACCOUNTS_ROOT + ":role:account", "account"),
        text(ACCOUNTS_ROOT + ":role:email", "email"),
        text(ACCOUNTS_ROOT + ":role:tier", "tier"),
        Cell(ACCOUNTS_ROOT, NULL_CELL_ID, NULL_CELL_ID, b"accounts"),
        text(FOUNDER_EMAIL_ROOT, FOUNDER),
    ))
    return store


def test_both_founder_accounts_are_founders():
    store = CellStore()
    ensure_accounts(store, founder_email=FOUNDER)
    ensure_accounts(store, founder_email=FOUNDER_TWO)  # the cloud proves the second founder on its own sign-in
    snapshot = store.snapshot()
    assert set(founder_emails(snapshot)) == {FOUNDER, FOUNDER_TWO}
    assert founder_email(snapshot) == FOUNDER
    assert is_founder(snapshot, " Founder-Two@Example.Test ")
    assert not is_founder(snapshot, "colleague@example.com")
    assert not is_founder(snapshot, "not-an-email")
    assert upsert_account(store, FOUNDER_TWO)[2] == "founder"
    for founder in (FOUNDER, FOUNDER_TWO):
        with pytest.raises(InvalidCell, match="cannot be re-tiered"):
            set_tier(store, founder, "pro")


def test_the_founders_migration_only_appends():
    store = _graph_before_the_founders_relation()
    assert FOUNDERS_ROOT not in store.snapshot().cells
    assert upsert_account(store, FOUNDER_TWO)[2] == "free", "one founder before the migration"
    ensure_accounts(store, founder_email=FOUNDER)
    ensure_accounts(store, founder_email=FOUNDER_TWO)  # the cloud proves the second founder on its own sign-in
    snapshot = store.snapshot()
    assert set(founder_emails(snapshot)) == {FOUNDER, FOUNDER_TWO}
    assert founder_email(snapshot) == FOUNDER, "the recorded founder is never replaced"
    tiers = {row["email"]: row["tier"] for row in read_accounts(snapshot)}
    assert tiers[FOUNDER_TWO] == "founder"
    revision = snapshot.revision
    ensure_accounts(store, founder_email=FOUNDER)
    ensure_accounts(store, founder_email=FOUNDER_TWO)
    assert store.snapshot().revision == revision, "a repeated sign-in must not rewrite the founders"