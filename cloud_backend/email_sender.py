"""Thin wrapper around Resend for transactional email.

Falls back to stdout-logging when RESEND_API_KEY is unset (local dev
+ smoke tests). Production deploys MUST set the key; otherwise the
"check your inbox" magic-link UX fails silently.
"""
from __future__ import annotations

import httpx

import config


RESEND_URL = "https://api.resend.com/emails"


async def send_magic_link(*, to: str, link: str) -> bool:
    """Send the sign-in link. Returns True on accepted (HTTP 200/202)."""
    subject = "Your ArchHub sign-in link"
    text = (
        f"Click this link to sign in to ArchHub Cloud:\n\n"
        f"{link}\n\n"
        f"Link expires in 5 minutes. If you didn't request this, "
        f"ignore the email."
    )
    html = (
        f"<p>Click the link below to sign in to ArchHub Cloud:</p>"
        f"<p><a href='{link}'>{link}</a></p>"
        f"<p style='color:#888;font-size:12px;'>Link expires in 5 "
        f"minutes. If you didn't request this, ignore the email.</p>"
    )

    if not config.RESEND_API_KEY:
        # Dev mode: log instead of sending.
        print(f"[email] would send to {to}: {subject}\n  link={link}",
              flush=True)
        return True

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
