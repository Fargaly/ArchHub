"""Identity is an email account with proof; tiers are the founder's dial; one founder."""
import inspect
import json

import pytest

from nodelang.cell_accounts import ensure_accounts, set_tier, upsert_account
from nodelang.cloud_session import signed_in_cloud_account
from nodelang.map_import import resolve_map_path
from nodelang.universal_application import build_universal_application
from nodelang.universal_cell import InvalidCell


def test_the_founder_tier_is_not_assignable():
    store, _registry = build_universal_application(resolve_map_path())
    ensure_accounts(store, founder_email="ahmed.fargaly98@gmail.com")
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
