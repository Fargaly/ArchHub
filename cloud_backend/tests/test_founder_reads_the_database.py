"""The founder reads the cloud database, one SELECT at a time (Cockpit P8, 2026-09-29).

SQLite enforces the limits (cockpit_query): a read-only connection with
query_only, an authorizer that permits only reads and refuses credentials and
users' private content, one statement, a row cap and a time limit. Every query
is audited; non-founders are refused by the route walk.
"""
from __future__ import annotations

import pytest

FOUNDER = "founder.desktop@example.test"


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    import main
    return TestClient(main.app, raise_server_exceptions=False)


def _auth(email: str) -> dict:
    import db
    user = db.get_or_create_user(email)
    return {"Authorization": "Bearer " + db.issue_token(user["id"])}


def _query(client, sql, headers=None):
    return client.post("/founder/api/db/query", headers=headers or _auth(FOUNDER),
                       json={"sql": sql})


def test_a_select_answers_with_columns_and_rows(client):
    import db
    db.get_or_create_user("reader.one@studio.example")
    r = _query(client, "SELECT email, plan FROM users WHERE email = 'reader.one@studio.example'")
    assert r.status_code == 200, r.text
    assert r.json()["columns"] == ["email", "plan"]
    assert r.json()["rows"] == [["reader.one@studio.example", "trial"]]
    (row,) = [a for a in db.recent_founder_actions(20) if a["action"] == "db.query" and a["ok"]]
    assert "reader.one@studio.example" in row["result"]


@pytest.mark.parametrize("sql", [
    "DELETE FROM users",
    "UPDATE users SET plan = 'firm'",
    "INSERT INTO users (id, email, created_at) VALUES ('x', 'x@x', 0)",
    "DROP TABLE users",
    "CREATE TABLE court (x)",
    "PRAGMA writable_schema = 1",
    "ATTACH DATABASE 'court.db' AS other",
    "SELECT 1; DELETE FROM users",
])
def test_anything_but_one_read_is_refused_and_changes_nothing(client, sql):
    import db
    db.get_or_create_user("still.here@studio.example")
    founder = _auth(FOUNDER)                                # every account exists already
    before = db.find_users("", limit=200)
    r = _query(client, sql, founder)
    assert r.status_code == 400, (sql, r.text)
    assert db.find_users("", limit=200) == before
    assert db.get_user_by_email("still.here@studio.example")["plan"] == "trial"


@pytest.mark.parametrize("sql", [
    "SELECT * FROM tokens",
    "SELECT token FROM tokens",
    "SELECT * FROM codes",
    "SELECT token_digest FROM devices",
    "SELECT * FROM refund_confirmations",
    "SELECT * FROM memory_facts",
    "SELECT * FROM training_samples",
    "SELECT u.email FROM users u JOIN tokens t ON t.user_id = u.id",
])
def test_credentials_and_private_content_are_never_read(client, sql):
    r = _query(client, sql)
    assert r.status_code == 400, (sql, r.text)
    error = r.json()["error"]
    assert "prohibited" in error or "not authorized" in error, error   # SQLite's own refusal


def test_rows_are_capped_and_a_runaway_query_is_stopped(client):
    r = _query(client, "WITH RECURSIVE n(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM n "
                       "WHERE x < 1000) SELECT x FROM n")
    assert r.status_code == 200 and len(r.json()["rows"]) == 200 and r.json()["truncated"] is True
    endless = _query(client, "WITH RECURSIVE n(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM n) "
                             "SELECT count(*) FROM n")
    assert endless.status_code == 400 and "ran past" in endless.json()["error"]


def test_the_cockpit_agent_still_has_no_sql_tool():
    import cockpit_agent
    assert not any("sql" in name or "query" in name for name in cockpit_agent.TOOLS)