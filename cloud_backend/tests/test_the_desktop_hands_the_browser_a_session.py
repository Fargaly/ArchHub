"""The desktop hands the browser a cockpit session instead of a token form.

The founder asked on 2026-09-07 where his on-cloud cockpit was. It was
running: /founder answered 403, and a browser navigating there was sent to a
sign-in page asking for a token he has no way to hold. The desktop already
holds his founder session, so it mints one short-lived, single-use claim link
here and opens that.

This court holds the hand-off and its limits: only the founder can mint one,
the link is spent exactly once, and it is a code -- not a session -- that
travels in the opened URL.
"""
from __future__ import annotations

import pytest


FOUNDER_EMAIL = "founder@archhub-handoff-test.com"
STRANGER = "someone.else@studio.example"


@pytest.fixture(autouse=True)
def _set_founder(monkeypatch):
    monkeypatch.setenv("FOUNDER_EMAIL", FOUNDER_EMAIL)
    yield


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    import main
    return TestClient(main.app, base_url="https://testserver",
                      raise_server_exceptions=False)


def _token_for(address: str) -> str:
    import db
    user = db.get_or_create_user(address)
    return db.issue_token(user["id"])


def test_the_founder_mints_a_claim_link_with_his_desktop_session(client):
    token = _token_for(FOUNDER_EMAIL)
    answer = client.post(
        "/founder/api/browser-code",
        headers={"Authorization": "Bearer " + token},
    )
    assert answer.status_code == 200, answer.text
    claim = answer.json()["claim_url"]
    assert "/founder/claim?code=" in claim
    assert claim.startswith("https://")
    assert token not in claim, "the session itself must never travel in the URL"


def test_the_claim_link_lands_in_the_cockpit_signed_in(client):
    token = _token_for(FOUNDER_EMAIL)
    claim = client.post(
        "/founder/api/browser-code",
        headers={"Authorization": "Bearer " + token},
    ).json()["claim_url"]
    path = claim.split("testserver", 1)[-1] if "testserver" in claim else (
        "/founder/claim?code=" + claim.split("code=", 1)[1]
    )
    landed = client.get(path, follow_redirects=False)
    assert landed.status_code == 303
    assert landed.headers["location"] == "/founder"
    assert "founder_session" in landed.headers.get("set-cookie", "")


def test_one_claim_link_is_spent_exactly_once(client):
    token = _token_for(FOUNDER_EMAIL)
    claim = client.post(
        "/founder/api/browser-code",
        headers={"Authorization": "Bearer " + token},
    ).json()["claim_url"]
    path = "/founder/claim?code=" + claim.split("code=", 1)[1]
    assert client.get(path, follow_redirects=False).status_code == 303
    again = client.get(path, follow_redirects=False)
    assert again.status_code == 401, "a spent code must not open the cockpit"


def test_a_stranger_cannot_mint_a_cockpit_session(client):
    token = _token_for(STRANGER)
    refused = client.post(
        "/founder/api/browser-code",
        headers={"Authorization": "Bearer " + token},
    )
    assert refused.status_code == 403
    assert refused.json()["detail"] == "founder_only"


def test_an_unauthenticated_caller_cannot_mint_a_cockpit_session(client):
    refused = client.post("/founder/api/browser-code")
    assert refused.status_code == 403
