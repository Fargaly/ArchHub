"""Independent adverse decisions: no transport, keys, live OAuth or provider IO."""
import pytest

from nodelang import social_approval, social_connections
from nodelang.cell_authorization import AuthorizationDenied
from nodelang.universal_cell import InvalidCell
from tests_replica.test_social3_send import CASES, _prepare
from tests_replica.test_social_approval_graph import social_world, world, _decide, _authorize  # noqa: F401


@pytest.mark.parametrize("case", CASES, ids=[case[0] for case in CASES])
def test_altered_approval_digest_and_explicit_denial_never_admit_dispatch(case):
    request, _inputs = _prepare(case)
    w = world()
    item = next(row for row in social_approval.pending(w.server, w.binding)
                if row["delegation"] == request["delegation"])
    digest = item["input_digest"]
    changed = ("0" if digest[0] != "0" else "1") + digest[1:]
    with pytest.raises((AuthorizationDenied, InvalidCell)):
        _decide(w.server, w.binding, {"delegation": item["delegation"],
            "input_digest": changed, "decision": "approve"})
    with pytest.raises((AuthorizationDenied, InvalidCell)):
        _authorize(request)
    denied = _decide(w.server, w.binding, {"delegation": item["delegation"],
        "input_digest": digest, "decision": "deny"})
    assert denied["decision"] == "denied"
    with pytest.raises((AuthorizationDenied, InvalidCell)):
        _authorize(request)


def test_real_connection_projection_retains_verified_identity_and_explicit_review_blocker(monkeypatch):
    named = "Meta app review: instagram_content_publish approval not verified"
    monkeypatch.setattr(social_connections.broker, "status", lambda provider: {
        "state": "saved", "publish_blocker": named, "review_state": "unverified"})
    row = social_connections.connection("instagram", accounts=[{
        "provider": "meta", "vault_entry": "social-meta-ig-123", "account_id": "123",
        "account_binding": "provider-verified", "display_name": "founder"}], attempt={"phase": "taken"})
    assert row["state"] == "connected" and row["display_name"] == "founder"
    assert row["can_connect"] is True
    assert row["review_state"] == "unverified"
    assert row["publish_blocker"] == row["blocker"] == named
