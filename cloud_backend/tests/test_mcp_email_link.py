"""The owner can approve an MCP client (Spark, Notion) by an emailed link instead of Google.

The inbox proves the address, exactly as Google's verified id_token does; everything after
that is the Google path's own continue step. The link goes only to the owner addresses,
works once, for fifteen minutes, and only in the browser that approved.

Run: python -m pytest cloud_backend/tests/test_mcp_email_link.py -q
"""
from __future__ import annotations

import os
import re
import sys
import urllib.parse

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_mcp_oauth import REDIRECT, _browser, _consent_form, _pkce, _register, _token

OWNERS = {"founder.desktop@example.test", "founder@example.test"}


@pytest.fixture
def mail(monkeypatch):
    import email_sender
    sent = []

    async def capture(*, to, subject, text, html):
        sent.append({"to": to, "subject": subject, "text": text})
        return True

    monkeypatch.setattr(email_sender, "_send", capture)
    return sent


def _links(sent):
    return {item["to"]: re.search(r"https://api\.archhub\.io(/oauth/email-link\?t=[^\s]+)", item["text"]).group(1)
            for item in sent}


def _ask_for_link(browser, mail):
    client_id = _register(browser)
    verifier, challenge = _pkce()
    pending, csrf, page = _consent_form(browser, client_id, challenge)
    assert "email the owner a sign-in link" in page.text
    r = browser.post("/oauth/consent", data={"pending": pending, "csrf": csrf, "decision": "email"})
    assert r.status_code == 200 and "Check your email" in r.text, r.text
    return client_id, verifier, pending, _links(mail)


def test_the_owner_approves_by_the_emailed_link_and_the_client_gets_its_token(mail):
    browser = _browser()
    client_id, verifier, pending, links = _ask_for_link(browser, mail)
    assert set(links) == OWNERS, "one link per owner address and to no one else"
    back = browser.get(links["founder.desktop@example.test"])
    assert back.status_code == 302 and back.headers["location"].startswith("https://api.archhub.io/oauth/continue")
    done = browser.get(back.headers["location"].replace("https://api.archhub.io", ""))
    query = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(done.headers["location"]).query))
    assert done.headers["location"].startswith(REDIRECT) and query["state"] == "st-1"
    r = _token(browser, grant_type="authorization_code", code=query["code"], redirect_uri=REDIRECT,
               client_id=client_id, code_verifier=verifier, resource="https://api.archhub.io/mcp")
    assert r.status_code == 200 and r.json()["access_token"], r.text


def test_a_link_works_once_and_opening_one_spends_the_other(mail):
    browser = _browser()
    _, _, _, links = _ask_for_link(browser, mail)
    assert browser.get(links["founder.desktop@example.test"]).status_code == 302
    assert browser.get(links["founder.desktop@example.test"]).status_code == 400
    assert browser.get(links["founder@example.test"]).status_code == 400


def test_a_link_opened_in_another_browser_records_nothing(mail):
    import db
    founder, stranger = _browser(), _browser()
    _, _, pending, links = _ask_for_link(founder, mail)
    assert stranger.get(links["founder@example.test"]).status_code == 400
    with db.connect() as con:
        assert con.execute("SELECT verified_email FROM oauth_pending WHERE id = ?", (pending,)).fetchone()[0] is None


def test_an_expired_link_is_refused(mail, monkeypatch):
    import oauth_mcp
    browser = _browser()
    _, _, _, links = _ask_for_link(browser, mail)
    real = oauth_mcp.time.time
    monkeypatch.setattr(oauth_mcp.time, "time", lambda: real() + oauth_mcp.EMAIL_LINK_TTL + 5)
    assert browser.get(links["founder@example.test"]).status_code == 400


def test_a_send_failure_says_so_and_nothing_is_continued(mail, monkeypatch):
    import email_sender

    async def down(**kw):
        return False

    monkeypatch.setattr(email_sender, "_send", down)
    browser = _browser()
    client_id = _register(browser)
    _, challenge = _pkce()
    pending, csrf, _ = _consent_form(browser, client_id, challenge)
    r = browser.post("/oauth/consent", data={"pending": pending, "csrf": csrf, "decision": "email"})
    assert r.status_code == 503 and "could not be sent" in r.text


def test_a_link_never_outlives_its_request_and_says_its_real_minutes(mail, monkeypatch):
    """The request (oauth_pending, PENDING_TTL) ends before a 15-minute link would: the link ends with it."""
    import oauth_mcp
    browser = _browser()
    _, _, _, links = _ask_for_link(browser, mail)
    minutes = oauth_mcp.PENDING_TTL // 60
    stated = {re.search(r"within (\d+) minutes", item["text"]).group(1) for item in mail}
    assert stated <= {str(minutes - 1), str(minutes)}, ("the email states the request's real minutes", stated)
    real = oauth_mcp.time.time
    monkeypatch.setattr(oauth_mcp.time, "time", lambda: real() + oauth_mcp.PENDING_TTL + 5)
    assert browser.get(links["founder@example.test"]).status_code == 400, "the request ended, so the link did"
