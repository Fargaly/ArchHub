"""Welcome email — roadmap #P2 onboarding first-touch.

Covers:
  - send_welcome_email builds a complete, email-safe message
  - a NEW account's register triggers the welcome
  - an EXISTING account's register does NOT re-send it
"""
from __future__ import annotations

import asyncio

import pytest


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    import main
    return TestClient(main.app)


def _challenge() -> str:
    import base64
    import hashlib
    import secrets
    v = secrets.token_urlsafe(48)
    return base64.urlsafe_b64encode(
        hashlib.sha256(v.encode()).digest()).rstrip(b"=").decode()


class TestWelcomeEmailTemplate:
    def test_template_has_subject_and_bodies(self, monkeypatch):
        import email_sender
        captured: dict = {}

        async def fake_send(**kw):
            captured.update(kw)
            return True

        monkeypatch.setattr(email_sender, "_send", fake_send)
        ok = asyncio.run(
            email_sender.send_welcome_email(to="new@studio.com"))
        assert ok is True
        assert captured["subject"] == "Welcome to ArchHub"
        assert captured["to"] == "new@studio.com"
        # Both bodies present + carry the onboarding content.
        assert "Getting started" in captured["html"]
        assert "Getting started" in captured["text"]
        assert "ArchHub" in captured["html"]
        # Email-safe HTML — inline styles only, never script.
        assert "<script" not in captured["html"].lower()


class TestWelcomeOnRegister:
    def _capture_sends(self, monkeypatch) -> list:
        """Patch the shared low-level sender; record every subject so a
        test can assert which emails went out (magic-link + welcome)."""
        import email_sender
        sent: list = []

        async def fake_send(**kw):
            sent.append(kw.get("subject", ""))
            return True

        monkeypatch.setattr(email_sender, "_send", fake_send)
        return sent

    def test_new_user_register_sends_welcome(self, client, monkeypatch):
        sent = self._capture_sends(monkeypatch)
        r = client.post("/v1/auth/register", json={
            "email": "fresh@studio.com", "code_challenge": _challenge()})
        assert r.status_code == 202
        assert "Welcome to ArchHub" in sent
        assert "Your ArchHub sign-in link" in sent

    def test_existing_user_register_no_welcome(self, client, monkeypatch):
        sent = self._capture_sends(monkeypatch)
        # First register creates the account → welcome fires.
        client.post("/v1/auth/register", json={
            "email": "repeat@studio.com", "code_challenge": _challenge()})
        assert "Welcome to ArchHub" in sent
        # Second register — same email, now an existing user.
        sent.clear()
        client.post("/v1/auth/register", json={
            "email": "repeat@studio.com", "code_challenge": _challenge()})
        assert "Welcome to ArchHub" not in sent
        assert "Your ArchHub sign-in link" in sent
