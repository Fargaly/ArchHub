"""The cockpit door is a sign-in, not a token hunt.

The founder asked, on 2026-09-05, "where do I get the cockpit token from?"
The page had one field and it wanted a token he had to dig out of a JSON file
the desktop app writes. This court holds the door he actually has: type the
address, click the link in the inbox, land in the cockpit -- and holds the two
things that make that door safe, that the page never reveals which address
owns the cockpit, and that the session cookie is minted by the server rather
than being anything the visitor typed.
"""
from __future__ import annotations

import pytest


FOUNDER_EMAIL = "founder@archhub-signin-test.com"
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


@pytest.fixture
def sent(monkeypatch):
    """Capture every magic link the cockpit tries to mail."""
    posted = []
    async def fake_send(*, to, link):
        posted.append({"to": to, "link": link})
        return True
    import email_sender
    monkeypatch.setattr(email_sender, "send_magic_link", fake_send)
    return posted


def test_the_page_asks_for_an_email_and_keeps_the_token_as_a_fallback(client):
    r = client.get("/founder/login")
    assert r.status_code == 200
    page = r.text
    assert 'action="/founder/login/email"' in page and 'name="email"' in page
    assert 'action="/founder/login"' in page and 'name="token"' in page
    assert "Settings -&gt; Account" not in page  # the old dead instruction is gone


def test_a_stranger_gets_the_same_answer_and_no_mail(client, sent):
    r = client.post("/founder/login/email", data={"email": STRANGER})
    assert r.status_code == 200
    assert "on its way" in r.text
    assert sent == []  # never mail an address that does not own the cockpit
    said_to_stranger = r.text
    r2 = client.post("/founder/login/email", data={"email": FOUNDER_EMAIL})
    assert r2.status_code == 200 and r2.text == said_to_stranger  # byte-identical


def test_the_founder_is_mailed_a_link_that_opens_the_cockpit(client, sent):
    r = client.post("/founder/login/email", data={"email": FOUNDER_EMAIL})
    assert r.status_code == 200 and len(sent) == 1
    assert sent[0]["to"] == FOUNDER_EMAIL
    link = sent[0]["link"]
    assert "/founder/claim?code=" in link, link
    code = link.split("code=", 1)[1]

    claim = client.get("/founder/claim", params={"code": code}, follow_redirects=False)
    assert claim.status_code == 303 and claim.headers["location"] == "/founder"
    cookie = claim.cookies.get("founder_session")
    assert cookie and cookie != code  # server-minted session, never the emailed code
    set_cookie = claim.headers.get("set-cookie", "")
    assert "HttpOnly" in set_cookie and "Secure" in set_cookie and "Path=/founder" in set_cookie

    client.cookies.set("founder_session", cookie)
    opened = client.get("/founder", follow_redirects=False)
    assert opened.status_code == 200  # the cookie really opens the cockpit


def test_a_code_is_one_use_and_a_junk_code_is_refused(client, sent):
    client.post("/founder/login/email", data={"email": FOUNDER_EMAIL})
    code = sent[0]["link"].split("code=", 1)[1]
    first = client.get("/founder/claim", params={"code": code}, follow_redirects=False)
    assert first.status_code == 303
    client.cookies.clear()
    again = client.get("/founder/claim", params={"code": code}, follow_redirects=False)
    assert again.status_code == 401  # spent
    junk = client.get("/founder/claim", params={"code": "not-a-real-code"}, follow_redirects=False)
    assert junk.status_code == 401
    assert "expired or not for this cockpit" in junk.text


def test_a_strangers_code_never_opens_the_cockpit(client, sent, monkeypatch):
    """A real, valid sign-in code for another account is still refused here."""
    import db
    user = db.get_or_create_user(STRANGER)
    code = db.issue_code(user["id"], "")
    r = client.get("/founder/claim", params={"code": code}, follow_redirects=False)
    assert r.status_code == 401 and not r.cookies.get("founder_session")
