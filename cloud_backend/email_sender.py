"""Thin wrapper around Resend for transactional email.

Falls back to stdout-logging when RESEND_API_KEY is unset (local dev
+ smoke tests). Production deploys MUST set the key; otherwise the
"check your inbox" magic-link UX fails silently.

Templates:
  send_magic_link    — the sign-in link (5-min TTL)
  send_welcome_email — onboarding first-touch, sent once when a new
                       account is created (roadmap #P2)
"""
from __future__ import annotations

import httpx

import config


RESEND_URL = "https://api.resend.com/emails"


async def _send(*, to: str, subject: str, text: str, html: str) -> bool:
    """POST one email to Resend. Returns True on accepted (2xx). In dev
    (no RESEND_API_KEY) logs to stdout and returns True so the local
    UX still flows."""
    if not config.RESEND_API_KEY:
        print(f"[email] would send to {to}: {subject}", flush=True)
        return True
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(
                RESEND_URL,
                headers={
                    "Authorization": f"Bearer {config.RESEND_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "from": config.FROM_EMAIL,
                    "to": [to],
                    "subject": subject,
                    "text": text,
                    "html": html,
                },
            )
        return 200 <= r.status_code < 300
    except Exception as ex:
        print(f"[email] send failed to {to}: {type(ex).__name__}: {ex}",
              flush=True)
        return False


def _wrap(body_html: str) -> str:
    """Wrap inner HTML in a brand-coherent, email-client-safe shell —
    light background, terra accent, inline styles only."""
    return (
        "<div style=\"font-family:-apple-system,Segoe UI,Roboto,sans-serif;"
        "max-width:480px;margin:0 auto;padding:32px 28px;color:#1d1d22;"
        "background:#ffffff;\">"
        "<div style=\"font-family:Georgia,serif;font-style:italic;"
        "font-size:26px;color:#d97757;margin-bottom:18px;\">ArchHub</div>"
        + body_html +
        "<hr style=\"border:none;border-top:1px solid #e8e6dc;"
        "margin:26px 0 14px;\">"
        "<div style=\"color:#9b938a;font-size:12px;line-height:1.5;\">"
        "ArchHub — talk to your AEC stack. "
        "<a href=\"https://archhub.io/security\" "
        "style=\"color:#9b938a;\">Trust Center</a></div>"
        "</div>"
    )


async def send_magic_link(*, to: str, link: str) -> bool:
    """Send the sign-in link. Returns True on accepted."""
    subject = "Your ArchHub sign-in link"
    text = (
        f"Click this link to sign in to ArchHub Cloud:\n\n"
        f"{link}\n\n"
        f"Link expires in 5 minutes. If you didn't request this, "
        f"ignore the email."
    )
    html = _wrap(
        "<p style=\"font-size:15px;line-height:1.55;\">Click the button "
        "below to sign in to ArchHub Cloud:</p>"
        f"<p><a href=\"{link}\" style=\"display:inline-block;"
        "background:#d97757;color:#ffffff;text-decoration:none;"
        "padding:12px 22px;border-radius:8px;font-size:15px;"
        "font-weight:500;\">Sign in to ArchHub</a></p>"
        "<p style=\"color:#9b938a;font-size:12px;\">Link expires in 5 "
        "minutes. If you didn't request this, ignore the email.</p>"
    )
    return await _send(to=to, subject=subject, text=text, html=html)


async def send_welcome_email(*, to: str) -> bool:
    """Onboarding first-touch — sent once when a new account is
    created. Roadmap #P2 welcome sequence."""
    subject = "Welcome to ArchHub"
    text = (
        "Welcome to ArchHub.\n\n"
        "ArchHub drives your AEC stack — Revit, AutoCAD, Rhino, 3ds "
        "Max, Blender, Speckle, Excel, Outlook — from one chat.\n\n"
        "Getting started:\n"
        "  1. Open ArchHub on your desktop.\n"
        "  2. Wire a host node into an AI conversation and ask it "
        "about your model.\n"
        "  3. Save what works as a Skill — reusable and shareable.\n\n"
        "Browse the in-app Marketplace for ready-made Skills, or build "
        "your own custom nodes with AI.\n\n"
        "Questions? Reply to this email.\n\n"
        "— The ArchHub team"
    )
    html = _wrap(
        "<p style=\"font-size:17px;font-weight:600;margin:0 0 4px;\">"
        "Welcome to ArchHub.</p>"
        "<p style=\"font-size:15px;line-height:1.55;color:#5e5750;\">"
        "ArchHub drives your AEC stack — Revit, AutoCAD, Rhino, "
        "3ds Max, Blender, Speckle, Excel, Outlook — from one "
        "chat.</p>"
        "<p style=\"font-size:14px;font-weight:600;margin:20px 0 6px;\">"
        "Getting started</p>"
        "<ol style=\"font-size:14px;line-height:1.7;color:#5e5750;"
        "padding-left:20px;margin:0;\">"
        "<li>Open ArchHub on your desktop.</li>"
        "<li>Wire a host node into an AI conversation and ask it about "
        "your model.</li>"
        "<li>Save what works as a Skill — reusable and shareable."
        "</li></ol>"
        "<p style=\"font-size:14px;line-height:1.55;color:#5e5750;"
        "margin-top:18px;\">Browse the in-app Marketplace for "
        "ready-made Skills, or build your own custom nodes with AI.</p>"
        "<p style=\"font-size:13px;color:#9b938a;\">Questions? Just "
        "reply to this email.</p>"
    )
    return await _send(to=to, subject=subject, text=text, html=html)
