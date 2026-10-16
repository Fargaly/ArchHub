"""A current account session renews; revoked/expired/suspended sessions cannot."""
import time

import pytest


@pytest.mark.parametrize("state", ["current", "expired", "revoked", "suspended"])
def test_refresh_preserves_exact_account_and_refuses_dead_sessions(state):
    import db
    import main
    from fastapi.testclient import TestClient
    user = db.get_or_create_user("refresh@example.test")
    token = db.issue_token(user["id"], ttl_seconds=60)
    digest = db.token_digest(token)
    with db.connect() as connection:
        if state == "expired":
            connection.execute("UPDATE tokens SET expires_at = ? WHERE token = ?", (int(time.time()) - 1, digest))
        elif state == "revoked":
            connection.execute("DELETE FROM tokens WHERE token = ?", (digest,))
        elif state == "suspended":
            connection.execute("UPDATE users SET suspended_at = ? WHERE id = ?", (int(time.time()), user["id"]))
    response = TestClient(main.app).post("/v1/auth/refresh", headers={"Authorization": "Bearer " + token})
    assert response.status_code == (200 if state == "current" else 401)
    if state == "current":
        assert response.json()["expires_at"] > time.time() + 86400
        assert db.user_for_token(token)["id"] == user["id"]
        with db.connect() as connection:
            assert connection.execute("SELECT count(*) FROM tokens").fetchone()[0] == 1
